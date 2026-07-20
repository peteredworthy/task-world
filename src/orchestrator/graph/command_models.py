"""Strict command payloads and explicit graph command context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from orchestrator.graph.macros import MacroInvocation
from orchestrator.graph.models import Actor, EventEnvelope, FileStateRecord
from orchestrator.graph.projections import GraphProjection


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
    ops: list[dict[str, Any]] = Field(default_factory=_empty_patch_ops)


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
    cache_write_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    wall_time_ms: int = Field(default=0, ge=0)


class GatekeeperCostCommandRow(StrictCommandPayload):
    model_id: str | None = None
    gen_ai_usage_input_tokens: int | None = Field(default=None, ge=0)
    gen_ai_usage_output_tokens: int | None = Field(default=None, ge=0)
    gen_ai_usage_cache_read_input_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
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
    "RecordDecisionCommand",
    "RecordGatekeeperVerdictsCommand",
    "RecordHeartbeatCommand",
    "RecordRequirementRevisionCommand",
    "RecordSupportEvidenceCommand",
    "ResumeCommand",
    "ScheduleTickCommand",
    "SeedCompiledEventsCommand",
    "StartCommand",
    "StrictCommandPayload",
    "SubmitCallbackCommand",
    "SubmitPatchCommand",
    "TriggerCommand",
]
