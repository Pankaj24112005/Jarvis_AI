# JARVIS (Just A Rather Very Intelligent System)

<div align="center">

![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)
![Gemini Ecosystem](https://img.shields.io/badge/google--genai-2.8%2B-0284C7.svg)
![Architecture](https://img.shields.io/badge/architecture-event--driven%20%7C%20modular-1D4ED8.svg)
![Tests](https://img.shields.io/badge/test%20suite-220%20passed%20%7C%20100%25-047857.svg)
![Security](https://img.shields.io/badge/security-5--tier%20deterministic%20gating-BE123C.svg)
![License](https://img.shields.io/badge/license-MIT-334155.svg)

**A high-performance, multimodal personal AI operating layer built natively for the Google Gemini ecosystem.**

[Architecture](#system-architecture) • [Key Features](#key-features) • [Quickstart](#quickstart--installation) • [Usage](#usage--entry-points) • [Tool Suite](#standardized-tool-suite-37-tools) • [Task & Verification Engine](#task--workflow-intelligence-phase-8) • [Security](#security--governance) • [Testing](#test-suite--validation)

</div>

---

## Executive Overview

**JARVIS** is an autonomous, multimodal personal AI operating system that bridges the gap between state-of-the-art foundation models and local computer operation. Unlike conventional wrappers or script-based agents, JARVIS operates on a strict software engineering philosophy:

> **"The LLM is the reasoning engine, not the entire system."**

The language model (Google Gemini) provides intelligence, planning, and evaluation, while deterministic software provides finite state management, 5-tier permission enforcement, multi-tier memory indexing, hardware control, anti-loop recovery, and physical outcome verification.

### Core Architectural Invariants

- **Gemini-Native Intelligence**: Deep integration with the official `google-genai` SDK, supporting `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-3.8-flash`, Gemini Live bidirectional WebSockets (16kHz PCM audio in / 24kHz audio out), and 2D spatial visual grounding.
- **Strict Model Abstraction**: All LLM interactions route through an abstract `AIProvider` base class. Future models or local models can be slotted in without modifying core agent logic.
- **Decoupled Asynchronous Event Bus**: The Voice subsystem, Screen Perception, Web HUD, and Tool Executors communicate asynchronously via an in-memory `EventBus`. No subsystem blocks the main event loop.
- **5-Tier Deterministic Security**: High-risk or mutating operations (e.g., terminal commands, process kills, system modifications) pass through a strict `PermissionController` requiring explicit human approval.
- **Outcome-Verified Execution**: *Tool execution success does not equal real-world outcome success.* An evidence-based `StepVerifier` checks actual OS state (active window, visual changes, exit codes) before marking steps complete.
- **Zero-LLM Anti-Loop Recovery**: Failure recovery decisions are 100% deterministic code with tri-state idempotency tables, bounded safety budgets, and A-B-A-B cycle detection.

---

## System Architecture

```mermaid
graph TD
    %% Styling Classes
    classDef clientLayer fill:#0284C7,stroke:#0369A1,stroke-width:2px,color:#FFFFFF;
    classDef agentLayer fill:#1D4ED8,stroke:#1E40AF,stroke-width:2px,color:#FFFFFF;
    classDef memoryLayer fill:#B45309,stroke:#92400E,stroke-width:2px,color:#FFFFFF;
    classDef modelLayer fill:#047857,stroke:#065F46,stroke-width:2px,color:#FFFFFF;
    classDef taskLayer fill:#4338CA,stroke:#3730A3,stroke-width:2px,color:#FFFFFF;
    classDef secLayer fill:#BE123C,stroke:#9F1239,stroke-width:2px,color:#FFFFFF;
    classDef toolLayer fill:#0F766E,stroke:#115E59,stroke-width:2px,color:#FFFFFF;
    classDef envLayer fill:#334155,stroke:#1E293B,stroke-width:2px,color:#FFFFFF;

    subgraph Interaction_Layer["Interaction & Observability Layer"]
        CLI["CLI Interface (main.py)"]:::clientLayer
        Voice["Live Voice Loop (cli_voice.py)"]:::clientLayer
        HUD["Cybernetic HUD (run_hud.py / FastAPI)"]:::clientLayer
    end

    subgraph Core_Orchestration["Core Orchestration & Telemetry"]
        Agent["JarvisAgent (jarvis/core/agent.py)"]:::agentLayer
        StateMachine["StateMachine (jarvis/core/state.py)"]:::agentLayer
        EventBus["Asynchronous EventBus (jarvis/events.py)"]:::agentLayer
    end

    subgraph Memory_Subsystem["5-Tier Cognitive Memory Subsystem"]
        MemMgr["MemoryManager (jarvis/memory/manager.py)"]:::memoryLayer
        ShortTerm["ShortTermMemory (In-memory buffer)"]:::memoryLayer
        Working["WorkingMemory (Task scratchpad)"]:::memoryLayer
        Episodic["EpisodicMemory (SQLite Timeline)"]:::memoryLayer
        Semantic["SemanticMemory (Facts Vault & Embeddings)"]:::memoryLayer
        Project["ProjectMemory (Git & Workspace Context)"]:::memoryLayer
    end

    subgraph Model_Provider["Multimodal Model Layer"]
        Gemini["GeminiProvider (jarvis/models/gemini.py)"]:::modelLayer
        LiveSession["Gemini Live Preview (16k In / 24k Out)"]:::modelLayer
    end

    subgraph Task_Subsystem["Structured Task & Verification Engine (Phase 8)"]
        TaskMgr["TaskManager (jarvis/tasks/manager.py)"]:::taskLayer
        StepExec["StepExecutor (jarvis/tasks/executor.py)"]:::taskLayer
        StepVerif["StepVerifier (jarvis/tasks/verifier.py)"]:::taskLayer
        Recovery["RecoveryPolicy & AntiLoopGuard (jarvis/tasks/recovery.py)"]:::taskLayer
    end

    subgraph Security_Governance["Security & Governance"]
        PermController["PermissionController (5-Tier Gating)"]:::secLayer
        HumanGate["Human Approval Prompt (CLI / HUD)"]:::secLayer
        AuditLog["Sanitized AuditLogger (logs/audit.log)"]:::secLayer
    end

    subgraph Execution_Subsystem["Authoritative Tool Subsystem (37 Built-in Tools)"]
        ToolReg["ToolRegistry (jarvis/tools/registry.py)"]:::toolLayer
        FSTools["FileSystem Tools (read, write, modify, delete, search)"]:::toolLayer
        AppTools["Application Tools (launch, focus, close, terminate)"]:::toolLayer
        CompTools["Computer Tools (mouse, keyboard, shortcuts, screen)"]:::toolLayer
        ScreenTools["Screen Tools (active_window, capture_screen, analyze)"]:::toolLayer
        WebTools["Web & Media Tools (browser, search, fetch, youtube)"]:::toolLayer
    end

    subgraph Workstation_OS["Workstation OS & Environment"]
        OS_Win["Windows Workstation OS"]:::envLayer
        Display["Desktop Display & Active Windows"]:::envLayer
        AudioHw["Microphone & Speaker Hardware"]:::envLayer
    end

    %% Wiring & Dataflow
    CLI -->|Text Prompts| Agent
    Voice -->|16kHz PCM Frames| LiveSession
    LiveSession -->|Tool Call Requests| Agent
    Agent --> StateMachine
    Agent --> EventBus
    EventBus -.->|Broadcast Telemetry| HUD
    EventBus -.->|State Tracking| StateMachine

    Agent -->|Query Context| MemMgr
    MemMgr --> ShortTerm
    MemMgr --> Working
    MemMgr --> Episodic
    MemMgr --> Semantic
    MemMgr --> Project
    MemMgr -->|Augmented Context| Agent

    Agent -->|Generate / Tool Loop| Gemini
    Agent -->|Execute Task Workflows| TaskMgr
    TaskMgr --> StepExec
    StepExec -->|1. Dispatch Tool Request| ToolReg
    ToolReg -->|2. Check Permission Level| PermController
    PermController -->|If Level >= 3| HumanGate
    PermController -->|Sanitized Audit Event| AuditLog
    PermController -->|Authorized Approval| ToolReg

    ToolReg --> FSTools
    ToolReg --> AppTools
    ToolReg --> CompTools
    ToolReg --> ScreenTools
    ToolReg --> WebTools

    FSTools --> OS_Win
    AppTools --> OS_Win
    CompTools --> Display
    ScreenTools --> Display
    LiveSession --> AudioHw

    ToolReg -->|3. Tool Execution Result| StepExec
    StepExec -->|4. Post-Execution Outcome Validation| StepVerif
    StepVerif -->|Sensory Verification (Active Window / OCR)| ScreenTools
    StepVerif -->|Verification Status| StepExec

    StepExec -->|If NOT_VERIFIED| Recovery
    Recovery -->|Idempotency, Budget & Loop Check| StepExec
```

---

## Key Features

### 🎙️ Real-Time Bidirectional Voice & True Barge-In
- **Gemini Live Streaming**: Connects directly to Google Gemini's live audio WebSocket endpoint, ingesting 16kHz PCM microphone audio and streaming back 24kHz synthesized speech.
- **Push-to-Talk (PTT)**: Global hotkey (`Ctrl+Space`) to initiate speech without wake-word false triggers.
- **Zero-Latency Barge-In**: Interrupting JARVIS at any millisecond while speaking immediately cuts off audio playback, resets audio buffers, and processes user speech.
- **Prebuilt Voices**: Configurable voice personality options (`Charon`, `Orus`, `Gacrux`, `Puck`, `Aoede`).
- **Hybrid Fallback**: Gracefully falls back to offline STT (`SpeechRecognition`) and native system TTS (`pyttsx3`) if the live cloud stream is unavailable.

### 🖥️ Desktop Perception & Computer Control
- **Multimodal Screen Analysis**: Captures full-screen frames, crops active windows, and extracts UI layout context.
- **Visual Grounding**: Resolves natural language UI descriptions (e.g. *"Click the blue Submit button"*) into exact `(x, y)` screen coordinates via Gemini Vision spatial understanding.
- **Window Management**: Enumerates running desktop applications, retrieves foreground window titles and process IDs, focuses windows, and executes graceful window closure (`WM_CLOSE`) or forced termination (`SIGTERM`).
- **Input Simulation**: Full programmatic control of mouse clicks, drags, scrolling, text typing, key presses, and multi-key keyboard shortcuts (`PyAutoGUI`).
- **Web Automation**: Built-in Selenium driver and async HTTP scrapers for reading articles, querying search engines, and interacting with browser pages.

### 🧠 5-Tier Cognitive Memory Subsystem
JARVIS stores memories in human-readable, transparent formats (Markdown + SQLite + JSON) without proprietary database lock-in:

| Tier | Module | Storage / Mechanism | Purpose |
| :--- | :--- | :--- | :--- |
| **Short-Term** | `ShortTermMemory` | In-memory sliding window FIFO | Retains recent conversation turns and immediate context. |
| **Working** | `WorkingMemory` | Thread-safe key-value scratchpad | Holds active task state, extracted variables, and transient plans. |
| **Episodic** | `EpisodicMemory` | SQLite (`memory/episodic.db`) | Searchable, chronological log of user sessions, tasks, and historical events. |
| **Semantic** | `SemanticMemory` | JSON vault + `text-embedding-004` | Long-term factual knowledge, user preferences, and habits with cosine vector recall. |
| **Project** | `ProjectMemory` | Markdown (`memory/projects/`) | Git repository context, project guidelines, active task backlog, and tech stacks. |

### 🛡️ 5-Tier Deterministic Security & Governance
Every single tool requested by the model is evaluated before execution against an authoritative risk matrix:

- **Level 0 (Safe)**: Non-mutating read actions (e.g., read file, list dir, get active window). Auto-approved.
- **Level 1 (Low Risk)**: Lightweight benign actions (e.g., web search, mouse move). Auto-approved.
- **Level 2 (Moderate)**: Targeted non-destructive operations (e.g., focus window, take screenshot). Auto-approved.
- **Level 3 (High Risk)**: Mutating modifications (e.g., write file, modify file, launch application, terminal commands). **Requires explicit human confirmation.**
- **Level 4 (Critical)**: Dangerous or irreversible operations (e.g., delete file, kill process, execute arbitrary shell scripts). **Requires explicit human confirmation.**

All actions, parameter inputs, and approval outcomes are sanitized (passwords, tokens, API keys, and binary blobs redacted) and permanently appended to `logs/audit.log`.

### ⚡ Task & Workflow Intelligence (Phase 8)
- **Authoritative Lifecycle Engine**: Multi-step goals are governed by `TaskManager` and `TaskStep` models with formal state transitions (`PENDING` $\to$ `PLANNING` $\to$ `EXECUTING` $\to$ `VERIFYING` $\to$ `COMPLETED`).
- **Outcome Verification Invariant**: `StepVerifier` checks real-world evidence (active window title, foreground process, screen diff, exit code) to confirm whether an action actually succeeded.
- **Zero-LLM Bounded Recovery**: `RecoveryPolicy` enforces an authoritative idempotency matrix (`IDEMPOTENT`, `NON_IDEMPOTENT`, `UNKNOWN`). Non-idempotent actions (clicks, keystrokes, shell scripts) are strictly prevented from auto-retrying.
- **Anti-Loop Guard**: Computes SHA-256 fingerprints of actions and failures to detect recurring errors and immediate A-B-A-B cyclic loops.

### 🌐 Cybernetic Web HUD & Telemetry
- **Reactive Fast-Refresh Interface**: Built with Vanilla CSS, WebGL/Canvas, and WebSockets served via FastAPI and Uvicorn.
- **Live Observability**: Visualizes real-time state waveforms, mic volume, latency metrics, active tools, task progress cards, and system audit events.
- **Browser App Mode**: Automatically launches Chrome in standalone app mode (`--app=http://127.0.0.1:8000`) for a native desktop feel.

---

## Quickstart & Installation

### 1. Prerequisites
- **Operating System**: Microsoft Windows 10/11 (fully tested for OS desktop control and audio hardware).
- **Python**: Python 3.11, 3.12, or 3.13 (64-bit).
- **Google Gemini API Key**: Obtain a key from [Google AI Studio](https://aistudio.google.com/).

### 2. Clone & Environment Setup

```bash
# Clone the repository
git clone https://github.com/your-username/jarvis-gemini.git
cd jarvis-gemini

# Create and activate a virtual environment (optional but recommended)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install google-genai pydantic pydantic-settings python-dotenv rich fastapi uvicorn websockets pyautogui pygetwindow SpeechRecognition pyttsx3 opencv-python pillow selenium httpx requests pygame keyboard pytest pytest-asyncio
```

### 3. Configure Credentials

Copy the example environment template and configure your Gemini API key:

```powershell
cp .env.example .env
```

Edit `.env` with your preferred settings:

```ini
# Google Gemini API Configuration
GEMINI_API_KEY=AIzaSy...your_actual_key_here

# Model Selection
GEMINI_PRIMARY_MODEL=gemini-2.5-flash
GEMINI_FAST_MODEL=gemini-2.0-flash
GEMINI_EMBEDDING_MODEL=text-embedding-004

# Assistant Persona
JARVIS_NAME=JARVIS
USER_NAME=Sir

# Voice & HUD Configuration
VOICE_ENABLED=true
WEB_HUD_ENABLED=true
GEMINI_LIVE_VOICE=Charon

# Security Threshold (0 = Safe, 3 = High Risk confirmation, 4 = Critical)
PERMISSION_CONFIRMATION_THRESHOLD=3
```

---

## Usage & Entry Points

JARVIS provides three dedicated entry points depending on your workflow:

### 1. Interactive Command-Line Chat (`main.py`)
Launch the rich text terminal interface:

```bash
python main.py
```

- Type prompts directly to interact with JARVIS, plan tasks, and execute tools.
- Supports built-in commands: `help`, `status`, `memory`, `clear`, `exit`.
- **Offline Simulation Mode**: If `GEMINI_API_KEY` is omitted, `main.py` automatically initializes `MockAIProvider`, allowing complete testing of CLI commands, state transitions, and tool interfaces without external network access.

### 2. Live Bidirectional Voice Assistant (`cli_voice.py`)
Launch the real-time voice interface powered by Gemini Live:

```bash
# Default voice (Charon)
python cli_voice.py

# Specify voice and simultaneously launch Cybernetic HUD
python cli_voice.py --voice Aoede --hud
```

- **Push-to-Talk**: Hold `Ctrl+Space` to speak; release to transmit.
- **Barge-in Interruption**: Press `Ctrl+Space` anytime while JARVIS is speaking to immediately halt audio output.

### 3. Standalone Cybernetic HUD (`run_hud.py`)
Run the telemetry presentation server independently for testing and UI inspection:

```bash
python run_hud.py
```

Opens `http://127.0.0.1:8000` in Chrome app mode, rendering real-time system metrics, audio visualizer canvas, and event streams.

---

## Standardized Tool Suite (37 Tools)

All tools inherit from `BaseTool`, define typed Pydantic parameters, declare a deterministic `PermissionLevel`, and automatically generate Gemini function-calling schemas:

| Category | Tool Name | Permission Level | Description |
| :--- | :--- | :--- | :--- |
| **Filesystem** | `read_file` | Level 0 (Safe) | Read UTF-8 contents of a local file. |
| | `list_directory` | Level 0 (Safe) | List directory contents with sizes and timestamps. |
| | `search_files` | Level 0 (Safe) | Search files by glob pattern or regex within a directory. |
| | `write_file` | Level 3 (High) | Write complete text content to a destination file. |
| | `modify_file` | Level 3 (High) | Perform targeted multi-line string replacements in a file. |
| | `delete_file` | Level 4 (Critical)| Safely delete an existing file from the filesystem. |
| **Terminal** | `terminal_execute` | Level 4 (Critical)| Execute shell command with timeout and audit logging. |
| **Applications** | `list_running_applications`| Level 0 (Safe) | List active processes and window titles. |
| | `launch_application` | Level 3 (High) | Launch a desktop application executable. |
| | `focus_application` | Level 2 (Moderate)| Bring an application window to the foreground. |
| | `close_application` | Level 3 (High) | Request graceful closure (`WM_CLOSE`) of an application. |
| | `terminate_process` | Level 4 (Critical)| Forcefully terminate a process by PID or name. |
| **Computer Control** | `mouse_move` | Level 1 (Low) | Move the cursor smoothly to `(x, y)` coordinates. |
| | `mouse_click` | Level 2 (Moderate)| Perform left mouse click at optional `(x, y)`. |
| | `double_click` | Level 2 (Moderate)| Perform double left-click. |
| | `right_click` | Level 2 (Moderate)| Perform context menu right-click. |
| | `mouse_scroll` | Level 1 (Low) | Scroll the mouse wheel vertically or horizontally. |
| | `keyboard_type` | Level 3 (High) | Type arbitrary text string with realistic key intervals. |
| | `key_press` | Level 2 (Moderate)| Press and release a single key (e.g. `enter`, `esc`, `tab`).|
| | `keyboard_hotkey` | Level 3 (High) | Press key combinations (e.g. `ctrl+c`, `alt+tab`). |
| | `capture_screenshot` | Level 2 (Moderate)| Capture desktop screenshot and return as image bytes. |
| **Screen Perception** | `get_active_window` | Level 0 (Safe) | Retrieve title, geometry, and process of foreground window.|
| | `get_active_application` | Level 0 (Safe) | Identify the foreground desktop process name. |
| | `capture_screen` | Level 2 (Moderate)| In-memory screen capture for visual validation. |
| | `analyze_screen` | Level 1 (Low) | Run multimodal Gemini analysis on screen regions. |
| | `visual_grounding_click` | Level 3 (High) | Resolve natural language description to coordinates and click.|
| **Browser & Web** | `browser_open` | Level 2 (Moderate)| Launch browser session or open a specific URL. |
| | `read_webpage` | Level 0 (Safe) | Extract parsed text, links, and structure from a URL. |
| | `browser_action` | Level 2 (Moderate)| Click elements, submit forms, or scroll in browser. |
| | `browser_control` | Level 2 (Moderate)| Manage tabs, navigation history, and window size. |
| | `web_search` | Level 1 (Low) | Query web search engines for real-time information. |
| | `fetch_web_content` | Level 0 (Safe) | Fetch raw HTTP response from a target URL. |
| **Peripherals & Media** | `open_camera` | Level 2 (Moderate)| Initialize local webcam video capture. |
| | `capture_camera_frame`| Level 2 (Moderate)| Capture an individual snapshot frame from camera. |
| | `analyze_camera_frame`| Level 1 (Low) | Multimodal visual inspection of camera frames. |
| | `youtube_control` | Level 2 (Moderate)| Search, play, pause, or mute YouTube media. |
| | `music_control` | Level 2 (Moderate)| Control local or streaming audio playback. |

---

## Task & Workflow Intelligence (Phase 8)

Multi-step automation in JARVIS is governed by a strict five-tier workflow hierarchy:

```
Goal Prompt ──► TaskManager ──► StepExecutor ──► StepVerifier ──► RecoveryPolicy
```

### Deterministic State Machine Separation

| Machine | Defined In | Scope & Responsibility |
| :--- | :--- | :--- |
| **`AgentState`** | `jarvis/core/state.py` | **System-Wide Operational State**: Tracks what the JARVIS process is doing at the hardware and model layer (`IDLE`, `LISTENING`, `THINKING`, `TOOL_EXECUTION`, `WAITING_FOR_PERMISSION`, `SPEAKING`, `INTERRUPTED`, `RECONNECTING`, `ERROR`, `CANCELLED`). |
| **`TaskStatus`** | `jarvis/tasks/model.py` | **Workflow Progression State**: Tracks the overall multi-step goal lifecycle (`PENDING`, `PLANNING`, `EXECUTING`, `WAITING_PERMISSION`, `VERIFYING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`). |
| **`StepStatus`** | `jarvis/tasks/model.py` | **Individual Atomic Step State**: Tracks single tool call lifecycle (`PENDING`, `EXECUTING`, `WAITING_PERMISSION`, `VERIFYING`, `SUCCESS`, `FAILED`, `SKIPPED`). |

### The Verification Invariant
A tool call returning an exit code of `0` does not guarantee that the application opened, that the window focused, or that the document saved. `StepVerifier` inspects:
1. **Structured Tool Return Payloads**: Exit codes, returned flags, and error buffers.
2. **Foreground Window Inspection**: Verifies foreground window titles and processes via `GetActiveWindowTool`.
3. **Multimodal Screen Inspection**: Uses `CaptureScreenTool` + `GeminiProvider.analyze_image()` with prompt-injection defense to confirm visual presence.

### Bounded Failure Recovery
- **Idempotency Guard**: Only actions marked `IDEMPOTENT` in the canonical table can be retried automatically. Non-idempotent actions (keyboard typing, mouse clicks, file writes, shell execution) immediately halt for user direction.
- **Launch Safety**: If `launch_application` fails verification because the window is still rendering, JARVIS does **not** launch duplicate processes. It applies a settling delay and executes a `verify_only` pass.
- **Anti-Loop Fingerprinting**: Tracks consecutive identical failure hashes and alternating A-B-A-B cycle patterns to prevent runaway loops.

---

## Configuration Reference

All settings can be configured via environment variables or a local `.env` file:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `GEMINI_API_KEY` | `SecretStr` | `""` | Google Gemini API key from AI Studio. |
| `GEMINI_PRIMARY_MODEL` | `str` | `gemini-2.5-flash` | Primary reasoning model for planning and chat. |
| `GEMINI_FAST_MODEL` | `str` | `gemini-2.0-flash` | Low-latency model for quick classifications. |
| `GEMINI_EMBEDDING_MODEL`| `str` | `text-embedding-004` | Embedding model for semantic vector memory. |
| `JARVIS_NAME` | `str` | `JARVIS` | Assistant persona name. |
| `USER_NAME` | `str` | `Sir` | User salutation title. |
| `VOICE_ENABLED` | `bool` | `false` | Enable/disable audio hardware input/output. |
| `GEMINI_LIVE_VOICE` | `str` | `Charon` | Prebuilt voice name (`Charon`, `Orus`, `Gacrux`, `Puck`, `Aoede`). |
| `WEB_HUD_ENABLED` | `bool` | `false` | Enable/disable FastAPI HUD server. |
| `WEB_HUD_HOST` | `str` | `127.0.0.1` | Local IP interface for HUD server. |
| `WEB_HUD_PORT` | `int` | `8000` | Local port for HUD server. |
| `WEB_HUD_AUTO_OPEN` | `bool` | `true` | Automatically launch HUD in Chrome app mode. |
| `PERMISSION_CONFIRMATION_THRESHOLD` | `int` | `3` | Minimum risk level (0–4) requiring human approval. |
| `LOG_LEVEL` | `str` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `DEBUG` | `bool` | `false` | Enable diagnostic debug traces and verbose logs. |

---

## Repository Structure

```text
jarvis-gemini/
├── .env.example                # Configuration template
├── main.py                     # Interactive text CLI entry point
├── cli_voice.py                # Gemini Live real-time voice interface
├── run_hud.py                  # Standalone Cybernetic HUD server
├── docs/                       # Technical architecture & phase reports
│   ├── architecture.md         # Detailed system design specification
│   ├── jarvis-current-architecture.md
│   ├── memory.md               # 5-tier memory subsystem design
│   ├── phase8-architecture.md  # Task & verification engine design
│   ├── phase8-implementation-progress.md
│   └── project_report/         # Academic/technical reports & diagrams
├── jarvis/                     # Core application package
│   ├── config.py               # Pydantic Settings configuration loader
│   ├── events.py               # Async pub/sub EventBus & EventType definitions
│   ├── core/                   # Orchestration layer
│   │   ├── agent.py            # JarvisAgent orchestrator
│   │   └── state.py            # StateMachine & AgentState definitions
│   ├── models/                 # Model abstraction layer
│   │   ├── base.py             # AIProvider abstract base class
│   │   └── gemini.py           # GeminiProvider (google-genai SDK)
│   ├── memory/                 # 5-tier memory subsystem
│   │   ├── manager.py          # Unified MemoryManager coordinator
│   │   ├── short_term.py       # Sliding window conversation buffer
│   │   ├── working.py          # Active task scratchpad
│   │   ├── episodic.py         # SQLite timeline of historical events
│   │   ├── semantic.py         # Fact vault with text embeddings
│   │   └── project.py          # Repository & workspace state tracking
│   ├── security/               # Security & permission governance
│   │   └── permissions.py      # 5-Tier PermissionController & risk gating
│   ├── tasks/                  # Task & workflow intelligence (Phase 8)
│   │   ├── model.py            # Task, TaskStep, TaskStatus, StepStatus
│   │   ├── manager.py          # TaskManager lifecycle engine
│   │   ├── executor.py         # StepExecutor tool dispatcher
│   │   ├── verifier.py         # StepVerifier evidence validator
│   │   └── recovery.py         # RecoveryPolicy & AntiLoopGuard
│   ├── tools/                  # 37 Standardized tools
│   │   ├── base.py             # BaseTool abstract base class
│   │   ├── registry.py         # ToolRegistry & execution dispatcher
│   │   ├── filesystem.py       # File reading, writing, and search
│   │   ├── terminal.py         # Safe shell command execution
│   │   ├── applications.py     # Process & window lifecycle management
│   │   ├── computer.py         # Keyboard & mouse automation
│   │   ├── screen.py           # Display perception & active window capture
│   │   ├── grounding.py        # Gemini Vision coordinate clicker
│   │   ├── browser.py          # Selenium browser control
│   │   ├── web_research.py     # HTTP search & content extractors
│   │   ├── camera.py           # Webcam frame capture & analysis
│   │   └── media.py            # YouTube & media playback
│   ├── visualizer/             # Cybernetic Web HUD
│   │   ├── server.py           # FastAPI & WebSocket server
│   │   ├── adapter.py          # EventBus-to-HUD telemetry adapter
│   │   └── static/             # Frontend HTML5, CSS, Canvas & JS
│   └── voice/                  # Voice & audio streaming subsystem
│       ├── audio_io.py         # 16kHz capture & 24kHz playback buffers
│       ├── live_session.py     # Gemini Live bidirectional WebSocket session
│       ├── loop.py             # Push-to-Talk voice event loop
│       ├── ptt.py              # Global keyboard hotkey listener
│       └── tts.py              # Offline TTS engine fallback (pyttsx3)
├── scripts/                    # Diagnostics, benchmarks, and standalone probes
└── tests/                      # Comprehensive automated pytest suite (220 tests)
```

---

## Test Suite & Validation

The test suite is completely decoupled from live network calls via test doubles, mock providers, and asynchronous fixtures, ensuring 100% offline reproducibility:

```bash
# Run the complete test suite
pytest tests/

# Run with verbose output and duration profiling
pytest tests/ -v --durations=10

# Run specific subsystem tests
pytest tests/test_tasks.py tests/test_task_manager.py tests/test_task_executor.py
pytest tests/test_step_verifier.py tests/test_task_recovery.py
pytest tests/test_voice.py tests/test_visualizer.py
```

### Verified Test Coverage Summary

```text
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.1.1
rootdir: D:\my work\Jarves gemini

tests/test_agent.py ...........                                          [ 5%]
tests/test_memory.py .......................                             [15%]
tests/test_permissions.py ......                                         [18%]
tests/test_phase6.py ..........................                          [30%]
tests/test_phase7.py ...................                                 [38%]
tests/test_step_verifier.py ...............                              [45%]
tests/test_task_executor.py ............                                 [51%]
tests/test_task_manager.py ................                              [58%]
tests/test_task_recovery.py ........................                     [69%]
tests/test_tasks.py ................                                     [76%]
tests/test_tools.py ........                                             [80%]
tests/test_visualizer.py ...............                                 [86%]
tests/test_voice.py .............................                        [100%]

============================= 220 passed in ~42s =============================
```

---

## Security & Privacy Notice

- **Local Storage**: All conversation logs, SQLite databases, and project notes are stored strictly on your local device under `.jarvis/` and `memory/`.
- **Secret Redaction**: API keys, credentials, and authentication tokens are masked by Pydantic `SecretStr` and automatically scrubbed from logs and telemetry.
- **Never Commit `.env`**: `.env` is explicitly ignored in `.gitignore`. Never commit or publish your live API credentials.

---

## License

This project is licensed under the [MIT License](LICENSE).
