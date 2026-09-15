"""Product-boundary test for the Slice 3 rejected-plan reproducer."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "docs/intent/31-decision-runtime/reproduce-rejected-plan-gap.py"


def test_rejected_plan_reproducer_entrypoint_resolves_without_pythonpath() -> None:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "Ready: rejected-plan reproducer imports resolve without PYTHONPATH" in result.stdout
