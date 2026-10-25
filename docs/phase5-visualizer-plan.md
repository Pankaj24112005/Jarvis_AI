# Phase 5 Implementation Plan: JARVIS Visualizer & Cybernetic HUD

**Author:** JARVIS Architecture Team  
**Milestone:** Phase 5 — Visualizer Subsystem  
**Date:** September 2026  
**Status:** Proposal (Awaiting User Review)

---

## 1. Objective & Scope

Build the **presentation and visual observability layer** for JARVIS without creating a second AI or altering Phase 4 voice stabilization logic.

The visualizer will:
* Subscribe directly to `jarvis.events.EventBus` and `jarvis.core.state.StateMachine`.
* Expose a high-performance, real-time WebSocket telemetry stream via an embedded FastAPI server.
* Render a cinema-grade 60 FPS Arc Reactor & Cybernetic HUD in HTML5 Canvas / WebGL.
* Display real-time states (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `TOOL_EXECUTION`, `WAITING_FOR_PERMISSION`, `INTERRUPTED`, `RECONNECTING`, `ERROR`).
* React to audio stream activity and Push-to-Talk (PTT) status.
* Provide an interactive, secure human approval modal for Level 3/4 tools.
* Shut down cleanly alongside the agent with zero resource leaks.

---

## 2. Directory & Component Structure

```
jarvis/
├── visualizer/
│   ├── __init__.py               # Exports VisualizerAdapter, create_visualizer_app
│   ├── base.py                   # Data schemas (TelemetryFrame, VisualizerSnapshot)
│   ├── adapter.py                # EventBus -> WebSocket bridge & snapshot caching
│   ├── server.py                 # FastAPI application, static mounting & WebSocket route
│   └── static/
│       ├── index.html            # Cybernetic HUD layout & Canvas mounting points
│       ├── style.css             # Glassmorphism, holographic neon styling, responsive HUD
│       └── app.js                # 60 FPS procedural Arc Reactor canvas, audio reactivity
├── config.py                     # Adds WEB_HUD_PORT (default 8000), WEB_HUD_AUTO_OPEN
cli_voice.py                      # Adds --hud option to launch visualizer alongside voice
run_hud.py                        # Standalone launcher for the visualizer HUD
tests/
└── test_visualizer.py            # Unit & integration tests for adapter, server, websockets
```

---

## 3. Step-by-Step Implementation Breakdown

### Step 1: Telemetry Data Contracts & Base Schemas (`jarvis/visualizer/base.py`)
* Define `TelemetryFrameType` (`STATE_CHANGE`, `AUDIO_ENERGY`, `TOOL_ACTIVITY`, `PERMISSION_ALERT`, `MEMORY_UPDATE`, `SYSTEM_LOG`).
* Define `TelemetryFrame` dataclass / Pydantic model with strict JSON serialization.
* Define `VisualizerSnapshot` capturing current system status (agent state, active voice, active tool, memory turn count, PTT status).
* Sanitize all outgoing telemetry payloads using existing `_SECRET_PATTERN` from `jarvis.security.permissions`.

### Step 2: EventBus Adapter (`jarvis/visualizer/adapter.py`)
* Create `VisualizerAdapter`:
  * Takes `event_bus: EventBus`, `state_machine: StateMachine`, `permission_controller: PermissionController`, and `memory_manager: MemoryManager`.
  * Subscribes to:
    * `EventType.AGENT_STATE_CHANGED`
    * `EventType.VOICE_SPEECH_STARTED`, `VOICE_SPEECH_ENDED`, `VOICE_AUDIO_CHUNK`, `VOICE_INTERRUPTED`, `VOICE_RECONNECTING`, `VOICE_PLAYBACK_STARTED`, `VOICE_PLAYBACK_FINISHED`
    * `EventType.TOOL_REQUESTED`, `EventType.TOOL_EXECUTED`, `EventType.TOOL_FAILED`
    * `EventType.PERMISSION_REQUESTED`, `EventType.PERMISSION_GRANTED`, `EventType.PERMISSION_DENIED`
    * `EventType.ERROR_OCCURRED`
  * Maintains thread-safe set of connected `WebSocket` clients.
  * Throttles audio amplitude events to 30 Hz to avoid flooding WebSockets while transmitting state transitions immediately.
  * Provides `get_snapshot()` for instant hydration upon new WebSocket client connection.

