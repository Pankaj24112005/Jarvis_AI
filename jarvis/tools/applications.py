"""Application Management Tools for inspecting, launching, and controlling desktop apps."""

import asyncio
import os
import shutil
import subprocess
import sys
from typing import Any
import psutil
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


KNOWN_WINDOWS_APPS: dict[str, dict[str, Any]] = {
    # UWP Applications (Registered Shell URI Schemes)
    "camera": {"type": "uri", "target": "microsoft.windows.camera:", "proc_names": ["windowscamera.exe", "camera.exe"]},
    "webcam": {"type": "uri", "target": "microsoft.windows.camera:", "proc_names": ["windowscamera.exe", "camera.exe"]},
    "calculator": {"type": "uri", "target": "calculator:", "proc_names": ["calculatorapp.exe", "calculator.exe"]},
    "calc": {"type": "uri", "target": "calculator:", "proc_names": ["calculatorapp.exe", "calculator.exe"]},
    "paint": {"type": "uri", "target": "ms-paint:", "proc_names": ["mspaint.exe", "paint.exe"]},
    "settings": {"type": "uri", "target": "ms-settings:", "proc_names": ["systemsettings.exe"]},
    "photos": {"type": "uri", "target": "ms-photos:", "proc_names": ["photos.exe", "microsoft.photos.exe"]},
    "maps": {"type": "uri", "target": "bingmaps:", "proc_names": ["maps.exe"]},

    # Win32 Desktop Applications
    "notepad": {"type": "binary", "target": "notepad.exe", "proc_names": ["notepad.exe"]},
    "explorer": {"type": "binary", "target": "explorer.exe", "proc_names": ["explorer.exe"]},
    "cmd": {"type": "binary", "target": "cmd.exe", "proc_names": ["cmd.exe"]},
    "powershell": {"type": "binary", "target": "powershell.exe", "proc_names": ["powershell.exe"]},
    "terminal": {"type": "binary", "target": "wt.exe", "proc_names": ["windowsterminal.exe", "wt.exe"]},
    "chrome": {"type": "binary", "target": "chrome.exe", "proc_names": ["chrome.exe"]},
    "edge": {"type": "binary", "target": "msedge.exe", "proc_names": ["msedge.exe"]},
    "msedge": {"type": "binary", "target": "msedge.exe", "proc_names": ["msedge.exe"]},
}


