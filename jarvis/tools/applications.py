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


class LaunchApplicationTool(BaseTool):
    """Launches an application by name or executable path."""

    name = "launch_application"
    description = "Launch a desktop application by name or executable path (e.g., 'notepad', 'calc', 'chrome')."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Name or executable path of the application to launch",
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
            cmd = f'start "" "{app_name}" {args}' if sys.platform == "win32" else f"{app_name} {args} &"
            proc = await asyncio.create_subprocess_shell(cmd)
            return ToolResult(
                success=True,
                result={"app_name": app_name, "status": "launched", "pid": proc.pid},
            )
        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to launch application '{app_name}': {str(ex)}")


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
    """Closes an application by process name or PID (Requires Level 3 Confirmation)."""

    name = "close_application"
    description = "Terminate/close an application by process name or PID. Triggers confirmation."
    permission_level = PermissionLevel.HIGH_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "name_or_pid": {
                    "type": "STRING",
                    "description": "Process name (e.g. 'notepad.exe') or numeric PID to terminate",
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
                p.terminate()
                closed.append(f"PID {pid} ({p.name()})")
            else:
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        if proc.info["name"].lower() == target.lower():
                            proc.terminate()
                            closed.append(f"PID {proc.info['pid']} ({proc.info['name']})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            if not closed:
                return ToolResult(success=False, error=f"No matching process found for '{name_or_pid}'.")

            return ToolResult(success=True, result={"closed": closed, "count": len(closed)})
        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to terminate '{name_or_pid}': {str(ex)}")
