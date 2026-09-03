"""Model-derived, event-backed checkpoint coverage for flexible projection JSON."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from types import UnionType
from typing import (
    Any,
    Annotated,
    Literal,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

import pytest

from orchestrator.graph import (
    EventEnvelope,
    FrozenJsonValue,
    FrozenMap,
    GraphProjection,
    ProjectionModel,
    StrictNestedModel,
    TypedRecordBase,
    build_projection,
    boundary_manifest_hash,
    projection_from_checkpoint,
    projection_to_checkpoint,
    thaw_json,
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
        ("ExecutionAttemptValue", "payload"),
        ("ExecutionAttemptValue", "validation_witness"),
        ("NodeSpecProjection", "dispatch_payload"),
        ("OversightDecisionValue", "decider"),
        ("OversightDecisionValue", "scope"),
        ("AuthorityDecisionValue", "scope"),
        ("CheckResultValue", "command"),
        ("CheckResultValue", "command_binding"),
        ("CheckResultValue", "environment_policy"),
        ("CompletionDecisionValue", "blockers"),
        ("DecisionRecordValue", "scope"),
        ("OutputRecord", "value"),
        ("GitRef", "diff_summary"),
        ("GraphPatchProposalValue", "macro_invocations"),
        ("GraphPatchProposalValue", "ops"),
        ("TypedRecordBase", "payload"),
        ("TypedRecordBase", "provenance"),
        ("RecoveryPlanValue", "graph_changes"),
        ("RoutineSnapshotValue", "dynamic_feature"),
        ("SemanticArtifactValidation", "validated_json"),
        ("SemanticArtifactValue", "content"),
        ("SemanticArtifactValue", "provenance"),
        ("SemanticSchemaDeclarationValue", "json_schema"),
        ("VerificationReportRecord", "evidence"),
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
    if annotation in {Any, FrozenJsonValue}:
        return True
    if annotation in active:
        return False
    if isinstance(annotation, TypeAliasType):
        return _contains_flexible_json(annotation.__value__, active | {annotation})
    origin = get_origin(annotation)
    if origin is Annotated:
        return _contains_flexible_json(get_args(annotation)[0], active)
    if origin in {Union, UnionType, tuple, list, dict, FrozenMap}:
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
        elif isinstance(annotation, type) and (
            issubclass(annotation, ProjectionModel)
            or issubclass(annotation, TypedRecordBase)
            or issubclass(annotation, StrictNestedModel)
        ):
            walk(annotation, active)

    def walk(
        model: type[ProjectionModel] | type[TypedRecordBase], active: frozenset[object]
    ) -> None:
        if model in seen:
            return
        seen.add(model)
        hints = get_type_hints(model, include_extras=True)
        for declaring in reversed(model.__mro__):
            if not isinstance(declaring, type) or not (
                issubclass(declaring, ProjectionModel)
                or issubclass(declaring, TypedRecordBase)
                or issubclass(declaring, StrictNestedModel)
            ):
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
    checkpoint_present: Callable[[dict[str, object]], bool] | None = None
    omits_none: bool = False

    def expected_value(self, probe: object) -> object:
        """Return the ordinary JSON value deliberately installed by this case."""
        return _adapt(probe, self.container)


def _adapt(probe: object, container: Literal["direct", "map-value", "tuple-map-value"]) -> object:
    if container == "direct":
        return probe
    if container == "map-value":
        return {"probe": probe}
    return [{"probe": probe}]


def _checkpoint_path_present(checkpoint: dict[str, object], path: tuple[str, ...]) -> bool:
    value: object = checkpoint.get("state")
    for item in path:
        if not isinstance(value, dict) or item not in value:
            return False
        value = value[item]
    return True


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
        if record_type in {"routine_snapshot", "semantic_schema_declaration", "semantic_artifact"}
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
        record = checkpoint["state"]["records"]["by_id"][record_id]
        if envelope:
            return record.get(field)
        if field == "value":
            return record["value"]
        return record["value"].get(field)

    def checkpoint_present(checkpoint: dict[str, object]) -> bool:
        record = checkpoint["state"]["records"]["by_id"][record_id]
        if envelope:
            return field in record
        return "value" in record if field == "value" else field in record["value"]

    return FlexibleJsonCase(
        owner,
        field,
        events,
        projected,
        checkpoint,
        container,
        checkpoint_present,
        omits_none=container == "direct",
    )


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
        value: object = checkpoint["state"]
        for item in path:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(item)
            else:
                value = value[item]  # type: ignore[index]
        return value

    return FlexibleJsonCase(
        owner,
        field,
        events,
        projected,
        checkpoint,
        container,
        lambda checkpoint: _checkpoint_path_present(checkpoint, path),
        omits_none=True,
    )


def _cases() -> dict[tuple[str, str], FlexibleJsonCase]:
    cases: dict[tuple[str, str], FlexibleJsonCase] = {}
    cases[("NodeSpecProjection", "dispatch_payload")] = FlexibleJsonCase(
        "NodeSpecProjection",
        "dispatch_payload",
        lambda probe: (_node("dispatch-node", membership=_adapt(probe, "map-value")),),
        lambda p: p.nodes["dispatch-node"].spec.dispatch_payload["membership"],
        lambda c: c["state"]["nodes"]["dispatch-node"]["spec"]["dispatch_payload"]["membership"],
        "map-value",
    )
    cases[("CommandDefinitionValue", "value")] = FlexibleJsonCase(
        "CommandDefinitionValue",
        "value",
        lambda probe: (_node("command-node", command_definition=_adapt(probe, "map-value")),),
        lambda p: p.nodes["command-node"].spec.command_definition.value,  # type: ignore[union-attr]
        lambda c: c["state"]["nodes"]["command-node"]["spec"]["command_definition"]["value"],
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
            lambda c, f=field: c["state"]["topology"]["edges"][f"edge-{f}"].get(f),
            "direct" if container == "direct" else "map-value",
            (
                lambda c, f=field, k=container: f in c["state"]["topology"]["edges"][f"edge-{f}"]
                if k == "direct"
                else None
            ),
            container == "direct",
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
        lambda c: c["state"]["execution"]["callback_events_by_key"]["callback\x00callback"].get(
            "payload"
        ),
        "map-value",
    )  # type: ignore[index]
    cases[("ExecutionAttemptValue", "payload")] = FlexibleJsonCase(
        "ExecutionAttemptValue",
        "payload",
        lambda probe: (
            _node("node"),
            event(
                "lease_granted",
                {
                    "lease_id": "lease",
                    "node_id": "node",
                    "generation": 1,
                    "execution_id": "execution",
                    "base_snapshot_id": "snapshot",
                },
                1,
            ),
            event(
                "runner_baseline_recorded",
                {
                    "execution_id": "execution",
                    "node_id": "node",
                    "lease_id": "lease",
                    "lease_generation": 1,
                    "baseline_snapshot_id": "snapshot",
                    "baseline_tree_sha": "a" * 40,
                    "entries": [],
                    "boundary_hash": boundary_manifest_hash("a" * 40, []),
                    "cache_roots": [],
                },
                2,
            ),
            event(
                "runner_submission_staged",
                {
                    "execution_id": "execution",
                    "node_id": "node",
                    "lease_id": "lease",
                    "lease_generation": 1,
                    "idempotency_key": "key",
                    "payload": _adapt(probe, "map-value"),
                    "payload_hash": "sha256:1",
                    "staged_snapshot_id": "staged",
                    "staged_snapshot_ref": "refs/orchestrator/snapshots/staged",
                    "staged_commit_sha": "b" * 40,
                    "staged_tree_sha": "a" * 40,
                    "boundary_hash": boundary_manifest_hash("a" * 40, []),
                    "boundary_entries": [],
                    "base_snapshot_id": "snapshot",
                    "observed_graph_position": 1,
                    "is_mutating": True,
                    "complete_node": True,
                    "new_state": "completed",
                },
                3,
            ),
        ),
        lambda p: p.execution.attempts_by_execution_id["execution"].payload,
        lambda c: c["state"]["execution"]["attempts_by_execution_id"]["execution"].get("payload"),
        "map-value",
    )  # type: ignore[index]
    cases[("ExecutionAttemptValue", "validation_witness")] = FlexibleJsonCase(
        "ExecutionAttemptValue",
        "validation_witness",
        lambda probe: (
            _node("node"),
            event(
                "lease_granted",
                {
                    "lease_id": "lease",
                    "node_id": "node",
                    "generation": 1,
                    "execution_id": "execution",
                    "base_snapshot_id": "snapshot",
                },
                1,
            ),
            event(
                "runner_baseline_recorded",
                {
                    "execution_id": "execution",
                    "node_id": "node",
                    "lease_id": "lease",
                    "lease_generation": 1,
                    "baseline_snapshot_id": "snapshot",
                    "baseline_tree_sha": "a" * 40,
                    "entries": [],
                    "boundary_hash": boundary_manifest_hash("a" * 40, []),
                    "cache_roots": [],
                },
                2,
            ),
            event(
                "runner_submission_staged",
                {
                    "execution_id": "execution",
                    "node_id": "node",
                    "lease_id": "lease",
                    "lease_generation": 1,
                    "idempotency_key": "key",
                    "payload": {"result": "ok"},
                    "payload_hash": "sha256:1",
                    "staged_snapshot_id": "staged",
                    "staged_snapshot_ref": "refs/orchestrator/snapshots/staged",
                    "staged_commit_sha": "b" * 40,
                    "staged_tree_sha": "a" * 40,
                    "boundary_hash": boundary_manifest_hash("a" * 40, []),
                    "boundary_entries": [],
                    "base_snapshot_id": "snapshot",
                    "observed_graph_position": 1,
                    "is_mutating": True,
                    "complete_node": True,
                    "new_state": "completed",
                    "validation_witness": {
                        "schema_version": 1,
                        "node_id": "node",
                        "execution_id": "execution",
                        "lease_id": "lease",
                        "lease_generation": 1,
                        "base_snapshot_id": "snapshot",
                        "disposition": "no_configured_commands",
                        "commands": [],
                        "validated_boundary": {
                            "snapshot_id": "staged",
                            "snapshot_ref": "refs/orchestrator/snapshots/staged",
                            "commit_sha": "b" * 40,
                            "tree_sha": "a" * 40,
                            "boundary_hash": boundary_manifest_hash("a" * 40, []),
                        },
                        "probe": probe,
                    },
                },
                3,
            ),
        ),
        lambda p: p.execution.attempts_by_execution_id["execution"].validation_witness["probe"],
        lambda c: c["state"]["execution"]["attempts_by_execution_id"]["execution"][
            "validation_witness"
        ]["probe"],
        "direct",
    )
    cases[("OutputRecord", "value")] = _record_case(
        "OutputRecord",
        "value",
        "fan_out_inputs",
        "fan_out_inputs",
        "FanOutInputs",
        lambda p: p,
        container="map-value",
    )
    cases[("CompletionDecisionValue", "blockers")] = _record_case(
        "CompletionDecisionValue",
        "blockers",
        "completion_decision",
        "completion_decision",
        "CompletionDecision",
        lambda p: {"status": "blocked", "blockers": p},
        container="tuple-map-value",
    )
    cases[("DecisionRecordValue", "scope")] = _record_case(
        "DecisionRecordValue",
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
    cases[("AuthorityDecisionValue", "scope")] = _record_case(
        "AuthorityDecisionValue",
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
    cases[("GraphPatchProposalValue", "ops")] = _record_case(
        "GraphPatchProposalValue",
        "ops",
        "graph_patch_proposal",
        "graph_patch_proposal",
        "GraphPatch",
        lambda p: {
            "patch_id": "patch-ops",
            "proposed_by_node_id": "node-record-GraphPatchProposalValue-ops",
            "base_graph_position": 0,
            "ops": p,
        },
        container="tuple-map-value",
    )
    cases[("GraphPatchProposalValue", "macro_invocations")] = _record_case(
        "GraphPatchProposalValue",
        "macro_invocations",
        "graph_patch_proposal",
        "graph_patch_proposal",
        "GraphPatch",
        lambda p: {
            "patch_id": "patch-macros",
            "proposed_by_node_id": "node-record-GraphPatchProposalValue-macro_invocations",
            "base_graph_position": 0,
            "macro_invocations": p,
        },
        container="tuple-map-value",
    )
    cases[("RecoveryPlanValue", "graph_changes")] = _record_case(
        "RecoveryPlanValue",
        "graph_changes",
        "recovery_plan",
        "recovery_plan",
        "RecoveryPlan",
        lambda p: {"action": "retry", "responsible_actor": "controller", "graph_changes": p},
        container="tuple-map-value",
    )
    cases[("RoutineSnapshotValue", "dynamic_feature")] = _record_case(
        "RoutineSnapshotValue",
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
    cases[("VerificationReportRecord", "evidence")] = _record_case(
        "VerificationReportRecord",
        "evidence",
        "verification_report",
        "verification_report",
        "VerificationReport",
        lambda p: {"outcome": "passed", "grades": []},
        extra={"candidate_id": "candidate", "outcome": "passed", "evidence": None},
    )
    # evidence is an envelope field and needs its own event-backed producer.
    evidence = cases[("VerificationReportRecord", "evidence")]
    cases[("VerificationReportRecord", "evidence")] = FlexibleJsonCase(
        evidence.owner,
        evidence.field,
        lambda probe: _record(
            "record-VerificationReportRecord-evidence",
            "verification_report",
            "verification_report",
            "VerificationReport",
            {"outcome": "passed", "grades": []},
            candidate_id="candidate",
            outcome="passed",
            evidence=probe,
        ),
        lambda p: getattr(
            _required_record(p, "record-VerificationReportRecord-evidence"), "evidence"
        ),
        lambda c: c["state"]["records"]["by_id"]["record-VerificationReportRecord-evidence"].get(
            "evidence"
        ),
        "direct",
        lambda c: "evidence"
        in c["state"]["records"]["by_id"]["record-VerificationReportRecord-evidence"],
        omits_none=True,
    )  # type: ignore[index]
    for field in ("payload", "provenance"):
        cases[("TypedRecordBase", field)] = _record_case(
            "TypedRecordBase",
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
        cases[("CheckResultValue", field)] = _record_case(
            "CheckResultValue",
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
    cases[("GitRef", "diff_summary")] = FlexibleJsonCase(
        "GitRef",
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
        lambda c: c["state"]["records"]["by_id"]["file-state"]["git"]["diff_summary"],
        "map-value",
    )  # type: ignore[index]

    def semantic_declaration_events(probe: object) -> tuple[EventEnvelope, ...]:
        return _record(
            "semantic-schema-flex",
            "semantic_schema_declaration",
            "semantic_schema_declaration",
            "SemanticSchemaDeclaration",
            {
                "schema_id": "flexible-schema",
                "version": 1,
                "semantic_role": "flexible",
                "json_schema": {"type": "object", "probe": probe},
                "authority": "routine_snapshot",
            },
            schema_version=1,
        )

    cases[("SemanticSchemaDeclarationValue", "json_schema")] = FlexibleJsonCase(
        "SemanticSchemaDeclarationValue",
        "json_schema",
        semantic_declaration_events,
        lambda p: getattr(_required_record(p, "semantic-schema-flex").value, "json_schema")[
            "probe"
        ],
        lambda c: c["state"]["records"]["by_id"]["semantic-schema-flex"]["value"]["json_schema"][
            "probe"
        ],
        "direct",
    )

    def semantic_artifact_events(
        probe: object, *, field: str, referenced: bool = False
    ) -> tuple[EventEnvelope, ...]:
        value: dict[str, object] = {
            "semantic_role": "flexible",
            "schema_id": "flexible-schema",
            "schema_version": 1,
            "provenance": {"probe": probe} if field == "provenance" else {},
            "authority_status": "accepted",
        }
        if referenced:
            digest = "sha256:" + "0" * 64
            value.update(
                {
                    "artifact_ref": {
                        "artifact_id": digest,
                        "content_hash": digest,
                        "size_bytes": 1,
                        "media_type": "application/json",
                        "encoding": "utf-8",
                        "storage_uri": "artifact://sha256/" + "0" * 64,
                    },
                    "artifact_validation": {
                        "declaration_record_id": "semantic-schema-flex",
                        "content_hash": digest,
                        "validated_json": {"probe": probe},
                    },
                }
            )
        else:
            value["content"] = {"probe": probe}
        return _record(
            f"semantic-artifact-{field}",
            "semantic_artifact",
            "semantic_artifact",
            "SemanticArtifact",
            value,
            schema_version=1,
        )

    for owner, field, referenced in (
        ("SemanticArtifactValue", "content", False),
        ("SemanticArtifactValue", "provenance", False),
        ("SemanticArtifactValidation", "validated_json", True),
    ):
        record_id = f"semantic-artifact-{field}"
        cases[(owner, field)] = FlexibleJsonCase(
            owner,
            field,
            lambda probe, field=field, referenced=referenced: semantic_artifact_events(
                probe, field=field, referenced=referenced
            ),
            (
                lambda p, field=field, referenced=referenced: (
                    getattr(_required_record(p, f"semantic-artifact-{field}").value, field)["probe"]
                    if not referenced
                    else _required_record(
                        p, f"semantic-artifact-{field}"
                    ).value.artifact_validation.validated_json["probe"]
                )
            ),
            (
                lambda c, record_id=record_id, field=field, referenced=referenced: (
                    c["state"]["records"]["by_id"][record_id]["value"][field]["probe"]
                    if not referenced
                    else c["state"]["records"]["by_id"][record_id]["value"]["artifact_validation"][
                        "validated_json"
                    ]["probe"]
                )
            ),
            "direct",
        )
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
    expected = case.expected_value(probe)
    assert thaw_json(case.projected_value(projection)) == expected
    checkpoint = projection_to_checkpoint(projection)
    checkpoint_value = case.checkpoint_value(checkpoint)
    if case.checkpoint_present is not None:
        assert case.checkpoint_present(checkpoint) is not (probe is None and case.omits_none)
    _assert_plain_json(checkpoint_value)
    assert checkpoint_value == expected
    restored = projection_from_checkpoint(deepcopy(checkpoint))
    assert restored == projection
    assert thaw_json(case.projected_value(restored)) == expected
    _assert_deeply_immutable(case.projected_value(restored))
