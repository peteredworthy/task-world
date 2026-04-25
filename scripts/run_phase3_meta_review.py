#!/usr/bin/env python3
"""Run the phase-3 meta-review gate before wider rollout.

Phase 3 adds a deliberate reviewer between planning and execution. The reviewer
can reject broad or weak slice routines, require a revised routine, and emit
planner-tuning feedback after execution evidence is available.
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
DEFAULT_FEATURE = "phase3-meta-review-smoke"
DEFAULT_OUTPUT = "docs/large-tasks/phase-3-meta-review-results.json"
DEFAULT_REPORT = "docs/large-tasks/phase-3-meta-review-report.html"
DEFAULT_STATE = "docs/large-tasks/phase-3-meta-review-state.json"
DEFAULT_CANDIDATES_DIR = "docs/large-tasks/phase-3/candidates"
DEFAULT_LOCAL_WORKTREE = "docs/large-tasks/phase-3/local-worktree"
ReviewDecision = Literal["approve", "revise", "reject"]


@dataclass(frozen=True)
class MetaReview:
    review_number: int
    decision: ReviewDecision
    findings: list[str]
    required_changes: list[str]
    planner_tuning: list[str]
    incremental_score: int
    real_surface_score: int
    dead_code_risk_score: int
    bug_absent_detection: bool


@dataclass(frozen=True)
class CandidateRecord:
    review_number: int
    routine_id: str
    routine_path: str
    task_count: int
    validation_errors: list[str]
    review: MetaReview


@dataclass(frozen=True)
class ExecutionEvidence:
    routine_id: str
    status: str
    worktree_path: str
    evidence_files: list[str]
    elapsed_seconds: int
    notes: list[str]


@dataclass(frozen=True)
class Phase3Result:
    objective: str
    feature: str
    completed: bool
    stop_reason: str
    candidates: list[CandidateRecord]
    execution: ExecutionEvidence | None
    post_execution_review: MetaReview | None
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


def validate_routine(api_url: str, routine_yaml: str) -> list[str]:
    response = request_json(
        "POST",
        f"{api_url.rstrip('/')}/api/routines/validate",
        {"yaml_content": routine_yaml},
    )
    if response.get("valid") is True:
        return []
    errors = response.get("errors")
    if isinstance(errors, list):
        return [str(error) for error in errors]
    return ["Routine validation failed without structured errors"]


def count_tasks(routine: dict[str, Any]) -> int:
    steps = routine.get("steps")
    if not isinstance(steps, list):
        return 0
    count = 0
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("tasks"), list):
            count += len(step["tasks"])
    return count


def flatten_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True).lower()


def demo_candidate(review_number: int, feature: str, previous: MetaReview | None) -> dict[str, Any]:
    if previous is None:
        return {
            "id": "phase3-broad-unreviewed-candidate",
            "name": "Phase 3 Broad Candidate",
            "description": "Intentionally broad candidate used to prove meta-review rejection.",
            "steps": [
                {
                    "id": "S-01",
                    "title": "Build many areas",
                    "tasks": [
                        {
                            "id": "T-01",
                            "title": "Add helper checks",
                            "script": "mkdir -p docs/{feature} && echo helper > docs/{feature}/helper.txt".format(
                                feature=feature
                            ),
                            "requirements": [{"id": "R1", "desc": "Create helper-only checks."}],
                        },
                        {
                            "id": "T-02",
                            "title": "Draft follow-up area plan",
                            "script": "mkdir -p docs/{feature} && echo broad > docs/{feature}/broad.txt".format(
                                feature=feature
                            ),
                            "requirements": [{"id": "R1", "desc": "Plan multiple future areas."}],
                        },
                    ],
                }
            ],
        }

    script = (
        "mkdir -p docs/{feature} && "
        "printf '%s\\n' "
        "'approved: meta-review required a single bounded slice' "
        "'real_surface: local execution path writes observable evidence' "
        "'bug_absent: bug-not-found is an accepted stop outcome' "
        "'dead_code_guard: helper-only proof is insufficient' "
        "> docs/{feature}/approved-slice-evidence.txt"
    ).format(feature=feature)
    return {
        "id": "phase3-approved-meta-reviewed-slice",
        "name": "Phase 3 Approved Meta-Reviewed Slice",
        "description": "Single revised slice produced after reviewer feedback.",
        "steps": [
            {
                "id": "S-01",
                "title": "Execute reviewed slice",
                "step_context": "Run only the approved evidence slice after meta-review.",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Write reviewed evidence",
                        "script": script,
                        "requirements": [
                            {
                                "id": "R1",
                                "desc": "Prove a single bounded slice before wider rollout.",
                            },
                            {
                                "id": "R2",
                                "desc": "Name the real execution surface and produce observable evidence.",
                            },
                            {
                                "id": "R3",
                                "desc": "Treat bug not found as a valid stop or replan outcome.",
                            },
                            {
                                "id": "R4",
                                "desc": "Reject helper-only or dead-code verification as sufficient proof.",
                            },
                        ],
                    }
                ],
            }
        ],
    }


def demo_meta_review(
    *,
    review_number: int,
    routine: dict[str, Any],
    execution: ExecutionEvidence | None = None,
) -> MetaReview:
    text = flatten_text(routine)
    task_count = count_tasks(routine)
    findings: list[str] = []
    required_changes: list[str] = []
    planner_tuning: list[str] = []

    incremental_score = 5 if task_count <= 1 else 1
    real_surface_score = 5 if "real execution surface" in text or "real_surface" in text else 1
    bug_absent_detection = "bug not found" in text or "bug-not-found" in text
    dead_code_risk_score = 1 if "helper-only" in text and task_count > 1 else 5

    if task_count > 1:
        findings.append("Candidate contains multiple executable tasks before one slice is proven.")
        required_changes.append("Reduce the routine to one executable task.")
        planner_tuning.append(
            "Default uncertain work to one vertical slice until evidence supports fan-out."
        )
    if real_surface_score < 3:
        findings.append("Candidate does not name a real execution surface.")
        required_changes.append("Require a real surface check instead of helper-only evidence.")
        planner_tuning.append(
            "Make real-surface verification a hard gate in generated slice routines."
        )
    if not bug_absent_detection:
        findings.append("Candidate cannot detect bug-not-found as a valid outcome.")
        required_changes.append("Add an explicit bug-not-found stop/replan condition.")
        planner_tuning.append(
            "Planner should encode disconfirmation outcomes, not only success paths."
        )
    if dead_code_risk_score < 3:
        findings.append("Candidate has high dead-code or helper-only false-positive risk.")
        required_changes.append("Add a guard that helper-only proof is insufficient.")

    if execution is not None and execution.status == "completed" and execution.evidence_files:
        planner_tuning.append(
            "Post-run evidence supports promoting meta-review findings into the planner contract."
        )

    decision: ReviewDecision = "approve" if not required_changes else "revise"
    return MetaReview(
        review_number=review_number,
        decision=decision,
        findings=findings,
        required_changes=required_changes,
        planner_tuning=planner_tuning,
        incremental_score=incremental_score,
        real_surface_score=real_surface_score,
        dead_code_risk_score=dead_code_risk_score,
        bug_absent_detection=bug_absent_detection,
    )


def review_from_response(response: dict[str, Any], review_number: int) -> MetaReview:
    decision = response.get("decision")
    if decision not in ("approve", "revise", "reject"):
        raise RuntimeError("Reviewer decision must be approve, revise, or reject")
    return MetaReview(
        review_number=review_number,
        decision=cast(ReviewDecision, decision),
        findings=[str(item) for item in response.get("findings", [])],
        required_changes=[str(item) for item in response.get("required_changes", [])],
        planner_tuning=[str(item) for item in response.get("planner_tuning", [])],
        incremental_score=int(response.get("incremental_score", 0)),
        real_surface_score=int(response.get("real_surface_score", 0)),
        dead_code_risk_score=int(response.get("dead_code_risk_score", 0)),
        bug_absent_detection=bool(response.get("bug_absent_detection", False)),
    )


def run_local_execution(
    routine: dict[str, Any],
    feature: str,
    local_worktree: Path,
) -> ExecutionEvidence:
    started = time.monotonic()
    local_worktree.mkdir(parents=True, exist_ok=True)
    steps = routine.get("steps")
    task: dict[str, Any] | None = None
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        tasks = steps[0].get("tasks")
        if isinstance(tasks, list) and tasks and isinstance(tasks[0], dict):
            task = cast(dict[str, Any], tasks[0])
    if task is None or not isinstance(task.get("script"), str):
        raise RuntimeError("Approved routine must have a first script task")

    completed = subprocess.run(
        task["script"],
        cwd=local_worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        check=False,
    )
    feature_dir = local_worktree / "docs" / feature
    evidence_files = (
        [
            str(path.relative_to(local_worktree))
            for path in sorted(feature_dir.glob("**/*"))
            if path.is_file()
        ]
        if feature_dir.exists()
        else []
    )
    notes = [completed.stdout.strip()] if completed.stdout.strip() else []
    if completed.returncode != 0:
        notes.append(f"Local execution exited {completed.returncode}.")
    return ExecutionEvidence(
        routine_id=str(routine.get("id", "")),
        status="completed" if completed.returncode == 0 else "failed",
        worktree_path=str(local_worktree),
        evidence_files=evidence_files,
        elapsed_seconds=int(time.monotonic() - started),
        notes=notes,
    )


def compute_success_criteria(
    candidates: list[CandidateRecord],
    execution: ExecutionEvidence | None,
    post_execution_review: MetaReview | None,
) -> dict[str, bool]:
    approved = [candidate for candidate in candidates if candidate.review.decision == "approve"]
    revised = len(candidates) >= 2 and candidates[0].review.decision == "revise"
    first_score = candidates[0].review.incremental_score if candidates else 0
    last_score = candidates[-1].review.incremental_score if candidates else 0
    first_dead_code = candidates[0].review.dead_code_risk_score if candidates else 0
    last_dead_code = candidates[-1].review.dead_code_risk_score if candidates else 0
    return {
        "review_rejected_broad_candidate": revised,
        "approved_only_after_revision": bool(approved) and approved[0].review_number > 1,
        "review_converged_to_smaller_slice": last_score > first_score,
        "real_surface_gate_passed": bool(candidates)
        and candidates[-1].review.real_surface_score >= 4,
        "bug_absent_outcome_detectable": bool(candidates)
        and candidates[-1].review.bug_absent_detection,
        "dead_code_risk_reduced": last_dead_code > first_dead_code,
        "executed_only_approved_candidate": execution is not None
        and bool(approved)
        and execution.routine_id == approved[0].routine_id,
        "planner_tuning_emitted": post_execution_review is not None
        and bool(post_execution_review.planner_tuning),
        "ready_for_phase4": execution is not None
        and execution.status == "completed"
        and bool(execution.evidence_files)
        and post_execution_review is not None,
    }


def render_report(result: Phase3Result) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{candidate.review_number}</td>"
        f"<td><code>{html.escape(candidate.routine_id)}</code></td>"
        f"<td>{candidate.task_count}</td>"
        f"<td>{html.escape(candidate.review.decision)}</td>"
        f"<td>{candidate.review.incremental_score}</td>"
        f"<td>{candidate.review.real_surface_score}</td>"
        f"<td>{candidate.review.dead_code_risk_score}</td>"
        "</tr>"
        for candidate in result.candidates
    )
    criteria = "\n".join(
        f'<li><span class="{"pass" if passed else "fail"}">'
        f"{'PASS' if passed else 'FAIL'}</span> {html.escape(name.replace('_', ' '))}</li>"
        for name, passed in result.success_criteria.items()
    )
    findings = "\n".join(
        f"<li>Review {candidate.review_number}: "
        f"{html.escape('; '.join(candidate.review.findings) or 'approved with no findings')}</li>"
        for candidate in result.candidates
    )
    tuning = (
        "\n".join(
            f"<li>{html.escape(item)}</li>"
            for item in (
                result.post_execution_review.planner_tuning if result.post_execution_review else []
            )
        )
        or "<li>No tuning feedback recorded.</li>"
    )
    evidence = ", ".join(result.execution.evidence_files) if result.execution else "No execution"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Phase 3 Meta-Review Report</title>
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
    <h1>Phase 3 Meta-Review</h1>
    <p>{html.escape(result.objective)}</p>
    <p><strong>Result:</strong> {html.escape(result.stop_reason)}</p>
  </section>
  <section>
    <h2>Review Gate</h2>
    <table>
      <thead><tr><th>Review</th><th>Routine</th><th>Tasks</th><th>Decision</th><th>Incremental</th><th>Real Surface</th><th>Dead-Code Risk</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Findings</h2>
    <ul>{findings}</ul>
  </section>
  <section>
    <h2>Planner Tuning</h2>
    <ul>{tuning}</ul>
  </section>
  <section>
    <h2>Protocol Scope</h2>
    <p>The deterministic demo proves the review gate, revision loop, execution boundary, and persisted evidence. Production use should provide a strong external reviewer through the same JSON stdin/stdout command protocol.</p>
  </section>
  <section>
    <h2>Success Criteria</h2>
    <ul>{criteria}</ul>
    <p><strong>Evidence:</strong> {html.escape(evidence)}</p>
  </section>
</main>
</body>
</html>
"""


