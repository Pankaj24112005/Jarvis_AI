"""Controlled Terminal / Shell Execution Tool with Command Safety Classification."""

import asyncio
import re
import shlex
import subprocess
from typing import Any
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger

# Commands classified as inherently destructive or critical
_HIGH_RISK_COMMANDS = re.compile(
    r"(?i)\b(del|rmdir|rd|format|shutdown|reboot|diskpart|reg|regedit|bcdedit|"
    r"icacls|takeown|net\s+user|net\s+localgroup|taskkill|kill|rm\s+-rf|dd|"
    r"mkfs|chmod\s+777|chown|powershell\s+-[eE]nc)\b"
)

# Harmless read-only commands
_SAFE_COMMANDS = re.compile(
    r"(?i)^\s*(python\s+--version|git\s+status|git\s+log|dir|ls|where|where\.exe|"
    r"echo|whoami|date|time|hostname|pip\s+list|Get-ChildItem|Get-Command)\b"
)


class TerminalExecuteTool(BaseTool):
    """Executes a shell command in a controlled subprocess with strict timeout and safety classification."""

    name = "terminal_execute"
    description = "Execute a shell command with stdout/stderr capture and safety validation."
    permission_level = PermissionLevel.HIGH_RISK  # Default to High Risk unless explicitly safe
    timeout_seconds = 30.0

    def __init__(self, default_timeout: float = 30.0) -> None:
        self.timeout_seconds = default_timeout

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Shell command to execute",
                },
                "timeout": {
                    "type": "INTEGER",
                    "description": "Optional timeout in seconds (default: 30)",
                },
            },
            "required": ["command"],
        }

    def classify_command(self, command: str) -> PermissionLevel:
        """Dynamically classify the risk level of a shell command."""
        cmd_strip = command.strip()
        if _HIGH_RISK_COMMANDS.search(cmd_strip):
            return PermissionLevel.HIGH_RISK
        if _SAFE_COMMANDS.search(cmd_strip):
            return PermissionLevel.LOW_RISK
        # General commands (e.g. running scripts, tests)
        return PermissionLevel.MODERATE

    async def execute(self, command: str, timeout: int | None = None, **kwargs) -> ToolResult:
        cmd_timeout = float(timeout or self.timeout_seconds)
        logger.info("Executing shell command: %s (timeout: %.1fs)", command, cmd_timeout)

        try:
            # Run in subprocess via asyncio
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=cmd_timeout,
                )
                stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
                stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
                exit_code = proc.returncode

                # Limit output size to prevent overflowing context
                max_chars = 4000
                truncated = len(stdout) > max_chars
                if truncated:
                    stdout = stdout[:max_chars] + f"\n... [Truncated: {len(stdout) - max_chars} characters omitted]"

                return ToolResult(
                    success=(exit_code == 0),
                    result={
                        "command": command,
                        "exit_code": exit_code,
                        "stdout": stdout,
                        "stderr": stderr,
                    },
                    error=None if exit_code == 0 else f"Process exited with non-zero code {exit_code}: {stderr}",
                )

            except asyncio.TimeoutError:
                # Force kill runaway process
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                return ToolResult(
                    success=False,
                    error=f"Command '{command}' timed out after {cmd_timeout} seconds and was terminated.",
                )

        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to execute command: {str(ex)}")
