"""Integration tests for CLIAgent with real subprocesses."""

from datetime import timedelta

import pytest

from orchestrator.config.models import NudgerConfig
from orchestrator.config import ChecklistStatus
from orchestrator.runners import CLIAgent
from orchestrator.runners.errors import AgentExecutionError, AgentNotAvailableError
from orchestrator.runners.types import ChecklistUpdateCallback, ExecutionContext, SubmitCallback


def _make_context(
    working_dir: str = "/tmp",
    api_base_url: str | None = None,
    prompt: str = "hello",
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir=working_dir,
        prompt=prompt,
        requirements=["R1"],
        api_base_url=api_base_url,
    )


def _noop_callbacks() -> tuple[ChecklistUpdateCallback, SubmitCallback]:
    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    return on_update, on_submit


async def test_echo_command() -> None:
    """Test running echo as a simple subprocess."""
    agent = CLIAgent(command="echo", args=["hello world"])
    on_update, on_submit = _noop_callbacks()

    result = await agent.execute(_make_context(), on_update, on_submit)
    assert result.success is True


async def test_python_command() -> None:
    """Test running python3 -c as subprocess."""
    agent = CLIAgent(command="python3", args=["-c", "print('output from python')"])
    on_update, on_submit = _noop_callbacks()

    result = await agent.execute(_make_context(), on_update, on_submit)
    assert result.success is True


async def test_cli_agent_stores_pid() -> None:
    """CLI agent stores the subprocess PID in agent_metadata."""
    agent = CLIAgent(command="echo", args=["test"])
    on_update, on_submit = _noop_callbacks()

    result = await agent.execute(_make_context(), on_update, on_submit)
    assert result.success is True
    assert "pid" in result.agent_metadata
    assert isinstance(result.agent_metadata["pid"], int)
    assert result.agent_metadata["pid"] > 0


async def test_nonexistent_command() -> None:
    """Nonexistent command raises AgentNotAvailableError."""
    agent = CLIAgent(command="nonexistent_command_xyz_12345")
    on_update, on_submit = _noop_callbacks()

    with pytest.raises(AgentNotAvailableError, match="not found in PATH"):
        await agent.execute(_make_context(), on_update, on_submit)


async def test_failing_command() -> None:
    """Command that exits with non-zero returns success=False."""
    agent = CLIAgent(command="python3", args=["-c", "raise SystemExit(1)"])
    on_update, on_submit = _noop_callbacks()

    result = await agent.execute(_make_context(), on_update, on_submit)
    assert result.success is False
    assert result.error is not None
    assert "exit" in result.error.lower() or "code" in result.error.lower()


async def test_on_submit_called_after_success() -> None:
    """on_submit callback is called when subprocess exits with code 0."""
    agent = CLIAgent(command="echo", args=["success"])
    submit_called = False

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        nonlocal submit_called
        submit_called = True

    result = await agent.execute(_make_context(), on_update, on_submit)
    assert result.success is True
    assert submit_called is True, "on_submit should be called after successful execution"


async def test_on_submit_not_called_after_failure() -> None:
    """on_submit callback is NOT called when subprocess exits with non-zero code."""
    agent = CLIAgent(command="python3", args=["-c", "raise SystemExit(1)"])
    submit_called = False

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        nonlocal submit_called
        submit_called = True

    result = await agent.execute(_make_context(), on_update, on_submit)
    assert result.success is False
    assert submit_called is False, "on_submit should NOT be called after failed execution"


async def test_on_submit_not_called_after_stuck_kill() -> None:
    """on_submit callback is NOT called when agent is killed for being stuck."""
    agent = CLIAgent(
        command="python3",
        args=["-c", "import time; time.sleep(300)"],
        nudger_config=NudgerConfig(
            output_timeout=timedelta(milliseconds=200),
            max_nudges=1,
            nudge_interval=timedelta(seconds=0),
        ),
        poll_interval=0.05,
    )
    submit_called = False

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        nonlocal submit_called
        submit_called = True

    with pytest.raises(AgentExecutionError, match="stuck"):
        await agent.execute(_make_context(), on_update, on_submit)

    assert submit_called is False, "on_submit should NOT be called when agent is killed"


