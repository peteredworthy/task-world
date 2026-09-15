"""Subprocess tests for the read-only recovery diagnostic CLI."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


RUN_ID = "d20ff4dd-9cd1-4f29-9df1-d344a0582907"


class _Handler(BaseHTTPRequestHandler):
    responses: dict[str, object] = {}
    paths: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib protocol name
        self.paths.append(self.path)
        value = self.responses.get(self.path)
        if value is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def _run(responses: dict[str, object], run_id: str = RUN_ID) -> subprocess.CompletedProcess[str]:
    _Handler.responses = responses
    _Handler.paths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return subprocess.run(
            [
                sys.executable,
                "examples/recovery/run_diagnostic.py",
                run_id,
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    finally:
        server.shutdown()
        thread.join()


def _run_response(**updates: object) -> dict[str, object]:
    return {
        "id": RUN_ID,
        "status": "paused",
        "is_graph_backed": True,
        **updates,
    }


def test_cli_legacy_run_needs_only_run_response() -> None:
    result = _run({f"/api/runs/{RUN_ID}": _run_response(status="completed", is_graph_backed=False)})
    assert result.returncode == 0
    assert json.loads(result.stdout)["failures"] == []


def test_cli_present_empty_node_states_is_complete() -> None:
    result = _run(
        {
            f"/api/runs/{RUN_ID}": _run_response(status="completed"),
            f"/api/runs/{RUN_ID}/graph": {"run_id": RUN_ID, "node_states": {}},
        }
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["unavailable"] == []


def test_cli_missing_malformed_or_wrong_run_graph_is_partial() -> None:
    graph = {}
    unavailable = "graph:ValidationError"
    result = _run(
        {
            f"/api/runs/{RUN_ID}": _run_response(),
            f"/api/runs/{RUN_ID}/graph": graph,
        }
    )
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["run_id"] == RUN_ID
    assert report["unavailable"] == [unavailable]


def test_cli_truncated_node_states_is_partial() -> None:
    graph = {"run_id": RUN_ID, "node_states": {}, "truncated": True}
    result = _run(
        {
            f"/api/runs/{RUN_ID}": _run_response(),
            f"/api/runs/{RUN_ID}/graph": graph,
        }
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["unavailable"] == ["graph:node_states_truncated"]


def test_cli_empty_or_malformed_failed_node_evidence_is_partial() -> None:
    responses: dict[str, object] = {
        f"/api/runs/{RUN_ID}": _run_response(),
        f"/api/runs/{RUN_ID}/graph": {
            "run_id": RUN_ID,
            "node_states": {"empty": "failed", "bad": "failed", "wrong": "failed"},
        },
        f"/api/runs/{RUN_ID}/graph/nodes/empty": {
            "run_id": RUN_ID,
            "node_id": "empty",
            "callback_history": [],
            "events": [],
        },
        f"/api/runs/{RUN_ID}/graph/nodes/bad": {
            "run_id": RUN_ID,
            "node_id": "bad",
            "events": "not-a-list",
        },
        f"/api/runs/{RUN_ID}/graph/nodes/wrong": {
            "run_id": "another-run",
            "node_id": "wrong",
        },
    }
    result = _run(responses)
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["run_id"] == RUN_ID
    assert report["unavailable"] == ["node:bad", "node:wrong", "node:empty"]
    assert [failure["node_id"] for failure in report["failures"]] == ["bad", "empty", "wrong"]


def test_cli_rejects_wrong_run_response_identity() -> None:
    result = _run(
        {
            f"/api/runs/{RUN_ID}": _run_response(
                id="00000000-0000-0000-0000-000000000001", status="completed"
            )
        }
    )
    assert result.returncode == 2
    assert result.stdout == ""


def test_cli_caps_node_reads_at_ten() -> None:
    nodes = {f"node-{index}": "failed" for index in range(11)}
    responses: dict[str, object] = {
        f"/api/runs/{RUN_ID}": _run_response(status="failed"),
        f"/api/runs/{RUN_ID}/graph": {"run_id": RUN_ID, "node_states": nodes},
    }
    for node_id in nodes:
        responses[f"/api/runs/{RUN_ID}/graph/nodes/{node_id}"] = {
            "run_id": RUN_ID,
            "node_id": node_id,
            "callback_history": [
                {
                    "event_id": f"failure-{node_id}",
                    "position": 100,
                    "event_type": "agent_died",
                    "payload": {"node_id": node_id, "reason": "node failed"},
                }
            ],
            "events": [],
        }
    result = _run(responses)
    assert result.returncode == 1
    assert len(json.loads(result.stdout)["unavailable"]) == 1
    assert len([path for path in _Handler.paths if "/graph/nodes/" in path]) == 10


def test_cli_rejects_oversized_run_response() -> None:
    result = _run({f"/api/runs/{RUN_ID}": "x" * 2_000_001})
    assert result.returncode == 2
    assert result.stdout == ""


def test_cli_invalid_arguments_and_unavailable_server_are_exit_two() -> None:
    invalid = subprocess.run(
        [sys.executable, "examples/recovery/run_diagnostic.py", "not-a-uuid"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert invalid.stdout == ""
    assert "diagnostic unavailable" in invalid.stderr

    unavailable = subprocess.run(
        [
            sys.executable,
            "examples/recovery/run_diagnostic.py",
            RUN_ID,
            "--base-url",
            "http://127.0.0.1:1",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert unavailable.returncode == 2
    assert unavailable.stdout == ""
