# Reference Repository Analysis: jaredrhod/fullstack-agent

## 1. Executive Summary

This document provides a technical and architectural analysis of the reference repository:
`https://github.com/jaredrhod/fullstack-agent`
and its four foundational sub-projects:
- `ai-memory-vault` (`https://github.com/jaredrhod/ai-memory-vault`)
- `backtalk` (`https://github.com/jaredrhod/backtalk`)
- `ai-visualizer` (`https://github.com/jaredrhod/ai-visualizer`)
- `barehands` (`https://github.com/jaredrhod/barehands`)

The primary objective of this analysis is to identify the core architectural principles, isolate model-independent components, pinpoint Claude-specific coupling, and establish the engineering requirements to replace the proprietary Claude dependency with an independent, Google Gemini-native architecture.

---

## 2. Component Breakdown of the Reference Stack

### 2.1 Orchestrator: `fullstack-agent`
- **Purpose**: A setup wizard and unified launcher for the four sub-projects.
- **Implementation**: Written as an interactive wizard script (`fullstack-agent.md`) executed inside Claude Code CLI (`claude "set me up"`).
- **Coupling**: Entirely reliant on Claude Code CLI to interpret instructions, prompt the user, run shell commands, and generate configuration files.

### 2.2 Memory Layer: `ai-memory-vault`
- **Purpose**: Persistent long-term memory for personal AI assistants.
- **Architecture**:
  - File-based markdown vault (compatible with Obsidian).
  - Structured folders: Daily notes, user profile, lessons learned, project logs, and "Jobs" (reusable prompt templates / skill instructions).
  - "AI Priming": Instructing the agent to read specific markdown files (e.g., guidelines, knowledge base) before generating responses.
  - Migration script that scans Claude Code's internal project memory (`~/.claude/projects/*/memory/`) and copies notes into the vault.
- **Strengths**: Plain-text human-readable format, zero database lock-in, accessible via any text editor or Obsidian.
- **Limitations**: In the reference setup, retrieval is manual or keyword-based via Claude Code's file reading tools; lacking structured semantic vector ranking or automatic contextual recall.

### 2.3 Voice Layer: `backtalk`
- **Purpose**: Low-latency voice conversation loop.
- **Architecture**:
  - Push-to-Talk (PTT) with configurable hotkey (e.g., Home key) and hands-free VAD option.
  - Speech-to-Text: Local offline Whisper model or system STT.
  - Text-to-Speech: Local TTS engine (Kokoro / Piper / pyttsx3) or ElevenLabs API.
  - Signal Bridge: Writes atomic state files (`.voice_state`, `.voice_waveform`, `.voice_transcript`) to disk for inter-process communication with visualizers.
  - Voice Console: Intercepts specific spoken phrases (e.g., "clear session", "stop asking for permission", "switch model") before routing to LLM.
- **Coupling**: The brain in `backtalk` is hardcoded to run `claude` CLI subprocesses or use Claude Agent SDK hooks.

### 2.4 Face / HUD: `ai-visualizer`
- **Purpose**: Full-screen, browser-based visualizer reacting to the assistant's state.
- **Architecture**:
  - Built with Vanilla HTML5 Canvas, CSS, and WebGL.
  - Four visual themes: "Circuit Board", "Radial Particle Starburst", "Face in the Code (Matrix Rain)", and "Neural Core".
  - Inter-Process Communication (IPC): A lightweight Python HTTP server polls local signal files (`.voice_state` and `.voice_waveform`) and exposes them via SSE / polling to the frontend.
  - States visualized: `idle`, `listening`, `thinking`, `speaking`.

### 2.5 Gesture Layer: `barehands`
- **Purpose**: Webcam-based hand gesture control and 3D card manipulation.
- **Architecture**:
  - Client-side Google MediaPipe Hand Landmarker running in Chrome via CDN scripts.
  - Three.js 3D glass card renderer floating over live camera feed.
  - Gesture mapping: Pinch, drag, swipe, hover.
  - Board staging script (`bin/board.sh`) allowing an AI to post markdown cards or images onto the user's screen.

