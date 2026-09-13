"""Product-path responsiveness while submission waits in a real Git hook."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from httpx import AsyncClient

from tests.integration.conftest import _git
from tests.integration.signal_helpers import DrainFn


def _install_waiting_hook(
    worktree_path: Path,
    marker: Path,
    release: Path,
) -> None:
    hook_path = Path(_git(["rev-parse", "--git-path", "hooks/pre-commit"], cwd=worktree_path))
    if not hook_path.is_absolute():
        hook_path = worktree_path / hook_path
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(
        "#!/bin/sh\n"
        f"touch {shlex.quote(str(marker))}\n"
        "attempt=0\n"
        f"while [ ! -f {shlex.quote(str(release))} ] && [ $attempt -lt 500 ]; do\n"
        "  attempt=$((attempt + 1))\n"
        "  sleep 0.01\n"
        "done\n"
        f"[ -f {shlex.quote(str(release))} ] || exit 97\n"
    )
    hook_path.chmod(0o755)


async def _wait_for_file(path: Path, submit: asyncio.Task) -> None:
    async with asyncio.timeout(3):
        while not path.exists():
            if submit.done():
                response = submit.result()
                raise AssertionError(
                    "submission exited before the Git hook started: "
                    f"{response.status_code} {response.text}"
                )
            await asyncio.sleep(0.01)


async def test_health_and_run_read_remain_responsive_during_submit_hook(
    client_with_repo: tuple[AsyncClient, Path, DrainFn],
    tmp_path: Path,
) -> None:
    client, repo_path, drain = client_with_repo
    create_response = await client.post(
        "/api/runs",
        json={
            "execution_mode": "legacy",
            "routine_id": "auto-verify-routine",
            "repo_name": repo_path.name,
            "branch": "main",
        },
    )
    assert create_response.status_code == 201
    run = create_response.json()
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    start_response = await client.post(f"/api/runs/{run_id}/start")
    assert start_response.status_code == 202
    await drain(run_id)
    run = (await client.get(f"/api/runs/{run_id}")).json()
    worktree_path = Path(run["worktree_path"])

    task_start = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert task_start.status_code == 200
    checklist = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    assert checklist.status_code == 200

    marker = tmp_path / "hook-started"
    release = tmp_path / "hook-release"
    _install_waiting_hook(worktree_path, marker, release)
    (worktree_path / "responsive-submit.txt").write_text("preserved by submission\n")

    submit = asyncio.create_task(client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit"))
    try:
        await _wait_for_file(marker, submit)

        async with asyncio.timeout(1):
            health = await client.get("/health")
        async with asyncio.timeout(1):
            run_read = await client.get(f"/api/runs/{run_id}")

        assert health.status_code == 200
        assert run_read.status_code == 200
        assert run_read.json()["status"] == "active"
        assert not submit.done()

        release.touch()
        submit_response = await submit
        assert submit_response.status_code == 200
        assert submit_response.json()["new_status"] == "building"

        head_after = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        activity = await client.get(f"/api/runs/{run_id}/activity?limit=100&payload_mode=full")
        assert activity.status_code == 200
        events = activity.json()["events"]
        event_types = [event["event_type"] for event in events]
        requested_index = event_types.index("run_worktree_commit_requested")
        completed_index = event_types.index("run_worktree_commit_completed")
        assert requested_index < completed_index
        completed = events[completed_index]["payload"]
        assert completed["created_commit"] is True
        assert completed["head_after"] == head_after
        assert completed["commit_sha"] == head_after
        assert (worktree_path / "responsive-submit.txt").read_text() == (
            "preserved by submission\n"
        )
    finally:
        release.touch()
        if not submit.done():
            await submit
