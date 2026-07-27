import json
from pathlib import Path

from scripts.generate_graph_projection_goldens import (
    build_replay_goldens,
    canonical_json,
    check_canonical_json,
)


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "graph_projection_migration"
REPLAY_GOLDENS = FIXTURE_DIR / "replay_goldens.json"


def test_replay_goldens_match_current_projection() -> None:
    expected = json.loads(REPLAY_GOLDENS.read_text())

    assert build_replay_goldens() == expected


def test_canonical_json_check_accepts_exact_canonical_text(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    value = {"a": {"b": 1}, "z": [2, 3]}
    path.write_text(canonical_json(value))

    assert check_canonical_json(path, value) is None


def test_canonical_json_check_reports_key_ordering_drift(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    value = {"a": 1, "z": 2}
    path.write_text('{\n  "z": 2,\n  "a": 1\n}\n')

    mismatch = check_canonical_json(path, value)

    assert mismatch is not None
    assert '  "z": 2' in mismatch
    assert '+  "a": 1' in mismatch
    assert path.read_text() == '{\n  "z": 2,\n  "a": 1\n}\n'


def test_canonical_json_check_reports_indentation_drift(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    value = {"a": {"b": 1}}
    path.write_text('{\n    "a": {\n        "b": 1\n    }\n}\n')

    mismatch = check_canonical_json(path, value)

    assert mismatch is not None
    assert '-    "a": {' in mismatch
    assert '+  "a": {' in mismatch


def test_canonical_json_check_reports_missing_terminal_newline(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    value = {"a": 1}
    path.write_text('{\n  "a": 1\n}')

    mismatch = check_canonical_json(path, value)

    assert mismatch is not None
    assert "No newline at end of file" in mismatch


def test_canonical_json_check_reports_crlf_drift(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    value = {"a": 1}
    path.write_bytes(b'{\r\n  "a": 1\r\n}\r\n')

    mismatch = check_canonical_json(path, value)

    assert mismatch is not None
