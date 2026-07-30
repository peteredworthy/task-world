"""Subprocess contracts for graph projection performance baselines."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.benchmark_graph_projection import corpus_metadata, corpus_events, gate_violations
from orchestrator.graph import (
    OutputRecordAcceptedPayload,
    PROJECTION_SCHEMA_VERSION,
    accepted_record_summaries_by_id_view,
    checkpoint_schema_is_current,
    edges_view,
    initial_projection,
    project_record,
    projection_to_checkpoint,
    reduce_event,
)


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


@pytest.mark.parametrize("scenario", ("general", "edge-heavy", "record-heavy"))
def test_corpus_events_are_valid_unique_canonical_streams_with_declared_growth(
    scenario: str,
) -> None:
    events = corpus_events(scenario, 100)
    metadata = corpus_metadata(scenario, 100)

    assert len(events) == metadata["event_count"] == 100
    assert len({event.event_id for event in events}) == 100
    assert len({event.position for event in events}) == 100

    projection = initial_projection()
    for event in events:
        if event.event_type == "output_record_accepted":
            payload = event.payload
            assert payload["record_id"] not in {
                prior.payload["record_id"]
                for prior in events[: event.position]
                if prior.event_type == "output_record_accepted"
            }
            accepted_record = OutputRecordAcceptedPayload.model_validate(payload).root
            projected_record = project_record(accepted_record)
            assert projected_record.record_id == payload["record_id"]
            assert projected_record.port == "candidate"
            assert projected_record.schema_ == "ImplementationCandidate"
            assert payload["record_kind"] == "output"
            assert payload["port"] == "candidate"
            assert payload["schema"] == "ImplementationCandidate"
            assert isinstance(payload["value"], dict)
            assert isinstance(payload["payload"], dict)
            assert isinstance(payload["provenance"], dict)
        projection = reduce_event(projection, event)

    assert len(projection["node_kinds"]) == metadata["projected"]["nodes"]
    assert len(edges_view(projection)) == metadata["projected"]["edges"]
    assert len(accepted_record_summaries_by_id_view(projection)) == metadata["projected"]["records"]
    assert metadata["projected"]["append_index_entries"] == metadata["projected"]["records"]


@pytest.mark.parametrize("scenario", ("general", "edge-heavy", "record-heavy"))
def test_full_checkpoint_metrics_cover_the_final_projection_not_snapshot_prefix(
    scenario: str,
) -> None:
    events = corpus_events(scenario, 100)
    metadata = corpus_metadata(scenario, 100)
    full_projection = initial_projection()
    prefix_projection = initial_projection()
    for event in events:
        full_projection = reduce_event(full_projection, event)
    for event in events[: len(events) // 2]:
        prefix_projection = reduce_event(prefix_projection, event)

    full_checkpoint = projection_to_checkpoint(full_projection)
    prefix_checkpoint = projection_to_checkpoint(prefix_projection)
    expected = metadata["projected"]
    assert len(full_checkpoint["node_kinds"]) == expected["nodes"]
    assert len(full_checkpoint["edges"]) == expected["edges"]
    assert len(full_checkpoint["output_record_payloads"]) == expected["records"]
    assert len(full_checkpoint["node_kinds"]) >= len(prefix_checkpoint["node_kinds"])
    assert len(full_checkpoint["edges"]) >= len(prefix_checkpoint["edges"])
    assert len(full_checkpoint["output_record_payloads"]) >= len(
        prefix_checkpoint["output_record_payloads"]
    )


def test_checkpoint_schema_decision_is_public_and_rejects_stale_versions() -> None:
    assert checkpoint_schema_is_current(PROJECTION_SCHEMA_VERSION)
    assert not checkpoint_schema_is_current(PROJECTION_SCHEMA_VERSION - 1)


def test_smoke_measurements_report_honest_operation_boundaries_and_real_views() -> None:
    baseline_path = ROOT / "tmp" / "benchmark-smoke-unused.json"
    result = json.loads(
        _run(
            "--sizes",
            "100",
            "--warmups",
            "1",
            "--runs",
            "1",
            "--baseline",
            str(baseline_path),
        ).stdout
    )

    for scenario, scenario_result in result["scenarios"].items():
        measurements = scenario_result["sizes"]["100"]
        metrics = measurements["metrics"]
        assert (
            measurements["metadata"]["operation_boundaries"]["snapshot_tail"]
            == "decode_checkpoint_then_reduce_suffix"
        )
        assert (
            measurements["metadata"]["operation_boundaries"]["cold_rebuild"]
            == "reject_stale_schema_then_replay"
        )
        assert not checkpoint_schema_is_current(
            measurements["metadata"]["operation_boundaries"]["cold_rebuild"]
        )
        assert measurements["metadata"]["stream"]["event_count"] == 100
        assert metrics["peak_memory_bytes"]["sample_count"] == 1
        for metric in (
            "reducer_full_replay",
            "snapshot_tail",
            "cold_rebuild",
            "append_heavy_indexes",
        ):
            assert metrics[metric]["sample_count"] == 1
            assert metrics[metric]["median"] >= 0
        assert scenario in result["scaling_probes"]


def test_corpus_metadata_expresses_scenario_dominance_without_generated_total_snapshots() -> None:
    metadata = {
        scenario: corpus_metadata(scenario, 100)
        for scenario in ("general", "edge-heavy", "record-heavy")
    }

    assert metadata["general"]["family_counts"].keys() >= {
        "node_created",
        "node_state_changed",
        "edge_created",
        "output_record_accepted",
    }
    assert metadata["edge-heavy"]["projected"]["edges"] > metadata["general"]["projected"]["edges"]
    assert (
        metadata["record-heavy"]["projected"]["records"]
        > metadata["general"]["projected"]["records"]
    )
    assert (
        metadata["record-heavy"]["projected"]["records"]
        > metadata["edge-heavy"]["projected"]["records"]
    )


def test_smoke_writes_and_reloads_a_versioned_100_event_baseline_without_ratio_gating(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline = _write_minimal_baseline(baseline_path)

    assert json.loads(baseline_path.read_text()) == baseline
    assert baseline["schema_version"] == 2
    assert baseline["tool"]["hash"]
    assert baseline["artifact"]["role"] == "baseline"
    assert baseline["configuration"]["requested_sizes"] == [100]
    assert baseline["configuration"]["probe_sizes"] == [100, 200]
    assert baseline["max_event_count"] == {
        "count": None,
        "source": "unsupported",
        "status": "unsupported",
    }

    scenarios = baseline["scenarios"]
    assert set(scenarios) == {"edge-heavy", "general", "record-heavy"}
    for scenario_result in scenarios.values():
        for measurements in scenario_result["sizes"].values():
            metrics = measurements["metrics"]
            assert metrics["checkpoint_bytes"]["unit"] == "bytes"
            assert metrics["peak_memory_bytes"]["unit"] == "bytes"
            assert metrics["reducer_full_replay"]["unit"] == "ms"


def _gate_document(
    *,
    role: str,
    replay: float = 100.0,
    memory: float = 100.0,
    checkpoint: float = 100.0,
    codec: float = 100.0,
    cold_rebuild: float = 100.0,
    scale_low: float = 110.0,
    scale_high: float = 210.0,
) -> dict[str, object]:
    """Return a complete, hand-built schema-v2 gate document."""
    metrics = {
        "reducer_full_replay": (replay, "ms"),
        "peak_memory_bytes": (memory, "bytes"),
        "checkpoint_bytes": (checkpoint, "bytes"),
        "checkpoint_encode": (codec, "ms"),
        "checkpoint_decode": (codec, "ms"),
        "public_view": (codec, "ms"),
        "cold_rebuild": (cold_rebuild, "ms"),
    }

    def measurement(values: dict[str, tuple[float, str]]) -> dict[str, object]:
        return {
            name: {"median": value, "unit": unit, "source": "current", "sample_count": 2}
            for name, (value, unit) in values.items()
        }

    sizes = {
        size: {"metrics": measurement(metrics), "metadata": {"event_count": int(size)}}
        for size in ("100", "200")
    }
    return {
        "schema_version": 2,
        "tool": {"identity": "graph-projection-benchmark", "version": "2", "hash": "tool-hash"},
        "artifact": {"role": role, "implementation_signature": f"{role}-implementation"},
        "source": {"revision": f"{role}-revision"},
        "corpus": {"hash": "corpus-hash", "scenario_hash": "scenario-hash"},
        "configuration": {
            "requested_sizes": [100],
            "probe_sizes": [100, 200],
            "warmups": 1,
            "runs": 2,
        },
        "environment": {
            "comparable": {
                "architecture": "arm64",
                "python": "3.12.0",
                "dependencies": {"pydantic": "2", "sqlalchemy": "2"},
            },
            "informational": {"host": "test-host", "os": "test-os"},
        },
        "max_event_count": {"count": None, "status": "unsupported", "source": "unsupported"},
        "scenarios": {
            scenario: {"sizes": sizes} for scenario in ("general", "edge-heavy", "record-heavy")
        },
        "scaling_probes": {
            scenario: {
                "100_to_200": {
                    "n": {"median": scale_low, "startup_median": 10.0, "unit": "ms"},
                    "two_n": {"median": scale_high, "startup_median": 10.0, "unit": "ms"},
                }
            }
            for scenario in ("general", "edge-heavy", "record-heavy")
        },
    }


def test_gate_evaluator_accepts_complete_strict_documents() -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(
        role="target", checkpoint=99.0, replay=115.0, memory=115.0, codec=125.0, cold_rebuild=115.0
    )

    assert gate_violations(baseline, target) == []


@pytest.mark.parametrize(
    ("field", "limit", "label"),
    [
        ("replay", 1.15, "replay"),
        ("memory", 1.15, "peak-memory"),
        ("checkpoint", 1.0, "checkpoint-size"),
        ("codec", 1.25, "codec/view"),
        ("cold_rebuild", 1.15, "cold-rebuild"),
    ],
)
@pytest.mark.parametrize("multiplier", (0.999, 1.0, 1.001))
def test_gate_ratio_boundaries_are_exact(
    field: str, limit: float, label: str, multiplier: float
) -> None:
    baseline = _gate_document(role="baseline")
    target_options = {"checkpoint": 99.0, field: 100.0 * limit * multiplier}
    target = _gate_document(role="target", **target_options)

    violations = gate_violations(baseline, target)

    assert (any(label in violation for violation in violations)) is (multiplier > 1.0)


def test_gate_evaluator_rejects_missing_metric_with_sorted_compatibility_diagnostics() -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0)
    scenarios = target["scenarios"]
    assert isinstance(scenarios, dict)
    general = scenarios["general"]
    assert isinstance(general, dict)
    sizes = general["sizes"]
    assert isinstance(sizes, dict)
    size_100 = sizes["100"]
    assert isinstance(size_100, dict)
    metrics = size_100["metrics"]
    assert isinstance(metrics, dict)
    del metrics["checkpoint_decode"]
    tool = target["tool"]
    assert isinstance(tool, dict)
    tool["hash"] = "stale-tool"

    violations = gate_violations(baseline, target)

    assert violations == sorted(violations)
    assert any("tool.hash" in violation for violation in violations) or any(
        "checkpoint_decode" in violation for violation in violations
    )


@pytest.mark.parametrize("scale_high", (259.9, 260.0, 260.1))
def test_scaling_boundary_subtracts_startup(scale_high: float) -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0, scale_high=scale_high)

    violations = gate_violations(baseline, target)

    assert (any("scaling" in violation for violation in violations)) is (scale_high > 260.0)


def test_scaling_refuses_nonpositive_startup_adjusted_denominator() -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0, scale_low=10.0)

    assert any(
        "invalid denominator" in violation for violation in gate_violations(baseline, target)
    )


@pytest.mark.parametrize("checkpoint", (99.1, 100.0, 100.1))
def test_record_heavy_checkpoint_requires_strict_shrink(checkpoint: float) -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=checkpoint)

    violations = gate_violations(baseline, target)

    assert (any("record-heavy checkpoint" in violation for violation in violations)) is (
        checkpoint >= 100.0
    )
