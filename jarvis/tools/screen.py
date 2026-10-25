"""Screen Perception & Context Awareness tools for JARVIS (Phase 7).

Provides on-demand, privacy-preserving screen capture, active window/application
context inspection, and visual error/scene analysis via Gemini Vision.
"""

import asyncio
import base64
import io
from pathlib import Path
from typing import Any
import psutil
import pyautogui

from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


def grab_screen_image():
    """Captures the current screen as a PIL Image.

    Attempts pyautogui.screenshot() first. If it fails (e.g. PIL ImageGrab
    OSError: screen grab failed on Windows), uses Windows GDI BitBlt via ctypes.
    """
    try:
        return pyautogui.screenshot()
    except Exception:
        import sys
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            from PIL import Image

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
            gdi32.SelectObject(hdc_mem, hbm)
            gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, 0x00CC0020)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            buf = ctypes.create_string_buffer(width * height * 4)
            gdi32.GetDIBits(hdc_mem, hbm, 0, height, buf, ctypes.byref(bmi), 0)
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)
            return Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1).convert("RGB")
        raise


class CaptureScreenTool(BaseTool):
    """Captures the current display screen into memory without persistent storage by default.

    Privacy Guarantees:
    - Never runs background capture loops.
    - Operates only when explicitly requested.
    - Encodes to memory as JPEG; writes to disk only if save_path is provided.
    """

    name = "capture_screen"
    description = (
        "Capture the current display screen into memory for inspection or vision analysis. "
        "Does not save to disk unless an explicit save_path is specified."
    )
    permission_level = PermissionLevel.LOW_RISK

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "save_path": {
                    "type": "STRING",
                    "description": "Optional file path to persist screenshot (default: None, memory only)",
                }
            },
            "required": [],
        }

    async def execute(self, save_path: str | None = None, **kwargs) -> ToolResult:
        try:
            await self.event_bus.emit(EventType.SCREEN_CAPTURE_STARTED, {"save_path": save_path})

            loop = asyncio.get_running_loop()
            img = await loop.run_in_executor(None, grab_screen_image)

            # Convert to JPEG in memory
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            jpeg_bytes = buffer.getvalue()
            b64_str = base64.b64encode(jpeg_bytes).decode("ascii")

            saved_path = None
            if save_path:
                out_path = Path(save_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                await loop.run_in_executor(None, lambda: img.save(out_path))
                saved_path = str(out_path)

            await self.event_bus.emit(
                EventType.SCREEN_CAPTURE_FINISHED,
                {"width": img.width, "height": img.height, "saved": saved_path is not None},
            )

            return ToolResult(
                success=True,
                result={
                    "status": "captured",
                    "width": img.width,
                    "height": img.height,
                    "format": "jpeg",
                    "size_bytes": len(jpeg_bytes),
                    "image_base64": b64_str,
                    "saved_to_disk": saved_path is not None,
                    "path": saved_path,
                },
            )

        except Exception as ex:
            logger.error("Screen capture failed: %s", ex)
            return ToolResult(success=False, error=f"Screen capture failed: {str(ex)}")


class GetActiveWindowTool(BaseTool):
    """Inspects the currently active foreground desktop window."""

    name = "get_active_window"
    description = (
        "Inspect the current foreground window title, process name, PID, and position."
    )
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
            import pygetwindow as gw

            win = gw.getActiveWindow()
            if not win or not win.title:
                return ToolResult(
                    success=True,
                    result={
                        "has_active_window": False,
                        "title": None,
                        "note": "No active foreground window detected (desktop or background focused).",
                    },
                )

            # Resolve process name & PID if possible
            pid = None
            process_name = None
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = getattr(win, "_hWnd", None)
                if hwnd:
                    lpdw_process_id = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_process_id))
                    pid = int(lpdw_process_id.value)
                    if pid:
                        p = psutil.Process(pid)
                        process_name = p.name()
            except Exception:
                pass

            return ToolResult(
                success=True,
                result={
                    "has_active_window": True,
                    "title": win.title,
                    "process_name": process_name or "unknown",
                    "pid": pid,
                    "geometry": {
                        "left": getattr(win, "left", None),
                        "top": getattr(win, "top", None),
                        "width": getattr(win, "width", None),
                        "height": getattr(win, "height", None),
                    },
                    "is_minimized": getattr(win, "isMinimized", False),
                    "is_maximized": getattr(win, "isMaximized", False),
                },
            )

        except Exception as ex:
            logger.error("Get active window failed: %s", ex)
            return ToolResult(success=False, error=f"Failed to inspect active window: {str(ex)}")


