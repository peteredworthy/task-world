"""Tests for routine loader error handling."""

import pytest

from orchestrator.routines.errors import (
    RoutineNotFoundError,
    RoutineParseError,
    RoutineValidationError,
)
from orchestrator.routines.loader import load_routine_from_path


def test_load_nonexistent_file(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path))
    with pytest.raises(RoutineNotFoundError):
        load_routine_from_path(path / "nonexistent.yaml")


def test_load_invalid_yaml(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path))
    bad_file = path / "bad.yaml"
    bad_file.write_text("not: valid: yaml: [")
    with pytest.raises(RoutineParseError):
        load_routine_from_path(bad_file)


def test_load_empty_file(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path))
    empty_file = path / "empty.yaml"
    empty_file.write_text("")
    with pytest.raises(RoutineParseError, match="Empty"):
        load_routine_from_path(empty_file)


def test_load_missing_required_field(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path))
    bad_file = path / "missing.yaml"
    bad_file.write_text("routine:\n  name: No ID")
    with pytest.raises(RoutineValidationError):
        load_routine_from_path(bad_file)
