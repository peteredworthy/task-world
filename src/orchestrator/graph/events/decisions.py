"""Strict appeal and decision event specifications and reducers."""

from typing import Any, Literal

from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


class AppealOpenedPayload(StrictPayload):
    node_id: str
    appealed_node_id: str
    appeal_type: Literal["invalid_test"]
    candidate_id: str | None = None
    task_region_id: str | None = None
    lease_id: str | None = None


class ApprovalDecisionRecordedPayload(StrictPayload):
    node_id: str
    decision: Literal["approved", "rejected", "deferred"]
    decider: JsonValue
    task_region_id: str | None = None
    gate_id: str | None = None
    appeal_node_id: str | None = None
    scope: dict[str, JsonValue] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None


class AuthorityDecisionRecordedPayload(StrictPayload):
    node_id: str
    decision: Literal["granted", "denied", "deferred"]
    decider: JsonValue
    task_region_id: str | None = None
    appeal_node_id: str | None = None
    scope: dict[str, JsonValue] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None


class OversightDecisionRecordedPayload(StrictPayload):
    node_id: str
    decision: Literal["accepted", "rejected", "invalid_test_accepted"]
    decider: JsonValue
    appealed_node_id: str | None = None
    appeal_node_id: str | None = None
    task_region_id: str | None = None
    candidate_id: str | None = None
    appeal_type: Literal["invalid_test"] | None = None
    scope: dict[str, JsonValue] | None = None
    reason: str | None = None
    record_id: str | None = None


def reduce_appeal_opened(state: Any, payload: AppealOpenedPayload, metadata: EventMetadata) -> Any:
    from orchestrator.graph.projections import (
        derive_task_states,
        record_open_appeal,
        copy_projection,
    )

    next_state = copy_projection(state)
    record_open_appeal(next_state, payload, metadata.position)
    next_state["task_states"] = derive_task_states(next_state)
    return next_state


def reduce_approval_decision(
    state: Any, payload: ApprovalDecisionRecordedPayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import (
        derive_task_states,
        record_gate_decision,
        record_latest_approval_decision,
        copy_projection,
    )

    del metadata
    next_state = copy_projection(state)
    record_latest_approval_decision(next_state["approval_decisions"], payload)
    record_gate_decision(next_state, payload)
    next_state["task_states"] = derive_task_states(next_state)
    return next_state


def reduce_authority_decision(
    state: Any, payload: AuthorityDecisionRecordedPayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import (
        derive_task_states,
        record_authority_decision,
        record_latest_authority_decision,
        copy_projection,
    )

    del metadata
    next_state = copy_projection(state)
    record_latest_authority_decision(next_state["authority_decisions"], payload)
    record_authority_decision(next_state, payload)
    next_state["task_states"] = derive_task_states(next_state)
    return next_state


def reduce_oversight_decision(
    state: Any, payload: OversightDecisionRecordedPayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import (
        derive_task_states,
        record_latest_decision,
        record_oversight_decision,
        copy_projection,
    )

    next_state = copy_projection(state)
    record_latest_decision(next_state["oversight_decisions"], payload, metadata.position)
    record_oversight_decision(next_state, payload, metadata.position)
    next_state["task_states"] = derive_task_states(next_state)
    return next_state


APPEAL_OPENED = EventSpecification(
    "appeal_opened", AppealOpenedPayload, reduce_appeal_opened, ProjectionParticipation.MUTATES
)
APPROVAL_DECISION_RECORDED = EventSpecification(
    "approval_decision_recorded",
    ApprovalDecisionRecordedPayload,
    reduce_approval_decision,
    ProjectionParticipation.MUTATES,
)
AUTHORITY_DECISION_RECORDED = EventSpecification(
    "authority_decision_recorded",
    AuthorityDecisionRecordedPayload,
    reduce_authority_decision,
    ProjectionParticipation.MUTATES,
)
OVERSIGHT_DECISION_RECORDED = EventSpecification(
    "oversight_decision_recorded",
    OversightDecisionRecordedPayload,
    reduce_oversight_decision,
    ProjectionParticipation.MUTATES,
)
EVENT_SPECIFICATIONS = (
    APPEAL_OPENED,
    APPROVAL_DECISION_RECORDED,
    AUTHORITY_DECISION_RECORDED,
    OVERSIGHT_DECISION_RECORDED,
)
