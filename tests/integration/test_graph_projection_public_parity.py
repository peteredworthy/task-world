import json
from pathlib import Path

import pytest

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph_runtime import GraphEventStore
from scripts.generate_graph_projection_goldens import _events, _scenarios, public_view_bodies


PUBLIC_VIEW_GOLDENS = (
    Path(__file__).parent.parent
    / "fixtures"
    / "graph_projection_migration"
    / "public_view_goldens.json"
)


@pytest.mark.asyncio
async def test_seeded_public_surfaces_match_golden_through_sqlite() -> None:
    expected = json.loads(PUBLIC_VIEW_GOLDENS.read_text())
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            store = GraphEventStore(session)
            selected = [
                scenario for scenario in _scenarios() if scenario["name"].startswith("invariant_")
            ]
            for index, scenario in enumerate(selected, start=1):
                run_id = f"public-golden-{index}"
                events = [
                    event.model_copy(update={"run_id": run_id}) for event in _events(scenario)
                ]
                await store.append_events(run_id, 0, events)
                persisted_events = await store.read_run_summary_rebuild(run_id)
                assert public_view_bodies(persisted_events) == expected[scenario["name"]]
    finally:
        await engine.dispose()
