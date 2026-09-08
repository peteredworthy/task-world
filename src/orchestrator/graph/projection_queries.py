"""Pure queries over graph projection storage.

Each query owns the physical projection access and returns values that cannot
mutate projection containers.
"""

from typing import Any, Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict

from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    GraphPatchProposalRecord,
    CallbackIdempotencyEvent,
    CandidateProjection,
    CheckResultProjection,
    CommandDefinitionProjection,
    CleanupRequestedProjection,
    EdgeProjection,
    EnvironmentFailureProjection,
    FileStateRecord,
    InputBindingProjection,
    LeaseProjection,
    OutputRecordAcceptedPayload,
    RequirementRecord,
    RoutineSnapshotRecord,
    SemanticSchemaDeclarationRecord,
    ResourceClaimProjection,
    RegionSnapshotProjection,
    TaskRegionSnapshotAuthorityProjection,
    VerificationResultProjection,
    VerifierVerdictProjection,
)
from orchestrator.graph.cache_authority import (
    CacheAuthorityBinding,
    CacheAuthorityPolicy,
    LEGACY_CACHE_AUTHORITY_V1,
    POLICY_VERSION,
    cache_authority_hash,
    canonicalize_cache_authority,
    has_cache_authority_carrier,
)
from orchestrator.graph.projection_collections import (
    FrozenJsonValue,
    FrozenMap,
    JsonValue,
    thaw_json,
)
from orchestrator.graph.projection_models import (
    ExecutionAttemptValue,
    GraphRecordSummaryProjection,
    PlannerPatchDecisionValue,
)
from orchestrator.graph.projections import (
    AcceptedOutputRecord,
    GraphProjection,
    GraphRecordSummary,
    LatestRoutineSnapshotRecord,
    RecoveryNodeIndexEntry,
    requirement_freshness_facts_from_projection,
)
from orchestrator.graph.semantic_artifacts import semantic_schema_declarations


class EvidenceClosureError(ValueError):
    """Raised when accepted evidence cannot form a deterministic closure."""


class EvidenceClosure(BaseModel):
    """Immutable evidence citations shared by prompts, records, and validation."""

    model_config = ConfigDict(frozen=True)

    candidate_record_ids: tuple[str, ...] = ()
    file_state_record_ids: tuple[str, ...] = ()
    verification_report_record_ids: tuple[str, ...] = ()
    evaluated_record_ids: tuple[str, ...] = ()

    def citations(self) -> dict[str, list[str]]:
        return {
            field: list(values)
            for field in (
                "candidate_record_ids",
                "file_state_record_ids",
                "verification_report_record_ids",
                "evaluated_record_ids",
            )
            if (values := getattr(self, field))
        }


EvidenceConsumer = Literal["check", "verifier", "final_audit", "callback"]


