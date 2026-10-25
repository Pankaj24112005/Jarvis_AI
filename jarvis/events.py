"""Asynchronous Event Bus for decoupled communication in JARVIS."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine
from jarvis.utils.logging import logger


class EventType(str, Enum):
    """Enumeration of standardized system events."""

    AGENT_STATE_CHANGED = "agent.state_changed"
    USER_MESSAGE = "user.message"
    AI_THINKING = "ai.thinking"
    AI_RESPONSE_CHUNK = "ai.response_chunk"
    AI_RESPONSE_COMPLETED = "ai.response_completed"
    TOOL_REQUESTED = "tool.requested"
    TOOL_EXECUTED = "tool.executed"
    TOOL_FAILED = "tool.failed"
    PERMISSION_REQUESTED = "permission.requested"
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_DENIED = "permission.denied"
    VOICE_SPEECH_STARTED = "voice.speech_started"
    VOICE_SPEECH_ENDED = "voice.speech_ended"
    VOICE_AUDIO_CHUNK = "voice.audio_chunk"
    VOICE_INTERRUPTED = "voice.interrupted"
    VOICE_RECONNECTING = "voice.reconnecting"
    VOICE_PLAYBACK_STARTED = "voice.playback_started"
    VOICE_PLAYBACK_FINISHED = "voice.playback_finished"
    GESTURE_DETECTED = "gesture.detected"
    ERROR_OCCURRED = "system.error"

    # Phase 7: Screen Perception & Computer Control Telemetry
    SCREEN_CAPTURE_STARTED = "screen.capture_started"
    SCREEN_CAPTURE_FINISHED = "screen.capture_finished"
    VISION_ANALYSIS_STARTED = "vision.analysis_started"
    VISION_ANALYSIS_FINISHED = "vision.analysis_finished"
    COMPUTER_ACTION_REQUESTED = "computer.action_requested"
    COMPUTER_ACTION_EXECUTED = "computer.action_executed"
    COMPUTER_ACTION_VERIFIED = "computer.action_verified"
    COMPUTER_ACTION_FAILED = "computer.action_failed"

    # Phase 8: Task & Workflow Intelligence Telemetry
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_STATUS_CHANGED = "task.status_changed"
    TASK_STEP_STARTED = "task.step_started"
    TASK_STEP_COMPLETED = "task.step_completed"
    TASK_STEP_FAILED = "task.step_failed"
    TASK_STEP_RETRYING = "task.step_retrying"
    TASK_RECOVERY_STARTED = "task.recovery_started"
    TASK_RECOVERY_EXHAUSTED = "task.recovery_exhausted"
    TASK_ANTI_LOOP_TRIGGERED = "task.anti_loop_triggered"
    TASK_WAITING_PERMISSION = "task.waiting_permission"
    TASK_PERMISSION_GRANTED = "task.permission_granted"
    TASK_PERMISSION_DENIED = "task.permission_denied"
    TASK_VERIFYING = "task.verifying"
    TASK_STEP_VERIFIED = "task.step_verified"
    TASK_STEP_VERIFICATION_FAILED = "task.step_verification_failed"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"
    TASK_CANCEL_REQUESTED = "task.cancel_requested"
    TASK_CANCELLED = "task.cancelled"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"


@dataclass
class Event:
    """Represents a discrete event dispatched through the event bus."""

    type: EventType | str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


EventHandler = Callable[[Event], Coroutine[Any, Any, None] | None]


class EventBus:
    """Asynchronous Pub/Sub event bus."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType | str, handler: EventHandler) -> None:
        """Subscribe a synchronous or asynchronous handler to an event type."""
        key = str(event_type.value if isinstance(event_type, EventType) else event_type)
        if key not in self._subscribers:
            self._subscribers[key] = []
        if handler not in self._subscribers[key]:
            self._subscribers[key].append(handler)

    def unsubscribe(self, event_type: EventType | str, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type."""
        key = str(event_type.value if isinstance(event_type, EventType) else event_type)
        if key in self._subscribers and handler in self._subscribers[key]:
            self._subscribers[key].remove(handler)

    async def emit(self, event_type: EventType | str, data: dict[str, Any] | None = None) -> Event:
        """Dispatch an event to all registered subscribers asynchronously."""
        key = str(event_type.value if isinstance(event_type, EventType) else event_type)
        event = Event(type=key, data=data or {})

        handlers = list(self._subscribers.get(key, []))
        # Also notify wildcard subscribers if any
        wildcard_handlers = list(self._subscribers.get("*", []))
        all_handlers = handlers + wildcard_handlers

        for handler in all_handlers:
            try:
                res = handler(event)
                if asyncio.iscoroutine(res):
                    # Schedule as background task or await
                    asyncio.create_task(self._safe_await(res, key))
            except Exception as ex:
                logger.error(f"Error in synchronous handler for event {key}: {ex}", exc_info=True)

        return event

    async def _safe_await(self, coro: Coroutine[Any, Any, None], event_key: str) -> None:
        try:
            await coro
        except Exception as ex:
            logger.error(f"Error in async handler for event {event_key}: {ex}", exc_info=True)


# Global default event bus instance
default_event_bus = EventBus()
