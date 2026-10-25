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
    TerminateProcessTool,
)
from jarvis.tools.computer import (
    MouseMoveTool,
    MouseClickTool,
    DoubleClickTool,
    RightClickTool,
    MouseScrollTool,
    KeyboardTypeTool,
    KeyPressTool,
    KeyboardHotkeyTool,
    CaptureScreenshotTool,
)
from jarvis.tools.browser import (
    OpenBrowserTool,
    ReadWebpageTool,
    BrowserActionTool,
    BrowserControlTool,
)
from jarvis.tools.web_research import (
    WebSearchTool,
    FetchWebContentTool,
)
from jarvis.tools.camera import (
    OpenCameraTool,
    CaptureCameraFrameTool,
    AnalyzeCameraFrameTool,
)
from jarvis.tools.media import YouTubeControlTool
from jarvis.voice.music import MusicControlTool
from jarvis.tools.screen import (
    CaptureScreenTool,
    GetActiveWindowTool,
    GetActiveApplicationTool,
    AnalyzeScreenTool,
)
from jarvis.tools.grounding import VisualGroundingClickTool


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
    registry.register(TerminateProcessTool())

    # Computer control
    registry.register(MouseMoveTool())
    registry.register(MouseClickTool())
    registry.register(DoubleClickTool())
    registry.register(RightClickTool())
    registry.register(MouseScrollTool())
    registry.register(KeyboardTypeTool())
    registry.register(KeyPressTool())
    registry.register(KeyboardHotkeyTool())
    registry.register(CaptureScreenshotTool())

    # Browser & Web Research
    registry.register(OpenBrowserTool())
    registry.register(ReadWebpageTool())
    registry.register(BrowserActionTool())
    registry.register(BrowserControlTool())
    registry.register(WebSearchTool())
    registry.register(FetchWebContentTool())

    # Media, Camera & Music Tools
    registry.register(YouTubeControlTool())
    registry.register(OpenCameraTool())
    registry.register(CaptureCameraFrameTool())
    registry.register(AnalyzeCameraFrameTool())
    registry.register(MusicControlTool())

    # Phase 7: Screen Perception & Visual Grounding
    registry.register(CaptureScreenTool())
    registry.register(GetActiveWindowTool())
    registry.register(GetActiveApplicationTool())
    registry.register(AnalyzeScreenTool())
    registry.register(VisualGroundingClickTool())


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
    "TerminateProcessTool",
    "MouseMoveTool",
    "MouseClickTool",
    "DoubleClickTool",
    "RightClickTool",
    "MouseScrollTool",
    "KeyboardTypeTool",
    "KeyPressTool",
    "KeyboardHotkeyTool",
    "CaptureScreenshotTool",
    "OpenBrowserTool",
    "ReadWebpageTool",
    "BrowserActionTool",
    "BrowserControlTool",
    "WebSearchTool",
    "FetchWebContentTool",
    "YouTubeControlTool",
    "OpenCameraTool",
    "CaptureCameraFrameTool",
    "AnalyzeCameraFrameTool",
    "MusicControlTool",
    "CaptureScreenTool",
    "GetActiveWindowTool",
    "GetActiveApplicationTool",
    "AnalyzeScreenTool",
    "VisualGroundingClickTool",
]
