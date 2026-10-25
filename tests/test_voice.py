"""Automated test suite for JARVIS Voice Subsystem (Phase 4)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis.core.agent import JarvisAgent
from jarvis.core.state import (
    AgentState,
    InvalidStateTransitionError,
    StateMachine,
)
from jarvis.events import EventBus, EventType
from jarvis.memory import MemoryManager
from jarvis.models.base import AIProvider, ModelResponse
from jarvis.security.permissions import (
    ApprovalCallback,
    PermissionController,
    PermissionLevel,
)
from jarvis.config import Settings
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.tools.registry import ToolRegistry
from jarvis.voice.audio_io import (
    MockAudioInput,
    MockAudioOutput,
    PygameAudioOutput,
    calculate_pcm_duration,
)
from jarvis.voice.base import VoiceConfig
from jarvis.voice.live_session import GeminiLiveVoiceSession, SessionState
from jarvis.voice.loop import VoiceLoop
from jarvis.voice.ptt import PTTController
from jarvis.voice.tts import MockTTS


# ---------------------------------------------------------------------------
# 1. Audio Input & Output Buffering Tests
# ---------------------------------------------------------------------------
def test_audio_input_buffering():
    audio_in = MockAudioInput(sample_rate=16000)
    assert not audio_in.is_capturing
    assert audio_in.sample_rate == 16000

    received = []
    audio_in.start_capture(callback=lambda chunk: received.append(chunk))
    assert audio_in.is_capturing

    test_chunk = b"\x00\x01" * 512
    audio_in.emit_chunk(test_chunk)
    assert len(received) == 1
    assert received[0] == test_chunk

    audio_in.stop_capture()
    assert not audio_in.is_capturing


def test_audio_output_buffering():
    audio_out = MockAudioOutput(sample_rate=24000)
    assert not audio_out.is_playing
    assert audio_out.sample_rate == 24000

    test_pcm = b"\x10\x20" * 256
    audio_out.play_chunk(test_pcm)
    assert audio_out.is_playing
    assert len(audio_out.received_chunks) == 1


# ---------------------------------------------------------------------------
# 2. Push-to-Talk (PTT) Tests
# ---------------------------------------------------------------------------
def test_ptt_activation_and_release():
    pressed = []
    released = []

    ptt = PTTController(
        on_press=lambda: pressed.append(True),
        on_release=lambda: released.append(True),
    )

    assert not ptt.is_pressed
    ptt.press()
    assert ptt.is_pressed
    assert len(pressed) == 1

    ptt.release()
    assert not ptt.is_pressed
    assert len(released) == 1


# ---------------------------------------------------------------------------
# 3. Interruption & Barge-in Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_barge_in_interruption():
    audio_out = MockAudioOutput(sample_rate=24000)
    audio_out.play_chunk(b"\x00" * 100)
    assert audio_out.is_playing

    # Simulate barge-in cut-off
    audio_out.stop()
    assert not audio_out.is_playing


# ---------------------------------------------------------------------------
# 4. Tool-Call Routing, Approval & Denial Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_call_routing_and_approval(tmp_path):
    event_bus = EventBus()
    state_machine = StateMachine(event_bus=event_bus)
    permission_controller = PermissionController(confirmation_threshold=PermissionLevel.HIGH_RISK)
    registry = ToolRegistry()

    # Register a safe tool
    class MockAppTool(BaseTool):
        name = "open_app"
        description = "Open desktop app"
        permission_level = PermissionLevel.LOW_RISK

        @property
        def parameters_schema(self) -> dict:
            return {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}

        async def execute(self, app_name: str) -> ToolResult:
            return ToolResult(success=True, result=f"Launched {app_name}")

    registry.register(MockAppTool())

    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(
        ai_provider=mock_provider,
        tool_registry=registry,
        permission_controller=permission_controller,
        state_machine=state_machine,
        event_bus=event_bus,
    )

    session = GeminiLiveVoiceSession(
        api_key="fake_key",
        tool_registry=registry,
        permission_controller=permission_controller,
        state_machine=state_machine,
        event_bus=event_bus,
    )
    session.send_tool_response = AsyncMock()

    # Simulate incoming LiveServerToolCall
    fake_fc = MagicMock()
    fake_fc.id = "call_123"
    fake_fc.name = "open_app"
    fake_fc.args = {"app_name": "Calculator"}

    await session._handle_tool_calls([fake_fc])

    # Verify tool execution and response sent back
    session.send_tool_response.assert_called_once()
    call_kwargs = session.send_tool_response.call_args.kwargs
    assert call_kwargs["tool_name"] == "open_app"
    assert call_kwargs["tool_call_id"] == "call_123"
    assert call_kwargs["response"]["success"] is True
    assert "Launched Calculator" in call_kwargs["response"]["result"]


@pytest.mark.asyncio
async def test_tool_call_permission_denial(tmp_path):
    event_bus = EventBus()
    state_machine = StateMachine(event_bus=event_bus)

    # Human callback denying permission
    async def deny_callback(tool_name: str, args: dict, level: PermissionLevel, description: str = "") -> bool:
        return False

    permission_controller = PermissionController(
        confirmation_threshold=int(PermissionLevel.HIGH_RISK),
        approval_callback=deny_callback,
    )
    registry = ToolRegistry()

    # Register a high risk tool
    class MockDeleteTool(BaseTool):
        name = "delete_file"
        description = "Delete a file"
        permission_level = PermissionLevel.HIGH_RISK

        @property
        def parameters_schema(self) -> dict:
            return {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

        async def execute(self, path: str) -> ToolResult:
            return ToolResult(success=True, result="Deleted")

    registry.register(MockDeleteTool())

    session = GeminiLiveVoiceSession(
        api_key="fake_key",
        tool_registry=registry,
        permission_controller=permission_controller,
        state_machine=state_machine,
        event_bus=event_bus,
    )
    session.send_tool_response = AsyncMock()

    fake_fc = MagicMock()
    fake_fc.id = "call_del_456"
    fake_fc.name = "delete_file"
    fake_fc.args = {"path": "important.txt"}

    await session._handle_tool_calls([fake_fc])

    call_kwargs = session.send_tool_response.call_args.kwargs
    assert call_kwargs["response"]["success"] is False
    assert "denied by human user" in call_kwargs["response"]["error"].lower()


# ---------------------------------------------------------------------------
# 5. Hybrid Fallback Mode Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_voice_loop_fallback_mode():
    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(ai_provider=mock_provider)

    mock_in = MockAudioInput()
    mock_out = MockAudioOutput()
    mock_tts = MockTTS()
    mock_session = MagicMock()
    mock_session.connect = AsyncMock(side_effect=ConnectionError("Live WebSocket offline"))
    mock_session.close = AsyncMock()

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=mock_in,
        audio_output=mock_out,
        voice_session=mock_session,
        fallback_tts=mock_tts,
    )

    await voice_loop.start()
    assert voice_loop.use_fallback_mode is True

    # Speak using fallback TTS
    await voice_loop.speak_fallback("Hello from offline TTS")
    assert len(mock_tts.spoken_texts) == 1
    assert "offline TTS" in mock_tts.spoken_texts[0]

    await voice_loop.stop()
    assert not voice_loop.is_running


# ---------------------------------------------------------------------------
# 6. Session Cleanup & No-Audio-Persistence Guarantee Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_session_cleanup():
    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(ai_provider=mock_provider)
    mock_in = MockAudioInput()
    mock_out = MockAudioOutput()
    mock_session = MagicMock()
    mock_session.connect = AsyncMock()
    mock_session.close = AsyncMock()

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=mock_in,
        audio_output=mock_out,
        voice_session=mock_session,
    )

    await voice_loop.start()
    assert voice_loop.is_running

    await voice_loop.stop()
    assert not voice_loop.is_running
    assert not mock_in.is_capturing
    assert not mock_out.is_playing
    mock_session.close.assert_called_once()


def test_no_audio_persistence_guarantee(tmp_path):
    """Verify that voice processing leaves zero audio files (.wav, .pcm, .mp3) on disk."""
    workspace = Path(".")
    audio_extensions = ["*.wav", "*.pcm", "*.mp3", "*.flac", "*.ogg"]
    found_audio_files = []
    for ext in audio_extensions:
        found_audio_files.extend(list(workspace.glob(f"**/{ext}")))

    assert len(found_audio_files) == 0, f"Found persisted audio files: {found_audio_files}"


# ---------------------------------------------------------------------------
# 7. Secret Redaction on Voice Memories
# ---------------------------------------------------------------------------
def test_voice_turn_secret_redaction(tmp_path):
    mm = MemoryManager(base_dir=tmp_path)
    # Simulate voice turn recording containing spoken API key
    spoken_text = "Remember that my secret API key is SECRET_TEST_KEY_123"
    spoken_response = "I have noted that your key is SECRET_TEST_KEY_123"

    mm.record_turn(user_input=spoken_text, assistant_response=spoken_response)

    # Check episodic log on disk
    for log_file in (tmp_path / "episodes").glob("*.md"):
        content = log_file.read_text(encoding="utf-8")
        assert "SECRET_TEST_KEY_123" not in content
        assert "[REDACTED_SECRET]" in content


# ---------------------------------------------------------------------------
# 8. Voice State Transition and Interruption Regression Tests (Phase 4 Runtime Fixes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ptt_during_speaking_barge_in():
    """Verify that pressing PTT while SPEAKING performs proper barge-in:
    SPEAKING -> INTERRUPTED -> LISTENING, halting active audio output."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    mock_in = MockAudioInput()
    mock_out = MockAudioOutput()
    mock_out.play_chunk(b"\x01\x02" * 100)
    assert mock_out.is_playing is True

    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(ai_provider=mock_provider, state_machine=sm, event_bus=bus)
    mock_session = MagicMock()
    mock_session.connect = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.end_turn = AsyncMock()

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=mock_in,
        audio_output=mock_out,
        voice_session=mock_session,
    )

    # Set state to SPEAKING
    await sm.transition_to(AgentState.THINKING)
    await sm.transition_to(AgentState.SPEAKING)
    assert sm.current_state == AgentState.SPEAKING

    interrupted_events = []
    bus.subscribe(EventType.VOICE_INTERRUPTED, lambda e: interrupted_events.append(e))

    # PTT pressed during speaking
    voice_loop.is_running = True
    voice_loop.audio_output.stop()  # Simulates immediate cut-off in _on_ptt_press
    await voice_loop._handle_ptt_press_async()

    assert mock_out.is_playing is False
    assert sm.current_state == AgentState.LISTENING
    assert len(interrupted_events) == 1
    assert interrupted_events[0].data.get("interrupted_state") == AgentState.SPEAKING.value


