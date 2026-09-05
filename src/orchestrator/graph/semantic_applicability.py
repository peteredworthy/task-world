"""Fact-backed semantic applicability for repository-write workers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, cast

from orchestrator.graph.models import (
    CandidateRecord,
    CheckResultRecord,
    GapClassificationRecord,
    RequirementRecord,
    SemanticArtifactRecord,
    VerificationReportRecord,
)
from orchestrator.graph.reliable_plan_evaluation import ReliablePlanAssignmentCarrier
from orchestrator.graph.projection_queries import (
    failed_verification_results_by_record_id_view,
    input_bindings_view,
    leases_view,
    node_payload_view,
    output_record_payloads_view,
    semantic_schema_declarations_view,
    task_candidates_view,
    verifier_verdicts_view,
)
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.semantic_artifacts import accepted_semantic_declaration


WriteWorkerSemanticApplicability = Literal[
    "not_applicable",
    "general_write",
    "effectful_batch",
    "declared_batch_correction",
    "semantic_plan_revision",
    "invalid_declared_batch_write",
]


def correction_superseded_task_region_id(
    projection: GraphProjection,
    node: Mapping[str, Any],
    *,
    require_stamped_lineage: bool = True,
) -> str | None:
    """Return the failed region a proven rejected-candidate correction replaces."""
    if (
        node.get("kind") != "worker"
        or node.get("semantic_stage") != "corrective_work"
        or node.get("base_snapshot_selection") != "rejected_candidate"
    ):
        return None
    failed_record_id = node.get("failed_verification_record_id")
    failed_candidate_id = node.get("failed_candidate_id")
    batch_id = node.get("declared_batch_id")
    if (
        not isinstance(failed_record_id, str)
        or not isinstance(failed_candidate_id, str)
        or node.get("base_snapshot_candidate_id") != failed_candidate_id
        or not isinstance(batch_id, str)
    ):
        return None

    records = output_record_payloads_view(projection)
    report = records.get(failed_record_id)
    failed = failed_verification_results_by_record_id_view(projection).get(failed_record_id)
    if (
        not isinstance(report, VerificationReportRecord)
        or report.outcome != "failed"
        or report.candidate_id != failed_candidate_id
        or failed is None
        or failed.candidate_id != failed_candidate_id
        or failed.node_id != report.producer_node_id
    ):
        return None
    if require_stamped_lineage and (
        node.get("recovery_reason") != "failed_verification"
        or node.get("recovery_of_node_id") != report.producer_node_id
        or node.get("recovery_of_record_id") != failed_record_id
    ):
        return None
    failed_verifier = node_payload_view(projection, report.producer_node_id) or {}
    failed_region_id = failed.task_region_id or failed_verifier.get("task_region_id")
    if (
        not isinstance(failed_region_id, str)
        or failed_verifier.get("kind") != "verifier"
        or failed_verifier.get("semantic_stage") != "effectful_batch"
        or failed_verifier.get("declared_batch_id") != batch_id
    ):
        return None

    failed_candidate = next(
        (
            record
            for record in records.values()
            if isinstance(record, CandidateRecord)
            and record.candidate_id == failed_candidate_id
            and record.task_region_id == failed_region_id
        ),
        None,
    )
    if failed_candidate is None:
        return None
    failed_producer = node_payload_view(projection, failed_candidate.producer_node_id) or {}
    if (
        failed_producer.get("kind") != "worker"
        or failed_producer.get("semantic_stage") != "effectful_batch"
        or failed_producer.get("declared_batch_id") != batch_id
        or failed_producer.get("task_region_id") != failed_region_id
    ):
        return None
    candidates = task_candidates_view(projection).get(failed_region_id, [])
    if not candidates:
        return None
    latest = max(candidates, key=lambda candidate: (candidate.attempt_number, candidate.position))
    verdict = verifier_verdicts_view(projection).get(failed_candidate_id)
    if latest.candidate_id != failed_candidate_id or verdict is None or verdict.verdict != "failed":
        return None
    return failed_region_id


def accepted_declared_batch_ids(projection: GraphProjection) -> set[str]:
    """Return batch identities from accepted typed semantic artifacts."""
    batch_ids: set[str] = set()
    for record in output_record_payloads_view(projection).values():
        if not isinstance(record, SemanticArtifactRecord):
            continue
        if record.value.authority_status != "accepted" or record.value.content is None:
            continue
        raw_batches = record.value.content.get("batches")
        if not isinstance(raw_batches, Sequence) or isinstance(raw_batches, (str, bytes)):
            continue
        for raw_batch in cast(Sequence[Any], raw_batches):
            if isinstance(raw_batch, str):
                batch_ids.add(raw_batch)
            elif isinstance(raw_batch, Mapping):
                typed_batch = cast(Mapping[str, Any], raw_batch)
                batch_id = typed_batch.get("batch_id", typed_batch.get("id"))
                if isinstance(batch_id, str):
                    batch_ids.add(batch_id)
    return batch_ids


def classify_write_worker_semantics(
    node_id: str,
    node: Mapping[str, Any],
    projection: GraphProjection,
    *,
    edges: Iterable[Mapping[str, Any]],
    nodes: Mapping[str, Mapping[str, Any]] | None = None,
) -> WriteWorkerSemanticApplicability:
    """Classify a write worker from immutable graph records and topology.

    A corrective semantic-plan revision is deliberately narrow. It is proven
    by accepted artifact/schema lineage, one exact failed plan-verification
    report, matching requirements, and the worker's typed candidate/artifact
    consumer topology. Names, prose, actor role, and stage alone confer no
    authority.
    """
    if node.get("kind") != "worker" or node.get("access_mode") != "write":
        return "not_applicable"
    if node.get("semantic_stage") == "effectful_batch":
        return "effectful_batch"

    edge_list = [dict(edge) for edge in edges]
    if _is_exact_semantic_plan_revision(
        node_id,
        node,
        projection,
        edge_list,
        nodes=nodes or {},
    ):
        return "semantic_plan_revision"
    if _is_exact_declared_batch_correction(
        node_id,
        node,
        projection,
        edge_list,
        nodes=nodes or {},
    ):
        return "declared_batch_correction"
    if accepted_declared_batch_ids(projection):
        return "invalid_declared_batch_write"
    return "general_write"


def _is_exact_declared_batch_correction(
    node_id: str,
    node: Mapping[str, Any],
    projection: GraphProjection,
    edges: list[dict[str, Any]],
    *,
    nodes: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Recognize the one correction shape allowed beside declared batches."""
    if (
        node.get("semantic_stage") != "corrective_work"
        or node.get("effect_contract") != "effectful_write"
        or node.get("access_mode") != "write"
        or node.get("reliable_plan_assignment_role") != "correction_worker"
    ):
        return False
    raw_carrier = node.get("reliable_plan_assignment_carrier")
    try:
        carrier = ReliablePlanAssignmentCarrier.model_validate(raw_carrier)
    except (TypeError, ValueError):
        return False
    assignment = carrier.assignment_for("correction_worker")
    if (
        node.get("reliable_plan_skeleton_id") != carrier.skeleton_id
        or node.get("reliable_plan_selected_runner_type") != carrier.selected_runner_type
        or node.get("runner_model_override") != assignment.model
        or node.get("profile") != assignment.profile.value
    ):
        return False
    root = node_payload_view(projection, "root") or {}
    if root and (
        root.get("reliable_plan_skeleton_id") != carrier.skeleton_id
        or root.get("reliable_plan_assignment_carrier") != carrier.model_dump(mode="json")
    ):
        return False

    records = output_record_payloads_view(projection)
    incoming = [
        edge
        for edge in edges
        if edge.get("to_node_id") == node_id and edge.get("required") is not False
    ]
    report_edges = [edge for edge in incoming if edge.get("to_port") == "verification_report"]
    check_edges = [edge for edge in incoming if edge.get("to_port") == "check_result"]
    gap_edges = [edge for edge in incoming if edge.get("to_port") == "classified_gap"]
    if len(report_edges) != 1 or not check_edges or len(gap_edges) != 1:
        return False

    report_id = _exact_selected_record_id(
        report_edges[0],
        record_type="verification_report",
        schema="VerificationReport",
        terminal=("outcome", "failed"),
    )
    check_ids = [
        _exact_selected_record_id(
            edge,
            record_type="check_result",
            schema="CheckResult",
            terminal=("status", "failed"),
        )
        for edge in check_edges
    ]
    gap_id = _exact_selected_record_id(
        gap_edges[0],
        record_type="gap_classification",
        schema="GapClassification",
        terminal=("classification", "corrective_work_required"),
    )
    if report_id is None or gap_id is None or any(record_id is None for record_id in check_ids):
        return False
    typed_check_ids = cast(list[str], check_ids)
    if (
        node.get("failed_verification_record_id") != report_id
        or node.get("classified_gap_record_id") != gap_id
        or not isinstance(node.get("failed_check_record_ids"), list)
        or set(cast(list[Any], node["failed_check_record_ids"])) != set(typed_check_ids)
        or len(cast(list[Any], node["failed_check_record_ids"])) != len(typed_check_ids)
    ):
        return False

    report = records.get(report_id)
    checks = [records.get(record_id) for record_id in typed_check_ids]
    gap = records.get(gap_id)
    if (
        not isinstance(report, VerificationReportRecord)
        or report.outcome != "failed"
        or any(
            not isinstance(check, CheckResultRecord) or check.value.status != "failed"
            for check in checks
        )
    ):
        return False
    candidate_id = report.candidate_id
    if (
        any(cast(CheckResultRecord, check).candidate_id != candidate_id for check in checks)
        or node.get("failed_candidate_id") != candidate_id
    ):
        return False
    candidate = records.get(candidate_id)
    if not isinstance(candidate, CandidateRecord):
        return False
    producer = _node(nodes, projection, candidate.producer_node_id)
    batch_id = producer.get("declared_batch_id")
    if (
        producer.get("kind") != "worker"
        or producer.get("semantic_stage") != "effectful_batch"
        or not isinstance(batch_id, str)
        or batch_id not in accepted_declared_batch_ids(projection)
        or node.get("declared_batch_id") != batch_id
        or report.producer_node_id != report_edges[0].get("from_node_id")
        or any(
            cast(CheckResultRecord, check).producer_node_id != edge.get("from_node_id")
            for check, edge in zip(checks, check_edges, strict=True)
        )
    ):
        return False
    required_evidence = {report_id, *typed_check_ids}
    gap_source = gap_edges[0].get("from_node_id")
    if isinstance(gap, GapClassificationRecord):
        provenance = gap.provenance or {}
        cited = provenance.get("evaluated_record_ids")
        valid_gap = (
            gap.value.classification == "corrective_work_required"
            and gap.producer_node_id == gap_source
            and isinstance(cited, list)
            and required_evidence.issubset(
                {item for item in cast(list[Any], cited) if isinstance(item, str)}
            )
        )
    else:
        valid_gap = _is_active_exact_gap_promise(
            projection,
            gap_source,
            gap_id,
            required_evidence,
        )
    if not valid_gap:
        return False

    consumers = [
        edge
        for edge in edges
        if edge.get("from_node_id") == node_id
        and edge.get("from_port") == "candidate"
        and edge.get("to_port") == "candidate_under_test"
        and edge.get("required") is not False
        and isinstance(edge.get("to_node_id"), str)
        and _node(nodes, projection, cast(str, edge["to_node_id"])).get("kind") == "verifier"
    ]
    if len(consumers) != 1:
        return False
    consumer_id = consumers[0].get("to_node_id")
    consumer: Mapping[str, Any] = (
        _node(nodes, projection, consumer_id) if isinstance(consumer_id, str) else {}
    )
    selector = _selector(consumers[0])
    return (
        consumers[0].get("dependency_type", "input_binding") == "input_binding"
        and selector.get("record_type") == "candidate"
        and selector.get("schema") == "ImplementationCandidate"
        and consumer.get("kind") == "verifier"
        and consumer.get("role") == "verifier"
        and consumer.get("semantic_stage") == "corrective_work"
        and consumer.get("declared_batch_id") == batch_id
        and consumer.get("task_region_id") == node.get("task_region_id")
        and consumer.get("failed_candidate_id") == candidate_id
    )


