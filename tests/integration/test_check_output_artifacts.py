from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import ArtifactStore, FilesystemArtifactStore, StoredArtifactRef
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    project_node_states,
    project_run_state,
    project_task_states,
)
from orchestrator.graph_runtime import (
    CHECK_OUTPUT_TAIL_CHARS,
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    StaleProjectionError,
)
from tests.unit.graph_test_utils import canonical_event_payload


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


class NoAgentFactory:
    def create_runner(self, context: GraphDispatchContext) -> Any:
        raise AssertionError(f"check dispatch unexpectedly requested an agent: {context.node_id}")


class AppendFailingStore:
    """Write through to a real store, then make the real event append fail."""

    def __init__(
        self,
        store: FilesystemArtifactStore,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._store = store
        self._session_factory = session_factory
        self.refs: list[StoredArtifactRef] = []

    async def put(
        self,
        content: bytes,
        *,
        media_type: str,
        encoding: str | None = None,
    ) -> StoredArtifactRef:
        ref = await self._store.put(content, media_type=media_type, encoding=encoding)
        self.refs.append(ref)
        async with self._session_factory() as session:
            await session.execute(
                text(
                    "CREATE TRIGGER reject_check_append BEFORE INSERT ON events_v2 "
                    "BEGIN SELECT RAISE(FAIL, 'append rejected'); END"
                )
            )
            await session.commit()
        return ref

    async def read(self, ref: StoredArtifactRef) -> bytes:
        return await self._store.read(ref)

    async def delete(self, ref: StoredArtifactRef) -> None:
        await self._store.delete(ref)


def _event(run_id: str, position: int, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id=run_id,
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


async def _run_check(
    tmp_path: Path,
    command: str,
    store: ArtifactStore | Callable[[async_sessionmaker[AsyncSession]], ArtifactStore],
    *,
    append_failure: bool = False,
) -> list[EventEnvelope]:
    engine = create_engine(tmp_path / "graph.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    artifact_store = store(session_factory) if callable(store) else store
    run_id = "check-output-artifacts"
    events = [
        _event(run_id, 1, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            run_id,
            2,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "region-1",
            },
        ),
        _event(
            run_id,
            3,
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "candidate_id": "candidate-1",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "task_region_id": "region-1",
                "value": {"summary": "candidate"},
            },
        ),
        _event(
            run_id,
            4,
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "region-1",
            },
        ),
        _event(
            run_id,
            5,
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "candidate_id": "candidate-1",
                "producer_node_id": "verifier-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "task_region_id": "region-1",
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": []},
            },
        ),
        _event(
            run_id,
            6,
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "ready",
                "task_region_id": "region-1",
                "candidate_id": "candidate-1",
                "command_definition": {"id": "check-1", "cmd": command, "timeout_seconds": 5},
            },
        ),
        _event(
            run_id,
            7,
            "input_bound",
            {
                "edge_id": "edge-verification-check",
                "to_node_id": "check-1",
                "to_port": "verification_evidence",
                "record_ids": ["verification-1"],
                "bound_at_position": 7,
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        NoAgentFactory(),
        worktree_path=tmp_path,
        artifact_store=artifact_store,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1, "base_snapshot_id": "S0"},
    )
    await dispatcher.dispatch_pending()
    if append_failure:
        with pytest.raises(StaleProjectionError):
            await executor.wait_for_all()
    else:
        await executor.wait_for_all()
    async with session_factory() as session:
        result = await GraphEventStore(session).read_run(run_id)
    await engine.dispose()
    return result


def _check_value(events: list[EventEnvelope]) -> dict[str, Any]:
    event = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "check_result"
    )
    return event.payload["value"]


