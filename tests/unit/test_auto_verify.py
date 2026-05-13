"""Tests for auto-verify command evaluation and orchestration."""

from pathlib import Path

import pytest

from orchestrator.config.models import AutoVerifyConfig, AutoVerifyItemConfig
from orchestrator.workflow import (
    AutoVerifyResult,
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


class FakeAutoVerifyRunner:
    def __init__(self, results: dict[str, tuple[int | None, str]]) -> None:
        self.results = results
        self.calls: list[tuple[str, Path, int]] = []

    async def run_command(self, cmd: str, cwd: Path, tail_lines: int) -> tuple[int | None, str]:
        self.calls.append((cmd, cwd, tail_lines))
        return self.results[cmd]


class TestRunAutoVerify:
    @pytest.mark.asyncio
    async def test_run_all_commands(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="echo ok"),
                AutoVerifyItemConfig(id="check2", cmd="echo also_ok"),
            ]
        )
        runner = FakeAutoVerifyRunner(
            {
                "echo ok": (0, "ok"),
                "echo also_ok": (0, "also_ok"),
            }
        )
        results = await run_auto_verify(config, runner, tmp_path)
        assert len(results) == 2
        assert all(r.passed for r in results)
        assert runner.calls == [
            ("echo ok", tmp_path, config.tail_lines),
            ("echo also_ok", tmp_path, config.tail_lines),
        ]

    @pytest.mark.asyncio
    async def test_mixed_results(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="pass", cmd="echo ok"),
                AutoVerifyItemConfig(id="fail", cmd="false"),
            ]
        )
        runner = FakeAutoVerifyRunner(
            {
                "echo ok": (0, "ok"),
                "false": (1, ""),
            }
        )
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
        runner = FakeAutoVerifyRunner({"echo test_output": (0, "test_output")})
        results = await run_auto_verify(config, runner, tmp_path)
        assert len(results) == 1
        assert "test_output" in results[0].output

    @pytest.mark.asyncio
    async def test_empty_config(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(items=[])
        runner = FakeAutoVerifyRunner({})
        results = await run_auto_verify(config, runner, tmp_path)
        assert results == []
        assert runner.calls == []

    @pytest.mark.asyncio
    async def test_result_serialization(self, tmp_path: Path) -> None:
        """AutoVerifyResult can be serialized to dict for storage in Attempt."""
        config = AutoVerifyConfig(
            items=[
                AutoVerifyItemConfig(id="check1", cmd="echo ok"),
            ]
        )
        runner = FakeAutoVerifyRunner({"echo ok": (0, "ok")})
        results = await run_auto_verify(config, runner, tmp_path)
        # Convert to dict (as stored in Attempt.auto_verify_results)
        result_dict = results[0].model_dump()
        assert isinstance(result_dict, dict)
        assert result_dict["item_id"] == "check1"
        assert result_dict["passed"] is True
        # Round-trip back to model
        restored = AutoVerifyResult.model_validate(result_dict)
        assert restored == results[0]

    @pytest.mark.asyncio
    async def test_command_crash_is_reported(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(items=[AutoVerifyItemConfig(id="check1", cmd="boom")])
        runner = FakeAutoVerifyRunner({"boom": (None, "Command crashed: OSError: boom")})

        results = await run_auto_verify(config, runner, tmp_path)

        assert results == [
            AutoVerifyResult(
                item_id="check1",
                cmd="boom",
                passed=False,
                exit_code=0,
                output="Command crashed: OSError: boom",
                crashed=True,
                crash_error="Command crashed: OSError: boom",
            )
        ]

    @pytest.mark.asyncio
    async def test_variables_are_resolved_before_runner_call(self, tmp_path: Path) -> None:
        config = AutoVerifyConfig(
            items=[AutoVerifyItemConfig(id="check1", cmd="test {{output_path}}")]
        )
        runner = FakeAutoVerifyRunner({"test docs/out.md": (0, "ok")})

        results = await run_auto_verify(
            config,
            runner,
            tmp_path,
            variables={"output_path": "docs/out.md"},
        )

        assert results[0].cmd == "test docs/out.md"
        assert runner.calls == [("test docs/out.md", tmp_path, config.tail_lines)]
