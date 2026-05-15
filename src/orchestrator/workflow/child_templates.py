"""Compiled child workflow templates for super-parent oversight runs."""

from __future__ import annotations

import re
import shlex
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestrator.config import RoutineConfig


ChildWorkflowTemplateId = Literal[
    "bug_fix_with_regression_test",
    "test_coverage_gap",
    "frontend_behavior_fix",
    "investigation_only",
    "implementation_slice",
    "planning_to_implementation_brief",
    "partial_progress_recovery",
    "cleanup_refactor",
    "environment_blocker_repro",
]


_TEMPLATE_TITLES: dict[str, str] = {
    "bug_fix_with_regression_test": "Bug Fix With Regression Test",
    "test_coverage_gap": "Test Coverage Gap",
    "frontend_behavior_fix": "Frontend Behavior Fix",
    "investigation_only": "Investigation Only",
    "implementation_slice": "Narrow Implementation Slice",
    "planning_to_implementation_brief": "Planning To Implementation Brief",
    "partial_progress_recovery": "Partial Progress Recovery",
    "cleanup_refactor": "Cleanup Refactor",
    "environment_blocker_repro": "Environment Blocker Reproduction",
}

_TEMPLATE_REQUIREMENTS: dict[str, list[str]] = {
    "bug_fix_with_regression_test": [
        "Reproduce or attempt to reproduce the target behavior before changing code.",
        "Apply the smallest code change that addresses the target behavior.",
        "Add or update a regression test unless evidence shows the behavior is already covered.",
    ],
    "test_coverage_gap": [
        "Identify the production behavior the missing test should protect.",
        "Add focused test coverage without changing production behavior unless a real bug is found.",
    ],
    "frontend_behavior_fix": [
        "Exercise the real frontend path or document the environment blocker that prevents it.",
        "Apply the smallest UI or state-management change that addresses the target behavior.",
        "Verify the behavior through the configured frontend validation surface.",
    ],
    "investigation_only": [
        "Inspect the target area and answer the slice assumption with concrete evidence.",
        "Do not change source behavior unless the slice brief explicitly allows it.",
    ],
    "implementation_slice": [
        "Implement only the bounded behavior named by the slice goal.",
        "Keep edits inside one subsystem, API surface, or narrow file cluster.",
        "Run the focused verification surface named by the parent slice.",
    ],
    "planning_to_implementation_brief": [
        "Investigate the broad target enough to split it into one safe implementation slice.",
        "Write a child-authored implementation brief with scope, files, risks, and verification.",
        "Do not make production behavior changes while producing the brief.",
    ],
    "partial_progress_recovery": [
        "Inspect the current worktree state and identify what partial work exists.",
        "Package changed files, completed work, blockers, and recommended next steps for the parent.",
        "Do not continue broad implementation unless the slice explicitly narrows that recovery work.",
    ],
    "cleanup_refactor": [
        "Make the cleanup or refactor without changing externally visible behavior.",
        "Run a verification surface that would catch behavior drift in the touched area.",
    ],
    "environment_blocker_repro": [
        "Try the exact setup or reproduction path that may be blocked by the environment.",
        "Collect enough command output and context for the parent to classify the blocker.",
    ],
}


class ChildSliceSpec(BaseModel):
    """Compact parent-authored slice spec compiled into a child routine."""

    model_config = ConfigDict(extra="forbid")

    template_id: ChildWorkflowTemplateId
    slice_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    goal: str = Field(min_length=1)
    routine_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    title: str | None = Field(default=None, min_length=1)
    target_inventory_ids: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    expected_files_changed: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    evidence_expectations: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    real_execution_surface: str = Field(default="project validation", min_length=1)
    real_frontend_path_required: bool = False
    notes: str = ""
    max_attempts: int = Field(default=2, ge=1, le=4)

    @model_validator(mode="after")
    def _validate_paths_and_commands(self) -> "ChildSliceSpec":
        for path in self.allowed_paths + self.expected_files_changed:
            _reject_unsafe_path(path)
        for command in self.verification_commands:
            if not command.strip():
                raise ValueError("verification_commands entries must be non-empty")
        return self


