"""Typed runtime errors for graph persistence and outbox dispatch."""

from collections.abc import Sequence
from typing import Any

from orchestrator.config import FailureCategory, FailureDiagnostic, FailureNextAction
from orchestrator.runners import (
    AgentConfigError,
    AgentExecutionError,
    AgentNotAvailableError,
    AgentRateLimitError,
    AgentTimeoutError,
    SubmissionRejectedError,
    SubmissionRepairExhaustedError,
)


class GraphRuntimeError(Exception):
    """Base class for graph runtime failures."""


class SubmissionQualityGateError(GraphRuntimeError, ValueError):
    """Raised before staging when authoritative validation does not pass."""

    def __init__(self, message: str, *, report: Any | None = None) -> None:
        self.report = report
        super().__init__(message)


class InvalidExecutionContractError(SubmissionQualityGateError):
    """Raised when immutable node execution authority is malformed."""


class StaleProjectionError(GraphRuntimeError):
    """Raised when a command appends against a stale run-local position."""


class PatchOperationConflictError(GraphRuntimeError, ValueError):
    """Raised when a semantic operation key is reused with different intent."""


class GraphEventEnvelopeTooLargeError(GraphRuntimeError):
    """Raised when a complete serialized event exceeds the write contract."""

    def __init__(self, *, event_type: str, observed_bytes: int, limit_bytes: int) -> None:
        self.event_type = event_type
        self.observed_bytes = observed_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"graph event {event_type!r} is {observed_bytes} bytes; maximum is {limit_bytes} bytes"
        )


class OutboxAppendError(GraphRuntimeError):
    """Raised when side-effect intent cannot be written atomically."""


class CompromisedFileStateError(GraphRuntimeError):
    """Raised when runtime dispatch would consume a compromised file-state record."""


class CacheScanBudgetExceededError(GraphRuntimeError):
    """Historical v1 cache-scan failure retained for durable replay/readback."""

    def __init__(
        self,
        *,
        metric: str,
        limit: int,
        observed: int,
        path: str,
    ) -> None:
        self.metric = metric
        self.limit = limit
        self.observed = observed
        self.path = path
        super().__init__(
            f"cache scan {metric} budget exceeded at {path!r}: limit={limit}, observed={observed}"
        )


class RecoveryEventError(GraphRuntimeError):
    """Raised when a durable recovery request is missing or malformed."""


class RecoveryRestoreError(GraphRuntimeError):
    """Raised when selective restoration from the durable baseline fails."""


class RecoveryCompletionRejectedError(GraphRuntimeError):
    """Raised when the kernel rejects durable recovery completion accounting."""


class ProcessQuiescenceError(GraphRuntimeError):
    """Raised when an owned runner cannot be stopped before recovery."""


class RunnerProcessMissingError(GraphRuntimeError):
    """Raised when a dispatched runner's verified process identity disappears."""


class DecisionAnswerBudgetExhaustedError(GraphRuntimeError, ValueError):
    """Raised when a decision request has received its second invalid answer."""

    def __init__(self, *, execution_id: str, budget: int, observed: int) -> None:
        self.execution_id = execution_id
        self.budget = budget
        self.observed = observed
        super().__init__(
            f"decision answer rejection budget exhausted for execution {execution_id!r}: "
            f"budget={budget}, observed={observed}"
        )


class DecisionAnswerDeliveryConflictError(GraphRuntimeError, ValueError):
    """Raised when one trusted delivery identity carries different content."""


class DecisionBindingConflictError(GraphRuntimeError, ValueError):
    """Raised when decision staging/finalization observes stale bound authority."""


