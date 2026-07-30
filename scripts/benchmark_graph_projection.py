"""Measure deterministic graph projection replay baselines and enforce cutover gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tracemalloc
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable

from orchestrator.graph import (
    Actor,
    ActorKind,
    EdgeValue,
    EventEnvelope,
    ImmutableGraphProjection,
    NodeProjection,
    NodeSpecProjection,
    PROJECTION_SCHEMA_VERSION,
    accepted_record_summaries_by_id_view,
    edges_view,
    initial_projection,
    map_set,
    node_states_view,
    output_records_by_node_port_view,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
)


ROOT = Path(__file__).parents[1]
SCENARIOS_PATH = ROOT / "tests/fixtures/graph_projection_performance/scenarios.json"
DEFAULT_BASELINE = ROOT / "tests/fixtures/graph_projection_performance/baseline.json"
SCENARIO_NAMES = ("general", "edge-heavy", "record-heavy")
TIME_METRICS = (
    "reducer_full_replay",
    "reducer_per_event",
    "snapshot_tail",
    "cold_rebuild",
    "checkpoint_encode",
    "checkpoint_decode",
    "public_view",
    "append_heavy_indexes",
    "persistent_primitive_scaffold",
)


def _event(index: int, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"benchmark-{event_type}-{index}",
        run_id="benchmark-graph-projection",
        position=index,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        payload=payload,
    )


def _node_event(index: int, node_id: str) -> EventEnvelope:
    return _event(index, "node_created", {"node_id": node_id, "kind": "worker", "state": "planned"})


def _edge_event(index: int, previous_node_id: str, node_id: str) -> EventEnvelope:
    return _event(
        index,
        "edge_created",
        {
            "edge_id": f"benchmark-edge-{index:06d}",
            "from_node_id": previous_node_id,
            "from_port": "output",
            "to_node_id": node_id,
            "to_port": "input",
            "dependency_type": "input_binding",
        },
    )


def _record_event(index: int, node_id: str, scenario: str) -> EventEnvelope:
    body = f"{scenario}-record-value-{index:06d}"
    if scenario == "general":
        # The mixed corpus retains fewer records but representative richer output payloads.
        body *= 100
    return _event(
        index,
        "output_record_accepted",
        {
            "record_id": f"benchmark-{scenario}-record-{index:06d}",
            "record_type": "fan_out_inputs",
            "record_kind": "output",
            "producer_node_id": node_id,
            "producer_port": "output",
            "port": "output",
            "schema": "BenchmarkRecord",
            "value": {"index": index, "body": body},
        },
    )


def corpus_events(scenario: str, size: int) -> list[EventEnvelope]:
    """Build exactly *size* valid canonical events with deterministic dependencies."""
    if scenario not in SCENARIO_NAMES:
        raise ValueError(f"unknown benchmark scenario: {scenario}")

    events = [_node_event(0, "benchmark-node-000000")]
    for index in range(1, size):
        if scenario == "record-heavy":
            events.append(_record_event(index, "benchmark-node-000000", scenario))
        elif scenario == "edge-heavy":
            node_number = (index + 1) // 2
            node_id = f"benchmark-node-{node_number:06d}"
            if index % 2:
                events.append(_node_event(index, node_id))
            else:
                events.append(_edge_event(index, f"benchmark-node-{node_number - 1:06d}", node_id))
        else:
            node_number = (index + 3) // 4
            node_id = f"benchmark-node-{node_number:06d}"
            phase = (index - 1) % 4
            if phase == 0:
                events.append(_node_event(index, node_id))
            elif phase == 1:
                events.append(_edge_event(index, f"benchmark-node-{node_number - 1:06d}", node_id))
            elif phase == 2:
                events.append(
                    _event(
                        index,
                        "node_state_changed",
                        {"node_id": node_id, "new_state": "ready", "reason": "benchmark"},
                    )
                )
            else:
                events.append(_record_event(index, node_id, scenario))
    return events


def corpus_metadata(scenario: str, size: int) -> dict[str, Any]:
    """Derive cardinality expectations from the emitted stream, not fixed totals."""
    events = corpus_events(scenario, size)
    counts = {
        event_type: sum(event.event_type == event_type for event in events)
        for event_type in {event.event_type for event in events}
    }
    records = counts.get("output_record_accepted", 0)
    return {
        "scenario": scenario,
        "event_count": len(events),
        "family_counts": counts,
        "projected": {
            "nodes": counts.get("node_created", 0),
            "edges": counts.get("edge_created", 0),
            "records": records,
            "append_index_entries": records,
        },
    }


def _replay(events: list[EventEnvelope]):
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _reduce_tail(projection: Any, tail: list[EventEnvelope]) -> Any:
    for event in tail:
        projection = reduce_event(projection, event)
    return projection


def _append_index_cardinality(projection: Any) -> int:
    return sum(
        len(records)
        for ports in output_records_by_node_port_view(projection).values()
        for records in ports.values()
    )


def _public_view(scenario: str, projection: Any) -> dict[str, Any]:
    if scenario == "record-heavy":
        return {
            "records": accepted_record_summaries_by_id_view(projection),
            "by_port": output_records_by_node_port_view(projection),
        }
    if scenario == "edge-heavy":
        return {"edges": edges_view(projection), "node_states": node_states_view(projection)}
    return {
        "edges": edges_view(projection),
        "records": accepted_record_summaries_by_id_view(projection),
        "node_states": node_states_view(projection),
    }


def _public_view_cardinality(view: dict[str, Any]) -> int:
    return sum(len(value) for value in view.values())


def _persistent_typed_operation(event_count: int) -> ImmutableGraphProjection:
    """Exercise Task 8's real persistent map and grouped-model replacement shape."""
    projection = ImmutableGraphProjection()
    for index in range(event_count):
        node_id = f"scaffold-node-{index:06d}"
        node = NodeProjection(
            spec=NodeSpecProjection(node_id=node_id, creation_position=index, kind="worker")
        )
        projection = projection.model_copy(
            update={"nodes": map_set(projection.nodes, node_id, node)}
        )
        if index:
            edge_id = f"scaffold-edge-{index:06d}"
            edge = EdgeValue(
                edge_id=edge_id,
                from_node_id=f"scaffold-node-{index - 1:06d}",
                from_port="output",
                to_node_id=node_id,
                to_port="input",
            )
            topology = projection.topology.model_copy(
                update={"edges": map_set(projection.topology.edges, edge_id, edge)}
            )
            projection = projection.model_copy(update={"topology": topology})
    return projection