def compile_child_routine_from_spec(spec: ChildSliceSpec | dict[str, object]) -> dict[str, object]:
    """Compile a compact child slice spec into a schema-valid embedded routine."""

    if not isinstance(spec, ChildSliceSpec):
        spec = ChildSliceSpec.model_validate(spec)

    routine_id = spec.routine_id or f"child-{spec.slice_id}"
    title = spec.title or _TEMPLATE_TITLES[spec.template_id]
    evidence_path = f"docs/run-evidence/{spec.slice_id}-evidence.json"
    planning_brief_path = f"docs/run-evidence/{spec.slice_id}-implementation-brief.md"
    recovery_summary_path = f"docs/run-evidence/{spec.slice_id}-recovery-summary.md"
    validation_code = (
        "import json; "
        "from pathlib import Path; "
        f"b=json.loads(Path('{evidence_path}').read_text()); "
        "req='schema_version slice_id routine_id assumption_tested summary commands_run "
        "test_results target_bug_reproduced real_frontend_path_exercised "
        "real_execution_surface files_changed evidence_files open_uncertainties "
        "next_recommendation outcome'.split(); "
        "missing=[k for k in req if k not in b]; "
        "assert not missing, missing; "
        "assert b['schema_version']=='run.evidence.v1'; "
        f"assert b['slice_id']=='{spec.slice_id}'; "
        f"assert b['routine_id']=='{routine_id}'; "
        "assert b['target_bug_reproduced'] in "
        "('reproduced','not_reproduced','not_targeted','unknown'); "
        "assert b['next_recommendation'] in "
        "('proceed','replan','stop','environment_blocked'); "
        "assert b['outcome'] in ('verified_fix','bug_not_reproduced',"
        "'behavior_already_correct','environment_blocked','needs_revision',"
        "'partial_progress','unrelated_failure'); "
        "assert all(isinstance(c,dict) and isinstance(c.get('command'),str) "
        "and isinstance(c.get('exit_code'),int) for c in b['commands_run']); "
        "assert all(isinstance(t,dict) and t.get('status') in "
        "('passed','failed','skipped','not_run') for t in b['test_results'])"
    )

    auto_verify_items: list[dict[str, object]] = [
        {
            "id": "evidence_bundle_schema",
            "cmd": f'uv run python -c "{validation_code}"',
            "must": True,
        }
    ]
    for index, command in enumerate(spec.verification_commands, start=1):
        _, shell_command = _command_label_and_shell(command, f"verification_{index}")
        auto_verify_items.append(
            {
                "id": f"slice_verification_{index}",
                "cmd": shell_command,
                "must": True,
            }
        )

    routine: dict[str, object] = {
        "id": routine_id,
        "name": f"{title}: {spec.slice_id}",
        "description": (
            "Generated child workflow from a compact super-parent slice spec. "
            "Do not promote this embedded routine to routines/ without human review."
        ),
        "strict_validation": True,
        "steps": _steps_for_spec(
            spec,
            routine_id=routine_id,
            title=title,
            evidence_path=evidence_path,
            planning_brief_path=planning_brief_path,
            recovery_summary_path=recovery_summary_path,
            auto_verify_items=auto_verify_items,
        ),
    }

    # Validate before returning so callers cannot create malformed child runs.
    RoutineConfig.model_validate(routine)
    return routine


