"""Strict command payloads and explicit graph command context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from orchestrator.graph.macros import MacroInvocation
from orchestrator.graph.models import (
    Actor,
    EventEnvelope,
    FileStateRecord,
    RunnerBoundaryEntry,
    StoredArtifactRef,
)
from orchestrator.graph.boundary_types import (
    BoundaryValidationError,
    validate_callback_json,
    boundary_manifest_hash,
    validate_git_oid,
    validate_recovery_paths,
    validate_repo_relative_path,
    validate_snapshot_ref,
    validate_sha256,
)
from orchestrator.graph.cache_authority import (
    CacheStatusEvidence,
    RunnerCacheRoot,
    canonicalize_cache_roots,
    canonicalize_cache_status_evidence,
)
from orchestrator.graph.projections import GraphProjection
from orchestrator.state import ModelTokenUsage


class StrictCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


CommandIdentifier = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, pattern=r"^\S+$"),
]
ActorLabel = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, pattern=r".*\S.*"),
]


class GraphCommandContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: CommandIdentifier
    current_graph_position: int = Field(ge=-1)
    actor: Actor | None = None


class PatchCommandContext(GraphCommandContext):
    proposed_by_node_id: CommandIdentifier
    actor_role: str


class Clock(Protocol):
    def now(self) -> Any: ...


class IdGenerator(Protocol):
    def next_id(self, prefix: str = "") -> str: ...


ApplyCommandHandler = Callable[
    [
        GraphProjection,
        list[EventEnvelope],
        str,
        Any,
        GraphCommandContext,
        Callable[[str, dict[str, Any]], EventEnvelope],
        Clock,
        IdGenerator,
    ],
    list[EventEnvelope],
]


@dataclass(frozen=True)
class CommandSpec:
    payload_model: type[StrictCommandPayload]
    handler: ApplyCommandHandler


class TriggerCommand(StrictCommandPayload):
    trigger: str | None = None


class AcceptRunCommand(TriggerCommand):
    pass


class StartCommand(TriggerCommand):
    pass


class PauseCommand(TriggerCommand):
    pass


class ResumeCommand(TriggerCommand):
    pass


class CancelCommand(TriggerCommand):
    pass


class CompleteCommand(TriggerCommand):
    completion_decision_record_id: CommandIdentifier | None = None
    node_id: CommandIdentifier | None = None


class FailCommand(StrictCommandPayload):
    reason: str = "unrecoverable_controller_error"


class RecordHeartbeatCommand(StrictCommandPayload):
    lease_id: CommandIdentifier
    node_id: CommandIdentifier | None = None
    generation: int | None = Field(default=None, ge=0)
    ttl_seconds: int = Field(default=300, gt=0)


class SeedCompiledEventsCommand(StrictCommandPayload):
    events: list[EventEnvelope] = Field(min_length=1)


class ScheduleTickCommand(StrictCommandPayload):
    base_snapshot_id: CommandIdentifier | None = None
    max_grants: int = Field(default=10, ge=0)
    lease_seconds: int = Field(default=300, gt=0)
    lease_ids: dict[CommandIdentifier, CommandIdentifier] = Field(default_factory=dict)
    priorities: dict[str, int] = Field(default_factory=dict)
    region_order: dict[str, int] = Field(default_factory=dict)


class ReconcileCommand(StrictCommandPayload):
    pass


class SubmitCallbackCommand(StrictCommandPayload):
    node_id: CommandIdentifier
    execution_id: CommandIdentifier
    lease_id: CommandIdentifier
    lease_generation: int = Field(ge=0)
    base_snapshot_id: CommandIdentifier
    observed_graph_position: int = Field(ge=0)
    idempotency_key: CommandIdentifier
    payload_hash: CommandIdentifier | None = None
    payload: dict[str, Any] | None = None
    is_mutating: bool = True
    complete_node: bool = True
    new_state: Literal["completed", "failed"] = "completed"

    @model_validator(mode="after")
    def validate_payload_identity(self) -> SubmitCallbackCommand:
        if self.payload is None and self.payload_hash is None:
            raise ValueError("callback requires payload or payload_hash")
        return self


def _canonical_boundary_entries(
    entries: list[RunnerBoundaryEntry],
) -> list[RunnerBoundaryEntry]:
    by_path: dict[str, RunnerBoundaryEntry] = {}
    for entry in entries:
        if entry.path in by_path:
            raise ValueError(f"boundary entries duplicate {entry.path!r}")
        by_path[entry.path] = entry
    return [by_path[path] for path in sorted(by_path)]


def _canonical_command_cache_roots(
    roots: list[RunnerCacheRoot], cache_authority_hash: str | None
) -> list[RunnerCacheRoot]:
    del cache_authority_hash
    return list(canonicalize_cache_roots(roots))


def _empty_runner_cache_roots() -> list[RunnerCacheRoot]:
    return []


def _empty_cache_status_evidence() -> list[CacheStatusEvidence]:
    return []


class RecordRunnerBaselineCommand(StrictCommandPayload):
    execution_id: CommandIdentifier
    node_id: CommandIdentifier
    lease_id: CommandIdentifier
    lease_generation: int = Field(ge=0)
    lease_base_snapshot_id: CommandIdentifier | None = None
    baseline_snapshot_id: CommandIdentifier
    baseline_snapshot_ref: CommandIdentifier
    baseline_commit_sha: CommandIdentifier
    baseline_tree_sha: CommandIdentifier
    entries: list[RunnerBoundaryEntry]
    boundary_hash: CommandIdentifier
    cache_authority_hash: CommandIdentifier | None = None
    cache_roots: list[RunnerCacheRoot] = Field(default_factory=_empty_runner_cache_roots)
    cache_status_evidence: list[CacheStatusEvidence] = Field(
        default_factory=_empty_cache_status_evidence
    )

    @field_validator("boundary_hash")
    @classmethod
    def hash_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @field_validator("baseline_tree_sha")
    @classmethod
    def tree_is_git_oid(cls, value: str) -> str:
        return validate_git_oid(value)

    @model_validator(mode="after")
    def canonical_entries(self) -> RecordRunnerBaselineCommand:
        """Store one deterministic preimage per path with no ambiguous overlap."""
        by_path: dict[str, RunnerBoundaryEntry] = {}
        for entry in self.entries:
            previous = by_path.get(entry.path)
            if previous is not None and previous != entry:
                raise ValueError(f"baseline entries conflict for {entry.path!r}")
            by_path[entry.path] = entry
        paths = sorted(by_path)
        for index, path in enumerate(paths):
            if index and path.startswith(f"{paths[index - 1]}/"):
                raise ValueError("baseline entries must not contain ancestor/descendant paths")
        self.entries = [by_path[path] for path in paths]
        try:
            self.cache_roots = _canonical_command_cache_roots(
                self.cache_roots, self.cache_authority_hash
            )
            self.cache_status_evidence = list(
                canonicalize_cache_status_evidence(self.cache_status_evidence)
            )
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc
        if self.boundary_hash != boundary_manifest_hash(
            self.baseline_tree_sha,
            self.entries,
            self.cache_status_evidence,
            self.cache_authority_hash,
        ):
            raise ValueError("boundary_hash does not match baseline manifest")
        validate_snapshot_ref(self.baseline_snapshot_ref, self.baseline_snapshot_id)
        validate_git_oid(self.baseline_commit_sha)
        return self


class StageRunnerSubmissionCommand(SubmitCallbackCommand):
    payload_ref: StoredArtifactRef | None = None
    staged_snapshot_id: CommandIdentifier
    staged_snapshot_ref: CommandIdentifier
    staged_commit_sha: CommandIdentifier
    staged_tree_sha: CommandIdentifier
    boundary_hash: CommandIdentifier
    boundary_entries: list[RunnerBoundaryEntry]
    cache_authority_hash: CommandIdentifier | None = None
    cache_roots: list[RunnerCacheRoot] = Field(default_factory=_empty_runner_cache_roots)
    cache_status_evidence: list[CacheStatusEvidence] = Field(
        default_factory=_empty_cache_status_evidence
    )

    @field_validator("payload_hash", "boundary_hash")
    @classmethod
    def hashes_are_sha256(cls, value: str | None) -> str | None:
        return None if value is None else validate_sha256(value)

    @field_validator("staged_tree_sha")
    @classmethod
    def tree_is_git_oid(cls, value: str) -> str:
        return validate_git_oid(value)

    @field_validator("boundary_entries")
    @classmethod
    def canonical_boundary_entries(
        cls, value: list[RunnerBoundaryEntry]
    ) -> list[RunnerBoundaryEntry]:
        return _canonical_boundary_entries(value)

    @model_validator(mode="after")
    def payload_is_bounded_json(self) -> StageRunnerSubmissionCommand:
        if self.payload is None:
            raise ValueError("managed runner staging requires the callback payload")
        try:
            validate_callback_json(self.payload)
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc
        self.cache_roots = _canonical_command_cache_roots(
            self.cache_roots, self.cache_authority_hash
        )
        self.cache_status_evidence = list(
            canonicalize_cache_status_evidence(self.cache_status_evidence)
        )
        if self.boundary_hash != boundary_manifest_hash(
            self.staged_tree_sha,
            self.boundary_entries,
            self.cache_status_evidence,
            self.cache_authority_hash,
        ):
            raise ValueError("boundary_hash does not match staged manifest")
        validate_snapshot_ref(self.staged_snapshot_ref, self.staged_snapshot_id)
        validate_git_oid(self.staged_commit_sha)
        return self


class FinalizeRunnerExecutionCommand(StrictCommandPayload):
    execution_id: CommandIdentifier
    node_id: CommandIdentifier
    lease_id: CommandIdentifier
    lease_generation: int = Field(ge=0)
    final_snapshot_id: CommandIdentifier
    final_snapshot_ref: CommandIdentifier
    final_commit_sha: CommandIdentifier
    final_tree_sha: CommandIdentifier
    boundary_hash: CommandIdentifier
    boundary_entries: list[RunnerBoundaryEntry]
    cache_authority_hash: CommandIdentifier | None = None
    cache_roots: list[RunnerCacheRoot] = Field(default_factory=_empty_runner_cache_roots)
    cache_status_evidence: list[CacheStatusEvidence] = Field(
        default_factory=_empty_cache_status_evidence
    )
    # Effectful runtime resolution supplies this transient body. It is used by
    # the pure command kernel but removed from the finalized event payload.
    callback_payload: dict[str, Any] | None = None

    @field_validator("boundary_hash")
    @classmethod
    def boundary_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @field_validator("final_tree_sha")
    @classmethod
    def tree_is_git_oid(cls, value: str) -> str:
        return validate_git_oid(value)

    @field_validator("boundary_entries")
    @classmethod
    def canonical_boundary_entries(
        cls, value: list[RunnerBoundaryEntry]
    ) -> list[RunnerBoundaryEntry]:
        return _canonical_boundary_entries(value)

    @model_validator(mode="after")
    def boundary_matches_manifest(self) -> FinalizeRunnerExecutionCommand:
        self.cache_roots = _canonical_command_cache_roots(
            self.cache_roots, self.cache_authority_hash
        )
        self.cache_status_evidence = list(
            canonicalize_cache_status_evidence(self.cache_status_evidence)
        )
        if self.boundary_hash != boundary_manifest_hash(
            self.final_tree_sha,
            self.boundary_entries,
            self.cache_status_evidence,
            self.cache_authority_hash,
        ):
            raise ValueError("boundary_hash does not match final manifest")
        validate_snapshot_ref(self.final_snapshot_ref, self.final_snapshot_id)
        validate_git_oid(self.final_commit_sha)
        return self


class RequestRunnerRecoveryCommand(StrictCommandPayload):
    """Record cleanup for a managed execution which did not reach finalization."""

    execution_id: CommandIdentifier
    node_id: CommandIdentifier
    lease_id: CommandIdentifier
    lease_generation: int = Field(ge=0)
    reason: Literal["runner_died", "cancelled"]
    max_attempts: int = Field(default=0, ge=0)
    recovery_snapshot_id: CommandIdentifier | None = None
    recovery_snapshot_ref: CommandIdentifier | None = None
    recovery_commit_sha: CommandIdentifier | None = None
    final_tree_sha: CommandIdentifier
    boundary_hash: CommandIdentifier
    boundary_entries: list[RunnerBoundaryEntry]
    cache_authority_hash: CommandIdentifier | None = None
    cache_status_evidence: list[CacheStatusEvidence] = Field(
        default_factory=_empty_cache_status_evidence
    )
    observed_cache_roots: list[RunnerCacheRoot] = Field(default_factory=_empty_runner_cache_roots)
    recovery_scope: Literal["selective", "full_baseline"] = "selective"

    @field_validator("boundary_hash")
    @classmethod
    def boundary_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @field_validator("final_tree_sha")
    @classmethod
    def tree_is_git_oid(cls, value: str) -> str:
        return validate_git_oid(value)

    @field_validator("boundary_entries")
    @classmethod
    def canonical_boundary_entries(
        cls, value: list[RunnerBoundaryEntry]
    ) -> list[RunnerBoundaryEntry]:
        return _canonical_boundary_entries(value)

    @model_validator(mode="after")
    def boundary_matches_manifest(self) -> RequestRunnerRecoveryCommand:
        self.cache_status_evidence = list(
            canonicalize_cache_status_evidence(self.cache_status_evidence)
        )
        self.observed_cache_roots = _canonical_command_cache_roots(
            self.observed_cache_roots, self.cache_authority_hash
        )
        if self.boundary_hash != boundary_manifest_hash(
            self.final_tree_sha,
            self.boundary_entries,
            self.cache_status_evidence,
            self.cache_authority_hash,
        ):
            raise ValueError("boundary_hash does not match recovery manifest")
        ownership = (
            self.recovery_snapshot_id,
            self.recovery_snapshot_ref,
            self.recovery_commit_sha,
            self.final_tree_sha,
        )
        if any(value is None for value in ownership) and any(
            value is not None for value in ownership[:-1]
        ):
            raise ValueError(
                "recovery snapshot id, ref, commit, and tree must be supplied together"
            )
        if self.recovery_snapshot_id is not None:
            validate_snapshot_ref(self.recovery_snapshot_ref or "", self.recovery_snapshot_id)
            validate_git_oid(self.recovery_commit_sha or "")
        if self.recovery_scope == "full_baseline" and self.boundary_entries:
            raise ValueError("full-baseline recovery must not serialize boundary entries")
        return self


class CompleteRunnerRecoveryCommand(StrictCommandPayload):
    execution_id: CommandIdentifier
    recovery_id: CommandIdentifier
    node_id: CommandIdentifier
    lease_id: CommandIdentifier
    lease_generation: int = Field(ge=0)
    baseline_snapshot_id: CommandIdentifier
    baseline_tree_sha: CommandIdentifier
    requested_paths: list[str]
    proof_hash: CommandIdentifier
    restored_paths: list[str] = Field(default_factory=list)
    removed_paths: list[str] = Field(default_factory=list)
    recovery_scope: Literal["selective", "full_baseline"] = "selective"

    @field_validator("requested_paths", "restored_paths", "removed_paths")
    @classmethod
    def normalized_paths(cls, values: list[str]) -> list[str]:
        return [validate_repo_relative_path(value) for value in values]

    @field_validator("baseline_tree_sha")
    @classmethod
    def recovery_tree_is_git_oid(cls, value: str) -> str:
        return validate_git_oid(value)

    @field_validator("proof_hash")
    @classmethod
    def proof_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @model_validator(mode="after")
    def recovery_accounting_is_exact(self) -> CompleteRunnerRecoveryCommand:
        if self.recovery_scope == "full_baseline":
            if self.requested_paths or self.restored_paths or self.removed_paths:
                raise ValueError("full-baseline recovery has no path accounting")
            return self
        validate_recovery_paths(self.requested_paths, self.restored_paths, self.removed_paths)
        requested = tuple(self.requested_paths)
        restored = tuple(self.restored_paths)
        removed = tuple(self.removed_paths)
        if len(set(requested)) != len(requested):
            raise ValueError("requested_paths must not contain duplicates")
        if len(set(restored)) != len(restored) or len(set(removed)) != len(removed):
            raise ValueError("recovery accounting paths must not contain duplicates")
        if set(restored) & set(removed) or set(restored) | set(removed) != set(requested):
            raise ValueError(
                "restored and removed paths must be disjoint and exactly cover requested_paths"
            )
        return self


def _empty_patch_ops() -> list[dict[str, Any]]:
    return []


def _empty_macro_invocations() -> list[MacroInvocation]:
    return []


class PatchCommandFields(StrictCommandPayload):
    macro_invocations: list[MacroInvocation] = Field(default_factory=_empty_macro_invocations)
    rationale_record_id: CommandIdentifier | None = None
    budget_gate_node_id: CommandIdentifier | None = None
    carryover_record_id: CommandIdentifier | None = None


class SubmitPatchCommand(PatchCommandFields):
    patch_id: CommandIdentifier
    base_graph_position: int = Field(ge=-1)
    ops: list[dict[str, Any]] = Field(default_factory=_empty_patch_ops, max_length=200)


class AcknowledgeStartCommand(StrictCommandPayload):
    node_id: CommandIdentifier
    lease_id: CommandIdentifier
    lease_generation: int = Field(ge=0)
    execution_id: CommandIdentifier
    prompt_summary: dict[str, Any] | None = None


class AgentDiedCommand(StrictCommandPayload):
    lease_id: CommandIdentifier
    execution_id: CommandIdentifier | None = None
    reason: str = "runtime_process_died"
    max_attempts: int = Field(default=0, ge=0)
    retry_backoff_seconds: int = Field(default=0, ge=0)
    health_evidence_record_id: CommandIdentifier | None = None
    # Set by the driver when its per-node orphan-recovery budget
    # (MAX_NODE_RECOVERIES_PER_DRIVE) is exhausted: the caller is stating that
    # it will not attempt recovery for this node again, so the kernel must
    # conclude the lease terminally rather than scheduling another retry.
    recovery_exhausted: bool = False


class RaiseAppealCommand(StrictCommandPayload):
    node_id: CommandIdentifier
    appeal_type: Literal["invalid_test"]
    appeal_node_id: CommandIdentifier | None = None
    oversight_node_id: CommandIdentifier | None = None
    candidate_id: CommandIdentifier | None = None
    task_region_id: CommandIdentifier | None = None
    lease_id: CommandIdentifier | None = None


DECISION_VALUES = {
    "approval": frozenset({"approved", "rejected", "deferred"}),
    "authority": frozenset({"granted", "denied", "deferred"}),
    "oversight": frozenset({"accepted", "rejected", "invalid_test_accepted"}),
}


class RecordDecisionCommand(StrictCommandPayload):
    decision_type: Literal["approval", "authority", "oversight"]
    node_id: CommandIdentifier
    decision: str
    decider: Actor | ActorLabel
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: CommandIdentifier | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> RecordDecisionCommand:
        if self.decision not in DECISION_VALUES[self.decision_type]:
            options = ", ".join(sorted(DECISION_VALUES[self.decision_type]))
            raise ValueError(f"decision for {self.decision_type} must be one of: {options}")
        return self


GatekeeperClassification = Literal[
    "tool_cache",
    "build_output",
    "test_artifact",
    "secret",
    "external_artifact",
    "unknown_ignored",
]


class GatekeeperVerdictCommandRow(StrictCommandPayload):
    path: str
    classification: GatekeeperClassification
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    model_id: str | None = None
    gen_ai_usage_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_output_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_read_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_creation_input_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    wall_time_ms: int = Field(default=0, ge=0)


class GatekeeperCostCommandRow(StrictCommandPayload):
    model_id: str | None = None
    gen_ai_usage_input_tokens: int | None = Field(default=None, ge=0)
    gen_ai_usage_output_tokens: int | None = Field(default=None, ge=0)
    gen_ai_usage_cache_read_input_tokens: int | None = Field(default=None, ge=0)
    gen_ai_usage_cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    wall_time_ms: int | None = Field(default=None, ge=0)


class RecordGatekeeperVerdictsCommand(StrictCommandPayload):
    file_state_record_id: CommandIdentifier
    execution_id: CommandIdentifier
    verdicts: list[GatekeeperVerdictCommandRow] = Field(min_length=1)
    consult_id: CommandIdentifier = "gatekeeper-consult"
    model_id: str | None = None
    cost: GatekeeperCostCommandRow | None = None


class RecordRequirementRevisionCommand(StrictCommandPayload):
    requirement_id: CommandIdentifier
    version_id: CommandIdentifier
    classification: str | None = None
    requires_authority: bool | None = None
    validation_strengthening: bool | None = None
    active: bool = True
    previous_version_id: CommandIdentifier | None = None
    revision_index: int | None = Field(default=None, ge=0)
    authority_required_reason: str | None = None
    revision_id: CommandIdentifier | None = None
    proposal_id: CommandIdentifier | None = None
    patch_id: CommandIdentifier | None = None
    node_id: CommandIdentifier | None = None
    requirement: dict[str, Any] | None = None


class RecordSupportEvidenceCommand(StrictCommandPayload):
    support_id: CommandIdentifier
    evidence_id: CommandIdentifier
    requirement_id: CommandIdentifier
    requirement_version_id: CommandIdentifier | None = None
    status: str | None = None
    stale_reason: str | None = None
    confidence: str | None = None


class RecordNodeUsageCommand(StrictCommandPayload):
    node_id: CommandIdentifier
    node_kind: CommandIdentifier
    node_role: str | None = None
    profile: str | None = None
    execution_id: CommandIdentifier
    num_actions: int = Field(default=0, ge=0)
    usage: list[ModelTokenUsage] = Field(min_length=1)


class LeaseScopedEvaluationCommand(StrictCommandPayload):
    node_id: CommandIdentifier
    record_id: CommandIdentifier | None = None
    lease_id: CommandIdentifier | None = None
    lease_generation: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_lease_pair(self) -> LeaseScopedEvaluationCommand:
        if (self.lease_id is None) != (self.lease_generation is None):
            raise ValueError("lease_id and lease_generation must be provided together")
        return self


class EvaluateJoinCommand(LeaseScopedEvaluationCommand):
    pass


class EvaluateFinalGateCommand(LeaseScopedEvaluationCommand):
    pass


class StrictFileStateRecord(FileStateRecord):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecordCleanupAppliedCommand(StrictCommandPayload):
    cleanup_id: CommandIdentifier
    superseding_file_state_record: StrictFileStateRecord
    deleted_snapshot_ref: bool = False
    reason: str | None = None


class RecordManagedSnapshotCleanupAppliedCommand(StrictCommandPayload):
    cleanup_id: CommandIdentifier
    snapshot_id: CommandIdentifier
    snapshot_ref: CommandIdentifier
    tree_sha: CommandIdentifier
    commit_sha: CommandIdentifier
    node_id: CommandIdentifier
    lease_id: CommandIdentifier
    lease_generation: int = Field(ge=0)
    snapshot_role: Literal["baseline", "staged", "final", "recovery"]
    deleted_snapshot_ref: bool = False

    @model_validator(mode="after")
    def exact_ref_is_owned(self) -> "RecordManagedSnapshotCleanupAppliedCommand":
        validate_snapshot_ref(self.snapshot_ref, self.snapshot_id)
        validate_git_oid(self.tree_sha)
        validate_git_oid(self.commit_sha)
        return self


__all__ = [
    "AcceptRunCommand",
    "AcknowledgeStartCommand",
    "AgentDiedCommand",
    "ActorLabel",
    "ApplyCommandHandler",
    "CancelCommand",
    "CommandSpec",
    "CommandIdentifier",
    "CompleteCommand",
    "EvaluateFinalGateCommand",
    "EvaluateJoinCommand",
    "FailCommand",
    "GatekeeperCostCommandRow",
    "GatekeeperVerdictCommandRow",
    "GraphCommandContext",
    "PatchCommandContext",
    "PauseCommand",
    "RaiseAppealCommand",
    "ReconcileCommand",
    "RecordCleanupAppliedCommand",
    "RecordManagedSnapshotCleanupAppliedCommand",
    "RecordRunnerBaselineCommand",
    "RecordDecisionCommand",
    "RecordGatekeeperVerdictsCommand",
    "RecordHeartbeatCommand",
    "RecordNodeUsageCommand",
    "RecordRequirementRevisionCommand",
    "RecordSupportEvidenceCommand",
    "ResumeCommand",
    "ScheduleTickCommand",
    "SeedCompiledEventsCommand",
    "StartCommand",
    "StrictCommandPayload",
    "SubmitCallbackCommand",
    "StageRunnerSubmissionCommand",
    "FinalizeRunnerExecutionCommand",
    "CompleteRunnerRecoveryCommand",
    "SubmitPatchCommand",
    "TriggerCommand",
]
