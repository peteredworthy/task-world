"""Strict checkpoint codec and referential validation for the immutable scaffold."""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any, Callable, Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import PydanticSerializationError

from orchestrator.graph.projection_models import (
    PROJECTED_RECORD_TYPES,
    ImmutableGraphProjection,
    ProjectedAnalysisSummaryRecord,
    ProjectedArtifactReferenceRecord,
    ProjectedAuthorityDecisionRecord,
    ProjectedAuthorityRequestRecord,
    ProjectedCandidateRecord,
    ProjectedCheckResultRecord,
    ProjectedCompletionDecisionRecord,
    ProjectedDecisionRecord,
    ProjectedDecisionRequestRecord,
    ProjectedFailureRecord,
    ProjectedFanOutInputsRecord,
    ProjectedFileStateRecord,
    ProjectedGapClassificationRecord,
    ProjectedGraphPatchProposalRecord,
    ProjectedJoinResultRecord,
    ProjectedRecoveryPlanRecord,
    ProjectedRequirementRecord,
    ProjectedRoutineSnapshotRecord,
    ProjectedRunContextRecord,
    ProjectedVerificationReportRecord,
    ProjectedRecordBase,
)


class ProjectionCheckpointCodecError(ValueError):
    """A Pydantic serialization failure while writing an immutable checkpoint."""


class ProjectionIntegrityDiagnostic(BaseModel):
    """One deterministic explanation of an invalid checkpoint relationship."""

    model_config = ConfigDict(frozen=True)
    path: str
    reason: str