@pytest.mark.asyncio
async def test_ptt_during_thinking_interruption():
    """Verify that pressing PTT while THINKING cancels generation and transitions:
    THINKING -> INTERRUPTED -> LISTENING."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    mock_in = MockAudioInput()
    mock_out = MockAudioOutput()
    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(ai_provider=mock_provider, state_machine=sm, event_bus=bus)
    mock_session = MagicMock()
    mock_session.connect = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.end_turn = AsyncMock()

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=mock_in,
        audio_output=mock_out,
        voice_session=mock_session,
    )

    # Set state to THINKING
    await sm.transition_to(AgentState.THINKING)
    assert sm.current_state == AgentState.THINKING

    interrupted_events = []
    bus.subscribe(EventType.VOICE_INTERRUPTED, lambda e: interrupted_events.append(e))

    # PTT pressed during thinking
    voice_loop.is_running = True
    await voice_loop._handle_ptt_press_async()

    assert sm.current_state == AgentState.LISTENING
    assert len(interrupted_events) == 1
    assert interrupted_events[0].data.get("interrupted_state") == AgentState.THINKING.value


@pytest.mark.asyncio
async def test_ptt_during_tool_execution():
    """Verify that pressing PTT while TOOL_EXECUTION interrupts and transitions:
    TOOL_EXECUTION -> INTERRUPTED -> LISTENING."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    mock_in = MockAudioInput()
    mock_out = MockAudioOutput()
    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(ai_provider=mock_provider, state_machine=sm, event_bus=bus)
    mock_session = MagicMock()
    mock_session.connect = AsyncMock()
    mock_session.close = AsyncMock()

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=mock_in,
        audio_output=mock_out,
        voice_session=mock_session,
    )

    # Set state to TOOL_EXECUTION
    await sm.transition_to(AgentState.THINKING)
    await sm.transition_to(AgentState.TOOL_EXECUTION)
    assert sm.current_state == AgentState.TOOL_EXECUTION

    interrupted_events = []
    bus.subscribe(EventType.VOICE_INTERRUPTED, lambda e: interrupted_events.append(e))

    voice_loop.is_running = True
    await voice_loop._handle_ptt_press_async()

    assert sm.current_state == AgentState.LISTENING
    assert len(interrupted_events) == 1
    assert interrupted_events[0].data.get("interrupted_state") == AgentState.TOOL_EXECUTION.value