def _is_active_exact_gap_promise(
    projection: GraphProjection,
    source_node_id: object,
    record_id: str,
    required_evidence: set[str],
) -> bool:
    """Recognize the callback-owned gap record promised by an active planner."""
    if not isinstance(source_node_id, str):
        return False
    source = node_payload_view(projection, source_node_id) or {}
    if source.get("kind") != "planner" or source.get("role") != "gap_planner":
        return False
    promised = any(
        lease.node_id == source_node_id
        and lease.state == "active"
        and record_id == f"classified-gap-{lease.execution_id}"
        for lease in leases_view(projection).values()
    )
    if not promised:
        return False
    bound_ids = {
        bound_id
        for binding in input_bindings_view(projection).get(source_node_id, {}).values()
        for bound_id in binding.record_ids
    }
    return required_evidence.issubset(bound_ids)


def _exact_selected_record_id(
    edge: Mapping[str, Any],
    *,
    record_type: str,
    schema: str,
    terminal: tuple[str, str],
) -> str | None:
    selector = _selector(edge)
    record_id = selector.get("record_id")
    if (
        edge.get("dependency_type", "input_binding") != "input_binding"
        or not isinstance(record_id, str)
        or selector.get("record_type") != record_type
        or selector.get("schema") != schema
        or selector.get(terminal[0]) != terminal[1]
    ):
        return None
    return record_id


