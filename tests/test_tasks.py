"""Unit tests for Phase 8.1 Task and Workflow Data Models."""

import time
import pytest

from jarvis.tasks.model import (
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)


# ==============================================================================
# 1. Task Creation & Defaults Tests
# ==============================================================================

def test_task_creation_defaults():
    """Verify Task initializes with valid defaults, unique ID, and PENDING status."""
    goal = "Open Chrome and search for Python documentation"
    task = Task(goal=goal)

    assert task.goal == goal
    assert task.task_id.startswith("task_")
    assert len(task.task_id) > 5
    assert task.status == TaskStatus.PENDING
    assert task.steps == []
    assert task.current_step_index == 0
    assert task.total_steps == 0
    assert task.cancellation_requested is False
    assert task.failure_reason is None
    assert task.completed_at is None
    assert task.total_tool_calls == 0
    assert isinstance(task.metadata, dict)
    assert task.is_finished is False
    assert task.created_at <= time.time()
    assert task.updated_at <= time.time()


def test_unique_task_ids():
    """Verify independently created tasks receive distinct unique IDs."""
    t1 = Task(goal="Goal 1")
    t2 = Task(goal="Goal 2")
    t3 = Task(goal="Goal 3")

    ids = {t1.task_id, t2.task_id, t3.task_id}
    assert len(ids) == 3


def test_custom_task_id():
    """Verify custom task ID is preserved when provided."""
    task = Task(goal="Custom task", task_id="custom_12345")
    assert task.task_id == "custom_12345"


# ==============================================================================
# 2. TaskStep Creation & Lifecycle Tests
# ==============================================================================

def test_task_step_creation():
    """Verify TaskStep initializes with expected attributes and defaults."""
    step = TaskStep(
        index=0,
        description="Launch Chrome browser",
        tool_name="launch_application",
        arguments={"app_name": "chrome"},
        verification_method="window_title",
    )

    assert step.index == 0
    assert step.description == "Launch Chrome browser"
    assert step.tool_name == "launch_application"
    assert step.arguments == {"app_name": "chrome"}
    assert step.status == StepStatus.PENDING
    assert step.verification_method == "window_title"
    assert step.verified is False
    assert step.retries == 0
    assert step.step_id.startswith("step_0_")
    assert step.duration_ms == 0.0


def test_task_step_lifecycle_methods():
    """Verify TaskStep progression helper methods."""
    step = TaskStep(index=0, description="Read webpage", tool_name="browser_read_page")

    # 1. Mark executing
    step.mark_executing()
    assert step.status == StepStatus.EXECUTING
    assert step.started_at is not None

    # 2. Mark verifying
    step.mark_verifying(method="return_value")
    assert step.status == StepStatus.VERIFYING
    assert step.verification_method == "return_value"

    # 3. Mark success
    step.mark_success(result={"text": "documentation"}, verified=True, notes="Page text non-empty")
    assert step.status == StepStatus.SUCCESS
    assert step.verified is True
    assert step.result == {"text": "documentation"}
    assert step.verification_notes == "Page text non-empty"
    assert step.completed_at is not None
    assert step.duration_ms >= 0.0


def test_task_step_mark_failed():
    """Verify TaskStep mark_failed sets error and status."""
    step = TaskStep(index=1, description="Click missing button", tool_name="visual_grounding_click")
    step.mark_executing()
    time.sleep(0.01)
    step.mark_failed(error="Target element not found on screen")

    assert step.status == StepStatus.FAILED
    assert step.verified is False
    assert step.error == "Target element not found on screen"
    assert step.completed_at is not None
    assert step.duration_ms > 0.0


# ==============================================================================
# 3. Ordered Steps Management in Task
# ==============================================================================

def test_task_ordered_steps_and_progression():
    """Verify ordered step appending, indexing, and advancement."""
    task = Task(goal="Multi-step workflow")

    s0 = TaskStep(index=999, description="Step 1: Open app")  # index will be renumbered
    s1 = TaskStep(index=999, description="Step 2: Type text")
    s2 = TaskStep(index=999, description="Step 3: Close app")

    task.add_step(s0)
    task.add_step(s1)
    task.add_step(s2)

    assert task.total_steps == 3
    assert s0.index == 0
    assert s1.index == 1
    assert s2.index == 2

    # Current step retrieval
    assert task.get_current_step() == s0
    assert task.get_step(1) == s1
    assert task.get_step(2) == s2
    assert task.get_step(5) is None

    # Step advancement
    next_step = task.advance_step()
    assert task.current_step_index == 1
    assert next_step == s1
    assert task.get_current_step() == s1

    next_step = task.advance_step()
    assert task.current_step_index == 2
    assert next_step == s2

    # Beyond end
    next_step = task.advance_step()
    assert task.current_step_index == 3
    assert next_step is None
    assert task.get_current_step() is None


# ==============================================================================
# 4. Status Progression & Completion Tests
# ==============================================================================

