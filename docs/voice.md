# JARVIS Voice Subsystem Specification (Phase 4)

## 1. Overview & Architecture

The JARVIS Voice Subsystem implements a **Hybrid Dual-Engine** architecture. Voice functions strictly as an **interface layer**, routing all intelligence through `JarvisAgent`, security through `PermissionController`, memory through `MemoryManager`, and actions through `ToolRegistry`.

```
                    ┌──────────────────────────────────────┐
                    │       Push-to-Talk [Ctrl+Space]      │
                    └──────────────────┬───────────────────┘
                                       ▼
                       ┌───────────────────────────────┐
                       │     AudioInput (16kHz PCM)    │
                       └───────────────┬───────────────┘
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼ (Primary Live Engine)                       ▼ (Offline Fallback Engine)
┌─────────────────────────────────────────┐       ┌─────────────────────────────────────┐
│       GeminiLiveVoiceSession            │       │       JarvisAgent (Turn-Based)      │
│ (models/gemini-3.1-flash-live-preview)  │       │          (gemini-3.8-flash)         │
│                                         │       └──────────────────┬──────────────────┘
│  - Realtime Bidirectional WebSocket     │                          ▼
│  - Server-Side Voice Activity Detection │               ┌─────────────────────┐
│  - Native Barge-In & Tool Cancellation  │               │   BaseTTS (pyttsx3) │
└──────────────────┬──────────────────────┘               └──────────┬──────────┘
                   │                                                 │
                   │ Synchronous Tool Calls                          │
                   ▼                                                 │
      ┌─────────────────────────┐                                    │
      │  ToolRegistry           │                                    │
      │   ↓                     │                                    │
      │  PermissionController   │                                    │
      │   ↓                     │                                    │
      │  AuditLogger (Redacted) │                                    │
      └─────────────────────────┘                                    │
                   │                                                 │
                   ▼ (24kHz PCM Chunks)                              │
                   └──────────────────────┬──────────────────────────┘
                                          ▼
                              ┌───────────────────────┐
                              │ AudioOutput (24kHz)   │
                              │ [PygameAudioOutput]   │
                              └───────────┬───────────┘
                                          │
                            Barge-In Stop: < 0.05 ms
                                          ▼
                                    [Speakers]
```

---

## 2. Core Interfaces & Abstractions

The entire voice subsystem is written against abstract base classes in `jarvis.voice.base`:

| Interface | Concrete Implementations | Responsibility |
| :--- | :--- | :--- |
| `AudioInput` | `PygameAudioInput`, `MockAudioInput` | Captures 16kHz 16-bit mono audio without disk persistence |
| `AudioOutput` | `PygameAudioOutput`, `MockAudioOutput` | Plays 24kHz raw PCM chunks via 44-byte RIFF WAV container to prevent SDL2 stereo channel doubling (<0.05ms stop) |
| `BaseTTS` | `Pyttsx3TTS`, `MockTTS` | Pluggable text-to-speech fallback engine for offline or turn-based mode |
| `VoiceSession` | `GeminiLiveVoiceSession` | Persistent bidirectional WebSocket session handling multi-turn audio streaming, tool calling, GoAway, and resumption |
| `VoiceConfig` | Dataclass configuration | Manages sample rates, models, prebuilt voices (`Charon` default, `Orus`, `Gacrux`, `Puck`, `Aoede`), and timeouts |

---

## 3. Push-to-Talk (PTT) & True Barge-In

### Push-to-Talk
- Implemented via `jarvis.voice.ptt.PTTController`.
- Windows hotkey: `GetAsyncKeyState(VK_CONTROL)` + `GetAsyncKeyState(VK_SPACE)`.
- Eliminates room audio false-triggers, eliminates microphone acoustic feedback loops, and avoids unnecessary API costs.
- Non-blocking background listener polling at 20ms intervals.

### True Barge-In / Interruption
- **Local Interruption**: When the user presses `[Ctrl+Space]` while JARVIS is actively outputting audio, `AudioOutput.stop()` executes in **0.023 ms**, immediately clearing all queued buffers and halting the hardware mixer.
- **Server Interruption**: Gemini Live API server detects user voice overlap and emits `msg.server_content.interrupted = True`. The client halts playback and updates the state machine to `AgentState.INTERRUPTED` before resuming `AgentState.LISTENING`.

---

### Voice Configuration & Personalities
The voice subsystem supports selectable prebuilt voices passed via `VoiceConfig.prebuilt_voice` or the `--voice` CLI option:
- **`Charon`** (Default): Mature, confident, composed British/informational tone ideal for JARVIS.
- **`Orus`**: Direct, firm tone.
- **`Gacrux`**: Warm, conversational tone.
- **`Puck`**: Energetic, youthful tone.
- **`Aoede`**: Sophisticated, calm tone.

Execution pipeline:
`CLI (--voice <name>) -> VoiceConfig -> GeminiLiveVoiceSession -> types.LiveConnectConfig`

