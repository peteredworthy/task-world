#!/usr/bin/env python3
"""Evaluate the phase-1 incremental oversight planning contract.

This script is intentionally read-only. It gathers evidence from:
- the orchestrator API for the failed reference run
- the generated UI-QA planning artifacts
- the current idea-to-plan YAML routine

It writes an HTML report so a later agent or human can resume from concrete
evidence instead of a long-lived model session.
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_RUN_ID = "349cc782-43e4-4c46-a199-34a887a25856"
DEFAULT_API = "http://localhost:8000"
DEFAULT_OUTPUT = "docs/large-tasks/phase-1-oversight-report.html"
DEFAULT_SMOKE_RESULTS = "docs/large-tasks/phase-1-orchestrator-smoke-results.json"
REQUIRED_OVERSIGHT_TERMS = [
    "Planning mode: incremental oversight",
    "Assumption Under Test",
    "Target Behavior Or Missing Proof",
    "Real Verification Surface",
    "Stop Or Replan Conditions",
    "Evidence Artifacts",
]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class CommandEvidence:
    command: str
    cwd: str
    exit_code: int | None
    timed_out: bool
    output_excerpt: str


def fetch_json(url: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")), None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, str(exc)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse as a mapping")
    return data


def count_tasks_in_steps(step_dir: Path) -> int:
    count = 0
    for path in sorted(step_dir.glob("*.yaml")):
        data = load_yaml(path)
        step = data.get("step", data)
        tasks = step.get("tasks", [])
        if isinstance(tasks, list):
            count += len(tasks)
    return count


def summarize_run(run: dict[str, Any] | None) -> dict[str, Any]:
    if run is None:
        return {}
    steps = run.get("steps") or []
    tasks = [task for step in steps for task in step.get("tasks", [])]
    return {
        "status": run.get("status"),
        "pause_reason": run.get("pause_reason"),
        "last_error": run.get("last_error"),
        "step_count": len(steps),
        "task_count": len(tasks),
        "completed_tasks": sum(1 for task in tasks if task.get("status") == "completed"),
        "building_tasks": sum(1 for task in tasks if task.get("status") == "building"),
        "total_actions": run.get("total_num_actions"),
        "total_duration_ms": run.get("total_duration_ms"),
        "worktree_path": run.get("worktree_path"),
    }


def run_command(command: list[str], cwd: Path, timeout: int = 45) -> CommandEvidence:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        output = completed.stdout
        return CommandEvidence(
            command=" ".join(command),
            cwd=str(cwd),
            exit_code=completed.returncode,
            timed_out=False,
            output_excerpt=tail(output, 80),
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return CommandEvidence(
            command=" ".join(command),
            cwd=str(cwd),
            exit_code=None,
            timed_out=True,
            output_excerpt=tail(output, 80),
        )


def tail(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def extract_planning_failure_evidence(repo: Path) -> dict[str, Any]:
    verification = (repo / "docs/UI-QA/verification-report.md").read_text()
    dry_run = (repo / "docs/UI-QA/dry-run-notes.md").read_text()
    run_bdd = (repo / "worktrees/r82/ui/tests/bdd/run-bdd.mjs").read_text()
    package_json = json.loads((repo / "worktrees/r82/ui/package.json").read_text())
    bdd_features = sorted((repo / "worktrees/r82/ui/tests/bdd/features").glob("*.feature"))
    generated_specs = sorted((repo / "worktrees/r82/ui/tests/bdd/.feature-gen").glob("*.spec.ts"))
    known_issue_count = sum(path.read_text().count("@known-issue") for path in bdd_features)
    must_false_mentions = verification.count("must: false")
    return {
        "verification_status": "Ready to implement"
        if "Ready to implement" in verification
        else "not ready",
        "must_false_mentions": must_false_mentions,
        "quality_note_present": "several are must:false" in verification,
        "dry_run_recommended_no_core_changes": dry_run.count("No changes")
        + dry_run.count("No changes."),
        "feature_file_count": len(bdd_features),
        "generated_spec_count": len(generated_specs),
        "known_issue_count": known_issue_count,
        "test_bdd_script": package_json.get("scripts", {}).get("test:bdd", ""),
        "fallback_runner_present": "Playwright launch failed" in run_bdd
        and "runFallbackHarness" in run_bdd,
        "fallback_can_return_success": "if (realResult.status === 0)" in run_bdd
        and "fallbackResult.status !== 0" in run_bdd,
    }


def build_checks(
    routine_text: str,
    routine: dict[str, Any],
    ui_qa_steps: int,
    planning_failure: dict[str, Any],
    direct_bdd: CommandEvidence,
) -> list[Check]:
    root = routine.get("routine", routine)
    steps = root.get("steps", [])
    s03 = next((step for step in steps if step.get("id") == "S-03"), {})
    s04 = next((step for step in steps if step.get("id") == "S-04"), {})
    s06 = next((step for step in steps if step.get("id") == "S-06"), {})

    checks = [
        Check(
            "Failed-run baseline is broad",
            ui_qa_steps > 1,
            f"UI-QA generated {ui_qa_steps} executable step YAML files before the phase-1 change.",
        ),
        Check(
            "Original verifier masked weak gates",
            planning_failure["must_false_mentions"] > 0
            and planning_failure["quality_note_present"],
            "The UI-QA verification report marked the plan ready while noting behavior checks were must:false.",
        ),
        Check(
            "Generated harness can mask real browser failure",
            planning_failure["fallback_runner_present"]
            and planning_failure["fallback_can_return_success"],
            "run-bdd.mjs reruns a fallback harness after Playwright failure and returns success if that fallback passes.",
        ),
        Check(
            "Real browser surface was not proven",
            direct_bdd.exit_code not in (0, None),
            f"Direct Playwright check exited {direct_bdd.exit_code}; this is the real-surface failure the plan should have stopped on.",
        ),
        Check(
            "Routine detects incremental oversight mode",
            "Planning mode: incremental oversight" in routine_text,
            "S-01 now instructs the planner to mark large/uncertain work as incremental oversight.",
        ),
        Check(
            "Step planning limits executable output",
            "Create exactly one executable step plan" in json.dumps(s03),
            "S-03 requires exactly one step plan when incremental oversight mode is active.",
        ),
        Check(
            "Required evidence headings are enforced",
            all(term in routine_text for term in REQUIRED_OVERSIGHT_TERMS),
            "Routine text contains all required oversight headings.",
        ),
        Check(
            "Task YAML preserves evidence contract",
            "incremental_yaml_contract_if_enabled" in json.dumps(s04),
            "S-04 has an auto-verify guard for preserving oversight fields in YAML.",
        ),
        Check(
            "Final verification evaluates oversight readiness",
            "Incremental Oversight Readiness" in json.dumps(s06)
            and "masked verification" in json.dumps(s06),
            "S-06 requires oversight readiness and now rejects fallback-masked real-surface failures.",
        ),
    ]
    return checks


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int) and value > 1000:
        return f"{value:,}"
    return str(value)


def load_smoke_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [item for item in data if isinstance(item, dict)]


def render_report(
    *,
    run_id: str,
    api_url: str,
    api_error: str | None,
    run_summary: dict[str, Any],
    checks: list[Check],
    planning_failure: dict[str, Any],
    direct_bdd: CommandEvidence,
    ui_qa_step_count: int,
    ui_qa_task_count: int,
    smoke_results: list[dict[str, Any]],
    output_path: Path,
) -> str:
    check_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(check.name)}</td>"
        f'<td class="{"pass" if check.passed else "fail"}">{"PASS" if check.passed else "FAIL"}</td>'
        f"<td>{html.escape(check.evidence)}</td>"
        "</tr>"
        for check in checks
    )
    run_rows = "\n".join(
        f"<tr><th>{html.escape(key)}</th><td>{html.escape(format_value(value))}</td></tr>"
        for key, value in run_summary.items()
    )
    planning_rows = "\n".join(
        f"<tr><th>{html.escape(key)}</th><td>{html.escape(format_value(value))}</td></tr>"
        for key, value in planning_failure.items()
    )
    smoke_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(format_value(item.get('stage')))}</td>"
        f"<td><code>{html.escape(format_value(item.get('run_id')))}</code></td>"
        f"<td>{html.escape(format_value(item.get('status')))} / {html.escape(format_value(item.get('pause_reason')))}</td>"
        f'<td class="{"pass" if item.get("passed") else "fail"}">{"PASS" if item.get("passed") else "PARTIAL"}</td>'
        f"<td>{html.escape(format_value(item.get('measurement')))}</td>"
        "</tr>"
        for item in smoke_results
    )
    bdd_excerpt = html.escape(direct_bdd.output_excerpt)
    score = sum(1 for check in checks if check.passed)
    api_note = (
        f"Orchestrator API unavailable: {html.escape(api_error)}"
        if api_error
        else f"Fetched from {html.escape(api_url)}/api/runs/{html.escape(run_id)}"
    )
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Phase 1 Incremental Oversight Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }}
    main {{ max-width: 1100px; margin: 0 auto; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    .meta {{ color: #5d6d7e; margin-top: 0; }}
    .panel {{ border: 1px solid #d6dbdf; border-radius: 8px; padding: 18px; margin: 18px 0; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border: 1px solid #d6dbdf; padding: 9px 11px; text-align: left; vertical-align: top; }}
    th {{ background: #f4f6f7; width: 230px; }}
    .pass {{ color: #0b6b3a; font-weight: 700; }}
    .fail {{ color: #a93226; font-weight: 700; }}
    code {{ background: #f4f6f7; padding: 1px 4px; border-radius: 4px; }}
    ul {{ line-height: 1.5; }}
  </style>
</head>
<body>
<main>
  <h1>Phase 1 Incremental Oversight Report</h1>
  <p class="meta">Reference run: <code>{html.escape(run_id)}</code>. {api_note}</p>

  <section class="panel">
    <h2>Result</h2>
    <p><strong>{score}/{len(checks)} checks passed.</strong> The failure was a planning and verification failure before it was an executor failure: a broad plan generated many pieces, static verification declared readiness, and real browser failures were not made blocking evidence.</p>
  </section>

  <section class="panel">
    <h2>Failed Run Evidence</h2>
    <table>{run_rows}</table>
    <p>The generated UI-QA routine contains <strong>{ui_qa_step_count}</strong> executable step files and <strong>{ui_qa_task_count}</strong> tasks. That is the broad decomposition phase 1 is intended to prevent for uncertain work.</p>
  </section>

  <section class="panel">
    <h2>Planning Failure Evidence</h2>
    <table>{planning_rows}</table>
    <p>The key issue is not that Codex Server eventually hit a streaming parser error. The run had already spent substantial effort on a plan that allowed broad workflow generation before proving the first real UI test path was runnable.</p>
  </section>

  <section class="panel">
    <h2>Real-Surface Test</h2>
    <table>
      <tr><th>command</th><td><code>{html.escape(direct_bdd.command)}</code></td></tr>
      <tr><th>cwd</th><td>{html.escape(direct_bdd.cwd)}</td></tr>
      <tr><th>exit_code</th><td>{html.escape(format_value(direct_bdd.exit_code))}</td></tr>
      <tr><th>timed_out</th><td>{html.escape(format_value(direct_bdd.timed_out))}</td></tr>
    </table>
    <pre>{bdd_excerpt}</pre>
  </section>

  <section class="panel">
    <h2>Phase 1 Checks</h2>
    <table>
      <tr><th>Check</th><th>Status</th><th>Evidence</th></tr>
      {check_rows}
    </table>
  </section>

  <section class="panel">
    <h2>Root-Generation Orchestrator Smokes</h2>
    <table>
      <tr><th>Stage</th><th>Run</th><th>Status</th><th>Measured</th><th>Evidence</th></tr>
      {smoke_rows}
    </table>
    <p>These smokes exercise the root <code>idea-to-plan-yaml-steps</code> planning flow and bounded continuations through Orchestrator. They confirm the updated planning contract changes the generated S-01/S-03/S-04 artifacts, but executor/verifier interruptions mean this is not yet a full S-01 through S-08 completion proof.</p>
  </section>

  <section class="panel">
    <h2>Before Phase 2+</h2>
    <ul>
      <li>Run the updated planning routine on a large frontend task and require the first slice to prove one real browser path before any additional workflows are planned.</li>
      <li>Phase 2 must treat a failed real-surface command as a stop/replan event even if a fallback harness or shim passes.</li>
      <li>Phase 3 review should reject plans whose strongest behavior proof is <code>must: false</code>, generated-file counts, fallback harness success, or helper-only assertions.</li>
      <li>The <code>codex_server</code> separator failure still needs operational follow-up, but it should not distract from the planning failure that caused the wasted work.</li>
    </ul>
  </section>
</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text)
    return html_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--smoke-results", default=DEFAULT_SMOKE_RESULTS)
    parser.add_argument("--skip-live-test", action="store_true")
    args = parser.parse_args()

    repo = Path.cwd()
    routine_path = repo / "routines/idea-to-plan-yaml-steps/routine.yaml"
    ui_qa_step_dir = repo / "routines/UI-QA/steps"

    run, api_error = fetch_json(f"{args.api_url.rstrip('/')}/api/runs/{args.run_id}")
    run_summary = summarize_run(run)
    routine_text = routine_path.read_text()
    routine = load_yaml(routine_path)
    planning_failure = extract_planning_failure_evidence(repo)
    direct_bdd = (
        CommandEvidence("skipped", str(repo), 0, False, "Live test skipped by --skip-live-test.")
        if args.skip_live_test
        else run_command(
            [
                "npm",
                "exec",
                "--",
                "playwright",
                "test",
                "--config",
                "playwright.bdd.config.ts",
                "--reporter=list",
                "--max-failures=1",
            ],
            repo / "worktrees/r82/ui",
            timeout=45,
        )
    )
    ui_qa_step_count = len(list(ui_qa_step_dir.glob("*.yaml")))
    ui_qa_task_count = count_tasks_in_steps(ui_qa_step_dir)
    checks = build_checks(routine_text, routine, ui_qa_step_count, planning_failure, direct_bdd)
    smoke_results = load_smoke_results(repo / args.smoke_results)
    render_report(
        run_id=args.run_id,
        api_url=args.api_url.rstrip("/"),
        api_error=api_error,
        run_summary=run_summary,
        checks=checks,
        planning_failure=planning_failure,
        direct_bdd=direct_bdd,
        ui_qa_step_count=ui_qa_step_count,
        ui_qa_task_count=ui_qa_task_count,
        smoke_results=smoke_results,
        output_path=repo / args.output,
    )
    print(
        json.dumps(
            {"output": args.output, "passed": sum(c.passed for c in checks), "total": len(checks)},
            indent=2,
        )
    )
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
