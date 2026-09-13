"""Computer Control Tools via PyAutoGUI with permission gating."""

import asyncio
import base64
import io
from pathlib import Path
from typing import Any
import pyautogui
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger

# PyAutoGUI fail-safe: moving cursor to screen corner stops runaway operations
pyautogui.FAILSAFE = True


class MouseMoveTool(BaseTool):
    """Moves the mouse cursor to target screen coordinates."""

    name = "mouse_move"
    description = "Move the mouse cursor to absolute screen coordinates (x, y)."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "x": {"type": "INTEGER", "description": "Target X screen coordinate"},
                "y": {"type": "INTEGER", "description": "Target Y screen coordinate"},
                "duration": {"type": "NUMBER", "description": "Movement duration in seconds (default: 0.2)"},
            },
            "required": ["x", "y"],
        }

    async def execute(self, x: int, y: int, duration: float = 0.2, **kwargs) -> ToolResult:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.moveTo(x, y, duration=duration))
            return ToolResult(success=True, result={"x": x, "y": y, "status": "moved"})
        except Exception as ex:
            return ToolResult(success=False, error=f"Mouse movement failed: {str(ex)}")


class MouseClickTool(BaseTool):
    """Performs a mouse click at the current or specified coordinates."""

    name = "mouse_click"
    description = "Click mouse button at current position or specified (x, y) coordinates."
    permission_level = PermissionLevel.MODERATE

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "x": {"type": "INTEGER", "description": "Optional X screen coordinate"},
                "y": {"type": "INTEGER", "description": "Optional Y screen coordinate"},
                "button": {
                    "type": "STRING",
                    "description": "Mouse button: 'left', 'right', or 'middle' (default: 'left')",
                },
                "clicks": {"type": "INTEGER", "description": "Number of clicks (default: 1)"},
            },
            "required": [],
        }

    async def execute(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1, **kwargs) -> ToolResult:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.click(x=x, y=y, button=button, clicks=clicks))
            pos = pyautogui.position()
            return ToolResult(success=True, result={"x": pos[0], "y": pos[1], "button": button, "clicks": clicks})
        except Exception as ex:
            return ToolResult(success=False, error=f"Mouse click failed: {str(ex)}")


class KeyboardTypeTool(BaseTool):
    """Types a string of text via simulated keystrokes."""

    name = "keyboard_type"
    description = "Type text as simulated keystrokes into the active focused window."
    permission_level = PermissionLevel.MODERATE

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "Text string to type"},
                "interval": {"type": "NUMBER", "description": "Interval between keystrokes in seconds (default: 0.02)"},
            },
            "required": ["text"],
        }

    async def execute(self, text: str, interval: float = 0.02, **kwargs) -> ToolResult:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.write(text, interval=interval))
            return ToolResult(success=True, result={"typed_length": len(text), "status": "typed"})
        except Exception as ex:
            return ToolResult(success=False, error=f"Keyboard typing failed: {str(ex)}")


class KeyboardHotkeyTool(BaseTool):
    """Presses a combination of hotkeys (e.g. ['ctrl', 'c'] or ['alt', 'f4'])."""

    name = "keyboard_hotkey"
    description = "Send a keyboard hotkey shortcut combination (e.g. ['ctrl', 's'] or ['win', 'r'])."
    permission_level = PermissionLevel.MODERATE

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "keys": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "List of key names to press in sequence (e.g. ['ctrl', 'c'])",
                }
            },
            "required": ["keys"],
        }

    async def execute(self, keys: list[str], **kwargs) -> ToolResult:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.hotkey(*keys))
            return ToolResult(success=True, result={"hotkey": "+".join(keys), "status": "executed"})
        except Exception as ex:
            return ToolResult(success=False, error=f"Hotkey execution failed: {str(ex)}")


class CaptureScreenshotTool(BaseTool):
    """Captures a screenshot of the display screen and optionally saves it."""

    name = "capture_screenshot"
    description = "Capture a screenshot of the current screen. Returns image metadata and file path."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "save_path": {
                    "type": "STRING",
                    "description": "Optional file path to save screenshot (default: 'logs/screenshot.png')",
                }
            },
            "required": [],
        }

    async def execute(self, save_path: str = "logs/screenshot.png", **kwargs) -> ToolResult:
        try:
            out_file = Path(save_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)

            loop = asyncio.get_running_loop()
            img = await loop.run_in_executor(None, lambda: pyautogui.screenshot())
            await loop.run_in_executor(None, lambda: img.save(out_file))

            return ToolResult(
                success=True,
                result={
                    "path": str(out_file),
                    "width": img.width,
                    "height": img.height,
                    "status": "captured",
                },
            )
        except Exception as ex:
            return ToolResult(success=False, error=f"Screenshot capture failed: {str(ex)}")