def _steps_for_spec(
    spec: ChildSliceSpec,
    *,
    routine_id: str,
    title: str,
    evidence_path: str,
    planning_brief_path: str,
    recovery_summary_path: str,
    auto_verify_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    if spec.template_id == "planning_to_implementation_brief":
        return _planning_brief_steps(
            spec,
            routine_id=routine_id,
            evidence_path=evidence_path,
            planning_brief_path=planning_brief_path,
            auto_verify_items=auto_verify_items,
        )
    if spec.template_id == "partial_progress_recovery":
        return _partial_progress_recovery_steps(
            spec,
            routine_id=routine_id,
            evidence_path=evidence_path,
            recovery_summary_path=recovery_summary_path,
            auto_verify_items=auto_verify_items,
        )
    return [
        {
            "id": "CH-01",
            "title": title,
            "step_context": (
                "Complete the bounded child slice and return a compact, schema-valid "
                "run.evidence.v1 bundle for the parent."
            ),
            "tasks": [
                {
                    "id": "T-01",
                    "title": f"Execute {spec.slice_id}",
                    "task_context": _task_context(spec, routine_id, evidence_path),
                    "requirements": _requirements_for_spec(spec),
                    "artifacts": [{"path": evidence_path, "required": True}],
                    "auto_verify": {"items": auto_verify_items},
                    "retry": {"max_attempts": spec.max_attempts},
                }
            ],
        }
    ]


def _planning_brief_steps(
    spec: ChildSliceSpec,
    *,
    routine_id: str,
    evidence_path: str,
    planning_brief_path: str,
    auto_verify_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    brief_verify = {
        "id": "implementation_brief_exists",
        "cmd": f"test -f {planning_brief_path}",
        "must": True,
    }
    brief_requirements = [
        {
            "id": "R1",
            "desc": "Implementation brief narrows the broad item to one child-sized slice.",
            "priority": "critical",
        },
        {
            "id": "R2",
            "desc": "Brief names target files or subsystems, verification commands, risks, and stop conditions.",
            "priority": "critical",
        },
        {
            "id": "R3",
            "desc": "No production behavior changes are made while planning the next slice.",
            "priority": "critical",
        },
    ]
    evidence_requirements = _requirements_for_spec(spec)
    return [
        {
            "id": "CH-01",
            "title": "Investigate And Draft Brief",
            "step_context": (
                "Use this planning pass to shrink broad inventory into one concrete implementation "
                "slice for a later child."
            ),
            "tasks": [
                {
                    "id": "T-01",
                    "title": f"Plan {spec.slice_id}",
                    "task_context": _planning_brief_context(
                        spec,
                        routine_id=routine_id,
                        planning_brief_path=planning_brief_path,
                    ),
                    "requirements": brief_requirements,
                    "artifacts": [{"path": planning_brief_path, "required": True}],
                    "auto_verify": {"items": [brief_verify]},
                    "retry": {"max_attempts": spec.max_attempts},
                }
            ],
        },
        {
            "id": "CH-02",
            "title": "Package Planning Evidence",
            "step_context": (
                "Convert the implementation brief into parent-readable run.evidence.v1 evidence."
            ),
            "tasks": [
                {
                    "id": "T-01",
                    "title": f"Package {spec.slice_id} planning evidence",
                    "task_context": _task_context(spec, routine_id, evidence_path)
                    + (
                        "\n\nThis is a planning child. Reference "
                        f"`{planning_brief_path}` in `evidence_files`, set "
                        "`target_bug_reproduced` to `not_targeted`, and use an acceptance "
                        "outcome such as `behavior_already_correct` with "
                        "`next_recommendation` `proceed` when the brief is ready for the parent."
                    ),
                    "requirements": evidence_requirements,
                    "artifacts": [{"path": evidence_path, "required": True}],
                    "auto_verify": {"items": [brief_verify, *auto_verify_items]},
                    "retry": {"max_attempts": spec.max_attempts},
                }
            ],
        },
    ]


def _partial_progress_recovery_steps(
    spec: ChildSliceSpec,
    *,
    routine_id: str,
    evidence_path: str,
    recovery_summary_path: str,
    auto_verify_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    summary_verify = {
        "id": "recovery_summary_exists",
        "cmd": f"test -f {recovery_summary_path}",
        "must": True,
    }
    summary_requirements = [
        {
            "id": "R1",
            "desc": "Recovery summary lists changed files and what each change appears to do.",
            "priority": "critical",
        },
        {
            "id": "R2",
            "desc": "Summary separates completed work, unverified work, blockers, and recommended next action.",
            "priority": "critical",
        },
        {
            "id": "R3",
            "desc": "Recovery work does not broaden the original child slice.",
            "priority": "critical",
        },
    ]
    evidence_requirements = _requirements_for_spec(spec)
    return [
        {
            "id": "CH-01",
            "title": "Inspect Partial Work",
            "step_context": (
                "Recover child progress by summarizing the current worktree and blockers before "
                "the parent decides whether to resume, replan, or stop."
            ),
            "tasks": [
                {
                    "id": "T-01",
                    "title": f"Recover {spec.slice_id}",
                    "task_context": _partial_progress_recovery_context(
                        spec,
                        routine_id=routine_id,
                        recovery_summary_path=recovery_summary_path,
                    ),
                    "requirements": summary_requirements,
                    "artifacts": [{"path": recovery_summary_path, "required": True}],
                    "auto_verify": {"items": [summary_verify]},
                    "retry": {"max_attempts": spec.max_attempts},
                }
            ],
        },
        {
            "id": "CH-02",
            "title": "Package Recovery Evidence",
            "step_context": (
                "Write run.evidence.v1 evidence that communicates partial progress and next action."
            ),
            "tasks": [
                {
                    "id": "T-01",
                    "title": f"Package {spec.slice_id} recovery evidence",
                    "task_context": _task_context(spec, routine_id, evidence_path)
                    + (
                        "\n\nThis is a recovery child. Reference "
                        f"`{recovery_summary_path}` in `evidence_files`, set "
                        "`outcome` to `partial_progress` unless the recovery proves there is "
                        "no useful work, and set `next_recommendation` to `replan`, `stop`, "
                        "or `environment_blocked` based on the summary."
                    ),
                    "requirements": evidence_requirements,
                    "artifacts": [{"path": evidence_path, "required": True}],
                    "auto_verify": {"items": [summary_verify, *auto_verify_items]},
                    "retry": {"max_attempts": spec.max_attempts},
                }
            ],
        },
    ]


def _requirements_for_spec(spec: ChildSliceSpec) -> list[dict[str, object]]:
    template_requirements = list(_TEMPLATE_REQUIREMENTS[spec.template_id])
    common_requirements = [
        "Stay within the slice goal and allowed paths unless evidence requires a documented replan.",
        "Use scripts/run_child_evidence.py to run requested verification commands and keep the evidence bundle current, unless the helper itself is the documented blocker.",
        "Write a schema-valid run.evidence.v1 bundle with exact enum values and matching slice/routine IDs.",
    ]
    requirements = template_requirements + common_requirements
    return [
        {
            "id": f"R{index}",
            "desc": requirement,
            "priority": "critical",
        }
        for index, requirement in enumerate(requirements, start=1)
    ]


def _task_context(spec: ChildSliceSpec, routine_id: str, evidence_path: str) -> str:
    allowed_paths = _unique(["scripts/run_child_evidence.py", *spec.allowed_paths])
    sections = [
        f"Slice ID: {spec.slice_id}",
        f"Routine ID: {routine_id}",
        f"Goal: {spec.goal}",
        _format_list("Target inventory IDs", spec.target_inventory_ids),
        _format_list("Allowed paths", allowed_paths),
        _format_list("Expected files changed", spec.expected_files_changed),
        _format_list("Verification commands", spec.verification_commands),
        _evidence_helper_section(spec, routine_id, evidence_path),
        _format_list("Evidence expectations", spec.evidence_expectations),
        _format_list("Stop or replan conditions", spec.stop_conditions),
        f"Real execution surface: {spec.real_execution_surface}",
        f"Real frontend path required: {str(spec.real_frontend_path_required).lower()}",
    ]
    if spec.notes:
        sections.append(f"Parent notes: {spec.notes}")

    sections.append(
        "\nWrite the evidence bundle at "
        f"`{evidence_path}`. It must be JSON with schema_version `run.evidence.v1` "
        "and exact fields: slice_id, routine_id, assumption_tested, summary, commands_run, "
        "test_results, target_bug_reproduced, real_frontend_path_exercised, "
        "real_execution_surface, files_changed, evidence_files, open_uncertainties, "
        "next_recommendation, and outcome. commands_run entries are objects with command, "
        "exit_code, stdout_excerpt, and stderr_excerpt. test_results entries are objects "
        "with name, status, and details. Valid test status values are passed, failed, "
        "skipped, and not_run. Valid target_bug_reproduced values are reproduced, "
        "not_reproduced, not_targeted, and unknown. Valid next_recommendation values are "
        "proceed, replan, stop, and environment_blocked. Valid outcome values are "
        "verified_fix, bug_not_reproduced, behavior_already_correct, environment_blocked, "
        "needs_revision, partial_progress, and unrelated_failure."
    )
    sections.append(
        "After the evidence bundle is current and required verification commands have run, "
        "update every satisfied checklist item and submit the child task. Do not keep "
        "investigating after the slice assumption has enough evidence for the parent to review."
    )
    return "\n\n".join(section for section in sections if section)


def _planning_brief_context(
    spec: ChildSliceSpec,
    *,
    routine_id: str,
    planning_brief_path: str,
) -> str:
    allowed_paths = _unique(["scripts/run_child_evidence.py", *spec.allowed_paths])
    sections = [
        f"Slice ID: {spec.slice_id}",
        f"Routine ID: {routine_id}",
        f"Planning goal: {spec.goal}",
        _format_list("Target inventory IDs", spec.target_inventory_ids),
        _format_list("Allowed inspection paths", allowed_paths),
        _format_list("Evidence expectations", spec.evidence_expectations),
        _format_list("Stop or replan conditions", spec.stop_conditions),
        f"Real execution surface to preserve: {spec.real_execution_surface}",
        (
            "Write the implementation brief at "
            f"`{planning_brief_path}` with these exact headings: `Goal`, `Narrow Slice`, "
            "`Allowed Paths`, `Expected Files Changed`, `Verification Commands`, "
            "`Risks And Unknowns`, `Stop Conditions`, and `Suggested Child Template`. "
            "The narrow slice must be small enough for one implementation child and must name "
            "the recommended template_id for that child."
        ),
        (
            "Do not edit production code, tests, dependency files, lockfiles, migrations, UI files, "
            "or routine files in this planning task. The only required artifact is the brief."
        ),
    ]
    if spec.notes:
        sections.append(f"Parent notes: {spec.notes}")
    return "\n\n".join(section for section in sections if section)


def _partial_progress_recovery_context(
    spec: ChildSliceSpec,
    *,
    routine_id: str,
    recovery_summary_path: str,
) -> str:
    allowed_paths = _unique(["scripts/run_child_evidence.py", *spec.allowed_paths])
    sections = [
        f"Slice ID: {spec.slice_id}",
        f"Routine ID: {routine_id}",
        f"Recovery goal: {spec.goal}",
        _format_list("Target inventory IDs", spec.target_inventory_ids),
        _format_list("Allowed inspection paths", allowed_paths),
        _format_list("Expected files changed", spec.expected_files_changed),
        _format_list(
            "Verification commands to run only if still appropriate", spec.verification_commands
        ),
        _format_list("Evidence expectations", spec.evidence_expectations),
        _format_list("Stop or replan conditions", spec.stop_conditions),
        (
            "Write the recovery summary at "
            f"`{recovery_summary_path}` with these exact headings: `Observed Run State`, "
            "`Changed Files`, `Completed Work`, `Unverified Or Incomplete Work`, "
            "`Blockers`, `Recommended Next Action`, and `Suggested Follow-Up Slice`. "
            "Use `git status --porcelain` and targeted file inspection to populate it."
        ),
        (
            "Do not continue broad implementation. Make edits only when they are needed to package "
            "the recovery summary or when the slice explicitly authorizes a narrow completion step."
        ),
    ]
    if spec.notes:
        sections.append(f"Parent notes: {spec.notes}")
    return "\n\n".join(section for section in sections if section)


def _evidence_helper_section(spec: ChildSliceSpec, routine_id: str, evidence_path: str) -> str:
    if not spec.verification_commands:
        return (
            "Evidence helper: `scripts/run_child_evidence.py` is available if this slice gains "
            "verification commands while executing. Do not hand-roll command log capture when the "
            "helper can run the command and update the evidence bundle."
        )

    parts = [
        "uv",
        "run",
        "python",
        "scripts/run_child_evidence.py",
        "--slice-id",
        spec.slice_id,
        "--routine-id",
        routine_id,
        "--evidence-path",
        evidence_path,
        "--assumption",
        spec.goal,
        "--real-execution-surface",
        spec.real_execution_surface,
    ]
    if spec.real_frontend_path_required:
        parts.append("--real-frontend-path-exercised")
    for index, command in enumerate(spec.verification_commands, start=1):
        label, shell_command = _command_label_and_shell(command, f"verification_{index}")
        parts.extend(["--command", f"{label}::{shell_command}"])

    command_text = " ".join(shlex.quote(part) for part in parts)
    return (
        "Evidence helper:\n"
        "Run the requested verification surface through the helper instead of redirecting "
        "command output by hand and reading it back. The helper writes a valid evidence "
        "bundle before it starts, updates it after each command, writes per-command logs "
        "under `.evidence/`, and exits non-zero if any command fails.\n\n"
        "Suggested command:\n"
        f"```bash\n{command_text}\n```"
    )


def _format_list(label: str, values: list[str]) -> str:
    if not values:
        return f"{label}: none specified"
    return label + ":\n" + "\n".join(f"- {value}" for value in values)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _command_label_and_shell(command: str, default_label: str) -> tuple[str, str]:
    """Split optional evidence-helper labels from shell commands.

    Parent-authored slice specs sometimes pass commands as ``label::command``.
    The evidence helper accepts that form, but auto-verify must receive only the
    executable shell command. Raw commands remain supported and get a generated
    helper label.
    """
    label, separator, shell_command = command.partition("::")
    if separator and label and shell_command.strip() and re.fullmatch(r"[A-Za-z0-9_.:-]+", label):
        return label, shell_command.strip()
    return default_label, command.strip()


def _reject_unsafe_path(path: str) -> None:
    if not path.strip():
        raise ValueError("path entries must be non-empty")
    if path.startswith("/"):
        raise ValueError(f"path must be relative: {path}")
    if "\\" in path:
        raise ValueError(f"path must use forward slashes: {path}")
    if re.search(r"(^|/)\.\.(/|$)", path):
        raise ValueError(f"path must not traverse parent directories: {path}")