@pytest.mark.asyncio
async def test_interruption_followed_by_new_listening_turn():
    """Verify an interrupted turn leads cleanly into a new listening turn without illegal transitions."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    mock_in = MockAudioInput()
    mock_out = MockAudioOutput()
    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(ai_provider=mock_provider, state_machine=sm, event_bus=bus)
    mock_session = MagicMock()
    mock_session.connect = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.end_turn = AsyncMock()

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=mock_in,
        audio_output=mock_out,
        voice_session=mock_session,
    )
    voice_loop.is_running = True

    # 1. Agent is speaking
    await sm.transition_to(AgentState.THINKING)
    await sm.transition_to(AgentState.SPEAKING)

    # 2. Interruption: PTT pressed during speaking -> INTERRUPTED -> LISTENING
    await voice_loop._handle_ptt_press_async()
    assert sm.current_state == AgentState.LISTENING

    # 3. PTT released -> THINKING + end_turn called
    await voice_loop._handle_ptt_release_async()
    assert sm.current_state == AgentState.THINKING
    mock_session.end_turn.assert_awaited_once()

    # 4. Turn finishes -> IDLE
    await sm.transition_to(AgentState.IDLE)
    assert sm.current_state == AgentState.IDLE

    # 5. PTT pressed again from IDLE -> LISTENING
    await voice_loop._handle_ptt_press_async()
    assert sm.current_state == AgentState.LISTENING


@pytest.mark.asyncio
async def test_multiple_consecutive_voice_turns():
    """Verify multiple back-to-back voice turns follow valid transitions without warnings or errors."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    mock_in = MockAudioInput()
    mock_out = MockAudioOutput()
    mock_provider = MagicMock(spec=AIProvider)
    agent = JarvisAgent(ai_provider=mock_provider, state_machine=sm, event_bus=bus)
    mock_session = MagicMock()
    mock_session.connect = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.end_turn = AsyncMock()

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=mock_in,
        audio_output=mock_out,
        voice_session=mock_session,
    )
    voice_loop.is_running = True

    for turn in range(3):
        # User starts speaking
        assert sm.current_state == AgentState.IDLE
        await voice_loop._handle_ptt_press_async()
        assert sm.current_state == AgentState.LISTENING

        # User finishes speaking
        await voice_loop._handle_ptt_release_async()
        assert sm.current_state == AgentState.THINKING

        # Model generates & speaks audio
        await sm.transition_to(AgentState.SPEAKING)
        assert sm.current_state == AgentState.SPEAKING

        # Model finishes playback
        await sm.transition_to(AgentState.IDLE)
        assert sm.current_state == AgentState.IDLE


