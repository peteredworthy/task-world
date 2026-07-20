"""Declarative payload retention for compact graph-event reads."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, get_args, get_origin

from pydantic import BaseModel

from orchestrator.graph.event_registry import EVENT_PAYLOAD_MODELS

RetentionMode = Literal["projection", "light", "summary", "node_detail"]
_KNOWN_ENVELOPE_FIELDS = frozenset[str]()


def _fields(source: str) -> frozenset[str]:
    return frozenset(source.split())


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
        unknown_envelope_fields = self.envelope_fields - _KNOWN_ENVELOPE_FIELDS
        if unknown_envelope_fields:
            names = ", ".join(sorted(unknown_envelope_fields))
            raise ValueError(f"unknown envelope fields: {names}")
        serialized_fields = payload_model_fields(self.model) | self.envelope_fields
        for mode in ("projection", "light", "summary", "node_detail"):
            unknown = getattr(self, mode) - serialized_fields
            if unknown:
                names = ", ".join(sorted(unknown))
                raise ValueError(f"{self.model.__name__} {mode} fields are not serialized: {names}")


def _spec(
    event_type: str,
    *,
    projection: str,
    light: str,
    summary: str,
    node_detail: str,
) -> EventPayloadSpec:
    return EventPayloadSpec(
        model=EVENT_PAYLOAD_MODELS[event_type],
        projection=_fields(projection),
        light=_fields(light),
        summary=_fields(summary),
        node_detail=_fields(node_detail),
    )


def _same(event_type: str, fields: str) -> EventPayloadSpec:
    retained = _fields(fields)
    return EventPayloadSpec(
        model=EVENT_PAYLOAD_MODELS[event_type],
        projection=retained,
        light=retained,
        summary=retained,
        node_detail=retained,
    )


# Every modeled event deliberately owns its four retention sets. W5.5 debt:
# complete ``value`` retention preserves parity but does not solve large nested-
# value read amplification; SQL remains mode-based until the artifact cutover.
EVENT_PAYLOAD_SPECS: MappingProxyType[str, EventPayloadSpec] = MappingProxyType(
    {
        "agent_dispatch_requested": _same(
            "agent_dispatch_requested",
            "base_snapshot_id execution_id generation lease_granted_event_id lease_id node_id resource_claims",
        ),
        "agent_died": _same("agent_died", "execution_id generation lease_id node_id reason"),
        "appeal_opened": _spec(
            "appeal_opened",
            projection="appeal_type appealed_node_id candidate_id kind lease_id membership node_id state task_region_id",
            light="appeal_type appealed_node_id candidate_id kind lease_id membership node_id state task_region_id",
            summary="appeal_type appealed_node_id candidate_id kind lease_id membership node_id run_id state task_region_id",
            node_detail="appeal_type appealed_node_id candidate_id kind lease_id membership node_id state task_region_id",
        ),
        "approval_decision_recorded": _spec(
            "approval_decision_recorded",
            projection="appeal_type candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id task_region_id",
            light="appeal_node_id appeal_type appealed_node_id candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id task_region_id",
            summary="appeal_node_id appeal_type appealed_node_id candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id run_id task_region_id",
            node_detail="candidate_id decider decision decision_type expires_at membership node_id reason record_id task_region_id",
        ),
        "authority_decision_recorded": _spec(
            "authority_decision_recorded",
            projection="appeal_type candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id task_region_id",
            light="appeal_node_id appeal_type appealed_node_id candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id task_region_id",
            summary="appeal_node_id appeal_type appealed_node_id candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id run_id task_region_id",
            node_detail="candidate_id decider decision decision_type expires_at membership node_id reason record_id task_region_id",
        ),
        "callback_accepted": _spec(
            "callback_accepted",
            projection="execution_id lease_id node_id reason",
            light="execution_id lease_generation lease_id node_id reason",
            summary="execution_id idempotency_key lease_generation lease_id node_id payload reason",
            node_detail="execution_id lease_generation lease_id node_id reason",
        ),
        "callback_duplicate_returned": _spec(
            "callback_duplicate_returned",
            projection="execution_id lease_id node_id reason",
            light="execution_id lease_generation lease_id node_id reason",
            summary="execution_id idempotency_key lease_generation lease_id node_id payload reason",
            node_detail="execution_id lease_generation lease_id node_id reason",
        ),
        "callback_rejected_conflict": _spec(
            "callback_rejected_conflict",
            projection="execution_id lease_id node_id reason",
            light="execution_id lease_generation lease_id node_id reason",
            summary="execution_id idempotency_key lease_generation lease_id node_id payload reason",
            node_detail="execution_id lease_generation lease_id node_id reason",
        ),
        "callback_rejected_stale": _spec(
            "callback_rejected_stale",
            projection="execution_id lease_id node_id reason",
            light="execution_id lease_generation lease_id node_id reason",
            summary="execution_id idempotency_key lease_generation lease_id node_id payload reason",
            node_detail="execution_id lease_generation lease_id node_id reason",
        ),
        "cleanup_applied": _spec(
            "cleanup_applied",
            projection="authority execution_id file_state_record_id reason",
            light="authority cleanup_id deleted_snapshot_ref execution_id file_state_record_id reason superseding_record_id",
            summary="authority cleanup_id deleted_snapshot_ref execution_id file_state_record_id reason superseding_record_id",
            node_detail="authority execution_id reason",
        ),
        "cleanup_requested": _spec(
            "cleanup_requested",
            projection="authority execution_id file_state_record_id producer_node_id reason snapshot_id",
            light="authority cleanup_id execution_id file_state_record_id producer_node_id reason",
            summary="authority cleanup_id execution_id file_state_record_id producer_node_id reason snapshot_id",
            node_detail="authority execution_id producer_node_id reason",
        ),
        "command_recorded": _same("command_recorded", "command_payload command_type"),
        "command_rejected": _spec(
            "command_rejected",
            projection="reason",
            light="patch_id proposed_by_node_id reason",
            summary="actor_role blockers command_type patch_id proposed_by_node_id reason rejection_reason",
            node_detail="reason",
        ),
        "dead_input_detected": _same(
            "dead_input_detected",
            "from_node_id node_id reason to_port",
        ),
        "edge_created": _spec(
            "edge_created",
            projection="accepted_record_selector binding_policy dependency_type edge_id freshness_policy from_node_id from_node_kind from_node_role from_port metadata prompt_hydration_policy required to_node_id to_port",
            light="accepted_record_selector binding_policy dependency_type edge_id freshness_policy from_node_id from_node_kind from_node_role from_port metadata prompt_hydration_policy required to_node_id to_port",
            summary="accepted_record_selector binding_policy dependency_type edge_id freshness_policy from_node_id from_node_kind from_node_role from_port metadata prompt_hydration_policy required to_node_id to_port",
            node_detail="accepted_record_selector binding_policy edge_id from_node_id from_node_kind from_node_role from_port to_node_id to_port",
        ),
        "file_state_accepted": _spec(
            "file_state_accepted",
            projection="base_snapshot_id candidate_id port producer_node_id record_id record_kind record_type schema snapshot_id supersedes_record_id task_region_id verdict",
            light="base_snapshot_id candidate_id cleanup_id port producer_node_id record_id record_kind record_type schema supersedes_record_id task_region_id verdict",
            summary="base_snapshot_id candidate_id cleanup_id payload port producer_node_id provenance record_id record_kind record_type run_id schema snapshot_id supersedes_record_id task_region_id verdict",
            node_detail="base_snapshot_id candidate_id classifications patch_bundle_id port producer_node_id record_id record_kind schema supersedes_record_id task_region_id verdict",
        ),
        "file_state_rejected": _spec(
            "file_state_rejected",
            projection="base_snapshot_id candidate_id port producer_node_id reason record_id record_kind record_type schema snapshot_id supersedes_record_id task_region_id verdict",
            light="base_snapshot_id candidate_id cleanup_id port producer_node_id reason record_id record_kind record_type schema supersedes_record_id task_region_id verdict",
            summary="base_snapshot_id candidate_id cleanup_id payload port producer_node_id provenance reason record_id record_kind record_type run_id schema snapshot_id supersedes_record_id task_region_id verdict",
            node_detail="base_snapshot_id candidate_id classifications patch_bundle_id port producer_node_id reason record_id record_kind schema supersedes_record_id task_region_id verdict",
        ),
        "gatekeeper_cost_recorded": _spec(
            "gatekeeper_cost_recorded",
            projection="execution_id file_state_record_id",
            light="consult_id cost_usd execution_id file_state_record_id gen_ai_usage_cache_creation_input_tokens gen_ai_usage_cache_read_input_tokens gen_ai_usage_input_tokens gen_ai_usage_output_tokens item_count model_id wall_time_ms",
            summary="consult_id cost_usd execution_id file_state_record_id gen_ai_usage_cache_creation_input_tokens gen_ai_usage_cache_read_input_tokens gen_ai_usage_input_tokens gen_ai_usage_output_tokens item_count model_id wall_time_ms",
            node_detail="execution_id",
        ),
        "gatekeeper_verdict_recorded": _spec(
            "gatekeeper_verdict_recorded",
            projection="execution_id file_state_record_id producer_node_id resolved_count verdicts",
            light="execution_id file_state_record_id producer_node_id resolved_count verdicts",
            summary="execution_id file_state_record_id producer_node_id resolved_count verdicts",
            node_detail="execution_id producer_node_id",
        ),
        "graph_patch_accepted": _spec(
            "graph_patch_accepted",
            projection="carryover_record_id session_id",
            light="patch_id proposed_by_node_id session_id successor_planner_node_ids",
            summary="actor_role patch_id proposed_by_node_id session_id successor_planner_node_ids",
            node_detail="session_id",
        ),
        "graph_patch_rejected": _spec(
            "graph_patch_rejected",
            projection="reason",
            light="patch_id proposed_by_node_id reason",
            summary="actor_role patch_id proposed_by_node_id reason rejection_reason",
            node_detail="reason",
        ),
        "heartbeat_recorded": _same(
            "heartbeat_recorded", "execution_id expires_at generation lease_id node_id"
        ),
        "input_bound": _spec(
            "input_bound",
            projection="binding_policy bound_at_position edge_id record_bound_positions record_ids supersedes_record_id to_node_id to_port trigger",
            light="binding_policy bound_at_position edge_id record_bound_positions record_ids supersedes_record_id to_node_id to_port trigger",
            summary="binding_policy bound_at_position edge_id record_bound_positions record_ids supersedes_record_id to_node_id to_port trigger",
            node_detail="binding_policy edge_id record_ids supersedes_record_id to_node_id to_port trigger",
        ),
        "lease_expired": _same(
            "lease_expired", "execution_id expires_at generation lease_id node_id reason"
        ),
        "lease_granted": _same(
            "lease_granted",
            "base_snapshot_id execution_id expires_at generation kind lease_id node_id resource_claims session_id task_region_id",
        ),
        "lease_released": _same("lease_released", "generation lease_id node_id"),
        "lease_renewed": _same(
            "lease_renewed", "execution_id expires_at generation lease_id node_id"
        ),
        "lease_revoked": _same(
            "lease_revoked", "execution_id generation lease_id node_id reason trigger"
        ),
        "lease_suspended": _same(
            "lease_suspended", "execution_id generation lease_id node_id reason"
        ),
        "node_authority_changed": _same(
            "node_authority_changed",
            "allowed_actions authority node_id preconditions resource_claims",
        ),
        "node_created": _spec(
            "node_created",
            projection="allowed_actions approval_prompt approval_type attempt_number authority authority_request authority_request_record authority_request_record_id blocker blocker_reason candidate_id carryover_record_id command_binding command_definition command_definition_id decision_request decision_request_record_id execution_id failed_candidate_id gate_type generation_index guarded_planner_node_id hidden_oracle_command human_prompt id inputs kind max_attempts membership message node_id outputs planner_chain planner_generation_budget preconditions priority prompt reason recovery_of_node_id recovery_of_record_id recovery_reason region_label rejected_patch_id requirement requirement_id resource_claims role session_id state task_region_id",
            light="allowed_actions appealed_node_id approval_prompt approval_type attempt_number authority authority_request authority_request_record authority_request_record_id blocker blocker_reason candidate_id command_binding command_definition command_definition_id decision_request decision_request_record_id execution_id failed_candidate_id gate_type generation_index guarded_planner_node_id hidden_oracle_command human_prompt id inputs kind max_attempts membership message node_id outputs planner_chain planner_generation_budget preconditions priority prompt reason recovery_of_node_id recovery_of_record_id recovery_reason region_label rejected_patch_id requirement requirement_id resource_claims role session_id state task_region_id",
            summary="allowed_actions appealed_node_id approval_prompt approval_type attempt_number authority authority_request authority_request_record authority_request_record_id blocker blocker_reason candidate_id command_binding command_definition command_definition_id decision_request decision_request_record_id execution_id failed_candidate_id gate_type generation_index guarded_planner_node_id hidden_oracle_command human_prompt id inputs kind max_attempts membership message node_id outputs planner_chain planner_generation_budget preconditions priority prompt reason recovery_of_node_id recovery_of_record_id recovery_reason region_label rejected_patch_id requirement requirement_id resource_claims role run_id session_id state task_region_id",
            node_detail="allowed_actions approval_prompt approval_type attempt_number authority authority_request authority_request_record authority_request_record_id blocker blocker_reason candidate_id command_binding command_definition command_definition_id decision_request decision_request_record_id execution_id failed_candidate_id gate_type generation_index guarded_planner_node_id hidden_oracle_command human_prompt id inputs kind max_attempts membership message node_id outputs planner_chain planner_generation_budget preconditions priority prompt reason recovery_of_node_id recovery_of_record_id recovery_reason region_label rejected_patch_id requirement requirement_id resource_claims role session_id state task_region_id",
        ),
        "node_deferred": _same("node_deferred", "node_id reason"),
        "node_ready": _same("node_ready", "node_id"),
        "node_retired": _same("node_retired", "node_id reason"),
        "node_state_changed": _spec(
            "node_state_changed",
            projection="attempt_number membership new_state node_id reason retry_not_before trigger",
            light="attempt_number membership new_state node_id reason retry_not_before trigger",
            summary="attempt_number blockers graph_verifier_grades membership new_state node_id operations reason retry_not_before tokens_by_node tokens_by_node_kind trigger",
            node_detail="attempt_number membership new_state node_id prompt_summary reason retry_not_before trigger",
        ),
        "node_usage_recorded": _same(
            "node_usage_recorded",
            "cost_usd execution_id gen_ai_response_finish_reasons gen_ai_usage_cache_creation_input_tokens gen_ai_usage_cache_read_input_tokens gen_ai_usage_input_tokens gen_ai_usage_output_tokens gen_ai_usage_reasoning_output_tokens latency_ms model node_id node_kind node_role num_actions profile rate_missing usage_count usage_index usage_key",
        ),
        "output_record_accepted": _spec(
            "output_record_accepted",
            projection="attempt_number base_snapshot_id candidate_id evidence file_state_record_id outcome port producer_node_id record_id record_kind record_type schema snapshot_id supersedes_record_id supersedes_task_region_id supersedes_task_region_ids task_region_id value verdict",
            light="attempt_number base_snapshot_id candidate_id candidate_record_id candidate_record_ids cleanup_id evaluated_record_ids file_state_record_id file_state_record_ids outcome port producer_node_id record_id record_kind record_type schema supersedes_record_id supersedes_task_region_id supersedes_task_region_ids task_region_id verdict",
            summary="attempt_number base_snapshot_id candidate_id candidate_record_id candidate_record_ids cleanup_id evaluated_record_ids evidence file_state_record_id file_state_record_ids outcome payload port producer_node_id provenance record_id record_kind record_type run_id schema snapshot_id supersedes_record_id supersedes_task_region_id supersedes_task_region_ids task_region_id value verdict",
            node_detail="attempt_number base_snapshot_id candidate_id candidate_record_id candidate_record_ids classifications evaluated_record_ids file_state_record_ids outcome patch_bundle_id port producer_node_id record_id record_kind schema supersedes_record_id task_region_id verdict",
        ),
        "oversight_decision_recorded": _spec(
            "oversight_decision_recorded",
            projection="appeal_type candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id task_region_id",
            light="appeal_node_id appeal_type appealed_node_id candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id task_region_id",
            summary="appeal_node_id appeal_type appealed_node_id candidate_id decider decision decision_type expires_at gate_id membership node_id reason record_id run_id task_region_id",
            node_detail="candidate_id decider decision decision_type expires_at membership node_id reason record_id task_region_id",
        ),
        "plan_region_marked_suspect": _spec(
            "plan_region_marked_suspect",
            projection="node_id reason",
            light="node_id reason region_id",
            summary="node_id reason region_id",
            node_detail="node_id reason",
        ),
        "requirement_revision_recorded": _spec(
            "requirement_revision_recorded",
            projection="classification id node_id requirement requirement_id",
            light="active authority_required_reason behavior_change change_classification classification explicit_authority_required id new_behavior node_id patch_id previous_version_id proposal_id requirement requirement_id requirement_version_id requires_authority revision_id revision_index revision_type semantic_change validation_strengthening version_id",
            summary="active authority_required_reason behavior_change change_classification classification explicit_authority_required id new_behavior node_id patch_id previous_version_id proposal_id requirement requirement_id requirement_version_id requires_authority revision_id revision_index revision_type run_id semantic_change validation_strengthening version_id",
            node_detail="id node_id requirement requirement_id",
        ),
        "revision_created": _spec(
            "revision_created",
            projection="",
            light="verifier_node worker_node",
            summary="node verifier_node worker_node",
            node_detail="",
        ),
        "run_lifecycle_changed": _spec(
            "run_lifecycle_changed",
            projection="command_type from_state node_id reason recovery_of_node_id recovery_of_record_id recovery_reason to_state trigger",
            light="command_type from_state node_id patch_id reason recovery_of_node_id recovery_of_record_id recovery_reason to_state trigger",
            summary="command_type from_state node_id patch_id reason recovery_of_node_id recovery_of_record_id recovery_reason to_state trigger",
            node_detail="command_type from_state node_id reason recovery_of_node_id recovery_of_record_id recovery_reason to_state trigger",
        ),
        "runtime_retry_scheduled": _same(
            "runtime_retry_scheduled",
            "generation lease_id node_id policy reason retry_not_before",
        ),
        "session_state_changed": _spec(
            "session_state_changed",
            projection="carryover_record_id node_id session_id state",
            light="lease_generation node_id session_id state",
            summary="lease_generation node_id session_id state",
            node_detail="lease_generation node_id session_id state",
        ),
        "support_evidence_recorded": _spec(
            "support_evidence_recorded",
            projection="edge_id requirement_id status",
            light="confidence edge_id evidence_id requirement_id requirement_version_id stale_reason status support_id version_id",
            summary="confidence edge_id evidence_id requirement_id requirement_version_id run_id stale_reason status support_id version_id",
            node_detail="edge_id requirement_id",
        ),
        "verification_failed": _spec(
            "verification_failed",
            projection="candidate_id evidence node_id outcome record_id task_region_id value verifier_node_id",
            light="candidate_id node_id outcome record_id task_region_id",
            summary="candidate_id evidence node_id outcome record_id task_region_id value verifier_node_id",
            node_detail="candidate_id node_id outcome record_id task_region_id",
        ),
        "verification_passed": _spec(
            "verification_passed",
            projection="candidate_id evidence node_id outcome record_id task_region_id value verifier_node_id",
            light="candidate_id node_id outcome record_id task_region_id",
            summary="candidate_id evidence node_id outcome record_id task_region_id value verifier_node_id",
            node_detail="candidate_id node_id outcome record_id task_region_id",
        ),
    }
)


def validate_event_payload_specs(
    payload_models: Mapping[str, type[BaseModel]],
    payload_specs: Mapping[str, EventPayloadSpec],
) -> None:
    missing = payload_models.keys() - payload_specs.keys()
    if missing:
        raise ValueError(f"missing payload specs: {', '.join(sorted(missing))}")
    stale = payload_specs.keys() - payload_models.keys()
    if stale:
        raise ValueError(f"stale payload specs: {', '.join(sorted(stale))}")
    mismatched = [
        event_type
        for event_type, model in payload_models.items()
        if payload_specs[event_type].model is not model
    ]
    if mismatched:
        raise ValueError(f"payload spec model mismatch: {', '.join(sorted(mismatched))}")


validate_event_payload_specs(EVENT_PAYLOAD_MODELS, EVENT_PAYLOAD_SPECS)


def generated_payload_fields(mode: RetentionMode) -> tuple[str, ...]:
    fields: set[str] = set()
    for spec in EVENT_PAYLOAD_SPECS.values():
        fields.update(getattr(spec, mode))
    return tuple(sorted(fields))


GRAPH_PROJECTION_PAYLOAD_FIELDS = generated_payload_fields("projection")
LIGHT_GRAPH_PAYLOAD_FIELDS = generated_payload_fields("light")
SUMMARY_REBUILD_PAYLOAD_FIELDS = generated_payload_fields("summary")
NODE_DETAIL_PAYLOAD_FIELDS = generated_payload_fields("node_detail")
