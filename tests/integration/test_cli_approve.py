"""Integration tests for execution-mode-aware CLI approvals."""

from typing import Any

from click.testing import CliRunner
from fastapi import FastAPI
from httpx import ASGITransport

from orchestrator.cli.approve import _graph_approval_payload
from orchestrator.cli.main import cli


def test_graph_approval_payload_is_typed() -> None:
    assert _graph_approval_payload(
        node_id="gate-1",
        approved=False,
        decider_id="alice",
        reason="Needs correction.",
    ) == {
        "decision_type": "approval",
        "node_id": "gate-1",
        "decision": "rejected",
        "decider": {"kind": "human", "id": "alice", "role": "operator"},
        "reason": "Needs correction.",
    }


def _approval_app(execution_mode: str) -> tuple[FastAPI, list[dict[str, Any]], list[str]]:
    app = FastAPI()
    submissions: list[dict[str, Any]] = []
    requests: list[str] = []

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, str]:
        requests.append(f"run:{run_id}")
        return {"id": run_id, "execution_mode": execution_mode}

    @app.get("/api/runs/{run_id}/graph/decisions")
    async def get_graph_decisions(run_id: str) -> dict[str, Any]:
        requests.append(f"graph:{run_id}")
        return {
            "run_id": run_id,
            "event_count": 1,
            "pending_gates": [
                {
                    "node_id": "gate-1",
                    "gate_type": "human_approval",
                    "prompt": "Approve verified candidate?",
                },
                {
                    "node_id": "authority-1",
                    "gate_type": "authority_request",
                    "prompt": "Grant write access?",
                },
            ],
            "appeals": [],
            "review": {"ready": False, "blockers": []},
        }

    @app.post("/api/runs/{run_id}/graph/decisions")
    async def post_graph_decision(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        requests.append(f"graph-post:{run_id}")
        submissions.append(payload)
        return {"run_id": run_id, "graph_position": 2, "events": [], "decision_view": {}}

    @app.get("/api/runs/{run_id}/pending-actions")
    async def get_pending_actions(run_id: str) -> list[dict[str, Any]]:
        requests.append(f"legacy:{run_id}")
        return [
            {
                "action_type": "approval",
                "task_id": "task-1",
                "step_id": "step-1",
                "summary_artifact": "Verified output",
                "approval_prompt": "Continue?",
            }
        ]

    @app.post("/api/runs/{run_id}/steps/{step_id}/approve")
    async def post_step_approval(
        run_id: str, step_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        requests.append(f"legacy-post:{run_id}:{step_id}")
        submissions.append(payload)
        return {"human_approval": {"approved_by": payload["approved_by"]}}

    return app, submissions, requests


def test_graph_run_discovers_and_rejects_pending_human_gate() -> None:
    app, submissions, requests = _approval_app("graph")

    result = CliRunner().invoke(
        cli,
        ["runs", "approve", "graph-run", "--url", "http://test"],
        input="n\nalice\nNeeds correction.\n",
        obj={"http_transport": ASGITransport(app=app)},
    )

    assert result.exit_code == 0, result.output
    assert submissions == [
        {
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "rejected",
            "decider": {"kind": "human", "id": "alice", "role": "operator"},
            "reason": "Needs correction.",
        }
    ]
    assert requests == ["run:graph-run", "graph:graph-run", "graph-post:graph-run"]


def test_graph_run_approves_pending_human_gate() -> None:
    app, submissions, _requests = _approval_app("graph")

    result = CliRunner().invoke(
        cli,
        ["runs", "approve", "graph-run", "--url", "http://test"],
        input="y\nalice\nReviewed output.\n",
        obj={"http_transport": ASGITransport(app=app)},
    )

    assert result.exit_code == 0, result.output
    assert submissions[0]["decision"] == "approved"
    assert submissions[0]["reason"] == "Reviewed output."


def test_legacy_run_keeps_step_approval_no_answer_behavior() -> None:
    app, submissions, requests = _approval_app("legacy")

    result = CliRunner().invoke(
        cli,
        ["runs", "approve", "legacy-run", "--url", "http://test"],
        input="n\nalice\nn\n",
        obj={"http_transport": ASGITransport(app=app)},
    )

    assert result.exit_code == 0, result.output
    assert submissions == [{"approved_by": "alice", "comment": None}]
    assert requests == ["run:legacy-run", "legacy:legacy-run", "legacy-post:legacy-run:step-1"]
