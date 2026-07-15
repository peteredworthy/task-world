"""Canonical ownership for graph event names."""

from types import MappingProxyType

from pydantic import BaseModel


# This is the single registry of event names emitted by graph command and runtime
# producers. Canonical ownership is derived from it rather than duplicating the
# names in a consumer-side allowlist.
PRODUCED_EVENT_TYPES = frozenset(
    {
        "agent_died",
        "agent_dispatch_requested",
        "appeal_opened",
        "approval_decision_recorded",
        "authority_decision_recorded",
        "callback_accepted",
        "callback_duplicate_returned",
        "callback_rejected_conflict",
        "callback_rejected_stale",
        "cleanup_applied",
        "cleanup_requested",
        "command_recorded",
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
        "output_record_accepted",
        "oversight_decision_recorded",
        "plan_region_marked_suspect",
        "region_marked_suspect",
        "requirement_revision_recorded",
        "revision_created",
        "run_lifecycle_changed",
        "runtime_retry_scheduled",
        "session_state_changed",
        "support_evidence_recorded",
        "verification_failed",
        "verification_passed",
    }
)

# Stale callbacks can still surface this event even though no current command
# producer emits it.
EXTERNAL_EVENT_TYPES = frozenset({"lease_suspended"})

EVENT_PAYLOAD_MODELS: MappingProxyType[str, type[BaseModel]] = MappingProxyType({})


def canonical_event_types(produced_event_types: frozenset[str]) -> frozenset[str]:
    """Return event names owned by current producers or external ingress."""
    return produced_event_types | EXTERNAL_EVENT_TYPES


CANONICAL_EVENT_TYPES = canonical_event_types(PRODUCED_EVENT_TYPES)
