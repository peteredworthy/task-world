#!/usr/bin/env python3
"""Run and measure a bounded phase-1 planning experiment through Orchestrator.

The script uses the Orchestrator REST API only. It creates a planning run for the
updated idea-to-plan-yaml-steps routine, starts it with a small model, waits with a
bounded polling interval, and writes a JSON measurement file. It does not modify the
database directly and it does not restart services.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_API = "http://localhost:8000"
DEFAULT_FEATURE = "phase1-oversight-experiment"
DEFAULT_OUTPUT = "docs/large-tasks/phase-1-orchestrator-experiment.json"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_TIMEOUT_SECONDS = 2700
DEFAULT_POLL_SECONDS = 20

EXPERIMENT_IDEA = """\
Design a frontend workflow test suite for the Orchestrator UI, focused on proving
that mocked API data, route handlers, and browser-visible UI behavior actually fit
together. This is intentionally large and uncertain: the current UI may not expose
the expected headings, selectors, navigation paths, or settings controls, and a
previous broad UI-QA routine generated many BDD files before proving a single real
browser path.

Do not plan the whole suite. The first slice should prove exactly one real browser
workflow end-to-end, using the actual UI route and actual Playwright browser runner.
The slice must detect and stop if a fallback harness, generated spec count, shim-only
assertion, or must:false command is the only passing evidence. If the real browser
path fails, capture that failure as evidence for replanning instead of expanding to
more workflows.

