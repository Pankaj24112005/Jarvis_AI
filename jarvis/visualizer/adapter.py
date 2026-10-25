"""EventBus adapter converting internal JARVIS events into sanitized visual telemetry."""

import asyncio
import time
import uuid
from typing import Any
from fastapi import WebSocket

from jarvis.core.state import AgentState, StateMachine
from jarvis.events import Event, EventBus, EventType, default_event_bus
from jarvis.security.permissions import PermissionLevel
from jarvis.utils.logging import logger
from jarvis.visualizer.base import (
    TelemetryFrame,
    TelemetryFrameType,
    VisualizerSnapshot,
    sanitize_telemetry_data,
)


class VisualizerAdapter:
    """Translates EventBus events into real-time telemetry frames for WebSocket clients."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
        voice_name: str = "Charon",
    ) -> None:
        self.event_bus = event_bus or default_event_bus
        self.state_machine = state_machine
        self.voice_name = voice_name

        self._snapshot = VisualizerSnapshot(
            agent_state=self.state_machine.current_state.value if self.state_machine else "IDLE",
            voice_name=self.voice_name,
        )

        self._clients: set[WebSocket] = set()
        self._clients_lock = asyncio.Lock()
        self._pending_permissions: dict[str, asyncio.Future[bool]] = {}
        self._last_audio_broadcast_time: float = 0.0
        self._audio_broadcast_interval: float = 0.033  # ~30 Hz maximum rate for audio pulses
        self._is_subscribed = False

        self._subscribe_events()

    @property
    def snapshot(self) -> VisualizerSnapshot:
        """Return the current visual state snapshot."""
        return self._snapshot

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def _subscribe_events(self) -> None:
        """Register handlers on the existing EventBus for known system events."""
        if self._is_subscribed:
            return

        self.event_bus.subscribe(EventType.AGENT_STATE_CHANGED, self._on_agent_state_changed)
        self.event_bus.subscribe(EventType.VOICE_SPEECH_STARTED, self._on_voice_speech_started)
        self.event_bus.subscribe(EventType.VOICE_SPEECH_ENDED, self._on_voice_speech_ended)
        self.event_bus.subscribe(EventType.VOICE_AUDIO_CHUNK, self._on_voice_audio_chunk)
        self.event_bus.subscribe(EventType.VOICE_INTERRUPTED, self._on_voice_interrupted)
        self.event_bus.subscribe(EventType.VOICE_RECONNECTING, self._on_voice_reconnecting)
        self.event_bus.subscribe(EventType.VOICE_PLAYBACK_STARTED, self._on_voice_playback_started)
        self.event_bus.subscribe(EventType.VOICE_PLAYBACK_FINISHED, self._on_voice_playback_finished)
        self.event_bus.subscribe(EventType.TOOL_REQUESTED, self._on_tool_requested)
        self.event_bus.subscribe(EventType.TOOL_EXECUTED, self._on_tool_executed)
        self.event_bus.subscribe(EventType.TOOL_FAILED, self._on_tool_failed)
        self.event_bus.subscribe(EventType.PERMISSION_REQUESTED, self._on_permission_requested)
        self.event_bus.subscribe(EventType.PERMISSION_GRANTED, self._on_permission_granted)
        self.event_bus.subscribe(EventType.PERMISSION_DENIED, self._on_permission_denied)
        self.event_bus.subscribe(EventType.ERROR_OCCURRED, self._on_error_occurred)

        # Phase 7: Screen perception & computer interaction telemetry
        self.event_bus.subscribe(EventType.SCREEN_CAPTURE_STARTED, self._on_computer_activity)
        self.event_bus.subscribe(EventType.SCREEN_CAPTURE_FINISHED, self._on_computer_activity)
        self.event_bus.subscribe(EventType.VISION_ANALYSIS_STARTED, self._on_computer_activity)
        self.event_bus.subscribe(EventType.VISION_ANALYSIS_FINISHED, self._on_computer_activity)
        self.event_bus.subscribe(EventType.COMPUTER_ACTION_REQUESTED, self._on_computer_activity)
        self.event_bus.subscribe(EventType.COMPUTER_ACTION_EXECUTED, self._on_computer_activity)
        self.event_bus.subscribe(EventType.COMPUTER_ACTION_VERIFIED, self._on_computer_activity)
        self.event_bus.subscribe(EventType.COMPUTER_ACTION_FAILED, self._on_computer_activity)

        self._is_subscribed = True
        logger.debug("VisualizerAdapter successfully subscribed to EventBus.")

    async def register_client(self, websocket: WebSocket) -> None:
        """Register a newly connected WebSocket client and send immediate snapshot."""
        async with self._clients_lock:
            self._clients.add(websocket)
            self._snapshot.connected_clients_count = len(self._clients)

        # Send initial snapshot frame
        initial_frame = TelemetryFrame(
            type=TelemetryFrameType.SNAPSHOT,
            data=self._snapshot.to_dict(),
        )
        try:
            await websocket.send_text(initial_frame.to_json())
        except Exception as ex:
            logger.debug("Failed to send initial snapshot to WebSocket client: %s", ex)
            await self.unregister_client(websocket)

    async def unregister_client(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket client cleanly."""
        async with self._clients_lock:
            if websocket in self._clients:
                self._clients.remove(websocket)
                self._snapshot.connected_clients_count = len(self._clients)

    async def broadcast(self, frame: TelemetryFrame) -> None:
        """Broadcast a telemetry frame to all active WebSocket clients."""
        if not self._clients:
            return

        payload = frame.to_json()
        dead_clients: list[WebSocket] = []

        async with self._clients_lock:
            clients_snapshot = list(self._clients)

        for ws in clients_snapshot:
            try:
                await ws.send_text(payload)
            except Exception:
                dead_clients.append(ws)

        if dead_clients:
            async with self._clients_lock:
                for ws in dead_clients:
                    self._clients.discard(ws)
                self._snapshot.connected_clients_count = len(self._clients)

    def _safe_schedule_broadcast(self, frame: TelemetryFrame) -> None:
        """Schedule WebSocket broadcast asynchronously if an event loop is active."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(frame))
        except RuntimeError:
            pass

    # -------------------------------------------------------------------------
    # Synchronous Event Handlers translating EventBus -> Visualizer Telemetry
    # -------------------------------------------------------------------------

    def _on_agent_state_changed(self, event: Event) -> None:
        new_state = str(event.data.get("new_state", "IDLE"))
        old_state = str(event.data.get("old_state", "IDLE"))
        reason = str(event.data.get("reason", ""))

        self._snapshot.agent_state = new_state
        self._snapshot.timestamp = time.time()

        if new_state == "IDLE":
            self._snapshot.active_tool_status = None
            self._snapshot.audio_energy = 0.0
            self._snapshot.is_speaking = False

        frame = TelemetryFrame(
            type=TelemetryFrameType.STATE_CHANGE,
            data={
                "old_state": old_state,
                "new_state": new_state,
                "reason": reason,
            },
        )
        self._safe_schedule_broadcast(frame)

    def _on_voice_speech_started(self, event: Event) -> None:
        self._snapshot.ptt_pressed = True
        self._snapshot.audio_energy = 0.65
        frame = TelemetryFrame(
            type=TelemetryFrameType.SPEECH_ACTIVITY,
            data={"ptt_pressed": True, "event": "speech_started"},
        )
        self._safe_schedule_broadcast(frame)

    def _on_voice_speech_ended(self, event: Event) -> None:
        self._snapshot.ptt_pressed = False
        frame = TelemetryFrame(
            type=TelemetryFrameType.SPEECH_ACTIVITY,
            data={"ptt_pressed": False, "event": "speech_ended"},
        )
        self._safe_schedule_broadcast(frame)

    def _on_voice_audio_chunk(self, event: Event) -> None:
        """Handle ephemeral audio chunk notifications with throttling (never persists audio)."""
        now = time.time()
        if now - self._last_audio_broadcast_time < self._audio_broadcast_interval:
            return

        self._last_audio_broadcast_time = now
        chunk_size = event.data.get("size", 1024)
        energy = min(1.0, max(0.15, (chunk_size / 2048.0) * 0.8))
        self._snapshot.audio_energy = energy

        frame = TelemetryFrame(
            type=TelemetryFrameType.AUDIO_ENERGY,
            data={"energy": energy, "size": chunk_size},
        )
        self._safe_schedule_broadcast(frame)

    def _on_voice_interrupted(self, event: Event) -> None:
        self._snapshot.audio_energy = 0.0
        self._snapshot.is_speaking = False
        interrupted_state = event.data.get("interrupted_state", "SPEAKING")
        frame = TelemetryFrame(
            type=TelemetryFrameType.STATE_CHANGE,
            data={"new_state": "INTERRUPTED", "interrupted_state": interrupted_state},
        )
        self._safe_schedule_broadcast(frame)

    def _on_voice_reconnecting(self, event: Event) -> None:
        reason = event.data.get("reason", "Connection lost")
        attempt = event.data.get("attempt", 1)
        frame = TelemetryFrame(
            type=TelemetryFrameType.STATE_CHANGE,
            data={"new_state": "RECONNECTING", "reason": reason, "attempt": attempt},
        )
        self._safe_schedule_broadcast(frame)

    def _on_voice_playback_started(self, event: Event) -> None:
        self._snapshot.is_speaking = True
        self._snapshot.audio_energy = 0.8
        frame = TelemetryFrame(
            type=TelemetryFrameType.SPEECH_ACTIVITY,
            data={"is_speaking": True},
        )
        self._safe_schedule_broadcast(frame)

    def _on_voice_playback_finished(self, event: Event) -> None:
        self._snapshot.is_speaking = False
        self._snapshot.audio_energy = 0.0
        frame = TelemetryFrame(
            type=TelemetryFrameType.SPEECH_ACTIVITY,
            data={"is_speaking": False},
        )
        self._safe_schedule_broadcast(frame)

    def _on_tool_requested(self, event: Event) -> None:
        tool_name = event.data.get("tool", "unknown_tool")
        args = event.data.get("arguments", {})
        self._snapshot.active_tool = tool_name
        self._snapshot.active_tool_args = sanitize_telemetry_data(args)
        self._snapshot.active_tool_status = "REQUESTED"
        self._snapshot.active_tool_error = None

        frame = TelemetryFrame(
            type=TelemetryFrameType.TOOL_ACTIVITY,
            data={
                "tool": tool_name,
                "status": "REQUESTED",
                "arguments": self._snapshot.active_tool_args,
            },
        )
        self._safe_schedule_broadcast(frame)

    def _on_tool_executed(self, event: Event) -> None:
        tool_name = event.data.get("tool", "unknown_tool")
        self._snapshot.active_tool = tool_name
        self._snapshot.active_tool_status = "EXECUTED"
        self._snapshot.active_tool_error = None

        frame = TelemetryFrame(
            type=TelemetryFrameType.TOOL_ACTIVITY,
            data={"tool": tool_name, "status": "EXECUTED"},
        )
        self._safe_schedule_broadcast(frame)

    def _on_tool_failed(self, event: Event) -> None:
        tool_name = event.data.get("tool", "unknown_tool")
        error_msg = str(event.data.get("error", "Execution failed"))
        self._snapshot.active_tool = tool_name
        self._snapshot.active_tool_status = "FAILED"
        self._snapshot.active_tool_error = error_msg

        frame = TelemetryFrame(
            type=TelemetryFrameType.TOOL_ACTIVITY,
            data={"tool": tool_name, "status": "FAILED", "error": error_msg},
        )
        self._safe_schedule_broadcast(frame)

    def _on_permission_requested(self, event: Event) -> None:
        tool_name = event.data.get("tool", "")
        level = event.data.get("level", 3)
        args = event.data.get("arguments", {})
        req_id = event.data.get("request_id") or str(uuid.uuid4())

        alert_data = {
            "request_id": req_id,
            "tool": tool_name,
            "level": level,
            "arguments": sanitize_telemetry_data(args),
            "description": event.data.get("description", f"Authorization required for {tool_name}"),
        }
        self._snapshot.pending_permission = alert_data

        frame = TelemetryFrame(
            type=TelemetryFrameType.PERMISSION_ALERT,
            data=alert_data,
        )
        self._safe_schedule_broadcast(frame)

    def _on_permission_granted(self, event: Event) -> None:
        self._snapshot.pending_permission = None
        tool_name = event.data.get("tool", "")
        frame = TelemetryFrame(
            type=TelemetryFrameType.PERMISSION_ALERT,
            data={"status": "GRANTED", "tool": tool_name},
        )
        self._safe_schedule_broadcast(frame)

    def _on_permission_denied(self, event: Event) -> None:
        self._snapshot.pending_permission = None
        tool_name = event.data.get("tool", "")
        frame = TelemetryFrame(
            type=TelemetryFrameType.PERMISSION_ALERT,
            data={"status": "DENIED", "tool": tool_name},
        )
        self._safe_schedule_broadcast(frame)

    def _on_error_occurred(self, event: Event) -> None:
        err = str(event.data.get("error", "Unknown system error"))
        self._snapshot.last_error = err
        frame = TelemetryFrame(
            type=TelemetryFrameType.SYSTEM_ERROR,
            data={"error": err},
        )
        self._safe_schedule_broadcast(frame)

    def _on_computer_activity(self, event: Event) -> None:
        event_name = event.type.value if hasattr(event.type, "value") else str(event.type)
        sanitized_data = sanitize_telemetry_data(event.data)
        frame = TelemetryFrame(
            type=TelemetryFrameType.COMPUTER_ACTIVITY,
            data={"activity": event_name, **sanitized_data},
        )
        self._safe_schedule_broadcast(frame)

    # -------------------------------------------------------------------------
    # Safe Interactive Permission Bridge (HUD -> PermissionController)
    # -------------------------------------------------------------------------

    def create_permission_request(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        level: PermissionLevel | int,
        description: str = "",
    ) -> tuple[str, asyncio.Future[bool]]:
        """Create a pending permission future for interactive resolution."""
        req_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending_permissions[req_id] = future

        alert_data = {
            "request_id": req_id,
            "tool": tool_name,
            "level": int(level),
            "arguments": sanitize_telemetry_data(arguments),
            "description": description or f"Authorization required for {tool_name}",
        }
        self._snapshot.pending_permission = alert_data

        frame = TelemetryFrame(
            type=TelemetryFrameType.PERMISSION_ALERT,
            data=alert_data,
        )
        self._safe_schedule_broadcast(frame)
        return req_id, future

    def resolve_permission(self, request_id: str, approved: bool) -> bool:
        """Resolve a pending permission request with human authorization decision."""
        future = self._pending_permissions.pop(request_id, None)
        if future and not future.done():
            future.set_result(approved)
            self._snapshot.pending_permission = None
            logger.info("Resolved permission request %s -> approved=%s", request_id, approved)
            return True
        return False