class LaunchApplicationTool(BaseTool):
    """Launches an application safely by known name, URI scheme, or executable path."""

    name = "launch_application"
    description = (
        "Launch a desktop or Windows UWP application safely by name (e.g., 'camera', 'calculator', 'notepad', 'chrome')."
    )
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Name or executable of the application to launch (e.g. 'camera', 'calculator', 'notepad')",
                },
                "args": {
                    "type": "STRING",
                    "description": "Optional command-line arguments to pass to the application",
                },
            },
            "required": ["app_name"],
        }

    async def execute(self, app_name: str, args: str = "", **kwargs) -> ToolResult:
        try:
            normalized = app_name.strip().lower()

            # Prevent command chaining and arbitrary shell injection
            if any(char in app_name for char in [";", "&", "|", "`", "$", ">", "<", "\n", "\r"]):
                return ToolResult(
                    success=False,
                    error=f"Invalid characters detected in application name: '{app_name}'. Shell meta-characters are prohibited.",
                )

            # 1. Check known safe application table
            if normalized in KNOWN_WINDOWS_APPS:
                app_info = KNOWN_WINDOWS_APPS[normalized]
                app_type = app_info["type"]
                target = app_info["target"]
                proc_names = app_info.get("proc_names", [])

                if app_type == "uri":
                    if sys.platform == "win32":
                        os.startfile(target)
                    else:
                        import webbrowser
                        webbrowser.open(target)

                    verified = await self._verify_launch(proc_names, timeout=2.0)
                    return ToolResult(
                        success=True,
                        result={
                            "app_name": app_name,
                            "status": "launched",
                            "launch_type": "uri",
                            "target": target,
                            "verified": verified,
                        },
                    )

                elif app_type == "binary":
                    bin_path = shutil.which(target) or target
                    import shlex
                    arg_list = shlex.split(args) if args else []
                    proc = await asyncio.create_subprocess_exec(
                        bin_path,
                        *arg_list,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    verified = await self._verify_launch(proc_names, proc=proc, timeout=1.5)
                    return ToolResult(
                        success=True,
                        result={
                            "app_name": app_name,
                            "status": "launched",
                            "launch_type": "binary",
                            "target": bin_path,
                            "pid": proc.pid,
                            "verified": verified,
                        },
                    )

            # 2. Check if it's a direct Windows URI scheme (e.g., "calc:")
            if sys.platform == "win32" and normalized.endswith(":"):
                os.startfile(normalized)
                return ToolResult(
                    success=True,
                    result={"app_name": app_name, "status": "launched", "launch_type": "uri", "target": normalized},
                )

            # 3. Check system PATH for binary executable
            bin_path = shutil.which(app_name)
            if bin_path:
                import shlex
                arg_list = shlex.split(args) if args else []
                proc = await asyncio.create_subprocess_exec(
                    bin_path,
                    *arg_list,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                verified = await self._verify_launch([os.path.basename(bin_path).lower()], proc=proc, timeout=1.5)
                return ToolResult(
                    success=True,
                    result={
                        "app_name": app_name,
                        "status": "launched",
                        "launch_type": "binary",
                        "target": bin_path,
                        "pid": proc.pid,
                        "verified": verified,
                    },
                )

            return ToolResult(
                success=False,
                error=(
                    f"Application '{app_name}' not recognized in known applications or system PATH. "
                    f"Available known apps: {', '.join(sorted(set(KNOWN_WINDOWS_APPS.keys())))}"
                ),
            )

        except Exception as ex:
            logger.error("Failed to launch application '%s': %s", app_name, ex)
            return ToolResult(success=False, error=f"Failed to launch application '{app_name}': {str(ex)}")

    async def _verify_launch(
        self,
        proc_names: list[str],
        proc: asyncio.subprocess.Process | None = None,
        timeout: float = 1.5,
    ) -> bool:
        """Verify that the process was started successfully and did not immediately crash."""
        if proc is not None:
            await asyncio.sleep(0.3)
            if proc.returncode is not None and proc.returncode != 0:
                return False

        if not proc_names:
            return True

        norm_proc_names = [p.lower() for p in proc_names]
        end_time = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < end_time:
            for p in psutil.process_iter(["name"]):
                try:
                    pname = p.info.get("name", "")
                    if pname and pname.lower() in norm_proc_names:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            await asyncio.sleep(0.3)

        return False


class ListRunningApplicationsTool(BaseTool):
    """Lists currently running desktop applications and system processes."""

    name = "list_running_applications"
    description = "List currently running user applications and processes with PID and memory usage."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "max_results": {
                    "type": "INTEGER",
                    "description": "Maximum number of processes to return (default: 30)",
                }
            },
            "required": [],
        }

    async def execute(self, max_results: int = 30, **kwargs) -> ToolResult:
        try:
            apps = []
            for proc in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    info = proc.info
                    name = info.get("name", "")
                    # Filter out system idle or empty
                    if not name or name.lower() in ["system idle process", "registry"]:
                        continue
                    mem = info.get("memory_info")
                    mem_mb = round(mem.rss / (1024 * 1024), 1) if mem else 0
                    apps.append({
                        "pid": info["pid"],
                        "name": name,
                        "memory_mb": mem_mb,
                    })
                    if len(apps) >= max_results:
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            return ToolResult(success=True, result={"processes": apps, "count": len(apps)})
        except Exception as ex:
            return ToolResult(success=False, error=str(ex))


class FocusApplicationTool(BaseTool):
    """Brings an application window into focus by matching its title."""

    name = "focus_application"
    description = "Focus/bring to front an application window matching a title substring."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Window title substring to search and focus",
                }
            },
            "required": ["title"],
        }

    async def execute(self, title: str, **kwargs) -> ToolResult:
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return ToolResult(success=False, error=f"No open window found with title matching '{title}'.")

            win = windows[0]
            if win.isMinimized:
                win.restore()
            win.activate()

            return ToolResult(success=True, result={"title": win.title, "status": "focused"})
        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to focus window '{title}': {str(ex)}")


