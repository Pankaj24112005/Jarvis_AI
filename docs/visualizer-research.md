# JARVIS Visualizer & UI Subsystem: Architecture & Technology Research

**Author:** JARVIS Architecture Team  
**Phase:** Phase 5 — Visualizer / UI Subsystem  
**Date:** September 2026  
**Status:** Design & Research (Pre-Implementation Review)

---

## 1. Requirements

The JARVIS Visualizer is a presentation and observability layer designed to provide a real-time, responsive visual representation of the agent's internal operations without altering the underlying core intelligence.

### 1.1 Functional Requirements
1. **Real-Time State Indication**: Faithfully display all discrete states from `AgentState`:
   * `IDLE`: Resting / standby state with calm, ambient pulsing.
   * `LISTENING`: Active audio capture state with responsive microphone wave / ring expansion.
   * `THINKING`: Model reasoning state with rapid orbital rotation / quantum processing animation.
   * `SPEAKING`: Voice playback state with audio-reactive waveform / energy pulse.
   * `TOOL_EXECUTION`: Active computer or tool operation with live tool badge and execution telemetry.
   * `WAITING_FOR_PERMISSION`: High-visibility alert for Level 3/4 security actions requiring human authorization.
   * `INTERRUPTED`: Immediate visual response to user barge-in (<35ms).
   * `RECONNECTING`: Connection recovery indicator showing retry attempts.
   * `ERROR`: Clear diagnostic alert displaying the failure reason.
2. **Audio & Voice Status Telemetry**:
   * Visual indicator of Push-to-Talk (PTT) status (Key held vs released).
   * Visualizer representation of audio activity (inbound microphone input & outbound 24kHz speaker stream).
3. **Tool Execution & Permission Observability**:
   * Display name of active tool, arguments (sanitized), and execution status (`REQUESTED`, `EXECUTED`, `FAILED`).
   * Visual prompt for Level 3/4 permissions with "ALLOW" and "DENY" interactive signals.
4. **Memory & Workspace Context Overview**:
   * Telemetry widget showing active workspace, active task summary (Working Memory), and memory facts count.
5. **Decoupled Lifecycle**:
   * The visualizer must be 100% decoupled from the agent. If the visualizer crashes, closes, or disconnects, the agent, voice loop, and tools must continue functioning without interruption.
   * Conversely, starting the visualizer must not spawn a secondary AI or duplicate state logic.

### 1.2 Non-Functional Requirements
1. **Framerate & Fluidity**: 60 FPS rendering for organic animations (particle streams, glowing neon arcs, pulsating cores).
2. **Low Overhead**: Must consume < 2% CPU and < 100 MB RAM on the host machine to prevent starving the Gemini Live audio streaming loop and real-time PTT processing.
3. **Latency**: Visual state transitions must register in < 50ms from `EventBus` emission.
4. **Modularity**: Strict separation of concerns via the Adapter Pattern:
   $$\text{JARVIS Core} \longrightarrow \text{EventBus} \longrightarrow \text{VisualizerAdapter} \longrightarrow \text{UI/Animation Layer}$$
5. **Windows Desktop Ergonomics**: Support for clean desktop presentation, borderless windowing, and optional always-on-top HUD display.

---

## 2. Candidate Technologies

We investigated six candidate approaches for building the Windows desktop JARVIS visualizer:

1. **PySide6 / Qt 6 (C++ bindings via Qt for Python)**
2. **PyQt5 (Qt 5.15.2 / PyQt 5.15.11 — currently installed)**
3. **Tkinter (Python standard library)**
4. **Pygame (SDL2 — currently installed)**
5. **Web-Based Local UI (FastAPI 0.136.1 + WebSocket + HTML5 Canvas / WebGL — currently installed)**
6. **Lightweight Desktop Web Wrappers (`pywebview` / CEF / Electron / Tauri)**

---

## 3. Technology Comparison Matrix