def _timed(fn: Callable[[], Any], runs: int, unit: str = "ms") -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(runs):
        start = perf_counter()
        fn()
        samples.append((perf_counter() - start) * 1000)
    return {
        "median": round(median(samples), 6),
        "unit": unit,
        "source": "current",
        "sample_count": len(samples),
    }


def _warm(fn: Callable[[], Any], warmups: int) -> None:
    for _ in range(warmups):
        fn()


def _require_current_checkpoint_schema(schema_version: int) -> None:
    if schema_version != PROJECTION_SCHEMA_VERSION:
        raise ValueError(
            f"checkpoint schema {schema_version} is incompatible with {PROJECTION_SCHEMA_VERSION}"
        )


def _measure(scenario: str, events: list[EventEnvelope], warmups: int, runs: int) -> dict[str, Any]:
    projection = _replay(events)
    snapshot_split = len(events) // 2
    snapshot_prefix = _replay(events[:snapshot_split])
    checkpoint = projection_to_checkpoint(snapshot_prefix)
    checkpoint_json = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))
    snapshot_tail = events[snapshot_split:]

    def snapshot_operation() -> Any:
        return _reduce_tail(projection_from_checkpoint(checkpoint), snapshot_tail)

    assert snapshot_operation() == projection

    append_split = max(1, len(events) * 9 // 10)
    append_prefix = _replay(events[:append_split])
    append_tail = events[append_split:]

    def append_operation() -> Any:
        return _reduce_tail(append_prefix, append_tail)

    append_result = append_operation()
    assert append_result == projection

    stale_schema_version = PROJECTION_SCHEMA_VERSION - 1

    def cold_rebuild_operation() -> Any:
        try:
            _require_current_checkpoint_schema(stale_schema_version)
        except ValueError:
            return _replay(events)
        raise RuntimeError("stale checkpoint schema was accepted")

    assert cold_rebuild_operation() == projection

    def public_operation() -> dict[str, Any]:
        return _public_view(scenario, projection)

    public_view = public_operation()
    assert _public_view_cardinality(public_view) > 0

    operations = {
        "reducer_full_replay": lambda: _replay(events),
        "snapshot_tail": snapshot_operation,
        "cold_rebuild": cold_rebuild_operation,
        "checkpoint_encode": lambda: projection_to_checkpoint(snapshot_prefix),
        "checkpoint_decode": lambda: projection_from_checkpoint(checkpoint),
        "public_view": public_operation,
        "append_heavy_indexes": append_operation,
        "persistent_primitive_scaffold": lambda: _persistent_typed_operation(len(events)),
    }
    for operation in operations.values():
        _warm(operation, warmups)

    replay = _timed(operations["reducer_full_replay"], runs)
    per_event = dict(replay)
    per_event["median"] = round(replay["median"] / len(events), 9)
    per_event["unit"] = "ms/event"
    measurements = {
        "reducer_full_replay": replay,
        "reducer_per_event": per_event,
        "snapshot_tail": _timed(operations["snapshot_tail"], runs),
        "cold_rebuild": _timed(operations["cold_rebuild"], runs),
        "checkpoint_encode": _timed(operations["checkpoint_encode"], runs),
        "checkpoint_decode": _timed(operations["checkpoint_decode"], runs),
        "public_view": _timed(operations["public_view"], runs),
        "append_heavy_indexes": _timed(operations["append_heavy_indexes"], runs),
        "persistent_primitive_scaffold": _timed(operations["persistent_primitive_scaffold"], runs),
        "checkpoint_bytes": {
            "median": len(checkpoint_json.encode()),
            "unit": "bytes",
            "source": "current",
        },
        "max_observed": {"count": len(events), "source": "synthetic_corpus", "status": "available"},
    }
    measurements["public_view"]["result_cardinality"] = _public_view_cardinality(public_view)
    measurements["append_heavy_indexes"]["result_cardinality"] = _append_index_cardinality(
        append_result
    )
    measurements["cold_rebuild"]["rejected_schema_version"] = stale_schema_version
    measurements["operation_boundaries"] = {
        "snapshot_tail": "decode_checkpoint_then_reduce_suffix",
        "append_heavy_indexes": "prebuilt_prefix_then_reduce_suffix",
        "cold_rebuild": "reject_stale_schema_then_replay",
        "peak_memory_bytes": "replay_only_excluding_prebuilt_corpus",
    }
    memory_samples: list[int] = []
    for _ in range(runs):
        tracemalloc.start()
        _replay(events)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        memory_samples.append(peak)
    measurements["peak_memory_bytes"] = {
        "median": median(memory_samples),
        "unit": "bytes",
        "source": "current",
        "sample_count": len(memory_samples),
        "allocation_boundary": "replay_only_excluding_prebuilt_corpus",
    }
    return measurements


def _api_max_event_count(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=0.1) as response:
            payload = json.loads(response.read())
        count = payload.get("max_event_count")
        if type(count) is int:
            return {"count": count, "status": "available", "source": "api"}
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        pass
    return {"count": None, "status": "unavailable", "source": "api"}


def _environment() -> dict[str, Any]:
    dependencies = {name: version(name) for name in ("pydantic", "sqlalchemy")}
    return {
        "hardware": {"machine": platform.machine(), "processor": platform.processor()},
        "os": {"platform": platform.platform(), "release": platform.release()},
        "python": sys.version.split()[0],
        "dependencies": dependencies,
    }


def benchmark(sizes: list[int], warmups: int, runs: int, api_url: str) -> dict[str, Any]:
    scenario_metadata = json.loads(SCENARIOS_PATH.read_text())
    corpora = {
        f"{name}:{size}": [event.model_dump(mode="json") for event in corpus_events(name, size)]
        for name in SCENARIO_NAMES
        for size in sizes
    }
    corpus_hash = hashlib.sha256(
        json.dumps(corpora, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    scenarios: dict[str, Any] = {}
    for name in SCENARIO_NAMES:
        # The largest requested corpus is the gate corpus; smaller sizes establish scaling data.
        by_size = {
            str(size): _measure(name, corpus_events(name, size), warmups, runs) for size in sizes
        }
        selected = dict(by_size[str(max(sizes))])
        selected["event_count"] = max(sizes)
        selected["scenario"] = name
        selected["stream_metadata"] = corpus_metadata(name, max(sizes))
        selected["by_size"] = by_size
        scenarios[name] = selected
    return {
        "schema_version": 1,
        "measurement_source": "current-reducer",
        "scenario_metadata": scenario_metadata,
        "corpus": {"hash": corpus_hash, "sizes": sizes},
        "configuration": {"sizes": sizes, "warmups": warmups, "runs": runs},
        "environment": _environment(),
        "api_max_event_count": _api_max_event_count(api_url),
        "scenarios": scenarios,
    }


def _median(result: dict[str, Any], scenario: str, metric: str) -> float:
    return float(result["scenarios"][scenario][metric]["median"])


def gate_violations(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    if baseline.get("schema_version") != 1 or current.get("schema_version") != 1:
        return ["incompatible baseline schema_version"]
    for key in ("corpus", "configuration", "environment"):
        if baseline.get(key) != current.get(key):
            return [f"incompatible baseline {key}"]
    if baseline.get("measurement_source") != "current-reducer":
        return ["synthetic baseline measurements are not eligible for gates"]
    violations: list[str] = []
    for scenario in SCENARIO_NAMES:
        for metric, ratio, label in (
            ("reducer_full_replay", 1.15, "replay"),
            ("peak_memory_bytes", 1.15, "peak-memory"),
            ("checkpoint_bytes", 1.0, "checkpoint-size"),
            ("checkpoint_encode", 1.25, "codec/view"),
            ("checkpoint_decode", 1.25, "codec/view"),
            ("public_view", 1.25, "codec/view"),
            ("cold_rebuild", 1.15, "cold-rebuild"),
        ):
            prior, observed = (
                _median(baseline, scenario, metric),
                _median(current, scenario, metric),
            )
            # One-run invocations are deliberately a CLI smoke contract, not a
            # statistically useful performance sample. Zero/invalid thresholds
            # remain failures so the smoke test still exercises each diagnostic.
            if prior <= 0 or (current["configuration"]["runs"] >= 2 and observed > prior * ratio):
                violations.append(
                    f"{label} {scenario}/{metric}: {observed} exceeds {prior} * {ratio}"
                )
        sizes = current["configuration"]["sizes"]
        if len(sizes) >= 2:
            low, high = str(min(sizes)), str(max(sizes))
            low_value = current["scenarios"][scenario]["by_size"][low]["reducer_per_event"][
                "median"
            ]
            high_value = current["scenarios"][scenario]["by_size"][high]["reducer_per_event"][
                "median"
            ]
            if low_value <= 0 or (
                current["configuration"]["runs"] >= 2 and high_value / low_value > 2.5
            ):
                violations.append(
                    f"scale {scenario}/reducer_full_replay exceeds 2.5x after startup exclusion"
                )
    record_checkpoint = _median(current, "record-heavy", "checkpoint_bytes")
    general_checkpoint = _median(current, "general", "checkpoint_bytes")
    if record_checkpoint >= general_checkpoint:
        violations.append(
            "record-heavy checkpoint must be strictly smaller than general checkpoint"
        )
    return violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--check-gates", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/graph/max-event-count")
    args = parser.parse_args()
    if any(size < 2 for size in args.sizes) or sorted(set(args.sizes)) != args.sizes:
        parser.error("--sizes must be sorted, unique integers of at least 2")
    if args.warmups < 0 or args.runs < 1:
        parser.error("--warmups must be nonnegative and --runs must be positive")
    if args.write_baseline and args.check_gates:
        parser.error("--write-baseline and --check-gates are mutually exclusive")
    return args


def main() -> None:
    args = parse_args()
    result = benchmark(args.sizes, args.warmups, args.runs, args.api_url)
    if args.write_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.check_gates:
        if not args.baseline.exists():
            raise SystemExit(f"baseline not found: {args.baseline}")
        violations = gate_violations(json.loads(args.baseline.read_text()), result)
        result["gates"] = {
            "status": "passed" if not violations else "failed",
            "violations": violations,
        }
        if violations:
            print("\n".join(violations), file=sys.stderr)
            print(json.dumps(result, indent=2, sort_keys=True))
            raise SystemExit(1)
    else:
        result["gates"] = {"status": "not_checked", "violations": []}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
