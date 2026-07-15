"""Typed recovery and topology repair derived from a hydrated graph projection."""

from __future__ import annotations

from typing import Any, cast

from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.commands.event_creator import TypedEventCreator
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    binding_policy_for_edge,
    input_port_contract,
    merge_bound_record_ids,
)
from orchestrator.graph.events.lifecycle import RUN_LIFECYCLE_CHANGED, RunLifecycleChangedPayload
from orchestrator.graph.events.topology import (
    EDGE_CREATED,
    INPUT_BOUND,
    NODE_CREATED,
    NODE_RETIRED,
    NODE_STATE_CHANGED,
    EdgeCreatedPayload,
    InputBoundPayload,
    NodeCreatedPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
)
from orchestrator.graph.models import (
    PortModel,
    VerificationResultProjection,
    record_selector_matches,
)
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.specifications import HydratedEvent


TERMINAL_RUN_STATES = frozenset({"cancelled", "completed", "failed"})


def active_lease_node_ids(projection: GraphProjection) -> list[str]:
    return [
        str(lease["node_id"])
        for lease in projection["leases"].values()
        if lease.get("state") == "active" and isinstance(lease.get("node_id"), str)
    ]


def project_with_events(
    projection: GraphProjection, source_events: list[HydratedEvent], catalog: GraphCatalog
) -> GraphProjection:
    output = projection
    for event in source_events:
        if event.metadata.payload_schema_generation != 2:
            raise ValueError("source repair accepts only catalog-created generation 2 events")
        output = catalog.resolve_event(event.metadata.event_type).reduce(output, event)
    return output


def dedupe_repair_events(events: list[HydratedEvent]) -> list[HydratedEvent]:
    seen: list[tuple[str, object]] = []
    return [
        event
        for event in events
        if not ((key := (event.event_type, event.payload)) in seen or seen.append(key))
    ]


def failed_check_recovery_events(
    projection: GraphProjection,
    active_leases: list[str],
    creator: TypedEventCreator,
    *,
    record_ids: set[str] | None = None,
) -> list[HydratedEvent]:
    if not _repairable(projection, active_leases, require_no_planned=True):
        return []
    snapshot = _latest_routine_snapshot_record(projection)
    if snapshot is None:
        return []
    output: list[HydratedEvent] = []
    for failed in _current_failed_check_results(projection):
        if record_ids is not None and failed["record_id"] not in record_ids:
            continue
        if _recovery_exists(
            projection,
            failed,
            "failure_record" if failed.get("record_type") == "failure_record" else "check_result",
        ):
            continue
        output.extend(
            _create_recovery(
                projection, failed, snapshot, creator, failed.get("record_type") == "failure_record"
            )
        )
    return output


def failed_verification_recovery_events(
    projection: GraphProjection,
    active_leases: list[str],
    creator: TypedEventCreator,
    *,
    record_ids: set[str] | None = None,
) -> list[HydratedEvent]:
    if not _repairable(projection, active_leases):
        return []
    snapshot = _latest_routine_snapshot_record(projection)
    if snapshot is None:
        return []
    output: list[HydratedEvent] = []
    for failed in _current_failed_verification_results(projection):
        if record_ids is not None and failed["record_id"] not in record_ids:
            continue
        if _recovery_exists(projection, failed, "verification_report"):
            continue
        output.extend(
            _create_recovery(projection, failed, snapshot, creator, False, verification=True)
        )
    return output


def _repairable(
    projection: GraphProjection, active_leases: list[str], *, require_no_planned: bool = False
) -> bool:
    if projection["run_state"] != "active" or active_leases or projection["ready_nodes"]:
        return False
    if require_no_planned and any(
        state in {"planned", "blocked", "ready"} for state in projection["node_states"].values()
    ):
        return False
    return any(state != "accepted" for state in projection["task_states"].values())


