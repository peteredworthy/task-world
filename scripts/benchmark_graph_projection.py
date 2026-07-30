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
    EventEnvelope,
    edges_view,
    empty_frozen_map,
    initial_projection,
    map_set,
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


def corpus_events(scenario: str, size: int) -> list[EventEnvelope]:
    """Build a valid, deterministic corpus of exactly *size* graph events."""
    events: list[EventEnvelope] = []
    for index in range(size):
        if scenario == "record-heavy":
            if index == 0:
                events.append(
                    _event(
                        index,
                        "node_created",
                        {"node_id": "record-writer", "kind": "worker", "state": "planned"},
                    )
                )
            else:
                events.append(
                    _event(
                        index,
                        "output_record_accepted",
                        {
                            "record_id": "rolling-record",
                            "record_kind": "output",
                            "producer_node_id": "record-writer",
                            "port": "output",
                            "schema": "BenchmarkRecord",
                            "value": {"index": index, "body": f"record-value-{index:06d}"},
                        },
                    )
                )
            continue
        node_id = f"node-{index // 2}"
        if scenario == "edge-heavy" and index % 2:
            previous = f"node-{max(0, index // 2 - 1)}"
            payload = {
                "edge_id": f"edge-{index}",
                "from_node_id": previous,
                "from_port": "output",
                "to_node_id": node_id,
                "to_port": "input",
            }
            events.append(_event(index, "edge_created", payload))
        elif scenario == "general" and index % 3 == 2:
            events.append(
                _event(
                    index,
                    "output_record_accepted",
                    {
                        "record_id": f"record-{index}",
                        "record_kind": "output",
                        "producer_node_id": node_id,
                        "port": "output",
                        "schema": "BenchmarkRecord",
                        "value": {"index": index, "body": f"general-value-{index:06d}" * 4},
                    },
                )
            )
        elif scenario == "general" and index % 3 == 1:
            events.append(
                _event(
                    index,
                    "node_state_changed",
                    {"node_id": node_id, "new_state": "ready", "reason": "benchmark"},
                )
            )
        else:
            events.append(
                _event(
                    index,
                    "node_created",
                    {"node_id": node_id, "kind": "worker", "state": "planned"},
                )
            )
    return events


def _replay(events: list[EventEnvelope]):
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _snapshot_then_apply_tail(events: list[EventEnvelope]):
    split = len(events) // 2
    projection = _replay(events[:split])
    for event in events[split:]:
        projection = reduce_event(projection, event)
    return projection


def _append_heavy_indexes(events: list[EventEnvelope]):
    split = max(1, len(events) * 9 // 10)
    projection = _replay(events[:split])
    for event in events[split:]:
        projection = reduce_event(projection, event)
    return projection


def _persistent_primitive_operation(event_count: int):
    values = empty_frozen_map()
    for index in range(event_count):
        values = map_set(values, str(index), index)
    return values


def _timed(fn: Callable[[], Any], runs: int, unit: str = "ms") -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(runs):
        start = perf_counter()
        fn()
        samples.append((perf_counter() - start) * 1000)
    return {"median": round(median(samples), 6), "unit": unit, "source": "current"}


def _measure(events: list[EventEnvelope], warmups: int, runs: int) -> dict[str, Any]:
    for _ in range(warmups):
        _replay(events)
    projection = _replay(events)
    checkpoint = projection_to_checkpoint(projection)
    checkpoint_json = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))
    replay = _timed(lambda: _replay(events), runs)
    per_event = dict(replay)
    per_event["median"] = round(replay["median"] / len(events), 9)
    per_event["unit"] = "ms/event"
    measurements = {
        "reducer_full_replay": replay,
        "reducer_per_event": per_event,
        "snapshot_tail": _timed(lambda: _snapshot_then_apply_tail(events), runs),
        "cold_rebuild": _timed(lambda: _replay(events), runs),
        "checkpoint_encode": _timed(lambda: projection_to_checkpoint(projection), runs),
        "checkpoint_decode": _timed(lambda: projection_from_checkpoint(checkpoint), runs),
        "public_view": _timed(lambda: edges_view(projection), runs),
        "append_heavy_indexes": _timed(lambda: _append_heavy_indexes(events), runs),
        "persistent_primitive_scaffold": _timed(
            lambda: _persistent_primitive_operation(len(events)), runs
        ),
        "checkpoint_bytes": {
            "median": len(checkpoint_json.encode()),
            "unit": "bytes",
            "source": "current",
        },
        "max_observed": {"count": len(events), "source": "synthetic_corpus", "status": "available"},
    }
    tracemalloc.start()
    _replay(events)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    measurements["peak_memory_bytes"] = {"median": peak, "unit": "bytes", "source": "current"}
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
        by_size = {str(size): _measure(corpus_events(name, size), warmups, runs) for size in sizes}
        selected = dict(by_size[str(max(sizes))])
        selected["event_count"] = max(sizes)
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
