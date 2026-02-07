"""Tests for auto-verify command execution and evaluation."""

from pathlib import Path

import pytest

from orchestrator.config.models import AutoVerifyConfig, AutoVerifyItemConfig
from orchestrator.workflow.auto_verify import (
    AutoVerifyResult,
    LocalAutoVerifyRunner,
    evaluate_auto_verify,
    run_auto_verify,
)


# --- Pure function tests ---


class TestEvaluateAutoVerify:
    def test_all_passing(self) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="echo ok", must=True),
                AutoVerifyItemConfig(id="check2", cmd="echo ok", must=False),
            ]
        )
        results = [
            AutoVerifyResult(
                item_id="check1", cmd="echo ok", passed=True, exit_code=0, output="ok"
            ),
            AutoVerifyResult(
                item_id="check2", cmd="echo ok", passed=True, exit_code=0, output="ok"
            ),
        ]
        passed, failures = evaluate_auto_verify(config, results)
        assert passed is True
        assert failures == []

    def test_must_item_fails(self) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="false", must=True),
            ]
        )
        results = [
            AutoVerifyResult(item_id="check1", cmd="false", passed=False, exit_code=1, output=""),
        ]
        passed, failures = evaluate_auto_verify(config, results)
        assert passed is False
        assert failures == ["check1"]

    def test_non_must_fail_still_passes(self) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="echo ok", must=True),
                AutoVerifyItemConfig(id="check2", cmd="false", must=False),
            ]
        )
        results = [
            AutoVerifyResult(
                item_id="check1", cmd="echo ok", passed=True, exit_code=0, output="ok"
            ),
            AutoVerifyResult(item_id="check2", cmd="false", passed=False, exit_code=1, output=""),
        ]
        passed, failures = evaluate_auto_verify(config, results)
        assert passed is True
        assert failures == []

    def test_empty_items(self) -> None:
        config = AutoVerifyConfig(items=[])
        passed, failures = evaluate_auto_verify(config, [])
        assert passed is True
        assert failures == []

    def test_multiple_must_failures(self) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="false", must=True),
                AutoVerifyItemConfig(id="check2", cmd="false", must=True),
                AutoVerifyItemConfig(id="check3", cmd="echo ok", must=False),
            ]
        )
        results = [
            AutoVerifyResult(item_id="check1", cmd="false", passed=False, exit_code=1, output=""),
            AutoVerifyResult(item_id="check2", cmd="false", passed=False, exit_code=1, output=""),
            AutoVerifyResult(item_id="check3", cmd="echo ok", passed=False, exit_code=1, output=""),
        ]
        passed, failures = evaluate_auto_verify(config, results)
        assert passed is False
        assert failures == ["check1", "check2"]


# --- Integration tests with real subprocess ---


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
        # Generate more than 3 lines of output
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


class TestRunAutoVerify:
    @pytest.mark.asyncio
    async def test_run_all_commands(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="echo ok"),
                AutoVerifyItemConfig(id="check2", cmd="echo also_ok"),
            ]
        )
        runner = LocalAutoVerifyRunner()
        results = await run_auto_verify(config, runner, tmp_path)
        assert len(results) == 2
        assert all(r.passed for r in results)

    @pytest.mark.asyncio
    async def test_mixed_results(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="pass", cmd="echo ok"),
                AutoVerifyItemConfig(id="fail", cmd="false"),
            ]
        )
        runner = LocalAutoVerifyRunner()
        results = await run_auto_verify(config, runner, tmp_path)
        assert results[0].passed is True
        assert results[1].passed is False

    @pytest.mark.asyncio
    async def test_results_contain_output(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="echo test_output"),
            ]
        )
        runner = LocalAutoVerifyRunner()
        results = await run_auto_verify(config, runner, tmp_path)
        assert len(results) == 1
        assert "test_output" in results[0].output

    @pytest.mark.asyncio
    async def test_empty_config(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(items=[])
        runner = LocalAutoVerifyRunner()
        results = await run_auto_verify(config, runner, tmp_path)
        assert results == []

    @pytest.mark.asyncio
    async def test_result_serialization(self, tmp_path: Path) -> None:
        """AutoVerifyResult can be serialized to dict for storage in Attempt."""
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="echo ok"),
            ]
        )
        runner = LocalAutoVerifyRunner()
        results = await run_auto_verify(config, runner, tmp_path)
        # Convert to dict (as stored in Attempt.auto_verify_results)
        result_dict = results[0].model_dump()
        assert isinstance(result_dict, dict)
        assert result_dict["item_id"] == "check1"
        assert result_dict["passed"] is True
        # Round-trip back to model
        restored = AutoVerifyResult.model_validate(result_dict)
        assert restored == results[0]
