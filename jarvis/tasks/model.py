"""Foundational Task and Workflow Data Models for JARVIS Phase 8.

Architectural Distinction:
- AgentState (jarvis.core.state.AgentState):
    Governs overall system operational, interaction, and hardware states:
    IDLE, LISTENING, THINKING, TOOL_EXECUTION, WAITING_FOR_PERMISSION, SPEAKING, ERROR, CANCELLED.
- TaskStatus (jarvis.tasks.model.TaskStatus):
    Governs the workflow progression of a multi-step user goal:
    PENDING, PLANNING, EXECUTING, WAITING_PERMISSION, VERIFYING, PAUSED, COMPLETED, FAILED, CANCELLED.
- StepStatus (jarvis.tasks.model.StepStatus):
    Governs the lifecycle of an individual atomic step within a task:
    PENDING, EXECUTING, WAITING_PERMISSION, VERIFYING, SUCCESS, FAILED, SKIPPED.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any
import uuid


class TaskStatus(str, Enum):
    """Lifecycle status of a multi-step workflow task."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    VERIFYING = "VERIFYING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepStatus(str, Enum):
    """Lifecycle status of an individual step within a task."""

    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    VERIFYING = "VERIFYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class TaskStep:
    """Represents a discrete, ordered step within a multi-step task workflow."""

    index: int
    description: str
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    step_id: str = ""
    status: StepStatus = StepStatus.PENDING
    verification_method: str = "none"  # "window_title", "screen_change", "exit_code", "return_value", "none"
    verified: bool = False
    verification_notes: str = ""
    result: Any = None
    error: str | None = None
    retries: int = 0
    started_at: float | None = None
    completed_at: float | None = None
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.index, int) or self.index < 0:
            raise ValueError(f"TaskStep index must be a non-negative integer, got {self.index!r}")
        if not self.description or not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("TaskStep description must be a non-empty string")
        if not self.step_id:
            self.step_id = f"step_{self.index}_{uuid.uuid4().hex[:6]}"

        if isinstance(self.status, str):
            try:
                self.status = StepStatus(self.status)
            except ValueError:
                raise ValueError(f"Invalid StepStatus: '{self.status}'")
        elif not isinstance(self.status, StepStatus):
            raise TypeError(f"status must be a StepStatus instance, got {type(self.status)}")

    def mark_executing(self) -> None:
        """Mark step as actively executing."""
        self.status = StepStatus.EXECUTING
        self.started_at = time.time()

    def mark_verifying(self, method: str = "") -> None:
        """Mark step as undergoing outcome verification."""
        self.status = StepStatus.VERIFYING
        if method:
            self.verification_method = method

    def mark_success(self, result: Any = None, verified: bool = True, notes: str = "") -> None:
        """Mark step as successfully completed and verified."""
        self.status = StepStatus.SUCCESS
        self.result = result
        self.verified = verified
        if notes:
            self.verification_notes = notes
        self.completed_at = time.time()
        if self.started_at:
            self.duration_ms = round((self.completed_at - self.started_at) * 1000, 2)

    def mark_failed(self, error: str, verified: bool = False) -> None:
        """Mark step as failed."""
        self.status = StepStatus.FAILED
        self.error = error
        self.verified = verified
        self.completed_at = time.time()
        if self.started_at:
            self.duration_ms = round((self.completed_at - self.started_at) * 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize step to a JSON-compatible dictionary."""
        return {
            "step_id": self.step_id,
            "index": self.index,
            "description": self.description,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "verification_method": self.verification_method,
            "verified": self.verified,
            "verification_notes": self.verification_notes,
            "result": self.result,
            "error": self.error,
            "retries": self.retries,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskStep":
        """Deserialize step from a dictionary."""
        raw = dict(data)
        if "status" in raw and isinstance(raw["status"], str):
            raw["status"] = StepStatus(raw["status"])
        return cls(**raw)


@dataclass
class Task:
    """Authoritative data model for a multi-step user task / workflow."""

    goal: str
    task_id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    steps: list[TaskStep] = field(default_factory=list)
    current_step_index: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    cancellation_requested: bool = False
    failure_reason: str | None = None
    total_tool_calls: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.goal or not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("Task goal must be a non-empty string")
        if not self.task_id:
            self.task_id = f"task_{uuid.uuid4().hex[:8]}"

        if isinstance(self.status, str):
            try:
                self.status = TaskStatus(self.status)
            except ValueError:
                raise ValueError(f"Invalid TaskStatus: '{self.status}'")
        elif not isinstance(self.status, TaskStatus):
            raise TypeError(f"status must be a TaskStatus instance, got {type(self.status)}")

    @property
    def total_steps(self) -> int:
        """Total number of declared steps."""
        return len(self.steps)

    @property
    def is_finished(self) -> bool:
        """Check whether task reached a terminal state."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    def add_step(self, step: TaskStep) -> TaskStep:
        """Append an ordered step to the workflow."""
        if not isinstance(step, TaskStep):
            raise TypeError(f"Expected TaskStep instance, got {type(step)}")
        step.index = len(self.steps)
        self.steps.append(step)
        self.updated_at = time.time()
        return step

    def get_current_step(self) -> TaskStep | None:
        """Retrieve active step by current_step_index."""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def get_step(self, index: int) -> TaskStep | None:
        """Retrieve step by index."""
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None

    def advance_step(self) -> TaskStep | None:
        """Advance current step index and return new active step if available."""
        self.current_step_index += 1
        self.updated_at = time.time()
        return self.get_current_step()

    def mark_completed(self) -> None:
        """Mark task as successfully completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = time.time()
        self.updated_at = self.completed_at

    def mark_failed(self, reason: str) -> None:
        """Mark task as failed with diagnostic reason."""
        self.status = TaskStatus.FAILED
        self.failure_reason = reason
        self.completed_at = time.time()
        self.updated_at = self.completed_at

    def request_cancellation(self, reason: str = "User requested cancellation") -> None:
        """Signal cancellation request."""
        self.cancellation_requested = True
        self.updated_at = time.time()

    def mark_cancelled(self, reason: str = "User cancelled task") -> None:
        """Mark task as terminated by cancellation."""
        self.status = TaskStatus.CANCELLED
        self.cancellation_requested = True
        self.failure_reason = reason
        self.completed_at = time.time()
        self.updated_at = self.completed_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize complete task with nested steps to a dictionary."""
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_index": self.current_step_index,
            "total_steps": self.total_steps,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "cancellation_requested": self.cancellation_requested,
            "failure_reason": self.failure_reason,
            "total_tool_calls": self.total_tool_calls,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Deserialize complete task from a dictionary."""
        raw = dict(data)
        raw.pop("total_steps", None)  # computed property

        if "status" in raw and isinstance(raw["status"], str):
            raw["status"] = TaskStatus(raw["status"])

        raw_steps = raw.pop("steps", [])
        steps = [TaskStep.from_dict(s) for s in raw_steps]

        task = cls(**raw)
        task.steps = steps
        return task
