"""Measure deterministic graph projection replay baselines and enforce cutover gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tracemalloc
from decimal import Decimal
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from statistics import median
from time import perf_counter
from math import isfinite
from typing import Annotated, Any, Callable, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

import orchestrator.graph as graph

from orchestrator.graph import (
    Actor,
    ActorKind,
    EdgeValue,
    EventEnvelope,
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
BENCHMARK_PROTOCOL = {
    "version": 1,
    "scenarios": SCENARIO_NAMES,
    "corpora": "canonical-event-envelope-v1",
    "operation_boundaries": {
        "replay": "canonical_event_fold",
        "peak_memory": "replay_only_excluding_prebuilt_corpus",
        "cold_rebuild": "reject_stale_schema_then_replay",
    },
    "units": {"time": "ms", "memory": "bytes"},
    "gates": {
        "replay_memory_cold": "1.15",
        "checkpoint": "1.0",
        "codec_view": "1.25",
        "scale": "2.5",
    },
}


def protocol_hash() -> str:
    return hashlib.sha256(
        json.dumps(BENCHMARK_PROTOCOL, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


GATED_METRICS = {
    "reducer_full_replay": ("ms", 1.15, "replay"),
    "peak_memory_bytes": ("bytes", 1.15, "peak-memory"),
    "checkpoint_bytes": ("bytes", 1.0, "checkpoint-size"),
    "checkpoint_encode": ("ms", 1.25, "codec/view"),
    "checkpoint_decode": ("ms", 1.25, "codec/view"),
    "public_view": ("ms", 1.25, "codec/view"),
}


class StrictResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SourceRevision(StrictResultModel):
    revision: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")


class ToolIdentity(StrictResultModel):
    identity: Literal["graph-projection-benchmark"]
    version: Literal["2"]
    hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactIdentity(StrictResultModel):
    role: Literal["baseline", "target"]
    implementation_signature: StrictStr = Field(min_length=1)


class CorpusIdentity(StrictResultModel):
    hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class BenchmarkConfiguration(StrictResultModel):
    requested_sizes: list[StrictInt]
    probe_sizes: list[StrictInt]
    warmups: StrictInt = Field(ge=0)
    runs: StrictInt = Field(gt=0)

    @field_validator("requested_sizes", "probe_sizes")
    @classmethod
    def sizes_are_sorted_unique_positive(cls, value: list[int]) -> list[int]:
        if not value or any(size <= 0 for size in value) or value != sorted(set(value)):
            raise ValueError("must be sorted, unique, positive integers")
        return value

    @model_validator(mode="after")
    def probe_sizes_are_requested_doubles(self) -> BenchmarkConfiguration:
        expected = sorted({size for size in self.requested_sizes for size in (size, size * 2)})
        if self.probe_sizes != expected:
            raise ValueError("probe_sizes must be the exact union of requested sizes and doubles")
        return self


class ComparableDependencies(StrictResultModel):
    pydantic: StrictStr = Field(min_length=1)
    sqlalchemy: StrictStr = Field(min_length=1)


class ComparableEnvironment(StrictResultModel):
    architecture: StrictStr = Field(min_length=1)
    python: StrictStr = Field(min_length=1)
    dependencies: ComparableDependencies


class InformationalEnvironment(StrictResultModel):
    host: StrictStr
    processor: StrictStr
    os: StrictStr
    os_release: StrictStr


class BenchmarkEnvironment(StrictResultModel):
    comparable: ComparableEnvironment
    informational: InformationalEnvironment


class UnsupportedMaxEventCount(StrictResultModel):
    kind: Literal["unsupported"]
    count: None
    status: Literal["unsupported"]
    source: Literal["unsupported"]


class OperatorMaxEventCount(StrictResultModel):
    kind: Literal["available"]
    count: StrictInt = Field(ge=0)
    status: Literal["available"]
    source: Literal["operator"]


MaxEventCount = Annotated[
    UnsupportedMaxEventCount | OperatorMaxEventCount,
    Field(discriminator="kind"),
]


class SampledMetric(StrictResultModel):
    kind: Literal["sampled"]
    median: StrictFloat
    unit: Literal["ms", "ms/event", "bytes"]
    source: Literal["current"]
    sample_count: StrictInt = Field(ge=1)

    @field_validator("median")
    @classmethod
    def median_is_finite_nonnegative(cls, value: float) -> float:
        if not isfinite(value) or value < 0:
            raise ValueError("must be finite and nonnegative")
        return value


class CheckpointBytesMetric(StrictResultModel):
    kind: Literal["deterministic"]
    median: StrictFloat
    unit: Literal["bytes"]
    source: Literal["current"]
    sample_count: Literal[1]

    @field_validator("median")
    @classmethod
    def median_is_finite_nonnegative(cls, value: float) -> float:
        if not isfinite(value) or value < 0:
            raise ValueError("must be finite and nonnegative")
        return value


class MetricCollection(StrictResultModel):
    reducer_full_replay: SampledMetric
    reducer_per_event: SampledMetric
    snapshot_tail: SampledMetric
    cold_rebuild: SampledMetric
    checkpoint_encode: SampledMetric
    checkpoint_decode: SampledMetric
    public_view: SampledMetric
    append_heavy_indexes: SampledMetric
    persistent_primitive_scaffold: SampledMetric
    peak_memory_bytes: SampledMetric
    checkpoint_bytes: CheckpointBytesMetric

    @model_validator(mode="after")
    def metrics_have_canonical_units(self) -> MetricCollection:
        expected_units = {
            "reducer_per_event": "ms/event",
            "peak_memory_bytes": "bytes",
            "checkpoint_bytes": "bytes",
        }
        for name in type(self).model_fields:
            expected = expected_units.get(name, "ms")
            if getattr(self, name).unit != expected:
                raise ValueError(f"{name} must use {expected}")
        return self


class EventFamilyCardinalities(StrictResultModel):
    node_created: StrictInt = Field(ge=0)
    node_state_changed: StrictInt = Field(ge=0)
    edge_created: StrictInt = Field(ge=0)
    output_record_accepted: StrictInt = Field(ge=0)


class ProjectedCardinalities(StrictResultModel):
    nodes: StrictInt = Field(ge=0)
    edges: StrictInt = Field(ge=0)
    records: StrictInt = Field(ge=0)
    append_index_entries: StrictInt = Field(ge=0)


class ScaffoldCardinalities(StrictResultModel):
    nodes: StrictInt = Field(ge=0)
    edges: StrictInt = Field(ge=0)


class StreamMetadata(StrictResultModel):
    scenario: Literal["general", "edge-heavy", "record-heavy"]
    event_count: StrictInt = Field(gt=0)
    family_counts: EventFamilyCardinalities
    projected: ProjectedCardinalities


class OperationBoundaries(StrictResultModel):
    snapshot_tail: Literal["decode_checkpoint_then_reduce_suffix"]
    append_heavy_indexes: Literal["prebuilt_prefix_then_reduce_suffix"]
    cold_rebuild: Literal["reject_stale_schema_then_replay"]
    peak_memory_bytes: Literal["replay_only_excluding_prebuilt_corpus"]


class SizeMetadata(StrictResultModel):
    event_count: StrictInt = Field(gt=0)
    stream: StreamMetadata
    scaffold: ScaffoldCardinalities
    operation_boundaries: OperationBoundaries


class SizeResult(StrictResultModel):
    metrics: MetricCollection
    metadata: SizeMetadata


class ScenarioResult(StrictResultModel):
    sizes: dict[StrictStr, SizeResult]


class ScalingPair(StrictResultModel):
    n: StrictInt = Field(gt=0)
    two_n: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def second_size_is_double(self) -> ScalingPair:
        if self.two_n != self.n * 2:
            raise ValueError("two_n must equal twice n")
        return self


class ScalingProbe(StrictResultModel):
    pair: ScalingPair
    startup: SampledMetric

    @field_validator("startup")
    @classmethod
    def startup_is_milliseconds(cls, value: SampledMetric) -> SampledMetric:
        if value.unit != "ms":
            raise ValueError("startup must use ms")
        return value


class BenchmarkResult(StrictResultModel):
    schema_version: Literal[2]
    tool: ToolIdentity
    artifact: ArtifactIdentity
    source: SourceRevision
    corpus: CorpusIdentity
    configuration: BenchmarkConfiguration
    environment: BenchmarkEnvironment
    max_event_count: MaxEventCount
    scenarios: dict[Literal["general", "edge-heavy", "record-heavy"], ScenarioResult]
    scaling_probes: dict[Literal["general", "edge-heavy", "record-heavy"], list[ScalingProbe]]

    @model_validator(mode="after")
    def content_matches_configuration(self) -> BenchmarkResult:
        expected_scenarios = set(SCENARIO_NAMES)
        if (
            set(self.scenarios) != expected_scenarios
            or set(self.scaling_probes) != expected_scenarios
        ):
            raise ValueError(
                "scenarios and scaling_probes must contain exactly the required scenarios"
            )
        expected_sizes = {str(size) for size in self.configuration.probe_sizes}
        for scenario_name in SCENARIO_NAMES:
            scenario = self.scenarios[scenario_name]
            if set(scenario.sizes) != expected_sizes:
                raise ValueError(f"scenario {scenario_name} sizes must exactly match probe_sizes")
            for size_key, result in scenario.sizes.items():
                size = int(size_key)
                if (
                    result.metadata.event_count != size
                    or result.metadata.stream.event_count != size
                ):
                    raise ValueError(f"scenario {scenario_name}/{size} event_count must equal size")
                if result.metadata.stream.scenario != scenario_name:
                    raise ValueError(f"scenario {scenario_name}/{size} stream scenario must match")
                for metric in type(result.metrics).model_fields:
                    value = getattr(result.metrics, metric)
                    if (
                        isinstance(value, SampledMetric)
                        and value.sample_count != self.configuration.runs
                    ):
                        raise ValueError(
                            f"scenario {scenario_name}/{size}/{metric} sample_count must equal runs"
                        )
            pairs = {
                (probe.pair.n, probe.pair.two_n) for probe in self.scaling_probes[scenario_name]
            }
            if len(pairs) != len(self.scaling_probes[scenario_name]):
                raise ValueError(f"scaling probes for {scenario_name} must not duplicate pairs")
            if any(
                probe.startup.sample_count != self.configuration.runs
                for probe in self.scaling_probes[scenario_name]
            ):
                raise ValueError(
                    f"scaling startup sample_count for {scenario_name} must equal runs"
                )
        return self


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
        "family_counts": {
            "node_created": counts.get("node_created", 0),
            "node_state_changed": counts.get("node_state_changed", 0),
            "edge_created": counts.get("edge_created", 0),
            "output_record_accepted": counts.get("output_record_accepted", 0),
        },
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


def _persistent_typed_operation(event_count: int) -> Any:
    """Exercise Task 8's real persistent map and grouped-model replacement shape."""
    graph_projection_type = getattr(graph, "GraphProjection", None)
    projection_type = graph_projection_type
    if graph_projection_type is not None and not hasattr(graph_projection_type(), "model_copy"):
        projection_type = getattr(graph, "ImmutableGraphProjection", None)
    if projection_type is None:
        raise RuntimeError("no public grouped graph projection type is available")
    projection = projection_type()
    if not hasattr(projection, "model_copy"):
        raise RuntimeError("public grouped graph projection type is not immutable")
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
        "kind": "sampled",
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
    scaffold = _persistent_typed_operation(len(events))
    scaffold_cardinalities = {
        "nodes": len(scaffold.nodes),
        "edges": len(scaffold.topology.edges),
    }

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
            "kind": "deterministic",
            "median": float(len(checkpoint_json.encode())),
            "unit": "bytes",
            "source": "current",
            "sample_count": 1,
        },
        "max_observed": {"count": len(events), "source": "synthetic_corpus", "status": "available"},
        "scaffold_cardinalities": scaffold_cardinalities,
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
        "kind": "sampled",
        "median": float(median(memory_samples)),
        "unit": "bytes",
        "source": "current",
        "sample_count": len(memory_samples),
        "allocation_boundary": "replay_only_excluding_prebuilt_corpus",
    }
    return measurements


