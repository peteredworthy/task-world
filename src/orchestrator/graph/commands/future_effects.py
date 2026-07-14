"""Fail-closed Task 3/4/6 event compatibility boundary."""

from orchestrator.graph.specifications import HydratedEvent

FUTURE_EFFECT_EVENT_NAMES = frozenset(
    {
        "appeal_opened",
        "approval_decision_recorded",
        "authority_decision_recorded",
        "cleanup_applied",
        "cleanup_requested",
        "dead_input_detected",
        "edge_created",
        "file_state_accepted",
        "file_state_rejected",
        "gatekeeper_cost_recorded",
        "gatekeeper_verdict_recorded",
        "graph_patch_accepted",
        "graph_patch_rejected",
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
        "requirement_revision_recorded",
        "revision_created",
        "session_state_changed",
        "support_evidence_recorded",
        "verification_failed",
        "verification_passed",
    }
)


def require_future_effect(event: HydratedEvent) -> HydratedEvent:
    if event.event_type not in FUTURE_EFFECT_EVENT_NAMES:
        raise ValueError(f"legacy future-effect adapter rejected event type {event.event_type!r}")
    return event


__all__ = ["FUTURE_EFFECT_EVENT_NAMES", "require_future_effect"]
