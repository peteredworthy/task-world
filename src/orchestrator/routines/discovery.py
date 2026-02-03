"""Discover routines from directories."""

from dataclasses import dataclass
from pathlib import Path

from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import RoutineConfig
from orchestrator.routines.errors import RoutineError
from orchestrator.routines.loader import load_routine_from_path


@dataclass
class DiscoveredRoutine:
    """A routine discovered from a directory scan."""

    config: RoutineConfig
    source: RoutineSource
    path: Path


def discover_routines(
    directories: list[tuple[Path, RoutineSource]],
) -> list[DiscoveredRoutine]:
    """Scan directories for routine YAML files.

    Args:
        directories: List of (directory_path, source_type) tuples.

    Returns:
        List of DiscoveredRoutine for each valid routine found.
        Invalid files are silently skipped.
    """
    routines: list[DiscoveredRoutine] = []

    for directory, source in directories:
        if not directory.is_dir():
            continue

        for yaml_path in sorted(directory.glob("*.yaml")):
            try:
                config = load_routine_from_path(yaml_path)
                routines.append(DiscoveredRoutine(config=config, source=source, path=yaml_path))
            except RoutineError:
                continue

        for yml_path in sorted(directory.glob("*.yml")):
            try:
                config = load_routine_from_path(yml_path)
                routines.append(DiscoveredRoutine(config=config, source=source, path=yml_path))
            except RoutineError:
                continue

    return routines
