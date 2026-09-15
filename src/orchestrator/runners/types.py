"""Agent-related types for the orchestrator."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.config import FailureDiagnostic
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus
from orchestrator.config.models import MCPServerConfig


class BroadcastCallback(Protocol):
    """Protocol for broadcasting run events to connected WebSocket clients.

    Runners depend on this protocol rather than the concrete ConnectionManager
    from api/, preserving the Execution → Interface layering boundary.
    """

    async def broadcast_event(self, event: object) -> None:
        """Broadcast a WorkflowEvent to the relevant run's subscribers."""
        ...


# Callback type aliases.
# run_id and task_id are captured in the closure by the caller,
# so callbacks only need req_id, status, and optional note.
ChecklistUpdateCallback = Callable[[str, ChecklistStatus, str | None], Awaitable[None]]
"""(req_id, status, note) -> None. run_id/task_id bound by caller."""

SubmitArguments = dict[str, Any]


class SubmissionInvocation(BaseModel):
    """Trusted delivery identity carried beside model-authored submit arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    execution_id: str = Field(min_length=1)
    answer_attempt_id: str = Field(min_length=1)
    transport_channel: str = Field(min_length=1)
    transport_session_id: str = Field(min_length=1)
    transport_request_id: str = Field(min_length=1)
    arguments: SubmitArguments | None = None

    @field_validator(
        "execution_id",
        "answer_attempt_id",
        "transport_channel",
        "transport_session_id",
        "transport_request_id",
    )
    @classmethod
    def identity_fields_are_substantive(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("submission invocation identity must contain non-whitespace text")
        return value


SubmissionRejectionCategory = Literal[
    "submission_format_rejected",
    "candidate_check_failed",
    "validation_environment_blocked",
]


class SubmissionRejectionEvidence(BaseModel):
    """Bounded structured evidence explaining why a submit was rejected."""

    model_config = {"frozen": True}

    category: SubmissionRejectionCategory
    command: str | None = Field(default=None, max_length=512)
    command_source: str | None = Field(default=None, max_length=128)
    command_sha256: str | None = Field(default=None, max_length=64)
    exit_code: int | None = None
    timed_out: bool = False
    failed_test_ids: tuple[str, ...] = ()
    failed_test_ids_truncated: bool = False
    final_diagnostic: str = Field(min_length=1, max_length=2_048)
    stdout_sha256: str | None = Field(default=None, max_length=64)
    stderr_sha256: str | None = Field(default=None, max_length=64)
    stdout_bytes: int | None = Field(default=None, ge=0)
    stderr_bytes: int | None = Field(default=None, ge=0)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    evidence_truncated: bool = False
    failure_identity_status: Literal["established", "unknown"] = "unknown"
    semantic_failure_fingerprint: str | None = Field(default=None, max_length=64)
    durable_audit_reference: str | None = Field(default=None, max_length=256)


class SubmissionAcknowledgement(BaseModel):
    """Truthful durable state returned by a runner submission callback.

    A first successful callback can only report ``durably_staged`` because
    graph finalization follows successful runner return.  A duplicate or
    reconnected callback may subsequently read back ``finalized_accepted``
    from the canonical execution attempt.  ``rejected`` is the only failure
    disposition and always carries actionable detail in ``message``.
    """

    model_config = {"frozen": True}

    disposition: Literal["rejected", "durably_staged", "finalized_accepted"]
    message: str = Field(min_length=1, max_length=4_096)
    execution_id: str | None = None
    graph_position: int | None = Field(default=None, ge=0)
    rejection_category: SubmissionRejectionCategory | None = None
    rejection_evidence: SubmissionRejectionEvidence | None = None
    failure_diagnostic: FailureDiagnostic | None = None

    @property
    def is_rejected(self) -> bool:
        return self.disposition == "rejected"


def submission_rejection_requires_stop(acknowledgement: SubmissionAcknowledgement) -> bool:
    """Return whether a rejection must not trigger authored-code correction."""
    diagnostic = acknowledgement.failure_diagnostic
    return acknowledgement.rejection_category == "validation_environment_blocked" or (
        diagnostic is not None and not diagnostic.correction_allowed
    )


SubmitCallbackResult = SubmissionAcknowledgement | None
SubmitCallback = (
    Callable[[], Awaitable[SubmitCallbackResult]]
    | Callable[
        [SubmitArguments | SubmissionInvocation | None],
        Awaitable[SubmitCallbackResult],
    ]
)
"""Legacy or trusted-invocation submission callback with a truthful result."""

LogLineCallback = Callable[[list[str]], Awaitable[None]]

GradeCallback = Callable[[str, str, str | None], Awaitable[None]]
"""(req_id, grade, grade_reason) -> None. run_id/task_id bound by caller."""

CompleteRecoveryCallback = Callable[[str, str | None], Awaitable[None]]
"""(outcome, notes) -> None. outcome is 'retry', 'skip', or 'abandon'. run_id/task_id bound by caller."""

AgentMetadataCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Called when agent subprocess is created, with metadata like pid."""

EscalationCallback = Callable[[str, str], Awaitable[None]]
"""(requirement_id, reason) -> None. Called when agent flags a requirement as unfulfillable."""

GraphPatchCallback = Callable[[dict[str, Any]], Awaitable[str]]
"""Called when a graph planner submits a patch through the callback tool.

Args:
    patch_payload: A JSON-compatible payload matching PatchEnvelope plus caller
        identity fields.

Returns:
    A status message to expose to the model.
"""