def classify_failure(
    error: BaseException,
    *,
    protected_evidence_refs: Sequence[str] = (),
) -> FailureDiagnostic:
    """Classify failures once at the graph/runner boundary.

    Provider-specific exception text remains in existing protected event or
    evidence carriers; this function publishes only stable categories and a
    bounded next action.
    """

    refs = tuple(protected_evidence_refs)
    if isinstance(error, SubmissionRejectedError):
        existing = error.acknowledgement.failure_diagnostic
        if existing is not None:
            if refs and existing.protected_evidence_refs != refs:
                return existing.model_copy(update={"protected_evidence_refs": refs})
            return existing
        category = error.acknowledgement.rejection_category
        if category == "candidate_check_failed":
            return _diagnostic(
                "candidate_check",
                "candidate_check_failed",
                "The candidate did not pass an authoritative check.",
                "correct_candidate",
                True,
                refs,
            )
        if category == "validation_environment_blocked":
            return _diagnostic(
                "infrastructure_environment",
                "validation_environment_blocked",
                "The validation environment is unavailable or blocked.",
                "resolve_environment",
                False,
                refs,
            )
        return _diagnostic(
            "answer_validation",
            "submission_format_rejected",
            "The submitted answer does not match the bound answer contract.",
            "correct_answer",
            True,
            refs,
        )

    if isinstance(error, SubmissionQualityGateError):
        failure_category = getattr(error.report, "failure_category", None)
        if failure_category == "validation_environment_blockage":
            return _diagnostic(
                "infrastructure_environment",
                "validation_environment_blocked",
                "The validation environment is unavailable or blocked.",
                "resolve_environment",
                False,
                refs,
            )
        if failure_category == "candidate_check_failure":
            return _diagnostic(
                "candidate_check",
                "candidate_check_failed",
                "The candidate did not pass an authoritative check.",
                "correct_candidate",
                True,
                refs,
            )
        if isinstance(error, InvalidExecutionContractError):
            return _diagnostic(
                "answer_validation",
                "invalid_execution_contract",
                "The bound answer contract is invalid and requires operator repair.",
                "stop",
                False,
                refs,
            )
        return _diagnostic(
            "answer_validation",
            "answer_validation_failed",
            "The submitted answer does not match the bound answer contract.",
            "correct_answer",
            True,
            refs,
        )

    if isinstance(
        error,
        StaleProjectionError | DecisionAnswerDeliveryConflictError | DecisionBindingConflictError,
    ):
        return _diagnostic(
            "stale_binding",
            "stale_binding",
            "The submission was based on stale bound evidence or authority.",
            "refresh_binding",
            False,
            refs,
        )
    if isinstance(
        error,
        CacheScanBudgetExceededError
        | SubmissionRepairExhaustedError
        | DecisionAnswerBudgetExhaustedError,
    ):
        return _diagnostic(
            "budget_exhaustion",
            "budget_exhausted",
            "The configured correction or recovery budget is exhausted.",
            "stop",
            False,
            refs,
        )
    if isinstance(error, CompromisedFileStateError):
        return _diagnostic(
            "infrastructure_environment",
            "compromised_file_state",
            "The execution environment failed its file-state integrity check.",
            "resolve_environment",
            False,
            refs,
        )
    if isinstance(error, ProcessQuiescenceError):
        return _diagnostic(
            "infrastructure_environment",
            "process_quiescence_failed",
            "The runner environment could not be safely quiesced.",
            "resolve_environment",
            False,
            refs,
        )
    if isinstance(error, AgentConfigError | AgentNotAvailableError | AgentRateLimitError):
        return _diagnostic(
            "infrastructure_environment",
            "runner_environment_blocked",
            "The runner environment is unavailable or blocked.",
            "resolve_environment",
            False,
            refs,
        )
    if isinstance(error, AgentExecutionError | AgentTimeoutError):
        return _diagnostic(
            "execution",
            "runner_execution_failed",
            "The runner did not complete the execution.",
            "retry_or_recover",
            False,
            refs,
        )
    if isinstance(error, ValueError):
        return _diagnostic(
            "answer_validation",
            "answer_validation_failed",
            "The submitted answer does not match the bound answer contract.",
            "correct_answer",
            True,
            refs,
        )
    return _diagnostic(
        "execution",
        "runtime_failure",
        "The runner did not complete the execution.",
        "retry_or_recover",
        False,
        refs,
    )


def _diagnostic(
    category: FailureCategory,
    code: str,
    message: str,
    next_action: FailureNextAction,
    correction_allowed: bool,
    refs: tuple[str, ...],
) -> FailureDiagnostic:
    return FailureDiagnostic(
        category=category,
        code=code,
        message=message,
        next_action=next_action,
        correction_allowed=correction_allowed,
        protected_evidence_refs=refs,
    )