class CloseApplicationTool(BaseTool):
    """Gracefully closes an application or window by name or title without killing processes."""

    name = "close_application"
    description = (
        "Gracefully close a desktop application or window by name (e.g. 'Chrome', 'Notepad', 'Calculator', "
        "or 'current'). Sends a standard WM_CLOSE signal without killing processes. "
        "For force-terminating a hung process, use 'terminate_process'. "
        "For closing a single browser tab, use 'browser_control' with action='close_tab'."
    )
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Name of the application or window to close (e.g. 'Chrome', 'Notepad', 'Calculator', 'current')",
                }
            },
            "required": ["app_name"],
        }

    async def execute(self, app_name: str, **kwargs) -> ToolResult:
        try:
            target = app_name.strip()
            norm = target.lower()

            # Strip extension if model passes process name (e.g., 'chrome.exe' -> 'chrome')
            if norm.endswith(".exe"):
                norm = norm[:-4]

            import pygetwindow as gw

            target_window = None
            all_windows = [w for w in gw.getAllWindows() if w.title and w.title.strip()]

            if norm in ["current", "this", "this application", "active", "foreground"]:
                active = gw.getActiveWindow()
                if active and active.title:
                    target_window = active
            else:
                # 1. Direct title substring match
                matching_windows = [w for w in all_windows if norm in w.title.lower()]

                # 2. Known apps mapping fallback
                if not matching_windows and norm in KNOWN_WINDOWS_APPS:
                    known_info = KNOWN_WINDOWS_APPS[norm]
                    proc_names = [p.replace(".exe", "").lower() for p in known_info.get("proc_names", [])]
                    for w in all_windows:
                        w_lower = w.title.lower()
                        if any(pn in w_lower for pn in proc_names):
                            matching_windows.append(w)

                if matching_windows:
                    # Prefer active/foreground window if it matches, otherwise use first matching
                    active = gw.getActiveWindow()
                    if active and active in matching_windows:
                        target_window = active
                    else:
                        target_window = matching_windows[0]

            if not target_window:
                return ToolResult(
                    success=False,
                    error=(
                        f"No open window found matching application '{app_name}'. "
                        f"If the application is running in the background without a window, "
                        f"use 'terminate_process' to terminate it."
                    ),
                )

            win_title = target_window.title
            target_hwnd = getattr(target_window, "_hWnd", None)

            # Request graceful close via standard Windows WM_CLOSE (identical to clicking the X button)
            target_window.close()

            # Verify that the window actually closed
            closed = False
            for _ in range(6):
                await asyncio.sleep(0.25)
                current_windows = [w for w in gw.getAllWindows() if w.title and w.title.strip()]
                # Window is closed if its HWND or title is no longer present
                still_open = any(
                    (target_hwnd and getattr(w, "_hWnd", None) == target_hwnd) or w.title == win_title
                    for w in current_windows
                )
                if not still_open:
                    closed = True
                    break

            return ToolResult(
                success=True,
                result={
                    "success": True,
                    "action": "graceful_close",
                    "application": target,
                    "window_title": win_title,
                    "closed": closed,
                    "note": (
                        "Application window closed successfully."
                        if closed
                        else "Close signal sent. The application may be prompting to save unsaved work."
                    ),
                },
            )

        except Exception as ex:
            logger.error("Failed to gracefully close application '%s': %s", app_name, ex)
            return ToolResult(success=False, error=f"Failed to close application '{app_name}': {str(ex)}")


class TerminateProcessTool(BaseTool):
    """Forcefully terminates an operating system process by name or PID (Requires Level 3 Confirmation)."""

    name = "terminate_process"
    description = (
        "Forcefully terminate/kill a running process by process name or PID (e.g., 'kill Chrome', "
        "'force terminate Chrome', 'kill process 1234'). Requires user confirmation. "
        "Use ONLY when explicitly asked to force terminate or kill."
    )
    permission_level = PermissionLevel.HIGH_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "name_or_pid": {
                    "type": "STRING",
                    "description": "Process name (e.g. 'notepad.exe', 'chrome.exe') or numeric PID to kill",
                }
            },
            "required": ["name_or_pid"],
        }

    async def execute(self, name_or_pid: str, **kwargs) -> ToolResult:
        try:
            target = name_or_pid.strip()
            closed = []

            if target.isdigit():
                pid = int(target)
                p = psutil.Process(pid)
                p_name = p.name()
                p.terminate()
                closed.append(f"PID {pid} ({p_name})")
            else:
                norm_target = target.lower()
                target_exe = norm_target if norm_target.endswith(".exe") else f"{norm_target}.exe"
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        pname = (proc.info.get("name") or "").lower()
                        if pname in [norm_target, target_exe]:
                            proc.terminate()
                            closed.append(f"PID {proc.info['pid']} ({proc.info['name']})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            if not closed:
                return ToolResult(success=False, error=f"No matching process found for '{name_or_pid}'.")

            return ToolResult(
                success=True,
                result={
                    "action": "force_terminate",
                    "target": name_or_pid,
                    "closed": closed,
                    "count": len(closed),
                },
            )
        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to terminate '{name_or_pid}': {str(ex)}")