def _max_event_count(operator_count: int | None) -> dict[str, Any]:
    """Record only a supported count source; this API has no count-only endpoint."""
    if operator_count is None:
        return {
            "kind": "unsupported",
            "count": None,
            "status": "unsupported",
            "source": "unsupported",
        }
    if type(operator_count) is not int or operator_count < 0:
        raise ValueError("operator max event count must be a nonnegative exact integer")
    return {
        "kind": "available",
        "count": operator_count,
        "status": "available",
        "source": "operator",
    }


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


def _source_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    revision = completed.stdout.strip()
    if (
        completed.returncode
        or len(revision) != 40
        or any(character not in "0123456789abcdef" for character in revision)
    ):
        raise RuntimeError("benchmark requires a 40-hex git source revision")
    return revision


def _metric_result(value: dict[str, Any], runs: int) -> dict[str, Any]:
    return {
        "kind": value.get("kind", "sampled"),
        "median": value["median"],
        "unit": value["unit"],
        "source": value["source"],
        "sample_count": value.get("sample_count", runs),
    }


def _implementation_identity() -> tuple[Literal["baseline", "target"], str]:
    projection = initial_projection()
    grouped = hasattr(projection, "model_copy")
    role: Literal["baseline", "target"] = "target" if grouped else "baseline"
    shape = type(projection).__name__ if grouped else "legacy-mapping"
    return role, f"{shape}:projection-schema-{PROJECTION_SCHEMA_VERSION}"