### Step 3: FastAPI Server & WebSocket Hub (`jarvis/visualizer/server.py`)
* Create `create_visualizer_app(adapter: VisualizerAdapter) -> FastAPI`.
* Routes:
  * `GET /`: Serves `static/index.html`.
  * `GET /api/snapshot`: Returns full JSON state snapshot.
  * `POST /api/permission`: Endpoint allowing user to click "Approve" or "Deny" directly from the HUD.
  * `WS /ws/telemetry`: Persistent bidirectional WebSocket streaming real-time telemetry frames.
* Background Server Runner:
  * `VisualizerServer` class with `start()`, `stop()`, and `is_running`.
  * Can run either as an `asyncio.Task` inside an existing event loop (e.g. `cli_voice.py`) or as a standalone process via `uvicorn.Server`.
  * Port fallback mechanism: if `8000` is busy, tries `8001`, `8002` automatically.

### Step 4: Cybernetic HUD Front-End (`jarvis/visualizer/static/`)
* **`index.html`**:
  * Concentric circular Canvas container for the Arc Reactor core.
  * Floating telemetry cards: System State, Active Model/Voice, Tool Radar, Memory Context, Audio Spectrum Bar.
  * Modal dialog for interactive Level 3/4 permission confirmations.
* **`style.css`**:
  * Deep sci-fi dark palette (`#080c14` background, translucent `#0f172a` glass panels with `backdrop-filter: blur(12px)`).
  * State-driven accent variables (`--theme-color`: Cyan for IDLE, Gold for THINKING, Emerald for SPEAKING, Magenta for TOOL, Crimson for PERMISSION).
  * Monospace cybernetic typography, glowing borders, and smooth transitions.
* **`app.js`**:
  * WebSocket manager with automatic reconnection on disconnect.
  * Procedural 2D Canvas Arc Reactor:
    * 3 concentric geometric rings rotating at speeds proportional to agent activity.
    * Central pulsing core expanding with speech and microphone energy.
    * 120 orbital ambient particles swirling with physics attraction.
  * Tool execution panel displaying tool name, runtime counter, and success/error badges.
  * Interactive Permission Modal submitting POST request back to `/api/permission`.

### Step 5: Integration & CLI Launchers
* Add `--hud` flag to [`cli_voice.py`](file:///d:/my%20work/Jarves%20gemini/cli_voice.py):
  * When enabled, starts `VisualizerServer` alongside `VoiceLoop`.
  * Automatically attempts to open Chrome App mode (`chrome.exe --app=http://127.0.0.1:8000 --window-size=960,680`) or falls back to `webbrowser.open()`.
* Create `run_hud.py`:
  * Standalone CLI to launch the visualizer independently for monitoring or development.
* Update [`jarvis/config.py`](file:///d:/my%20work/Jarves%20gemini/jarvis/config.py):
  * Add `web_hud_port: int = 8000`.
  * Add `web_hud_auto_open: bool = True`.

### Step 6: Automated Testing & Verification (`tests/test_visualizer.py`)
* Test suite verifying:
  1. `test_adapter_initialization_and_snapshot`: Checks initial state snapshot accuracy.
  2. `test_adapter_state_change_event_broadcast`: Dispatches `AGENT_STATE_CHANGED` and verifies WebSocket payload formatting.
  3. `test_adapter_voice_events`: Dispatches audio chunks, PTT events, and verifies throttled telemetry.
  4. `test_adapter_tool_events`: Dispatches tool requests and executions; checks argument sanitization.
  5. `test_permission_ui_resolution`: Verifies HTTP approval endpoint signals `PermissionController`.
  6. `test_websocket_connect_and_disconnect`: Verifies client connection lifecycle and clean cleanup on disconnect.
  7. `test_server_graceful_shutdown`: Confirms uvicorn server shuts down cleanly without hanging tasks.
* Run full regression test suite: `python -m pytest tests/ -v` to ensure all 77 pre-existing tests continue to pass.

---

## 4. Verification & Acceptance Criteria

1. **Architecture Integrity**:
   * Zero model calls or reasoning logic inside the visualizer subsystem.
   * Visualizer only consumes events; it does not dictate agent state.
2. **State Fidelity**:
   * All 9 discrete agent states visually distinct with correct color, rotation, and particle behavior.
3. **Audio Reactivity**:
   * Core reacts visibly when user holds PTT and speaks.
   * Core pulses in sync with 24kHz speaker audio playback.
4. **Interruption Response**:
   * Pressing PTT during playback immediately cuts off the speaking animation and transitions to listening in < 35ms.
5. **Stability & Test Coverage**:
   * 100% automated test pass rate with new visualizer test suite added to the existing 77 tests.
   * Zero memory leaks or hanging async tasks on shutdown.

