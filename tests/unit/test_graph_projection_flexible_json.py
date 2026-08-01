"""Model-derived, event-backed checkpoint coverage for flexible projection JSON."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from types import UnionType
from typing import Annotated, Literal, TypeAliasType, Union, get_args, get_origin, get_type_hints

import pytest

from orchestrator.graph import (
    EventEnvelope,
    FrozenJsonValue,
    FrozenMap,
    GraphProjection,
    ProjectionModel,
    build_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
)
from tests.unit.graph_projection_behavior_cases import event


EXPECTED_FLEXIBLE_JSON_FIELDS = frozenset(
    {
        ("ApprovalDecisionValue", "scope"),
        ("AuthorityDecisionValue", "scope"),
        ("CallbackEventValue", "payload"),
        ("CommandDefinitionValue", "value"),
        ("EdgeValue", "accepted_record_selector"),
        ("EdgeValue", "binding_policy"),
        ("EdgeValue", "description"),
        ("EdgeValue", "freshness_policy"),
        ("EdgeValue", "metadata"),
        ("EdgeValue", "prompt_hydration_policy"),
        ("EdgeValue", "purpose"),
        ("EdgeValue", "selection"),
        ("OversightDecisionValue", "decider"),
        ("OversightDecisionValue", "scope"),
        ("ProjectedAuthorityDecisionRecordValue", "scope"),
        ("ProjectedCheckResultRecordValue", "command"),
        ("ProjectedCheckResultRecordValue", "command_binding"),
        ("ProjectedCheckResultRecordValue", "environment_policy"),
        ("ProjectedCompletionDecisionValue", "blockers"),
        ("ProjectedDecisionRecordValue", "scope"),
        ("ProjectedFanOutInputsRecord", "value"),
        ("ProjectedGitRef", "diff_summary"),
        ("ProjectedGraphPatchProposalValue", "macro_invocations"),
        ("ProjectedGraphPatchProposalValue", "ops"),
        ("ProjectedRecordBase", "payload"),
        ("ProjectedRecordBase", "provenance"),
        ("ProjectedRecoveryPlanValue", "graph_changes"),
        ("ProjectedRoutineSnapshotValue", "dynamic_feature"),
        ("ProjectedVerificationReportRecord", "evidence"),
    }
)

JSON_PROBES = (
    {"nested": [{"array": [1, True, None]}, "text"]},
    [1, {"nested": [False, None]}],
    "scalar",
    7,
    False,
    None,
)


def _contains_flexible_json(annotation: object, active: set[object]) -> bool:
    if annotation is FrozenJsonValue:
        return True
    if annotation in active:
        return False
    if isinstance(annotation, TypeAliasType):
        return _contains_flexible_json(annotation.__value__, active | {annotation})
    origin = get_origin(annotation)
    if origin is Annotated:
        return _contains_flexible_json(get_args(annotation)[0], active)
    if origin in {Union, UnionType, tuple, FrozenMap}:
        return any(_contains_flexible_json(item, active) for item in get_args(annotation))
    return False


def discover_flexible_json_fields(root: type[ProjectionModel]) -> frozenset[tuple[str, str]]:
    """Walk model annotations without treating nested models as open JSON leaves."""
    found: set[tuple[str, str]] = set()
    seen: set[type[ProjectionModel]] = set()

    active_aliases: set[TypeAliasType] = set()

    def visit(annotation: object, active: frozenset[type[ProjectionModel]]) -> None:
        if annotation is FrozenJsonValue:
            return
        if isinstance(annotation, TypeAliasType):
            if annotation in active_aliases:
                return
            active_aliases.add(annotation)
            try:
                visit(annotation.__value__, active)
            finally:
                active_aliases.remove(annotation)
            return
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is Annotated:
            visit(args[0], active)
        elif origin in (Union, UnionType, tuple):
            for item in args:
                if item is not Ellipsis and item is not type(None):
                    visit(item, active)
        elif origin is FrozenMap:
            if len(args) == 2:
                visit(args[1], active)
        elif isinstance(annotation, type) and issubclass(annotation, ProjectionModel):
            walk(annotation, active)

    def walk(model: type[ProjectionModel], active: frozenset[type[ProjectionModel]]) -> None:
        if model in seen:
            return
        seen.add(model)
        hints = get_type_hints(model, include_extras=True)
        for declaring in reversed(model.__mro__):
            if not isinstance(declaring, type) or not issubclass(declaring, ProjectionModel):
                continue
            for name in getattr(declaring, "__annotations__", {}):
                annotation = hints[name]
                if _contains_flexible_json(annotation, set()):
                    found.add((declaring.__name__, name))
                visit(annotation, active | {model})

    walk(root, frozenset())
    return frozenset(found)


@dataclass(frozen=True)
class FlexibleJsonCase:
    owner: str
    field: str
    events: Callable[[object], tuple[EventEnvelope, ...]]
    projected_value: Callable[[GraphProjection], object]
    checkpoint_value: Callable[[dict[str, object]], object]
    container: Literal["direct", "map-value", "tuple-map-value"]


def _adapt(probe: object, container: Literal["direct", "map-value", "tuple-map-value"]) -> object:
    if container == "direct":
        return probe
    if container == "map-value":
        return {"probe": probe}
    return [{"probe": probe}]


def _node(node_id: str, position: int = 0, **payload: object) -> EventEnvelope:
    return event(
        "node_created",
        {"node_id": node_id, "kind": "worker", "state": "planned", **payload},
        position,
    )


def _required_record(projection: object, record_id: str) -> object:
    return getattr(getattr(projection, "records"), "by_id")[record_id]


def _required_callback(projection: object, idempotency_key: str) -> object:
    return getattr(getattr(projection, "execution"), "callback_events_by_key")[idempotency_key]


def _required_file_state(projection: object, record_id: str) -> object:
    return _required_record(projection, record_id)


def _required_edge(projection: object, edge_id: str) -> object:
    return getattr(getattr(projection, "topology"), "edges")[edge_id]


def _record(
    record_id: str, record_type: str, port: str, schema: str, value: object, **extra: object
) -> tuple[EventEnvelope, ...]:
    node_id = f"node-{record_id}"
    record_kind = (
        "verification"
        if record_type == "verification_report"
        else "graph_record"
        if record_type == "routine_snapshot"
        else "output"
    )
    prerequisites: tuple[EventEnvelope, ...] = ()
    if record_type in {"check_result", "verification_report"}:
        prerequisites = (
            _node("candidate-node", 0, task_region_id="task"),
            event(
                "output_record_accepted",
                {
                    "record_id": "candidate-record",
                    "record_kind": "output",
                    "record_type": "candidate",
                    "producer_node_id": "candidate-node",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "candidate_id": "candidate",
                    "task_region_id": "task",
                    "value": {"summary": "candidate"},
                },
                1,
            ),
        )
        return (
            *prerequisites,
            _node(node_id, 2),
            event(
                "output_record_accepted",
                {
                    "record_id": record_id,
                    "record_kind": record_kind,
                    "record_type": record_type,
                    "producer_node_id": node_id,
                    "port": port,
                    "schema": schema,
                    "value": value,
                    **extra,
                },
                3,
            ),
        )
    return (
        _node(node_id),
        event(
            "output_record_accepted",
            {
                "record_id": record_id,
                "record_kind": record_kind,
                "record_type": record_type,
                "producer_node_id": node_id,
                "port": port,
                "schema": schema,
                "value": value,
                **extra,
            },
            1,
        ),
    )


def _record_case(
    owner: str,
    field: str,
    record_type: str,
    port: str,
    schema: str,
    value_factory: Callable[[object], dict[str, object]],
    *,
    container: Literal["direct", "map-value", "tuple-map-value"] = "direct",
    envelope: bool = False,
    extra: dict[str, object] | None = None,
) -> FlexibleJsonCase:
    record_id = f"record-{owner}-{field}"

    def events(probe: object) -> tuple[EventEnvelope, ...]:
        value = value_factory(_adapt(probe, container))
        payload = (
            {"payload" if field == "payload" else "provenance": _adapt(probe, "map-value")}
            if envelope
            else {}
        )
        return _record(record_id, record_type, port, schema, value, **payload, **(extra or {}))

    def projected(projection: GraphProjection) -> object:
        record = _required_record(projection, record_id)
        if envelope:
            return getattr(record, field)
        value = getattr(record, "value")
        return value if field == "value" else getattr(value, field)

    def checkpoint(checkpoint: dict[str, object]) -> object:
        record = checkpoint["records"]["by_id"][record_id]  # type: ignore[index]
        if envelope:
            return record.get(field)
        if field == "value":
            return record["value"]
        return record["value"].get(field)

    return FlexibleJsonCase(owner, field, events, projected, checkpoint, container)


def _direct_case(
    owner: str,
    field: str,
    event_type: str,
    base: dict[str, object],
    path: tuple[str, ...],
    container: Literal["direct", "map-value", "tuple-map-value"] = "direct",
) -> FlexibleJsonCase:
    def events(probe: object) -> tuple[EventEnvelope, ...]:
        data = {**base, field: _adapt(probe, container)}
        node_id = str(data["node_id"])
        return (_node(node_id), event(event_type, data, 1))

    def projected(projection: GraphProjection) -> object:
        value: object = projection
        for item in path:
            value = getattr(value, item) if not isinstance(value, FrozenMap) else value[item]
        return value

    def checkpoint(checkpoint: dict[str, object]) -> object:
        value: object = checkpoint
        for item in path:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(item)
            else:
                value = value[item]  # type: ignore[index]
        return value

    return FlexibleJsonCase(owner, field, events, projected, checkpoint, container)


def _cases() -> dict[tuple[str, str], FlexibleJsonCase]:
    cases: dict[tuple[str, str], FlexibleJsonCase] = {}
    cases[("CommandDefinitionValue", "value")] = FlexibleJsonCase(
        "CommandDefinitionValue",
        "value",
        lambda probe: (_node("command-node", command_definition=_adapt(probe, "map-value")),),
        lambda p: p.nodes["command-node"].spec.command_definition.value,  # type: ignore[union-attr]
        lambda c: c["nodes"]["command-node"]["spec"]["command_definition"]["value"],  # type: ignore[index]
        "map-value",
    )
    edge_fields = {
        field: "map-value" if field in {"accepted_record_selector", "metadata"} else "direct"
        for field in (
            "accepted_record_selector",
            "purpose",
            "description",
            "selection",
            "binding_policy",
            "freshness_policy",
            "prompt_hydration_policy",
            "metadata",
        )
    }
    for field, container in edge_fields.items():
        cases[("EdgeValue", field)] = FlexibleJsonCase(
            "EdgeValue",
            field,
            lambda probe, f=field, k=container: (
                _node("edge-source"),
                _node("edge-target", 1),
                event(
                    "edge_created",
                    {
                        "edge_id": f"edge-{f}",
                        "from_node_id": "edge-source",
                        "from_port": "out",
                        "to_node_id": "edge-target",
                        "to_port": "in",
                        f: _adapt(probe, k),
                    },
                    2,
                ),
            ),
            lambda p, f=field: getattr(_required_edge(p, f"edge-{f}"), f),
            lambda c, f=field: c["topology"]["edges"][f"edge-{f}"].get(f),
            "direct" if container == "direct" else "map-value",
        )  # type: ignore[index]
    for owner, field, kind, decision in (
        ("ApprovalDecisionValue", "scope", "approval", "approved"),
        ("AuthorityDecisionValue", "scope", "authority", "granted"),
        ("OversightDecisionValue", "decider", "oversight", "accepted"),
        ("OversightDecisionValue", "scope", "oversight", "accepted"),
    ):
        cases[(owner, field)] = _direct_case(
            owner,
            field,
            f"{kind}_decision_recorded",
            {
                "record_id": f"{kind}-{field}",
                "decision_type": kind,
                "node_id": f"{kind}-{field}",
                "decider": "controller",
                "decision": decision,
            },
            ("governance", f"{kind}_decisions_by_id", f"{kind}-{field}", field),
        )
    cases[("CallbackEventValue", "payload")] = FlexibleJsonCase(
        "CallbackEventValue",
        "payload",
        lambda probe: (
            _node("callback"),
            event(
                "callback_accepted",
                {
                    "node_id": "callback",
                    "lease_id": "lease",
                    "lease_generation": 1,
                    "execution_id": "execution",
                    "idempotency_key": "callback",
                    "reason": "accepted",
                    "payload": _adapt(probe, "map-value"),
                },
                1,
            ),
        ),
        lambda p: getattr(_required_callback(p, "callback\x00callback"), "payload"),
        lambda c: c["execution"]["callback_events_by_key"]["callback\x00callback"].get("payload"),
        "map-value",
    )  # type: ignore[index]
    cases[("ProjectedFanOutInputsRecord", "value")] = _record_case(
        "ProjectedFanOutInputsRecord",
        "value",
        "fan_out_inputs",
        "fan_out_inputs",
        "FanOutInputs",
        lambda p: p,
        container="map-value",
    )
    cases[("ProjectedCompletionDecisionValue", "blockers")] = _record_case(
        "ProjectedCompletionDecisionValue",
        "blockers",
        "completion_decision",
        "completion_decision",
        "CompletionDecision",
        lambda p: {"status": "blocked", "blockers": p},
        container="tuple-map-value",
    )
    cases[("ProjectedDecisionRecordValue", "scope")] = _record_case(
        "ProjectedDecisionRecordValue",
        "scope",
        "decision_record",
        "decision_record",
        "DecisionRecord",
        lambda p: {
            "decision": "approved",
            "decision_type": "approval",
            "decider": "controller",
            "scope": p,
        },
        container="map-value",
    )
    cases[("ProjectedAuthorityDecisionRecordValue", "scope")] = _record_case(
        "ProjectedAuthorityDecisionRecordValue",
        "scope",
        "authority_decision",
        "authority_decision",
        "AuthorityDecision",
        lambda p: {
            "decision": "granted",
            "decision_type": "authority",
            "decider": "controller",
            "scope": p,
        },
        container="map-value",
    )
    cases[("ProjectedGraphPatchProposalValue", "ops")] = _record_case(
        "ProjectedGraphPatchProposalValue",
        "ops",
        "graph_patch_proposal",
        "graph_patch_proposal",
        "GraphPatch",
        lambda p: {
            "patch_id": "patch-ops",
            "proposed_by_node_id": "node-record-ProjectedGraphPatchProposalValue-ops",
            "base_graph_position": 0,
            "ops": p,
        },
        container="tuple-map-value",
    )
    cases[("ProjectedGraphPatchProposalValue", "macro_invocations")] = _record_case(
        "ProjectedGraphPatchProposalValue",
        "macro_invocations",
        "graph_patch_proposal",
        "graph_patch_proposal",
        "GraphPatch",
        lambda p: {
            "patch_id": "patch-macros",
            "proposed_by_node_id": "node-record-ProjectedGraphPatchProposalValue-macro_invocations",
            "base_graph_position": 0,
            "macro_invocations": p,
        },
        container="tuple-map-value",
    )
    cases[("ProjectedRecoveryPlanValue", "graph_changes")] = _record_case(
        "ProjectedRecoveryPlanValue",
        "graph_changes",
        "recovery_plan",
        "recovery_plan",
        "RecoveryPlan",
        lambda p: {"action": "retry", "responsible_actor": "controller", "graph_changes": p},
        container="tuple-map-value",
    )
    cases[("ProjectedRoutineSnapshotValue", "dynamic_feature")] = _record_case(
        "ProjectedRoutineSnapshotValue",
        "dynamic_feature",
        "routine_snapshot",
        "routine_snapshot",
        "RoutineSnapshot",
        lambda p: {
            "routine_id": "routine",
            "name": "routine",
            "content_hash": "hash",
            "step_count": 0,
            "task_count": 0,
            "dynamic_feature": p,
        },
        container="map-value",
    )
    cases[("ProjectedVerificationReportRecord", "evidence")] = _record_case(
        "ProjectedVerificationReportRecord",
        "evidence",
        "verification_report",
        "verification_report",
        "VerificationReport",
        lambda p: {"outcome": "passed", "grades": []},
        extra={"candidate_id": "candidate", "outcome": "passed", "evidence": None},
    )
    # evidence is an envelope field and needs its own event-backed producer.
    evidence = cases[("ProjectedVerificationReportRecord", "evidence")]
    cases[("ProjectedVerificationReportRecord", "evidence")] = FlexibleJsonCase(
        evidence.owner,
        evidence.field,
        lambda probe: _record(
            "record-ProjectedVerificationReportRecord-evidence",
            "verification_report",
            "verification_report",
            "VerificationReport",
            {"outcome": "passed", "grades": []},
            candidate_id="candidate",
            outcome="passed",
            evidence=probe,
        ),
        lambda p: getattr(
            _required_record(p, "record-ProjectedVerificationReportRecord-evidence"), "evidence"
        ),
        lambda c: c["records"]["by_id"]["record-ProjectedVerificationReportRecord-evidence"].get(
            "evidence"
        ),
        "direct",
    )  # type: ignore[index]
    for field in ("payload", "provenance"):
        cases[("ProjectedRecordBase", field)] = _record_case(
            "ProjectedRecordBase",
            field,
            "fan_out_inputs",
            "fan_out_inputs",
            "FanOutInputs",
            lambda p: {"base": "value"},
            envelope=True,
            container="map-value",
        )
    check_base = {
        "status": "passed",
        "classification": "passed",
        "command_id": "command",
        "command_text": "run",
        "worktree_path": "/tmp",
        "base_snapshot_id": "base",
        "execution_id": "execution",
        "duration_ms": 0,
        "stdout_tail": "",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timeout_seconds": 1.0,
    }
    for field, container in (
        ("command_binding", "direct"),
        ("command", "map-value"),
        ("environment_policy", "map-value"),
    ):
        cases[("ProjectedCheckResultRecordValue", field)] = _record_case(
            "ProjectedCheckResultRecordValue",
            field,
            "check_result",
            "check_result",
            "CheckResult",
            lambda p, f=field: {
                **check_base,
                "command": {"base": "command"},
                "environment_policy": {"base": "environment"},
                f: p,
            },
            container=container,
            extra={"candidate_id": "candidate", "task_region_id": "task", "attempt_number": 0},
        )
    cases[("ProjectedGitRef", "diff_summary")] = FlexibleJsonCase(
        "ProjectedGitRef",
        "diff_summary",
        lambda probe: (
            _node("file-node"),
            event(
                "file_state_accepted",
                {
                    "record_id": "file-state",
                    "record_kind": "file_state",
                    "record_type": "file_state",
                    "producer_node_id": "file-node",
                    "port": "file_state",
                    "schema": "FileStateRecord",
                    "snapshot_id": "snapshot",
                    "git": {"diff_summary": _adapt(probe, "map-value")},
                },
                1,
            ),
        ),
        lambda p: getattr(getattr(_required_file_state(p, "file-state"), "git"), "diff_summary"),
        lambda c: c["records"]["by_id"]["file-state"]["git"]["diff_summary"],
        "map-value",
    )  # type: ignore[index]
    return cases


FLEXIBLE_JSON_CASES = _cases()


def _assert_plain_json(value: object) -> None:
    assert type(value) in {dict, list, str, int, float, bool, type(None)}
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for child in value.values():
            _assert_plain_json(child)
    elif type(value) is list:
        for child in value:
            _assert_plain_json(child)


def _assert_deeply_immutable(value: object) -> None:
    if type(value) is FrozenMap:
        for child in value.values():
            _assert_deeply_immutable(child)
    elif type(value) is tuple:
        for child in value:
            _assert_deeply_immutable(child)
    else:
        assert type(value) in {str, int, float, bool, type(None)}


def test_flexible_json_cases_exactly_match_reachable_model_fields() -> None:
    assert discover_flexible_json_fields(GraphProjection) == EXPECTED_FLEXIBLE_JSON_FIELDS
    assert frozenset(FLEXIBLE_JSON_CASES) == EXPECTED_FLEXIBLE_JSON_FIELDS


@pytest.mark.parametrize(
    "probe", JSON_PROBES, ids=("object", "array", "str", "int", "bool", "null")
)
@pytest.mark.parametrize(
    "case", FLEXIBLE_JSON_CASES.values(), ids=lambda case: f"{case.owner}.{case.field}"
)
def test_every_flexible_json_field_round_trips_through_plain_checkpoint_json(
    case: FlexibleJsonCase, probe: object
) -> None:
    projection = build_projection(list(case.events(probe)))
    checkpoint = projection_to_checkpoint(projection)
    _assert_plain_json(case.checkpoint_value(checkpoint))
    restored = projection_from_checkpoint(deepcopy(checkpoint))
    assert restored == projection
    assert case.projected_value(restored) == case.projected_value(projection)
    _assert_deeply_immutable(case.projected_value(restored))