def effective_active_node_ids_view(
    projection: GraphProjection,
    *,
    additionally_retired_node_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return lifecycle-aware topology nodes in deterministic graph order."""
    excluded = set(additionally_retired_node_ids)
    states = node_states_view(projection)
    return tuple(
        node_id
        for node_id in projection.nodes
        if node_id not in excluded and states.get(node_id) not in {"retired", "cancelled"}
    )


def evidence_closure_for_node(
    projection: GraphProjection,
    node_id: str,
    *,
    consumer: EvidenceConsumer = "callback",
) -> EvidenceClosure:
    """Resolve one deterministic, transitive evidence contract for a node.

    Direct verification/check/requirement inputs lead the evaluated order,
    followed by their transitive cited evidence, then directly or transitively
    identified candidate and file-state records. Unknown accepted references
    and citation cycles fail closed for every consumer.
    """
    del consumer  # One shared contract; the name documents the calling boundary.
    node = node_payload_view(projection, node_id) or {}

    bindings = input_bindings_view(projection).get(node_id, {})
    candidate_ids = _record_ids_for_binding_ports(
        bindings,
        ("candidate_under_test", "candidate", "semantic_artifact"),
    )
    file_state_ids = _record_ids_for_binding_ports(
        bindings,
        ("file_state", "accepted_file_state"),
    )
    evidence_ports = tuple(
        port
        for port in sorted(bindings)
        if port
        in {
            "check_result",
            "dynamic_feature_acceptance",
            "verification_evidence",
            "verification_report",
            "verifier_check_results",
        }
        or port.startswith(("check_result_", "requirement_", "verification_report_"))
    )
    evidence_ids = _record_ids_for_binding_ports(bindings, evidence_ports)

    output_records = record_payloads_view(projection)
    file_states = file_state_records_view(projection)
    known_ids = {*output_records, *file_states}
    for record_id in tuple(candidate_ids):
        payload = output_records.get(record_id)
        if payload is not None:
            file_state_ids.extend(_citation_ids(payload, "file_state_record_ids"))

    indirect_ids: list[str] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(record_id: str) -> None:
        if record_id in visiting:
            cycle = " -> ".join([*visiting[visiting.index(record_id) :], record_id])
            raise EvidenceClosureError(f"evidence citation cycle: {cycle}")
        if record_id in visited:
            return
        if record_id not in known_ids:
            # Legacy/replayed projections may retain a typed citation after its
            # record body has been compacted. Preserve the durable ID as an
            # opaque leaf; only accepted record bodies can extend the closure.
            visited.add(record_id)
            return
        visiting.append(record_id)
        payload = output_records.get(record_id)
        if payload is not None:
            candidate_ids.extend(_citation_ids(payload, "candidate_record_ids"))
            file_state_ids.extend(_citation_ids(payload, "file_state_record_ids"))
            children = _citation_ids(payload, "evaluated_record_ids")
            for child_id in children:
                if child_id not in indirect_ids:
                    indirect_ids.append(child_id)
                visit(child_id)
        visiting.pop()
        visited.add(record_id)

    for evidence_id in evidence_ids:
        visit(evidence_id)

    candidate_ids = _unique_ids(candidate_ids)
    for candidate_id in candidate_ids:
        payload = output_records.get(candidate_id)
        if payload is not None:
            file_state_ids.extend(_citation_ids(payload, "file_state_record_ids"))
    if not file_state_ids and node.get("semantic_stage") != "plan_verification":
        region_id = node.get("task_region_id")
        if isinstance(region_id, str):
            for record_id, record in file_states.items():
                record_region_id = record.task_region_id
                if not isinstance(record_region_id, str) and isinstance(
                    record.producer_node_id, str
                ):
                    record_region_id = node_task_regions_view(projection).get(
                        record.producer_node_id
                    )
                if record_region_id == region_id:
                    file_state_ids.append(record_id)

    candidate_ids = _unique_ids(candidate_ids)
    file_state_ids = _unique_ids(file_state_ids)
    evaluated_ids = _unique_ids([*evidence_ids, *indirect_ids, *candidate_ids, *file_state_ids])
    return EvidenceClosure(
        candidate_record_ids=tuple(candidate_ids),
        file_state_record_ids=tuple(file_state_ids),
        verification_report_record_ids=tuple(_unique_ids(evidence_ids)),
        evaluated_record_ids=tuple(evaluated_ids),
    )


def _record_ids_for_binding_ports(
    bindings: dict[str, InputBindingProjection], ports: tuple[str, ...]
) -> list[str]:
    return _unique_ids(
        [
            record_id
            for port in ports
            if (binding := bindings.get(port)) is not None
            for record_id in binding.record_ids
        ]
    )


def _citation_ids(payload: dict[str, Any], field: str) -> list[str]:
    for source in (
        payload,
        payload.get("value"),
        payload.get("provenance"),
        payload.get("evidence"),
    ):
        if not isinstance(source, dict):
            continue
        raw_ids = cast(dict[str, Any], source).get(field)
        if raw_ids is None:
            continue
        if not isinstance(raw_ids, list):
            raise EvidenceClosureError(f"{field} must contain only record IDs")
        typed_ids = cast(list[Any], raw_ids)
        if any(not isinstance(item, str) for item in typed_ids):
            raise EvidenceClosureError(f"{field} must contain only record IDs")
        return cast(list[str], typed_ids)
    return []


def _unique_ids(record_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(record_ids))


def semantic_schema_declarations_view(
    projection: GraphProjection,
) -> dict[tuple[str, int], SemanticSchemaDeclarationRecord]:
    """Return accepted semantic declarations without exposing record storage."""
    return dict(semantic_schema_declarations(projection.records.by_id))


def non_gap_planner_has_accepted_patch(projection: GraphProjection, node_id: str) -> bool:
    """Return whether a regular planner has already published an accepted patch."""
    node = projection.nodes.get(node_id)
    return (
        node is not None
        and node.spec.kind == "planner"
        and node.spec.role != "gap_planner"
        and bool(projection.planning.accepted_patch_ids_by_node.get(node_id))
    )


def non_gap_planner_completion_contract_satisfied(
    projection: GraphProjection, node_id: str
) -> bool:
    """Return whether an accepted planner patch satisfies its durable horizon contract."""
    if not non_gap_planner_has_accepted_patch(projection, node_id):
        return False
    planner = node_payload_view(projection, node_id) or {}
    if planner.get("semantic_stage") != "successor_planning":
        if not isinstance(planner.get("reliable_plan_skeleton_id"), str):
            return True
        accepted_patch_ids = set(projection.planning.accepted_patch_ids_by_node.get(node_id, ()))
        payloads = [
            payload
            for candidate_id in projection.nodes
            if (payload := node_payload_view(projection, candidate_id) or {}).get("patch_id")
            in accepted_patch_ids
        ]
        discovery_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("semantic_stage") == "discovery"
        }
        verifier_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("semantic_stage") == "plan_verification"
        }
        successor_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("kind") == "planner"
            and payload.get("semantic_stage") == "successor_planning"
        }
        recovery_payloads = [
            payload
            for payload in payloads
            if payload.get("kind") == "planner" and payload.get("role") == "gap_planner"
        ]
        recovery_patch_ids = {payload.get("patch_id") for payload in recovery_payloads}
        return len(recovery_payloads) == 1 and bool(
            discovery_patch_ids & verifier_patch_ids & successor_patch_ids & recovery_patch_ids
        )

    remaining = planner.get("reliable_plan_remaining_horizons")
    horizon = planner.get("planning_horizon")
    skeleton_id = planner.get("reliable_plan_skeleton_id")
    if (
        not isinstance(remaining, int)
        or isinstance(remaining, bool)
        or not isinstance(horizon, int)
        or isinstance(horizon, bool)
        or not isinstance(skeleton_id, str)
    ):
        return False

    accepted_patch_ids = set(projection.planning.accepted_patch_ids_by_node.get(node_id, ()))
    payloads = [
        payload
        for candidate_id in projection.nodes
        if (payload := node_payload_view(projection, candidate_id) or {}).get("patch_id")
        in accepted_patch_ids
    ]
    if not reliable_plan_successor_horizon_materialized(projection, node_id):
        return False
    if remaining > 1:
        batch_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("kind") == "worker"
            and payload.get("semantic_stage") == "effectful_batch"
            and payload.get("planning_horizon") == horizon
        }
        successor_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("kind") == "planner"
            and payload.get("role") != "gap_planner"
            and payload.get("semantic_stage") == "successor_planning"
            and payload.get("planning_horizon") == horizon + 1
            and payload.get("reliable_plan_skeleton_id") == skeleton_id
        }
        recovery_payloads = [
            payload
            for payload in payloads
            if payload.get("kind") == "planner" and payload.get("role") == "gap_planner"
        ]
        recovery_patch_ids = {payload.get("patch_id") for payload in recovery_payloads}
        return len(recovery_payloads) == 1 and bool(
            batch_patch_ids & successor_patch_ids & recovery_patch_ids
        )
    if remaining == 1:
        batch_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("kind") == "worker"
            and payload.get("semantic_stage") == "effectful_batch"
            and payload.get("planning_horizon") == horizon
        }
        final_acceptance_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("kind") == "check"
            and payload.get("semantic_stage") == "final_acceptance"
            and payload.get("command_binding") == "dynamic_feature_acceptance"
        }
        final_audit_patch_ids = {
            payload.get("patch_id")
            for payload in payloads
            if payload.get("kind") == "verifier" and payload.get("semantic_stage") == "final_audit"
        }
        final_gate_patch_ids = {
            payload.get("patch_id") for payload in payloads if payload.get("kind") == "final_gate"
        }
        recovery_payloads = [
            payload
            for payload in payloads
            if payload.get("kind") == "planner" and payload.get("role") == "gap_planner"
        ]
        recovery_patch_ids = {payload.get("patch_id") for payload in recovery_payloads}
        return len(recovery_payloads) == 3 and bool(
            batch_patch_ids
            & final_acceptance_patch_ids
            & final_audit_patch_ids
            & final_gate_patch_ids
            & recovery_patch_ids
        )
    return False


def reliable_plan_successor_horizon_materialized(projection: GraphProjection, node_id: str) -> bool:
    """Return whether a successor planner durably created its effectful batch."""
    planner = node_payload_view(projection, node_id) or {}
    if planner.get("semantic_stage") != "successor_planning":
        return False
    horizon = planner.get("planning_horizon")
    skeleton_id = planner.get("reliable_plan_skeleton_id")
    accepted_patch_ids = set(projection.planning.accepted_patch_ids_by_node.get(node_id, ()))
    return any(
        payload.get("patch_id") in accepted_patch_ids
        and payload.get("kind") == "worker"
        and payload.get("semantic_stage") == "effectful_batch"
        and payload.get("planning_horizon") == horizon
        and payload.get("reliable_plan_skeleton_id") == skeleton_id
        for candidate_id in projection.nodes
        if (payload := node_payload_view(projection, candidate_id) or {})
    )


def output_record_payloads_view(
    projection: GraphProjection,
) -> dict[str, AcceptedOutputRecordPayload]:
    return {
        record_id: OutputRecordAcceptedPayload.model_validate(
            record.model_dump(mode="json", by_alias=True)
        ).root
        for record_id, record in projection.records.by_id.items()
        if record.record_type != "file_state"
    }


def record_payloads_view(projection: GraphProjection) -> dict[str, dict[str, Any]]:
    """Return independent canonical payloads for all accepted graph records."""
    payloads: dict[str, dict[str, Any]] = {}
    for record_id in projection.records.by_id:
        record = _accepted_output_record(projection, record_id)
        payload = record.model_dump(
            mode="json", by_alias=True, exclude_defaults=True, exclude_none=True
        )
        # Literal envelope fields remain part of a canonical record even when
        # their value equals the concrete model's default.  Prompt hydration
        # and citations use these fields to describe a projected record without
        # reaching back into the event history.
        payload.update(
            record.model_dump(
                mode="json",
                by_alias=True,
                include={
                    "record_id",
                    "record_type",
                    "record_kind",
                    "producer_node_id",
                    "port",
                    "schema_",
                },
                exclude_none=True,
            )
        )
        payloads[record_id] = payload
    return payloads


def accepted_no_successor_patches_by_node_view(
    projection: GraphProjection,
) -> dict[str, list[str]]:
    return {
        node_id: list(ids)
        for node_id, ids in projection.planning.no_successor_patch_ids_by_node.items()
    }


def accepted_output_records_by_node_port_view(
    projection: GraphProjection,
) -> dict[str, dict[str, list[AcceptedOutputRecord]]]:
    return {
        node_id: {
            port: [
                {
                    "record_id": record_id,
                    "payload": _accepted_output_record(projection, record_id),
                }
                for record_id in record_ids
            ]
            for port, record_ids in ports.items()
        }
        for node_id, ports in projection.records.ids_by_node_port.items()
    }


def accepted_record_summaries_by_id_view(
    projection: GraphProjection,
) -> dict[str, GraphRecordSummary]:
    return {
        record_id: _graph_record_summary(summary)
        for record_id, summary in projection.records.summaries_by_id.items()
    }


def active_requirement_versions_view(projection: GraphProjection) -> dict[str, str]:
    return dict(projection.requirements.active_version_id_by_requirement)


def callback_idempotency_events_view(
    projection: GraphProjection,
) -> dict[str, CallbackIdempotencyEvent]:
    return {
        key: CallbackIdempotencyEvent.model_validate(value.model_dump(mode="json"))
        for key, value in projection.execution.callback_events_by_key.items()
    }


def execution_attempts_view(projection: GraphProjection) -> dict[str, ExecutionAttemptValue]:
    """Return immutable runner attempts keyed by external execution identity."""
    return dict(projection.execution.attempts_by_execution_id)


def check_results_view(projection: GraphProjection) -> dict[str, CheckResultProjection]:
    return {
        node_id: CheckResultProjection.model_validate(result.model_dump(mode="json"))
        for node_id, result in projection.verification.check_results_by_node.items()
    }


def cleanup_applied_ids_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.execution.applied_cleanup_ids)


def cleanup_requested_events_view(
    projection: GraphProjection,
) -> dict[str, CleanupRequestedProjection]:
    return {
        cleanup_id: CleanupRequestedProjection.model_validate(request.model_dump(mode="json"))
        for cleanup_id, request in projection.execution.cleanup_requests_by_id.items()
    }


def edges_view(projection: GraphProjection) -> dict[str, EdgeProjection]:
    return {
        edge_id: EdgeProjection.model_validate(edge.model_dump(mode="json"))
        for edge_id, edge in projection.topology.edges.items()
    }


def environment_failures_view(
    projection: GraphProjection,
) -> dict[str, EnvironmentFailureProjection]:
    return {
        task_id: EnvironmentFailureProjection.model_validate(failure.model_dump(mode="json"))
        for task_id, failure in projection.execution.environment_failures_by_task.items()
    }


def failed_verification_candidate_ids_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.verification.failed_candidate_ids)


def failed_verification_results_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, VerificationResultProjection]:
    return {
        record_id: VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        for record_id, result in projection.verification.failed_results_by_record_id.items()
    }


def file_state_records_view(projection: GraphProjection) -> dict[str, FileStateRecord]:
    return {
        record_id: FileStateRecord.model_validate(
            {
                key: value
                for key, value in record.model_dump(mode="json", by_alias=True).items()
                if key != "acceptance_identity"
            }
        )
        for record_id, record in projection.records.by_id.items()
        if isinstance(record, FileStateRecord)
    }


def input_bindings_view(
    projection: GraphProjection,
) -> dict[str, dict[str, InputBindingProjection]]:
    return {
        node_id: {
            port: InputBindingProjection.model_validate(ports[port].model_dump(mode="json"))
            for port in projection.topology.input_binding_port_order.get(node_id, ())
        }
        for node_id, ports in projection.topology.input_bindings.items()
    }


def last_deferred_reasons_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.scheduling.last_deferred_reason
        for node_id, node in projection.nodes.items()
        if node.scheduling.last_deferred_reason is not None
    }


def leases_view(projection: GraphProjection) -> dict[str, LeaseProjection]:
    return {
        lease_id: LeaseProjection.model_validate(
            projection.execution.leases[lease_id].model_dump(mode="json")
        )
        for lease_id in projection.execution.lease_ids_in_grant_order
    }


def node_attempts_view(projection: GraphProjection) -> dict[str, int]:
    return {
        node_id: node.runtime.attempt_number
        for node_id, node in projection.nodes.items()
        if node.runtime.attempt_number is not None
    }


def runtime_retry_counts_view(projection: GraphProjection) -> dict[str, int]:
    """Return canonical accepted runtime-retry event counts by node."""
    return {
        node_id: node.scheduling.runtime_retry_count
        for node_id, node in projection.nodes.items()
        if node.scheduling.runtime_retry_count > 0
    }


def node_max_attempts_view(projection: GraphProjection) -> dict[str, int]:
    from orchestrator.graph.retry_policy import effective_node_max_attempts

    return {
        node_id: effective
        for node_id, node in projection.nodes.items()
        if (effective := effective_node_max_attempts(node.spec.kind, node.spec.max_attempts))
        is not None
    }


def node_command_definitions_view(
    projection: GraphProjection,
) -> dict[str, CommandDefinitionProjection]:
    return {
        node_id: _command_definition_value(node.spec.command_definition.value)
        for node_id, node in projection.nodes.items()
        if node.spec.command_definition is not None
    }


def node_payload_view(projection: GraphProjection, node_id: str) -> dict[str, Any] | None:
    """Return the durable scheduler payload for one projected node."""
    node = projection.nodes.get(node_id)
    if node is None:
        return None
    payload = thaw_json(node.spec.dispatch_payload)
    if not isinstance(payload, dict):
        payload = {}
    stable = node.spec.model_dump(mode="json", exclude_none=True)
    stable.pop("dispatch_payload", None)
    stable.pop("creation_position", None)
    payload.update(stable)
    runtime = node.runtime.model_dump(mode="json", exclude_none=True)
    payload.update(runtime)
    command_definition = payload.get("command_definition")
    if isinstance(command_definition, dict) and "value" in command_definition:
        payload["command_definition"] = command_definition["value"]
    return payload


def requirements_for_node_view(projection: GraphProjection, node_id: str) -> list[str]:
    """Return current bound requirement text without replaying creation events."""
    record_ids: list[str] = []
    bindings = projection.topology.input_bindings.get(node_id, FrozenMap())
    for port in projection.topology.input_binding_port_order.get(node_id, ()):
        if not port.startswith("requirement_"):
            continue
        binding = bindings.get(port)
        if binding is not None:
            record_ids.extend(binding.record_ids)
    requirements: list[str] = []
    for record_id in record_ids:
        record = projection.records.by_id.get(record_id)
        if not isinstance(record, RequirementRecord):
            continue
        requirements.append(f"{record.value.id}: {record.value.text}")
    return requirements


def routine_snapshot_dynamic_feature_view(
    projection: GraphProjection,
) -> dict[str, Any] | None:
    """Return a thawed copy of the latest routine's dynamic feature inputs."""
    latest = projection.planning.latest_routine_snapshot
    record = projection.records.by_id.get(latest.record_id) if latest is not None else None
    if not isinstance(record, RoutineSnapshotRecord):
        return None
    dynamic_feature = record.value.dynamic_feature
    if dynamic_feature is None:
        return None
    thawed = thaw_json(dynamic_feature)
    return cast(dict[str, Any], thawed) if isinstance(thawed, dict) else None


def planner_freshness_packet_view(projection: GraphProjection) -> dict[str, Any]:
    """Return planner requirement freshness directly from the runtime projection."""
    facts = requirement_freshness_facts_from_projection(projection)
    return {
        "requirement_freshness": facts,
        "unsupported_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["unsupported"]
        ],
        "stale_support_ids": [
            support_id for fact in facts for support_id in fact["stale_support_ids"]
        ],
        "authority_required_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["requires_authority"]
        ],
    }