def _is_exact_semantic_plan_revision(
    node_id: str,
    node: Mapping[str, Any],
    projection: GraphProjection,
    edges: list[dict[str, Any]],
    *,
    nodes: Mapping[str, Mapping[str, Any]],
) -> bool:
    if (
        node.get("semantic_stage") != "corrective_work"
        or node.get("effect_contract") != "effectful_write"
    ):
        return False
    artifact_id = node.get("recovery_of_record_id")
    if not isinstance(artifact_id, str) or node.get("failed_candidate_id") != artifact_id:
        return False
    schema_id = node.get("semantic_schema_id")
    schema_version = node.get("semantic_schema_version")
    if not isinstance(schema_id, str) or not isinstance(schema_version, int):
        return False

    records = output_record_payloads_view(projection)
    artifact = records.get(artifact_id)
    if not isinstance(artifact, SemanticArtifactRecord):
        return False
    if (
        artifact.value.authority_status != "accepted"
        or artifact.value.semantic_role != "implementation_plan"
        or artifact.value.schema_id != schema_id
        or artifact.value.schema_version != schema_version
    ):
        return False
    declaration = accepted_semantic_declaration(
        semantic_schema_declarations_view(projection), schema_id, schema_version
    )
    if declaration is None or declaration.value.semantic_role != "implementation_plan":
        return False
    producer = _node(nodes, projection, artifact.producer_node_id)
    if (
        producer.get("kind") != "worker"
        or producer.get("role") != "discovery"
        or producer.get("semantic_stage") != "discovery"
        or producer.get("access_mode") != "read_only"
        or producer.get("semantic_schema_id") != schema_id
        or producer.get("semantic_schema_version") != schema_version
    ):
        return False

    requirement_record_ids = _bound_requirement_record_ids(node, records)
    if requirement_record_ids is None or not requirement_record_ids:
        return False
    if not requirement_record_ids.issubset(set(artifact.value.requirement_ids)):
        return False

    report_edges = [
        edge
        for edge in edges
        if edge.get("to_node_id") == node_id
        and edge.get("to_port") == "verification_report"
        and edge.get("required") is not False
    ]
    if len(report_edges) != 1:
        return False
    report_edge = report_edges[0]
    selector = _selector(report_edge)
    report_id = selector.get("record_id")
    report_source = report_edge.get("from_node_id")
    if (
        not isinstance(report_id, str)
        or not isinstance(report_source, str)
        or report_edge.get("from_port") != "verification_report"
        or report_edge.get("dependency_type", "input_binding") != "input_binding"
        or selector.get("record_type") != "verification_report"
        or selector.get("schema") != "VerificationReport"
        or selector.get("outcome") != "failed"
    ):
        return False
    report = records.get(report_id)
    report_producer = _node(nodes, projection, report_source)
    if (
        not isinstance(report, VerificationReportRecord)
        or report.producer_node_id != report_source
        or report.outcome != "failed"
        or report.candidate_id != artifact_id
        or artifact_id not in report.candidate_record_ids
        or artifact_id not in report.evaluated_record_ids
        or not requirement_record_ids.issubset(set(report.evaluated_record_ids))
        or report_producer.get("kind") != "verifier"
        or report_producer.get("semantic_stage") != "plan_verification"
        or report_producer.get("semantic_schema_id") != schema_id
        or report_producer.get("semantic_schema_version") != schema_version
    ):
        return False
    if report.candidate_record_id is not None and report.candidate_record_id != artifact_id:
        return False

    semantic_consumers = [
        edge
        for edge in edges
        if edge.get("from_node_id") == node_id
        and edge.get("from_port") == "semantic_artifact"
        and edge.get("to_port") == "semantic_artifact"
        and edge.get("required") is not False
    ]
    if len(semantic_consumers) != 1:
        return False
    semantic_edge = semantic_consumers[0]
    semantic_selector = _selector(semantic_edge)
    consumer_id = semantic_edge.get("to_node_id")
    consumer: Mapping[str, Any] = (
        _node(nodes, projection, consumer_id) if isinstance(consumer_id, str) else {}
    )
    if (
        semantic_edge.get("dependency_type", "input_binding") != "input_binding"
        or semantic_selector.get("record_type") != "semantic_artifact"
        or semantic_selector.get("schema") != "SemanticArtifact"
        or semantic_selector.get("semantic_schema_id") != schema_id
        or semantic_selector.get("semantic_schema_version") != schema_version
        or consumer.get("kind") != "verifier"
        or consumer.get("task_region_id") != node.get("task_region_id")
        or consumer.get("failed_candidate_id") != artifact_id
    ):
        return False
    candidate_consumers = [
        edge
        for edge in edges
        if edge.get("from_node_id") == node_id
        and edge.get("from_port") == "candidate"
        and edge.get("to_node_id") == consumer_id
        and edge.get("to_port") == "candidate_under_test"
        and edge.get("required") is not False
    ]
    if len(candidate_consumers) != 1:
        return False
    candidate_selector = _selector(candidate_consumers[0])
    return (
        candidate_consumers[0].get("dependency_type", "input_binding") == "input_binding"
        and candidate_selector.get("record_type") == "candidate"
        and candidate_selector.get("schema") == "ImplementationCandidate"
    )


def _bound_requirement_record_ids(
    node: Mapping[str, Any],
    records: Mapping[str, object],
) -> set[str] | None:
    raw_ids = node.get("bound_requirement_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return None
    record_id_by_requirement_id = {
        record.value.id: record.record_id
        for record in records.values()
        if isinstance(record, RequirementRecord)
    }
    output: set[str] = set()
    for raw_id in cast(list[Any], raw_ids):
        if not isinstance(raw_id, str):
            return None
        if isinstance(records.get(raw_id), RequirementRecord):
            output.add(raw_id)
            continue
        record_id = record_id_by_requirement_id.get(raw_id)
        if record_id is None:
            return None
        output.add(record_id)
    return output


def _selector(edge: Mapping[str, Any]) -> Mapping[str, Any]:
    selector = edge.get("accepted_record_selector")
    return cast(Mapping[str, Any], selector) if isinstance(selector, Mapping) else {}


def _node(
    nodes: Mapping[str, Mapping[str, Any]],
    projection: GraphProjection,
    node_id: str,
) -> Mapping[str, Any]:
    return nodes.get(node_id) or node_payload_view(projection, node_id) or {}
