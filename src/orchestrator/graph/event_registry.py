"""Canonical ownership for graph event names."""

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from pydantic import BaseModel

from orchestrator.graph.models import (
    AgentDispatchRequestedPayload,
    AgentDiedPayload,
    AppealOpenedPayload,
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    CallbackAcceptedPayload,
    CallbackDuplicateReturnedPayload,
    CallbackRejectedPayload,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    CommandRecordedPayload,
    CommandRejectedPayload,
    DeadInputDetectedPayload,
    EdgeProjection,
    FileStateAcceptedPayload,
    FileStateRejectedPayload,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdictRecordedPayload,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
    HeartbeatRecordedPayload,
    InputBoundPayload,
    LeaseExpiredPayload,
    LeaseGrantedPayload,
    LeaseReleasedPayload,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
    LeaseSuspendedPayload,
    NodeAuthorityChangedPayload,
    NodeCreatedPayload,
    NodeDeferredPayload,
    NodeReadyPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
    NodeUsageRecordedPayload,
    NodeSuspectPayload,
    OutputRecordAcceptedPayload,
    OversightDecisionRecordedPayload,
    PlannerSessionStateChangedPayload,
    RequirementRevisionPayload,
    RevisionCreatedPayload,
    RunLifecycleChangedPayload,
    RuntimeRetryScheduledPayload,
    SupportEvidencePayload,
    VerificationFailedPayload,
    VerificationPassedPayload,
)


RETIRED_EVENT_TYPES = frozenset(
    {"region_marked_suspect", "authority_narrowed", "candidate_superseded"}
)


# Immutable producer metadata is the sole internal-name declaration. Every
# producer boundary validates emitted names against it, and canonical ownership
# is derived from its values.
INTERNAL_EVENT_TYPES_BY_PRODUCER: MappingProxyType[str, frozenset[str]] = MappingProxyType(
    {
        "graph_command_factory": frozenset(
            {
                "agent_died",
                "appeal_opened",
                "approval_decision_recorded",
                "authority_decision_recorded",
                "callback_accepted",
                "callback_duplicate_returned",
                "callback_rejected_conflict",
                "callback_rejected_stale",
                "cleanup_applied",
                "cleanup_requested",
                "command_rejected",
                "dead_input_detected",
                "edge_created",
                "file_state_accepted",
                "file_state_rejected",
                "gatekeeper_cost_recorded",
                "gatekeeper_verdict_recorded",
                "graph_patch_accepted",
                "graph_patch_rejected",
                "heartbeat_recorded",
                "input_bound",
                "lease_expired",
                "lease_granted",
                "lease_released",
                "lease_renewed",
                "lease_revoked",
                "node_authority_changed",
                "node_created",
                "node_deferred",
                "node_ready",
                "node_retired",
                "node_state_changed",
                "node_usage_recorded",
                "output_record_accepted",
                "oversight_decision_recorded",
                "plan_region_marked_suspect",
                "requirement_revision_recorded",
                "revision_created",
                "run_lifecycle_changed",
                "runtime_retry_scheduled",
                "session_state_changed",
                "support_evidence_recorded",
                "verification_failed",
                "verification_passed",
            }
        ),
        "graph_runtime_controller": frozenset({"agent_dispatch_requested"}),
        "graph_scenario_harness": frozenset({"command_recorded"}),
    }
)

# Stale callbacks can still surface this event even though no current command
# producer emits it.
EXTERNAL_EVENT_TYPES = frozenset({"lease_suspended"})

