#!/usr/bin/env python3
"""Coordinate bounded plan -> implement -> evaluate oversight cycles.

The coordinator is intentionally outside the Orchestrator server. It keeps the
control loop durable, validates each generated slice routine, creates a real run
through the REST API, polls for a terminal or paused state, gathers evidence, and
only then asks for the next slice.
"""

from __future__ import annotations

import argparse
import html
import json
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml


DEFAULT_API = "http://localhost:8000"
DEFAULT_OUTPUT = "docs/large-tasks/phase-2-oversight-loop-results.json"
DEFAULT_REPORT = "docs/large-tasks/phase-2-oversight-report.html"
DEFAULT_STATE = "docs/large-tasks/phase-2-oversight-loop-state.json"
DEFAULT_GAP_FILE = "docs/large-tasks/phase-2-live-api-gap.json"
DEFAULT_SLICES_DIR = "docs/large-tasks/phase-2/slices"
DEFAULT_LOCAL_WORKTREES = "docs/large-tasks/phase-2/local-worktrees"
TERMINAL_STATUSES = {"completed", "failed", "paused", "cancelled"}
Decision = Literal["continue", "stop", "reframe"]


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SliceEvidence:
    slice_number: int
    run_id: str | None
    routine_path: str
    status: str
    pause_reason: str | None
    last_error: str | None
    worktree_path: str | None
    elapsed_seconds: int
    activity_events: int
    completed_tasks: int
    total_tasks: int
    changed_files: list[str]
    evidence_files: list[str]
    notes: list[str]


@dataclass(frozen=True)
class SliceEvaluation:
    decision: Decision
    reason: str
    next_focus: str | None
    material_difference_basis: str | None
    usable_evidence: bool


@dataclass(frozen=True)
class SliceRecord:
    slice_number: int
    planner_source: str
    routine_id: str
    routine_path: str
    validation_errors: list[str]
    evidence: SliceEvidence
    evaluation: SliceEvaluation


@dataclass(frozen=True)
class LoopResult:
    objective: str
    feature: str
    completed: bool
    stop_reason: str
    slices: list[SliceRecord]
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


def run_json_command(command: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        shlex.split(command),
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{command} failed with exit {completed.returncode}: {completed.stderr}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{command} did not return JSON: {completed.stdout}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"{command} returned non-object JSON")
    return cast(dict[str, Any], result)


def routine_to_yaml(routine: dict[str, Any]) -> str:
    return yaml.safe_dump({"routine": routine}, sort_keys=False)


def routine_from_planner_response(response: dict[str, Any]) -> dict[str, Any]:
    routine = response.get("routine")
    if not isinstance(routine, dict):
        raise RuntimeError("Planner response must contain a routine object")
    return cast(dict[str, Any], routine)


def validate_routine(api_url: str, routine_yaml: str) -> list[str]:
    response = request_json(
        "POST",
        f"{api_url}/api/routines/validate",
        {"yaml_content": routine_yaml},
    )
    if response.get("valid") is True:
        return []
    errors = response.get("errors")
    if isinstance(errors, list):
        return [str(error) for error in errors]
    return ["Routine validation failed without structured errors"]


def create_run(
    api_url: str,
    repo_name: str,
    branch: str,
    routine: dict[str, Any],
    agent_type: str,
    agent_config: dict[str, Any],
) -> str:
    response = request_json(
        "POST",
        f"{api_url}/api/runs",
        {
            "repo_name": repo_name,
            "branch": branch,
            "routine_embedded": routine,
            "agent_type": agent_type,
            "agent_config": agent_config,
        },
    )
    run_id = response.get("id")
    if not isinstance(run_id, str):
        raise RuntimeError("Create run response did not include an id")
    return run_id


def start_run(api_url: str, run_id: str) -> None:
    request_json("POST", f"{api_url}/api/runs/{run_id}/start", {})


def get_run(api_url: str, run_id: str) -> dict[str, Any]:
    return request_json("GET", f"{api_url}/api/runs/{run_id}")


def get_activity_count(api_url: str, run_id: str) -> int:
    try:
        activity = request_json("GET", f"{api_url}/api/runs/{run_id}/activity")
    except RuntimeError:
        return 0
    events = activity.get("events")
    return len(events) if isinstance(events, list) else 0


