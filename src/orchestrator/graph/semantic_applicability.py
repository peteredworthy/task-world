"""Fact-backed semantic applicability for repository-write workers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, cast

from orchestrator.graph.models import (
    RequirementRecord,
    SemanticArtifactRecord,
    VerificationReportRecord,
)
from orchestrator.graph.projection_queries import (
    node_payload_view,
    output_record_payloads_view,
    semantic_schema_declarations_view,
)
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.semantic_artifacts import accepted_semantic_declaration


WriteWorkerSemanticApplicability = Literal[
    "not_applicable",
    "general_write",
    "effectful_batch",
    "semantic_plan_revision",
    "invalid_declared_batch_write",
]


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
    if accepted_declared_batch_ids(projection):
        return "invalid_declared_batch_write"
    return "general_write"


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
