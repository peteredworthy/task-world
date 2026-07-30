"""Subprocess contracts for graph projection performance baselines."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.benchmark_graph_projection import corpus_metadata, corpus_events
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

    for scenario, measurements in result["scenarios"].items():
        assert (
            measurements["operation_boundaries"]["snapshot_tail"]
            == "decode_checkpoint_then_reduce_suffix"
        )
        assert (
            measurements["operation_boundaries"]["cold_rebuild"]
            == "reject_stale_schema_then_replay"
        )
        assert not checkpoint_schema_is_current(
            measurements["cold_rebuild"]["rejected_schema_version"]
        )
        expected_checkpoint = measurements["stream_metadata"]["projected"]
        assert measurements["checkpoint_cardinalities"] == {
            "nodes": expected_checkpoint["nodes"],
            "edges": expected_checkpoint["edges"],
            "records": expected_checkpoint["records"],
        }
        assert measurements["peak_memory_bytes"]["sample_count"] == 1
        assert (
            measurements["peak_memory_bytes"]["allocation_boundary"]
            == "replay_only_excluding_prebuilt_corpus"
        )
        for metric in (
            "reducer_full_replay",
            "snapshot_tail",
            "cold_rebuild",
            "append_heavy_indexes",
        ):
            assert measurements[metric]["sample_count"] == 1
            assert measurements[metric]["median"] >= 0
        assert measurements["public_view"]["result_cardinality"] > 0
        if scenario != "edge-heavy":
            assert measurements["append_heavy_indexes"]["result_cardinality"] > 0
        assert measurements["scenario"] == scenario


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