async def test_prompt_enrichment_reaches_subprocess() -> None:
    """When api_base_url is set, the enriched prompt (with REST endpoints) is sent to stdin."""
    agent = CLIAgent(command="cat")
    on_update, on_submit = _noop_callbacks()

    ctx = _make_context(
        prompt="Build the feature",
        api_base_url="http://localhost:8000",
    )
    result = await agent.execute(ctx, on_update, on_submit)
    assert result.success is True
    output = "\n".join(result.output_lines)
    assert "Build the feature" in output
    assert "Base URL: http://localhost:8000" in output
    assert "Run ID: run-1, Task ID: task-1" in output
    assert "PATCH http://localhost:8000/api/runs/run-1/tasks/task-1/checklist/{req_id}" in output
    assert "POST http://localhost:8000/api/runs/run-1/tasks/task-1/submit" in output


async def test_prompt_enrichment_mcp_channel() -> None:
    """With callback_channel='mcp', MCP instructions are sent to stdin."""
    agent = CLIAgent(command="cat", callback_channel="mcp")
    on_update, on_submit = _noop_callbacks()

    ctx = _make_context(
        prompt="Build the feature",
        api_base_url="http://localhost:8000",
    )
    result = await agent.execute(ctx, on_update, on_submit)
    assert result.success is True
    output = "\n".join(result.output_lines)
    assert "Build the feature" in output
    assert "MCP Server Connection" in output
    assert "Connect to: http://localhost:8000/mcp/sse" in output
    assert "orchestrator_update_checklist('run-1', 'task-1', 'R1', 'done')" in output
    assert "orchestrator_submit" in output


async def test_model_flag_in_subprocess() -> None:
    """When model is set, --model flag appears in command args."""
    # python3 -c will ignore the --model flag but run successfully
    agent = CLIAgent(
        command="python3",
        model="test-model",
        args=["-c", "print('ok')"],
    )
    # The --model flag is prepended, so full args are:
    # ["--model", "test-model", "-c", "print('ok')"]
    # python3 doesn't understand --model, so it'll fail — that's expected
    # Let's just verify the args were constructed correctly
    assert agent._args == ["--model", "test-model", "-c", "print('ok')"]  # pyright: ignore[reportPrivateUsage]


async def test_stdin_mode_open() -> None:
    """With stdin_mode='open', stdin stays open for nudge delivery."""
    agent = CLIAgent(command="cat", stdin_mode="open")
    on_update, on_submit = _noop_callbacks()

    # cat with open stdin will hang, so use a short timeout via nudger
    from datetime import timedelta

    agent = CLIAgent(
        command="python3",
        args=["-c", "import sys; data = sys.stdin.readline(); print(data.strip())"],
        stdin_mode="open",
        nudger_config=NudgerConfig(
            output_timeout=timedelta(seconds=10),
            max_nudges=1,
        ),
    )
    result = await agent.execute(_make_context(), on_update, on_submit)
    assert result.success is True


async def test_stuck_subprocess_triggers_kill() -> None:
    """Slow subprocess that produces no output gets killed after max nudges."""
    agent = CLIAgent(
        command="python3",
        args=["-c", "import time; time.sleep(300)"],
        nudger_config=NudgerConfig(
            output_timeout=timedelta(milliseconds=200),
            max_nudges=1,
            nudge_interval=timedelta(seconds=0),
        ),
        poll_interval=0.05,
    )
    on_update, on_submit = _noop_callbacks()

    with pytest.raises(AgentExecutionError, match="stuck"):
        await agent.execute(_make_context(), on_update, on_submit)
