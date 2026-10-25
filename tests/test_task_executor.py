"""Unit and Integration Tests for Phase 8.3 Step Execution & Dispatching."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType
from jarvis.security.permissions import (
    AuditLogger,
    PermissionController,
    PermissionLevel,
)
from jarvis.tasks.executor import (
    StepExecutionResult,
    StepExecutor,
    sanitize_step_result,
    sanitize_telemetry_dict,
)
from jarvis.tasks.model import StepStatus, Task, TaskStep
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.tools.registry import ToolRegistry


# ==============================================================================
# Test Fixtures & Dummy Tools
# ==============================================================================

class SafeEchoTool(BaseTool):
    name = "safe_echo"
    description = "Echoes a message safely."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self):
        return {
            "type": "OBJECT",
            "properties": {
                "message": {"type": "STRING", "description": "Text to echo"}
            },
            "required": ["message"],
        }

    async def execute(self, message: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, result={"echo": message})


class DangerousActionTool(BaseTool):
    name = "dangerous_action"
    description = "Performs a high-risk operation requiring approval."
    permission_level = PermissionLevel.HIGH_RISK

    @property
    def parameters_schema(self):
        return {
            "type": "OBJECT",
            "properties": {
                "target": {"type": "STRING", "description": "Target resource"}
            },
            "required": ["target"],
        }

    async def execute(self, target: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, result={"deleted": target})


class CrashingTool(BaseTool):
    name = "crashing_tool"
    description = "Always raises an unhandled exception."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("Simulated internal tool crash")


class CapturePayloadTool(BaseTool):
    name = "capture_payload"
    description = "Returns a result containing an image base64 blob."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            result={
                "status": "captured",
                "width": 1920,
                "height": 1080,
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk" * 50,
            },
        )


# ==============================================================================
# 1. Tool Resolution & Execution Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_registered_tool_resolves_and_executes_successfully():
    """Verify StepExecutor resolves tool from ToolRegistry and executes successfully."""
    registry = ToolRegistry()
    registry.register(SafeEchoTool())
    bus = EventBus()
    controller = PermissionController()

    executor = StepExecutor(
        tool_registry=registry,
        permission_controller=controller,
        event_bus=bus,
    )

    step = TaskStep(
        index=0,
        description="Echo greeting",
        tool_name="safe_echo",
        arguments={"message": "Hello JARVIS"},
    )
    task = Task(goal="Greet user")

    res = await executor.execute_step(step=step, task=task)

    assert isinstance(res, StepExecutionResult)
    assert res.success is True
    assert res.status == StepStatus.SUCCESS
    assert res.result == {"echo": "Hello JARVIS"}
    assert res.error is None
    assert res.duration_ms >= 0.0

    # TaskStep model verification
    assert step.status == StepStatus.SUCCESS
    assert step.result == {"echo": "Hello JARVIS"}
    assert step.completed_at is not None
    assert step.duration_ms >= 0.0


@pytest.mark.asyncio
async def test_unknown_tool_fails_safely():
    """Verify unregistered tool fails gracefully without throwing an unhandled exception."""
    registry = ToolRegistry()
    bus = EventBus()
    controller = PermissionController()
    executor = StepExecutor(
        tool_registry=registry,
        permission_controller=controller,
        event_bus=bus,
    )

    step = TaskStep(
        index=0,
        description="Execute imaginary tool",
        tool_name="non_existent_tool",
        arguments={"foo": "bar"},
    )

    res = await executor.execute_step(step=step)

    assert res.success is False
    assert res.status == StepStatus.FAILED
    assert "not registered in ToolRegistry" in (res.error or "")
    assert step.status == StepStatus.FAILED
    assert "not registered in ToolRegistry" in (step.error or "")


# ==============================================================================
# 2. Argument Validation & Failure Handling Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_invalid_arguments_fails_execution():
    """Verify missing required arguments are caught by ToolRegistry validation."""
    registry = ToolRegistry()
    registry.register(SafeEchoTool())  # requires 'message'
    executor = StepExecutor(tool_registry=registry)

    step = TaskStep(
        index=0,
        description="Call echo without message",
        tool_name="safe_echo",
        arguments={},  # missing required 'message'
    )

    res = await executor.execute_step(step=step)

    assert res.success is False
    assert res.status == StepStatus.FAILED
    assert "Argument validation failed" in (res.error or "")
    assert step.status == StepStatus.FAILED


@pytest.mark.asyncio
async def test_tool_exception_handled_gracefully():
    """Verify tool raising unhandled exception is caught and marked as FAILED."""
    registry = ToolRegistry()
    registry.register(CrashingTool())
    executor = StepExecutor(tool_registry=registry)

    step = TaskStep(
        index=0,
        description="Run crashing tool",
        tool_name="crashing_tool",
        arguments={},
    )

    res = await executor.execute_step(step=step)

    assert res.success is False
    assert res.status == StepStatus.FAILED
    assert "Simulated internal tool crash" in (res.error or "")
    assert step.status == StepStatus.FAILED


# ==============================================================================
# 3. Permission Gating & Human Approval Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_low_risk_tool_auto_approved():
    """Verify Level 1 tools execute automatically without human confirmation prompt."""
    registry = ToolRegistry()
    registry.register(SafeEchoTool())
    prompt_called = False

    async def mock_approval(*args, **kwargs):
        nonlocal prompt_called
        prompt_called = True
        return True

    controller = PermissionController(confirmation_threshold=3, approval_callback=mock_approval)
    executor = StepExecutor(tool_registry=registry, permission_controller=controller)

    step = TaskStep(index=0, description="Auto-approved echo", tool_name="safe_echo", arguments={"message": "hi"})
    res = await executor.execute_step(step=step)

    assert res.success is True
    assert prompt_called is False


@pytest.mark.asyncio
async def test_high_risk_tool_prompts_and_executes_when_approved():
    """Verify Level 3 tool prompts for approval and succeeds if user approves."""
    registry = ToolRegistry()
    registry.register(DangerousActionTool())
    prompt_called = False

    async def mock_approval_allow(tool_name, arguments, level, description):
        nonlocal prompt_called
        prompt_called = True
        assert tool_name == "dangerous_action"
        assert level == PermissionLevel.HIGH_RISK
        return True

    controller = PermissionController(confirmation_threshold=3, approval_callback=mock_approval_allow)
    executor = StepExecutor(tool_registry=registry, permission_controller=controller)

    step = TaskStep(index=0, description="Delete file", tool_name="dangerous_action", arguments={"target": "temp.txt"})
    res = await executor.execute_step(step=step)

    assert prompt_called is True
    assert res.success is True
    assert res.status == StepStatus.SUCCESS
    assert res.result == {"deleted": "temp.txt"}


@pytest.mark.asyncio
async def test_high_risk_tool_fails_when_permission_denied():
    """Verify Level 3 tool is blocked when user denies confirmation."""
    registry = ToolRegistry()
    registry.register(DangerousActionTool())

    async def mock_approval_deny(*args, **kwargs):
        return False  # Explicit human denial

    controller = PermissionController(confirmation_threshold=3, approval_callback=mock_approval_deny)
    executor = StepExecutor(tool_registry=registry, permission_controller=controller)

    step = TaskStep(index=0, description="Delete file", tool_name="dangerous_action", arguments={"target": "important.db"})
    res = await executor.execute_step(step=step)

    assert res.success is False
    assert res.status == StepStatus.FAILED
    assert "Permission denied" in (res.error or "")
    assert step.status == StepStatus.FAILED


# ==============================================================================
# 4. Cancellation Boundary Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_step_aborts_if_task_already_requested_cancellation():
    """Verify step does not invoke tool if task was cancelled before execution started."""
    tool_executed = False

    class TrackingTool(BaseTool):
        name = "tracking_tool"
        description = "Track execution."
        permission_level = PermissionLevel.LOW_RISK

        @property
        def parameters_schema(self):
            return {"type": "OBJECT", "properties": {}, "required": []}

        async def execute(self, **kwargs) -> ToolResult:
            nonlocal tool_executed
            tool_executed = True
            return ToolResult(success=True, result={"ok": True})

    registry = ToolRegistry()
    registry.register(TrackingTool())
    executor = StepExecutor(tool_registry=registry)

    task = Task(goal="Pre-cancelled task")
    task.cancellation_requested = True  # Pre-cancelled

    step = TaskStep(index=0, description="Do not run", tool_name="tracking_tool")
    res = await executor.execute_step(step=step, task=task)

    assert tool_executed is False
    assert res.success is False
    assert res.status == StepStatus.FAILED
    assert "cancellation was requested" in (res.error or "")


# ==============================================================================
# 5. EventBus Telemetry Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_eventbus_telemetry_emission():
    """Verify TASK_STEP_STARTED, TASK_WAITING_PERMISSION, and TASK_STEP_COMPLETED events."""
    bus = EventBus()
    events_received = []

    def record_event(evt):
        events_received.append(evt.type.value if hasattr(evt.type, "value") else str(evt.type))

    bus.subscribe(EventType.TASK_STEP_STARTED, record_event)
    bus.subscribe(EventType.TASK_WAITING_PERMISSION, record_event)
    bus.subscribe(EventType.TASK_STEP_COMPLETED, record_event)

    registry = ToolRegistry()
    registry.register(DangerousActionTool())

    async def mock_allow(*args, **kwargs):
        return True

    controller = PermissionController(confirmation_threshold=3, approval_callback=mock_allow)
    executor = StepExecutor(
        tool_registry=registry,
        permission_controller=controller,
        event_bus=bus,
    )

    task = Task(goal="Telemetry task")
    step = TaskStep(index=0, description="Perform action", tool_name="dangerous_action", arguments={"target": "item"})

    res = await executor.execute_step(step=step, task=task)
    assert res.success is True

    assert EventType.TASK_STEP_STARTED.value in events_received
    assert EventType.TASK_WAITING_PERMISSION.value in events_received
    assert EventType.TASK_STEP_COMPLETED.value in events_received


# ==============================================================================
# 6. Security & Payload Sanitization Tests
# ==============================================================================

def test_telemetry_sanitization_helper():
    """Verify secrets and binary payloads are redacted from telemetry payloads."""
    raw = {
        "api_key": "AIzaSySecret12345",
        "password": "SuperSecretPassword!",
        "normal_arg": "safe_value",
        "image_bytes": b"binary_data",
        "nested": {"token": "secret_token_abc"},
    }
    sanitized = sanitize_telemetry_dict(raw)

    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["normal_arg"] == "safe_value"
    assert sanitized["image_bytes"] == "[IMAGE_DATA_REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_step_result_prunes_large_base64_blobs():
    """Verify bulky base64 image strings are sanitized before persisting on TaskStep."""
    registry = ToolRegistry()
    registry.register(CapturePayloadTool())
    executor = StepExecutor(tool_registry=registry)

    step = TaskStep(index=0, description="Capture screen payload", tool_name="capture_payload")
    res = await executor.execute_step(step=step)

    assert res.success is True
    assert res.result["status"] == "captured"
    assert res.result["width"] == 1920
    # image_base64 is pruned from memory storage
    assert res.result["image_base64"] == "[IMAGE_DATA_REDACTED]"
    assert step.result["image_base64"] == "[IMAGE_DATA_REDACTED]"


# ==============================================================================
# 7. StateMachine Synchronization Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_state_machine_synchronization_during_step_execution():
    """Verify StepExecutor updates StateMachine appropriately and restores IDLE."""
    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    registry = ToolRegistry()
    registry.register(SafeEchoTool())
    executor = StepExecutor(tool_registry=registry, event_bus=bus, state_machine=sm)

    assert sm.current_state == AgentState.IDLE

    step = TaskStep(index=0, description="Echo message", tool_name="safe_echo", arguments={"message": "test"})
    res = await executor.execute_step(step=step)

    assert res.success is True
    # Restores to IDLE upon completion
    assert sm.current_state == AgentState.IDLE
