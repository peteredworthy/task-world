"""Regression coverage for bounded graph outbox side-effect delivery."""

from __future__ import annotations

import json

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    boundary_manifest_hash,
    cache_authority_hash,
    CacheAuthorityPolicy,
    CacheStatusEvidence,
    derive_cache_roots,
    EventEnvelope,
    RunnerBaselineRecordedPayload,
)
from orchestrator.graph_runtime import GraphEventEnvelopeTooLargeError, GraphEventStore
from orchestrator.graph_runtime.store import (
    GRAPH_EVENT_PAYLOAD_BYTES,
    GRAPH_RUNTIME_TAIL_EVENTS,
    GraphReadModelUnavailable,
    graph_aggregate_id,
)
from tests.integration.test_graph_managed_snapshot_cleanup import (
    _dispatcher,
    _events,
    _managed_fixture,
    _rows,
)

pytestmark = pytest.mark.slow


@pytest.fixture
async def outbox_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-outbox-durability.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_event_reader_accepts_exact_cap_and_rejects_one_byte_over(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "exact-runtime-cap"
    event = _callback_event(run_id, 1, 0)
    empty_size = len(event.model_dump_json().encode())
    exact_body_size = GRAPH_EVENT_PAYLOAD_BYTES - empty_size
    exact = _callback_event(run_id, 1, exact_body_size)
    assert len(exact.model_dump_json().encode()) == GRAPH_EVENT_PAYLOAD_BYTES
    await _append(sessions, run_id, [exact])

    async with sessions() as session:
        bounded = await GraphEventStore(session).read_bounded_runtime_events(
            run_id, from_position=1
        )
    assert [item.position for item in bounded] == [1]

    oversized = _callback_event(run_id, 2, exact_body_size + 1)
    assert len(oversized.model_dump_json().encode()) == GRAPH_EVENT_PAYLOAD_BYTES + 1
    with pytest.raises(GraphEventEnvelopeTooLargeError, match="maximum is 32768 bytes"):
        await _append(sessions, run_id, [oversized])
    async with sessions() as session:
        assert await GraphEventStore(session).current_position(run_id) == 1


@pytest.mark.asyncio
async def test_runner_recovery_uses_checkpoint_after_oversized_historical_event(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = outbox_db
    fixture = await _managed_fixture(
        sessions, tmp_path, "recovery-oversized-history", mismatch=True
    )
    position = await fixture.controller.current_position(fixture.run_id)
    await _append(
        sessions,
        fixture.run_id,
        [_callback_event(fixture.run_id, position + 1, 0)],
    )

    dispatcher = _dispatcher(sessions, fixture, tmp_path)
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    recovery_rows = await _rows(sessions, fixture.run_id, "runner_recovery")
    assert len(recovery_rows) == 1
    assert recovery_rows[0].status == "completed"
    assert (await _event_types(sessions, fixture.run_id)).count("runner_recovery_completed") == 1


@pytest.mark.asyncio
async def test_snapshot_cleanup_uses_checkpoint_after_oversized_historical_event(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = outbox_db
    fixture = await _managed_fixture(
        sessions, tmp_path, "cleanup-oversized-history", mismatch=False
    )
    position = await fixture.controller.current_position(fixture.run_id)
    await _append(
        sessions,
        fixture.run_id,
        [_callback_event(fixture.run_id, position + 1, 0)],
    )

    await _dispatcher(sessions, fixture, tmp_path).dispatch_pending(run_id=fixture.run_id)
    cleanup_rows = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    assert cleanup_rows and all(row.status == "completed" for row in cleanup_rows)
    assert (await _event_types(sessions, fixture.run_id)).count("cleanup_applied") == 3


@pytest.mark.asyncio
async def test_runner_recovery_does_not_scan_beyond_tail_cap_or_duplicate_completion(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = outbox_db
    fixture = await _managed_fixture(sessions, tmp_path, "recovery-long-history", mismatch=True)
    position = await fixture.controller.current_position(fixture.run_id)
    await _append(
        sessions,
        fixture.run_id,
        [
            _callback_event(fixture.run_id, position + offset, 0)
            for offset in range(1, GRAPH_RUNTIME_TAIL_EVENTS + 2)
        ],
    )

    async with sessions() as session:
        with pytest.raises(GraphReadModelUnavailable, match="recovery_tail_exceeds_bounded_cap"):
            await GraphEventStore(session).read_bounded_runtime_events(fixture.run_id)

    dispatcher = _dispatcher(sessions, fixture, tmp_path)
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert (await _event_types(sessions, fixture.run_id)).count("runner_recovery_completed") == 1


@pytest.mark.asyncio
async def test_runtime_reader_compacts_legacy_oversized_file_state_in_sql(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "legacy-cache-compaction"
    event = _callback_event(run_id, 1, 0).model_copy(
        update={
            "event_type": "file_state_accepted",
            "payload": {
                "record_id": "file-state-1",
                "paths": [
                    {
                        "path": f".venv/cache-{index}",
                        "classification": "tool_cache",
                        "detail": "x" * 128,
                    }
                    for index in range(400)
                ]
                + [{"path": "src/app.py", "classification": "tracked_change"}],
                "payload": {
                    "paths": [
                        {
                            "path": f".pytest_cache/archive-{index}",
                            "classification": "tool_cache",
                            "detail": "x" * 128,
                        }
                        for index in range(400)
                    ]
                    + [
                        {"path": "legacy-without-classification.txt"},
                        {"path": "legacy-null-classification.txt", "classification": None},
                        {
                            "path": "generated/report.json",
                            "classification": "build_output",
                        },
                    ]
                },
            },
        }
    )
    rendered = event.model_dump_json()
    assert len(rendered.encode()) > GRAPH_EVENT_PAYLOAD_BYTES
    async with sessions() as session:
        async with session.begin():
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=1,
                    event_type=event.event_type,
                    payload=rendered,
                    timestamp=event.timestamp.isoformat(),
                )
            )

    async with sessions() as session:
        replayed = await GraphEventStore(session).read_bounded_runtime_events(
            run_id, from_position=1
        )

    assert replayed[0].payload["paths"] == [
        {"path": "src/app.py", "classification": "tracked_change"}
    ]
    assert replayed[0].payload["payload"]["paths"] == [
        {"path": "legacy-without-classification.txt"},
        {"path": "legacy-null-classification.txt", "classification": None},
        {"path": "generated/report.json", "classification": "build_output"},
    ]
    async with sessions() as session:
        full_page = await GraphEventStore(session).read_bounded_full_event_page(
            run_id,
            from_position=1,
            limit=1,
            payload_byte_cap=GRAPH_EVENT_PAYLOAD_BYTES,
        )
    full_payload = json.loads(full_page[0].payload_json or "null")
    assert full_payload["paths"] == replayed[0].payload["paths"]
    assert full_payload["payload"]["paths"] == replayed[0].payload["payload"]["paths"]


@pytest.mark.asyncio
async def test_runtime_reader_compacts_eligible_cache_carriers_below_cap_in_sql(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "below-cap-cache-compaction"
    policy = CacheAuthorityPolicy()
    evidence = [CacheStatusEvidence(path=".venv/module.pyc", kind="ignored")]
    roots = derive_cache_roots(evidence, policy)
    authority_hash = cache_authority_hash(policy)
    tree_sha = "a" * 40
    file_state = _callback_event(run_id, 1, 0).model_copy(
        update={
            "event_type": "file_state_accepted",
            "payload": {
                "record_id": "file-state-1",
                "paths": [
                    {"path": ".venv/module.pyc", "classification": "tool_cache"},
                    {"path": "legacy-without-classification.txt"},
                    {"path": "legacy-null-classification.txt", "classification": None},
                    {"path": "src/app.py", "classification": "tracked_change"},
                ],
                "payload": {
                    "paths": [
                        {"path": ".ruff_cache/archive", "classification": "tool_cache"},
                        {"path": "nested-without-classification.txt"},
                        {"path": "nested-null-classification.txt", "classification": None},
                        {
                            "path": "generated/nested.txt",
                            "classification": "build_output",
                        },
                    ]
                },
            },
        }
    )
    compact_runner = _callback_event(run_id, 2, 0).model_copy(
        update={
            "event_type": "runner_baseline_recorded",
            "payload": {
                "execution_id": "execution-1",
                "node_id": "node-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "baseline_snapshot_id": "baseline-1",
                "baseline_tree_sha": tree_sha,
                "entries": [],
                "boundary_hash": boundary_manifest_hash(
                    tree_sha,
                    [],
                    evidence,
                    authority_hash,
                ),
                "cache_authority_hash": authority_hash,
                "cache_status_evidence": [item.model_dump(mode="json") for item in evidence],
                "cache_roots": [item.model_dump(mode="json") for item in roots],
            },
        }
    )
    explicit_legacy_runner = _callback_event(run_id, 3, 0).model_copy(
        update={
            "event_type": "runner_baseline_recorded",
            "payload": {
                "execution_id": "execution-legacy",
                "node_id": "node-1",
                "lease_id": "lease-legacy",
                "lease_generation": 1,
                "baseline_snapshot_id": "baseline-legacy",
                "baseline_tree_sha": tree_sha,
                "entries": [],
                "boundary_hash": boundary_manifest_hash(tree_sha, [], (), None),
                "cache_roots": ["legacy-cache"],
            },
        }
    )
    file_state_without_nested_payload = _callback_event(run_id, 4, 0).model_copy(
        update={
            "event_type": "file_state_accepted",
            "payload": {
                "record_id": "file-state-without-nested-payload",
                "paths": [
                    {"path": ".mypy_cache/archive", "classification": "tool_cache"},
                    {"path": "src/other.py", "classification": "tracked_change"},
                ],
            },
        }
    )
    assert all(
        len(event.model_dump_json().encode()) < GRAPH_EVENT_PAYLOAD_BYTES
        for event in (
            file_state,
            compact_runner,
            explicit_legacy_runner,
            file_state_without_nested_payload,
        )
    )
    async with sessions() as session:
        async with session.begin():
            session.add_all(
                [
                    EventV2Model(
                        aggregate_id=graph_aggregate_id(run_id),
                        version=event.position,
                        event_type=event.event_type,
                        payload=event.model_dump_json(),
                        timestamp=event.timestamp.isoformat(),
                    )
                    for event in (
                        file_state,
                        compact_runner,
                        explicit_legacy_runner,
                        file_state_without_nested_payload,
                    )
                ]
            )

    async with sessions() as session:
        replayed = await GraphEventStore(session).read_bounded_runtime_events(
            run_id, from_position=1
        )

    assert replayed[0].payload["paths"] == [
        {"path": "legacy-without-classification.txt"},
        {"path": "legacy-null-classification.txt", "classification": None},
        {"path": "src/app.py", "classification": "tracked_change"},
    ]
    assert replayed[0].payload["payload"]["paths"] == [
        {"path": "nested-without-classification.txt"},
        {"path": "nested-null-classification.txt", "classification": None},
        {"path": "generated/nested.txt", "classification": "build_output"},
    ]
    assert "cache_roots" not in replayed[1].payload
    assert replayed[1].payload["cache_status_evidence"] == [
        {"path": ".venv/module.pyc", "kind": "ignored"}
    ]
    assert replayed[2].payload["cache_roots"] == ["legacy-cache"]
    assert replayed[3].payload["paths"] == [
        {"path": "src/other.py", "classification": "tracked_change"}
    ]
    assert "payload" not in replayed[3].payload


@pytest.mark.asyncio
async def test_runtime_reader_compacts_legacy_oversized_runner_root_carriers_in_sql(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "legacy-runner-cache-compaction"
    policy = CacheAuthorityPolicy()
    evidence = [
        CacheStatusEvidence(
            path=f"package-{index}/__pycache__/module.pyc",
            kind="ignored",
        )
        for index in range(400)
    ]
    roots = derive_cache_roots(evidence, policy)
    authority_hash = cache_authority_hash(policy)
    tree_sha = "a" * 40
    event = _callback_event(run_id, 1, 0).model_copy(
        update={
            "event_type": "runner_baseline_recorded",
            "payload": {
                "execution_id": "execution-1",
                "node_id": "node-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "baseline_snapshot_id": "baseline-1",
                "baseline_tree_sha": tree_sha,
                "entries": [],
                "boundary_hash": boundary_manifest_hash(
                    tree_sha,
                    [],
                    evidence,
                    authority_hash,
                ),
                "cache_authority_hash": authority_hash,
                "cache_status_evidence": [item.model_dump(mode="json") for item in evidence],
                "cache_roots": [item.model_dump(mode="json") for item in roots],
            },
        }
    )
    original_payload = RunnerBaselineRecordedPayload.model_validate(event.payload)
    rendered = event.model_dump_json()
    assert len(rendered.encode()) > GRAPH_EVENT_PAYLOAD_BYTES
    async with sessions() as session:
        async with session.begin():
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=1,
                    event_type=event.event_type,
                    payload=rendered,
                    timestamp=event.timestamp.isoformat(),
                )
            )

    async with sessions() as session:
        replayed = await GraphEventStore(session).read_bounded_runtime_events(
            run_id, from_position=1
        )

    compacted_payload = RunnerBaselineRecordedPayload.model_validate(replayed[0].payload)
    assert "cache_roots" not in replayed[0].payload
    assert derive_cache_roots(original_payload.cache_status_evidence or (), policy) == tuple(
        original_payload.cache_roots
    )
    assert derive_cache_roots(compacted_payload.cache_status_evidence or (), policy) == roots


@pytest.mark.asyncio
async def test_runtime_reader_does_not_compact_explicit_legacy_string_roots(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "legacy-explicit-root-authority"
    tree_sha = "b" * 40
    roots = [f"legacy-cache-{index:04d}-{'x' * 30}" for index in range(900)]
    payload = RunnerBaselineRecordedPayload(
        execution_id="execution-1",
        node_id="node-1",
        lease_id="lease-1",
        lease_generation=1,
        baseline_snapshot_id="baseline-1",
        baseline_tree_sha=tree_sha,
        entries=[],
        boundary_hash=boundary_manifest_hash(tree_sha, [], (), None),
        cache_roots=roots,
    ).model_dump(mode="json", exclude_none=True)
    event = _callback_event(run_id, 1, 0).model_copy(
        update={"event_type": "runner_baseline_recorded", "payload": payload}
    )
    rendered = event.model_dump_json()
    assert len(rendered.encode()) > GRAPH_EVENT_PAYLOAD_BYTES
    async with sessions() as session:
        async with session.begin():
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=1,
                    event_type=event.event_type,
                    payload=rendered,
                    timestamp=event.timestamp.isoformat(),
                )
            )

    async with sessions() as session:
        with pytest.raises(GraphReadModelUnavailable, match="event_payload_exceeds_byte_cap"):
            await GraphEventStore(session).read_bounded_runtime_events(run_id, from_position=1)


@pytest.mark.asyncio
async def test_file_state_report_sql_bounds_oversized_non_cache_boundary(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "oversized-non-cache-file-state"
    event = _callback_event(run_id, 1, 0).model_copy(
        update={
            "event_type": "file_state_accepted",
            "payload": {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "node-1",
                "snapshot_id": "snapshot-1",
                "verdict": "captured",
                "paths": [
                    {
                        "path": f"generated/output-{index}.txt",
                        "source": "untracked",
                        "classification": "build_output",
                        "detail": "x" * 128,
                    }
                    for index in range(220)
                ],
            },
        }
    )
    rendered = event.model_dump_json()
    assert GRAPH_EVENT_PAYLOAD_BYTES < len(rendered.encode()) < 256 * 1024
    async with sessions() as session:
        async with session.begin():
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=1,
                    event_type=event.event_type,
                    payload=rendered,
                    timestamp=event.timestamp.isoformat(),
                )
            )

    async with sessions() as session:
        page = await GraphEventStore(session).read_file_state_report_page(
            run_id,
            from_position=1,
            limit=1,
            path_limit=2,
        )

    boundary = page.boundaries[0]
    assert "paths" not in boundary.payload
    assert boundary.payload["_captured_source_entries_total"] == 220
    assert [item["path"] for item in boundary.payload["classifications"]] == [
        "generated/output-0.txt",
        "generated/output-1.txt",
    ]


@pytest.mark.asyncio
async def test_file_state_report_fallback_excludes_cache_paths_and_counts(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "oversized-mixed-file-state"
    event = _callback_event(run_id, 1, 0).model_copy(
        update={
            "event_type": "file_state_accepted",
            "payload": {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "node-1",
                "snapshot_id": "snapshot-1",
                "verdict": "captured",
                "paths": [
                    {
                        "path": f".venv/cache-{index}",
                        "classification": "tool_cache",
                        "detail": "x" * 128,
                    }
                    for index in range(400)
                ]
                + [
                    {"path": "legacy-without-classification.txt"},
                    {"path": "legacy-null-classification.txt", "classification": None},
                ]
                + [
                    {
                        "path": f"generated/output-{index}.txt",
                        "source": "untracked",
                        "classification": "build_output",
                        "detail": "x" * 128,
                    }
                    for index in range(220)
                ],
            },
        }
    )
    rendered = event.model_dump_json()
    assert len(rendered.encode()) > GRAPH_EVENT_PAYLOAD_BYTES
    compacted_non_cache = event.model_copy(
        update={
            "payload": {
                **event.payload,
                "paths": event.payload["paths"][400:],
            }
        }
    )
    assert len(compacted_non_cache.model_dump_json().encode()) > GRAPH_EVENT_PAYLOAD_BYTES
    async with sessions() as session:
        async with session.begin():
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=1,
                    event_type=event.event_type,
                    payload=rendered,
                    timestamp=event.timestamp.isoformat(),
                )
            )

    async with sessions() as session:
        page = await GraphEventStore(session).read_file_state_report_page(
            run_id,
            from_position=1,
            limit=1,
            path_limit=4,
        )

    payload = page.boundaries[0].payload
    assert payload["_captured_source_entries_total"] == 222
    assert payload["_classification_counts"] == {"build_output": 220}
    assert payload["classifications"] == [
        {"path": "legacy-without-classification.txt"},
        {"path": "legacy-null-classification.txt", "classification": None},
        {
            "path": "generated/output-0.txt",
            "source": "untracked",
            "classification": "build_output",
            "detail": "x" * 128,
        },
        {
            "path": "generated/output-1.txt",
            "source": "untracked",
            "classification": "build_output",
            "detail": "x" * 128,
        },
    ]
    assert all(entry.get("classification") != "tool_cache" for entry in payload["classifications"])


