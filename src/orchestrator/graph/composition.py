"""Composition-owned dependencies for graph command execution."""

from dataclasses import dataclass

from orchestrator.graph._commands import (
    accepted_output_record_events,
    cancel_active_lease_events,
    failure_record_payload,
    file_state_authority_conflict,
    file_state_rejected_conflict,
    file_state_rejected_events,
    lease_node_id,
    lifecycle_completion_decision_event,
    output_record_contract_conflict,
    output_record_provenance_conflict,
    planner_session_state_event,
    recovery_plan_record_payload,
    required_output_record_conflict,
    source_repair_events,
    typed_lease_event_payload,
    verification_record_conflict,
)
from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.specifications import FutureCommandEffects


@dataclass(frozen=True)
class GraphCommandDependencies:
    """The immutable dependency bundle consumed by graph command runtimes."""

    catalog: GraphCatalog
    future_effects: FutureCommandEffects


def build_graph_command_dependencies(
    catalog: GraphCatalog,
) -> GraphCommandDependencies:
    """Compose the production graph kernel at the graph module boundary."""

    return GraphCommandDependencies(
        catalog=catalog,
        future_effects=FutureCommandEffects(
            accepted_output_record_events=accepted_output_record_events,
            file_state_authority_conflict=file_state_authority_conflict,
            file_state_rejected_conflict=file_state_rejected_conflict,
            file_state_rejected_events=file_state_rejected_events,
            lease_node_id=lease_node_id,
            output_record_contract_conflict=output_record_contract_conflict,
            output_record_provenance_conflict=output_record_provenance_conflict,
            planner_session_state_event=planner_session_state_event,
            required_output_record_conflict=required_output_record_conflict,
            source_repair_events=source_repair_events,
            typed_lease_event_payload=typed_lease_event_payload,
            verification_record_conflict=verification_record_conflict,
            cancel_active_lease_events=cancel_active_lease_events,
            lifecycle_completion_decision_event=lifecycle_completion_decision_event,
            failure_record_payload=failure_record_payload,
            recovery_plan_record_payload=recovery_plan_record_payload,
        ),
    )


__all__ = ["GraphCommandDependencies", "build_graph_command_dependencies"]
