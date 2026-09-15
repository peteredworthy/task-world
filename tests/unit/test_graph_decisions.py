"""Contract tests for decision-v1 models, selection, and transport envelopes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from pydantic import TypeAdapter, ValidationError

from orchestrator.config import RoutineConfig
from orchestrator.graph_runtime import GraphDispatchContext, render_graph_node_prompt
from tests.unit.graph_test_utils import event as graph_event
from orchestrator.runners import (
    SubmissionContract,
    SubmissionInvocation,
    SubmissionOutputContract,
    submission_tool_input_schema,
)
from orchestrator.graph import (
    BatchDecision,
    CorrectionDecision,
    DECISION_PLAN_SCHEMA_ID,
    DecisionContractResolutionError,
    DecisionSubmissionEnvelope,
    DecisionSubmissionRequest,
    DiscoveryBrief,
    FakeClock,
    GraphCommandContext,
    ImplementationPlan,
    PatchCommandContext,
    SequentialIdGenerator,
    VerificationDecision,
    verification_decision_schema,
    verification_decision_schema_sha256,
    WorkResult,
    apply_command,
    batch_decision_schema_sha256,
    boundary_manifest_hash,
    build_projection,
    callback_payload_identity,
    canonical_decision_answer_hash,
    compile_batch_decision,
    compile_work_result,
    compile_verification_decision,
    compile_routine,
    decision_plan_declaration,
    decision_recovery_uses_legacy_contract,
    decode_submission_payload,
    execution_attempts_view,
    leases_view,
    node_payload_view,
    node_states_view,
    reliable_plan_check_decision_tool_schema,
    reduce_event,
    recovery_proof_hash,
    resolve_decision_applicability,
    resolve_batch_decision_context,
    resolve_work_result_context,
    resolve_verification_decision_context,
    semantic_schema_declarations_view,
    work_result_schema,
    work_result_schema_sha256,
)


def test_verification_decision_schema_is_strict_and_requires_one_finding_per_alias() -> None:
    schema = verification_decision_schema()
    assert schema["additionalProperties"] is False
    assert verification_decision_schema_sha256().startswith("sha256:")
    answer = {
        "findings": [{"obligation": "o1", "grade": "A", "reason": "satisfied", "evidence": []}]
    }
    VerificationDecision.model_validate(answer)
    with pytest.raises(ValidationError):
        VerificationDecision.model_validate({**answer, "unexpected": True})
    with pytest.raises(ValidationError):
        VerificationDecision.model_validate(
            {"findings": [answer["findings"][0], answer["findings"][0]]}
        )


def test_verification_decision_rejects_unknown_aliases_and_empty_reasons() -> None:
    with pytest.raises(ValidationError):
        VerificationDecision.model_validate(
            {"findings": [{"obligation": "x1", "grade": "A", "reason": "ok", "evidence": []}]}
        )
    with pytest.raises(ValidationError):
        VerificationDecision.model_validate(
            {"findings": [{"obligation": "o1", "grade": "A", "reason": " ", "evidence": []}]}
        )


@pytest.mark.parametrize(
    "mutate",
    ["empty", "duplicate"],
)
def test_verification_decision_rejects_incomplete_or_unknown_findings(mutate: str) -> None:
    answer: dict[str, Any] = {
        "findings": [
            {"obligation": "o1", "grade": "A", "reason": "covered", "evidence": []},
            {"obligation": "o2", "grade": "A", "reason": "covered", "evidence": []},
        ]
    }
    if mutate == "empty":
        answer["findings"] = []
    else:
        answer["findings"][1]["obligation"] = "o1"

    with pytest.raises(ValidationError):
        VerificationDecision.model_validate(answer)


def _planner_routine(*, interaction: str | None = None) -> RoutineConfig:
    payload: dict[str, Any] = {
        "id": "decision-routine",
        "name": "Decision routine",
        "steps": [{"id": "plan", "title": "Plan", "kind": "planner"}],
    }
    if interaction is not None:
        payload["agent_interaction_contract"] = interaction
    return RoutineConfig.model_validate(payload)


def _worker_routine(*, interaction: str | None = None) -> RoutineConfig:
    payload: dict[str, Any] = {
        "id": "decision-worker-routine",
        "name": "Decision worker routine",
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Implement task",
                    }
                ],
            }
        ],
    }
    if interaction is not None:
        payload["agent_interaction_contract"] = interaction
    return RoutineConfig.model_validate(payload)


def _compile(routine: RoutineConfig):
    return compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="decision-run",
    )


def _valid_plan() -> dict[str, Any]:
    return {
        "summary": "Implement in dependency order.",
        "batches": [
            {
                "key": "core",
                "objective": "Build the core.",
                "scope": ["src/core.py"],
                "requirements": ["r1"],
                "acceptance": ["The core works."],
                "checks": [{"name": "unit", "command_definition": {"argv": ["pytest"]}}],
            },
            {
                "key": "api",
                "objective": "Expose the core.",
                "scope": ["src/api.py"],
                "requirements": ["r2"],
                "depends_on": ["core"],
                "acceptance": ["The API works."],
                "checks": [{"name": "oracle", "command_binding": "dynamic_feature_hidden_oracle"}],
            },
        ],
    }


def _context_ref(digest: str) -> dict[str, Any]:
    return {
        "artifact_id": digest,
        "content_hash": digest,
        "size_bytes": 12,
        "media_type": "application/json",
        "encoding": "utf-8",
        "storage_uri": f"artifact://sha256/{digest.removeprefix('sha256:')}",
    }


def decision_successor_events(requirement_count: int = 1) -> list[Any]:
    compiled = _compile(_planner_routine(interaction="decision-v1"))
    events = []
    for position, item in enumerate(compiled, start=1):
        payload = dict(item.payload)
        if item.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload.update(
                {
                    "state": "running",
                    "semantic_stage": "successor_planning",
                    "planning_horizon": 1,
                    "reliable_plan_remaining_horizons": 1,
                    "reliable_plan_one_horizon_authorized": True,
                    "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                    "reliable_plan_qualification_evidence_hash": "sha256:" + "d" * 64,
                    "reliable_plan_assignment_carrier": {
                        "skeleton_id": "reliable-plan-fff4f6b7-v1",
                        "selected_runner_type": "codex_server",
                        "arm": {
                            "arm_id": "decision-test",
                            **{
                                role: {
                                    "runner_type": "codex_server",
                                    "model": "test-model",
                                    "profile": profile,
                                }
                                for role, profile in {
                                    "planner": "architect",
                                    "discovery_worker": "summarizer",
                                    "implementation_worker": "coder",
                                    "correction_worker": "coder",
                                    "verifier": "coder",
                                    "successor_planner": "architect",
                                }.items()
                            },
                        },
                    },
                    "task_region_id": "successor-core",
                    "scope": "core",
                    "inputs": [
                        {
                            "port": "routine_snapshot",
                            "direction": "input",
                            "schema": "RoutineSnapshot",
                            "required": True,
                        },
                        {
                            "port": "semantic_artifact",
                            "direction": "input",
                            "schema": "SemanticArtifact",
                            "required": True,
                        },
                        {
                            "port": "verification_report",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                        *[
                            {
                                "port": f"requirement_{index}",
                                "direction": "input",
                                "schema": "RequirementRecord",
                                "required": True,
                            }
                            for index in range(1, requirement_count + 1)
                        ],
                    ],
                    "outputs": [
                        {
                            "port": "decision",
                            "direction": "output",
                            "schema": "DecisionAnswer",
                            "record_layers": ["graph_record"],
                            "required": True,
                        },
                        {
                            "port": "semantic_artifact",
                            "direction": "output",
                            "schema": "SemanticArtifact",
                            "record_layers": ["graph_record"],
                            "required": False,
                        },
                    ],
                }
            )
        if item.event_type == "output_record_accepted":
            payload["graph_position"] = position
            if payload.get("record_id") == "routine-snapshot-record":
                value = dict(cast(dict[str, Any], payload["value"]))
                value["dynamic_feature"] = {
                    "acceptance_command": "true",
                    "hidden_oracle_command": "true",
                    "patch_budget": 2,
                }
                payload["value"] = value
        if item.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {record_id: position for record_id in record_ids}
        events.append(item.model_copy(update={"position": position, "payload": payload}))

    additions = [
        (
            "node_created",
            {
                "node_id": "worker-discovery",
                "kind": "worker",
                "role": "discovery",
                "state": "completed",
                "semantic_stage": "discovery",
                "outputs": [
                    {
                        "port": "semantic_artifact",
                        "direction": "output",
                        "schema": "SemanticArtifact",
                        "record_layers": ["graph_record"],
                    }
                ],
            },
        ),
        (
            "node_created",
            {
                "node_id": "verifier-plan",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "semantic_stage": "plan_verification",
                "outputs": [
                    {
                        "port": "verification_report",
                        "direction": "output",
                        "schema": "VerificationReport",
                        "record_layers": ["verification"],
                    }
                ],
            },
        ),
    ]
    additions.extend(
        (
            "node_created",
            {
                "node_id": f"requirement-{index}",
                "kind": "requirement",
                "role": "requirement",
                "state": "completed",
                "outputs": [
                    {
                        "port": "requirement",
                        "direction": "output",
                        "schema": "RequirementRecord",
                        "record_layers": ["graph_record"],
                    }
                ],
            },
        )
        for index in range(1, requirement_count + 1)
    )
    for kind, payload in additions:
        events.append(graph_event(kind, payload, position=len(events) + 1))

    plan_position = len(events) + 1
    plan = _valid_plan()
    plan["batches"] = [plan["batches"][0]]
    plan["batches"][0]["requirements"] = [f"r{index}" for index in range(1, requirement_count + 1)]
    events.append(
        graph_event(
            "output_record_accepted",
            {
                "record_id": "accepted-decision-plan",
                "record_kind": "graph_record",
                "record_type": "semantic_artifact",
                "producer_node_id": "worker-discovery",
                "producer_port": "semantic_artifact",
                "port": "semantic_artifact",
                "schema": "SemanticArtifact",
                "schema_version": 1,
                "graph_position": plan_position,
                "value": {
                    "semantic_role": "implementation_plan",
                    "schema_id": DECISION_PLAN_SCHEMA_ID,
                    "schema_version": 1,
                    "content": plan,
                    "provenance": {"source": "discovery"},
                    "source_record_ids": [
                        f"requirement-record-{index}" for index in range(1, requirement_count + 1)
                    ],
                    "requirement_ids": [
                        f"REQ-{index}" for index in range(1, requirement_count + 1)
                    ],
                    "task_region_id": "discovery",
                    "validation_status": "validated",
                    "authority_status": "accepted",
                },
            },
            position=plan_position,
        )
    )
    verification_position = len(events) + 1
    events.append(
        graph_event(
            "output_record_accepted",
            {
                "record_id": "plan-passed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-plan",
                "port": "verification_report",
                "schema": "VerificationReport",
                "graph_position": verification_position,
                "candidate_id": "accepted-decision-plan",
                "candidate_record_id": "accepted-decision-plan",
                "candidate_record_ids": ["accepted-decision-plan"],
                "task_region_id": "plan-verification",
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": []},
                "evaluated_record_ids": [
                    "accepted-decision-plan",
                    *[f"requirement-record-{index}" for index in range(1, requirement_count + 1)],
                ],
            },
            position=verification_position,
        )
    )
    requirement_positions: dict[int, int] = {}
    for index in range(1, requirement_count + 1):
        requirement_position = len(events) + 1
        requirement_positions[index] = requirement_position
        events.append(
            graph_event(
                "output_record_accepted",
                {
                    "record_id": f"requirement-record-{index}",
                    "record_kind": "graph_record",
                    "record_type": "requirement_record",
                    "producer_node_id": f"requirement-{index}",
                    "port": "requirement",
                    "schema": "RequirementRecord",
                    "graph_position": requirement_position,
                    "value": {
                        "id": f"REQ-{index}",
                        "text": f"Implement bounded requirement {index}.",
                        "priority": "critical",
                        "source": "routine",
                        "version": f"v{index}",
                        "must": True,
                    },
                },
                position=requirement_position,
            )
        )
    bindings = [
        (
            "plan-to-verifier",
            "worker-discovery",
            "semantic_artifact",
            "semantic_artifact",
            "accepted-decision-plan",
            plan_position,
            {"record_id": "accepted-decision-plan"},
            "verifier-plan",
        ),
        (
            "plan-to-successor",
            "worker-discovery",
            "semantic_artifact",
            "semantic_artifact",
            "accepted-decision-plan",
            plan_position,
            {"record_id": "accepted-decision-plan"},
            "planner-plan",
        ),
        (
            "verification-to-successor",
            "verifier-plan",
            "verification_report",
            "verification_report",
            "plan-passed",
            verification_position,
            {"record_id": "plan-passed"},
            "planner-plan",
        ),
    ]
    bindings.extend(
        (
            f"requirement-{index}-to-successor",
            f"requirement-{index}",
            "requirement",
            f"requirement_{index}",
            f"requirement-record-{index}",
            requirement_positions[index],
            {"record_id": f"requirement-record-{index}"},
            "planner-plan",
        )
        for index in range(1, requirement_count + 1)
    )
    for (
        edge_id,
        source,
        source_port,
        target_port,
        record_id,
        _record_position,
        selector,
        target,
    ) in bindings:
        events.append(
            graph_event(
                "edge_created",
                {
                    "edge_id": edge_id,
                    "from_node_id": source,
                    "from_port": source_port,
                    "to_node_id": target,
                    "to_port": target_port,
                    "required": True,
                    "dependency_type": "input_binding",
                    "accepted_record_selector": selector,
                },
                position=len(events) + 1,
            )
        )
        bound_position = len(events) + 1
        events.append(
            graph_event(
                "input_bound",
                {
                    "edge_id": edge_id,
                    "to_node_id": target,
                    "to_port": target_port,
                    "record_ids": [record_id],
                    "bound_at_position": bound_position,
                    "record_bound_positions": {record_id: bound_position},
                },
                position=bound_position,
            )
        )
    return events


def _decision_successor_projection(requirement_count: int = 1):
    return build_projection(decision_successor_events(requirement_count))


def _work_result_projection(
    *,
    node_id: str = "worker-core",
    node_overrides: dict[str, Any] | None = None,
    bind_evidence: bool = True,
):
    events = []
    for event in decision_successor_events():
        payload = dict(event.payload)
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload["node_id"] = node_id
            payload.update(
                {
                    "kind": "worker",
                    "role": "implementer",
                    "semantic_stage": "effectful_batch",
                    "task_region_id": "batch-core",
                    "access_mode": "write",
                    "effect_contract": "effectful_write",
                    "outputs": [
                        {
                            "port": "candidate",
                            "direction": "output",
                            "schema": "ImplementationCandidate",
                            "required": True,
                        },
                        {
                            "port": "file_state",
                            "direction": "output",
                            "schema": "FileStateRecord",
                            "required": True,
                        },
                        {
                            "port": "decision",
                            "direction": "output",
                            "schema": "DecisionAnswer",
                            "required": True,
                        },
                    ],
                }
            )
            payload.update(node_overrides or {})
        if event.event_type in {"edge_created", "input_bound"}:
            if payload.get("to_node_id") == "planner-plan":
                if not bind_evidence and payload.get("to_port") in {
                    "semantic_artifact",
                    "verification_report",
                }:
                    continue
                payload["to_node_id"] = node_id
        events.append(event.model_copy(update={"payload": payload}))
    return build_projection(events)


def test_work_result_schema_and_canonical_answers_are_strict() -> None:
    schema = work_result_schema()
    assert schema["discriminator"]["propertyName"] == "status"
    assert work_result_schema_sha256().startswith("sha256:")
    assert (
        TypeAdapter(WorkResult)
        .validate_python({"status": "ready", "summary": "Committed candidate is ready."})
        .status
        == "ready"
    )
    assert (
        TypeAdapter(WorkResult)
        .validate_python(
            {
                "status": "blocked",
                "blocker": {
                    "reason": "Missing credentials.",
                    "needed_information": ["A test credential"],
                    "evidence": [],
                },
            }
        )
        .status
        == "blocked"
    )
    with pytest.raises(ValidationError, match="non-whitespace"):
        TypeAdapter(WorkResult).validate_python({"status": "ready", "summary": "  "})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TypeAdapter(WorkResult).validate_python(
            {"status": "ready", "summary": "ready", "candidate_id": "model-owned"}
        )


@pytest.mark.parametrize(
    ("answer", "disposition", "completion_state"),
    [
        (
            {"status": "ready", "summary": "Implemented and ready for checks."},
            "proceed",
            "completed",
        ),
        (
            {
                "status": "blocked",
                "blocker": {
                    "reason": "The required fixture is unavailable.",
                    "needed_information": ["Fixture path"],
                    "evidence": [],
                },
            },
            "blocked",
            "failed",
        ),
    ],
)
def test_compile_work_result_owns_only_answer_and_runtime_disposition(
    answer: dict[str, Any],
    disposition: str,
    completion_state: str,
) -> None:
    projection = _work_result_projection()
    resolved = resolve_work_result_context(projection, "worker-core")
    assert resolved.task_region_id == "batch-core"
    compiled = compile_work_result(
        projection,
        node_id="worker-core",
        decision_request_id="request-work-result",
        base_graph_position=100,
        answer=answer,
    )
    assert compiled.ops == ()
    assert compiled.disposition == disposition
    assert compiled.completion_state == completion_state
    assert compiled.decision_record.value.family == "work_result"
    assert compiled.decision_record.value.answer == answer
    assert compiled.decision_record.value.bound_input_record_ids
    assert compiled.decision_record.value.consequence_patch_id.startswith("work-result-")


@pytest.mark.parametrize(
    "answer",
    [
        {"status": "ready", "summary": "Implemented and ready for checks."},
        {
            "status": "blocked",
            "blocker": {
                "reason": "The required fixture is unavailable.",
                "needed_information": ["Fixture path"],
                "evidence": [],
            },
        },
    ],
)
def test_work_result_identity_is_scoped_and_stable_across_redelivery_and_replay(
    answer: dict[str, Any],
) -> None:
    projection = _work_result_projection()
    first = compile_work_result(
        projection,
        node_id="worker-core",
        decision_request_id="request-first-execution",
        base_graph_position=100,
        answer=answer,
    )
    another_execution = compile_work_result(
        projection,
        node_id="worker-core",
        decision_request_id="request-another-execution",
        base_graph_position=100,
        answer=answer,
    )
    another_worker = compile_work_result(
        _work_result_projection(node_id="worker-other"),
        node_id="worker-other",
        decision_request_id="request-first-execution",
        base_graph_position=100,
        answer=answer,
    )
    compilations = (first, another_execution, another_worker)
    assert len({item.patch_id for item in compilations}) == 3
    assert len({item.decision_record.record_id for item in compilations}) == 3
    assert len({item.decision_record.value.answer_sha256 for item in compilations}) == 1

    # Delivery order, graph position, and reconstructing the same durable graph
    # do not create a new logical answer or a new consequence identity.
    reordered_answer = dict(reversed(list(answer.items())))
    for repeated_projection in (projection, _work_result_projection()):
        repeated = compile_work_result(
            repeated_projection,
            node_id="worker-core",
            decision_request_id="request-first-execution",
            base_graph_position=200,
            answer=reordered_answer,
        )
        assert repeated.patch_id == first.patch_id
        assert repeated.decision_record == first.decision_record
        assert repeated.bound_inputs == first.bound_inputs
        assert repeated.read_set == first.read_set


def _blocked_work_answer(evidence: list[str]) -> dict[str, Any]:
    return {
        "status": "blocked",
        "blocker": {
            "reason": "The bound evidence leaves a required fixture unresolved.",
            "needed_information": ["Fixture path"],
            "evidence": evidence,
        },
    }


def test_worker_blocker_uses_only_offered_frozen_evidence() -> None:
    projection = _work_result_projection()
    resolved = resolve_work_result_context(projection, "worker-core")
    expected = {"e1": "accepted-decision-plan", "e2": "plan-passed"}
    assert dict(resolved.evidence_aliases.object_items()) == expected
    assert resolved.protected_question_context()["evidence_aliases"] == expected
    compiled = compile_work_result(
        projection,
        node_id="worker-core",
        decision_request_id="blocked-evidence-request",
        base_graph_position=100,
        answer=_blocked_work_answer(["e1", "e2"]),
    )
    assert compiled.disposition == "blocked"
    assert compiled.decision_record.value.answer == _blocked_work_answer(["e1", "e2"])
    node = node_payload_view(projection, "worker-core")
    assert node is not None
    prompt = render_graph_node_prompt(
        GraphDispatchContext(
            run_id="run-1",
            node_id="worker-core",
            node_kind="worker",
            node_role="implementer",
            node_payload=dict(node),
            requirements=[],
            worktree_path="/tmp/work-result-prompt",
            lease_id="work-lease",
            lease_generation=1,
            execution_id="work-execution",
            base_snapshot_id="work-base",
            dispatch_event_id="dispatch-work",
            graph_projection=projection,
            graph_events=[],
        )
    )
    assert '"evidence_aliases": {"e1": "accepted-decision-plan", "e2": "plan-passed"}' in prompt


@pytest.mark.parametrize("evidence", [["e999"], ["e3"]])
def test_worker_blocker_rejects_unknown_or_unbound_evidence(evidence: list[str]) -> None:
    projection = _work_result_projection()
    # A globally accepted report for a different candidate is not an offered
    # input to this worker, even though it exists in the same graph.
    unbound_report = next(
        item
        for item in decision_successor_events()
        if item.event_type == "output_record_accepted"
        and item.payload.get("record_id") == "plan-passed"
    )
    payload = dict(unbound_report.payload)
    payload.update(
        {
            "record_id": "unbound-foreign-report",
            "candidate_id": "foreign-candidate",
            "candidate_record_id": "foreign-candidate",
            "candidate_record_ids": ["foreign-candidate"],
            "graph_position": 100,
        }
    )
    projection = reduce_event(
        projection, unbound_report.model_copy(update={"position": 100, "payload": payload})
    )
    with pytest.raises(ValueError, match="unknown evidence alias"):
        compile_work_result(
            projection,
            node_id="worker-core",
            decision_request_id="blocked-evidence-request",
            base_graph_position=100,
            answer=_blocked_work_answer(evidence),
        )


def test_corrective_worker_does_not_offer_evidence_for_another_candidate() -> None:
    projection = _work_result_projection(
        node_overrides={
            "semantic_stage": "corrective_work",
            "base_snapshot_selection": "rejected_candidate",
            "base_snapshot_candidate_id": "rejected-candidate",
        }
    )
    resolved = resolve_work_result_context(projection, "worker-core")
    assert "plan-passed" not in resolved.evidence_aliases.values()
    with pytest.raises(ValueError, match="unknown evidence alias"):
        compile_work_result(
            projection,
            node_id="worker-core",
            decision_request_id="blocked-evidence-request",
            base_graph_position=100,
            answer=_blocked_work_answer(["e2"]),
        )


def test_worker_without_offered_evidence_requires_empty_blocker_evidence() -> None:
    projection = _work_result_projection(bind_evidence=False)
    resolved = resolve_work_result_context(projection, "worker-core")
    assert not resolved.evidence_aliases
    for evidence in ([], ["e1"]):
        if evidence:
            with pytest.raises(ValueError, match="unknown evidence alias"):
                compile_work_result(
                    projection,
                    node_id="worker-core",
                    decision_request_id="blocked-without-evidence",
                    base_graph_position=100,
                    answer=_blocked_work_answer(evidence),
                )
        else:
            compiled = compile_work_result(
                projection,
                node_id="worker-core",
                decision_request_id="blocked-without-evidence",
                base_graph_position=100,
                answer=_blocked_work_answer(evidence),
            )
            assert compiled.disposition == "blocked"


def _verification_events(
    *,
    receipt_statuses: tuple[str, ...] = ("passed",),
    receipt_mutations: dict[int, dict[str, Any]] | None = None,
    declare_extra_check: bool = False,
) -> list[Any]:
    """Build one exact decision-v1 verifier request from public graph events."""
    events: list[Any] = []
    for item in _compile(_planner_routine(interaction="decision-v1")):
        payload = dict(item.payload)
        if item.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload.update(
                {
                    "kind": "verifier",
                    "role": "verifier",
                    "semantic_stage": "effectful_batch",
                    "task_region_id": "batch-core",
                    "acceptance": ["The exact candidate passes acceptance."],
                    "rubric": ["The implementation is maintainable."],
                    "inputs": [
                        {
                            "port": "routine_snapshot",
                            "direction": "input",
                            "schema": "RoutineSnapshot",
                            "required": True,
                        },
                        {
                            "port": "candidate_under_test",
                            "direction": "input",
                            "schema": "ImplementationCandidate",
                            "required": True,
                        },
                        *[
                            {
                                "port": f"check_result_{index}",
                                "direction": "input",
                                "schema": "CheckResult",
                                "required": True,
                            }
                            for index in range(
                                1,
                                len(receipt_statuses) + 1 + int(declare_extra_check),
                            )
                        ],
                        {
                            "port": "requirement_1",
                            "direction": "input",
                            "schema": "Requirement",
                            "required": True,
                        },
                    ],
                    "outputs": [
                        {
                            "port": "decision",
                            "direction": "output",
                            "schema": "DecisionAnswer",
                            "record_layers": ["graph_record"],
                            "required": True,
                        },
                        {
                            "port": "verification_report",
                            "direction": "output",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                        {
                            "port": "semantic_artifact",
                            "direction": "output",
                            "schema": "SemanticArtifact",
                            "record_layers": ["graph_record"],
                            "required": True,
                        },
                    ],
                }
            )
        if item.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = len(events) + 1
            payload["record_bound_positions"] = {
                record_id: len(events) + 1 for record_id in record_ids
            }
        if item.event_type == "output_record_accepted":
            payload["graph_position"] = len(events) + 1
        events.append(item.model_copy(update={"position": len(events) + 1, "payload": payload}))

    def append(kind: str, payload: dict[str, Any]) -> int:
        position = len(events) + 1
        if kind == "output_record_accepted":
            payload = {**payload, "graph_position": position}
        events.append(graph_event(kind, payload, position=position))
        return position

    append(
        "node_created",
        {"node_id": "requirement-core", "kind": "requirement", "role": "requirement"},
    )
    append("node_created", {"node_id": "worker-core", "kind": "worker", "role": "implementer"})
    requirement_position = append(
        "output_record_accepted",
        {
            "record_id": "requirement-core-record",
            "record_kind": "graph_record",
            "record_type": "requirement_record",
            "producer_node_id": "requirement-core",
            "port": "requirement",
            "schema": "RequirementRecord",
            "value": {
                "id": "REQ-CORE",
                "text": "Implement the exact behavior.",
                "priority": "critical",
                "source": "routine",
                "version": "v1",
                "must": True,
            },
        },
    )
    append(
        "file_state_accepted",
        {
            "record_id": "file-state-core-record",
            "record_kind": "file_state",
            "record_type": "file_state",
            "producer_node_id": "worker-core",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": "candidate-snapshot",
            "candidate_id": "candidate-core-record",
            "task_region_id": "batch-core",
            "verdict": "captured",
            "git": {
                "commit_sha": "a" * 40,
                "tree_sha": "b" * 40,
                "ref": "refs/orchestrator/snapshots/candidate-snapshot",
            },
        },
    )
    candidate_position = append(
        "output_record_accepted",
        {
            "record_id": "candidate-core-record",
            "record_kind": "output",
            "record_type": "candidate",
            "producer_node_id": "worker-core",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "candidate_id": "candidate-core-record",
            "task_region_id": "batch-core",
            "attempt_number": 1,
            "file_state_record_id": "file-state-core-record",
            "file_state_record_ids": ["file-state-core-record"],
            "value": {
                "summary": "candidate",
                "changed_paths": ["src/core.py"],
                "requirements_addressed": ["REQ-CORE"],
                "file_state_record_id": "file-state-core-record",
                "file_state_record_ids": ["file-state-core-record"],
            },
        },
    )
    mutations = receipt_mutations or {}
    receipt_rows: list[tuple[int, str, str]] = []
    for index, status in enumerate(receipt_statuses, 1):
        check_id = f"check-core-{index}"
        command = {
            "id": f"command-core-{index}",
            "argv": ["true"],
            "timeout_seconds": 5.0,
        }
        append(
            "node_created",
            {
                "node_id": check_id,
                "kind": "check",
                "role": "batch_check",
                "semantic_stage": "effectful_batch",
                "task_region_id": "batch-core",
                "command_definition": command,
                "base_snapshot_selection": "candidate_under_test",
            },
        )
        receipt_id = f"check-core-record-{index}"
        receipt = {
            "record_id": receipt_id,
            "record_kind": "output",
            "record_type": "check_result",
            "producer_node_id": check_id,
            "port": "check_result",
            "schema": "CheckResult",
            "candidate_id": "candidate-core-record",
            "task_region_id": "batch-core",
            "attempt_number": 1,
            "candidate_record_id": "candidate-core-record",
            "candidate_record_ids": ["candidate-core-record"],
            "file_state_record_ids": ["file-state-core-record"],
            "evaluated_record_ids": ["candidate-core-record"],
            "value": {
                "status": status,
                "classification": status,
                "command_id": f"command-core-{index}",
                "command_text": "true",
                "command": command,
                "worktree_path": "/tmp/source-worktree",
                "source_worktree_path": "/tmp/source-worktree",
                "execution_worktree_path": "/tmp/check-worktree",
                "base_snapshot_id": "candidate-snapshot",
                "execution_snapshot_id": "candidate-snapshot",
                "execution_snapshot_ref": "refs/orchestrator/snapshots/candidate-snapshot",
                "execution_id": f"check-execution-{index}",
                "exit_code": 0 if status == "passed" else 1 if status == "failed" else None,
                "duration_ms": 1,
                "stdout_tail": "",
                "stderr_tail": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "timeout_seconds": 5.0,
                "environment_policy": {
                    "cwd": "/tmp/check-worktree",
                    "env": "inherited",
                    "shell": False,
                    "source_worktree_path": "/tmp/source-worktree",
                    "snapshot_id": "candidate-snapshot",
                    "dependency_provisioning": [],
                },
                "source": "node_command_definition",
                "candidate_record_ids": ["candidate-core-record"],
                "file_state_record_ids": ["file-state-core-record"],
                "evaluated_record_ids": ["candidate-core-record"],
            },
        }
        mutation = mutations.get(index)
        if mutation:
            receipt = deepcopy(receipt)
            for path, value in mutation.items():
                target = receipt
                parts = path.split(".")
                for part in parts[:-1]:
                    target = cast(dict[str, Any], target[part])
                target[parts[-1]] = value
        receipt_position = append("output_record_accepted", receipt)
        receipt_rows.append((receipt_position, check_id, receipt_id))

    edge_rows = [
        (
            "edge-worker-candidate-to-verifier",
            "worker-core",
            "candidate",
            "candidate_under_test",
            "candidate-core-record",
            candidate_position,
        ),
        (
            "edge-requirement-to-verifier",
            "requirement-core",
            "requirement",
            "requirement_1",
            "requirement-core-record",
            requirement_position,
        ),
        *[
            (
                f"edge-{check_id}-to-verifier",
                check_id,
                "check_result",
                f"check_result_{index}",
                receipt_id,
                receipt_position,
            )
            for index, (receipt_position, check_id, receipt_id) in enumerate(receipt_rows, 1)
        ],
    ]
    for edge_id, source, source_port, target_port, record_id, record_position in edge_rows:
        append(
            "edge_created",
            {
                "edge_id": edge_id,
                "from_node_id": source,
                "from_port": source_port,
                "to_node_id": "planner-plan",
                "to_port": target_port,
                "required": True,
                "dependency_type": "input_binding",
            },
        )
        bound_position = len(events) + 1
        append(
            "input_bound",
            {
                "edge_id": edge_id,
                "to_node_id": "planner-plan",
                "to_port": target_port,
                "record_ids": [record_id],
                "record_bound_positions": {record_id: record_position},
                "bound_at_position": bound_position,
            },
        )
    return events


def _all_a_answer(obligation_count: int, evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [
            {
                "obligation": f"o{index}",
                "grade": "A",
                "reason": "Satisfied.",
                "evidence": list(evidence or []),
            }
            for index in range(1, obligation_count + 1)
        ]
    }


def _decision_envelope() -> dict[str, Any]:
    answer = {
        "decision": {
            "disposition": "proceed",
            "implementation_notes": "",
            "evidence": [{"items": ["e1"]}],
        }
    }
    context_hash = f"sha256:{'a' * 64}"
    return {
        "format": "decision-submission-v1",
        "request": {
            "decision_request_id": "request-1",
            "execution_id": "execution-1",
            "routine_snapshot_record_id": "routine-snapshot-record",
            "interaction_contract": "decision-v1",
            "answer_schema_id": "orchestrator.decision.batch",
            "answer_schema_version": 1,
            "answer_schema_sha256": f"sha256:{'b' * 64}",
            "compiler_contract_version": 1,
            "question_context_ref": _context_ref(context_hash),
            "question_context_sha256": context_hash,
            "bound_inputs": [
                {
                    "port": "routine_snapshot",
                    "record_id": "routine-snapshot-record",
                    "record_type": "routine_snapshot",
                    "schema": "RoutineSnapshot",
                    "schema_version": None,
                    "record_position": 2,
                    "bound_at_position": 3,
                }
            ],
        },
        "answer_attempt_id": "attempt-1",
        "answer": answer,
        "answer_sha256": canonical_decision_answer_hash(answer),
    }


def test_routine_selection_is_optional_strict_and_legacy_hash_stable() -> None:
    legacy = _planner_routine()
    selected = _planner_routine(interaction="decision-v1")

    assert legacy.agent_interaction_contract is None
    assert selected.agent_interaction_contract == "decision-v1"
    with pytest.raises(ValidationError, match="agent_interaction_contract"):
        _planner_routine(interaction="decision-v2")

    legacy_snapshot = next(
        event.payload["value"]
        for event in _compile(legacy)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    selected_snapshot = next(
        event.payload["value"]
        for event in _compile(selected)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    assert "agent_interaction_contract" not in legacy_snapshot
    assert legacy_snapshot["content_hash"] == (
        "346f3bd3c71f6eb1ab77a8dd13bd62a8cb162d41d5743c946306fda9d8107a31"
    )
    assert selected_snapshot["agent_interaction_contract"] == "decision-v1"
    assert selected_snapshot["content_hash"] != legacy_snapshot["content_hash"]


def test_compiler_freezes_generated_plan_once_and_rejects_conflicting_claim() -> None:
    routine = _planner_routine(interaction="decision-v1")
    projection = build_projection(_compile(routine))
    declarations = semantic_schema_declarations_view(projection)
    generated = decision_plan_declaration()

    assert list(key for key in declarations if key == (DECISION_PLAN_SCHEMA_ID, 1)) == [
        (DECISION_PLAN_SCHEMA_ID, 1)
    ]
    declaration_schema = declarations[(DECISION_PLAN_SCHEMA_ID, 1)].value.model_dump(mode="json")[
        "json_schema"
    ]
    assert declaration_schema == generated.json_schema

    exact_claim = routine.model_copy(update={"semantic_artifact_schemas": [generated]})
    exact_events = _compile(exact_claim)
    exact_records = [
        event
        for event in exact_events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "semantic_schema_declaration"
        and event.payload["value"]["schema_id"] == DECISION_PLAN_SCHEMA_ID
    ]
    assert len(exact_records) == 1

    conflicting = generated.model_copy(
        update={"json_schema": {"type": "object", "additionalProperties": True}}
    )
    conflict_routine = routine.model_copy(update={"semantic_artifact_schemas": [conflicting]})
    with pytest.raises(ValueError, match="conflicts with generated built-in"):
        _compile(conflict_routine)


def test_legacy_descriptive_check_schema_remains_custom_and_is_not_executable_plan() -> None:
    legacy_schema = {
        "type": "object",
        "properties": {
            "checks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["checks"],
        "additionalProperties": False,
    }
    routine_payload = _planner_routine().model_dump(mode="json")
    routine_payload["semantic_artifact_schemas"] = [
        {
            "schema_id": "legacy.descriptive-plan",
            "version": 1,
            "semantic_role": "implementation_plan",
            "json_schema": legacy_schema,
        }
    ]
    routine = RoutineConfig.model_validate(routine_payload)
    declarations = semantic_schema_declarations_view(build_projection(_compile(routine)))

    assert (
        declarations[("legacy.descriptive-plan", 1)].value.model_dump(mode="json")["json_schema"]
        == legacy_schema
    )
    assert (DECISION_PLAN_SCHEMA_ID, 1) not in declarations


def test_resolver_uses_trusted_contract_stage_and_exact_bound_snapshot() -> None:
    decision_projection = build_projection(_compile(_planner_routine(interaction="decision-v1")))
    resolved = resolve_decision_applicability(decision_projection, "planner-plan")

    assert resolved is not None
    assert resolved.family == "discovery_brief"
    assert resolved.routine_snapshot_record_id == "routine-snapshot-record"
    assert node_payload_view(decision_projection, "planner-plan")["semantic_stage"] == (
        "initial_planning"
    )

    legacy_projection = build_projection(_compile(_planner_routine()))
    assert resolve_decision_applicability(legacy_projection, "planner-plan") is None
    assert decision_recovery_uses_legacy_contract(legacy_projection, "planner-plan") is True
    assert decision_recovery_uses_legacy_contract(decision_projection, "planner-plan") is False
    assert resolve_decision_applicability(decision_projection, "routine-snapshot") is None

    events = _compile(_planner_routine(interaction="decision-v1"))
    malformed = [
        event.model_copy(update={"payload": {**event.payload, "record_ids": ["missing-snapshot"]}})
        if event.event_type == "input_bound"
        and event.payload.get("to_node_id") == "planner-plan"
        and event.payload.get("to_port") == "routine_snapshot"
        else event
        for event in events
    ]
    with pytest.raises(
        DecisionContractResolutionError,
        match="does not reference a routine snapshot",
    ):
        resolve_decision_applicability(build_projection(malformed), "planner-plan")
    assert (
        decision_recovery_uses_legacy_contract(
            build_projection(malformed),
            "planner-plan",
        )
        is False
    )


def test_resolver_rejects_missing_or_impossible_snapshot_authority() -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    without_binding = [
        event
        for event in events
        if not (
            event.event_type == "input_bound"
            and event.payload.get("to_node_id") == "planner-plan"
            and event.payload.get("to_port") == "routine_snapshot"
        )
    ]
    with pytest.raises(DecisionContractResolutionError, match="requires an exact"):
        resolve_decision_applicability(build_projection(without_binding), "planner-plan")

    impossible_positions = [
        event.model_copy(
            update={
                "payload": {
                    **event.payload,
                    "record_bound_positions": {"routine-snapshot-record": 7},
                    "bound_at_position": 6,
                }
            }
        )
        if event.event_type == "input_bound"
        and event.payload.get("to_node_id") == "planner-plan"
        and event.payload.get("to_port") == "routine_snapshot"
        else event
        for event in events
    ]
    with pytest.raises(DecisionContractResolutionError, match="bound position"):
        resolve_decision_applicability(
            build_projection(impossible_positions),
            "planner-plan",
        )

    before_record_position = [
        event.model_copy(update={"payload": {**event.payload, "graph_position": 5}})
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
        else event.model_copy(
            update={
                "payload": {
                    **event.payload,
                    "record_bound_positions": {"routine-snapshot-record": 4},
                    "bound_at_position": 6,
                }
            }
        )
        if event.event_type == "input_bound"
        and event.payload.get("to_node_id") == "planner-plan"
        and event.payload.get("to_port") == "routine_snapshot"
        else event
        for event in events
    ]
    with pytest.raises(DecisionContractResolutionError, match="bound position"):
        resolve_decision_applicability(
            build_projection(before_record_position),
            "planner-plan",
        )

    arbitrary_negative_position = [
        event.model_copy(
            update={
                "payload": {
                    **event.payload,
                    "record_bound_positions": {"routine-snapshot-record": -2},
                    "bound_at_position": 0,
                }
            }
        )
        if event.event_type == "input_bound"
        and event.payload.get("to_node_id") == "planner-plan"
        and event.payload.get("to_port") == "routine_snapshot"
        else event
        for event in events
    ]
    with pytest.raises(DecisionContractResolutionError, match="bound position"):
        resolve_decision_applicability(
            build_projection(arbitrary_negative_position),
            "planner-plan",
        )


def test_resolver_accepts_compiled_sentinel_and_durable_snapshot_positions() -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))

    assert resolve_decision_applicability(build_projection(events), "planner-plan")

    durable_events = []
    for position, event in enumerate(events, start=1):
        payload = dict(event.payload)
        if (
            event.event_type == "output_record_accepted"
            and payload.get("record_id") == "routine-snapshot-record"
        ):
            payload["graph_position"] = position
        if (
            event.event_type == "input_bound"
            and payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "routine_snapshot"
        ):
            payload["bound_at_position"] = position
        durable_events.append(event.model_copy(update={"position": position, "payload": payload}))

    assert resolve_decision_applicability(
        build_projection(durable_events),
        "planner-plan",
    )


@pytest.mark.parametrize("mutated_authority", ["record_port", "edge_from_port"])
def test_resolver_rejects_mismatched_snapshot_record_and_edge_ports(
    mutated_authority: str,
) -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    mismatched = []
    for event in events:
        payload = dict(event.payload)
        if (
            mutated_authority == "record_port"
            and event.event_type == "output_record_accepted"
            and payload.get("record_id") == "routine-snapshot-record"
        ):
            assert payload.get("port") == "snapshot"
            payload["port"] = "routine_snapshot"
        if (
            mutated_authority == "edge_from_port"
            and event.event_type == "edge_created"
            and payload.get("from_node_id") == "routine-snapshot"
            and payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "routine_snapshot"
        ):
            assert payload.get("from_port") == "snapshot"
            payload["from_port"] = "routine_snapshot"
        mismatched.append(event.model_copy(update={"payload": payload}))

    with pytest.raises(
        DecisionContractResolutionError,
        match="snapshot binding authority is inconsistent",
    ):
        resolve_decision_applicability(build_projection(mismatched), "planner-plan")


def test_resolver_rejects_snapshot_bound_through_state_dependency_edge() -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    assert resolve_decision_applicability(build_projection(events), "planner-plan")

    wrong_dependency_type = []
    for event in events:
        payload = dict(event.payload)
        if (
            event.event_type == "edge_created"
            and payload.get("from_node_id") == "routine-snapshot"
            and payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "routine_snapshot"
        ):
            assert payload.get("dependency_type") == "input_binding"
            payload["dependency_type"] = "state_dependency"
        wrong_dependency_type.append(event.model_copy(update={"payload": payload}))

    with pytest.raises(
        DecisionContractResolutionError,
        match="snapshot binding authority is inconsistent",
    ):
        resolve_decision_applicability(
            build_projection(wrong_dependency_type),
            "planner-plan",
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("optional_edge", "binding authority is inconsistent"),
        ("missing_selector", "requires an accepted record selector"),
        ("wrong_selector_id", "does not match the bound record"),
        ("incompatible_selector", "binding authority is inconsistent"),
        ("edge_policy_invalid", "binding authority is inconsistent"),
    ],
)
def test_resolver_rejects_incomplete_edge_selector_and_policy_authority(
    mutation: str,
    expected: str,
) -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    mutated = []
    for event in events:
        payload = dict(event.payload)
        if (
            event.event_type == "edge_created"
            and payload.get("from_node_id") == "routine-snapshot"
            and payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "routine_snapshot"
        ):
            if mutation == "optional_edge":
                payload["required"] = False
            elif mutation == "missing_selector":
                payload.pop("accepted_record_selector", None)
            elif mutation == "wrong_selector_id":
                payload["accepted_record_selector"] = {
                    "record_type": "routine_snapshot",
                    "schema": "RoutineSnapshot",
                    "record_id": "other-snapshot",
                }
            elif mutation == "incompatible_selector":
                payload["accepted_record_selector"] = {
                    "record_type": "run_context",
                    "schema": "RunContext",
                }
            elif mutation == "edge_policy_invalid":
                payload["binding_policy"] = "bind_all"
        mutated.append(event.model_copy(update={"payload": payload}))

    with pytest.raises(DecisionContractResolutionError, match=expected):
        resolve_decision_applicability(build_projection(mutated), "planner-plan")


def test_resolver_uses_canonical_projected_binding_policy() -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    never_rebind = []
    for event in events:
        payload = dict(event.payload)
        if (
            event.event_type == "edge_created"
            and payload.get("from_node_id") == "routine-snapshot"
            and payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "routine_snapshot"
        ):
            payload["binding_policy"] = "never_rebind"
        never_rebind.append(event.model_copy(update={"payload": payload}))

    assert resolve_decision_applicability(
        build_projection(never_rebind),
        "planner-plan",
    )


@pytest.mark.parametrize(
    ("declaration_owner", "field", "value"),
    [
        ("target", "remove", None),
        ("target", "direction", "output"),
        ("target", "schema", "OtherSnapshot"),
        ("target", "required", False),
        ("producer", "remove", None),
        ("producer", "direction", "input"),
        ("producer", "schema", "OtherSnapshot"),
        ("producer", "record_layers", []),
    ],
)
def test_resolver_rejects_malformed_concrete_snapshot_port_declarations(
    declaration_owner: str,
    field: str,
    value: object,
) -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    mutated = []
    for event in events:
        payload = dict(event.payload)
        node_id = payload.get("node_id")
        if event.event_type == "node_created" and (
            (declaration_owner == "target" and node_id == "planner-plan")
            or (declaration_owner == "producer" and node_id == "routine-snapshot")
        ):
            collection = "inputs" if declaration_owner == "target" else "outputs"
            port_name = "routine_snapshot" if declaration_owner == "target" else "snapshot"
            ports = []
            for raw_port in cast(list[dict[str, Any]], payload[collection]):
                port = dict(raw_port)
                if port.get("port") == port_name:
                    if field == "remove":
                        continue
                    port[field] = value
                ports.append(port)
            payload[collection] = ports
        mutated.append(event.model_copy(update={"payload": payload}))

    with pytest.raises(DecisionContractResolutionError, match="snapshot"):
        resolve_decision_applicability(build_projection(mutated), "planner-plan")


def test_resolver_rejects_versioned_routine_snapshot_record() -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    versioned = [
        event.model_copy(update={"payload": {**event.payload, "schema_version": 1}})
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
        else event
        for event in events
    ]

    with pytest.raises(
        DecisionContractResolutionError,
        match="record identity or schema contract",
    ):
        resolve_decision_applicability(build_projection(versioned), "planner-plan")


@pytest.mark.parametrize(
    "semantic_stage",
    [
        "initial_planning",
        "discovery",
        "successor_planning",
        "gap_planning",
        "effectful_batch",
        "corrective_work",
        "plan_verification",
        "final_audit",
    ],
)
@pytest.mark.parametrize("malformed_field", ["kind", "role"])
def test_recognized_decision_stage_with_malformed_kind_or_role_and_no_binding_fails_closed(
    semantic_stage: str,
    malformed_field: str,
) -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    malformed_without_binding = []
    for event in events:
        if (
            event.event_type == "input_bound"
            and event.payload.get("to_node_id") == "planner-plan"
            and event.payload.get("to_port") == "routine_snapshot"
        ):
            continue
        payload = dict(event.payload)
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload[malformed_field] = f"not-a-planner-{malformed_field}"
            payload["semantic_stage"] = semantic_stage
        malformed_without_binding.append(event.model_copy(update={"payload": payload}))

    with pytest.raises(DecisionContractResolutionError, match="decision-capable role"):
        resolve_decision_applicability(
            build_projection(malformed_without_binding),
            "planner-plan",
        )


def test_valid_legacy_target_at_recognized_stage_remains_legacy() -> None:
    events = [
        event.model_copy(
            update={"payload": {**event.payload, "semantic_stage": "initial_planning"}}
        )
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
        else event
        for event in _compile(_planner_routine())
    ]

    assert resolve_decision_applicability(build_projection(events), "planner-plan") is None


def test_valid_legacy_worker_stage_marker_does_not_activate_decision_contract() -> None:
    events = [
        event.model_copy(update={"payload": {**event.payload, "semantic_stage": "effectful_batch"}})
        if event.event_type == "node_created"
        and event.payload.get("node_id") == "worker-step-1-task-1"
        else event
        for event in _compile(_worker_routine())
    ]

    assert (
        resolve_decision_applicability(
            build_projection(events),
            "worker-step-1-task-1",
        )
        is None
    )


def test_selected_decision_contract_rejects_same_unrecognized_worker_role_stage() -> None:
    events = [
        event.model_copy(update={"payload": {**event.payload, "semantic_stage": "effectful_batch"}})
        if event.event_type == "node_created"
        and event.payload.get("node_id") == "worker-step-1-task-1"
        else event
        for event in _compile(_worker_routine(interaction="decision-v1"))
    ]

    with pytest.raises(DecisionContractResolutionError, match="unrecognized role/stage"):
        resolve_decision_applicability(
            build_projection(events),
            "worker-step-1-task-1",
        )


def test_resolver_rejects_decision_snapshot_for_unrecognized_stage() -> None:
    def with_final_gate(events: list[Any]) -> list[Any]:
        return [
            event.model_copy(update={"payload": {**event.payload, "semantic_stage": "final_gate"}})
            if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
            else event
            for event in events
        ]

    unrecognized_stage = with_final_gate(_compile(_planner_routine(interaction="decision-v1")))

    with pytest.raises(DecisionContractResolutionError, match="unrecognized role/stage"):
        resolve_decision_applicability(
            build_projection(unrecognized_stage),
            "planner-plan",
        )
    assert (
        resolve_decision_applicability(
            build_projection(with_final_gate(_compile(_planner_routine()))),
            "planner-plan",
        )
        is None
    )


def test_resolver_rejects_decision_snapshot_for_invalid_target_role() -> None:
    def with_invalid_target_role(events: list[Any]) -> list[Any]:
        return [
            event.model_copy(update={"payload": {**event.payload, "role": "reviewer"}})
            if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
            else event
            for event in events
        ]

    with pytest.raises(
        DecisionContractResolutionError,
        match="canonical routine snapshot input",
    ):
        resolve_decision_applicability(
            build_projection(
                with_invalid_target_role(_compile(_planner_routine(interaction="decision-v1")))
            ),
            "planner-plan",
        )

    with pytest.raises(
        DecisionContractResolutionError,
        match="canonical routine snapshot input",
    ):
        resolve_decision_applicability(
            build_projection(with_invalid_target_role(_compile(_planner_routine()))),
            "planner-plan",
        )


def test_resolver_rejects_snapshot_producer_role_not_allowed_by_contract() -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    invalid_producer = [
        event.model_copy(update={"payload": {**event.payload, "role": "planner"}})
        if event.event_type == "node_created" and event.payload.get("node_id") == "routine-snapshot"
        else event
        for event in events
    ]

    with pytest.raises(
        DecisionContractResolutionError,
        match="snapshot binding authority is inconsistent",
    ):
        resolve_decision_applicability(
            build_projection(invalid_producer),
            "planner-plan",
        )

    assert (
        resolve_decision_applicability(
            build_projection(_compile(_planner_routine())),
            "planner-plan",
        )
        is None
    )


def test_resolver_rejects_negative_durable_snapshot_graph_position() -> None:
    events = _compile(_planner_routine(interaction="decision-v1"))
    invalid_durable_events = []
    for position, event in enumerate(events, start=1):
        payload = dict(event.payload)
        if (
            event.event_type == "output_record_accepted"
            and payload.get("record_id") == "routine-snapshot-record"
        ):
            payload["graph_position"] = -1
        if (
            event.event_type == "input_bound"
            and payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "routine_snapshot"
        ):
            payload["bound_at_position"] = position
        invalid_durable_events.append(
            event.model_copy(update={"position": position, "payload": payload})
        )

    with pytest.raises(DecisionContractResolutionError, match="bound position"):
        resolve_decision_applicability(
            build_projection(invalid_durable_events),
            "planner-plan",
        )


def test_strict_decision_models_accept_contract_shapes_and_reject_internal_fields() -> None:
    assert (
        DiscoveryBrief.model_validate(
            {"questions": ["Which parser owns this?"], "rationale": "Ownership is unclear."}
        ).focus
        == []
    )
    assert ImplementationPlan.model_validate(_valid_plan()).batches[1].depends_on == ["core"]
    assert (
        TypeAdapter(BatchDecision)
        .validate_python({"disposition": "proceed", "implementation_notes": ""})
        .disposition
        == "proceed"
    )
    assert (
        TypeAdapter(CorrectionDecision)
        .validate_python(
            {"disposition": "no_gap", "reason": "Evidence is sufficient.", "evidence": ["e1"]}
        )
        .disposition
        == "no_gap"
    )
    assert (
        VerificationDecision.model_validate(
            {"findings": [{"obligation": "o1", "grade": "A", "reason": "Covered.", "evidence": []}]}
        )
        .findings[0]
        .grade
        == "A"
    )
    assert (
        TypeAdapter(WorkResult)
        .validate_python({"status": "ready", "summary": "Candidate is ready."})
        .status
        == "ready"
    )

    with pytest.raises(ValidationError, match="extra_forbidden"):
        TypeAdapter(BatchDecision).validate_python(
            {
                "disposition": "proceed",
                "implementation_notes": "",
                "base_graph_position": 9,
            }
        )
    with pytest.raises(ValidationError, match="non-whitespace"):
        DiscoveryBrief.model_validate({"questions": ["  "], "rationale": "why"})
    with pytest.raises(ValidationError, match="literal_error"):
        VerificationDecision.model_validate(
            {"findings": [{"obligation": "o1", "grade": "pass", "reason": "x", "evidence": []}]}
        )


@pytest.mark.parametrize(
    "mutation, message",
    [
        (
            lambda plan: plan["batches"][1].update({"key": "core"}),
            "unique keys",
        ),
        (
            lambda plan: plan["batches"][1].update({"depends_on": ["missing"]}),
            "unknown dependencies",
        ),
        (
            lambda plan: plan["batches"][0].update({"depends_on": ["api"]}),
            "dependency cycle",
        ),
        (
            lambda plan: plan["batches"][0].update({"checks": []}),
            "too_short",
        ),
        (
            lambda plan: plan["batches"][0].update({"checks": ["descriptive prose"]}),
            "model_type",
        ),
        (
            lambda plan: plan["batches"][0].update(
                {"checks": [{"name": "not executable", "command_definition": {}}]}
            ),
            "requires non-empty argv",
        ),
    ],
)
def test_plan_rejects_invalid_topology_and_non_executable_checks(
    mutation: Any, message: str
) -> None:
    plan = _valid_plan()
    mutation(plan)
    with pytest.raises(ValidationError, match=message):
        ImplementationPlan.model_validate(plan)


def test_check_choice_preserves_authoritative_legacy_argv_semantics() -> None:
    plan = _valid_plan()
    plan["batches"][0]["checks"] = [
        {"name": "legacy argv", "command_definition": {"argv": ["tool", ""]}}
    ]

    parsed = ImplementationPlan.model_validate(plan)

    assert parsed.batches[0].checks[0].command_definition == {"argv": ["tool", ""]}


def test_check_owner_drives_plan_declaration_and_submit_schema() -> None:
    check_schema = reliable_plan_check_decision_tool_schema()
    plan_schema = decision_plan_declaration().json_schema
    generated_check = plan_schema["$defs"]["CheckChoice"]

    assert generated_check == {**check_schema, "title": "CheckChoice"}
    assert generated_check["properties"]["command_definition"]["additionalProperties"] is True
    assert generated_check["oneOf"] == [
        {"required": ["command_binding"]},
        {"required": ["command_definition"]},
    ]
    contract = SubmissionContract(
        outputs=(
            SubmissionOutputContract(
                port="semantic_artifact",
                schema_name="SemanticArtifact",
                semantic_schema_id=DECISION_PLAN_SCHEMA_ID,
                semantic_schema_version=1,
                semantic_role="implementation_plan",
                content_json_schema=plan_schema,
            ),
        )
    )
    submit_schema = submission_tool_input_schema(contract)
    embedded_plan = submit_schema["properties"]["outputs"]["properties"]["semantic_artifact"]
    assert "$defs" not in embedded_plan
    assert '"$ref"' not in str(embedded_plan)
    assert embedded_plan["properties"]["batches"]["items"]["title"] == "Batch"


def test_tagged_envelope_and_explicit_legacy_decoder_do_not_guess_shapes() -> None:
    payload = _decision_envelope()
    parsed = DecisionSubmissionEnvelope.model_validate(payload)
    assert parsed.model_dump(mode="json", by_alias=True) == payload
    assert decode_submission_payload(payload, interaction_contract="decision-v1") == parsed

    legacy_payload = {"output_records": [{"record_id": "legacy-record"}], "complete": True}
    legacy = decode_submission_payload(legacy_payload, interaction_contract="legacy")
    assert legacy.output_records == ({"record_id": "legacy-record"},)

    with pytest.raises(ValidationError, match="literal_error"):
        DecisionSubmissionEnvelope.model_validate({**payload, "format": "output_records"})
    with pytest.raises(ValidationError, match="answer_sha256 does not match"):
        DecisionSubmissionEnvelope.model_validate(
            {**payload, "answer_sha256": f"sha256:{'c' * 64}"}
        )
    partial_request = dict(payload["request"])
    partial_input = dict(partial_request["bound_inputs"][0])
    partial_input.pop("schema_version")
    partial_request["bound_inputs"] = [partial_input]
    with pytest.raises(ValidationError, match="schema_version"):
        DecisionSubmissionEnvelope.model_validate({**payload, "request": partial_request})
    unknown_compiler = {**payload["request"], "compiler_contract_version": 2}
    with pytest.raises(ValidationError, match="literal_error"):
        DecisionSubmissionEnvelope.model_validate({**payload, "request": unknown_compiler})
    with pytest.raises(ValidationError, match="output_records"):
        decode_submission_payload(payload, interaction_contract="legacy")
    with pytest.raises(ValueError, match="unknown agent interaction contract"):
        decode_submission_payload(
            payload,
            interaction_contract=cast(Any, "decision-v2"),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("port", "other", "exactly one routine snapshot port row"),
        ("record_id", "other-snapshot", "invalid record contract"),
        ("record_type", "other", "invalid record contract"),
        ("schema", "OtherSnapshot", "invalid record contract"),
        ("schema_version", 1, "invalid record contract"),
    ],
)
def test_submission_request_rejects_wrong_snapshot_bound_row(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _decision_envelope()
    request = dict(payload["request"])
    snapshot_row = dict(request["bound_inputs"][0])
    snapshot_row[field] = value
    request["bound_inputs"] = [snapshot_row]

    with pytest.raises(ValidationError, match=message):
        DecisionSubmissionEnvelope.model_validate({**payload, "request": request})


def test_submission_request_rejects_two_snapshot_port_rows() -> None:
    payload = _decision_envelope()
    request = dict(payload["request"])
    snapshot_row = dict(request["bound_inputs"][0])
    request["bound_inputs"] = [
        snapshot_row,
        {**snapshot_row, "record_id": "other-snapshot"},
    ]

    with pytest.raises(ValidationError, match="exactly one routine snapshot port row"):
        DecisionSubmissionEnvelope.model_validate({**payload, "request": request})


def test_submission_request_allows_snapshot_record_on_another_port() -> None:
    payload = _decision_envelope()
    request = dict(payload["request"])
    snapshot_row = dict(request["bound_inputs"][0])
    request["bound_inputs"] = [
        snapshot_row,
        {**snapshot_row, "port": "supporting_context"},
    ]

    parsed = DecisionSubmissionEnvelope.model_validate({**payload, "request": request})

    assert [item.port for item in parsed.request.bound_inputs] == [
        "routine_snapshot",
        "supporting_context",
    ]


def test_submission_answer_is_deeply_immutable_and_dumps_canonically() -> None:
    payload = _decision_envelope()
    parsed = DecisionSubmissionEnvelope.model_validate(payload)
    nested_answer = cast(Any, parsed.answer["decision"])

    with pytest.raises(TypeError):
        nested_answer["disposition"] = "revise"
    nested_items = cast(Any, nested_answer["evidence"])[0]["items"]
    with pytest.raises(AttributeError):
        nested_items.append("e2")
    assert parsed.model_dump(mode="json", by_alias=True) == payload
    assert canonical_decision_answer_hash(parsed.answer) == payload["answer_sha256"]


def test_submission_invocation_metadata_stays_outside_model_schema() -> None:
    invocation = SubmissionInvocation(
        execution_id="execution-1",
        answer_attempt_id="attempt-1",
        transport_channel="codex-dynamic-tool",
        transport_session_id="thread-1",
        transport_request_id="call-1",
        arguments={"outputs": {"decision": {"status": "ready", "summary": "Ready."}}},
    )
    assert invocation.answer_attempt_id == "attempt-1"

    schema = submission_tool_input_schema(
        SubmissionContract(
            outputs=(
                SubmissionOutputContract(
                    port="decision",
                    schema_name="WorkResult",
                    content_json_schema=TypeAdapter(WorkResult).json_schema(),
                ),
            )
        )
    )
    encoded = str(schema)
    assert "answer_attempt_id" not in encoded
    assert "transport_session_id" not in encoded
    assert set(schema) == {"type", "properties", "required", "additionalProperties"}


def test_successor_context_and_compiler_bind_exact_inputs_deterministically() -> None:
    projection = _decision_successor_projection()
    resolved = resolve_batch_decision_context(projection, "planner-plan")

    assert resolved.selected_batch.key == "core"
    assert dict(resolved.requirement_aliases.object_items()) == {"r1": "REQ-1"}
    assert [item.port for item in resolved.bound_inputs] == [
        "routine_snapshot",
        "semantic_artifact",
        "verification_report",
        "requirement_1",
    ]
    question = resolved.protected_question_context()
    assert question["planning_horizon"] == 1
    assert question["remaining_horizons"] == 1
    assert question["check_policy"]["selected_batch_checks"] == [
        {"name": "unit", "command_definition": {"argv": ["pytest"]}}
    ]

    first = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="request-exact-1",
        base_graph_position=99,
        answer={"disposition": "proceed", "implementation_notes": "Keep scope exact."},
    )
    replay = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="request-exact-1",
        base_graph_position=99,
        answer={"disposition": "proceed", "implementation_notes": "Keep scope exact."},
    )

    assert first == replay
    assert first.patch_id.startswith("decision-patch-")
    assert first.decision_record.value.consequence_patch_id == first.patch_id
    assert first.decision_record.value.bound_input_record_ids == [
        item.record_id for item in resolved.bound_inputs
    ]
    created = [op["node"] for op in first.ops if op.get("op") == "create_node"]
    assert {node.get("kind") for node in created} >= {"worker", "verifier", "check"}
    assert all(
        node.get("declared_batch_id") == "core"
        for node in created
        if node.get("semantic_stage") == "effectful_batch"
    )
    implementation_worker = next(
        node
        for node in created
        if node.get("kind") == "worker" and node.get("semantic_stage") == "effectful_batch"
    )
    assert implementation_worker["implementation_notes"] == "Keep scope exact."
    generated_verifiers = [node for node in created if node.get("kind") == "verifier"]
    assert generated_verifiers
    for verifier in generated_verifiers:
        assert verifier["acceptance"] == ["The core works."]
        assert any(item["port"] == "routine_snapshot" for item in verifier["inputs"])
        assert any(item["port"] == "decision" for item in verifier["outputs"])
    assert {"planner-plan", "REQ-1", "v1"} <= set(first.read_set)


@pytest.mark.parametrize(
    ("scenario", "answer", "cancel_requested", "verification_outcome", "expected"),
    [
        (
            "proceed_no_cancel",
            {"disposition": "proceed", "implementation_notes": "Keep scope exact."},
            False,
            None,
            ("proceed", "completed", 0),
        ),
        (
            "proceed_cancel",
            {"disposition": "proceed", "implementation_notes": "Keep scope exact."},
            True,
            None,
            ("proceed", "completed", 0),
        ),
        (
            "revise_plan_nonfinal_pass_no_cancel",
            {
                "disposition": "revise_plan",
                "reason": "Add the missing bounded review point.",
                "amendment": {
                    "refinements": [
                        {"batch": "core", "review_points": ["Review the bounded core."]}
                    ]
                },
            },
            False,
            "passed",
            ("revise_plan", "completed", 1),
        ),
        (
            "revise_plan_nonfinal_pass_cancel",
            {
                "disposition": "revise_plan",
                "reason": "Add the missing bounded review point.",
                "amendment": {
                    "refinements": [
                        {"batch": "core", "review_points": ["Review the bounded core."]}
                    ]
                },
            },
            True,
            "passed",
            ("revise_plan", "completed", 1),
        ),
        (
            "revise_plan_nonfinal_fail",
            {
                "disposition": "revise_plan",
                "reason": "Add the missing bounded review point.",
                "amendment": {
                    "refinements": [
                        {"batch": "core", "review_points": ["Review the bounded core."]}
                    ]
                },
            },
            False,
            "failed",
            ("revise_plan", "completed", 1),
        ),
        (
            "revise_plan_final_pass",
            {
                "disposition": "revise_plan",
                "reason": "Add the missing bounded review point.",
                "amendment": {
                    "refinements": [
                        {"batch": "core", "review_points": ["Review the bounded core."]}
                    ]
                },
            },
            False,
            "passed",
            ("revise_plan", "completed", 1),
        ),
        (
            "blocked",
            {
                "disposition": "blocked",
                "blocker": {
                    "reason": "A required owner decision is unavailable.",
                    "needed_information": ["Choose the supported core contract."],
                    "evidence": [],
                },
            },
            False,
            None,
            ("blocked", "failed", 0),
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and "_" in value else None,
)
def test_decision_runtime_variants_share_pure_answer_compilation_before_finalization(
    scenario: str,
    answer: dict[str, Any],
    cancel_requested: bool,
    verification_outcome: str | None,
    expected: tuple[str, str, int],
) -> None:
    """Runtime races and later verification never leak into staged answer compilation."""
    compiled = compile_batch_decision(
        _decision_successor_projection(),
        node_id="planner-plan",
        decision_request_id=f"decision-runtime-{scenario}",
        base_graph_position=99,
        answer=answer,
    )

    disposition, completion_state, semantic_count = expected
    assert compiled.disposition == disposition
    assert compiled.completion_state == completion_state
    assert len(compiled.semantic_records) == semantic_count
    assert compiled.decision_record.value.answer["disposition"] == answer["disposition"]
    assert "cancel_requested" not in compiled.decision_record.value.answer
    assert "verification_outcome" not in compiled.decision_record.value.answer
    assert cancel_requested is (
        scenario.endswith("_cancel") and not scenario.endswith("_no_cancel")
    )
    assert verification_outcome == (
        "failed" if scenario.endswith("fail") else "passed" if "pass" in scenario else None
    )


def test_typed_verifier_requires_exact_passing_mandatory_receipts() -> None:
    projection = build_projection(_verification_events())
    resolved = resolve_verification_decision_context(projection, "planner-plan")

    assert [item.source_field for item in resolved.obligation_table] == [
        "value.text",
        "acceptance",
        "rubric",
    ]
    assert dict(resolved.evidence_aliases.object_items()) == {
        "e1": "candidate-core-record",
        "e2": "check-core-record-1",
    }
    assert [item.record_id for item in resolved.mandatory_check_receipts] == ["check-core-record-1"]

    compiled = compile_verification_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="verification-request",
        base_graph_position=max(item.position for item in _verification_events()),
        answer=_all_a_answer(len(resolved.obligation_table), ["e1", "e2"]),
    )

    assert compiled.verification_record is not None
    assert compiled.verification_record.outcome == "passed"
    assert compiled.verification_record.evaluated_record_ids == [
        "check-core-record-1",
        "requirement-core-record",
        "candidate-core-record",
        "file-state-core-record",
    ]
    assert {"requirement-core-record", "REQ-CORE", "v1", "requirement-core"} <= set(
        compiled.read_set
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"candidate_id": "foreign-candidate"}, "candidate"),
        ({"producer_node_id": "foreign-check"}, "producer"),
        ({"value.command_id": "different-command"}, "command identity"),
        ({"value.command": {"id": "command-core-1", "argv": ["false"]}}, "command definition"),
        ({"value.command_binding": "dynamic_feature_hidden_oracle"}, "command binding"),
        ({"value.timeout_seconds": 6.0}, "timeout"),
        ({"value.execution_snapshot_id": "other-snapshot"}, "snapshot"),
        ({"value.execution_snapshot_ref": "refs/orchestrator/snapshots/other"}, "snapshot ref"),
        (
            {
                "value.environment_policy": {
                    "cwd": "/tmp/check-worktree",
                    "env": "custom",
                    "shell": False,
                    "source_worktree_path": "/tmp/source-worktree",
                    "snapshot_id": "candidate-snapshot",
                    "dependency_provisioning": [],
                }
            },
            "environment policy",
        ),
        ({"value.source": "foreign_policy"}, "source policy"),
    ],
)
def test_typed_verifier_rejects_foreign_or_mismatched_receipt(
    mutation: dict[str, Any], message: str
) -> None:
    projection = build_projection(_verification_events(receipt_mutations={1: mutation}))

    with pytest.raises(DecisionContractResolutionError, match=message):
        resolve_verification_decision_context(projection, "planner-plan")


@pytest.mark.parametrize("status", ["failed", "timeout"])
def test_all_a_verifier_answer_cannot_override_nonpassing_receipt(status: str) -> None:
    projection = build_projection(_verification_events(receipt_statuses=(status,)))
    resolved = resolve_verification_decision_context(projection, "planner-plan")

    compiled = compile_verification_decision(
        projection,
        node_id="planner-plan",
        decision_request_id=f"verification-{status}",
        base_graph_position=999,
        answer=_all_a_answer(len(resolved.obligation_table)),
    )

    assert compiled.verification_record is not None
    assert compiled.verification_record.outcome == "failed"
    assert compiled.verification_record.evaluated_record_ids == [
        "check-core-record-1",
        "requirement-core-record",
        "candidate-core-record",
        "file-state-core-record",
    ]


def test_verifier_rejects_incomplete_or_stale_mandatory_receipt_coverage() -> None:
    incomplete = build_projection(_verification_events(declare_extra_check=True))
    with pytest.raises(DecisionContractResolutionError, match="missing mandatory check receipt"):
        resolve_verification_decision_context(incomplete, "planner-plan")

    events = _verification_events()
    stale = deepcopy(
        next(
            item
            for item in events
            if item.event_type == "output_record_accepted"
            and item.payload.get("record_id") == "check-core-record-1"
        )
    )
    stale_payload = deepcopy(stale.payload)
    stale_payload["record_id"] = "check-core-record-newer"
    stale_payload["graph_position"] = len(events) + 1
    events.append(stale.model_copy(update={"position": len(events) + 1, "payload": stale_payload}))
    with pytest.raises(DecisionContractResolutionError, match="stale"):
        resolve_verification_decision_context(build_projection(events), "planner-plan")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "omits obligation aliases"),
        ("unknown-obligation", "unknown obligation aliases"),
        ("unknown-evidence", "unknown evidence alias"),
    ],
)
def test_typed_verifier_rejects_incomplete_or_unknown_answer_findings(
    mutation: str, message: str
) -> None:
    projection = build_projection(_verification_events())
    resolved = resolve_verification_decision_context(projection, "planner-plan")
    answer = _all_a_answer(len(resolved.obligation_table), ["e1"])
    if mutation == "missing":
        answer["findings"] = answer["findings"][:-1]
    elif mutation == "unknown-obligation":
        answer["findings"][0]["obligation"] = "o99"
    else:
        answer["findings"][0]["evidence"] = ["e99"]

    with pytest.raises((ValidationError, ValueError), match=message):
        compile_verification_decision(
            projection,
            node_id="planner-plan",
            decision_request_id=f"invalid-{mutation}",
            base_graph_position=len(_verification_events()),
            answer=answer,
        )


def test_failed_report_preserves_every_mandatory_receipt_across_replay() -> None:
    events = _verification_events(receipt_statuses=("failed", "timeout"))
    projection = build_projection(events)
    resolved = resolve_verification_decision_context(projection, "planner-plan")
    compiled = compile_verification_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="verification-multiple-failures",
        base_graph_position=len(events),
        answer=_all_a_answer(len(resolved.obligation_table)),
    )

    assert compiled.verification_record is not None
    assert compiled.verification_record.outcome == "failed"
    assert compiled.verification_record.evaluated_record_ids == [
        "check-core-record-1",
        "check-core-record-2",
        "requirement-core-record",
        "candidate-core-record",
        "file-state-core-record",
    ]
    replayed = build_projection(events)
    assert resolve_verification_decision_context(replayed, "planner-plan") == resolved


def test_final_audit_uses_acceptance_receipt_candidate_not_all_prior_batch_candidates() -> None:
    raw_events = _verification_events()
    events: list[Any] = []
    for item in raw_events:
        payload = deepcopy(item.payload)
        if item.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload["semantic_stage"] = "final_audit"
            payload["inputs"] = [
                {
                    "port": "routine_snapshot",
                    "direction": "input",
                    "schema": "RoutineSnapshot",
                    "required": True,
                },
                {
                    "port": "verification_report_batch_1",
                    "direction": "input",
                    "schema": "VerificationReport",
                    "required": True,
                },
                {
                    "port": "verification_report_batch_2",
                    "direction": "input",
                    "schema": "VerificationReport",
                    "required": True,
                },
                {
                    "port": "dynamic_feature_acceptance",
                    "direction": "input",
                    "schema": "CheckResult",
                    "required": True,
                },
            ]
        if item.event_type == "node_created" and payload.get("node_id") == "check-core-1":
            payload["semantic_stage"] = "final_acceptance"
        if payload.get("edge_id") in {
            "edge-worker-candidate-to-verifier",
            "edge-requirement-to-verifier",
        }:
            continue
        if payload.get("to_node_id") == "planner-plan" and payload.get("to_port") in {
            "candidate_under_test",
            "requirement_1",
        }:
            continue
        if payload.get("edge_id") == "edge-check-core-1-to-verifier":
            payload["to_port"] = "dynamic_feature_acceptance"
        events.append(item.model_copy(update={"position": len(events) + 1, "payload": payload}))

    def append(kind: str, payload: dict[str, Any]) -> int:
        position = len(events) + 1
        if kind == "output_record_accepted":
            payload = {**payload, "graph_position": position}
        events.append(graph_event(kind, payload, position=position))
        return position

    for index, candidate_id in enumerate(("candidate-old", "candidate-core-record"), 1):
        verifier_id = f"verifier-batch-{index}"
        record_id = f"verification-batch-{index}"
        append(
            "node_created",
            {
                "node_id": verifier_id,
                "kind": "verifier",
                "role": "verifier",
                "semantic_stage": "effectful_batch",
            },
        )
        record_position = append(
            "output_record_accepted",
            {
                "record_id": record_id,
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": verifier_id,
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": candidate_id,
                "candidate_record_id": candidate_id,
                "candidate_record_ids": [candidate_id],
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": []},
                "evaluated_record_ids": [candidate_id],
            },
        )
        edge_id = f"edge-{verifier_id}-to-final-audit"
        target_port = f"verification_report_batch_{index}"
        append(
            "edge_created",
            {
                "edge_id": edge_id,
                "from_node_id": verifier_id,
                "from_port": "verification_report",
                "to_node_id": "planner-plan",
                "to_port": target_port,
                "required": True,
            },
        )
        append(
            "input_bound",
            {
                "edge_id": edge_id,
                "to_node_id": "planner-plan",
                "to_port": target_port,
                "record_ids": [record_id],
                "record_bound_positions": {record_id: record_position},
                "bound_at_position": len(events) + 1,
            },
        )

    projection = build_projection(events)
    resolved = resolve_verification_decision_context(projection, "planner-plan")

    assert resolved.semantic_stage == "final_audit"
    assert resolved.candidate_record_ids == ("candidate-core-record",)
    assert resolved.mandatory_check_receipts[0].record_id == "check-core-record-1"
    compiled = compile_verification_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="final-audit-request",
        base_graph_position=len(events),
        answer=_all_a_answer(len(resolved.obligation_table), ["e1", "e2", "e3"]),
    )
    assert compiled.verification_record is not None
    assert compiled.verification_record.candidate_record_ids == ["candidate-core-record"]
    assert {
        "verification-batch-1",
        "verification-batch-2",
        "check-core-record-1",
    }.issubset(compiled.verification_record.evaluated_record_ids)


def test_verifier_minimum_grades_follow_bound_requirement_and_review_policy() -> None:
    events = _verification_events()
    projection = build_projection(events)
    resolved = resolve_verification_decision_context(projection, "planner-plan")

    assert [item.minimum_grade for item in resolved.obligation_table] == ["A", "A", "A"]
    answer = _all_a_answer(len(resolved.obligation_table))
    answer["findings"][0]["grade"] = "C"
    compiled = compile_verification_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="critical-cannot-pass-with-c",
        base_graph_position=len(events),
        answer=answer,
    )
    assert compiled.verification_record is not None
    assert compiled.verification_record.outcome == "failed"


def test_verification_report_links_separate_versioned_judgment_artifact() -> None:
    events = _verification_events()
    projection = build_projection(events)
    resolved = resolve_verification_decision_context(projection, "planner-plan")
    compiled = compile_verification_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="judgment-artifact-request",
        base_graph_position=len(events),
        answer=_all_a_answer(len(resolved.obligation_table), ["e1"]),
    )

    assert len(compiled.semantic_records) == 1
    judgment = compiled.semantic_records[0]
    assert judgment.value.semantic_role == "verification_judgment"
    assert judgment.value.schema_id == "orchestrator.reliable-plan.verification-judgment"
    assert judgment.value.schema_version == 1
    assert judgment.value.content is not None
    assert judgment.value.content["obligations"] == [
        item.model_dump(mode="json") for item in resolved.obligation_table
    ]
    assert compiled.verification_record is not None
    assert compiled.verification_record.value.judgment_artifact_record_id == judgment.record_id
    assert compiled.verification_record.evidence == {
        "judgment_artifact_record_id": judgment.record_id
    }


def test_successor_requirement_aliases_keep_numeric_order_past_nine() -> None:
    projection = _decision_successor_projection(requirement_count=10)

    resolved = resolve_batch_decision_context(projection, "planner-plan")

    assert dict(resolved.requirement_aliases.object_items()) == {
        f"r{index}": f"REQ-{index}" for index in range(1, 11)
    }
    assert [item.port for item in resolved.bound_inputs[-10:]] == [
        f"requirement_{index}" for index in range(1, 11)
    ]


def test_decision_compiler_uses_bound_records_despite_duplicate_logical_candidates() -> None:
    projection = _decision_successor_projection()
    duplicate_events = [
        graph_event(
            "output_record_accepted",
            {
                "record_id": "duplicate-plan",
                "record_kind": "graph_record",
                "record_type": "semantic_artifact",
                "producer_node_id": "other-discovery",
                "producer_port": "semantic_artifact",
                "port": "semantic_artifact",
                "schema": "SemanticArtifact",
                "schema_version": 1,
                "graph_position": 500,
                "value": {
                    "semantic_role": "implementation_plan",
                    "schema_id": DECISION_PLAN_SCHEMA_ID,
                    "schema_version": 1,
                    "content": _valid_plan(),
                    "provenance": {"source": "duplicate"},
                    "source_record_ids": [],
                    "requirement_ids": ["REQ-1"],
                    "task_region_id": "duplicate",
                    "validation_status": "validated",
                    "authority_status": "accepted",
                },
            },
            position=500,
        ),
        graph_event(
            "output_record_accepted",
            {
                "record_id": "duplicate-requirement",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "other-requirement",
                "port": "requirement",
                "schema": "RequirementRecord",
                "graph_position": 501,
                "value": {
                    "id": "REQ-1",
                    "text": "Unbound duplicate.",
                    "version": "other",
                },
            },
            position=501,
        ),
    ]
    for event in duplicate_events:
        projection = reduce_event(projection, event)

    compiled = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="exact-bound-records",
        base_graph_position=501,
        answer={"disposition": "proceed", "implementation_notes": ""},
    )

    requirement_selectors = [
        op["accepted_record_selector"]
        for op in compiled.ops
        if op.get("op") == "create_edge" and op.get("to_port") == "requirement_1"
    ]
    assert requirement_selectors
    assert all(item["record_id"] == "requirement-record-1" for item in requirement_selectors)


def test_successor_compiler_rejects_empty_plan_amendment() -> None:
    projection = _decision_successor_projection()

    with pytest.raises((ValidationError, ValueError)):
        compile_batch_decision(
            projection,
            node_id="planner-plan",
            decision_request_id="request-exact-1",
            base_graph_position=99,
            answer={"disposition": "revise_plan", "reason": "Needs work", "amendment": {}},
        )


def _apply_decision_boundary(
    projection: Any,
    command_type: str,
    payload: dict[str, Any],
    *,
    position: int,
    events: list[Any] | None = None,
) -> list[Any]:
    return apply_command(
        projection,
        events or [],
        command_type,
        payload,
        GraphCommandContext(run_id="run-1", current_graph_position=position),
        FakeClock(),
        SequentialIdGenerator(),
    )


def _reduce_planned_events(projection: Any, planned: list[Any], start: int) -> Any:
    for offset, item in enumerate(planned, start=1):
        projection = reduce_event(
            projection,
            item.model_copy(update={"position": start + offset}),
        )
    return projection


@pytest.mark.parametrize("phase", ["stage", "finalize"])
@pytest.mark.parametrize("requirement_id", ["REQ-1", "requirement-record-1", "REQ-UNRELATED"])
def test_work_result_boundaries_reject_changed_read_authority(
    phase: str, requirement_id: str
) -> None:
    projection = _work_result_projection()
    root = node_payload_view(projection, "root")
    assert root is not None
    cache_hash = cast(str, root["cache_authority_hash"])
    boundary_hash = boundary_manifest_hash("a" * 40, [], cache_authority_hash=cache_hash)
    identity = {
        "execution_id": "work-execution",
        "node_id": "worker-core",
        "lease_id": "work-lease",
        "lease_generation": 1,
    }
    projection = reduce_event(
        projection,
        graph_event(
            "lease_granted",
            {
                "execution_id": "work-execution",
                "node_id": "worker-core",
                "lease_id": "work-lease",
                "generation": 1,
                "base_snapshot_id": "work-base",
                "cache_authority_hash": cache_hash,
            },
            position=100,
        ),
    )
    baseline = _apply_decision_boundary(
        projection,
        "record_runner_baseline",
        {
            **identity,
            "lease_base_snapshot_id": "work-base",
            "baseline_snapshot_id": "work-base",
            "baseline_snapshot_ref": "refs/orchestrator/snapshots/work-base",
            "baseline_commit_sha": "a" * 40,
            "baseline_tree_sha": "a" * 40,
            "entries": [],
            "boundary_hash": boundary_hash,
            "cache_authority_hash": cache_hash,
        },
        position=100,
    )
    assert baseline[0].event_type == "runner_baseline_recorded", baseline
    projection = _reduce_planned_events(projection, baseline, 100)
    resolved = resolve_work_result_context(projection, "worker-core")
    question_context = resolved.protected_question_context()
    context_hash, context_size = callback_payload_identity(question_context)
    answer = {
        "decision": {
            "status": "blocked",
            "blocker": {
                "reason": "Fixture unavailable.",
                "needed_information": ["Fixture path"],
                "evidence": [],
            },
        }
    }
    compiled = compile_work_result(
        projection,
        node_id="worker-core",
        decision_request_id="work-request",
        base_graph_position=101,
        answer=answer["decision"],
    )
    records = [compiled.decision_record.model_dump(mode="json", by_alias=True)]
    request = DecisionSubmissionRequest(
        decision_request_id="work-request",
        execution_id="work-execution",
        routine_snapshot_record_id=resolved.routine_snapshot_record_id,
        interaction_contract="decision-v1",
        answer_schema_id="orchestrator.reliable-plan.work-result",
        answer_schema_version=1,
        answer_schema_sha256=work_result_schema_sha256(),
        compiler_contract_version=1,
        question_context_ref={**_context_ref(context_hash), "size_bytes": context_size},
        question_context_sha256=context_hash,
        bound_inputs=resolved.bound_inputs,
    )
    envelope = DecisionSubmissionEnvelope(
        format="decision-submission-v1",
        request=request,
        answer_attempt_id="work-delivery",
        answer=answer,
        answer_sha256=canonical_decision_answer_hash(answer),
    ).model_dump(mode="json", by_alias=True)
    stage_payload = {
        **identity,
        "base_snapshot_id": "work-base",
        "observed_graph_position": 101,
        "idempotency_key": "work-request:submit",
        "payload": envelope,
        "payload_hash": callback_payload_identity(envelope)[0],
        "is_mutating": True,
        "complete_node": True,
        "new_state": "failed",
        "staged_snapshot_id": "work-staged",
        "staged_snapshot_ref": "refs/orchestrator/snapshots/work-staged",
        "staged_commit_sha": "a" * 40,
        "staged_tree_sha": "a" * 40,
        "boundary_hash": boundary_hash,
        "boundary_entries": [],
        "cache_authority_hash": cache_hash,
        "controller_output_records": records,
    }
    revision = graph_event(
        "requirement_revision_recorded",
        {
            "requirement_id": requirement_id,
            "version_id": "revised-v2",
            "node_id": "requirement-1" if requirement_id != "REQ-UNRELATED" else "other-node",
        },
        position=102 if phase == "stage" else 104,
    )
    if phase == "stage":
        result = _apply_decision_boundary(
            projection,
            "stage_runner_submission",
            stage_payload,
            position=102,
            events=[revision],
        )
    else:
        staged_events = _apply_decision_boundary(
            projection, "stage_runner_submission", stage_payload, position=101
        )
        assert staged_events[0].event_type == "runner_submission_staged", staged_events
        projection = _reduce_planned_events(projection, staged_events, 101)
        final_payload = {
            **identity,
            "final_snapshot_id": "work-final",
            "final_snapshot_ref": "refs/orchestrator/snapshots/work-final",
            "final_commit_sha": "a" * 40,
            "final_tree_sha": "a" * 40,
            "boundary_hash": boundary_hash,
            "boundary_entries": [],
            "cache_authority_hash": cache_hash,
        }
        attempt = execution_attempts_view(projection)["work-execution"]
        witness = _apply_decision_boundary(
            projection,
            "witness_runner_completion",
            {
                **final_payload,
                "staged_payload_hash": attempt.payload_hash,
                "staged_payload_size_bytes": attempt.payload_size_bytes,
                "staged_snapshot_id": attempt.staged_snapshot_id,
                "staged_snapshot_ref": attempt.staged_snapshot_ref,
                "staged_commit_sha": attempt.staged_commit_sha,
                "staged_tree_sha": attempt.staged_tree_sha,
                "staged_boundary_hash": attempt.staged_boundary_hash,
                "runner_return_kind": "terminal_answer_completed",
            },
            position=102,
        )
        assert witness[0].event_type == "runner_completion_witnessed", witness
        projection = _reduce_planned_events(projection, witness, 102)
        result = _apply_decision_boundary(
            projection,
            "finalize_runner_execution",
            {
                **final_payload,
                "callback_payload": envelope,
                "decision_base_graph_position": 101,
                "decision_question_context": question_context,
                "controller_output_records": records,
            },
            position=104,
            events=[revision],
        )
    if requirement_id == "REQ-UNRELATED":
        expected = "runner_submission_staged" if phase == "stage" else "runner_execution_finalized"
        assert result[0].event_type == expected, result
    else:
        assert [item.event_type for item in result] == ["command_rejected"], result
        assert "read authority changed" in str(result[0].payload["reason"])


def test_decision_stage_is_effect_free_finalization_atomic_and_recovery_terminal() -> None:
    projection = _decision_successor_projection()
    root = node_payload_view(projection, "root")
    assert root is not None
    cache_authority_hash = cast(str, root["cache_authority_hash"])
    lease_position = 100
    projection = reduce_event(
        projection,
        graph_event(
            "lease_granted",
            {
                "lease_id": "decision-lease",
                "node_id": "planner-plan",
                "generation": 1,
                "execution_id": "decision-execution",
                "base_snapshot_id": "decision-base",
                "cache_authority_hash": cache_authority_hash,
            },
            position=lease_position,
        ),
    )
    oid = "a" * 40
    boundary_hash = boundary_manifest_hash(oid, [], cache_authority_hash=cache_authority_hash)
    baseline_payload = {
        "execution_id": "decision-execution",
        "node_id": "planner-plan",
        "lease_id": "decision-lease",
        "lease_generation": 1,
        "lease_base_snapshot_id": "decision-base",
        "baseline_snapshot_id": "decision-base",
        "baseline_snapshot_ref": "refs/orchestrator/snapshots/decision-base",
        "baseline_commit_sha": oid,
        "baseline_tree_sha": oid,
        "entries": [],
        "boundary_hash": boundary_hash,
        "cache_authority_hash": cache_authority_hash,
    }
    baseline_events = _apply_decision_boundary(
        projection,
        "record_runner_baseline",
        baseline_payload,
        position=lease_position,
    )
    assert [item.event_type for item in baseline_events] == ["runner_baseline_recorded"], (
        baseline_events
    )
    projection = _reduce_planned_events(projection, baseline_events, lease_position)

    resolved = resolve_batch_decision_context(projection, "planner-plan")
    answer = {"decision": {"disposition": "proceed", "implementation_notes": ""}}
    preview = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="decision-request-atomic",
        base_graph_position=101,
        answer=answer["decision"],
    )
    preview_events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": preview.patch_id,
            "base_graph_position": preview.base_graph_position,
            "ops": list(preview.ops),
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=101,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert preview_events[0].event_type == "graph_patch_accepted", preview_events
    question_context = resolved.protected_question_context()
    context_hash, context_size = callback_payload_identity(question_context)
    request = DecisionSubmissionRequest(
        decision_request_id="decision-request-atomic",
        execution_id="decision-execution",
        routine_snapshot_record_id=resolved.routine_snapshot_record_id,
        interaction_contract="decision-v1",
        answer_schema_id="orchestrator.reliable-plan.batch-decision",
        answer_schema_version=1,
        answer_schema_sha256=batch_decision_schema_sha256(),
        compiler_contract_version=1,
        question_context_ref={
            "artifact_id": context_hash,
            "content_hash": context_hash,
            "size_bytes": context_size,
            "media_type": "application/json",
            "encoding": "utf-8",
            "storage_uri": "artifact://sha256/" + context_hash.removeprefix("sha256:"),
        },
        question_context_sha256=context_hash,
        bound_inputs=resolved.bound_inputs,
    )
    envelope = DecisionSubmissionEnvelope(
        format="decision-submission-v1",
        request=request,
        answer_attempt_id="answer-attempt-1",
        answer=answer,
        answer_sha256=canonical_decision_answer_hash(answer),
    ).model_dump(mode="json", by_alias=True)
    payload_hash, _ = callback_payload_identity(envelope)
    stage_position = lease_position + len(baseline_events)
    stage_payload = {
        "execution_id": "decision-execution",
        "node_id": "planner-plan",
        "lease_id": "decision-lease",
        "lease_generation": 1,
        "base_snapshot_id": "decision-base",
        "observed_graph_position": stage_position,
        "idempotency_key": "decision-request-atomic:submit",
        "payload": envelope,
        "payload_hash": payload_hash,
        "is_mutating": True,
        "complete_node": True,
        "new_state": "completed",
        "staged_snapshot_id": "decision-staged",
        "staged_snapshot_ref": "refs/orchestrator/snapshots/decision-staged",
        "staged_commit_sha": oid,
        "staged_tree_sha": oid,
        "boundary_hash": boundary_hash,
        "boundary_entries": [],
        "cache_authority_hash": cache_authority_hash,
    }
    legacy_bypass = _apply_decision_boundary(
        projection,
        "stage_runner_submission",
        {
            **stage_payload,
            "payload": {"output_records": []},
            "payload_hash": callback_payload_identity({"output_records": []})[0],
        },
        position=stage_position,
    )
    assert legacy_bypass[0].event_type == "command_rejected"
    assert "frozen authority" in str(legacy_bypass[0].payload["reason"])
    stale_envelope = deepcopy(envelope)
    stale_envelope["request"]["bound_inputs"][1]["bound_at_position"] += 1
    stale_payload = {
        **stage_payload,
        "payload": stale_envelope,
        "payload_hash": callback_payload_identity(stale_envelope)[0],
    }
    stale_events = _apply_decision_boundary(
        projection,
        "stage_runner_submission",
        stale_payload,
        position=stage_position,
    )
    assert stale_events[0].event_type == "command_rejected"
    assert "exact successor authority" in str(stale_events[0].payload["reason"])

    stage_events = _apply_decision_boundary(
        projection,
        "stage_runner_submission",
        stage_payload,
        position=stage_position,
    )
    assert [item.event_type for item in stage_events] == ["runner_submission_staged"], stage_events
    assert not any(
        item.event_type in {"graph_patch_accepted", "output_record_accepted", "node_state_changed"}
        for item in stage_events
    )
    staged = _reduce_planned_events(projection, stage_events, stage_position)
    assert (
        _apply_decision_boundary(
            staged,
            "stage_runner_submission",
            stage_payload,
            position=stage_position + 1,
        )
        == []
    )
    conflicting_envelope = deepcopy(envelope)
    conflicting_answer = {
        "decision": {
            "disposition": "proceed",
            "implementation_notes": "A conflicting retransmission.",
        }
    }
    conflicting_envelope["answer"] = conflicting_answer
    conflicting_envelope["answer_sha256"] = canonical_decision_answer_hash(conflicting_answer)
    conflicting_events = _apply_decision_boundary(
        staged,
        "stage_runner_submission",
        {
            **stage_payload,
            "payload": conflicting_envelope,
            "payload_hash": callback_payload_identity(conflicting_envelope)[0],
        },
        position=stage_position + 1,
    )
    assert conflicting_events[0].event_type == "command_rejected"
    assert "submission conflicts" in str(conflicting_events[0].payload["reason"])

    final_payload = {
        "execution_id": "decision-execution",
        "node_id": "planner-plan",
        "lease_id": "decision-lease",
        "lease_generation": 1,
        "final_snapshot_id": "decision-final",
        "final_snapshot_ref": "refs/orchestrator/snapshots/decision-final",
        "final_commit_sha": oid,
        "final_tree_sha": oid,
        "boundary_hash": boundary_hash,
        "boundary_entries": [],
        "cache_authority_hash": cache_authority_hash,
    }
    attempt = execution_attempts_view(staged)["decision-execution"]
    common_witness = {
        **final_payload,
        "staged_payload_hash": attempt.payload_hash,
        "staged_payload_size_bytes": attempt.payload_size_bytes,
        "staged_snapshot_id": attempt.staged_snapshot_id,
        "staged_snapshot_ref": attempt.staged_snapshot_ref,
        "staged_commit_sha": attempt.staged_commit_sha,
        "staged_tree_sha": attempt.staged_tree_sha,
        "staged_boundary_hash": attempt.staged_boundary_hash,
    }
    wrong_witness_events = _apply_decision_boundary(
        staged,
        "witness_runner_completion",
        {**common_witness, "runner_return_kind": "successful_return"},
        position=stage_position + 1,
    )
    wrong_witness = _reduce_planned_events(staged, wrong_witness_events, stage_position + 1)
    rejected = _apply_decision_boundary(
        wrong_witness,
        "finalize_runner_execution",
        {**final_payload, "callback_payload": envelope},
        position=stage_position + 2,
    )
    assert rejected[0].event_type == "command_rejected"
    assert "terminal_answer_completed" in str(rejected[0].payload["reason"])

    witness_events = _apply_decision_boundary(
        staged,
        "witness_runner_completion",
        {**common_witness, "runner_return_kind": "terminal_answer_completed"},
        position=stage_position + 1,
    )
    witnessed = _reduce_planned_events(staged, witness_events, stage_position + 1)
    missing_context = _apply_decision_boundary(
        witnessed,
        "finalize_runner_execution",
        {
            **final_payload,
            "callback_payload": envelope,
            "decision_base_graph_position": stage_position,
        },
        position=stage_position + 2,
    )
    assert missing_context[0].event_type == "command_rejected"
    assert "question context was not resolved" in str(missing_context[0].payload["reason"])
    corrupt_context = _apply_decision_boundary(
        witnessed,
        "finalize_runner_execution",
        {
            **final_payload,
            "callback_payload": envelope,
            "decision_base_graph_position": stage_position,
            "decision_question_context": {**question_context, "planning_horizon": 2},
        },
        position=stage_position + 2,
    )
    assert corrupt_context[0].event_type == "command_rejected"
    assert "stale or corrupt" in str(corrupt_context[0].payload["reason"])
    revision = graph_event(
        "requirement_revision_recorded",
        {
            "run_id": "run-1",
            "requirement_id": "REQ-1",
            "version_id": "revised",
            "node_id": "requirement-1",
        },
        position=stage_position + 2,
    )
    stale_requirement = _apply_decision_boundary(
        witnessed,
        "finalize_runner_execution",
        {
            **final_payload,
            "callback_payload": envelope,
            "decision_base_graph_position": stage_position,
            "decision_question_context": question_context,
        },
        position=stage_position + 2,
        events=[revision],
    )
    assert stale_requirement[0].event_type == "command_rejected"
    assert "read authority changed" in str(stale_requirement[0].payload["reason"])
    unrelated_revision = graph_event(
        "requirement_revision_recorded",
        {
            "run_id": "run-1",
            "requirement_id": "REQ-UNRELATED",
            "version_id": "unrelated-revision",
            "node_id": "unrelated-requirement-node",
        },
        position=stage_position + 2,
    )
    unrelated_result = _apply_decision_boundary(
        witnessed,
        "finalize_runner_execution",
        {
            **final_payload,
            "callback_payload": envelope,
            "decision_base_graph_position": stage_position,
            "decision_question_context": question_context,
        },
        position=stage_position + 2,
        events=[unrelated_revision],
    )
    assert unrelated_result[0].event_type == "runner_execution_finalized"
    assert [item.event_type for item in unrelated_result].count("graph_patch_accepted") == 1
    finalized = _apply_decision_boundary(
        witnessed,
        "finalize_runner_execution",
        {
            **final_payload,
            "callback_payload": envelope,
            "decision_base_graph_position": stage_position,
            "decision_question_context": question_context,
        },
        position=stage_position + 2,
    )
    event_types = [item.event_type for item in finalized]
    assert event_types[0] == "runner_execution_finalized"
    assert event_types.count("graph_patch_accepted") == 1
    assert event_types.count("output_record_accepted") == 1, "\n".join(event_types)
    assert event_types.count("node_state_changed") == 1
    decision_output = next(
        item for item in finalized if item.event_type == "output_record_accepted"
    )
    assert decision_output.payload["record_type"] == "decision_answer"
    assert decision_output.payload["schema_version"] == 1
    assert decision_output.payload["value"]["answer_schema_version"] == 1
    assert (
        next(item for item in finalized if item.event_type == "node_state_changed").payload[
            "new_state"
        ]
        == "completed"
    )

    recovery_payload = {
        "execution_id": "decision-execution",
        "node_id": "planner-plan",
        "lease_id": "decision-lease",
        "lease_generation": 1,
        "reason": "cancelled",
        "max_attempts": 3,
        "retry_after_recovery": False,
        "recovery_snapshot_id": "decision-recovery",
        "recovery_snapshot_ref": "refs/orchestrator/snapshots/decision-recovery",
        "recovery_commit_sha": oid,
        "final_tree_sha": oid,
        "boundary_hash": boundary_hash,
        "boundary_entries": [],
        "cache_authority_hash": cache_authority_hash,
    }
    cancelled_before_witness = _apply_decision_boundary(
        staged,
        "request_runner_recovery",
        recovery_payload,
        position=stage_position + 1,
    )
    assert [item.event_type for item in cancelled_before_witness] == ["runner_recovery_requested"]
    cancelled_staged = _reduce_planned_events(staged, cancelled_before_witness, stage_position + 1)
    late_witness = _apply_decision_boundary(
        cancelled_staged,
        "witness_runner_completion",
        {**common_witness, "runner_return_kind": "terminal_answer_completed"},
        position=stage_position + 2,
    )
    assert late_witness[0].event_type == "command_rejected"
    assert not any(
        item.event_type in {"graph_patch_accepted", "output_record_accepted", "node_state_changed"}
        for item in [*cancelled_before_witness, *late_witness]
    )

    cancelled_after_witness = _apply_decision_boundary(
        witnessed,
        "request_runner_recovery",
        recovery_payload,
        position=stage_position + 2,
    )
    assert [item.event_type for item in cancelled_after_witness] == ["runner_recovery_requested"]
    cancelled_witnessed = _reduce_planned_events(
        witnessed, cancelled_after_witness, stage_position + 2
    )
    late_finalize = _apply_decision_boundary(
        cancelled_witnessed,
        "finalize_runner_execution",
        {
            **final_payload,
            "callback_payload": envelope,
            "decision_base_graph_position": stage_position,
            "decision_question_context": question_context,
        },
        position=stage_position + 3,
    )
    assert late_finalize[0].event_type == "command_rejected"
    assert not any(
        item.event_type in {"graph_patch_accepted", "output_record_accepted", "node_state_changed"}
        for item in [*cancelled_after_witness, *late_finalize]
    )

    finalized_projection = _reduce_planned_events(witnessed, finalized, stage_position + 2)
    cancel_after_finalize = _apply_decision_boundary(
        finalized_projection,
        "request_runner_recovery",
        recovery_payload,
        position=stage_position + 2 + len(finalized),
    )
    assert cancel_after_finalize[0].event_type == "command_rejected"
    assert [item.event_type for item in finalized].count("graph_patch_accepted") == 1
    assert [item.event_type for item in finalized].count("output_record_accepted") == 1

    # A decision-v1 run that dies after its consequence patch was accepted but
    # before judgment/finalization is terminal: it cannot use either the legacy
    # accepted-patch completion shortcut or the legacy automatic retry path.
    patch_only = _reduce_planned_events(
        witnessed,
        [
            item
            for item in finalized
            if item.event_type == "graph_patch_accepted"
            or item.payload.get("patch_id") == preview.patch_id
        ],
        stage_position + 2,
    )
    died_request = _apply_decision_boundary(
        patch_only,
        "request_runner_recovery",
        {**recovery_payload, "reason": "runner_died", "retry_after_recovery": True},
        position=stage_position + 2 + len(finalized),
    )
    assert [item.event_type for item in died_request] == ["runner_recovery_requested"]
    recovery_pending = _reduce_planned_events(
        patch_only, died_request, stage_position + 2 + len(finalized)
    )
    recovery_id = cast(str, died_request[0].payload["recovery_id"])
    recovered = _apply_decision_boundary(
        recovery_pending,
        "complete_runner_recovery",
        {
            "execution_id": "decision-execution",
            "recovery_id": recovery_id,
            "node_id": "planner-plan",
            "lease_id": "decision-lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "decision-base",
            "baseline_tree_sha": oid,
            "requested_paths": [],
            "proof_hash": recovery_proof_hash(
                execution_id="decision-execution",
                recovery_id=recovery_id,
                node_id="planner-plan",
                lease_id="decision-lease",
                lease_generation=1,
                baseline_snapshot_id="decision-base",
                baseline_tree_sha=oid,
                requested_paths=(),
                restored_paths=(),
                removed_paths=(),
            ),
            "restored_paths": [],
            "removed_paths": [],
        },
        position=stage_position + 3 + len(finalized),
    )
    triggers = {
        item.payload.get("trigger") for item in recovered if item.event_type == "node_state_changed"
    }
    assert "accepted_graph_patch_before_agent_death" not in triggers
    assert triggers == {"runner_recovery_terminal"}
    assert not any(item.event_type == "runtime_retry_scheduled" for item in recovered)
    assert not any(item.event_type == "graph_patch_accepted" for item in recovered)
    assert not any(
        item.event_type == "output_record_accepted"
        and item.payload.get("record_type") == "decision_answer"
        for item in recovered
    )
    failure = next(item for item in recovered if item.event_type == "output_record_accepted")
    assert failure.payload["value"]["failure_class"] == "infrastructure_failure"
    assert failure.payload["value"]["error_class"] == "runner_died"
    assert failure.payload["value"]["retryable"] is False

    terminal_projection = _reduce_planned_events(
        recovery_pending,
        recovered,
        stage_position + 3 + len(finalized),
    )
    assert node_states_view(terminal_projection)["planner-plan"] == "failed"
    assert leases_view(terminal_projection)["decision-lease"].state == "revoked"
    terminal_attempt = execution_attempts_view(terminal_projection)["decision-execution"]
    assert terminal_attempt.state == "recovered"
    assert terminal_attempt.retry_scheduled is False