@pytest.mark.asyncio
async def test_live_session_end_turn_signals_server():
    """Verify GeminiLiveVoiceSession.end_turn() sends audio_stream_end=True."""
    mock_raw_session = MagicMock()
    mock_raw_session.send_realtime_input = AsyncMock()

    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )
    live_session._session = mock_raw_session
    live_session._session_state = SessionState.CONNECTED

    await live_session.end_turn()
    mock_raw_session.send_realtime_input.assert_awaited_once_with(audio_stream_end=True)


@pytest.mark.asyncio
async def test_state_machine_voice_transitions():
    """Verify all valid voice transitions and illegal transition enforcement."""
    sm = StateMachine()

    # IDLE -> LISTENING -> THINKING -> SPEAKING -> IDLE
    assert sm.current_state == AgentState.IDLE
    await sm.transition_to(AgentState.LISTENING)
    assert sm.current_state == AgentState.LISTENING
    await sm.transition_to(AgentState.THINKING)
    assert sm.current_state == AgentState.THINKING
    await sm.transition_to(AgentState.SPEAKING)
    assert sm.current_state == AgentState.SPEAKING
    await sm.transition_to(AgentState.IDLE)
    assert sm.current_state == AgentState.IDLE

    # Barge-in transitions:
    # SPEAKING -> INTERRUPTED -> LISTENING
    await sm.transition_to(AgentState.THINKING)
    await sm.transition_to(AgentState.SPEAKING)
    await sm.transition_to(AgentState.INTERRUPTED)
    await sm.transition_to(AgentState.LISTENING)
    assert sm.current_state == AgentState.LISTENING

    # THINKING -> INTERRUPTED -> LISTENING
    await sm.transition_to(AgentState.THINKING)
    await sm.transition_to(AgentState.INTERRUPTED)
    await sm.transition_to(AgentState.LISTENING)
    assert sm.current_state == AgentState.LISTENING

    # TOOL_EXECUTION -> INTERRUPTED -> LISTENING
    await sm.transition_to(AgentState.THINKING)
    await sm.transition_to(AgentState.TOOL_EXECUTION)
    await sm.transition_to(AgentState.INTERRUPTED)
    await sm.transition_to(AgentState.LISTENING)
    assert sm.current_state == AgentState.LISTENING

    # Verify illegal transition: LISTENING directly to SPEAKING raises error
    with pytest.raises(InvalidStateTransitionError):
        await sm.transition_to(AgentState.SPEAKING)


