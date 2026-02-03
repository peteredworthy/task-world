"""Load routine definitions from YAML files."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from orchestrator.config.models import RoutineConfig
from orchestrator.routines.errors import (
    RoutineNotFoundError,
    RoutineParseError,
    RoutineValidationError,
)


def load_routine_from_path(path: Path) -> RoutineConfig:
    """Load a routine from a YAML file.

    Args:
        path: Path to the YAML file

    Returns:
        Validated RoutineConfig

    Raises:
        RoutineNotFoundError: If file doesn't exist
        RoutineParseError: If YAML is invalid
        RoutineValidationError: If content doesn't match schema
    """
    if not path.exists():
        raise RoutineNotFoundError(str(path))

    try:
        content = path.read_text()
        data: Any = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise RoutineParseError(str(path), str(e)) from e

    if data is None:
        raise RoutineParseError(str(path), "Empty file")

    # Handle both wrapped and unwrapped format
    if isinstance(data, dict) and "routine" in data:
        data = data["routine"]  # type: ignore[assignment]

    try:
        return RoutineConfig.model_validate(data)
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        raise RoutineValidationError(str(path), errors) from e
