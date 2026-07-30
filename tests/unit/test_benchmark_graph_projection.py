"""Subprocess contracts for graph projection performance baselines."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.benchmark_graph_projection import (
    BENCHMARK_PROTOCOL,
    BenchmarkResult,
    corpus_metadata,
    corpus_events,
    gate_violations,
    protocol_hash,
)
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
        "kind": "unsupported",
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
    gated_metrics = {
        "reducer_full_replay": (replay, "ms"),
        "peak_memory_bytes": (memory, "bytes"),
        "checkpoint_bytes": (checkpoint, "bytes"),
        "checkpoint_encode": (codec, "ms"),
        "checkpoint_decode": (codec, "ms"),
        "public_view": (codec, "ms"),
        "cold_rebuild": (cold_rebuild, "ms"),
    }

    def measurement(values: dict[str, tuple[float, str]]) -> dict[str, object]:
        sampled = {
            name: {
                "kind": "sampled",
                "median": float(value),
                "unit": unit,
                "source": "current",
                "sample_count": 2,
            }
            for name, (value, unit) in values.items()
            if name != "checkpoint_bytes"
        }
        return {
            **sampled,
            "reducer_per_event": {
                "kind": "sampled",
                "median": 1.0,
                "unit": "ms/event",
                "source": "current",
                "sample_count": 2,
            },
            "snapshot_tail": {
                "kind": "sampled",
                "median": 2.0,
                "unit": "ms",
                "source": "current",
                "sample_count": 2,
            },
            "append_heavy_indexes": {
                "kind": "sampled",
                "median": 3.0,
                "unit": "ms",
                "source": "current",
                "sample_count": 2,
            },
            "persistent_primitive_scaffold": {
                "kind": "sampled",
                "median": 4.0,
                "unit": "ms",
                "source": "current",
                "sample_count": 2,
            },
            "checkpoint_bytes": {
                "kind": "deterministic",
                "median": float(values["checkpoint_bytes"][0]),
                "unit": "bytes",
                "source": "current",
                "sample_count": 1,
            },
        }

    def metadata(scenario: str, size: int) -> dict[str, object]:
        return {
            "event_count": size,
            "stream": {
                "scenario": scenario,
                "event_count": size,
                "family_counts": {
                    "node_created": 1,
                    "node_state_changed": 0,
                    "edge_created": 0,
                    "output_record_accepted": size - 1,
                },
                "projected": {
                    "nodes": 1,
                    "edges": 0,
                    "records": size - 1,
                    "append_index_entries": size - 1,
                },
            },
            "operation_boundaries": {
                "snapshot_tail": "decode_checkpoint_then_reduce_suffix",
                "append_heavy_indexes": "prebuilt_prefix_then_reduce_suffix",
                "cold_rebuild": "reject_stale_schema_then_replay",
                "peak_memory_bytes": "replay_only_excluding_prebuilt_corpus",
            },
        }

    return {
        "schema_version": 2,
        "tool": {"identity": "graph-projection-benchmark", "version": "2", "hash": "c" * 64},
        "artifact": {"role": role, "implementation_signature": f"{role}-implementation"},
        "source": {"revision": "a" * 40 if role == "baseline" else "b" * 40},
        "corpus": {"hash": "a" * 64, "scenario_hash": "b" * 64},
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
            "informational": {
                "host": "test-host",
                "processor": "test-cpu",
                "os": "test-os",
                "os_release": "1",
            },
        },
        "max_event_count": {
            "kind": "unsupported",
            "count": None,
            "status": "unsupported",
            "source": "unsupported",
        },
        "scenarios": {
            scenario: {
                "sizes": {
                    size: {
                        "metrics": measurement(gated_metrics),
                        "metadata": metadata(scenario, int(size)),
                    }
                    for size in ("100", "200")
                }
            }
            for scenario in ("general", "edge-heavy", "record-heavy")
        },
        "scaling_probes": {
            scenario: [
                {
                    "pair": {"n": 100, "two_n": 200},
                    "startup": {
                        "kind": "sampled",
                        "median": 10.0,
                        "unit": "ms",
                        "source": "current",
                        "sample_count": 2,
                    },
                }
            ]
            for scenario in ("general", "edge-heavy", "record-heavy")
        },
    }


def test_gate_evaluator_accepts_complete_strict_documents() -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(
        role="target", checkpoint=99.0, replay=115.0, memory=115.0, codec=125.0, cold_rebuild=115.0
    )

    assert gate_violations(baseline, target) == []


def test_protocol_hash_is_stable_when_implementation_fingerprints_differ() -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0)

    assert BENCHMARK_PROTOCOL["version"] == 1
    assert protocol_hash() == protocol_hash()
    assert (
        baseline["artifact"]["implementation_signature"]
        != target["artifact"]["implementation_signature"]
    )
    assert baseline["tool"]["hash"] == target["tool"]["hash"]
    assert protocol_hash() != ""


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
    tool["hash"] = "d" * 64

    violations = gate_violations(baseline, target)

    assert violations == sorted(violations)
    assert any("tool.hash" in violation for violation in violations) or any(
        "checkpoint_decode" in violation for violation in violations
    )


@pytest.mark.parametrize("scale_high", (259.9, 260.0, 260.1))
def test_scaling_boundary_subtracts_startup(scale_high: float) -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0, scale_high=scale_high)
    scenarios = target["scenarios"]
    assert isinstance(scenarios, dict)
    for scenario in scenarios.values():
        assert isinstance(scenario, dict)
        sizes = scenario["sizes"]
        assert isinstance(sizes, dict)
        for size, median in (("100", 110.0), ("200", scale_high)):
            measurement = sizes[size]
            assert isinstance(measurement, dict)
            metrics = measurement["metrics"]
            assert isinstance(metrics, dict)
            replay = metrics["reducer_full_replay"]
            assert isinstance(replay, dict)
            replay["median"] = median

    violations = gate_violations(baseline, target)

    assert (any("scaling" in violation for violation in violations)) is (scale_high > 260.0)


def test_scaling_refuses_nonpositive_startup_adjusted_denominator() -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0, scale_low=10.0)
    scenarios = target["scenarios"]
    assert isinstance(scenarios, dict)
    for scenario in scenarios.values():
        assert isinstance(scenario, dict)
        sizes = scenario["sizes"]
        assert isinstance(sizes, dict)
        measurement = sizes["100"]
        assert isinstance(measurement, dict)
        metrics = measurement["metrics"]
        assert isinstance(metrics, dict)
        replay = metrics["reducer_full_replay"]
        assert isinstance(replay, dict)
        replay["median"] = 10.0

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


def test_artifact_schema_rejects_nested_extra_fields_and_coerced_metric_medians() -> None:
    document = _gate_document(role="baseline")
    invalid = deepcopy(document)
    corpus = invalid["corpus"]
    assert isinstance(corpus, dict)
    corpus["unexpected"] = "not allowed"
    scenarios = invalid["scenarios"]
    assert isinstance(scenarios, dict)
    general = scenarios["general"]
    assert isinstance(general, dict)
    sizes = general["sizes"]
    assert isinstance(sizes, dict)
    size = sizes["100"]
    assert isinstance(size, dict)
    metrics = size["metrics"]
    assert isinstance(metrics, dict)
    replay = metrics["reducer_full_replay"]
    assert isinstance(replay, dict)
    replay["median"] = "100.0"

    with pytest.raises(ValidationError) as error:
        BenchmarkResult.model_validate(invalid)

    locations = {issue["loc"] for issue in error.value.errors()}
    assert ("corpus", "unexpected") in locations
    assert (
        "scenarios",
        "general",
        "sizes",
        "100",
        "metrics",
        "reducer_full_replay",
        "median",
    ) in locations


@pytest.mark.parametrize(
    ("mutation", "expected_location"),
    [
        (
            lambda document: document["configuration"].update({"probe_sizes": [100]}),
            ("configuration",),
        ),
        (lambda document: document["configuration"].update({"runs": 0}), ("configuration", "runs")),
        (lambda document: document["corpus"].update({"hash": "not-a-hash"}), ("corpus", "hash")),
        (
            lambda document: document["scenarios"]["general"]["sizes"]["100"]["metrics"][
                "checkpoint_bytes"
            ].update({"sample_count": 2}),
            ("scenarios", "general", "sizes", "100", "metrics", "checkpoint_bytes", "sample_count"),
        ),
        (
            lambda document: document["scenarios"]["general"]["sizes"]["100"]["metrics"][
                "reducer_full_replay"
            ].update({"median": float("nan")}),
            ("scenarios", "general", "sizes", "100", "metrics", "reducer_full_replay", "median"),
        ),
    ],
)
def test_artifact_schema_rejects_cross_field_and_metric_accounting_violations(
    mutation: object, expected_location: tuple[str, ...]
) -> None:
    document = _gate_document(role="baseline")
    assert callable(mutation)
    mutation(document)

    with pytest.raises(ValidationError) as error:
        BenchmarkResult.model_validate(document)

    assert any(
        issue["loc"][: len(expected_location)] == expected_location
        for issue in error.value.errors()
    )


def test_scaling_probes_store_only_pair_and_startup_and_use_canonical_replay_metrics() -> None:
    document = _gate_document(role="target", checkpoint=99.0)
    probes = document["scaling_probes"]
    assert isinstance(probes, dict)
    for scenario_probes in probes.values():
        assert isinstance(scenario_probes, list)
        assert set(scenario_probes[0]) == {"pair", "startup"}

    scenarios = document["scenarios"]
    assert isinstance(scenarios, dict)
    for scenario in scenarios.values():
        assert isinstance(scenario, dict)
        sizes = scenario["sizes"]
        assert isinstance(sizes, dict)
        for size, median in (("100", 10.0), ("200", 250.1)):
            measurement = sizes[size]
            assert isinstance(measurement, dict)
            metrics = measurement["metrics"]
            assert isinstance(metrics, dict)
            replay = metrics["reducer_full_replay"]
            assert isinstance(replay, dict)
            replay["median"] = median

    assert any(
        "scaling" in issue for issue in gate_violations(_gate_document(role="baseline"), document)
    )


@pytest.mark.parametrize(
    ("family", "mutate", "expected"),
    [
        ("protocol", lambda document: document["tool"].update({"hash": "d" * 64}), "protocol.hash"),
        ("corpus", lambda document: document["corpus"].update({"hash": "d" * 64}), "corpus.hash"),
        (
            "runtime",
            lambda document: document["environment"]["comparable"].update(
                {"architecture": "x86_64"}
            ),
            "runtime architecture",
        ),
        (
            "sample accounting",
            lambda document: document["configuration"].update({"warmups": 0}),
            "sample accounting.warmups",
        ),
        (
            "pairs",
            lambda document: document["scaling_probes"]["general"][0].update(
                {"pair": {"n": 50, "two_n": 100}}
            ),
            "pairs general",
        ),
    ],
)
def test_compatibility_diagnostics_isolate_each_family(
    family: str, mutate: object, expected: str
) -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0)
    assert callable(mutate)
    mutate(target)

    violations = gate_violations(baseline, target)

    assert violations == [f"incompatible {expected}"]


@pytest.mark.parametrize("scenario", ("general", "edge-heavy", "record-heavy"))
@pytest.mark.parametrize("size", ("100", "200"))
@pytest.mark.parametrize(
    ("metric", "outside", "label"),
    [
        ("reducer_full_replay", 115.1, "replay"),
        ("peak_memory_bytes", 115.1, "peak-memory"),
        ("checkpoint_bytes", 100.1, "checkpoint-size"),
        ("checkpoint_encode", 125.1, "codec/view"),
        ("checkpoint_decode", 125.1, "codec/view"),
        ("public_view", 125.1, "codec/view"),
        ("cold_rebuild", 115.1, "cold-rebuild"),
    ],
)
def test_every_scenario_size_metric_gate_rejects_its_own_outside_value(
    scenario: str, size: str, metric: str, outside: float, label: str
) -> None:
    baseline = _gate_document(role="baseline")
    target = _gate_document(role="target", checkpoint=99.0)
    scenarios = target["scenarios"]
    assert isinstance(scenarios, dict)
    scenario_document = scenarios[scenario]
    assert isinstance(scenario_document, dict)
    sizes = scenario_document["sizes"]
    assert isinstance(sizes, dict)
    measurement = sizes[size]
    assert isinstance(measurement, dict)
    metrics = measurement["metrics"]
    assert isinstance(metrics, dict)
    selected_metric = metrics[metric]
    assert isinstance(selected_metric, dict)
    selected_metric["median"] = outside

    assert any(
        f"{label} {scenario}/{size}" in violation for violation in gate_violations(baseline, target)
    )
