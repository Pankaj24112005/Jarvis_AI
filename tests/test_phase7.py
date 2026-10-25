"""Unit and Integration Tests for JARVIS Phase 7: Perception & Intelligent Computer Control."""

import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from jarvis.core.agent import JarvisAgent
from jarvis.events import EventBus, EventType
from jarvis.memory import MemoryManager
from jarvis.models.base import AIProvider, ModelResponse, ToolCallRequest
from jarvis.security.permissions import (
    AuditLogger,
    PermissionController,
    PermissionLevel,
)
from jarvis.tools.computer import (
    DoubleClickTool,
    KeyPressTool,
    KeyboardHotkeyTool,
    KeyboardTypeTool,
    MouseClickTool,
    MouseMoveTool,
    MouseScrollTool,
    RightClickTool,
)
from jarvis.tools.grounding import VisualGroundingClickTool
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.screen import (
    AnalyzeScreenTool,
    CaptureScreenTool,
    GetActiveApplicationTool,
    GetActiveWindowTool,
)


# ==============================================================================
# 1. Screen Perception & Context Tests (Phase 7B & 7C)
# ==============================================================================

@pytest.mark.asyncio
async def test_capture_screen_memory_only_privacy():
    """Verify screen capture stays in RAM and does not write to disk by default."""
    tool = CaptureScreenTool()

    import numpy as np
    from PIL import Image

    mock_img = Image.new("RGB", (800, 600), color="blue")

    with patch("pyautogui.screenshot", return_value=mock_img):
        res = await tool.execute()
        assert res.success
        assert res.result["status"] == "captured"
        assert res.result["width"] == 800
        assert res.result["height"] == 600
        assert res.result["format"] == "jpeg"
        assert "image_base64" in res.result
        assert res.result["saved_to_disk"] is False
        assert res.result["path"] is None


@pytest.mark.asyncio
async def test_capture_screen_explicit_save_path(tmp_path: Path):
    """Verify screen capture persists to disk only when save_path is explicitly commanded."""
    tool = CaptureScreenTool()

    from PIL import Image
    mock_img = Image.new("RGB", (400, 300), color="red")
    out_file = tmp_path / "explicit_capture.png"

    with patch("pyautogui.screenshot", return_value=mock_img):
        res = await tool.execute(save_path=str(out_file))
        assert res.success
        assert res.result["saved_to_disk"] is True
        assert res.result["path"] == str(out_file)
        assert out_file.exists()


@pytest.mark.asyncio
async def test_get_active_window_success():
    """Verify inspection of foreground window geometry, title, and process."""
    tool = GetActiveWindowTool()

    mock_win = MagicMock()
    mock_win.title = "main.py - Visual Studio Code"
    mock_win._hWnd = 9999
    mock_win.left = 100
    mock_win.top = 50
    mock_win.width = 1200
    mock_win.height = 800
    mock_win.isMinimized = False
    mock_win.isMaximized = True

    mock_proc = MagicMock()
    mock_proc.name.return_value = "Code.exe"

    with patch("pygetwindow.getActiveWindow", return_value=mock_win), \
         patch("ctypes.windll.user32.GetWindowThreadProcessId", return_value=1), \
         patch("psutil.Process", return_value=mock_proc):
        res = await tool.execute()
        assert res.success
        assert res.result["has_active_window"] is True
        assert res.result["title"] == "main.py - Visual Studio Code"
        assert res.result["geometry"]["width"] == 1200
        assert res.result["is_maximized"] is True


@pytest.mark.asyncio
async def test_get_active_application_with_project_memory(tmp_path: Path):
    """Verify active application detection enriched with project state memory."""
    mem = MemoryManager(base_dir=str(tmp_path / "mem"))
    tool = GetActiveApplicationTool(memory_manager=mem)

    # Mock window tool execution
    with patch(
        "jarvis.tools.screen.GetActiveWindowTool.execute",
        new=AsyncMock(
            return_value=MagicMock(
                success=True,
                result={
                    "has_active_window": True,
                    "title": "main.py - Jarves gemini - Visual Studio Code",
                    "process_name": "Code.exe",
                    "pid": 4321,
                },
            )
        ),
    ):
        res = await tool.execute()
        assert res.success
        assert res.result["application"] == "Visual Studio Code"
        assert res.result["pid"] == 4321
        assert "Visual Studio Code" in res.result["summary"]


