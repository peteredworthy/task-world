#!/usr/bin/env python3
"""Standardize oversight-loop evidence bundles for phase 4.

Phase 4 keeps the solution at the convention/script layer. The coordinator
validates each slice routine through the Orchestrator API when available,
executes deterministic demo slices locally, validates their JSON evidence
bundles, classifies the outcome, and writes durable results for the next
planning cycle.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


DEFAULT_API = "http://localhost:8000"
DEFAULT_FEATURE = "phase4-evidence-standardization-smoke"
DEFAULT_OUTPUT = "docs/large-tasks/phase-4-evidence-standardization-results.json"
DEFAULT_REPORT = "docs/large-tasks/phase-4-evidence-standardization-report.html"
DEFAULT_STATE = "docs/large-tasks/phase-4-evidence-standardization-state.json"
DEFAULT_SLICES_DIR = "docs/large-tasks/phase-4/slices"
DEFAULT_LOCAL_WORKTREE = "docs/large-tasks/phase-4/local-worktree"
DEFAULT_SCHEMA_DOC = "docs/large-tasks/phase-4/evidence-bundle-schema.md"

BugStatus = Literal["reproduced", "not_reproduced", "not_targeted", "unknown"]
Recommendation = Literal["proceed", "replan", "stop", "environment_blocked"]
Outcome = Literal["verified_fix", "bug_not_reproduced", "environment_blocked", "needs_revision"]
RoutineValidationStatus = Literal["valid", "invalid", "api_unavailable"]


class CommandEvidence(BaseModel):
    command: str = Field(min_length=1)
    exit_code: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""


class TestEvidence(BaseModel):
    name: str = Field(min_length=1)
    status: Literal["passed", "failed", "skipped", "not_run"]
    details: str = ""


class EvidenceBundle(BaseModel):
    schema_version: Literal["phase4.evidence.v1"]
    slice_id: str = Field(min_length=1)
    routine_id: str = Field(min_length=1)
    assumption_tested: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    commands_run: list[CommandEvidence] = Field(min_length=1)
    test_results: list[TestEvidence] = Field(min_length=1)
    target_bug_reproduced: BugStatus
    real_frontend_path_exercised: bool
    real_execution_surface: str = Field(min_length=1)
    files_changed: list[str]
    evidence_files: list[str]
    open_uncertainties: list[str]
    next_recommendation: Recommendation
    outcome: Outcome

    @field_validator("files_changed", "evidence_files", "open_uncertainties")
    @classmethod
    def no_empty_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("list items must be non-empty strings")
        return value


@dataclass(frozen=True)
class RoutineValidation:
    status: RoutineValidationStatus
    errors: list[str]


@dataclass(frozen=True)
class SliceResult:
    slice_id: str
    routine_id: str
    routine_path: str
    validation: RoutineValidation
    evidence_path: str
    bundle: dict[str, Any] | None
    outcome: Outcome | None
    valid_bundle: bool
    evaluation_notes: list[str]


@dataclass(frozen=True)
class OrchestratorExecutionEvidence:
    run_id: str | None
    status: str
    pause_reason: str | None
    worktree_path: str | None
    evidence_files: list[str]
    activity_events: int
    notes: list[str]


@dataclass(frozen=True)
class Phase4Result:
    objective: str
    feature: str
    completed: bool
    stop_reason: str
    schema_doc: str
    slices: list[SliceResult]
    orchestrator_execution: OrchestratorExecutionEvidence | None
    success_criteria: dict[str, bool]


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return cast(dict[str, Any], json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def routine_to_yaml(routine: dict[str, Any]) -> str:
    return yaml.safe_dump({"routine": routine}, sort_keys=False)


def validate_routine(api_url: str, routine_yaml: str) -> RoutineValidation:
    try:
        response = request_json(
            "POST",
            f"{api_url.rstrip('/')}/api/routines/validate",
            {"yaml_content": routine_yaml},
        )
    except RuntimeError as exc:
        return RoutineValidation(status="api_unavailable", errors=[str(exc)])
    if response.get("valid") is True:
        return RoutineValidation(status="valid", errors=[])
    errors = response.get("errors")
    if isinstance(errors, list):
        return RoutineValidation(status="invalid", errors=[str(error) for error in errors])
    return RoutineValidation(status="invalid", errors=["Routine validation failed."])


def evidence_payload(
    *,
    feature: str,
    slice_id: str,
    routine_id: str,
    assumption: str,
    summary: str,
    target_bug_reproduced: BugStatus,
    real_frontend_path_exercised: bool,
    real_execution_surface: str,
    probe_command: str,
    probe_exit_code: int,
    probe_stdout: str,
    probe_stderr: str,
    files_changed: list[str],
    open_uncertainties: list[str],
    next_recommendation: Recommendation,
    outcome: Outcome,
) -> dict[str, Any]:
    evidence_file = f"docs/{feature}/{slice_id}-evidence.json"
    return {
        "schema_version": "phase4.evidence.v1",
        "slice_id": slice_id,
        "routine_id": routine_id,
        "assumption_tested": assumption,
        "summary": summary,
        "commands_run": [
            {
                "command": probe_command,
                "exit_code": probe_exit_code,
                "stdout_excerpt": probe_stdout,
                "stderr_excerpt": probe_stderr,
            }
        ],
        "test_results": [
            {
                "name": "phase4 evidence contract",
                "status": "passed" if outcome != "environment_blocked" else "skipped",
                "details": "Validated by phase 4 schema.",
            }
        ],
        "target_bug_reproduced": target_bug_reproduced,
        "real_frontend_path_exercised": real_frontend_path_exercised,
        "real_execution_surface": real_execution_surface,
        "files_changed": files_changed,
        "evidence_files": [evidence_file],
        "open_uncertainties": open_uncertainties,
        "next_recommendation": next_recommendation,
        "outcome": outcome,
    }


def demo_specs(feature: str) -> list[dict[str, Any]]:
    return [
        evidence_payload(
            feature=feature,
            slice_id="slice-01-verified-fix",
            routine_id="phase4-verified-fix",
            assumption="A completed slice can prove a fix with a standard evidence bundle.",
            summary="The target behavior passed on the real execution surface.",
            target_bug_reproduced="reproduced",
            real_frontend_path_exercised=False,
            real_execution_surface="Local slice worktree filesystem probe",
            probe_command=(
                "test -f docs/phase4-evidence-standardization-smoke/"
                "slice-01-verified-fix-target.txt && printf '%s\\n' 'target artifact exists'"
            ),
            probe_exit_code=0,
            probe_stdout="target artifact exists",
            probe_stderr="",
            files_changed=[
                "routines/phase4-verified-fix.sh",
                "docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-target.txt",
                "docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-evidence.json",
            ],
            open_uncertainties=[],
            next_recommendation="proceed",
            outcome="verified_fix",
        ),
        evidence_payload(
            feature=feature,
            slice_id="slice-02-bug-not-reproduced",
            routine_id="phase4-bug-not-reproduced",
            assumption="A slice can stop cleanly when the target bug is not reproduced.",
            summary="The reported bug was not reproduced on the named real surface.",
            target_bug_reproduced="not_reproduced",
            real_frontend_path_exercised=False,
            real_execution_surface="Local slice worktree filesystem probe",
            probe_command=(
                "test ! -f docs/phase4-evidence-standardization-smoke/"
                "slice-02-bug-not-reproduced-present.txt && "
                "printf '%s\\n' 'reported bug marker absent'"
            ),
            probe_exit_code=0,
            probe_stdout="reported bug marker absent",
            probe_stderr="",
            files_changed=[
                "routines/phase4-bug-not-reproduced.sh",
                "docs/phase4-evidence-standardization-smoke/slice-02-bug-not-reproduced-evidence.json",
            ],
            open_uncertainties=["Need reporter environment details before implementation."],
            next_recommendation="stop",
            outcome="bug_not_reproduced",
        ),
        evidence_payload(
            feature=feature,
            slice_id="slice-03-environment-blocked",
            routine_id="phase4-environment-blocked",
            assumption="A slice can preserve environment failures without mislabeling them as fixes.",
            summary="The browser surface could not run, so the result is blocked.",
            target_bug_reproduced="unknown",
            real_frontend_path_exercised=False,
            real_execution_surface="Local browser-runtime availability probe",
            probe_command=(
                "test -x .phase4/browser-runtime || "
                "{ printf '%s\\n' 'browser runtime marker missing' >&2; false; }"
            ),
            probe_exit_code=1,
            probe_stdout="",
            probe_stderr="browser runtime marker missing",
            files_changed=[
                "routines/phase4-environment-blocked.sh",
                "docs/phase4-evidence-standardization-smoke/slice-03-environment-blocked-evidence.json",
            ],
            open_uncertainties=["Install or expose the browser runtime before replanning."],
            next_recommendation="environment_blocked",
            outcome="environment_blocked",
        ),
    ]


def routine_for_bundle(bundle: dict[str, Any], feature: str) -> dict[str, Any]:
    slice_id = str(bundle["slice_id"])
    routine_id = str(bundle["routine_id"])
    evidence_file = f"docs/{feature}/{slice_id}-evidence.json"
    target_file = f"docs/{feature}/{slice_id}-target.txt"
    probe = bundle["commands_run"][0]
    expected_exit = int(probe["exit_code"])
    probe_command = str(probe["command"])
    stdout_excerpt = str(probe["stdout_excerpt"])
    stderr_excerpt = str(probe["stderr_excerpt"])
    setup_command = (
        f"mkdir -p docs/{feature} && printf '%s\\n' 'target artifact exists' > {target_file}"
        if slice_id == "slice-01-verified-fix"
        else f"mkdir -p docs/{feature}"
    )
    payload = json.dumps(bundle, indent=2)
    script = (
        "mkdir -p routines docs/{feature} && "
        "cat > routines/{routine_id}.sh <<'SH'\n"
        "#!/bin/sh\n"
        "set -u\n"
        "{setup_command}\n"
        "probe_command={probe_command}\n"
        "probe_stdout={stdout_excerpt}\n"
        "probe_stderr={stderr_excerpt}\n"
        'eval "$probe_command"\n'
        "probe_exit=$?\n"
        'if [ "$probe_exit" -ne {expected_exit} ]; then\n'
        "  printf '%s\\n' \"unexpected probe exit $probe_exit for $probe_command\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "cat > {evidence_file} <<'JSON'\n"
        "{payload}\n"
        "JSON\n"
        "SH\n"
        "sh routines/{routine_id}.sh"
    ).format(
        feature=feature,
        routine_id=routine_id,
        setup_command=setup_command,
        probe_command=json.dumps(probe_command),
        stdout_excerpt=json.dumps(stdout_excerpt),
        stderr_excerpt=json.dumps(stderr_excerpt),
        expected_exit=expected_exit,
        evidence_file=evidence_file,
        payload=payload,
    )
    return {
        "id": routine_id,
        "name": f"Phase 4 Evidence {slice_id}",
        "description": "Deterministic slice proving the phase 4 evidence bundle contract.",
        "steps": [
            {
                "id": "S-01",
                "title": "Write standard evidence bundle",
                "step_context": "Produce one standard evidence bundle for the current slice.",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Persist evidence JSON",
                        "script": script,
                        "requirements": [
                            {
                                "id": "R1",
                                "desc": "Write a phase4.evidence.v1 JSON evidence bundle.",
                            },
                            {
                                "id": "R2",
                                "desc": "Classify the slice outcome for the next planner.",
                            },
                        ],
                    }
                ],
            }
        ],
    }


def extract_first_script(routine: dict[str, Any]) -> str:
    steps = routine.get("steps")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        tasks = steps[0].get("tasks")
        if isinstance(tasks, list) and tasks and isinstance(tasks[0], dict):
            script = tasks[0].get("script")
            if isinstance(script, str):
                return script
    raise RuntimeError("Routine must include a first script task")


def classify_bundle(bundle: EvidenceBundle) -> tuple[Outcome, list[str]]:
    notes: list[str] = []
    if bundle.outcome == "verified_fix":
        if any(result.status != "passed" for result in bundle.test_results):
            notes.append("Verified fixes require passing test results.")
        if bundle.next_recommendation != "proceed":
            notes.append("Verified fixes should recommend proceeding.")
        if any(command.exit_code != 0 for command in bundle.commands_run):
            notes.append("Verified fixes require successful command evidence.")
    elif bundle.outcome == "bug_not_reproduced":
        if bundle.target_bug_reproduced != "not_reproduced":
            notes.append("Bug-not-reproduced outcomes must set target_bug_reproduced.")
        if bundle.next_recommendation not in ("stop", "replan"):
            notes.append("Bug-not-reproduced outcomes should stop or replan.")
    elif bundle.outcome == "environment_blocked":
        if bundle.real_frontend_path_exercised:
            notes.append("Environment-blocked outcomes cannot claim real-path execution.")
        if bundle.next_recommendation != "environment_blocked":
            notes.append("Environment-blocked outcomes must recommend environment_blocked.")
    else:
        notes.append("Needs-revision evidence is not phase-4 ready.")

    required_context = [
        bundle.assumption_tested,
        bundle.summary,
        bundle.real_execution_surface,
    ]
    if not all(item.strip() for item in required_context):
        notes.append("Bundle is missing planner-consumable context.")
    return bundle.outcome if not notes else "needs_revision", notes


def execute_routine(
    routine: dict[str, Any],
    *,
    feature: str,
    local_worktree: Path,
    expected_evidence_name: str,
) -> tuple[Path, list[str]]:
    script = extract_first_script(routine)
    started = time.monotonic()
    if local_worktree.exists():
        shutil.rmtree(local_worktree)
    local_worktree.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        script,
        cwd=local_worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        check=False,
    )
    notes = [completed.stdout.strip()] if completed.stdout.strip() else []
    if completed.returncode != 0:
        raise RuntimeError(f"Local execution exited {completed.returncode}: {completed.stdout}")
    notes.append(f"Local execution elapsed {int(time.monotonic() - started)} seconds.")
    evidence_path = local_worktree / "docs" / feature / expected_evidence_name
    if not evidence_path.exists():
        raise RuntimeError(f"Routine did not write expected evidence file: {evidence_path}")
    return evidence_path, notes


def load_and_evaluate_bundle(
    evidence_path: Path,
) -> tuple[EvidenceBundle | None, Outcome | None, list[str]]:
    try:
        raw = json.loads(evidence_path.read_text())
    except json.JSONDecodeError as exc:
        return None, None, [f"Evidence JSON parse failed: {exc}"]
    try:
        bundle = EvidenceBundle.model_validate(raw)
    except ValidationError as exc:
        return None, None, [str(exc)]
    outcome, notes = classify_bundle(bundle)
    return bundle, outcome, notes


def load_orchestrator_execution(
    run_path: Path | None,
    activity_path: Path | None,
    feature: str,
) -> OrchestratorExecutionEvidence | None:
    if run_path is None:
        return None
    run = json.loads(run_path.read_text())
    activity_events = 0
    if activity_path is not None and activity_path.exists():
        activity = json.loads(activity_path.read_text())
        events = activity.get("events")
        activity_events = len(events) if isinstance(events, list) else 0
    worktree = run.get("worktree_path") if isinstance(run.get("worktree_path"), str) else None
    evidence_files: list[str] = []
    if worktree is not None:
        feature_dir = Path(worktree) / "docs" / feature
        if feature_dir.exists():
            evidence_files = [
                str(path.relative_to(worktree))
                for path in sorted(feature_dir.glob("*-evidence.json"))
                if path.is_file()
            ]
    notes: list[str] = []
    if run.get("status") != "completed":
        notes.append("Orchestrator run did not complete.")
    if not evidence_files:
        notes.append("No evidence bundle was produced in the orchestrator worktree.")
    return OrchestratorExecutionEvidence(
        run_id=str(run.get("id")) if run.get("id") is not None else None,
        status=str(run.get("status")),
        pause_reason=str(run["pause_reason"]) if run.get("pause_reason") is not None else None,
        worktree_path=worktree,
        evidence_files=evidence_files,
        activity_events=activity_events,
        notes=notes,
    )


def compute_success_criteria(
    slices: list[SliceResult],
    orchestrator_execution: OrchestratorExecutionEvidence | None,
) -> dict[str, bool]:
    outcomes = {slice_result.outcome for slice_result in slices}
    orchestrator_execution_completed = (
        orchestrator_execution is not None
        and orchestrator_execution.status == "completed"
        and bool(orchestrator_execution.evidence_files)
    )
    return {
        "standard_schema_documented": True,
        "every_bundle_valid": all(slice_result.valid_bundle for slice_result in slices),
        "planner_context_present": all(
            slice_result.bundle is not None
            and bool(slice_result.bundle.get("assumption_tested"))
            and bool(slice_result.bundle.get("summary"))
            and bool(slice_result.bundle.get("next_recommendation"))
            for slice_result in slices
        ),
        "verified_fix_distinguishable": "verified_fix" in outcomes,
        "bug_not_reproduced_distinguishable": "bug_not_reproduced" in outcomes,
        "environment_blocked_distinguishable": "environment_blocked" in outcomes,
        "orchestrator_validation_passed": all(
            slice_result.validation.status == "valid" for slice_result in slices
        ),
        "orchestrator_execution_completed": orchestrator_execution_completed,
        "ready_for_phase5": bool(slices)
        and all(slice_result.valid_bundle for slice_result in slices)
        and all(slice_result.validation.status == "valid" for slice_result in slices)
        and orchestrator_execution_completed
        and {"verified_fix", "bug_not_reproduced", "environment_blocked"}.issubset(outcomes),
    }


def schema_doc() -> str:
    return """# Phase 4 Evidence Bundle Schema

