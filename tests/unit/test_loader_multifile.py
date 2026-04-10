"""Tests for multi-file routine loading (step file references)."""

from pathlib import Path

import pytest

from orchestrator.config import (
    RoutineConfig,
    StepConfig,
    RoutineValidationError,
    load_routine_from_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_TASK = """\
tasks:
  - id: t1
    title: Task One
    task_context: Do the thing.
"""

_STEP_BODY = f"""\
title: External Step
{_MINIMAL_TASK}"""


def _write_routine_yaml(tmp_path: Path, steps_block: str) -> Path:
    """Write a minimal routine YAML whose steps section is steps_block."""
    routine_file = tmp_path / "routine.yaml"
    routine_file.write_text("id: test-routine\nname: Test Routine\nsteps:\n" + steps_block + "\n")
    return routine_file


def _write_step_file(directory: Path, filename: str, content: str) -> Path:
    step_file = directory / filename
    step_file.write_text(content)
    return step_file


# ---------------------------------------------------------------------------
# 1. Loader resolves step file references correctly
# ---------------------------------------------------------------------------


def test_file_reference_resolved(tmp_path: Path) -> None:
    """Step with file: field is replaced by the external file's content."""
    _write_step_file(tmp_path, "step_a.yaml", _STEP_BODY)

    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: step-a\n    file: step_a.yaml\n",
    )

    routine = load_routine_from_path(routine_file)

    assert isinstance(routine, RoutineConfig)
    assert len(routine.steps) == 1
    step = routine.steps[0]
    # id from parent routine takes precedence
    assert step.id == "step-a"
    assert step.title == "External Step"
    assert len(step.tasks) == 1
    assert step.tasks[0].id == "t1"


def test_file_reference_parent_id_wins(tmp_path: Path) -> None:
    """When external file also defines an id, the parent routine's id wins."""
    step_content = "id: inner-id\n" + _STEP_BODY
    _write_step_file(tmp_path, "step_b.yaml", step_content)

    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: outer-id\n    file: step_b.yaml\n",
    )

    routine = load_routine_from_path(routine_file)
    assert routine.steps[0].id == "outer-id"


def test_file_reference_with_step_wrapper(tmp_path: Path) -> None:
    """External files wrapped in a top-level 'step:' key are unwrapped."""
    step_content = "step:\n  title: Wrapped Step\n  " + _MINIMAL_TASK.replace("\n", "\n  ")
    _write_step_file(tmp_path, "wrapped.yaml", step_content)

    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: wrapped-step\n    file: wrapped.yaml\n",
    )

    routine = load_routine_from_path(routine_file)
    assert routine.steps[0].title == "Wrapped Step"


def test_file_reference_relative_path(tmp_path: Path) -> None:
    """Files in a subdirectory are resolved relative to the routine file."""
    sub = tmp_path / "steps"
    sub.mkdir()
    _write_step_file(sub, "deep.yaml", _STEP_BODY)

    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: deep-step\n    file: steps/deep.yaml\n",
    )

    routine = load_routine_from_path(routine_file)
    assert routine.steps[0].id == "deep-step"
    assert routine.steps[0].title == "External Step"


# ---------------------------------------------------------------------------
# 2. Missing step file raises RoutineValidationError
# ---------------------------------------------------------------------------


def test_missing_step_file_raises(tmp_path: Path) -> None:
    """Referencing a non-existent file raises RoutineValidationError."""
    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: missing-step\n    file: does_not_exist.yaml\n",
    )

    with pytest.raises(RoutineValidationError):
        load_routine_from_path(routine_file)


def test_missing_step_file_error_mentions_filename(tmp_path: Path) -> None:
    """Error message mentions the missing filename."""
    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: step-x\n    file: ghost.yaml\n",
    )

    with pytest.raises(RoutineValidationError, match="ghost.yaml"):
        load_routine_from_path(routine_file)


def test_missing_step_file_error_mentions_step_id(tmp_path: Path) -> None:
    """Error message mentions which step triggered the missing file."""
    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: broken-step\n    file: nope.yaml\n",
    )

    with pytest.raises(RoutineValidationError, match="broken-step"):
        load_routine_from_path(routine_file)


# ---------------------------------------------------------------------------
# 3. Step with file AND other fields raises RoutineValidationError
#
# The loader builds the merged step dict from the EXTERNAL file content.
# Overlap is detected at model-validation time when the external file itself
# contains a 'file' key alongside other step fields.
# ---------------------------------------------------------------------------


def test_step_model_rejects_file_and_title_together() -> None:
    """StepConfig rejects a dict that sets both 'file' and 'title'."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="file"):
        StepConfig.model_validate({"id": "s", "file": "ref.yaml", "title": "Conflict"})


def test_loader_rejects_external_file_with_file_and_title(tmp_path: Path) -> None:
    """If the external step file itself has file + title, validation fails.

    The loader uses the external file's content as the merged step dict.
    If that dict contains both 'file' and 'title', StepConfig raises.
    """
    # External step file has BOTH file and title — an invalid combination.
    _write_step_file(
        tmp_path,
        "bad_step.yaml",
        "file: another.yaml\ntitle: Should Not Be Here\n",
    )

    routine_file = _write_routine_yaml(
        tmp_path,
        "  - id: overlap-step\n    file: bad_step.yaml\n",
    )

    with pytest.raises(RoutineValidationError):
        load_routine_from_path(routine_file)


def test_step_model_rejects_file_and_tasks_together() -> None:
    """StepConfig rejects a dict that sets both 'file' and 'tasks'."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="file"):
        StepConfig.model_validate(
            {
                "id": "s",
                "file": "ref.yaml",
                "tasks": [{"id": "t1", "title": "T", "task_context": "ctx"}],
            }
        )