def test_task_mark_completed():
    """Verify Task completion transitions status and sets timestamps."""
    task = Task(goal="Complete task")
    assert not task.is_finished

    task.mark_completed()
    assert task.status == TaskStatus.COMPLETED
    assert task.is_finished is True
    assert task.completed_at is not None
    assert task.updated_at == task.completed_at


def test_task_mark_failed():
    """Verify Task failure sets diagnostic reason and finishes task."""
    task = Task(goal="Failing task")
    task.mark_failed(reason="Step 2 timed out after 30 seconds")

    assert task.status == TaskStatus.FAILED
    assert task.is_finished is True
    assert task.failure_reason == "Step 2 timed out after 30 seconds"
    assert task.completed_at is not None


# ==============================================================================
# 5. Cancellation State Representation
# ==============================================================================

def test_task_cancellation_representation():
    """Verify request_cancellation and mark_cancelled states."""
    task = Task(goal="Task to cancel")

    assert task.cancellation_requested is False

    # 1. Request cancellation signal
    task.request_cancellation(reason="User said 'Stop'")
    assert task.cancellation_requested is True
    assert not task.is_finished

    # 2. Mark cancelled
    task.mark_cancelled(reason="User confirmed cancellation")
    assert task.status == TaskStatus.CANCELLED
    assert task.is_finished is True
    assert task.failure_reason == "User confirmed cancellation"
    assert task.completed_at is not None


# ==============================================================================
# 6. Serialization & Deserialization Round-Trip Tests
# ==============================================================================

def test_task_step_serialization_roundtrip():
    """Verify TaskStep serialization to_dict and deserialization from_dict."""
    original = TaskStep(
        index=2,
        description="Inspect active window",
        tool_name="get_active_window",
        arguments={"timeout": 5},
        step_id="step_custom_id",
        status=StepStatus.SUCCESS,
        verification_method="window_title",
        verified=True,
        verification_notes="Window confirmed",
        result={"title": "Notepad"},
        error=None,
        retries=1,
        started_at=1000.0,
        completed_at=1000.25,
        duration_ms=250.0,
    )

    data = original.to_dict()
    assert isinstance(data, dict)
    assert data["step_id"] == "step_custom_id"
    assert data["status"] == "SUCCESS"

    restored = TaskStep.from_dict(data)
    assert restored.step_id == original.step_id
    assert restored.index == original.index
    assert restored.description == original.description
    assert restored.tool_name == original.tool_name
    assert restored.arguments == original.arguments
    assert restored.status == StepStatus.SUCCESS
    assert restored.verified is True
    assert restored.result == original.result
    assert restored.duration_ms == 250.0


def test_task_serialization_roundtrip():
    """Verify Task serialization to_dict and deserialization from_dict with nested steps."""
    original = Task(
        goal="Open browser and read article",
        task_id="task_abc123",
        status=TaskStatus.EXECUTING,
        metadata={"project": "research"},
    )
    original.add_step(TaskStep(index=0, description="Open Chrome", tool_name="launch_application"))
    original.add_step(TaskStep(index=1, description="Read article", tool_name="browser_read_page"))

    data = original.to_dict()
    assert isinstance(data, dict)
    assert data["task_id"] == "task_abc123"
    assert data["status"] == "EXECUTING"
    assert len(data["steps"]) == 2
    assert data["total_steps"] == 2

    restored = Task.from_dict(data)
    assert restored.task_id == original.task_id
    assert restored.goal == original.goal
    assert restored.status == TaskStatus.EXECUTING
    assert restored.total_steps == 2
    assert restored.metadata == {"project": "research"}
    assert restored.steps[0].description == "Open Chrome"
    assert restored.steps[1].tool_name == "browser_read_page"


# ==============================================================================
# 7. Validation & Invalid Data Handling Tests
# ==============================================================================

def test_invalid_task_goal():
    """Verify Task raises ValueError if goal is empty or whitespace."""
    with pytest.raises(ValueError, match="goal must be a non-empty string"):
        Task(goal="")

    with pytest.raises(ValueError, match="goal must be a non-empty string"):
        Task(goal="   ")


def test_invalid_task_step_data():
    """Verify TaskStep raises ValueError on negative index or empty description."""
    with pytest.raises(ValueError, match="index must be a non-negative integer"):
        TaskStep(index=-1, description="Invalid negative index")

    with pytest.raises(ValueError, match="description must be a non-empty string"):
        TaskStep(index=0, description="")

    with pytest.raises(ValueError, match="description must be a non-empty string"):
        TaskStep(index=0, description="  ")


def test_invalid_status_enum():
    """Verify invalid status string or type raises error."""
    with pytest.raises(ValueError, match="Invalid TaskStatus"):
        Task(goal="Valid goal", status="INVALID_STATUS")

    with pytest.raises(ValueError, match="Invalid StepStatus"):
        TaskStep(index=0, description="Valid step", status="NON_EXISTENT_STEP_STATUS")


def test_add_invalid_step_type():
    """Verify add_step rejects non-TaskStep objects."""
    task = Task(goal="Valid goal")
    with pytest.raises(TypeError, match="Expected TaskStep instance"):
        task.add_step("not_a_step")  # type: ignore
