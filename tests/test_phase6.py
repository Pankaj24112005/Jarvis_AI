"""Unit & Integration Tests for JARVIS Phase 6: Application, Media, Vision & Music Subsystems."""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis.core.agent import JarvisAgent
from jarvis.models.base import AIProvider, ModelResponse, ToolCallRequest
from jarvis.security.permissions import (
    AuditLogger,
    PermissionController,
    PermissionLevel,
)
from jarvis.tools.applications import (
    KNOWN_WINDOWS_APPS,
    CloseApplicationTool,
    LaunchApplicationTool,
    TerminateProcessTool,
)
from jarvis.tools.browser import BrowserControlTool
from jarvis.tools.camera import (
    AnalyzeCameraFrameTool,
    CaptureCameraFrameTool,
    OpenCameraTool,
)
from jarvis.tools.media import YouTubeControlTool
from jarvis.tools.registry import ToolRegistry, default_tool_registry
from jarvis.voice.music import (
    GoogleLiveMusicGenerator,
    MusicControlTool,
    SingingCapabilityHandler,
)


# ==============================================================================
# 1. Application Control Tests (Phase 6B)
# ==============================================================================

@pytest.mark.asyncio
async def test_launch_application_uwp_camera():
    """Verify that launching 'camera' safely uses Windows UWP URI and verifies."""
    tool = LaunchApplicationTool()

    with patch("os.startfile") as mock_startfile, \
         patch.object(tool, "_verify_launch", new=AsyncMock(return_value=True)):
        res = await tool.execute(app_name="camera")
        assert res.success
        assert res.result["launch_type"] == "uri"
        assert res.result["target"] == "microsoft.windows.camera:"
        assert res.result["verified"] is True
        mock_startfile.assert_called_once_with("microsoft.windows.camera:")


@pytest.mark.asyncio
async def test_launch_application_binary_notepad():
    """Verify that launching 'notepad' resolves binary and creates process safely."""
    tool = LaunchApplicationTool()

    mock_proc = MagicMock()
    mock_proc.pid = 1234
    mock_proc.returncode = None

    with patch("shutil.which", return_value="C:\\Windows\\System32\\notepad.exe"), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)), \
         patch.object(tool, "_verify_launch", new=AsyncMock(return_value=True)):
        res = await tool.execute(app_name="notepad")
        assert res.success
        assert res.result["launch_type"] == "binary"
        assert res.result["pid"] == 1234
        assert res.result["verified"] is True


@pytest.mark.asyncio
async def test_launch_application_injection_prevention():
    """Verify that command injection attempts are blocked."""
    tool = LaunchApplicationTool()

    # Semicolon injection
    res1 = await tool.execute(app_name="notepad; rm -rf /")
    assert not res1.success
    assert "Invalid characters detected" in res1.error

    # Pipe injection
    res2 = await tool.execute(app_name="calc | whoami")
    assert not res2.success
    assert "Invalid characters detected" in res2.error

    # Ampersand chaining
    res3 = await tool.execute(app_name="notepad & dir")
    assert not res3.success
    assert "Invalid characters detected" in res3.error


@pytest.mark.asyncio
async def test_launch_application_unknown():
    """Verify that unknown applications fail with informative message."""
    tool = LaunchApplicationTool()

    with patch("shutil.which", return_value=None):
        res = await tool.execute(app_name="non_existent_app_9999")
        assert not res.success
        assert "not recognized in known applications" in res.error


# ==============================================================================
# 2. Camera Tools Tests (Phase 6E)
# ==============================================================================

@pytest.mark.asyncio
async def test_open_camera_tool():
    """Verify open_camera launches native Windows Camera app via URI."""
    tool = OpenCameraTool()

    with patch("os.startfile") as mock_startfile, \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch("psutil.process_iter", return_value=[]):
        res = await tool.execute()
        assert res.success
        assert res.result["uri"] == "microsoft.windows.camera:"
        mock_startfile.assert_called_once_with("microsoft.windows.camera:")


