"""Step Executor for dispatching TaskStep execution through existing JARVIS tool infrastructure (Phase 8.3).

Architectural Invariants:
- The Step Executor is strictly an execution and dispatching component.
- It is NOT an AI agent or planner; it contains zero LLMs.
- It dispatches tool requests exclusively through the authoritative ToolRegistry
  and PermissionController. No direct system or driver calls bypass ToolRegistry.
- Step execution updates TaskStep lifecycle fields without implementing verification (Phase 8.4)
  or retry loops (Phase 8.5).
"""

import asyncio
from dataclasses import dataclass
import time
from typing import Any

from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.security.permissions import (
    PermissionController,
    PermissionLevel,
    default_permission_controller,
)
from jarvis.tasks.model import StepStatus, Task, TaskStep
from jarvis.tasks.recovery import (
    ActionFingerprint,
    FailureClassification,
    IdempotencyPolicy,
    RecoveryDecision,
    RecoveryPolicy,
)
from jarvis.tools.base import ToolResult
from jarvis.tools.registry import ToolRegistry, default_tool_registry
from jarvis.utils.logging import logger

_SECRET_TERMS = ("key", "pass", "secret", "token", "auth", "cred")


def sanitize_telemetry_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive key names and binary/base64 payloads for safe telemetry."""
    sanitized: dict[str, Any] = {}
    for k, v in data.items():
        k_lower = str(k).lower()
        if any(term in k_lower for term in _SECRET_TERMS):
            sanitized[k] = "[REDACTED]"
        elif any(term in k_lower for term in ("base64", "image_bytes", "raw_bytes")):
            sanitized[k] = "[IMAGE_DATA_REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_telemetry_dict(v)
        elif isinstance(v, str):
            if len(v) > 500 and " " not in v[:100]:
                sanitized[k] = "[BLOB_DATA_REDACTED]"
            else:
                sanitized[k] = v
        else:
            sanitized[k] = v
    return sanitized


def sanitize_step_result(result: Any) -> Any:
    """Sanitize bulky image payloads or binary blobs before storing on TaskStep."""
    if isinstance(result, dict):
        cleaned = dict(result)
        if "image_base64" in cleaned:
            cleaned["image_base64"] = "[IMAGE_DATA_REDACTED]"
        return cleaned
    return result


@dataclass
class StepExecutionResult:
    """Structured outcome of an individual TaskStep execution."""

    step_id: str
    success: bool
    status: StepStatus
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class StepExecutor:
    """Dispatches TaskStep through ToolRegistry, PermissionController, AuditLogger, and RecoveryPolicy."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        permission_controller: PermissionController | None = None,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
        step_verifier: Any | None = None,
        recovery_policy: Any | None = None,
    ) -> None:
        self.tool_registry = tool_registry or default_tool_registry
        self.permission_controller = permission_controller or default_permission_controller
        self.event_bus = event_bus or default_event_bus
        self.state_machine = state_machine
        self.step_verifier = step_verifier
        if recovery_policy is False:
            self.recovery_policy = None
        elif recovery_policy is not None:
            self.recovery_policy = recovery_policy
        else:
            self.recovery_policy = RecoveryPolicy(event_bus=self.event_bus)

    async def execute_step(
        self,
        step: TaskStep,
        task: Task | None = None,
    ) -> StepExecutionResult:
        """Execute a TaskStep through the existing tool infrastructure with bounded recovery.

        HARD ARCHITECTURAL REQUIREMENT:
        This method MUST NOT recursively invoke itself. Recovery is executed via an
        iterative bounded loop keeping call-stack depth O(1).
        """
        if not isinstance(step, TaskStep):
            raise TypeError(f"Expected TaskStep instance, got {type(step)}")

        task_id = task.task_id if task else None

        # 1. Pre-execution Cancellation Boundary Check
        if task and task.cancellation_requested:
            err = "Execution cancelled: cancellation was requested before step execution."
            logger.info("TaskStep [%s] aborted due to prior cancellation request.", step.step_id)
            step.mark_failed(error=err)
            await self.event_bus.emit(
                EventType.TASK_STEP_FAILED,
                {
                    "task_id": task_id,
                    "step_id": step.step_id,
                    "error": err,
                    "cancelled": True,
                },
            )
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                status=StepStatus.FAILED,
                error=err,
            )

        # 2. Check if task is already finished
        if task and task.is_finished:
            raise ValueError(f"Cannot execute step on a finished task (status: {task.status.value})")

        # 3. Mark step as executing and emit event
        step.mark_executing()
        sanitized_args = sanitize_telemetry_dict(step.arguments)

        logger.info(
            "Executing TaskStep [%s] (index %d): %s -> tool '%s'",
            step.step_id,
            step.index,
            step.description,
            step.tool_name,
        )

        await self.event_bus.emit(
            EventType.TASK_STEP_STARTED,
            {
                "task_id": task_id,
                "step_id": step.step_id,
                "index": step.index,
                "description": step.description,
                "tool_name": step.tool_name,
                "arguments": sanitized_args,
            },
        )

        # 4. Resolve tool in ToolRegistry
        tool = self.tool_registry.get(step.tool_name)
        if not tool:
            err = f"Tool '{step.tool_name}' is not registered in ToolRegistry."
            logger.warning(err)
            step.mark_failed(error=err)
            await self.event_bus.emit(
                EventType.TASK_STEP_FAILED,
                {
                    "task_id": task_id,
                    "step_id": step.step_id,
                    "error": err,
                    "reason": "tool_not_found",
                },
            )
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                status=StepStatus.FAILED,
                error=err,
            )

        # 5. Permission Gating Observation
        requires_approval = (
            tool.permission_level >= self.permission_controller.confirmation_threshold
            or tool.permission_level == PermissionLevel.CRITICAL
        )

        if requires_approval:
            step.status = StepStatus.WAITING_PERMISSION
            await self.event_bus.emit(
                EventType.TASK_WAITING_PERMISSION,
                {
                    "task_id": task_id,
                    "step_id": step.step_id,
                    "tool_name": tool.name,
                    "level": int(tool.permission_level),
                },
            )
            if self.state_machine and self.state_machine.current_state != AgentState.WAITING_FOR_PERMISSION:
                await self.state_machine.transition_to(
                    AgentState.WAITING_FOR_PERMISSION,
                    reason=f"Step awaiting permission for {tool.name}",
                )

        # 6. Iterative Bounded Execution Loop (O(1) stack depth)
        attempt = 0
        verify_only = False
        tool_result: ToolResult | None = None
        cleaned_result: Any = None
        action_fp = ActionFingerprint.compute(step.tool_name, step.arguments)

        try:
            while True:
                # Cancellation check before any operation in this iteration
                if task and task.cancellation_requested:
                    err = "Execution cancelled: cancellation was requested."
                    logger.info("TaskStep [%s] aborted due to cancellation request.", step.step_id)
                    step.mark_failed(error=err)
                    await self.event_bus.emit(
                        EventType.TASK_STEP_FAILED,
                        {
                            "task_id": task_id,
                            "step_id": step.step_id,
                            "error": err,
                            "cancelled": True,
                        },
                    )
                    return StepExecutionResult(
                        step_id=step.step_id,
                        success=False,
                        status=StepStatus.FAILED,
                        error=err,
                        duration_ms=step.duration_ms,
                    )

                # Tool Execution Branch
                if not verify_only:
                    if self.state_machine and not requires_approval:
                        if self.state_machine.current_state == AgentState.IDLE:
                            await self.state_machine.transition_to(
                                AgentState.THINKING, reason="Preparing tool execution"
                            )
                        if self.state_machine.current_state == AgentState.THINKING:
                            await self.state_machine.transition_to(
                                AgentState.TOOL_EXECUTION, reason=f"Executing {tool.name}"
                            )

                    # Cumulative tool calls count toward budget
                    if task:
                        task.total_tool_calls += 1

                    # Record action execution in anti-loop guard
                    if self.recovery_policy:
                        self.recovery_policy.anti_loop_guard.record_action(action_fp)

                    try:
                        tool_result = await self.tool_registry.execute(
                            tool_name=step.tool_name,
                            arguments=step.arguments,
                            permission_controller=self.permission_controller,
                        )
                    except Exception as ex:
                        err = f"Unexpected exception executing TaskStep: {str(ex)}"
                        logger.error(err, exc_info=True)
                        tool_result = ToolResult(success=False, error=err)

                    if requires_approval and tool_result.success:
                        step.status = StepStatus.EXECUTING
                        if self.state_machine and self.state_machine.current_state == AgentState.WAITING_FOR_PERMISSION:
                            await self.state_machine.transition_to(
                                AgentState.TOOL_EXECUTION, reason="Permission approved"
                            )
                else:
                    # Scenario 2: Launch application settling verification retry
                    # Tool is NOT re-executed to prevent duplicate instance creation
                    verify_only = False

                # Outcome Evaluation
                if tool_result and tool_result.success:
                    cleaned_result = sanitize_step_result(tool_result.result)
                    step.result = cleaned_result

                    # Outcome Verification (Phase 8.4)
                    if self.step_verifier is not None:
                        from jarvis.tasks.verifier import VerificationStatus

                        v_result = await self.step_verifier.verify_step(
                            step, task=task, tool_result=tool_result
                        )

                        if v_result.status == VerificationStatus.VERIFIED:
                            step.mark_success(result=cleaned_result, verified=True)
                            if self.recovery_policy:
                                self.recovery_policy.anti_loop_guard.record_success(action_fp, step.step_id)
                            await self.event_bus.emit(
                                EventType.TASK_STEP_COMPLETED,
                                {
                                    "task_id": task_id,
                                    "step_id": step.step_id,
                                    "index": step.index,
                                    "tool_name": step.tool_name,
                                    "verified": True,
                                    "verification_method": v_result.method,
                                    "duration_ms": step.duration_ms,
                                },
                            )
                            return StepExecutionResult(
                                step_id=step.step_id,
                                success=True,
                                status=StepStatus.SUCCESS,
                                result=cleaned_result,
                                duration_ms=step.duration_ms,
                            )
                        elif v_result.status in (
                            VerificationStatus.NOT_PERFORMED,
                            VerificationStatus.VERIFICATION_NOT_AVAILABLE,
                        ):
                            step.mark_success(result=cleaned_result, verified=False)
                            if self.recovery_policy:
                                self.recovery_policy.anti_loop_guard.record_success(action_fp, step.step_id)
                            await self.event_bus.emit(
                                EventType.TASK_STEP_COMPLETED,
                                {
                                    "task_id": task_id,
                                    "step_id": step.step_id,
                                    "index": step.index,
                                    "tool_name": step.tool_name,
                                    "verified": False,
                                    "verification_method": v_result.method,
                                    "duration_ms": step.duration_ms,
                                },
                            )
                            return StepExecutionResult(
                                step_id=step.step_id,
                                success=True,
                                status=StepStatus.SUCCESS,
                                result=cleaned_result,
                                duration_ms=step.duration_ms,
                            )
                        elif v_result.status == VerificationStatus.VERIFICATION_FAILED:
                            # Verification crashed or corrupted; NEVER retry underlying side-effecting action
                            step.mark_failed(
                                error=step.error or v_result.reason or "Verification failed",
                                verified=False,
                            )
                            if self.recovery_policy:
                                self.recovery_policy.anti_loop_guard.record_failure(action_fp, step.step_id)
                            await self.event_bus.emit(
                                EventType.TASK_STEP_FAILED,
                                {
                                    "task_id": task_id,
                                    "step_id": step.step_id,
                                    "index": step.index,
                                    "tool_name": step.tool_name,
                                    "error": step.error,
                                    "verified": False,
                                    "verification_method": v_result.method,
                                    "duration_ms": step.duration_ms,
                                },
                            )
                            return StepExecutionResult(
                                step_id=step.step_id,
                                success=False,
                                status=StepStatus.FAILED,
                                error=step.error,
                                duration_ms=step.duration_ms,
                            )
                        else:
                            # NOT_VERIFIED: outcome not confirmed
                            if self.recovery_policy:
                                self.recovery_policy.anti_loop_guard.record_failure(action_fp, step.step_id)

                            decision = (
                                self.recovery_policy.evaluate(
                                    task=task,
                                    step=step,
                                    tool_result=tool_result,
                                    verification_result=v_result,
                                )
                                if self.recovery_policy
                                else None
                            )

                            if decision and decision.can_retry:
                                if step.retries == 0:
                                    await self.event_bus.emit(
                                        EventType.TASK_RECOVERY_STARTED,
                                        {
                                            "task_id": task_id,
                                            "step_id": step.step_id,
                                            "tool_name": step.tool_name,
                                            "retry_count": step.retries + 1,
                                            "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                            "failure_classification": decision.classification.value,
                                            "idempotency": decision.idempotency.value,
                                            "action_fingerprint": decision.action_fingerprint,
                                            "reason": decision.reason,
                                        },
                                    )

                                await self.event_bus.emit(
                                    EventType.TASK_STEP_RETRYING,
                                    {
                                        "task_id": task_id,
                                        "step_id": step.step_id,
                                        "tool_name": step.tool_name,
                                        "retry_count": step.retries + 1,
                                        "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                        "failure_classification": decision.classification.value,
                                        "idempotency": decision.idempotency.value,
                                        "action_fingerprint": decision.action_fingerprint,
                                        "reason": decision.reason,
                                    },
                                )

                                if task:
                                    task.metadata["recovery_count"] = (
                                        task.metadata.get("recovery_count", 0) + 1
                                    )
                                    task.metadata["recovery"] = {
                                        "last_retry_step": step.step_id,
                                        "retries": step.retries + 1,
                                        "last_classification": decision.classification.value,
                                    }

                                # Cancellation check before cooldown
                                if task and task.cancellation_requested:
                                    step.mark_failed("Cancelled during recovery.")
                                    return StepExecutionResult(
                                        step_id=step.step_id,
                                        success=False,
                                        status=StepStatus.FAILED,
                                        error="Cancelled during recovery.",
                                        duration_ms=step.duration_ms,
                                    )

                                # Cooldown with continuous cancellation checks
                                sleep_rem = decision.cooldown_seconds
                                while sleep_rem > 0:
                                    if task and task.cancellation_requested:
                                        break
                                    slice_t = min(0.05, sleep_rem)
                                    await asyncio.sleep(slice_t)
                                    sleep_rem -= slice_t

                                # Cancellation check after cooldown
                                if task and task.cancellation_requested:
                                    step.mark_failed("Cancelled after recovery cooldown.")
                                    return StepExecutionResult(
                                        step_id=step.step_id,
                                        success=False,
                                        status=StepStatus.FAILED,
                                        error="Cancelled after recovery cooldown.",
                                        duration_ms=step.duration_ms,
                                    )

                                step.retries += 1
                                attempt += 1
                                verify_only = decision.verify_only
                                continue
                            else:
                                # Recovery denied, budgets exhausted, or anti-loop triggered
                                if decision and decision.anti_loop_triggered:
                                    await self.event_bus.emit(
                                        EventType.TASK_ANTI_LOOP_TRIGGERED,
                                        {
                                            "task_id": task_id,
                                            "step_id": step.step_id,
                                            "tool_name": step.tool_name,
                                            "retry_count": step.retries,
                                            "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                            "failure_classification": decision.classification.value,
                                            "idempotency": decision.idempotency.value,
                                            "action_fingerprint": decision.action_fingerprint,
                                            "reason": decision.reason,
                                        },
                                    )
                                elif decision and decision.classification == FailureClassification.BUDGET_EXHAUSTED:
                                    await self.event_bus.emit(
                                        EventType.TASK_RECOVERY_EXHAUSTED,
                                        {
                                            "task_id": task_id,
                                            "step_id": step.step_id,
                                            "tool_name": step.tool_name,
                                            "retry_count": step.retries,
                                            "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                            "failure_classification": decision.classification.value,
                                            "idempotency": decision.idempotency.value,
                                            "action_fingerprint": decision.action_fingerprint,
                                            "reason": decision.reason,
                                        },
                                    )

                                step.mark_failed(
                                    error=step.error or v_result.reason or "Outcome verification not confirmed",
                                    verified=False,
                                )
                                await self.event_bus.emit(
                                    EventType.TASK_STEP_FAILED,
                                    {
                                        "task_id": task_id,
                                        "step_id": step.step_id,
                                        "index": step.index,
                                        "tool_name": step.tool_name,
                                        "error": step.error,
                                        "verified": False,
                                        "verification_method": v_result.method,
                                        "duration_ms": step.duration_ms,
                                    },
                                )
                                return StepExecutionResult(
                                    step_id=step.step_id,
                                    success=False,
                                    status=StepStatus.FAILED,
                                    error=step.error,
                                    duration_ms=step.duration_ms,
                                )
                    else:
                        # Legacy Phase 8.3 baseline (no verifier)
                        step.mark_success(result=cleaned_result, verified=False)
                        await self.event_bus.emit(
                            EventType.TASK_STEP_COMPLETED,
                            {
                                "task_id": task_id,
                                "step_id": step.step_id,
                                "index": step.index,
                                "tool_name": step.tool_name,
                                "duration_ms": step.duration_ms,
                            },
                        )
                        return StepExecutionResult(
                            step_id=step.step_id,
                            success=True,
                            status=StepStatus.SUCCESS,
                            result=cleaned_result,
                            duration_ms=step.duration_ms,
                        )
                else:
                    # Tool execution failed
                    if self.recovery_policy:
                        self.recovery_policy.anti_loop_guard.record_failure(action_fp, step.step_id)

                    decision = (
                        self.recovery_policy.evaluate(
                            task=task,
                            step=step,
                            tool_result=tool_result,
                            verification_result=None,
                        )
                        if self.recovery_policy
                        else None
                    )

                    if decision and decision.can_retry:
                        if step.retries == 0:
                            await self.event_bus.emit(
                                EventType.TASK_RECOVERY_STARTED,
                                {
                                    "task_id": task_id,
                                    "step_id": step.step_id,
                                    "tool_name": step.tool_name,
                                    "retry_count": step.retries + 1,
                                    "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                    "failure_classification": decision.classification.value,
                                    "idempotency": decision.idempotency.value,
                                    "action_fingerprint": decision.action_fingerprint,
                                    "reason": decision.reason,
                                },
                            )

                        await self.event_bus.emit(
                            EventType.TASK_STEP_RETRYING,
                            {
                                "task_id": task_id,
                                "step_id": step.step_id,
                                "tool_name": step.tool_name,
                                "retry_count": step.retries + 1,
                                "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                "failure_classification": decision.classification.value,
                                "idempotency": decision.idempotency.value,
                                "action_fingerprint": decision.action_fingerprint,
                                "reason": decision.reason,
                            },
                        )

                        if task:
                            task.metadata["recovery_count"] = (
                                task.metadata.get("recovery_count", 0) + 1
                            )
                            task.metadata["recovery"] = {
                                "last_retry_step": step.step_id,
                                "retries": step.retries + 1,
                                "last_classification": decision.classification.value,
                            }

                        if task and task.cancellation_requested:
                            step.mark_failed("Cancelled during recovery.")
                            return StepExecutionResult(
                                step_id=step.step_id,
                                success=False,
                                status=StepStatus.FAILED,
                                error="Cancelled during recovery.",
                                duration_ms=step.duration_ms,
                            )

                        sleep_rem = decision.cooldown_seconds
                        while sleep_rem > 0:
                            if task and task.cancellation_requested:
                                break
                            slice_t = min(0.05, sleep_rem)
                            await asyncio.sleep(slice_t)
                            sleep_rem -= slice_t

                        if task and task.cancellation_requested:
                            step.mark_failed("Cancelled after recovery cooldown.")
                            return StepExecutionResult(
                                step_id=step.step_id,
                                success=False,
                                status=StepStatus.FAILED,
                                error="Cancelled after recovery cooldown.",
                                duration_ms=step.duration_ms,
                            )

                        step.retries += 1
                        attempt += 1
                        continue
                    else:
                        # Recovery denied, budget exhausted, or anti-loop triggered
                        if decision and decision.anti_loop_triggered:
                            await self.event_bus.emit(
                                EventType.TASK_ANTI_LOOP_TRIGGERED,
                                {
                                    "task_id": task_id,
                                    "step_id": step.step_id,
                                    "tool_name": step.tool_name,
                                    "retry_count": step.retries,
                                    "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                    "failure_classification": decision.classification.value,
                                    "idempotency": decision.idempotency.value,
                                    "action_fingerprint": decision.action_fingerprint,
                                    "reason": decision.reason,
                                },
                            )
                        elif decision and decision.classification == FailureClassification.BUDGET_EXHAUSTED:
                            await self.event_bus.emit(
                                EventType.TASK_RECOVERY_EXHAUSTED,
                                {
                                    "task_id": task_id,
                                    "step_id": step.step_id,
                                    "tool_name": step.tool_name,
                                    "retry_count": step.retries,
                                    "max_retries": self.recovery_policy.MAX_RETRIES_PER_STEP,
                                    "failure_classification": decision.classification.value,
                                    "idempotency": decision.idempotency.value,
                                    "action_fingerprint": decision.action_fingerprint,
                                    "reason": decision.reason,
                                },
                            )

                        err_msg = (tool_result.error if tool_result else None) or "Tool execution failed"
                        step.mark_failed(error=err_msg)

                        await self.event_bus.emit(
                            EventType.TASK_STEP_FAILED,
                            {
                                "task_id": task_id,
                                "step_id": step.step_id,
                                "index": step.index,
                                "tool_name": step.tool_name,
                                "error": err_msg,
                                "duration_ms": step.duration_ms,
                            },
                        )
                        return StepExecutionResult(
                            step_id=step.step_id,
                            success=False,
                            status=StepStatus.FAILED,
                            error=err_msg,
                            duration_ms=step.duration_ms,
                        )

        finally:
            # Restore StateMachine state if appropriate
            if self.state_machine and self.state_machine.current_state in (
                AgentState.TOOL_EXECUTION,
                AgentState.WAITING_FOR_PERMISSION,
            ):
                try:
                    await self.state_machine.transition_to(
                        AgentState.IDLE, reason="TaskStep execution finished"
                    )
                except Exception:
                    pass