def planner_patch_facts_view(
    projection: GraphProjection, node_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Return open proposals and durable patch decisions for one planner."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for decision in projection.planning.patch_decisions_by_id.values():
        if decision.proposed_by_node_id != node_id:
            continue
        entry = {
            "patch_id": decision.patch_id,
            "base_graph_position": decision.base_graph_position,
            "position": decision.position,
        }
        if decision.status == "accepted":
            accepted.append(entry)
        else:
            if decision.reason is not None:
                entry["reason"] = decision.reason
            if decision.base_graph_position is None:
                entry.pop("base_graph_position")
            rejected.append(entry)

    open_proposals: list[dict[str, Any]] = []
    for record in projection.records.by_id.values():
        if not isinstance(record, GraphPatchProposalRecord):
            continue
        proposal = record.value
        if proposal.proposed_by_node_id != node_id:
            continue
        if proposal.patch_id in projection.governance.resolved_patch_ids:
            continue
        open_proposals.append(
            {
                "patch_id": proposal.patch_id,
                "base_graph_position": proposal.base_graph_position,
                "rationale": proposal.rationale,
            }
        )

    def patch_key(item: dict[str, Any]) -> str:
        return str(item.get("patch_id", ""))

    return {
        "open_proposals": sorted(open_proposals, key=patch_key),
        "accepted_patches": sorted(accepted, key=patch_key),
        "patch_rejections": sorted(rejected, key=patch_key),
    }


def planner_patch_decisions_by_id_view(
    projection: GraphProjection,
) -> dict[str, PlannerPatchDecisionValue]:
    """Return durable patch decisions used to reconcile lost acknowledgements."""

    return dict(projection.planning.patch_decisions_by_id)


def pattern_library_view(projection: GraphProjection) -> dict[str, dict[str, dict[str, Any]]]:
    """Derive learned path classifications from projected file-state records."""
    paths: dict[str, dict[str, Any]] = {}
    patterns: dict[str, dict[str, Any]] = {}
    for record_id, record in file_state_records_view(projection).items():
        for entry in record.paths:
            if (
                entry.source not in {"untracked", "ignored"}
                or entry.classification in {None, "secret"}
                or not (entry.matched_rule or "").startswith("gatekeeper:")
            ):
                continue
            path = entry.path
            pattern = _derived_gatekeeper_pattern(path)
            value = {
                "classification": entry.classification,
                "source_record_ids": [record_id],
                "source_kinds": ["untracked", "ignored"],
            }
            paths[path] = {"path": path, **value}
            patterns[pattern] = {"pattern": pattern, **value}
    return {
        "patterns": {key: patterns[key] for key in sorted(patterns)},
        "paths": {key: paths[key] for key in sorted(paths)},
    }


def _derived_gatekeeper_pattern(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "/" not in path or "." not in name or name.startswith("."):
        return path
    directory = path.rsplit("/", 1)[0]
    extension = name.rsplit(".", 1)[-1]
    return f"{directory}/*.{extension}"


def node_creation_positions_view(projection: GraphProjection) -> dict[str, int]:
    return {node_id: node.spec.creation_position for node_id, node in projection.nodes.items()}


def node_cache_authority_hash(projection: GraphProjection, node_id: str) -> str | None:
    node = projection.nodes.get(node_id)
    return node.spec.cache_authority_hash if node is not None else None


def node_gate_decisions_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.governance.node_gate_decisions)


def node_failed_candidates_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.runtime.failed_candidate_id
        for node_id, node in projection.nodes.items()
        if node.runtime.failed_candidate_id is not None
    }