---

## 3. Claude-Specific Dependencies Identified

The reference project suffers from deep, proprietary lock-in to Anthropic:

| Component | Reference Implementation | Problem / Limitation |
| :--- | :--- | :--- |
| **Agent Core** | Shell calls to `claude "prompt"` and Claude Code CLI | Inflexible, slow process startup per turn, no programmatic Python control. |
| **Tool Execution** | Claude Code built-in tools (`Bash`, `FileEdit`, `GlobTool`) | Opaque execution, cannot customize permission schemas or add custom Python tools. |
| **Memory Migration**| Targets `~/.claude/projects/*/memory/` | Completely specific to Claude Code local cache. |
| **Voice Loop** | Invokes Claude CLI subprocess | High latency, brittle stdout parsing, cannot stream token-by-token audio. |
| **Authentication** | Claude Pro subscription / Anthropic auth token | Incompatible with Google Gemini ecosystem and enterprise deployments. |

---

## 4. Reusable Architectural Concepts

Despite the Claude coupling, several design patterns from the reference project are highly effective:

1. **State Signaling**: The clean separation between the agent's internal state machine (`IDLE`, `LISTENING`, `THINKING`, `TOOL_EXECUTION`, `SPEAKING`, `WAITING_FOR_PERMISSION`) and the visualizer UI.
2. **Push-to-Talk UX**: PTT guarantees mic isolation, preventing room noise, speaker audio loops, and unintentional triggers.
3. **Local Plain-Text Memory**: Markdown-based persistent memory ensures user data sovereignty, transparency, and simple backup.
4. **Decoupled Multimodal Perception**: Using local computer vision (MediaPipe / OpenCV) for real-time gesture interaction without sending continuous video streams to cloud APIs.

---

## 5. Clean Gemini-Native Architectural Redesign

Our implementation completely discards Claude and builds an independent Python agent:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          JARVIS Python Engine                          │
│                                                                        │
│  ┌───────────────────────┐             ┌────────────────────────────┐  │
│  │   Gemini Provider     │             │     Event Bus (asyncio)    │  │
│  │  (google-genai SDK)   │             │   Pub/Sub State Management │  │
│  └───────────┬───────────┘             └─────────────┬──────────────┘  │
│              │                                       │                 │
│              ▼                                       ▼                 │
│  ┌───────────────────────┐             ┌────────────────────────────┐  │
│  │   Core Agent Loop     │◄───────────►│       Voice Engine         │  │
│  │  Reasoning & Planning │             │  PTT / STT / Offline TTS   │  │
│  └───────────┬───────────┘             └─────────────┬──────────────┘  │
│              │                                       │                 │
│              ▼                                       ▼                 │
│  ┌───────────────────────┐             ┌────────────────────────────┐  │
│  │  5-Tier Security Gate │             │    Vision & Gestures       │  │
│  │  Level 0-4 Perms      │             │    OpenCV + MediaPipe      │  │
│  └───────────┬───────────┘             └─────────────┬──────────────┘  │
│              │                                       │                 │
│              ▼                                       ▼                 │
│  ┌───────────────────────┐             ┌────────────────────────────┐  │
│  │ Standardized Tool Set │             │    FastAPI / WS Server     │  │
│  │ Files, Shell, Apps    │             │    Real-time HUD / UI      │  │
│  └───────────────────────┘             └────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Engineering Upgrades:
1. **Official `google-genai` SDK**: Direct native integration using `client.aio.models.generate_content` and `client.aio.models.generate_content_stream`.
2. **Native Function Calling**: Declarative tool schemas registered directly into Gemini's `GenerateContentConfig(tools=[...])`.
3. **5-Tier Security Controller**: Deterministic gating where dangerous actions (Levels 3 & 4) require human confirmation before execution.
4. **In-Memory Async Event Bus**: Instant event delivery between Agent, Voice, Vision, and WebSockets without relying on slow disk polling.
5. **Multi-Tier Memory**: Combining short-term conversation context, episodic execution logs, and semantic markdown memory vaults with keyword/similarity ranking.
