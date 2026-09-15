"""Explicit one-shot graph crash barrier contracts."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.graph_runtime import (
    CRASH_BARRIER_AUTHORIZATION,
    CRASH_BARRIER_ENV,
    CrashBarrierError,
    CrashBarrierConfig,
    DisabledCrashBarrier,
    FileCrashBarrier,
    CrashBarrierObservation,
    CrashBarrierPlanConfig,
    CrashBarrierPlanState,
    CrashBarrierRecoveryProof,
    CrashBarrierTarget,
    bounded_crash_barrier_readback,
    crash_barrier_from_environment,
)


async def test_barrier_is_disabled_when_environment_is_absent() -> None:
    barrier = crash_barrier_from_environment({})

    assert isinstance(barrier, DisabledCrashBarrier)
    await barrier.wait_if_armed(
        run_id="run-1",
        execution_id="exec-1",
        point="after_staging_pre_witness",
    )


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "{}",
        json.dumps(
            {
                "authorization": "not-authorized",
                "run_id": "run-1",
                "execution_id": "exec-1",
                "point": "after_staging_pre_witness",
            }
        ),
    ],
)
def test_nonempty_malformed_or_unauthorized_barrier_fails_closed(raw: str) -> None:
    with pytest.raises(CrashBarrierError):
        crash_barrier_from_environment({CRASH_BARRIER_ENV: raw})


async def test_exact_scoped_barrier_is_observable_releasable_and_one_shot(
    tmp_path,
) -> None:
    barrier = FileCrashBarrier(
        CrashBarrierConfig(
            authorization=CRASH_BARRIER_AUTHORIZATION,
            run_id="run-1",
            execution_id="exec-1",
            point="after_staging_pre_witness",
        ),
        state_dir=tmp_path,
    )
    await barrier.wait_if_armed(
        run_id="another-run",
        execution_id="exec-1",
        point="after_staging_pre_witness",
    )

    waiter = asyncio.create_task(
        barrier.wait_if_armed(
            run_id="run-1",
            execution_id="exec-1",
            point="after_staging_pre_witness",
        )
    )
    while True:
        state = barrier.read_status()
        if state is not None:
            break
        await asyncio.sleep(0.01)

    assert state.status == "reached"
    assert state.run_id == "run-1"
    assert state.execution_id == "exec-1"
    assert waiter.done() is False
    barrier.release()
    await asyncio.wait_for(waiter, timeout=1)
    released = barrier.read_status()
    assert released is not None
    assert released.status == "released"

    # A released barrier is one-shot and cannot stop the same boundary again.
    await asyncio.wait_for(
        barrier.wait_if_armed(
            run_id="run-1",
            execution_id="exec-1",
            point="after_staging_pre_witness",
        ),
        timeout=0.1,
    )


@pytest.mark.parametrize(
    ("point", "attempt_state"),
    [
        ("pre_stage", "baseline_captured"),
        ("after_staging_pre_witness", "submission_staged"),
        ("after_witness_pre_finalization", "completion_witnessed"),
        ("after_commit_pre_ack", "finalized"),
    ],
)
async def test_schema_one_supports_the_outer_decision_crash_boundaries(
    tmp_path: Path,
    point: str,
    attempt_state: str,
) -> None:
    barrier = FileCrashBarrier(
        CrashBarrierConfig(
            authorization=CRASH_BARRIER_AUTHORIZATION,
            run_id="run-outer-boundary",
            execution_id="exec-outer-boundary",
            point=point,
        ),
        state_dir=tmp_path,
        poll_seconds=0.01,
    )
    waiter = asyncio.create_task(
        barrier.wait_if_armed(
            run_id="run-outer-boundary",
            execution_id="exec-outer-boundary",
            point=point,
            observation=CrashBarrierObservation(
                run_id="run-outer-boundary",
                node_id="worker-1",
                execution_id="exec-outer-boundary",
                lease_id="lease-1",
                lease_generation=1,
                node_kind="worker",
                node_role="builder",
                semantic_stage="effectful_batch",
                point=point,
                attempt_state=attempt_state,
            ),
        )
    )
    while barrier.read_status() is None:
        await asyncio.sleep(0.01)
    barrier.release()
    await asyncio.wait_for(waiter, timeout=1)
    state = barrier.read_status()
    assert state is not None and state.status == "released"


def _plan_config(run_id: str = "run-1") -> CrashBarrierPlanConfig:
    return CrashBarrierPlanConfig(
        schema_version=2,
        authorization=CRASH_BARRIER_AUTHORIZATION,
        run_id=run_id,
        nonce="drill_nonce_123456",
        target=CrashBarrierTarget(kind="worker", semantic_stage="effectful_batch"),
        slots=("after_staging_pre_witness", "after_witness_pre_finalization"),
    )


def _observation(
    *,
    execution_id: str,
    generation: int,
    point: str = "after_staging_pre_witness",
    run_id: str = "run-1",
    node_id: str = "effectful-1",
    kind: str = "worker",
    stage: str = "effectful_batch",
    recovered: tuple[CrashBarrierRecoveryProof, ...] = (),
) -> CrashBarrierObservation:
    return CrashBarrierObservation(
        run_id=run_id,
        node_id=node_id,
        execution_id=execution_id,
        lease_id=f"lease-{generation}",
        lease_generation=generation,
        node_kind=kind,
        node_role="builder",
        semantic_stage=stage,
        point=point,
        attempt_state=(
            "submission_staged" if point == "after_staging_pre_witness" else "completion_witnessed"
        ),
        recovered_attempts=recovered,
    )


async def test_schema_two_atomically_binds_only_one_matching_first_execution(tmp_path) -> None:
    barrier = FileCrashBarrier(_plan_config(), state_dir=tmp_path, poll_seconds=0.01)
    excluded = (
        _observation(execution_id="cross-run", generation=1, run_id="run-2"),
        _observation(execution_id="planner", generation=1, kind="planner"),
        _observation(execution_id="other-stage", generation=1, stage="discovery"),
    )
    for observation in excluded:
        await barrier.wait_if_armed(
            run_id=observation.run_id,
            execution_id=observation.execution_id,
            point=observation.point,
            observation=observation,
        )
    initial = barrier.read_status()
    assert isinstance(initial, CrashBarrierPlanState)
    assert initial.slots[0].status == "unbound"

    first = _observation(execution_id="exec-a", generation=1)
    second = _observation(execution_id="exec-b", generation=1, node_id="effectful-2")
    tasks = [
        asyncio.create_task(
            barrier.wait_if_armed(
                run_id=item.run_id,
                execution_id=item.execution_id,
                point=item.point,
                observation=item,
            )
        )
        for item in (first, second)
    ]
    while True:
        state = barrier.read_status()
        assert isinstance(state, CrashBarrierPlanState)
        if state.slots[0].status == "reached":
            break
        await asyncio.sleep(0.01)
    assert state.slots[0].execution_id in {"exec-a", "exec-b"}
    barrier.release(slot=1)
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
    final = barrier.read_status()
    assert isinstance(final, CrashBarrierPlanState)
    assert final.slots[0].status == "released"


async def test_schema_two_requires_dead_owner_and_exact_recovery_lineage_for_slot_two(
    tmp_path: Path,
) -> None:
    config = _plan_config()
    raw_config = config.model_dump_json()
    script = """
