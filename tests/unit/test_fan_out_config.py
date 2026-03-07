"""Unit tests for FanOutConfig validation and TaskConfig mutual exclusion."""

import pytest

from orchestrator.config.models import (
    AutoVerifyConfig,
    AutoVerifyItemConfig,
    FanOutConfig,
    TaskConfig,
)


class TestFanOutConfigDefaults:
    def test_fan_out_config_defaults(self) -> None:
        """FanOutConfig should have sensible defaults for optional fields."""
        cfg = FanOutConfig(
            input_glob="*.md",
            output_pattern="out/{{item_stem}}.txt",
            per_item_prompt="Process {{item_content}}",
        )
        assert cfg.max_attempts == 4
        assert cfg.max_concurrent == 4
        assert cfg.shared_context == []
        assert cfg.auto_verify is None

    def test_fan_out_config_all_fields(self) -> None:
        """FanOutConfig should accept all fields explicitly."""
        auto_verify = AutoVerifyConfig(
            items=[AutoVerifyItemConfig(id="check1", cmd="test -f out.txt", must=True)],
            tail_lines=10,
        )
        cfg = FanOutConfig(
            input_glob="src/**/*.py",
            output_pattern="output/{{item_stem}}-result.md",
            per_item_prompt="Analyse: {{item_content}}",
            shared_context=["README.md", "DESIGN.md"],
            max_attempts=6,
            max_concurrent=8,
            auto_verify=auto_verify,
        )
        assert cfg.input_glob == "src/**/*.py"
        assert cfg.output_pattern == "output/{{item_stem}}-result.md"
        assert cfg.per_item_prompt == "Analyse: {{item_content}}"
        assert cfg.shared_context == ["README.md", "DESIGN.md"]
        assert cfg.max_attempts == 6
        assert cfg.max_concurrent == 8
        assert cfg.auto_verify is not None
        assert len(cfg.auto_verify.items) == 1
        assert cfg.auto_verify.items[0].id == "check1"


class TestTaskConfigMutualExclusion:
    def test_task_config_fan_out_exclusive_with_context(self) -> None:
        """fan_out + task_context must raise ValueError."""
        with pytest.raises(ValueError, match="fan_out.*task_context.*mutually exclusive"):
            TaskConfig(
                id="T1",
                title="Bad",
                task_context="Some context",
                fan_out=FanOutConfig(
                    input_glob="*.md",
                    output_pattern="out/{{item_stem}}.txt",
                    per_item_prompt="Do it",
                ),
            )

    def test_task_config_script_exclusive_with_context(self) -> None:
        """script + task_context must raise ValueError."""
        with pytest.raises(ValueError, match="script.*task_context.*mutually exclusive"):
            TaskConfig(
                id="T1",
                title="Bad",
                task_context="Some context",
                script="echo hello",
            )

    def test_task_config_fan_out_exclusive_with_script(self) -> None:
        """fan_out + script must raise ValueError."""
        with pytest.raises(ValueError, match="fan_out.*script.*mutually exclusive"):
            TaskConfig(
                id="T1",
                title="Bad",
                fan_out=FanOutConfig(
                    input_glob="*.md",
                    output_pattern="out/{{item_stem}}.txt",
                    per_item_prompt="Do it",
                ),
                script="echo hello",
            )

    def test_task_config_fan_out_only(self) -> None:
        """fan_out without task_context or script should work."""
        task = TaskConfig(
            id="T1",
            title="Fan Out Task",
            fan_out=FanOutConfig(
                input_glob="*.md",
                output_pattern="out/{{item_stem}}.txt",
                per_item_prompt="Process {{item_content}}",
            ),
        )
        assert task.fan_out is not None
        assert task.task_context == ""
        assert task.script is None

    def test_task_config_script_only(self) -> None:
        """script without task_context or fan_out should work."""
        task = TaskConfig(
            id="T1",
            title="Script Task",
            script="echo 'hello world'",
        )
        assert task.script == "echo 'hello world'"
        assert task.task_context == ""
        assert task.fan_out is None

    def test_task_config_normal(self) -> None:
        """task_context without fan_out or script should work (existing behaviour)."""
        task = TaskConfig(
            id="T1",
            title="Normal Task",
            task_context="Do the thing",
            requirements=[],
        )
        assert task.task_context == "Do the thing"
        assert task.fan_out is None
        assert task.script is None
