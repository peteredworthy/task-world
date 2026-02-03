"""Status enums for the orchestrator."""

from enum import Enum


class RunStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    VERIFYING = "verifying"
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


class RoutineSource(str, Enum):
    LOCAL = "local"
