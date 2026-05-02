"""Integration tests for native oversight parent/child orchestration."""

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from orchestrator.workflow.service import WorkflowService
from tests.integration.signal_helpers import DrainFn

EMBEDDED_ROUTINE: dict[str, Any] = {
    "id": "phase5-child-slice",
    "name": "Phase 5 Child Slice",
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


async def test_create_list_start_child_run_and_read_evidence(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    tmp_path: Path,
) -> None:
    client, drain, _, _, app = _shared_app_fixture

    parent_resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": EMBEDDED_ROUTINE,
            "repo_name": "phase5-parent",
            "branch": "main",
            "agent_type": "user_managed",
        },
    )
    assert parent_resp.status_code == 201, parent_resp.text
    parent_id = parent_resp.json()["id"]

    child_resp = await client.post(
        f"/api/runs/{parent_id}/children",
        json={
            "routine_embedded": EMBEDDED_ROUTINE,
            "parent_slice_id": "slice-01",
            "next_action_decision": "continue",
            "start": True,
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

    worktree = tmp_path / "child-worktree"
    evidence_dir = worktree / "docs" / "phase5"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        """{
  "schema_version": "phase4.evidence.v1",
  "slice_id": "slice-01",
  "routine_id": "phase5-child-slice",
  "assumption_tested": "Native child runs can expose structured evidence.",
  "summary": "The child run evidence was retrieved through the API.",
  "commands_run": [{"command": "printf ok", "exit_code": 0, "stdout_excerpt": "ok", "stderr_excerpt": ""}],
  "test_results": [{"name": "evidence", "status": "passed", "details": "valid"}],
  "target_bug_reproduced": "not_targeted",
  "real_frontend_path_exercised": false,
  "real_execution_surface": "API evidence endpoint",
  "files_changed": ["docs/phase5/slice-01-evidence.json"],
  "evidence_files": ["docs/phase5/slice-01-evidence.json"],
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
    assert evidence[0]["path"] == "docs/phase5/slice-01-evidence.json"
    assert evidence[0]["bundle"]["outcome"] == "verified_fix"
