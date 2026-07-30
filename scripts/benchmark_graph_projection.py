"""Measure deterministic graph projection replay baselines and enforce cutover gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tracemalloc
from decimal import Decimal
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    checkpoint_schema_is_current,
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
RESULT_SCHEMA_VERSION = 2
TOOL_IDENTITY = "graph-projection-benchmark"
TOOL_VERSION = "2"
GATED_METRICS = {
    "reducer_full_replay": ("ms", 1.15, "replay"),
    "peak_memory_bytes": ("bytes", 1.15, "peak-memory"),
    "checkpoint_bytes": ("bytes", 1.0, "checkpoint-size"),
    "checkpoint_encode": ("ms", 1.25, "codec/view"),
    "checkpoint_decode": ("ms", 1.25, "codec/view"),
    "public_view": ("ms", 1.25, "codec/view"),
}


class StrictResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricResult(StrictResultModel):
    median: float
    unit: str
    source: str
    sample_count: int = Field(ge=1)


class SizeResult(StrictResultModel):
    metrics: dict[str, MetricResult]
    metadata: dict[str, Any]


class ScenarioResult(StrictResultModel):
    sizes: dict[str, SizeResult]


class ScalingPoint(StrictResultModel):
    median: float
    startup_median: float
    unit: Literal["ms"]


class ScalingProbe(StrictResultModel):
    n: ScalingPoint
    two_n: ScalingPoint


class ToolIdentity(StrictResultModel):
    identity: Literal["graph-projection-benchmark"]
    version: Literal["2"]
    hash: str = Field(min_length=1)


class ArtifactIdentity(StrictResultModel):
    role: Literal["baseline", "target"]
    implementation_signature: str = Field(min_length=1)


class BenchmarkResult(StrictResultModel):
    schema_version: Literal[2]
    tool: ToolIdentity
    artifact: ArtifactIdentity
    source: dict[str, str]
    corpus: dict[str, Any]
    configuration: dict[str, Any]
    environment: dict[str, Any]
    max_event_count: dict[str, Any]
    scenarios: dict[str, ScenarioResult]
    scaling_probes: dict[str, dict[str, ScalingProbe]]


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
            "producer_port": "candidate",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "value": {"index": index, "summary": body, "changed_paths": [f"src/{index:06d}.py"]},
            "payload": {"corpus": scenario, "sequence": index},
            "provenance": {"producer": node_id, "source": "benchmark"},
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


def _require_current_checkpoint_schema(schema_version: int | None) -> None:
    if not checkpoint_schema_is_current(schema_version):
        raise ValueError(
            f"checkpoint schema {schema_version} is incompatible with {PROJECTION_SCHEMA_VERSION}"
        )


def _measure(scenario: str, events: list[EventEnvelope], warmups: int, runs: int) -> dict[str, Any]:
    projection = _replay(events)
    snapshot_split = len(events) // 2
    snapshot_prefix = _replay(events[:snapshot_split])
    snapshot_checkpoint = projection_to_checkpoint(snapshot_prefix)
    full_checkpoint = projection_to_checkpoint(projection)
    checkpoint_json = json.dumps(full_checkpoint, sort_keys=True, separators=(",", ":"))
    snapshot_tail = events[snapshot_split:]

    def snapshot_operation() -> Any:
        return _reduce_tail(projection_from_checkpoint(snapshot_checkpoint), snapshot_tail)

    assert snapshot_operation() == projection
    assert projection_from_checkpoint(full_checkpoint) == projection

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
        "checkpoint_encode": lambda: projection_to_checkpoint(projection),
        "checkpoint_decode": lambda: projection_from_checkpoint(full_checkpoint),
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
        "checkpoint_cardinalities": {
            "nodes": len(full_checkpoint["node_kinds"]),
            "edges": len(full_checkpoint["edges"]),
            "records": len(full_checkpoint["output_record_payloads"]),
        },
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


def _max_event_count(operator_count: int | None) -> dict[str, Any]:
    """Record only a supported count source; this API has no count-only endpoint."""
    if operator_count is None:
        return {"count": None, "status": "unsupported", "source": "unsupported"}
    if type(operator_count) is not int or operator_count < 0:
        raise ValueError("operator max event count must be a nonnegative exact integer")
    return {"count": operator_count, "status": "available", "source": "operator"}


def _environment() -> dict[str, Any]:
    dependencies = {name: version(name) for name in ("pydantic", "sqlalchemy")}
    return {
        "comparable": {
            "architecture": platform.machine(),
            "python": sys.version.split()[0],
            "dependencies": dependencies,
        },
        "informational": {
            "host": platform.node(),
            "processor": platform.processor(),
            "os": platform.system(),
            "os_release": platform.release(),
        },
    }


def _script_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _source_revision() -> str:
    return os.environ.get("GIT_COMMIT", "unknown")


def _metric_result(value: dict[str, Any], runs: int) -> dict[str, Any]:
    return {
        "median": value["median"],
        "unit": value["unit"],
        "source": value["source"],
        "sample_count": value.get("sample_count", runs),
    }


def benchmark(
    sizes: list[int],
    warmups: int,
    runs: int,
    api_url: str,
    *,
    artifact_role: Literal["baseline", "target"] = "target",
    operator_max_event_count: int | None = None,
) -> dict[str, Any]:
    del api_url  # Retained CLI compatibility; no bounded count-only endpoint exists.
    probe_sizes = sorted({size for size in sizes for size in (size, size * 2)})
    corpora = {
        f"{name}:{size}": [event.model_dump(mode="json") for event in corpus_events(name, size)]
        for name in SCENARIO_NAMES
        for size in probe_sizes
    }
    corpus_hash = hashlib.sha256(
        json.dumps(corpora, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    scenarios: dict[str, Any] = {}
    scaling_probes: dict[str, dict[str, Any]] = {}
    for name in SCENARIO_NAMES:
        by_size = {
            str(size): _measure(name, corpus_events(name, size), warmups, runs)
            for size in probe_sizes
        }
        scenarios[name] = {
            "sizes": {
                size: {
                    "metrics": {
                        metric: _metric_result(value, runs)
                        for metric, value in measurement.items()
                        if isinstance(value, dict) and "median" in value and "unit" in value
                    },
                    "metadata": {
                        "event_count": int(size),
                        "stream": corpus_metadata(name, int(size)),
                        "operation_boundaries": measurement["operation_boundaries"],
                    },
                }
                for size, measurement in by_size.items()
            }
        }
        scaling_probes[name] = {}
        for size in sizes:
            small = by_size[str(size)]["reducer_full_replay"]["median"]
            large = by_size[str(size * 2)]["reducer_full_replay"]["median"]
            startup = _timed(lambda: _replay([]), runs)["median"]
            scaling_probes[name][f"{size}_to_{size * 2}"] = {
                "n": {"median": small, "startup_median": startup, "unit": "ms"},
                "two_n": {"median": large, "startup_median": startup, "unit": "ms"},
            }
    result = BenchmarkResult(
        schema_version=RESULT_SCHEMA_VERSION,
        tool={"identity": TOOL_IDENTITY, "version": TOOL_VERSION, "hash": _script_hash()},
        artifact={
            "role": artifact_role,
            "implementation_signature": (
                "pre-cutover-current-reducer"
                if artifact_role == "baseline"
                else "post-cutover-immutable-projection"
            ),
        },
        source={"revision": _source_revision()},
        corpus={
            "hash": corpus_hash,
            "scenario_hash": hashlib.sha256(SCENARIOS_PATH.read_bytes()).hexdigest(),
        },
        configuration={
            "requested_sizes": sizes,
            "probe_sizes": probe_sizes,
            "warmups": warmups,
            "runs": runs,
        },
        environment=_environment(),
        max_event_count=_max_event_count(operator_max_event_count),
        scenarios=scenarios,
        scaling_probes=scaling_probes,
    )
    return result.model_dump(mode="json")


def _validation_diagnostics(document: dict[str, Any], name: str) -> list[str]:
    try:
        BenchmarkResult.model_validate(document)
    except ValidationError as error:
        return sorted(
            f"invalid {name} {'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
    return []


def _configuration_values(result: BenchmarkResult, key: str) -> list[int] | None:
    value = result.configuration.get(key)
    if not isinstance(value, list) or any(type(item) is not int or item < 2 for item in value):
        return None
    return value


def _exceeds(observed: float, baseline: float, limit: str) -> bool:
    return Decimal(str(observed)) > Decimal(str(baseline)) * Decimal(limit)


def gate_violations(baseline: dict[str, Any], target: dict[str, Any]) -> list[str]:
    """Validate comparability before applying every release equation exactly."""
    diagnostics = _validation_diagnostics(baseline, "baseline") + _validation_diagnostics(
        target, "target"
    )
    if diagnostics:
        return sorted(diagnostics)
    prior = BenchmarkResult.model_validate(baseline)
    observed = BenchmarkResult.model_validate(target)
    compatibility: list[str] = []
    if prior.artifact.role != "baseline":
        compatibility.append("incompatible baseline artifact.role: expected baseline")
    if observed.artifact.role != "target":
        compatibility.append("incompatible target artifact.role: expected target")
    if prior.artifact.implementation_signature == observed.artifact.implementation_signature:
        compatibility.append(
            "incompatible artifact.implementation_signature: baseline and target must differ"
        )
    for field in ("identity", "version", "hash"):
        if getattr(prior.tool, field) != getattr(observed.tool, field):
            compatibility.append(f"incompatible tool.{field}")
    for field in ("hash", "scenario_hash"):
        if prior.corpus.get(field) != observed.corpus.get(field):
            compatibility.append(f"incompatible corpus.{field}")
    if prior.environment.get("comparable") != observed.environment.get("comparable"):
        compatibility.append("incompatible environment.comparable")
    requested = _configuration_values(prior, "requested_sizes")
    target_requested = _configuration_values(observed, "requested_sizes")
    probes = _configuration_values(prior, "probe_sizes")
    target_probes = _configuration_values(observed, "probe_sizes")
    if requested is None or target_requested is None or requested != target_requested:
        compatibility.append("incompatible configuration.requested_sizes")
    if probes is None or target_probes is None or probes != target_probes:
        compatibility.append("incompatible configuration.probe_sizes")
    for key in ("warmups", "runs"):
        if prior.configuration.get(key) != observed.configuration.get(key):
            compatibility.append(f"incompatible configuration.{key}")
    if set(prior.scenarios) != set(SCENARIO_NAMES) or set(observed.scenarios) != set(
        SCENARIO_NAMES
    ):
        compatibility.append("incompatible scenarios: expected edge-heavy,general,record-heavy")
    if compatibility:
        return sorted(compatibility)

    required_sizes = [*requested, *probes] if requested is not None and probes is not None else []
    violations: list[str] = []
    for scenario in SCENARIO_NAMES:
        baseline_sizes = prior.scenarios[scenario].sizes
        target_sizes = observed.scenarios[scenario].sizes
        for size in required_sizes:
            size_key = str(size)
            if size_key not in baseline_sizes or size_key not in target_sizes:
                violations.append(f"incompatible {scenario}/{size}: missing size measurement")
                continue
            for metric, (unit, limit, label) in GATED_METRICS.items():
                before = baseline_sizes[size_key].metrics.get(metric)
                after = target_sizes[size_key].metrics.get(metric)
                if before is None or after is None:
                    violations.append(f"incompatible {scenario}/{size}/{metric}: missing metric")
                    continue
                if before.unit != unit or after.unit != unit or before.source != after.source:
                    violations.append(f"incompatible {scenario}/{size}/{metric}: unit or source")
                    continue
                if before.median <= 0:
                    violations.append(
                        f"{label} {scenario}/{size}/{metric}: invalid baseline median"
                    )
                elif _exceeds(after.median, before.median, str(limit)):
                    violations.append(
                        f"{label} {scenario}/{size}/{metric}: {after.median} exceeds {before.median} * {limit}"
                    )
            cold_before = baseline_sizes[size_key].metrics.get("reducer_full_replay")
            cold_after = target_sizes[size_key].metrics.get("cold_rebuild")
            if cold_before is None or cold_after is None:
                violations.append(f"incompatible {scenario}/{size}/cold_rebuild: missing metric")
            elif (
                cold_before.unit != "ms"
                or cold_after.unit != "ms"
                or cold_before.source != cold_after.source
            ):
                violations.append(f"incompatible {scenario}/{size}/cold_rebuild: unit or source")
            elif cold_before.median <= 0:
                violations.append(f"cold-rebuild {scenario}/{size}: invalid baseline replay median")
            elif _exceeds(cold_after.median, cold_before.median, "1.15"):
                violations.append(
                    f"cold-rebuild {scenario}/{size}: {cold_after.median} exceeds {cold_before.median} * 1.15"
                )
            if scenario == "record-heavy":
                before = baseline_sizes[size_key].metrics.get("checkpoint_bytes")
                after = target_sizes[size_key].metrics.get("checkpoint_bytes")
                if before is not None and after is not None and after.median >= before.median:
                    violations.append(
                        f"record-heavy checkpoint {scenario}/{size}: {after.median} must be strictly smaller than {before.median}"
                    )
        for size in requested or []:
            probe_key = f"{size}_to_{size * 2}"
            probe = observed.scaling_probes.get(scenario, {}).get(probe_key)
            if probe is None:
                violations.append(f"incompatible scaling {scenario}/{probe_key}: missing probe")
                continue
            denominator = probe.n.median - probe.n.startup_median
            numerator = probe.two_n.median - probe.two_n.startup_median
            if denominator <= 0:
                violations.append(f"scaling {scenario}/{probe_key}: invalid denominator")
            elif numerator / denominator > 2.5:
                violations.append(
                    f"scaling {scenario}/{probe_key}: {numerator} / {denominator} exceeds 2.5"
                )
    return sorted(violations)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--check-gates", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/graph/max-event-count")
    parser.add_argument("--max-event-count", type=int)
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
    result = benchmark(
        args.sizes,
        args.warmups,
        args.runs,
        args.api_url,
        artifact_role="baseline" if args.write_baseline else "target",
        operator_max_event_count=args.max_event_count,
    )
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
