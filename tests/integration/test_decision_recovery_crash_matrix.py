"""Decision-v1 crash boundaries through production recovery."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType
from sqlalchemy import select

from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    FakeClock,
    SequentialIdGenerator,
    execution_attempts_view,
    leases_view,
    node_states_view,
    output_record_payloads_view,
    StoredArtifactRef,
)
from orchestrator.graph_runtime import (
    CrashBarrierPoint,
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    recover,
    reconcile_runtime,
    replay_decision_answer_receipt,
    resolve_orchestrator_source_root,
    StaticGraphAgentFactory,
)
from orchestrator.runners import (
    AgentExecutionError,
    ExecutionResult,
    SubmissionAcknowledgement,
    SubmissionInvocation,
    SubmissionRejectedError,
)
from tests.integration.test_graph_decision_runtime import (
    _DecisionRunner,
    _init_repo,
)
from tests.unit.graph_test_utils import event as graph_event
from tests.unit.test_graph_decisions import decision_successor_events


class _ProcessCrash(BaseException):
    """Stand-in for the child disappearing at an exact durable boundary."""


class _CrashAtBoundary:
    def __init__(self, point: CrashBarrierPoint) -> None:
        self.point = point
        self.reached = asyncio.Event()

    async def wait_if_armed(
        self,
        *,
        run_id: str,
        execution_id: str,
        point: CrashBarrierPoint,
        observation: Any = None,
    ) -> None:
        del run_id, execution_id, observation
        if point == self.point:
            self.reached.set()
            raise _ProcessCrash(point)

    def read_status(self) -> None:
        return None


class _EnvironmentRejectedDecisionRunner(_DecisionRunner):
    """Represent an adapter propagating a non-correctable callback rejection."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise SubmissionRejectedError(
            SubmissionAcknowledgement(
                disposition="rejected",
                message="validation environment is unavailable",
                rejection_category="validation_environment_blocked",
            )
        )


class _ProcessFailedDecisionRunner(_DecisionRunner):
    """Represent a provider-neutral runner process failure."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AgentExecutionError("codex_server", "provider process exited")


class _RejectionBudgetDecisionRunner(_DecisionRunner):
    """Exercise trusted ingress identities without provider-specific retry state."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.acknowledgements: list[SubmissionAcknowledgement] = []
        self.authored_delivery_count = 0
        self.rejection_stop_calls = 0

    async def request_submission_rejection_stop(self) -> None:
        self.rejection_stop_calls += 1

    async def execute(
        self,
        _context: Any,
        _on_checklist_update: Any,
        on_submit: Any,
        **_kwargs: Any,
    ) -> ExecutionResult:
        invalid_arguments = {"outputs": {"decision": {"disposition": "not-a-batch-decision"}}}
        first = SubmissionInvocation(
            execution_id=self._execution_id,
            answer_attempt_id="answer-1",
            transport_channel="trusted-test-ingress",
            transport_session_id="session-before-restart",
            transport_request_id="delivery-1",
            arguments=invalid_arguments,
        )
        self.authored_delivery_count += 1
        for invocation in (first, first):
            try:
                await on_submit(invocation)
            except SubmissionRejectedError as exc:
                self.acknowledgements.append(exc.acknowledgement)

        fresh = GraphController(
            self._sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
        )
        after_redelivery = execution_attempts_view(await fresh.read_projection(_context.run_id))[
            self._execution_id
        ]
        assert len(after_redelivery.decision_answer_rejections) == 1

        second = first.model_copy(
            update={
                "answer_attempt_id": "answer-2",
                "transport_session_id": "session-after-restart",
                "transport_request_id": "delivery-2",
            }
        )
        self.authored_delivery_count += 1
        try:
            await on_submit(second)
        except SubmissionRejectedError as exc:
            self.acknowledgements.append(exc.acknowledgement)

        after_second = execution_attempts_view(await fresh.read_projection(_context.run_id))[
            self._execution_id
        ]
        assert len(after_second.decision_answer_rejections) == 2
        return ExecutionResult(success=True)