def node_pending_appeals_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.governance.pending_appeals_by_node)


def node_preconditions_view(projection: GraphProjection) -> dict[str, list[str]]:
    return {node_id: list(node.spec.preconditions) for node_id, node in projection.nodes.items()}


def node_kinds_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.kind
        for node_id, node in projection.nodes.items()
        if node.spec.kind is not None
    }


def node_resource_claims_view(
    projection: GraphProjection,
) -> dict[str, list[ResourceClaimProjection]]:
    return {
        node_id: [
            ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
            for claim in node.spec.resource_claims
        ]
        for node_id, node in projection.nodes.items()
    }


def node_roles_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.role
        for node_id, node in projection.nodes.items()
        if node.spec.role is not None
    }


def node_states_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.runtime.state
        for node_id, node in projection.nodes.items()
        if node.runtime.state is not None
    }


def node_task_regions_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.task_region_id
        for node_id, node in projection.nodes.items()
        if node.spec.task_region_id is not None
    }


def node_base_snapshot_selections_view(
    projection: GraphProjection,
) -> dict[str, dict[str, str | None]]:
    """Return each node's declared semantic snapshot selection contract."""
    return {
        node_id: {
            "selection": node.spec.base_snapshot_selection,
            "region_id": node.spec.base_snapshot_region_id,
            "candidate_id": node.spec.base_snapshot_candidate_id,
        }
        for node_id, node in projection.nodes.items()
        if node.spec.base_snapshot_selection is not None
    }


