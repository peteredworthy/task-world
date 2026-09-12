"""Reproduce the Slice 3F rejected-plan contract blocker without a live server.

Run from the recovery-stabilization worktree:
    PYTHONPATH=. UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
        docs/intent/31-decision-runtime/reproduce-rejected-plan-gap.py

The disposable real dispatch sequence produces an F plan verification; resolving
its generated correction node currently raises DecisionContractResolutionError.
This is diagnostic evidence of the architectural stop recorded in implementation.md.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.config import AgentRunnerType
from orchestrator.db import create_engine, create_session_factory
from orchestrator.graph import (
    FakeClock,
    SequentialIdGenerator,
    node_kinds_view,
    node_payload_view,
    resolve_correction_decision_context,
)
from orchestrator.graph_runtime import GraphController
from tests.integration.test_graph_decision_runtime import (
    test_initial_discovery_brief_runs_through_production_dispatch_and_finalization,
)


async def reproduce() -> None:
    with TemporaryDirectory(prefix="rejected-plan-gap-") as directory:
        root = Path(directory).resolve()
        await test_initial_discovery_brief_runs_through_production_dispatch_and_finalization(
            root, AgentRunnerType.CODEX_SERVER, "F", "failed", False, False
        )
        engine = create_engine(root / "initial-decision.db")
        try:
            controller = GraphController(
                create_session_factory(engine),
                FakeClock(),
                SequentialIdGenerator(),
                auto_dispatch=False,
            )
            projection = await controller.read_projection("initial-decision-product")
            correction_id = next(
                node_id
                for node_id in node_kinds_view(projection)
                if (node_payload_view(projection, node_id) or {}).get("role") == "gap_planner"
            )
            print(f"Generated correction node: {correction_id}")
            resolve_correction_decision_context(projection, correction_id)
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(reproduce())
