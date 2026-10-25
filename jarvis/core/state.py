"""Deterministic Agent State Machine for JARVIS."""

from enum import Enum
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.utils.logging import logger


class AgentState(str, Enum):
    """Discrete operational states of the JARVIS agent."""

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    WAITING_FOR_PERMISSION = "WAITING_FOR_PERMISSION"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class StateMachine:
    """Manages state transitions and emits change events."""

    # Explicit mapping of permitted target states from each source state
    _VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
        AgentState.IDLE: {
            AgentState.LISTENING,
            AgentState.THINKING,
            AgentState.RECONNECTING,
            AgentState.ERROR,
        },
        AgentState.LISTENING: {
            AgentState.THINKING,
            AgentState.IDLE,
            AgentState.INTERRUPTED,
            AgentState.CANCELLED,
            AgentState.RECONNECTING,
            AgentState.ERROR,
        },
        AgentState.THINKING: {
            AgentState.TOOL_EXECUTION,
            AgentState.WAITING_FOR_PERMISSION,
            AgentState.SPEAKING,
            AgentState.INTERRUPTED,
            AgentState.IDLE,
            AgentState.CANCELLED,
            AgentState.RECONNECTING,
            AgentState.ERROR,
        },
        AgentState.TOOL_EXECUTION: {
            AgentState.THINKING,
            AgentState.WAITING_FOR_PERMISSION,
            AgentState.SPEAKING,
            AgentState.INTERRUPTED,
            AgentState.IDLE,
            AgentState.CANCELLED,
            AgentState.RECONNECTING,
            AgentState.ERROR,
        },
        AgentState.WAITING_FOR_PERMISSION: {
            AgentState.TOOL_EXECUTION,
            AgentState.THINKING,
            AgentState.SPEAKING,
            AgentState.INTERRUPTED,
            AgentState.IDLE,
            AgentState.CANCELLED,
            AgentState.ERROR,
        },
        AgentState.SPEAKING: {
            AgentState.IDLE,
            AgentState.LISTENING,
            AgentState.THINKING,
            AgentState.TOOL_EXECUTION,
            AgentState.INTERRUPTED,
            AgentState.CANCELLED,
            AgentState.RECONNECTING,
            AgentState.ERROR,
        },
        AgentState.INTERRUPTED: {
            AgentState.LISTENING,
            AgentState.IDLE,
            AgentState.THINKING,
            AgentState.ERROR,
        },
        AgentState.RECONNECTING: {
            AgentState.IDLE,
            AgentState.LISTENING,
            AgentState.THINKING,
            AgentState.ERROR,
        },
        AgentState.ERROR: {
            AgentState.IDLE,
            AgentState.THINKING,
            AgentState.RECONNECTING,
        },
        AgentState.CANCELLED: {
            AgentState.IDLE,
            AgentState.LISTENING,
        },
    }

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._state = AgentState.IDLE
        self._event_bus = event_bus or default_event_bus

    @property
    def current_state(self) -> AgentState:
        """Get current state."""
        return self._state

    def is_idle(self) -> bool:
        return self._state == AgentState.IDLE

    def is_thinking(self) -> bool:
        return self._state == AgentState.THINKING

    async def transition_to(self, new_state: AgentState, reason: str = "") -> None:
        """Attempt to transition to a new state and emit transition event."""
        if new_state == self._state:
            return  # No-op on identical state

        valid_targets = self._VALID_TRANSITIONS.get(self._state, set())
        if new_state not in valid_targets:
            msg = f"Illegal transition from {self._state.value} to {new_state.value} (reason: {reason})"
            logger.warning(msg)
            # We record warning; for resilience, we enforce transitions unless it causes unrecoverable desync
            # But let's allow transition to ERROR from anywhere
            if new_state != AgentState.ERROR:
                raise InvalidStateTransitionError(msg)

        old_state = self._state
        self._state = new_state
        logger.debug(
            "State transition: %s -> %s%s",
            old_state.value,
            new_state.value,
            f" ({reason})" if reason else "",
        )

        await self._event_bus.emit(
            EventType.AGENT_STATE_CHANGED,
            {
                "old_state": old_state.value,
                "new_state": new_state.value,
                "reason": reason,
            },
        )
