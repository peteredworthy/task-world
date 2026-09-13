from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    BoundaryValidationError,
    EventEnvelope,
    FakeClock,
    PatchCommandContext,
    SequentialIdGenerator,
    compile_routine,
    node_payload_view,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    MAX_REJECTION_EVIDENCE_BYTES,
    RejectionEvidenceArtifact,
    RejectionEvidencePublicRef,
    ReliablePlanRejectionRecorder,
    capture_reliable_plan_rejection_evidence,
    replay_reliable_plan_rejection,
    resolve_orchestrator_source_root,
)

pytestmark = pytest.mark.slow


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _source_repo(root: Path) -> Path:
    repo = root / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    source_file = repo / "src" / "orchestrator" / "source.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "src/orchestrator/source.py")
    _git(repo, "commit", "-qm", "initial")
    return repo


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "dynamic-graph-feature",
            "name": "Rejection evidence",
            "planner_generation_budget": 2,
            "steps": [
                {
                    "id": "plan",
                    "kind": "planner",
                    "title": "Plan one reliable region",
                    "available_tools": [
                        "submit_graph_patch",
                        "construct_reliable_plan_region",
                    ],
                }
            ],
        }
    )


async def _seed(sessions: Any, controller: GraphController, run_id: str) -> int:
    clock = FakeClock()
    ids = SequentialIdGenerator()
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {
            "events": compile_routine(
                _routine(),
                clock,
                ids,
                run_id=run_id,
                run_config={
                    "acceptance_command": "true",
                    "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                    "reliable_plan_selected_runner_type": "codex_server",
                    "reliable_plan_one_horizon_authorized": True,
                    "reliable_plan_remaining_horizons": 1,
                    "reliable_plan_qualification_evidence_hash": "sha256:" + "a" * 64,
                    "reliable_plan_model_assignments": {
                        "arm_id": "test-arm",
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
            )
        },
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    return started.projection_position


async def _pad_graph_prefix(
    sessions: Any,
    controller: GraphController,
    run_id: str,
    target_position: int,
    *,
    reason_size: int = 1,
) -> int:
    position = await controller.current_position(run_id)
    while position < target_position:
        count = min(100, target_position - position)
        padding = [
            EventEnvelope(
                event_id=f"padding-{position + offset}",
                run_id=run_id,
                position=-1,
                event_type="command_rejected",
                schema_version=1,
                actor=Actor(kind=ActorKind.CONTROLLER),
                causation_id="padding",
                timestamp=FakeClock().now(),
                payload={"command_type": "padding", "reason": "x" * reason_size},
            )
            for offset in range(1, count + 1)
        ]
        async with sessions() as session:
            await GraphEventStore(session).append_events(run_id, position, padding)
            await session.commit()
        position += count
        await controller.read_projection(run_id)
    return position


def _rejected_request(position: int, secret: str = "private-token-123") -> dict[str, Any]:
    return {
        "patch_id": "invalid-reliable-plan",
        "base_graph_position": position,
        "macro_invocations": [
            {
                "macro": "construct_reliable_plan_region",
                "args": {
                    "operation_key": "invalid-reliable-plan",
                    "scope": f"bounded feature {secret}",
                    "objective": "request an unknown requirement",
                    "requirement_ids": ["missing-requirement"],
                    "dependencies": [],
                    "acceptance": ["must be accepted"],
                    "checks": [],
                    "rubric": ["must be valid"],
                },
            }
        ],
    }


async def _capture_fixture(
    tmp_path: Path,
    *,
    pad_to_position: int | None = None,
    padding_reason_size: int = 1,
    orchestrator_source_path: Path | None = None,
) -> tuple[Any, Any, Path, Any, str]:
    source = _source_repo(tmp_path)
    artifact_store = FilesystemArtifactStore(tmp_path / "private-artifacts")
    engine = create_engine(tmp_path / "live.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
        reliable_plan_rejection_recorder=ReliablePlanRejectionRecorder(
            sessions,
            artifact_store,
            orchestrator_source_path or source,
        ),
    )
    run_id = "rejection-evidence-run"
    position = await _seed(sessions, controller, run_id)
    if pad_to_position is not None:
        position = await _pad_graph_prefix(
            sessions,
            controller,
            run_id,
            pad_to_position,
            reason_size=padding_reason_size,
        )
    request = _rejected_request(position)
    projection = await controller.read_projection(run_id)
    async with sessions() as session:
        prefix = await GraphEventStore(session).read_run(run_id)
    planner_payload = node_payload_view(projection, "planner-plan")
    assert planner_payload is not None
    executor = GraphDispatchExecutor(
        sessions,
        controller,
        _UnusedAgentFactory(),
        worktree_path=source,
        artifact_store=artifact_store,
    )
    response = await executor._submit_graph_patch_callback(
        GraphDispatchContext(
            run_id=run_id,
            node_id="planner-plan",
            node_kind="planner",
            node_role="planner",
            node_payload=planner_payload,
            requirements=[],
            worktree_path=str(source),
            lease_id="lease-rejection",
            lease_generation=1,
            execution_id="execution-rejection",
            base_snapshot_id="routine-snapshot",
            dispatch_event_id="dispatch-rejection",
            graph_projection=projection,
            graph_events=prefix,
            graph_position=position,
        ),
        request,
    )
    assert response is not None and "unknown_requirement_identity" in response
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
    rejection = next(
        event
        for event in reversed(events)
        if event.event_type in {"graph_patch_rejected", "command_rejected"}
    )
    public_event_json = json.dumps(rejection.payload, sort_keys=True)
    assert "private-token-123" not in public_event_json
    assert "missing-requirement" not in public_event_json
    assert set(rejection.payload["rejection_evidence"]) == {
        "artifact_ref",
        "content_hash",
        "size_bytes",
        "classification",
        "replayable",
    }
    public_ref = RejectionEvidencePublicRef.model_validate(rejection.payload["rejection_evidence"])
    async with sessions() as session:
        authorized = await GraphEventStore(session).read_authorized_artifact_reference(
            run_id,
            public_ref.content_hash,
        )
    assert authorized is not None
    return engine, artifact_store, source, public_ref, response


class _UnusedAgentFactory:
    def preflight(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("rejection callback must not start an agent")


class _UnavailableEvidenceRecorder:
    async def __call__(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
        raise OSError("private request text must never reach public logs")

    def create_runner(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rejection callback must not start an agent")


@pytest.mark.asyncio
async def test_exact_rejection_capture_and_isolated_sqlite_replay(tmp_path: Path) -> None:
    engine, artifacts, source, public_ref, response = await _capture_fixture(tmp_path)
    replay_engine = create_engine(tmp_path / "replay.db")
    await init_db(replay_engine)
    replay_sessions = create_session_factory(replay_engine)
    try:
        captured = RejectionEvidenceArtifact.model_validate_json(
            await artifacts.read(public_ref.artifact_ref)
        )
        assert captured.replayable is True
        assert captured.request == _rejected_request(captured.graph_position)
        assert captured.response == response
        assert captured.source_identity.complete is True
        assert captured.graph_prefix is not None

        replayed = await replay_reliable_plan_rejection(
            artifact_store=artifacts,
            evidence_ref=public_ref.artifact_ref,
            isolated_session_factory=replay_sessions,
            clock=FakeClock(),
            id_gen=SequentialIdGenerator(),
            worktree_path=source,
        )
        assert replayed.response == response
    finally:
        await replay_engine.dispose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_capture_failure_preserves_rejection_with_static_safe_metadata(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "capture-failure.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
        reliable_plan_rejection_recorder=_UnavailableEvidenceRecorder(),
    )
    try:
        position = await _seed(sessions, controller, "capture-failure-run")
        request = _rejected_request(position)
        result = await controller.handle_command(
            "capture-failure-run",
            position,
            "submit_patch",
            request,
            context=PatchCommandContext(
                run_id="capture-failure-run",
                current_graph_position=position,
                proposed_by_node_id="planner-plan",
                actor_role="planner",
            ),
        )
        rejection = next(
            event
            for event in result.events
            if event.event_type in {"graph_patch_rejected", "command_rejected"}
        )
        assert rejection.payload["rejection_evidence"] == {
            "classification": "capture_failed",
            "replayable": False,
        }
        assert "unknown_requirement_identity" in str(rejection.payload["reason"])
        assert "private-token-123" not in json.dumps(rejection.payload)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_public_reference_redacts_request_and_response(tmp_path: Path) -> None:
    engine, artifacts, _source, public_ref, _response = await _capture_fixture(tmp_path)
    try:
        public_json = public_ref.model_dump_json()
        assert "private-token-123" not in public_json
        assert "missing-requirement" not in public_json
        assert set(public_ref.model_dump()) == {
            "artifact_ref",
            "content_hash",
            "size_bytes",
            "classification",
            "replayable",
        }
        protected = await artifacts.read(public_ref.artifact_ref)
        assert b"private-token-123" in protected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_production_capture_identifies_executing_orchestrator_not_target_repo(
    tmp_path: Path,
) -> None:
    orchestrator_source = resolve_orchestrator_source_root()
    engine, artifacts, target_repo, public_ref, _response = await _capture_fixture(
        tmp_path,
        orchestrator_source_path=orchestrator_source,
    )
    try:
        captured = RejectionEvidenceArtifact.model_validate_json(
            await artifacts.read(public_ref.artifact_ref)
        )
        executing_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=orchestrator_source,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        target_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert captured.source_identity.head_commit == executing_head
        assert captured.source_identity.head_commit != target_head
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_exact_replay_retains_known_successor_scale_prefix(tmp_path: Path) -> None:
    engine, artifacts, source, public_ref, response = await _capture_fixture(
        tmp_path,
        pad_to_position=160,
    )
    replay_engine = create_engine(tmp_path / "successor-scale-replay.db")
    await init_db(replay_engine)
    try:
        captured = RejectionEvidenceArtifact.model_validate_json(
            await artifacts.read(public_ref.artifact_ref)
        )
        assert captured.graph_position == 160
        assert captured.graph_prefix_complete is True
        assert captured.request_response_complete is True
        replayed = await replay_reliable_plan_rejection(
            artifact_store=artifacts,
            evidence_ref=public_ref.artifact_ref,
            isolated_session_factory=create_session_factory(replay_engine),
            clock=FakeClock(),
            id_gen=SequentialIdGenerator(),
            worktree_path=source,
        )
        assert replayed.response == response
    finally:
        await replay_engine.dispose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_oversize_graph_prefix_retains_small_exact_request_and_response(
    tmp_path: Path,
) -> None:
    engine, artifacts, _source, public_ref, response = await _capture_fixture(
        tmp_path,
        pad_to_position=160,
        padding_reason_size=3_000,
    )
    try:
        captured = RejectionEvidenceArtifact.model_validate_json(
            await artifacts.read(public_ref.artifact_ref)
        )
        assert captured.classification == "graph_prefix_incomplete"
        assert captured.replayable is False
        assert captured.graph_prefix_complete is False
        assert captured.graph_prefix is None
        assert captured.request_response_complete is True
        assert captured.request == _rejected_request(160)
        assert captured.response == response
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_oversize_capture_is_bounded_and_explicitly_non_replayable(
    tmp_path: Path,
) -> None:
    engine, artifacts, source, public_ref, response = await _capture_fixture(tmp_path)
    try:
        captured = RejectionEvidenceArtifact.model_validate_json(
            await artifacts.read(public_ref.artifact_ref)
        )
        oversize_request = dict(captured.request or {})
        oversize_request["private_blob"] = "s" * 600_000
        oversize = await capture_reliable_plan_rejection_evidence(
            session_factory=create_session_factory(engine),
            artifact_store=artifacts,
            worktree_path=source,
            run_id=captured.run_id,
            proposed_by_node_id=captured.proposed_by_node_id,
            actor_role=captured.actor_role,
            graph_position=captured.graph_position,
            request=oversize_request,
            response=response,
        )
        assert oversize.classification == "evidence_oversize"
        assert oversize.replayable is False
        assert oversize.size_bytes <= MAX_REJECTION_EVIDENCE_BYTES
        manifest = RejectionEvidenceArtifact.model_validate_json(
            await artifacts.read(oversize.artifact_ref)
        )
        assert manifest.request is None
        assert manifest.request_response_complete is False
        assert manifest.graph_prefix_complete is True
        with pytest.raises(BoundaryValidationError, match="non-replayable"):
            await replay_reliable_plan_rejection(
                artifact_store=artifacts,
                evidence_ref=oversize.artifact_ref,
                isolated_session_factory=create_session_factory(engine),
                clock=FakeClock(),
                id_gen=SequentialIdGenerator(),
                worktree_path=source,
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_source_and_graph_identity_mismatches_reject_replay(tmp_path: Path) -> None:
    engine, artifacts, source, public_ref, _response = await _capture_fixture(tmp_path)
    replay_engine = create_engine(tmp_path / "mismatch-replay.db")
    await init_db(replay_engine)
    replay_sessions = create_session_factory(replay_engine)
    try:
        source_file = source / "src" / "orchestrator" / "source.py"
        source_file.write_text("VALUE = 2\n", encoding="utf-8")
        with pytest.raises(BoundaryValidationError, match="source identity mismatch"):
            await replay_reliable_plan_rejection(
                artifact_store=artifacts,
                evidence_ref=public_ref.artifact_ref,
                isolated_session_factory=replay_sessions,
                clock=FakeClock(),
                id_gen=SequentialIdGenerator(),
                worktree_path=source,
            )
        source_file.write_text("VALUE = 1\n", encoding="utf-8")

        captured = RejectionEvidenceArtifact.model_validate_json(
            await artifacts.read(public_ref.artifact_ref)
        )
        assert captured.graph_prefix
        tampered = captured.model_copy(update={"graph_prefix": captured.graph_prefix[:-1]})
        async with artifacts.publication():
            tampered_ref = await artifacts.put(
                json.dumps(
                    tampered.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode(),
                media_type=public_ref.artifact_ref.media_type,
                encoding="utf-8",
            )
        with pytest.raises(BoundaryValidationError, match="graph prefix identity mismatch"):
            await replay_reliable_plan_rejection(
                artifact_store=artifacts,
                evidence_ref=tampered_ref,
                isolated_session_factory=replay_sessions,
                clock=FakeClock(),
                id_gen=SequentialIdGenerator(),
                worktree_path=source,
            )
    finally:
        await replay_engine.dispose()
        await engine.dispose()
