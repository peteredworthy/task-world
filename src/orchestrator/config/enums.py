"""Status enums for the orchestrator."""

from enum import Enum


class RunStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    PENDING_USER_ACTION = "pending_user_action"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"


class ChecklistStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED = "blocked"


class Priority(str, Enum):
    CRITICAL = "critical"
    EXPECTED = "expected"
    NICE = "nice"


class AgentType(str, Enum):
    OPENHANDS_LOCAL = "openhands_local"
    OPENHANDS_DOCKER = "openhands_docker"
    CLI_SUBPROCESS = "cli_subprocess"
    USER_MANAGED = "user_managed"
    CODEX_SERVER = "codex_server"
    CODEX_SERVER_REMOTE = "codex_server_remote"


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
