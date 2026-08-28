"""Credential/server-gated three-arm reliable-plan live dogfood harness.

The harness never starts a server. Missing dependencies are honest blocked
evidence. With dependencies present it waits boundedly for terminal runs and
builds the strict graph/alternate/legacy comparison from operator read APIs.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from orchestrator.graph import (
    ReliablePlanComparisonArtifact,
    ReliablePlanCorrectnessMetrics,
    ReliablePlanEvaluationConfig,
    ReliablePlanEvaluationResult,
    ReliablePlanGraphShapeMetrics,
    ReliablePlanRecoveryMetrics,
    ReliablePlanUsageMetrics,
    authorize_reliable_plan_one_horizon,
    serialize_authorized_reliable_plan_run_config,
)
from orchestrator.graph_runtime import run_reliable_plan_product_path_scenarios


_REQUIRED_ENV = (
    "RELIABLE_PLAN_E2E_BASE_URL",
    "RELIABLE_PLAN_E2E_ROUTINE_ID",
    "RELIABLE_PLAN_E2E_LEGACY_ROUTINE_ID",
    "RELIABLE_PLAN_E2E_REPO_NAME",
    "RELIABLE_PLAN_E2E_BRANCH",
    "RELIABLE_PLAN_E2E_QUALIFICATION_PATH",
    "OPENAI_API_KEY",
)
_TERMINAL = {"completed", "failed", "cancelled"}


async def _wait_terminal(
    client: httpx.AsyncClient,
    run_id: str,
    *,
    timeout_seconds: float = 900,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run.get("status") in _TERMINAL:
            return run
        await asyncio.sleep(2)
    raise AssertionError(f"run {run_id} did not become terminal within {timeout_seconds}s")


async def _extract_result(
    client: httpx.AsyncClient,
    run: dict[str, Any],
    *,
    arm,
    baseline_kind: str,
) -> ReliablePlanEvaluationResult:
    run_id = str(run["id"])
    graph_response, topology_response, health_response = await asyncio.gather(
        client.get(f"/api/runs/{run_id}/graph"),
        client.get(f"/api/runs/{run_id}/graph/topology?limit=1000"),
        client.get(f"/api/runs/{run_id}/graph/health"),
    )
    for response in (graph_response, topology_response, health_response):
        assert response.status_code == 200, response.text
    graph = graph_response.json()
    topology = topology_response.json()
    health = health_response.json()
    states = graph.get("node_states", {})
    node_ids = sorted(states)
    node_details = []
    for node_id in node_ids:
        response = await client.get(f"/api/runs/{run_id}/graph/nodes/{node_id}")
        assert response.status_code == 200, response.text
        node_details.append(response.json())
    usage = {
        "tokens": sum(int(item.get("usage_summary", {}).get("tokens", 0)) for item in node_details),
        "actions": sum(
            int(item.get("usage_summary", {}).get("actions", 0)) for item in node_details
        ),
        "duration_ms": sum(
            int(item.get("usage_summary", {}).get("duration_ms", 0)) for item in node_details
        ),
    }
    batches = sorted(
        {
            batch
            for item in node_details
            for batch in item.get("declared_batch_ids", [])
            if isinstance(batch, str)
        }
    )
    horizons = sorted(
        {
            horizon
            for item in node_details
            if isinstance((horizon := item.get("planning_horizon")), int)
        }
    )
    leases = graph.get("leases", {})
    failed_count = sum(state == "failed" for state in states.values())
    blockers = health.get("blockers", [])
    recovery_count = sum(item.get("correction_reason") is not None for item in node_details)
    return ReliablePlanEvaluationResult(
        run_id=run_id,
        arm_id=arm.arm_id,
        evidence_status="complete",
        baseline_kind=baseline_kind,
        correctness=ReliablePlanCorrectnessMetrics(
            passed=run.get("status") == "completed" and failed_count == 0 and not blockers,
            terminal_state=graph.get("run_state"),
            final_blocker_count=len(blockers),
            failed_node_count=failed_count,
        ),
        revision_count=sum(max(0, int(item.get("attempt_number", 1)) - 1) for item in node_details),
        graph_shape=ReliablePlanGraphShapeMetrics(
            node_count=len(states),
            edge_count=len(topology.get("edges", [])),
            batch_ids=tuple(batches),
            planning_horizons=tuple(horizons),
        ),
        usage=ReliablePlanUsageMetrics(
            total_tokens=usage["tokens"],
            total_actions=usage["actions"],
            total_duration_ms=usage["duration_ms"],
        ),
        recovery=ReliablePlanRecoveryMetrics(
            infrastructure_failure_count=len(health.get("expired_leases", [])),
            retry_count=sum(
                max(0, int(item.get("attempt_number", 1)) - 1) for item in node_details
            ),
            recovery_node_count=recovery_count,
            revoked_lease_count=sum(lease.get("state") == "revoked" for lease in leases.values()),
            active_lease_count=sum(lease.get("state") == "active" for lease in leases.values()),
        ),
        model_profiles=arm,
    )


@pytest.mark.asyncio
async def test_live_reliable_plan_comparison_uses_terminal_operator_readbacks() -> None:
    missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
    if missing:
        pytest.skip("live reliable-plan evidence blocked: missing " + ", ".join(missing))
    config = ReliablePlanEvaluationConfig.model_validate_json(
        Path("tests/fixtures/graph/reliable_plan_fff4f6b7.json").read_text()
    )
    qualification_run = await run_reliable_plan_product_path_scenarios(
        config.scenario_manifest,
        root=Path(os.environ["RELIABLE_PLAN_E2E_QUALIFICATION_PATH"]),
    )
    gated = authorize_reliable_plan_one_horizon(
        config,
        qualification_run.projection,
        qualification_run.accepted_receipt_record_id,
    )
    qualification = qualification_run.qualification
    base_url = os.environ["RELIABLE_PLAN_E2E_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        try:
            runners_response = await client.get("/api/agent-runners")
        except httpx.HTTPError as exc:
            pytest.skip(f"live reliable-plan evidence blocked: server unavailable: {exc}")
        assert runners_response.status_code == 200
        available = {
            item["type"] for item in runners_response.json() if item.get("available") is True
        }
        if "codex_server" not in available:
            pytest.skip("live reliable-plan evidence blocked: codex_server unavailable")
        grant_response = await client.post("/api/runs/reliable-plan-qualification")
        assert grant_response.status_code == 201, grant_response.text
        qualification_reference = str(grant_response.json()["reference"])

        requests = [
            (gated.luna_arm, "graph", os.environ["RELIABLE_PLAN_E2E_ROUTINE_ID"]),
            (gated.alternate_arm, "graph", os.environ["RELIABLE_PLAN_E2E_ROUTINE_ID"]),
            (
                gated.alternate_arm.model_copy(update={"arm_id": "legacy-plan-then-execute"}),
                "legacy",
                os.environ["RELIABLE_PLAN_E2E_LEGACY_ROUTINE_ID"],
            ),
        ]
        created: list[tuple[Any, str, str]] = []
        for arm, mode, routine_id in requests:
            response = await client.post(
                "/api/runs",
                json={
                    "routine_id": routine_id,
                    "repo_name": os.environ["RELIABLE_PLAN_E2E_REPO_NAME"],
                    "branch": os.environ["RELIABLE_PLAN_E2E_BRANCH"],
                    "execution_mode": mode,
                    "agent_runner_type": arm.implementation_worker.runner_type,
                    "agent_runner_config": {"model": arm.implementation_worker.model},
                    "config": serialize_authorized_reliable_plan_run_config(gated, arm),
                    "reliable_plan_qualification_reference": qualification_reference,
                },
            )
            assert response.status_code == 201, response.text
            run_id = str(response.json()["id"])
            started = await client.post(f"/api/runs/{run_id}/start")
            assert started.status_code == 202, started.text
            created.append((arm, mode, run_id))
            if mode != "legacy":
                grant_response = await client.post("/api/runs/reliable-plan-qualification")
                assert grant_response.status_code == 201, grant_response.text
                qualification_reference = str(grant_response.json()["reference"])

        terminal = await asyncio.gather(
            *(_wait_terminal(client, run_id) for _, _, run_id in created)
        )
        results = [
            await _extract_result(
                client,
                run,
                arm=arm,
                baseline_kind=("legacy_plan_then_execute" if mode == "legacy" else "dynamic_graph"),
            )
            for (arm, mode, _), run in zip(created, terminal, strict=True)
        ]
        comparison = ReliablePlanComparisonArtifact(
            qualification=qualification,
            luna=results[0],
            alternate=results[1],
            legacy_baseline=results[2],
        )
        assert comparison.luna.correctness.passed
        assert comparison.alternate.correctness.passed
        assert comparison.legacy_baseline.correctness.passed
        assert comparison.luna.recovery.active_lease_count == 0
        assert comparison.alternate.recovery.active_lease_count == 0
        assert comparison.deltas is not None