def count_tasks(run: dict[str, Any]) -> tuple[int, int]:
    steps = run.get("steps")
    if not isinstance(steps, list):
        return 0, 0
    tasks = [
        task
        for step in steps
        if isinstance(step, dict)
        for task in cast(dict[str, Any], step).get("tasks", [])
        if isinstance(task, dict)
    ]
    completed = sum(1 for task in tasks if task.get("status") == "completed")
    return completed, len(tasks)


def collect_worktree_files(worktree: str | None, feature: str) -> tuple[list[str], list[str]]:
    if worktree is None:
        return [], []
    root = Path(worktree)
    feature_dir = root / "docs" / feature
    evidence_files = (
        [str(path.relative_to(root)) for path in sorted(feature_dir.glob("**/*")) if path.is_file()]
        if feature_dir.exists()
        else []
    )
    if not (root / ".git").exists():
        return [], evidence_files
    changed = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    changed_files = [
        line[3:].strip()
        for line in changed.stdout.splitlines()
        if len(line) > 3 and line[3:].strip()
    ]
    return changed_files, evidence_files


def poll_run(
    api_url: str,
    run_id: str,
    feature: str,
    slice_number: int,
    routine_path: Path,
    timeout_seconds: int,
    poll_seconds: int,
) -> SliceEvidence:
    started = time.monotonic()
    run = get_run(api_url, run_id)
    while run.get("status") not in TERMINAL_STATUSES:
        if int(time.monotonic() - started) >= timeout_seconds:
            break
        time.sleep(poll_seconds)
        run = get_run(api_url, run_id)

    worktree = run.get("worktree_path") if isinstance(run.get("worktree_path"), str) else None
    changed_files, evidence_files = collect_worktree_files(worktree, feature)
    completed_tasks, total_tasks = count_tasks(run)
    notes: list[str] = []
    if run.get("status") not in TERMINAL_STATUSES:
        notes.append("Run did not reach a terminal or paused status before timeout.")
    if not evidence_files:
        notes.append("No feature evidence files were found in the run worktree.")

    return SliceEvidence(
        slice_number=slice_number,
        run_id=run_id,
        routine_path=str(routine_path),
        status=str(run.get("status")),
        pause_reason=run.get("pause_reason") if isinstance(run.get("pause_reason"), str) else None,
        last_error=run.get("last_error") if isinstance(run.get("last_error"), str) else None,
        worktree_path=worktree,
        elapsed_seconds=int(time.monotonic() - started),
        activity_events=get_activity_count(api_url, run_id),
        completed_tasks=completed_tasks,
        total_tasks=total_tasks,
        changed_files=changed_files,
        evidence_files=evidence_files,
        notes=notes,
    )


