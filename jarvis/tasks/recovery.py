"""Bounded Failure Recovery & Anti-Looping Engine for JARVIS (Phase 8.5).

Architectural Invariants:
- A failure may be recoverable, but recovery must always be bounded, observable,
  auditable, permission-aware, and termination-guaranteed.
- Purely deterministic logic: ZERO Gemini or LLM calls in Phase 8.5 recovery.
- Strict Safety Evaluation Hierarchy:
    1. Task duration budget (< 180s)
    2. Cumulative tool-call budget (< 10 calls)
    3. Step retry budget (< 2 retries)
    4. Task recovery budget (< 3 total)
    5. Idempotency / Action Safety (IDEMPOTENT required; UNKNOWN/NON_IDEMPOTENT = REJECT)
    6. Failure classification (Must be a recoverable category)
    7. Action fingerprint (Consecutive identical failure check)
    8. Failure fingerprint (Recurring error check)
    9. Cycle detection (A-B-A-B ping-pong loop check)
    10. Recovery decision (Granted ONLY if all 1-9 pass)
- Non-Recursive Execution: Recovery is an iterative O(1) loop inside StepExecutor;
  StepExecutor.execute_step() MUST NOT recursively call itself.
- Verification Semantics:
    - VERIFIED -> SUCCESS, verified=True, NO recovery.
    - NOT_VERIFIED -> Recovery allowed ONLY if action is explicitly IDEMPOTENT and budgets permit.
    - VERIFICATION_NOT_AVAILABLE -> SUCCESS, verified=False, NO retry.
    - VERIFICATION_FAILED -> FAILED, verified=False, NO retry of underlying action.
- Launch Safety: For launch_application, do NOT blindly relaunch. Prefer settling delay
  and window inspection before considering another launch to prevent duplicate instances.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any

from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.tasks.model import Task, TaskStep
from jarvis.tasks.verifier import VerificationResult, VerificationStatus
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


class IdempotencyPolicy(str, Enum):
    """Tri-state classification of tool idempotency and retry safety."""

    IDEMPOTENT = "idempotent"          # Explicitly safe to re-execute identically
    NON_IDEMPOTENT = "non_idempotent"  # State-mutating / side-effecting; automatic re-execution unsafe
    UNKNOWN = "unknown"                # Unspecified / unclassified; MUST NOT be automatically retried


# Authoritative deterministic canonical classification table
_CANONICAL_IDEMPOTENCY_TABLE: dict[str, IdempotencyPolicy] = {
    # Read-only / inspection (Strictly Idempotent)
    "browser_read_page": IdempotencyPolicy.IDEMPOTENT,
    "get_active_window": IdempotencyPolicy.IDEMPOTENT,
    "get_active_application": IdempotencyPolicy.IDEMPOTENT,
    "capture_screen": IdempotencyPolicy.IDEMPOTENT,
    "filesystem_read": IdempotencyPolicy.IDEMPOTENT,
    "filesystem_list": IdempotencyPolicy.IDEMPOTENT,
    "filesystem_search": IdempotencyPolicy.IDEMPOTENT,
    "web_search": IdempotencyPolicy.IDEMPOTENT,
    "fetch_web_content": IdempotencyPolicy.IDEMPOTENT,
    "list_running_applications": IdempotencyPolicy.IDEMPOTENT,
    # Navigation / Launch / Focus (Idempotent Target State)
    "browser_open": IdempotencyPolicy.IDEMPOTENT,
    "launch_application": IdempotencyPolicy.IDEMPOTENT,
    "focus_application": IdempotencyPolicy.IDEMPOTENT,
    # Mutating / Side-Effecting (Strictly Non-Idempotent)
    "mouse_click": IdempotencyPolicy.NON_IDEMPOTENT,
    "mouse_double_click": IdempotencyPolicy.NON_IDEMPOTENT,
    "mouse_right_click": IdempotencyPolicy.NON_IDEMPOTENT,
    "mouse_scroll": IdempotencyPolicy.NON_IDEMPOTENT,
    "keyboard_type": IdempotencyPolicy.NON_IDEMPOTENT,
    "keyboard_press": IdempotencyPolicy.NON_IDEMPOTENT,
    "keyboard_hotkey": IdempotencyPolicy.NON_IDEMPOTENT,
    "visual_grounding_click": IdempotencyPolicy.NON_IDEMPOTENT,
    "terminal_execute": IdempotencyPolicy.NON_IDEMPOTENT,
    "filesystem_write": IdempotencyPolicy.NON_IDEMPOTENT,
    "filesystem_modify": IdempotencyPolicy.NON_IDEMPOTENT,
    "filesystem_delete": IdempotencyPolicy.NON_IDEMPOTENT,
    "close_application": IdempotencyPolicy.NON_IDEMPOTENT,
    "terminate_process": IdempotencyPolicy.NON_IDEMPOTENT,
    "browser_action": IdempotencyPolicy.NON_IDEMPOTENT,
    "browser_control": IdempotencyPolicy.NON_IDEMPOTENT,
    "youtube_control": IdempotencyPolicy.NON_IDEMPOTENT,
    "music_control": IdempotencyPolicy.NON_IDEMPOTENT,
}


def get_tool_idempotency(tool: BaseTool | str | None) -> IdempotencyPolicy:
    """Resolve the idempotency policy of a tool deterministically.

    Critical Invariant:
    UNKNOWN idempotency MUST NOT be automatically retried.
    Do NOT infer idempotency from tool name substrings, descriptions, or natural language.
    """
    if not tool:
        return IdempotencyPolicy.UNKNOWN

    tool_name = tool.name if isinstance(tool, BaseTool) else str(tool).strip().lower()

    # 1. Canonical table lookup
    if tool_name in _CANONICAL_IDEMPOTENCY_TABLE:
        canonical = _CANONICAL_IDEMPOTENCY_TABLE[tool_name]
        # Safety invariant: canonical NON_IDEMPOTENT can NEVER be overridden
        if canonical == IdempotencyPolicy.NON_IDEMPOTENT:
            return IdempotencyPolicy.NON_IDEMPOTENT
        return canonical

    # 2. Check explicit tool property if available (must not override canonical NON_IDEMPOTENT)
    if isinstance(tool, BaseTool) and hasattr(tool, "is_idempotent"):
        prop = getattr(tool, "is_idempotent")
        if prop is True:
            return IdempotencyPolicy.IDEMPOTENT
        elif prop is False:
            return IdempotencyPolicy.NON_IDEMPOTENT

    # 3. Default strictly to UNKNOWN
    return IdempotencyPolicy.UNKNOWN


class FailureClassification(str, Enum):
    """Deterministic taxonomy of task and step execution failures."""

    TRANSIENT_TIMEOUT = "transient_timeout"
    GUI_RACE_CONDITION = "gui_race_condition"
    WINDOW_NOT_FOCUSED = "window_not_focused"
    OUTCOME_NOT_CONFIRMED = "outcome_not_confirmed"
    VERIFICATION_NOT_AVAILABLE = "verification_not_available"
    VERIFICATION_FAILED = "verification_failed"
    PERMISSION_DENIED = "permission_denied"
    SECURITY_VIOLATION = "security_violation"
    INVALID_ARGUMENTS = "invalid_arguments"
    UNKNOWN_TOOL = "unknown_tool"
    NON_IDEMPOTENT_ACTION = "non_idempotent_action"
    BUDGET_EXHAUSTED = "budget_exhausted"


class FailureClassifier:
    """Classifies tool execution and outcome verification failures deterministically."""

    @staticmethod
    def classify(
        tool_result: ToolResult | None = None,
        verification_result: VerificationResult | None = None,
        exception: Exception | None = None,
    ) -> FailureClassification:
        """Classify failure based strictly on structured return types and errors."""
        # 1. Check ToolResult error details
        err = (tool_result.error if tool_result else None) or (str(exception) if exception else "")
        err_lower = err.lower()

        # Permission denial is absolute and terminal
        if "permission denied" in err_lower or "denied execution" in err_lower:
            return FailureClassification.PERMISSION_DENIED

        # Security policy violations
        if any(w in err_lower for w in ("shell meta-characters", "path traversal", "prohibited")):
            return FailureClassification.SECURITY_VIOLATION

        # Argument validation errors
        if any(w in err_lower for w in ("missing required parameter", "argument validation failed")):
            return FailureClassification.INVALID_ARGUMENTS

        # Unknown tool
        if any(w in err_lower for w in ("is not registered", "not registered in toolregistry", "unknown tool")):
            return FailureClassification.UNKNOWN_TOOL

        # Timeout errors
        if isinstance(exception, TimeoutError) or "timed out after" in err_lower or "timeout" in err_lower:
            return FailureClassification.TRANSIENT_TIMEOUT

        # 2. Check VerificationResult details
        if verification_result:
            if verification_result.status == VerificationStatus.VERIFICATION_NOT_AVAILABLE:
                return FailureClassification.VERIFICATION_NOT_AVAILABLE
            elif verification_result.status == VerificationStatus.VERIFICATION_FAILED:
                return FailureClassification.VERIFICATION_FAILED
            elif verification_result.status == VerificationStatus.NOT_VERIFIED:
                v_reason = (verification_result.reason or "").lower()
                if "no active foreground window" in v_reason or "desktop" in v_reason:
                    return FailureClassification.GUI_RACE_CONDITION
                elif "does not match expected" in v_reason and "window" in v_reason:
                    return FailureClassification.WINDOW_NOT_FOCUSED
                return FailureClassification.OUTCOME_NOT_CONFIRMED

        return FailureClassification.OUTCOME_NOT_CONFIRMED


class ActionFingerprint:
    """Generates normalized deterministic fingerprints for actions and failures."""

    @staticmethod
    def compute(tool_name: str, arguments: dict[str, Any]) -> str:
        """Compute SHA-256 fingerprint for a tool call."""
        norm_tool = str(tool_name).strip().lower()
        # Clean and sort arguments
        clean_args = {k: v for k, v in sorted(arguments.items())}
        raw_str = f"{norm_tool}:{json.dumps(clean_args, sort_keys=True, default=str)}"
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def compute_failure_fingerprint(
        action_fingerprint: str,
        classification: FailureClassification,
        error: str,
    ) -> str:
        """Compute SHA-256 fingerprint for a specific failure occurrence."""
        norm_err = str(error).strip()[:100].lower()
        raw_str = f"{action_fingerprint}:{classification.value}:{norm_err}"
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


class AntiLoopGuard:
    """Enforces structural anti-looping constraints against repetitive actions and cycles."""

    def __init__(self) -> None:
        self.action_failure_counts: dict[str, int] = {}
        self.action_history: list[str] = []
        self.step_verification_failures: dict[str, int] = {}

    def record_action(self, fingerprint: str) -> None:
        """Record an executed action fingerprint in the sliding window history."""
        self.action_history.append(fingerprint)
        if len(self.action_history) > 10:
            self.action_history.pop(0)

    def record_failure(self, fingerprint: str, step_id: str) -> None:
        """Record a failure for loop detection."""
        self.action_failure_counts[fingerprint] = self.action_failure_counts.get(fingerprint, 0) + 1
        self.step_verification_failures[step_id] = self.step_verification_failures.get(step_id, 0) + 1

    def record_success(self, fingerprint: str, step_id: str) -> None:
        """Reset failure counts on successful outcome."""
        self.action_failure_counts[fingerprint] = 0
        self.step_verification_failures[step_id] = 0

    def is_loop_detected(self, fingerprint: str, step_id: str) -> tuple[bool, str]:
        """Check whether current state constitutes a forbidden execution loop."""
        # 1. Identical Action Failure: 2 consecutive failures of identical action
        if self.action_failure_counts.get(fingerprint, 0) >= 2:
            return True, f"Identical action fingerprint '{fingerprint}' failed 2 consecutive times."

        # 2. Repeated Step Verification Failure: same step failed verification twice
        if self.step_verification_failures.get(step_id, 0) >= 2:
            return True, f"Step '{step_id}' failed outcome verification 2 consecutive times."

        # 3. Cycle Detection (Ping-Pong A-B-A-B or periodic loop)
        if len(self.action_history) >= 4:
            # Check period 2 cycle: [A, B, A, B]
            if (
                self.action_history[-1] == self.action_history[-3]
                and self.action_history[-2] == self.action_history[-4]
                and self.action_history[-1] != self.action_history[-2]
            ):
                return True, f"Periodic alternating loop (A-B-A-B) detected: '{self.action_history[-2]}' <-> '{self.action_history[-1]}'."

        return False, ""


@dataclass
class RecoveryDecision:
    """Structured decision output from RecoveryPolicy."""

    can_retry: bool
    classification: FailureClassification
    action_fingerprint: str
    idempotency: IdempotencyPolicy
    reason: str
    cooldown_seconds: float = 0.0
    verify_only: bool = False  # If True, re-run verification without relaunching tool (Launch Safety)
    anti_loop_triggered: bool = False


class RecoveryPolicy:
    """Authoritative bounded recovery engine enforcing safety hierarchy and budget limits."""

    # Explicit Hard Bounds
    MAX_RETRIES_PER_STEP = 2
    MAX_RECOVERY_ATTEMPTS_PER_TASK = 3
    MAX_CUMULATIVE_TOOL_CALLS = 10
    MAX_TASK_DURATION = 180.0
    DEFAULT_RETRY_COOLDOWN = 0.5

    def __init__(
        self,
        event_bus: EventBus | None = None,
        anti_loop_guard: AntiLoopGuard | None = None,
        cooldown_seconds: float | None = None,
    ) -> None:
        self.event_bus = event_bus or default_event_bus
        self.anti_loop_guard = anti_loop_guard or AntiLoopGuard()
        self.cooldown_seconds = (
            self.DEFAULT_RETRY_COOLDOWN if cooldown_seconds is None else cooldown_seconds
        )

    def evaluate(
        self,
        task: Task | None,
        step: TaskStep,
        tool_result: ToolResult | None = None,
        verification_result: VerificationResult | None = None,
        exception: Exception | None = None,
    ) -> RecoveryDecision:
        """Evaluate failure against the strict safety hierarchy and return a RecoveryDecision."""
        fingerprint = ActionFingerprint.compute(step.tool_name, step.arguments)
        idempotency = get_tool_idempotency(step.tool_name)
        classification = FailureClassifier.classify(tool_result, verification_result, exception)

        # -------------------------------------------------------------
        # STRICT SAFETY EVALUATION HIERARCHY
        # -------------------------------------------------------------

        # 1. Task Duration Budget Check
        if task and (time.time() - task.created_at > self.MAX_TASK_DURATION):
            return RecoveryDecision(
                can_retry=False,
                classification=FailureClassification.BUDGET_EXHAUSTED,
                action_fingerprint=fingerprint,
                idempotency=idempotency,
                reason=f"Task duration budget ({self.MAX_TASK_DURATION}s) exceeded.",
            )

        # 2. Cumulative Tool-Call Budget Check
        if task and task.total_tool_calls >= self.MAX_CUMULATIVE_TOOL_CALLS:
            return RecoveryDecision(
                can_retry=False,
                classification=FailureClassification.BUDGET_EXHAUSTED,
                action_fingerprint=fingerprint,
                idempotency=idempotency,
                reason=f"Cumulative tool-call budget ({self.MAX_CUMULATIVE_TOOL_CALLS}) exhausted.",
            )

        # 3. Step Retry Budget Check
        if step.retries >= self.MAX_RETRIES_PER_STEP:
            return RecoveryDecision(
                can_retry=False,
                classification=FailureClassification.BUDGET_EXHAUSTED,
                action_fingerprint=fingerprint,
                idempotency=idempotency,
                reason=f"Step retry budget ({self.MAX_RETRIES_PER_STEP}) exhausted.",
            )

        # 4. Task Total Recovery Budget Check
        task_recovery_count = task.metadata.get("recovery_count", 0) if task else 0
        if task_recovery_count >= self.MAX_RECOVERY_ATTEMPTS_PER_TASK:
            return RecoveryDecision(
                can_retry=False,
                classification=FailureClassification.BUDGET_EXHAUSTED,
                action_fingerprint=fingerprint,
                idempotency=idempotency,
                reason=f"Task recovery budget ({self.MAX_RECOVERY_ATTEMPTS_PER_TASK}) exhausted.",
            )

        # 5. Idempotency / Action Safety Policy Check
        # Critical Invariant: UNKNOWN and NON_IDEMPOTENT MUST NEVER be automatically retried
        if idempotency != IdempotencyPolicy.IDEMPOTENT:
            return RecoveryDecision(
                can_retry=False,
                classification=FailureClassification.NON_IDEMPOTENT_ACTION,
                action_fingerprint=fingerprint,
                idempotency=idempotency,
                reason=(
                    f"Tool '{step.tool_name}' has idempotency '{idempotency.value}'; "
                    f"automatic retry is strictly prohibited to prevent duplicate side effects."
                ),
            )

        # 6. Failure Classification Check (Must be recoverable)
        recoverable_classes = (
            FailureClassification.TRANSIENT_TIMEOUT,
            FailureClassification.GUI_RACE_CONDITION,
            FailureClassification.WINDOW_NOT_FOCUSED,
            FailureClassification.OUTCOME_NOT_CONFIRMED,
        )
        if classification not in recoverable_classes:
            return RecoveryDecision(
                can_retry=False,
                classification=classification,
                action_fingerprint=fingerprint,
                idempotency=idempotency,
                reason=f"Failure classification '{classification.value}' is non-recoverable.",
            )

        # 7. Action Fingerprint & Loop Check
        is_loop, loop_reason = self.anti_loop_guard.is_loop_detected(fingerprint, step.step_id)
        if is_loop:
            return RecoveryDecision(
                can_retry=False,
                classification=classification,
                action_fingerprint=fingerprint,
                idempotency=idempotency,
                reason=f"AntiLoopGuard halted recovery: {loop_reason}",
                anti_loop_triggered=True,
            )

        # -------------------------------------------------------------
        # ALL SAFETY CONDITIONS PASSED: GRANT BOUNDED RETRY
        # -------------------------------------------------------------
        # Launch Application Safety Check (Scenario 2):
        # For launch_application, if immediate verification failed due to GUI race or focus lag,
        # do NOT blindly relaunch! Prefer settling delay and re-running verification.
        verify_only = False
        if step.tool_name == "launch_application" and classification in (
            FailureClassification.GUI_RACE_CONDITION,
            FailureClassification.WINDOW_NOT_FOCUSED,
        ):
            verify_only = True

        return RecoveryDecision(
            can_retry=True,
            classification=classification,
            action_fingerprint=fingerprint,
            idempotency=idempotency,
            cooldown_seconds=self.cooldown_seconds,
            verify_only=verify_only,
            reason=(
                f"Bounded recovery granted for recoverable failure '{classification.value}' "
                f"on idempotent tool '{step.tool_name}'."
            ),
        )