class GetActiveApplicationTool(BaseTool):
    """Identifies the active application and enriches it with project memory context."""

    name = "get_active_application"
    description = (
        "Identify the currently active application and working project context "
        "(e.g., answering 'What application is open?' or 'What am I working on?')."
    )
    permission_level = PermissionLevel.LOW_RISK

    def __init__(self, memory_manager: Any = None) -> None:
        self.memory_manager = memory_manager

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            window_tool = GetActiveWindowTool()
            win_res = await window_tool.execute()

            if not win_res.success or not win_res.result or not win_res.result.get("has_active_window"):
                return ToolResult(
                    success=True,
                    result={
                        "application": "Desktop / None",
                        "window_title": None,
                        "project_context": self._get_project_context(),
                        "summary": "You are currently on the Desktop with no active window in foreground.",
                    },
                )

            data = win_res.result
            raw_title = data.get("title", "")
            proc_name = data.get("process_name", "")

            # Identify human-friendly application name
            app_name = self._resolve_app_name(raw_title, proc_name)
            project_info = self._get_project_context()

            summary = f"Your active application is {app_name} (Window: '{raw_title}')."
            if project_info and project_info.get("project_name") != "Unknown":
                summary += f" Project context: {project_info.get('project_name')} (branch: {project_info.get('current_branch')})."

            return ToolResult(
                success=True,
                result={
                    "application": app_name,
                    "window_title": raw_title,
                    "process_name": proc_name,
                    "pid": data.get("pid"),
                    "project_context": project_info,
                    "summary": summary,
                },
            )

        except Exception as ex:
            logger.error("Get active application failed: %s", ex)
            return ToolResult(success=False, error=f"Failed to identify active application: {str(ex)}")

    def _resolve_app_name(self, title: str, proc_name: str) -> str:
        title_lower = title.lower()
        proc_lower = proc_name.lower()

        if "visual studio code" in title_lower or "code.exe" in proc_lower:
            return "Visual Studio Code"
        elif "chrome" in title_lower or "chrome.exe" in proc_lower:
            return "Google Chrome"
        elif "edge" in title_lower or "msedge.exe" in proc_lower:
            return "Microsoft Edge"
        elif "notepad" in title_lower or "notepad.exe" in proc_lower:
            return "Notepad"
        elif "calculator" in title_lower or "calculatorapp" in proc_lower:
            return "Calculator"
        elif "camera" in title_lower or "windowscamera" in proc_lower:
            return "Windows Camera"
        elif "terminal" in title_lower or "cmd.exe" in proc_lower or "powershell" in proc_lower or "wt.exe" in proc_lower:
            return "Terminal"
        else:
            return proc_name.replace(".exe", "").capitalize() if proc_name else title

    def _get_project_context(self) -> dict[str, Any] | None:
        if self.memory_manager and hasattr(self.memory_manager, "project"):
            proj = self.memory_manager.project
            if hasattr(proj, "get_project_state"):
                state = proj.get_project_state()
                return {
                    "project_name": state.project_name,
                    "workspace_root": state.workspace_root,
                    "current_branch": state.current_branch,
                    "active_phase": state.active_phase,
                }
        return None


class AnalyzeScreenTool(BaseTool):
    """Captures the current screen and asks Gemini Vision to analyze it."""

    name = "analyze_screen"
    description = (
        "Look at what is on the screen and analyze it (e.g., answering 'What do you see on my screen?', "
        "'What is on my screen?', 'Look at my screen and explain this error')."
    )
    permission_level = PermissionLevel.MODERATE

    def __init__(self, ai_provider: Any = None, event_bus: EventBus | None = None) -> None:
        self.ai_provider = ai_provider
        self.event_bus = event_bus or default_event_bus

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "prompt": {
                    "type": "STRING",
                    "description": "Specific question or instruction for analyzing the screen (default: describe screen content and open apps)",
                }
            },
            "required": [],
        }

    async def execute(
        self,
        prompt: str = "Describe what is on my screen in detail, including open applications, errors, and key content.",
        **kwargs,
    ) -> ToolResult:
        try:
            # 1. Capture screen in-memory
            capture_tool = CaptureScreenTool(event_bus=self.event_bus)
            cap_res = await capture_tool.execute()
            if not cap_res.success or not cap_res.result:
                return ToolResult(success=False, error=f"Screen capture failed: {cap_res.error}")

            raw_b64 = cap_res.result.get("image_base64", "")
            jpeg_bytes = base64.b64decode(raw_b64)

            # 2. Get active window context for grounding
            win_tool = GetActiveWindowTool()
            win_res = await win_tool.execute()
            active_title = win_res.result.get("title") if win_res.success and win_res.result else "Unknown"

            # 3. Vision Analysis
            await self.event_bus.emit(EventType.VISION_ANALYSIS_STARTED, {"prompt": prompt})

            if self.ai_provider and hasattr(self.ai_provider, "analyze_image"):
                system_instruction = (
                    "You are JARVIS inspecting the user's computer screen. "
                    "Analyze the visual content with technical accuracy, clarity, and conciseness. "
                    "Focus specifically on open applications, visible errors, code snippets, or UI controls."
                )
                response = await self.ai_provider.analyze_image(
                    prompt=f"{prompt}\n[Active Window Context: {active_title}]",
                    image_bytes=jpeg_bytes,
                    system_instruction=system_instruction,
                )
                analysis_text = response.text if hasattr(response, "text") else str(response)

                await self.event_bus.emit(EventType.VISION_ANALYSIS_FINISHED, {"success": True})

                return ToolResult(
                    success=True,
                    result={
                        "status": "analyzed",
                        "prompt": prompt,
                        "analysis": analysis_text,
                        "active_window": active_title,
                        "resolution": f"{cap_res.result.get('width')}x{cap_res.result.get('height')}",
                    },
                )

            await self.event_bus.emit(EventType.VISION_ANALYSIS_FINISHED, {"success": False, "reason": "no_ai_provider"})
            return ToolResult(
                success=True,
                result={
                    "status": "captured_without_ai_provider",
                    "prompt": prompt,
                    "active_window": active_title,
                    "resolution": f"{cap_res.result.get('width')}x{cap_res.result.get('height')}",
                    "note": "Screenshot captured successfully in memory, but AI vision provider is not bound to tool instance.",
                },
            )

        except Exception as ex:
            await self.event_bus.emit(EventType.VISION_ANALYSIS_FINISHED, {"success": False, "error": str(ex)})
            logger.error("Analyze screen failed: %s", ex)
            return ToolResult(success=False, error=f"Screen analysis failed: {str(ex)}")