EVENT_PAYLOAD_MODELS: MappingProxyType[str, type[BaseModel]] = MappingProxyType(
    {
        "agent_dispatch_requested": AgentDispatchRequestedPayload,
        "agent_died": AgentDiedPayload,
        "appeal_opened": AppealOpenedPayload,
        "approval_decision_recorded": ApprovalDecisionRecordedPayload,
        "authority_decision_recorded": AuthorityDecisionRecordedPayload,
        "callback_accepted": CallbackAcceptedPayload,
        "callback_duplicate_returned": CallbackDuplicateReturnedPayload,
        "callback_rejected_conflict": CallbackRejectedPayload,
        "callback_rejected_stale": CallbackRejectedPayload,
        "cleanup_applied": CleanupAppliedPayload,
        "cleanup_requested": CleanupRequestedPayload,
        "command_recorded": CommandRecordedPayload,
        "command_rejected": CommandRejectedPayload,
        "dead_input_detected": DeadInputDetectedPayload,
        "edge_created": EdgeProjection,
        "file_state_accepted": FileStateAcceptedPayload,
        "file_state_rejected": FileStateRejectedPayload,
        "gatekeeper_cost_recorded": GatekeeperCostRecordedPayload,
        "gatekeeper_verdict_recorded": GatekeeperVerdictRecordedPayload,
        "graph_patch_accepted": GraphPatchAcceptedPayload,
        "graph_patch_rejected": GraphPatchRejectedPayload,
        "heartbeat_recorded": HeartbeatRecordedPayload,
        "input_bound": InputBoundPayload,
        "lease_expired": LeaseExpiredPayload,
        "lease_granted": LeaseGrantedPayload,
        "lease_released": LeaseReleasedPayload,
        "lease_renewed": LeaseRenewedPayload,
        "lease_revoked": LeaseRevokedPayload,
        "lease_suspended": LeaseSuspendedPayload,
        "node_authority_changed": NodeAuthorityChangedPayload,
        "node_created": NodeCreatedPayload,
        "node_deferred": NodeDeferredPayload,
        "node_ready": NodeReadyPayload,
        "node_retired": NodeRetiredPayload,
        "node_state_changed": NodeStateChangedPayload,
        "node_usage_recorded": NodeUsageRecordedPayload,
        "output_record_accepted": OutputRecordAcceptedPayload,
        "oversight_decision_recorded": OversightDecisionRecordedPayload,
        "plan_region_marked_suspect": NodeSuspectPayload,
        "requirement_revision_recorded": RequirementRevisionPayload,
        "revision_created": RevisionCreatedPayload,
        "run_lifecycle_changed": RunLifecycleChangedPayload,
        "runtime_retry_scheduled": RuntimeRetryScheduledPayload,
        "session_state_changed": PlannerSessionStateChangedPayload,
        "support_evidence_recorded": SupportEvidencePayload,
        "verification_passed": VerificationPassedPayload,
        "verification_failed": VerificationFailedPayload,
    }
)


def _event_type_union(event_type_sets: Iterable[frozenset[str]]) -> frozenset[str]:
    event_types: set[str] = set()
    for event_type_set in event_type_sets:
        event_types.update(event_type_set)
    return frozenset(event_types)


def internal_event_types(
    event_types_by_producer: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    """Return the immutable union of current internal producer declarations."""
    return _event_type_union(event_types_by_producer.values())


PRODUCED_EVENT_TYPES = internal_event_types(INTERNAL_EVENT_TYPES_BY_PRODUCER)


def canonical_event_types(produced_event_types: frozenset[str]) -> frozenset[str]:
    """Return event names owned by current producers or external ingress."""
    return produced_event_types | EXTERNAL_EVENT_TYPES


CANONICAL_EVENT_TYPES = canonical_event_types(PRODUCED_EVENT_TYPES)


def validate_event_ownership(
    event_types_by_producer: Mapping[str, frozenset[str]],
    canonical_event_types: frozenset[str],
) -> None:
    """Reject producer declarations that omit or retain canonical internal names."""
    declared = _event_type_union(event_types_by_producer.values())
    canonical_internal = canonical_event_types - EXTERNAL_EVENT_TYPES
    retired_overlap = RETIRED_EVENT_TYPES & (declared | canonical_event_types)
    if retired_overlap:
        retired_names = ", ".join(sorted(retired_overlap))
        raise ValueError(f"retired event types cannot be owned: {retired_names}")
    if declared != canonical_internal:
        mismatch = sorted(declared ^ canonical_internal)
        raise ValueError(f"producer ownership mismatch: {', '.join(mismatch)}")


def validate_emitted_event_type(producer: str, event_type: str) -> None:
    """Reject an event emitted by the current producer boundary without ownership."""
    registered_event_types = INTERNAL_EVENT_TYPES_BY_PRODUCER.get(producer, frozenset())
    if event_type not in registered_event_types:
        raise ValueError(f"unregistered event type for {producer}: {event_type}")


validate_event_ownership(INTERNAL_EVENT_TYPES_BY_PRODUCER, CANONICAL_EVENT_TYPES)

if frozenset(EVENT_PAYLOAD_MODELS) != CANONICAL_EVENT_TYPES:
    mismatch = ", ".join(sorted(frozenset(EVENT_PAYLOAD_MODELS) ^ CANONICAL_EVENT_TYPES))
    raise ValueError(f"canonical event payload model coverage mismatch: {mismatch}")
