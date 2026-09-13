"""Main entry point for JARVIS - Interactive CLI text interface."""

import asyncio
import sys
from typing import AsyncIterator
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from jarvis.config import Settings, get_settings
from jarvis.core.agent import JarvisAgent
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import Event, EventType, default_event_bus
from jarvis.models.base import AIProvider, ModelResponse
from jarvis.models.gemini import GeminiConfigurationError, GeminiProvider
from jarvis.utils.logging import logger

console = Console()


class MockAIProvider(AIProvider):
    """Local simulation provider when no Gemini API key is configured."""

    async def generate(self, prompt: str, system_instruction: str | None = None, **kwargs) -> ModelResponse:
        await asyncio.sleep(0.3)
        clean = prompt.strip().split("\n")[-1]
        if "hello" in clean.lower():
            text = "Hello! I am JARVIS (Simulation Mode). All core systems are operational."
        elif "time" in clean.lower():
            import datetime
            text = f"The current system time is {datetime.datetime.now().strftime('%H:%M:%S')}."
        elif "diagnostic" in clean.lower():
            text = (
                "System Diagnostic Report (Simulation):\n"
                "• Core Agent: ONLINE\n"
                "• State Machine: ONLINE\n"
                "• Event Bus: ONLINE\n"
                "• Model Provider: Mock Simulation (Set GEMINI_API_KEY in .env for live Gemini)"
            )
        else:
            text = (
                f"I acknowledge your input: '{clean}'. "
                "I am currently operating in offline simulation mode. "
                "Add your GEMINI_API_KEY to .env to enable full Gemini intelligence."
            )
        return ModelResponse(text=text)

    async def stream(self, prompt: str, system_instruction: str | None = None, **kwargs) -> AsyncIterator[str]:
        res = await self.generate(prompt, system_instruction, **kwargs)
        for word in res.text.split(" "):
            yield word + " "
            await asyncio.sleep(0.05)

    async def generate_with_tools(self, prompt: str, tools: list, **kwargs) -> ModelResponse:
        return await self.generate(prompt, **kwargs)

    async def analyze_image(self, prompt: str, image_bytes: bytes, **kwargs) -> ModelResponse:
        return ModelResponse(text="[Image received in simulation mode]")

    async def create_embedding(self, text: str, **kwargs) -> list[float]:
        return [0.0] * 768


def render_banner(settings: Settings, is_live: bool) -> None:
    """Display the JARVIS startup banner."""
    status_str = "[bold green]LIVE (Gemini Connected)[/bold green]" if is_live else "[bold yellow]SIMULATION MODE (Missing API Key)[/bold yellow]"
    grid = Table.grid(padding=1)
    grid.add_column()
    grid.add_row(f"[bold cyan]J A R V I S[/bold cyan]  |  [dim]Personal AI Operating Layer[/dim]")
    grid.add_row(f"Status: {status_str}  •  Model: [cyan]{settings.gemini_primary_model}[/cyan]")
    grid.add_row("[dim]Type 'help' for commands, or 'exit' / 'quit' to close.[/dim]")

    console.print(Panel(grid, border_style="cyan", expand=False))


async def run_cli() -> None:
    """Run the interactive command-line session."""
    settings = get_settings()

    # Determine provider (Live Gemini vs Mock)
    is_live = False
    ai_provider: AIProvider

    if settings.is_gemini_configured:
        try:
            ai_provider = GeminiProvider(
                api_key=settings.get_gemini_api_key(),
                primary_model=settings.gemini_primary_model,
                fast_model=settings.gemini_fast_model,
                embedding_model=settings.gemini_embedding_model,
            )
            is_live = True
        except GeminiConfigurationError as ex:
            console.print(f"[yellow]Warning:[/yellow] {ex}")
            ai_provider = MockAIProvider()
    else:
        ai_provider = MockAIProvider()

    agent = JarvisAgent(ai_provider=ai_provider, settings=settings)

    render_banner(settings, is_live)

    if not is_live:
        console.print(
            Panel(
                "[bold yellow]Notice: GEMINI_API_KEY is not set in your .env file.[/bold yellow]\n\n"
                "To connect live Google Gemini:\n"
                " 1. Open or create [bold].env[/bold] in this directory.\n"
                " 2. Set [bold]GEMINI_API_KEY=your_key_here[/bold]\n"
                " 3. Restart JARVIS.\n\n"
                "[dim]Running in offline Simulation Mode for now. All agent state transitions work normally.[/dim]",
                border_style="yellow",
                expand=False,
            )
        )

    # Subscribe to state transitions for real-time visual feedback in console
    def on_state_change(event: Event) -> None:
        new_state = event.data.get("new_state", "")
        old_state = event.data.get("old_state", "")
        if settings.debug:
            console.print(f"[dim](State: {old_state} -> {new_state})[/dim]")

    default_event_bus.subscribe(EventType.AGENT_STATE_CHANGED, on_state_change)

    while True:
        try:
            user_input = Prompt.ask(f"[bold green]{settings.user_name}[/bold green]").strip()
            if not user_input:
                continue

            # Command interceptors
            cmd = user_input.lower()
            if cmd in ("exit", "quit", "q"):
                console.print(f"[cyan]{settings.jarvis_name}:[/cyan] Goodbye, {settings.user_name}.")
                break
            elif cmd == "clear":
                agent.clear_history()
                console.print("[dim]Conversation history cleared.[/dim]")
                continue
            elif cmd == "state":
                console.print(f"[dim]Current Agent State: {agent.current_state.value}[/dim]")
                continue
            elif cmd == "help":
                console.print(
                    "[bold]Available Commands:[/bold]\n"
                    " • [cyan]exit[/cyan] / [cyan]quit[/cyan]: Exit JARVIS\n"
                    " • [cyan]clear[/cyan]: Clear conversation buffer\n"
                    " • [cyan]state[/cyan]: Show current agent state\n"
                    " • [cyan]help[/cyan]: Display this help message"
                )
                continue

            # Process turn with spinner
            with console.status(f"[cyan]{settings.jarvis_name} is thinking...[/cyan]", spinner="dots"):
                response_text = await agent.process_user_input(user_input)

            console.print(f"[bold cyan]{settings.jarvis_name}:[/bold cyan] {response_text}\n")

        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[cyan]{settings.jarvis_name}:[/cyan] Session terminated. Goodbye, {settings.user_name}.")
            break
        except Exception as ex:
            console.print(f"[bold red]An unexpected error occurred:[/bold red] {ex}")


def main() -> None:
    """CLI entry point."""
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