def output_records_by_node_port_view(
    projection: GraphProjection,
) -> dict[str, dict[str, list[AcceptedOutputRecordPayload]]]:
    return {
        node_id: {
            port: [
                _accepted_output_record(projection, record_id)
                for record_id in record_ids
                if projection.records.by_id[record_id].record_type != "file_state"
            ]
            for port, record_ids in ports.items()
        }
        for node_id, ports in projection.records.ids_by_node_port.items()
    }


def _accepted_output_record(
    projection: GraphProjection, record_id: str
) -> AcceptedOutputRecordPayload:
    record = projection.records.by_id[record_id]
    if isinstance(record, FileStateRecord):
        return record.model_copy(update={"acceptance_identity": None})
    return record


def passed_verification_candidate_ids_view(projection: GraphProjection) -> list[str]:
    return list(projection.verification.passed_candidate_ids)


def passed_verification_results_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, VerificationResultProjection]:
    return {
        record_id: VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        for record_id, result in projection.verification.passed_results_by_record_id.items()
    }


def planner_generations_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.planning.generation_by_node)


def planner_session_carryovers_view(projection: GraphProjection) -> dict[str, str | None]:
    return {
        session_id: session.carryover_record_id
        for session_id, session in projection.planning.sessions.items()
    }


def planner_sessions_view(projection: GraphProjection) -> dict[str, str]:
    return dict(projection.planning.session_id_by_node)