Every oversight-loop slice should write one JSON evidence bundle using
`schema_version: phase4.evidence.v1`.

Required planner-facing fields:

- `assumption_tested`: the assumption this slice was designed to test.
- `summary`: concise result of the slice.
- `commands_run`: commands and exit codes used as evidence.
- `test_results`: pass/fail/skip/not-run records.
- `target_bug_reproduced`: `reproduced`, `not_reproduced`, `not_targeted`, or `unknown`.
- `real_frontend_path_exercised`: whether the real user-facing path ran.
- `real_execution_surface`: the actual surface checked, not a helper-only proxy.
- `files_changed`: changed files relevant to the slice.
- `evidence_files`: artifacts a reviewer or next planner can inspect.
- `open_uncertainties`: remaining unknowns.
- `next_recommendation`: `proceed`, `replan`, `stop`, or `environment_blocked`.
- `outcome`: `verified_fix`, `bug_not_reproduced`, `environment_blocked`, or `needs_revision`.

The next planner should consume this bundle directly before authoring the next
slice. `verified_fix`, `bug_not_reproduced`, and `environment_blocked` are
distinct outcomes and must not be collapsed into a generic pass/fail summary.
"""


def render_report(result: Phase4Result) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(slice_result.slice_id)}</td>"
        f"<td><code>{html.escape(slice_result.routine_id)}</code></td>"
        f"<td>{html.escape(slice_result.validation.status)}</td>"
        f"<td>{html.escape(str(slice_result.outcome or 'none'))}</td>"
        f"<td>{'yes' if slice_result.valid_bundle else 'no'}</td>"
        "</tr>"
        for slice_result in result.slices
    )
    criteria = "\n".join(
        f'<li><span class="{"pass" if passed else "fail"}">'
        f"{'PASS' if passed else 'FAIL'}</span> {html.escape(name.replace('_', ' '))}</li>"
        for name, passed in result.success_criteria.items()
    )
    files = "\n".join(
        f"<li>{html.escape(slice_result.evidence_path)}</li>" for slice_result in result.slices
    )
    if result.orchestrator_execution is None:
        orchestrator = "<p>No orchestrator execution evidence was attached.</p>"
    else:
        notes = "\n".join(
            f"<li>{html.escape(note)}</li>" for note in result.orchestrator_execution.notes
        )
        evidence = ", ".join(result.orchestrator_execution.evidence_files) or "none"
        orchestrator = (
            f"<p><strong>Run:</strong> <code>{html.escape(result.orchestrator_execution.run_id or '')}</code></p>"
            f"<p><strong>Status:</strong> {html.escape(result.orchestrator_execution.status)}"
            f" / {html.escape(result.orchestrator_execution.pause_reason or '')}</p>"
            f"<p><strong>Worktree:</strong> {html.escape(result.orchestrator_execution.worktree_path or '')}</p>"
            f"<p><strong>Evidence files in worktree:</strong> {html.escape(evidence)}</p>"
            f"<ul>{notes}</ul>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Phase 4 Evidence Standardization Report</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, system-ui, sans-serif; }}
    body {{ margin: 0; background: #f7f8fa; color: #1f2933; }}
    main {{ scroll-snap-type: y mandatory; height: 100vh; overflow-y: auto; }}
    section {{ min-height: 100vh; scroll-snap-align: start; padding: 8vh 10vw; box-sizing: border-box; }}
    h1 {{ font-size: 56px; margin: 0 0 24px; letter-spacing: 0; }}
    h2 {{ font-size: 40px; margin: 0 0 24px; letter-spacing: 0; }}
    p, li, td, th {{ font-size: 20px; line-height: 1.45; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d9dee7; }}
    th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #e6e9ef; vertical-align: top; }}
    code {{ font-size: 16px; }}
    .kicker {{ color: #4b5563; font-size: 18px; text-transform: uppercase; letter-spacing: 0.08em; }}
    .pass {{ color: #0f766e; font-weight: 700; }}
    .fail {{ color: #b91c1c; font-weight: 700; }}
  </style>
</head>
<body>
<main>
  <section>
    <p class="kicker">Large Task Delivery</p>
    <h1>Phase 4 Evidence Standardization</h1>
    <p>{html.escape(result.objective)}</p>
    <p><strong>Result:</strong> {html.escape(result.stop_reason)}</p>
  </section>
  <section>
    <h2>Standard Contract</h2>
    <p>Each slice now emits one JSON bundle with the tested assumption, commands, test results, real execution surface, file changes, uncertainties, next recommendation, and outcome classification.</p>
    <p><strong>Schema:</strong> {html.escape(result.schema_doc)}</p>
  </section>
  <section>
    <h2>Demo Slices</h2>
    <table>
      <thead><tr><th>Slice</th><th>Routine</th><th>Routine validation</th><th>Outcome</th><th>Valid bundle</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Outcome Separation</h2>
    <p>The same schema distinguishes verified fix, bug not reproduced, and environment blocked. The next planner can branch from these fields without rereading the full run log.</p>
    <ul>{files}</ul>
  </section>
  <section>
    <h2>Success Criteria</h2>
    <ul>{criteria}</ul>
  </section>
  <section>
    <h2>Orchestrator Execution</h2>
    {orchestrator}
  </section>
  <section>
    <h2>Phase 5 Readiness</h2>
    <p>The evidence schema is stable, but Phase 5 is only ready once an orchestrator run completes and produces this bundle in its run worktree.</p>
  </section>
</main>
</body>
</html>
"""