import asyncio, os
from pathlib import Path
from orchestrator.graph_runtime import crash_barrier_from_environment, CrashBarrierObservation
b = crash_barrier_from_environment({'ORCHESTRATOR_GRAPH_CRASH_BARRIER': os.environ['DRILL']}, state_dir=Path(os.environ['STATE']))
o = CrashBarrierObservation(run_id='run-1', node_id='effectful-1', execution_id='exec-1', lease_id='lease-1', lease_generation=1, node_kind='worker', node_role='builder', semantic_stage='effectful_batch', point='after_staging_pre_witness', attempt_state='submission_staged')
asyncio.run(b.wait_if_armed(run_id=o.run_id, execution_id=o.execution_id, point=o.point, observation=o))
"""
    environment = {**os.environ, "DRILL": raw_config, "STATE": str(tmp_path)}
    child = subprocess.Popen([sys.executable, "-c", script], env=environment)
    barrier = FileCrashBarrier(config, state_dir=tmp_path, poll_seconds=0.01)
    try:
        while True:
            state = barrier.read_status()
            assert isinstance(state, CrashBarrierPlanState)
            if state.slots[0].status == "reached":
                break
            if child.poll() is not None:
                raise AssertionError(f"barrier child exited early: {child.returncode}")
            await asyncio.sleep(0.01)
        live_owner_observation = _observation(execution_id="exec-2", generation=2)
        with pytest.raises(CrashBarrierError, match="live or reused"):
            await barrier.wait_if_armed(
                run_id=live_owner_observation.run_id,
                execution_id=live_owner_observation.execution_id,
                point=live_owner_observation.point,
                observation=live_owner_observation,
            )
        child.kill()
        child.wait(timeout=2)
        first = _observation(execution_id="exec-1", generation=1)
        await barrier.wait_if_armed(
            run_id=first.run_id,
            execution_id=first.execution_id,
            point=first.point,
            observation=first,
        )
        consumed = barrier.read_status()
        assert isinstance(consumed, CrashBarrierPlanState)
        assert consumed.slots[0].status == "consumed_after_process_loss"

        insufficient = _observation(
            execution_id="exec-2",
            generation=2,
            point="after_witness_pre_finalization",
        )
        await barrier.wait_if_armed(
            run_id=insufficient.run_id,
            execution_id=insufficient.execution_id,
            point=insufficient.point,
            observation=insufficient,
        )
        still_unbound = barrier.read_status()
        assert isinstance(still_unbound, CrashBarrierPlanState)
        assert still_unbound.slots[1].status == "unbound"

        proof = CrashBarrierRecoveryProof(
            node_id="effectful-1",
            execution_id="exec-1",
            lease_generation=1,
            state="recovered",
            completion_disposition="restored_unwitnessed",
            retry_authorized=True,
        )
        successor = insufficient.model_copy(update={"recovered_attempts": (proof,)})
        waiter = asyncio.create_task(
            barrier.wait_if_armed(
                run_id=successor.run_id,
                execution_id=successor.execution_id,
                point=successor.point,
                observation=successor,
            )
        )
        while True:
            reached = barrier.read_status()
            assert isinstance(reached, CrashBarrierPlanState)
            if reached.slots[1].status == "reached":
                break
            await asyncio.sleep(0.01)
        assert reached.slots[1].node_id == reached.slots[0].node_id
        assert reached.slots[1].lease_generation == 2
        barrier.release(slot=2)
        await waiter
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)


def test_schema_two_environment_is_strict_and_initializes_bounded_state(tmp_path) -> None:
    config = _plan_config()
    barrier = crash_barrier_from_environment(
        {CRASH_BARRIER_ENV: config.model_dump_json()}, state_dir=tmp_path
    )
    state = barrier.read_status()
    assert isinstance(state, CrashBarrierPlanState)
    assert state.run_id == "run-1"
    assert state.slots[0].status == state.slots[1].status == "unbound"
    assert len(state.config_hash) == 64
    assert not list(tmp_path.iterdir())
    assert "release_token" not in json.dumps(bounded_crash_barrier_readback(state))

    malformed = config.model_dump(mode="json")
    malformed["slots"] = list(reversed(malformed["slots"]))
    with pytest.raises(CrashBarrierError):
        crash_barrier_from_environment({CRASH_BARRIER_ENV: json.dumps(malformed)})