| Evaluation Criteria | PyQt5 (Installed) | PySide6 | Tkinter (Built-in) | Pygame (Installed) | Web-Based HUD (FastAPI + WebGL/Canvas) | pywebview / Tauri |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Animation Capability** | Good (QPainter/QML) | High (QML/QtQuick3D) | Poor (Primitive Canvas) | High (Direct 2D) | **Exceptional** (Canvas 2D, WebGL, CSS3) | Exceptional |
| **Aesthetic Quality ("WOW" Factor)** | Medium-High | High | Very Low (Dated) | Medium (Geometric) | **Cinema-Grade** (Glow, Bloom, Shaders) | Cinema-Grade |
| **Window Transparency** | Native (WA_Translucent) | Native | Poor / Flickery | Difficult on Windows | Requires browser app mode or wrapper | Native |
| **Always-On-Top Support** | Native (WindowStaysOnTop) | Native | Native | Difficult | Browser window / PWA mode | Native |
| **Asyncio Event Loop Integration** | Complex (Requires thread bridge / qasync) | Complex (Requires thread bridge) | Polling `after()` | Manual loop polling | **Native** (FastAPI runs inside asyncio event loop) | Multi-process / IPC |
| **CPU Impact on Python** | Moderate (5-15% on QPainter) | Moderate (4-12%) | Low (1-3%) | High if unthrottled (10-25%) | **Negligible (<0.5% in Python)** (GPU rendered in browser) | Low-Moderate |
| **RAM Footprint** | ~90 - 150 MB | ~120 - 200 MB | ~20 - 35 MB | ~40 - 70 MB | **~25 MB backend + browser tab** | ~120 - 250 MB |
| **Environment Availability** | **Installed** (5.15.11) | **Not Installed** | **Installed** | **Installed** (2.6.1) | **Installed** (`fastapi`, `uvicorn`, `websockets`) | **Not Installed** |
| **Maintainability & UI Velocity** | Moderate (Verbose Qt boilerplate) | Moderate | High initial / Poor scale | Poor (manual layouts) | **High** (Declarative HTML/CSS/JS, reusable shaders) | High |
| **Risk of Crashing Agent Loop** | Moderate (Qt thread crashes kill process) | Moderate | Low | Moderate | **Zero** (Isolated across WebSocket boundary) | Low |

---

## 4. Recommended Technology: FastAPI + WebSocket + Cybernetic HTML5 Canvas / WebGL HUD

### The Decision
We recommend **FastAPI / WebSocket Server with a Hardware-Accelerated HTML5 Canvas / WebGL Cybernetic HUD**, paired with an optional **Standalone Chrome App Mode Window** (`chrome.exe --app=http://localhost:8000`).

---

## 5. Why It Fits This Project

