"""Profile catalog-hydrated graph readback paths with strict sample payloads."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import resource
import sys
import tracemalloc
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter
from types import ModuleType
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphCatalog,
    HydratedEvent,
    build_graph_catalog,
)
from orchestrator.graph_runtime import GraphEventStore


RUN_ID = "profile-graph-readback"
SAMPLE_SOURCE = "tests/unit/graph_catalog_samples.py"


def _load_event_samples() -> dict[str, dict[str, object]]:
    source_path = Path(__file__).resolve().parents[1] / SAMPLE_SOURCE
    specification = importlib.util.spec_from_file_location("graph_catalog_samples", source_path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load profiler sample source: {source_path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    samples = cast(ModuleType, module).EVENT_SAMPLES
    if not isinstance(samples, dict):
        raise RuntimeError(f"invalid profiler sample source: {source_path}")
    return cast(dict[str, dict[str, object]], samples)


EVENT_SAMPLES = _load_event_samples()


@dataclass(frozen=True)
class ReaderMeasurement:
    name: str
    samples: int
    median_wall_ms: float
    min_wall_ms: float
    max_wall_ms: float
    rows: int
    payload_bytes: int
    tracemalloc_peak_bytes: int
    payload_parity: bool


def _event(event_type: str, payload: dict[str, Any], index: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"profile-{event_type}-{index}",
        run_id=RUN_ID,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="profile",
        correlation_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        payload=payload,
    )


def _sample_payload(
    catalog: GraphCatalog,
    event_type: str,
    payload: dict[str, object],
) -> dict[str, Any]:
    return catalog.resolve_event(event_type).validate_payload(payload).to_json()


def _heavy_payload(catalog: GraphCatalog, index: int, payload_kb: int) -> dict[str, Any]:
    payload = deepcopy(EVENT_SAMPLES["output_record_accepted"])
    record = payload["record"]
    assert isinstance(record, dict)
    record["record_id"] = f"profile-record-{index}"
    record["candidate_id"] = f"profile-candidate-{index}"
    value = record["value"]
    assert isinstance(value, dict)
    value["body"] = "x" * (payload_kb * 1024)
    return _sample_payload(catalog, "output_record_accepted", payload)


def _synthetic_events(
    event_count: int,
    heavy_every: int,
    payload_kb: int,
) -> list[EventEnvelope]:
    catalog = build_graph_catalog()
    events: list[EventEnvelope] = []
    for index in range(event_count):
        if (index + 1) % heavy_every == 0:
            event_type = "output_record_accepted"
            payload = _heavy_payload(catalog, index, payload_kb)
        else:
            event_type = "run_lifecycle_changed"
            payload = _sample_payload(catalog, event_type, EVENT_SAMPLES[event_type])
        events.append(_event(event_type, payload, index))
    return events


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    catalog: GraphCatalog,
    *,
    event_count: int,
    heavy_every: int,
    payload_kb: int,
) -> int:
    events = _synthetic_events(event_count, heavy_every, payload_kb)
    async with session_factory() as session:
        async with session.begin():
            stored = await GraphEventStore(session, catalog).append_events(RUN_ID, 0, events)
    return len(stored)


async def _read(
    session_factory: async_sessionmaker[AsyncSession],
    catalog: GraphCatalog,
    reader_name: str,
) -> list[HydratedEvent]:
    async with session_factory() as session:
        store = GraphEventStore(session, catalog)
        reader = getattr(store, reader_name)
        return await reader(RUN_ID)


def _serialized_payloads(events: list[HydratedEvent]) -> bytes:
    return json.dumps(
        [event.payload.to_json() for event in events],
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


async def _measure_reader(
    name: str,
    iterations: int,
    fn: Callable[[], Awaitable[list[HydratedEvent]]],
    baseline_payloads: bytes | None,
) -> tuple[ReaderMeasurement, bytes]:
    wall_samples: list[float] = []
    peak_samples: list[int] = []
    serialized = b""
    rows = 0
    parity = True
    for _ in range(iterations):
        tracemalloc.start()
        start = perf_counter()
        events = await fn()
        serialized = _serialized_payloads(events)
        wall_samples.append((perf_counter() - start) * 1000)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_samples.append(peak)
        rows = len(events)
        if baseline_payloads is not None:
            parity = parity and serialized == baseline_payloads
    measurement = ReaderMeasurement(
        name=name,
        samples=iterations,
        median_wall_ms=round(median(wall_samples), 3),
        min_wall_ms=round(min(wall_samples), 3),
        max_wall_ms=round(max(wall_samples), 3),
        rows=rows,
        payload_bytes=len(serialized),
        tracemalloc_peak_bytes=int(median(peak_samples)),
        payload_parity=parity,
    )
    return measurement, serialized


def _process_max_rss_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1024)


async def profile(args: argparse.Namespace) -> dict[str, Any]:
    profile_start = perf_counter()
    catalog = build_graph_catalog()
    engine: AsyncEngine = create_engine(Path(args.db_path) if args.db_path else ":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        stored_rows = await _seed(
            session_factory,
            catalog,
            event_count=args.events,
            heavy_every=args.heavy_every,
            payload_kb=args.payload_kb,
        )
        readers = (
            "read_run",
            "read_run_light",
            "read_run_summary_rebuild",
            "read_run_projection",
            "read_run_node_detail",
        )
        measurements: list[ReaderMeasurement] = []
        baseline_payloads: bytes | None = None
        for reader_name in readers:
            measurement, serialized = await _measure_reader(
                reader_name,
                args.iterations,
                lambda reader_name=reader_name: _read(session_factory, catalog, reader_name),
                baseline_payloads,
            )
            measurements.append(measurement)
            if baseline_payloads is None:
                baseline_payloads = serialized
        wall_ms = round((perf_counter() - profile_start) * 1000, 3)
        return {
            "config": {
                "events": args.events,
                "heavy_every": args.heavy_every,
                "payload_kb": args.payload_kb,
                "iterations": args.iterations,
                "sample_source": SAMPLE_SOURCE,
            },
            "profile": {
                "stored_rows": stored_rows,
                "wall_ms": wall_ms,
                "process_max_rss_bytes": _process_max_rss_bytes(),
            },
            "readers": [asdict(measurement) for measurement in measurements],
        }
    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=300)
    parser.add_argument("--heavy-every", type=int, default=2)
    parser.add_argument("--payload-kb", type=int, default=64)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--db-path", default="")
    args = parser.parse_args()
    if args.events < 1:
        parser.error("--events must be at least 1")
    if args.heavy_every < 1:
        parser.error("--heavy-every must be at least 1")
    if args.payload_kb < 1:
        parser.error("--payload-kb must be at least 1")
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    return args


def main() -> None:
    print(json.dumps(asyncio.run(profile(parse_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