def ready_nodes_view(projection: GraphProjection) -> list[str]:
    return list(projection.scheduling.ready_node_ids)


def recorded_node_usage_keys_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.usage.recorded_keys)


class UsageMetricsView(TypedDict):
    tokens_by_node: dict[str, int]
    tokens_by_node_kind: dict[str, int]
    latency_ms_by_node_kind: dict[str, int]
    execution_count_by_node_kind: dict[str, int]
    action_count_by_node_kind: dict[str, int]


def usage_metrics_view(projection: GraphProjection) -> UsageMetricsView:
    """Return the public, carrier-owned graph usage aggregates.

    Reliable-plan evaluation consumes this query rather than reaching into the
    grouped projection.  The values are additive carrier facts; callers decide
    how to label or compare an evaluation arm.
    """
    usage = projection.usage
    return {
        "tokens_by_node": dict(usage.tokens_by_node),
        "tokens_by_node_kind": dict(usage.tokens_by_node_kind),
        "latency_ms_by_node_kind": dict(usage.latency_ms_by_node_kind),
        "execution_count_by_node_kind": dict(usage.execution_count_by_node_kind),
        "action_count_by_node_kind": dict(usage.action_count_by_node_kind),
    }


def recovery_nodes_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, list[RecoveryNodeIndexEntry]]:
    return {
        record_id: [
            RecoveryNodeIndexEntry.model_validate(entry.model_dump(mode="json"))
            for entry in entries
        ]
        for record_id, entries in projection.verification.recovery_nodes_by_record_id.items()
    }


