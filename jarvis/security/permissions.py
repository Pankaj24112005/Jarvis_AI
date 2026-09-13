"""5-Tier Security Model, Permission Controller, Human Approval, and Audit Logging."""

import asyncio
import json
import re
import time
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Coroutine
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from jarvis.utils.logging import logger

_console = Console()

# Pattern for redacting sensitive values in audit logs
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|password|secret|token|auth|credential)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?"
)


class PermissionLevel(IntEnum):
    """5-Tier Security Classification for all tools and system operations."""

    SAFE = 0  # Read-only public info, internal calculations, non-sensitive queries
    LOW_RISK = 1  # Read permitted workspace files, list directories, standard web search, launch apps
    MODERATE = 2  # Create/modify workspace files, non-destructive dev commands, mouse/keyboard input
    HIGH_RISK = 3  # Delete files, run arbitrary shell commands, install software, kill processes
    CRITICAL = 4  # System/OS modifications, account/credential changes, highly destructive operations


class PermissionDecision:
    """Encapsulates the authorization decision for a tool request."""

    def __init__(self, is_approved: bool, reason: str, level: PermissionLevel) -> None:
        self.is_approved = is_approved
        self.reason = reason
        self.level = level

    def __bool__(self) -> bool:
        return self.is_approved

    def __repr__(self) -> str:
        return f"PermissionDecision(approved={self.is_approved}, level={self.level.name}, reason='{self.reason}')"


class AuditLogger:
    """Appends structured and sanitized audit entries to logs/audit.log."""

    def __init__(self, log_path: str = "logs/audit.log") -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        level: PermissionLevel | int,
        approved: bool,
        duration_ms: float = 0.0,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Write an audit entry with sanitized arguments and outcomes."""
        sanitized_args = self._sanitize_dict(arguments)
        perm_level = level if isinstance(level, PermissionLevel) else PermissionLevel(level)
        entry = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": tool_name,
            "level": int(perm_level),
            "level_name": perm_level.name,
            "approved": approved,
            "duration_ms": round(duration_ms, 2),
            "success": error is None,
            "error": error,
            "arguments": sanitized_args,
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as ex:
            logger.error("Failed to write audit log entry: %s", ex)

    def _sanitize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact sensitive key names and patterns."""
        sanitized: dict[str, Any] = {}
        for k, v in data.items():
            if any(term in k.lower() for term in ["key", "pass", "secret", "token", "auth", "cred"]):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_dict(v)
            elif isinstance(v, str):
                sanitized[k] = _SECRET_PATTERN.sub(r"\1=[REDACTED]", v)
            else:
                sanitized[k] = v
        return sanitized


ApprovalCallback = Callable[[str, dict[str, Any], PermissionLevel, str], Coroutine[Any, Any, bool]]


async def default_cli_approval_prompt(
    tool_name: str,
    arguments: dict[str, Any],
    level: PermissionLevel,
    description: str,
) -> bool:
    """Interactive console approval prompt for high-risk actions."""
    title = f"[bold red]SECURITY CONFIRMATION REQUIRED[/bold red] (Level {int(level)}: {level.name})"
    content = (
        f"[bold cyan]JARVIS[/bold cyan] wants to execute: [bold yellow]{tool_name}[/bold yellow]\n\n"
        f"[bold]Description:[/bold] {description}\n"
        f"[bold]Arguments:[/bold] {json.dumps(arguments, indent=2, default=str)}"
    )

    _console.print()
    _console.print(Panel(content, title=title, border_style="red", expand=False))

    loop = asyncio.get_running_loop()
    # Run interactive prompt without blocking event loop
    approved = await loop.run_in_executor(
        None,
        lambda: Confirm.ask(
            f"[bold red]Allow {tool_name} to execute?[/bold red]",
            default=False,
            console=_console,
        ),
    )
    return approved


class PermissionController:
    """Deterministic security gatekeeper evaluating permissions and obtaining human approval."""

    def __init__(
        self,
        confirmation_threshold: int = 3,
        approval_callback: ApprovalCallback | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.confirmation_threshold = confirmation_threshold
        self.approval_callback = approval_callback or default_cli_approval_prompt
        self.audit_logger = audit_logger or AuditLogger()

    async def check_and_authorize(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        level: PermissionLevel,
        description: str = "",
    ) -> PermissionDecision:
        """Evaluate permission level and request human confirmation if threshold is met."""
        # Level 4 is always critical and must never bypass approval
        requires_approval = (int(level) >= self.confirmation_threshold) or (level == PermissionLevel.CRITICAL)

        if not requires_approval:
            # Auto-approved
            return PermissionDecision(
                is_approved=True,
                reason=f"Auto-approved (Level {int(level)} < Threshold {self.confirmation_threshold})",
                level=level,
            )

        logger.warning(
            "Tool '%s' requires human confirmation (Level %d: %s >= %d)",
            tool_name,
            int(level),
            level.name,
            self.confirmation_threshold,
        )

        try:
            is_approved = await self.approval_callback(tool_name, arguments, level, description)
            if is_approved:
                reason = "Explicitly authorized by human user"
            else:
                reason = "Explicitly DENIED by human user"

            return PermissionDecision(is_approved=is_approved, reason=reason, level=level)

        except Exception as ex:
            logger.error("Error during approval prompt for '%s': %s", tool_name, ex)
            return PermissionDecision(is_approved=False, reason=f"Approval prompt failed: {ex}", level=level)


# Global default controller
default_permission_controller = PermissionController()