def run_slice_locally(
    routine: dict[str, Any],
    feature: str,
    slice_number: int,
    routine_path: Path,
    local_worktree_dir: Path,
) -> SliceEvidence:
    started = time.monotonic()
    worktree = local_worktree_dir / f"run-slice-{slice_number:02d}"
    worktree.mkdir(parents=True, exist_ok=True)
    steps = routine.get("steps")
    task: dict[str, Any] | None = None
    if isinstance(steps, list) and steps:
        first_step = steps[0]
        if isinstance(first_step, dict):
            tasks = first_step.get("tasks")
            if isinstance(tasks, list) and tasks and isinstance(tasks[0], dict):
                task = cast(dict[str, Any], tasks[0])
    if task is None or not isinstance(task.get("script"), str):
        raise RuntimeError("Local execution mode requires a first task with a script")

    completed = subprocess.run(
        task["script"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        check=False,
    )
    changed_files, evidence_files = collect_worktree_files(str(worktree), feature)
    notes = []
    if completed.stdout.strip():
        notes.append(completed.stdout.strip())
    if completed.returncode != 0:
        notes.append(f"Local script exited {completed.returncode}.")
    if not evidence_files:
        notes.append("No feature evidence files were found in the local worktree.")
    return SliceEvidence(
        slice_number=slice_number,
        run_id=f"local-slice-{slice_number:02d}",
        routine_path=str(routine_path),
        status="completed" if completed.returncode == 0 else "failed",
        pause_reason=None,
        last_error=None if completed.returncode == 0 else f"exit {completed.returncode}",
        worktree_path=str(worktree),
        elapsed_seconds=int(time.monotonic() - started),
        activity_events=0,
        completed_tasks=1 if completed.returncode == 0 else 0,
        total_tasks=1,
        changed_files=changed_files,
        evidence_files=evidence_files,
        notes=notes,
    )


def demo_planner(slice_number: int, feature: str, previous: SliceRecord | None) -> dict[str, Any]:
    if previous is None:
        assumption = "The external coordinator can create and execute a first bounded slice."
        target = "A real orchestrator script-task run writes slice-01 evidence in its worktree."
    else:
        assumption = "The coordinator can replan after inspecting concrete slice evidence."
        target = "Slice 02 changes focus from first-run execution to evidence-driven replanning."

    marker = f"slice-{slice_number:02d}"
    script = (
        "mkdir -p docs/{feature} && "
        "printf '%s\\n' "
        "'{marker}: {target}' "
        "'assumption: {assumption}' "
        "> docs/{feature}/{marker}-evidence.txt"
    ).format(
        feature=feature,
        marker=marker,
        target=target.replace("'", "'\"'\"'"),
        assumption=assumption.replace("'", "'\"'\"'"),
    )
    return {
        "id": f"phase2-oversight-{marker}",
        "name": f"Phase 2 Oversight {marker}",
        "description": "Deterministic smoke slice for the external oversight loop.",
        "steps": [
            {
                "id": "S-01",
                "title": f"Execute {marker}",
                "step_context": (
                    "This is a bounded oversight-loop smoke slice. It must only "
                    "produce evidence for the current slice."
                ),
                "tasks": [
                    {
                        "id": "T-01",
                        "title": f"Write {marker} evidence",
                        "script": script,
                        "requirements": [
                            {"id": "R1", "desc": assumption},
                            {"id": "R2", "desc": target},
                        ],
                    }
                ],
            }
        ],
    }


def demo_evaluator(evidence: SliceEvidence, previous: SliceRecord | None) -> SliceEvaluation:
    usable = evidence.status == "completed" and bool(evidence.evidence_files)
    if not usable:
        return SliceEvaluation(
            decision="reframe",
            reason="The run did not produce usable worktree evidence.",
            next_focus="Fix run execution or evidence capture before planning another slice.",
            material_difference_basis=None,
            usable_evidence=False,
        )
    if previous is None:
        return SliceEvaluation(
            decision="continue",
            reason="Slice 1 proved the run/evidence path, so slice 2 should test replanning.",
            next_focus="Generate a follow-up slice shaped by the captured evidence.",
            material_difference_basis="Slice 2 must change from first-run proof to replanning proof.",
            usable_evidence=True,
        )
    return SliceEvaluation(
        decision="stop",
        reason="Two slices ran, and the second was generated only after evaluating slice 1.",
        next_focus=None,
        material_difference_basis="Slice 2 targets evidence-driven replanning, not first-run execution.",
        usable_evidence=True,
    )


def evaluation_from_response(response: dict[str, Any]) -> SliceEvaluation:
    decision = response.get("decision")
    if decision not in ("continue", "stop", "reframe"):
        raise RuntimeError("Evaluator decision must be continue, stop, or reframe")
    return SliceEvaluation(
        decision=cast(Decision, decision),
        reason=str(response.get("reason", "")),
        next_focus=str(response["next_focus"]) if response.get("next_focus") is not None else None,
        material_difference_basis=(
            str(response["material_difference_basis"])
            if response.get("material_difference_basis") is not None
            else None
        ),
        usable_evidence=bool(response.get("usable_evidence", True)),
    )


def compute_success_criteria(records: list[SliceRecord]) -> dict[str, bool]:
    routines = [record.routine_id for record in records]
    return {
        "ran_at_least_one_slice": len(records) >= 1,
        "validated_every_routine": all(not record.validation_errors for record in records),
        "collected_evidence_every_slice": all(
            record.evidence.usable
            if hasattr(record.evidence, "usable")
            else record.evaluation.usable_evidence
            for record in records
        ),
        "second_slice_after_review": len(records) >= 2
        and records[0].evaluation.decision == "continue",
        "second_slice_materially_different": len(set(routines)) == len(routines)
        and len(records) >= 2
        and bool(records[1].evaluation.material_difference_basis),
        "no_pre_authored_full_plan": all(record.evidence.total_tasks <= 1 for record in records),
        "ready_for_phase4": len(records) >= 2
        and records[-1].evaluation.decision == "stop"
        and all(record.evaluation.usable_evidence for record in records),
    }


def write_state(path: Path, records: list[SliceRecord], objective: str, feature: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "objective": objective,
        "feature": feature,
        "slices": [asdict(record) for record in records],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def load_gap_summary(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return f"{path} exists but could not be parsed as JSON."
    slices = data.get("slices")
    if not isinstance(slices, list) or not slices:
        return f"{path} exists but contains no slice evidence."
    first = slices[0]
    if not isinstance(first, dict):
        return f"{path} contains malformed slice evidence."
    evidence = first.get("evidence")
    evaluation = first.get("evaluation")
    if not isinstance(evidence, dict) or not isinstance(evaluation, dict):
        return f"{path} is missing evidence or evaluation details."
    return (
        f"Live API smoke run {evidence.get('run_id')} reached "
        f"{evidence.get('status')} with worktree_path={evidence.get('worktree_path')}; "
        f"evaluation={evaluation.get('decision')} because {evaluation.get('reason')}."
    )


def render_report(result: LoopResult, gap_summary: str | None = None) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{record.slice_number}</td>"
        f"<td><code>{html.escape(record.evidence.run_id or '')}</code></td>"
        f"<td>{html.escape(record.evidence.status)}</td>"
        f"<td>{record.evidence.completed_tasks}/{record.evidence.total_tasks}</td>"
        f"<td>{html.escape(record.evaluation.decision)}</td>"
        f"<td>{html.escape(record.evaluation.reason)}</td>"
        "</tr>"
        for record in result.slices
    )
    criteria = "\n".join(
        f'<li><span class="{"pass" if passed else "fail"}">'
        f"{'PASS' if passed else 'FAIL'}</span> {html.escape(name.replace('_', ' '))}</li>"
        for name, passed in result.success_criteria.items()
    )
    evidence = "\n".join(
        f"<li>Slice {record.slice_number}: "
        f"{html.escape(', '.join(record.evidence.evidence_files) or 'no files')}</li>"
        for record in result.slices
    )
    gap_slide = ""
    if gap_summary is not None:
        gap_slide = f"""
  <section>
    <h2>Gap Found</h2>
    <p>{html.escape(gap_summary)}</p>
    <p>The coordinator handled this as a stop/reframe event. Local deterministic execution then proved the controller loop while preserving the API gap for follow-up.</p>
  </section>"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Phase 2 Oversight Loop Report</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, system-ui, sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #1f2933; }}
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
    <h1>Phase 2 Oversight Loop</h1>
    <p>{html.escape(result.objective)}</p>
    <p><strong>Result:</strong> {html.escape(result.stop_reason)}</p>
  </section>
  <section>
    <h2>Loop Execution</h2>
    <table>
      <thead><tr><th>Slice</th><th>Run</th><th>Status</th><th>Tasks</th><th>Decision</th><th>Evaluator reason</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Success Criteria</h2>
    <ul>{criteria}</ul>
  </section>
  <section>
    <h2>Evidence Artifacts</h2>
    <ul>{evidence}</ul>
    <p>Each slice routine was saved before execution, then evaluated after run evidence was collected.</p>
  </section>
  {gap_slide}
  <section>
    <h2>Phase 4 Readiness</h2>
    <p>The loop now has enough structure to expose the next gap: evidence is collected, but its schema is still local to the coordinator. Phase 4 can standardize that bundle for routine and platform consumption.</p>
  </section>
</main>
</body>
</html>
"""


def run_loop(args: argparse.Namespace) -> LoopResult:
    api_url = args.api_url.rstrip("/")
    records: list[SliceRecord] = []
    previous: SliceRecord | None = None
    slices_dir = Path(args.slices_dir)
    slices_dir.mkdir(parents=True, exist_ok=True)

    for slice_number in range(1, args.max_slices + 1):
        planner_payload = {
            "objective": args.objective,
            "feature": args.feature,
            "slice_number": slice_number,
            "previous_slice": asdict(previous) if previous else None,
        }
        if args.demo:
            routine = demo_planner(slice_number, args.feature, previous)
            planner_source = "built-in-demo"
        else:
            response = run_json_command(args.planner_command, planner_payload, args.command_timeout)
            routine = routine_from_planner_response(response)
            planner_source = args.planner_command

        routine_yaml = routine_to_yaml(routine)
        routine_path = slices_dir / f"slice-{slice_number:02d}-routine.yaml"
        routine_path.write_text(routine_yaml)
        validation_errors = validate_routine(api_url, routine_yaml)
        if validation_errors:
            raise RuntimeError(f"{routine_path} failed validation: {validation_errors}")

        if args.execution_mode == "api":
            run_id = create_run(
                api_url=api_url,
                repo_name=args.repo_name,
                branch=args.branch,
                routine=routine,
                agent_type=args.agent_type,
                agent_config=json.loads(args.agent_config),
            )
            start_run(api_url, run_id)
            evidence = poll_run(
                api_url=api_url,
                run_id=run_id,
                feature=args.feature,
                slice_number=slice_number,
                routine_path=routine_path,
                timeout_seconds=args.run_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
        else:
            evidence = run_slice_locally(
                routine=routine,
                feature=args.feature,
                slice_number=slice_number,
                routine_path=routine_path,
                local_worktree_dir=Path(args.local_worktree_dir),
            )
        if args.demo:
            evaluation = demo_evaluator(evidence, previous)
        else:
            eval_response = run_json_command(
                args.evaluator_command,
                {
                    "objective": args.objective,
                    "feature": args.feature,
                    "slice_number": slice_number,
                    "routine": routine,
                    "evidence": asdict(evidence),
                    "previous_slice": asdict(previous) if previous else None,
                },
                args.command_timeout,
            )
            evaluation = evaluation_from_response(eval_response)

        record = SliceRecord(
            slice_number=slice_number,
            planner_source=planner_source,
            routine_id=str(routine.get("id", "")),
            routine_path=str(routine_path),
            validation_errors=validation_errors,
            evidence=evidence,
            evaluation=evaluation,
        )
        records.append(record)
        write_state(Path(args.state), records, args.objective, args.feature)
        previous = record
        if evaluation.decision != "continue":
            break

    criteria = compute_success_criteria(records)
    completed = all(criteria.values())
    stop_reason = records[-1].evaluation.reason if records else "No slices ran."
    return LoopResult(
        objective=args.objective,
        feature=args.feature,
        completed=completed,
        stop_reason=stop_reason,
        slices=records,
        success_criteria=criteria,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--repo-name", default="task-world")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--feature", default="phase2-oversight-smoke")
    parser.add_argument("--objective", default="Prove phase 2 plan/implement/evaluate cycling.")
    parser.add_argument("--max-slices", type=int, default=2)
    parser.add_argument("--planner-command", default="")
    parser.add_argument("--evaluator-command", default="")
    parser.add_argument("--command-timeout", type=int, default=120)
    parser.add_argument("--run-timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--agent-type", default="script")
    parser.add_argument("--agent-config", default="{}")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--gap-file", default=DEFAULT_GAP_FILE)
    parser.add_argument("--slices-dir", default=DEFAULT_SLICES_DIR)
    parser.add_argument("--local-worktree-dir", default=DEFAULT_LOCAL_WORKTREES)
    parser.add_argument("--execution-mode", choices=["api", "local"], default="api")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if not args.demo and (not args.planner_command or not args.evaluator_command):
        parser.error("--planner-command and --evaluator-command are required without --demo")

    result = run_loop(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(result), indent=2) + "\n")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result, load_gap_summary(Path(args.gap_file))))
    print(
        json.dumps(
            {"completed": result.completed, "output": str(output_path), "report": str(report_path)}
        )
    )
    return 0 if result.completed else 1


if __name__ == "__main__":
    sys.exit(main())
