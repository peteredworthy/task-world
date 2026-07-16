"""Declarative payload retention for compact graph-event reads."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, get_args, get_origin

from pydantic import BaseModel

from orchestrator.graph.event_registry import EVENT_PAYLOAD_MODELS

RetentionMode = Literal["projection", "light", "summary", "node_detail"]


def _field_names(source: str) -> frozenset[str]:
    return frozenset(source.split())


# These mode policies preserve the current compact readers. Fields no longer
# serialized by any canonical payload model are intentionally not retained.
# W5.5 debt: retaining complete ``value`` keeps SQL mode-based and preserves
# parity, but does not solve large nested-value read amplification.
_PROJECTION_FIELDS = _field_names(
    """
    accepted_record_selector allowed_actions approval_prompt approval_type appeal_type
    attempt_number approved authority authority_request authority_request_record
    authority_request_record_id base_snapshot_id binding_policy blocker blocker_reason
    bound_at_position candidate_id carryover_record_id classification command_binding
    command_definition command_definition_id decision decision_request
    decision_request_record_id dependency_type edge_id evidence execution_id expires_at
    failed_candidate_id file_state_record_id freshness_policy from_node_id from_node_kind
    from_node_role from_port from_state gate_id gate_type generation generation_index
    guarded_planner_node_id hidden_oracle_command human_prompt id inputs kind lease_id
    membership message metadata new_state node_id outcome outputs planner_chain
    planner_generation_budget port preconditions priority producer_node_id prompt
    prompt_hydration_policy reason record_bound_positions record_id record_ids record_kind
    record_type recovery_of_node_id recovery_of_record_id recovery_reason region_label
    rejected_patch_id requirement requirement_id required resolved_count resource_claims
    retry_not_before role schema session_id snapshot_id state status supersedes_record_id
    supersedes_task_region_id supersedes_task_region_ids task_region_id to_node_id to_port
    to_state trigger value verdict verdicts verifier_node_id
    """
)
_LIGHT_FIELDS = _field_names(
    """
    accepted_record_selector active allowed_actions appeal_node_id appeal_type
    appealed_node_id approval_prompt approval_type attempt_number approved authority
    authority_request authority_request_record authority_request_record_id
    authority_required_reason base_snapshot_id behavior_change binding_policy blocker
    blocker_reason bound_at_position cache_read_tokens cache_write_tokens candidate_id
    candidate_record_id candidate_record_ids change_classification classification cleanup_id
    command_binding command_definition command_definition_id confidence consult_id cost_usd
    decision decision_request decision_request_record_id deleted_snapshot_ref dependency_type
    edge_id evaluated_record_ids evidence_id execution_id expires_at
    explicit_authority_required failed_candidate_id file_state_record_id
    file_state_record_ids freshness_policy from_node_id from_node_kind from_node_role
    from_port from_state gate_id gate_type generation generation_index
    guarded_planner_node_id hidden_oracle_command human_prompt id input input_tokens inputs
    item_count kind lease_generation lease_id membership message metadata model_id
    new_behavior new_state node_id operation outcome output_tokens outputs patch_id path
    planner_chain planner_generation_budget port preconditions previous_version_id priority
    producer_node_id prompt prompt_hydration_policy proposal_id proposed_by_node_id reason
    record_bound_positions record_id record_ids record_kind record_type recovery_of_node_id
    recovery_of_record_id recovery_reason region_id region_label rejected_patch_id
    rejected_patches requirement requirement_id requirement_version_id required
    requires_authority resolved_count resource_claims retry_not_before revision_id
    revision_index revision_type role schema semantic_change session_id stale_only
    stale_reason state status successor_planner_node_ids supersedes_record_id
    supersedes_task_region_id supersedes_task_region_ids superseding_record_id support_id
    supported task_region_id to_node_id to_port to_state trigger unsupported
    validation_strengthening verdict verdicts version_id wall_time_ms worker_node verifier_node
    """
)
_SUMMARY_FIELDS = _field_names(
    """
    accepted_patches accepted_record_selector active actor_role allowed_actions appeal_node_id
    appeal_type appealed_node_id approval_prompt approval_type attempt_number approved authority
    authority_request authority_request_record authority_request_record_id
    authority_required_reason base_snapshot_id behavior_change binding_policy blocker blockers
    blocker_reason bound_at_position cache_read_tokens cache_write_tokens candidate_id
    candidate_record_id candidate_record_ids change_classification classification cleanup_id
    command_binding command_definition command_definition_id command_type confidence consult_id
    cost_usd decider decision decision_request decision_request_record_id decision_type
    deleted_snapshot_ref dependency_type edge_id evaluated_record_ids evidence evidence_id
    execution_id expires_at explicit_authority_required failed_candidate_id
    file_state_record_id file_state_record_ids freshness_policy from_node_id from_node_kind
    from_node_role from_port from_state gate_id gate_type generation generation_index grade
    grades graph_verifier_grades guarded_planner_node_id hidden_oracle_command human_prompt id
    idempotency_key input input_tokens inputs item_count kind lease_generation lease_id
    membership message metadata model_id new_behavior new_state node node_id node_kind operation
    operations ops outcome output_tokens outputs patch_id patch_ops patch_rejection_reasons path
    payload planner_chain planner_generation_budget port preconditions previous_version_id
    priority producer_node_id prompt prompt_hydration_policy proposal_id proposed_by_node_id
    provenance reason record_bound_positions record_id record_ids record_kind record_type
    recovery_of_node_id recovery_of_record_id recovery_reason region_id region_label
    rejected_patch_id rejected_patches rejection_reason requirement requirement_id
    requirement_version_id required requires_authority resolved_count resource_claims
    retry_not_before revision_id revision_index revision_type role run_id schema semantic_change
    session_id snapshot_id stale_only stale_reason state status successor_planner_node_ids
    supersedes_record_id supersedes_task_region_id supersedes_task_region_ids
    superseding_record_id support_id supported task_region_id to_node_id to_port to_state tokens
    tokens_by_node tokens_by_node_kind trigger unsupported validation_strengthening value verdict
    verdicts verifier_node_id version_id wall_time_ms worker_node verifier_node
    """
)
_NODE_DETAIL_FIELDS = _field_names(
    """
    accepted_record_selector allowed_actions approval_prompt approval_type attempt_number
    authority authority_request authority_request_record authority_request_record_id
    base_snapshot_id binding_policy blocker blocker_reason candidate_id candidate_record_id
    candidate_record_ids classifications command_binding command_definition
    command_definition_id decision_request decision_request_record_id diff_summary edge_id
    evaluated_record_ids execution_id expires_at failed_candidate_id file_state_record_ids
    from_node_id from_node_kind from_node_role from_port gate_type generation generation_index
    guarded_planner_node_id hidden_oracle_command human_prompt id input inputs kind
    lease_generation lease_id membership message new_state node_id outcome outputs
    patch_bundle_id planner_chain planner_generation_budget port preconditions priority
    producer_node_id prompt prompt_summary reason record_id record_ids record_kind
    recovery_of_node_id recovery_of_record_id recovery_reason region_label rejected_patch_id
    requirement requirement_id resource_claims retry_not_before role schema session_id state
    supersedes_record_id task_region_id to_node_id to_port trigger verdict
    """
)


def payload_model_fields(model: type[BaseModel]) -> frozenset[str]:
    """Return every top-level key a payload model can serialize."""
    fields = {
        field.serialization_alias or name
        for name, field in model.model_fields.items()
        if name != "root"
    }
    root = model.model_fields.get("root")
    if root is not None:
        fields.update(_annotation_model_fields(root.annotation))
    return frozenset(fields)


def _annotation_model_fields(annotation: object) -> set[str]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return set(payload_model_fields(annotation))
    fields: set[str] = set()
    if get_origin(annotation) is not None:
        for argument in get_args(annotation):
            fields.update(_annotation_model_fields(argument))
    return fields


@dataclass(frozen=True)
class EventPayloadSpec:
    model: type[BaseModel]
    projection: frozenset[str] = frozenset()
    light: frozenset[str] = frozenset()
    summary: frozenset[str] = frozenset()
    node_detail: frozenset[str] = frozenset()
    envelope_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        serialized_fields = payload_model_fields(self.model) | self.envelope_fields
        for mode in ("projection", "light", "summary", "node_detail"):
            unknown = getattr(self, mode) - serialized_fields
            if unknown:
                names = ", ".join(sorted(unknown))
                raise ValueError(f"{self.model.__name__} {mode} fields are not serialized: {names}")


def _payload_spec(model: type[BaseModel]) -> EventPayloadSpec:
    serialized_fields = payload_model_fields(model)
    return EventPayloadSpec(
        model=model,
        projection=_PROJECTION_FIELDS & serialized_fields,
        light=_LIGHT_FIELDS & serialized_fields,
        summary=_SUMMARY_FIELDS & serialized_fields,
        node_detail=_NODE_DETAIL_FIELDS & serialized_fields,
    )


EVENT_PAYLOAD_SPECS: MappingProxyType[str, EventPayloadSpec] = MappingProxyType(
    {event_type: _payload_spec(model) for event_type, model in EVENT_PAYLOAD_MODELS.items()}
)


def generated_payload_fields(mode: RetentionMode) -> tuple[str, ...]:
    fields: set[str] = set()
    for spec in EVENT_PAYLOAD_SPECS.values():
        fields.update(getattr(spec, mode))
    return tuple(sorted(fields))


GRAPH_PROJECTION_PAYLOAD_FIELDS = generated_payload_fields("projection")
LIGHT_GRAPH_PAYLOAD_FIELDS = generated_payload_fields("light")
SUMMARY_REBUILD_PAYLOAD_FIELDS = generated_payload_fields("summary")
NODE_DETAIL_PAYLOAD_FIELDS = generated_payload_fields("node_detail")
