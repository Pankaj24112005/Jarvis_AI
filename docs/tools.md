# JARVIS Standardized Tool Reference

## 1. Tool Architecture

Every tool in JARVIS inherits from `BaseTool` ([`jarvis/tools/base.py`](file:///d:/my%20work/Jarves%20gemini/jarvis/tools/base.py)) and executes through the central `ToolRegistry` ([`jarvis/tools/registry.py`](file:///d:/my%20work/Jarves%20gemini/jarvis/tools/registry.py)).

### Execution Pipeline
$$\text{Gemini Function Call} \longrightarrow \text{ToolRegistry} \longrightarrow \text{Schema Validation} \longrightarrow \text{PermissionController} \longrightarrow \text{Human Approval (if L3/L4)} \longrightarrow \text{Tool Execution} \longrightarrow \text{Audit Logger} \longrightarrow \text{ToolResult}$$

---

## 2. Built-in Tools Summary

| Tool Name | Module | Level | Description |
| :--- | :--- | :---: | :--- |
| `list_dir` | `filesystem.py` | 1 | List contents of a directory in the workspace |
| `read_file` | `filesystem.py` | 1 | Read text content from a workspace file |
| `write_file` | `filesystem.py` | 2 | Create or overwrite a workspace file |
| `modify_file` | `filesystem.py` | 2 | Replace substring in a workspace file |
| `delete_file` | `filesystem.py` | 3 | Delete file from workspace (Requires Confirmation) |
| `search_files` | `filesystem.py` | 1 | Search for files by pattern or content query |
| `terminal_execute` | `terminal.py` | 3* | Execute shell command with safety classification |
| `launch_application` | `applications.py`| 1 | Launch desktop application by name |
| `list_running_applications`| `applications.py`| 1 | List running processes and memory |
| `focus_application` | `applications.py`| 1 | Focus desktop window matching title |
| `close_application` | `applications.py`| 3 | Close application by process name or PID |
| `mouse_move` | `computer.py` | 1 | Move mouse cursor to (x, y) coordinates |
| `mouse_click` | `computer.py` | 2 | Click mouse at position |
| `keyboard_type` | `computer.py` | 2 | Type string into focused window |
| `keyboard_hotkey` | `computer.py` | 2 | Trigger keyboard shortcut combination |
| `capture_screenshot` | `computer.py` | 1 | Capture full screen screenshot to file |
| `browser_open` | `browser.py` | 1 | Open URL in browser |
| `browser_read_page` | `browser.py` | 1 | Extract clean text content from web URL |
| `browser_action` | `browser.py` | 2 | Headless browser interaction (click, type, back) |
| `web_search` | `web_research.py` | 1 | Search internet for queries and URLs |
| `fetch_web_content` | `web_research.py` | 1 | Fetch article text and structured content |

*\*Note: `terminal_execute` dynamically classifies commands: harmless queries (e.g., `python --version`, `git status`) are treated as Level 1/2, while destructive commands (`del`, `rmdir`, `shutdown`) are strictly Level 3.*

---

## 3. Filesystem Security Sandbox
All filesystem tools strictly enforce boundary resolution via `resolve_safe_path()`:
- Path traversal sequences (e.g. `../../Windows/System32`) are blocked with `PathSecurityError`.
- Operations outside the workspace root are rejected before any filesystem call is attempted.
