"""Product-real decision-v1 dispatch, CAS, and atomic-finalization proof."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from contextlib import asynccontextmanager
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from httpx import ASGITransport, AsyncClient
from starlette.types import Message

import pytest
import yaml
from sqlalchemy import select

from orchestrator.api import GraphMcpDispatcher
from orchestrator.artifacts import (
    ArtifactIntegrityError,
    FilesystemArtifactStore,
    StoredArtifactRef,
)
from orchestrator.config import AgentRunnerType, RoutineConfig
from orchestrator.db import (
    EventV2Model,
    GraphOutboxModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import (
    DecisionSubmissionEnvelope,
    FakeClock,
    SequentialIdGenerator,
    execution_attempts_view,
    file_state_records_view,
    input_bindings_view,
    leases_view,
    node_kinds_view,
    node_payload_view,
    node_states_view,
    output_record_payloads_view,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    GraphMcpExecutionRegistry,
    OutboxDispatcher,
    replay_decision_answer_receipt,
    resolve_orchestrator_source_root,
    StaticGraphAgentFactory,
)
from orchestrator.runners import (
    AgentRunnerInfo,
    CodexServerAgent,
    ExecutionContext,
    ExecutionResult,
    SubmissionAcknowledgement,
    SubmissionInvocation,
    SubmissionRejectedError,
    AgentMetadataCallback,
    ChecklistUpdateCallback,
    EscalationCallback,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from tests.unit.test_graph_decisions import (
    _compile,
    _planner_routine,
    _verification_events,
    decision_successor_events,
)
from tests.unit.test_initial_planning_decision import _durable_initial_events
from tests.unit.test_rejected_plan_correction_decision import _rejected_amendment_events
from tests.unit.graph_test_utils import event as graph_event
from tests.integration.test_codex_dynamic_tool_receipts import (
    ScriptedJsonRpcTransport,
    _handshake_and,
    _tool_call,
    _turn_completed,
)


def _events_for_runner(events: list[Any], runner_type: AgentRunnerType) -> list[Any]:
    """Retarget a disposable qualified graph to one supported runner adapter."""
    output: list[Any] = []
    for event in events:
        payload = dict(event.payload)
        if event.event_type == "node_created":
            payload["reliable_plan_selected_runner_type"] = runner_type.value
            carrier = payload.get("reliable_plan_assignment_carrier")
            if isinstance(carrier, dict):
                updated_carrier = deepcopy(carrier)
                updated_carrier["selected_runner_type"] = runner_type.value
                arm = updated_carrier.get("arm")
                if isinstance(arm, dict):
                    for assignment in arm.values():
                        if isinstance(assignment, dict):
                            assignment["runner_type"] = runner_type.value
                payload["reliable_plan_assignment_carrier"] = updated_carrier
        if event.event_type == "edge_created":
            selector = payload.get("accepted_record_selector")
            if isinstance(selector, dict) and "record_type" not in selector:
                record_type = {
                    "semantic_artifact": "semantic_artifact",
                    "verification_report": "verification_report",
                }.get(str(payload.get("to_port")), "requirement_record")
                payload["accepted_record_selector"] = {
                    **selector,
                    "record_type": record_type,
                }
        output.append(event.model_copy(update={"payload": payload}))
    return output


async def _exercise_runtime_check_verifier(
    tmp_path: Path,
    *,
    check_exit_code: int,
    expected_outcome: str | None,
    mutate_after_answer: bool = False,
    revision: str | None = None,
) -> None:
    worktree = tmp_path / "runtime-check-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "runtime-check.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    ids = SequentialIdGenerator()
    controller = GraphController(
        sessions,
        FakeClock(),
        ids,
        auto_dispatch=False,
    )
    run_id = "runtime-check-verifier"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _events_for_runner(
            _runtime_check_seed_events(
                worktree,
                check_exit_code=check_exit_code,
            ),
            AgentRunnerType.CODEX_SERVER,
        )
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "runtime-check-base",
            "max_grants": 1,
            "priorities": {"worker-core": 100, "check-core-1": 50, "planner-plan": 1},
        },
    )
    worker_item = next(
        item
        for item in scheduled.outbox_items
        if item.kind == "agent_dispatch" and item.payload.get("node_id") == "worker-core"
    )
    artifacts = FilesystemArtifactStore(tmp_path / "runtime-check-artifacts")
    worker_runner = _LegacyWorkerRunner()

    def build_worker_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _LegacyWorkerRunner:
        del run_id, phase
        return worker_runner

    worker_executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_worker_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await worker_executor.dispatch(worker_item)
    await worker_executor.wait_for_all(timeout_seconds=10)
    async with sessions() as session:
        worker_events = await GraphEventStore(session).read_run(run_id)
    worker_projection = await controller.read_projection(run_id)
    assert any(
        record.record_type == "candidate" and record.producer_node_id == "worker-core"
        for record in output_record_payloads_view(worker_projection).values()
    ), " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
        for event in worker_events[-25:]
    )
    check_scheduled = await controller.handle_command(
        run_id,
        worker_events[-1].position,
        "schedule_tick",
        {
            "base_snapshot_id": "runtime-check-base",
            "max_grants": 1,
            "priorities": {"check-core-1": 100, "planner-plan": 1},
        },
    )
    assert any(
        item.payload.get("node_id") == "check-core-1" for item in check_scheduled.outbox_items
    ), {
        "events": [(event.event_type, event.payload) for event in check_scheduled.events],
        "outbox": [(item.kind, item.payload) for item in check_scheduled.outbox_items],
    }
    check_item = next(
        item
        for item in check_scheduled.outbox_items
        if item.payload.get("node_id") == "check-core-1"
    )
    registry = GraphMcpExecutionRegistry()

    def verifier_answer(context: ExecutionContext) -> dict[str, Any]:
        aliases = list(dict.fromkeys(re.findall(r'"alias"\s*:\s*"(o[1-9][0-9]*)"', context.prompt)))
        assert len(aliases) >= 2
        return {
            "findings": [
                {
                    "obligation": alias,
                    "grade": "A",
                    "reason": "The exact candidate satisfies this obligation.",
                    "evidence": [],
                }
                for alias in aliases
            ]
        }

    async def revise_authority(context: ExecutionContext) -> None:
        assert revision is not None
        async with sessions() as session:
            position = await GraphEventStore(session).current_position(run_id)
        changed = await controller.handle_command(
            run_id,
            position,
            "record_requirement_revision",
            {
                "requirement_id": "REQ-1" if revision == "bound" else "unrelated-requirement",
                "version_id": "revision-v2",
                "classification": "semantic",
                "node_id": "requirement-core" if revision == "bound" else "unrelated-node",
            },
        )
        assert any(event.event_type == "requirement_revision_recorded" for event in changed.events)

    verifier_runner = _WorkResultRunner(
        worktree,
        {},
        expect_rejection=revision == "bound",
        runner_type=AgentRunnerType.CODEX_SERVER,
        registry=registry,
        answer_factory=verifier_answer,
        mutate_after_answer=mutate_after_answer,
        authority_change=revise_authority if revision is not None else None,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _WorkResultRunner:
        del run_id, phase
        return verifier_runner

    check_executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await check_executor.dispatch(check_item)
    await check_executor.wait_for_all(timeout_seconds=10)

    restarted = GraphController(
        sessions,
        FakeClock(),
        ids,
        auto_dispatch=False,
    )
    after_check = await restarted.read_projection(run_id)
    check_records = [
        record
        for record in output_record_payloads_view(after_check).values()
        if record.record_type == "check_result" and record.producer_node_id == "check-core-1"
    ]
    assert len(check_records) == 1
    receipt = check_records[0]
    assert receipt.value.status == ("passed" if check_exit_code == 0 else "failed")
    assert receipt.value.command_id == "command-core-1"
    assert receipt.value.command == {
        "id": "command-core-1",
        "argv": ["sh", "-c", f"printf runtime-check-ran; exit {check_exit_code}"],
        "timeout_seconds": 5.0,
    }
    assert receipt.value.stdout_tail == "runtime-check-ran"
    assert receipt.candidate_record_ids == ["candidate-core-record"]
    candidate = output_record_payloads_view(after_check)["candidate-core-record"]
    assert receipt.file_state_record_ids == candidate.file_state_record_ids
    assert input_bindings_view(after_check)["planner-plan"]["check_result_1"].record_ids == [
        receipt.record_id
    ]

    async with sessions() as session:
        after_check_events = await GraphEventStore(session).read_run(run_id)
    rescheduled = await restarted.handle_command(
        run_id,
        after_check_events[-1].position,
        "schedule_tick",
        {
            "base_snapshot_id": "runtime-check-base",
            "max_grants": 1,
            "priorities": {"check-core-1": 100, "planner-plan": 50},
        },
    )
    assert not any(
        item.payload.get("node_id") == "check-core-1" for item in rescheduled.outbox_items
    )
    verifier_item = next(
        item
        for item in rescheduled.outbox_items
        if item.kind == "agent_dispatch" and item.payload.get("node_id") == "planner-plan"
    )
    verifier_executor = GraphDispatchExecutor(
        sessions,
        restarted,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        graph_mcp_registry=registry,
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await verifier_executor.dispatch(verifier_item)
    await verifier_executor.wait_for_all(timeout_seconds=10)
    final = await restarted.read_projection(run_id)
    reports = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "verification_report" and record.producer_node_id == "planner-plan"
    ]
    async with sessions() as session:
        verifier_events = await GraphEventStore(session).read_run(run_id)
    assert verifier_runner.execution_context is not None
    expected_report_count = 0 if mutate_after_answer or revision == "bound" else 1
    assert len(reports) == expected_report_count, (
        " | ".join(
            f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
            for event in verifier_events[-30:]
        )
        + f" | file_states={file_state_records_view(final)}"
    )
    if expected_report_count:
        assert reports[0].outcome == expected_outcome
        assert receipt.record_id in reports[0].evaluated_record_ids
        judgment_id = reports[0].value.judgment_artifact_record_id
        assert isinstance(judgment_id, str)
        public_records = output_record_payloads_view(final)
        judgment = public_records[judgment_id]
        assert judgment.record_type == "semantic_artifact"
        assert judgment.value.semantic_role == "verification_judgment"
        assert receipt.record_id in judgment.value.source_record_ids
    else:
        assert not any(
            record.record_type == "semantic_artifact"
            and getattr(record.value, "semantic_role", None) == "verification_judgment"
            for record in output_record_payloads_view(final).values()
        )
    assert verifier_runner.execution_context is not None
    assert f'"status": "{receipt.value.status}"' in verifier_runner.execution_context.prompt
    assert "runtime-check-ran" in verifier_runner.execution_context.prompt
    final_events = verifier_events
    assert (
        sum(
            event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "check_result"
            for event in final_events
        )
        == 1
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_check_executes_once_before_typed_verifier_and_survives_restart(
    tmp_path: Path,
) -> None:
    await _exercise_runtime_check_verifier(
        tmp_path,
        check_exit_code=0,
        expected_outcome="passed",
    )


@pytest.mark.asyncio
async def test_runtime_check_post_answer_mutation_survives_restart_without_publishing_report(
    tmp_path: Path,
) -> None:
    await _exercise_runtime_check_verifier(
        tmp_path,
        check_exit_code=0,
        expected_outcome=None,
        mutate_after_answer=True,
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_typed_verifier_rejects_bound_requirement_revision(
    tmp_path: Path,
) -> None:
    await _exercise_runtime_check_verifier(
        tmp_path,
        check_exit_code=0,
        expected_outcome=None,
        revision="bound",
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_typed_verifier_accepts_unrelated_requirement_revision(
    tmp_path: Path,
) -> None:
    await _exercise_runtime_check_verifier(
        tmp_path,
        check_exit_code=0,
        expected_outcome="passed",
        revision="unrelated",
    )


def _ordered_decision_seed_events(runner_type: AgentRunnerType) -> list[Any]:
    """Make the compact decision fixture valid for durable replay seeding."""
    events = _events_for_runner(decision_successor_events(), runner_type)
    planner_authority = next(
        event.payload
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
    )
    planner_carrier = planner_authority["reliable_plan_assignment_carrier"]
    planner_skeleton_id = planner_authority["reliable_plan_skeleton_id"]
    planner_evidence_hash = planner_authority["reliable_plan_qualification_evidence_hash"]
    requirement_events = [
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "requirement_record"
    ]
    events = [event for event in events if event not in requirement_events]
    plan_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    events[plan_index:plan_index] = requirement_events
    positioned: list[Any] = []
    for position, event in enumerate(events, start=1):
        payload = dict(event.payload)
        if event.event_type == "node_created" and payload.get("node_id") == "root":
            payload.update(
                {
                    "reliable_plan_skeleton_id": planner_skeleton_id,
                    "reliable_plan_assignment_carrier": deepcopy(planner_carrier),
                    "reliable_plan_qualification_evidence_hash": planner_evidence_hash,
                    "reliable_plan_selected_runner_type": runner_type.value,
                    "reliable_plan_assignment_role": "planner",
                    "runner_model_override": "test-model",
                    "profile": "architect",
                }
            )
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload.update(
                {
                    "state": "planned",
                    "reliable_plan_assignment_role": "successor_planner",
                    "reliable_plan_selected_runner_type": runner_type.value,
                    "runner_model_override": "test-model",
                    "profile": "architect",
                }
            )
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {record_id: position for record_id in record_ids}
        positioned.append(event.model_copy(update={"position": position, "payload": payload}))
    return positioned


def _ordered_rejected_amendment_seed_events(
    runner_type: AgentRunnerType,
) -> tuple[list[Any], str]:
    """Make the rejected-amendment unit fixture valid for durable replay."""
    raw_events, gap_id, _rejected_plan_id = _rejected_amendment_events()
    events = _events_for_runner(raw_events, runner_type)
    requirement_events = [
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "requirement_record"
    ]
    events = [event for event in events if event not in requirement_events]
    plan_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    events[plan_index:plan_index] = requirement_events
    batch_report_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "batch-core-passed"
    )
    events.insert(
        batch_report_index,
        graph_event(
            "output_record_accepted",
            {
                "record_id": "candidate-core",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-discovery",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-core",
                "task_region_id": "successor-core",
                "attempt_number": 1,
                "value": {"summary": "accepted core candidate"},
            },
            position=0,
        ),
    )
    cache_authority_hash = next(
        cast(str, event.payload["cache_authority_hash"])
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    positioned: list[Any] = []
    for position, event in enumerate(events, start=1):
        payload = dict(event.payload)
        if event.event_type == "node_created":
            payload.setdefault("cache_authority_hash", cache_authority_hash)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {
                record_id: position for record_id in record_ids
            }
        positioned.append(event.model_copy(update={"position": position, "payload": payload}))
    return positioned, gap_id


def _ordered_work_result_seed_events(*, include_semantic_output: bool = False) -> list[Any]:
    """Retarget the accepted decision fixture to one executable worker."""
    events = _ordered_decision_seed_events(AgentRunnerType.CODEX_SERVER)
    if include_semantic_output:
        routine_payload = _planner_routine(interaction="decision-v1").model_dump(mode="json")
        routine_payload.update(
            yaml.safe_load("""
