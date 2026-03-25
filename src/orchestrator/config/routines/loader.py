"""Load routine definitions from YAML files."""

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from orchestrator.config.models import RoutineConfig
from orchestrator.config.routines.errors import (
    RoutineNotFoundError,
    RoutineParseError,
    RoutineValidationError,
)


def _resolve_step_files(
    steps: list[Any],
    routine_dir: Path,
    routine_path: Path,
    visited: set[Path],
) -> list[Any]:
    """Resolve any steps that reference external YAML files.

    For each step with a 'file' field, loads the referenced YAML and merges
    it with the step (preserving the step's 'id').

    Args:
        steps: List of step dicts from the routine YAML
        routine_dir: Directory of the routine file (for resolving relative paths)
        routine_path: Path of the root routine file (for circular reference detection)
        visited: Set of already-visited file paths (for circular reference detection)

    Returns:
        New list of step dicts with file references resolved

    Raises:
        RoutineValidationError: If a referenced file is missing or circular
        RoutineParseError: If a referenced step file has invalid YAML
    """
    resolved: list[Any] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict) or "file" not in raw_step:
            resolved.append(raw_step)
            continue

        step: dict[str, Any] = cast(dict[str, Any], raw_step)
        step_id: str = str(step.get("id", "<unknown>"))
        file_ref: str = str(step["file"])
        step_file: Path = (routine_dir / file_ref).resolve()

        # Circular reference detection
        if step_file in visited:
            raise RoutineValidationError(
                str(routine_path),
                [f"Step '{step_id}': circular reference detected for file '{file_ref}'"],
            )

        if not step_file.exists():
            raise RoutineValidationError(
                str(routine_path),
                [
                    f"Step '{step_id}': referenced file '{file_ref}' not found "
                    f"(resolved to '{step_file}')"
                ],
            )

        try:
            ext_content: str = step_file.read_text()
            ext_raw: Any = yaml.safe_load(ext_content)
        except yaml.YAMLError as e:
            raise RoutineParseError(str(step_file), str(e)) from e

        if ext_raw is None:
            raise RoutineParseError(str(step_file), "Empty file")

        if not isinstance(ext_raw, dict):
            raise RoutineValidationError(
                str(routine_path),
                [f"Step '{step_id}': referenced file '{file_ref}' must contain a YAML mapping"],
            )

        ext_data: dict[str, Any] = cast(dict[str, Any], ext_raw)

        # Handle optional 'step:' wrapper in external file
        if "step" in ext_data and len(ext_data) == 1:
            inner = ext_data["step"]
            if isinstance(inner, dict):
                ext_data = cast(dict[str, Any], inner)

        # Merge: external file provides full step definition; parent id takes precedence
        merged: dict[str, Any] = dict(ext_data)
        merged["id"] = step_id  # parent id always wins

        resolved.append(merged)

    return resolved


def load_routine_from_path(path: Path) -> RoutineConfig:
    """Load a routine from a YAML file.

    Steps with a 'file' field are resolved relative to the routine directory
    and assembled into the final RoutineConfig.

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

    # Resolve external step file references before validation
    if isinstance(data, dict) and "steps" in data and isinstance(data["steps"], list):
        routine_dir = path.parent
        visited: set[Path] = {path.resolve()}
        data["steps"] = _resolve_step_files(
            cast(list[Any], data["steps"]), routine_dir, path, visited
        )

    try:
        return RoutineConfig.model_validate(data)
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        raise RoutineValidationError(str(path), errors) from e
