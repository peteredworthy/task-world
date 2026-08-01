from orchestrator.graph import build_projection, node_states_view
from tests.unit.graph_test_utils import event


def test_event_helper_builds_strict_canonical_projection() -> None:
    projection = build_projection(
        [event("node_created", {"node_id": "worker-1", "kind": "worker"})]
    )

    assert node_states_view(projection) == {"worker-1": "planned"}