def _create_recovery(
    projection: GraphProjection,
    failed: dict[str, str],
    snapshot: dict[str, str],
    creator: TypedEventCreator,
    is_failure_record: bool,
    *,
    verification: bool = False,
) -> list[HydratedEvent]:
    record_id, source_node = failed["record_id"], failed["node_id"]
    recovery_id = f"planner-recover-{_stable_id(record_id)}"
    if recovery_id in projection["node_states"]:
        return []
    region = f"recovery-{_stable_id(failed.get('task_region_id', source_node))}"
    reason = "failed_verification" if verification else "failed_required_check"
    output = [
        creator.create(
            NODE_CREATED,
            NodeCreatedPayload(
                node_id=recovery_id,
                kind="planner",
                role="gap_planner",
                state="planned",
                task_region_id=region,
                recovery_reason=reason,
                recovery_of_node_id=source_node,
                recovery_of_record_id=record_id,
            ),
        )
    ]
    source_port = (
        "verification_report"
        if verification
        else ("failure_record" if is_failure_record else "check_result")
    )
    selector: dict[str, Any] = (
        {"record_type": "verification_report", "schema": "VerificationReport", "outcome": "failed"}
        if verification
        else {
            "record_type": "failure_record" if is_failure_record else "check_result",
            "schema": "FailureRecord" if is_failure_record else "CheckResult",
        }
    )
    if not verification and not is_failure_record:
        selector["status"] = "failed"
    edges = [
        EdgeCreatedPayload(
            edge_id=f"edge-{_stable_id(record_id)}-recovery-evidence",
            from_node_id=source_node,
            from_port=source_port,
            to_node_id=recovery_id,
            to_port="verification_evidence",
            accepted_record_selector=selector,
            metadata={"purpose": reason, "recovery_of_record_id": record_id},
        ),
        EdgeCreatedPayload(
            edge_id=f"edge-routine-snapshot-{recovery_id}",
            from_node_id=snapshot["producer_node_id"],
            from_port=snapshot["port"],
            to_node_id=recovery_id,
            to_port="routine_snapshot",
            accepted_record_selector={
                "record_type": "routine_snapshot",
                "schema": "RoutineSnapshot",
            },
            metadata={"purpose": f"{reason}_context"},
        ),
    ]
    for edge in edges:
        if not _would_cycle(projection, edge.from_node_id, edge.to_node_id):
            output.append(creator.create(EDGE_CREATED, edge))
            output.extend(input_bound_events_for_edge(projection, edge, creator))
    return output


def passed_verification_terminalization_events(
    projection: GraphProjection,
    active_leases: list[str],
    creator: TypedEventCreator,
    *,
    record_ids: set[str] | None = None,
) -> list[HydratedEvent]:
    if not _repairable(projection, active_leases):
        return []
    output: list[HydratedEvent] = []
    passed = _current_passed_verifications(projection)
    for verification in passed:
        if record_ids is not None and verification["record_id"] not in record_ids:
            continue
        roots = _failure_branch_roots(
            projection, verification["node_id"], "verification_report", "failed"
        )
        if verification == passed[-1]:
            output.extend(_final_check_edges(projection, verification, creator, bool(roots)))
        output.extend(_retire_nodes(projection, _retirable_downstream(projection, roots), creator))
    return output


def passed_check_terminalization_events(
    projection: GraphProjection,
    active_leases: list[str],
    creator: TypedEventCreator,
    *,
    check_node_ids: set[str] | None = None,
) -> list[HydratedEvent]:
    if not _repairable(projection, active_leases):
        return []
    output: list[HydratedEvent] = []
    for node_id, result in projection["check_results"].items():
        if check_node_ids is not None and node_id not in check_node_ids:
            continue
        if result.status in {"passed", "pass", "ok"}:
            roots = [
                str(edge["to_node_id"])
                for edge in projection["edges"].values()
                if edge.get("from_node_id") == node_id
                and edge.get("from_port") == "check_result"
                and isinstance(edge.get("to_node_id"), str)
                and (
                    edge.get("required") is False
                    or _is_gap_planner(projection, str(edge["to_node_id"]))
                )
            ]
            output.extend(
                _retire_nodes(projection, _retirable_downstream(projection, roots), creator)
            )
    return output


def no_successor_recovery_terminal_failure_events(
    projection: GraphProjection,
    active_leases: list[str],
    creator: TypedEventCreator,
    *,
    recovery_node_ids: set[str] | None = None,
) -> list[HydratedEvent]:
    if not _repairable(projection, active_leases) or any(
        state in {"planned", "blocked", "ready", "leased", "running", "suspended"}
        for state in projection["node_states"].values()
    ):
        return []
    for failed in [
        *_current_failed_check_results(projection),
        *_current_failed_verification_results(projection),
    ]:
        for recovery in projection["recovery_nodes_by_record_id"].get(failed["record_id"], []):
            node_id = recovery.node_id
            if recovery_node_ids is not None and node_id not in recovery_node_ids:
                continue
            patches = projection["accepted_no_successor_patches_by_node"].get(node_id, [])
            if (
                projection["node_states"].get(node_id) != "completed"
                or not patches
                or _recovery_succeeded(projection, node_id)
            ):
                continue
            if failed.get("classification") in {
                "environment_error",
                "tool_error",
                "tool_unavailable",
            }:
                continue
            return [
                creator.create(
                    RUN_LIFECYCLE_CHANGED,
                    RunLifecycleChangedPayload(
                        command_type="schedule_tick",
                        from_state="active",
                        to_state="failed",
                        trigger="recovery_planner_no_successor",
                        node_id=node_id,
                        patch_id=patches[-1],
                        recovery_of_record_id=failed["record_id"],
                        recovery_reason=recovery.recovery_reason,
                    ),
                )
            ]
    return []


