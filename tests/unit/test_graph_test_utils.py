from collections.abc import Callable

import pytest

from orchestrator.graph import initial_projection, projection_to_checkpoint
from tests.unit.graph_test_utils import (
    projection_fixture_append,
    projection_fixture_replace,
    projection_fixture_set,
    projection_fixture_update,
)


def test_projection_fixture_replace_round_trips_and_preserves_input() -> None:
    original = initial_projection()

    replaced = projection_fixture_replace(original, "ready_nodes", ("node-1", "node-2"))

    assert projection_to_checkpoint(replaced)["ready_nodes"] == ["node-1", "node-2"]
    assert projection_to_checkpoint(original)["ready_nodes"] == []


def test_projection_fixture_set_clones_each_mapping_and_normalizes_value() -> None:
    original = projection_fixture_replace(
        initial_projection(), "node_output_ports", {"node-1": {"old": ["record-1"]}}
    )

    replaced = projection_fixture_set(
        original,
        "node_output_ports",
        ("node-1", "new"),
        ("record-2", "record-3"),
    )

    assert projection_to_checkpoint(replaced)["node_output_ports"]["node-1"]["new"] == [
        "record-2",
        "record-3",
    ]
    assert "new" not in projection_to_checkpoint(original)["node_output_ports"]["node-1"]
    assert replaced is not original


def test_projection_fixture_update_and_append_preserve_input() -> None:
    original = initial_projection()

    updated = projection_fixture_update(original, "node_roles", {"node-1": "builder"})
    appended = projection_fixture_append(updated, "ready_nodes", "node-1")

    assert projection_to_checkpoint(updated)["node_roles"] == {"node-1": "builder"}
    assert projection_to_checkpoint(appended)["ready_nodes"] == ["node-1"]
    assert projection_to_checkpoint(original)["node_roles"] == {}
    assert projection_to_checkpoint(updated)["ready_nodes"] == []


def test_projection_fixture_set_preserves_normalized_raw_fixture_payload() -> None:
    original = initial_projection()

    replaced = projection_fixture_set(
        original, "open_proposal_blockers", ("proposal-1",), {"reasons": ("original",)}
    )

    assert projection_to_checkpoint(replaced)["open_proposal_blockers"] == {
        "proposal-1": {"reasons": ["original"]}
    }
    assert projection_to_checkpoint(original)["open_proposal_blockers"] == {}


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda: projection_fixture_replace(initial_projection(), "missing", 1), "unknown"),
        (lambda: projection_fixture_set(initial_projection(), "node_roles", (), 1), "nonempty"),
        (
            lambda: projection_fixture_set(
                initial_projection(), "node_roles", ("node-1", 0), "builder"
            ),
            "strings",
        ),
        (
            lambda: projection_fixture_set(
                projection_fixture_replace(
                    initial_projection(), "node_roles", {"node-1": "builder"}
                ),
                "node_roles",
                ("node-1", "nested"),
                "value",
            ),
            "mapping",
        ),
        (lambda: projection_fixture_update(initial_projection(), "ready_nodes", {}), "mapping"),
        (lambda: projection_fixture_append(initial_projection(), "node_roles", "node-1"), "list"),
        (
            lambda: projection_fixture_replace(initial_projection(), "node_roles", {1: "builder"}),
            "strings",
        ),
    ],
)
def test_projection_fixture_helpers_fail_closed(
    operation: Callable[[], object], message: str
) -> None:
    with pytest.raises((KeyError, TypeError, ValueError), match=message):
        operation()
