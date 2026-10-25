"""Working Memory maintaining task-scoped context, intermediate variables, and tool outcomes."""

import time
from dataclasses import dataclass, field
from typing import Any
from jarvis.utils.logging import logger


@dataclass
class TaskState:
    """State tracking for an active task within working memory."""

    objective: str = ""
    current_step: int = 0
    total_steps: int = 0
    active_project: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)


class WorkingMemory:
    """Ephemeral working scratchpad for intermediate task context and execution variables."""

    def __init__(self) -> None:
        self._state = TaskState()

    @property
    def is_active(self) -> bool:
        """Check if an active objective is set."""
        return bool(self._state.objective)

    @property
    def objective(self) -> str:
        return self._state.objective

    def set_objective(self, objective: str, project: str = "", total_steps: int = 0) -> None:
        """Initialize or update the active task objective."""
        self._state.objective = objective
        self._state.active_project = project
        self._state.total_steps = total_steps
        self._state.started_at = time.time()
        logger.debug("Working memory objective set: '%s'", objective)

    def set_step(self, step_number: int) -> None:
        """Update current step index."""
        self._state.current_step = step_number

    def set_variable(self, key: str, value: Any) -> None:
        """Store an intermediate task variable."""
        self._state.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Retrieve an intermediate task variable."""
        return self._state.variables.get(key, default)

    def record_tool_result(self, tool_name: str, result: Any) -> None:
        """Log a tool execution result in working memory."""
        self._state.tool_results.append({
            "tool": tool_name,
            "result": result,
            "timestamp": time.time(),
        })

    def record_decision(self, decision: str) -> None:
        """Record a tactical decision made during task execution."""
        self._state.decisions.append(decision)
        logger.debug("Recorded task decision: %s", decision)

    def track_file_modified(self, file_path: str) -> None:
        """Keep track of files modified in this task."""
        if file_path not in self._state.modified_files:
            self._state.modified_files.append(file_path)

    def get_summary(self) -> str:
        """Format working memory state into a concise context block."""
        if not self._state.objective:
            return ""

        parts = [
            f"Active Objective: {self._state.objective}",
            f"Step: {self._state.current_step}/{self._state.total_steps}" if self._state.total_steps else f"Step: {self._state.current_step}",
        ]
        if self._state.active_project:
            parts.append(f"Project: {self._state.active_project}")
        if self._state.modified_files:
            parts.append(f"Modified Files: {', '.join(self._state.modified_files)}")
        if self._state.decisions:
            parts.append("Recent Decisions: " + "; ".join(self._state.decisions[-3:]))

        return " | ".join(parts)

    def reset(self) -> None:
        """Clear ephemeral working state when task completes."""
        self._state = TaskState()
        logger.debug("Working memory reset.")