def _decision_seed(run_id: str) -> list[Any]:
    """Use the same generated successor graph as the production decision test."""
    source_events = decision_successor_events()
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
    output: list[Any] = []
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
            payload.update(
                {
                    "reliable_plan_selected_runner_type": "codex_server",
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
                    "reliable_plan_selected_runner_type": "codex_server",
                    "runner_model_override": "test-model",
                    "profile": "architect",
                }
            )
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
        output.append(event.model_copy(update={"run_id": run_id, "payload": payload}))

    requirement_events = [
        event
        for event in output
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "requirement_record"
    ]
    output = [event for event in output if event not in requirement_events]
    plan_index = next(
        index
        for index, event in enumerate(output)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    output[plan_index:plan_index] = requirement_events
    positioned: list[Any] = []
    for position, event in enumerate(output, start=1):
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        positioned.append(event.model_copy(update={"position": position, "payload": payload}))
    final: list[Any] = []
    for event in positioned:
        payload = dict(event.payload)
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = event.position
            payload["record_bound_positions"] = {
                record_id: event.position for record_id in record_ids
            }
        final.append(event.model_copy(update={"payload": payload}))
    return final


@pytest.mark.parametrize(
    "point",
    [
        "pre_stage",
        "after_staging_pre_witness",
        "after_witness_pre_finalization",
        "after_commit_pre_ack",
    ],
)
@pytest.mark.asyncio
async def test_decision_v1_crash_matrix_replays_without_duplicate_effects(
    tmp_path: Path,
    point: CrashBarrierPoint,
) -> None:
    worktree = tmp_path / "worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "decision-crash.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
    )
    run_id = f"decision-crash-{point}"
    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {"events": _decision_seed(run_id)},
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {"base_snapshot_id": "decision-crash-base", "max_grants": 1},
        )
        dispatch_item = next(
            item for item in scheduled.outbox_items if item.kind == "agent_dispatch"
        )
        projection = await controller.read_projection(run_id)
        lease = next(
            lease for lease in leases_view(projection).values() if lease.node_id == "planner-plan"
        )
        assert lease.execution_id is not None
        artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
        runner = _DecisionRunner(controller, sessions, artifacts, lease.execution_id)
        barrier = _CrashAtBoundary(point)

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
            StaticGraphAgentFactory(AgentRunnerType.CODEX_SERVER, runner_builder=build_runner),
            worktree_path=worktree,
            artifact_store=artifacts,
            crash_barrier=barrier,
        )
        await executor.dispatch(dispatch_item)
        await executor.wait_for_all(timeout_seconds=10)
        assert barrier.reached.is_set()

        final_projection = projection
        events: list[Any] = []
        stable_counts: dict[str, int] | None = None
        for _restart_index in range(3):
            restarted_controller = GraphController(
                sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
            )
            restarted_executor = GraphDispatchExecutor(
                sessions,
                restarted_controller,
                StaticGraphAgentFactory(
                    AgentRunnerType.CODEX_SERVER,
                    runner_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        AssertionError("decision recovery must not redispatch the model")
                    ),
                ),
                worktree_path=worktree,
                artifact_store=artifacts,
            )
            outbox = OutboxDispatcher(sessions, restarted_executor, FakeClock())
            report = await recover(sessions, outbox, run_id=run_id)
            await reconcile_runtime(restarted_controller, restarted_executor, report, outbox)
            final_projection = await restarted_controller.read_projection(run_id)
            async with sessions() as session:
                events = await GraphEventStore(session).read_run(run_id)
            current_counts = {
                event_type: sum(event.event_type == event_type for event in events)
                for event_type in (
                    "runner_submission_staged",
                    "runner_completion_witnessed",
                    "runner_execution_finalized",
                    "decision_answer_rejected",
                )
            }
            if stable_counts is not None:
                assert current_counts == stable_counts
            stable_counts = current_counts
            attempts = execution_attempts_view(final_projection)
            assert tuple(attempts) == (lease.execution_id,)
            assert not attempts[lease.execution_id].decision_answer_rejections
            recovered_lease = leases_view(final_projection)[lease.lease_id]
            assert recovered_lease.execution_id == lease.execution_id
            assert recovered_lease.generation == lease.generation
            assert recovered_lease.state != "active"

        attempt = execution_attempts_view(final_projection)[lease.execution_id]
        counts = {
            "runner_submission_staged": sum(
                event.event_type == "runner_submission_staged" for event in events
            ),
            "runner_completion_witnessed": sum(
                event.event_type == "runner_completion_witnessed" for event in events
            ),
            "runner_execution_finalized": sum(
                event.event_type == "runner_execution_finalized" for event in events
            ),
            "decision_answer": sum(
                event.event_type == "output_record_accepted"
                and event.payload.get("record_type") == "decision_answer"
                for event in events
            ),
            "decision_patch": sum(
                event.event_type == "graph_patch_accepted"
                and event.payload.get("proposed_by_node_id") == "planner-plan"
                for event in events
            ),
        }
        if point == "pre_stage":
            assert attempt.state == "recovered"
            assert counts["runner_submission_staged"] == 0
            assert counts["runner_execution_finalized"] == 0
            assert node_states_view(final_projection)["planner-plan"] == "failed"
        elif point == "after_staging_pre_witness":
            assert attempt.state == "recovered"
            assert counts["runner_submission_staged"] == 1
            assert counts["runner_completion_witnessed"] == 0
            assert counts["runner_execution_finalized"] == 0
            assert node_states_view(final_projection)["planner-plan"] == "failed"
        else:
            assert attempt.state == "finalized"
            assert counts["runner_submission_staged"] == 1
            assert counts["runner_completion_witnessed"] == 1
            assert counts["runner_execution_finalized"] == 1
            assert counts["decision_answer"] == 1
            assert counts["decision_patch"] == 1
            assert node_states_view(final_projection)["planner-plan"] == "completed"
        assert len(
            [
                record
                for record in output_record_payloads_view(final_projection).values()
                if record.record_type == "decision_answer"
            ]
        ) == (1 if point in {"after_witness_pre_finalization", "after_commit_pre_ack"} else 0)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rejection_budget_survives_redelivery_restart_recovery_and_replays_receipts(
    tmp_path: Path,
) -> None:
    """D1/redelivery/restart/D2 remains one execution with two replayable receipts."""
    worktree = tmp_path / "worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "decision-budget.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
    )
    run_id = "decision-rejection-budget"
    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {"events": _decision_seed(run_id)},
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {"base_snapshot_id": "decision-budget-base", "max_grants": 1},
        )
        dispatch_item = next(
            item for item in scheduled.outbox_items if item.kind == "agent_dispatch"
        )
        projection = await controller.read_projection(run_id)
        lease = next(
            lease for lease in leases_view(projection).values() if lease.node_id == "planner-plan"
        )
        assert lease.execution_id is not None
        artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
        runner = _RejectionBudgetDecisionRunner(controller, sessions, artifacts, lease.execution_id)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            StaticGraphAgentFactory(
                AgentRunnerType.CODEX_SERVER,
                runner_builder=lambda *_args, **_kwargs: runner,
            ),
            worktree_path=worktree,
            artifact_store=artifacts,
        )

        await executor.dispatch(dispatch_item)
        await executor.wait_for_all(timeout_seconds=10)

        requested = await controller.read_projection(run_id)
        requested_attempt = execution_attempts_view(requested)[lease.execution_id]
        assert requested_attempt.state == "recovery_requested"
        assert requested_attempt.recovery_reason == "submission_repair_exhausted"
        assert runner.authored_delivery_count == 2
        assert runner.rejection_stop_calls == 1
        assert len(runner.acknowledgements) == 3
        assert (
            runner.acknowledgements[0].failure_diagnostic
            == runner.acknowledgements[1].failure_diagnostic
        )
        assert runner.acknowledgements[0].failure_diagnostic is not None
        assert runner.acknowledgements[0].failure_diagnostic.next_action == "correct_answer"
        assert runner.acknowledgements[2].failure_diagnostic is not None
        assert runner.acknowledgements[2].failure_diagnostic.next_action == "stop"

        restarted_controller = GraphController(
            sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
        )
        restarted_executor = GraphDispatchExecutor(
            sessions,
            restarted_controller,
            StaticGraphAgentFactory(
                AgentRunnerType.CODEX_SERVER,
                runner_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("budget recovery must not create a third runner")
                ),
            ),
            worktree_path=worktree,
            artifact_store=artifacts,
        )
        dispatcher = OutboxDispatcher(
            sessions, restarted_executor, FakeClock(), retry_jitter_seconds=0
        )
        report = await recover(sessions, dispatcher, run_id=run_id)
        await reconcile_runtime(restarted_controller, restarted_executor, report, dispatcher)
        await dispatcher.dispatch_pending(
            run_id=run_id,
            allowed_kinds=frozenset({"snapshot_publish", "runner_recovery"}),
        )

        recovered = await restarted_controller.read_projection(run_id)
        attempts = execution_attempts_view(recovered)
        assert tuple(attempts) == (lease.execution_id,)
        rejection_facts = attempts[lease.execution_id].decision_answer_rejections
        assert len(rejection_facts) == 2
        assert rejection_facts[0].answer_sha256 == rejection_facts[1].answer_sha256
        assert rejection_facts[0].delivery_id != rejection_facts[1].delivery_id
        assert all(item.decision_answer_receipt_ref is not None for item in rejection_facts)
        assert attempts[lease.execution_id].state == "recovered"
        assert node_states_view(recovered)["planner-plan"] == "failed"
        assert leases_view(recovered)[lease.lease_id].state == "revoked"

        for index, rejection in enumerate(rejection_facts, start=1):
            replay_engine = create_engine(tmp_path / f"replay-{index}.db")
            await init_db(replay_engine)
            try:
                replay = await replay_decision_answer_receipt(
                    artifact_store=artifacts,
                    evidence_ref=StoredArtifactRef.model_validate(
                        rejection.decision_answer_receipt_ref
                    ),
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

        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
            current_position = await GraphEventStore(session).current_position(run_id)
            explicit_retry = graph_event(
                "node_state_changed",
                {
                    "node_id": "planner-plan",
                    "new_state": "ready",
                    "trigger": "explicit_operator_retry_fixture",
                    "attempt_number": 2,
                },
                position=current_position + 1,
            ).model_copy(update={"run_id": run_id})
            await GraphEventStore(session).append_events(run_id, current_position, [explicit_retry])
            await session.commit()
        assert sum(event.event_type == "decision_answer_rejected" for event in events) == 2
        budget_error = next(
            event
            for event in events
            if event.event_type == "decision_answer_rejected"
            and event.payload["failure_diagnostic"]["category"] == "budget_exhaustion"
        )
        assert budget_error.payload["failure_diagnostic"]["next_action"] == "stop"
        assert budget_error.payload["failure_diagnostic"]["correction_allowed"] is False

        retry_controller = GraphController(
            sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
        )
        retry_scheduled = await retry_controller.handle_command(
            run_id,
            current_position + 1,
            "schedule_tick",
            {"base_snapshot_id": "explicit-retry-base", "max_grants": 1},
        )
        retry_item = next(
            item for item in retry_scheduled.outbox_items if item.kind == "agent_dispatch"
        )
        runner_factory_calls: list[str] = []

        def forbidden_retry_runner(*_args: Any, **_kwargs: Any) -> _DecisionRunner:
            runner_factory_calls.append("created")
            return runner

        retry_executor = GraphDispatchExecutor(
            sessions,
            retry_controller,
            StaticGraphAgentFactory(
                AgentRunnerType.CODEX_SERVER,
                runner_builder=forbidden_retry_runner,
            ),
            worktree_path=worktree,
            artifact_store=FilesystemArtifactStore(tmp_path / "missing-retry-receipts"),
        )
        await retry_executor.dispatch(retry_item)
        assert runner_factory_calls == []
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("failure_kind", "recovery_reason", "category", "next_action"),
    [
        (
            "environment",
            "validation_environment_blocked",
            "infrastructure_environment",
            "resolve_environment",
        ),
        ("runner", "runner_died", "execution", "retry_or_recover"),
    ],
)
@pytest.mark.asyncio
async def test_noncorrectable_decision_rejection_enters_and_completes_recovery(
    tmp_path: Path,
    failure_kind: str,
    recovery_reason: str,
    category: str,
    next_action: str,
) -> None:
    worktree = tmp_path / "worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "environment-rejection.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "decision-environment-rejection"
    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {"events": _decision_seed(run_id)},
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {"base_snapshot_id": "decision-environment-base", "max_grants": 1},
        )
        dispatch_item = next(
            item for item in scheduled.outbox_items if item.kind == "agent_dispatch"
        )
        projection = await controller.read_projection(run_id)
        lease = next(
            lease for lease in leases_view(projection).values() if lease.node_id == "planner-plan"
        )
        assert lease.execution_id is not None
        artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
        runner_type = (
            _EnvironmentRejectedDecisionRunner
            if failure_kind == "environment"
            else _ProcessFailedDecisionRunner
        )
        runner = runner_type(
            controller,
            sessions,
            artifacts,
            lease.execution_id,
        )
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            StaticGraphAgentFactory(
                AgentRunnerType.CODEX_SERVER,
                runner_builder=lambda *_args, **_kwargs: runner,
            ),
            worktree_path=worktree,
            artifact_store=artifacts,
        )

        await executor.dispatch(dispatch_item)
        await executor.wait_for_all(timeout_seconds=10)

        requested_projection = await controller.read_projection(run_id)
        attempt = execution_attempts_view(requested_projection)[lease.execution_id]
        assert attempt.state == "recovery_requested"
        assert attempt.recovery_reason == recovery_reason

        dispatcher = OutboxDispatcher(sessions, executor, FakeClock(), retry_jitter_seconds=0)
        await dispatcher.dispatch_pending(
            run_id=run_id,
            allowed_kinds=frozenset({"snapshot_publish"}),
        )
        await dispatcher.dispatch_pending(
            run_id=run_id,
            allowed_kinds=frozenset({"runner_recovery"}),
        )

        recovered = await controller.read_projection(run_id)
        assert execution_attempts_view(recovered)[lease.execution_id].state == "recovered"
        assert node_states_view(recovered)["planner-plan"] == "failed"
        assert leases_view(recovered)[lease.lease_id].state == "revoked"
        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
            public_errors = list(
                (
                    await session.execute(
                        select(EventV2Model).where(EventV2Model.event_type == "agent_error")
                    )
                ).scalars()
            )
        public_error = next(
            payload
            for event in public_errors
            if isinstance(payload := json.loads(event.payload), dict)
            and payload.get("execution_id") == lease.execution_id
        )
        diagnostic = public_error["failure_diagnostic"]
        assert diagnostic["category"] == category
        assert diagnostic["next_action"] == next_action
        assert diagnostic["correction_allowed"] is False
        assert not any(event.event_type == "decision_answer_rejected" for event in events)
    finally:
        await engine.dispose()
