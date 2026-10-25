"""Text-to-Speech (TTS) fallback providers for JARVIS."""

import asyncio
import threading
from typing import Any

from jarvis.utils.logging import logger
from jarvis.voice.base import BaseTTS

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except Exception:
    PYTTSX3_AVAILABLE = False


class Pyttsx3TTS(BaseTTS):
    """Local offline TTS provider using pyttsx3 (SAPI5 on Windows)."""

    def __init__(self, voice_name: str | None = None, rate: int = 190) -> None:
        self.voice_name = voice_name
        self.rate = rate
        self._engine: Any = None
        self._is_speaking = False
        self._lock = threading.Lock()
        self._init_engine()

    def _init_engine(self) -> None:
        """Initialize the local pyttsx3 engine."""
        if not PYTTSX3_AVAILABLE:
            return
        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self.rate)
            if self.voice_name:
                voices = self._engine.getProperty("voices")
                for v in voices:
                    if self.voice_name.lower() in v.name.lower():
                        self._engine.setProperty("voice", v.id)
                        break
        except Exception as ex:
            logger.warning("Failed to initialize pyttsx3: %s", ex)

    async def speak(self, text: str) -> None:
        """Synthesize and speak text asynchronously without blocking the event loop."""
        if not text or not PYTTSX3_AVAILABLE:
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_speak, text)

    def _sync_speak(self, text: str) -> None:
        """Synchronous speech execution inside thread executor."""
        with self._lock:
            self._is_speaking = True
            try:
                # Re-initialize engine if needed for thread safety
                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate)
                engine.say(text)
                engine.runAndWait()
            except Exception as ex:
                logger.debug("pyttsx3 speech error: %s", ex)
            finally:
                self._is_speaking = False

    def stop(self) -> None:
        """Immediately stop speech playback."""
        with self._lock:
            if self._engine and self._is_speaking:
                try:
                    self._engine.stop()
                except Exception as ex:
                    logger.debug("Error stopping pyttsx3: %s", ex)
            self._is_speaking = False


class MockTTS(BaseTTS):
    """In-memory mock TTS for tests."""

    def __init__(self) -> None:
        self.spoken_texts: list[str] = []
        self._is_speaking = False

    async def speak(self, text: str) -> None:
        self.spoken_texts.append(text)

    def stop(self) -> None:
        self._is_speaking = False
