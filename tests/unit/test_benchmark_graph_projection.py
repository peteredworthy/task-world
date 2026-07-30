"""Subprocess contracts for graph projection performance baselines."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "benchmark_graph_projection.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", str(SCRIPT), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_minimal_baseline(path: Path, sizes: tuple[int, ...] = (100,)) -> dict[str, object]:
    result = _run(
        "--sizes",
        *(str(size) for size in sizes),
        "--warmups",
        "1",
        "--runs",
        "1",
        "--baseline",
        str(path),
        "--write-baseline",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(path.read_text())


def test_writes_deterministic_canonical_100_event_baseline_and_checks_it(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline = _write_minimal_baseline(baseline_path)

    assert json.loads(baseline_path.read_text()) == baseline
    assert baseline["schema_version"] == 1
    assert baseline["corpus"]["hash"]
    assert baseline["configuration"] == {"runs": 1, "sizes": [100], "warmups": 1}
    assert baseline["api_max_event_count"]["status"] in {"available", "unavailable"}
    assert set(baseline["environment"]) >= {"hardware", "os", "python", "dependencies"}

    scenarios = baseline["scenarios"]
    assert set(scenarios) == {"edge-heavy", "general", "record-heavy"}
    for measurements in scenarios.values():
        assert measurements["event_count"] == 100
        assert measurements["checkpoint_bytes"]["unit"] == "bytes"
        assert measurements["peak_memory_bytes"]["unit"] == "bytes"
        assert measurements["reducer_full_replay"]["unit"] == "ms"
        assert measurements["reducer_per_event"]["unit"] == "ms/event"
        assert measurements["max_observed"]["source"] == "synthetic_corpus"

    checked = _run(
        "--sizes",
        "100",
        "--warmups",
        "1",
        "--runs",
        "1",
        "--baseline",
        str(baseline_path),
        "--check-gates",
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["gates"] == {"status": "passed", "violations": []}


@pytest.mark.parametrize(
    ("scenario", "metric", "expected"),
    [
        ("general", "reducer_full_replay", "replay"),
        ("general", "peak_memory_bytes", "peak-memory"),
        ("general", "checkpoint_bytes", "checkpoint-size"),
        ("general", "checkpoint_encode", "codec/view"),
        ("general", "cold_rebuild", "cold-rebuild"),
        ("record-heavy", "checkpoint_record_heavy_smaller", "checkpoint-size"),
    ],
)
def test_check_gates_reports_each_synthetic_metric_failure(
    tmp_path: Path, scenario: str, metric: str, expected: str
) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline = _write_minimal_baseline(baseline_path)
    scenario_data = baseline["scenarios"][scenario]
    if metric == "checkpoint_record_heavy_smaller":
        scenario_data["checkpoint_bytes"]["median"] = 0
    else:
        scenario_data[metric]["median"] = 0
    baseline_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")

    checked = _run(
        "--sizes",
        "100",
        "--warmups",
        "1",
        "--runs",
        "1",
        "--baseline",
        str(baseline_path),
        "--check-gates",
    )

    assert checked.returncode != 0
    assert expected in checked.stderr
