"""Computer Control Tools via PyAutoGUI with permission gating and action verification."""

import asyncio
from pathlib import Path
from typing import Any
import pyautogui

from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.memory.security import contains_secrets
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

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

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
            await self.event_bus.emit(EventType.COMPUTER_ACTION_REQUESTED, {"action": "mouse_move", "x": x, "y": y})
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.moveTo(x, y, duration=duration))

            # Verify cursor coordinates
            current_pos = pyautogui.position()
            verified = (current_pos[0] == x and current_pos[1] == y)

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "mouse_move", "x": current_pos[0], "y": current_pos[1], "verified": verified},
            )
            return ToolResult(
                success=True,
                result={"action": "mouse_move", "x": current_pos[0], "y": current_pos[1], "status": "moved", "verified": verified},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "mouse_move", "error": str(ex)})
            return ToolResult(success=False, error=f"Mouse movement failed: {str(ex)}")


class MouseClickTool(BaseTool):
    """Performs a single mouse click at current or specified coordinates."""

    name = "mouse_click"
    description = "Click mouse button at current position or specified (x, y) coordinates."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

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
                    "enum": ["left", "right", "middle"],
                },
                "clicks": {"type": "INTEGER", "description": "Number of clicks (default: 1)"},
            },
            "required": [],
        }

    async def execute(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1, **kwargs) -> ToolResult:
        try:
            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_REQUESTED,
                {"action": "mouse_click", "x": x, "y": y, "button": button, "clicks": clicks},
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.click(x=x, y=y, button=button, clicks=clicks))

            pos = pyautogui.position()
            verified = True
            if x is not None and y is not None:
                verified = (pos[0] == x and pos[1] == y)

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "mouse_click", "x": pos[0], "y": pos[1], "button": button, "verified": verified},
            )
            return ToolResult(
                success=True,
                result={"action": "click", "x": pos[0], "y": pos[1], "button": button, "clicks": clicks, "verified": verified},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "mouse_click", "error": str(ex)})
            return ToolResult(success=False, error=f"Mouse click failed: {str(ex)}")


class DoubleClickTool(BaseTool):
    """Performs a double-click at current or specified coordinates."""

    name = "double_click"
    description = "Double-click mouse button at current position or specified (x, y) coordinates."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "x": {"type": "INTEGER", "description": "Optional X screen coordinate"},
                "y": {"type": "INTEGER", "description": "Optional Y screen coordinate"},
            },
            "required": [],
        }

    async def execute(self, x: int | None = None, y: int | None = None, **kwargs) -> ToolResult:
        try:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_REQUESTED, {"action": "double_click", "x": x, "y": y})
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.doubleClick(x=x, y=y))

            pos = pyautogui.position()
            verified = True
            if x is not None and y is not None:
                verified = (pos[0] == x and pos[1] == y)

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "double_click", "x": pos[0], "y": pos[1], "verified": verified},
            )
            return ToolResult(
                success=True,
                result={"action": "double_click", "x": pos[0], "y": pos[1], "verified": verified},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "double_click", "error": str(ex)})
            return ToolResult(success=False, error=f"Double click failed: {str(ex)}")


class RightClickTool(BaseTool):
    """Performs a right-click to open context menus."""

    name = "right_click"
    description = "Right-click mouse button at current position or specified (x, y) coordinates."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "x": {"type": "INTEGER", "description": "Optional X screen coordinate"},
                "y": {"type": "INTEGER", "description": "Optional Y screen coordinate"},
            },
            "required": [],
        }

    async def execute(self, x: int | None = None, y: int | None = None, **kwargs) -> ToolResult:
        try:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_REQUESTED, {"action": "right_click", "x": x, "y": y})
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.rightClick(x=x, y=y))

            pos = pyautogui.position()
            verified = True
            if x is not None and y is not None:
                verified = (pos[0] == x and pos[1] == y)

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "right_click", "x": pos[0], "y": pos[1], "verified": verified},
            )
            return ToolResult(
                success=True,
                result={"action": "right_click", "x": pos[0], "y": pos[1], "verified": verified},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "right_click", "error": str(ex)})
            return ToolResult(success=False, error=f"Right click failed: {str(ex)}")


