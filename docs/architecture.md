# JARVIS System Architecture Specification

## 1. Architectural Philosophy

JARVIS is designed as an intelligent operating layer over the user's computer. The core guiding architectural principles are:

1. **LLM as the Reasoning Engine, Not the Entire System**: The language model (Google Gemini) provides intelligence, planning, and evaluation. Deterministic software provides state management, permission enforcement, memory indexing, hardware control, and safety boundaries.
2. **Strict Model Abstraction**: The core agent interacts only with an abstract `AIProvider` interface. The primary implementation is `GeminiProvider`, leveraging the official `google-genai` SDK. Future models or local providers can be slotted in without modifying core agent logic.
3. **Decoupled Asynchronous Event-Driven Design**: The Voice system, Vision system, UI Visualizer, and Tool Executors communicate asynchronously via an in-memory `EventBus`. No component blocks the main event loop.
4. **Defense in Depth & 5-Tier Permission Security**: Model-requested tools pass through a deterministic Permission Controller. Destructive operations (Levels 3 & 4) strictly require human confirmation.
5. **Local-First Transparency**: Configuration, memories, audit logs, and project states are stored in plain text (Markdown/JSON) directly on the local machine.

---

## 2. High-Level System Architecture

```mermaid
graph TD
    User([User: Text / Voice / Gestures]) --> InputRouter[Input Router / CLI / Voice Loop]
    InputRouter --> EventBus[Async Event Bus]

    subgraph Core Engine
        EventBus --> StateMachine[Agent State Machine]
        StateMachine --> JarvisAgent[JarvisAgent]
        JarvisAgent --> Planner[Task Planner & Observer]
        JarvisAgent --> MemorySystem[Multi-Tier Memory]
    end

    subgraph Model Abstraction
        JarvisAgent --> AIProvider[AIProvider Interface]
        AIProvider --> GeminiProvider[GeminiProvider: google-genai]
        GeminiProvider --> GoogleGemini[(Google Gemini API)]
    end

    subgraph Security & Tools
        JarvisAgent --> SecurityGate[5-Tier Permission Controller]
        SecurityGate --> ToolRegistry[Tool Registry]
        ToolRegistry --> FileTools[Filesystem Tools]
        ToolRegistry --> ShellTools[Terminal & Process Tools]
        ToolRegistry --> AppTools[Application Control]
        ToolRegistry --> ComputerTools[Mouse / Keyboard / Screen]
        ToolRegistry --> BrowserTools[Web & Research Tools]
    end

    subgraph Peripherals & UI
        EventBus --> VoiceEngine[Voice Engine: STT / TTS]
        EventBus --> VisionEngine[Vision & Gestures: OpenCV / MediaPipe]
        EventBus --> VisualizerServer[FastAPI / WebSocket Server]
        VisualizerServer --> WebHUD[Browser HUD / Visualizer Face]
    end
```

---

## 3. Core Component Specifications

### 3.1 Model Abstraction Layer (`jarvis.models`)

The model abstraction isolates all LLM communication behind an abstract base class:

```python
class AIProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_instruction: str | None = None, **kwargs) -> ModelResponse: ...

    @abstractmethod
    async def stream(self, prompt: str, system_instruction: str | None = None, **kwargs) -> AsyncIterator[str]: ...

    @abstractmethod
    async def generate_with_tools(self, prompt: str, tools: list[BaseTool], **kwargs) -> ModelResponse: ...

    @abstractmethod
    async def analyze_image(self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> ModelResponse: ...

    @abstractmethod
    async def create_embedding(self, text: str) -> list[float]: ...
```

#### `GeminiProvider` Implementation:
- **SDK**: Official `google-genai` (version 2.8+).
- **Client**: `client = genai.Client(api_key=...)`.
- **Async Execution**: Employs `client.aio.models.generate_content(...)` and `client.aio.models.generate_content_stream(...)` to prevent blocking the event loop.
- **Tool Calling**: Converts internal `BaseTool` JSON schemas into Gemini's `types.GenerateContentConfig(tools=[...])`. Model function calls arrive as `response.function_calls` and are serialized to standard tool requests.
- **Multimodal**: Passes images as `types.Part.from_bytes(data=image_bytes, mime_type=mime_type)`.
- **Structured Outputs**: Leverages `types.GenerateContentConfig(response_schema=..., response_mime_type="application/json")` when deterministic Pydantic objects are required.
- **Resilience**: Configurable exponential backoff retries for rate limits (`429`) and transient network issues.

---

### 3.2 Agent State Machine (`jarvis.core.state`)

The agent operates under a deterministic finite state machine with strict transition rules:

| State | Description | Trigger / Next State |
| :--- | :--- | :--- |
| `IDLE` | Waiting for user input or wake event | User speaks or types -> `LISTENING` / `PROCESSING` |
| `LISTENING` | Receiving audio stream or user prompt | Speech ends -> `THINKING` |
| `THINKING` | Querying Gemini model for reasoning/plan | Direct response -> `SPEAKING`; Tool request -> `TOOL_EXECUTION` |
| `TOOL_EXECUTION` | Executing permitted tool or evaluating permission | High-risk tool -> `WAITING_FOR_PERMISSION`; Tool finished -> `THINKING` |
| `WAITING_FOR_PERMISSION` | Awaiting human approval for Level 3/4 action | Approved -> `TOOL_EXECUTION`; Denied -> `THINKING` |
| `SPEAKING` | Generating voice output or rendering response | Audio finished -> `IDLE` |
| `ERROR` | External API failure or device disconnect | Recovered / logged -> `IDLE` |
| `CANCELLED` | User interrupted turn or pressed stop key | Reset -> `IDLE` |

---

### 3.3 Event Bus Architecture (`jarvis.events`)

An asynchronous Publish/Subscribe event bus connects all subsystems without tight coupling:

- **`Event` dataclass**: `name: str`, `payload: dict`, `timestamp: float`.
- **Core Event Types**:
  - `AGENT_STATE_CHANGED`: Emitted on every state transition (payload: `old_state`, `new_state`).
  - `USER_MESSAGE`: Emitted when user sends a text or speech message.
  - `AI_RESPONSE_CHUNK`: Streaming tokens for low-latency voice and UI rendering.
  - `AI_RESPONSE_COMPLETED`: Complete textual output from the model.
  - `TOOL_REQUESTED`: Model proposed a tool call.
  - `PERMISSION_REQUESTED`: Tool requires explicit human approval.
  - `PERMISSION_GRANTED` / `PERMISSION_DENIED`: User response to confirmation prompt.
  - `TOOL_EXECUTED`: Tool completed with result or error.
  - `GESTURE_DETECTED`: Hand gesture recognized from webcam.

---

### 3.4 Security & 5-Tier Permission Controller (`jarvis.security`)

To prevent arbitrary or destructive operations, all tools are classified into 5 strict tiers:

```
LEVEL 0: SAFE ────────────► Auto-Approved (e.g. read time, public docs, internal calculations)
LEVEL 1: LOW RISK ────────► Auto-Approved (e.g. read project file, list directory, launch calculator)
LEVEL 2: MODERATE ────────► Monitored (e.g. create/edit project files, safe git commands)
LEVEL 3: HIGH RISK ───────► Confirm by Default (e.g. delete file, execute shell command, kill process)
LEVEL 4: CRITICAL ────────► ALWAYS CONFIRM (e.g. system config, credential modification, recursive delete)
```

The `PermissionController`:
1. Validates the tool's required permission level against the active security profile.
2. If the operation meets or exceeds the confirmation threshold, the agent transitions to `WAITING_FOR_PERMISSION`.
3. Prompts the user with the exact tool name, target arguments, and rationale.
4. User can respond via Console `[Allow]/[Deny]`, Web HUD button, or Thumbs-up/Thumbs-down gesture.
5. All permission evaluations and execution outcomes are recorded in `logs/audit.log`.

---

### 3.5 Multi-Tier Memory System (`jarvis.memory`)

Memory is structured into distinct tiers based on retention and purpose:

1. **Short-Term Memory**:
   - In-memory sliding window of recent conversation turns.
   - Truncated or summarized automatically to stay within optimal context windows.
2. **Working Memory**:
   - Stores active multi-step task state, goal description, step results, and scratchpad notes.
3. **Episodic Memory**:
   - Persistent interaction logs saved as daily Markdown files (`memory/episodes/YYYY-MM-DD.md`).
   - Summaries of key tasks accomplished during past sessions.
4. **Semantic Memory & Knowledge Vault**:
   - Plain-text Markdown files structured in categories: `Profile/`, `Projects/`, `Preferences/`, `Skills/`.
   - Indexed via local keyword matching and lightweight vector embeddings for rapid relevance retrieval.
5. **Project-State Awareness**:
   - Scans active workspace for `.jarvis/` directory containing `project_state.json`, `decisions.md`, and `tasks.md`.
   - Inspects local Git repository state (current branch, modified files, uncommitted changes).

---

### 3.6 Voice & Multimodal Perception

- **Voice Pipeline**:
  - Push-to-Talk (PTT) ensures zero accidental room audio triggers and eliminates audio feedback loops.
  - STT: Local SpeechRecognition with configurable backend.
  - TTS: Offline native Windows SAPI5 via `pyttsx3` for sub-second, zero-cost responses.
  - State files (`.voice_state` and `.voice_waveform`) maintain backward compatibility with external visualizers.
- **Vision Pipeline**:
  - Screen capture tool for desktop inspection.
  - Webcam input via OpenCV.
  - Gesture recognizer via MediaPipe with graceful fallback when cameras are absent.