@pytest.mark.asyncio
async def test_file_state_report_rejects_oversized_associated_gatekeeper_event(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "oversized-file-state-gatekeeper-fact"
    boundary = _callback_event(run_id, 1, 0).model_copy(
        update={
            "event_type": "file_state_accepted",
            "payload": {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "node-1",
                "snapshot_id": "snapshot-1",
                "verdict": "captured",
                "paths": [],
            },
        }
    )
    fact = _callback_event(run_id, 2, 0).model_copy(
        update={
            "event_type": "gatekeeper_verdict_recorded",
            "payload": {
                "file_state_record_id": "file-state-1",
                "execution_id": "execution-1",
                "producer_node_id": "node-1",
                "resolved_count": 1,
                "verdicts": [
                    {
                        "path": "generated/output.txt",
                        "classification": "build_output",
                        "confidence": 1.0,
                        "rationale": "x" * 40_000,
                    }
                ],
            },
        }
    )
    assert GRAPH_EVENT_PAYLOAD_BYTES < len(fact.model_dump_json().encode()) < 256 * 1024
    async with sessions() as session:
        async with session.begin():
            session.add_all(
                [
                    EventV2Model(
                        aggregate_id=graph_aggregate_id(run_id),
                        version=event.position,
                        event_type=event.event_type,
                        payload=event.model_dump_json(),
                        timestamp=event.timestamp.isoformat(),
                    )
                    for event in (boundary, fact)
                ]
            )

    async with sessions() as session:
        with pytest.raises(GraphReadModelUnavailable, match="event_payload_exceeds_byte_cap"):
            await GraphEventStore(session).read_file_state_report_page(
                run_id,
                from_position=1,
                limit=1,
                path_limit=2,
            )


def _callback_event(run_id: str, position: int, body_size: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"oversized-callback-{position}",
        run_id=run_id,
        position=position,
        event_type="callback_rejected_conflict",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "node_id": "node-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "execution_id": "execution-1",
            "idempotency_key": f"callback-{position}",
            "payload": {"body": "x" * body_size},
            "reason": "fixture",
        },
    )


async def _append(
    sessions: async_sessionmaker[AsyncSession], run_id: str, events: list[EventEnvelope]
) -> None:
    async with sessions() as session:
        async with session.begin():
            position = await GraphEventStore(session).current_position(run_id)
            await GraphEventStore(session).append_events(run_id, position, events)


async def _event_types(sessions: async_sessionmaker[AsyncSession], run_id: str) -> list[str]:
    return [event.event_type for event in await _events(sessions, run_id)]
