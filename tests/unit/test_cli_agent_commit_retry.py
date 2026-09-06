"""cli_subprocess commit-gate re-prompt behavior.

A one-shot CLI runner cannot bounce a pre-commit gate failure back into a live
session the way the codex app-server does (commit 8f62b04c). Instead, when the
post-exit submit raises WorktreeCommitError (ruff/pyright/tests hook failure),
the runner re-spawns the agent with the hook output as a fix prompt and retries
the submit, bounded by max_commit_fix_attempts. The worktree persists between
spawns, so the agent fixes its own changes in place.

These tests use hand-written fake subprocess objects injected via the
``subprocess_factory`` seam, satisfying the project rule against test doubles
that patch runtime behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.git import WorktreeCommitError
from orchestrator.runners import (
    CLIAgent,
    SubmissionAcknowledgement,
    SubmissionRejectedError,
    SubmissionRejectionEvidence,
)
from orchestrator.runners.errors import AgentExecutionError
from orchestrator.runners.types import ExecutionContext


class _FakeStdin:
    def __init__(self) -> None:
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

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

    acknowledgements: list[SubmissionAcknowledgement] = []

    async def on_submit() -> SubmissionAcknowledgement:
        submit_calls.append(1)
        if len(submit_calls) == 1:
            raise WorktreeCommitError(str(tmp_path), "pyright: error — type partially unknown")
        acknowledgement = SubmissionAcknowledgement(
            disposition="durably_staged",
            message="durably staged; pending runner completion and not yet accepted",
            execution_id="execution-1",
            graph_position=12,
        )
        acknowledgements.append(acknowledgement)
        return acknowledgement

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
    assert [item.disposition for item in acknowledgements] == ["durably_staged"]


async def test_quality_gate_rejection_reprompts_with_actionable_output(
    tmp_path: object,
) -> None:
    spawned: list[_FakeProcess] = []
    submit_calls: list[int] = []

    async def on_submit() -> None:
        submit_calls.append(1)
        if len(submit_calls) == 1:
            detail = (
                "submission quality gate failed with exit code 7; "
                "command='uv run pytest'; Bounded output tail: test_example failed"
            )
            raise SubmissionRejectedError(
                SubmissionAcknowledgement(
                    disposition="rejected",
                    message=detail,
                    rejection_category="candidate_check_failed",
                    rejection_evidence=SubmissionRejectionEvidence(
                        category="candidate_check_failed",
                        command="uv run pytest",
                        final_diagnostic="test_example failed",
                    ),
                )
            )

    agent = CLIAgent(
        command="sh",
        parser=None,
        subprocess_factory=_factory(spawned),
        max_commit_fix_attempts=1,
    )

    result = await agent.execute(_ctx(tmp_path), _noop_checklist, on_submit, on_output=None)

    assert result.success is True
    assert len(submit_calls) == 2
    assert len(spawned) == 2
    correction_prompt = b"".join(spawned[1].stdin.writes).decode("utf-8")
    assert "authoritative validation checks" in correction_prompt
    assert "uv run pytest" in correction_prompt
    assert "test_example failed" in correction_prompt


async def test_typed_rejected_ack_reprompts_then_accepts_finalized_readback(
    tmp_path: object,
) -> None:
    spawned: list[_FakeProcess] = []
    acknowledgements = [
        SubmissionAcknowledgement(
            disposition="rejected",
            message="submission rejected: acceptance command failed",
            execution_id="execution-1",
            graph_position=11,
        ),
        SubmissionAcknowledgement(
            disposition="finalized_accepted",
            message="submission is durably finalized and accepted",
            execution_id="execution-1",
            graph_position=19,
        ),
    ]

    async def on_submit() -> SubmissionAcknowledgement:
        return acknowledgements.pop(0)

    agent = CLIAgent(
        command="sh",
        parser=None,
        subprocess_factory=_factory(spawned),
        max_commit_fix_attempts=1,
    )

    result = await agent.execute(_ctx(tmp_path), _noop_checklist, on_submit, on_output=None)

    assert result.success is True
    assert acknowledgements == []
    assert len(spawned) == 2
    correction_prompt = b"".join(spawned[1].stdin.writes).decode("utf-8")
    assert '"disposition":"rejected"' in correction_prompt
    assert "acceptance command failed" in correction_prompt


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