---

## 4. Empirical Diagnoses & Stabilization Fixes

### 1. 2× Playback Speed Root Cause & Fix
- **Empirical Diagnosis**: Windows SDL2 audio mixer defaults to stereo `(channels=2)`. When raw 16-bit mono 24,000 Hz PCM chunks were played directly via `pygame.mixer.Sound(buffer=pcm)`, Pygame consumed 4 bytes per frame (stereo) instead of 2 bytes per frame (mono). This halved playback duration (`sound.get_length() == 0.5s` for 1.0s of audio) and caused the audio to play at 2× speed with high-pitched chipmunk voice.
- **Fix**: Raw PCM chunks are wrapped with a standard 44-byte RIFF WAV header specifying `channels=1`, `sample_rate=24000`, `bits_per_sample=16`. This instructs SDL2 to map mono samples to both hardware stereo channels correctly, restoring wall-clock playback duration to 1:1 real-time (wall-clock playback duration ratio: 0.998).
- **Diagnostics**: Every played audio chunk logs input sample rate, PCM bit depth, channels, byte count, sample count, expected duration (`samples / 24000`), actual mixer format, and Pygame sound duration.

### 2. WebSocket 1011 Keepalive Ping Timeout Root Cause & Fix
- **Root Cause 1**: In the `google-genai` SDK, `session.receive()` is an async generator for a single turn (terminating after `turn_complete=True`). Wrapping it in an outer `while self._session_state == SessionState.CONNECTED:` ensures subsequent turns seamlessly await new turns on the persistent WebSocket.
- **Root Cause 2**: When a user interrupted speaking or thinking, the session previously triggered a violent teardown and reconnection while the microphone was active. This severed the active WebSocket on Google's edge proxies, causing stale connection ping timeouts: `1011 (internal error) keepalive ping timeout; no close frame received`.
- **Fix**: In-session interruptions (`interrupt()`) now preserve the active WebSocket connection. Only when the transport is genuinely disconnected is a reconnection initiated with exponential backoff and optional session resumption (`LiveServerSessionResumptionUpdate.new_handle`).

### 3. Transport Lifecycle State Separation
Session transport lifecycle is decoupled from `AgentState`:
- `SessionState.DISCONNECTED`: Session is offline.
- `SessionState.CONNECTED`: Active bidirectional WebSocket.
- `SessionState.RECONNECTING`: Attempting reconnection with backoff and resumption.
- `SessionState.CLOSING`: Gracefully winding down tasks.
- `SessionState.CLOSED`: Session terminated.

---

## 5. Voice State Machine & Lifecycle Transitions

The Voice Subsystem strictly adheres to the deterministic `StateMachine` in `jarvis.core.state`. Transitions are driven by genuine voice events rather than ad-hoc state overwrites.

### Primary Lifecycle
1. **Idle**: `AgentState.IDLE`
2. **User Speech Start (PTT Pressed)**: `IDLE -> LISTENING` (mic capture begins, `VOICE_SPEECH_STARTED` emitted).
3. **User Speech End (PTT Released)**: `LISTENING -> THINKING` (`VOICE_SPEECH_ENDED` emitted, `end_turn()` transmitted to Gemini Live session).
4. **Model Spoken Response**: `THINKING -> SPEAKING` (24kHz PCM chunks streamed to audio output).
5. **Turn Completion**: `SPEAKING -> IDLE` (turn finalized, short-term/episodic memory recorded).

### Interruption & Barge-In Lifecycle
When the user presses PTT while JARVIS is active:
- **PTT during `SPEAKING`**:
  - `AudioOutput.stop()` is triggered immediately (<0.05ms).
  - State machine executes: `SPEAKING -> INTERRUPTED -> LISTENING`.
  - Stale queued chunks are discarded. Live connection is preserved.
- **PTT during `THINKING`**:
  - State machine executes: `THINKING -> INTERRUPTED -> LISTENING`.
  - Pending generation is aborted; stale server chunks are discarded in `_receive_loop`.
  - Live connection is preserved.

---

## 6. How to Run the Voice CLI Demonstration

To start the interactive Push-to-Talk voice assistant with default Charon voice:

```bash
python cli_voice.py --voice Charon
```

Supported voices: `--voice Charon`, `--voice Orus`, `--voice Gacrux`, `--voice Puck`, `--voice Aoede`.

### Controls:
- **Hold `[Ctrl+Space]`**: Speak your question or command into your microphone.
- **Release `[Ctrl+Space]`**: JARVIS processes speech with Gemini Live and streams audio response to your speakers.
- **Press `[Ctrl+Space]` while JARVIS is speaking/thinking**: Instantly interrupts JARVIS (Barge-in).
- **Press `[Ctrl+C]`**: Cleanly terminates the voice session and audio loops.

To run the automated 5-turn end-to-end Live verification suite:

```bash
python scripts/test_live_voice_loop_five_turns.py
```