1. **Already 100% Installed and Validated in Current Runtime**:
   * `fastapi` 0.136.1, `uvicorn` 0.46.0, and `websockets` 15.0.1 are pre-installed in the active environment.
   * No heavy dependencies (like PySide6's 300MB download) or native C++ compilers required.
2. **Absolute Event Loop Harmony with Python `asyncio`**:
   * JARVIS is architected from the ground up on `asyncio` (`JarvisAgent`, `GeminiLiveVoiceSession`, `EventBus`, `StateMachine`).
   * FastAPI runs natively inside the existing `asyncio` event loop. It does not require `qasync`, cross-thread locking, or `pyqtSignal` marshaling.
3. **Zero Python CPU Starvation for Voice & Gemini Live**:
   * High-framerate graphics (60 FPS particles, rotating holographic rings, glowing neon shaders) run entirely inside the client browser engine powered by the user's GPU.
   * Python only serializes lightweight JSON state diffs (~500 bytes per event). Python CPU utilization for the visualizer remains under **0.5%**, ensuring zero audio jitter or voice dropouts.
4. **Cinematic JARVIS Visual Aesthetics**:
   * Replicating the authentic Marvel Iron Man "Arc Reactor" / "Stark Industries holographic console" in Qt or Tkinter requires thousands of lines of low-level geometric math and shader bindings.
   * In WebGL / HTML5 Canvas + CSS, we achieve true bloom, glowing cyan particle fields, rotating concentric glyphs, SVG vector scaling, and audio spectrum visualizers effortlessly.
5. **Fault Isolation (Immunity from GUI Crashes)**:
   * If a desktop GUI window crashes in PyQt, the entire Python interpreter process often terminates, killing the voice session and agent.
   * With the WebSocket architecture, if the user closes the browser or refreshes the page, the backend VisualizerAdapter simply notes the client disconnection and JARVIS continues running seamlessly.

---

## 6. Proposed Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        JARVIS SYSTEM CORE                              │
│                                                                        │
│   ┌────────────────┐   Transitions    ┌────────────────────────────┐  │
│   │  JarvisAgent   │ ───────────────> │  Deterministic StateMachine│  │
│   └────────────────┘                  └─────────────┬──────────────┘  │
│           │                                         │                 │
│           │ Submits Tools & Context                 │ State Events    │
│           ▼                                         ▼                 │
│   ┌────────────────┐                  ┌────────────────────────────┐  │
│   │ ToolRegistry & │                  │                            │  │
│   │ MemoryManager  │                  │     Async EventBus         │  │
│   └───────┬────────┘                  │  (jarvis.events.EventBus)  │  │
│           │ Tool / Memory Events      │                            │  │
│           └─────────────────────────> │                            │  │
│                                       └─────────────┬──────────────┘  │
└─────────────────────────────────────────────────────┼──────────────────┘
                                                      │ Subscribes to events
                                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    VISUALIZER ADAPTER SUBSYSTEM                        │
│                     (jarvis.visualizer.adapter)                        │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                    VisualizerAdapter                           │   │
│   │  - Subscribes to EventBus wildcard ("*")                       │   │
│   │  - Maintains cached visual state snapshot                      │   │
│   │  - Debounces high-frequency audio telemetry (<30ms)            │   │
│   │  - Emits normalized JSON frames to connected WebSockets        │   │
│   └────────────────────────────────┬───────────────────────────────┘   │
│                                    │                                   │
│                                    ▼                                   │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                   FastAPI / Uvicorn Server                     │   │
│   │  - Endpoint: GET / (Serves Cybernetic HUD Static Assets)       │   │
│   │  - Endpoint: WS /ws/telemetry (Bidirectional WebSocket)        │   │
│   │  - Endpoint: POST /api/permission (Approve/Deny from UI)       │   │
│   └────────────────────────────────┬───────────────────────────────┘   │
└────────────────────────────────────┼───────────────────────────────────┘
                                     │ WebSocket Stream (ws://127.0.0.1:8000/ws/telemetry)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      CYBERNETIC HUD FRONT-END                          │
│               (HTML5 Canvas / WebGL / CSS3 / Vanilla JS)               │
│                                                                        │
│   ┌───────────────────────┐ ┌──────────────────────┐ ┌───────────────┐ │
│   │   Arc Reactor Core    │ │   Orbital Rings &    │ │ Tool Radar &  │ │
│   │  (WebGL / 2D Canvas)  │ │   Particle Emitters  │ │ Permission HUD│ │
│   │  - State Color Shifts │ │  - Rotation Speed    │ │ - Live Action │ │
│   │  - Audio-Reactive     │ │  - Particle Density  │ │ - Prompt Modal│ │
│   └───────────────────────┘ └──────────────────────┘ └───────────────┘ │
│                                                                        │
│   Display Modes:                                                       │
│   - Desktop App Mode: `chrome.exe --app=http://127.0.0.1:8000 ...`     │
│   - Browser Tab HUD: Any modern browser (Chrome, Edge, Firefox)        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Event and State Mapping

The `VisualizerAdapter` maps internal events directly to front-end visual states:

| AgentState / Event | Visualizer UI Manifestation | Color Palette | Animation Behavior |
| :--- | :--- | :--- | :--- |
| **`IDLE`** | Standby HUD | Electric Cyan (`#00f0ff`) | Slow ambient breathing pulse (0.5 Hz), idle concentric ring drift. |
| **`LISTENING`** | Voice Input Active | Neon Azure (`#0099ff`) | Core expands outward; mic audio waves radiate from center; PTT badge illuminates. |
| **`THINKING`** | Model Reasoning Active | Quantum Gold (`#ffb700`) | Concentric orbital rings counter-rotate at high velocity; central glyph spins; data stream cascade. |
| **`SPEAKING`** | Voice Playback Active | Vibrant Emerald (`#00ff88`) | Audio-reactive waveform pulses dynamically to model speech cadence; outer ring shockwaves. |
| **`TOOL_EXECUTION`** | Tool Pipeline Active | Cyber Magenta (`#d900ff`) | Radar scan sweeps; active tool badge displays with argument preview and duration timer. |
| **`WAITING_FOR_PERMISSION`**| Security Confirmation | High-Alert Crimson (`#ff2a4b`) | Urgent pulsing alert ring; glowing warning perimeter; interactive **ALLOW / DENY** modal buttons. |
| **`INTERRUPTED`** | Barge-In Cut-off | Bright Sapphire (`#0044ff`) | Instant visual contraction shockwave (<35ms), immediate smooth transition to `LISTENING`. |
| **`RECONNECTING`** | Session Recovery | Amber Warning (`#ff7700`) | Intermittent strobe; spinning reconnect sync icon; retry attempt counter displayed. |
| **`ERROR`** | Fault Condition | Severe Red (`#ff0033`) | Core fractures / glitch effect; error description badge with auto-dismiss countdown. |

---

## 8. UI Layout Concept

The HUD is designed as a modular, cinema-grade cybernetic console:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ [JARVIS HUD v5.0]           STATUS: [SPEAKING]           GEMINI: 3.1 FLASH LIVE │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌────────────────────┐   ┌───────────────────────────┐   ┌────────────────┐   │
│   │ TELEMETRY WIDGET   │   │     ARC REACTOR CORE      │   │ TOOL RADAR     │   │
│   │                    │   │                           │   │                │   │
│   │ • State: SPEAKING  │   │        /─────────\        │   │ Active:        │   │
│   │ • Voice: Charon    │   │      /   .-*~*-.   \      │   │ filesystem_read│   │
│   │ • Model: 3.1-Live  │   │     /   /   |   \   \     │   │                │   │
│   │ • PTT: [RELEASED]  │   │    |   |  ( O )  |   |    │   │ Level: 1 (SAFE)│   │
│   │ • Audio Out: 24kHz │   │     \   \   |   /   /     │   │ Duration: 42ms │   │
│   │ • Uptime: 00:14:22 │   │      \   `-._.-'   /      │   │                │   │
│   └────────────────────┘   │        \─────────/        │   └────────────────┘   │
│                            │                           │                        │
│   ┌────────────────────┐   │   Audio Reactive Pulse    │   ┌────────────────┐   │
│   │ MEMORY CONTEXT     │   │      60 FPS WebGL         │   │ SECURITY GATE  │   │
│   │                    │   └───────────────────────────┘   │                │   │
│   │ • Short-term: 4 trn│                                   │ Threshold: 3   │   │
│   │ • Working: None    │   ─────────────────────────────   │ Status: SECURE │   │
│   │ • Facts: 12 cached │   SPECTRUM: |||||||||||||||||||   │ Logs: audit.log│   │
│   └────────────────────┘                                   └────────────────┘   │
│                                                                                 │
│  [CONSOLE LOG]: Voice response completed: "All systems online and operational." │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Animation Strategy

1. **Procedural Geometry (HTML5 Canvas 2D + CSS3 Filters)**:
   * **Concentric Rings**: Rendered mathematically via Canvas `arc()`, rotating with independent angular velocities:
     $$\theta_i(t) = \omega_i \cdot t + \phi_i$$
   * **Particle Field**: 150 floating dust/energy particles responding to core attraction forces and state energy levels.
   * **Glow & Bloom**: CSS `drop-shadow` filters combined with canvas `shadowBlur` and composite operations (`lighter`) create deep holographic light dispersion.
2. **Audio-Reactive Modulation**:
   * The `VOICE_AUDIO_CHUNK` and playback state feed an envelope follower calculating dynamic amplitude ($A \in [0.0, 1.0]$).
   * Ring radius, particle emission speed, and core luminescence expand dynamically proportional to $A$.
3. **Smooth State Transitions**:
   * Color transitions use linear interpolation (LERP) in RGB color space over 250ms, ensuring state changes feel organic rather than abrupt.

---

## 10. Performance Considerations

* **CPU Offloading**: The entire rendering engine runs on the client browser utilizing hardware GPU acceleration via `requestAnimationFrame`.
* **Telemetry Throttling**: While the Canvas runs at 60 FPS, the backend WebSocket adapter only transmits state transitions immediately, and throttles continuous telemetry (audio energy, logs) to 25–30 Hz (33ms intervals), saving network stack and serialization CPU.
* **Payload Size**: Telemetry payloads are concise JSON objects under 500 bytes.
* **No Blocking Calls**: All FastAPI and WebSocket handlers use native `async`/`await` without any synchronous thread blocking.

---

## 11. Security Considerations

1. **Local-Only Binding**: The visualizer server binds strictly to `127.0.0.1` (loopback). It is **not** exposed to the local network or external interfaces.
2. **Secret Redaction**: Arguments displayed in the UI pass through the existing `_SECRET_PATTERN` sanitizer, ensuring API keys, tokens, or passwords are never visible on the screen or in WebSocket frames.
3. **Interactive Permission Gating**: If the user approves or denies a Level 3/4 action via the UI, the decision is signed with a unique one-time token (`request_id`) and validated by the `PermissionController`.

---

## 12. Failure Handling & Resilience

1. **Browser Refresh / Disconnect**: If the client window is refreshed or closed, the server cleans up the WebSocket connection cleanly (`websockets.exceptions.ConnectionClosed`). The core agent experiences zero side effects.
2. **Port Conflict**: Configurable port via `Settings.web_hud_port` (default: `8000`), with automatic fallback to `8001`, `8002` if port 8000 is occupied.
3. **Core Crash Isolation**: If an unhandled error occurs in the visualizer client script, a client-side error boundary displays a discreet reconnect prompt without impacting JARVIS.

---

## 13. Dependencies

* **Backend Requirements (Already Installed in Active Environment)**:
  * `fastapi`: `0.136.1`
  * `uvicorn`: `0.46.0`
  * `websockets`: `15.0.1`
* **Front-End Requirements**:
  * Pure Vanilla JavaScript (ES6+), HTML5, and CSS3.
  * Zero external npm packages, zero Node build steps, zero bloated client frameworks (React/Vue/Webpack).
  * 100% self-contained local static assets served directly by FastAPI.

---

## 14. Implementation Phases

* **Phase 5.1: Visualizer Core & WebSocket Adapter**
  * Implement `jarvis/visualizer/adapter.py` connecting `EventBus` to WebSocket clients.
  * Implement `jarvis/visualizer/server.py` launching FastAPI in background task or CLI.
* **Phase 5.2: Cybernetic HUD UI Front-End**
  * Build responsive HTML5 Canvas Arc Reactor interface with 60 FPS animation engine.
  * Implement real-time state transitions and audio-reactive pulsing.
* **Phase 5.3: Telemetry, Tools & Permission Integration**
  * Add tool radar and real-time interactive confirmation cards.
  * Add memory overview and voice status indicators.
* **Phase 5.4: Desktop Ergonomics & CLI Launchers**
  * Add `--hud` option to `cli_voice.py` and dedicated `run_hud.py` launcher.
  * Auto-open in Chrome App mode or default browser.
* **Phase 5.5: Automated Testing & Verification**
  * Unit tests for WebSocket adapter, state serialization, and event routing.
  * End-to-end multi-state test suite.

---

## 15. Risks and Limitations

1. **Browser Window Decorator**: Without a native wrapper like PyQt, standard browser tabs have browser navigation bars.  
   * *Mitigation*: Provide automated launch command with `chrome.exe --app=http://127.0.0.1:8000 --window-size=960,680`, giving a clean, frameless, native-app window appearance.
2. **Desktop Transparency**: Full transparent overlay directly on top of Windows desktop icons requires native windowing (`PyQt5`).  
   * *Mitigation*: The `VisualizerAdapter` is built with a decoupled interface. If a transparent desktop floating widget is desired in the future, a 150-line PyQt5 widget can plug into the exact same WebSocket stream without rewriting any backend code.

