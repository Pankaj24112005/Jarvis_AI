"""Unified Voice Interaction Loop implementing Hybrid Dual-Engine Voice Architecture."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from jarvis.config import Settings, get_settings
if TYPE_CHECKING:
    from jarvis.core.agent import JarvisAgent
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.memory import MemoryManager, default_memory_manager
from jarvis.utils.logging import logger
from jarvis.voice.audio_io import (
    AudioInput,
    AudioOutput,
    PygameAudioInput,
    PygameAudioOutput,
)
from jarvis.voice.base import BaseTTS, VoiceConfig, VoiceSession
from jarvis.voice.live_session import GeminiLiveVoiceSession
from jarvis.voice.ptt import PTTController
from jarvis.voice.tts import Pyttsx3TTS


class VoiceLoop:
    """Coordinates Push-to-Talk, audio capture, streaming Live session, and TTS fallback."""

    def __init__(
        self,
        agent: JarvisAgent,
        audio_input: AudioInput | None = None,
        audio_output: AudioOutput | None = None,
        voice_session: VoiceSession | None = None,
        fallback_tts: BaseTTS | None = None,
        config: VoiceConfig | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.agent = agent
        self.settings = settings or get_settings()
        self.config = config or VoiceConfig()
        self.event_bus = agent.event_bus or default_event_bus
        self.state_machine = agent.state_machine

        # Pluggable audio I/O and TTS
        self.audio_input = audio_input or PygameAudioInput(sample_rate=self.config.input_sample_rate)
        self.audio_output = audio_output or PygameAudioOutput(sample_rate=self.config.output_sample_rate)
        self.fallback_tts = fallback_tts or Pyttsx3TTS()

        # Primary Live Voice Session
        api_key = self.settings.gemini_api_key.get_secret_value()
        self.voice_session = voice_session or GeminiLiveVoiceSession(
            api_key=api_key,
            config=self.config,
            tool_registry=self.agent.tool_registry,
            permission_controller=self.agent.permission_controller,
            memory_manager=self.agent.memory_manager,
            state_machine=self.state_machine,
            event_bus=self.event_bus,
            settings=self.settings,
        )

        self.ptt = PTTController(
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
        )

        self.is_running = False
        self.use_fallback_mode = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ptt_lock: asyncio.Lock | None = None

    async def _get_ptt_lock(self) -> asyncio.Lock:
        if self._ptt_lock is None:
            self._ptt_lock = asyncio.Lock()
        return self._ptt_lock

    async def start(self) -> None:
        """Initialize audio components, establish live voice session, and start PTT listener."""
        self._loop = asyncio.get_running_loop()
        self._ptt_lock = asyncio.Lock()
        self.is_running = True

        logger.info("Initializing Voice Subsystem (Hybrid Dual-Engine)...")

        # Connect Live session
        if isinstance(self.voice_session, GeminiLiveVoiceSession):
            self.voice_session.set_callbacks(
                on_audio_chunk=self._on_live_audio_chunk,
                on_interrupted=self._on_live_interrupted,
                on_turn_complete=self._on_live_turn_complete,
            )

        try:
            await self.voice_session.connect()
            self.use_fallback_mode = False
            logger.info("Voice Subsystem operating in PRIMARY Mode (Gemini Live API).")
        except Exception as ex:
            logger.warning("Failed to connect to Live session: %s. Engaging FALLBACK Engine.", ex)
            self.use_fallback_mode = True
            await self.event_bus.emit(EventType.FALLBACK_TRIGGERED if hasattr(EventType, "FALLBACK_TRIGGERED") else "voice.fallback", {})

        # Start PTT listener
        self.ptt.start_hotkey_listener()

    def _on_ptt_press(self) -> None:
        """Called when PTT is pressed."""
        if not self.is_running:
            return

        # 1. Immediate barge-in if JARVIS is currently speaking
        if self.audio_output.is_playing:
            self.audio_output.stop()
            logger.debug("Barge-in triggered by PTT press. Halting audio output.")

        # 2. Begin capturing microphone audio immediately so no speech is clipped
        self.audio_input.start_capture(callback=self._on_captured_chunk)

        # 3. Schedule async state transitions with proper interruption semantics
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._handle_ptt_press_async(), self._loop)

    async def _handle_ptt_press_async(self) -> None:
        """Execute state transitions for PTT press with proper interruption/barge-in semantics."""
        lock = await self._get_ptt_lock()
        async with lock:
            if self.state_machine:
                curr_state = self.state_machine.current_state

                # Check if barge-in / interruption is required
                if curr_state in (
                    AgentState.SPEAKING,
                    AgentState.THINKING,
                    AgentState.TOOL_EXECUTION,
                    AgentState.WAITING_FOR_PERMISSION,
                ):
                    logger.info(
                        "Barge-in / interruption from state %s triggered by PTT press.",
                        curr_state.value,
                    )
                    await self.state_machine.transition_to(
                        AgentState.INTERRUPTED,
                        reason=f"PTT pressed during {curr_state.value}",
                    )
                    await self.event_bus.emit(
                        EventType.VOICE_INTERRUPTED,
                        {"interrupted_state": curr_state.value},
                    )
                    if hasattr(self.voice_session, "interrupt"):
                        fn = getattr(self.voice_session, "interrupt")
                        if callable(fn):
                            res = fn()
                            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                                await res

                elif curr_state not in (AgentState.IDLE, AgentState.INTERRUPTED, AgentState.LISTENING):
                    await self.state_machine.transition_to(
                        AgentState.IDLE,
                        reason="Reset before PTT",
                    )

                # Enter LISTENING state if not already in LISTENING
                if self.state_machine.current_state != AgentState.LISTENING:
                    await self.state_machine.transition_to(
                        AgentState.LISTENING,
                        reason="PTT pressed",
                    )

                # Ensure Live session is connected for this turn (reconnecting with resumption if needed)
                if hasattr(self.voice_session, "is_connected") and not self.voice_session.is_connected:
                    if hasattr(self.voice_session, "connect"):
                        fn = getattr(self.voice_session, "connect")
                        if callable(fn):
                            try:
                                res = fn()
                                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                                    await res
                            except Exception as ex:
                                logger.warning("Failed to connect live session for PTT turn: %s", ex)

            await self.event_bus.emit(EventType.VOICE_SPEECH_STARTED, {})

    def _on_ptt_release(self) -> None:
        """Called when PTT is released."""
        if not self.is_running:
            return

        # 1. Halt microphone capture
        self.audio_input.stop_capture()

        # 2. Schedule release async handler
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._handle_ptt_release_async(), self._loop)

    async def _handle_ptt_release_async(self) -> None:
        """Execute state transitions for PTT release and finalize user turn."""
        lock = await self._get_ptt_lock()
        async with lock:
            if self.state_machine and self.state_machine.current_state == AgentState.LISTENING:
                await self.state_machine.transition_to(
                    AgentState.THINKING,
                    reason="PTT released",
                )
            await self.event_bus.emit(EventType.VOICE_SPEECH_ENDED, {})
            if self.voice_session:
                await self.voice_session.end_turn()

    def _on_captured_chunk(self, chunk: bytes) -> None:
        """Receive microphone PCM chunk and stream to Live session."""
        if self.is_running and self._loop and not self.use_fallback_mode:
            asyncio.run_coroutine_threadsafe(
                self.voice_session.send_audio_chunk(chunk),
                self._loop,
            )

    def _on_live_audio_chunk(self, chunk: bytes) -> None:
        """Queue incoming 24kHz audio chunk for speaker playback."""
        if self.is_running:
            if self.state_machine and self.state_machine.current_state in (
                AgentState.LISTENING,
                AgentState.INTERRUPTED,
            ):
                return
            self.audio_output.play_chunk(chunk)

    def _on_live_interrupted(self) -> None:
        """Halt speaker output immediately upon server-detected barge-in."""
        self.audio_output.stop()
        logger.info("Speaker playback stopped on Live barge-in signal.")

    def _on_live_turn_complete(self, transcript: str) -> None:
        """Log turn completion."""
        logger.debug("Live voice turn completed. Response: %s", transcript[:100])

    async def speak_fallback(self, text: str) -> None:
        """Speak response using the pluggable offline TTS fallback."""
        if self.state_machine:
            if self.state_machine.current_state == AgentState.IDLE:
                await self.state_machine.transition_to(AgentState.THINKING, reason="Preparing TTS response")
            await self.state_machine.transition_to(AgentState.SPEAKING, reason="Fallback TTS speaking")

        await self.fallback_tts.speak(text)

        if self.state_machine:
            await self.state_machine.transition_to(AgentState.IDLE, reason="Fallback TTS finished")

    async def stop(self) -> None:
        """Clean shutdown of all voice components."""
        self.is_running = False
        self.ptt.stop_hotkey_listener()
        self.audio_input.stop_capture()
        self.audio_output.stop()
        self.fallback_tts.stop()

        if self.voice_session:
            res = self.voice_session.close()
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                await res

        logger.info("Voice Subsystem terminated cleanly.")