@pytest.mark.asyncio
async def test_sub_threshold_check_output_stays_inline_without_artifacts(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    events = await _run_check(
        tmp_path,
        "printf small-output; printf small-error >&2",
        FilesystemArtifactStore(artifact_root),
    )

    value = _check_value(events)
    assert value["stdout_tail"] == "small-output"
    assert value["stderr_tail"] == "small-error"
    assert value.get("stdout_ref") is None
    assert value.get("stderr_ref") is None
    assert value["stdout_truncated"] is False
    assert value["stderr_truncated"] is False
    assert not artifact_root.exists()


@pytest.mark.asyncio
async def test_exact_byte_threshold_stays_inline_without_artifact(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    events = await _run_check(
        tmp_path,
        "printf '%*s' 16384 '' | tr ' ' x",
        FilesystemArtifactStore(artifact_root),
    )

    value = _check_value(events)
    assert value["stdout_tail"] == "x" * 16_384
    assert value.get("stdout_ref") is None
    assert value["stdout_truncated"] is False
    assert not artifact_root.exists()


@pytest.mark.asyncio
async def test_one_byte_above_threshold_writes_complete_artifact(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    events = await _run_check(tmp_path, "printf '%*s' 16385 '' | tr ' ' x", store)

    value = _check_value(events)
    assert value["stdout_tail"] == "x" * CHECK_OUTPUT_TAIL_CHARS
    assert value["stdout_truncated"] is True
    ref = StoredArtifactRef.model_validate(value["stdout_ref"])
    assert await store.read(ref) == b"x" * 16_385


@pytest.mark.asyncio
async def test_multibyte_output_uses_byte_threshold_and_unicode_character_tail(
    tmp_path: Path,
) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    output = "a" * 16_381 + "🙂"
    assert len(output.encode("utf-8")) == 16_385
    events = await _run_check(
        tmp_path,
        "printf '%*s' 16381 '' | tr ' ' a; printf '🙂'",
        store,
    )

    value = _check_value(events)
    assert value["stdout_tail"] == "a" * 3_999 + "🙂"
    assert len(value["stdout_tail"]) == CHECK_OUTPUT_TAIL_CHARS
    ref = StoredArtifactRef.model_validate(value["stdout_ref"])
    assert await store.read(ref) == output.encode("utf-8")


@pytest.mark.asyncio
async def test_large_check_output_is_written_before_bounded_event_append(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    command = (
        "i=0; while [ $i -lt 17000 ]; do printf x; i=$((i+1)); done; "
        "i=0; while [ $i -lt 17000 ]; do printf y >&2; i=$((i+1)); done"
    )
    events = await _run_check(tmp_path, command, store)

    value = _check_value(events)
    assert value["stdout_tail"] == "x" * CHECK_OUTPUT_TAIL_CHARS
    assert value["stderr_tail"] == "y" * CHECK_OUTPUT_TAIL_CHARS
    assert value["stdout_truncated"] is True
    assert value["stderr_truncated"] is True
    stdout_ref = StoredArtifactRef.model_validate(value["stdout_ref"])
    stderr_ref = StoredArtifactRef.model_validate(value["stderr_ref"])
    assert await store.read(stdout_ref) == b"x" * 17_000
    assert await store.read(stderr_ref) == b"y" * 17_000


@pytest.mark.asyncio
async def test_two_mebibyte_outputs_replay_without_artifacts_and_keep_event_json_bounded(
    tmp_path: Path,
) -> None:
    """The producer persists complete blobs while every replay remains store-free."""
    artifact_root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(artifact_root)
    output_size = 2 * 1024 * 1024
    command = (
        f"head -c {output_size} /dev/zero | tr '\\000' x; "
        f"head -c {output_size} /dev/zero | tr '\\000' y >&2"
    )

    events = await _run_check(tmp_path, command, store)
    value = _check_value(events)
    stdout = b"x" * output_size
    stderr = b"y" * output_size
    stdout_ref = StoredArtifactRef.model_validate(value["stdout_ref"])
    stderr_ref = StoredArtifactRef.model_validate(value["stderr_ref"])

    assert value["stdout_tail"] == "x" * CHECK_OUTPUT_TAIL_CHARS
    assert value["stderr_tail"] == "y" * CHECK_OUTPUT_TAIL_CHARS
    assert len(value["stdout_tail"]) == CHECK_OUTPUT_TAIL_CHARS
    assert len(value["stderr_tail"]) == CHECK_OUTPUT_TAIL_CHARS
    assert await store.read(stdout_ref) == stdout
    assert await store.read(stderr_ref) == stderr
    assert stdout_ref.size_bytes == len(stdout)
    assert stderr_ref.size_bytes == len(stderr)
    assert stdout_ref.content_hash == f"sha256:{hashlib.sha256(stdout).hexdigest()}"
    assert stderr_ref.content_hash == f"sha256:{hashlib.sha256(stderr).hexdigest()}"

    engine = create_engine(tmp_path / "graph.db")
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        persisted_json = await session.scalar(
            text(
                "SELECT payload FROM events_v2 "
                "WHERE event_type = 'output_record_accepted' "
                "AND json_extract(payload, '$.payload.record_type') = 'check_result'"
            )
        )
    await engine.dispose()

    assert isinstance(persisted_json, str)
    persisted_event = json.loads(persisted_json)
    persisted_value = persisted_event["payload"]["value"]
    assert persisted_value["stdout_ref"] == stdout_ref.model_dump(mode="json")
    assert persisted_value["stderr_ref"] == stderr_ref.model_dump(mode="json")
    assert persisted_value["stdout_tail"] == "x" * CHECK_OUTPUT_TAIL_CHARS
    assert persisted_value["stderr_tail"] == "y" * CHECK_OUTPUT_TAIL_CHARS
    assert "x" * (CHECK_OUTPUT_TAIL_CHARS + 1) not in persisted_json
    assert "y" * (CHECK_OUTPUT_TAIL_CHARS + 1) not in persisted_json
    assert len(persisted_json.encode("utf-8")) < 32 * 1024

    shutil.rmtree(artifact_root)
    engine = create_engine(tmp_path / "graph.db")
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        replay_store = GraphEventStore(session)
        full_replay = await replay_store.read_run("check-output-artifacts")
        compact_replay = await replay_store.read_run_projection("check-output-artifacts")
    await engine.dispose()

    assert not artifact_root.exists()
    assert project_run_state(full_replay) == project_run_state(compact_replay)
    assert project_node_states(full_replay) == project_node_states(compact_replay)
    assert project_task_states(full_replay) == project_task_states(compact_replay)


@pytest.mark.asyncio
async def test_artifact_write_failure_prevents_callback_append(tmp_path: Path) -> None:
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("file")
    command = "i=0; while [ $i -lt 17000 ]; do printf x; i=$((i+1)); done"

    events = await _run_check(tmp_path, command, FilesystemArtifactStore(invalid_root))

    assert not any(event.event_type == "callback_accepted" for event in events)
    assert not any(
        event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "check_result"
        for event in events
    )


@pytest.mark.asyncio
async def test_callback_append_failure_leaves_readable_orphan(tmp_path: Path) -> None:
    real_store = FilesystemArtifactStore(tmp_path / "artifacts")
    stores: list[AppendFailingStore] = []

    def make_store(session_factory: async_sessionmaker[AsyncSession]) -> AppendFailingStore:
        store = AppendFailingStore(real_store, session_factory)
        stores.append(store)
        return store

    command = "i=0; while [ $i -lt 17000 ]; do printf z; i=$((i+1)); done"
    events = await _run_check(tmp_path, command, make_store, append_failure=True)

    assert not any(event.event_type == "callback_accepted" for event in events)
    store = stores[0]
    assert len(store.refs) == 1
    assert await real_store.read(store.refs[0]) == b"z" * 17_000
