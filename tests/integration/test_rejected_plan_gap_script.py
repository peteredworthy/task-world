"""Product-boundary test for the Slice 3 rejected-plan reproducer."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "docs/intent/31-decision-runtime/reproduce-rejected-plan-gap.py"


def test_rejected_plan_reproducer_runs_directly_without_pythonpath() -> None:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "Passed: rejected plan → repeated repair → independent verification → successor"
        in result.stdout
    )