@pytest.mark.asyncio
async def test_capture_camera_frame_success():
    """Verify single frame capture, immediate device release, and JPEG base64 encoding."""
    tool = CaptureCameraFrameTool()

    import numpy as np
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, mock_frame)

    mock_cv2 = MagicMock()
    mock_cv2.CAP_DSHOW = 700
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.imencode.return_value = (True, MagicMock(tobytes=lambda: b"\xff\xd8\xffdummyjpeg"))

    with patch.dict("sys.modules", {"cv2": mock_cv2}):
        res = await tool.execute()
        assert res.success
        assert res.result["format"] == "jpeg"
        assert res.result["width"] == 640
        assert res.result["height"] == 480
        assert "image_base64" in res.result
        mock_cap.release.assert_called_once()


@pytest.mark.asyncio
async def test_capture_camera_frame_no_device():
    """Verify error handling when camera device is inaccessible or in use."""
    tool = CaptureCameraFrameTool()

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False

    mock_cv2 = MagicMock()
    mock_cv2.VideoCapture.return_value = mock_cap

    with patch.dict("sys.modules", {"cv2": mock_cv2}):
        res = await tool.execute()
        assert not res.success
        assert "Unable to capture frame" in res.error
        mock_cap.release.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_camera_frame_with_ai():
    """Verify analyze_camera_frame captures frame and calls ai_provider.analyze_image."""
    mock_ai = MagicMock(spec=AIProvider)
    mock_ai.analyze_image = AsyncMock(
        return_value=ModelResponse(text="A cup of coffee next to a laptop.")
    )

    tool = AnalyzeCameraFrameTool(ai_provider=mock_ai)

    # Mock CaptureCameraFrameTool to succeed
    with patch(
        "jarvis.tools.camera.CaptureCameraFrameTool.execute",
        new=AsyncMock(
            return_value=MagicMock(
                success=True,
                result={
                    "width": 640,
                    "height": 480,
                    "image_base64": "dummyb64",
                },
            )
        ),
    ), patch("base64.b64decode", return_value=b"fake_jpeg_bytes"):
        res = await tool.execute(prompt="What is in front of me?")
        assert res.success
        assert res.result["status"] == "analyzed"
        assert "coffee next to a laptop" in res.result["analysis"]
        mock_ai.analyze_image.assert_called_once_with(
            prompt="What is in front of me?",
            image_bytes=b"fake_jpeg_bytes",
        )


# ==============================================================================
# 3. YouTube Media Control Tests (Phase 6C / 6D)
# ==============================================================================

