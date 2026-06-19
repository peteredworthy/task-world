"""Profile graph readback hot paths with one synthetic local run.

This script is intentionally deterministic and LLM-free. It writes a single
graph event stream to SQLite, then times the same read/projection/serialization
steps used by graph API endpoints.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import orchestrator.api as api
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore


RUN_ID = "profile-graph-readback"
PROFILE_NODE_ID = "worker-profile-0"
build_graph_projection_response = cast(
    Callable[[str, list[EventEnvelope]], Any],
    getattr(api, "build_graph_projection_response"),
)
build_node_detail_response = cast(
    Callable[[str, str, list[EventEnvelope]], Any],
    getattr(api, "build_node_detail_response"),
)


@dataclass(frozen=True)
class Measurement:
    name: str
    samples: int
    median_ms: float
    min_ms: float
    max_ms: float
    output_bytes: int | None = None


def _event(event_id: str, event_type: str, payload: dict[str, Any], index: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
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


def _synthetic_events(event_count: int, heavy_every: int, payload_kb: int) -> list[EventEnvelope]:
    events = [
        _event("profile-run-active", "run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "profile-root",
            "node_created",
            {"node_id": "root", "kind": "root", "state": "completed"},
            1,
        ),
        _event(
            "profile-worker-node",
            "node_created",
            {
                "node_id": PROFILE_NODE_ID,
                "kind": "worker",
                "role": "builder",
                "state": "running",
                "task_region_id": "profile-task",
                "candidate_id": "candidate-profile-0",
            },
            2,
        ),
        _event(
            "profile-lease",
            "lease_granted",
            {
                "node_id": PROFILE_NODE_ID,
                "lease_id": "lease-profile-0",
                "generation": 1,
                "execution_id": "exec-profile-0",
                "expires_at": "2026-01-01T00:10:00+00:00",
            },
            3,
        ),
    ]
    heavy_text = "x" * (payload_kb * 1024)
    for index in range(4, event_count + 1):
        node_id = f"worker-profile-{index % 20}"
        if index % heavy_every == 0:
            producer_node_id = PROFILE_NODE_ID if index % (heavy_every * 5) == 0 else node_id
            events.append(
                _event(
                    f"profile-output-{index}",
                    "output_record_accepted",
                    {
                        "record_id": f"record-{index}",
                        "record_kind": "output",
                        "producer_node_id": producer_node_id,
                        "port": "profile_payload",
                        "schema": "ProfilePayload",
                        "value": {
                            "index": index,
                            "body": heavy_text,
                            "grades": [{"id": "req-1", "grade": "A"}],
                        },
                    },
                    index,
                )
            )
        elif index % 7 == 0:
            events.append(
                _event(
                    f"profile-callback-{index}",
                    "callback_accepted",
                    {
                        "node_id": node_id,
                        "lease_id": f"lease-{index}",
                        "lease_generation": 1,
                        "payload": {"body": heavy_text},
                    },
                    index,
                )
            )
        else:
            events.append(
                _event(
                    f"profile-node-{index}",
                    "node_state_changed",
                    {
                        "node_id": node_id,
                        "new_state": "ready" if index % 3 == 0 else "blocked",
                        "reason": "profile_synthetic_state",
                    },
                    index,
                )
            )
    return events[:event_count]


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event_count: int,
    heavy_every: int,
    payload_kb: int,
) -> int:
    events = _synthetic_events(event_count, heavy_every, payload_kb)
    async with session_factory() as session:
        async with session.begin():
            stored = await GraphEventStore(session).append_events(RUN_ID, 0, events)
    return len(stored)


async def _read_full(session_factory: async_sessionmaker[AsyncSession]) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(RUN_ID)


async def _read_light(session_factory: async_sessionmaker[AsyncSession]) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run_light(RUN_ID)


async def _read_projection(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run_projection(RUN_ID)


async def _read_summary(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        summaries = await GraphEventStore(session).read_run_summaries(RUN_ID)
    return json.dumps([asdict(summary) for summary in summaries], sort_keys=True)


async def _events_full_json(session_factory: async_sessionmaker[AsyncSession]) -> str:
    events = await _read_full(session_factory)
    return json.dumps([event.model_dump(mode="json") for event in events], sort_keys=True)


async def _projection_endpoint_like(session_factory: async_sessionmaker[AsyncSession]) -> str:
    events = await _read_projection(session_factory)
    return build_graph_projection_response(RUN_ID, events).model_dump_json()


async def _projection_endpoint_full_payload_like(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    events = await _read_full(session_factory)
    return build_graph_projection_response(RUN_ID, events).model_dump_json()


async def _node_detail_endpoint_like(session_factory: async_sessionmaker[AsyncSession]) -> str:
    events = await _read_light(session_factory)
    detail = build_node_detail_response(RUN_ID, PROFILE_NODE_ID, events, payload_mode="summary")
    if detail is None:
        msg = f"profile node not found: {PROFILE_NODE_ID}"
        raise RuntimeError(msg)
    return detail.model_dump_json()


async def _node_detail_endpoint_full_payload_like(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    events = await _read_full(session_factory)
    detail = build_node_detail_response(RUN_ID, PROFILE_NODE_ID, events, payload_mode="full")
    if detail is None:
        msg = f"profile node not found: {PROFILE_NODE_ID}"
        raise RuntimeError(msg)
    return detail.model_dump_json()


async def _measure_async(
    name: str,
    iterations: int,
    fn: Callable[[], Awaitable[object]],
) -> Measurement:
    samples: list[float] = []
    output_bytes: int | None = None
    for _ in range(iterations):
        start = perf_counter()
        output = await fn()
        elapsed_ms = (perf_counter() - start) * 1000
        samples.append(elapsed_ms)
        output_bytes = _output_size(output)
    return Measurement(
        name=name,
        samples=iterations,
        median_ms=round(median(samples), 3),
        min_ms=round(min(samples), 3),
        max_ms=round(max(samples), 3),
        output_bytes=output_bytes,
    )


async def _measure_sync(
    name: str,
    iterations: int,
    fn: Callable[[], object],
) -> Measurement:
    samples: list[float] = []
    output_bytes: int | None = None
    for _ in range(iterations):
        start = perf_counter()
        output = fn()
        elapsed_ms = (perf_counter() - start) * 1000
        samples.append(elapsed_ms)
        output_bytes = _output_size(output)
    return Measurement(
        name=name,
        samples=iterations,
        median_ms=round(median(samples), 3),
        min_ms=round(min(samples), 3),
        max_ms=round(max(samples), 3),
        output_bytes=output_bytes,
    )


def _output_size(output: object) -> int | None:
    if isinstance(output, str):
        return len(output.encode("utf-8"))
    if isinstance(output, list):
        return len(json.dumps([_jsonable(item) for item in output], sort_keys=True).encode("utf-8"))
    return None


def _jsonable(value: object) -> object:
    if isinstance(value, EventEnvelope):
        return value.model_dump(mode="json")
    return value


async def profile(args: argparse.Namespace) -> dict[str, Any]:
    engine: AsyncEngine = create_engine(Path(args.db_path) if args.db_path else ":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        seed_start = perf_counter()
        stored_events = await _seed(
            session_factory,
            event_count=args.events,
            heavy_every=args.heavy_every,
            payload_kb=args.payload_kb,
        )
        seed_ms = round((perf_counter() - seed_start) * 1000, 3)

        cached_events = await _read_full(session_factory)
        measurements = [
            Measurement(
                name="seed_append",
                samples=1,
                median_ms=seed_ms,
                min_ms=seed_ms,
                max_ms=seed_ms,
                output_bytes=None,
            ),
            await _measure_async(
                "store.read_run.full_materialize",
                args.iterations,
                lambda: _read_full(session_factory),
            ),
            await _measure_async(
                "store.read_run_light.projection_fields",
                args.iterations,
                lambda: _read_light(session_factory),
            ),
            await _measure_async(
                "store.read_run_projection.minimal_fields",
                args.iterations,
                lambda: _read_projection(session_factory),
            ),
            await _measure_async(
                "store.read_run_summaries.compact",
                args.iterations,
                lambda: _read_summary(session_factory),
            ),
            await _measure_sync(
                "projection.build_from_cached_events",
                args.iterations,
                lambda: build_graph_projection_response(RUN_ID, cached_events).model_dump_json(),
            ),
            await _measure_async(
                "endpoint_like.graph_projection",
                args.iterations,
                lambda: _projection_endpoint_like(session_factory),
            ),
            await _measure_async(
                "endpoint_like.graph_projection_full_payload_baseline",
                args.iterations,
                lambda: _projection_endpoint_full_payload_like(session_factory),
            ),
            await _measure_async(
                "endpoint_like.graph_events_full",
                args.iterations,
                lambda: _events_full_json(session_factory),
            ),
            await _measure_async(
                "endpoint_like.graph_events_summary",
                args.iterations,
                lambda: _read_summary(session_factory),
            ),
            await _measure_async(
                "endpoint_like.node_detail",
                args.iterations,
                lambda: _node_detail_endpoint_like(session_factory),
            ),
            await _measure_async(
                "endpoint_like.node_detail_full_payload",
                args.iterations,
                lambda: _node_detail_endpoint_full_payload_like(session_factory),
            ),
        ]
        return {
            "config": {
                "events": args.events,
                "heavy_every": args.heavy_every,
                "payload_kb": args.payload_kb,
                "iterations": args.iterations,
                "stored_events": stored_events,
            },
            "measurements": [asdict(measurement) for measurement in measurements],
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
    if args.events < 4:
        parser.error("--events must be at least 4")
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
