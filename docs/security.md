# JARVIS Security & 5-Tier Permission Model

## 1. Security Overview

JARVIS operates under strict defense-in-depth principles:
- The AI model (Google Gemini) has **zero direct access** to operating system primitives, shell commands, or files.
- The model can only emit structured tool requests.
- All requests are intercepted, validated, and authorized by the deterministic `PermissionController`.

---

## 2. The 5-Tier Permission Hierarchy

| Level | Classification | Examples | Policy / Action |
| :---: | :--- | :--- | :--- |
| **0** | **SAFE** | Internal calculations, time, status, public docs | Auto-approved |
| **1** | **LOW RISK** | Read allowed files, list directories, search web, launch apps | Auto-approved by default |
| **2** | **MODERATE** | Create/modify files, safe dev commands, mouse/keyboard | Monitored, auto-approved if threshold >= 3 |
| **3** | **HIGH RISK** | Delete files, shell commands, kill process, install software | **Mandatory Human Confirmation** |
| **4** | **CRITICAL** | System modifications, credentials, financial, account ops | **ALWAYS Mandatory Confirmation** |

---

## 3. Human Approval Workflow

When a tool request meets or exceeds the confirmation threshold (Level 3 or 4):
1. The agent transitions to `AgentState.WAITING_FOR_PERMISSION`.
2. The interactive prompt displays:
   - Tool name
   - Tool description
   - Sanitized arguments
   - Permission tier
3. The human user must respond with `[Allow]` or `[Deny]`.
4. If **Approved**: The tool executes, logs duration, and returns results to Gemini.
5. If **Denied**: Tool execution is immediately aborted, recorded as denied, and Gemini receives an informative denial message so it can replan gracefully.

---

## 4. Audit Logging & Secret Sanitization

All tool requests and execution outcomes are recorded in [`logs/audit.log`](file:///d:/my%20work/Jarves%20gemini/logs/audit.log).
- **Format**: Structured JSON Lines.
- **Fields**: `timestamp`, `iso_time`, `tool`, `level`, `approved`, `duration_ms`, `success`, `error`, `arguments`.
- **Sanitization**: All parameters matching secret terms (`api_key`, `password`, `token`, `secret`, `credential`) are automatically masked to `[REDACTED]` prior to logging.
