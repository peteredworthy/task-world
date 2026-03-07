"""Agent-related types for the orchestrator."""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from orchestrator.config.enums import AgentRunnerType, ChecklistStatus
from orchestrator.config.models import MCPServerConfig

# Callback type aliases.
# run_id and task_id are captured in the closure by the caller,
# so callbacks only need req_id, status, and optional note.
ChecklistUpdateCallback = Callable[[str, ChecklistStatus, str | None], Awaitable[None]]
"""(req_id, status, note) -> None. run_id/task_id bound by caller."""

SubmitCallback = Callable[[], Awaitable[None]]
"""Called when agent submits work for verification."""

LogLineCallback = Callable[[list[str]], Awaitable[None]]

GradeCallback = Callable[[str, str, str | None], Awaitable[None]]
"""(req_id, grade, grade_reason) -> None. run_id/task_id bound by caller."""

CompleteRecoveryCallback = Callable[[str, str | None], Awaitable[None]]
"""(outcome, notes) -> None. outcome is 'retry', 'skip', or 'abandon'. run_id/task_id bound by caller."""

AgentMetadataCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Called when agent subprocess is created, with metadata like pid."""

EscalationCallback = Callable[[str, str], Awaitable[None]]
"""(requirement_id, reason) -> None. Called when agent flags a requirement as unfulfillable."""


class ExecutionMetrics(BaseModel):
    """Metrics collected during agent execution."""

    tokens_read: int = 0
    tokens_write: int = 0
    tokens_cache: int = 0
    duration_ms: int = 0
    num_actions: int = 0


class ExecutionResult(BaseModel):
    """Result of agent execution."""

    success: bool
    error: str | None = None
    metrics: ExecutionMetrics = ExecutionMetrics()
    agent_metadata: dict[str, Any] = {}  # Runtime metadata like PID, container_id
    output_lines: list[str] = []
    action_log: Any = None  # ActionLog | None — typed as Any to avoid circular import


class ExecutionContext(BaseModel):
    """Context provided to an agent for execution."""

    run_id: str
    task_id: str
    working_dir: str
    prompt: str
    requirements: list[str]
    api_base_url: str | None = None
    auth_token: str | None = None
    end_commit: str | None = None  # For verifier: commit to checkout before verification
    step_id: str | None = None
    available_tools: list[str] | None = None
    mcp_servers: list[MCPServerConfig] | None = None


class AgentRunnerInfo(BaseModel):
    """Information about a concrete agent instance."""

    agent_type: AgentRunnerType
    name: str
    version: str | None = None


class AgentConfigField(BaseModel):
    """Schema for a single agent configuration field.

    Used by the frontend to render config forms per agent type.
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

    agent_type: str
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