def benchmark(
    sizes: list[int],
    warmups: int,
    runs: int,
    *,
    operator_max_event_count: int | None = None,
) -> dict[str, Any]:
    artifact_role, implementation_signature = _implementation_identity()
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
                        "scaffold": measurement["scaffold_cardinalities"],
                        "operation_boundaries": measurement["operation_boundaries"],
                    },
                }
                for size, measurement in by_size.items()
            }
        }
        scaling_probes[name] = []
        for size in sizes:
            startup = _timed(lambda: _replay([]), runs)["median"]
            scaling_probes[name].append(
                {
                    "pair": {"n": size, "two_n": size * 2},
                    "startup": {
                        "kind": "sampled",
                        "median": startup,
                        "unit": "ms",
                        "source": "current",
                        "sample_count": runs,
                    },
                }
            )
    result = BenchmarkResult(
        schema_version=RESULT_SCHEMA_VERSION,
        tool={"identity": TOOL_IDENTITY, "version": TOOL_VERSION, "hash": protocol_hash()},
        artifact={
            "role": artifact_role,
            "implementation_signature": implementation_signature,
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
    if prior.artifact.role != "baseline" or observed.artifact.role != "target":
        compatibility.append("incompatible roles: expected baseline and target")
    if prior.artifact.implementation_signature == observed.artifact.implementation_signature:
        compatibility.append("incompatible fingerprints: baseline and target must differ")
    for field in ("identity", "version", "hash"):
        if getattr(prior.tool, field) != getattr(observed.tool, field):
            compatibility.append(f"incompatible protocol.{field}")
    for field in ("hash", "scenario_hash"):
        if getattr(prior.corpus, field) != getattr(observed.corpus, field):
            compatibility.append(f"incompatible corpus.{field}")
    if prior.configuration.requested_sizes != observed.configuration.requested_sizes:
        compatibility.append("incompatible sizes.requested")
    if prior.configuration.probe_sizes != observed.configuration.probe_sizes:
        compatibility.append("incompatible sizes.probe")
    if prior.configuration.warmups != observed.configuration.warmups:
        compatibility.append("incompatible sample accounting.warmups")
    if prior.configuration.runs != observed.configuration.runs:
        compatibility.append("incompatible sample accounting.runs")
    if prior.environment.comparable.architecture != observed.environment.comparable.architecture:
        compatibility.append("incompatible runtime architecture")
    if prior.environment.comparable.python != observed.environment.comparable.python:
        compatibility.append("incompatible runtime Python")
    if prior.environment.comparable.dependencies != observed.environment.comparable.dependencies:
        compatibility.append("incompatible runtime deps")
    if set(prior.scenarios) != set(observed.scenarios):
        compatibility.append("incompatible scenario set")
    if set(prior.scaling_probes) != set(observed.scaling_probes):
        compatibility.append("incompatible scaling scenario set")
    expected_pairs = {(size, size * 2) for size in prior.configuration.requested_sizes}
    for scenario in SCENARIO_NAMES:
        baseline_pairs = {
            (probe.pair.n, probe.pair.two_n) for probe in prior.scaling_probes[scenario]
        }
        target_pairs = {
            (probe.pair.n, probe.pair.two_n) for probe in observed.scaling_probes[scenario]
        }
        if baseline_pairs != expected_pairs or target_pairs != expected_pairs:
            compatibility.append(f"incompatible pairs {scenario}")
    if compatibility:
        return sorted(compatibility)

    required_sizes = prior.configuration.probe_sizes
    violations: list[str] = []
    for scenario in SCENARIO_NAMES:
        baseline_sizes = prior.scenarios[scenario].sizes
        target_sizes = observed.scenarios[scenario].sizes
        for size in required_sizes:
            size_key = str(size)
            before_metadata = baseline_sizes[size_key].metadata
            after_metadata = target_sizes[size_key].metadata
            if before_metadata != after_metadata:
                violations.append(f"incompatible scenario metadata {scenario}/{size}")
            for metric, (unit, limit, label) in GATED_METRICS.items():
                before = getattr(baseline_sizes[size_key].metrics, metric)
                after = getattr(target_sizes[size_key].metrics, metric)
                if before.unit != unit or after.unit != unit or before.source != after.source:
                    violations.append(f"incompatible units/sources {scenario}/{size}/{metric}")
                    continue
                if before.median <= 0:
                    violations.append(
                        f"{label} {scenario}/{size}/{metric}: invalid baseline median"
                    )
                elif _exceeds(after.median, before.median, str(limit)):
                    violations.append(
                        f"{label} {scenario}/{size}/{metric}: {after.median} exceeds {before.median} * {limit}"
                    )
            cold_before = baseline_sizes[size_key].metrics.reducer_full_replay
            cold_after = target_sizes[size_key].metrics.cold_rebuild
            if (
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
                before = baseline_sizes[size_key].metrics.checkpoint_bytes
                after = target_sizes[size_key].metrics.checkpoint_bytes
                if after.median >= before.median:
                    violations.append(
                        f"record-heavy checkpoint {scenario}/{size}: {after.median} must be strictly smaller than {before.median}"
                    )
        for probe in observed.scaling_probes[scenario]:
            n, two_n = probe.pair.n, probe.pair.two_n
            probe_key = f"{n}_to_{two_n}"
            n_replay = target_sizes[str(n)].metrics.reducer_full_replay
            two_n_replay = target_sizes[str(two_n)].metrics.reducer_full_replay
            if n_replay.unit != "ms" or two_n_replay.unit != "ms":
                violations.append(f"incompatible units {scenario}/{probe_key}/reducer_full_replay")
                continue
            denominator = n_replay.median - probe.startup.median
            numerator = two_n_replay.median - probe.startup.median
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
    parser.add_argument("--max-event-count", type=int)
    args = parser.parse_args()
    if any(size < 2 for size in args.sizes) or sorted(set(args.sizes)) != args.sizes:
        parser.error("--sizes must be sorted, unique integers of at least 2")
    if args.warmups < 0 or args.runs < 1:
        parser.error("--warmups must be nonnegative and --runs must be positive")
    if args.max_event_count is not None and args.max_event_count < 0:
        parser.error("--max-event-count must be nonnegative")
    if args.write_baseline and args.check_gates:
        parser.error("--write-baseline and --check-gates are mutually exclusive")
    return args


def main() -> None:
    args = parse_args()
    result = benchmark(
        args.sizes,
        args.warmups,
        args.runs,
        operator_max_event_count=args.max_event_count,
    )
    if args.write_baseline and result["artifact"]["role"] != "baseline":
        raise SystemExit("--write-baseline requires the current legacy/baseline implementation")
    if args.check_gates and result["artifact"]["role"] != "target":
        raise SystemExit("--check-gates requires the current grouped/target implementation")
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