def _retire_nodes(
    projection: GraphProjection, node_ids: list[str], creator: TypedEventCreator
) -> list[HydratedEvent]:
    output: list[HydratedEvent] = []
    for node_id in node_ids:
        output.extend(
            [
                creator.create(
                    NODE_RETIRED,
                    NodeRetiredPayload(
                        node_id=node_id, reason="unreachable_after_passed_terminal_evidence"
                    ),
                ),
                creator.create(
                    NODE_STATE_CHANGED,
                    NodeStateChangedPayload(
                        node_id=node_id,
                        new_state="retired",
                        trigger="passed_terminal_evidence_recovery",
                    ),
                ),
            ]
        )
    return output


def _final_check_edges(
    projection: GraphProjection,
    verification: dict[str, str],
    creator: TypedEventCreator,
    allow_create: bool,
) -> list[HydratedEvent]:
    checks = [
        node
        for node, kind in projection["node_kinds"].items()
        if kind == "check"
        and projection["node_roles"].get(node) == "invariant_gate"
        and projection["node_states"].get(node) in {"planned", "blocked", "ready"}
        and "verification_evidence" not in projection["input_bindings"].get(node, {})
    ]
    output: list[HydratedEvent] = []
    if (
        allow_create
        and not checks
        and not any(
            kind == "check" and projection["node_roles"].get(node) == "invariant_gate"
            for node, kind in projection["node_kinds"].items()
        )
    ):
        check = f"check-final-invariant-{_stable_id(verification['record_id'])}"
        output.append(
            creator.create(
                NODE_CREATED,
                NodeCreatedPayload(
                    node_id=check,
                    kind="check",
                    role="invariant_gate",
                    state="planned",
                    task_region_id="final-invariant-region",
                    command_binding="dynamic_feature_hidden_oracle",
                    inputs=[
                        PortModel(
                            port="verification_evidence",
                            direction="input",
                            schema="VerificationReport",
                            required=True,
                        )
                    ],
                    outputs=[
                        PortModel(port="check_result", direction="output", schema="CheckResult")
                    ],
                ),
            )
        )
        checks = [check]
    for check in checks:
        if _would_cycle(projection, verification["node_id"], check):
            continue
        edge = EdgeCreatedPayload(
            edge_id=f"edge-{_stable_id(verification['record_id'])}-passed-verification-final-{_stable_id(check)}",
            from_node_id=verification["node_id"],
            from_port="verification_report",
            to_node_id=check,
            to_port="verification_evidence",
            accepted_record_selector={
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "outcome": "passed",
            },
            metadata={
                "purpose": "passed_verification_final_invariant_recovery",
                "recovery_of_record_id": verification["record_id"],
            },
        )
        output.append(creator.create(EDGE_CREATED, edge))
        output.extend(input_bound_events_for_edge(projection, edge, creator))
    return output


def input_bound_events_for_edge(
    projection: GraphProjection, edge: EdgeCreatedPayload, creator: TypedEventCreator
) -> list[HydratedEvent]:
    if edge.dependency_type not in {None, "input_binding"}:
        return []
    output: list[HydratedEvent] = []
    producers = (
        [edge.from_node_id]
        if edge.from_node_id != "*"
        else [
            node
            for node in sorted(projection["node_kinds"])
            if (
                edge.from_node_kind is None
                or projection["node_kinds"].get(node) == edge.from_node_kind
            )
            and (
                edge.from_node_role is None
                or projection["node_roles"].get(node) == edge.from_node_role
            )
        ]
    )
    for producer in producers:
        for record in (
            projection["output_records_by_node_port"].get(producer, {}).get(edge.from_port, [])
        ):
            raw = record.model_dump(mode="json")
            record_id = raw.get("record_id")
            if not isinstance(record_id, str) or not record_selector_matches(
                edge.accepted_record_selector, raw, _record_aliases(raw)
            ):
                continue
            payload = _input_bound_payload(projection, edge, record_id, raw)
            if payload is not None:
                output.append(creator.create(INPUT_BOUND, payload))
    return output