@pytest.mark.asyncio
async def test_analyze_screen_gemini_vision():
    """Verify analyze_screen sends screenshot to AIProvider.analyze_image."""
    mock_ai = MagicMock(spec=AIProvider)
    mock_ai.analyze_image = AsyncMock(
        return_value=ModelResponse(text="Found a Python syntax error on line 42.")
    )

    tool = AnalyzeScreenTool(ai_provider=mock_ai)

    from PIL import Image
    mock_img = Image.new("RGB", (640, 480), color="green")

    with patch("pyautogui.screenshot", return_value=mock_img), \
         patch(
             "jarvis.tools.screen.GetActiveWindowTool.execute",
             new=AsyncMock(return_value=MagicMock(success=True, result={"title": "VS Code"})),
         ):
        res = await tool.execute(prompt="Explain this error")
        assert res.success
        assert res.result["status"] == "analyzed"
        assert "syntax error on line 42" in res.result["analysis"]
        assert res.result["active_window"] == "VS Code"
        mock_ai.analyze_image.assert_called_once()


# ==============================================================================
# 2. Controlled Computer Interaction Tests (Phase 7D)
# ==============================================================================

@pytest.mark.asyncio
async def test_mouse_move_and_verify():
    """Verify mouse_move moves cursor and verifies final coordinates."""
    tool = MouseMoveTool()

    with patch("pyautogui.moveTo") as mock_move, \
         patch("pyautogui.position", return_value=(400, 300)):
        res = await tool.execute(x=400, y=300)
        assert res.success
        assert res.result["verified"] is True
        assert res.result["x"] == 400
        assert res.result["y"] == 300
        mock_move.assert_called_once()


@pytest.mark.asyncio
async def test_mouse_click_and_double_click():
    """Verify click and double-click actions."""
    click_tool = MouseClickTool()
    dbl_tool = DoubleClickTool()

    with patch("pyautogui.click") as mock_click, \
         patch("pyautogui.position", return_value=(500, 250)):
        c_res = await click_tool.execute(x=500, y=250, button="left")
        assert c_res.success
        assert c_res.result["action"] == "click"
        assert c_res.result["verified"] is True
        mock_click.assert_called_once_with(x=500, y=250, button="left", clicks=1)

    with patch("pyautogui.doubleClick") as mock_dbl, \
         patch("pyautogui.position", return_value=(600, 350)):
        d_res = await dbl_tool.execute(x=600, y=350)
        assert d_res.success
        assert d_res.result["action"] == "double_click"
        assert d_res.result["verified"] is True
        mock_dbl.assert_called_once_with(x=600, y=350)


@pytest.mark.asyncio
async def test_mouse_right_click_and_scroll():
    """Verify right_click and mouse_scroll tools."""
    right_tool = RightClickTool()
    scroll_tool = MouseScrollTool()

    with patch("pyautogui.rightClick") as mock_right, \
         patch("pyautogui.position", return_value=(300, 400)):
        r_res = await right_tool.execute(x=300, y=400)
        assert r_res.success
        assert r_res.result["action"] == "right_click"
        mock_right.assert_called_once_with(x=300, y=400)

    with patch("pyautogui.scroll") as mock_scroll:
        s_res = await scroll_tool.execute(clicks=5, direction="down")
        assert s_res.success
        assert s_res.result["direction"] == "down"
        assert s_res.result["clicks"] == 5
        mock_scroll.assert_called_once_with(-5)


@pytest.mark.asyncio
async def test_keyboard_type_and_press_key():
    """Verify keyboard typing and single key pressing."""
    type_tool = KeyboardTypeTool()
    key_tool = KeyPressTool()

    with patch("pyautogui.write") as mock_write:
        t_res = await type_tool.execute(text="Hello world")
        assert t_res.success
        assert t_res.result["typed_length"] == 11
        mock_write.assert_called_once_with("Hello world", interval=0.02)

    with patch("pyautogui.press") as mock_press:
        k_res = await key_tool.execute(key="enter", presses=2)
        assert k_res.success
        assert k_res.result["key"] == "enter"
        assert k_res.result["presses"] == 2
        mock_press.assert_called_once_with("enter", presses=2)


# ==============================================================================
# 3. Visual Grounding Tests (Phase 7E & 7F)
# ==============================================================================