class ExecutionMetrics(BaseModel):
    """Metrics collected during agent execution."""

    gen_ai_usage_input_tokens: int = 0
    gen_ai_usage_output_tokens: int = 0
    gen_ai_usage_cache_read_input_tokens: int = 0
    duration_ms: int = 0
    num_actions: int = 0


class SubmissionOutputContract(BaseModel):
    """Runner-facing contract for one agent-authored output port."""

    model_config = {"frozen": True}

    port: str = Field(min_length=1)
    schema_name: str = Field(min_length=1)
    required: bool = True
    record_type: str | None = None
    semantic_schema_id: str | None = None
    semantic_schema_version: int | None = Field(default=None, ge=1)
    semantic_role: str | None = None
    content_json_schema: dict[str, Any] | None = None


class SubmissionContract(BaseModel):
    """Graph-agnostic typed description of model-authored submit arguments."""

    model_config = {"frozen": True}

    interaction_contract: Literal["legacy", "decision-v1"] = "legacy"
    outputs: tuple[SubmissionOutputContract, ...] = ()

    @property
    def requires_arguments(self) -> bool:
        return any(
            output.required and output.content_json_schema is not None for output in self.outputs
        )


class ExecutionResult(BaseModel):
    """Result of agent execution."""

    success: bool
    error: str | None = None
    metrics: ExecutionMetrics = ExecutionMetrics()
    agent_metadata: dict[str, Any] = {}  # Runtime metadata like PID, container_id
    output_lines: list[str] = []
    action_log: Any = None  # ActionLog | None — typed as Any to avoid circular import
    # Provider-native metadata retained at the runner boundary. These are kept
    # outside normalized metrics because they describe a response, not a cost.
    gen_ai_response_finish_reasons: list[str] = Field(default_factory=list)
    gen_ai_usage_reasoning_output_tokens: int = Field(default=0, ge=0)
    completion_cause: Literal["terminal_answer_completed"] | None = None


class ExecutionContext(BaseModel):
    """Context provided to an agent for execution."""

    run_id: str
    execution_id: str | None = None
    task_id: str
    working_dir: str
    prompt: str
    requirements: list[str]
    api_base_url: str | None = None
    auth_token: str | None = None
    end_commit: str | None = None  # For verifier: commit to checkout before verification
    step_id: str | None = None
    node_id: str | None = None
    node_kind: str | None = None
    node_role: str | None = None
    expected_git_branch: str | None = None
    graph_patch_callback: GraphPatchCallback | None = None
    graph_mcp_url: str | None = None
    available_tools: list[str] | None = None
    required_tools: tuple[str, ...] = ()
    mcp_servers: list[MCPServerConfig] | None = None
    work_mode: Literal["implementation", "oversight"] = "implementation"
    submission_contract: SubmissionContract | None = None


class RunnerRuntimeObservationCapability(BaseModel):
    """Declares how a runner can be supervised during one execution.

    ``host_process`` promises a PID callback that can be bound to create-time
    and command identity. ``non_process_owning`` is for in-process adapters,
    while ``unsupported`` names a process-owning boundary (for example a
    container) for which that exact identity is not available yet.
    """

    model_config = {"frozen": True}

    mode: Literal["host_process", "non_process_owning", "unsupported"]
    reason: str = Field(min_length=1, max_length=512)


class AgentRunnerInfo(BaseModel):
    """Information about a concrete agent instance."""

    agent_runner_type: AgentRunnerType
    name: str
    version: str | None = None
    runtime_observation: RunnerRuntimeObservationCapability = Field(
        default_factory=lambda: RunnerRuntimeObservationCapability(
            mode="unsupported",
            reason="runner did not declare a runtime-observation capability",
        )
    )


class AgentConfigField(BaseModel):
    """Schema for a single agent runner configuration field.

    Used by the frontend to render config forms per agent runner type.
    """

    name: str
    field_type: str  # "string", "number", "boolean", "select"
    required: bool = False
    default: Any = None
    description: str = ""
    options: list[str] | None = None  # for "select" type
    allow_custom: bool = False  # if True, render as combobox (free-text + suggestions)


class QuotaBucket(BaseModel):
    """A named quota bucket within an agent's overall quota breakdown.

    Used to show per-window details (e.g. 5-hour session, 7-day weekly,
    Sonnet-specific) in the sidebar expandable panel.
    """

    label: str
    remaining_pct: float | None = None  # 0–100 remaining percentage
    remaining_usd: float | None = None  # remaining dollar amount (may be negative if over limit)
    resets_at: str | None = None  # ISO 8601 datetime string


class AgentRunnerQuota(BaseModel):
    """Quota/balance information for an agent runner."""

    balance_usd: float | None = None
    balance_pct: float | None = None
    max_balance_usd: float | None = None
    label: str = ""
    supports_quota: bool = True
    breakdown: list[QuotaBucket] | None = None  # per-bucket detail for expanded view
    fetched_at: str | None = None  # ISO 8601 timestamp of last successful fetch

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.balance_usd is None and self.balance_pct is None:
            raise ValueError("At least one of balance_usd or balance_pct must be set")


# Backward-compatible alias
AgentQuota = AgentRunnerQuota


class AgentRunnerOption(BaseModel):
    """An available agent runner option returned by the detector."""

    agent_runner_type: str
    name: str
    title: str = ""
    description: str = ""
    available: bool
    detail: str = ""
    install_hint: str = ""
    config_schema: list[AgentConfigField] = []
    quota: AgentRunnerQuota | None = None


# Backward-compatible alias
AgentOption = AgentRunnerOption