No clarifications are needed for the experiment. Make conservative assumptions and
prefer a small slice that demonstrates whether the verification surface is viable.
"""

CODEBASE_CONTEXT = """\
Python/FastAPI backend with React/Vite frontend in ui/. Existing planning routine
is routines/idea-to-plan-yaml-steps. Frontend tests use Playwright and Vitest.
Runs execute in isolated worktrees and artifacts are written under docs/<feature>/
and routines/<feature>/.
"""


@dataclass(frozen=True)
class ExperimentResult:
    run_id: str | None
    status: str | None
    pause_reason: str | None
    last_error: str | None
    worktree_path: str | None
    elapsed_seconds: int
    completed_steps: int
    total_steps: int
    completed_tasks: int
    total_tasks: int
    generated_step_plans: int
    generated_yaml_steps: int
    incremental_mode_detected: bool
    oversight_terms_in_first_step: bool
    broad_plan_detected: bool
    stopped_by_script: bool
    notes: list[str]


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
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def create_run(api_url: str, feature: str, model: str) -> dict[str, Any]:
    payload = {
        "routine_id": "idea-to-plan-yaml-steps",
        "repo_name": "task-world",
        "branch": "main",
        "config": {
            "feature": feature,
            "idea": EXPERIMENT_IDEA,
            "codebase_context": CODEBASE_CONTEXT,
        },
        "agent_type": "codex_server",
        "agent_config": {
            "model": model,
            "callback_channel": "rest",
            "restrictions": "managed",
        },
    }
    return request_json("POST", f"{api_url}/api/runs", payload)


def start_run(api_url: str, run_id: str) -> dict[str, Any]:
    return request_json("POST", f"{api_url}/api/runs/{run_id}/start", {})


def pause_run(api_url: str, run_id: str) -> None:
    request_json("POST", f"{api_url}/api/runs/{run_id}/pause", {})


def get_run(api_url: str, run_id: str) -> dict[str, Any]:
    return request_json("GET", f"{api_url}/api/runs/{run_id}")


def task_counts(run: dict[str, Any]) -> tuple[int, int, int, int]:
    steps = run.get("steps") or []
    completed_steps = sum(1 for step in steps if step.get("completed"))
    tasks = [task for step in steps for task in step.get("tasks", [])]
    completed_tasks = sum(1 for task in tasks if task.get("status") == "completed")
    return completed_steps, len(steps), completed_tasks, len(tasks)


def count_files(base: Path, pattern: str) -> int:
    return len(list(base.glob(pattern))) if base.exists() else 0


def analyze_outputs(
    worktree: Path | None, feature: str
) -> tuple[int, int, bool, bool, bool, list[str]]:
    notes: list[str] = []
    if worktree is None:
        return 0, 0, False, False, False, ["No worktree path was available."]

    docs_dir = worktree / "docs" / feature
    routine_steps_dir = worktree / "routines" / feature / "steps"
    plan_path = docs_dir / "plan.md"
    step_plans = count_files(docs_dir, "step-*-plan.md")
    yaml_steps = count_files(routine_steps_dir, "step-*-plan.yaml")
    plan_text = plan_path.read_text() if plan_path.exists() else ""
    first_step = docs_dir / "step-01-plan.md"
    first_step_text = first_step.read_text() if first_step.exists() else ""
    required_terms = [
        "Assumption Under Test",
        "Target Behavior Or Missing Proof",
        "Real Verification Surface",
        "Stop Or Replan Conditions",
        "Evidence Artifacts",
    ]
    incremental_mode = "Planning mode: incremental oversight" in plan_text
    terms_present = all(term in first_step_text for term in required_terms)
    broad_plan = step_plans > 1 or yaml_steps > 1

    if not incremental_mode:
        notes.append("plan.md does not declare incremental oversight mode.")
    if broad_plan:
        notes.append(f"Broad output detected: {step_plans} step plans, {yaml_steps} YAML steps.")
    if first_step.exists() and not terms_present:
        notes.append("step-01-plan.md exists but does not contain all required oversight terms.")
    return step_plans, yaml_steps, incremental_mode, terms_present, broad_plan, notes


def should_stop(run: dict[str, Any], worktree: Path | None, feature: str) -> bool:
    status = run.get("status")
    if status in {"paused", "completed", "failed", "cancelled"}:
        return True
    step_plans, yaml_steps, _, _, broad_plan, _ = analyze_outputs(worktree, feature)
    return broad_plan or yaml_steps >= 1 or step_plans > 1


def run_experiment(args: argparse.Namespace) -> ExperimentResult:
    api_url = args.api_url.rstrip("/")
    started = time.monotonic()
    run = create_run(api_url, args.feature, args.model)
    run_id = run["id"]
    start_run(api_url, run_id)
    stopped_by_script = False

    while True:
        run = get_run(api_url, run_id)
        worktree_raw = run.get("worktree_path")
        worktree = Path(worktree_raw) if worktree_raw else None
        elapsed = int(time.monotonic() - started)

        if should_stop(run, worktree, args.feature):
            if run.get("status") == "active" and args.pause_on_target:
                pause_run(api_url, run_id)
                stopped_by_script = True
                run = get_run(api_url, run_id)
            break

        if elapsed >= args.timeout_seconds:
            if run.get("status") == "active" and args.pause_on_target:
                pause_run(api_url, run_id)
                stopped_by_script = True
                run = get_run(api_url, run_id)
            break

        time.sleep(args.poll_seconds)

    worktree_raw = run.get("worktree_path")
    worktree = Path(worktree_raw) if worktree_raw else None
    completed_steps, total_steps, completed_tasks, total_tasks = task_counts(run)
    step_plans, yaml_steps, incremental, terms, broad, notes = analyze_outputs(
        worktree, args.feature
    )
    if run.get("status") == "active":
        notes.append("Run still active when script stopped.")

    return ExperimentResult(
        run_id=run_id,
        status=run.get("status"),
        pause_reason=run.get("pause_reason"),
        last_error=run.get("last_error"),
        worktree_path=worktree_raw,
        elapsed_seconds=int(time.monotonic() - started),
        completed_steps=completed_steps,
        total_steps=total_steps,
        completed_tasks=completed_tasks,
        total_tasks=total_tasks,
        generated_step_plans=step_plans,
        generated_yaml_steps=yaml_steps,
        incremental_mode_detected=incremental,
        oversight_terms_in_first_step=terms,
        broad_plan_detected=broad,
        stopped_by_script=stopped_by_script,
        notes=notes,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--feature", default=DEFAULT_FEATURE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--pause-on-target", action="store_true", default=True)
    args = parser.parse_args()

    result = run_experiment(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(result), indent=2))
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.incremental_mode_detected and not result.broad_plan_detected else 1


if __name__ == "__main__":
    sys.exit(main())