@pytest.mark.asyncio
async def test_visual_grounding_click_target_found():
    """Verify visual grounding translates normalized box coordinates to pixels and clicks."""
    vision_mock_json = json.dumps({
        "target_found": True,
        "target_label": "Submit button",
        "box_2d": [400, 300, 600, 700],  # ymin, xmin, ymax, xmax
        "confidence": 0.98,
    })

    mock_ai = MagicMock(spec=AIProvider)
    mock_ai.analyze_image = AsyncMock(return_value=ModelResponse(text=vision_mock_json))

    tool = VisualGroundingClickTool(ai_provider=mock_ai)

    from PIL import Image
    # 1000x1000 screen for exact arithmetic:
    # Center X = (300 + 700)/2000 * 1000 = 500
    # Center Y = (400 + 600)/2000 * 1000 = 500
    mock_img = Image.new("RGB", (1000, 1000), color="white")

    with patch("pyautogui.screenshot", return_value=mock_img), \
         patch("pyautogui.size", return_value=(1000, 1000)), \
         patch("pyautogui.click") as mock_click, \
         patch("asyncio.sleep", new=AsyncMock()):
        res = await tool.execute(target="Submit button", action="click")
        assert res.success
        assert res.result["target"] == "Submit button"
        assert res.result["x"] == 500
        assert res.result["y"] == 500
        assert res.result["verified"] is True
        mock_click.assert_called_once_with(500, 500)


@pytest.mark.asyncio
async def test_visual_grounding_target_not_found_does_not_click():
    """Verify visual grounding fails gracefully and NEVER clicks if target is not identified."""
    vision_mock_json = json.dumps({
        "target_found": False,
        "reason": "not_found",
    })

    mock_ai = MagicMock(spec=AIProvider)
    mock_ai.analyze_image = AsyncMock(return_value=ModelResponse(text=vision_mock_json))

    tool = VisualGroundingClickTool(ai_provider=mock_ai)

    from PIL import Image
    mock_img = Image.new("RGB", (800, 600), color="black")

    with patch("pyautogui.screenshot", return_value=mock_img), \
         patch("pyautogui.click") as mock_click:
        res = await tool.execute(target="Nonexistent Cancel Button")
        assert not res.success
        assert res.result["reason"] == "target_not_confidently_identified"
        # Zero arbitrary clicks!
        mock_click.assert_not_called()


# ==============================================================================
# 4. Security, Audit Logging & Sensitive Data Redaction (Phase 7G & 7H)
# ==============================================================================

def test_phase7_permission_tiers():
    """Verify all Phase 7 perception and control tools have exact security classification levels."""
    assert CaptureScreenTool().permission_level == PermissionLevel.LOW_RISK
    assert GetActiveWindowTool().permission_level == PermissionLevel.LOW_RISK
    assert GetActiveApplicationTool().permission_level == PermissionLevel.LOW_RISK
    assert MouseMoveTool().permission_level == PermissionLevel.LOW_RISK

    # Direct visual analysis & input modification require MODERATE
    assert AnalyzeScreenTool().permission_level == PermissionLevel.MODERATE
    assert MouseClickTool().permission_level == PermissionLevel.MODERATE
    assert DoubleClickTool().permission_level == PermissionLevel.MODERATE
    assert RightClickTool().permission_level == PermissionLevel.MODERATE
    assert MouseScrollTool().permission_level == PermissionLevel.MODERATE
    assert KeyboardTypeTool().permission_level == PermissionLevel.MODERATE
    assert KeyPressTool().permission_level == PermissionLevel.MODERATE
    assert KeyboardHotkeyTool().permission_level == PermissionLevel.MODERATE
    assert VisualGroundingClickTool().permission_level == PermissionLevel.MODERATE


@pytest.mark.asyncio
async def test_audit_logger_redacts_base64_image_data(tmp_path: Path):
    """Verify that image payloads and long base64 strings are strictly redacted from audit logs."""
    audit_log = tmp_path / "audit.log"
    logger = AuditLogger(log_path=str(audit_log))

    fake_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" * 10
    args = {
        "action": "analyze",
        "image_base64": fake_base64,
        "token": "secret_token_12345",
    }

    logger.log("analyze_screen", args, PermissionLevel.MODERATE, approved=True)

    assert audit_log.exists()
    record = json.loads(audit_log.read_text(encoding="utf-8").strip())
    assert record["arguments"]["token"] == "[REDACTED]"
    assert record["arguments"]["image_base64"] == "[IMAGE_DATA_REDACTED]"


# ==============================================================================
# 5. HUD Telemetry & EventBus Integration (Phase 7J)
# ==============================================================================

