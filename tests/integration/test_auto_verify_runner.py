"""Integration tests for local auto-verify command execution."""

from pathlib import Path

import pytest

from orchestrator.workflow import LocalAutoVerifyRunner


class TestLocalAutoVerifyRunner:
    @pytest.mark.asyncio
    async def test_successful_command(self, tmp_path: Path) -> None:
        runner = LocalAutoVerifyRunner()
        exit_code, output = await runner.run_command("echo hello", tmp_path, tail_lines=20)
        assert exit_code == 0
        assert "hello" in output

    @pytest.mark.asyncio
    async def test_failing_command(self, tmp_path: Path) -> None:
        runner = LocalAutoVerifyRunner()
        exit_code, _output = await runner.run_command("false", tmp_path, tail_lines=20)
        assert exit_code != 0

    @pytest.mark.asyncio
    async def test_tail_lines(self, tmp_path: Path) -> None:
        runner = LocalAutoVerifyRunner()
        exit_code, output = await runner.run_command(
            "for i in 1 2 3 4 5; do echo line$i; done", tmp_path, tail_lines=2
        )
        assert exit_code == 0
        lines = output.strip().splitlines()
        assert len(lines) == 2
        assert "line4" in lines[0]
        assert "line5" in lines[1]

    @pytest.mark.asyncio
    async def test_cwd_is_respected(self, tmp_path: Path) -> None:
        runner = LocalAutoVerifyRunner()
        exit_code, output = await runner.run_command("pwd", tmp_path, tail_lines=20)
        assert exit_code == 0
        assert str(tmp_path) in output

    @pytest.mark.asyncio
    async def test_stderr_captured_in_output(self, tmp_path: Path) -> None:
        runner = LocalAutoVerifyRunner()
        _exit_code, output = await runner.run_command("echo error_msg >&2", tmp_path, tail_lines=20)
        assert "error_msg" in output
