"""Camera tools for launching the Windows Camera app and capturing/analyzing frames safely."""

import asyncio
import base64
import os
import sys
from typing import Any
import psutil

from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


class OpenCameraTool(BaseTool):
    """Launches the native Windows Camera application for live user viewing."""

    name = "open_camera"
    description = "Launch the native Windows Camera application for live viewing."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            target_uri = "microsoft.windows.camera:"
            if sys.platform == "win32":
                os.startfile(target_uri)
            else:
                import webbrowser
                webbrowser.open(target_uri)

            # Brief verification of process/app launch
            verified = False
            for _ in range(5):
                await asyncio.sleep(0.3)
                for proc in psutil.process_iter(["name"]):
                    try:
                        pname = (proc.info.get("name") or "").lower()
                        if pname in ["windowscamera.exe", "camera.exe"]:
                            verified = True
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if verified:
                    break

            return ToolResult(
                success=True,
                result={
                    "app": "Windows Camera",
                    "status": "launched",
                    "uri": target_uri,
                    "verified": verified,
                    "note": "Camera application opened for display.",
                },
            )
        except Exception as ex:
            logger.error("Failed to open camera application: %s", ex)
            return ToolResult(success=False, error=f"Failed to open camera application: {str(ex)}")


class CaptureCameraFrameTool(BaseTool):
    """Captures a single frame from the camera device.

    Privacy Invariant:
    - Never continuously streams in the background.
    - Captures exactly one frame and immediately releases hardware handle.
    - Keeps data in-memory (no disk persistence) unless explicitly commanded.
    """

    name = "capture_camera_frame"
    description = (
        "Capture a single image frame from the system camera for vision analysis. "
        "Does not record video or save to disk."
    )
    permission_level = PermissionLevel.MODERATE

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "device_index": {
                    "type": "INTEGER",
                    "description": "Camera device index (default: 0)",
                }
            },
            "required": [],
        }

    async def execute(self, device_index: int = 0, **kwargs) -> ToolResult:
        try:
            frame_data = await asyncio.to_thread(self._capture_frame_sync, device_index)
            if frame_data is None:
                return ToolResult(
                    success=False,
                    error=(
                        f"Unable to capture frame from camera device {device_index}. "
                        "Device may be disconnected or currently in use by another application."
                    ),
                )

            width, height, jpeg_bytes = frame_data
            b64_str = base64.b64encode(jpeg_bytes).decode("ascii")

            return ToolResult(
                success=True,
                result={
                    "status": "captured",
                    "width": width,
                    "height": height,
                    "format": "jpeg",
                    "size_bytes": len(jpeg_bytes),
                    "image_base64": b64_str,
                },
            )
        except Exception as ex:
            logger.error("Camera frame capture error: %s", ex)
            return ToolResult(success=False, error=f"Camera frame capture failed: {str(ex)}")

    def _capture_frame_sync(self, device_index: int = 0) -> tuple[int, int, bytes] | None:
        try:
            import cv2
        except ImportError:
            raise RuntimeError("OpenCV (cv2) is not installed. Camera capture requires opencv-python.")

        cap = None
        try:
            # On Windows, DirectShow provides lower startup latency
            if sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
                cap = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(device_index)

            if not cap.isOpened():
                return None

            # Allow camera auto-exposure/balance a moment by reading a throwaway frame
            ret, frame = cap.read()
            if not ret or frame is None:
                return None

            h, w = frame.shape[:2]
            success, encoded_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not success:
                return None

            return w, h, encoded_buf.tobytes()

        finally:
            if cap is not None:
                cap.release()


class AnalyzeCameraFrameTool(BaseTool):
    """Captures a single camera frame and queries Gemini Vision to analyze what is seen."""

    name = "analyze_camera_frame"
    description = (
        "Look through the camera and analyze the scene, objects, or documents in front of the camera."
    )
    permission_level = PermissionLevel.MODERATE

    def __init__(self, ai_provider: Any = None) -> None:
        self.ai_provider = ai_provider

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "prompt": {
                    "type": "STRING",
                    "description": "Question or instruction for the vision model (e.g., 'What do you see?', 'Read the text')",
                }
            },
            "required": [],
        }

    async def execute(
        self,
        prompt: str = "Describe what you see in front of the camera in detail.",
        **kwargs,
    ) -> ToolResult:
        try:
            capture_tool = CaptureCameraFrameTool()
            cap_res = await capture_tool.execute()
            if not cap_res.success or not cap_res.result:
                return ToolResult(
                    success=False,
                    error=f"Camera capture failed before vision analysis: {cap_res.error}",
                )

            raw_b64 = cap_res.result.get("image_base64", "")
            jpeg_bytes = base64.b64decode(raw_b64)

            if self.ai_provider and hasattr(self.ai_provider, "analyze_image"):
                response = await self.ai_provider.analyze_image(prompt=prompt, image_bytes=jpeg_bytes)
                description = response.text if hasattr(response, "text") else str(response)
                return ToolResult(
                    success=True,
                    result={
                        "status": "analyzed",
                        "prompt": prompt,
                        "analysis": description,
                        "image_resolution": f"{cap_res.result.get('width')}x{cap_res.result.get('height')}",
                    },
                )

            return ToolResult(
                success=True,
                result={
                    "status": "captured_without_ai_provider",
                    "prompt": prompt,
                    "note": "Camera frame captured successfully. Vision provider not configured for direct tool evaluation.",
                    "size_bytes": len(jpeg_bytes),
                },
            )

        except Exception as ex:
            logger.error("Analyze camera frame failed: %s", ex)
            return ToolResult(success=False, error=f"Analyze camera frame failed: {str(ex)}")
