"""Base schemas, telemetry frames, and sanitization for JARVIS Visualizer."""

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from jarvis.memory.security import contains_secrets, redact_secrets


class TelemetryFrameType(str, Enum):
    """Types of telemetry packets broadcast over the WebSocket stream."""

    SNAPSHOT = "snapshot"
    STATE_CHANGE = "state_change"
    AUDIO_ENERGY = "audio_energy"
    SPEECH_ACTIVITY = "speech_activity"
    TOOL_ACTIVITY = "tool_activity"
    PERMISSION_ALERT = "permission_alert"
    SYSTEM_ERROR = "system_error"
    COMPUTER_ACTIVITY = "computer_activity"


def sanitize_telemetry_data(data: Any) -> Any:
    """Recursively redact secrets and sanitize values for safe JSON transmission."""
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in ["key", "pass", "secret", "token", "auth", "cred"]):
                sanitized[str(k)] = "[REDACTED]"
            else:
                sanitized[str(k)] = sanitize_telemetry_data(v)
        return sanitized
    elif isinstance(data, (list, tuple, set)):
        return [sanitize_telemetry_data(item) for item in data]
    elif isinstance(data, str):
        return redact_secrets(data)
    elif isinstance(data, (int, float, bool)) or data is None:
        return data
    else:
        # Fallback to string conversion with redaction
        return redact_secrets(str(data))


@dataclass
class VisualizerSnapshot:
    """Consolidated state snapshot representing the entire visual status of JARVIS."""

    agent_state: str = "IDLE"
    ptt_pressed: bool = False
    is_speaking: bool = False
    audio_energy: float = 0.0
    voice_name: str = "Charon"
    active_tool: str | None = None
    active_tool_args: dict[str, Any] = field(default_factory=dict)
    active_tool_level: int | None = None
    active_tool_status: str | None = None  # "REQUESTED", "EXECUTED", "FAILED"
    active_tool_error: str | None = None
    active_tool_duration_ms: float = 0.0
    pending_permission: dict[str, Any] | None = None
    last_transcript: str = ""
    last_error: str | None = None
    connected_clients_count: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        return sanitize_telemetry_data(raw)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class TelemetryFrame:
    """Atomic telemetry packet emitted to connected WebSockets."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": str(self.type.value if hasattr(self.type, "value") else self.type),
            "data": sanitize_telemetry_data(self.data),
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)
