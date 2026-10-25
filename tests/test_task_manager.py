"""Unit tests for Phase 8.2 TaskManager and Lifecycle Engine."""

import pytest

from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType
from jarvis.tasks.manager import (
    ActiveTaskConflictError,
    InvalidTaskStateTransitionError,
    TaskManager,
    TaskNotFoundError,
)
from jarvis.tasks.model import TaskStatus


# ==============================================================================
# 1. Task Creation & Active Task Registration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_task_creation_and_active_registration():
    """Verify TaskManager creates task, registers it as active, and emits TASK_CREATED."""
    bus = EventBus()
    events_received = []

    def handle_event(evt):
        events_received.append(evt)

    bus.subscribe(EventType.TASK_CREATED, handle_event)
    manager = TaskManager(event_bus=bus)

    task = await manager.create_task(goal="Search Python docs", metadata={"session": "test1"})

    assert task.goal == "Search Python docs"
    assert task.status == TaskStatus.PENDING
    assert manager.active_task_id == task.task_id
    assert manager.get_active_task() == task
    assert manager.get_task(task.task_id) == task

    assert len(events_received) == 1
    assert events_received[0].data["task_id"] == task.task_id
    assert events_received[0].data["goal"] == "Search Python docs"


@pytest.mark.asyncio
async def test_unique_task_ids_across_sequential_tasks():
    """Verify sequential tasks created after completion receive distinct IDs."""
    manager = TaskManager()

    t1 = await manager.create_task(goal="Goal 1")
    await manager.start_task(t1.task_id)
    await manager.transition_task(t1.task_id, TaskStatus.EXECUTING)
    await manager.complete_task(t1.task_id)

    t2 = await manager.create_task(goal="Goal 2")

    assert t1.task_id != t2.task_id
    assert manager.get_task(t1.task_id) == t1
    assert manager.get_task(t2.task_id) == t2
    assert manager.get_active_task() == t2


# ==============================================================================
# 2. Conflicting Active Task Prevention Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_prevent_conflicting_simultaneous_active_tasks():
    """Verify creating a second task fails while another task is in progress."""
    manager = TaskManager()

    t1 = await manager.create_task(goal="In-flight goal")
    assert manager.get_active_task() == t1

    with pytest.raises(ActiveTaskConflictError, match="is already active with status 'PENDING'"):
        await manager.create_task(goal="Conflicting second goal")

    # Start and move to EXECUTING
    await manager.start_task(t1.task_id)
    await manager.transition_task(t1.task_id, TaskStatus.EXECUTING)

    with pytest.raises(ActiveTaskConflictError, match="is already active with status 'EXECUTING'"):
        await manager.create_task(goal="Conflicting second goal")


# ==============================================================================
# 3. Happy Path Lifecycle Transitions Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_complete_task_lifecycle_happy_path():
    """Verify progression PENDING -> PLANNING -> EXECUTING -> VERIFYING -> COMPLETED."""
    bus = EventBus()
    status_changes = []

    def handle_status_change(evt):
        status_changes.append(evt.data["new_status"])

    bus.subscribe(EventType.TASK_STATUS_CHANGED, handle_status_change)
    manager = TaskManager(event_bus=bus)

    task = await manager.create_task(goal="Complete lifecycle task")
    assert task.status == TaskStatus.PENDING

    # 1. Start task -> PLANNING
    await manager.start_task(task.task_id, to_status=TaskStatus.PLANNING)
    assert task.status == TaskStatus.PLANNING

    # 2. PLANNING -> EXECUTING
    await manager.transition_task(task.task_id, TaskStatus.EXECUTING, reason="Plan ready")
    assert task.status == TaskStatus.EXECUTING

    # 3. EXECUTING -> VERIFYING
    await manager.transition_task(task.task_id, TaskStatus.VERIFYING, reason="Validating step result")
    assert task.status == TaskStatus.VERIFYING

    # 4. VERIFYING -> COMPLETED
    completed_task = await manager.complete_task(task.task_id)
    assert completed_task.status == TaskStatus.COMPLETED
    assert completed_task.is_finished is True
    assert completed_task.completed_at is not None

    # Verify active task is cleared
    assert manager.active_task_id is None
    assert manager.get_active_task() is None

    assert status_changes == ["PLANNING", "EXECUTING", "VERIFYING", "COMPLETED"]


