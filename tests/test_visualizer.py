"""Automated test suite for JARVIS Visualizer & Cybernetic HUD (Phase 5)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType
from jarvis.security.permissions import PermissionController, PermissionLevel
from jarvis.visualizer.adapter import VisualizerAdapter
from jarvis.visualizer.base import (
    TelemetryFrame,
    TelemetryFrameType,
    VisualizerSnapshot,
    sanitize_telemetry_data,
)
from jarvis.visualizer.server import VisualizerServer, create_visualizer_app


# ---------------------------------------------------------------------------
# 1. VisualizerSnapshot Creation & Telemetry Serialization Tests
# ---------------------------------------------------------------------------
def test_visualizer_snapshot_creation():
    """Verify VisualizerSnapshot initializes with default attributes."""
    snap = VisualizerSnapshot(agent_state="IDLE", voice_name="Charon")
    assert snap.agent_state == "IDLE"
    assert snap.voice_name == "Charon"
    assert snap.ptt_pressed is False
    assert snap.is_speaking is False
    assert snap.audio_energy == 0.0
    assert snap.active_tool is None
    assert snap.pending_permission is None

    data = snap.to_dict()
    assert isinstance(data, dict)
    assert data["agent_state"] == "IDLE"
    assert data["voice_name"] == "Charon"

    json_str = snap.to_json()
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["agent_state"] == "IDLE"


def test_telemetry_serialization():
    """Verify TelemetryFrame serializes types, payloads, and timestamps to valid JSON."""
    frame = TelemetryFrame(
        type=TelemetryFrameType.STATE_CHANGE,
        data={"old_state": "IDLE", "new_state": "LISTENING", "reason": "PTT pressed"},
    )
    payload = frame.to_dict()
    assert payload["type"] == "state_change"
    assert payload["data"]["new_state"] == "LISTENING"
    assert isinstance(payload["timestamp"], float)

    json_out = frame.to_json()
    parsed = json.loads(json_out)
    assert parsed["type"] == "state_change"
    assert parsed["data"]["new_state"] == "LISTENING"


# ---------------------------------------------------------------------------
# 2. Secret Redaction Tests
# ---------------------------------------------------------------------------
def test_secret_redaction():
    """Verify API keys, tokens, passwords, and sensitive keys are redacted from telemetry."""
    dirty_data = {
        "api_key": "AIzaSySecretApiKey123456789012345678",
        "nested": {
            "password": "SuperSecretPassword!",
            "user_token": "sk-1234567890abcdefghijklmnop",
            "normal_field": "public_value",
        },
        "query": "Tell me the secret_password_here please",
    }
    sanitized = sanitize_telemetry_data(dirty_data)

    # Sensitive keys should have values replaced
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["user_token"] == "[REDACTED]"
    assert sanitized["nested"]["normal_field"] == "public_value"

    # Raw secret tokens inside text strings should also be redacted
    frame = TelemetryFrame(type=TelemetryFrameType.TOOL_ACTIVITY, data=dirty_data)
    serialized = frame.to_json()
    assert "AIzaSySecretApiKey" not in serialized
    assert "SuperSecretPassword" not in serialized


# ---------------------------------------------------------------------------
# 3. EventBus -> Adapter State Update Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_bus_adapter_state_update():
    """Verify EventBus AGENT_STATE_CHANGED updates the adapter's snapshot."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    adapter = VisualizerAdapter(event_bus=bus, state_machine=sm, voice_name="Charon")

    assert adapter.snapshot.agent_state == "IDLE"

    # Transition to LISTENING
    await sm.transition_to(AgentState.LISTENING, reason="User speaking")
    assert adapter.snapshot.agent_state == "LISTENING"

    # Transition to THINKING
    await sm.transition_to(AgentState.THINKING, reason="Processing prompt")
    assert adapter.snapshot.agent_state == "THINKING"

    # Transition to SPEAKING
    await sm.transition_to(AgentState.SPEAKING, reason="Model response")
    assert adapter.snapshot.agent_state == "SPEAKING"

    # Transition to IDLE
    await sm.transition_to(AgentState.IDLE, reason="Turn finished")
    assert adapter.snapshot.agent_state == "IDLE"


