"""cli_subprocess commit-gate re-prompt behavior.

A one-shot CLI runner cannot bounce a pre-commit gate failure back into a live
session the way the codex app-server does (commit 8f62b04c). Instead, when the
post-exit submit raises WorktreeCommitError (ruff/pyright/tests hook failure),
the runner re-spawns the agent with the hook output as a fix prompt and retries
the submit, bounded by max_commit_fix_attempts. The worktree persists between
spawns, so the agent fixes its own changes in place.

These tests use hand-written fake subprocess objects injected via the
``subprocess_factory`` seam — no mocks/monkeypatching (project rule).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from orchestrator.git import WorktreeCommitError
from orchestrator.runners import CLIAgent
from orchestrator.runners.errors import AgentExecutionError
from orchestrator.runners.types import ExecutionContext


class _FakeStdin:
    def __init__(self) -> None:
        self.closed = False

    def write(self, _data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeStdout:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeProcess:
    """Minimal stand-in for asyncio.subprocess.Process."""

    def __init__(self, chunks: list[bytes], returncode: int = 0) -> None:
        self.pid = 4242
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(chunks)
        self.returncode: int | None = None
        self._rc = returncode

    async def wait(self) -> int:
        self.returncode = self._rc
        return self._rc

    def terminate(self) -> None:
        return None


async def _noop_checklist(_req_id: str, _status: object, _note: str | None) -> None:
    return None


def _ctx(tmp_path: object, graph_patch_callback: Any | None = None) -> ExecutionContext:
    return ExecutionContext(
        run_id="r1",
        task_id="t1",
        working_dir=str(tmp_path),
        prompt="implement the thing",
        requirements=[],
        graph_patch_callback=graph_patch_callback,
    )


def _factory(spawned: list[_FakeProcess]):
    async def factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        proc = _FakeProcess([b"working...\n"], returncode=0)
        spawned.append(proc)
        return proc

    return factory


async def test_commit_gate_failure_reprompts_then_resubmits(tmp_path: object) -> None:
    spawned: list[_FakeProcess] = []
    submit_calls: list[int] = []

    async def on_submit() -> None:
        submit_calls.append(1)
        if len(submit_calls) == 1:
            raise WorktreeCommitError(str(tmp_path), "pyright: error — type partially unknown")
        return None  # second submit succeeds (agent fixed the lint)

    agent = CLIAgent(
        command="sh",  # on PATH; not "claude", so no mcp-json / claude args
        parser=None,
        subprocess_factory=_factory(spawned),
        max_commit_fix_attempts=2,
    )

    result = await agent.execute(_ctx(tmp_path), _noop_checklist, on_submit, on_output=None)

    assert result.success is True
    assert len(submit_calls) == 2  # first rejected by gate, retried, succeeded
    assert len(spawned) == 2  # initial build + one fix pass


async def test_commit_gate_failure_is_bounded_then_raises(tmp_path: object) -> None:
    spawned: list[_FakeProcess] = []
    submit_calls: list[int] = []

    async def on_submit() -> None:
        submit_calls.append(1)
        raise WorktreeCommitError(str(tmp_path), "still failing checks")

    agent = CLIAgent(
        command="sh",
        parser=None,
        subprocess_factory=_factory(spawned),
        max_commit_fix_attempts=2,
    )

    with pytest.raises(AgentExecutionError):
        await agent.execute(_ctx(tmp_path), _noop_checklist, on_submit, on_output=None)

    # initial build + 2 bounded fix passes, then the 3rd rejection propagates
    assert len(spawned) == 3
    assert len(submit_calls) == 3


async def test_success_path_submits_once_without_extra_spawn(tmp_path: object) -> None:
    spawned: list[_FakeProcess] = []
    submit_calls: list[int] = []

    async def on_submit() -> None:
        submit_calls.append(1)  # gate passes first time

    agent = CLIAgent(
        command="sh",
        parser=None,
        subprocess_factory=_factory(spawned),
        max_commit_fix_attempts=2,
    )

    result = await agent.execute(_ctx(tmp_path), _noop_checklist, on_submit, on_output=None)

    assert result.success is True
    assert len(submit_calls) == 1
    assert len(spawned) == 1  # no fix pass when the gate passes


async def test_graph_patch_sentinel_routes_to_callback_before_submit(tmp_path: object) -> None:
    spawned: list[_FakeProcess] = []
    submitted_patches: list[dict[str, Any]] = []
    submit_calls: list[int] = []
    sentinel = 'ORCHESTRATOR_GRAPH_PATCH:{"patch_id":"patch-1","base_graph_position":14,"ops":[]}\n'

    async def graph_patch_callback(payload: dict[str, Any]) -> str:
        submitted_patches.append(payload)
        return "graph patch patch-1 accepted"

    async def on_submit() -> None:
        submit_calls.append(1)
        assert submitted_patches

    async def factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        proc = _FakeProcess([sentinel.encode()], returncode=0)
        spawned.append(proc)
        return proc

    agent = CLIAgent(
        command="sh",
        parser=None,
        subprocess_factory=factory,
        max_commit_fix_attempts=2,
    )

    result = await agent.execute(
        _ctx(tmp_path, graph_patch_callback=graph_patch_callback),
        _noop_checklist,
        on_submit,
        on_output=None,
    )

    assert result.success is True
    assert submitted_patches == [{"patch_id": "patch-1", "base_graph_position": 14, "ops": []}]
    assert submit_calls == [1]
    assert len(spawned) == 1


async def test_graph_patch_sentinel_routes_from_claude_stream_json(tmp_path: object) -> None:
    submitted_patches: list[dict[str, Any]] = []
    sentinel = (
        'ORCHESTRATOR_GRAPH_PATCH:{"patch":{"patch_id":"patch-json",'
        '"base_graph_position":18,"ops":[]}}'
    )
    stream_line = (
        json.dumps(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": sentinel}]},
            }
        )
        + "\n"
    )

    async def graph_patch_callback(payload: dict[str, Any]) -> str:
        submitted_patches.append(payload)
        return "graph patch patch-json accepted"

    async def on_submit() -> None:
        assert submitted_patches

    async def factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return _FakeProcess([stream_line.encode()], returncode=0)

    agent = CLIAgent(
        command="sh",
        parser=None,
        subprocess_factory=factory,
        max_commit_fix_attempts=2,
    )

    result = await agent.execute(
        _ctx(tmp_path, graph_patch_callback=graph_patch_callback),
        _noop_checklist,
        on_submit,
        on_output=None,
    )

    assert result.success is True
    assert submitted_patches == [{"patch_id": "patch-json", "base_graph_position": 18, "ops": []}]