def write_state(path: Path, result: Phase3Result) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), indent=2) + "\n")


def run_phase3(args: argparse.Namespace) -> Phase3Result:
    candidates: list[CandidateRecord] = []
    previous_review: MetaReview | None = None
    approved_routine: dict[str, Any] | None = None
    candidates_dir = Path(args.candidates_dir)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    for review_number in range(1, args.max_reviews + 1):
        if args.demo:
            routine = demo_candidate(review_number, args.feature, previous_review)
        else:
            planner_response = run_json_command(
                args.planner_command,
                {
                    "objective": args.objective,
                    "feature": args.feature,
                    "review_number": review_number,
                    "previous_review": asdict(previous_review) if previous_review else None,
                },
                args.command_timeout,
            )
            raw_routine = planner_response.get("routine")
            if not isinstance(raw_routine, dict):
                raise RuntimeError("Planner response must include a routine object")
            routine = cast(dict[str, Any], raw_routine)

        routine_yaml = routine_to_yaml(routine)
        routine_path = candidates_dir / f"candidate-{review_number:02d}.yaml"
        routine_path.write_text(routine_yaml)
        validation_errors = validate_routine(args.api_url, routine_yaml)
        if validation_errors:
            raise RuntimeError(f"{routine_path} failed validation: {validation_errors}")

        if args.demo:
            review = demo_meta_review(review_number=review_number, routine=routine)
        else:
            response = run_json_command(
                args.reviewer_command,
                {
                    "objective": args.objective,
                    "feature": args.feature,
                    "review_number": review_number,
                    "routine": routine,
                    "previous_review": asdict(previous_review) if previous_review else None,
                },
                args.command_timeout,
            )
            review = review_from_response(response, review_number)

        record = CandidateRecord(
            review_number=review_number,
            routine_id=str(routine.get("id", "")),
            routine_path=str(routine_path),
            task_count=count_tasks(routine),
            validation_errors=validation_errors,
            review=review,
        )
        candidates.append(record)
        previous_review = review
        partial = Phase3Result(
            objective=args.objective,
            feature=args.feature,
            completed=False,
            stop_reason=f"Review {review_number} produced {review.decision}.",
            candidates=candidates,
            execution=None,
            post_execution_review=None,
            success_criteria={},
        )
        write_state(Path(args.state), partial)
        if review.decision == "approve":
            approved_routine = routine
            break
        if review.decision == "reject":
            break

    execution = (
        run_local_execution(approved_routine, args.feature, Path(args.local_worktree))
        if approved_routine is not None
        else None
    )
    if approved_routine is not None:
        post_execution_review = (
            demo_meta_review(
                review_number=len(candidates) + 1,
                routine=approved_routine,
                execution=execution,
            )
            if args.demo
            else review_from_response(
                run_json_command(
                    args.reviewer_command,
                    {
                        "objective": args.objective,
                        "feature": args.feature,
                        "review_number": len(candidates) + 1,
                        "routine": approved_routine,
                        "execution": asdict(execution) if execution else None,
                    },
                    args.command_timeout,
                ),
                len(candidates) + 1,
            )
        )
    else:
        post_execution_review = None

    criteria = compute_success_criteria(candidates, execution, post_execution_review)
    completed = all(criteria.values())
    stop_reason = (
        "Meta-review rejected a broad candidate, approved a revised slice, and emitted planner tuning."
        if completed
        else "Phase 3 meta-review did not satisfy all success criteria."
    )
    result = Phase3Result(
        objective=args.objective,
        feature=args.feature,
        completed=completed,
        stop_reason=stop_reason,
        candidates=candidates,
        execution=execution,
        post_execution_review=post_execution_review,
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
        default="Prove phase 3 meta-review before wider rollout.",
    )
    parser.add_argument("--max-reviews", type=int, default=3)
    parser.add_argument("--planner-command", default="")
    parser.add_argument("--reviewer-command", default="")
    parser.add_argument("--command-timeout", type=int, default=120)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--candidates-dir", default=DEFAULT_CANDIDATES_DIR)
    parser.add_argument("--local-worktree", default=DEFAULT_LOCAL_WORKTREE)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if not args.demo and (not args.planner_command or not args.reviewer_command):
        parser.error("--planner-command and --reviewer-command are required without --demo")

    result = run_phase3(args)
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
