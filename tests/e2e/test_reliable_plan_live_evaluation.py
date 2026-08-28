"""Credential/server-gated three-arm reliable-plan live dogfood harness.

The harness never starts a server. Missing dependencies are honest blocked
evidence. With dependencies present it waits boundedly for terminal runs and
builds the strict graph/alternate/legacy comparison from operator read APIs.
"""

from __future__ import annotations

import asyncio
import json
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
    "RELIABLE_PLAN_E2E_FEATURE_SPEC_PATH",
    "RELIABLE_PLAN_E2E_ACCEPTANCE_COMMAND",
    "OPENAI_API_KEY",
)
_TERMINAL = {"completed", "failed", "cancelled", "paused"}


async def _wait_terminal(
    client: httpx.AsyncClient,
    run_id: str,
    *,
    timeout_seconds: float = 3600,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_poll_error: httpx.HTTPError | None = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            response = await client.get(f"/api/runs/{run_id}")
        except httpx.HTTPError as exc:
            last_poll_error = exc
            await asyncio.sleep(2)
            continue
        assert response.status_code == 200, response.text
        run = response.json()
        if run.get("status") in _TERMINAL:
            return run
        await asyncio.sleep(2)
    detail = f"; last polling error: {last_poll_error}" if last_poll_error else ""
    raise AssertionError(f"run {run_id} did not become terminal within {timeout_seconds}s{detail}")


async def _read_canonical_graph_events(
    client: httpx.AsyncClient,
    run_id: str,
) -> list[dict[str, Any]]:
    """Read the canonical bounded event pages when summary views are unavailable."""
    events: list[dict[str, Any]] = []
    from_position = 0
    while True:
        response = await client.get(
            f"/api/runs/{run_id}/graph/events",
            params={
                "from_position": from_position,
                "limit": 100,
                "payload_mode": "full",
            },
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert isinstance(page, list)
        events.extend(page)
        if response.headers.get("X-Has-More") != "true":
            return events
        next_position = response.headers.get("X-Next-Position")
        assert next_position not in {None, "null"}
        parsed_position = int(next_position)
        assert parsed_position > from_position
        from_position = parsed_position


async def _extract_result(
    client: httpx.AsyncClient,
    run: dict[str, Any],
    *,
    arm,
    baseline_kind: str,
) -> ReliablePlanEvaluationResult:
    run_id = str(run["id"])
    graph_response, health_response, graph_events = await asyncio.gather(
        client.get(f"/api/runs/{run_id}/graph"),
        client.get(f"/api/runs/{run_id}/graph/health"),
        _read_canonical_graph_events(client, run_id),
    )
    for response in (graph_response, health_response):
        assert response.status_code == 200, response.text
    graph = graph_response.json()
    health = health_response.json()
    states = graph.get("node_states", {})
    node_payloads = [
        event.get("payload", {})
        for event in graph_events
        if event.get("event_type") == "node_created"
    ]
    usage_payloads_by_key = {
        str(payload.get("usage_key")): payload
        for event in graph_events
        if event.get("event_type") == "node_usage_recorded"
        and isinstance((payload := event.get("payload")), dict)
    }
    usage_payloads = list(usage_payloads_by_key.values())
    token_kinds: dict[str, int] = {}
    action_kinds: dict[str, int] = {}
    duration_kinds: dict[str, int] = {}
    for payload in usage_payloads:
        node_kind = str(payload.get("node_kind", "unknown"))
        token_kinds[node_kind] = (
            token_kinds.get(node_kind, 0)
            + int(payload.get("gen_ai_usage_input_tokens", 0))
            + int(payload.get("gen_ai_usage_output_tokens", 0))
        )
        if int(payload.get("usage_index", 0)) == 0:
            action_kinds[node_kind] = action_kinds.get(node_kind, 0) + int(
                payload.get("num_actions", 0)
            )
            duration_kinds[node_kind] = duration_kinds.get(node_kind, 0) + int(
                payload.get("latency_ms", 0)
            )
    if not usage_payloads:
        token_kinds["legacy"] = int(run.get("total_tokens_read", 0)) + int(
            run.get("total_tokens_write", 0)
        )
        action_kinds["legacy"] = int(run.get("total_num_actions", 0))
        duration_kinds["legacy"] = int(run.get("total_duration_ms", 0))
    batches: set[str] = set()
    for payload in node_payloads:
        if isinstance((batch := payload.get("declared_batch_id")), str):
            batches.add(batch)
        batches.update(
            batch for batch in payload.get("declared_batch_ids", []) if isinstance(batch, str)
        )
    horizons = sorted(
        {
            horizon
            for payload in node_payloads
            if isinstance((horizon := payload.get("planning_horizon")), int)
        }
    )
    attempts: dict[str, int] = {}
    for event in graph_events:
        if event.get("event_type") != "lease_granted":
            continue
        payload = event.get("payload", {})
        node_id = payload.get("node_id")
        generation = payload.get("generation")
        if isinstance(node_id, str) and isinstance(generation, int):
            attempts[node_id] = max(attempts.get(node_id, 0), generation)
    revision_count = sum(max(0, attempt - 1) for attempt in attempts.values())
    leases = graph.get("leases", {})
    failed_count = sum(state == "failed" for state in states.values())
    blockers = health.get("blockers", [])
    recovery_count = sum(payload.get("correction_reason") is not None for payload in node_payloads)
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
        revision_count=revision_count,
        graph_shape=ReliablePlanGraphShapeMetrics(
            node_count=len(states),
            edge_count=sum(event.get("event_type") == "edge_created" for event in graph_events),
            batch_ids=tuple(sorted(batches)),
            planning_horizons=tuple(horizons),
        ),
        usage=ReliablePlanUsageMetrics(
            total_tokens=sum(token_kinds.values()),
            total_actions=sum(action_kinds.values()),
            total_duration_ms=sum(duration_kinds.values()),
            tokens_by_node_kind=token_kinds,
            actions_by_node_kind=action_kinds,
            duration_ms_by_node_kind=duration_kinds,
        ),
        recovery=ReliablePlanRecoveryMetrics(
            infrastructure_failure_count=len(health.get("expired_leases", [])),
            retry_count=revision_count,
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
            item["agent_runner_type"]
            for item in runners_response.json()
            if item.get("available") is True
        }
        if "codex_server" not in available:
            pytest.skip("live reliable-plan evidence blocked: codex_server unavailable")
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
        existing_run_ids = tuple(
            item.strip()
            for item in os.getenv("RELIABLE_PLAN_E2E_EXISTING_RUN_IDS", "").split(",")
            if item.strip()
        )
        if existing_run_ids:
            assert len(existing_run_ids) == len(requests), (
                "RELIABLE_PLAN_E2E_EXISTING_RUN_IDS must contain the Luna, alternate, "
                "and legacy run IDs in that order"
            )
            created.extend(
                (arm, mode, run_id)
                for (arm, mode, _), run_id in zip(requests, existing_run_ids, strict=True)
            )
        else:
            grant_response = await client.post("/api/runs/reliable-plan-qualification")
            assert grant_response.status_code == 201, grant_response.text
            qualification_reference = str(grant_response.json()["reference"])
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
                        "config": {
                            "feature_spec_path": os.environ["RELIABLE_PLAN_E2E_FEATURE_SPEC_PATH"],
                            "acceptance_command": os.environ[
                                "RELIABLE_PLAN_E2E_ACCEPTANCE_COMMAND"
                            ],
                            **serialize_authorized_reliable_plan_run_config(gated, arm),
                        },
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
        evidence_path = (
            Path(os.environ["RELIABLE_PLAN_E2E_QUALIFICATION_PATH"])
            / "reliable-plan-comparison.json"
        )
        await asyncio.to_thread(
            evidence_path.write_text,
            json.dumps(comparison.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        )
        assert comparison.luna.correctness.passed
        assert comparison.alternate.correctness.passed
        assert comparison.legacy_baseline.correctness.passed
        assert comparison.luna.recovery.active_lease_count == 0
        assert comparison.alternate.recovery.active_lease_count == 0
        assert comparison.deltas is not None
