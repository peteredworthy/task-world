"""E2E coverage for CLIAgent callback instructions against a real HTTP server."""

import asyncio
import socket
import textwrap
from pathlib import Path

import pytest
import uvicorn
from httpx import AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.runners import CLIAgent
from orchestrator.runners.types import ExecutionContext
from orchestrator.workflow import InMemorySignalTransport
from orchestrator.workflow.service import WorkflowService

from tests.integration.signal_helpers import drain_signals

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


def _can_bind_socket() -> bool:
    """Check if we can bind a socket at runtime."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return True
    except PermissionError:
        return False


_needs_socket = pytest.mark.skipif(not _can_bind_socket(), reason="socket.bind blocked")


@pytest.mark.e2e
@_needs_socket
async def test_cli_subprocess_calls_rest_api_and_changes_workflow_state(
    tmp_path: Path,
) -> None:
    """CLIAgent reads callback instructions and drives workflow state over REST."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    db_path = tmp_path / "orchestrator.db"
    app = create_app(
        db_path=str(db_path),
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    signal_transport = InMemorySignalTransport()
    app.state.signal_transport = signal_transport

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    try:
        base_url = f"http://127.0.0.1:{port}"
        async with AsyncClient(base_url=base_url) as client:
            for _ in range(50):
                try:
                    resp = await client.get("/health")
                    if resp.status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("Server did not start")

            resp = await client.post(
                "/api/runs",
                json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
            )
            assert resp.status_code == 201
            run_id = resp.json()["id"]
            task_id = resp.json()["steps"][0]["tasks"][0]["id"]

            resp = await client.post(f"/api/runs/{run_id}/start")
            assert resp.status_code == 202

            async with app.state.session_factory() as drain_session:
                drain_service = WorkflowService(drain_session, signal_transport=signal_transport)
                await drain_signals(run_id, signal_transport, drain_session, drain_service)
                await drain_session.commit()

            resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
            assert resp.status_code == 200

            resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
            assert resp.json()["status"] == "building"

            script = textwrap.dedent("""\
                import json, re, sys, urllib.request
                prompt = sys.stdin.read()
                m = re.search(r'Base URL: (\\S+)', prompt)
                if not m:
                    print('ERROR: No Base URL in prompt', file=sys.stderr)
                    sys.exit(1)
                base = m.group(1)
                m = re.search(r'Run ID: (\\S+), Task ID: (\\S+)', prompt)
                if not m:
                    print('ERROR: No Run/Task ID in prompt', file=sys.stderr)
                    sys.exit(1)
                run_id, task_id = m.group(1), m.group(2)
                url = f'{base}/api/runs/{run_id}/tasks/{task_id}/checklist/R1'
                data = json.dumps({'status': 'done'}).encode()
                req = urllib.request.Request(
                    url, data=data,
                    headers={'Content-Type': 'application/json'},
                    method='PATCH',
                )
                urllib.request.urlopen(req)
                url = f'{base}/api/runs/{run_id}/tasks/{task_id}/submit'
                req = urllib.request.Request(
                    url, data=b'',
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                urllib.request.urlopen(req)
                print('OK')
            """)

            agent = CLIAgent(command="python3", args=["-c", script])
            context = ExecutionContext(
                run_id=run_id,
                task_id=task_id,
                working_dir=str(tmp_path),
                prompt="Complete the work",
                requirements=["R1"],
                api_base_url=base_url,
            )

            async def on_update(req_id: str, status: object, note: str | None) -> None:
                pass

            async def on_submit() -> None:
                pass

            result = await agent.execute(context, on_update, on_submit)
            assert result.success is True

            async with app.state.session_factory() as drain_session:
                service = WorkflowService(drain_session, signal_transport=signal_transport)
                await drain_signals(run_id, signal_transport, drain_session, service)
                await drain_session.commit()

            resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
            assert resp.json()["status"] == "verifying"
            assert resp.json()["checklist"][0]["status"] == "done"

    finally:
        server.should_exit = True
        await server_task
        await app.state.engine.dispose()