@pytest.mark.asyncio
async def test_youtube_control_play_success():
    """Verify play action resolves video ID, opens direct watch URL, and returns status."""
    tool = YouTubeControlTool()

    with patch.object(
        tool, "_resolve_top_video", return_value=("dQw4w9WgXcQ", "Never Gonna Give You Up")
    ), patch("webbrowser.open") as mock_browser, \
       patch.object(tool, "_is_youtube_window_present", return_value=True), \
       patch("asyncio.sleep", new=AsyncMock()):
        res = await tool.execute(action="play", query="Never Gonna Give You Up")
        assert res.success
        assert res.result["status"] == "playing"
        assert res.result["video_id"] == "dQw4w9WgXcQ"
        assert res.result["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert "autoplay_note" in res.result
        mock_browser.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


@pytest.mark.asyncio
async def test_youtube_control_play_fallback():
    """Verify play action falls back to search page if video ID resolution fails."""
    tool = YouTubeControlTool()

    with patch.object(tool, "_resolve_top_video", return_value=(None, None)), \
         patch("webbrowser.open") as mock_browser:
        res = await tool.execute(action="play", query="Obscure Indie Song")
        assert res.success
        assert res.result["status"] == "search_results_opened"
        assert res.result["requires_user_click"] is True
        assert "results?search_query=" in res.result["url"]
        mock_browser.assert_called_once()


def test_youtube_video_id_regex_parser():
    """Verify HTML parsing extracts standard 11-char YouTube video ID and title."""
    tool = YouTubeControlTool()

    sample_html = """
    <html>
      <body>
        <a href="/watch?v=9bZkp7q19f0">Watch</a>
        <div>"title":{"runs":[{"text":"PSY - GANGNAM STYLE (Official Music Video)"}]}</div>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.read.return_value = sample_html.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        vid_id, title = tool._resolve_top_video("gangnam style")
        assert vid_id == "9bZkp7q19f0"
        assert title == "PSY - GANGNAM STYLE (Official Music Video)"


@pytest.mark.asyncio
async def test_youtube_control_pause_resume_skip_stop():
    """Verify window control triggers expected keyboard events."""
    tool = YouTubeControlTool()

    mock_win = MagicMock()
    mock_win.title = "Rick Astley - Never Gonna Give You Up (Official Video) - YouTube - Google Chrome"
    mock_win.isMinimized = False

    with patch("pygetwindow.getAllWindows", return_value=[mock_win]), \
         patch("pyautogui.press") as mock_press, \
         patch("pyautogui.hotkey") as mock_hotkey, \
         patch("asyncio.sleep", new=AsyncMock()):

        # Pause
        p_res = await tool.execute(action="pause")
        assert p_res.success
        assert p_res.result["status"] == "paused"
        mock_press.assert_called_with("k")

        # Resume
        r_res = await tool.execute(action="resume")
        assert r_res.success
        assert r_res.result["status"] == "resumed"

        # Skip
        s_res = await tool.execute(action="skip")
        assert s_res.success
        assert s_res.result["status"] == "skipped"
        mock_hotkey.assert_called_with("shift", "n")

        # Stop
        stop_res = await tool.execute(action="stop")
        assert stop_res.success
        assert stop_res.result["status"] == "stopped"


@pytest.mark.asyncio
async def test_youtube_control_missing_query():
    """Verify play action fails fast if query is missing."""
    tool = YouTubeControlTool()
    res = await tool.execute(action="play", query="")
    assert not res.success
    assert "requires a 'query' parameter" in res.error


# ==============================================================================
# 4. Music & Singing Subsystem Tests (Phase 6F)
# ==============================================================================

def test_singing_capability_handler_honesty():
    """Verify singing requests return clear technical boundaries and alternatives."""
    info = SingingCapabilityHandler.inspect_request("Sing Bohemian Rhapsody")
    assert info["supported"] is False
    assert info["capability"] == "vocal_singing_synthesis"
    assert "do not support" in info["reason"].lower() or "conversational speech" in info["reason"].lower()
    assert any(a["tool"] == "youtube_control" for a in info["suggested_actions"])


def test_google_live_music_generator_capabilities():
    """Verify live music generator declares instrumental capabilities and boundaries."""
    gen = GoogleLiveMusicGenerator()
    caps = gen.get_capabilities()
    assert caps["instrumental_generation"] is True
    assert caps["vocal_singing_synthesis"] is False
    assert "bpm" in caps["controls"]
    assert "drums" in caps["controls"]


@pytest.mark.asyncio
async def test_music_control_tool_actions():
    """Verify MusicControlTool handles sing_song, get_capabilities, and stop actions."""
    tool = MusicControlTool()

    # sing_song
    sing_res = await tool.execute(action="sing_song", prompt="Sing Believer")
    assert sing_res.success
    assert sing_res.result["vocal_synthesis_available"] is False
    assert "youtube_control" in sing_res.result["recommendation"]

    # get_capabilities
    cap_res = await tool.execute(action="get_capabilities")
    assert cap_res.success
    assert cap_res.result["instrumental_generation"] is True

    # stop
    stop_res = await tool.execute(action="stop")
    assert stop_res.success
    assert stop_res.result["status"] == "stopped"


# ==============================================================================
# 5. Security, Permissions & Audit Logging for Phase 6 Tools
# ==============================================================================

def test_phase6_tool_permission_tiers():
    """Verify all Phase 6 tools have exact security classification levels."""
    assert LaunchApplicationTool().permission_level == PermissionLevel.LOW_RISK
    assert OpenCameraTool().permission_level == PermissionLevel.LOW_RISK
    assert YouTubeControlTool().permission_level == PermissionLevel.LOW_RISK
    assert MusicControlTool().permission_level == PermissionLevel.LOW_RISK

    # Direct hardware frame capture & vision analysis require MODERATE tier
    assert CaptureCameraFrameTool().permission_level == PermissionLevel.MODERATE
    assert AnalyzeCameraFrameTool().permission_level == PermissionLevel.MODERATE


@pytest.mark.asyncio
async def test_phase6_registry_and_audit_logging(tmp_path: Path):
    """Verify executing Phase 6 tools through ToolRegistry writes sanitized audit logs."""
    audit_log = tmp_path / "audit.log"
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(audit_log)))

    registry = ToolRegistry()
    registry.register(YouTubeControlTool())
    registry.register(MusicControlTool())

    # Execute MusicControlTool
    res = await registry.execute("music_control", {"action": "get_capabilities"}, controller)
    assert res.success

    # Check audit log content
    assert audit_log.exists()
    lines = audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    record = json.loads(lines[-1])
    assert record["tool"] == "music_control"
    assert record["approved"] is True
    assert record["level_name"] == "LOW_RISK"


# ==============================================================================
# 6. End-to-End Agent Tool Calling Loop with Phase 6 Tools
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_invokes_youtube_control(tmp_path: Path):
    """Verify JarvisAgent receives tool call from model and executes youtube_control."""
    audit_log = tmp_path / "audit.log"
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(audit_log)))

    registry = ToolRegistry()
    registry.register(YouTubeControlTool())

    class MockModel(AIProvider):
        def __init__(self):
            self.turn = 0

        async def generate(self, prompt: str, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return ModelResponse(
                    text="Playing your song",
                    tool_calls=[
                        ToolCallRequest(
                            name="youtube_control",
                            arguments={"action": "play", "query": "Believer"},
                        )
                    ],
                )
            return ModelResponse(text="Started playing Believer on YouTube.")

        async def stream(self, prompt: str, **kwargs):
            yield "stream"

        async def generate_with_tools(self, prompt: str, tools: list, **kwargs):
            return await self.generate(prompt, **kwargs)

        async def analyze_image(self, prompt: str, image_bytes: bytes, **kwargs):
            return ModelResponse()

        async def create_embedding(self, text: str, **kwargs):
            return []

    agent = JarvisAgent(
        ai_provider=MockModel(),
        tool_registry=registry,
        permission_controller=controller,
    )

    with patch.object(
        YouTubeControlTool, "_resolve_top_video", return_value=("fake_vid_id", "Believer")
    ), patch("webbrowser.open"), \
       patch.object(YouTubeControlTool, "_is_youtube_window_present", return_value=True), \
       patch("asyncio.sleep", new=AsyncMock()):
        response = await agent.process_user_input("Play Believer on YouTube")
        assert "youtube_control: success" in response
        assert "playing" in response.lower()


# ==============================================================================
# 7. Graceful Close, Force Terminate, and Browser Tab Closing Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_close_application_graceful_auto_approved(tmp_path: Path):
    """Verify close_application is classified as LOW_RISK and auto-approved."""
    audit_log = tmp_path / "audit.log"
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(audit_log)))

    registry = ToolRegistry()
    registry.register(CloseApplicationTool())

    mock_win = MagicMock()
    mock_win.title = "Google - Google Chrome"
    mock_win._hWnd = 1001

    # First call returns mock_win, second returns empty list (window closed)
    get_windows_side_effects = [[mock_win], []]

    with patch("pygetwindow.getAllWindows", side_effect=lambda: get_windows_side_effects.pop(0) if get_windows_side_effects else []), \
         patch("pygetwindow.getActiveWindow", return_value=mock_win), \
         patch("asyncio.sleep", new=AsyncMock()):
        res = await registry.execute("close_application", {"app_name": "Chrome"}, controller)
        assert res.success
        assert res.result["action"] == "graceful_close"
        assert res.result["application"] == "Chrome"
        assert res.result["closed"] is True
        mock_win.close.assert_called_once()

    # Verify audit log recorded LOW_RISK and approved
    assert audit_log.exists()
    records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").strip().splitlines()]
    assert records[-1]["tool"] == "close_application"
    assert records[-1]["level_name"] == "LOW_RISK"
    assert records[-1]["approved"] is True


@pytest.mark.asyncio
async def test_close_application_does_not_kill_process():
    """Verify that graceful close sends WM_CLOSE and never invokes psutil terminate."""
    tool = CloseApplicationTool()

    mock_win = MagicMock()
    mock_win.title = "Untitled - Notepad"
    mock_win._hWnd = 2002

    with patch("pygetwindow.getAllWindows", return_value=[mock_win]), \
         patch("pygetwindow.getActiveWindow", return_value=mock_win), \
         patch("psutil.Process.terminate") as mock_ps_terminate, \
         patch("asyncio.sleep", new=AsyncMock()):
        res = await tool.execute(app_name="Notepad")
        assert res.success
        assert res.result["action"] == "graceful_close"
        mock_win.close.assert_called_once()
        # Explicit verification: process termination was NEVER called
        mock_ps_terminate.assert_not_called()


@pytest.mark.asyncio
async def test_close_application_multi_window_targets_active_only():
    """Verify that when multiple Chrome windows exist, only the target/active one is closed."""
    tool = CloseApplicationTool()

    active_win = MagicMock()
    active_win.title = "Active Work Tab - Google Chrome"
    active_win._hWnd = 3001

    background_win = MagicMock()
    background_win.title = "Background Research - Google Chrome"
    background_win._hWnd = 3002

    with patch("pygetwindow.getAllWindows", return_value=[active_win, background_win]), \
         patch("pygetwindow.getActiveWindow", return_value=active_win), \
         patch("asyncio.sleep", new=AsyncMock()):
        res = await tool.execute(app_name="Chrome")
        assert res.success
        assert res.result["action"] == "graceful_close"
        # Only the active window was closed
        active_win.close.assert_called_once()
        background_win.close.assert_not_called()


@pytest.mark.asyncio
async def test_terminate_process_requires_confirmation(tmp_path: Path):
    """Verify terminate_process is HIGH_RISK (Level 3) and requires confirmation."""
    tool = TerminateProcessTool()
    assert tool.permission_level == PermissionLevel.HIGH_RISK

    audit_log = tmp_path / "audit.log"
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(audit_log)))

    registry = ToolRegistry()
    registry.register(tool)

    # 1. User denies permission
    with patch("jarvis.security.permissions.Confirm.ask", return_value=False):
        denied_res = await registry.execute("terminate_process", {"name_or_pid": "chrome.exe"}, controller)
        assert not denied_res.success
        assert "denied" in denied_res.error.lower()

    # 2. User approves permission
    mock_proc = MagicMock()
    mock_proc.info = {"pid": 9876, "name": "chrome.exe"}

    with patch("jarvis.security.permissions.Confirm.ask", return_value=True), \
         patch("psutil.process_iter", return_value=[mock_proc]):
        approved_res = await registry.execute("terminate_process", {"name_or_pid": "chrome.exe"}, controller)
        assert approved_res.success
        assert approved_res.result["action"] == "force_terminate"
        assert "PID 9876" in approved_res.result["closed"][0]
        mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_browser_control_close_tab_does_not_terminate_browser():
    """Verify browser_control(action='close_tab') sends Ctrl+W and does not terminate browser."""
    tool = BrowserControlTool()
    assert tool.permission_level == PermissionLevel.LOW_RISK

    mock_win = MagicMock()
    mock_win.title = "GitHub - Google Chrome"

    with patch("pygetwindow.getAllWindows", return_value=[mock_win]), \
         patch("pyautogui.hotkey") as mock_hotkey, \
         patch("psutil.Process.terminate") as mock_terminate, \
         patch("asyncio.sleep", new=AsyncMock()):
        res = await tool.execute(action="close_tab", target="Chrome")
        assert res.success
        assert res.result["action"] == "close_tab"
        assert res.result["status"] == "closed"
        mock_hotkey.assert_called_once_with("ctrl", "w")
        mock_terminate.assert_not_called()


@pytest.mark.asyncio
async def test_youtube_control_close_tab():
    """Verify youtube_control(action='close_tab') sends Ctrl+W and does not close browser."""
    tool = YouTubeControlTool()

    mock_win = MagicMock()
    mock_win.title = "Believer - YouTube - Google Chrome"
    mock_win.isMinimized = False

    with patch("pygetwindow.getAllWindows", return_value=[mock_win]), \
         patch("pyautogui.hotkey") as mock_hotkey, \
         patch("asyncio.sleep", new=AsyncMock()):
        res = await tool.execute(action="close_tab")
        assert res.success
        assert res.result["action"] == "close_tab"
        assert res.result["status"] == "tab_closed"
        mock_hotkey.assert_called_once_with("ctrl", "w")


@pytest.mark.asyncio
async def test_agent_intent_selection_close_vs_tab_vs_kill(tmp_path: Path):
    """Verify agent routes close application vs close tab vs force terminate correctly."""
    audit_log = tmp_path / "audit.log"
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(audit_log)))

    registry = ToolRegistry()
    registry.register(CloseApplicationTool())
    registry.register(BrowserControlTool())
    registry.register(TerminateProcessTool())

    from jarvis.memory import MemoryManager

    class IntentModel(AIProvider):
        async def generate(self, prompt: str, **kwargs):
            # Parse the latest user prompt line from formatted context
            lines = [l for l in prompt.splitlines() if "User:" in l or "kill" in l.lower() or "close" in l.lower()]
            current_input = lines[-1].lower() if lines else prompt.lower()

            if "close this tab" in current_input:
                tool_name = "browser_control"
                args = {"action": "close_tab"}
            elif "kill chrome" in current_input or "force close" in current_input:
                tool_name = "terminate_process"
                args = {"name_or_pid": "chrome.exe"}
            else:
                tool_name = "close_application"
                args = {"app_name": "Chrome"}
            return ModelResponse(
                text="Routing intent",
                tool_calls=[ToolCallRequest(name=tool_name, arguments=args)],
            )

        async def stream(self, prompt: str, **kwargs):
            yield "stream"

        async def generate_with_tools(self, prompt: str, tools: list, **kwargs):
            return await self.generate(prompt, **kwargs)

        async def analyze_image(self, prompt: str, image_bytes: bytes, **kwargs):
            return ModelResponse()

        async def create_embedding(self, text: str, **kwargs):
            return []

    mock_win = MagicMock()
    mock_win.title = "Google - Google Chrome"
    mock_proc = MagicMock()
    mock_proc.info = {"pid": 1122, "name": "chrome.exe"}

    # Test 1: "Close Chrome" -> calls close_application (auto-approved)
    model1 = IntentModel()
    mem1 = MemoryManager(base_dir=str(tmp_path / "mem1"))
    agent1 = JarvisAgent(ai_provider=model1, tool_registry=registry, permission_controller=controller, memory_manager=mem1)
    with patch("pygetwindow.getAllWindows", return_value=[mock_win]), \
         patch("pygetwindow.getActiveWindow", return_value=mock_win), \
         patch("asyncio.sleep", new=AsyncMock()):
        resp1 = await agent1.process_user_input("Close Chrome")
        assert "close_application: success" in resp1

    # Test 2: "Close this tab" -> calls browser_control (auto-approved)
    model2 = IntentModel()
    mem2 = MemoryManager(base_dir=str(tmp_path / "mem2"))
    agent2 = JarvisAgent(ai_provider=model2, tool_registry=registry, permission_controller=controller, memory_manager=mem2)
    with patch("pygetwindow.getAllWindows", return_value=[mock_win]), \
         patch("pyautogui.hotkey"), \
         patch("asyncio.sleep", new=AsyncMock()):
        resp2 = await agent2.process_user_input("Close this tab")
        assert "browser_control: success" in resp2

    # Test 3: "Kill Chrome" -> calls terminate_process (requires approval)
    model3 = IntentModel()
    mem3 = MemoryManager(base_dir=str(tmp_path / "mem3"))
    agent3 = JarvisAgent(ai_provider=model3, tool_registry=registry, permission_controller=controller, memory_manager=mem3)
    with patch("jarvis.security.permissions.Confirm.ask", return_value=True), \
         patch("psutil.process_iter", return_value=[mock_proc]):
        resp3 = await agent3.process_user_input("Kill Chrome")
        assert "terminate_process: success" in resp3

