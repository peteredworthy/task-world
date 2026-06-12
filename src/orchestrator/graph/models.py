"""Pydantic models for the execution graph PRD data contracts."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GraphBaseModel(BaseModel):
    """Base model that preserves forward-compatible PRD fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Dump the supplied PRD shape unless callers choose a different policy."""
        kwargs.setdefault("by_alias", True)
        kwargs.setdefault("exclude_unset", True)
        return super().model_dump(*args, **kwargs)


class RunLifecycleState(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    ACTIVE = "active"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class RunModel(GraphBaseModel):
    run_id: str
    routine_snapshot_id: str
    repo_id: str
    worktree_path: str
    run_branch: str
    lifecycle_state: RunLifecycleState
    root_snapshot_id: str
    event_position: int


class NodeKind(str, Enum):
    ROOT = "root"
    TASK_PROJECTION = "task_projection"
    WORKER = "worker"
    VERIFIER = "verifier"
    CHECK = "check"
    PLANNER = "planner"
    OVERSIGHT = "oversight"
    APPEAL = "appeal"
    GATE = "gate"
    RECOVERY = "recovery"
    REVIEW = "review"
    ARTIFACT = "artifact"
    REQUIREMENT = "requirement"
    FILE_STATE = "file_state"
    SESSION = "session"


class NodeState(str, Enum):
    PLANNED = "planned"
    BLOCKED = "blocked"
    READY = "ready"
    LEASED = "leased"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    RETIRED = "retired"
    CANCELLED = "cancelled"


class ResourceClaim(GraphBaseModel):
    mode: str
    scope: str
    paths: list[str] | None = None
    external_resource_key: str | None = None


def _empty_resource_claims() -> list[ResourceClaim]:
    return []


class Authority(GraphBaseModel):
    allowed_actions: list[str] = Field(default_factory=list)
    resource_claims: list[ResourceClaim] = Field(default_factory=_empty_resource_claims)


class PortModel(GraphBaseModel):
    node_id: str | None = None
    port: str
    direction: Literal["input", "output"] | None = None
    schema_: str | None = Field(default=None, alias="schema")
    record_layers: list[str] | None = None
    required: bool | None = None


def _empty_ports() -> list[PortModel]:
    return []


class NodeMembership(GraphBaseModel):
    task_region_id: str
    attempt_number: int
    candidate_id: str
    execution_id: str


class NodeModel(GraphBaseModel):
    node_id: str
    run_id: str | None = None
    kind: NodeKind
    role: str | None = None
    state: NodeState | None = None
    created_by_event: str | None = None
    authority: Authority | None = None
    inputs: list[PortModel] = Field(default_factory=_empty_ports)
    outputs: list[PortModel] = Field(default_factory=_empty_ports)
    membership: NodeMembership | None = None


class RecordSelector(GraphBaseModel):
    record_kinds: list[str]
    schema_: str | None = Field(default=None, alias="schema")


class EdgeModel(GraphBaseModel):
    edge_id: str
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool = True
    accepted_record_selector: RecordSelector | None = None


class InputBinding(GraphBaseModel):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str]
    bound_at_position: int


class OutputRecord(GraphBaseModel):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    value: dict[str, Any]


class GitRef(GraphBaseModel):
    commit_sha: str | None = None
    tree_sha: str | None = None
    no_commit_reason: str | None = None


class FileEntry(GraphBaseModel):
    path: str
    status: str | None = None
    classification: str | None = None
    policy: str | None = None


def _empty_file_entries() -> list[FileEntry]:
    return []


class FileStateRecord(GraphBaseModel):
    record_id: str
    record_kind: Literal["file_state"]
    snapshot_id: str
    base_snapshot_id: str | None = None
    producer_node_id: str | None = None
    git: GitRef | None = None
    tracked: list[FileEntry] = Field(default_factory=_empty_file_entries)
    untracked: list[FileEntry] = Field(default_factory=_empty_file_entries)
    ignored: list[FileEntry] = Field(default_factory=_empty_file_entries)
    external: list[FileEntry] = Field(default_factory=_empty_file_entries)
    patch_bundle_id: str | None = None
    tree_snapshot_id: str | None = None


class GraphRecordKind(str, Enum):
    NODE_CREATED = "node_created"
    EDGE_CREATED = "edge_created"
    NODE_RETIRED = "node_retired"
    NODE_STATE_CHANGED = "node_state_changed"
    LEASE_GRANTED = "lease_granted"
    LEASE_SUSPENDED = "lease_suspended"
    LEASE_REVOKED = "lease_revoked"
    CALLBACK_RECEIVED = "callback_received"
    CALLBACK_ACCEPTED = "callback_accepted"
    CALLBACK_REJECTED_STALE = "callback_rejected_stale"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    REVISION_CREATED = "revision_created"
    APPEAL_OPENED = "appeal_opened"
    OVERSIGHT_DECISION_RECORDED = "oversight_decision_recorded"
    APPROVAL_DECISION_RECORDED = "approval_decision_recorded"
    GRAPH_PATCH_ACCEPTED = "graph_patch_accepted"
    FILE_STATE_ACCEPTED = "file_state_accepted"


class GraphRecord(GraphBaseModel):
    record_id: str
    record_kind: GraphRecordKind
    run_id: str | None = None
    producer_node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ActorKind(str, Enum):
    CONTROLLER = "controller"
    AGENT = "agent"
    HUMAN = "human"
    SCHEDULER = "scheduler"
    SYSTEM = "system"


class Actor(GraphBaseModel):
    kind: ActorKind
    id: str | None = None
    node_id: str | None = None
    role: str | None = None


class EventEnvelope(GraphBaseModel):
    event_id: str
    run_id: str
    position: int
    event_type: str
    schema_version: int
    actor: Actor
    causation_id: str | None = None
    correlation_id: str | None = None
    timestamp: datetime
    payload: dict[str, Any]


class PatchOp(GraphBaseModel):
    op: str
    node: dict[str, Any] | None = None
    from_node_id: str | None = None
    from_port: str | None = None
    to_node_id: str | None = None
    to_port: str | None = None
    node_id: str | None = None
    resource_claims: list[ResourceClaim] | None = None
    allowed_actions: list[str] | None = None


class PatchEnvelope(GraphBaseModel):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: int
    ops: list[PatchOp]
    rationale_record_id: str | None = None


class LeaseState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    EXPIRED = "expired"
    RELEASED = "released"


class LeaseModel(GraphBaseModel):
    lease_id: str
    generation: int
    run_id: str
    node_id: str
    session_id: str | None = None
    base_snapshot_id: str
    resource_claims: list[ResourceClaim] = Field(default_factory=_empty_resource_claims)
    expires_at: datetime
    state: LeaseState


def _empty_record_proposals() -> list[dict[str, Any]]:
    return []


def _empty_patch_envelopes() -> list[PatchEnvelope]:
    return []


class CallbackEnvelope(GraphBaseModel):
    run_id: str
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int
    base_snapshot_id: str
    observed_graph_position: int
    idempotency_key: str
    records: list[dict[str, Any]] = Field(default_factory=_empty_record_proposals)
    proposed_graph_patches: list[PatchEnvelope] = Field(default_factory=_empty_patch_envelopes)