semantic_artifact_schemas:
  - schema_id: worker.release-note
    version: 1
    semantic_role: release_note
    json_schema:
      type: object
      required: [release_note]
      additionalProperties: false
      properties:
        release_note:
          type: string
          minLength: 1
""")
        )
        compiled = _compile(RoutineConfig.model_validate(routine_payload))
        snapshot = next(
            event
            for event in compiled
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "routine_snapshot"
        )
        declaration = next(
            event
            for event in compiled
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "semantic_schema_declaration"
            and event.payload["value"]["schema_id"] == "worker.release-note"
        )
        updated = []
        for event in events:
            if (
                event.event_type == "output_record_accepted"
                and event.payload.get("record_type") == "routine_snapshot"
            ):
                event = event.model_copy(
                    update={"payload": {**event.payload, "value": snapshot.payload["value"]}}
                )
                updated.extend([event, declaration])
                continue
            if (
                event.event_type == "node_created"
                and event.payload.get("role") == "routine_snapshot"
            ):
                event = event.model_copy(
                    update={
                        "payload": {
                            **event.payload,
                            "snapshot": snapshot.payload["value"],
                            "routine_snapshot_record": snapshot.payload,
                        }
                    }
                )
            updated.append(event)
        events = updated
    cache_authority_hash = next(
        event.payload["cache_authority_hash"]
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    output: list[Any] = []
    for event in events:
        payload = dict(event.payload)
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload["node_id"] = "worker-core"
            worker_outputs = [
                {
                    "port": "candidate",
                    "direction": "output",
                    "schema": "ImplementationCandidate",
                    "record_layers": ["graph_record"],
                    "required": True,
                },
                {
                    "port": "file_state",
                    "direction": "output",
                    "schema": "FileStateRecord",
                    "record_layers": ["graph_record"],
                    "required": True,
                },
            ]
            if include_semantic_output:
                payload.update(
                    {
                        "semantic_schema_id": "worker.release-note",
                        "semantic_schema_version": 1,
                    }
                )
                worker_outputs.append(
                    {
                        "port": "semantic_artifact",
                        "direction": "output",
                        "schema": "SemanticArtifact",
                        "record_layers": ["graph_record"],
                        "required": True,
                    }
                )
            worker_outputs.append(
                {
                    "port": "decision",
                    "direction": "output",
                    "schema": "DecisionAnswer",
                    "record_layers": ["graph_record"],
                    "required": True,
                }
            )
            payload.update(
                {
                    "kind": "worker",
                    "role": "implementer",
                    "state": "planned",
                    "semantic_stage": "effectful_batch",
                    "task_region_id": "batch-core",
                    "access_mode": "write",
                    "effect_contract": "effectful_write",
                    "authority": {
                        "allowed_actions": ["submit_records", "request_clarification"],
                        "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
                    },
                    "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
                    "cache_authority_hash": cache_authority_hash,
                    "reliable_plan_assignment_role": "implementation_worker",
                    "profile": "coder",
                    "outputs": worker_outputs,
                }
            )
        if (
            event.event_type in {"edge_created", "input_bound"}
            and payload.get("to_node_id") == "planner-plan"
        ):
            payload["to_node_id"] = "worker-core"
        output.append(event.model_copy(update={"payload": payload}))
    positioned = []
    for position, event in enumerate(output, start=1):
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        if event.event_type == "input_bound":
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {
                record_id: position for record_id in payload["record_ids"]
            }
        positioned.append(
            event.model_copy(
                update={
                    "event_id": f"worker-seed-{position}",
                    "position": position,
                    "payload": payload,
                }
            )
        )
    return positioned


async def _exercise_work_result_worker(
    tmp_path: Path,
    answer: dict[str, Any],
    expected_node_state: str,
    expect_candidate: bool,
    include_semantic_output: bool,
    expect_semantic_output: bool,
    expect_submission_rejection: bool,
    runner_type: AgentRunnerType,
    mutate_after_answer: bool = False,
    fail_check: bool = False,
    revision: str | None = None,
    revise_after_answer: bool = False,
    dispatch_recovery: bool = False,
    expected_recovery_node_state: str | None = None,
) -> None:
    worktree = tmp_path / "work-result-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "work-result.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "work-result-run"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _events_for_runner(
            _ordered_work_result_seed_events(include_semantic_output=include_semantic_output),
            runner_type,
        )
    ]
    if fail_check:
        seed_events = [
            event.model_copy(
                update={
                    "payload": {
                        **event.payload,
                        "acceptance_commands": ["test ! -f src/implemented.py"],
                    }
                }
            )
            if event.event_type == "node_created" and event.payload.get("node_id") == "worker-core"
            else event
            for event in seed_events
        ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "work-result-base",
            "max_grants": 1,
            "priorities": {"worker-core": 100},
        },
    )
    dispatch_item = next(
        item
        for item in scheduled.outbox_items
        if item.kind == "agent_dispatch" and item.payload.get("node_id") == "worker-core"
    )

    async def revise_authority(context: ExecutionContext) -> None:
        assert revision is not None
        async with sessions() as session:
            position = await GraphEventStore(session).current_position(run_id)
        changed = await controller.handle_command(
            run_id,
            position,
            "record_requirement_revision",
            {
                "requirement_id": "REQ-1" if revision == "bound" else "unrelated-requirement",
                "version_id": "revision-v2",
                "classification": "semantic",
                "node_id": "requirement-1" if revision == "bound" else "unrelated-node",
            },
        )
        assert any(event.event_type == "requirement_revision_recorded" for event in changed.events)

    registry = GraphMcpExecutionRegistry()
    runner = _WorkResultRunner(
        worktree,
        answer,
        expect_rejection=expect_submission_rejection,
        runner_type=runner_type,
        registry=registry,
        mutate_after_answer=mutate_after_answer,
        authority_change=revise_authority if revision is not None else None,
        revise_after_answer=revise_after_answer,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _WorkResultRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            runner_type,
            runner_builder=build_runner,
        ),
        graph_mcp_registry=registry,
        worktree_path=worktree,
        artifact_store=(artifacts := FilesystemArtifactStore(tmp_path / "work-result-artifacts")),
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    if dispatch_recovery:
        async with sessions() as session:
            async with session.begin():
                dispatch_rows = (
                    await session.execute(
                        select(GraphOutboxModel).where(
                            GraphOutboxModel.run_id == run_id,
                            GraphOutboxModel.kind == "agent_dispatch",
                        )
                    )
                ).scalars()
                for row in dispatch_rows:
                    row.status = "completed"
        await OutboxDispatcher(
            sessions,
            executor,
            FakeClock(),
            retry_jitter_seconds=0,
        ).dispatch_pending(
            run_id=run_id,
            allowed_kinds=frozenset({"snapshot_publish"}),
        )
        await OutboxDispatcher(
            sessions,
            executor,
            FakeClock(),
            retry_jitter_seconds=0,
        ).dispatch_pending(
            run_id=run_id,
            allowed_kinds=frozenset({"runner_recovery"}),
        )

    projection = await controller.read_projection(run_id)
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
    records = output_record_payloads_view(projection).values()
    decision_records = [record for record in records if record.record_type == "decision_answer"]
    semantic_records = [
        record
        for record in records
        if record.record_type == "semantic_artifact"
        and record.producer_node_id == "worker-core"
        and record.port == "semantic_artifact"
    ]
    candidates = [
        record
        for record in records
        if record.record_type == "candidate" and record.producer_node_id == "worker-core"
    ]
    file_states = [
        record
        for record in file_state_records_view(projection).values()
        if record.producer_node_id == "worker-core"
    ]
    assert runner.execution_context is not None
    if runner_type == AgentRunnerType.CLI_SUBPROCESS:
        assert runner.execution_context.graph_mcp_url is not None
        token = runner.execution_context.graph_mcp_url.split("/mcp-graph/", 1)[1].split("/", 1)[0]
        assert registry.get(token) is None
    assert runner.submission_rejected is expect_submission_rejection
    assert node_states_view(projection)["worker-core"] == expected_node_state, [
        (event.event_type, event.payload.get("reason"), event.payload.get("error_detail"))
        for event in events[-20:]
    ] + [
        (
            "attempts",
            [
                attempt.model_dump(mode="json")
                for attempt in execution_attempts_view(projection).values()
            ],
        )
    ]
    failed_after_staging = mutate_after_answer or (revision == "bound" and revise_after_answer)
    if expect_submission_rejection or failed_after_staging:
        if expected_recovery_node_state is not None:
            assert node_states_view(projection)["worker-core"] == expected_recovery_node_state, [
                [
                    (
                        event.event_type,
                        event.payload.get("reason"),
                        event.payload.get("trigger"),
                        event.payload.get("new_state"),
                    )
                    for event in events
                    if event.event_type
                    in {
                        "runner_recovery_requested",
                        "runner_recovery_completed",
                        "node_state_changed",
                    }
                ],
            ]
        if dispatch_recovery:
            assert not any(event.event_type == "runtime_retry_scheduled" for event in events)
            async with sessions() as session:
                agent_dispatches = (
                    await session.execute(
                        select(GraphOutboxModel).where(
                            GraphOutboxModel.run_id == run_id,
                            GraphOutboxModel.kind == "agent_dispatch",
                        )
                    )
                ).scalars()
                assert all(row.status == "completed" for row in agent_dispatches)
        assert next(iter(execution_attempts_view(projection).values())).state == (
            "recovered" if dispatch_recovery else "recovery_requested"
        )
        assert not decision_records
        assert not semantic_records
        assert not candidates
        assert not file_states
        assert runner.terminal_close_calls == (1 if failed_after_staging else 0)
        assert (
            any(event.event_type == "runner_submission_staged" for event in events)
            is failed_after_staging
        )
        if revision == "bound" and revise_after_answer:
            async with sessions() as session:
                public_errors = (
                    await session.execute(
                        select(EventV2Model).where(EventV2Model.event_type == "agent_error")
                    )
                ).scalars()
                diagnostics = [
                    payload.get("failure_diagnostic")
                    for event in public_errors
                    if isinstance(payload := json.loads(event.payload), dict)
                    and payload.get("execution_id") == runner.execution_context.execution_id
                ]
            stale_diagnostic = (
                next(
                    diagnostic
                    for diagnostic in diagnostics
                    if isinstance(diagnostic, dict)
                    and diagnostic.get("category") == "stale_binding"
                )
                if any(
                    isinstance(diagnostic, dict) and diagnostic.get("category") == "stale_binding"
                    for diagnostic in diagnostics
                )
                else None
            )
            assert stale_diagnostic is not None, [
                (event.event_type, event.payload) for event in events[-20:]
            ]
            assert stale_diagnostic["next_action"] == "refresh_binding"
            assert stale_diagnostic["correction_allowed"] is False
            assert not any(event.event_type == "decision_answer_rejected" for event in events)
        if fail_check:
            rejected_answers = [
                event for event in events if event.event_type == "decision_answer_rejected"
            ]
            assert len(rejected_answers) == 1
            diagnostic = rejected_answers[0].payload["failure_diagnostic"]
            assert diagnostic["category"] == "candidate_check"
            assert diagnostic["next_action"] == "correct_candidate"
            assert diagnostic["correction_allowed"] is True
            assert rejected_answers[0].payload["decision_answer_receipt_ref"] is not None
            receipt_ref = StoredArtifactRef.model_validate(
                rejected_answers[0].payload["decision_answer_receipt_ref"]
            )
            authority_position = max(event.position for event in events)
            shutil.rmtree(worktree)
            replay_engine = create_engine(tmp_path / "candidate-check-replay.db")
            await init_db(replay_engine)
            try:
                replay = await replay_decision_answer_receipt(
                    artifact_store=artifacts,
                    evidence_ref=receipt_ref,
                    authorization_session_factory=sessions,
                    isolated_session_factory=create_session_factory(replay_engine),
                    run_id=run_id,
                    worktree_path=resolve_orchestrator_source_root(),
                    clock=FakeClock(),
                    id_gen=SequentialIdGenerator(),
                )
            finally:
                await replay_engine.dispose()
            assert replay.original_status == "rejected"
            assert replay.rejection_phase == "candidate_check"
            assert replay.failure_diagnostic is not None
            assert replay.failure_diagnostic.category == "candidate_check"
            assert replay.failure_diagnostic.next_action == "correct_candidate"
            async with sessions() as session:
                assert await GraphEventStore(session).current_position(run_id) == authority_position
            assert runner.execute_calls == 1
            assert any(
                event.event_type == "runner_recovery_requested"
                and event.payload.get("reason") == "candidate_check_failed"
                for event in events
            ), [
                (event.event_type, event.payload.get("reason"), event.payload.get("error_detail"))
                for event in events
                if event.event_type
                in {"runner_recovery_requested", "runner_recovery_completed", "agent_error"}
            ]
        await engine.dispose()
        return
    assert len(decision_records) == 1
    assert decision_records[0].value.family == "work_result"
    assert bool(semantic_records) is expect_semantic_output
    if expect_semantic_output:
        assert semantic_records[0].value.content == answer["semantic_artifact"]
        assert semantic_records[0].value.schema_id == "worker.release-note"
    assert bool(candidates) is expect_candidate
    assert bool(file_states) is expect_candidate
    if expect_candidate:
        assert (worktree / "src" / "implemented.py").exists()
        assert file_states[0].git.commit_sha is not None
        assert any(event.event_type == "callback_accepted" for event in events)
    else:
        assert not (worktree / "src" / "implemented.py").exists()
        if answer.get("status") == "blocked":
            failed_transition = next(
                event
                for event in events
                if event.event_type == "node_state_changed"
                and event.payload.get("node_id") == "worker-core"
                and event.payload.get("new_state") == "failed"
            )
            assert failed_transition.payload["reason"] == answer["blocker"]["reason"]
    assert runner.terminal_close_calls == 1
    assert all(
        attempt.state == "finalized" for attempt in execution_attempts_view(projection).values()
    )
    assert not any(lease.state == "active" for lease in leases_view(projection).values())
    await engine.dispose()


@pytest.mark.asyncio
async def test_work_result_worker_commits_candidate_and_semantic_product(
    tmp_path: Path,
) -> None:
    await _exercise_work_result_worker(
        tmp_path=tmp_path,
        answer={
            "decision": {
                "status": "ready",
                "summary": "The committed implementation and product are ready.",
            },
            "semantic_artifact": {"release_note": "The parser now handles empty input."},
        },
        expected_node_state="completed",
        expect_candidate=True,
        include_semantic_output=True,
        expect_semantic_output=True,
        expect_submission_rejection=False,
        runner_type=AgentRunnerType.CODEX_SERVER,
    )


@pytest.mark.asyncio
async def test_work_result_worker_records_offered_blocker_without_candidate(
    tmp_path: Path,
) -> None:
    await _exercise_work_result_worker(
        tmp_path=tmp_path,
        answer={
            "status": "blocked",
            "blocker": {
                "reason": "The accepted evidence does not identify the required fixture.",
                "needed_information": ["The fixture path"],
                "evidence": ["e1"],
            },
        },
        expected_node_state="failed",
        expect_candidate=False,
        include_semantic_output=False,
        expect_semantic_output=False,
        expect_submission_rejection=False,
        runner_type=AgentRunnerType.CODEX_SERVER,
    )


@pytest.mark.asyncio
async def test_work_result_missing_required_semantic_product_is_rejected(
    tmp_path: Path,
) -> None:
    await _exercise_work_result_worker(
        tmp_path=tmp_path,
        answer={"status": "ready", "summary": "The implementation is ready."},
        expected_node_state="running",
        expect_candidate=False,
        include_semantic_output=True,
        expect_semantic_output=False,
        expect_submission_rejection=True,
        runner_type=AgentRunnerType.CODEX_SERVER,
    )


@pytest.mark.asyncio
async def test_work_result_post_answer_mutation_publishes_no_effects(
    tmp_path: Path,
) -> None:
    await _exercise_work_result_worker(
        tmp_path=tmp_path,
        answer={"status": "ready", "summary": "The implementation is ready."},
        expected_node_state="running",
        expect_candidate=False,
        include_semantic_output=False,
        expect_semantic_output=False,
        expect_submission_rejection=False,
        runner_type=AgentRunnerType.CODEX_SERVER,
        mutate_after_answer=True,
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_work_result_rejects_bound_authority_revision_before_staging(
    tmp_path: Path,
) -> None:
    await _exercise_work_result_worker(
        tmp_path=tmp_path,
        answer={"status": "ready", "summary": "The implementation is ready."},
        expected_node_state="running",
        expect_candidate=False,
        include_semantic_output=False,
        expect_semantic_output=False,
        expect_submission_rejection=True,
        runner_type=AgentRunnerType.CODEX_SERVER,
        revision="bound",
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_work_result_accepts_unrelated_authority_revision_before_staging(
    tmp_path: Path,
) -> None:
    await _exercise_work_result_worker(
        tmp_path=tmp_path,
        answer={"status": "ready", "summary": "The implementation is ready."},
        expected_node_state="completed",
        expect_candidate=True,
        include_semantic_output=False,
        expect_semantic_output=False,
        expect_submission_rejection=False,
        runner_type=AgentRunnerType.CODEX_SERVER,
        revision="unrelated",
    )


@pytest.mark.asyncio
async def test_decision_v1_recovery_does_not_redispatch_after_candidate_rejection(
    tmp_path: Path,
) -> None:
    """A staged decision answer cannot silently buy a second model execution."""
    await _exercise_work_result_worker(
        tmp_path=tmp_path,
        answer={"status": "ready", "summary": "The result is ready."},
        expected_node_state="failed",
        expect_candidate=False,
        include_semantic_output=False,
        expect_semantic_output=False,
        expect_submission_rejection=True,
        runner_type=AgentRunnerType.CODEX_SERVER,
        fail_check=True,
        dispatch_recovery=True,
        expected_recovery_node_state="failed",
    )


def _correction_seed_events() -> list[Any]:
    """Build a durable accepted-plan plus failed-batch correction fixture."""
    events = _ordered_decision_seed_events(AgentRunnerType.CODEX_SERVER)
    cache_authority_hash = next(
        event.payload["cache_authority_hash"]
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    updated: list[Any] = []
    for event in events:
        if event.event_type != "node_created" or event.payload.get("node_id") != "planner-plan":
            updated.append(event)
            continue
        payload = dict(event.payload)
        payload.update(
            {
                "role": "gap_planner",
                "semantic_stage": "gap_planning",
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
                        "port": "verification_evidence",
                        "direction": "input",
                        "schema": "VerificationReport",
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
                        "port": "classified_gap",
                        "direction": "output",
                        "schema": "GapClassification",
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
        updated.append(event.model_copy(update={"payload": payload}))
    events = updated
    position = len(events) + 1
    additions: list[tuple[str, dict[str, Any]]] = [
        (
            "node_created",
            {
                "node_id": "worker-batch-core",
                "kind": "worker",
                "role": "worker",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "task_region_id": "successor-core",
            },
        ),
        (
            "node_created",
            {
                "node_id": "check-batch-core",
                "kind": "check",
                "role": "check",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "command_definition": {"argv": ["pytest"]},
                "outputs": [
                    {
                        "port": "check_result",
                        "direction": "output",
                        "schema": "CheckResult",
                        "record_layers": ["verification"],
                    }
                ],
            },
        ),
        (
            "node_created",
            {
                "node_id": "verifier-batch-core",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "core",
                "planning_horizon": 1,
                "outputs": [
                    {
                        "port": "verification_report",
                        "direction": "output",
                        "schema": "VerificationReport",
                        "record_layers": ["verification"],
                    },
                    {
                        "port": "check_result",
                        "direction": "output",
                        "schema": "CheckResult",
                        "record_layers": ["verification"],
                    },
                ],
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "candidate-core",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-batch-core",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-core",
                "task_region_id": "successor-core",
                "attempt_number": 1,
                "value": {"summary": "failed batch candidate"},
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "gap-evidence-check",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-batch-core",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-core",
                "task_region_id": "successor-core",
                "attempt_number": 1,
                "value": {
                    "status": "failed",
                    "classification": "failed",
                    "command_id": "unit",
                    "command_text": "pytest",
                    "command": {"argv": ["pytest"]},
                    "worktree_path": "/tmp/worktree",
                    "base_snapshot_id": "decision-base",
                    "execution_id": "gap-execution",
                    "exit_code": 1,
                    "duration_ms": 1,
                    "stdout_tail": "",
                    "stderr_tail": "failed",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "timeout_seconds": 10.0,
                    "evaluated_record_ids": ["candidate-core"],
                    "environment_policy": {},
                },
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "gap-evidence-report",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-batch-core",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-core",
                "candidate_record_id": "candidate-core",
                "candidate_record_ids": ["candidate-core"],
                "task_region_id": "successor-core",
                "outcome": "failed",
                "value": {"outcome": "failed", "grades": []},
                "evaluated_record_ids": ["gap-evidence-check", "candidate-core"],
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "gap-evidence-to-planner",
                "from_node_id": "verifier-batch-core",
                "from_port": "verification_report",
                "to_node_id": "planner-plan",
                "to_port": "verification_evidence",
                "required": True,
                "dependency_type": "input_binding",
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "failed",
                },
            },
        ),
        (
            "input_bound",
            {
                "edge_id": "gap-evidence-to-planner",
                "to_node_id": "planner-plan",
                "to_port": "verification_evidence",
                "record_ids": ["gap-evidence-report"],
                "record_bound_positions": {"gap-evidence-report": position},
            },
        ),
    ]
    for event_type, payload in additions:
        if event_type == "output_record_accepted":
            payload = {**payload, "graph_position": position}
        if event_type == "input_bound":
            payload = {
                **payload,
                "bound_at_position": position,
                "record_bound_positions": {
                    record_id: position for record_id in payload["record_ids"]
                },
            }
        events.append(graph_event(event_type, payload, position=position))
        position += 1
    return events


async def _exercise_decision_dispatch_authority_revision(
    tmp_path: Path,
    *,
    run_id: str,
    source_events: list[Any],
    arguments: dict[str, Any],
    requirement_id: str,
    requirement_node_id: str,
    expect_rejection: bool,
) -> None:
    worktree = tmp_path / f"{run_id}-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / f"{run_id}.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in source_events
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events)
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": f"{run_id}-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(item for item in leases_view(projection).values() if item.node_id == "planner-plan")
    assert lease.execution_id is not None

    async def revise_authority(_context: ExecutionContext) -> None:
        async with sessions() as session:
            position = await GraphEventStore(session).current_position(run_id)
        changed = await controller.handle_command(
            run_id,
            position,
            "record_requirement_revision",
            {
                "requirement_id": requirement_id,
                "version_id": "revision-v2",
                "classification": "semantic",
                "node_id": requirement_node_id,
            },
        )
        assert any(event.event_type == "requirement_revision_recorded" for event in changed.events)

    artifacts = FilesystemArtifactStore(tmp_path / f"{run_id}-artifacts")
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        arguments=arguments,
        authority_change=revise_authority,
        expect_rejection=expect_rejection,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    decision_records = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer" and record.producer_node_id == "planner-plan"
    ]
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
    assert runner.submission_rejected is expect_rejection
    if expect_rejection:
        assert not decision_records
        assert any(event.event_type == "runner_recovery_requested" for event in events)
    else:
        assert len(decision_records) == 1
        assert node_states_view(final)["planner-plan"] == "completed"
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_initial_discovery_rejects_bound_requirement_revision(
    tmp_path: Path,
) -> None:
    await _exercise_decision_dispatch_authority_revision(
        tmp_path,
        run_id="initial-bound-authority",
        source_events=_events_for_runner(
            _durable_initial_events(), AgentRunnerType.CODEX_SERVER
        ),
        arguments={
            "outputs": {
                "decision": {
                    "questions": ["Which parser seam should own the feature?"],
                    "rationale": "Repository ownership requires inspection.",
                    "focus": ["docs/spec.md"],
                }
            }
        },
        requirement_id="dynamic_feature_acceptance",
        requirement_node_id="requirement-dynamic-feature-acceptance",
        expect_rejection=True,
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_initial_discovery_accepts_unrelated_requirement_revision(
    tmp_path: Path,
) -> None:
    await _exercise_decision_dispatch_authority_revision(
        tmp_path,
        run_id="initial-unrelated-authority",
        source_events=_events_for_runner(
            _durable_initial_events(), AgentRunnerType.CODEX_SERVER
        ),
        arguments={
            "outputs": {
                "decision": {
                    "questions": ["Which parser seam should own the feature?"],
                    "rationale": "Repository ownership requires inspection.",
                    "focus": ["docs/spec.md"],
                }
            }
        },
        requirement_id="unrelated_requirement",
        requirement_node_id="unrelated-node",
        expect_rejection=False,
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_correction_rejects_bound_requirement_revision(
    tmp_path: Path,
) -> None:
    await _exercise_decision_dispatch_authority_revision(
        tmp_path,
        run_id="correction-bound-authority",
        source_events=_correction_seed_events(),
        arguments={
            "outputs": {
                "decision": {
                    "disposition": "corrective_work",
                    "diagnosis": "The accepted batch failed its required check.",
                    "remedy": "Repair only the failed batch implementation.",
                    "focus": ["src/core.py"],
                    "evidence": ["e1", "e2"],
                }
            }
        },
        requirement_id="REQ-1",
        requirement_node_id="requirement-1",
        expect_rejection=True,
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_correction_accepts_unrelated_requirement_revision(
    tmp_path: Path,
) -> None:
    await _exercise_decision_dispatch_authority_revision(
        tmp_path,
        run_id="correction-unrelated-authority",
        source_events=_correction_seed_events(),
        arguments={
            "outputs": {
                "decision": {
                    "disposition": "corrective_work",
                    "diagnosis": "The accepted batch failed its required check.",
                    "remedy": "Repair only the failed batch implementation.",
                    "focus": ["src/core.py"],
                    "evidence": ["e1", "e2"],
                }
            }
        },
        requirement_id="unrelated_requirement",
        requirement_node_id="unrelated-node",
        expect_rejection=False,
    )


def _with_second_initial_requirement(events: list[Any]) -> list[Any]:
    output = list(events)
    position = max(event.position for event in output)
    cache_authority_hash = next(
        event.payload["cache_authority_hash"]
        for event in output
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    additions = [
        (
            "node_created",
            {
                "node_id": "requirement-secondary",
                "kind": "requirement",
                "role": "requirement",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "outputs": [
                    {
                        "port": "requirement",
                        "direction": "output",
                        "schema": "RequirementRecord",
                        "required": True,
                    }
                ],
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "requirement-secondary-record",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "requirement-secondary",
                "port": "requirement",
                "schema": "RequirementRecord",
                "value": {
                    "id": "secondary_requirement",
                    "text": "Expose the bounded parser through the API.",
                    "priority": "critical",
                    "source": "routine",
                    "version": "v1",
                    "must": True,
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-secondary-requirement-to-initial",
                "from_node_id": "requirement-secondary",
                "from_port": "requirement",
                "to_node_id": "planner-plan",
                "to_port": "requirement_2",
                "required": True,
                "dependency_type": "input_binding",
                "accepted_record_selector": {
                    "record_id": "requirement-secondary-record",
                    "record_type": "requirement_record",
                },
            },
        ),
        (
            "input_bound",
            {
                "edge_id": "edge-secondary-requirement-to-initial",
                "to_node_id": "planner-plan",
                "to_port": "requirement_2",
                "record_ids": ["requirement-secondary-record"],
            },
        ),
    ]
    for event_type, raw_payload in additions:
        position += 1
        payload = dict(raw_payload)
        if event_type == "output_record_accepted":
            payload["graph_position"] = position
        if event_type == "input_bound":
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {"requirement-secondary-record": position}
        output.append(graph_event(event_type, payload, position=position))
    return output


class _BoundaryRestartObserver:
    """Pause after durable boundary commits so a fresh controller can replay."""

    def __init__(self) -> None:
        self.stage_committed = asyncio.Event()
        self.witness_committed = asyncio.Event()
        self.release_stage = asyncio.Event()
        self.release_witness = asyncio.Event()

    async def __call__(
        self,
        phase: str,
        _run_id: str,
        command_type: str,
        _events: tuple[Any, ...],
    ) -> None:
        if phase != "after_commit":
            return
        if command_type == "stage_runner_submission":
            self.stage_committed.set()
            await self.release_stage.wait()
        if command_type == "witness_runner_completion":
            self.witness_committed.set()
            await self.release_witness.wait()


class _GraphMcpProtocolClient:
    """Real JSON-RPC over registered ASGI SSE, without a listening server."""

    def __init__(self, registry: GraphMcpExecutionRegistry, url: str) -> None:
        self._dispatcher = GraphMcpDispatcher(registry)
        self._path = urlsplit(url).path
        self._received: asyncio.Queue[Message] = asyncio.Queue()
        self._sent: asyncio.Queue[Message] = asyncio.Queue()
        self._endpoint = ""
        self._next_id = 0

    @asynccontextmanager
    async def connected(self) -> AsyncIterator[_GraphMcpProtocolClient]:
        await self._received.put({"type": "http.request", "body": b""})
        task = asyncio.create_task(
            self._dispatcher(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": self._path,
                    "raw_path": self._path.encode(),
                    "root_path": "",
                    "query_string": b"",
                    "headers": [(b"host", b"localhost:8000")],
                    "server": ("localhost", 8000),
                    "client": ("test-client", 1),
                },
                self._received.get,
                self._sent.put,
            )
        )
        try:
            response = await asyncio.wait_for(self._sent.get(), 5)
            assert response["type"] == "http.response.start" and response["status"] == 200
            self._endpoint = await self._event_data()
            result = await self.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "disposable-claude-protocol-client", "version": "1"},
                },
            )
            assert result["serverInfo"]["name"] == "orchestrator-graph-exec"
            await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
            yield self
        finally:
            await self._received.put({"type": "http.disconnect"})
            await asyncio.wait_for(task, 5)

    async def _event_data(self) -> str:
        while True:
            message = await asyncio.wait_for(self._sent.get(), 5)
            body = message.get("body", b"").decode()
            for line in body.splitlines():
                if line.startswith("data: "):
                    return line.removeprefix("data: ")

    async def _post(self, payload: dict[str, Any]) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self._dispatcher),
            base_url="http://localhost:8000",
        ) as client:
            response = await client.post(self._endpoint, json=payload)
            assert response.status_code == 202, response.text

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        await self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        )
        response = json.loads(await self._event_data())
        assert response["id"] == self._next_id
        assert "error" not in response, response
        return response["result"]

    async def submit(self, invocation: SubmissionInvocation) -> SubmissionAcknowledgement:
        result = await self.request(
            "tools/call", {"name": "submit", "arguments": invocation.arguments}
        )
        content = result["content"][0]["text"]
        if result.get("isError"):
            raise SubmissionRejectedError(
                SubmissionAcknowledgement(
                    disposition="rejected",
                    message=content[:4096],
                    execution_id=invocation.execution_id,
                )
            )
        return SubmissionAcknowledgement.model_validate_json(content)


class _DecisionRunner:
    def __init__(
        self,
        controller: GraphController,
        sessions: Any,
        artifacts: FilesystemArtifactStore,
        execution_id: str,
        arguments: dict[str, Any] | None = None,
        mutate_path_after_submit: Path | None = None,
        runner_type: AgentRunnerType = AgentRunnerType.CODEX_SERVER,
        graph_mcp_registry: Any | None = None,
        authority_change: Callable[[ExecutionContext], Awaitable[None]] | None = None,
        authority_change_after_answer: bool = False,
        expect_rejection: bool = False,
    ) -> None:
        self._controller = controller
        self._sessions = sessions
        self._artifacts = artifacts
        self._execution_id = execution_id
        self._arguments = arguments
        self._mutate_path_after_submit = mutate_path_after_submit
        self._runner_type = runner_type
        self._graph_mcp_registry = graph_mcp_registry
        self._authority_change = authority_change
        self._authority_change_after_answer = authority_change_after_answer
        self._expect_rejection = expect_rejection
        self.stage_was_effect_free = False
        self.context_resolved = False
        self.corruption_rejected = False
        self.duplicate_acknowledgement: SubmissionAcknowledgement | None = None
        self.conflict_rejected = False
        self.terminal_close_calls = 0
        self.execution_context: ExecutionContext | None = None
        self.graph_mcp_was_registered = False
        self.submission_rejected = False

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=self._runner_type,
            name="decision-product-runner",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        if self._runner_type == AgentRunnerType.CLI_SUBPROCESS:
            assert context.graph_mcp_url is not None
            assert self._graph_mcp_registry is not None
            client = _GraphMcpProtocolClient(self._graph_mcp_registry, context.graph_mcp_url)
            async with client.connected():
                listed = await client.request("tools/list", {})
                assert [tool["name"] for tool in listed["tools"]] == ["submit"]
                return await self._execute_decision(context, on_checklist_update, client.submit)
        return await self._execute_decision(context, on_checklist_update, on_submit)

    async def _execute_decision(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        self.execution_context = context
        if self._runner_type == AgentRunnerType.CLI_SUBPROCESS:
            assert context.graph_mcp_url is not None
            assert self._graph_mcp_registry is not None
            token = context.graph_mcp_url.split("/mcp-graph/", 1)[1].split("/", 1)[0]
            self.graph_mcp_was_registered = self._graph_mcp_registry.get(token) is not None
            assert self.graph_mcp_was_registered
        typed_submit = cast(
            Callable[
                [SubmissionInvocation],
                Awaitable[SubmissionAcknowledgement],
            ],
            on_submit,
        )
        arguments = self._arguments or {
            "outputs": {
                "decision": {
                    "disposition": "proceed",
                    "implementation_notes": "Implement the exact selected batch.",
                }
            }
        }
        invocation = SubmissionInvocation(
            execution_id=self._execution_id,
            answer_attempt_id="attempt-1",
            transport_channel=(
                "claude_graph_mcp"
                if self._runner_type == AgentRunnerType.CLI_SUBPROCESS
                else "codex_dynamic_tool"
            ),
            transport_session_id="session-1",
            transport_request_id="request-1",
            arguments=arguments,
        )
        if self._authority_change is not None and not self._authority_change_after_answer:
            await self._authority_change(context)
        try:
            first = await typed_submit(invocation)
        except SubmissionRejectedError:
            self.submission_rejected = True
            assert self._expect_rejection
            return ExecutionResult(success=True)
        assert not self._expect_rejection
        self.duplicate_acknowledgement = await typed_submit(invocation)
        assert self.duplicate_acknowledgement.disposition == first.disposition
        assert self.duplicate_acknowledgement.execution_id == first.execution_id

        projection = await self._controller.read_projection(context.run_id)
        attempt = execution_attempts_view(projection)[self._execution_id]
        assert attempt.state == "submission_staged"
        async with self._sessions() as session:
            events = await GraphEventStore(session).read_run(context.run_id)
        staged_event = next(
            event
            for event in events
            if event.event_type == "runner_submission_staged"
            and event.payload.get("execution_id") == self._execution_id
        )
        assert staged_event.payload.get("decision_answer_receipt_ref") is not None
        with tempfile.TemporaryDirectory(prefix="decision-replay-") as replay_dir:
            replay_engine = create_engine(Path(replay_dir) / "isolated.db")
            await init_db(replay_engine)
            replay = await replay_decision_answer_receipt(
                artifact_store=self._artifacts,
                evidence_ref=StoredArtifactRef.model_validate(
                    staged_event.payload["decision_answer_receipt_ref"]
                ),
                authorization_session_factory=self._sessions,
                isolated_session_factory=create_session_factory(replay_engine),
                run_id=context.run_id,
                worktree_path=resolve_orchestrator_source_root(),
                clock=FakeClock(),
                id_gen=SequentialIdGenerator(),
            )
            await replay_engine.dispose()
        assert replay.original_status == "accepted"
        stage_position = max(
            event.position
            for event in events
            if event.event_type == "runner_submission_staged"
            and event.payload.get("execution_id") == self._execution_id
        )
        post_stage = [event for event in events if event.position >= stage_position]
        self.stage_was_effect_free = not any(
            event.event_type
            in {"graph_patch_accepted", "output_record_accepted", "node_state_changed"}
            for event in post_stage
        )

        assert attempt.payload_ref is not None
        envelope_bytes = await self._artifacts.read(
            StoredArtifactRef.model_validate(attempt.payload_ref.model_dump(mode="json"))
        )
        envelope = DecisionSubmissionEnvelope.model_validate_json(envelope_bytes)
        question_bytes = await self._artifacts.read(envelope.request.question_context_ref)
        self.context_resolved = isinstance(json.loads(question_bytes), dict)
        corrupt_ref = envelope.request.question_context_ref.model_copy(
            update={"content_hash": "sha256:" + "0" * 64}
        )
        try:
            await self._artifacts.read(corrupt_ref)
        except ArtifactIntegrityError:
            self.corruption_rejected = True

        if "semantic_artifact" in cast(dict[str, Any], arguments["outputs"]):
            semantic_artifact = cast(
                dict[str, Any], cast(dict[str, Any], arguments["outputs"])["semantic_artifact"]
            )
            conflicting_arguments = {
                "outputs": {
                    "semantic_artifact": {
                        **semantic_artifact,
                        "summary": "A conflicting implementation plan.",
                    }
                }
            }
        else:
            original_decision = cast(
                dict[str, Any],
                cast(dict[str, Any], arguments["outputs"])["decision"],
            )
            disposition = original_decision.get("disposition")
            if disposition in {"revise_plan", "plan_revision"}:
                conflicting_decision = {
                    **original_decision,
                    "reason": "A different valid amendment cannot replace staging.",
                }
            elif disposition == "blocked":
                blocker = cast(dict[str, Any], original_decision["blocker"])
                conflicting_decision = {
                    **original_decision,
                    "blocker": {
                        **blocker,
                        "reason": "A different valid blocker cannot replace staging.",
                    },
                }
            else:
                conflicting_decision = {
                    **original_decision,
                    "implementation_notes": "Conflicting retransmission.",
                }
            conflicting_arguments = (
                {
                    "outputs": {
                        "decision": conflicting_decision,
                    }
                }
                if self._arguments is not None
                else {
                    "outputs": {
                        "decision": {
                            "disposition": "proceed",
                            "implementation_notes": "Conflicting retransmission.",
                        }
                    }
                }
            )
        conflict = invocation.model_copy(
            update={
                "answer_attempt_id": "attempt-2",
                "transport_request_id": "request-2",
                "arguments": conflicting_arguments,
            }
        )
        try:
            await typed_submit(conflict)
        except SubmissionRejectedError:
            self.conflict_rejected = True
        if self._authority_change is not None and self._authority_change_after_answer:
            await self._authority_change(context)
        if self._mutate_path_after_submit is not None:
            (Path(context.working_dir) / self._mutate_path_after_submit.name).write_text(
                "post-answer authoritative mutation\n", encoding="utf-8"
            )
        return ExecutionResult(
            success=True,
            completion_cause="terminal_answer_completed",
        )

    async def request_terminal_answer_completion(self) -> None:
        self.terminal_close_calls += 1

    async def cancel(self) -> None:
        return None


class _PlanVerifierRunner:
    def __init__(
        self,
        grade: str,
        runner_type: AgentRunnerType = AgentRunnerType.CODEX_SERVER,
        mutate_path_after_submit: Path | None = None,
    ) -> None:
        self._runner_type = runner_type
        self.execution_context: ExecutionContext | None = None
        self._grade = grade
        self._mutate_path_after_submit = mutate_path_after_submit
        self.terminal_close_calls = 0

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=self._runner_type,
            name="decision-plan-verifier",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        self.execution_context = context
        aliases = list(dict.fromkeys(re.findall(r'"alias"\s*:\s*"(o[1-9][0-9]*)"', context.prompt)))
        assert aliases
        typed_submit = cast(
            Callable[[SubmissionInvocation], Awaitable[SubmissionAcknowledgement]],
            on_submit,
        )
        acknowledgement = await typed_submit(
            SubmissionInvocation(
                execution_id=context.execution_id,
                answer_attempt_id="typed-verifier-attempt-1",
                transport_channel=(
                    "claude_graph_mcp"
                    if self._runner_type == AgentRunnerType.CLI_SUBPROCESS
                    else "codex_dynamic_tool"
                ),
                transport_session_id="typed-verifier-session",
                transport_request_id="typed-verifier-request",
                arguments={
                    "outputs": {
                        "decision": {
                            "findings": [
                                {
                                    "obligation": alias,
                                    "grade": self._grade,
                                    "reason": (
                                        "The exact candidate was assessed against this obligation."
                                    ),
                                    "evidence": [],
                                }
                                for alias in aliases
                            ]
                        }
                    }
                },
            )
        )
        assert acknowledgement.disposition == "durably_staged"
        if self._mutate_path_after_submit is not None:
            (Path(context.working_dir) / self._mutate_path_after_submit.name).write_text(
                "post-answer authoritative mutation\n", encoding="utf-8"
            )
        return ExecutionResult(success=True, completion_cause="terminal_answer_completed")

    async def request_terminal_answer_completion(self) -> None:
        self.terminal_close_calls += 1

    async def cancel(self) -> None:
        return None


class _LegacyWorkerRunner:
    """Produce a real captured candidate through the established worker boundary."""

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name="runtime-check-worker",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        del context, on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        acknowledgement = await on_submit()
        assert acknowledgement.disposition == "durably_staged"
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class _WorkResultRunner:
    """Author a worker result through actual Codex ingress or registered MCP."""

    def __init__(
        self,
        worktree: Path,
        answer: dict[str, Any],
        *,
        expect_rejection: bool = False,
        runner_type: AgentRunnerType = AgentRunnerType.CODEX_SERVER,
        registry: GraphMcpExecutionRegistry | None = None,
        mutate_after_answer: bool = False,
        authority_change: Callable[[ExecutionContext], Awaitable[None]] | None = None,
        revise_after_answer: bool = False,
        answer_factory: Callable[[ExecutionContext], dict[str, Any]] | None = None,
    ) -> None:
        self._worktree = worktree
        self._answer = answer
        self._answer_factory = answer_factory
        self._expect_rejection = expect_rejection
        self._runner_type = runner_type
        self._registry = registry
        self._mutate_after_answer = mutate_after_answer
        self._authority_change = authority_change
        self._revise_after_answer = revise_after_answer
        self._codex: CodexServerAgent | None = None
        self.submission_rejected = False
        self.terminal_close_calls = 0
        self.execute_calls = 0
        self.execution_context: ExecutionContext | None = None

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=self._runner_type,
            name="work-result-runner",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        self.execute_calls += 1
        self.execution_context = context
        if self._answer_factory is not None:
            self._answer = self._answer_factory(context)
        decision = cast(dict[str, Any], self._answer.get("decision", self._answer))
        source_path = self._worktree / "src" / "implemented.py"
        if decision.get("status") == "ready":
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(
                "def implemented() -> str:\n    return 'ready'\n", encoding="utf-8"
            )
        if self._authority_change is not None and not self._revise_after_answer:
            await self._authority_change(context)
        arguments = {
            "outputs": self._answer if "decision" in self._answer else {"decision": self._answer}
        }
        if self._runner_type == AgentRunnerType.CODEX_SERVER:
            transport = ScriptedJsonRpcTransport(
                _handshake_and(_tool_call(7, "submit", arguments), _turn_completed())
            )
            self._codex = CodexServerAgent(api_key=None, _environ={}, _transport=transport)
            try:
                result = await self._codex.execute(
                    context,
                    on_checklist_update,
                    on_submit,
                    on_output,
                    on_grade,
                    on_agent_metadata,
                    on_escalation,
                )
            except SubmissionRejectedError:
                response = next(message for message in transport.sent if message.get("id") == 7)
                self.submission_rejected = not response["result"]["success"]
                assert self._expect_rejection and self.submission_rejected, response
                raise
            response = next(message for message in transport.sent if message.get("id") == 7)
            self.submission_rejected = not response["result"]["success"]
            assert self.submission_rejected is self._expect_rejection, response
        else:
            assert context.graph_mcp_url is not None and self._registry is not None
            client = _GraphMcpProtocolClient(self._registry, context.graph_mcp_url)
            async with client.connected():
                listed = await client.request("tools/list", {})
                names = {tool["name"] for tool in listed["tools"]}
                assert "submit" in names
                assert not names.intersection(
                    {"graph_grade", "submit_graph_patch", "construct_reliable_plan_region"}
                )
                try:
                    acknowledgement = await client.submit(
                        SubmissionInvocation(
                            execution_id=context.execution_id,
                            answer_attempt_id="work-result-attempt-1",
                            transport_channel="claude_graph_mcp",
                            transport_session_id="work-result-session",
                            transport_request_id="work-result-request",
                            arguments=arguments,
                        )
                    )
                except SubmissionRejectedError:
                    assert self._expect_rejection
                    self.submission_rejected = True
                    return ExecutionResult(success=True)
                assert not self._expect_rejection
                assert acknowledgement.disposition == "durably_staged"
            result = ExecutionResult(success=True, completion_cause="terminal_answer_completed")
        if self._authority_change is not None and self._revise_after_answer:
            await self._authority_change(context)
        if self._mutate_after_answer:
            source_path.write_text("post-answer mutation\n", encoding="utf-8")
        return result

    async def request_terminal_answer_completion(self) -> None:
        self.terminal_close_calls += 1
        if self._codex is not None:
            await self._codex.request_terminal_answer_completion()

    async def cancel(self) -> None:
        if self._codex is not None:
            await self._codex.cancel()



async def _dispatch_named_decision_node(
    *,
    controller: GraphController,
    sessions: Any,
    run_id: str,
    node_id: str,
    worktree: Path,
    artifacts: FilesystemArtifactStore,
    registry: GraphMcpExecutionRegistry,
    runner_builder: Callable[[str], Any],
) -> Any:
    """Dispatch one already-planned node through the production executor."""
    async with sessions() as session:
        position = await GraphEventStore(session).current_position(run_id)
    scheduled = await controller.handle_command(
        run_id,
        position,
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {node_id: 100},
        },
    )
    dispatch_item = next(
        item
        for item in scheduled.outbox_items
        if item.kind == "agent_dispatch" and item.payload.get("node_id") == node_id
    )
    projection = await controller.read_projection(run_id)
    lease = next(item for item in leases_view(projection).values() if item.node_id == node_id)
    assert lease.execution_id is not None
    runner = runner_builder(lease.execution_id)

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> Any:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)
    return runner


async def _complete_rejected_initial_plan_scenario(
    *,
    controller: GraphController,
    sessions: Any,
    run_id: str,
    worktree: Path,
    artifacts: FilesystemArtifactStore,
    registry: GraphMcpExecutionRegistry,
) -> None:
    """Complete rejected plan -> rejected repair -> verified repair -> successor."""
    final_plan_id = ""
    for repair_number, verifier_grade in ((1, "F"), (2, "A")):
        projection = await controller.read_projection(run_id)
        correction_id = next(
            node_id
            for node_id in node_kinds_view(projection)
            if (node_payload_view(projection, node_id) or {}).get("role") == "gap_planner"
            and node_states_view(projection).get(node_id) == "planned"
        )
        review_point = f"Repair review point {repair_number}."

        def correction_runner(execution_id: str) -> _DecisionRunner:
            return _DecisionRunner(
                controller,
                sessions,
                artifacts,
                execution_id,
                runner_type=AgentRunnerType.CODEX_SERVER,
                graph_mcp_registry=registry,
                arguments={
                    "outputs": {
                        "decision": {
                            "disposition": "plan_revision",
                            "reason": f"Repair rejected plan attempt {repair_number}.",
                            "amendment": {
                                "refinements": [
                                    {
                                        "batch": "parser",
                                        "review_points": [review_point],
                                    }
                                ]
                            },
                        }
                    }
                },
            )

        await _dispatch_named_decision_node(
            controller=controller,
            sessions=sessions,
            run_id=run_id,
            node_id=correction_id,
            worktree=worktree,
            artifacts=artifacts,
            registry=registry,
            runner_builder=correction_runner,
        )
        repaired = await controller.read_projection(run_id)
        final_plan_id = next(
            record.record_id
            for record in output_record_payloads_view(repaired).values()
            if record.record_type == "semantic_artifact"
            and record.producer_node_id == correction_id
        )
        verifier_id = next(
            node_id
            for node_id in node_kinds_view(repaired)
            if node_states_view(repaired).get(node_id) == "planned"
            and (node_payload_view(repaired, node_id) or {}).get("semantic_stage")
            == "plan_verification"
            and (node_payload_view(repaired, node_id) or {}).get(
                "accepted_plan_amendment_record_id"
            )
            == final_plan_id
        )
        await _dispatch_named_decision_node(
            controller=controller,
            sessions=sessions,
            run_id=run_id,
            node_id=verifier_id,
            worktree=worktree,
            artifacts=artifacts,
            registry=registry,
            runner_builder=lambda _execution_id, grade=verifier_grade: _PlanVerifierRunner(
                grade,
                AgentRunnerType.CODEX_SERVER,
            ),
        )
        verified = await controller.read_projection(run_id)
        report = next(
            record
            for record in output_record_payloads_view(verified).values()
            if record.record_type == "verification_report"
            and record.producer_node_id == verifier_id
        )
        assert report.outcome == ("passed" if verifier_grade == "A" else "failed")

    final_projection = await controller.read_projection(run_id)
    successor_id = next(
        node_id
        for node_id in node_kinds_view(final_projection)
        if node_states_view(final_projection).get(node_id) == "planned"
        and (node_payload_view(final_projection, node_id) or {}).get("semantic_stage")
        == "successor_planning"
        and (node_payload_view(final_projection, node_id) or {}).get(
            "accepted_plan_amendment_record_id"
        )
        == final_plan_id
    )
    await _dispatch_named_decision_node(
        controller=controller,
        sessions=sessions,
        run_id=run_id,
        node_id=successor_id,
        worktree=worktree,
        artifacts=artifacts,
        registry=registry,
        runner_builder=lambda execution_id: _DecisionRunner(
            controller,
            sessions,
            artifacts,
            execution_id,
            runner_type=AgentRunnerType.CODEX_SERVER,
            graph_mcp_registry=registry,
        ),
    )
    completed = await controller.read_projection(run_id)
    assert node_states_view(completed)[successor_id] == "completed"


async def _exercise_initial_discovery_brief(
    tmp_path: Path,
    *,
    verifier_grade: str,
    mutate_after_answer: bool,
) -> None:
    worktree = tmp_path / "initial-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "initial-decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "initial-decision-product"
    registry = GraphMcpExecutionRegistry()
    raw_seed_events = _events_for_runner(
        _durable_initial_events(), AgentRunnerType.CODEX_SERVER
    )
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in raw_seed_events
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "initial-artifacts")
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        runner_type=AgentRunnerType.CODEX_SERVER,
        graph_mcp_registry=registry,
        arguments={
            "outputs": {
                "decision": {
                    "questions": ["Which parser seam should own the feature?"],
                    "rationale": "Repository ownership requires inspection.",
                    "focus": ["docs/spec.md"],
                }
            }
        },
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)
    assert runner.execution_context is not None

    restarted = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    final = await restarted.read_projection(run_id)
    async with sessions() as session:
        diagnostic_events = await GraphEventStore(session).read_run(run_id)
    assert node_states_view(final)["planner-plan"] == "completed", " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
        for event in diagnostic_events[-20:]
    )
    decision_records = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    assert len(decision_records) == 1
    assert decision_records[0].value.family == "discovery_brief"
    assert decision_records[0].value.bound_input_record_ids == [
        "routine-snapshot-record",
        "requirement-dynamic-feature-acceptance",
    ]
    semantic_stages = {
        payload.get("semantic_stage")
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
    }
    assert {"discovery", "plan_verification"}.issubset(semantic_stages)
    assert "successor_planning" not in semantic_stages
    assert runner.stage_was_effect_free
    assert runner.terminal_close_calls == 1

    discovery_id = next(
        node_id
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
        and payload.get("semantic_stage") == "discovery"
        and isinstance(payload.get("decision_successor_node_id"), str)
    )
    verifier_id = next(
        node_id
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
        and payload.get("semantic_stage") == "plan_verification"
    )
    discovery_payload = node_payload_view(final, discovery_id)
    assert discovery_payload is not None
    successor_id = cast(str, discovery_payload["decision_successor_node_id"])
    discovery_scheduled = await controller.handle_command(
        run_id,
        max(event.position for event in diagnostic_events),
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {discovery_id: 100, verifier_id: 50},
        },
    )
    discovery_item = next(
        item for item in discovery_scheduled.outbox_items if item.kind == "agent_dispatch"
    )
    discovery_projection = await controller.read_projection(run_id)
    discovery_lease = next(
        item for item in leases_view(discovery_projection).values() if item.node_id == discovery_id
    )
    assert discovery_lease.execution_id is not None
    plan_runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        discovery_lease.execution_id,
        runner_type=AgentRunnerType.CODEX_SERVER,
        graph_mcp_registry=registry,
        arguments={
            "outputs": {
                "semantic_artifact": {
                    "summary": "Implement and validate the bounded parser feature.",
                    "batches": [
                        {
                            "key": "parser",
                            "objective": "Implement the bounded parser feature.",
                            "scope": ["src/parser.py", "tests/unit/test_parser.py"],
                            "requirements": ["r1"],
                            "acceptance": [
                                "The parser satisfies the supplied feature specification."
                            ],
                            "checks": [
                                {
                                    "name": "parser unit tests",
                                    "command_definition": {
                                        "argv": [
                                            "uv",
                                            "run",
                                            "pytest",
                                            "tests/unit/test_parser.py",
                                        ]
                                    },
                                }
                            ],
                        },
                    ],
                }
            }
        },
    )

    def build_plan_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return plan_runner

    plan_executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_plan_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await plan_executor.dispatch(discovery_item)
    await plan_executor.wait_for_all(timeout_seconds=10)
    assert plan_runner.execution_context is not None
    plan_projection = await controller.read_projection(run_id)
    async with sessions() as session:
        plan_diagnostic_events = await GraphEventStore(session).read_run(run_id)
    plan_records = [
        record
        for record in output_record_payloads_view(plan_projection).values()
        if record.record_type == "semantic_artifact" and record.producer_node_id == discovery_id
    ]
    assert len(plan_records) == 1, " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
        for event in plan_diagnostic_events[-30:]
    )
    plan_record = plan_records[0]
    assert plan_record.value.schema_id == "orchestrator.reliable-plan.decision-plan"
    assert plan_record.value.requirement_ids == ["dynamic_feature_acceptance"]
    assert plan_record.value.provenance == {
        "source": "agent_submit",
        "execution_id": discovery_lease.execution_id,
    }
    assert plan_runner.execution_context is not None
    assert plan_runner.execution_context is not runner.execution_context
    assert plan_runner.execution_context.execution_id != runner.execution_context.execution_id
    assert Path(plan_runner.execution_context.working_dir) != worktree
    assert (
        subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert node_states_view(plan_projection)[successor_id] == "planned"
    assert not any(
        record.record_type == "verification_report" and record.producer_node_id == verifier_id
        for record in output_record_payloads_view(plan_projection).values()
    )
    async with sessions() as session:
        plan_events = await GraphEventStore(session).read_run(run_id)

    verifier_scheduled = await controller.handle_command(
        run_id,
        max(event.position for event in plan_events),
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {verifier_id: 100, successor_id: 1},
        },
    )
    verifier_item = next(
        item for item in verifier_scheduled.outbox_items if item.kind == "agent_dispatch"
    )
    verifier_projection = await controller.read_projection(run_id)
    verifier_lease = next(
        item for item in leases_view(verifier_projection).values() if item.node_id == verifier_id
    )
    assert verifier_lease.execution_id is not None
    verifier_runner = _PlanVerifierRunner(
        verifier_grade,
        AgentRunnerType.CODEX_SERVER,
        mutate_path_after_submit=worktree / "README.md" if mutate_after_answer else None,
    )

    def build_verifier_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _PlanVerifierRunner:
        del run_id, phase
        return verifier_runner

    verifier_executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_verifier_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await verifier_executor.dispatch(verifier_item)
    await verifier_executor.wait_for_all(timeout_seconds=10)
    assert verifier_runner.execution_context is not None
    verified = await controller.read_projection(run_id)
    reports = [
        record
        for record in output_record_payloads_view(verified).values()
        if record.record_type == "verification_report" and record.producer_node_id == verifier_id
    ]
    async with sessions() as session:
        verifier_diagnostic_events = await GraphEventStore(session).read_run(run_id)
    expected_report_count = 0 if mutate_after_answer else 1
    assert len(reports) == expected_report_count, " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
        for event in verifier_diagnostic_events[-30:]
    )
    if mutate_after_answer:
        assert any(
            event.event_type == "runner_recovery_requested"
            and event.payload.get("execution_id") == verifier_lease.execution_id
            for event in verifier_diagnostic_events
        )
        assert not any(
            event.event_type == "graph_patch_accepted"
            and event.payload.get("proposed_by_node_id") == verifier_id
            for event in verifier_diagnostic_events
        )
        await engine.dispose()
        return
    if verifier_grade == "F":
        assert reports[0].outcome == "failed"
        assert node_states_view(verified)[successor_id] == "planned"
        await _complete_rejected_initial_plan_scenario(
            controller=controller,
            sessions=sessions,
            run_id=run_id,
            worktree=worktree,
            artifacts=artifacts,
            registry=registry,
        )
        await engine.dispose()
        return
    assert reports[0].outcome == "passed"
    assert reports[0].evaluated_record_ids == [
        "requirement-dynamic-feature-acceptance",
        plan_record.record_id,
    ]
    assert verifier_runner.execution_context is not None
    assert verifier_runner.execution_context.execution_id == verifier_lease.execution_id
    assert (
        plan_runner.execution_context.execution_id != verifier_runner.execution_context.execution_id
    )
    async with sessions() as session:
        verified_events = await GraphEventStore(session).read_run(run_id)

    successor_scheduled = await controller.handle_command(
        run_id,
        max(event.position for event in verified_events),
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {successor_id: 100},
        },
    )
    successor_dispatches = [
        item.kind == "agent_dispatch" and item.payload.get("node_id") == successor_id
        for item in successor_scheduled.outbox_items
    ]
    assert any(successor_dispatches)
    successor_item = next(
        item
        for item in successor_scheduled.outbox_items
        if item.kind == "agent_dispatch" and item.payload.get("node_id") == successor_id
    )
    successor_projection = await controller.read_projection(run_id)
    successor_lease = next(
        item
        for item in leases_view(successor_projection).values()
        if item.node_id == successor_id
    )
    assert successor_lease.execution_id is not None
    successor_runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        successor_lease.execution_id,
        runner_type=AgentRunnerType.CODEX_SERVER,
        graph_mcp_registry=registry,
    )

    def build_successor_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return successor_runner

    successor_executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_successor_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await successor_executor.dispatch(successor_item)
    await successor_executor.wait_for_all(timeout_seconds=10)
    assert successor_runner.execution_context is not None
    joined = await controller.read_projection(run_id)

    successor_answers = [
        record
        for record in output_record_payloads_view(joined).values()
        if record.record_type == "decision_answer" and record.producer_node_id == successor_id
    ]
    assert len(successor_answers) == 1
    assert successor_answers[0].value.family == "batch_decision"
    assert node_states_view(joined)[successor_id] == "completed"
    assert not any(lease.state == "active" for lease in leases_view(joined).values())
    assert all(
        attempt.state == "finalized" for attempt in execution_attempts_view(joined).values()
    )
    assert successor_runner.execution_context is not None
    assert successor_runner.execution_context.execution_id not in {
        runner.execution_context.execution_id,
        plan_runner.execution_context.execution_id,
        verifier_runner.execution_context.execution_id,
    }
    assert any(
        (node_payload_view(joined, node_id) or {}).get("semantic_stage") == "effectful_batch"
        for node_id in node_kinds_view(joined)
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_initial_discovery_brief_runs_through_production_dispatch_and_finalization(
    tmp_path: Path,
) -> None:
    await _exercise_initial_discovery_brief(
        tmp_path,
        verifier_grade="A",
        mutate_after_answer=False,
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_initial_discovery_failed_verifier_recovers_through_verified_second_repair(
    tmp_path: Path,
) -> None:
    await _exercise_initial_discovery_brief(
        tmp_path,
        verifier_grade="F",
        mutate_after_answer=False,
    )


@pytest.mark.asyncio
async def test_initial_discovery_verifier_post_answer_mutation_publishes_no_effects(
    tmp_path: Path,
) -> None:
    await _exercise_initial_discovery_brief(
        tmp_path,
        verifier_grade="A",
        mutate_after_answer=True,
    )


@pytest.mark.asyncio
async def test_claude_cli_decision_dispatch_uses_a_live_per_execution_graph_mcp_route(
    tmp_path: Path,
) -> None:
    """The supported CLI adapter receives the same typed decision contract."""
    worktree = tmp_path / "cli-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "cli-decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "cli-decision-product"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _ordered_decision_seed_events(AgentRunnerType.CLI_SUBPROCESS)
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "cli-decision-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "cli-artifacts")
    registry = GraphMcpExecutionRegistry()
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        runner_type=AgentRunnerType.CLI_SUBPROCESS,
        graph_mcp_registry=registry,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CLI_SUBPROCESS,
            {"command": "claude"},
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    answers = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    assert len(answers) == 1
    assert answers[0].value.family == "batch_decision"
    assert node_states_view(final)["planner-plan"] == "completed"
    assert runner.graph_mcp_was_registered
    assert runner.execution_context is not None
    assert runner.execution_context.submission_contract is not None
    assert runner.execution_context.submission_contract.interaction_contract == "decision-v1"
    await engine.dispose()


@pytest.mark.asyncio
async def test_rejected_batch_dispatches_a_bounded_correction_decision(
    tmp_path: Path,
) -> None:
    """A failed batch offers exact evidence to one production correction answer."""
    worktree = tmp_path / "correction-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "correction-decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "correction-decision-product"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _correction_seed_events()
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "correction-decision-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "correction-artifacts")
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        arguments={
            "outputs": {
                "decision": {
                    "disposition": "corrective_work",
                    "diagnosis": "The accepted batch failed its required check.",
                    "remedy": "Repair only the failed batch implementation.",
                    "focus": ["src/core.py"],
                    "evidence": ["e1", "e2"],
                }
            }
        },
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    answers = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    gap_records = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "classified_gap"
    ]
    assert len(answers) == 1
    assert answers[0].value.family == "correction_decision"
    assert len(gap_records) == 1
    assert gap_records[0].value.classification == "corrective_work_required"
    assert node_states_view(final)["planner-plan"] == "completed"
    assert any(
        (node_payload_view(final, node_id) or {}).get("semantic_stage") == "corrective_work"
        for node_id in node_kinds_view(final)
    )
    assert not any(lease.state == "active" for lease in leases_view(final).values())
    assert all(attempt.state == "finalized" for attempt in execution_attempts_view(final).values())
    assert runner.terminal_close_calls == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_rejected_plan_repair_post_answer_mutation_publishes_no_effects(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "rejected-plan-repair-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "rejected-plan-repair.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "rejected-plan-repair-mutation"
    raw_events, gap_id = _ordered_rejected_amendment_seed_events(
        AgentRunnerType.CODEX_SERVER
    )
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in raw_events
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events)
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "rejected-plan-repair-base",
            "max_grants": 1,
            "priorities": {gap_id: 100},
        },
    )
    assert scheduled.outbox_items, [
        (event.event_type, event.payload) for event in scheduled.events
    ]
    dispatch_item = next(
        item
        for item in scheduled.outbox_items
        if item.kind == "agent_dispatch" and item.payload.get("node_id") == gap_id
    )
    projection = await controller.read_projection(run_id)
    lease = next(item for item in leases_view(projection).values() if item.node_id == gap_id)
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "rejected-plan-repair-artifacts")

    async def revise_bound_requirement(_context: ExecutionContext) -> None:
        async with sessions() as session:
            position = await GraphEventStore(session).current_position(run_id)
        changed = await controller.handle_command(
            run_id,
            position,
            "record_requirement_revision",
            {
                "requirement_id": "REQ-2",
                "version_id": "repair-authority-v2",
                "classification": "semantic",
                "node_id": "requirement-2",
            },
        )
        assert any(
            event.event_type == "requirement_revision_recorded" for event in changed.events
        )

    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        arguments={
            "outputs": {
                "decision": {
                    "disposition": "plan_revision",
                    "reason": "Resolve the exact plan-verifier finding.",
                    "amendment": {
                        "refinements": [
                            {
                                "batch": "api",
                                "review_points": ["Confirm the rejected-plan remedy."],
                            }
                        ]
                    },
                }
            }
        },
        authority_change=revise_bound_requirement,
        authority_change_after_answer=True,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
    gap_outputs = [
        record
        for record in output_record_payloads_view(final).values()
        if record.producer_node_id == gap_id
    ]
    assert not any(
        record.record_type in {"decision_answer", "semantic_artifact", "classified_gap"}
        for record in gap_outputs
    )
    assert [record.record_type for record in gap_outputs] == ["failure_record"]
    assert not any(
        event.event_type == "graph_patch_accepted"
        and event.payload.get("proposed_by_node_id") == gap_id
        for event in events
    )
    assert node_states_view(final)[gap_id] == "failed"
    await engine.dispose()


def _init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)
    (path / "README.md").write_text("decision runtime\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "initial"], check=True)


def _runtime_check_seed_events(
    worktree: Path,
    *,
    check_exit_code: int,
) -> list[Any]:
    """Build a durable exact-candidate verifier topology before check execution."""
    assert worktree.is_dir()
    raw_events = _verification_events()
    cache_authority_hash = next(
        event.payload["cache_authority_hash"]
        for event in raw_events
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    removed_record_id = "check-core-record-1"
    filtered: list[Any] = []
    for event in raw_events:
        payload = deepcopy(event.payload)
        if event.event_type == "output_record_accepted" and payload.get("record_id") in {
            removed_record_id,
            "candidate-core-record",
        }:
            continue
        if event.event_type == "file_state_accepted" and payload.get("record_id") == (
            "file-state-core-record"
        ):
            continue
        if event.event_type == "input_bound" and removed_record_id in payload.get("record_ids", []):
            continue
        if event.event_type == "input_bound" and "candidate-core-record" in payload.get(
            "record_ids", []
        ):
            continue
        if event.event_type == "node_created":
            node_id = payload.get("node_id")
            if node_id == "requirement-core":
                payload.update(
                    {
                        "state": "completed",
                        "outputs": [
                            {
                                "port": "requirement",
                                "direction": "output",
                                "schema": "RequirementRecord",
                                "record_layers": ["graph_record"],
                            }
                        ],
                    }
                )
            elif node_id == "worker-core":
                payload.update(
                    {
                        "state": "planned",
                        "role": "builder",
                        "access_mode": "write",
                        "effect_contract": "effectful_write",
                        "candidate_id": "candidate-core-record",
                        "cache_authority_hash": cache_authority_hash,
                        "reliable_plan_selected_runner_type": "codex_server",
                        "runner_model_override": "test-model",
                        "profile": "coder",
                        "outputs": [
                            {
                                "port": "candidate",
                                "direction": "output",
                                "schema": "ImplementationCandidate",
                            },
                            {
                                "port": "file_state",
                                "direction": "output",
                                "schema": "FileStateRecord",
                            },
                        ],
                    }
                )
            elif node_id == "check-core-1":
                payload.update(
                    {
                        "state": "planned",
                        "cache_authority_hash": cache_authority_hash,
                        "inputs": [
                            {
                                "port": "candidate_under_test",
                                "direction": "input",
                                "schema": "ImplementationCandidate",
                                "required": True,
                            }
                        ],
                        "outputs": [
                            {
                                "port": "check_result",
                                "direction": "output",
                                "schema": "CheckResult",
                                "required": True,
                            }
                        ],
                        "command_definition": {
                            "id": "command-core-1",
                            "argv": [
                                "sh",
                                "-c",
                                f"printf runtime-check-ran; exit {check_exit_code}",
                            ],
                            "timeout_seconds": 5.0,
                        },
                    }
                )
            elif node_id == "planner-plan":
                payload.update(
                    {
                        "state": "planned",
                        "reliable_plan_selected_runner_type": "codex_server",
                        "runner_model_override": "test-model",
                        "profile": "coder",
                    }
                )
        if event.event_type == "edge_created":
            payload.setdefault("dependency_type", "input_binding")
            if payload.get("edge_id") == "edge-worker-candidate-to-verifier":
                payload["accepted_record_selector"] = {
                    "record_id": "candidate-core-record",
                    "record_type": "candidate",
                }
            elif payload.get("edge_id") == "edge-requirement-to-verifier":
                payload["accepted_record_selector"] = {
                    "record_id": "requirement-core-record",
                    "record_type": "requirement_record",
                }
            elif payload.get("edge_id") == "edge-check-core-1-to-verifier":
                payload["accepted_record_selector"] = {"record_type": "check_result"}
        filtered.append(
            event.model_copy(
                update={
                    "event_type": (
                        "output_record_accepted"
                        if event.event_type == "file_state_accepted"
                        else event.event_type
                    ),
                    "payload": payload,
                }
            )
        )

    insert_at = next(
        index
        for index, event in enumerate(filtered)
        if event.event_type == "edge_created"
        and event.payload.get("edge_id") == "edge-worker-candidate-to-verifier"
    )
    candidate_to_check = [
        graph_event(
            "edge_created",
            {
                "edge_id": "edge-worker-candidate-to-check",
                "from_node_id": "worker-core",
                "from_port": "candidate",
                "to_node_id": "check-core-1",
                "to_port": "candidate_under_test",
                "required": True,
                "dependency_type": "input_binding",
                "accepted_record_selector": {
                    "record_id": "candidate-core-record",
                    "record_type": "candidate",
                },
            },
        )
    ]
    filtered[insert_at:insert_at] = candidate_to_check
    positioned: list[Any] = []
    for position, event in enumerate(filtered, 1):
        payload = dict(event.payload)
        if event.event_type in {"output_record_accepted", "file_state_accepted"}:
            if event.event_type == "output_record_accepted":
                payload["graph_position"] = position
        positioned.append(event.model_copy(update={"position": position, "payload": payload}))
    output: list[Any] = []
    for event in positioned:
        payload = dict(event.payload)
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["record_bound_positions"] = {
                record_id: event.position for record_id in record_ids
            }
            payload["bound_at_position"] = event.position
        output.append(event.model_copy(update={"payload": payload}))
    return output

async def _exercise_completion_witness_race(
    tmp_path: Path,
    *,
    cancel_after_witness: bool,
) -> None:
    worktree = tmp_path / "worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    boundary_observer = _BoundaryRestartObserver()
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
        command_commit_observer=boundary_observer,
    )
    run_id = "decision-run"
    source_events = decision_successor_events()
    baseline_position = max(event.position for event in source_events)
    source_events.extend(
        [
            graph_event(
                "edge_created",
                {
                    "edge_id": "baseline-plan-verifier-input",
                    "from_node_id": "worker-discovery",
                    "from_port": "semantic_artifact",
                    "to_node_id": "verifier-plan",
                    "to_port": "semantic_artifact",
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {
                        "record_id": "accepted-decision-plan",
                        "record_type": "semantic_artifact",
                    },
                },
                position=baseline_position + 1,
            ),
            graph_event(
                "input_bound",
                {
                    "edge_id": "baseline-plan-verifier-input",
                    "to_node_id": "verifier-plan",
                    "to_port": "semantic_artifact",
                    "record_ids": ["accepted-decision-plan"],
                    "bound_at_position": baseline_position + 2,
                    "record_bound_positions": {"accepted-decision-plan": baseline_position + 2},
                },
                position=baseline_position + 2,
            ),
        ]
    )
    planner_authority = next(
        event.payload
        for event in source_events
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
    )
    cache_authority_hash = next(
        event.payload["cache_authority_hash"]
        for event in source_events
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    seed_events = []
    for event in source_events:
        payload = dict(event.payload)
        if event.event_type == "node_created":
            payload.setdefault("cache_authority_hash", cache_authority_hash)
        if event.event_type == "node_created" and payload.get("node_id") == "root":
            for key in (
                "reliable_plan_skeleton_id",
                "reliable_plan_assignment_carrier",
                "reliable_plan_qualification_evidence_hash",
            ):
                payload[key] = planner_authority[key]
            payload["reliable_plan_selected_runner_type"] = "codex_server"
            payload["reliable_plan_assignment_role"] = "planner"
            payload["runner_model_override"] = "test-model"
            payload["profile"] = "architect"
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload["state"] = "planned"
            payload["reliable_plan_assignment_role"] = "successor_planner"
            payload["reliable_plan_selected_runner_type"] = "codex_server"
            payload["runner_model_override"] = "test-model"
            payload["profile"] = "architect"
        if event.event_type == "edge_created":
            selector = payload.get("accepted_record_selector")
            if isinstance(selector, dict) and "record_type" not in selector:
                record_type = {
                    "semantic_artifact": "semantic_artifact",
                    "verification_report": "verification_report",
                }.get(str(payload.get("to_port")), "requirement_record")
                payload["accepted_record_selector"] = {
                    **selector,
                    "record_type": record_type,
                }
        seed_events.append(event.model_copy(update={"run_id": run_id, "payload": payload}))
    requirement_events = [
        event
        for event in seed_events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "requirement_record"
    ]
    seed_events = [event for event in seed_events if event not in requirement_events]
    plan_index = next(
        index
        for index, event in enumerate(seed_events)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    seed_events[plan_index:plan_index] = requirement_events
    positioned_seed_events = []
    for position, event in enumerate(seed_events, start=1):
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        positioned_seed_events.append(
            event.model_copy(update={"position": position, "payload": payload})
        )
    seed_events = []
    for event in positioned_seed_events:
        payload = dict(event.payload)
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = event.position
            payload["record_bound_positions"] = {
                record_id: event.position for record_id in record_ids
            }
        seed_events.append(event.model_copy(update={"payload": payload}))
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "decision-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    assert scheduled.outbox_items, [(event.event_type, event.payload) for event in scheduled.events]
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await asyncio.wait_for(boundary_observer.stage_committed.wait(), timeout=5)
    stage_restart = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    staged_projection = await stage_restart.read_projection(run_id)
    assert execution_attempts_view(staged_projection)[cast(str, lease.execution_id)].state == (
        "submission_staged"
    )
    boundary_observer.release_stage.set()
    await asyncio.wait_for(boundary_observer.witness_committed.wait(), timeout=5)
    witness_restart = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    witnessed_projection = await witness_restart.read_projection(run_id)
    assert execution_attempts_view(witnessed_projection)[cast(str, lease.execution_id)].state == (
        "completion_witnessed"
    )
    async with sessions() as session:
        witnessed_position = await GraphEventStore(session).current_position(run_id)
    if cancel_after_witness:
        cancelled = await witness_restart.handle_command(
            run_id,
            witnessed_position,
            "cancel",
            {"trigger": "serialized_test_cancellation"},
        )
        assert any(event.event_type == "run_lifecycle_changed" for event in cancelled.events)
    boundary_observer.release_witness.set()
    await executor.wait_for_all(timeout_seconds=10)

    async with sessions() as diagnostic_session:
        diagnostic_events = await GraphEventStore(diagnostic_session).read_run(run_id)
    assert runner.stage_was_effect_free, " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}:{event.payload.get('new_state')}"
        for event in diagnostic_events[-20:]
    )
    assert runner.context_resolved
    assert runner.corruption_rejected
    assert runner.duplicate_acknowledgement is not None
    assert runner.duplicate_acknowledgement.disposition == "durably_staged"
    assert runner.conflict_rejected
    assert runner.terminal_close_calls == 1

    restarted_controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    final_projection = await restarted_controller.read_projection(run_id)
    assert node_states_view(final_projection)["planner-plan"] == (
        "cancelled" if cancel_after_witness else "completed"
    )
    decision_records = [
        record
        for record in output_record_payloads_view(final_projection).values()
        if record.record_type == "decision_answer"
    ]
    assert bool(decision_records) is not cancel_after_witness
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
        outbox = list(
            (
                await session.execute(
                    select(GraphOutboxModel).where(GraphOutboxModel.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
    finalizations = [event for event in events if event.event_type == "runner_execution_finalized"]
    decision_patches = [
        event
        for event in events
        if event.event_type == "graph_patch_accepted"
        and event.payload.get("proposed_by_node_id") == "planner-plan"
    ]
    decision_outputs = [
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "decision_answer"
    ]
    terminal_transitions = [
        event
        for event in events
        if event.event_type == "node_state_changed"
        and event.payload.get("node_id") == "planner-plan"
        and event.payload.get("new_state") == "completed"
    ]
    expected_effect_count = 0 if cancel_after_witness else 1
    assert len(finalizations) == expected_effect_count
    assert len(decision_patches) == expected_effect_count
    assert len(decision_outputs) == expected_effect_count
    assert len(terminal_transitions) == expected_effect_count
    assert outbox
    assert {row.event_id for row in outbox}.issubset({event.event_id for event in events})
    await engine.dispose()


@pytest.mark.asyncio
async def test_decision_finalizes_once_after_durable_completion_witness(
    tmp_path: Path,
) -> None:
    await _exercise_completion_witness_race(tmp_path, cancel_after_witness=False)


@pytest.mark.asyncio
async def test_cancellation_after_completion_witness_wins_before_atomic_finalization(
    tmp_path: Path,
) -> None:
    await _exercise_completion_witness_race(tmp_path, cancel_after_witness=True)
