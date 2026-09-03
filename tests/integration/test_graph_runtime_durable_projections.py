"""Canonical-event recovery for disposable graph runtime read models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete

from orchestrator.db import (
    create_engine,
    create_session_factory,
    GraphRuntimeSupervisionModel,
    GraphRuntimeSupervisionRepository,
    GraphSubmissionGateAuditModel,
    GraphSubmissionGateAuditRepository,
    SqliteEventStore,
    init_db,
)
from orchestrator.workflow import GraphRuntimeReconciled, GraphSubmissionGateAudited


async def test_supervision_readback_recovers_from_canonical_event(
    tmp_path,
) -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    engine = create_engine(tmp_path / "supervision.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await SqliteEventStore(session).append(
            GraphRuntimeReconciled(
                run_id="run-1",
                timestamp=now,
                graph_position=17,
                progress_fingerprint="semantic-progress",
                no_progress_attempts=2,
                driver_generation=3,
                driver_state="missing",
                action="missing_driver_rearmed",
                staged_count=1,
                active_lease_count=1,
            )
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(delete(GraphRuntimeSupervisionModel))
        await session.commit()
        recovered = await GraphRuntimeSupervisionRepository(session).get("run-1")

    assert recovered is not None
    assert recovered.observed_position == 17
    assert recovered.no_progress_attempts == 2
    assert recovered.last_action == "missing_driver_rearmed"
    assert recovered.staged_count == 1
    await engine.dispose()


async def test_gate_audit_readback_recovers_from_canonical_event(
    tmp_path,
) -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    engine = create_engine(tmp_path / "gate-audits.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    event = GraphSubmissionGateAudited(
        run_id="run-1",
        timestamp=now,
        node_id="worker-1",
        execution_id="exec-1",
        phase="baseline",
        base_snapshot_id="snapshot-1",
        base_tree_sha="a" * 40,
        status="failed",
        failure_fingerprint="fingerprint-1",
        report={"schema_version": 1, "results": []},
    )
    async with session_factory() as session:
        (stored,) = await SqliteEventStore(session).append(event)
        await GraphSubmissionGateAuditRepository(session).append(
            canonical_position=stored.position,
            run_id=event.run_id,
            node_id=event.node_id,
            execution_id=event.execution_id,
            phase=event.phase,
            base_snapshot_id=event.base_snapshot_id,
            base_tree_sha=event.base_tree_sha,
            candidate_tree_sha=event.candidate_tree_sha,
            status=event.status,
            failure_fingerprint=event.failure_fingerprint,
            report=event.report,
            created_at=event.timestamp,
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(delete(GraphSubmissionGateAuditModel))
        await session.commit()
        repository = GraphSubmissionGateAuditRepository(session)
        baseline = await repository.latest_baseline("run-1", "exec-1")
        page = await repository.list_for_run("run-1", limit=20)

    assert baseline is not None
    assert baseline.id == stored.position
    assert baseline.failure_fingerprint == "fingerprint-1"
    assert page == (baseline,)
    await engine.dispose()
