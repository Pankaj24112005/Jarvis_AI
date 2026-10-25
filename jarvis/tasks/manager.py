"""Authoritative TaskManager orchestrating Task lifecycle and state transitions (Phase 8.2).

Architectural Invariants:
- Exactly ONE authoritative TaskManager instance.
- TaskManager is an orchestration & lifecycle component, NOT an AI reasoning brain.
- Does NOT replace StateMachine:
    - AgentState: runtime/hardware state of JARVIS (IDLE, THINKING, TOOL_EXECUTION, etc.)
    - TaskStatus: workflow progression state of user goal (PENDING, PLANNING, EXECUTING, etc.)
- Exactly ONE active task at a time; prevents simultaneous conflicting active tasks.
"""

import asyncio
import time
from typing import Any

from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.tasks.model import Task, TaskStatus
from jarvis.utils.logging import logger


class TaskNotFoundError(KeyError):
    """Raised when operating on a non-existent task ID."""
    pass


class InvalidTaskStateTransitionError(ValueError):
    """Raised when attempting an illegal TaskStatus transition."""
    pass


class ActiveTaskConflictError(RuntimeError):
    """Raised when creating or starting a task while another task is active."""
    pass


# Deterministic state transition table for TaskStatus
_VALID_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.PLANNING,
        TaskStatus.EXECUTING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PLANNING: {
        TaskStatus.EXECUTING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.EXECUTING: {
        TaskStatus.WAITING_PERMISSION,
        TaskStatus.VERIFYING,
        TaskStatus.PAUSED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_PERMISSION: {
        TaskStatus.EXECUTING,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.VERIFYING: {
        TaskStatus.EXECUTING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PAUSED: {
        TaskStatus.EXECUTING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.COMPLETED: set(),  # Terminal state
    TaskStatus.FAILED: set(),     # Terminal state
    TaskStatus.CANCELLED: set(),  # Terminal state
}


class TaskManager:
    """Authoritative task lifecycle manager coordinating task state, events, and validation."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
    ) -> None:
        self.event_bus = event_bus or default_event_bus
        self.state_machine = state_machine
        self._tasks: dict[str, Task] = {}
        self._active_task_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def active_task_id(self) -> str | None:
        """Return currently active task ID if set."""
        return self._active_task_id

    async def create_task(
        self,
        goal: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Create and register a new task. Enforces single active task invariant."""
        async with self._lock:
            # Check if an existing task is currently active
            if self._active_task_id:
                active_task = self._tasks.get(self._active_task_id)
                if active_task and not active_task.is_finished:
                    raise ActiveTaskConflictError(
                        f"Cannot create task: Task '{self._active_task_id}' is already "
                        f"active with status '{active_task.status.value}'."
                    )

            task = Task(goal=goal, task_id=task_id or "", metadata=metadata or {})
            self._tasks[task.task_id] = task
            self._active_task_id = task.task_id

            logger.info("Task created [%s]: '%s'", task.task_id, task.goal[:60])

            await self.event_bus.emit(
                EventType.TASK_CREATED,
                {
                    "task_id": task.task_id,
                    "goal": task.goal,
                    "status": task.status.value,
                    "created_at": task.created_at,
                    "metadata": task.metadata,
                },
            )
            return task

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve task by ID without locking."""
        return self._tasks.get(task_id)

    def get_active_task(self) -> Task | None:
        """Retrieve the currently active in-flight task, if any."""
        if not self._active_task_id:
            return None
        task = self._tasks.get(self._active_task_id)
        if task and not task.is_finished:
            return task
        return None

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List tasks, optionally filtered by status."""
        if status is not None:
            return [t for t in self._tasks.values() if t.status == status]
        return list(self._tasks.values())

    async def start_task(
        self,
        task_id: str,
        to_status: TaskStatus = TaskStatus.PLANNING,
    ) -> Task:
        """Transition a PENDING task into PLANNING or EXECUTING."""
        if to_status not in (TaskStatus.PLANNING, TaskStatus.EXECUTING):
            raise ValueError(f"start_task target status must be PLANNING or EXECUTING, got {to_status}")

        async with self._lock:
            task = self._require_task(task_id)
            self._validate_transition(task.status, to_status, reason="Starting task")

            old_status = task.status
            task.status = to_status
            task.updated_at = time.time()

            logger.info("Task started [%s]: %s -> %s", task_id, old_status.value, to_status.value)

            await self._sync_state_machine(to_status, reason="Task started")

            await self.event_bus.emit(
                EventType.TASK_STARTED,
                {
                    "task_id": task_id,
                    "old_status": old_status.value,
                    "new_status": to_status.value,
                },
            )
            await self.event_bus.emit(
                EventType.TASK_STATUS_CHANGED,
                {
                    "task_id": task_id,
                    "old_status": old_status.value,
                    "new_status": to_status.value,
                    "reason": "Task started",
                },
            )
            return task

    async def transition_task(
        self,
        task_id: str,
        new_status: TaskStatus,
        reason: str = "",
    ) -> Task:
        """Perform a validated TaskStatus transition and emit change events."""
        async with self._lock:
            task = self._require_task(task_id)
            if task.status == new_status:
                return task  # Idempotent no-op

            self._validate_transition(task.status, new_status, reason=reason)

            old_status = task.status
            task.status = new_status
            now = time.time()
            task.updated_at = now

            if task.is_finished:
                task.completed_at = now
                if self._active_task_id == task_id:
                    self._active_task_id = None

            logger.info(
                "Task transition [%s]: %s -> %s%s",
                task_id,
                old_status.value,
                new_status.value,
                f" ({reason})" if reason else "",
            )

            await self._sync_state_machine(new_status, reason=reason)

            # Emit general status changed event
            await self.event_bus.emit(
                EventType.TASK_STATUS_CHANGED,
                {
                    "task_id": task_id,
                    "old_status": old_status.value,
                    "new_status": new_status.value,
                    "reason": reason,
                },
            )

            # Emit dedicated terminal or milestone events
            if new_status == TaskStatus.COMPLETED:
                duration_ms = round((now - task.created_at) * 1000, 2)
                await self.event_bus.emit(
                    EventType.TASK_COMPLETED,
                    {
                        "task_id": task_id,
                        "goal": task.goal,
                        "total_steps": task.total_steps,
                        "duration_ms": duration_ms,
                    },
                )
            elif new_status == TaskStatus.FAILED:
                await self.event_bus.emit(
                    EventType.TASK_FAILED,
                    {
                        "task_id": task_id,
                        "reason": task.failure_reason or reason,
                    },
                )
            elif new_status == TaskStatus.CANCELLED:
                await self.event_bus.emit(
                    EventType.TASK_CANCELLED,
                    {
                        "task_id": task_id,
                        "reason": task.failure_reason or reason,
                    },
                )
            elif new_status == TaskStatus.PAUSED:
                await self.event_bus.emit(
                    EventType.TASK_PAUSED,
                    {
                        "task_id": task_id,
                        "reason": reason,
                    },
                )

            return task

    async def pause_task(self, task_id: str, reason: str = "") -> Task:
        """Pause an actively executing or waiting task."""
        return await self.transition_task(task_id, TaskStatus.PAUSED, reason=reason or "Task paused")

    async def resume_task(self, task_id: str, reason: str = "") -> Task:
        """Resume a paused task back to EXECUTING."""
        task = await self.transition_task(task_id, TaskStatus.EXECUTING, reason=reason or "Task resumed")
        await self.event_bus.emit(
            EventType.TASK_RESUMED,
            {"task_id": task_id, "reason": reason or "Task resumed"},
        )
        return task

    async def request_cancellation(self, task_id: str, reason: str = "User requested cancellation") -> Task:
        """Signal cancellation intent on a task. Idempotent."""
        async with self._lock:
            task = self._require_task(task_id)
            if task.is_finished:
                return task  # Already finished, cancellation request ignored

            if not task.cancellation_requested:
                task.cancellation_requested = True
                task.updated_at = time.time()
                logger.info("Cancellation requested for task [%s]: %s", task_id, reason)
                await self.event_bus.emit(
                    EventType.TASK_CANCEL_REQUESTED,
                    {"task_id": task_id, "reason": reason},
                )
            return task

    async def cancel_task(self, task_id: str, reason: str = "User cancelled task") -> Task:
        """Transition task to CANCELLED state. Idempotent."""
        async with self._lock:
            task = self._require_task(task_id)
            if task.status == TaskStatus.CANCELLED:
                return task

            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                raise InvalidTaskStateTransitionError(
                    f"Cannot cancel task '{task_id}' because it has already reached terminal status '{task.status.value}'."
                )

            self._validate_transition(task.status, TaskStatus.CANCELLED, reason=reason)

            old_status = task.status
            task.mark_cancelled(reason=reason)
            if self._active_task_id == task_id:
                self._active_task_id = None

            logger.info("Task cancelled [%s]: %s", task_id, reason)

            await self._sync_state_machine(TaskStatus.CANCELLED, reason=reason)

            await self.event_bus.emit(
                EventType.TASK_STATUS_CHANGED,
                {
                    "task_id": task_id,
                    "old_status": old_status.value,
                    "new_status": TaskStatus.CANCELLED.value,
                    "reason": reason,
                },
            )
            await self.event_bus.emit(
                EventType.TASK_CANCELLED,
                {
                    "task_id": task_id,
                    "reason": reason,
                },
            )
            return task

    async def complete_task(self, task_id: str) -> Task:
        """Mark task as successfully completed."""
        async with self._lock:
            task = self._require_task(task_id)
            self._validate_transition(task.status, TaskStatus.COMPLETED, reason="Goal achieved")

            old_status = task.status
            task.mark_completed()
            if self._active_task_id == task_id:
                self._active_task_id = None

            logger.info("Task completed [%s]: '%s'", task_id, task.goal[:60])

            await self._sync_state_machine(TaskStatus.COMPLETED, reason="Task completed")

            await self.event_bus.emit(
                EventType.TASK_STATUS_CHANGED,
                {
                    "task_id": task_id,
                    "old_status": old_status.value,
                    "new_status": TaskStatus.COMPLETED.value,
                    "reason": "Goal achieved",
                },
            )
            duration_ms = round((task.completed_at - task.created_at) * 1000, 2) if task.completed_at else 0.0
            await self.event_bus.emit(
                EventType.TASK_COMPLETED,
                {
                    "task_id": task_id,
                    "goal": task.goal,
                    "total_steps": task.total_steps,
                    "duration_ms": duration_ms,
                },
            )
            return task

    async def fail_task(self, task_id: str, reason: str) -> Task:
        """Mark task as failed with diagnostic reason."""
        async with self._lock:
            task = self._require_task(task_id)
            self._validate_transition(task.status, TaskStatus.FAILED, reason=reason)

            old_status = task.status
            task.mark_failed(reason=reason)
            if self._active_task_id == task_id:
                self._active_task_id = None

            logger.warning("Task failed [%s]: %s", task_id, reason)

            await self._sync_state_machine(TaskStatus.FAILED, reason=reason)

            await self.event_bus.emit(
                EventType.TASK_STATUS_CHANGED,
                {
                    "task_id": task_id,
                    "old_status": old_status.value,
                    "new_status": TaskStatus.FAILED.value,
                    "reason": reason,
                },
            )
            await self.event_bus.emit(
                EventType.TASK_FAILED,
                {
                    "task_id": task_id,
                    "reason": reason,
                },
            )
            return task

    def clear_finished_tasks(self) -> int:
        """Remove finished (completed, failed, cancelled) tasks from internal registry."""
        finished_ids = [tid for tid, t in self._tasks.items() if t.is_finished]
        for tid in finished_ids:
            del self._tasks[tid]
        return len(finished_ids)

    def _require_task(self, task_id: str) -> Task:
        """Internal helper to retrieve task or raise TaskNotFoundError."""
        task = self._tasks.get(task_id)
        if not task:
            raise TaskNotFoundError(f"Task with ID '{task_id}' not found.")
        return task

    def _validate_transition(self, current: TaskStatus, target: TaskStatus, reason: str = "") -> None:
        """Validate if transition from current to target TaskStatus is permitted."""
        valid_targets = _VALID_TASK_TRANSITIONS.get(current, set())
        if target not in valid_targets:
            raise InvalidTaskStateTransitionError(
                f"Illegal task transition from {current.value} to {target.value}"
                f"{f' (reason: {reason})' if reason else ''}."
            )

    async def _sync_state_machine(self, new_task_status: TaskStatus, reason: str = "") -> None:
        """Optional synchronization with the authoritative AgentState StateMachine."""
        if not self.state_machine:
            return

        try:
            curr_agent_state = self.state_machine.current_state

            if new_task_status == TaskStatus.PLANNING:
                if curr_agent_state == AgentState.IDLE:
                    await self.state_machine.transition_to(
                        AgentState.THINKING,
                        reason=f"Task planning: {reason}",
                    )
            elif new_task_status == TaskStatus.EXECUTING:
                if curr_agent_state == AgentState.IDLE:
                    await self.state_machine.transition_to(
                        AgentState.THINKING,
                        reason=f"Task preparing: {reason}",
                    )
                    curr_agent_state = self.state_machine.current_state
                if curr_agent_state in (AgentState.THINKING, AgentState.WAITING_FOR_PERMISSION):
                    await self.state_machine.transition_to(
                        AgentState.TOOL_EXECUTION,
                        reason=f"Task executing: {reason}",
                    )
            elif new_task_status == TaskStatus.WAITING_PERMISSION:
                if curr_agent_state != AgentState.WAITING_FOR_PERMISSION:
                    await self.state_machine.transition_to(
                        AgentState.WAITING_FOR_PERMISSION,
                        reason=f"Task awaiting permission: {reason}",
                    )
            elif new_task_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if curr_agent_state in (AgentState.TOOL_EXECUTION, AgentState.WAITING_FOR_PERMISSION):
                    await self.state_machine.transition_to(
                        AgentState.IDLE,
                        reason=f"Task {new_task_status.value}: {reason}",
                    )
        except Exception as ex:
            # StateMachine synchronization is advisory; do not crash task lifecycle on state machine desync
            logger.debug("StateMachine synchronization notice: %s", ex)