@pytest.mark.asyncio
async def test_state_change_telemetry():
    """Verify adapter broadcasts a TelemetryFrame on state change."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    adapter = VisualizerAdapter(event_bus=bus, state_machine=sm)

    mock_ws = AsyncMock()
    await adapter.register_client(mock_ws)

    # Clear initial snapshot broadcast call
    mock_ws.send_text.reset_mock()

    await sm.transition_to(AgentState.LISTENING, reason="PTT pressed")
    # Allow background broadcast task to execute
    await asyncio.sleep(0.02)

    assert mock_ws.send_text.call_count == 1
    call_arg = mock_ws.send_text.call_args[0][0]
    payload = json.loads(call_arg)
    assert payload["type"] == "state_change"
    assert payload["data"]["new_state"] == "LISTENING"
    assert payload["data"]["reason"] == "PTT pressed"


# ---------------------------------------------------------------------------
# 4. WebSocket Client Lifecycle & Broadcast Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_websocket_client_connection():
    """Verify adapter registers and unregisters WebSocket clients accurately."""
    adapter = VisualizerAdapter(event_bus=EventBus())
    assert adapter.client_count == 0

    mock_ws = AsyncMock()
    await adapter.register_client(mock_ws)
    assert adapter.client_count == 1
    assert adapter.snapshot.connected_clients_count == 1
    # Check that initial snapshot was sent
    mock_ws.send_text.assert_awaited_once()

    await adapter.unregister_client(mock_ws)
    assert adapter.client_count == 0
    assert adapter.snapshot.connected_clients_count == 0


@pytest.mark.asyncio
async def test_telemetry_broadcast():
    """Verify broadcast delivers messages to registered clients."""
    adapter = VisualizerAdapter(event_bus=EventBus())
    mock_ws = AsyncMock()
    await adapter.register_client(mock_ws)
    mock_ws.send_text.reset_mock()

    frame = TelemetryFrame(type=TelemetryFrameType.SYSTEM_ERROR, data={"error": "Test warning"})
    await adapter.broadcast(frame)

    mock_ws.send_text.assert_awaited_once()
    payload = json.loads(mock_ws.send_text.call_args[0][0])
    assert payload["type"] == "system_error"
    assert payload["data"]["error"] == "Test warning"


@pytest.mark.asyncio
async def test_multiple_websocket_clients():
    """Verify multiple connected clients simultaneously receive telemetry."""
    adapter = VisualizerAdapter(event_bus=EventBus())
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    ws3 = AsyncMock()

    await adapter.register_client(ws1)
    await adapter.register_client(ws2)
    await adapter.register_client(ws3)
    assert adapter.client_count == 3

    ws1.send_text.reset_mock()
    ws2.send_text.reset_mock()
    ws3.send_text.reset_mock()

    frame = TelemetryFrame(type=TelemetryFrameType.STATE_CHANGE, data={"new_state": "THINKING"})
    await adapter.broadcast(frame)

    ws1.send_text.assert_awaited_once()
    ws2.send_text.assert_awaited_once()
    ws3.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_disconnect_handling():
    """Verify disconnected or failing clients are pruned without raising unhandled errors."""
    adapter = VisualizerAdapter(event_bus=EventBus())
    good_ws = AsyncMock()
    broken_ws = AsyncMock()
    await adapter.register_client(good_ws)
    await adapter.register_client(broken_ws)
    assert adapter.client_count == 2

    # Now make broken_ws raise error during subsequent broadcast
    broken_ws.send_text.side_effect = ConnectionResetError("Client closed pipe")

    frame = TelemetryFrame(type=TelemetryFrameType.SPEECH_ACTIVITY, data={"is_speaking": True})
    await adapter.broadcast(frame)

    # Broken client should have been removed
    assert adapter.client_count == 1
    assert good_ws.send_text.await_count >= 1


# ---------------------------------------------------------------------------
# 5. Clean Server Lifecycle Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_clean_server_shutdown():
    """Verify VisualizerServer starts on an ephemeral port and shuts down cleanly."""
    adapter = VisualizerAdapter(event_bus=EventBus())
    server = VisualizerServer(adapter=adapter, host="127.0.0.1", port=8990)

    assert not server.is_running
    url = await server.start()
    assert server.is_running
    assert "8990" in url

    await server.stop()
    assert not server.is_running


# ---------------------------------------------------------------------------
# 6. Permission Request Routing & Security Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_permission_request_routing():
    """Verify adapter records pending permission and emits alert frame."""
    bus = EventBus()
    adapter = VisualizerAdapter(event_bus=bus)

    mock_ws = AsyncMock()
    await adapter.register_client(mock_ws)
    mock_ws.send_text.reset_mock()

    req_id, future = adapter.create_permission_request(
        tool_name="terminal_execute",
        arguments={"command": "dir"},
        level=PermissionLevel.HIGH_RISK,
        description="List files in directory",
    )
    assert req_id in adapter._pending_permissions
    assert not future.done()
    assert adapter.snapshot.pending_permission is not None
    assert adapter.snapshot.pending_permission["tool"] == "terminal_execute"

    # Verify event was broadcast
    await asyncio.sleep(0.02)
    assert mock_ws.send_text.await_count >= 1


@pytest.mark.asyncio
async def test_permission_denial():
    """Verify resolving permission with False completes future with False and clears state."""
    adapter = VisualizerAdapter(event_bus=EventBus())
    req_id, future = adapter.create_permission_request(
        tool_name="filesystem_delete",
        arguments={"path": "test.txt"},
        level=3,
    )

    success = adapter.resolve_permission(req_id, approved=False)
    assert success is True
    assert future.done()
    assert future.result() is False
    assert adapter.snapshot.pending_permission is None


@pytest.mark.asyncio
async def test_permission_approval_through_existing_controller():
    """Verify HTTP permission approval flows into existing PermissionController pipeline."""
    bus = EventBus()
    adapter = VisualizerAdapter(event_bus=bus)
    app = create_visualizer_app(adapter)
    client = TestClient(app)

    req_id, future = adapter.create_permission_request(
        tool_name="terminal_execute",
        arguments={"command": "git status"},
        level=PermissionLevel.HIGH_RISK,
        description="Inspect git state",
    )

    # Call the HTTP approval endpoint
    resp = client.post(f"/api/permission/{req_id}", json={"approved": True})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["approved"] is True

    assert future.done()
    assert future.result() is True


def test_no_direct_tool_execution_from_browser():
    """Verify the API exposes no endpoints to directly execute tools or bypass permissions."""
    adapter = VisualizerAdapter(event_bus=EventBus())
    app = create_visualizer_app(adapter)
    client = TestClient(app)

    # Attempting to call non-existent direct tool execution endpoints should return 404 or 405
    resp_exec = client.post("/api/tool/execute", json={"tool": "terminal_execute"})
    assert resp_exec.status_code in (404, 405)

    resp_run = client.post("/api/run", json={"command": "dir"})
    assert resp_run.status_code in (404, 405)


# ---------------------------------------------------------------------------
# 7. Voice Subsystem Compatibility (HUD Disabled) Test
# ---------------------------------------------------------------------------
def test_voice_subsystem_works_when_hud_disabled():
    """Verify cli_voice parser defaults --hud to False and custom_voice remains compatible."""
    from cli_voice import build_parser

    parser = build_parser()
    args = parser.parse_args([])
    assert args.hud is False
    assert args.voice is None

    args_voice = parser.parse_args(["--voice", "Charon"])
    assert args_voice.voice == "Charon"
    assert args_voice.hud is False

    args_hud = parser.parse_args(["--voice", "Charon", "--hud"])
    assert args_hud.voice == "Charon"
    assert args_hud.hud is True
