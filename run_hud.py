"""Standalone development and monitoring launcher for JARVIS Visualizer HUD (Phase 5).

Note: This launcher does NOT create an AI agent or model session. It runs the presentation
server and event adapter independently for UI testing, development, and inspection.
"""

import asyncio
import os
import subprocess
import sys
import webbrowser
from rich.console import Console
from rich.panel import Panel

from jarvis.config import Settings
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType
from jarvis.visualizer.adapter import VisualizerAdapter
from jarvis.visualizer.server import VisualizerServer

console = Console()


def open_hud_browser(url: str) -> None:
    """Attempt to launch Chrome in application window mode or default browser."""
    # Attempt Chrome app mode on Windows for a clean standalone window
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            try:
                subprocess.Popen([p, f"--app={url}", "--window-size=980,720"])
                return
            except Exception:
                pass

    # Fallback to default browser
    try:
        webbrowser.open(url)
    except Exception as ex:
        console.print(f"[yellow]Could not open browser automatically: {ex}[/yellow]")


async def main() -> None:
    settings = Settings()
    host = settings.web_hud_host
    port = settings.web_hud_port

    event_bus = EventBus()
    state_machine = StateMachine(event_bus=event_bus)

    adapter = VisualizerAdapter(
        event_bus=event_bus,
        state_machine=state_machine,
        voice_name=settings.gemini_live_voice,
    )

    server = VisualizerServer(adapter=adapter, host=host, port=port)

    content = (
        "[bold cyan]JARVIS VISUALIZER HUD (STANDALONE RUNNER)[/bold cyan]\n"
        f"[bold green]Server: http://{host}:{port}[/bold green]\n"
        "[bold yellow]Mode: Presentation & Telemetry Observability (No AI agent active)[/bold yellow]\n"
        "[dim]Press [Ctrl+C] to stop server[/dim]"
    )
    console.print(Panel(content, border_style="cyan"))

    try:
        url = await server.start()
        console.print(f"[bold green]HUD online at: {url}[/bold green]")

        if settings.web_hud_auto_open:
            open_hud_browser(url)

        # Keep server running until interrupted
        while server.is_running:
            await asyncio.sleep(0.5)

    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]Shutting down HUD server...[/yellow]")
    finally:
        await server.stop()
        console.print("[dim]HUD server stopped.[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