def retry_not_before_by_node_view(projection: GraphProjection) -> dict[str, str | None]:
    return {
        node_id: node.scheduling.retry_not_before
        for node_id, node in projection.nodes.items()
        if node.scheduling.retry_not_before is not None
    }


def recovery_blockers_by_node_view(projection: GraphProjection) -> dict[str, str]:
    """Return durable recovery-required blockers keyed by executable node."""
    return {
        node_id: node.scheduling.recovery_blocker_record_id
        for node_id, node in projection.nodes.items()
        if node.scheduling.recovery_blocker_record_id is not None
    }


def task_candidates_view(
    projection: GraphProjection,
) -> dict[str, list[CandidateProjection]]:
    return {
        task_id: [
            CandidateProjection.model_validate(candidate.model_dump(mode="json"))
            for candidate in task.candidates
        ]
        for task_id, task in projection.tasks.items()
        if task.candidates
    }


def task_states_view(projection: GraphProjection) -> dict[str, str]:
    return {
        task_id: task.state for task_id, task in projection.tasks.items() if task.state is not None
    }


def task_region_snapshot_authority_view(
    projection: GraphProjection,
) -> dict[str, TaskRegionSnapshotAuthorityProjection]:
    """Return immutable accepted/current/rejected filesystem authority by region."""
    output: dict[str, TaskRegionSnapshotAuthorityProjection] = {}
    for task_region_id, task in projection.tasks.items():
        accepted = (
            RegionSnapshotProjection.model_validate(task.accepted_snapshot.model_dump(mode="json"))
            if task.accepted_snapshot is not None
            else None
        )
        current = (
            RegionSnapshotProjection.model_validate(
                task.current_candidate_snapshot.model_dump(mode="json")
            )
            if task.current_candidate_snapshot is not None
            else None
        )
        output[task_region_id] = TaskRegionSnapshotAuthorityProjection(
            task_region_id=task_region_id,
            accepted_snapshot=accepted,
            current_candidate_snapshot=current,
            rejected_snapshots=[
                RegionSnapshotProjection.model_validate(item.model_dump(mode="json"))
                for item in task.rejected_snapshots
            ],
        )
    return output


def verifier_verdicts_view(
    projection: GraphProjection,
) -> dict[str, VerifierVerdictProjection]:
    return {
        value.candidate_id: VerifierVerdictProjection.model_validate(value.model_dump(mode="json"))
        for value in projection.verification.verdicts_by_node.values()
    }


def resource_claims_for_node(
    projection: GraphProjection,
    node_id: str,
) -> tuple[ResourceClaimProjection, ...]:
    """Return a node's resource claims without exposing mutable projection storage."""
    node = projection.nodes.get(node_id)
    if node is None:
        return ()
    return tuple(
        ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
        for claim in node.spec.resource_claims
    )


