"""Runtime seeding path for compiled routine graphs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig
from orchestrator.graph import EventEnvelope, compile_routine
from orchestrator.graph.commands import Clock, IdGenerator
from orchestrator.graph_runtime.controller import GraphController


@dataclass(frozen=True)
class SeedRunResult:
    events: list[EventEnvelope]
    projection_position: int


async def seed_run(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
    *,
    run_id: str,
    clock: Clock,
    id_gen: IdGenerator,
    expected_position: int = 0,
    source_path: str | None = None,
    source_ref: str | None = None,
    run_config: dict[str, Any] | None = None,
) -> SeedRunResult:
    """Compile and transactionally append a run's initial graph.

    Seeding goes through ``GraphController`` so the controller remains the
    single append path for accepted graph mutations. Compilation events are
    durable graph topology and static input facts, so they do not produce
    side-effect outbox rows.
    """
    planned_events = compile_routine(
        routine,
        clock,
        id_gen,
        run_id=run_id,
        source_path=source_path,
        source_ref=source_ref,
        run_config=run_config,
    )
    result = await GraphController(
        session_factory,
        clock,
        id_gen,
        auto_dispatch=False,
    ).handle_command(
        run_id,
        expected_position,
        "seed_compiled_events",
        {"events": planned_events},
    )
    return SeedRunResult(
        events=result.events,
        projection_position=result.projection_position,
    )
