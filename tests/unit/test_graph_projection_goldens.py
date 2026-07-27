import json
from pathlib import Path

from scripts.generate_graph_projection_goldens import (
    build_public_view_goldens,
    build_replay_goldens,
)


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "graph_projection_migration"
REPLAY_GOLDENS = FIXTURE_DIR / "replay_goldens.json"
PUBLIC_VIEW_GOLDENS = FIXTURE_DIR / "public_view_goldens.json"


def test_replay_goldens_match_current_projection() -> None:
    expected = json.loads(REPLAY_GOLDENS.read_text())

    assert build_replay_goldens() == expected


def test_public_view_goldens_match_current_presenters() -> None:
    expected = json.loads(PUBLIC_VIEW_GOLDENS.read_text())

    assert build_public_view_goldens() == expected