class ProjectionCheckpointIntegrityError(ValueError):
    """All referential failures found in one immutable projection checkpoint."""

    def __init__(self, diagnostics: tuple[ProjectionIntegrityDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(f"{item.path}: {item.reason}" for item in diagnostics))


def immutable_projection_to_checkpoint(projection: ImmutableGraphProjection) -> dict[str, Any]:
    """Return the scaffold as ordinary JSON-compatible Python values."""
    try:
        return projection.model_dump(mode="json")
    except PydanticSerializationError as error:
        raise ProjectionCheckpointCodecError("immutable projection serialization failed") from error


def immutable_projection_from_checkpoint(raw: object) -> ImmutableGraphProjection:
    """Strictly validate a canonical checkpoint and its cross-group references."""
    _validate_canonical_checkpoint(raw)
    projection = ImmutableGraphProjection.model_validate(raw)
    validate_projection_integrity(projection)
    return projection


def _validate_canonical_checkpoint(raw: object) -> None:
    """Reject non-JSON transport values before immutable model conversion."""

    def reject(path: tuple[str | int, ...], value: object, message: str) -> None:
        raise ValidationError.from_exception_data(
            "ImmutableGraphProjection",
            [
                {
                    "type": "value_error",
                    "loc": path,
                    "input": value,
                    "ctx": {"error": ValueError(message)},
                }
            ],
        )

    if type(raw) is not dict:
        reject((), raw, "checkpoint root must be an exact JSON object")

    active_ids: set[int] = set()

    def visit(value: object, path: tuple[str | int, ...], depth: int) -> None:
        if depth > 100:
            reject(path, value, "checkpoint JSON depth must not exceed 100")
        value_type = type(value)
        if value is None or value_type in {bool, int, str}:
            return
        if value_type is float:
            if not isfinite(cast(float, value)):
                reject(path, value, "checkpoint JSON numbers must be finite")
            return
        if value_type is list:
            value_id = id(value)
            if value_id in active_ids:
                reject(path, value, "checkpoint JSON cannot contain a cycle")
            active_ids.add(value_id)
            try:
                for index, child in enumerate(cast(list[object], value)):
                    visit(child, (*path, index), depth + 1)
            finally:
                active_ids.remove(value_id)
            return
        if value_type is dict:
            value_id = id(value)
            if value_id in active_ids:
                reject(path, value, "checkpoint JSON cannot contain a cycle")
            dictionary = cast(dict[object, object], value)
            if any(type(key) is not str for key in dictionary):
                reject(path, value, "checkpoint JSON objects must have string keys")
            active_ids.add(value_id)
            try:
                for key, child in dictionary.items():
                    visit(child, (*path, cast(str, key)), depth + 1)
            finally:
                active_ids.remove(value_id)
            return
        reject(
            path, value, f"checkpoint must contain canonical JSON values, not {value_type.__name__}"
        )

    root = cast(dict[object, object], raw)
    visit(cast(object, root), (), 0)


def validate_projection_integrity(projection: ImmutableGraphProjection) -> None:
    """Validate all stored references without mutating or repairing ``projection``."""
    diagnostics: list[ProjectionIntegrityDiagnostic] = []

    def fail(path: str, reason: str) -> None:
        diagnostics.append(ProjectionIntegrityDiagnostic(path=path, reason=reason))

    nodes, tasks, records = projection.nodes, projection.tasks, projection.records.by_id

    def reference(values: Any, value: str | None, path: str, kind: str) -> None:
        if value is not None and value not in values:
            fail(path, f"references missing {kind} {value!r}")

    def node(value: str | None, path: str) -> None:
        reference(nodes, value, path, "node")

    def task(value: str | None, path: str) -> None:
        reference(tasks, value, path, "task")

    def record(value: str | None, path: str) -> None:
        reference(records, value, path, "record")

    candidate_paths: dict[str, list[str]] = defaultdict(list)
    for task_id, item in tasks.items():
        for index, candidate_item in enumerate(item.candidates):
            candidate_paths[candidate_item.candidate_id].append(
                f"tasks.{task_id}.candidates[{index}].candidate_id"
            )
    for record_id, item in records.items():
        for candidate_id, suffix in _record_candidate_identities(item):
            candidate_paths[candidate_id].append(f"records.by_id.{record_id}.{suffix}")

    def candidate(value: str | None, path: str) -> None:
        if value is None:
            return
        paths = candidate_paths.get(value, [])
        if not paths:
            fail(path, f"references missing candidate {value!r}")
        elif len(paths) > 1:
            fail(path, f"references ambiguous candidate {value!r}: {', '.join(sorted(paths))}")

    for node_id, item in nodes.items():
        base = f"nodes.{node_id}"
        if item.spec.node_id != node_id:
            fail(f"{base}.spec.node_id", f"must equal map key {node_id!r}")
        task(item.spec.task_region_id, f"{base}.spec.task_region_id")
        if item.spec.authority_request_record is not None:
            envelope = item.spec.authority_request_record
            record(envelope.record_id, f"{base}.spec.authority_request_record.record_id")
            node(
                envelope.producer_node_id, f"{base}.spec.authority_request_record.producer_node_id"
            )
            node(
                envelope.value.target_node_id,
                f"{base}.spec.authority_request_record.value.target_node_id",
            )
            task(
                envelope.value.target_region_id,
                f"{base}.spec.authority_request_record.value.target_region_id",
            )
        if item.spec.decision_request is not None:
            node(
                item.spec.decision_request.target_node_id,
                f"{base}.spec.decision_request.target_node_id",
            )
            task(
                item.spec.decision_request.target_region_id,
                f"{base}.spec.decision_request.target_region_id",
            )
        if item.spec.authority_request is not None:
            node(
                item.spec.authority_request.target_node_id,
                f"{base}.spec.authority_request.target_node_id",
            )
            task(
                item.spec.authority_request.target_region_id,
                f"{base}.spec.authority_request.target_region_id",
            )
        for field in ("candidate_id", "failed_candidate_id"):
            candidate(getattr(item.runtime, field), f"{base}.runtime.{field}")

    for task_id, item in tasks.items():
        for number, candidate_item in enumerate(item.candidates):
            base = f"tasks.{task_id}.candidates[{number}]"
            for index, record_id in enumerate(candidate_item.file_state_record_ids):
                record(record_id, f"{base}.file_state_record_ids[{index}]")
            for index, related_task in enumerate(candidate_item.supersedes_task_region_ids):
                task(related_task, f"{base}.supersedes_task_region_ids[{index}]")

    expected_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for record_id, item in records.items():
        base = f"records.by_id.{record_id}"
        if item.record_id != record_id:
            fail(f"{base}.record_id", f"must equal map key {record_id!r}")
        node(item.producer_node_id, f"{base}.producer_node_id")
        if item.producer_node_id is not None:
            expected_index[item.producer_node_id][item.port].append(record_id)
        _record_relations(item, base, record, task, node, candidate, projection, fail)

    for node_id, ports in projection.records.ids_by_node_port.items():
        node(node_id, f"records.ids_by_node_port.{node_id}")
        for port, ids in ports.items():
            base = f"records.ids_by_node_port.{node_id}.{port}"
            if port not in expected_index.get(node_id, {}):
                fail(base, "is not a canonical record index")
            if ids != tuple(expected_index.get(node_id, {}).get(port, ())):
                fail(base, "must exactly derive record IDs for its node and port")
            for index, record_id in enumerate(ids):
                record(record_id, f"{base}[{index}]")
    for node_id, ports in expected_index.items():
        for port in ports:
            if (
                node_id not in projection.records.ids_by_node_port
                or port not in projection.records.ids_by_node_port[node_id]
            ):
                fail(
                    f"records.ids_by_node_port.{node_id}.{port}",
                    "is missing canonical record index",
                )

    for record_id, summary in projection.records.summaries_by_id.items():
        base = f"records.summaries_by_id.{record_id}"
        item = records.get(record_id)
        if item is None:
            fail(base, f"references missing record {record_id!r}")
            continue
        expected = (
            item.record_id,
            item.record_type,
            item.record_kind,
            item.schema_,
            item.producer_node_id,
            item.producer_port or item.port,
            item.graph_position,
        )
        actual = (
            summary.record_id,
            summary.record_type,
            summary.record_kind,
            summary.schema_,
            summary.producer_node_id,
            summary.producer_port,
            summary.position,
        )
        for field, left, right in zip(
            (
                "record_id",
                "record_type",
                "record_kind",
                "schema",
                "producer_node_id",
                "producer_port",
                "position",
            ),
            actual,
            expected,
            strict=True,
        ):
            if left != right:
                fail(f"{base}.{field}", "must derive from canonical record")
    for record_id in records:
        if record_id not in projection.records.summaries_by_id:
            fail(f"records.summaries_by_id.{record_id}", "is missing canonical record summary")

    _topology_relations(projection, node, record, fail)
    _planning_relations(projection, node, record, fail)
    _verification_relations(projection, node, task, record, candidate, fail)
    _governance_relations(projection, node, task, fail)
    _requirement_relations(projection, record, fail)
    _execution_relations(projection, node, task, record, fail)
    for index, node_id in enumerate(projection.scheduling.ready_node_ids):
        node(node_id, f"scheduling.ready_node_ids[{index}]")
    for field in ("tokens_by_node", "recorded_keys"):
        for node_id in getattr(projection.usage, field):
            node(node_id, f"usage.{field}.{node_id}")

    if diagnostics:
        raise ProjectionCheckpointIntegrityError(
            tuple(sorted(diagnostics, key=lambda item: (item.path, item.reason)))
        )


RecordResolver = Callable[[str | None, str], None]
RelationFamily = Literal[
    "node",
    "task",
    "record",
    "candidate",
    "requirement",
    "revision",
    "support",
    "lease",
    "cleanup",
    "edge",
    "session",
    "external",
]

# Every identifier-bearing projection path is deliberately catalogued.  A
# resolver family means it is checked against represented state; external
# means the value denotes an intentionally unrepresented system (git, command,
# artifact, execution, callback, or snapshot) rather than a graph relation.
RELATION_POLICY_CATALOG: dict[str, RelationFamily] = {
    "nodes.*.spec.task_region_id": "task",
    "nodes.*.spec.authority_request_record.record_id": "record",
    "nodes.*.spec.authority_request_record.producer_node_id": "node",
    "nodes.*.spec.authority_request_record.value.target_node_id": "node",
    "nodes.*.spec.authority_request_record.value.target_region_id": "task",
    "nodes.*.runtime.candidate_id": "candidate",
    "nodes.*.runtime.failed_candidate_id": "candidate",
    "tasks.*.candidates.*.file_state_record_ids": "record",
    "tasks.*.candidates.*.supersedes_task_region_ids": "task",
    "topology.edges.*.from_node_id": "node",
    "topology.edges.*.to_node_id": "node",
    "topology.input_bindings.*.*.edge_id": "edge",
    "topology.input_bindings.*.*.to_node_id": "node",
    "topology.input_bindings.*.*.record_ids": "record",
    "topology.input_bindings.*.*.supersedes_record_id": "record",
    "planning.successor_by_node": "node",
    "planning.accepted_patch_ids_by_node": "record",
    "planning.no_successor_patch_ids_by_node": "record",
    "planning.latest_no_successor_patch_id_by_node": "record",
    "planning.latest_routine_snapshot.record_id": "record",
    "planning.latest_routine_snapshot.producer_node_id": "node",
    "planning.session_id_by_node": "session",
    "planning.sessions.*.current_node_id": "node",
    "planning.sessions.*.carryover_record_id": "record",
    "verification.verdicts_by_node.*.candidate_id": "candidate",
    "verification.*_results_by_record_id.*.record_id": "record",
    "verification.*_results_by_record_id.*.node_id": "node",
    "verification.*_results_by_record_id.*.candidate_id": "candidate",
    "verification.*_results_by_record_id.*.task_region_id": "task",
    "verification.recovery_nodes_by_record_id": "record",
    "verification.check_results_by_node.*.record_id": "record",
    "verification.check_results_by_node.*.candidate_record_ids": "record",
    "verification.check_results_by_node.*.file_state_record_ids": "record",
    "verification.check_results_by_node.*.evaluated_record_ids": "record",
    "verification.invalid_test_blocks_by_task": "task",
    "governance.*_decisions_by_node.*.task_region_id": "task",
    "governance.*_decisions_by_node.*.appeal_node_id": "node",
    "governance.oversight_decisions_by_node.*.appealed_node_id": "node",
    "governance.decision_requests_by_node.*.target_node_id": "node",
    "governance.decision_requests_by_node.*.target_region_id": "task",
    "governance.authority_revision_blockers.*.node_id": "node",
    "governance.authority_revision_blockers.*.edge_id": "edge",
    "governance.authority_revision_blockers.*.from_node_id": "node",
    "governance.authority_revision_blockers.*.task_region_id": "task",
    "governance.authority_revision_blockers.*.requirement_id": "requirement",
    "governance.authority_revision_blockers.*.revision_id": "revision",
    "governance.authority_revision_blockers.*.support_ids": "support",
    "governance.authority_revision_blockers.*.proposal_id": "record",
    "requirements.revisions_by_id.*.previous_version_id": "revision",
    "requirements.active_version_id_by_requirement": "revision",
    "requirements.support_by_id.*.evidence_id": "record",
    "requirements.support_by_id.*.requirement_version_id": "revision",
    "execution.leases.*.node_id": "node",
    "execution.leases.*.task_region_id": "task",
    "execution.leases.*.session_id": "session",
    "execution.environment_failures_by_task.*.node_id": "node",
    "execution.environment_failures_by_task.*.task_region_id": "task",
    "execution.environment_failures_by_task.*.record_id": "record",
    "execution.callback_events_by_key.*.node_id": "node",
    "execution.callback_events_by_key.*.idempotency_key": "external",
    "execution.cleanup_requests_by_id.*.file_state_record_id": "record",
    "execution.cleanup_requests_by_id.*.producer_node_id": "node",
    "execution.applied_cleanup_ids": "cleanup",
    "usage.tokens_by_node": "node",
    "usage.recorded_keys": "node",
    "records.failure_record.value.failed_node_id": "node",
    "records.failure_record.value.lease_id": "lease",
    "records.file_state.cleanup_id": "cleanup",
    "records.file_state.supersedes_record_id": "record",
    "records.file_state.superseded_by_record_id": "record",
    "records.candidate.task_region_id": "task",
    "records.candidate.file_state_record_ids": "record",
    "records.check_result.candidate_id": "candidate",
    "records.check_result.task_region_id": "task",
    "records.check_result.value.cited_record_id": "record",
    "records.check_result.value.reused_verification_record_id": "record",
    "records.graph_patch_proposal.value.proposed_by_node_id": "node",
    "records.graph_patch_proposal.value.rationale_record_id": "record",
    "records.analysis_summary.value.source_record_ids": "record",
    "records.artifact_reference.value.source_record_ids": "record",
    "records.join_result.value.source_record_ids": "record",
    "records.verification_report.candidate_id": "candidate",
    "records.verification_report.task_region_id": "task",
    "records.verification_report.candidate_record_ids": "record",
    "records.*.git.ref": "external",
    "records.*.value.command_id": "external",
    "records.*.value.execution_id": "external",
    "records.*.snapshot_id": "external",
    "records.*.base_snapshot_id": "external",
    "records.*.cleanup_applied_event_id": "external",
}


def projection_relation_policy_catalog() -> dict[str, RelationFamily]:
    """Return the finite reviewed policy catalog without exposing mutable state."""
    return dict(RELATION_POLICY_CATALOG)


def _record_relations(
    item: ProjectedRecordBase,
    base: str,
    record: RecordResolver,
    task: RecordResolver,
    node: RecordResolver,
    candidate: RecordResolver,
    projection: ImmutableGraphProjection,
    fail: Callable[[str, str], None],
) -> None:
    policy = _RECORD_RELATION_POLICIES.get(type(item))
    if policy is None:
        raise RuntimeError(f"missing relation visitor for {type(item).__name__}")
    _visit_projected_record(item, base, record, task, node, candidate, projection, fail)


# Explicitly name both handled and relation-neutral record types.  This is an
# intentionally finite registry, not a reflection-derived count.
_RECORD_RELATION_POLICIES: dict[type[ProjectedRecordBase], str] = {
    ProjectedAnalysisSummaryRecord: "handled: source records",
    ProjectedArtifactReferenceRecord: "handled: source records",
    ProjectedAuthorityDecisionRecord: "neutral: decision value has no represented IDs",
    ProjectedAuthorityRequestRecord: "handled: authority targets",
    ProjectedCandidateRecord: "handled: candidate, task, and file-state references",
    ProjectedCheckResultRecord: "handled: candidate, task, and evaluation records",
    ProjectedCompletionDecisionRecord: "neutral: blockers are opaque structured diagnostics",
    ProjectedDecisionRecord: "neutral: decision scope/actor IDs are external",
    ProjectedDecisionRequestRecord: "handled: decision targets",
    ProjectedFailureRecord: "handled: failed node, task, and lease",
    ProjectedFanOutInputsRecord: "handled: candidate, task, and file-state references",
    ProjectedFileStateRecord: "handled: task, candidate, record, and cleanup references",
    ProjectedGapClassificationRecord: "handled: task region",
    ProjectedGraphPatchProposalRecord: "handled: proposer and rationale record",
    ProjectedJoinResultRecord: "handled: source records",
    ProjectedRecoveryPlanRecord: "neutral: responsible actor and patch JSON are external/opaque",
    ProjectedRequirementRecord: "handled: requirement supersession",
    ProjectedRoutineSnapshotRecord: "neutral: routine/source refs are external",
    ProjectedRunContextRecord: "neutral: routine identifiers are external",
    ProjectedVerificationReportRecord: "handled: candidate, task, records, and grades",
}

if set(_RECORD_RELATION_POLICIES) != set(PROJECTED_RECORD_TYPES):
    raise RuntimeError("projected record relation policies must exactly cover ProjectedRecord")


def _record_each(values: tuple[str, ...], path: str, resolve: RecordResolver) -> None:
    for index, value in enumerate(values):
        resolve(value, f"{path}[{index}]")


def _visit_projected_record(
    item: ProjectedRecordBase,
    base: str,
    record: RecordResolver,
    task: RecordResolver,
    node: RecordResolver,
    candidate: RecordResolver,
    projection: ImmutableGraphProjection,
    fail: Callable[[str, str], None],
) -> None:
    """Typed visitor over every concrete public ProjectedRecord member."""
    requirement_ids = {
        revision.requirement_id for revision in projection.requirements.revisions_by_id.values()
    }

    if isinstance(item, ProjectedAnalysisSummaryRecord):
        _record_each(item.value.source_record_ids, f"{base}.value.source_record_ids", record)
    elif isinstance(item, ProjectedArtifactReferenceRecord):
        _record_each(item.value.source_record_ids, f"{base}.value.source_record_ids", record)
    elif isinstance(item, ProjectedAuthorityDecisionRecord):
        return
    elif isinstance(item, ProjectedAuthorityRequestRecord):
        node(item.value.target_node_id, f"{base}.value.target_node_id")
        task(item.value.target_region_id, f"{base}.value.target_region_id")
    elif isinstance(item, ProjectedCandidateRecord):
        candidate(item.candidate_id, f"{base}.candidate_id")
        task(item.task_region_id, f"{base}.task_region_id")
        record(item.file_state_record_id, f"{base}.file_state_record_id")
        _record_each(item.file_state_record_ids, f"{base}.file_state_record_ids", record)
        record(item.value.file_state_record_id, f"{base}.value.file_state_record_id")
        _record_each(
            item.value.file_state_record_ids, f"{base}.value.file_state_record_ids", record
        )
        task(item.supersedes_task_region_id, f"{base}.supersedes_task_region_id")
        for index, value in enumerate(item.supersedes_task_region_ids):
            task(value, f"{base}.supersedes_task_region_ids[{index}]")
        for index, value in enumerate(item.value.requirements_addressed):
            if value not in requirement_ids:
                fail(
                    f"{base}.value.requirements_addressed[{index}]",
                    f"references missing requirement {value!r}",
                )
    elif isinstance(item, ProjectedCheckResultRecord):
        candidate(item.candidate_id, f"{base}.candidate_id")
        task(item.task_region_id, f"{base}.task_region_id")
        record(item.candidate_record_id, f"{base}.candidate_record_id")
        for field, values in (
            ("candidate_record_ids", item.candidate_record_ids),
            ("file_state_record_ids", item.file_state_record_ids),
            ("verification_report_record_ids", item.verification_report_record_ids),
            ("evaluated_record_ids", item.evaluated_record_ids),
            ("value.candidate_record_ids", item.value.candidate_record_ids),
            ("value.file_state_record_ids", item.value.file_state_record_ids),
            ("value.verification_report_record_ids", item.value.verification_report_record_ids),
            ("value.evaluated_record_ids", item.value.evaluated_record_ids),
        ):
            _record_each(values, f"{base}.{field}", record)
        record(item.value.cited_record_id, f"{base}.value.cited_record_id")
        record(
            item.value.reused_verification_record_id, f"{base}.value.reused_verification_record_id"
        )
    elif isinstance(item, ProjectedCompletionDecisionRecord):
        return
    elif isinstance(item, ProjectedDecisionRecord):
        return
    elif isinstance(item, ProjectedDecisionRequestRecord):
        node(item.value.target_node_id, f"{base}.value.target_node_id")
        task(item.value.target_region_id, f"{base}.value.target_region_id")
    elif isinstance(item, ProjectedFailureRecord):
        task(item.task_region_id, f"{base}.task_region_id")
        node(item.value.failed_node_id, f"{base}.value.failed_node_id")
        if (
            item.value.lease_id is not None
            and item.value.lease_id not in projection.execution.leases
        ):
            fail(f"{base}.value.lease_id", f"references missing lease {item.value.lease_id!r}")
    elif isinstance(item, ProjectedFanOutInputsRecord):
        candidate(item.candidate_id, f"{base}.candidate_id")
        task(item.task_region_id, f"{base}.task_region_id")
        record(item.file_state_record_id, f"{base}.file_state_record_id")
        _record_each(item.file_state_record_ids, f"{base}.file_state_record_ids", record)
    elif isinstance(item, ProjectedFileStateRecord):
        task(item.task_region_id, f"{base}.task_region_id")
        candidate(item.candidate_id, f"{base}.candidate_id")
        record(item.supersedes_record_id, f"{base}.supersedes_record_id")
        record(item.superseded_by_record_id, f"{base}.superseded_by_record_id")
        if (
            item.cleanup_id is not None
            and item.cleanup_id not in projection.execution.cleanup_requests_by_id
        ):
            fail(f"{base}.cleanup_id", f"references missing cleanup request {item.cleanup_id!r}")
    elif isinstance(item, ProjectedGapClassificationRecord):
        task(item.value.task_region_id, f"{base}.value.task_region_id")
    elif isinstance(item, ProjectedGraphPatchProposalRecord):
        node(item.value.proposed_by_node_id, f"{base}.value.proposed_by_node_id")
        record(item.value.rationale_record_id, f"{base}.value.rationale_record_id")
    elif isinstance(item, ProjectedJoinResultRecord):
        _record_each(item.value.source_record_ids, f"{base}.value.source_record_ids", record)
    elif isinstance(item, ProjectedRecoveryPlanRecord):
        return
    elif isinstance(item, ProjectedRequirementRecord):
        return
    elif isinstance(item, ProjectedRoutineSnapshotRecord):
        return
    elif isinstance(item, ProjectedRunContextRecord):
        return
    elif isinstance(item, ProjectedVerificationReportRecord):
        candidate(item.candidate_id, f"{base}.candidate_id")
        task(item.task_region_id, f"{base}.task_region_id")
        record(item.candidate_record_id, f"{base}.candidate_record_id")
        for field, values in (
            ("candidate_record_ids", item.candidate_record_ids),
            ("file_state_record_ids", item.file_state_record_ids),
            ("evaluated_record_ids", item.evaluated_record_ids),
        ):
            _record_each(values, f"{base}.{field}", record)
    else:  # pragma: no cover - registry equality makes this defensive only.
        raise RuntimeError(f"unhandled projected record {type(item).__name__}")


def _record_candidate_identities(item: ProjectedRecordBase) -> tuple[tuple[str, str], ...]:
    if isinstance(
        item,
        (ProjectedCandidateRecord, ProjectedCheckResultRecord, ProjectedVerificationReportRecord),
    ):
        return ((item.candidate_id, "candidate_id"),)
    if isinstance(item, ProjectedFanOutInputsRecord) and item.candidate_id is not None:
        return ((item.candidate_id, "candidate_id"),)
    if isinstance(item, ProjectedFileStateRecord) and item.candidate_id is not None:
        return ((item.candidate_id, "candidate_id"),)
    return ()


def _topology_relations(
    projection: ImmutableGraphProjection,
    node: Callable[[str | None, str], None],
    record: Callable[[str | None, str], None],
    fail: Callable[[str, str], None],
) -> None:
    topology = projection.topology
    inbound: dict[str, list[str]] = defaultdict(list)
    outbound: dict[str, list[str]] = defaultdict(list)
    for edge_id, edge in topology.edges.items():
        base = f"topology.edges.{edge_id}"
        if edge.edge_id != edge_id:
            fail(f"{base}.edge_id", f"must equal map key {edge_id!r}")
        node(edge.from_node_id, f"{base}.from_node_id")
        node(edge.to_node_id, f"{base}.to_node_id")
        inbound[edge.to_node_id].append(edge_id)
        outbound[edge.from_node_id].append(edge_id)
    for field, expected in (("inbound_edge_ids", inbound), ("outbound_edge_ids", outbound)):
        actual = getattr(topology, field)
        for node_id in set(actual) | set(expected):
            if node_id not in expected:
                fail(f"topology.{field}.{node_id}", "is not a canonical adjacency key")
            if actual.get(node_id, ()) != tuple(expected.get(node_id, ())):
                fail(
                    f"topology.{field}.{node_id}",
                    f"must exactly derive {field.removesuffix('_edge_ids')} edge IDs",
                )
    for node_id, ports in topology.input_bindings.items():
        node(node_id, f"topology.input_bindings.{node_id}")
        for port, binding in ports.items():
            base = f"topology.input_bindings.{node_id}.{port}"
            if binding.to_node_id != node_id:
                fail(f"{base}.to_node_id", f"must equal outer node key {node_id!r}")
            if binding.to_port != port:
                fail(f"{base}.to_port", f"must equal outer port key {port!r}")
            if binding.edge_id is not None:
                edge = topology.edges.get(binding.edge_id)
                if edge is None:
                    fail(f"{base}.edge_id", f"references missing edge {binding.edge_id!r}")
                elif (edge.to_node_id, edge.to_port) != (node_id, port):
                    fail(f"{base}.edge_id", "must target the binding node and port")
            for index, record_id in enumerate(binding.record_ids):
                record(record_id, f"{base}.record_ids[{index}]")
            record(binding.supersedes_record_id, f"{base}.supersedes_record_id")
            if binding.record_bound_positions is not None and set(
                binding.record_bound_positions
            ) != set(binding.record_ids):
                fail(f"{base}.record_bound_positions", "must have exactly one entry per record ID")


def _planning_relations(
    projection: ImmutableGraphProjection,
    node: Callable[[str | None, str], None],
    record: Callable[[str | None, str], None],
    fail: Callable[[str, str], None],
) -> None:
    planning = projection.planning
    for node_id, successor in planning.successor_by_node.items():
        node(node_id, f"planning.successor_by_node.{node_id}")
        node(successor, f"planning.successor_by_node.{node_id}")
    for field in ("accepted_patch_ids_by_node", "no_successor_patch_ids_by_node"):
        for node_id, ids in getattr(planning, field).items():
            node(node_id, f"planning.{field}.{node_id}")
            for index, record_id in enumerate(ids):
                record(record_id, f"planning.{field}.{node_id}[{index}]")
    for node_id, record_id in planning.latest_no_successor_patch_id_by_node.items():
        node(node_id, f"planning.latest_no_successor_patch_id_by_node.{node_id}")
        record(record_id, f"planning.latest_no_successor_patch_id_by_node.{node_id}")
        if record_id not in planning.no_successor_patch_ids_by_node.get(node_id, ()):
            fail(
                f"planning.latest_no_successor_patch_id_by_node.{node_id}",
                "must appear in no-successor patch IDs",
            )
    if planning.latest_routine_snapshot is not None:
        record(
            planning.latest_routine_snapshot.record_id, "planning.latest_routine_snapshot.record_id"
        )
        node(
            planning.latest_routine_snapshot.producer_node_id,
            "planning.latest_routine_snapshot.producer_node_id",
        )
    for field in ("generation_by_node", "session_id_by_node", "region_label_by_node"):
        for node_id in getattr(planning, field):
            node(node_id, f"planning.{field}.{node_id}")
    for node_id, session_id in planning.session_id_by_node.items():
        if session_id not in planning.sessions:
            fail(
                f"planning.session_id_by_node.{node_id}",
                f"references missing session {session_id!r}",
            )
    for session_id, session in planning.sessions.items():
        node(session.current_node_id, f"planning.sessions.{session_id}.current_node_id")
        record(session.carryover_record_id, f"planning.sessions.{session_id}.carryover_record_id")


def _verification_relations(
    projection: ImmutableGraphProjection,
    node: Callable[[str | None, str], None],
    task: Callable[[str | None, str], None],
    record: Callable[[str | None, str], None],
    candidate: Callable[[str | None, str], None],
    fail: Callable[[str, str], None],
) -> None:
    value = projection.verification
    for node_id, verdict in value.verdicts_by_node.items():
        node(node_id, f"verification.verdicts_by_node.{node_id}")
        candidate(verdict.candidate_id, f"verification.verdicts_by_node.{node_id}.candidate_id")
    for result_name, results in (
        ("passed", value.passed_results_by_record_id),
        ("failed", value.failed_results_by_record_id),
    ):
        for record_id, result in results.items():
            base = f"verification.{result_name}_results_by_record_id.{record_id}"
            if result.record_id != record_id:
                fail(f"{base}.record_id", f"must equal map key {record_id!r}")
            record(record_id, base)
            node(result.node_id, f"{base}.node_id")
            task(result.task_region_id, f"{base}.task_region_id")
            candidate(result.candidate_id, f"{base}.candidate_id")
    for index, candidate_id in enumerate(value.passed_candidate_ids):
        candidate(candidate_id, f"verification.passed_candidate_ids[{index}]")
    for candidate_id in value.failed_candidate_ids:
        candidate(candidate_id, f"verification.failed_candidate_ids.{candidate_id}")
    for record_id, recoveries in value.recovery_nodes_by_record_id.items():
        record(record_id, f"verification.recovery_nodes_by_record_id.{record_id}")
        for index, recovery in enumerate(recoveries):
            node(
                recovery.node_id,
                f"verification.recovery_nodes_by_record_id.{record_id}[{index}].node_id",
            )
    for node_id, result in value.check_results_by_node.items():
        base = f"verification.check_results_by_node.{node_id}"
        if result.node_id != node_id:
            fail(f"{base}.node_id", f"must equal map key {node_id!r}")
        node(node_id, base)
        task(result.task_region_id, f"{base}.task_region_id")
        record(result.record_id, f"{base}.record_id")
        for field in ("candidate_record_ids", "file_state_record_ids", "evaluated_record_ids"):
            for index, record_id in enumerate(getattr(result, field)):
                record(record_id, f"{base}.{field}[{index}]")
    for task_id in value.invalid_test_blocks_by_task:
        task(task_id, f"verification.invalid_test_blocks_by_task.{task_id}")
        candidate(
            value.invalid_test_blocks_by_task[task_id].candidate_id,
            f"verification.invalid_test_blocks_by_task.{task_id}.candidate_id",
        )


def _governance_relations(
    projection: ImmutableGraphProjection,
    node: Callable[[str | None, str], None],
    task: Callable[[str | None, str], None],
    fail: Callable[[str, str], None],
) -> None:
    value = projection.governance
    for field in (
        "pending_appeals_by_node",
        "node_gate_decisions",
        "approval_decisions_by_node",
        "authority_decisions_by_node",
        "oversight_decisions_by_node",
        "decision_requests_by_node",
    ):
        for node_id, item in getattr(value, field).items():
            base = f"governance.{field}.{node_id}"
            node(node_id, base)
            if hasattr(item, "node_id") and item.node_id != node_id:
                fail(f"{base}.node_id", f"must equal map key {node_id!r}")
            task(getattr(item, "task_region_id", None), f"{base}.task_region_id")
            for related in ("appeal_node_id", "appealed_node_id", "target_node_id"):
                node(getattr(item, related, None), f"{base}.{related}")
    for field in ("configured_gates_by_task", "gate_decisions_by_task"):
        for task_id in getattr(value, field):
            task(task_id, f"governance.{field}.{task_id}")
    for blocker_id, blocker in value.authority_revision_blockers.items():
        base = f"governance.authority_revision_blockers.{blocker_id}"
        node(blocker.node_id, f"{base}.node_id")
        task(blocker.task_region_id, f"{base}.task_region_id")
        if blocker.edge_id is not None and blocker.edge_id not in projection.topology.edges:
            fail(f"{base}.edge_id", f"references missing edge {blocker.edge_id!r}")
        node(blocker.from_node_id, f"{base}.from_node_id")
        if blocker.proposal_id is not None and blocker.proposal_id not in projection.records.by_id:
            fail(f"{base}.proposal_id", f"references missing record {blocker.proposal_id!r}")
        revision = (
            projection.requirements.revisions_by_id.get(blocker.revision_id)
            if blocker.revision_id is not None
            else None
        )
        if blocker.revision_id is not None and revision is None:
            fail(
                f"{base}.revision_id",
                f"references missing requirement revision {blocker.revision_id!r}",
            )
        if blocker.requirement_id is not None and blocker.requirement_id not in {
            item.requirement_id for item in projection.requirements.revisions_by_id.values()
        }:
            fail(
                f"{base}.requirement_id",
                f"references missing requirement {blocker.requirement_id!r}",
            )
        if (
            revision is not None
            and blocker.requirement_id is not None
            and revision.requirement_id != blocker.requirement_id
        ):
            fail(f"{base}.revision_id", "must reference a revision for its requirement")
        for index, support_id in enumerate(blocker.support_ids):
            if support_id not in projection.requirements.support_by_id:
                fail(f"{base}.support_ids[{index}]", f"references missing support {support_id!r}")


def _requirement_relations(
    projection: ImmutableGraphProjection,
    record: Callable[[str | None, str], None],
    fail: Callable[[str, str], None],
) -> None:
    value = projection.requirements
    for version_id, revision in value.revisions_by_id.items():
        if revision.version_id != version_id:
            fail(
                f"requirements.revisions_by_id.{version_id}.version_id",
                f"must equal map key {version_id!r}",
            )
        if (
            revision.previous_version_id is not None
            and revision.previous_version_id not in value.revisions_by_id
        ):
            fail(
                f"requirements.revisions_by_id.{version_id}.previous_version_id",
                "references missing requirement revision",
            )
    for requirement_id, version_id in value.active_version_id_by_requirement.items():
        revision = value.revisions_by_id.get(version_id)
        if revision is None or revision.requirement_id != requirement_id:
            fail(
                f"requirements.active_version_id_by_requirement.{requirement_id}",
                "must reference a revision for its requirement",
            )
    for support_id, support in value.support_by_id.items():
        base = f"requirements.support_by_id.{support_id}"
        if support.support_id != support_id:
            fail(f"{base}.support_id", f"must equal map key {support_id!r}")
        record(support.evidence_id, f"{base}.evidence_id")
        revision = value.revisions_by_id.get(support.requirement_version_id)
        if revision is None or revision.requirement_id != support.requirement_id:
            fail(f"{base}.requirement_version_id", "must reference a revision for its requirement")


def _execution_relations(
    projection: ImmutableGraphProjection,
    node: Callable[[str | None, str], None],
    task: Callable[[str | None, str], None],
    record: Callable[[str | None, str], None],
    fail: Callable[[str, str], None],
) -> None:
    value = projection.execution
    for lease_id, lease in value.leases.items():
        base = f"execution.leases.{lease_id}"
        if lease.lease_id != lease_id:
            fail(f"{base}.lease_id", f"must equal map key {lease_id!r}")
        node(lease.node_id, f"{base}.node_id")
        task(lease.task_region_id, f"{base}.task_region_id")
        if lease.session_id is not None and lease.session_id not in projection.planning.sessions:
            fail(f"{base}.session_id", f"references missing session {lease.session_id!r}")
    for task_id, failure in value.environment_failures_by_task.items():
        base = f"execution.environment_failures_by_task.{task_id}"
        task(task_id, base)
        if failure.task_region_id is not None and failure.task_region_id != task_id:
            fail(f"{base}.task_region_id", f"must equal outer task key {task_id!r}")
        task(failure.task_region_id, f"{base}.task_region_id")
        node(failure.node_id, f"{base}.node_id")
        record(failure.record_id, f"{base}.record_id")
    for key, callback in value.callback_events_by_key.items():
        base = f"execution.callback_events_by_key.{key}"
        if callback.idempotency_key != key:
            fail(f"{base}.idempotency_key", f"must equal map key {key!r}")
        node(callback.node_id, f"{base}.node_id")
    for cleanup_id, cleanup in value.cleanup_requests_by_id.items():
        base = f"execution.cleanup_requests_by_id.{cleanup_id}"
        if cleanup.cleanup_id != cleanup_id:
            fail(f"{base}.cleanup_id", f"must equal map key {cleanup_id!r}")
        record(cleanup.file_state_record_id, f"{base}.file_state_record_id")
        node(cleanup.producer_node_id, f"{base}.producer_node_id")
    for cleanup_id in value.applied_cleanup_ids:
        if cleanup_id not in value.cleanup_requests_by_id:
            fail(
                f"execution.applied_cleanup_ids.{cleanup_id}", "references missing cleanup request"
            )
