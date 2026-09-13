"""Standardized tool system for JARVIS."""

from jarvis.tools.base import BaseTool, ToolResult
from jarvis.tools.registry import ToolRegistry, default_tool_registry
from jarvis.tools.filesystem import (
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
    ModifyFileTool,
    DeleteFileTool,
    SearchFilesTool,
)
from jarvis.tools.terminal import TerminalExecuteTool
from jarvis.tools.applications import (
    LaunchApplicationTool,
    ListRunningApplicationsTool,
    FocusApplicationTool,
    CloseApplicationTool,
)
from jarvis.tools.computer import (
    MouseMoveTool,
    MouseClickTool,
    KeyboardTypeTool,
    KeyboardHotkeyTool,
    CaptureScreenshotTool,
)
from jarvis.tools.browser import (
    OpenBrowserTool,
    ReadWebpageTool,
    BrowserActionTool,
)
from jarvis.tools.web_research import (
    WebSearchTool,
    FetchWebContentTool,
)


def register_default_tools(registry: ToolRegistry) -> None:
    """Register the complete built-in tool suite into the provided registry."""
    # Filesystem tools
    registry.register(ListDirTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ModifyFileTool())
    registry.register(DeleteFileTool())
    registry.register(SearchFilesTool())

    # Terminal tool
    registry.register(TerminalExecuteTool())

    # Application management
    registry.register(LaunchApplicationTool())
    registry.register(ListRunningApplicationsTool())
    registry.register(FocusApplicationTool())
    registry.register(CloseApplicationTool())

    # Computer control
    registry.register(MouseMoveTool())
    registry.register(MouseClickTool())
    registry.register(KeyboardTypeTool())
    registry.register(KeyboardHotkeyTool())
    registry.register(CaptureScreenshotTool())

    # Browser & Web Research
    registry.register(OpenBrowserTool())
    registry.register(ReadWebpageTool())
    registry.register(BrowserActionTool())
    registry.register(WebSearchTool())
    registry.register(FetchWebContentTool())


# Automatically register default tools into default_tool_registry
register_default_tools(default_tool_registry)

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "default_tool_registry",
    "register_default_tools",
    "ListDirTool",
    "ReadFileTool",
    "WriteFileTool",
    "ModifyFileTool",
    "DeleteFileTool",
    "SearchFilesTool",
    "TerminalExecuteTool",
    "LaunchApplicationTool",
    "ListRunningApplicationsTool",
    "FocusApplicationTool",
    "CloseApplicationTool",
    "MouseMoveTool",
    "MouseClickTool",
    "KeyboardTypeTool",
    "KeyboardHotkeyTool",
    "CaptureScreenshotTool",
    "OpenBrowserTool",
    "ReadWebpageTool",
    "BrowserActionTool",
    "WebSearchTool",
    "FetchWebContentTool",
]
