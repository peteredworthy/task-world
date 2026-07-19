"""Runtime state Pydantic models for runs, steps, tasks, and attempts."""

from datetime import datetime, timezone
from enum import Enum
from collections.abc import Iterable
from typing import Any, SupportsIndex, cast

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    computed_field,
    model_validator,
)

from orchestrator.config.models import EnvFileSpec
from orchestrator.config.enums import (
    AgentRunnerType,
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.state._utils import generate_id


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Maximum size for tool result output (5KB)
MAX_TOOL_OUTPUT_SIZE = 5 * 1024


class ActionEntryKind(str, Enum):
    """Discriminator for action log entry types."""

    SYSTEM_INIT = "system_init"
    ASSISTANT_TEXT = "assistant_text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    RESULT = "result"
    ERROR = "error"


class ToolUseDetail(BaseModel):
    """Detail for a tool_use entry."""

    tool_use_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = {}
    summary: str | None = None


class ToolResultDetail(BaseModel):
    """Detail for a tool_result entry."""

    tool_use_id: str = ""
    output: str = ""  # Truncated to MAX_TOOL_OUTPUT_SIZE
    exit_code: int | None = None
    success: bool = True
    output_length: int = 0  # Original output length before truncation


class TurnMetrics(BaseModel):
    """Per-turn token/cost metrics."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


class ActionLogEntry(BaseModel):
    """A single entry in the action log.

    Uses `kind` discriminator + nullable content fields (not inheritance)
    for clean JSON serialization. `tool_use_id` on ToolUseDetail/ToolResultDetail
    links tool_use entries to their corresponding tool_result entries.
    """

    sequence_num: int = 0
    kind: ActionEntryKind
    timestamp: datetime | None = None
    text: str | None = None
    tool_use: ToolUseDetail | None = None
    tool_result: ToolResultDetail | None = None
    metrics: TurnMetrics | None = None
    raw_type: str | None = None  # Original event type from the agent stream


class SubAgentLog(BaseModel):
    """Token usage and action data for a single Claude Code sub-agent session.

    Sub-agents are spawned by the parent agent via the ``Agent`` tool
    (e.g. ``subagent_type: "Explore"``). They run as separate Claude Code
    processes and their token costs are NOT included in the parent session's
    reported usage — so they must be captured separately.

    Data comes from ``~/.claude/projects/{slug}/{session_id}/subagents/``.
    """

    agent_id: str = ""
    subagent_type: str = Field(
        default="",
        validation_alias=AliasChoices("subagent_type", "agent_runner_type"),
    )  # e.g. "Explore"
    description: str = ""
    model: str | None = None

    # Per-turn token totals (summed across all turns; no ``result`` event)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    input_tokens_include_cache: bool = True

    # Structured tool calls (Read/Bash/Glob/Grep) so we know what was explored
    entries: list[ActionLogEntry] = []


class ActionLog(BaseModel):
    """Complete structured action log for an agent execution.

    Contains individual entries plus session-level metadata and aggregate totals.
    """

    entries: list[ActionLogEntry] = []

    # Session metadata
    session_id: str | None = None
    agent_model: str | None = None
    tools_available: list[str] = []

    # Aggregate totals
    total_turns: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    # Provider-semantic marker: false means input excludes cache components.
    input_tokens_include_cache: bool = True

    # Sub-agent sessions spawned via the Agent tool (separate billing, not in totals above)
    sub_agents: list[SubAgentLog] = []

    # Sub-agent aggregate totals (separate from parent for cost accounting)
    sub_agent_total_input_tokens: int = 0
    sub_agent_total_output_tokens: int = 0
    sub_agent_total_cache_read_tokens: int = 0
    sub_agent_total_cache_creation_tokens: int = 0

    # Rate-limit detection (set by parser when Claude CLI returns limit message)
    rate_limit_hit: bool = False
    rate_limit_resets_at: datetime | None = None

    # Exit classification (set by parser from the result event's subtype field)
    # e.g. "error_max_turns", "error_during_tool_use", "success"
    exit_subtype: str = ""


class ChecklistItem(BaseModel):
    """Runtime state of a single requirement."""

    req_id: str
    desc: str
    priority: Priority
    status: ChecklistStatus = ChecklistStatus.OPEN
    note: str | None = None
    grade: str | None = None
    grade_reason: str | None = None


class _FrozenReasonList(list[str]):
    """List-shaped JSON boundary value that rejects in-place mutation."""

    def __setitem__(self, key: SupportsIndex | slice, value: str | Iterable[str]) -> None:
        raise TypeError("finish reasons are immutable")

    def __delitem__(self, key: SupportsIndex | slice) -> None:
        raise TypeError("finish reasons are immutable")

    def append(self, item: str) -> None:
        raise TypeError("finish reasons are immutable")

    def extend(self, values: Iterable[str]) -> None:
        raise TypeError("finish reasons are immutable")

    def insert(self, index: SupportsIndex, item: str) -> None:
        raise TypeError("finish reasons are immutable")

    def pop(self, index: SupportsIndex = -1) -> str:
        raise TypeError("finish reasons are immutable")

    def remove(self, value: str) -> None:
        raise TypeError("finish reasons are immutable")

    def clear(self) -> None:
        raise TypeError("finish reasons are immutable")

    def reverse(self) -> None:
        raise TypeError("finish reasons are immutable")

    def sort(self, *, key: Any = None, reverse: bool = False) -> None:
        raise TypeError("finish reasons are immutable")

    def __iadd__(self, value: Iterable[str]) -> "_FrozenReasonList":
        raise TypeError("finish reasons are immutable")

    def __imul__(self, value: SupportsIndex) -> "_FrozenReasonList":
        raise TypeError("finish reasons are immutable")


class _LegacyCostRates(BaseModel):
    """Validated transitional rate snapshot used only by legacy constructors."""

    model_config = ConfigDict(strict=True)

    cost_per_m_cache_read: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    cost_per_m_cache_creation: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    cost_per_m_input: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    cost_per_m_output: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class ModelTokenUsage(BaseModel):
    """An immutable OTel usage fact for one execution and model.

    Cache components are included in ``gen_ai_usage_input_tokens``. Reasoning
    remains observable as a separate output component but is not an additional
    billable output quantity.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    gen_ai_usage_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_output_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_read_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_creation_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_reasoning_output_tokens: int = Field(default=0, ge=0)
    gen_ai_response_finish_reasons: list[str] = Field(default_factory=list)
    cost_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    latency_ms: int = Field(default=0, ge=0)
    rate_missing: bool = False
    _legacy_cost_rates: dict[str, float] = PrivateAttr(default_factory=lambda: dict[str, float]())

    def __init__(self, **data: Any) -> None:
        """Accept Task 3's temporary legacy constructor payloads."""
        rate_fields = (
            "cost_per_m_cache_read",
            "cost_per_m_cache_creation",
            "cost_per_m_input",
            "cost_per_m_output",
        )
        legacy_rate_data = {field: data[field] for field in rate_fields if field in data}
        legacy_cost_rates = _LegacyCostRates.model_validate(legacy_rate_data).model_dump()
        if legacy_cost_rates and "cost_usd" not in data:
            input_tokens = int(data.get("gen_ai_usage_input_tokens", data.get("input_tokens", 0)))
            cache_read = int(
                data.get("gen_ai_usage_cache_read_input_tokens", data.get("cache_read_tokens", 0))
            )
            cache_creation = int(
                data.get(
                    "gen_ai_usage_cache_creation_input_tokens", data.get("cache_creation_tokens", 0)
                )
            )
            data["cost_usd"] = (
                cache_read * legacy_cost_rates.get("cost_per_m_cache_read", 0.0)
                + cache_creation * legacy_cost_rates.get("cost_per_m_cache_creation", 0.0)
                + (input_tokens - cache_read - cache_creation)
                * legacy_cost_rates.get("cost_per_m_input", 0.0)
                + int(data.get("gen_ai_usage_output_tokens", data.get("output_tokens", 0)))
                * legacy_cost_rates.get("cost_per_m_output", 0.0)
            ) / 1_000_000
        super().__init__(**data)
        object.__setattr__(self, "_legacy_cost_rates", legacy_cost_rates)

    @model_validator(mode="before")
    @classmethod
    def _translate_legacy_token_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        translated: dict[str, Any] = dict(cast(dict[str, Any], data))
        for legacy, canonical in (
            ("input_tokens", "gen_ai_usage_input_tokens"),
            ("output_tokens", "gen_ai_usage_output_tokens"),
            ("cache_read_tokens", "gen_ai_usage_cache_read_input_tokens"),
            ("cache_creation_tokens", "gen_ai_usage_cache_creation_input_tokens"),
        ):
            if legacy in translated and canonical in translated:
                if translated[legacy] != translated[canonical]:
                    raise ValueError(f"conflicting {legacy} and {canonical} values")
            elif legacy in translated:
                translated[canonical] = translated[legacy]
        return translated

    @model_validator(mode="after")
    def _cache_components_are_part_of_input(self) -> "ModelTokenUsage":
        cache_tokens = (
            self.gen_ai_usage_cache_read_input_tokens
            + self.gen_ai_usage_cache_creation_input_tokens
        )
        if cache_tokens > self.gen_ai_usage_input_tokens:
            raise ValueError("cache input components cannot exceed input tokens")
        object.__setattr__(
            self,
            "gen_ai_response_finish_reasons",
            _FrozenReasonList(self.gen_ai_response_finish_reasons),
        )
        return self

    # Transitional Task 2 bridge. Task 3 migrates remaining old-field readers.
    @computed_field
    @property
    def cache_read_tokens(self) -> int:
        return self.gen_ai_usage_cache_read_input_tokens

    @computed_field
    @property
    def cache_creation_tokens(self) -> int:
        return self.gen_ai_usage_cache_creation_input_tokens

    @computed_field
    @property
    def input_tokens(self) -> int:
        return self.gen_ai_usage_input_tokens

    @computed_field
    @property
    def output_tokens(self) -> int:
        return self.gen_ai_usage_output_tokens

    def _cost_rate(self, field: str) -> float:
        return self._legacy_cost_rates.get(field, 0.0)

    @computed_field
    @property
    def cost_per_m_cache_read(self) -> float:
        return self._cost_rate("cost_per_m_cache_read")

    @computed_field
    @property
    def cost_per_m_cache_creation(self) -> float:
        return self._cost_rate("cost_per_m_cache_creation")

    @computed_field
    @property
    def cost_per_m_input(self) -> float:
        return self._cost_rate("cost_per_m_input")

    @computed_field
    @property
    def cost_per_m_output(self) -> float:
        return self._cost_rate("cost_per_m_output")

    @property
    def total_cost_usd(self) -> float:
        """Temporary legacy accessor for the cost captured at execution time."""
        return self.cost_usd


class AttemptMetrics(BaseModel):
    """Metrics for a single attempt."""

    tokens_read: int = 0
    tokens_write: int = 0
    tokens_cache: int = 0
    duration_ms: int = 0
    num_actions: int = 0


class GradeSnapshotItem(BaseModel):
    """Snapshot of a single checklist item's grade and builder note at attempt completion."""

    req_id: str
    grade: str | None = None
    grade_reason: str | None = None
    note: str | None = None


class Attempt(BaseModel):
    """A single builder-verifier cycle."""

    id: str = Field(default_factory=generate_id)
    attempt_num: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    paused_at: datetime | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    outcome: str | None = None  # "passed", "revision_needed", "failed", "paused", "reverted"
    metrics: AttemptMetrics = Field(default_factory=AttemptMetrics)
    grade_snapshot: list[GradeSnapshotItem] = Field(default_factory=lambda: [])
    auto_verify_results: list[dict[str, Any]] = Field(default_factory=lambda: [])

    # Agent snapshot - record what agent was used for this attempt
    agent_runner_type: AgentRunnerType | None = None
    agent_model: str | None = None  # e.g. "claude-sonnet-4-5-20250514"
    agent_settings: dict[str, Any] = Field(default_factory=dict)

    # Agent output capture
    agent_output: str | None = None  # Final captured output (joined lines)
    error: str | None = None  # Error message if agent failed

    # Per-model token usage breakdown (replaces flat metrics for accurate cost)
    token_usage_by_model: list[ModelTokenUsage] = Field(default_factory=lambda: [])

    # Structured action log (tool calls, text, metrics)
    action_log: ActionLog | None = None

    # Git tracking - commit SHAs for builder/verifier handoff
    start_commit: str | None = None  # Commit at attempt start
    end_commit: str | None = None  # Commit at attempt end (after builder)


class TaskState(BaseModel):
    """Runtime state of a task."""

    id: str = Field(default_factory=generate_id)
    config_id: str
    title: str = ""
    status: TaskStatus = TaskStatus.PENDING
    complexity: str = "standard"
    checklist: list[ChecklistItem] = Field(default_factory=lambda: [])
    attempts: list[Attempt] = Field(default_factory=lambda: [])
    current_attempt: int = 0
    max_attempts: int = 3
    pending_action_type: str | None = None  # "clarification" | "approval"
    pending_clarification_id: str | None = None
    has_verification: bool = True  # False if task has no auto_verify items and no verifier rubric

    # Fan-out fields
    parent_task_id: str | None = None
    fan_out_index: int | None = None
    fan_out_input: str | None = None
    fan_out_output: str | None = None
    child_id: str | None = None  # Stable UUID for fan-out children (durable across restarts)


class HumanApproval(BaseModel):
    """Record of human gate approval."""

    approved_by: str
    approved_at: datetime
    comment: str | None = None


class StepState(BaseModel):
    """Runtime state of a step."""

    id: str = Field(default_factory=generate_id)
    config_id: str
    title: str = ""
    tasks: list[TaskState] = Field(default_factory=lambda: [])
    completed: bool = False
    human_approval: HumanApproval | None = None
    condition: dict[str, Any] | None = None  # Condition from StepConfig (preserved as dict)
    skipped: bool = False
    skip_reason: str | None = None


class TransitionTracker(BaseModel):
    """Track backward transitions to prevent infinite loops."""

    counts: dict[str, int] = Field(default_factory=dict)

    def record_transition(self, from_step: str, to_step: str) -> None:
        """Record a transition from one step to another."""
        key = f"{from_step}->{to_step}"
        self.counts[key] = self.counts.get(key, 0) + 1

    def can_transition(self, from_step: str, to_step: str, max_iterations: int) -> bool:
        """Check if a transition can occur without exceeding max iterations."""
        key = f"{from_step}->{to_step}"
        return self.counts.get(key, 0) < max_iterations

    def get_count(self, from_step: str, to_step: str) -> int:
        """Get the number of times a transition has occurred."""
        key = f"{from_step}->{to_step}"
        return self.counts.get(key, 0)

    model_config = {"arbitrary_types_allowed": True}


class Run(BaseModel):
    """Runtime state of an entire run."""

    id: str = Field(default_factory=generate_id)
    repo_name: str
    status: RunStatus = RunStatus.DRAFT
    pause_reason: str | None = None  # e.g., "agent_died", "manual_pause"
    last_error: str | None = None  # Human-readable error detail when paused due to error
    execution_mode: str = "graph"

    # Routine reference
    routine_id: str | None = None
    routine_sha: str | None = None
    routine_source: RoutineSource | None = None
    routine_embedded: dict[str, Any] | None = None

    # Routine traceability (for project routines)
    routine_path: str | None = None  # Path within repo (e.g., "routines/feature.yaml")
    routine_commit: str | None = None  # Commit SHA when routine was read
    routine_source_dir: str | None = (
        None  # Absolute path to routine dir on disk (transient, not persisted)
    )

    # Oversight parent/child orchestration
    parent_run_id: str | None = None
    parent_task_id: str | None = None
    parent_slice_id: str | None = None
    oversight_state: dict[str, Any] = Field(default_factory=lambda: {})

    # Agent configuration
    agent_runner_type: AgentRunnerType | None = None
    agent_runner_config: dict[str, Any] = Field(default_factory=lambda: {})
    verifier_model: str | None = None  # Pinned at run creation; verifier always uses this model

    # Worktree
    worktree_enabled: bool = True
    worktree_path: str | None = None
    delete_worktree_on_completion: bool = False
    source_branch: str | None = None
    source_branch_sha: str | None = None
    intended_seed_sha: str | None = None
    merge_strategy: str = "squash"

    # Config passed to routine
    config: dict[str, Any] = Field(default_factory=lambda: {})

    # Environment files
    env_file_specs: list[EnvFileSpec] = Field(default_factory=lambda: [])
    env_source_dir: str | None = None

    # Runtime state
    steps: list[StepState] = Field(default_factory=lambda: [])
    current_step_index: int = 0
    transition_tracker: TransitionTracker | None = Field(default_factory=TransitionTracker)

    # Timestamps
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    agent_runner_started_at: datetime | None = None

    # Aggregate metrics
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0

    # Per-model token usage breakdown (aggregated across all attempts)
    token_usage_by_model: list[ModelTokenUsage] = Field(default_factory=lambda: [])
