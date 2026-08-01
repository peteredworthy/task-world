"""Regression checks for test-suite runtime configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).parents[2]


def test_default_and_precommit_suites_use_adaptive_workers() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert "-n auto" in addopts
    assert "--dist loadfile" in addopts

    precommit = yaml.safe_load((PROJECT_ROOT / ".pre-commit-config.yaml").read_text())
    pytest_hook = next(
        hook for repo in precommit["repos"] for hook in repo["hooks"] if hook["id"] == "pytest"
    )
    assert "-n 2" not in pytest_hook["entry"]