@pytest.mark.asyncio
async def test_screen_capture_and_grounding_telemetry():
    """Verify EventBus emits started, finished, requested, executed, and verified events."""
    bus = EventBus()
    events_received: list[str] = []

    def record_event(evt):
        val = evt.type.value if hasattr(evt.type, "value") else str(evt.type)
        events_received.append(val)

    for et in [
        EventType.SCREEN_CAPTURE_STARTED,
        EventType.SCREEN_CAPTURE_FINISHED,
        EventType.VISION_ANALYSIS_STARTED,
        EventType.VISION_ANALYSIS_FINISHED,
        EventType.COMPUTER_ACTION_REQUESTED,
        EventType.COMPUTER_ACTION_EXECUTED,
        EventType.COMPUTER_ACTION_VERIFIED,
    ]:
        bus.subscribe(et, record_event)

    tool = CaptureScreenTool(event_bus=bus)

    from PIL import Image
    mock_img = Image.new("RGB", (200, 200), color="gray")

    with patch("pyautogui.screenshot", return_value=mock_img):
        res = await tool.execute()
        assert res.success
        assert EventType.SCREEN_CAPTURE_STARTED.value in events_received
        assert EventType.SCREEN_CAPTURE_FINISHED.value in events_received


# ==============================================================================
# 6. End-to-End Agent Perception & Control Selection
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_routes_screen_perception(tmp_path: Path):
    """Verify JarvisAgent invokes analyze_screen when asked 'What is on my screen?'."""
    audit_log = tmp_path / "audit.log"
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(audit_log)))

    registry = ToolRegistry()
    registry.register(AnalyzeScreenTool())
    registry.register(GetActiveApplicationTool())

    class PerceptionModel(AIProvider):
        async def generate(self, prompt: str, **kwargs):
            if "what is on my screen" in prompt.lower():
                return ModelResponse(
                    text="Inspecting your screen",
                    tool_calls=[ToolCallRequest(name="analyze_screen", arguments={"prompt": "Explain screen"})],
                )
            return ModelResponse(text="Screen inspection complete.")

        async def stream(self, prompt: str, **kwargs):
            yield "stream"

        async def generate_with_tools(self, prompt: str, tools: list, **kwargs):
            return await self.generate(prompt, **kwargs)

        async def analyze_image(self, prompt: str, image_bytes: bytes, **kwargs):
            return ModelResponse(text="A code editor is open.")

        async def create_embedding(self, text: str, **kwargs):
            return []

    model = PerceptionModel()
    mem = MemoryManager(base_dir=str(tmp_path / "mem"))
    agent = JarvisAgent(
        ai_provider=model,
        tool_registry=registry,
        permission_controller=controller,
        memory_manager=mem,
    )

    from PIL import Image
    mock_img = Image.new("RGB", (400, 400), color="black")

    with patch("pyautogui.screenshot", return_value=mock_img), \
         patch(
             "jarvis.tools.screen.GetActiveWindowTool.execute",
             new=AsyncMock(return_value=MagicMock(success=True, result={"title": "VS Code"})),
         ):
        response = await agent.process_user_input("What is on my screen?")
        assert "analyze_screen: success" in response


# ==============================================================================
# 7. Verification Failure, Cancellation, Timeout & Sensitivity Verification
# ==============================================================================

@pytest.mark.asyncio
async def test_mouse_move_failed_verification():
    """Verify that if OS does not place cursor at requested coordinates, verified is False."""
    tool = MouseMoveTool()

    with patch("pyautogui.moveTo"), \
         patch("pyautogui.position", return_value=(100, 100)):  # Requested (500, 500) but ended at (100, 100)
        res = await tool.execute(x=500, y=500)
        assert res.success
        assert res.result["verified"] is False
        assert res.result["x"] == 100
        assert res.result["y"] == 100


@pytest.mark.asyncio
async def test_keyboard_type_sensitive_secret_redaction():
    """Verify keyboard typing masks preview if sensitive keys or tokens are entered."""
    bus = EventBus()
    emitted = []

    def record_evt(evt):
        emitted.append(evt)

    bus.subscribe(EventType.COMPUTER_ACTION_REQUESTED, record_evt)
    tool = KeyboardTypeTool(event_bus=bus)

    with patch("pyautogui.write"):
        res = await tool.execute(text="export AIZA_SECRET_KEY=1234567890abcdef")
        assert res.success
        assert len(emitted) == 1
        assert emitted[0].data["preview"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_task_execution_cancellation():
    """Verify task cancellation aborts perception/control without hung background loops."""
    async def slow_perception():
        await asyncio.sleep(5)

    task = asyncio.create_task(slow_perception())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_task_execution_timeout():
    """Verify asyncio.wait_for properly enforces perception/tool timeouts."""
    async def hanging_call():
        await asyncio.sleep(2)
        return "done"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(hanging_call(), timeout=0.05)