def _input_bound_payload(
    projection: GraphProjection, edge: EdgeCreatedPayload, record_id: str, record: dict[str, Any]
) -> InputBoundPayload | None:
    existing = (
        projection["input_bindings"]
        .get(edge.to_node_id, {})
        .get(edge.to_port, {})
        .get("record_ids", [])
    )
    raw_existing = cast(list[object], existing) if isinstance(existing, list) else []
    current = [value for value in raw_existing if isinstance(value, str)]
    contract = DEFAULT_NODE_CONTRACTS.contract_for(
        projection["node_kinds"].get(edge.to_node_id, ""),
        projection["node_roles"].get(edge.to_node_id),
    )
    policy = binding_policy_for_edge(
        edge.model_dump(mode="python"),
        input_port_contract(contract, edge.to_port) if contract else None,
    )
    next_ids = merge_bound_record_ids(
        policy,
        current,
        [record_id],
        supersedes_record_id=cast(str | None, record.get("supersedes_record_id")),
    )
    if next_ids == current and current:
        return None
    return InputBoundPayload(
        edge_id=edge.edge_id,
        to_node_id=edge.to_node_id,
        to_port=edge.to_port,
        record_ids=next_ids,
        bound_at_position=0,
        binding_policy=policy
        if policy != "bind_first" or edge.binding_policy is not None
        else None,
        supersedes_record_id=cast(str | None, record.get("supersedes_record_id")),
        trigger="edge_backfill",
    )


def _current_failed_check_results(projection: GraphProjection) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for node, result in projection["check_results"].items():
        if result.status in {"passed", "pass", "ok"} or not result.record_id:
            continue
        item = {"node_id": node, "record_id": result.record_id}
        for key in ("classification", "task_region_id"):
            value = getattr(result, key)
            if isinstance(value, str) and value:
                item[key] = value
        output.append(item)
    for node, ports in projection["accepted_output_records_by_node_port"].items():
        if projection["node_kinds"].get(node) != "check" or node in projection["check_results"]:
            continue
        for record in ports.get("failure_record", []):
            if record.get("record_id") and record.get("payload"):
                output.append(
                    {
                        "node_id": node,
                        "record_id": str(record["record_id"]),
                        "record_type": "failure_record",
                        "task_region_id": projection["node_task_regions"].get(node, node),
                    }
                )
    return output


def _verification_dict(value: VerificationResultProjection) -> dict[str, str] | None:
    raw = value.model_dump(mode="json")
    return (
        {key: item for key, item in raw.items() if isinstance(item, str)}
        if isinstance(raw.get("node_id"), str) and isinstance(raw.get("record_id"), str)
        else None
    )


def _current_failed_verification_results(projection: GraphProjection) -> list[dict[str, str]]:
    return [
        item
        for value in projection["failed_verification_results_by_record_id"].values()
        if (item := _verification_dict(value)) is not None
        and item.get("candidate_id") not in projection["passed_verification_candidate_ids"]
        and not _superseded(projection, item)
    ]


def _current_passed_verifications(projection: GraphProjection) -> list[dict[str, str]]:
    return [
        item
        for value in projection["passed_verification_results_by_record_id"].values()
        if (item := _verification_dict(value)) is not None
        and item.get("candidate_id") not in projection["failed_verification_candidate_ids"]
    ]


def _superseded(projection: GraphProjection, failed: dict[str, str]) -> bool:
    region = failed.get("task_region_id") or projection["node_task_regions"].get(failed["node_id"])
    verdict = projection["verifier_verdicts"].get(failed.get("candidate_id", ""))
    if region is None or verdict is None:
        return False
    return any(
        (passed.task_region_id or projection["node_task_regions"].get(passed.node_id)) == region
        and (later := projection["verifier_verdicts"].get(passed.candidate_id or "")) is not None
        and later.verdict == "passed"
        and later.position > verdict.position
        for passed in projection["passed_verification_results_by_record_id"].values()
    )