@pytest.mark.asyncio
async def test_pause_and_resume_lifecycle():
    """Verify EXECUTING -> PAUSED -> EXECUTING transition sequence."""
    bus = EventBus()
    paused_events = []
    resumed_events = []

    bus.subscribe(EventType.TASK_PAUSED, lambda evt: paused_events.append(evt))
    bus.subscribe(EventType.TASK_RESUMED, lambda evt: resumed_events.append(evt))

    manager = TaskManager(event_bus=bus)
    task = await manager.create_task(goal="Pausable task")
    await manager.start_task(task.task_id, to_status=TaskStatus.EXECUTING)

    # Pause task
    await manager.pause_task(task.task_id, reason="User paused")
    assert task.status == TaskStatus.PAUSED
    assert len(paused_events) == 1

    # Resume task
    await manager.resume_task(task.task_id, reason="User resumed")
    assert task.status == TaskStatus.EXECUTING
    assert len(resumed_events) == 1


@pytest.mark.asyncio
async def test_waiting_permission_and_resume():
    """Verify EXECUTING -> WAITING_PERMISSION -> EXECUTING sequence."""
    manager = TaskManager()
    task = await manager.create_task(goal="Task with high-risk action")
    await manager.start_task(task.task_id, to_status=TaskStatus.EXECUTING)

    await manager.transition_task(task.task_id, TaskStatus.WAITING_PERMISSION, reason="Requires permission")
    assert task.status == TaskStatus.WAITING_PERMISSION

    await manager.transition_task(task.task_id, TaskStatus.EXECUTING, reason="Permission granted")
    assert task.status == TaskStatus.EXECUTING


# ==============================================================================
# 4. Invalid State Transition Enforcement Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_invalid_state_transition_pending_to_completed():
    """Verify PENDING -> COMPLETED is rejected."""
    manager = TaskManager()
    task = await manager.create_task(goal="Direct completion task")

    with pytest.raises(InvalidTaskStateTransitionError, match="Illegal task transition from PENDING to COMPLETED"):
        await manager.complete_task(task.task_id)


@pytest.mark.asyncio
async def test_invalid_state_transition_completed_to_executing():
    """Verify terminal state COMPLETED cannot transition to EXECUTING."""
    manager = TaskManager()
    task = await manager.create_task(goal="Completed task")
    await manager.start_task(task.task_id, to_status=TaskStatus.EXECUTING)
    await manager.complete_task(task.task_id)

    with pytest.raises(InvalidTaskStateTransitionError, match="Illegal task transition from COMPLETED to EXECUTING"):
        await manager.transition_task(task.task_id, TaskStatus.EXECUTING)


@pytest.mark.asyncio
async def test_invalid_state_transition_cancelled_to_executing():
    """Verify terminal state CANCELLED cannot transition to EXECUTING."""
    manager = TaskManager()
    task = await manager.create_task(goal="Cancelled task")
    await manager.cancel_task(task.task_id)

    with pytest.raises(InvalidTaskStateTransitionError, match="Illegal task transition from CANCELLED to EXECUTING"):
        await manager.transition_task(task.task_id, TaskStatus.EXECUTING)


@pytest.mark.asyncio
async def test_invalid_state_transition_failed_to_executing():
    """Verify terminal state FAILED cannot transition to EXECUTING."""
    manager = TaskManager()
    task = await manager.create_task(goal="Failed task")
    await manager.fail_task(task.task_id, reason="Error occurred")

    with pytest.raises(InvalidTaskStateTransitionError, match="Illegal task transition from FAILED to EXECUTING"):
        await manager.transition_task(task.task_id, TaskStatus.EXECUTING)


# ==============================================================================
# 5. Cancellation Lifecycle & Idempotency Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_cancellation_flow_and_idempotency():
    """Verify request_cancellation sets flag and cancel_task marks CANCELLED idempotently."""
    bus = EventBus()
    cancel_requests = []
    cancelled_events = []

    bus.subscribe(EventType.TASK_CANCEL_REQUESTED, lambda evt: cancel_requests.append(evt))
    bus.subscribe(EventType.TASK_CANCELLED, lambda evt: cancelled_events.append(evt))

    manager = TaskManager(event_bus=bus)
    task = await manager.create_task(goal="Task to cancel")
    await manager.start_task(task.task_id, to_status=TaskStatus.EXECUTING)

    # 1. Request cancellation
    await manager.request_cancellation(task.task_id, reason="User said 'Stop'")
    assert task.cancellation_requested is True
    assert task.status == TaskStatus.EXECUTING  # Still executing until cancel_task is finalized
    assert len(cancel_requests) == 1

    # Repeated request_cancellation is idempotent (does not emit duplicate event)
    await manager.request_cancellation(task.task_id, reason="User said 'Stop' again")
    assert len(cancel_requests) == 1

    # 2. Finalize cancellation
    await manager.cancel_task(task.task_id, reason="Halted execution")
    assert task.status == TaskStatus.CANCELLED
    assert task.is_finished is True
    assert task.failure_reason == "Halted execution"
    assert manager.get_active_task() is None
    assert len(cancelled_events) == 1

    # Repeated cancel_task is idempotent
    await manager.cancel_task(task.task_id, reason="Redundant cancel")
    assert len(cancelled_events) == 1


