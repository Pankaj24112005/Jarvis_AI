"""JARVIS Voice Subsystem: Hybrid Dual-Engine Voice Architecture with Gemini Live."""

from jarvis.voice.audio_io import (
    AudioInput,
    AudioOutput,
    MockAudioInput,
    MockAudioOutput,
    PygameAudioInput,
    PygameAudioOutput,
    calculate_pcm_duration,
)
from jarvis.voice.base import BaseTTS, VoiceConfig, VoiceEventType, VoiceSession
from jarvis.voice.live_session import GeminiLiveVoiceSession, LiveSessionState, SessionState
from jarvis.voice.loop import VoiceLoop
from jarvis.voice.ptt import PTTController
from jarvis.voice.tts import MockTTS, Pyttsx3TTS
from jarvis.voice.music import (
    MusicGenerator,
    GoogleLiveMusicGenerator,
    SingingCapabilityHandler,
    MusicControlTool,
)

__all__ = [
    "AudioInput",
    "AudioOutput",
    "BaseTTS",
    "VoiceConfig",
    "VoiceSession",
    "VoiceEventType",
    "PygameAudioInput",
    "PygameAudioOutput",
    "MockAudioInput",
    "MockAudioOutput",
    "calculate_pcm_duration",
    "Pyttsx3TTS",
    "MockTTS",
    "GeminiLiveVoiceSession",
    "SessionState",
    "LiveSessionState",
    "PTTController",
    "VoiceLoop",
    "MusicGenerator",
    "GoogleLiveMusicGenerator",
    "SingingCapabilityHandler",
    "MusicControlTool",
]