def _latest_routine_snapshot_record(projection: GraphProjection) -> dict[str, str] | None:
    record = projection.get("latest_routine_snapshot_record")
    if record is not None:
        return {
            "record_id": record.record_id,
            "producer_node_id": record.producer_node_id,
            "port": record.port,
        }
    for summary in reversed(list(projection["accepted_record_summaries_by_id"].values())):
        if summary.record_type == "routine_snapshot" or summary.schema_ == "RoutineSnapshot":
            if summary.producer_node_id and summary.producer_port:
                return {
                    "record_id": summary.record_id,
                    "producer_node_id": summary.producer_node_id,
                    "port": summary.producer_port,
                }
    return None


def _recovery_exists(projection: GraphProjection, failed: dict[str, str], port: str) -> bool:
    return any(
        edge.get("from_node_id") == failed["node_id"]
        and edge.get("from_port") == port
        and edge.get("to_port") == "verification_evidence"
        and isinstance((target := edge.get("to_node_id")), str)
        and projection["node_kinds"].get(target) == "planner"
        and projection["node_roles"].get(target) == "gap_planner"
        and projection["node_states"].get(target) not in {"cancelled", "failed", "retired"}
        for edge in projection["edges"].values()
    )


def _failure_branch_roots(
    projection: GraphProjection, node: str, port: str, outcome: str
) -> list[str]:
    return [
        str(edge["to_node_id"])
        for edge in projection["edges"].values()
        if edge.get("from_node_id") == node
        and edge.get("from_port") == port
        and edge.get("to_port") == "verification_evidence"
        and _selector_outcome(edge) == outcome
        and isinstance(edge.get("to_node_id"), str)
    ]


def _selector_outcome(edge: dict[str, Any]) -> str | None:
    selector = edge.get("accepted_record_selector")
    if not isinstance(selector, dict):
        return None
    value = cast(dict[str, Any], selector).get("outcome")
    return value if isinstance(value, str) else None


def _retirable_downstream(projection: GraphProjection, roots: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if projection["node_states"].get(node) in {
            None,
            "completed",
            "failed",
            "cancelled",
            "retired",
        } or (
            projection["node_kinds"].get(node) == "check"
            and projection["node_roles"].get(node) == "invariant_gate"
        ):
            continue
        output.append(node)
        stack.extend(
            str(edge["to_node_id"])
            for edge in projection["edges"].values()
            if edge.get("from_node_id") == node
            and edge.get("dependency_type") != "state_dependency"
            and isinstance(edge.get("to_node_id"), str)
        )
    return output


def _recovery_succeeded(projection: GraphProjection, node: str) -> bool:
    downstream = set(_retirable_downstream(projection, [node]))
    return (
        any(
            result.node_id in downstream
            for result in projection["passed_verification_results_by_record_id"].values()
        )
        or any(
            check in downstream and result.status in {"passed", "pass", "ok"}
            for check, result in projection["check_results"].items()
        )
        or any(
            edge.get("from_node_id") == node
            and projection["node_kinds"].get(cast(str, edge.get("to_node_id")))
            not in {None, "planner"}
            for edge in projection["edges"].values()
        )
    )


def _would_cycle(projection: GraphProjection, source: str, target: str) -> bool:
    seen: set[str] = set()
    stack = [target]
    while stack:
        node = stack.pop()
        if node == source:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(
            str(edge["to_node_id"])
            for edge in projection["edges"].values()
            if edge.get("from_node_id") == node and isinstance(edge.get("to_node_id"), str)
        )
    return False


def _is_gap_planner(projection: GraphProjection, node: str) -> bool:
    return (
        projection["node_kinds"].get(node) == "gap_planner"
        or projection["node_roles"].get(node) == "gap_planner"
    )


def _record_aliases(record: dict[str, Any]) -> set[str]:
    return (
        {"verification_result"}
        if record.get("record_kind") == "verification"
        else (
            {"accepted_file_state", "file_state"}
            if record.get("record_kind") == "file_state"
            else set()
        )
    )


def _stable_id(value: str) -> str:
    return (
        "".join(
            char.lower() if char.isalnum() or char in {"-", "_", "."} else "-"
            for char in value.strip()
        ).strip("-")
        or "unknown"
    )


__all__ = [
    "TERMINAL_RUN_STATES",
    "active_lease_node_ids",
    "dedupe_repair_events",
    "failed_check_recovery_events",
    "failed_verification_recovery_events",
    "input_bound_events_for_edge",
    "no_successor_recovery_terminal_failure_events",
    "passed_check_terminalization_events",
    "passed_verification_terminalization_events",
    "project_with_events",
]
