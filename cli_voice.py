"""JARVIS Voice Interface CLI Demonstration (Phase 4).

Features:
- Push-to-Talk: Hold [Ctrl+Space] to speak, release to send.
- Gemini Live API: Real-time 16kHz audio input -> 24kHz audio output streaming.
- True Barge-In: Pressing [Ctrl+Space] while JARVIS speaks halts playback immediately.
- Hybrid Fallback: Gracefully switches to turn-based Gemini + TTS if Live is unavailable.
- Live Tool Calling: Voice-invoked tools evaluated through ToolRegistry & PermissionController.
"""

import argparse
import asyncio
import os
import sys
import time
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from jarvis.config import Settings
from jarvis.core.agent import JarvisAgent
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import Event, EventBus, EventType
from jarvis.memory import MemoryManager
from jarvis.models.gemini import GeminiProvider
from jarvis.security.permissions import PermissionController, PermissionLevel
from jarvis.tools import ToolRegistry, register_default_tools
from jarvis.voice.audio_io import PygameAudioInput, PygameAudioOutput
from jarvis.voice.base import VoiceConfig
from jarvis.voice.live_session import GeminiLiveVoiceSession
from jarvis.voice.loop import VoiceLoop
from jarvis.voice.ptt import PTTController
from jarvis.voice.tts import Pyttsx3TTS

console = Console()

_STATE_COLORS = {
    AgentState.IDLE: "bright_black",
    AgentState.LISTENING: "bright_cyan",
    AgentState.THINKING: "bright_yellow",
    AgentState.SPEAKING: "bright_green",
    AgentState.TOOL_EXECUTION: "bright_magenta",
    AgentState.WAITING_FOR_PERMISSION: "bright_red",
    AgentState.INTERRUPTED: "bright_blue",
    AgentState.RECONNECTING: "bright_yellow",
    AgentState.ERROR: "bold red",
}