def test_step_model_rejects_file_and_step_context_together() -> None:
    """StepConfig rejects a dict that sets both 'file' and 'step_context'."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="file"):
        StepConfig.model_validate({"id": "s", "file": "ref.yaml", "step_context": "extra context"})


# ---------------------------------------------------------------------------
# 4. Inline steps (no file) work unchanged
# ---------------------------------------------------------------------------


def test_inline_step_no_file(tmp_path: Path) -> None:
    """Steps without file: field are loaded inline as before."""
    step_yaml = (
        "  - id: inline-step\n"
        "    title: Inline Step\n"
        "    tasks:\n"
        "      - id: t-inline\n"
        "        title: Inline Task\n"
        "        task_context: do the thing\n"
    )
    routine_file = _write_routine_yaml(tmp_path, step_yaml)

    routine = load_routine_from_path(routine_file)

    assert len(routine.steps) == 1
    assert routine.steps[0].id == "inline-step"
    assert routine.steps[0].title == "Inline Step"
    assert routine.steps[0].tasks[0].id == "t-inline"


def test_inline_multiple_steps(tmp_path: Path) -> None:
    """Multiple inline steps all load correctly."""
    step_yaml = (
        "  - id: step-one\n"
        "    title: Step One\n"
        "    tasks:\n"
        "      - id: ta\n"
        "        title: A\n"
        "        task_context: ctx\n"
        "  - id: step-two\n"
        "    title: Step Two\n"
        "    tasks:\n"
        "      - id: tb\n"
        "        title: B\n"
        "        task_context: ctx\n"
    )
    routine_file = _write_routine_yaml(tmp_path, step_yaml)

    routine = load_routine_from_path(routine_file)

    assert len(routine.steps) == 2
    assert routine.steps[0].id == "step-one"
    assert routine.steps[1].id == "step-two"


def test_inline_and_file_steps_together(tmp_path: Path) -> None:
    """Mix of inline and file-referenced steps all load correctly."""
    _write_step_file(tmp_path, "ext_step.yaml", _STEP_BODY)

    step_yaml = (
        "  - id: inline\n"
        "    title: Inline\n"
        "    tasks:\n"
        "      - id: t-a\n"
        "        title: Task A\n"
        "        task_context: ctx\n"
        "  - id: external\n"
        "    file: ext_step.yaml\n"
    )
    routine_file = _write_routine_yaml(tmp_path, step_yaml)

    routine = load_routine_from_path(routine_file)

    assert len(routine.steps) == 2
    assert routine.steps[0].id == "inline"
    assert routine.steps[0].title == "Inline"
    assert routine.steps[1].id == "external"
    assert routine.steps[1].title == "External Step"


# ---------------------------------------------------------------------------
# 5. Full routine load from multi-file structure
# ---------------------------------------------------------------------------


def test_full_multifile_routine(tmp_path: Path) -> None:
    """Complete routine where every step comes from a separate YAML file."""
    step1_content = """\
title: Step One
tasks:
  - id: task-1a
    title: First Task
    task_context: Do something meaningful.
  - id: task-1b
    title: Second Task
    task_context: Do something else.
"""
    step2_content = """\
title: Step Two
tasks:
  - id: task-2a
    title: Third Task
    task_context: Final task context.
"""
    _write_step_file(tmp_path, "step1.yaml", step1_content)
    _write_step_file(tmp_path, "step2.yaml", step2_content)

    routine_file = tmp_path / "routine.yaml"
    routine_file.write_text(
        "id: multi-file-routine\n"
        "name: Multi-File Routine\n"
        "steps:\n"
        "  - id: s1\n"
        "    file: step1.yaml\n"
        "  - id: s2\n"
        "    file: step2.yaml\n"
    )

    routine = load_routine_from_path(routine_file)

    assert isinstance(routine, RoutineConfig)
    assert routine.id == "multi-file-routine"
    assert len(routine.steps) == 2

    s1 = routine.steps[0]
    assert s1.id == "s1"
    assert s1.title == "Step One"
    assert len(s1.tasks) == 2
    assert s1.tasks[0].id == "task-1a"
    assert s1.tasks[1].id == "task-1b"

    s2 = routine.steps[1]
    assert s2.id == "s2"
    assert s2.title == "Step Two"
    assert len(s2.tasks) == 1
    assert s2.tasks[0].id == "task-2a"


def test_full_multifile_routine_with_inline_mix(tmp_path: Path) -> None:
    """Multi-file routine with a mix of file-ref and inline steps validates fully."""
    _write_step_file(
        tmp_path,
        "analysis.yaml",
        "title: Analysis Step\ntasks:\n  - id: analyze\n    title: Analyze\n    task_context: Analyze the codebase.\n",
    )

    routine_file = tmp_path / "main.yaml"
    routine_file.write_text(
        "id: mixed-routine\n"
        "name: Mixed Routine\n"
        "steps:\n"
        "  - id: setup\n"
        "    title: Setup\n"
        "    tasks:\n"
        "      - id: init\n"
        "        title: Initialize\n"
        "        task_context: Set up the environment.\n"
        "  - id: analysis\n"
        "    file: analysis.yaml\n"
    )

    routine = load_routine_from_path(routine_file)

    assert routine.id == "mixed-routine"
    assert len(routine.steps) == 2
    assert routine.steps[0].id == "setup"
    assert routine.steps[0].tasks[0].id == "init"
    assert routine.steps[1].id == "analysis"
    assert routine.steps[1].tasks[0].id == "analyze"