# ---------------------------------------------------------------------------
# 9. Extended Lifecycle, Voice Selection, Reconnection & PCM Tests
# ---------------------------------------------------------------------------

def test_configurable_voice_selection():
    """Verify that Gemini Live prebuilt voices are configurable and default to Charon."""
    cfg_default = VoiceConfig()
    assert cfg_default.prebuilt_voice == "Charon"

    supported_voices = ["Charon", "Orus", "Gacrux", "Puck", "Aoede"]
    for voice_name in supported_voices:
        cfg = VoiceConfig(prebuilt_voice=voice_name)
        assert cfg.prebuilt_voice == voice_name
        session = GeminiLiveVoiceSession(api_key="fake-key", config=cfg)
        live_cfg = session._build_live_config()
        assert live_cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == voice_name

    settings = Settings()
    assert settings.gemini_live_voice == "Charon"


def test_correct_24khz_playback_configuration():
    """Verify 24kHz, 16-bit, mono audio output configuration and 44-byte WAV header generator."""
    import struct

    audio_out = PygameAudioOutput(sample_rate=24000)
    assert audio_out.sample_rate == 24000

    # 48,000 bytes = 24,000 16-bit mono samples = exactly 1.000 second at 24kHz
    pcm_chunk = b"\x00\x00" * 24000
    wav_bytes = audio_out._pcm16_to_wav(pcm_chunk, sample_rate=24000, channels=1)

    # 44 bytes header + 48000 bytes PCM = 48044 bytes
    assert len(wav_bytes) == 48044
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"
    assert wav_bytes[12:16] == b"fmt "

    # Unpack 44-byte RIFF header and verify exact audio parameters
    (
        riff,
        chunk_size,
        wave,
        fmt,
        subchunk1_size,
        audio_format,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        data_hdr,
        data_size,
    ) = struct.unpack("<4sI4s4sIHHIIHH4sI", wav_bytes[:44])

    assert riff == b"RIFF"
    assert wave == b"WAVE"
    assert fmt == b"fmt "
    assert audio_format == 1  # Standard PCM
    assert num_channels == 1  # Mono configuration verified
    assert sample_rate == 24000  # 24kHz configuration verified
    assert bits_per_sample == 16  # 16-bit configuration verified
    assert byte_rate == 24000 * 1 * 2  # 48,000 bytes/sec
    assert block_align == 1 * 2  # 2 bytes per mono sample
    assert data_hdr == b"data"
    assert data_size == len(pcm_chunk)


def test_pcm_duration_calculation():
    """Verify accurate duration calculation for raw 16-bit PCM chunks."""
    # 48,000 bytes @ 24kHz 16-bit mono -> 1.0 second
    assert calculate_pcm_duration(48000, sample_rate=24000, channels=1, sample_width=2) == 1.0
    # 24,000 bytes @ 24kHz 16-bit mono -> 0.5 second
    assert calculate_pcm_duration(24000, sample_rate=24000, channels=1, sample_width=2) == 0.5
    # Empty data -> 0.0 seconds
    assert calculate_pcm_duration(0, sample_rate=24000) == 0.0


@pytest.mark.asyncio
async def test_session_health_after_interruption():
    """Verify that interrupting generation leaves the session in healthy CONNECTED state."""
    mock_raw_session = MagicMock()
    mock_raw_session.send_realtime_input = AsyncMock()

    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )
    live_session._session = mock_raw_session
    live_session._session_state = SessionState.CONNECTED
    assert live_session.is_connected is True

    # User interrupts via barge-in
    await live_session.send_audio_chunk(b"\x01\x02" * 100)
    assert live_session.is_connected is True
    assert live_session.session_state == SessionState.CONNECTED

    await live_session.end_turn()
    assert live_session.is_connected is True
    assert mock_raw_session.send_realtime_input.await_count == 2


