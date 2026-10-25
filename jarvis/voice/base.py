"""Abstract interfaces and data contracts for the JARVIS Voice Subsystem."""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable


class VoiceEventType(str, Enum):
    """Event types specific to the voice interaction layer."""

    PTT_PRESSED = "voice.ptt_pressed"
    PTT_RELEASED = "voice.ptt_released"
    AUDIO_CHUNK_CAPTURED = "voice.audio_chunk_captured"
    AUDIO_CHUNK_RECEIVED = "voice.audio_chunk_received"
    SPEECH_STARTED = "voice.speech_started"
    SPEECH_ENDED = "voice.speech_ended"
    BARGE_IN_DETECTED = "voice.barge_in_detected"
    SESSION_CONNECTED = "voice.session_connected"
    SESSION_RECONNECTING = "voice.session_reconnecting"
    SESSION_CLOSED = "voice.session_closed"
    FALLBACK_TRIGGERED = "voice.fallback_triggered"


@dataclass
class VoiceConfig:
    """Configuration settings for voice input, output, and session."""

    input_sample_rate: int = 16000
    input_channels: int = 1
    input_chunk_size: int = 1024
    output_sample_rate: int = 24000
    output_channels: int = 1
    live_model: str = "models/gemini-3.1-flash-live-preview"
    prebuilt_voice: str = "Charon"  # Charon (default), Orus, Gacrux, Puck, Aoede
    ptt_hotkey: str = "ctrl+space"
    max_reconnect_attempts: int = 3
    reconnect_delay: float = 1.0


class AudioInput(ABC):
    """Abstract interface for audio capture from microphone or mock stream."""

    @abstractmethod
    def start_capture(self, callback: Callable[[bytes], None]) -> None:
        """Begin capturing audio and dispatch PCM chunks to callback."""
        pass

    @abstractmethod
    def stop_capture(self) -> None:
        """Halt audio capture."""
        pass

    @property
    @abstractmethod
    def is_capturing(self) -> bool:
        """Return whether audio capture is currently active."""
        pass

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Return capture sample rate in Hz (e.g. 16000)."""
        pass


class AudioOutput(ABC):
    """Abstract interface for audio playback with immediate interruption support."""

    @abstractmethod
    def play_chunk(self, pcm_data: bytes) -> None:
        """Queue or play a raw PCM audio chunk."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop all audio playback (barge-in cut-off)."""
        pass

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """Return whether audio is currently playing."""
        pass

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Return playback sample rate in Hz (e.g. 24000)."""
        pass

    @abstractmethod
    def wait_done(self, timeout: float | None = None) -> None:
        """Wait until active audio buffer has finished playing."""
        pass


class BaseTTS(ABC):
    """Abstract interface for pluggable text-to-speech fallback engines."""

    @abstractmethod
    async def speak(self, text: str) -> None:
        """Synthesize text and play through speakers."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Halt ongoing speech synthesis playback."""
        pass


class VoiceSession(ABC):
    """Abstract interface for bidirectional streaming voice sessions."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish bidirectional voice session connection."""
        pass

    @abstractmethod
    async def send_audio_chunk(self, pcm_data: bytes) -> None:
        """Stream an input audio chunk to the voice model."""
        pass

    @abstractmethod
    async def end_turn(self) -> None:
        """Signal that the user has completed their spoken turn."""
        pass

    @abstractmethod
    async def send_tool_response(self, tool_call_id: str, tool_name: str, response: dict[str, Any]) -> None:
        """Transmit synchronous tool execution result back to the session."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Gracefully terminate the voice session."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if session WebSocket is currently open and healthy."""
        pass
