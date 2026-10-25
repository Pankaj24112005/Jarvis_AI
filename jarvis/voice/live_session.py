"""Gemini Multimodal Live API Voice Session with native tool routing and barge-in."""

import asyncio
from enum import Enum
from typing import Any, Callable, Coroutine
from google import genai
from google.genai import types

from jarvis.config import Settings, get_settings
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.memory import MemoryManager, default_memory_manager
from jarvis.security.permissions import (
    PermissionController,
    PermissionLevel,
    default_permission_controller,
)
from jarvis.tools.base import ToolResult
from jarvis.tools.registry import ToolRegistry, default_tool_registry
from jarvis.utils.logging import logger
from jarvis.voice.base import VoiceConfig, VoiceSession


class SessionState(str, Enum):
    """Explicit lifecycle states of the Live WebSocket session."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


LiveSessionState = SessionState


class GeminiLiveVoiceSession(VoiceSession):
    """Bidirectional streaming live session with Gemini over WebSockets."""

    def __init__(
        self,
        api_key: str,
        config: VoiceConfig | None = None,
        tool_registry: ToolRegistry | None = None,
        permission_controller: PermissionController | None = None,
        memory_manager: MemoryManager | None = None,
        state_machine: StateMachine | None = None,
        event_bus: EventBus | None = None,
        settings: Settings | None = None,
        on_audio_chunk: Callable[[bytes], None] | None = None,
        on_interrupted: Callable[[], None] | None = None,
        on_turn_complete: Callable[[str], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.voice_config = config or VoiceConfig()
        self.tool_registry = tool_registry or default_tool_registry
        self.permission_controller = permission_controller or default_permission_controller
        self.memory_manager = memory_manager or default_memory_manager
        self.state_machine = state_machine
        self.event_bus = event_bus or default_event_bus
        self.settings = settings or get_settings()

        self._client = genai.Client(api_key=self.api_key)
        self._session_ctx: Any = None
        self._session: Any = None
        self._session_state = SessionState.DISCONNECTED
        self._resumption_handle: str | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._reconnect_lock = asyncio.Lock()

        self._on_audio_chunk = on_audio_chunk
        self._on_interrupted = on_interrupted
        self._on_turn_complete = on_turn_complete
        self._current_model_text = ""

    @property
    def is_connected(self) -> bool:
        return self._session_state == SessionState.CONNECTED and self._session is not None

    @property
    def session_state(self) -> SessionState:
        return self._session_state

    @property
    def resumption_handle(self) -> str | None:
        return self._resumption_handle

    def set_callbacks(
        self,
        on_audio_chunk: Callable[[bytes], None],
        on_interrupted: Callable[[], None],
        on_turn_complete: Callable[[str], None] | None = None,
    ) -> None:
        """Register client callbacks for incoming audio chunks and barge-in events."""
        self._on_audio_chunk = on_audio_chunk
        self._on_interrupted = on_interrupted
        self._on_turn_complete = on_turn_complete

    def _build_system_instruction(self) -> str:
        """Construct system persona instruction with injected memory context."""
        base_persona = (
            f"You are {self.settings.jarvis_name}, a sophisticated, polite, "
            f"concise, and witty personal AI operating assistant. "
            f"Address the user as {self.settings.user_name}. "
            f"You are speaking live to the user. Speak naturally, concisely, and with composure. "
            f"When asked to perform tasks on the computer, invoke the tools provided to you. "
            f"Do not pretend to execute actions if a tool is available to perform it."
        )
        # Inject memory and workspace context
        memory_context = self.memory_manager.build_augmented_context(
            user_query="Current project state and user preferences",
            max_tokens=800,
        )
        if memory_context:
            return f"{base_persona}\n\n[Active Memory & Workspace Context]:\n{memory_context}"
        return base_persona

    def _build_live_config(self) -> types.LiveConnectConfig:
        """Build LiveConnectConfig with current tools and optional session resumption."""
        gemini_tools = self.tool_registry.get_gemini_tools() if self.tool_registry else []
        resumption_cfg = None
        if self._resumption_handle:
            resumption_cfg = types.SessionResumptionConfig(handle=self._resumption_handle)
            logger.info("Resuming session with handle: %s...", self._resumption_handle[:16])

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_config.prebuilt_voice
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=self._build_system_instruction())]
            ),
            tools=gemini_tools if gemini_tools else None,
            session_resumption=resumption_cfg,
        )

    async def _cleanup_stale_session(self) -> None:
        """Cancel existing receive loop and close underlying session context cleanly."""
        if self._receive_task:
            task = self._receive_task
            self._receive_task = None
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception as ex:
                logger.debug("Error exiting session context: %s", ex)
            self._session_ctx = None
            self._session = None

    async def connect(self) -> None:
        """Establish the bidirectional live WebSocket connection with Gemini."""
        if self._session_state == SessionState.CONNECTED and self._session:
            return

        async with self._reconnect_lock:
            if self._session_state == SessionState.CONNECTED and self._session:
                return

            await self._cleanup_stale_session()

            for attempt in range(1, self.voice_config.max_reconnect_attempts + 1):
                try:
                    if attempt > 1 and self.state_machine:
                        await self.state_machine.transition_to(
                            AgentState.RECONNECTING,
                            reason=f"Reconnecting live session (attempt {attempt})",
                        )
                        await self.event_bus.emit(EventType.VOICE_RECONNECTING, {"attempt": attempt})

                    live_config = self._build_live_config()
                    self._session_ctx = self._client.aio.live.connect(
                        model=self.voice_config.live_model,
                        config=live_config,
                    )
                    self._session = await self._session_ctx.__aenter__()
                    self._session_state = SessionState.CONNECTED
                    logger.info(
                        "Connected to Gemini Live API (%s) with voice: %s (resumption=%s)",
                        self.voice_config.live_model,
                        self.voice_config.prebuilt_voice,
                        bool(self._resumption_handle),
                    )

                    # Launch single background message receiver
                    self._receive_task = asyncio.create_task(self._receive_loop())
                    if self.state_machine and self.state_machine.current_state == AgentState.RECONNECTING:
                        await self.state_machine.transition_to(AgentState.IDLE, reason="Reconnected")
                    return

                except Exception as ex:
                    logger.warning(
                        "Failed to connect to Gemini Live session (attempt %d/%d): %s",
                        attempt,
                        self.voice_config.max_reconnect_attempts,
                        ex,
                    )
                    # If resumption failed, clear handle to try fresh next attempt
                    if self._resumption_handle:
                        logger.info("Resumption failed. Clearing stale resumption handle.")
                        self._resumption_handle = None

                    if attempt == self.voice_config.max_reconnect_attempts:
                        self._session_state = SessionState.DISCONNECTED
                        raise RuntimeError(f"Unable to establish Gemini Live session: {ex}") from ex
                    await asyncio.sleep(self.voice_config.reconnect_delay * (2 ** (attempt - 1)))

    async def reconnect(self, reason: str = "Connection lost") -> bool:
        """Safely reconnect to Gemini Live with task cleanup and resumption support."""
        if self._session_state in (SessionState.RECONNECTING, SessionState.CLOSING, SessionState.CLOSED):
            return False

        async with self._reconnect_lock:
            if self._session_state in (SessionState.RECONNECTING, SessionState.CLOSING, SessionState.CLOSED):
                return False

            self._session_state = SessionState.RECONNECTING
            logger.info("Reconnecting Gemini Live session (reason: %s)...", reason)

            if self.state_machine and self.state_machine.current_state != AgentState.RECONNECTING:
                await self.state_machine.transition_to(
                    AgentState.RECONNECTING,
                    reason=f"Live session reconnecting: {reason}",
                )
            await self.event_bus.emit(EventType.VOICE_RECONNECTING, {"reason": reason})

            await self._cleanup_stale_session()

            for attempt in range(1, self.voice_config.max_reconnect_attempts + 1):
                try:
                    logger.info(
                        "Live session reconnection attempt %d/%d...",
                        attempt,
                        self.voice_config.max_reconnect_attempts,
                    )
                    live_config = self._build_live_config()
                    self._session_ctx = self._client.aio.live.connect(
                        model=self.voice_config.live_model,
                        config=live_config,
                    )
                    self._session = await self._session_ctx.__aenter__()
                    self._session_state = SessionState.CONNECTED

                    # Launch single background message receiver
                    self._receive_task = asyncio.create_task(self._receive_loop())

                    if self.state_machine and self.state_machine.current_state == AgentState.RECONNECTING:
                        await self.state_machine.transition_to(AgentState.IDLE, reason="Reconnected successfully")
                    await self.event_bus.emit(
                        EventType.VOICE_SESSION_CONNECTED if hasattr(EventType, "VOICE_SESSION_CONNECTED") else "voice.session_connected",
                        {},
                    )
                    logger.info("Successfully reconnected to Gemini Live.")
                    return True

                except Exception as ex:
                    logger.warning("Reconnection attempt %d failed: %s", attempt, ex)
                    if self._resumption_handle:
                        logger.info("Clearing stale resumption handle for fresh reconnection.")
                        self._resumption_handle = None

                    if attempt < self.voice_config.max_reconnect_attempts:
                        await asyncio.sleep(self.voice_config.reconnect_delay * (2 ** (attempt - 1)))

            self._session_state = SessionState.DISCONNECTED
            if self.state_machine and self.state_machine.current_state == AgentState.RECONNECTING:
                await self.state_machine.transition_to(AgentState.ERROR, reason="Reconnection failed")
            return False

    async def interrupt(self) -> None:
        """Cleanly handle in-session user interruption without destroying WebSocket connection."""
        logger.info("Handling in-session interruption (preserving live WebSocket connection)...")
        self._current_model_text = ""
        # If connection was lost or disconnected, then reconnect; otherwise preserve active session
        if self._session_state != SessionState.CONNECTED or self._session is None:
            logger.info("Live session was disconnected during interruption. Reconnecting...")
            await self.connect()

    async def send_audio_chunk(self, pcm_data: bytes, end_of_turn: bool = False) -> None:
        """Stream an input audio chunk (16kHz PCM) to Gemini."""
        if self._session_state in (SessionState.CLOSING, SessionState.CLOSED):
            return

        if self._session_state != SessionState.CONNECTED or not self._session:
            # Do not spam connect() on every incoming mic chunk when disconnected
            return

        async with self._send_lock:
            try:
                if pcm_data:
                    blob = types.Blob(data=pcm_data, mime_type="audio/pcm;rate=16000")
                    await self._session.send_realtime_input(audio=blob)

                if end_of_turn:
                    await self.end_turn()
            except Exception as ex:
                logger.warning("Failed to send audio chunk: %s", ex)
                if self._session_state == SessionState.CONNECTED:
                    self._session_state = SessionState.DISCONNECTED
                    asyncio.create_task(self.reconnect(reason=f"Send audio chunk error: {ex}"))

    async def send_text(self, text: str) -> None:
        """Stream a text input to Gemini Live session."""
        if self._session_state != SessionState.CONNECTED or not self._session or not text:
            return

        async with self._send_lock:
            try:
                await self._session.send_client_content(
                    turns=[types.Content(role="user", parts=[types.Part.from_text(text=text)])],
                    turn_complete=True,
                )
            except Exception as ex:
                logger.warning("Failed to send text: %s", ex)
                if self._session_state == SessionState.CONNECTED:
                    self._session_state = SessionState.DISCONNECTED
                    asyncio.create_task(self.reconnect(reason=f"Send text error: {ex}"))

    async def end_turn(self) -> None:
        """Signal that user completed speaking."""
        if self._session_state != SessionState.CONNECTED or not self._session:
            return

        async with self._send_lock:
            try:
                logger.debug("User turn marked complete for live voice session (sending audio_stream_end=True).")
                await self._session.send_realtime_input(audio_stream_end=True)
            except Exception as ex:
                logger.warning("Failed to send audio_stream_end to live session: %s", ex)
                if self._session_state == SessionState.CONNECTED:
                    self._session_state = SessionState.DISCONNECTED
                    asyncio.create_task(self.reconnect(reason=f"end_turn error: {ex}"))

    async def send_tool_response(self, tool_call_id: str, tool_name: str, response: dict[str, Any]) -> None:
        """Send function execution result back to Gemini to continue speech."""
        if self._session_state != SessionState.CONNECTED or not self._session:
            return

        func_resp = types.FunctionResponse(
            name=tool_name,
            id=tool_call_id,
            response=response,
        )
        async with self._send_lock:
            try:
                await self._session.send_tool_response(function_responses=func_resp)
                logger.debug("Sent tool response for [%s] (id=%s)", tool_name, tool_call_id)
            except Exception as ex:
                logger.warning("Failed to send tool response for [%s]: %s", tool_name, ex)
                if self._session_state not in (SessionState.CLOSING, SessionState.CLOSED, SessionState.RECONNECTING):
                    self._session_state = SessionState.DISCONNECTED
                    asyncio.create_task(self.reconnect(reason=f"send_tool_response error: {ex}"))

    async def _receive_loop(self) -> None:
        """Background loop receiving audio chunks, tool calls, and barge-in events across multiple turns."""
        try:
            while self._session_state == SessionState.CONNECTED and self._session is not None:
                async for msg in self._session.receive():
                    # Check if session transitioned away from CONNECTED during turn
                    if self._session_state != SessionState.CONNECTED:
                        break

                    # 1. Handle GoAway (Server notification that session will close soon)
                    if getattr(msg, "go_away", None):
                        time_left = getattr(msg.go_away, "time_left", None)
                        logger.warning(
                            "Gemini Live server sent GoAway (time_left=%s). Scheduling session resumption.",
                            time_left,
                        )
                        asyncio.create_task(self.reconnect(reason="Server GoAway"))
                        continue

                    # 2. Handle Session Resumption Update
                    if getattr(msg, "session_resumption_update", None):
                        res = msg.session_resumption_update
                        if getattr(res, "new_handle", None):
                            self._resumption_handle = res.new_handle
                            logger.debug("Received new session resumption handle: %s...", self._resumption_handle[:16])

                    # 3. Handle Tool Call Cancellation
                    if getattr(msg, "tool_call_cancellation", None):
                        cancelled_ids = getattr(msg.tool_call_cancellation, "ids", [])
                        logger.info("Tool call cancellation received from server for IDs: %s", cancelled_ids)

                    # 4. Handle Tool Calls
                    if msg.tool_call and msg.tool_call.function_calls:
                        await self._handle_tool_calls(msg.tool_call.function_calls)
                        continue

                    # 5. Handle Server Content & Audio Chunks
                    if msg.server_content:
                        # Check for Barge-in / Interruption
                        if getattr(msg.server_content, "interrupted", False):
                            logger.info("Barge-in / interruption detected by Gemini Live server.")
                            if self.state_machine and self.state_machine.current_state != AgentState.INTERRUPTED:
                                await self.state_machine.transition_to(
                                    AgentState.INTERRUPTED,
                                    reason="Server detected barge-in",
                                )
                            await self.event_bus.emit(EventType.VOICE_INTERRUPTED, {})
                            if self._on_interrupted:
                                self._on_interrupted()
                            if self.state_machine and self.state_machine.current_state == AgentState.INTERRUPTED:
                                await self.state_machine.transition_to(AgentState.LISTENING, reason="Resuming listen after interrupt")
                            continue

                        # Check for Generation Complete
                        if getattr(msg.server_content, "generation_complete", False):
                            logger.debug("Gemini Live server signaled generation_complete.")

                        # Process audio parts from model turn
                        if msg.server_content.model_turn:
                            # If user is currently holding PTT or interrupted, discard late chunks from cancelled turn
                            if self.state_machine and self.state_machine.current_state in (AgentState.LISTENING, AgentState.INTERRUPTED):
                                logger.debug("Discarding model turn chunk received during %s state.", self.state_machine.current_state)
                                continue

                            if self.state_machine and self.state_machine.current_state != AgentState.SPEAKING:
                                if self.state_machine.current_state == AgentState.IDLE:
                                    await self.state_machine.transition_to(AgentState.THINKING, reason="Processing model response")
                                if self.state_machine.current_state in (AgentState.THINKING, AgentState.TOOL_EXECUTION):
                                    await self.state_machine.transition_to(AgentState.SPEAKING, reason="Streaming audio")
                                    await self.event_bus.emit(EventType.VOICE_PLAYBACK_STARTED, {})

                            for part in msg.server_content.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    pcm_chunk = part.inline_data.data
                                    await self.event_bus.emit(EventType.VOICE_AUDIO_CHUNK, {"size": len(pcm_chunk)})
                                    if self._on_audio_chunk:
                                        self._on_audio_chunk(pcm_chunk)
                                if part.text:
                                    self._current_model_text += part.text

                        # Extract speech output transcription text
                        if getattr(msg.server_content, "output_transcription", None):
                            trans = msg.server_content.output_transcription
                            if getattr(trans, "text", None):
                                self._current_model_text += trans.text

                        # Turn complete
                        if getattr(msg.server_content, "turn_complete", False):
                            if self.state_machine and self.state_machine.current_state in (
                                AgentState.SPEAKING,
                                AgentState.THINKING,
                                AgentState.TOOL_EXECUTION,
                            ):
                                await self.state_machine.transition_to(AgentState.IDLE, reason="Turn finished")
                                await self.event_bus.emit(EventType.VOICE_PLAYBACK_FINISHED, {})

                            transcript = self._current_model_text or "[Spoken Audio Response]"
                            if self._on_turn_complete:
                                self._on_turn_complete(transcript)

                            if self._current_model_text:
                                # Record turn in short-term and episodic memory with secret redaction
                                self.memory_manager.record_turn(
                                    user_input="[Spoken User Audio Input]",
                                    assistant_response=self._current_model_text,
                                )
                                self._current_model_text = ""

        except asyncio.CancelledError:
            logger.debug("Voice session receive loop cancelled.")
        except Exception as ex:
            if self._session_state == SessionState.CONNECTED:
                logger.warning("Voice session connection lost or error: %s", ex)
                self._session_state = SessionState.DISCONNECTED
                asyncio.create_task(self.reconnect(reason=f"Receive loop error: {ex}"))
        finally:
            if self._session_state == SessionState.CONNECTED:
                logger.info("Live WebSocket stream closed by server. Updating session state to DISCONNECTED.")
                self._session_state = SessionState.DISCONNECTED

    async def _handle_tool_calls(self, function_calls: list[Any]) -> None:
        """Evaluate permissions and execute tools requested over the live session."""
        if self.state_machine and self.state_machine.current_state != AgentState.TOOL_EXECUTION:
            if self.state_machine.current_state in (AgentState.IDLE, AgentState.LISTENING):
                await self.state_machine.transition_to(
                    AgentState.THINKING, reason="Processing live tool calls"
                )
            await self.state_machine.transition_to(
                AgentState.TOOL_EXECUTION,
                reason=f"Executing {len(function_calls)} voice-requested tools",
            )

        for fc in function_calls:
            call_id = fc.id
            tool_name = fc.name
            arguments = fc.args if hasattr(fc, "args") and fc.args else {}

            await self.event_bus.emit(
                EventType.TOOL_REQUESTED,
                {"tool": tool_name, "arguments": arguments, "source": "voice"},
            )

            tool_instance = self.tool_registry.get(tool_name)
            # Verify permission gating (Levels 3 and 4 require human confirmation)
            if tool_instance and (
                tool_instance.permission_level >= self.permission_controller.confirmation_threshold
                or tool_instance.permission_level == PermissionLevel.CRITICAL
            ):
                if self.state_machine:
                    await self.state_machine.transition_to(
                        AgentState.WAITING_FOR_PERMISSION,
                        reason=f"Awaiting confirmation for {tool_name}",
                    )

            # Execute via ToolRegistry pipeline (PermissionController -> AuditLogger)
            result: ToolResult = await self.tool_registry.execute(
                tool_name=tool_name,
                arguments=arguments,
                permission_controller=self.permission_controller,
            )

            if self.state_machine:
                await self.state_machine.transition_to(AgentState.TOOL_EXECUTION, reason="Tool executed")

            if result.success:
                await self.event_bus.emit(EventType.TOOL_EXECUTED, {"tool": tool_name, "result": result.result})
            else:
                await self.event_bus.emit(EventType.TOOL_FAILED, {"tool": tool_name, "error": result.error})

            # Return tool response to Gemini Live session synchronously
            await self.send_tool_response(
                tool_call_id=call_id,
                tool_name=tool_name,
                response=result.to_dict(),
            )

    async def close(self) -> None:
        """Close the live WebSocket session cleanly."""
        self._session_state = SessionState.CLOSING
        async with self._reconnect_lock:
            await self._cleanup_stale_session()
            self._session_state = SessionState.CLOSED
        logger.info("Closed Gemini Live voice session.")
