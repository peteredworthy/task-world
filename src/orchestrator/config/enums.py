"""Status enums for the orchestrator."""

from enum import Enum


class RunStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Statuses from which a run can never leave (except the operator reopen edge
# for FAILED graph runs; CANCELLED has no reopen path — the graph kernel
# treats cancelled as strictly terminal).
TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class TaskStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    PENDING_USER_ACTION = "pending_user_action"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    FAN_OUT_RUNNING = "fan_out_running"
    COMPLETED = "completed"
    FAILED = "failed"


class ChecklistStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED = "blocked"
    ESCALATED = "escalated"


class Priority(str, Enum):
    CRITICAL = "critical"
    EXPECTED = "expected"
    NICE = "nice"


class AgentRunnerType(str, Enum):
    OPENHANDS_LOCAL = "openhands_local"
    OPENHANDS_DOCKER = "openhands_docker"
    CLI_SUBPROCESS = "cli_subprocess"
    CODEX_SERVER = "codex_server"
    RETIRED = "retired"


SELECTABLE_AGENT_RUNNER_TYPES: frozenset[AgentRunnerType] = frozenset(
    {
        AgentRunnerType.OPENHANDS_LOCAL,
        AgentRunnerType.OPENHANDS_DOCKER,
        AgentRunnerType.CLI_SUBPROCESS,
        AgentRunnerType.CODEX_SERVER,
    }
)
SELECTABLE_AGENT_RUNNER_VALUES: frozenset[str] = frozenset(
    {"openhands_local", "openhands_docker", "cli_subprocess", "codex_server"}
)


def normalize_persisted_agent_runner_type(
    value: AgentRunnerType | str | None,
) -> AgentRunnerType | None:
    """Parse a persisted runner value, mapping the historical SDK marker."""
    if value is None or isinstance(value, AgentRunnerType):
        return value
    if value == "claude_sdk":
        return AgentRunnerType.RETIRED
    return AgentRunnerType(value)


def is_selectable_agent_runner_type(value: AgentRunnerType) -> bool:
    """Return whether a runner can be selected for new execution."""
    return value in SELECTABLE_AGENT_RUNNER_TYPES


class RoutineSource(str, Enum):
    LOCAL = "local"
    EMBEDDED = "embedded"
    PROJECT = "project"


class GateType(str, Enum):
    CHECKLIST = "checklist"
    GRADE_THRESHOLD = "grade_threshold"
    HUMAN_APPROVAL = "human_approval"
    AUTO_VERIFY = "auto_verify"


class MergeStrategy(str, Enum):
    SQUASH = "squash"  # default - condense run commits into one
    MERGE = "merge"  # preserve full history with merge commit


class StepType(str, Enum):
    STANDARD = "standard"
    DRY_RUN = "dry_run"


class Complexity(str, Enum):
    SIMPLE = "simple"
    STANDARD = "standard"


class ModelProfile(str, Enum):
    ARCHITECT = "architect"
    DESIGNER = "designer"
    CODER = "coder"
    SUMMARIZER = "summarizer"