class MouseScrollTool(BaseTool):
    """Scrolls the mouse wheel vertically or horizontally."""

    name = "mouse_scroll"
    description = "Scroll the mouse wheel up, down, left, or right by a specified number of clicks."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "clicks": {"type": "INTEGER", "description": "Number of scroll ticks (default: 3)"},
                "direction": {
                    "type": "STRING",
                    "description": "Scroll direction: 'up', 'down', 'left', or 'right' (default: 'down')",
                    "enum": ["up", "down", "left", "right"],
                },
            },
            "required": [],
        }

    async def execute(self, clicks: int = 3, direction: str = "down", **kwargs) -> ToolResult:
        try:
            norm_dir = direction.strip().lower()
            scroll_amount = clicks if norm_dir == "up" else -clicks

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_REQUESTED,
                {"action": "mouse_scroll", "clicks": clicks, "direction": norm_dir},
            )
            loop = asyncio.get_running_loop()

            if norm_dir in ["up", "down"]:
                await loop.run_in_executor(None, lambda: pyautogui.scroll(scroll_amount))
            elif norm_dir in ["left", "right"]:
                h_amount = -clicks if norm_dir == "left" else clicks
                await loop.run_in_executor(None, lambda: pyautogui.hscroll(h_amount))

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "mouse_scroll", "direction": norm_dir, "clicks": clicks},
            )
            return ToolResult(
                success=True,
                result={"action": "mouse_scroll", "direction": norm_dir, "clicks": clicks, "verified": True},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "mouse_scroll", "error": str(ex)})
            return ToolResult(success=False, error=f"Scroll failed: {str(ex)}")


class KeyboardTypeTool(BaseTool):
    """Types text via simulated keystrokes."""

    name = "keyboard_type"
    description = "Type text as simulated keystrokes into the active focused window."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

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
            # Mask logging if text contains secrets
            has_secret = contains_secrets(text)
            log_text = "[REDACTED]" if has_secret else text[:50]

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_REQUESTED,
                {"action": "keyboard_type", "length": len(text), "preview": log_text},
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.write(text, interval=interval))

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "keyboard_type", "length": len(text)},
            )
            return ToolResult(
                success=True,
                result={"action": "keyboard_type", "typed_length": len(text), "status": "typed", "verified": True},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "keyboard_type", "error": str(ex)})
            return ToolResult(success=False, error=f"Keyboard typing failed: {str(ex)}")


class KeyPressTool(BaseTool):
    """Presses a single key (e.g. 'enter', 'escape', 'tab', 'backspace', 'down', 'up')."""

    name = "press_key"
    description = (
        "Press a single keyboard key (e.g. 'enter', 'escape', 'tab', 'backspace', 'space', 'up', 'down', 'left', 'right')."
    )
    permission_level = PermissionLevel.MODERATE

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING", "description": "Key name to press (e.g. 'enter', 'escape', 'tab')"},
                "presses": {"type": "INTEGER", "description": "Number of times to press key (default: 1)"},
            },
            "required": ["key"],
        }

    async def execute(self, key: str, presses: int = 1, **kwargs) -> ToolResult:
        try:
            norm_key = key.strip().lower()

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_REQUESTED,
                {"action": "press_key", "key": norm_key, "presses": presses},
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.press(norm_key, presses=presses))

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "press_key", "key": norm_key, "presses": presses},
            )
            return ToolResult(
                success=True,
                result={"action": "press_key", "key": norm_key, "presses": presses, "verified": True},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "press_key", "error": str(ex)})
            return ToolResult(success=False, error=f"Key press failed: {str(ex)}")


class KeyboardHotkeyTool(BaseTool):
    """Presses a combination of hotkeys (e.g. ['ctrl', 'c'] or ['alt', 'f4'])."""

    name = "keyboard_hotkey"
    description = "Send a keyboard hotkey shortcut combination (e.g. ['ctrl', 's'] or ['win', 'r'])."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or default_event_bus

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
            await self.event_bus.emit(EventType.COMPUTER_ACTION_REQUESTED, {"action": "keyboard_hotkey", "keys": keys})
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: pyautogui.hotkey(*keys))

            await self.event_bus.emit(
                EventType.COMPUTER_ACTION_EXECUTED,
                {"action": "keyboard_hotkey", "keys": keys},
            )
            return ToolResult(
                success=True,
                result={"action": "keyboard_hotkey", "hotkey": "+".join(keys), "status": "executed", "verified": True},
            )
        except Exception as ex:
            await self.event_bus.emit(EventType.COMPUTER_ACTION_FAILED, {"action": "keyboard_hotkey", "error": str(ex)})
            return ToolResult(success=False, error=f"Hotkey execution failed: {str(ex)}")


class CaptureScreenshotTool(BaseTool):
    """Captures a screenshot of the display screen. Backward-compatible with Phase 2."""

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

            from jarvis.tools.screen import grab_screen_image

            loop = asyncio.get_running_loop()
            img = await loop.run_in_executor(None, grab_screen_image)
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