@pytest.mark.asyncio
async def test_cannot_cancel_already_completed_task():
    """Verify attempting to cancel a COMPLETED task raises an error."""
    manager = TaskManager()
    task = await manager.create_task(goal="Done task")
    await manager.start_task(task.task_id, to_status=TaskStatus.EXECUTING)
    await manager.complete_task(task.task_id)

    with pytest.raises(InvalidTaskStateTransitionError, match="Cannot cancel task.*already reached terminal status 'COMPLETED'"):
        await manager.cancel_task(task.task_id)


# ==============================================================================
# 6. Failure Lifecycle Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_fail_task_lifecycle():
    """Verify failing a task sets status FAILED, records reason, and clears active task."""
    bus = EventBus()
    failed_events = []
    bus.subscribe(EventType.TASK_FAILED, lambda evt: failed_events.append(evt))

    manager = TaskManager(event_bus=bus)
    task = await manager.create_task(goal="Doomed task")
    await manager.start_task(task.task_id, to_status=TaskStatus.PLANNING)

    await manager.fail_task(task.task_id, reason="Planning decomposition impossible")
    assert task.status == TaskStatus.FAILED
    assert task.failure_reason == "Planning decomposition impossible"
    assert task.is_finished is True
    assert manager.get_active_task() is None
    assert len(failed_events) == 1
    assert failed_events[0].data["reason"] == "Planning decomposition impossible"


# ==============================================================================
# 7. Non-Existent Task Handling Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_non_existent_task_operations_raise_task_not_found():
    """Verify operations on non-existent task IDs raise TaskNotFoundError."""
    manager = TaskManager()

    with pytest.raises(TaskNotFoundError, match="Task with ID 'ghost_task' not found"):
        await manager.start_task("ghost_task")

    with pytest.raises(TaskNotFoundError, match="Task with ID 'ghost_task' not found"):
        await manager.transition_task("ghost_task", TaskStatus.EXECUTING)

    with pytest.raises(TaskNotFoundError, match="Task with ID 'ghost_task' not found"):
        await manager.complete_task("ghost_task")

    with pytest.raises(TaskNotFoundError, match="Task with ID 'ghost_task' not found"):
        await manager.fail_task("ghost_task", reason="Error")

    with pytest.raises(TaskNotFoundError, match="Task with ID 'ghost_task' not found"):
        await manager.cancel_task("ghost_task")


# ==============================================================================
# 8. Finished Tasks Cleanup & Listing Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_list_and_clear_finished_tasks():
    """Verify task filtering and clearing of completed/failed/cancelled tasks."""
    manager = TaskManager()

    t1 = await manager.create_task(goal="Task 1")
    await manager.start_task(t1.task_id, to_status=TaskStatus.EXECUTING)
    await manager.complete_task(t1.task_id)

    t2 = await manager.create_task(goal="Task 2")
    await manager.fail_task(t2.task_id, reason="Failed")

    t3 = await manager.create_task(goal="Task 3")
    # t3 remains active

    all_tasks = manager.list_tasks()
    assert len(all_tasks) == 3

    completed = manager.list_tasks(status=TaskStatus.COMPLETED)
    assert len(completed) == 1
    assert completed[0] == t1

    # Clear finished tasks (t1, t2)
    cleared_count = manager.clear_finished_tasks()
    assert cleared_count == 2

    # Active t3 remains
    remaining = manager.list_tasks()
    assert len(remaining) == 1
    assert remaining[0] == t3
    assert manager.get_active_task() == t3


# ==============================================================================
# 9. StateMachine Synchronization & Separation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_state_machine_synchronization():
    """Verify TaskManager optionally updates StateMachine on key task events."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    manager = TaskManager(event_bus=bus, state_machine=sm)

    assert sm.current_state == AgentState.IDLE

    task = await manager.create_task(goal="Synced task")
    assert sm.current_state == AgentState.IDLE

    # Starting -> EXECUTING transitions StateMachine to TOOL_EXECUTION
    await manager.start_task(task.task_id, to_status=TaskStatus.EXECUTING)
    assert sm.current_state == AgentState.TOOL_EXECUTION

    # WAITING_PERMISSION transitions StateMachine to WAITING_FOR_PERMISSION
    await manager.transition_task(task.task_id, TaskStatus.WAITING_PERMISSION, reason="Waiting for approval")
    assert sm.current_state == AgentState.WAITING_FOR_PERMISSION

    # Permission approved -> EXECUTING transitions back to TOOL_EXECUTION
    await manager.transition_task(task.task_id, TaskStatus.EXECUTING, reason="Approved")
    assert sm.current_state == AgentState.TOOL_EXECUTION

    # Task completed transitions StateMachine back to IDLE
    await manager.complete_task(task.task_id)
    assert sm.current_state == AgentState.IDLE
