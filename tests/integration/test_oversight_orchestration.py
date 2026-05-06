"""Integration tests for native oversight parent/child orchestration."""

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from orchestrator.api import get_runner_executor
from orchestrator.workflow.service import WorkflowService
from tests.integration.git_helpers import _git
from tests.integration.signal_helpers import DrainFn

EMBEDDED_ROUTINE: dict[str, Any] = {
    "id": "native-child-slice",
    "name": "Native Child Slice",
    "steps": [
        {
            "id": "S-01",
            "title": "Slice",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Prove slice",
                    "task_context": "Write evidence.",
                    "requirements": [{"id": "R1", "desc": "Evidence is present"}],
                }
            ],
        }
    ],
}


class RecordingExecutor:
    """Small executor test double that records cancelled run IDs."""

    def __init__(self) -> None:
        self.cancelled_run_ids: list[str] = []

    async def cancel_run(self, run_id: str) -> None:
        self.cancelled_run_ids.append(run_id)


async def test_create_list_start_child_run_and_read_evidence(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    git_repo: Path,
    tmp_path: Path,
) -> None:
    client, drain, _, _, app = _shared_app_fixture

    parent_resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": EMBEDDED_ROUTINE,
            "repo_name": git_repo.name,
            "branch": "main",
            "agent_runner_type": "user_managed",
        },
    )
    assert parent_resp.status_code == 201, parent_resp.text
    parent_id = parent_resp.json()["id"]

    start_parent_resp = await client.post(f"/api/runs/{parent_id}/start")
    assert start_parent_resp.status_code == 202, start_parent_resp.text
    await drain(parent_id)

    child_resp = await client.post(
        f"/api/runs/{parent_id}/children",
        json={
            "routine_embedded": EMBEDDED_ROUTINE,
            "parent_slice_id": "slice-01",
            "next_action_decision": "continue",
        },
    )
    assert child_resp.status_code == 201, child_resp.text
    child = child_resp.json()
    child_id = child["id"]
    assert child["parent_run_id"] == parent_id
    assert child["parent_slice_id"] == "slice-01"
    assert child["status"] == "draft"

    await drain(child_id)
    child_after_start = (await client.get(f"/api/runs/{child_id}")).json()
    assert child_after_start["status"] == "active"

    children_resp = await client.get(f"/api/runs/{parent_id}/children")
    assert children_resp.status_code == 200, children_resp.text
    children = children_resp.json()["children"]
    assert [item["id"] for item in children] == [child_id]

    parent_after_child = (await client.get(f"/api/runs/{parent_id}")).json()
    assert parent_after_child["oversight_state"]["last_child_run_id"] == child_id
    assert parent_after_child["oversight_state"]["slices"][0]["slice_id"] == "slice-01"
    parent_worktree = Path(parent_after_child["worktree_path"])
    report_path = parent_worktree / "docs" / "super-parent" / "final-report.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("# Final validation\n", encoding="utf-8")
    parent_head = _git(["rev-parse", "HEAD"], cwd=parent_worktree)

    worktree = tmp_path / "child-worktree"
    evidence_dir = worktree / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        """{
  "schema_version": "run.evidence.v1",
  "slice_id": "slice-01",
  "routine_id": "native-child-slice",
  "assumption_tested": "Native child runs can expose structured evidence.",
  "summary": "The child run evidence was retrieved through the API.",
  "commands_run": [{"command": "printf ok", "exit_code": 0, "stdout_excerpt": "ok", "stderr_excerpt": ""}],
  "test_results": [{"name": "evidence", "status": "passed", "details": "valid"}],
  "target_bug_reproduced": "not_targeted",
  "real_frontend_path_exercised": false,
  "real_execution_surface": "API evidence endpoint",
  "files_changed": ["docs/run-evidence/slice-01-evidence.json"],
  "evidence_files": ["docs/run-evidence/slice-01-evidence.json"],
  "open_uncertainties": [],
  "next_recommendation": "proceed",
  "outcome": "verified_fix"
}""",
        encoding="utf-8",
    )

    async with app.state.session_factory() as session:
        service = WorkflowService(session)
        await service.set_worktree_path(child_id, str(worktree))

    evidence_resp = await client.get(f"/api/runs/{child_id}/evidence")
    assert evidence_resp.status_code == 200, evidence_resp.text
    evidence = evidence_resp.json()["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["path"] == "docs/run-evidence/slice-01-evidence.json"
    assert evidence[0]["bundle"]["outcome"] == "verified_fix"

    parent_detail = (await client.get(f"/api/runs/{parent_id}")).json()
    parent_detail_oversight = parent_detail["oversight_state"]
    assert parent_detail_oversight["child_count"] == 1
    assert parent_detail_oversight["child_summaries"][0]["evidence"][0]["path"] == (
        "docs/run-evidence/slice-01-evidence.json"
    )

    run_list_resp = await client.get("/api/runs")
    assert run_list_resp.status_code == 200, run_list_resp.text
    parent_list_item = next(
        item for item in run_list_resp.json()["runs"] if item["id"] == parent_id
    )
    assert parent_list_item["oversight_state"]["child_count"] == 1

    refresh_resp = await client.post(f"/api/runs/{parent_id}/oversight/refresh")
    assert refresh_resp.status_code == 200, refresh_resp.text
    oversight = refresh_resp.json()["oversight_state"]
    assert oversight["child_count"] == 1
    assert oversight["child_summaries"][0]["run_id"] == child_id
    assert oversight["terminal_guard"]["can_complete"] is False

    get_oversight_resp = await client.get(f"/api/runs/{parent_id}/oversight")
    assert get_oversight_resp.status_code == 200, get_oversight_resp.text
    assert get_oversight_resp.json()["oversight_state"]["child_count"] == 1

    update_resp = await client.patch(
        f"/api/runs/{parent_id}/oversight",
        json={
            "current_understanding": {"summary": "one child is active"},
            "target_inventory": [{"id": "INV-001", "resolved": True}],
            "final_validation": {
                "passed": True,
                "integrated_commit_sha": parent_head,
                "report_path": "docs/super-parent/final-report.md",
                "commands_run": [
                    {
                        "command": "uv run pytest tests/integration/test_oversight_orchestration.py",
                        "exit_code": 0,
                    }
                ],
                "evidence_files": ["docs/super-parent/final-report.md"],
            },
            "decision": {"kind": "inventory_update", "target_id": "INV-001"},
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    updated_state = update_resp.json()["oversight_state"]
    assert updated_state["current_understanding"] == {"summary": "one child is active"}
    assert updated_state["target_inventory"][0]["id"] == "INV-001"
    assert updated_state["final_validation"]["passed"] is True
    assert updated_state["final_validation"]["service_verified"] is True
    assert updated_state["decisions"][0]["kind"] == "inventory_update"
    assert updated_state["terminal_guard"]["can_complete"] is False


async def test_parent_pause_cancels_active_child_executor(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    git_repo: Path,
) -> None:
    client, drain, _, _, app = _shared_app_fixture
    recorder = RecordingExecutor()
    app.dependency_overrides[get_runner_executor] = lambda: recorder
    try:
        parent_resp = await client.post(
            "/api/runs",
            json={
                "routine_embedded": EMBEDDED_ROUTINE,
                "repo_name": git_repo.name,
                "branch": "main",
                "agent_runner_type": "user_managed",
            },
        )
        assert parent_resp.status_code == 201, parent_resp.text
        parent_id = parent_resp.json()["id"]

        start_parent_resp = await client.post(f"/api/runs/{parent_id}/start")
        assert start_parent_resp.status_code == 202, start_parent_resp.text
        await drain(parent_id)

        child_resp = await client.post(
            f"/api/runs/{parent_id}/children",
            json={
                "routine_embedded": EMBEDDED_ROUTINE,
                "parent_slice_id": "slice-01",
                "next_action_decision": "continue",
            },
        )
        assert child_resp.status_code == 201, child_resp.text
        child_id = child_resp.json()["id"]
        await drain(child_id)

        pause_resp = await client.post(f"/api/runs/{parent_id}/pause")
        assert pause_resp.status_code == 202, pause_resp.text

        assert recorder.cancelled_run_ids == [parent_id, child_id]
    finally:
        app.dependency_overrides.pop(get_runner_executor, None)