def print_banner(voice_name: str = "Charon") -> None:
    content = (
        "[bold cyan]JARVIS VOICE INTERFACE (PHASE 4)[/bold cyan]\n"
        "[bold green]Engine: Gemini 3.1 Flash Live Preview (Bidirectional Audio)[/bold green]\n"
        f"[bold blue]Voice: {voice_name} (Informative / Composed)[/bold blue]\n"
        "[bold yellow]Control: Push-to-Talk (Hold [Ctrl+Space] to speak)[/bold yellow]\n"
        "[bold magenta]Interruption: Press [Ctrl+Space] anytime to interrupt playback[/bold magenta]"
    )
    console.print(Panel(content, border_style="cyan"))


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for JARVIS Voice Interface."""
    parser = argparse.ArgumentParser(description="JARVIS Voice Interface CLI")
    parser.add_argument(
        "--voice",
        "-v",
        type=str,
        default=None,
        choices=["Charon", "Orus", "Gacrux", "Puck", "Aoede"],
        help="Gemini Live prebuilt voice (default: Charon)",
    )
    parser.add_argument(
        "--hud",
        action="store_true",
        default=False,
        help="Launch the JARVIS Cybernetic HUD in browser / app window",
    )
    return parser


async def main(custom_voice: str | None = None, enable_hud: bool | None = None) -> None:
    parser = build_parser()
    # Parse known args so test runners or custom callers don't fail
    args, _ = parser.parse_known_args()

    settings = Settings()
    api_key = settings.gemini_api_key.get_secret_value()

    if not api_key:
        console.print("[bold red]ERROR: GEMINI_API_KEY is not configured in .env[/bold red]")
        sys.exit(1)

    selected_voice = custom_voice or args.voice or os.getenv("GEMINI_LIVE_VOICE") or settings.gemini_live_voice or "Charon"
    hud_requested = enable_hud if enable_hud is not None else args.hud
    print_banner(voice_name=selected_voice)

    # Core single sources of truth
    event_bus = EventBus()
    state_machine = StateMachine(event_bus=event_bus)
    permission_controller = PermissionController(confirmation_threshold=int(PermissionLevel.HIGH_RISK))
    tool_registry = ToolRegistry()

    # Register standard built-in tools
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

    # Audio subsystem components behind abstract interfaces
    audio_in = PygameAudioInput(sample_rate=16000, chunk_size=1024)
    audio_out = PygameAudioOutput(sample_rate=24000)
    fallback_tts = Pyttsx3TTS(rate=185)

    voice_config = VoiceConfig(
        live_model="models/gemini-3.1-flash-live-preview",
        input_sample_rate=16000,
        output_sample_rate=24000,
        prebuilt_voice=selected_voice,
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

    # Visual State Observer via EventBus
    def on_state_changed(event: Event) -> None:
        new_state = event.data.get("new_state", "UNKNOWN")
        color = _STATE_COLORS.get(AgentState(new_state) if new_state in AgentState._value2member_map_ else AgentState.IDLE, "white")
        console.print(f"[{color}]* [{new_state}][/{color}]", end=" ")
        sys.stdout.flush()

    event_bus.subscribe(EventType.AGENT_STATE_CHANGED, on_state_changed)

    # Tool Execution Observer
    def on_tool_event(event: Event) -> None:
        tool_name = event.data.get("tool", "")
        if event.type in (EventType.TOOL_REQUESTED, EventType.TOOL_REQUESTED.value):
            console.print(f"\n[bold magenta][TOOL] Voice Tool Invoked: {tool_name}[/bold magenta]")
        elif event.type in (EventType.TOOL_EXECUTED, EventType.TOOL_EXECUTED.value):
            console.print(f"[green][DONE] Tool Completed: {tool_name}[/green]")

    event_bus.subscribe(EventType.TOOL_REQUESTED, on_tool_event)
    event_bus.subscribe(EventType.TOOL_EXECUTED, on_tool_event)

    # Optional Web HUD Subsystem (Phase 5)
    hud_server = None
    if hud_requested:
        try:
            from run_hud import open_hud_browser
            from jarvis.visualizer.adapter import VisualizerAdapter
            from jarvis.visualizer.server import VisualizerServer

            visualizer_adapter = VisualizerAdapter(
                event_bus=event_bus,
                state_machine=state_machine,
                voice_name=selected_voice,
            )
            hud_server = VisualizerServer(
                adapter=visualizer_adapter,
                host=settings.web_hud_host,
                port=settings.web_hud_port,
            )
            hud_url = await hud_server.start()
            console.print(f"[bold green]JARVIS Cybernetic HUD online at: {hud_url}[/bold green]")

            if settings.web_hud_auto_open:
                open_hud_browser(hud_url)

            # Composite approval callback: allow either HUD or CLI to approve safely
            original_cli_prompt = permission_controller.approval_callback

            async def composite_approval_callback(
                tool_name: str, arguments: dict, level: PermissionLevel, desc: str
            ) -> bool:
                req_id, hud_future = visualizer_adapter.create_permission_request(
                    tool_name, arguments, level, desc
                )
                cli_task = asyncio.create_task(
                    original_cli_prompt(tool_name, arguments, level, desc)
                )

                # Wait for either HUD button click or CLI prompt
                done, pending = await asyncio.wait(
                    [hud_future, cli_task], return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()

                result = list(done)[0].result()
                if result:
                    await event_bus.emit(
                        EventType.PERMISSION_GRANTED,
                        {"tool": tool_name, "request_id": req_id},
                    )
                else:
                    await event_bus.emit(
                        EventType.PERMISSION_DENIED,
                        {"tool": tool_name, "request_id": req_id},
                    )
                return result

            permission_controller.approval_callback = composite_approval_callback

        except Exception as ex:
            console.print(f"[yellow]Warning: Could not launch Visualizer HUD: {ex}[/yellow]")

    console.print("[dim]Connecting to Gemini 3.1 Flash Live session...[/dim]")
    try:
        await voice_loop.start()
        console.print("\n[bold green]Ready! Hold [Ctrl+Space] to speak with JARVIS. Press [Ctrl+C] to exit.[/bold green]\n")

        # Keep running until Ctrl+C
        while voice_loop.is_running:
            await asyncio.sleep(0.5)

    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]Shutting down voice loop...[/yellow]")
    finally:
        if hud_server:
            try:
                await hud_server.stop()
            except Exception as ex:
                logger.debug("Error stopping HUD server: %s", ex)
        await voice_loop.stop()
        console.print("[dim]Voice subsystem stopped.[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
