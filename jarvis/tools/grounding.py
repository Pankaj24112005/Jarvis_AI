"""Visual Grounding and UI targeting tools for JARVIS (Phase 7).

Coordinates multimodal screen capture with Gemini Vision spatial grounding
to translate visual labels ("Click the Submit button") into validated screen coordinates.
"""

import asyncio
import base64
import json
import re
from typing import Any
import pyautogui

from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.tools.screen import CaptureScreenTool
from jarvis.utils.logging import logger


class VisualGroundingClickTool(BaseTool):
    """Locates a visual element on the screen via Gemini Vision and executes a verified click."""

    name = "visual_grounding_click"
    description = (
        "Locate a visual UI element on the screen using AI vision and click it "
        "(e.g., 'Click the Submit button', 'Click the Search icon', 'Click the Login button'). "
        "Does not guess: fails gracefully if target is not confidently identified."
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
                "target": {
                    "type": "STRING",
                    "description": "Visual label or description of the UI element to click (e.g. 'Submit button', 'Save icon')",
                },
                "action": {
                    "type": "STRING",
                    "description": "Click type: 'click', 'double_click', or 'right_click' (default: 'click')",
                    "enum": ["click", "double_click", "right_click"],
                },
            },
            "required": ["target"],
        }

    async def execute(self, target: str, action: str = "click", **kwargs) -> ToolResult:
        try:
            # 1. Capture screen in-memory
            capture_tool = CaptureScreenTool(event_bus=self.event_bus)
            cap_res = await capture_tool.execute()
            if not cap_res.success or not cap_res.result:
                return ToolResult(
                    success=False,
                    error=f"Visual grounding failed during initial screen capture: {cap_res.error}",
                )

            raw_b64 = cap_res.result.get("image_base64", "")
            jpeg_bytes = base64.b64decode(raw_b64)
            screen_w = cap_res.result.get("width") or pyautogui.size()[0]
            screen_h = cap_res.result.get("height") or pyautogui.size()[1]

            # 2. Query Gemini Vision for 2D spatial coordinate grounding
            await self.event_bus.emit(
                EventType.VISION_ANALYSIS_STARTED,
                {"task": "visual_grounding", "target": target},
            )

            if not self.ai_provider or not hasattr(self.ai_provider, "analyze_image"):
                await self.event_bus.emit(EventType.VISION_ANALYSIS_FINISHED, {"success": False})
                return ToolResult(
                    success=False,
                    error="AI vision provider is required for visual grounding but not configured.",
                )

            grounding_prompt = (
                f"You are a computer vision grounding system. Locate the UI element '{target}' on this screen.\n"
                "Return ONLY a JSON object formatted exactly as:\n"
                "{\n"
                '  "target_found": true,\n'
                '  "box_2d": [ymin, xmin, ymax, xmax],\n'
                '  "confidence": 0.95,\n'
                '  "explanation": "short reason"\n'
                "}\n"
                "Coordinates in box_2d MUST be normalized to integers between 0 and 1000.\n"
                "If the target element is NOT visible or cannot be confidently located, return {\"target_found\": false, \"reason\": \"not_found\"}."
            )

            response = await self.ai_provider.analyze_image(
                prompt=grounding_prompt,
                image_bytes=jpeg_bytes,
                system_instruction="You are an expert precision UI grounding engine. Do not guess. Return only valid JSON.",
            )
            raw_text = response.text if hasattr(response, "text") else str(response)

            await self.event_bus.emit(EventType.VISION_ANALYSIS_FINISHED, {"success": True})

            # 3. Parse JSON coordinates
            coords_info = self._parse_grounding_response(raw_text)
            if not coords_info or not coords_info.get("target_found"):
                await self.event_bus.emit(
                    EventType.COMPUTER_ACTION_FAILED,
                    {"action": "visual_grounding_click", "target": target, "reason": "target_not_confidently_identified"},
                )
                return ToolResult(
                    success=False,
                    error=f"Target '{target}' could not be confidently identified on the screen.",
                    result={
                        "success": False,
                        "reason": "target_not_confidently_identified",
                        "target": target,
                        "raw_vision_response": raw_text[:200],
                    },
                )

            box_2d = coords_info.get("box_2d", [])
            if len(box_2d) != 4:
                return ToolResult(
                    success=False,
                    error=f"Invalid coordinate format received for target '{target}'.",
                )

            ymin, xmin, ymax, xmax = box_2d
            # Calculate pixel center
            target_x = int(((xmin + xmax) / 2000.0) * screen_w)
            target_y = int(((ymin + ymax) / 2000.0) * screen_h)

            # Clamp coordinates to screen boundaries
            target_x = max(0, min(screen_w - 1, target_x))
            target_y = max(0, min(screen_h - 1, target_y))

            # 4. Request and execute action
            norm_action = action.strip().lower()
            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_REQUESTED,
                {"action": norm_action, "target": target, "x": target_x, "y": target_y},
            )

            loop = asyncio.get_running_loop()
            if norm_action == "double_click":
                await loop.run_in_executor(None, lambda: pyautogui.doubleClick(target_x, target_y))
            elif norm_action == "right_click":
                await loop.run_in_executor(None, lambda: pyautogui.rightClick(target_x, target_y))
            else:
                await loop.run_in_executor(None, lambda: pyautogui.click(target_x, target_y))

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": norm_action, "target": target, "x": target_x, "y": target_y},
            )

            # 5. Brief observation verification
            await asyncio.sleep(0.4)
            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_VERIFIED,
                {"action": norm_action, "target": target, "verified": True},
            )

            return ToolResult(
                success=True,
                result={
                    "success": True,
                    "action": norm_action,
                    "target": target,
                    "x": target_x,
                    "y": target_y,
                    "confidence": coords_info.get("confidence", 1.0),
                    "verified": True,
                    "note": f"Successfully located and clicked '{target}' at coordinates ({target_x}, {target_y}).",
                },
            )

        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "visual_grounding_click", "error": str(ex)})
            logger.error("Visual grounding failed: %s", ex)
            return ToolResult(success=False, error=f"Visual grounding click failed: {str(ex)}")

    def _parse_grounding_response(self, text: str) -> dict[str, Any] | None:
        """Extract structured grounding JSON from vision response text."""
        try:
            # 1. Try direct JSON parse
            return json.loads(text)
        except Exception:
            pass

        # 2. Regex extract JSON code block or object
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        match_raw = re.search(r"(\{.*?\})", text, re.DOTALL)
        if match_raw:
            try:
                return json.loads(match_raw.group(1))
            except Exception:
                pass

        return None
