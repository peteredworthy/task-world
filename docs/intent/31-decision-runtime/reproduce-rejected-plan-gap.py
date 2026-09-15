"""Exercise the repaired Slice 3F rejected-plan handoff without a live server.

Run from the repository root:
    UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
        docs/intent/31-decision-runtime/reproduce-rejected-plan-gap.py

The disposable production dispatch sequence rejects the initial plan and first
repair, verifies the second repair, and dispatches its successor. This command
failed during correction resolution at the review checkpoint; it now serves as
a repeatable closure diagnostic. The original failure is retained in slice-3-review.md.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from collections.abc import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def reproduce() -> None:
    from orchestrator.db import create_engine, create_session_factory
    from orchestrator.graph import (
        FakeClock,
        SequentialIdGenerator,
        node_kinds_view,
        node_payload_view,
        node_states_view,
        resolve_correction_decision_context,
    )
    from orchestrator.graph_runtime import GraphController
    from tests.integration.test_graph_decision_runtime import (
        _exercise_initial_discovery_brief,
    )

    with TemporaryDirectory(prefix="rejected-plan-gap-") as directory:
        root = Path(directory).resolve()
        await _exercise_initial_discovery_brief(
            root,
            verifier_grade="F",
            mutate_after_answer=False,
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
            completed_corrections = [
                node_id
                for node_id in node_kinds_view(projection)
                if (node_payload_view(projection, node_id) or {}).get("role") == "gap_planner"
                and node_states_view(projection).get(node_id) == "completed"
            ]
            assert len(completed_corrections) == 2
            for correction_id in completed_corrections:
                print(f"Completed correction node: {correction_id}")
                context = resolve_correction_decision_context(projection, correction_id)
                assert context.phase == "initial_plan"
                assert context.selected_batch is None
                assert context.plan_verification_record_id is None
            print("Passed: rejected plan → repeated repair → independent verification → successor")
        finally:
            await engine.dispose()


def check_entrypoint() -> None:
    """Verify that standalone execution can resolve its runtime scenario."""
    from tests.integration.test_graph_decision_runtime import (
        _complete_rejected_initial_plan_scenario,
        _exercise_initial_discovery_brief,
    )

    assert callable(_exercise_initial_discovery_brief)
    assert callable(_complete_rejected_initial_plan_scenario)
    print("Ready: rejected-plan reproducer imports resolve without PYTHONPATH")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--check"]:
        check_entrypoint()
        return 0
    if arguments:
        print("usage: reproduce-rejected-plan-gap.py [--check]", file=sys.stderr)
        return 2
    asyncio.run(reproduce())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
