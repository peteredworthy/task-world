"""Pure command applier for execution graph fixtures."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import posixpath
from typing import Any, Protocol, Sequence, cast

from orchestrator.graph.callbacks import (
    CallbackRequest,
)
from orchestrator.graph.command_bindings import canonicalize_check_command_definition
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy_for_edge,
    input_port_contract,
    merge_bound_record_ids,
    output_port_contract,
    validate_output_record,
)
from orchestrator.graph.macros import expand_patch_macros
from orchestrator.graph.events.file_state import (
    FILE_STATE_ACCEPTED,
    FILE_STATE_REJECTED,
)
from orchestrator.graph.models import (
    Actor,
    ActorKind,
    AnalysisSummaryRecord,
    ArtifactReferenceRecord,
    AuthorityDecisionRecord,
    AuthorityRequestRecord,
    CandidateRecord,
    CheckResultRecord,
    CompletionDecisionRecord,
    DecisionRequestRecord,
    DecisionRecord,
    EventEnvelope,
    FailureRecord,
    FileStateRecord,
    GraphPatchAcceptedPayload,
    GraphPatchProposalRecord,
    GraphPatchRejectedPayload,
    LegacyDeadInputPayloadBase,
    OutputRecord,
    PatchEnvelope,
    PatchOp,
    RecoveryPlanRecord,
    VerificationResultProjection,
    VerificationReportRecord,
    normalize_record_selector,
    record_selector_matches,
)
from orchestrator.graph.events.topology import (
    DEAD_INPUT_DETECTED,
    EDGE_CREATED,
    INPUT_BOUND,
    NODE_AUTHORITY_CHANGED,
    NODE_CREATED,
    NODE_DEFERRED,
    NODE_READY,
    NODE_RETIRED,
    NODE_STATE_CHANGED,
    PLAN_REGION_MARKED_SUSPECT,
    REVISION_CREATED,
    SESSION_STATE_CHANGED,
    PlannerSessionStateChangedPayload,
)
from orchestrator.graph.events.records import (
    OUTPUT_RECORD_ACCEPTED,
    VERIFICATION_FAILED,
    VERIFICATION_PASSED,
)
from orchestrator.graph.events.decisions import (
    APPEAL_OPENED,
)
from orchestrator.graph.patch_validator import validate_patch
from orchestrator.graph.projections import (
    GraphProjection,
    reduce_legacy_event,
)
from orchestrator.graph.scheduler import (
    NodeScheduleInfo,
    ResourceClaim,
    claims_conflict,
    evaluate_readiness,
    schedule,
)
from orchestrator.graph.events.lifecycle import (
    RUN_LIFECYCLE_CHANGED,
    COMMAND_REJECTED,
)
from orchestrator.graph.specifications import EventMetadata, EventSpecification, HydratedEvent
from orchestrator.graph.events.leases import (
    LEASE_EXPIRED,
    LEASE_GRANTED,
    LEASE_RELEASED,
    LEASE_RENEWED,
    LEASE_REVOKED,
)
from orchestrator.graph.events.patches import GRAPH_PATCH_ACCEPTED, GRAPH_PATCH_REJECTED


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def next_id(self, prefix: str = "") -> str: ...


RUN_LIFECYCLE_TRANSITIONS: dict[str, dict[str, str]] = {
    "accept_run": {"draft": "queued"},
    "start": {"queued": "active"},
    "pause": {"active": "pausing", "pausing": "paused"},
    # failed -> resuming is the operator reopen edge: it is only legal for a
    # human/operator actor (enforced in _apply_lifecycle_command), so a driver
    # or agent cannot silently un-fail a run. Added after the W2/W4
    # recovery_planner_no_successor false positives (2026-07-04) left runs
    # terminally failed with no kernel-legal recovery path.
    "resume": {"paused": "resuming", "resuming": "active", "failed": "resuming"},
    "cancel": {"active": "cancelling", "paused": "cancelling", "cancelling": "cancelled"},
    "complete": {"active": "completed"},
}
# Actor roles allowed to take the failed -> resuming reopen edge.
REOPEN_ACTOR_ROLES = {"human", "operator"}
TERMINAL_RUN_STATES = {"cancelled", "completed", "failed"}
NONTERMINAL_RUN_STATES = {
    "draft",
    "queued",
    "active",
    "pausing",
    "paused",
    "resuming",
    "cancelling",
}


_LEASE_EVENT_SPECS: dict[str, EventSpecification[Any]] = {
    specification.name: specification
    for specification in (
        LEASE_GRANTED,
        LEASE_RENEWED,
        LEASE_RELEASED,
        LEASE_REVOKED,
        LEASE_EXPIRED,
    )
}


_LIFECYCLE_EVENT_PAYLOAD_MODELS: dict[str, type[LegacyDeadInputPayloadBase]] = {}

_TOPOLOGY_EVENT_SPECS: dict[str, EventSpecification[Any]] = {
    specification.name: specification
    for specification in (
        NODE_CREATED,
        NODE_STATE_CHANGED,
        NODE_RETIRED,
        NODE_READY,
        NODE_DEFERRED,
        NODE_AUTHORITY_CHANGED,
        PLAN_REGION_MARKED_SUSPECT,
        EDGE_CREATED,
        INPUT_BOUND,
        SESSION_STATE_CHANGED,
        DEAD_INPUT_DETECTED,
        REVISION_CREATED,
    )
}


def typed_topology_event(
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    event_type: str,
    payload: dict[str, Any],
) -> EventEnvelope:
    """Validate a topology effect at its named specification boundary."""

    specification = _TOPOLOGY_EVENT_SPECS[event_type]
    return make_event(event_type, specification.validate_payload(payload).to_json())


def _typed_lifecycle_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    model = _LIFECYCLE_EVENT_PAYLOAD_MODELS.get(event_type)
    if model is None:
        return payload
    return model.model_validate(payload).model_dump(mode="json")


def apply_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    """Apply a pure graph command and return events a controller would append."""

    run_id = _run_id(events, payload)
    make_event = _event_factory(run_id, command_type, clock, id_gen)

    if command_type == "seed_compiled_events":
        return _apply_seed_compiled_events(projection, payload, make_event)
    if command_type == "submit_patch":
        return _apply_patch_command(projection, events, payload, make_event)
    if command_type == "schedule_tick":
        return schedule_tick_effects(projection, events, payload, clock, id_gen, make_event)
    if command_type == "reconcile":
        return _apply_reconcile(projection, events, make_event)
    if command_type == "raise_appeal":
        raise ValueError("raise_appeal requires typed command dispatch")
    if command_type == "record_decision":
        raise ValueError("record_decision requires typed command dispatch")
    if command_type == "record_gatekeeper_verdicts":
        raise ValueError("record_gatekeeper_verdicts requires typed command dispatch")
    if command_type == "record_requirement_revision":
        raise ValueError("record_requirement_revision requires typed command dispatch")
    if command_type == "record_support_evidence":
        raise ValueError("record_support_evidence requires typed command dispatch")
    if command_type == "record_cleanup_applied":
        raise ValueError("record_cleanup_applied requires typed command dispatch")
    return [
        _make_strict_event(
            make_event,
            COMMAND_REJECTED,
            {
                "command_type": command_type,
                "reason": f"unknown command: {command_type}",
            },
        )
    ]


def _release_active_node_leases(
    projection: GraphProjection,
    node_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for lease_id, lease in sorted(projection["leases"].items()):
        if lease.get("node_id") != node_id or lease.get("state") not in {"active", "suspended"}:
            continue
        payload: dict[str, Any] = {
            "node_id": node_id,
            "lease_id": lease_id,
        }
        generation = lease.get("generation")
        if isinstance(generation, int) and not isinstance(generation, bool):
            payload["generation"] = generation
        output.append(
            _make_strict_event(
                make_event, LEASE_RELEASED, _typed_lease_event_payload("lease_released", payload)
            )
        )
    return output


def _apply_seed_compiled_events(
    projection: GraphProjection,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    del projection, payload
    return [
        _command_rejected(
            make_event,
            "seed_compiled_events",
            "seed_compiled_events requires the typed graph catalog",
        )
    ]


def _file_state_changed_paths(record_payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for field in (
        "tracked",
        "untracked",
        "ignored",
        "external",
        "classifications",
        "residue",
        "rejected_paths",
    ):
        raw_entries = record_payload.get(field)
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in cast(list[Any], raw_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            if entry.get("classification") == "tool_cache":
                continue
            path = entry.get("path")
            if isinstance(path, str) and path not in paths:
                paths.append(path)
    return paths


def _repo_write_claim_covers_path(write_claims: list[ResourceClaim], path: str) -> bool:
    if not _file_state_path_is_repo_relative(path):
        return False
    requested = ResourceClaim(mode="read", scope="repo", paths=[path])
    return any(
        _claim_is_repo_write(claim) and claims_conflict(requested, claim) for claim in write_claims
    )


def _claim_is_repo_write(claim: ResourceClaim) -> bool:
    return claim.mode == "write" and claim.scope == "repo" and _claim_paths_are_repo_relative(claim)


def _claim_paths_are_repo_relative(claim: ResourceClaim) -> bool:
    return all(_file_state_path_is_repo_relative(path) for path in claim.paths)


def _file_state_path_is_repo_relative(path: str) -> bool:
    if path == "":
        return False
    if path.startswith("/"):
        return False
    normalized = posixpath.normpath(path)
    return normalized != ".." and not normalized.startswith("../")


def _accepted_file_state_record_events(
    projection: GraphProjection,
    expected_producer_node_id: str,
    record_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    record_payload.setdefault("producer_node_id", expected_producer_node_id)
    record_payload.setdefault("port", "file_state")
    record_payload.setdefault("schema", "FileStateRecord")
    try:
        record = FileStateRecord.model_validate(record_payload)
    except ValueError:
        return []
    payload = record.model_dump(mode="json")
    payload["record_type"] = "file_state"
    output = [
        make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload}),
        make_strict_event(make_event, FILE_STATE_ACCEPTED, payload),
    ]
    output.extend(
        _input_bound_events_for_record(
            projection,
            record.producer_node_id or expected_producer_node_id,
            record.port,
            record.record_id,
            payload,
            make_event,
            aliases={"accepted_file_state", "file_state"},
        )
    )
    return output


def _output_record_contract_port(
    contract: Any,
    record_payload: dict[str, Any],
) -> str | None:
    record_payload = dict(record_payload)
    if record_payload.get("record_kind") == "file_state":
        record_payload.setdefault("port", "file_state")
    if record_payload.get("record_kind") == "verification":
        record_payload.setdefault("port", "verification_report")
    port = record_payload.get("port")
    if not isinstance(port, str):
        return None
    if output_port_contract(contract, port) is None:
        return None
    if port == "verification_result":
        return "verification_report"
    return port


def _accepted_verification_record_events(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    record_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    candidate_id = _candidate_id_from_payload(record_payload)
    if candidate_id is None:
        return []
    if not _candidate_is_bound_to_verifier(projection, expected_producer_node_id, candidate_id):
        return []

    _add_evaluated_record_citations(record_payload, projection, expected_producer_node_id)
    try:
        record = _parse_verification_report_record(record_payload, expected_producer_node_id)
    except ValueError:
        return []
    payload = record.model_dump(mode="json")
    outcome = record.outcome
    task_region_id = projection["node_task_regions"].get(expected_producer_node_id)
    event_payload = {
        "node_id": request.node_id,
        "verifier_node_id": expected_producer_node_id,
        "candidate_id": candidate_id,
        "outcome": outcome,
        "record_id": record.record_id,
        "evaluated_record_ids": record.evaluated_record_ids,
        "evidence": payload.get("evidence"),
    }
    if task_region_id is not None:
        event_payload["task_region_id"] = task_region_id
    output = [
        make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload}),
        _make_strict_event(
            make_event,
            VERIFICATION_PASSED if outcome == "passed" else VERIFICATION_FAILED,
            event_payload,
        ),
    ]
    output.extend(
        _input_bound_events_for_record(
            projection,
            record.producer_node_id,
            record.port,
            record.record_id,
            payload,
            make_event,
            aliases={"verification_result"},
        )
    )
    return output


def _canonicalize_verification_record_port(record_payload: dict[str, Any]) -> None:
    if record_payload.get("port") == "verification_result":
        record_payload["port"] = "verification_report"


def _candidate_is_bound_to_verifier(
    projection: GraphProjection,
    verifier_node_id: str,
    candidate_id: str,
) -> bool:
    binding = projection["input_bindings"].get(verifier_node_id, {}).get("candidate_under_test")
    if binding is None:
        return False
    record_ids = binding.get("record_ids")
    return isinstance(record_ids, list) and candidate_id in record_ids


def _candidate_id_from_payload(payload: dict[str, Any] | FileStateRecord) -> str | None:
    if isinstance(payload, FileStateRecord):
        return payload.candidate_id
    candidate_id = payload.get("candidate_id")
    if isinstance(candidate_id, str):
        return candidate_id
    membership = payload.get("membership")
    if isinstance(membership, dict):
        value = cast(dict[str, Any], membership).get("candidate_id")
        if isinstance(value, str):
            return value
    return None


def _is_check_result_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "check_result"
        or payload.get("port") == "check_result"
        or payload.get("record_kind") == "check_result"
    )


def _is_verification_report_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_kind") == "verification"
        or payload.get("record_type") == "verification_report"
        or payload.get("port") in {"verification_report", "verification_result"}
        or payload.get("schema") == "VerificationReport"
    )


def _verification_report_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output["record_kind"] = "verification"
    output.setdefault("record_type", "verification_report")
    output.setdefault("port", "verification_report")
    output.setdefault("schema", "VerificationReport")
    return output


def _parse_verification_report_record(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> VerificationReportRecord:
    output = _verification_report_record_payload_for_validation(payload, expected_producer_node_id)
    _canonicalize_verification_record_port(output)
    return VerificationReportRecord.model_validate(output)


def _check_result_status_value(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    if isinstance(status, str):
        return status
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status
    return "unknown"


def _check_result_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "check_result")
    return output


def _is_candidate_record_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") == "candidate" or payload.get("port") == "candidate"


def _candidate_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "candidate")
    record_id = output.get("record_id")
    if isinstance(record_id, str) and record_id:
        output.setdefault("candidate_id", record_id)
    return output


ANALYSIS_SUMMARY_PORTS = frozenset({"analysis_summary", "planning_summary", "region_summary"})


def _is_analysis_summary_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "analysis_summary"
        or payload.get("port") in ANALYSIS_SUMMARY_PORTS
    )


def _analysis_summary_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "analysis_summary")
    return output


GRAPH_PATCH_PROPOSAL_PORTS = frozenset({"graph_patch_proposal", "graph_patch"})


def _is_graph_patch_proposal_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "graph_patch_proposal"
        or payload.get("port") in GRAPH_PATCH_PROPOSAL_PORTS
    )


def _graph_patch_proposal_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "graph_patch_proposal")
    return output


def _is_artifact_reference_record_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") == "artifact_reference" or payload.get("port") in {
        "artifact_reference",
        "artifact",
    }


def _artifact_reference_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_kind", "graph_record")
    output.setdefault("record_type", "artifact_reference")
    output.setdefault("schema", "ArtifactReference")
    output.setdefault("port", "artifact_reference")
    return output


def _same_callback_file_state_records(
    raw_records: list[Any],
    expected_producer_node_id: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_payload = dict(cast(dict[str, Any], raw_record))
        if (
            record_payload.get("record_kind") != "file_state"
            and record_payload.get("port") != "file_state"
        ):
            continue
        producer_node_id = record_payload.get("producer_node_id", expected_producer_node_id)
        if producer_node_id != expected_producer_node_id:
            continue
        record_id = record_payload.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            continue
        output.append(record_payload)
    return output


def _file_state_record_ids_for_candidate(
    candidate_payload: dict[str, Any],
    file_state_records: list[dict[str, Any]],
) -> list[str]:
    candidate_id = _candidate_id_from_payload(candidate_payload)
    output: list[str] = []
    for record in file_state_records:
        record_candidate_id = _candidate_id_from_payload(record)
        if (
            candidate_id is not None
            and record_candidate_id is not None
            and record_candidate_id != candidate_id
        ):
            continue
        record_id = record.get("record_id")
        if isinstance(record_id, str):
            output.append(record_id)
    return _unique_record_ids(output)


def _candidate_file_state_citation_conflict(
    record_payload: dict[str, Any],
    expected_file_state_ids: list[str],
    index: int,
) -> str | None:
    if not expected_file_state_ids:
        return None
    conflict = _explicit_record_ids_conflict(
        record_payload,
        "file_state_record_ids",
        expected_file_state_ids,
    )
    if conflict is not None:
        return f"output record at index {index} {conflict}"
    file_state_record_id = record_payload.get("file_state_record_id")
    if file_state_record_id is not None:
        if (
            not isinstance(file_state_record_id, str)
            or [file_state_record_id] != expected_file_state_ids
        ):
            return (
                "output record at index "
                f"{index} file_state_record_id does not match same-callback file-state records: "
                f"{file_state_record_id}"
            )
    return None


def _add_candidate_file_state_citations(
    record_payload: dict[str, Any],
    file_state_record_ids: list[str],
) -> None:
    if not file_state_record_ids:
        return
    citations = {"file_state_record_ids": file_state_record_ids}
    record_payload.setdefault("file_state_record_ids", list(file_state_record_ids))
    if len(file_state_record_ids) == 1:
        record_payload.setdefault("file_state_record_id", file_state_record_ids[0])
    _merge_record_citations(record_payload, "value", citations)
    _merge_record_citations(record_payload, "provenance", citations)


def _evaluated_record_citation_conflict(
    projection: GraphProjection,
    node_id: str,
    record_payload: dict[str, Any],
    index: int,
) -> str | None:
    citations = _evaluated_record_citations(projection, node_id)
    for field in ("candidate_record_ids", "file_state_record_ids", "evaluated_record_ids"):
        expected = citations.get(field)
        if expected is None:
            continue
        conflict = _explicit_record_ids_conflict(record_payload, field, expected)
        if conflict is not None:
            return f"output record at index {index} {conflict}"
    candidate_record_id = record_payload.get("candidate_record_id")
    expected_candidates = citations.get("candidate_record_ids")
    if candidate_record_id is not None and expected_candidates is not None:
        if not isinstance(candidate_record_id, str) or [candidate_record_id] != expected_candidates:
            return (
                "output record at index "
                f"{index} candidate_record_id does not match bound candidate records: "
                f"{candidate_record_id}"
            )
    return None


def _explicit_record_ids_conflict(
    record_payload: dict[str, Any],
    field: str,
    expected: list[str],
) -> str | None:
    candidates: list[tuple[str, Any]] = [(field, record_payload.get(field))]
    value = record_payload.get("value")
    if isinstance(value, dict):
        candidates.append((f"value.{field}", cast(dict[str, Any], value).get(field)))
    evidence = record_payload.get("evidence")
    if isinstance(evidence, dict):
        candidates.append((f"evidence.{field}", cast(dict[str, Any], evidence).get(field)))
    provenance = record_payload.get("provenance")
    if isinstance(provenance, dict):
        candidates.append((f"provenance.{field}", cast(dict[str, Any], provenance).get(field)))

    for path, value in candidates:
        if value is None:
            continue
        if not isinstance(value, list):
            return f"{path} must be a list of record IDs"
        record_ids = [
            record_id for record_id in cast(list[Any], value) if isinstance(record_id, str)
        ]
        if record_ids != expected:
            return f"{path} does not match bound records: {record_ids} != {expected}"
    return None


def _add_evaluated_record_citations(
    record_payload: dict[str, Any],
    projection: GraphProjection,
    node_id: str,
) -> None:
    citations = _evaluated_record_citations(projection, node_id)
    if not citations:
        return
    for key, value in citations.items():
        record_payload.setdefault(key, list(value))
    candidate_ids = citations.get("candidate_record_ids")
    if candidate_ids is not None and len(candidate_ids) == 1:
        record_payload.setdefault("candidate_record_id", candidate_ids[0])
    _merge_record_citations(record_payload, "provenance", citations)
    if _is_verification_report_record_payload(record_payload):
        _merge_record_citations(record_payload, "evidence", citations)
    if _is_check_result_record_payload(record_payload):
        _merge_record_citations(record_payload, "value", citations)


def _merge_record_citations(
    record_payload: dict[str, Any],
    field: str,
    citations: dict[str, list[str]],
) -> None:
    existing = record_payload.get(field)
    if existing is None:
        record_payload[field] = {key: list(value) for key, value in citations.items()}
        return
    if not isinstance(existing, dict):
        return
    merged = dict(cast(dict[str, Any], existing))
    for key, value in citations.items():
        merged.setdefault(key, list(value))
    record_payload[field] = merged


def _evaluated_record_citations(
    projection: GraphProjection,
    node_id: str,
) -> dict[str, list[str]]:
    candidate_record_ids = _bound_record_ids_for_ports(
        projection,
        node_id,
        ("candidate_under_test", "candidate"),
    )
    file_state_record_ids = _bound_record_ids_for_ports(
        projection,
        node_id,
        ("file_state", "accepted_file_state"),
    )
    if candidate_record_ids:
        file_state_record_ids.extend(
            _file_state_record_ids_for_candidate_records(projection, candidate_record_ids)
        )
    output: dict[str, list[str]] = {}
    unique_candidate_record_ids = _unique_record_ids(candidate_record_ids)
    unique_file_state_record_ids = _unique_record_ids(file_state_record_ids)
    if unique_candidate_record_ids:
        output["candidate_record_ids"] = unique_candidate_record_ids
    if unique_file_state_record_ids:
        output["file_state_record_ids"] = unique_file_state_record_ids
    evaluated_record_ids = _unique_record_ids(
        [*unique_candidate_record_ids, *unique_file_state_record_ids]
    )
    if evaluated_record_ids:
        output["evaluated_record_ids"] = evaluated_record_ids
    return output


def _file_state_record_ids_for_candidate_records(
    projection: GraphProjection,
    candidate_record_ids: list[str],
) -> list[str]:
    wanted = set(candidate_record_ids)
    output: list[str] = []
    for candidates in projection["task_candidates"].values():
        for candidate in candidates:
            candidate_id = candidate.candidate_id
            if candidate_id not in wanted:
                continue
            output.extend(candidate.file_state_record_ids)
    if output:
        return _unique_record_ids(output)
    for record in projection["file_state_records"].values():
        candidate_id = _candidate_id_from_payload(record)
        if candidate_id in wanted:
            output.append(record.record_id)
    return _unique_record_ids(output)


def _bound_record_ids_for_ports(
    projection: GraphProjection,
    node_id: str,
    ports: tuple[str, ...],
) -> list[str]:
    bindings = projection["input_bindings"].get(node_id, {})
    output: list[str] = []
    for port in ports:
        binding = bindings.get(port)
        if binding is None:
            continue
        record_ids = binding.get("record_ids")
        if not isinstance(record_ids, list):
            continue
        output.extend(
            record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)
        )
    return _unique_record_ids(output)


def _unique_record_ids(record_ids: list[str]) -> list[str]:
    output: list[str] = []
    for record_id in record_ids:
        if record_id not in output:
            output.append(record_id)
    return output


def _input_bound_events_for_record(
    projection: GraphProjection,
    producer_node_id: str,
    port: str,
    record_id: str,
    record_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    aliases: set[str] | None = None,
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    # Output records are facts produced by the leased node. Edges are the only
    # authority for routing those facts into downstream required inputs.
    for edge in projection["edges"].values():
        if edge.get("dependency_type", "input_binding") != "input_binding":
            continue
        if not _edge_accepts_producer(projection, edge, producer_node_id):
            continue
        if edge.get("from_port") != port:
            continue
        if not record_selector_matches(
            edge.get("accepted_record_selector"), record_payload, aliases
        ):
            continue
        edge_id = edge.get("edge_id")
        to_node_id = edge.get("to_node_id")
        to_port = edge.get("to_port")
        if not isinstance(edge_id, str) or not isinstance(to_node_id, str):
            continue
        if not isinstance(to_port, str):
            continue
        binding_payload = _input_bound_payload_for_record(
            projection,
            edge,
            edge_id=edge_id,
            to_node_id=to_node_id,
            to_port=to_port,
            record_id=record_id,
            record_payload=record_payload,
        )
        if binding_payload is None:
            continue
        output.append(
            typed_topology_event(
                make_event,
                "input_bound",
                binding_payload,
            )
        )
    return output


def _input_bound_payload_for_record(
    projection: GraphProjection,
    edge: dict[str, Any],
    *,
    edge_id: str,
    to_node_id: str,
    to_port: str,
    record_id: str,
    record_payload: dict[str, Any],
) -> dict[str, Any] | None:
    existing_ids = _existing_bound_record_ids(projection, to_node_id, to_port)
    target_port = _target_port_contract_for_edge(projection, edge)
    policy = binding_policy_for_edge(edge, target_port)
    next_ids = merge_bound_record_ids(
        policy,
        existing_ids,
        [record_id],
        supersedes_record_id=record_payload.get("supersedes_record_id"),
    )
    if next_ids == existing_ids and existing_ids:
        return None

    payload: dict[str, Any] = {
        "edge_id": edge_id,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "record_ids": next_ids,
        "bound_at_position": 0,
    }
    if policy != "bind_first" or isinstance(edge.get("binding_policy"), str):
        payload["binding_policy"] = policy
    supersedes_record_id = record_payload.get("supersedes_record_id")
    if isinstance(supersedes_record_id, str):
        payload["supersedes_record_id"] = supersedes_record_id
    return payload


def _existing_bound_record_ids(
    projection: GraphProjection,
    to_node_id: str,
    to_port: str,
) -> list[str]:
    binding = projection["input_bindings"].get(to_node_id, {}).get(to_port)
    if binding is None:
        return []
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list):
        return []
    return [record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)]


def _target_port_contract_for_edge(
    projection: GraphProjection,
    edge: dict[str, Any],
) -> PortContract | None:
    to_node_id = edge.get("to_node_id")
    to_port = edge.get("to_port")
    if not isinstance(to_node_id, str) or not isinstance(to_port, str):
        return None
    target_kind = projection["node_kinds"].get(to_node_id)
    if target_kind is None:
        return None
    target_role = projection["node_roles"].get(to_node_id)
    target_contract = DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
    if target_contract is None:
        return None
    return input_port_contract(target_contract, to_port)


def _apply_patch_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    actor_role = str(payload.get("actor_role", "planner"))
    run_state = projection["run_state"]
    if run_state is not None and run_state != "active":
        return [
            _command_rejected(
                make_event,
                "submit_patch",
                f"run_not_active:{run_state or 'unknown'}",
            )
        ]
    try:
        payload = expand_patch_macros(payload)
        patch = PatchEnvelope(
            patch_id=str(payload["patch_id"]),
            proposed_by_node_id=str(payload.get("proposed_by_node_id", "controller")),
            base_graph_position=int(payload.get("base_graph_position", -1)),
            ops=[PatchOp(**op) for op in cast(list[dict[str, Any]], payload.get("ops", []))],
            rationale_record_id=cast(str | None, payload.get("rationale_record_id")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return [
            _make_strict_event(
                make_event,
                COMMAND_REJECTED,
                {
                    "command_type": "submit_patch",
                    "reason": f"malformed patch: {exc}",
                    "patch_id": payload.get("patch_id"),
                    "base_graph_position": payload.get("base_graph_position"),
                    "actor_role": actor_role,
                    "proposed_by_node_id": payload.get("proposed_by_node_id"),
                },
            )
        ]

    current_position = _current_position(events, payload)
    events_since_base = [event for event in events if event.position > patch.base_graph_position]
    result = validate_patch(patch, current_position, events_since_base, projection, actor_role)
    if not result.accepted:
        return [
            _make_strict_event(
                make_event,
                GRAPH_PATCH_REJECTED,
                _patch_rejected_payload(
                    patch,
                    actor_role,
                    reason=result.rejection_reason,
                    read_set_diff=result.read_set_diff,
                ),
            )
        ]

    successor_planner_node_ids = _successor_planner_node_ids(patch)
    if actor_role == "planner" and len(successor_planner_node_ids) > 1:
        return [
            _make_strict_event(
                make_event,
                GRAPH_PATCH_REJECTED,
                _patch_rejected_payload(
                    patch,
                    actor_role,
                    reason="multiple_successor_planners_not_allowed",
                    read_set_diff=None,
                ),
            )
        ]
    if actor_role == "planner" and successor_planner_node_ids:
        budget_rejection = _planner_budget_rejection(projection, patch)
        if budget_rejection is not None:
            gate_node_id = str(
                payload.get(
                    "budget_gate_node_id",
                    f"gate-planner-budget-{patch.proposed_by_node_id}",
                )
            )
            return [
                _make_strict_event(
                    make_event,
                    GRAPH_PATCH_REJECTED,
                    {
                        **_patch_rejected_payload(
                            patch,
                            actor_role,
                            reason="planner_generation_budget_exhausted",
                            read_set_diff=None,
                        ),
                        "budget": budget_rejection["budget"],
                        "count": budget_rejection["count"],
                    },
                ),
                typed_topology_event(
                    make_event,
                    "node_created",
                    {
                        "node_id": gate_node_id,
                        "kind": "gate",
                        "state": "planned",
                        "role": "planner_generation_budget_gate",
                        "guarded_planner_node_id": patch.proposed_by_node_id,
                        "rejected_patch_id": patch.patch_id,
                        "reason": "planner_generation_budget_exhausted",
                    },
                ),
                typed_topology_event(
                    make_event,
                    "node_state_changed",
                    {
                        "node_id": gate_node_id,
                        "new_state": "ready",
                        "trigger": "planner_generation_budget_exhausted",
                    },
                ),
            ]

    request_record_error = _request_record_validation_error(patch)
    if request_record_error is not None:
        return [
            _make_strict_event(
                make_event,
                GRAPH_PATCH_REJECTED,
                _patch_rejected_payload(
                    patch,
                    actor_role,
                    reason=request_record_error,
                    read_set_diff=None,
                ),
            )
        ]

    parent_session_id = projection["planner_sessions"].get(patch.proposed_by_node_id)
    carryover_record_id = _carryover_record_id(payload)
    output = [
        _make_strict_event(
            make_event,
            GRAPH_PATCH_ACCEPTED,
            GraphPatchAcceptedPayload.model_validate(
                {
                    "patch_id": patch.patch_id,
                    "base_graph_position": patch.base_graph_position,
                    "actor_role": actor_role,
                    "proposed_by_node_id": patch.proposed_by_node_id,
                    "successor_planner_node_ids": successor_planner_node_ids,
                    "session_id": parent_session_id,
                    "carryover_record_id": carryover_record_id,
                }
            ).model_dump(mode="json"),
        )
    ]
    for op in patch.ops:
        output.extend(
            _patch_op_events(
                op,
                projection,
                events,
                make_event,
                inherited_session_id=parent_session_id,
                carryover_record_id=carryover_record_id,
            )
        )
    if carryover_record_id is not None and successor_planner_node_ids:
        output.append(
            typed_topology_event(
                make_event,
                "input_bound",
                {
                    "edge_id": f"edge-session-carryover-{successor_planner_node_ids[0]}",
                    "to_node_id": successor_planner_node_ids[0],
                    "to_port": "session_carryover",
                    "record_ids": [carryover_record_id],
                    "bound_at_position": 0,
                },
            )
        )
    output.extend(_source_repair_events(projection, events, output, make_event))
    return output


def _patch_rejected_payload(
    patch: PatchEnvelope,
    actor_role: str,
    *,
    reason: str | None,
    read_set_diff: dict[str, Any] | None,
) -> dict[str, Any]:
    return GraphPatchRejectedPayload.model_validate(
        {
            "patch_id": patch.patch_id,
            "base_graph_position": patch.base_graph_position,
            "actor_role": actor_role,
            "proposed_by_node_id": patch.proposed_by_node_id,
            "reason": reason,
            "read_set_diff": read_set_diff,
        }
    ).model_dump(mode="json")


def _request_record_validation_error(patch: PatchEnvelope) -> str | None:
    for op in patch.ops:
        if op.op != "create_node" or not isinstance(op.node, dict):
            continue
        try:
            _request_record_bindings_for_node(dict(op.node))
        except ValueError as exc:
            return f"invalid request record for node {op.node.get('node_id')}: {exc}"
    return None


def _successor_planner_node_ids(patch: PatchEnvelope) -> list[str]:
    node_ids: list[str] = []
    for op in patch.ops:
        if op.op != "create_node" or not isinstance(op.node, dict):
            continue
        node = op.node
        if node.get("kind") != "planner" or node.get("role") != "planner":
            continue
        node_id = node.get("node_id")
        if isinstance(node_id, str):
            node_ids.append(node_id)
    return node_ids


def _carryover_record_id(payload: dict[str, Any]) -> str | None:
    for key in ("carryover_summary", "carryover_record_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _planner_budget_rejection(
    projection: GraphProjection,
    patch: PatchEnvelope,
) -> dict[str, int] | None:
    parent_generation = projection["planner_generations"].get(patch.proposed_by_node_id, 0)
    attempted_generation = parent_generation + 1
    budget = projection["planner_generation_budget"]
    if attempted_generation <= budget:
        return None
    return {"budget": budget, "count": attempted_generation}


def schedule_tick_effects(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    from orchestrator.graph.commands.schedule import node_schedule_info

    output = _expired_lease_events(projection, clock.now(), make_event)
    expired_lease_ids = _expired_active_lease_ids(projection, clock.now())
    active_claims = [
        _claim_from_dict(claim)
        for lease in projection["leases"].values()
        if lease.get("state") == "active"
        and isinstance(lease.get("lease_id"), str)
        and lease.get("lease_id") not in expired_lease_ids
        for claim in cast(list[Any], lease.get("resource_claims", []))
    ]
    active_lease_node_ids = [
        str(lease["node_id"])
        for lease in projection["leases"].values()
        if lease.get("state") == "active"
        and isinstance(lease.get("lease_id"), str)
        and lease.get("lease_id") not in expired_lease_ids
        and isinstance(lease.get("node_id"), str)
    ]
    retiring_node_ids = {
        event.payload["node_id"]
        for event in output
        if event.event_type == "node_retired" and isinstance(event.payload.get("node_id"), str)
    }
    nodes: list[NodeScheduleInfo] = []
    readied_node_ids: set[str] = set()
    for node_id, node_state in projection["node_states"].items():
        if node_id in retiring_node_ids:
            continue
        if node_state not in {"planned", "blocked", "ready"}:
            continue
        node = node_schedule_info(projection, payload, node_id)
        backoff_reason = _retry_backoff_deferred_reason(projection, node_id, clock.now())
        if backoff_reason is not None:
            _append_node_deferred_if_changed(
                output,
                projection,
                node_id,
                backoff_reason,
                make_event,
            )
            continue
        readiness_node = replace(node, state="planned") if node_state == "ready" else node
        ready, reason = evaluate_readiness(
            readiness_node,
            projection["run_state"] or "draft",
            active_lease_node_ids,
            active_claims,
        )
        if not ready:
            dead_input = _dead_input_from_readiness(node, reason)
            if dead_input is not None:
                if projection.get("last_deferred_reasons", {}).get(node_id) != reason:
                    output.append(
                        typed_topology_event(
                            make_event,
                            "dead_input_detected",
                            {
                                "node_id": node_id,
                                **dead_input,
                                "reason": reason,
                            },
                        )
                    )
            _append_node_deferred_if_changed(
                output,
                projection,
                node_id,
                reason,
                make_event,
            )
            continue
        if node_state != "ready":
            output.append(typed_topology_event(make_event, "node_ready", {"node_id": node_id}))
            output.append(
                typed_topology_event(
                    make_event,
                    "node_state_changed",
                    {
                        "node_id": node_id,
                        "new_state": "ready",
                        "trigger": "readiness_evaluator",
                    },
                )
            )
            readied_node_ids.add(node_id)
        nodes.append(replace(node, state="ready"))
    decision = schedule(
        nodes,
        projection["run_state"] or "draft",
        active_claims,
        _current_position(events, payload),
        max_grants=int(payload.get("max_grants", 10)),
    )
    lease_seconds = int(payload.get("lease_seconds", 300))
    for node_id in decision.selected:
        claims = projection["node_resource_claims"].get(node_id, [])
        lease_id = (
            str(payload.get("lease_ids", {}).get(node_id))
            if isinstance(payload.get("lease_ids"), dict) and node_id in payload["lease_ids"]
            else id_gen.next_id("lease")
        )
        base_snapshot_id = _base_snapshot_id_for_node(projection, payload, node_id)
        if base_snapshot_id is None:
            _append_node_deferred_if_changed(
                output,
                projection,
                node_id,
                "missing_base_snapshot",
                make_event,
            )
            continue
        if node_id not in readied_node_ids:
            output.append(typed_topology_event(make_event, "node_ready", {"node_id": node_id}))
        planner_session_id = _planner_session_id(projection, node_id, id_gen)
        lease_generation = _next_lease_generation(projection, node_id)
        lease_payload: dict[str, Any] = {
            "lease_id": lease_id,
            "node_id": node_id,
            "generation": lease_generation,
            "execution_id": id_gen.next_id("exec"),
            "base_snapshot_id": base_snapshot_id,
            "expires_at": clock.now() + timedelta(seconds=lease_seconds),
            "resource_claims": tuple(_resource_claim_payload(claim) for claim in claims),
        }
        if planner_session_id is not None:
            lease_payload["session_id"] = planner_session_id
        output.append(_make_strict_event(make_event, LEASE_GRANTED, lease_payload))
        if planner_session_id is not None:
            session_payload = PlannerSessionStateChangedPayload.model_validate(
                {
                    "session_id": planner_session_id,
                    "state": "attached",
                    "node_id": node_id,
                    "lease_generation": lease_generation,
                    "carryover_record_id": _session_carryover_record_id(projection, node_id),
                }
            )
            output.append(
                typed_topology_event(
                    make_event,
                    "session_state_changed",
                    session_payload.model_dump(mode="json", exclude_none=False),
                )
            )
        output.append(
            typed_topology_event(
                make_event,
                "node_state_changed",
                {"node_id": node_id, "new_state": "leased", "trigger": "scheduler_grants_lease"},
            )
        )
    for node_id in decision.deferred:
        _append_node_deferred_if_changed(
            output,
            projection,
            node_id,
            decision.deferred_reasons[node_id],
            make_event,
        )
    return output


def _append_node_deferred_if_changed(
    output: list[EventEnvelope],
    projection: GraphProjection,
    node_id: str,
    reason: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> None:
    if projection.get("last_deferred_reasons", {}).get(node_id) == reason:
        return
    output.append(
        typed_topology_event(make_event, "node_deferred", {"node_id": node_id, "reason": reason})
    )


def _dead_input_from_readiness(
    node: NodeScheduleInfo,
    reason: str,
) -> dict[str, str] | None:
    prefix = "upstream_failed:"
    if not reason.startswith(prefix):
        return None
    from_node_id = reason.removeprefix(prefix)
    for edge in node.required_edges:
        if edge.from_node_id == from_node_id:
            return {"from_node_id": from_node_id, "to_port": edge.to_port}
    return {"from_node_id": from_node_id, "to_port": ""}


def _apply_reconcile(
    projection: GraphProjection,
    events: list[EventEnvelope],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    run_state = projection["run_state"]
    if run_state in TERMINAL_RUN_STATES:
        return [_command_rejected(make_event, "reconcile", f"terminal run: {run_state}")]
    return _repair_events(projection, make_event)


def _repair_events(
    projection: GraphProjection,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    active_lease_node_ids = _active_lease_node_ids(projection)
    output: list[EventEnvelope] = []
    output.extend(
        _failed_check_recovery_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _failed_verification_recovery_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _passed_verification_terminalization_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _passed_check_terminalization_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _no_successor_recovery_terminal_failure_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    return _dedupe_repair_events(output)


def _active_lease_node_ids(projection: GraphProjection) -> list[str]:
    return [
        str(lease["node_id"])
        for lease in projection["leases"].values()
        if lease.get("state") == "active" and isinstance(lease.get("node_id"), str)
    ]


def _project_with_events(
    projection: GraphProjection,
    source_events: list[EventEnvelope],
) -> GraphProjection:
    output = projection
    for event in source_events:
        if event.event_type == OUTPUT_RECORD_ACCEPTED.name:
            payload = OUTPUT_RECORD_ACCEPTED.validate_payload(event.payload)
            metadata = EventMetadata(
                event_id=event.event_id,
                run_id=event.run_id,
                position=event.position,
                event_type=event.event_type,
                payload_schema_generation=event.schema_version,
                actor=event.actor,
                causation_id=event.causation_id,
                correlation_id=event.correlation_id,
                timestamp=event.timestamp,
            )
            output = OUTPUT_RECORD_ACCEPTED.reduce(
                output, OUTPUT_RECORD_ACCEPTED.create(metadata, payload)
            )
        else:
            output = reduce_legacy_event(output, event)
    return output


def _dedupe_repair_events(repair_events: list[EventEnvelope]) -> list[EventEnvelope]:
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    output: list[EventEnvelope] = []
    for event in repair_events:
        key = (
            event.event_type,
            tuple(sorted((key, repr(value)) for key, value in event.payload.items())),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(event)
    return output


def _failed_check_recovery_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    record_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if projection["run_state"] != "active":
        return []
    if active_lease_node_ids:
        return []
    if any(
        state in {"planned", "blocked", "ready"} for state in projection["node_states"].values()
    ):
        return []
    if not any(state != "accepted" for state in projection["task_states"].values()):
        return []

    routine_snapshot = _latest_routine_snapshot_record(projection)
    if routine_snapshot is None:
        return []

    output: list[EventEnvelope] = []
    for failed_check in _current_failed_check_results(projection):
        if record_ids is not None and failed_check["record_id"] not in record_ids:
            continue
        recovery_node_id = _failed_check_recovery_node_id(failed_check)
        if recovery_node_id in projection["node_states"]:
            continue
        if _has_existing_failed_check_recovery(projection, failed_check):
            continue
        node_id = failed_check["node_id"]
        record_id = failed_check["record_id"]
        task_region_id = failed_check.get("task_region_id", node_id)
        recovery_region_id = f"recovery-{_stable_graph_id_part(task_region_id)}"
        record_type = failed_check.get("record_type", "check_result")
        source_port = "failure_record" if record_type == "failure_record" else "check_result"
        source_schema = "FailureRecord" if record_type == "failure_record" else "CheckResult"
        selector: dict[str, Any] = {"record_type": record_type, "schema": source_schema}
        if record_type == "check_result":
            selector["status"] = "failed"
        output.append(
            typed_topology_event(
                make_event,
                "node_created",
                {
                    "node_id": recovery_node_id,
                    "kind": "planner",
                    "role": "gap_planner",
                    "state": "planned",
                    "task_region_id": recovery_region_id,
                    "recovery_reason": "failed_required_check",
                    "recovery_of_node_id": node_id,
                    "recovery_of_record_id": record_id,
                },
            )
        )
        recovery_edges = [
            {
                "edge_id": f"edge-{_stable_graph_id_part(record_id)}-recovery-evidence",
                "from_node_id": node_id,
                "from_port": source_port,
                "to_node_id": recovery_node_id,
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": selector,
                "metadata": {
                    "purpose": "failed_required_check_recovery",
                    "recovery_of_record_id": record_id,
                },
            },
            {
                "edge_id": f"edge-routine-snapshot-{recovery_node_id}",
                "from_node_id": routine_snapshot["producer_node_id"],
                "from_port": routine_snapshot["port"],
                "to_node_id": recovery_node_id,
                "to_port": "routine_snapshot",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "routine_snapshot",
                    "schema": "RoutineSnapshot",
                },
                "metadata": {"purpose": "failed_required_check_recovery_context"},
            },
        ]
        for edge in recovery_edges:
            if _would_create_directed_cycle(
                projection,
                cast(str, edge["from_node_id"]),
                cast(str, edge["to_node_id"]),
            ):
                continue
            output.append(typed_topology_event(make_event, "edge_created", edge))
            output.extend(_input_bound_events_for_edge(projection, edge, make_event))
    return output


def _failed_verification_recovery_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    record_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if projection["run_state"] != "active":
        return []
    if active_lease_node_ids or projection["ready_nodes"]:
        return []
    if not any(state != "accepted" for state in projection["task_states"].values()):
        return []

    routine_snapshot = _latest_routine_snapshot_record(projection)
    if routine_snapshot is None:
        return []

    output: list[EventEnvelope] = []
    for verification in _current_failed_verification_results(projection):
        if record_ids is not None and verification["record_id"] not in record_ids:
            continue
        recovery_node_id = _failed_verification_recovery_node_id(verification)
        if recovery_node_id in projection["node_states"]:
            continue
        if _has_existing_failed_verification_recovery(projection, verification):
            continue
        node_id = verification["node_id"]
        record_id = verification["record_id"]
        task_region_id = verification.get("task_region_id", node_id)
        recovery_region_id = f"recovery-{_stable_graph_id_part(task_region_id)}"
        output.append(
            typed_topology_event(
                make_event,
                "node_created",
                {
                    "node_id": recovery_node_id,
                    "kind": "planner",
                    "role": "gap_planner",
                    "state": "planned",
                    "task_region_id": recovery_region_id,
                    "recovery_reason": "failed_verification",
                    "recovery_of_node_id": node_id,
                    "recovery_of_record_id": record_id,
                },
            )
        )
        recovery_edges = [
            {
                "edge_id": f"edge-{_stable_graph_id_part(record_id)}-recovery-evidence",
                "from_node_id": node_id,
                "from_port": "verification_report",
                "to_node_id": recovery_node_id,
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "failed",
                },
                "metadata": {
                    "purpose": "failed_verification_recovery",
                    "recovery_of_record_id": record_id,
                },
            },
            {
                "edge_id": f"edge-routine-snapshot-{recovery_node_id}",
                "from_node_id": routine_snapshot["producer_node_id"],
                "from_port": routine_snapshot["port"],
                "to_node_id": recovery_node_id,
                "to_port": "routine_snapshot",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "routine_snapshot",
                    "schema": "RoutineSnapshot",
                },
                "metadata": {"purpose": "failed_verification_recovery_context"},
            },
        ]
        for edge in recovery_edges:
            if _would_create_directed_cycle(
                projection,
                cast(str, edge["from_node_id"]),
                cast(str, edge["to_node_id"]),
            ):
                continue
            output.append(typed_topology_event(make_event, "edge_created", edge))
            output.extend(_input_bound_events_for_edge(projection, edge, make_event))
    return output


def _current_failed_verification_results(projection: GraphProjection) -> list[dict[str, str]]:
    passed_candidates = projection["passed_verification_candidate_ids"]
    current: list[dict[str, str]] = []
    for verification in projection["failed_verification_results_by_record_id"].values():
        verification_dict = _verification_result_dict(verification)
        if verification_dict is None:
            continue
        if verification_dict.get("candidate_id") in passed_candidates:
            continue
        if _superseded_by_later_regional_pass(projection, verification_dict):
            continue
        current.append(verification_dict)
    return current


def _superseded_by_later_regional_pass(
    projection: GraphProjection,
    verification: dict[str, Any],
) -> bool:
    """True when a later candidate in the same task region passed verification.

    Recovery never re-runs the failed candidate: a gap/recovery planner wires a
    corrective worker that produces a NEW candidate in the same region, and the
    corrective verifier grades that. The old failed verification's own
    candidate therefore never enters passed_verification_candidate_ids, so
    without this check the failure stays "current" forever — which is what let
    the recovery_planner_no_successor sweep fail runs W2/W4 after their
    repairs had already passed (incident 2026-07-04). Supersession requires a
    strictly later passing verdict (by verdict position) in the same region.
    """
    failed_region = _verification_task_region(projection, verification)
    if failed_region is None:
        return False
    failed_position = _candidate_verdict_position(projection, verification.get("candidate_id"))
    if failed_position is None:
        return False
    failed_record_id = verification.get("record_id")
    for passed in projection["passed_verification_results_by_record_id"].values():
        passed_dict = _verification_result_dict(passed)
        if passed_dict is None:
            continue
        if passed_dict.get("record_id") == failed_record_id:
            continue
        candidate_id = passed_dict.get("candidate_id")
        verdict = projection["verifier_verdicts"].get(candidate_id or "")
        if verdict is not None and verdict.verdict != "passed":
            # The candidate's latest verdict is a failure; not a supersession.
            continue
        if _verification_task_region(projection, passed_dict) != failed_region:
            continue
        passed_position = _candidate_verdict_position(projection, candidate_id)
        if passed_position is None:
            continue
        if passed_position > failed_position:
            return True
    return False


def _verification_task_region(
    projection: GraphProjection,
    verification: dict[str, str],
) -> str | None:
    task_region_id = verification.get("task_region_id")
    if isinstance(task_region_id, str) and task_region_id:
        return task_region_id
    node_id = verification.get("node_id")
    if isinstance(node_id, str) and node_id:
        return projection["node_task_regions"].get(node_id)
    return None


def _verification_result_dict(
    verification: VerificationResultProjection,
) -> dict[str, str] | None:
    data = verification.model_dump(mode="json")
    if not isinstance(data.get("node_id"), str) or not isinstance(data.get("record_id"), str):
        return None
    return {key: value for key, value in data.items() if isinstance(value, str)}


def _candidate_verdict_position(
    projection: GraphProjection,
    candidate_id: str | None,
) -> int | None:
    if not isinstance(candidate_id, str) or not candidate_id:
        return None
    verdict = projection["verifier_verdicts"].get(candidate_id)
    if verdict is None:
        return None
    return verdict.position


def _passed_verification_terminalization_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    record_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if projection["run_state"] != "active":
        return []
    if active_lease_node_ids or projection["ready_nodes"]:
        return []

    output: list[EventEnvelope] = []
    passed_verifications = _current_passed_verification_results(projection)
    latest_passed_verification = passed_verifications[-1] if passed_verifications else None
    for verification in passed_verifications:
        if record_ids is not None and verification["record_id"] not in record_ids:
            continue
        retirable_node_ids = _unreachable_failure_branch_node_ids(
            projection,
            verification["node_id"],
        )
        if verification == latest_passed_verification:
            output.extend(
                _passed_verification_final_check_edges(
                    projection,
                    verification,
                    make_event,
                    allow_create=bool(retirable_node_ids),
                )
            )
        if not retirable_node_ids:
            continue
        for node_id in retirable_node_ids:
            output.extend(_retire_node_events(projection, node_id, make_event))
    return output


def _passed_check_terminalization_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    check_node_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if projection["run_state"] != "active":
        return []
    if active_lease_node_ids or projection["ready_nodes"]:
        return []

    output: list[EventEnvelope] = []
    for check_node_id, result in sorted(projection["check_results"].items()):
        if check_node_ids is not None and check_node_id not in check_node_ids:
            continue
        if result.status not in {"passed", "pass", "ok"}:
            continue
        for node_id in _unreachable_check_failure_branch_node_ids(projection, check_node_id):
            output.extend(_retire_node_events(projection, node_id, make_event))
    return output


def _no_successor_recovery_terminal_failure_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    recovery_node_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if projection["run_state"] != "active":
        return []
    if active_lease_node_ids or projection["ready_nodes"]:
        return []
    if any(
        state in {"planned", "blocked", "ready", "leased", "running", "suspended"}
        for state in projection["node_states"].values()
    ):
        return []
    if not any(state != "accepted" for state in projection["task_states"].values()):
        return []

    terminal = _completed_no_successor_recovery(
        projection,
        recovery_node_ids=recovery_node_ids,
    )
    if terminal is None:
        return []
    if terminal.get("environment_failure") == "true":
        return []
    return [
        _make_strict_event(
            make_event,
            RUN_LIFECYCLE_CHANGED,
            {
                "command_type": "schedule_tick",
                "from_state": "active",
                "to_state": "failed",
                "trigger": "recovery_planner_no_successor",
                "node_id": terminal["node_id"],
                "patch_id": terminal["patch_id"],
                "recovery_of_record_id": terminal["recovery_of_record_id"],
                "recovery_reason": terminal["recovery_reason"],
            },
        )
    ]


def _completed_no_successor_recovery(
    projection: GraphProjection,
    *,
    recovery_node_ids: set[str] | None = None,
) -> dict[str, str] | None:
    """Find a completed recovery planner whose recovery is a genuine dead end.

    A recovery planner only counts as a dead end when ALL of the following
    hold: its latest accepted patch created no successor planner, it created
    no executable successor nodes (worker/verifier/check wired from the
    planner's outputs), and nothing downstream of the planner has since
    produced a passing verification or check. The last two guards were added
    after runs W2 (69ce4f7c) and W4 (0694df2d) were failed by this sweep on
    2026-07-04 even though their recovery patches had spawned corrective
    workers whose candidates passed verification and satisfied the final
    invariant checks — a successful recovery, misread as a dead end because
    only successor *planner* nodes were counted as continuation.
    """
    recovery_nodes = _recovery_nodes_by_record_id(projection)
    for failed in [
        *_current_failed_check_results(projection),
        *_current_failed_verification_results(projection),
    ]:
        record_id = failed["record_id"]
        for recovery in recovery_nodes.get(record_id, []):
            node_id = recovery["node_id"]
            if recovery_node_ids is not None and node_id not in recovery_node_ids:
                continue
            if projection["node_states"].get(node_id) != "completed":
                continue
            patch_id = _accepted_no_successor_patch_id(projection, node_id)
            if patch_id is None:
                continue
            if _recovery_created_executable_successors(projection, node_id):
                continue
            if _recovery_lineage_superseded(projection, node_id):
                continue
            return {
                "node_id": node_id,
                "patch_id": patch_id,
                "recovery_of_record_id": record_id,
                "recovery_reason": recovery["recovery_reason"],
                "environment_failure": str(
                    failed.get("classification")
                    in {"environment_error", "tool_error", "tool_unavailable"}
                ).lower(),
            }
    return None


def _recovery_nodes_by_record_id(
    projection: GraphProjection,
) -> dict[str, list[dict[str, str]]]:
    return {
        record_id: [
            {
                "node_id": recovery.node_id,
                "recovery_reason": recovery.recovery_reason,
            }
            for recovery in recoveries
        ]
        for record_id, recoveries in projection["recovery_nodes_by_record_id"].items()
    }


def _accepted_no_successor_patch_id(projection: GraphProjection, node_id: str) -> str | None:
    patch_ids = projection["accepted_no_successor_patches_by_node"].get(node_id, [])
    return patch_ids[-1] if patch_ids else None


def _recovery_created_executable_successors(
    projection: GraphProjection,
    recovery_node_id: str,
) -> bool:
    """True when a recovery planner wired executable (non-planner) successors.

    A gap/recovery planner's accepted patch links its output records to the
    corrective work it plans (e.g. classified_gap -> worker), so an outgoing
    edge to a later-created non-planner node means the recovery produced real
    work — not a dead end — even though successor_planner_node_ids was empty.
    """
    recovery_position = projection["node_creation_positions"].get(recovery_node_id, 0)
    for edge in projection["edges"].values():
        if edge.get("from_node_id") != recovery_node_id:
            continue
        to_node_id = edge.get("to_node_id")
        if not isinstance(to_node_id, str):
            continue
        if to_node_id not in projection["node_kinds"]:
            continue
        if projection["node_kinds"].get(to_node_id) == "planner":
            continue
        if projection["node_creation_positions"].get(to_node_id, 0) < recovery_position:
            continue
        return True
    return False


def _recovery_lineage_superseded(
    projection: GraphProjection,
    recovery_node_id: str,
) -> bool:
    """True when work downstream of a recovery planner has already passed.

    Walks the edge graph from the recovery planner and looks for a passing
    verification (whose candidate's latest verdict is still a pass) or a
    passing check result produced by any reachable node. Covers both recovery
    flavors: failed verifications (W2 shape) and failed required checks (W4
    shape), where the corrective chain is planner -> worker -> verifier.
    """
    reachable = _downstream_node_ids(projection, recovery_node_id)
    if not reachable:
        return False
    for verification in projection["passed_verification_results_by_record_id"].values():
        if verification.node_id not in reachable:
            continue
        candidate_id = verification.candidate_id
        verdict = projection["verifier_verdicts"].get(candidate_id or "")
        if verdict is None or verdict.verdict == "passed":
            return True
    for check_node_id, result in projection["check_results"].items():
        if check_node_id not in reachable:
            continue
        if result.status in {"passed", "pass", "ok"}:
            return True
    return False


def _downstream_node_ids(projection: GraphProjection, start_node_id: str) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for edge in projection["edges"].values():
        source = edge.get("from_node_id")
        target = edge.get("to_node_id")
        if isinstance(source, str) and isinstance(target, str):
            adjacency.setdefault(source, set()).add(target)
    seen: set[str] = set()
    frontier = [start_node_id]
    while frontier:
        node_id = frontier.pop()
        for neighbor in adjacency.get(node_id, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return seen


def _passed_verification_final_check_edges(
    projection: GraphProjection,
    verification: dict[str, str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    allow_create: bool = True,
) -> list[EventEnvelope]:
    verifier_node_id = verification["node_id"]
    record_id = verification["record_id"]
    output: list[EventEnvelope] = []
    check_node_ids = _final_checks_waiting_for_verification_evidence(projection)
    if allow_create and not check_node_ids and not _has_final_invariant_check(projection):
        check_node_id = f"check-final-invariant-{_stable_graph_id_part(record_id)}"
        if _would_create_directed_cycle(projection, verifier_node_id, check_node_id):
            return output
        output.append(
            typed_topology_event(
                make_event,
                "node_created",
                {
                    "node_id": check_node_id,
                    "kind": "check",
                    "role": "invariant_gate",
                    "state": "planned",
                    "task_region_id": "final-invariant-region",
                    "command_binding": "dynamic_feature_hidden_oracle",
                    "inputs": [
                        {
                            "port": "verification_evidence",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        }
                    ],
                    "outputs": [
                        {
                            "port": "check_result",
                            "direction": "output",
                            "schema": "CheckResult",
                        }
                    ],
                },
            )
        )
        check_node_ids = [check_node_id]
    for check_node_id in check_node_ids:
        if _has_verification_evidence_edge(projection, verifier_node_id, check_node_id):
            continue
        edge = {
            "edge_id": (
                f"edge-{_stable_graph_id_part(record_id)}-passed-verification-final-"
                f"{_stable_graph_id_part(check_node_id)}"
            ),
            "from_node_id": verifier_node_id,
            "from_port": "verification_report",
            "to_node_id": check_node_id,
            "to_port": "verification_evidence",
            "required": True,
            "accepted_record_selector": {
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "outcome": "passed",
            },
            "metadata": {
                "purpose": "passed_verification_final_invariant_recovery",
                "recovery_of_record_id": record_id,
            },
        }
        if _would_create_directed_cycle(projection, verifier_node_id, check_node_id):
            continue
        output.append(typed_topology_event(make_event, "edge_created", edge))
        output.extend(_input_bound_events_for_edge(projection, edge, make_event))
    return output


def _would_create_directed_cycle(
    projection: GraphProjection,
    from_node_id: str,
    to_node_id: str,
) -> bool:
    if from_node_id == to_node_id:
        return True
    adjacency: dict[str, set[str]] = {}
    for edge in projection["edges"].values():
        source = edge.get("from_node_id")
        target = edge.get("to_node_id")
        if isinstance(source, str) and isinstance(target, str):
            adjacency.setdefault(source, set()).add(target)

    seen: set[str] = set()
    stack = [to_node_id]
    while stack:
        node_id = stack.pop()
        if node_id == from_node_id:
            return True
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(sorted(adjacency.get(node_id, set()), reverse=True))
    return False


def _has_final_invariant_check(projection: GraphProjection) -> bool:
    return any(
        kind == "check" and projection["node_roles"].get(node_id) == "invariant_gate"
        for node_id, kind in projection["node_kinds"].items()
    )


def _current_passed_verification_results(projection: GraphProjection) -> list[dict[str, str]]:
    failed_candidates = projection["failed_verification_candidate_ids"]
    current: list[dict[str, str]] = []
    for verification in projection["passed_verification_results_by_record_id"].values():
        verification_dict = _verification_result_dict(verification)
        if verification_dict is None:
            continue
        if verification_dict.get("candidate_id") in failed_candidates:
            continue
        current.append(verification_dict)
    return current


def _final_checks_waiting_for_verification_evidence(
    projection: GraphProjection,
) -> list[str]:
    waiting: list[str] = []
    for node_id, kind in sorted(projection["node_kinds"].items()):
        if kind != "check":
            continue
        if projection["node_roles"].get(node_id) != "invariant_gate":
            continue
        if projection["node_states"].get(node_id) not in {"planned", "blocked", "ready"}:
            continue
        if "verification_evidence" in projection["input_bindings"].get(node_id, {}):
            continue
        waiting.append(node_id)
    return waiting


def _has_verification_evidence_edge(
    projection: GraphProjection,
    verifier_node_id: str,
    check_node_id: str,
) -> bool:
    for edge in projection["edges"].values():
        if edge.get("from_node_id") != verifier_node_id:
            continue
        if edge.get("from_port") != "verification_report":
            continue
        if edge.get("to_node_id") != check_node_id:
            continue
        if edge.get("to_port") == "verification_evidence":
            return True
    return False


def _unreachable_failure_branch_node_ids(
    projection: GraphProjection,
    passed_verifier_node_id: str,
) -> list[str]:
    roots: list[str] = []
    for edge in projection["edges"].values():
        if edge.get("from_node_id") != passed_verifier_node_id:
            continue
        if edge.get("from_port") != "verification_report":
            continue
        if edge.get("to_port") != "verification_evidence":
            continue
        if _selector_value_match(edge, "verdict") != "failed":
            continue
        to_node_id = edge.get("to_node_id")
        if isinstance(to_node_id, str):
            roots.append(to_node_id)
    return _downstream_retirable_node_ids(projection, roots)


def _unreachable_check_failure_branch_node_ids(
    projection: GraphProjection,
    passed_check_node_id: str,
) -> list[str]:
    roots: list[str] = []
    for edge in projection["edges"].values():
        if edge.get("from_node_id") != passed_check_node_id:
            continue
        if edge.get("from_port") != "check_result":
            continue
        to_node_id = edge.get("to_node_id")
        if not isinstance(to_node_id, str):
            continue
        if edge.get("required") is not False and not _is_gap_planner(projection, to_node_id):
            continue
        roots.append(to_node_id)
    return _downstream_retirable_node_ids(projection, roots)


def _downstream_retirable_node_ids(
    projection: GraphProjection,
    root_node_ids: list[str],
) -> list[str]:
    terminal_states = {"completed", "failed", "cancelled", "retired"}
    seen: set[str] = set()
    output: list[str] = []
    stack = list(reversed(root_node_ids))
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        state = projection["node_states"].get(node_id)
        if state in terminal_states or state is None:
            continue
        if _is_final_invariant_check(projection, node_id):
            continue
        output.append(node_id)
        downstream = [
            edge.get("to_node_id")
            for edge in projection["edges"].values()
            if edge.get("from_node_id") == node_id
            and edge.get("dependency_type") != "state_dependency"
        ]
        for downstream_node_id in reversed(downstream):
            if isinstance(downstream_node_id, str):
                stack.append(downstream_node_id)
    return output


def _is_final_invariant_check(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "check"
        and projection["node_roles"].get(node_id) == "invariant_gate"
    )


def _is_gap_planner(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "gap_planner"
        or projection["node_roles"].get(node_id) == "gap_planner"
    )


def _selector_value_match(edge: dict[str, Any], key: str) -> Any:
    selector = edge.get("accepted_record_selector")
    if not isinstance(selector, dict):
        return None
    typed_selector = cast(dict[str, Any], selector)
    record_type = typed_selector.get("record_type")
    if record_type == "verification_report" and key in {"verdict", "outcome"}:
        return typed_selector.get("outcome")
    if record_type == "check_result" and key == "status":
        return typed_selector.get("status")
    if record_type == "gap_classification" and key == "classification":
        return typed_selector.get("classification")
    return None


def _retire_node_events(
    projection: GraphProjection,
    node_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    if projection["node_states"].get(node_id) in {"completed", "failed", "cancelled", "retired"}:
        return []
    return [
        typed_topology_event(
            make_event,
            "node_retired",
            {
                "node_id": node_id,
                "reason": "unreachable_after_passed_terminal_evidence",
            },
        ),
        typed_topology_event(
            make_event,
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "retired",
                "trigger": "passed_terminal_evidence_recovery",
            },
        ),
    ]


def _has_existing_failed_verification_recovery(
    projection: GraphProjection,
    verification: dict[str, str],
) -> bool:
    node_id = verification["node_id"]
    for edge in projection["edges"].values():
        if edge.get("from_node_id") != node_id:
            continue
        if edge.get("from_port") != "verification_report":
            continue
        if edge.get("to_port") != "verification_evidence":
            continue
        to_node_id = edge.get("to_node_id")
        if not isinstance(to_node_id, str):
            continue
        if projection["node_states"].get(to_node_id) in {"cancelled", "failed", "retired"}:
            continue
        if projection["node_kinds"].get(to_node_id) == "planner" and (
            projection["node_roles"].get(to_node_id) == "gap_planner"
        ):
            return True
    return False


def _current_failed_check_results(projection: GraphProjection) -> list[dict[str, str]]:
    failed: list[dict[str, str]] = []
    for node_id, result in sorted(projection["check_results"].items()):
        status = result.status
        if status in {"passed", "pass", "ok"}:
            continue
        record_id = result.record_id
        if not isinstance(record_id, str) or not record_id:
            continue
        check_result = {"node_id": node_id, "record_id": record_id}
        classification = result.classification
        if isinstance(classification, str) and classification:
            check_result["classification"] = classification
        task_region_id = result.task_region_id
        if isinstance(task_region_id, str) and task_region_id:
            check_result["task_region_id"] = task_region_id
        failed.append(check_result)
    for node_id, ports in sorted(projection["accepted_output_records_by_node_port"].items()):
        if projection["node_kinds"].get(node_id) != "check":
            continue
        if projection["node_states"].get(node_id) in {"cancelled", "retired"}:
            continue
        if node_id in projection["check_results"]:
            continue
        for accepted_record in ports.get("failure_record", []):
            record_id = accepted_record.get("record_id")
            payload = accepted_record.get("payload")
            if not record_id:
                continue
            if not payload:
                continue
            payload_data = payload.model_dump(mode="json")
            check_result = {
                "node_id": node_id,
                "record_id": record_id,
                "record_type": "failure_record",
            }
            task_region_id = payload_data.get("task_region_id")
            if not isinstance(task_region_id, str) or not task_region_id:
                task_region_id = projection["node_task_regions"].get(node_id)
            if isinstance(task_region_id, str) and task_region_id:
                check_result["task_region_id"] = task_region_id
            failed.append(check_result)
    return failed


def _has_existing_failed_check_recovery(
    projection: GraphProjection,
    failed_check: dict[str, str],
) -> bool:
    node_id = failed_check["node_id"]
    source_port = (
        "failure_record" if failed_check.get("record_type") == "failure_record" else "check_result"
    )
    for edge in projection["edges"].values():
        if edge.get("from_node_id") != node_id:
            continue
        if edge.get("from_port") != source_port:
            continue
        if edge.get("to_port") != "verification_evidence":
            continue
        to_node_id = edge.get("to_node_id")
        if not isinstance(to_node_id, str):
            continue
        if projection["node_states"].get(to_node_id) in {"cancelled", "failed", "retired"}:
            continue
        if projection["node_kinds"].get(to_node_id) == "planner" and (
            projection["node_roles"].get(to_node_id) == "gap_planner"
        ):
            return True
    return False


def _latest_routine_snapshot_record(projection: GraphProjection) -> dict[str, str] | None:
    record = projection.get("latest_routine_snapshot_record")
    if record is not None:
        return {
            "record_id": record.record_id,
            "producer_node_id": record.producer_node_id,
            "port": record.port,
        }
    latest: dict[str, str] | None = None
    for summary in projection["accepted_record_summaries_by_id"].values():
        record_id = summary.get("record_id")
        producer_node_id = summary.get("producer_node_id")
        port = summary.get("producer_port")
        if not all(
            isinstance(value, str) and value for value in (record_id, producer_node_id, port)
        ):
            continue
        is_routine_snapshot = (
            summary.get("record_type") == "routine_snapshot"
            or summary.get("record_kind") == "routine_snapshot"
            or summary.get("schema") == "RoutineSnapshot"
            or (producer_node_id == "routine-snapshot" and port in {"snapshot", "routine_snapshot"})
        )
        if not is_routine_snapshot:
            continue
        latest = {
            "record_id": cast(str, record_id),
            "producer_node_id": cast(str, producer_node_id),
            "port": cast(str, port),
        }
    return latest


def _failed_check_recovery_node_id(check_result: dict[str, str]) -> str:
    return f"planner-recover-{_stable_graph_id_part(check_result['record_id'])}"


def _failed_verification_recovery_node_id(verification: dict[str, str]) -> str:
    return f"planner-recover-{_stable_graph_id_part(verification['record_id'])}"


def _stable_graph_id_part(value: str) -> str:
    chars = [
        char.lower() if char.isalnum() or char in {"-", "_", "."} else "-" for char in value.strip()
    ]
    normalized = "".join(chars).strip("-")
    return normalized or "unknown"


def _base_snapshot_id_for_node(
    projection: GraphProjection,
    payload: dict[str, Any],
    node_id: str,
) -> str | None:
    """Resolve a node's base snapshot from command override or input bindings.

    Returns None when no snapshot identity exists — the scheduler defers the
    node rather than fabricating an identity (PRD §19: every lease carries a
    real base snapshot).
    """
    override = payload.get("base_snapshot_id")
    if isinstance(override, str) and override:
        return override

    bindings = projection["input_bindings"].get(node_id, {})
    for port in ("base_snapshot", "root_snapshot", "routine_snapshot"):
        record_ids = bindings.get(port, {}).get("record_ids")
        if isinstance(record_ids, list) and record_ids:
            first_record_id = cast(list[Any], record_ids)[0]
            if isinstance(first_record_id, str) and first_record_id:
                return first_record_id
    return None


def _retry_backoff_deferred_reason(
    projection: GraphProjection,
    node_id: str,
    now: datetime,
) -> str | None:
    retry_not_before = projection["retry_not_before_by_node"].get(node_id)
    if retry_not_before is None:
        return None
    try:
        retry_at = datetime.fromisoformat(retry_not_before)
    except ValueError:
        return None
    if retry_at <= now:
        return None
    return f"retry_backoff_until:{retry_not_before}"


def _planner_session_id(
    projection: GraphProjection,
    node_id: str,
    id_gen: IdGenerator,
) -> str | None:
    if not _is_chain_planner(projection, node_id):
        return None
    session_id = projection["planner_sessions"].get(node_id)
    if isinstance(session_id, str):
        return session_id
    return id_gen.next_id("session")


def _next_lease_generation(projection: GraphProjection, node_id: str) -> int:
    if not _is_chain_planner(projection, node_id):
        return 1
    session_id = projection["planner_sessions"].get(node_id)
    generations = [
        lease.get("generation")
        for lease in projection["leases"].values()
        if session_id is not None
        and lease.get("session_id") == session_id
        and isinstance(lease.get("generation"), int)
    ]
    return max(cast(list[int], generations), default=0) + 1


def _session_carryover_record_id(projection: GraphProjection, node_id: str) -> str | None:
    binding = projection["input_bindings"].get(node_id, {}).get("session_carryover")
    if binding is None:
        return None
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list) or not record_ids:
        return None
    record_id = cast(list[Any], record_ids)[0]
    return record_id if isinstance(record_id, str) else None


def _is_chain_planner(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "planner"
        and projection["node_roles"].get(node_id) == "planner"
    )


def _decision_output_record(
    projection: GraphProjection,
    node_id: str,
    event_payload: dict[str, Any],
    decision_type: Any,
) -> dict[str, Any] | None:
    node_kind = projection["node_kinds"].get(node_id)
    if decision_type == "authority" or node_kind == "authority_request":
        record_type = "authority_decision"
        port = "authority_decision"
        schema = "AuthorityDecision"
    elif decision_type == "approval" or node_kind in {"gate", "human_gate"}:
        record_type = "decision_record"
        port = "decision_record"
        schema = "DecisionRecord"
    else:
        return None
    record_id = event_payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = f"{record_type}-{node_id}"
    value = {
        "decision": event_payload.get("decision"),
        "decision_type": decision_type,
        "decider": event_payload.get("decider"),
        "scope": event_payload.get("scope"),
        "expires_at": event_payload.get("expires_at"),
        "reason": event_payload.get("reason"),
    }
    record_payload = {
        "record_id": record_id,
        "record_kind": "output",
        "record_type": record_type,
        "producer_node_id": node_id,
        "port": port,
        "schema": schema,
        "value": {key: entry for key, entry in value.items() if entry is not None},
    }
    if record_type == "authority_decision":
        return AuthorityDecisionRecord.model_validate(record_payload).model_dump(mode="json")
    return DecisionRecord.model_validate(record_payload).model_dump(mode="json")


def _request_record_events_for_node(
    node_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for record_payload, to_port in _request_record_bindings_for_node(node_payload):
        output.append(
            make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": record_payload})
        )
        record_id = record_payload["record_id"]
        node_id = record_payload["producer_node_id"]
        output.append(
            typed_topology_event(
                make_event,
                "input_bound",
                {
                    "edge_id": f"edge-{record_id}-to-{node_id}-{to_port}",
                    "to_node_id": node_id,
                    "to_port": to_port,
                    "record_ids": [record_id],
                    "bound_at_position": 0,
                    "binding_policy": "bind_latest",
                },
            )
        )
    return output


def _request_record_bindings_for_node(
    node_payload: dict[str, Any],
) -> list[tuple[dict[str, Any], str]]:
    kind = node_payload.get("kind")
    if kind == "human_gate":
        record = _decision_request_record_for_node(node_payload)
        return [(record.model_dump(mode="json"), "decision_request")]
    if kind == "authority_request":
        record = _authority_request_record_for_node(node_payload)
        return [(record.model_dump(mode="json"), "authority_request_record")]
    return []


def _decision_request_record_for_node(node_payload: dict[str, Any]) -> DecisionRequestRecord:
    node_id = _required_node_id_for_request_record(node_payload)
    raw_request = _request_payload_object(node_payload, "decision_request")
    value = dict(raw_request)
    value.setdefault(
        "decision_type", _request_payload_string(node_payload, "decision_type") or "approval"
    )
    value.setdefault("options", ["approve", "reject"])
    value.setdefault(
        "consequence_summary",
        _request_payload_string(node_payload, "reason")
        or "Manual decision required before graph can continue.",
    )
    return DecisionRequestRecord.model_validate(
        {
            "record_id": _request_payload_string(node_payload, "decision_request_record_id")
            or f"decision-request-{node_id}",
            "record_kind": "graph_record",
            "record_type": "decision_request",
            "producer_node_id": node_id,
            "port": "decision_request",
            "schema": "DecisionRequest",
            "value": value,
        }
    )


def _authority_request_record_for_node(node_payload: dict[str, Any]) -> AuthorityRequestRecord:
    node_id = _required_node_id_for_request_record(node_payload)
    raw_request = _request_payload_object(
        node_payload,
        "authority_request_record",
        alias="authority_request",
    )
    value = dict(raw_request)
    value.setdefault(
        "reason", _request_payload_string(node_payload, "reason") or "Authority required."
    )
    target_region_id = _request_payload_string(node_payload, "task_region_id")
    if target_region_id is not None:
        value.setdefault("target_region_id", target_region_id)
    return AuthorityRequestRecord.model_validate(
        {
            "record_id": _request_payload_string(node_payload, "authority_request_record_id")
            or f"authority-request-{node_id}",
            "record_kind": "graph_record",
            "record_type": "authority_request_record",
            "producer_node_id": node_id,
            "port": "authority_request_record",
            "schema": "AuthorityRequest",
            "value": value,
        }
    )


def _required_node_id_for_request_record(node_payload: dict[str, Any]) -> str:
    node_id = node_payload.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        msg = "request record node requires node_id"
        raise ValueError(msg)
    return node_id


def _request_payload_object(
    node_payload: dict[str, Any],
    key: str,
    *,
    alias: str | None = None,
) -> dict[str, Any]:
    raw_request = node_payload.get(key)
    if raw_request is None and alias is not None:
        raw_request = node_payload.get(alias)
        key = alias if raw_request is not None else key
    if raw_request is None:
        return {}
    if not isinstance(raw_request, dict):
        msg = f"{key} must be an object"
        raise ValueError(msg)
    request = dict(cast(dict[str, Any], raw_request))
    value = request.get("value")
    if isinstance(value, dict):
        return dict(cast(dict[str, Any], value))
    return request


def _request_payload_string(node_payload: dict[str, Any], key: str) -> str | None:
    value = node_payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _patch_op_events(
    op: PatchOp,
    projection: GraphProjection,
    events: list[EventEnvelope],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    inherited_session_id: str | None = None,
    carryover_record_id: str | None = None,
) -> list[EventEnvelope]:
    op_payload = _op_payload(op)
    if op.op == "create_node" and isinstance(op.node, dict):
        node_payload = dict(op.node)
        _ensure_default_node_authority(node_payload)
        canonicalize_check_command_definition(node_payload, events)
        if node_payload.get("kind") == "planner" and node_payload.get("role") == "planner":
            if inherited_session_id is not None:
                node_payload.setdefault("session_id", inherited_session_id)
            _ensure_optional_session_carryover_input(node_payload)
            if carryover_record_id is not None:
                node_payload["carryover_record_id"] = carryover_record_id
        output = [typed_topology_event(make_event, "node_created", node_payload)]
        output.extend(_request_record_events_for_node(node_payload, make_event))
        return output
    if op.op == "create_edge":
        edge_id = op_payload.get("edge_id")
        required = op_payload.get("required")
        edge_payload = {
            "edge_id": edge_id,
            "from_node_id": op.from_node_id,
            "from_port": _canonical_patch_edge_from_port(op.from_port),
            "to_node_id": op.to_node_id,
            "to_port": op.to_port,
            "required": required if isinstance(required, bool) else True,
            "dependency_type": op_payload.get("dependency_type", "input_binding"),
        }
        for key in (
            "from_node_kind",
            "from_node_role",
            "purpose",
            "description",
            "selection",
            "binding_policy",
            "freshness_policy",
            "prompt_hydration_policy",
            "metadata",
        ):
            if key in op_payload:
                edge_payload[key] = op_payload[key]
        selector = op_payload.get("accepted_record_selector")
        if isinstance(selector, dict):
            edge_payload["accepted_record_selector"] = normalize_record_selector(selector)
        output = [typed_topology_event(make_event, "edge_created", edge_payload)]
        output.extend(_input_bound_events_for_edge(projection, edge_payload, make_event))
        return output
    if op.op == "retire_node" and isinstance(op.node_id, str):
        return [
            typed_topology_event(make_event, "node_retired", {"node_id": op.node_id}),
            typed_topology_event(
                make_event,
                "node_state_changed",
                {"node_id": op.node_id, "new_state": "retired", "trigger": "graph_patch_accepted"},
            ),
        ]
    if op.op == "create_gate":
        node_payload = _node_payload_for_op(op_payload, default_kind="gate")
        return [typed_topology_event(make_event, "node_created", node_payload)]
    if op.op == "create_revision_attempt":
        events = [
            typed_topology_event(
                make_event,
                "revision_created",
                {
                    key: value
                    for key, value in op_payload.items()
                    if key not in {"op", "node", "worker_node", "verifier_node"}
                },
            )
        ]
        for node_key, default_kind in (("worker_node", "worker"), ("verifier_node", "verifier")):
            raw_node = op_payload.get(node_key)
            if isinstance(raw_node, dict):
                events.append(
                    typed_topology_event(
                        make_event,
                        "node_created",
                        _node_payload_for_op(
                            {"node": raw_node, **op_payload},
                            default_kind=default_kind,
                        ),
                    )
                )
        if len(events) == 1:
            events.append(
                typed_topology_event(
                    make_event,
                    "node_created",
                    _node_payload_for_op(op_payload, default_kind="worker"),
                )
            )
        return events
    if op.op == "create_appeal":
        node_payload = _node_payload_for_op(op_payload, default_kind="appeal")
        appeal_payload = {
            key: value
            for key, value in op_payload.items()
            if key not in {"op", "node", "kind", "state"}
        }
        appeal_payload.setdefault("node_id", node_payload["node_id"])
        return [
            typed_topology_event(make_event, "node_created", node_payload),
            _make_strict_event(make_event, APPEAL_OPENED, appeal_payload),
        ]
    if op.op == "set_resource_claims" and isinstance(op.node_id, str):
        return [
            typed_topology_event(
                make_event,
                "node_authority_changed",
                {
                    "node_id": op.node_id,
                    "resource_claims": [claim.model_dump() for claim in op.resource_claims or []],
                },
            )
        ]
    if op.op == "set_allowed_actions" and isinstance(op.node_id, str):
        return [
            typed_topology_event(
                make_event,
                "node_authority_changed",
                {
                    "node_id": op.node_id,
                    "allowed_actions": list(op.allowed_actions or []),
                },
            )
        ]
    if op.op == "mark_plan_region_suspect":
        return [
            typed_topology_event(
                make_event,
                "plan_region_marked_suspect",
                {key: value for key, value in op_payload.items() if key != "op"},
            )
        ]
    return []


def _ensure_default_node_authority(node_payload: dict[str, Any]) -> None:
    if node_payload.get("kind") != "worker":
        return
    raw_authority = node_payload.get("authority")
    authority = dict(cast(dict[str, Any], raw_authority)) if isinstance(raw_authority, dict) else {}
    authority.setdefault(
        "allowed_actions",
        ["submit_records", "request_clarification", "raise_appeal"],
    )
    if "resource_claims" not in authority:
        authority["resource_claims"] = [{"mode": "write", "scope": "repo", "paths": ["."]}]
    for key in ("resource_claims", "allowed_actions", "preconditions"):
        if key in authority:
            node_payload.setdefault(key, authority[key])
    node_payload.pop("authority", None)


def _ensure_optional_session_carryover_input(node_payload: dict[str, Any]) -> None:
    inputs = node_payload.get("inputs")
    if not isinstance(inputs, list):
        node_payload["inputs"] = [
            {"port": "session_carryover", "direction": "input", "required": False}
        ]
        return
    typed_inputs = cast(list[Any], inputs)
    for raw_input in typed_inputs:
        if not isinstance(raw_input, dict):
            continue
        input_payload = cast(dict[str, Any], raw_input)
        if input_payload.get("port") == "session_carryover":
            input_payload["required"] = False
            return
    typed_inputs.append({"port": "session_carryover", "direction": "input", "required": False})


def _expired_lease_events(
    projection: GraphProjection,
    now: datetime,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    expired: list[EventEnvelope] = []
    for lease in projection["leases"].values():
        if not _lease_is_expired(lease, now):
            continue
        node_id = lease.get("node_id")
        expired.append(
            _make_strict_event(
                make_event,
                LEASE_EXPIRED,
                _typed_lease_event_payload(
                    "lease_expired",
                    {
                        "lease_id": lease.get("lease_id"),
                        "node_id": node_id,
                        "generation": lease.get("generation"),
                        "execution_id": lease.get("execution_id"),
                        "expires_at": datetime.fromisoformat(cast(str, lease.get("expires_at"))),
                        "reason": "lease_expired_without_callback",
                    },
                ),
            )
        )
        if isinstance(node_id, str):
            lease_id = lease.get("lease_id")
            typed_lease_id = lease_id if isinstance(lease_id, str) else None
            expired.append(
                make_strict_event(
                    make_event,
                    OUTPUT_RECORD_ACCEPTED,
                    {
                        "record": _failure_record_payload(
                            node_id=node_id,
                            phase="runtime",
                            error_class="lease_expired_without_callback",
                            retryable=False,
                            lease_id=typed_lease_id,
                            execution_id=lease.get("execution_id"),
                            generation=lease.get("generation"),
                            reason="lease_expired_without_callback",
                            metadata={"expires_at": lease.get("expires_at")},
                        )
                    },
                )
            )
            expired.append(
                typed_topology_event(
                    make_event,
                    "node_state_changed",
                    {
                        "node_id": node_id,
                        "new_state": "failed",
                        "trigger": "lease_expired_without_callback",
                        "reason": "lease_expired_without_callback",
                    },
                )
            )
    return expired


def _expired_active_lease_ids(projection: GraphProjection, now: datetime) -> set[str]:
    return {
        lease_id
        for lease in projection["leases"].values()
        if isinstance((lease_id := lease.get("lease_id")), str) and _lease_is_expired(lease, now)
    }


def _lease_is_expired(lease: dict[str, Any], now: datetime) -> bool:
    if lease.get("state") != "active":
        return False
    expires_at = lease.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    return datetime.fromisoformat(expires_at) <= now


def _op_payload(op: PatchOp) -> dict[str, Any]:
    return op.model_dump(exclude_none=True)


def _canonical_patch_edge_from_port(from_port: str | None) -> str | None:
    if from_port == "verification_result":
        return "verification_report"
    return from_port


def _node_payload_for_op(op_payload: dict[str, Any], *, default_kind: str) -> dict[str, Any]:
    raw_node = op_payload.get("node")
    node_payload = dict(cast(dict[str, Any], raw_node)) if isinstance(raw_node, dict) else {}
    node_id = node_payload.get("node_id")
    if not isinstance(node_id, str):
        for key in ("node_id", "gate_id", "appeal_node_id", "revision_node_id"):
            value = op_payload.get(key)
            if isinstance(value, str):
                node_id = value
                break
    node_payload["node_id"] = node_id if isinstance(node_id, str) else default_kind
    node_payload.setdefault("kind", default_kind)
    node_payload.setdefault("state", "planned")
    for key in (
        "task_region_id",
        "attempt_number",
        "candidate_id",
        "generation_index",
        "region_label",
        "session_id",
        "predecessor_node_ids",
        "appealed_node_id",
        "failed_candidate_id",
    ):
        if key in op_payload and key not in node_payload:
            node_payload[key] = op_payload[key]
    _ensure_default_node_authority(node_payload)
    membership = node_payload.pop("membership", None)
    if isinstance(membership, dict):
        for key, value in cast(dict[str, Any], membership).items():
            node_payload.setdefault(key, value)
    return node_payload


def _input_bound_events_for_edge(
    projection: GraphProjection,
    edge_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    if edge_payload.get("dependency_type", "input_binding") != "input_binding":
        return []
    edge_id = edge_payload.get("edge_id")
    from_node_id = edge_payload.get("from_node_id")
    from_port = edge_payload.get("from_port")
    to_node_id = edge_payload.get("to_node_id")
    to_port = edge_payload.get("to_port")
    if not all(
        isinstance(value, str) for value in (edge_id, from_node_id, from_port, to_node_id, to_port)
    ):
        return []
    typed_edge_id = cast(str, edge_id)
    typed_from_node_id = cast(str, from_node_id)
    typed_from_port = cast(str, from_port)
    typed_to_node_id = cast(str, to_node_id)
    typed_to_port = cast(str, to_port)

    output: list[EventEnvelope] = []
    for producer_node_id in _edge_backfill_producer_node_ids(
        projection,
        edge_payload,
        typed_from_node_id,
    ):
        records_by_port = projection["output_records_by_node_port"].get(producer_node_id, {})
        for record in records_by_port.get(typed_from_port, []):
            record_payload = record.model_dump(mode="json")
            record_id = record_payload.get("record_id")
            if not isinstance(record_id, str):
                continue
            if not record_selector_matches(
                edge_payload.get("accepted_record_selector"),
                record_payload,
                _record_selector_aliases(record_payload),
            ):
                continue
            binding_payload: dict[str, Any] = {
                "edge_id": typed_edge_id,
                "to_node_id": typed_to_node_id,
                "to_port": typed_to_port,
                "record_ids": [record_id],
                "bound_at_position": 0,
                "trigger": "edge_backfill",
            }
            binding_policy = edge_payload.get("binding_policy")
            if isinstance(binding_policy, str):
                binding_payload["binding_policy"] = binding_policy
            supersedes_record_id = record_payload.get("supersedes_record_id")
            if isinstance(supersedes_record_id, str):
                binding_payload["supersedes_record_id"] = supersedes_record_id
            output.append(typed_topology_event(make_event, "input_bound", binding_payload))
    return output


def _edge_accepts_producer(
    projection: GraphProjection,
    edge: dict[str, Any],
    producer_node_id: str,
) -> bool:
    from_node_id = edge.get("from_node_id")
    if from_node_id == producer_node_id:
        return True
    if from_node_id != "*":
        return False
    expected_kind = edge.get("from_node_kind")
    if (
        isinstance(expected_kind, str)
        and projection["node_kinds"].get(producer_node_id) != expected_kind
    ):
        return False
    expected_role = edge.get("from_node_role")
    if (
        isinstance(expected_role, str)
        and projection["node_roles"].get(producer_node_id) != expected_role
    ):
        return False
    return True


def _edge_backfill_producer_node_ids(
    projection: GraphProjection,
    edge: dict[str, Any],
    from_node_id: str,
) -> list[str]:
    if from_node_id != "*":
        return [from_node_id]
    return [
        node_id
        for node_id in sorted(projection["node_kinds"])
        if _edge_accepts_producer(projection, edge, node_id)
    ]


def _record_selector_aliases(record_payload: dict[str, Any]) -> set[str]:
    record_kind = record_payload.get("record_kind")
    if record_kind == "verification":
        return {"verification_result"}
    if record_kind == "file_state":
        return {"accepted_file_state", "file_state"}
    return set()


def _event_factory(
    run_id: str,
    command_type: str,
    clock: Clock,
    id_gen: IdGenerator,
) -> Callable[[str, dict[str, Any]], EventEnvelope]:
    def make_event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
        topology_specification = _TOPOLOGY_EVENT_SPECS.get(event_type)
        typed_payload = (
            topology_specification.validate_payload(payload).to_json()
            if topology_specification is not None
            else _typed_lifecycle_event_payload(event_type, payload)
        )
        return EventEnvelope(
            event_id=id_gen.next_id("event"),
            run_id=run_id,
            position=-1,
            event_type=event_type,
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            causation_id=command_type,
            timestamp=clock.now(),
            payload=typed_payload,
        )

    return make_event


def _run_id(events: Sequence[EventEnvelope | HydratedEvent], payload: dict[str, Any]) -> str:
    run_id = payload.get("run_id")
    if isinstance(run_id, str):
        return run_id
    if events:
        event = events[-1]
        return event.metadata.run_id if isinstance(event, HydratedEvent) else event.run_id
    return "run-1"


def _current_position(
    events: Sequence[EventEnvelope | HydratedEvent],
    payload: dict[str, Any] | None = None,
) -> int:
    if not events:
        current = (payload or {}).get("_current_graph_position")
        if isinstance(current, int) and not isinstance(current, bool):
            return current
        return -1
    return max(
        event.metadata.position if isinstance(event, HydratedEvent) else event.position
        for event in events
    )


def _claim_from_dict(claim: Any) -> ResourceClaim:
    claim_payload = _resource_claim_payload(claim)
    mode = str(claim_payload.get("mode", "read"))
    scope = str(claim_payload.get("scope", "repo"))
    paths = (
        [str(path) for path in claim_payload.get("paths", [])]
        if isinstance(claim_payload.get("paths"), list)
        else []
    )
    # Self-healing normalization (also applied on replay of historic events): planners
    # sometimes put a repo-relative path prefix directly in `scope` instead of the
    # canonical scope="repo" + paths=[...] shape. For read/write claims (the only modes
    # whose scheduling/authority semantics key off `scope == "repo"`), fold a
    # path-shaped scope into `paths` so both the scheduler-conflict check and the
    # write-authority check (`_claim_is_repo_write`) see identical, correct semantics.
    # external/graph_write/review_write claims use `scope` for other purposes (or not at
    # all) and are left untouched.
    if mode in {"read", "write"} and scope not in ("repo", ""):
        if scope not in paths:
            paths = [*paths, scope]
        scope = "repo"
    return ResourceClaim(
        mode=mode,
        scope=scope,
        paths=paths,
        snapshot_id=cast(str | None, claim_payload.get("snapshot_id")),
        external_resource_key=cast(str | None, claim_payload.get("external_resource_key")),
        exclusive=bool(claim_payload.get("exclusive", False)),
    )


def _resource_claim_payload(claim: Any) -> dict[str, Any]:
    if hasattr(claim, "model_dump"):
        dumped = claim.model_dump(mode="json")
        if isinstance(dumped, dict):
            return cast(dict[str, Any], dumped)
    if isinstance(claim, dict):
        return dict(cast(dict[str, Any], claim))
    return {}


apply_seed_compiled_events = _apply_seed_compiled_events
apply_patch_command = _apply_patch_command
apply_schedule_tick = schedule_tick_effects
apply_reconcile = _apply_reconcile
decision_output_record = _decision_output_record
input_bound_events_for_record = _input_bound_events_for_record
record_selector_aliases = _record_selector_aliases
release_active_node_leases = _release_active_node_leases


__all__ = [
    "_make_strict_event",
    "_typed_lease_event_payload",
    "_has_passed_completion_decision",
    "_lifecycle_completion_decision_event",
    "_cancel_active_lease_events",
    "_lease_node_id",
    "_output_record_provenance_conflict",
    "_file_state_rejected_conflict",
    "_file_state_authority_conflict",
    "_file_state_rejected_events",
    "_output_record_contract_conflict",
    "_accepted_output_record_events",
    "_verification_record_conflict",
    "_required_output_record_conflict",
    "_source_repair_events",
    "_planner_session_state_event",
    "_failure_record_payload",
    "_recovery_plan_record_payload",
    "_non_gap_planner_has_accepted_patch",
    "_is_rate_limit_death",
    "_is_non_retryable_runtime_death",
    "_positive_int",
    "_lifecycle_event",
    "_command_rejected",
    "_callback_payload",
]


def _make_strict_event(
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    specification: EventSpecification[Any],
    payload: dict[str, Any],
) -> EventEnvelope:
    validated = specification.validate_payload(payload)
    return make_event(
        specification.name,
        cast(dict[str, Any], validated.model_dump(mode="json", by_alias=True, exclude_unset=True)),
    )


def make_strict_event(
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    specification: EventSpecification[Any],
    payload: dict[str, Any],
) -> EventEnvelope:
    return _make_strict_event(make_event, specification, payload)


def _typed_lease_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    del event_type
    return payload


def _has_passed_completion_decision(projection: GraphProjection) -> bool:
    return projection["completion_decision_passed"]


def _lifecycle_completion_decision_event(
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> EventEnvelope:
    record_id = payload.get("completion_decision_record_id") or payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = id_gen.next_id("completion-decision")
    producer_node_id = payload.get("node_id")
    if not isinstance(producer_node_id, str) or not producer_node_id:
        producer_node_id = "run_lifecycle"
    record = CompletionDecisionRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": "completion_decision",
            "producer_node_id": producer_node_id,
            "port": "completion_decision",
            "schema": "CompletionDecision",
            "value": {"status": "passed", "blockers": []},
            "provenance": {"source": "lifecycle_complete"},
        }
    )
    return make_strict_event(
        make_event,
        OUTPUT_RECORD_ACCEPTED,
        {"record": record.model_dump(mode="json")},
    )


def _cancel_active_lease_events(
    projection: GraphProjection,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    trigger: Any,
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for lease_id, lease in sorted(projection["leases"].items()):
        if lease.get("state") not in {"active", "suspended"}:
            continue
        node_id = lease.get("node_id")
        if not isinstance(node_id, str):
            continue
        revoke_payload: dict[str, Any] = {
            "node_id": node_id,
            "lease_id": lease_id,
            "trigger": trigger,
            "reason": "run_cancelled",
        }
        generation = lease.get("generation")
        if isinstance(generation, int) and not isinstance(generation, bool):
            revoke_payload["generation"] = generation
        execution_id = lease.get("execution_id")
        if isinstance(execution_id, str):
            revoke_payload["execution_id"] = execution_id
        output.append(
            _make_strict_event(
                make_event,
                LEASE_REVOKED,
                _typed_lease_event_payload("lease_revoked", revoke_payload),
            )
        )

        node_state = projection["node_states"].get(node_id)
        if node_state not in {"completed", "failed", "cancelled", "retired"}:
            output.append(
                typed_topology_event(
                    make_event,
                    "node_state_changed",
                    {
                        "node_id": node_id,
                        "new_state": "cancelled",
                        "trigger": "run_cancelled",
                        "reason": "run_cancelled",
                    },
                )
            )
    return output


def _lease_node_id(projection: GraphProjection, lease_id: str) -> str | None:
    lease = projection["leases"].get(lease_id)
    if lease is None:
        return None
    node_id = lease.get("node_id")
    return node_id if isinstance(node_id, str) else None


def _output_record_provenance_conflict(
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None

    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        producer_node_id = record_payload.get("producer_node_id", expected_producer_node_id)
        if producer_node_id != expected_producer_node_id:
            return (
                "output record producer_node_id does not match lease node "
                f"at index {index}: {producer_node_id} != {expected_producer_node_id}"
            )
        if record_payload.get("record_kind") == "file_state":
            node_id = record_payload.get("node_id", expected_producer_node_id)
            if node_id != expected_producer_node_id:
                return (
                    "file_state record node_id does not match lease node "
                    f"at index {index}: {node_id} != {expected_producer_node_id}"
                )
    return None


def _file_state_rejected_conflict(
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    rejection = request.payload.get("file_state_rejected") if request.payload is not None else None
    if not isinstance(rejection, dict):
        return None
    rejection_payload = cast(dict[str, Any], rejection)
    node_id = rejection_payload.get("node_id", expected_producer_node_id)
    if node_id != expected_producer_node_id:
        return (
            "file_state_rejected node_id does not match lease node: "
            f"{node_id} != {expected_producer_node_id}"
        )
    producer_node_id = rejection_payload.get("producer_node_id", expected_producer_node_id)
    if producer_node_id != expected_producer_node_id:
        return (
            "file_state_rejected producer_node_id does not match lease node: "
            f"{producer_node_id} != {expected_producer_node_id}"
        )
    return None


def _file_state_authority_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None
    lease = projection["leases"].get(request.lease_id)
    if lease is None:
        return None
    node_id = _lease_node_id(projection, request.lease_id) or request.node_id
    if projection["node_kinds"].get(node_id) != "worker":
        return None
    raw_claims = lease.get("resource_claims", [])
    if not isinstance(raw_claims, list):
        raw_claims = []
    write_claims: list[ResourceClaim] = []
    for raw_claim in cast(list[Any], raw_claims):
        write_claims.append(_claim_from_dict(raw_claim))
    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        if record_payload.get("record_kind") != "file_state":
            continue
        changed_paths = _file_state_changed_paths(record_payload)
        unauthorized = [
            path for path in changed_paths if not _repo_write_claim_covers_path(write_claims, path)
        ]
        if unauthorized:
            return (
                f"file_state path outside lease write authority at index {index}: {unauthorized[0]}"
            )
    return None


def _file_state_rejected_events(
    request: CallbackRequest,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    rejection = request.payload.get("file_state_rejected") if request.payload is not None else None
    if not isinstance(rejection, dict):
        return []
    payload = dict(cast(dict[str, Any], rejection))
    payload.setdefault("node_id", request.node_id)
    payload.setdefault("lease_id", request.lease_id)
    payload.setdefault("lease_generation", request.lease_generation)
    payload.setdefault("base_snapshot_id", request.base_snapshot_id)
    return [make_strict_event(make_event, FILE_STATE_REJECTED, payload)]


def _output_record_contract_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None

    typed_raw_records = cast(list[Any], raw_records)
    file_state_records = _same_callback_file_state_records(
        typed_raw_records,
        expected_producer_node_id,
    )
    node_kind = projection["node_kinds"].get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = projection["node_roles"].get(expected_producer_node_id)
    typed_role = node_role if isinstance(node_role, str) else None
    for index, raw_record in enumerate(typed_raw_records):
        if not isinstance(raw_record, dict):
            return f"malformed output record at index {index}"
        record_payload = dict(cast(dict[str, Any], raw_record))
        if record_payload.get("record_kind") == "file_state":
            record_payload.setdefault("port", "file_state")
            record_payload.setdefault("record_type", "file_state")
        if record_payload.get("record_kind") == "verification":
            record_payload.setdefault("port", "verification_report")
        record_run_id = record_payload.get("run_id")
        if record_run_id is not None and record_run_id != request.run_id:
            return f"output record at index {index} run_id does not match callback run: {record_run_id}"
        if _is_candidate_record_payload(record_payload):
            record_payload = _candidate_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            expected_file_state_ids = _file_state_record_ids_for_candidate(
                record_payload,
                file_state_records,
            )
            citation_conflict = _candidate_file_state_citation_conflict(
                record_payload,
                expected_file_state_ids,
                index,
            )
            if citation_conflict is not None:
                return citation_conflict
        if _is_check_result_record_payload(record_payload):
            record_payload = _check_result_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            citation_conflict = _evaluated_record_citation_conflict(
                projection,
                expected_producer_node_id,
                record_payload,
                index,
            )
            if citation_conflict is not None:
                return citation_conflict
        error = validate_output_record(
            node_kind=node_kind,
            node_role=typed_role,
            record_payload=record_payload,
            index=index,
        )
        if error is not None:
            return error
        if _is_candidate_record_payload(record_payload):
            try:
                CandidateRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"candidate record at index {index} is invalid: {exc}"
        if _is_check_result_record_payload(record_payload):
            try:
                CheckResultRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"check_result record at index {index} is invalid: {exc}"
        if _is_verification_report_record_payload(record_payload):
            try:
                _parse_verification_report_record(record_payload, expected_producer_node_id)
            except ValueError as exc:
                return f"verification record at index {index} is invalid: {exc}"
        if _is_analysis_summary_record_payload(record_payload):
            record_payload = _analysis_summary_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                AnalysisSummaryRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"analysis_summary record at index {index} is invalid: {exc}"
        if _is_graph_patch_proposal_record_payload(record_payload):
            record_payload = _graph_patch_proposal_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                GraphPatchProposalRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"graph_patch_proposal record at index {index} is invalid: {exc}"
        if _is_artifact_reference_record_payload(record_payload):
            record_payload = _artifact_reference_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                ArtifactReferenceRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"artifact_reference record at index {index} is invalid: {exc}"
    return None


def _accepted_output_record_events(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return []

    typed_raw_records = cast(list[Any], raw_records)
    file_state_records = _same_callback_file_state_records(
        typed_raw_records,
        expected_producer_node_id,
    )
    output: list[EventEnvelope] = []
    for raw_record in typed_raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_payload = dict(cast(dict[str, Any], raw_record))
        record_payload.setdefault("producer_node_id", expected_producer_node_id)
        if record_payload.get("record_kind") == "file_state":
            record_payload.setdefault("port", "file_state")
            record_payload.setdefault("record_type", "file_state")
        if _is_verification_report_record_payload(record_payload):
            output.extend(
                _accepted_verification_record_events(
                    projection,
                    request,
                    expected_producer_node_id,
                    record_payload,
                    make_event,
                )
            )
            continue
        if record_payload.get("record_kind") == "file_state":
            output.extend(
                _accepted_file_state_record_events(
                    projection,
                    expected_producer_node_id,
                    record_payload,
                    make_event,
                )
            )
            continue
        if _is_check_result_record_payload(record_payload):
            _add_evaluated_record_citations(record_payload, projection, expected_producer_node_id)
            record_payload = _check_result_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = CheckResultRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(
                make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload})
            )
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_candidate_record_payload(record_payload):
            _add_candidate_file_state_citations(
                record_payload,
                _file_state_record_ids_for_candidate(record_payload, file_state_records),
            )
            record_payload = _candidate_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = CandidateRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(
                make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload})
            )
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_analysis_summary_record_payload(record_payload):
            record_payload = _analysis_summary_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = AnalysisSummaryRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(
                make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload})
            )
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_graph_patch_proposal_record_payload(record_payload):
            record_payload = _graph_patch_proposal_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = GraphPatchProposalRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(
                make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload})
            )
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_artifact_reference_record_payload(record_payload):
            record_payload = _artifact_reference_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = ArtifactReferenceRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(
                make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload})
            )
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        try:
            record = OutputRecord.model_validate(record_payload)
        except ValueError:
            continue
        output.append(
            make_strict_event(
                make_event, OUTPUT_RECORD_ACCEPTED, {"record": record.model_dump(mode="json")}
            )
        )
        output.extend(
            _input_bound_events_for_record(
                projection,
                record.producer_node_id,
                record.port,
                record.record_id,
                record.model_dump(mode="json"),
                make_event,
            )
        )
    return output


def _verification_record_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None

    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        if not _is_verification_report_record_payload(record_payload):
            continue
        try:
            record = _parse_verification_report_record(record_payload, expected_producer_node_id)
        except ValueError as exc:
            return f"verification record at index {index} is invalid: {exc}"
        if projection["node_kinds"].get(expected_producer_node_id) != "verifier":
            return f"verification record at index {index} was not produced by a verifier"
        candidate_id = record.candidate_id
        if not _candidate_is_bound_to_verifier(projection, expected_producer_node_id, candidate_id):
            return (
                f"verification record candidate_id at index {index} is not bound "
                f"to verifier input: {candidate_id}"
            )
        if not record.value.grades:
            return f"verification record at index {index} missing grades"
        record_payload = record.model_dump(mode="json")
        citation_conflict = _evaluated_record_citation_conflict(
            projection,
            expected_producer_node_id,
            record_payload,
            index,
        )
        if citation_conflict is not None:
            return citation_conflict
    return None


def _required_output_record_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    *,
    successful_completion: bool,
) -> str | None:
    if not successful_completion:
        return None

    node_kind = projection["node_kinds"].get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = projection["node_roles"].get(expected_producer_node_id)
    typed_role = node_role if isinstance(node_role, str) else None
    contract = DEFAULT_NODE_CONTRACTS.contract_for(node_kind, typed_role)
    if contract is None:
        return f"output records produced by unknown node type: {node_kind}"

    required_ports = {port.name for port in contract.output_ports.values() if port.required}
    if not required_ports:
        return None

    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        raw_records = []
    produced_ports = {
        canonical_port
        for raw_record in cast(list[Any], raw_records)
        if isinstance(raw_record, dict)
        for canonical_port in [
            _output_record_contract_port(contract, cast(dict[str, Any], raw_record))
        ]
        if canonical_port is not None
    }
    missing = sorted(required_ports - produced_ports)
    if missing:
        return f"node completion missing required output record ports: {', '.join(missing)}"
    return None


def _source_repair_events(
    projection: GraphProjection,
    events: list[EventEnvelope],
    source_events: list[EventEnvelope],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    accepted_records = [
        cast(dict[str, Any], event.payload["record"])
        for event in source_events
        if event.event_type == "output_record_accepted"
        and isinstance(event.payload["record"], dict)
        and isinstance(cast(dict[str, Any], event.payload["record"]).get("record_id"), str)
    ]
    repair_node_ids = {
        node_id
        for event in source_events
        for node_id in (
            event.payload.get("proposed_by_node_id"),
            event.payload.get("node_id"),
        )
        if (
            event.event_type == "graph_patch_accepted"
            or (
                event.event_type == "node_state_changed"
                and event.payload.get("new_state") == "completed"
            )
        )
        and isinstance(node_id, str)
    }
    patch_or_completion = bool(repair_node_ids)
    if not accepted_records and not patch_or_completion:
        return []

    scoped_projection = _project_with_events(projection, source_events)
    active_lease_node_ids = _active_lease_node_ids(scoped_projection)
    output: list[EventEnvelope] = []
    for record in accepted_records:
        record_id = cast(str, record["record_id"])
        producer_node_id = record.get("producer_node_id") or record.get("node_id")
        if not isinstance(producer_node_id, str):
            continue
        if _is_check_result_record_payload(record):
            status = _check_result_status_value(record)
            if status in {"passed", "pass", "ok"}:
                output.extend(
                    _passed_check_terminalization_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        check_node_ids={producer_node_id},
                    )
                )
            else:
                output.extend(
                    _failed_check_recovery_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        record_ids={record_id},
                    )
                )
            continue
        if record.get("record_kind") == "verification":
            verdict = record.get("verdict")
            value = record.get("value")
            if verdict is None and isinstance(value, dict):
                verdict = cast(dict[str, Any], value).get("verdict")
            if verdict in {"passed", "pass"}:
                output.extend(
                    _passed_verification_terminalization_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        record_ids={record_id},
                    )
                )
            elif verdict in {"failed", "fail"}:
                output.extend(
                    _failed_verification_recovery_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        record_ids={record_id},
                    )
                )
    if patch_or_completion:
        output.extend(
            _no_successor_recovery_terminal_failure_events(
                scoped_projection,
                active_lease_node_ids,
                make_event,
                recovery_node_ids=repair_node_ids,
            )
        )
    return _dedupe_repair_events(output)


def _planner_session_state_event(
    projection: GraphProjection,
    node_id: str,
    state: str,
    lease_generation: int,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> EventEnvelope | None:
    if not _is_chain_planner(projection, node_id):
        return None
    session_id = projection["planner_sessions"].get(node_id)
    if not isinstance(session_id, str):
        return None
    payload = PlannerSessionStateChangedPayload.model_validate(
        {
            "session_id": session_id,
            "state": state,
            "node_id": node_id,
            "lease_generation": lease_generation,
            "carryover_record_id": _session_carryover_record_id(projection, node_id),
        }
    )
    return typed_topology_event(
        make_event,
        "session_state_changed",
        payload.model_dump(mode="json", exclude_none=False),
    )


def _failure_record_payload(
    *,
    node_id: str,
    phase: str,
    error_class: str,
    retryable: bool,
    lease_id: str | None = None,
    execution_id: Any = None,
    generation: Any = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "failed_node_id": node_id,
        "phase": phase,
        "error_class": error_class,
        "retryable": retryable,
    }
    if lease_id is not None:
        value["lease_id"] = lease_id
    if isinstance(execution_id, str):
        value["execution_id"] = execution_id
    if isinstance(generation, int) and not isinstance(generation, bool):
        value["lease_generation"] = generation
    if reason is not None:
        value["reason"] = reason
    if metadata:
        value.update(metadata)
    record = FailureRecord.model_validate(
        {
            "record_id": f"failure-{node_id}-{lease_id or error_class}",
            "record_kind": "graph_record",
            "record_type": "failure_record",
            "producer_node_id": node_id,
            "port": "failure_record",
            "schema": "FailureRecord",
            "value": value,
        }
    )
    return record.model_dump(mode="json")


def _recovery_plan_record_payload(
    *,
    node_id: str,
    retry_payload: dict[str, Any],
    retry_backoff_seconds: int,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "action": "retry",
        "responsible_actor": "controller",
        "graph_changes": [
            {
                "op": "set_node_state",
                "node_id": node_id,
                "state": "ready" if retry_backoff_seconds <= 0 else "blocked",
            }
        ],
        "reason": str(retry_payload.get("reason", "runtime_process_died")),
    }
    if retry_backoff_seconds > 0:
        value["retry_after_seconds"] = retry_backoff_seconds
        retry_not_before = retry_payload.get("retry_not_before")
        if isinstance(retry_not_before, str):
            value["retry_not_before"] = retry_not_before
    record = RecoveryPlanRecord.model_validate(
        {
            "record_id": f"recovery-plan-{node_id}-{retry_payload.get('lease_id', 'retry')}",
            "record_kind": "output",
            "record_type": "recovery_plan",
            "producer_node_id": node_id,
            "port": "recovery_plan",
            "schema": "RecoveryPlan",
            "value": value,
        }
    )
    return record.model_dump(mode="json")


def _non_gap_planner_has_accepted_patch(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "planner"
        and projection["node_roles"].get(node_id) != "gap_planner"
        and bool(projection.get("accepted_graph_patches_by_node", {}).get(node_id))
    )


def _is_rate_limit_death(reason: str) -> bool:
    normalized = reason.lower()
    return (
        "rate limit" in normalized
        or "hit rate limit" in normalized
        or "usage limit" in normalized
        or "quota" in normalized
    )


def _is_non_retryable_runtime_death(reason: str) -> bool:
    return reason.startswith("check node missing command_definition") or reason.startswith(
        "check command_definition requires "
    )


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float) and value > 0:
        return int(value)
    return default


def _lifecycle_event(
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    command_type: str,
    from_state: str,
    to_state: str,
    trigger: Any,
) -> EventEnvelope:
    return _make_strict_event(
        make_event,
        RUN_LIFECYCLE_CHANGED,
        {
            "command_type": command_type,
            "from_state": from_state,
            "to_state": to_state,
            "trigger": trigger,
        },
    )


def _command_rejected(
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    command_type: str,
    reason: str,
) -> EventEnvelope:
    return _make_strict_event(
        make_event,
        COMMAND_REJECTED,
        {"command_type": command_type, "reason": reason},
    )


def _callback_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_payload = payload.get("payload")
    if raw_payload is None:
        payload_hash = payload.get("payload_hash")
        return {"payload_hash": payload_hash} if isinstance(payload_hash, str) else None
    return (
        cast(dict[str, Any], raw_payload)
        if isinstance(raw_payload, dict)
        else {"payload": raw_payload}
    )


@dataclass
class LegacyFutureCommandEffects:
    """Injected Task 3/4/6 compatibility capabilities; Task 9 deletes this."""

    accepted_output_record_events: Callable[..., Any] = _accepted_output_record_events
    file_state_authority_conflict: Callable[..., Any] = _file_state_authority_conflict
    file_state_rejected_conflict: Callable[..., Any] = _file_state_rejected_conflict
    file_state_rejected_events: Callable[..., Any] = _file_state_rejected_events
    lease_node_id: Callable[..., Any] = _lease_node_id
    output_record_contract_conflict: Callable[..., Any] = _output_record_contract_conflict
    output_record_provenance_conflict: Callable[..., Any] = _output_record_provenance_conflict
    planner_session_state_event: Callable[..., Any] = _planner_session_state_event
    required_output_record_conflict: Callable[..., Any] = _required_output_record_conflict
    source_repair_events: Callable[..., Any] = _source_repair_events
    typed_lease_event_payload: Callable[..., Any] = _typed_lease_event_payload
    verification_record_conflict: Callable[..., Any] = _verification_record_conflict
    cancel_active_lease_events: Callable[..., Any] = _cancel_active_lease_events
    lifecycle_completion_decision_event: Callable[..., Any] = _lifecycle_completion_decision_event
    failure_record_payload: Callable[..., Any] = _failure_record_payload
    recovery_plan_record_payload: Callable[..., Any] = _recovery_plan_record_payload


command_rejected = _command_rejected
event_factory = _event_factory
run_id = _run_id