def _command_definition_value(value: FrozenMap[str, FrozenJsonValue]) -> dict[str, JsonValue]:
    """Unwrap the frozen command-definition envelope into its public mapping."""
    definition = thaw_json(value)
    while isinstance(definition, dict) and set(definition) == {"value"}:
        definition = definition["value"]
    if not isinstance(definition, dict):
        raise ValueError("command definition must decode to a JSON object")
    return definition


def _graph_record_summary(summary: GraphRecordSummaryProjection) -> GraphRecordSummary:
    """Return the exact public TypedDict shape without exposing frozen storage."""
    view: GraphRecordSummary = {}
    if summary.record_id is not None:
        view["record_id"] = summary.record_id
    if summary.record_type is not None:
        view["record_type"] = summary.record_type
    if summary.record_kind is not None:
        view["record_kind"] = summary.record_kind
    if summary.schema_ is not None:
        view["schema"] = summary.schema_
    if summary.producer_node_id is not None:
        view["producer_node_id"] = summary.producer_node_id
    if summary.producer_port is not None:
        view["producer_port"] = summary.producer_port
    if summary.position is not None:
        view["position"] = summary.position
    return view


def lease_by_id(projection: GraphProjection, lease_id: str) -> LeaseProjection | None:
    """Return an independent lease copy, if it exists."""
    lease = projection.execution.leases.get(lease_id)
    return (
        LeaseProjection.model_validate(lease.model_dump(mode="json")) if lease is not None else None
    )


def run_state(projection: GraphProjection) -> str | None:
    """Return the current lifecycle state, or ``None`` before its first event."""
    return projection.lifecycle.run_state


def completion_decision_passed(projection: GraphProjection) -> bool:
    """Return whether the latest lifecycle completion decision passed."""
    return projection.lifecycle.completion_decision_passed


def planner_generation_budget(projection: GraphProjection) -> int:
    """Return the configured planner generation budget."""
    return projection.planning.generation_budget


def latest_routine_snapshot_record(
    projection: GraphProjection,
) -> LatestRoutineSnapshotRecord | None:
    """Return an independent latest routine snapshot record, if present."""
    record = projection.planning.latest_routine_snapshot
    return (
        LatestRoutineSnapshotRecord.model_validate(record.model_dump(mode="json"))
        if record is not None
        else None
    )


def cache_authority_binding(projection: GraphProjection) -> CacheAuthorityBinding:
    """Return the verified snapshot-owned cache authority, or frozen legacy V1.

    Snapshot values are the only full policy owner.  The preimage and digest are
    checked here rather than trusting a caller-supplied policy or command context.
    """
    record = projection.records.by_id.get("routine-snapshot-record")
    has_carrier = has_cache_authority_carrier(
        any(node.spec.cache_authority_hash is not None for node in projection.nodes.values()),
        (lease.cache_authority_hash for lease in projection.execution.leases.values()),
    )
    if record is None:
        if has_carrier:
            raise ValueError("routine snapshot graph requires canonical routine-snapshot-record")
        policy = LEGACY_CACHE_AUTHORITY_V1
        return CacheAuthorityBinding(
            policy=policy,
            preimage=canonicalize_cache_authority(policy),
            hash=cache_authority_hash(policy),
        )
    if not isinstance(record, RoutineSnapshotRecord):
        raise ValueError("routine-snapshot-record must be a routine snapshot record")
    value = getattr(record, "value")
    preimage = getattr(value, "cache_authority_preimage", None)
    digest = getattr(value, "cache_authority_hash", None)
    version = getattr(value, "cache_authority_version", None)
    absent = version is None and preimage is None and digest is None
    present = isinstance(version, str) and isinstance(preimage, str) and isinstance(digest, str)
    if absent:
        if has_carrier:
            raise ValueError("routine snapshot cache authority is mixed with authority carriers")
        policy = LEGACY_CACHE_AUTHORITY_V1
        return CacheAuthorityBinding(
            policy=policy,
            preimage=canonicalize_cache_authority(policy),
            hash=cache_authority_hash(policy),
        )
    if not present or version != POLICY_VERSION:
        raise ValueError("routine snapshot cache authority format is malformed or unknown")
    if not isinstance(preimage, str) or not isinstance(digest, str):
        raise ValueError("routine snapshot cache authority values must be strings")
    try:
        policy = CacheAuthorityPolicy.model_validate_json(preimage)
    except ValueError as exc:
        raise ValueError("routine snapshot has invalid cache authority preimage") from exc
    if canonicalize_cache_authority(policy) != preimage or cache_authority_hash(policy) != digest:
        raise ValueError("routine snapshot cache authority hash verification failed")
    return CacheAuthorityBinding(policy=policy, preimage=preimage, hash=digest)


def cache_authority_is_new_format(projection: GraphProjection) -> bool:
    record = projection.records.by_id.get("routine-snapshot-record")
    return bool(
        record is not None
        and getattr(getattr(record, "value", None), "cache_authority_version", None)
    )