def write_state(path: Path, result: Phase4Result) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), indent=2) + "\n")


def run_phase4(args: argparse.Namespace) -> Phase4Result:
    slices_dir = Path(args.slices_dir)
    slices_dir.mkdir(parents=True, exist_ok=True)
    local_worktree = Path(args.local_worktree)
    schema_path = Path(args.schema_doc)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(schema_doc())

    slice_results: list[SliceResult] = []
    for index, bundle_spec in enumerate(demo_specs(args.feature), start=1):
        routine = routine_for_bundle(bundle_spec, args.feature)
        routine_yaml = routine_to_yaml(routine)
        routine_path = slices_dir / f"slice-{index:02d}-routine.yaml"
        routine_path.write_text(routine_yaml)
        validation = validate_routine(args.api_url, routine_yaml)
        if validation.status == "invalid":
            raise RuntimeError(f"{routine_path} failed validation: {validation.errors}")

        evidence_path, execution_notes = execute_routine(
            routine,
            feature=args.feature,
            local_worktree=local_worktree / f"run-slice-{index:02d}",
            expected_evidence_name=f"{bundle_spec['slice_id']}-evidence.json",
        )
        bundle, outcome, evaluation_notes = load_and_evaluate_bundle(evidence_path)
        notes = execution_notes + evaluation_notes
        slice_results.append(
            SliceResult(
                slice_id=str(bundle_spec["slice_id"]),
                routine_id=str(bundle_spec["routine_id"]),
                routine_path=str(routine_path),
                validation=validation,
                evidence_path=str(evidence_path),
                bundle=bundle.model_dump() if bundle is not None else None,
                outcome=outcome,
                valid_bundle=bundle is not None and outcome == bundle.outcome,
                evaluation_notes=notes,
            )
        )

        partial = Phase4Result(
            objective=args.objective,
            feature=args.feature,
            completed=False,
            stop_reason=f"Recorded {index} standardized evidence bundle(s).",
            schema_doc=str(schema_path),
            slices=slice_results,
            orchestrator_execution=None,
            success_criteria={},
        )
        write_state(Path(args.state), partial)

    orchestrator_execution = load_orchestrator_execution(
        Path(args.orchestrator_run_json) if args.orchestrator_run_json else None,
        Path(args.orchestrator_activity_json) if args.orchestrator_activity_json else None,
        args.feature,
    )
    criteria = compute_success_criteria(slice_results, orchestrator_execution)
    completed = all(criteria.values())
    stop_reason = (
        "Evidence bundles are standardized, validated, and distinguish the required outcomes."
        if completed
        else "Evidence schema is standardized, but orchestrator execution is not yet proven."
    )
    result = Phase4Result(
        objective=args.objective,
        feature=args.feature,
        completed=completed,
        stop_reason=stop_reason,
        schema_doc=str(schema_path),
        slices=slice_results,
        orchestrator_execution=orchestrator_execution,
        success_criteria=criteria,
    )
    write_state(Path(args.state), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--feature", default=DEFAULT_FEATURE)
    parser.add_argument(
        "--objective",
        default="Prove phase 4 standardized evidence before native orchestration.",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--slices-dir", default=DEFAULT_SLICES_DIR)
    parser.add_argument("--local-worktree", default=DEFAULT_LOCAL_WORKTREE)
    parser.add_argument("--schema-doc", default=DEFAULT_SCHEMA_DOC)
    parser.add_argument("--orchestrator-run-json", default="")
    parser.add_argument("--orchestrator-activity-json", default="")
    args = parser.parse_args()

    result = run_phase4(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(result), indent=2) + "\n")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result))
    print(
        json.dumps(
            {"completed": result.completed, "output": str(output_path), "report": str(report_path)}
        )
    )
    return 0 if result.completed else 1


if __name__ == "__main__":
    sys.exit(main())
