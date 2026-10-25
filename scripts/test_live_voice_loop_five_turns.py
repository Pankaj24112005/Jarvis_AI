"""End-to-end 5-turn Live Voice verification script executing through VoiceLoop and GeminiLiveVoiceSession."""

import asyncio
import os
import sys
import time

sys.path.insert(0, ".")

from jarvis.config import Settings
from jarvis.core.agent import JarvisAgent
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import Event, EventBus, EventType
from jarvis.memory import MemoryManager
from jarvis.models.gemini import GeminiProvider
from jarvis.security.permissions import PermissionController
from jarvis.tools import ToolRegistry, register_default_tools
from jarvis.voice.audio_io import MockAudioInput, PygameAudioOutput
from jarvis.voice.base import VoiceConfig
from jarvis.voice.live_session import GeminiLiveVoiceSession, SessionState
from jarvis.voice.loop import VoiceLoop
from jarvis.voice.ptt import PTTController
from jarvis.voice.tts import Pyttsx3TTS


async def run_five_turn_test():
    settings = Settings()
    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        print("ERROR: No GEMINI_API_KEY available", flush=True)
        return False

    print("=== STARTING 5-TURN END-TO-END LIVE VOICE VERIFICATION ===", flush=True)
    print(f"Voice configured: Charon", flush=True)
    print(f"Model: models/gemini-3.1-flash-live-preview", flush=True)

    event_bus = EventBus()
    state_machine = StateMachine(event_bus=event_bus)
    permission_controller = PermissionController()
    tool_registry = ToolRegistry()
    register_default_tools(tool_registry)
    memory_manager = MemoryManager()
    ai_provider = GeminiProvider(api_key=api_key)

    agent = JarvisAgent(
        ai_provider=ai_provider,
        memory_manager=memory_manager,
        tool_registry=tool_registry,
        permission_controller=permission_controller,
        state_machine=state_machine,
        event_bus=event_bus,
    )

    audio_in = MockAudioInput(sample_rate=16000)
    audio_out = PygameAudioOutput(sample_rate=24000)
    fallback_tts = Pyttsx3TTS()

    voice_config = VoiceConfig(
        live_model="models/gemini-3.1-flash-live-preview",
        input_sample_rate=16000,
        output_sample_rate=24000,
        prebuilt_voice="Charon",
    )

    live_session = GeminiLiveVoiceSession(
        api_key=api_key,
        config=voice_config,
        tool_registry=tool_registry,
        permission_controller=permission_controller,
        memory_manager=memory_manager,
        state_machine=state_machine,
        event_bus=event_bus,
    )

    voice_loop = VoiceLoop(
        agent=agent,
        audio_input=audio_in,
        audio_output=audio_out,
        voice_session=live_session,
        fallback_tts=fallback_tts,
        config=voice_config,
    )

    # Track state changes
    state_history = []
    def on_state(e: Event):
        s = e.data.get("new_state")
        state_history.append(s)
        print(f" -> STATE: [{s}]", flush=True)

    event_bus.subscribe(EventType.AGENT_STATE_CHANGED, on_state)

    # Track transcripts
    transcripts = []
    def on_transcript(text: str):
        transcripts.append(text)
        print(f" [TRANSCRIPT]: {text.strip()}", flush=True)

    live_session._on_turn_complete = on_transcript

    print("\nStarting VoiceLoop...", flush=True)
    await voice_loop.start()
    # Stop the background hotkey listener in automated test so GetAsyncKeyState does not auto-release programmatic presses
    voice_loop.ptt.stop_hotkey_listener()
    assert voice_loop.is_running
    assert not voice_loop.use_fallback_mode
    assert live_session.is_connected
    assert live_session.session_state == SessionState.CONNECTED
    print("VoiceLoop started in PRIMARY Mode (Live WebSocket CONNECTED)!\n", flush=True)

    async def wait_for_idle(timeout: float = 12.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if state_machine.current_state == AgentState.IDLE:
                return True
            await asyncio.sleep(0.1)
        return False

    async def wait_for_state(target_state: AgentState, timeout: float = 6.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if state_machine.current_state == target_state:
                return True
            await asyncio.sleep(0.05)
        return False

    # -------------------------------------------------------------
    # TURN 1: PTT -> speak -> release -> response -> IDLE
    # -------------------------------------------------------------
    print("\n--- TURN 1: PTT -> speak -> release -> response -> IDLE ---", flush=True)
    voice_loop.ptt.press()
    await wait_for_state(AgentState.LISTENING)
    assert state_machine.current_state == AgentState.LISTENING

    # Send text prompt over Live session
    await live_session.send_text("Hello JARVIS, are you online? Respond in one short sentence.")
    voice_loop.ptt.release()
    await wait_for_state(AgentState.THINKING)

    turn1_ok = await wait_for_idle(timeout=10.0)
    print(f"TURN 1 completed: {turn1_ok}, Current state: {state_machine.current_state}", flush=True)
    assert turn1_ok
    assert state_machine.current_state == AgentState.IDLE
    assert live_session.is_connected

    # -------------------------------------------------------------
    # TURN 2: PTT -> speak -> release -> response -> IDLE
    # -------------------------------------------------------------
    print("\n--- TURN 2: PTT -> speak -> release -> response -> IDLE ---", flush=True)
    voice_loop.ptt.press()
    await wait_for_state(AgentState.LISTENING)
    assert state_machine.current_state == AgentState.LISTENING

    await live_session.send_text("What is two plus two? Respond in three words.")
    voice_loop.ptt.release()
    await wait_for_state(AgentState.THINKING)

    turn2_ok = await wait_for_idle(timeout=10.0)
    print(f"TURN 2 completed: {turn2_ok}, Current state: {state_machine.current_state}", flush=True)
    assert turn2_ok
    assert state_machine.current_state == AgentState.IDLE
    assert live_session.is_connected

    # -------------------------------------------------------------
    # TURN 3: PTT -> speak -> release -> response -> IDLE
    # -------------------------------------------------------------
    print("\n--- TURN 3: PTT -> speak -> release -> response -> IDLE ---", flush=True)
    voice_loop.ptt.press()
    await wait_for_state(AgentState.LISTENING)
    assert state_machine.current_state == AgentState.LISTENING

    await live_session.send_text("Confirm system diagnostic status in two words.")
    voice_loop.ptt.release()
    await wait_for_state(AgentState.THINKING)

    turn3_ok = await wait_for_idle(timeout=10.0)
    print(f"TURN 3 completed: {turn3_ok}, Current state: {state_machine.current_state}", flush=True)
    assert turn3_ok
    assert state_machine.current_state == AgentState.IDLE
    assert live_session.is_connected

    # -------------------------------------------------------------
    # TURN 4: PTT -> speak -> release -> THINKING
    #         -> press PTT to interrupt -> INTERRUPTED -> LISTENING
    #         -> speak a new command -> response -> IDLE
    # -------------------------------------------------------------
    print("\n--- TURN 4: Mid-flight PTT interruption & recovery ---", flush=True)
    voice_loop.ptt.press()
    await wait_for_state(AgentState.LISTENING)

    # Prompt a longer response
    await live_session.send_text("Recite the first 20 elements of the periodic table in full detail.")
    voice_loop.ptt.release()
    await wait_for_state(AgentState.THINKING)
    print("Turn 4 in THINKING state. Triggering PTT interruption...", flush=True)

    # Interrupt by pressing PTT!
    voice_loop.ptt.press()
    await wait_for_state(AgentState.LISTENING)
    print(f"Turn 4 interrupted! State is now: {state_machine.current_state}", flush=True)
    assert state_machine.current_state == AgentState.LISTENING
    assert live_session.is_connected  # Connection MUST be preserved!

    # Speak new command during the new LISTENING turn
    print("Speaking new replacement command...", flush=True)
    await live_session.send_text("Cancel that. Just say 'Acknowledged, sir'.")
    voice_loop.ptt.release()
    await wait_for_state(AgentState.THINKING)

    turn4_ok = await wait_for_idle(timeout=10.0)
    print(f"TURN 4 completed: {turn4_ok}, Current state: {state_machine.current_state}", flush=True)
    assert turn4_ok
    assert state_machine.current_state == AgentState.IDLE
    assert live_session.is_connected

    # -------------------------------------------------------------
    # TURN 5: PTT -> speak -> release -> normal response -> IDLE
    # -------------------------------------------------------------
    print("\n--- TURN 5: Normal post-interruption turn ---", flush=True)
    voice_loop.ptt.press()
    await wait_for_state(AgentState.LISTENING)
    assert state_machine.current_state == AgentState.LISTENING

    await live_session.send_text("Final test: are you operational? Answer yes or no.")
    voice_loop.ptt.release()
    await wait_for_state(AgentState.THINKING)

    turn5_ok = await wait_for_idle(timeout=10.0)
    print(f"TURN 5 completed: {turn5_ok}, Current state: {state_machine.current_state}", flush=True)
    assert turn5_ok
    assert state_machine.current_state == AgentState.IDLE
    assert live_session.is_connected

    print("\nShutting down voice loop cleanly...", flush=True)
    await voice_loop.stop()
    assert not voice_loop.is_running
    assert live_session.session_state == SessionState.CLOSED
    print("Session state after stop:", live_session.session_state, flush=True)
    print("\n=== ALL 5 TURNS COMPLETED SUCCESSFULLY ON PERSISTENT LIVE SESSION! ===", flush=True)
    return True


if __name__ == "__main__":
    success = asyncio.run(run_five_turn_test())
    sys.exit(0 if success else 1)