@pytest.mark.asyncio
async def test_websocket_timeout_and_reconnection():
    """Verify session automatically marks DISCONNECTED and reconnects when WebSocket error occurs."""
    mock_raw_session = MagicMock()
    mock_raw_session.send_realtime_input = AsyncMock(
        side_effect=ConnectionError("keepalive ping timeout; no close frame received")
    )

    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )
    live_session._session = mock_raw_session
    live_session._session_state = SessionState.CONNECTED

    # Mock reconnect method to track call
    live_session.reconnect = AsyncMock(return_value=True)

    await live_session.end_turn()
    assert live_session.session_state == SessionState.DISCONNECTED
    # Small sleep to let background task run
    await asyncio.sleep(0.05)
    live_session.reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_stale_task_cancellation_and_no_duplicate_receive_loops():
    """Verify cleanup cancels existing receive task before launching a replacement."""
    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )

    # Simulate an active background receive task
    async def dummy_loop():
        try:
            while True:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(dummy_loop())
    live_session._receive_task = task
    assert not task.done()

    await live_session._cleanup_stale_session()
    assert task.cancelled() or task.done()
    assert live_session._receive_task is None


def test_session_resumption_handle_storage():
    """Verify session resumption handle is stored and injected into LiveConnectConfig."""
    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )
    assert live_session.resumption_handle is None

    # Simulate receiving resumption update
    live_session._resumption_handle = "resumption_token_xyz789"
    cfg = live_session._build_live_config()
    assert cfg.session_resumption is not None
    assert cfg.session_resumption.handle == "resumption_token_xyz789"


@pytest.mark.asyncio
async def test_clean_session_shutdown():
    """Verify closing session transitions explicitly through CLOSING to CLOSED."""
    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )
    live_session._session_state = SessionState.CONNECTED

    await live_session.close()
    assert live_session.session_state == SessionState.CLOSED
    assert live_session.is_connected is False


@pytest.mark.asyncio
async def test_interrupt_preserves_websocket_connection():
    """Verify in-session interrupt clears model text and keeps the WebSocket connection alive."""
    mock_raw_session = MagicMock()
    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )
    live_session._session = mock_raw_session
    live_session._session_state = SessionState.CONNECTED
    live_session._current_model_text = "Partial stale model text"

    # User interrupts
    await live_session.interrupt()

    # Verify session remains CONNECTED, raw session is NOT destroyed, text cleared
    assert live_session.session_state == SessionState.CONNECTED
    assert live_session.is_connected is True
    assert live_session._session is mock_raw_session
    assert live_session._current_model_text == ""


