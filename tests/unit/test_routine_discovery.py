"""Tests for routine discovery, including project-local routines."""

from pathlib import Path

from orchestrator.config import discover_routines, RoutineSource

VALID_ROUTINE_YAML = """\
routine:
  id: "proj-routine"
  name: "Project Routine"
  steps:
    - id: "S1"
      title: "Step 1"
      tasks:
        - id: "T1"
          title: "Task 1"
          task_context: "Do something"
          requirements:
            - id: "R1"
              desc: "Requirement"
"""

SHARED_ROUTINE_YAML = """\
routine:
  id: "shared-routine"
  name: "Shared"
  steps:
    - id: "S1"
      title: "Step"
      tasks:
        - id: "T1"
          title: "Task"
          task_context: "Context"
          requirements:
            - id: "R1"
              desc: "Req"
"""


def test_discover_project_routines(tmp_path: Path) -> None:
    """Project-local routines are discovered with PROJECT source."""
    routines_dir = tmp_path / "routines"
    routines_dir.mkdir()
    routine_yaml = routines_dir / "test.yaml"
    routine_yaml.write_text(VALID_ROUTINE_YAML)

    found = discover_routines([(routines_dir, RoutineSource.PROJECT)])
    assert len(found) == 1
    assert found[0].source == RoutineSource.PROJECT
    assert found[0].config.id == "proj-routine"
    assert found[0].config.name == "Project Routine"
    assert found[0].path == routine_yaml


def test_project_routines_alongside_local(tmp_path: Path) -> None:
    """When same routine ID exists in both local and project, both are returned (project listed after local)."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    (local_dir / "shared.yaml").write_text(SHARED_ROUTINE_YAML)
    (project_dir / "shared.yaml").write_text(SHARED_ROUTINE_YAML)

    found = discover_routines(
        [
            (local_dir, RoutineSource.LOCAL),
            (project_dir, RoutineSource.PROJECT),
        ]
    )
    assert len(found) == 2
    assert found[0].source == RoutineSource.LOCAL
    assert found[1].source == RoutineSource.PROJECT


def test_project_source_enum_value() -> None:
    """RoutineSource.PROJECT has the expected string value."""
    assert RoutineSource.PROJECT.value == "project"


def test_discover_project_routines_empty_dir(tmp_path: Path) -> None:
    """Empty project routines directory returns no routines."""
    routines_dir = tmp_path / "routines"
    routines_dir.mkdir()

    found = discover_routines([(routines_dir, RoutineSource.PROJECT)])
    assert len(found) == 0


def test_discover_project_routines_nonexistent_dir(tmp_path: Path) -> None:
    """Nonexistent project directory is silently skipped."""
    nonexistent = tmp_path / "does-not-exist"

    found = discover_routines([(nonexistent, RoutineSource.PROJECT)])
    assert len(found) == 0


def test_discover_mixed_sources_ordering(tmp_path: Path) -> None:
    """Routines from multiple sources maintain directory ordering."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    local_yaml = """\
routine:
  id: "local-only"
  name: "Local Only"
  steps:
    - id: "S1"
      title: "Step"
      tasks:
        - id: "T1"
          title: "Task"
          task_context: "Context"
          requirements:
            - id: "R1"
              desc: "Req"
"""
    project_yaml = """\
routine:
  id: "project-only"
  name: "Project Only"
  steps:
    - id: "S1"
      title: "Step"
      tasks:
        - id: "T1"
          title: "Task"
          task_context: "Context"
          requirements:
            - id: "R1"
              desc: "Req"
"""

    (local_dir / "local.yaml").write_text(local_yaml)
    (project_dir / "project.yaml").write_text(project_yaml)

    found = discover_routines(
        [
            (local_dir, RoutineSource.LOCAL),
            (project_dir, RoutineSource.PROJECT),
        ]
    )
    assert len(found) == 2
    assert found[0].config.id == "local-only"
    assert found[0].source == RoutineSource.LOCAL
    assert found[1].config.id == "project-only"
    assert found[1].source == RoutineSource.PROJECT
