"""Task and Workflow Intelligence module for JARVIS (Phase 8)."""

from jarvis.tasks.model import (
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from jarvis.tasks.manager import (
    ActiveTaskConflictError,
    InvalidTaskStateTransitionError,
    TaskManager,
    TaskNotFoundError,
)

from jarvis.tasks.executor import (
    StepExecutionResult,
    StepExecutor,
)

from jarvis.tasks.verifier import (
    StepVerifier,
    VerificationMethod,
    VerificationResult,
    VerificationStatus,
    normalize_verification_method,
)

from jarvis.tasks.recovery import (
    ActionFingerprint,
    AntiLoopGuard,
    FailureClassification,
    FailureClassifier,
    IdempotencyPolicy,
    RecoveryDecision,
    RecoveryPolicy,
    get_tool_idempotency,
)

__all__ = [
    "Task",
    "TaskStep",
    "TaskStatus",
    "StepStatus",
    "TaskManager",
    "TaskNotFoundError",
    "InvalidTaskStateTransitionError",
    "ActiveTaskConflictError",
    "StepExecutor",
    "StepExecutionResult",
    "StepVerifier",
    "VerificationResult",
    "VerificationMethod",
    "VerificationStatus",
    "normalize_verification_method",
    "IdempotencyPolicy",
    "FailureClassification",
    "FailureClassifier",
    "ActionFingerprint",
    "AntiLoopGuard",
    "RecoveryDecision",
    "RecoveryPolicy",
    "get_tool_idempotency",
]