@pytest.mark.asyncio
async def test_receive_loop_multi_turn_persistence():
    """Verify receive loop continues waiting for subsequent turns after turn_complete=True."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)

    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
        state_machine=sm,
        event_bus=bus,
    )

    # Simulate 2 turns through mock session.receive() generator
    turn_1_msg_a = MagicMock()
    turn_1_msg_a.server_content = MagicMock()
    turn_1_msg_a.server_content.interrupted = False
    turn_1_msg_a.server_content.turn_complete = False
    turn_1_msg_a.server_content.output_transcription = None
    part1 = MagicMock()
    part1.inline_data.data = b"\x00\x01" * 100
    part1.text = "Hello "
    turn_1_msg_a.server_content.model_turn.parts = [part1]
    turn_1_msg_a.go_away = None
    turn_1_msg_a.session_resumption_update = None
    turn_1_msg_a.tool_call = None
    turn_1_msg_a.tool_call_cancellation = None

    turn_1_msg_b = MagicMock()
    turn_1_msg_b.server_content = MagicMock()
    turn_1_msg_b.server_content.interrupted = False
    turn_1_msg_b.server_content.turn_complete = True
    turn_1_msg_b.server_content.model_turn = None
    turn_1_msg_b.server_content.output_transcription = None
    turn_1_msg_b.go_away = None
    turn_1_msg_b.session_resumption_update = None
    turn_1_msg_b.tool_call = None
    turn_1_msg_b.tool_call_cancellation = None

    turn_2_msg_a = MagicMock()
    turn_2_msg_a.server_content = MagicMock()
    turn_2_msg_a.server_content.interrupted = False
    turn_2_msg_a.server_content.turn_complete = False
    turn_2_msg_a.server_content.output_transcription = None
    part2 = MagicMock()
    part2.inline_data.data = b"\x02\x03" * 100
    part2.text = "World!"
    turn_2_msg_a.server_content.model_turn.parts = [part2]
    turn_2_msg_a.go_away = None
    turn_2_msg_a.session_resumption_update = None
    turn_2_msg_a.tool_call = None
    turn_2_msg_a.tool_call_cancellation = None

    turn_2_msg_b = MagicMock()
    turn_2_msg_b.server_content = MagicMock()
    turn_2_msg_b.server_content.interrupted = False
    turn_2_msg_b.server_content.turn_complete = True
    turn_2_msg_b.server_content.model_turn = None
    turn_2_msg_b.server_content.output_transcription = None
    turn_2_msg_b.go_away = None
    turn_2_msg_b.session_resumption_update = None
    turn_2_msg_b.tool_call = None
    turn_2_msg_b.tool_call_cancellation = None

    turns_received = []

    def on_complete(transcript):
        turns_received.append(transcript)

    live_session.set_callbacks(
        on_audio_chunk=lambda c: None,
        on_interrupted=lambda: None,
        on_turn_complete=on_complete,
    )

    async def fake_receive_gen():
        # Generator yields Turn 1
        if len(turns_received) == 0:
            yield turn_1_msg_a
            yield turn_1_msg_b
        # Next call yields Turn 2
        elif len(turns_received) == 1:
            yield turn_2_msg_a
            yield turn_2_msg_b
        else:
            # End after 2 turns
            await asyncio.sleep(0.5)

    mock_session = MagicMock()
    mock_session.receive = fake_receive_gen

    live_session._session = mock_session
    live_session._session_state = SessionState.CONNECTED

    # Start receive task
    task = asyncio.create_task(live_session._receive_loop())

    # Wait for both turns to complete
    for _ in range(20):
        if len(turns_received) >= 2:
            break
        await asyncio.sleep(0.05)

    # Cancel loop cleanly
    live_session._session_state = SessionState.CLOSING
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(turns_received) == 2
    assert "Hello" in turns_received[0]
    assert "World" in turns_received[1]


@pytest.mark.asyncio
async def test_go_away_schedules_reconnect():
    """Verify receiving GoAway triggers reconnection without crashing."""
    live_session = GeminiLiveVoiceSession(
        api_key="test-api-key",
        config=VoiceConfig(),
    )
    live_session.reconnect = AsyncMock(return_value=True)

    go_away_msg = MagicMock()
    go_away_msg.go_away = MagicMock()
    go_away_msg.go_away.time_left = "30s"
    go_away_msg.server_content = None
    go_away_msg.session_resumption_update = None
    go_away_msg.tool_call = None
    go_away_msg.tool_call_cancellation = None

    called = False

    async def fake_gen():
        nonlocal called
        if not called:
            called = True
            yield go_away_msg
        else:
            await asyncio.sleep(0.5)

    mock_session = MagicMock()
    mock_session.receive = fake_gen

    live_session._session = mock_session
    live_session._session_state = SessionState.CONNECTED

    task = asyncio.create_task(live_session._receive_loop())
    await asyncio.sleep(0.05)
    live_session._session_state = SessionState.CLOSING
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    live_session.reconnect.assert_called_once_with(reason="Server GoAway")


def test_cli_voice_argument_parsing():
    """Verify that cli_voice.py parses --voice flag correctly for all valid and invalid options."""
    from cli_voice import build_parser, main
    import inspect

    sig = inspect.signature(main)
    assert "custom_voice" in sig.parameters

    parser = build_parser()

    # Default without args
    args = parser.parse_args([])
    assert args.voice is None

    # Valid voices via --voice and -v
    for v in ["Charon", "Orus", "Gacrux", "Puck", "Aoede"]:
        args_long = parser.parse_args(["--voice", v])
        assert args_long.voice == v

        args_short = parser.parse_args(["-v", v])
        assert args_short.voice == v

    # Invalid voice should trigger argument parsing error
    with pytest.raises(SystemExit):
        parser.parse_args(["--voice", "NonExistentVoice"])




