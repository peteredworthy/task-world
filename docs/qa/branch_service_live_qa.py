"""Live QA driver for docs/qa/branch-service-qa-plan.md.

The script uses the public REST API for run state and calls the child evidence
helper inside child worktrees to create real run.evidence.v1 files.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_URL = "http://127.0.0.1:8000"
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ApiResult:
    status: int
    body: Any


def api(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> ApiResult:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else None
            return ApiResult(status=response.status, body=body)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw) if raw else raw
        except json.JSONDecodeError:
            body = raw
        return ApiResult(status=exc.code, body=body)


def wait_run(run_id: str, predicate, *, timeout_seconds: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: ApiResult | None = None
    while time.monotonic() < deadline:
        last = api(f"/api/runs/{run_id}")
        if last.status == 200 and predicate(last.body):
            return last.body
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for run {run_id}; last={last}")


def wait_task(run_id: str, task_id: str, status: str, *, timeout_seconds: float = 30) -> None:
    def has_task_status(run: dict[str, Any]) -> bool:
        for step in run["steps"]:
            for task in step["tasks"]:
                if task["id"] == task_id:
                    return task["status"] == status
        return False

    wait_run(run_id, has_task_status, timeout_seconds=timeout_seconds)


def task_status(run: dict[str, Any], task_id: str) -> str | None:
    for step in run["steps"]:
        for task in step["tasks"]:
            if task["id"] == task_id:
                return task["status"]
    return None


def wait_task_status_or_none(
    run_id: str,
    task_id: str,
    status: str,
    *,
    timeout_seconds: float = 10,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        current = api(f"/api/runs/{run_id}")
        if current.status == 200 and task_status(current.body, task_id) == status:
            return current.body
        time.sleep(0.5)
    return None


def ensure_active(
    results: list[dict[str, Any]], run: dict[str, Any], *, check: str
) -> dict[str, Any]:
    """Resume a user-managed run if the stale-run sweeper paused it."""
    latest = api(f"/api/runs/{run['id']}")
    if latest.status != 200:
        record(
            results, check, status=latest.status, passed=False, run_id=run["id"], detail=latest.body
        )
        return run
    current = latest.body
    if current["status"] == "active":
        return current
    if current["status"] == "paused":
        resume = api(f"/api/runs/{run['id']}/resume", method="POST", payload={})
        record(
            results,
            check,
            status=resume.status,
            passed=resume.status == 202,
            run_id=run["id"],
            previous_pause_reason=current.get("pause_reason"),
        )
        return wait_run(run["id"], lambda item: item["status"] == "active")
    record(
        results,
        check,
        status=409,
        passed=False,
        run_id=run["id"],
        run_status=current["status"],
    )
    return current


def shell(command: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    return {
        "command": " ".join(command),
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }


def record(results: list[dict[str, Any]], check: str, **fields: Any) -> None:
    status = fields.get("status")
    passed = fields.pop("passed", None)
    if passed is None:
        passed = status is None or (200 <= int(status) < 300)
    results.append({"check": check, "pass": bool(passed), **fields})


def is_paused_transition_conflict(response: ApiResult) -> bool:
    if response.status != 409:
        return False
    text = json.dumps(response.body)
    return '"from_status": "paused"' in text or ("from_status" in text and "paused" in text)


def parent_routine(routine_id: str) -> dict[str, Any]:
    return {
        "id": routine_id,
        "name": "QA Parent Oversight Live",
        "description": "Tiny parent oversight QA probe.",
        "inputs": [],
        "steps": [
            {
                "id": "S-01",
                "title": "Parent oversight probe",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Keep parent active for child QA",
                        "instructions": "Do not edit source files. Use REST callbacks only.",
                        "requirements": [
                            {
                                "id": "R1",
                                "desc": "Parent run remains available for child oversight QA.",
                                "priority": "critical",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def child_routine(routine_id: str, slice_id: str) -> dict[str, Any]:
    evidence_path = f"docs/run-evidence/{slice_id}-evidence.json"
    return {
        "id": routine_id,
        "name": f"QA Child {slice_id}",
        "description": "Tiny child evidence QA probe.",
        "inputs": [],
        "steps": [
            {
                "id": "S-01",
                "title": "Child evidence probe",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Write child evidence",
                        "instructions": f"Write {evidence_path} using scripts/run_child_evidence.py.",
                        "requirements": [
                            {
                                "id": "R1",
                                "desc": "A run.evidence.v1 bundle exists for this slice.",
                                "priority": "critical",
                            }
                        ],
                        "artifacts": [{"path": evidence_path, "required": True}],
                    }
                ],
            }
        ],
    }


def create_parent(results: list[dict[str, Any]], *, max_child_runs: int) -> dict[str, Any]:
    routine_id = f"qa-parent-oversight-live-{int(time.time() * 1000)}"
    response = api(
        "/api/runs",
        method="POST",
        payload={
            "routine_embedded": parent_routine(routine_id),
            "repo_name": "task-world",
            "branch": "main",
            "config": {"max_child_runs": max_child_runs},
            "agent_runner_type": "user_managed",
            "agent_runner_config": {"callback_channel": "mcp", "timeout_minutes": 60},
        },
    )
    if response.status != 201:
        raise RuntimeError(f"create parent failed: {response.status} {response.body}")
    run_id = response.body["id"]
    record(results, "create parent run", status=response.status, run_id=run_id)

    start = api(f"/api/runs/{run_id}/start", method="POST", payload={})
    record(results, "start parent run", status=start.status, run_id=run_id)
    parent = wait_run(run_id, lambda run: run["status"] == "active" and run["worktree_path"])
    record(
        results,
        "parent active with worktree",
        status=200,
        run_id=run_id,
        worktree_path=parent["worktree_path"],
    )
    return parent


def patch_parent_oversight(results: list[dict[str, Any]], parent_id: str) -> dict[str, Any]:
    response = api(
        f"/api/runs/{parent_id}/oversight",
        method="PATCH",
        payload={
            "current_understanding": {"summary": "Live QA parent is ready for child probes."},
            "target_inventory": [{"id": "QA-TARGET-001", "resolved": False, "in_scope": True}],
            "decision": {"action": "launch_child", "reason": "exercise live QA child path"},
        },
    )
    state = response.body.get("oversight_state", {}) if isinstance(response.body, dict) else {}
    record(
        results,
        "patch parent oversight",
        status=response.status,
        run_id=parent_id,
        durable_summary=state.get("current_understanding", {}).get("summary"),
        target_count=len(state.get("target_inventory", [])),
    )
    return state


def create_child(
    results: list[dict[str, Any]],
    parent: dict[str, Any],
    *,
    slice_id: str,
    routine_id: str,
) -> dict[str, Any]:
    response: ApiResult | None = None
    for attempt in range(1, 4):
        parent = ensure_active(
            results, parent, check=f"resume parent before child create attempt {attempt}"
        )
        response = api(
            f"/api/runs/{parent['id']}/children",
            method="POST",
            payload={
                "routine_embedded": child_routine(routine_id, slice_id),
                "parent_slice_id": slice_id,
                "next_action_decision": "continue",
            },
        )
        if response.status == 201:
            break
        if is_paused_transition_conflict(response):
            record(
                results,
                "retry child create after parent pause race",
                status=response.status,
                passed=True,
                parent_run_id=parent["id"],
                attempt=attempt,
                detail=response.body,
            )
            time.sleep(1)
            continue
        break
    if response is None:
        raise RuntimeError("create child did not issue a request")
    if response.status != 201:
        raise RuntimeError(f"create child failed: {response.status} {response.body}")
    child_id = response.body["id"]
    child = wait_run(
        child_id,
        lambda run: run["status"] in {"active", "paused"} and run["worktree_path"],
        timeout_seconds=60,
    )
    child = ensure_active(results, child, check="resume child after worktree setup")
    inherited = (
        child["repo_name"] == parent["repo_name"]
        and child["agent_runner_type"] == parent["agent_runner_type"]
        and child["source_branch"] is not None
    )
    record(
        results,
        "create child run",
        status=response.status,
        run_id=child_id,
        parent_run_id=parent["id"],
        parent_slice_id=slice_id,
        worktree_path=child["worktree_path"],
        inherited_parent_settings=inherited,
    )
    return child


def attempt_second_child(results: list[dict[str, Any]], parent: dict[str, Any]) -> None:
    parent = ensure_active(results, parent, check="resume parent before guardrail probe")
    response = api(
        f"/api/runs/{parent['id']}/children",
        method="POST",
        payload={
            "routine_embedded": child_routine("qa-child-second-blocked-live", "QA-SLICE-SECOND"),
            "parent_slice_id": "QA-SLICE-SECOND",
            "next_action_decision": "continue",
        },
    )
    record(
        results,
        "unresolved child guardrail blocks second child",
        status=response.status,
        passed=response.status == 409,
        parent_run_id=parent["id"],
        detail=response.body,
    )


def write_valid_evidence(
    results: list[dict[str, Any]], child: dict[str, Any], *, slice_id: str
) -> None:
    worktree = Path(child["worktree_path"])
    helper = shell(
        [
            "uv",
            "run",
            "python",
            "scripts/run_child_evidence.py",
            "--slice-id",
            slice_id,
            "--routine-id",
            child["routine_id"],
            "--success-outcome",
            "behavior_already_correct",
            "--assumption",
            "Live QA can produce child evidence without LLM execution.",
            "--summary",
            "The live QA child evidence helper completed a harmless command.",
            "--real-execution-surface",
            "live REST QA child worktree",
            "--command",
            "qa_child_print::uv run python -c \"print('qa child evidence ok')\"",
        ],
        cwd=worktree,
    )
    record(
        results,
        "run child evidence helper",
        status=0 if helper["exit_code"] == 0 else 1,
        passed=helper["exit_code"] == 0,
        run_id=child["id"],
        command=helper["command"],
        worktree_path=str(worktree),
        stdout=helper["stdout"],
        stderr=helper["stderr"],
    )
    irrelevant = worktree / "docs" / "run-evidence" / "irrelevant.json"
    irrelevant.write_text('{"schema_version":"not.run.evidence"}\n', encoding="utf-8")
    git_add = shell(["git", "add", "docs/run-evidence", ".evidence"], cwd=worktree)
    git_commit = shell(["git", "commit", "-m", "Add QA child evidence"], cwd=worktree)
    record(
        results,
        "commit child evidence",
        status=0 if git_commit["exit_code"] == 0 else 1,
        passed=git_add["exit_code"] == 0 and git_commit["exit_code"] == 0,
        run_id=child["id"],
        add_stderr=git_add["stderr"],
        commit_stdout=git_commit["stdout"],
        commit_stderr=git_commit["stderr"],
    )


def write_identity_mismatched_evidence(
    results: list[dict[str, Any]],
    child: dict[str, Any],
    *,
    actual_slice_id: str,
) -> None:
    worktree = Path(child["worktree_path"])
    helper = shell(
        [
            "uv",
            "run",
            "python",
            "scripts/run_child_evidence.py",
            "--slice-id",
            "WRONG-SLICE-ID",
            "--routine-id",
            child["routine_id"],
            "--evidence-path",
            f"docs/run-evidence/{actual_slice_id}-evidence.json",
            "--success-outcome",
            "verified_fix",
            "--assumption",
            "Live QA identity mismatch should block acceptance.",
            "--summary",
            "This evidence intentionally uses the wrong slice_id.",
            "--real-execution-surface",
            "live REST QA child worktree",
            "--command",
            "qa_invalid_print::uv run python -c \"print('qa invalid evidence ok')\"",
        ],
        cwd=worktree,
    )
    record(
        results,
        "write identity-mismatched child evidence",
        status=0 if helper["exit_code"] == 0 else 1,
        passed=helper["exit_code"] == 0,
        run_id=child["id"],
        command=helper["command"],
    )
    shell(["git", "add", "docs/run-evidence", ".evidence"], cwd=worktree)
    commit = shell(["git", "commit", "-m", "Add invalid QA child evidence"], cwd=worktree)
    record(
        results,
        "commit invalid child evidence",
        status=0 if commit["exit_code"] == 0 else 1,
        passed=commit["exit_code"] == 0,
        run_id=child["id"],
        commit_stdout=commit["stdout"],
        commit_stderr=commit["stderr"],
    )


def complete_child(results: list[dict[str, Any]], child: dict[str, Any]) -> dict[str, Any]:
    child = ensure_active(results, child, check="resume child before task callbacks")
    run_id = child["id"]
    task_id = child["steps"][0]["tasks"][0]["id"]
    child = ensure_active(results, child, check="resume child before task start")
    start = api(f"/api/runs/{run_id}/tasks/{task_id}/start", method="POST", payload={})
    record(results, "start child task", status=start.status, run_id=run_id, task_id=task_id)
    child = ensure_active(results, child, check="resume child before checklist update")
    checklist = api(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        method="PATCH",
        payload={"status": "done", "note": "Live QA evidence written."},
    )
    record(results, "mark child checklist done", status=checklist.status, run_id=run_id)
    verifying_run = None
    submit_status = None
    submit_body = None
    for attempt in range(1, 5):
        child = ensure_active(results, child, check=f"resume child before submit attempt {attempt}")
        submit = api(f"/api/runs/{run_id}/tasks/{task_id}/submit", method="POST", payload={})
        submit_status = submit.status
        submit_body = submit.body
        if submit.status == 200:
            verifying_run = wait_task_status_or_none(run_id, task_id, "verifying")
            if verifying_run is not None:
                break
        time.sleep(1)
    record(
        results,
        "submit child task",
        status=submit_status or 0,
        passed=verifying_run is not None,
        run_id=run_id,
        detail=submit_body,
    )
    if verifying_run is None:
        raise RuntimeError(f"Child {run_id} did not enter verifying after submit retries")
    child = verifying_run
    child = ensure_active(results, child, check="resume child before grading")
    grade = api(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        method="PUT",
        payload={"grade": "A", "grade_reason": "Live QA evidence accepted."},
    )
    record(results, "grade child task", status=grade.status, run_id=run_id)
    completed_run = None
    complete_status = None
    complete_body = None
    for attempt in range(1, 5):
        child = ensure_active(
            results, child, check=f"resume child before complete attempt {attempt}"
        )
        complete = api(
            f"/api/runs/{run_id}/tasks/{task_id}/complete-verification",
            method="POST",
            payload={},
        )
        complete_status = complete.status
        complete_body = complete.body
        if complete.status == 200:
            completed_run = wait_run(
                run_id, lambda run: run["status"] == "completed", timeout_seconds=15
            )
            break
        time.sleep(1)
    record(
        results,
        "complete child verification",
        status=complete_status or 0,
        passed=completed_run is not None,
        run_id=run_id,
        detail=complete_body,
    )
    if completed_run is None:
        raise RuntimeError(f"Child {run_id} did not complete after verification retries")
    return completed_run


def accept_child(results: list[dict[str, Any]], parent_id: str, child_id: str) -> ApiResult:
    response: ApiResult | None = None
    for attempt in range(1, 4):
        latest_parent = api(f"/api/runs/{parent_id}")
        if latest_parent.status == 200 and isinstance(latest_parent.body, dict):
            ensure_active(
                results,
                latest_parent.body,
                check=f"resume parent before child accept attempt {attempt}",
            )
        else:
            record(
                results,
                "load parent before child accept",
                status=latest_parent.status,
                passed=False,
                parent_run_id=parent_id,
                detail=latest_parent.body,
            )
        response = api(
            f"/api/runs/{parent_id}/children/{child_id}/accept", method="POST", payload={}
        )
        if not is_paused_transition_conflict(response):
            break
        record(
            results,
            "retry child accept after parent pause race",
            status=response.status,
            passed=True,
            run_id=child_id,
            parent_run_id=parent_id,
            attempt=attempt,
            detail=response.body,
        )
        time.sleep(1)
    if response is None:
        raise RuntimeError("accept child did not issue a request")
    record(
        results,
        "accept child",
        status=response.status,
        run_id=child_id,
        parent_run_id=parent_id,
        detail=response.body,
    )
    return response


def resolve_child_path(results: list[dict[str, Any]]) -> None:
    parent = create_parent(results, max_child_runs=2)
    child = create_child(
        results,
        parent,
        slice_id="QA-SLICE-RESOLVE",
        routine_id="qa-child-resolve-live",
    )
    child = ensure_active(results, child, check="resume child before resolve pause")
    pause = api(f"/api/runs/{child['id']}/pause", method="POST", payload={})
    record(results, "pause child for resolve", status=pause.status, run_id=child["id"])
    wait_run(child["id"], lambda run: run["status"] == "paused")
    parent = ensure_active(results, parent, check="resume parent before child resolve")
    first = api(
        f"/api/runs/{parent['id']}/children/{child['id']}/resolve",
        method="POST",
        payload={"resolution": "reject", "reason": "Live QA reject path."},
    )
    record(
        results,
        "resolve child reject",
        status=first.status,
        run_id=child["id"],
        parent_run_id=parent["id"],
        detail=first.body,
    )
    parent = ensure_active(results, parent, check="resume parent before duplicate child resolve")
    duplicate = api(
        f"/api/runs/{parent['id']}/children/{child['id']}/resolve",
        method="POST",
        payload={"resolution": "reject", "reason": "Live QA duplicate reject path."},
    )
    state = duplicate.body.get("oversight_state", {}) if isinstance(duplicate.body, dict) else {}
    decisions = state.get("delegation_decisions", []) or state.get("decisions", [])
    stale_recorded = "StaleCommandIgnored" in json.dumps(decisions)
    record(
        results,
        "duplicate resolve is idempotent/stale",
        status=duplicate.status,
        passed=duplicate.status == 200 and stale_recorded,
        run_id=child["id"],
        parent_run_id=parent["id"],
        stale_recorded=stale_recorded,
    )
    parent = ensure_active(results, parent, check="resume parent before replacement child")
    replacement = api(
        f"/api/runs/{parent['id']}/children",
        method="POST",
        payload={
            "routine_embedded": child_routine("qa-child-replacement-live", "QA-SLICE-REPLACEMENT"),
            "parent_slice_id": "QA-SLICE-REPLACEMENT",
            "next_action_decision": "continue",
        },
    )
    record(
        results,
        "rejected child allows replacement",
        status=replacement.status,
        passed=replacement.status == 201,
        parent_run_id=parent["id"],
        replacement_run_id=replacement.body.get("id")
        if isinstance(replacement.body, dict)
        else None,
    )


def trace_path(results: list[dict[str, Any]]) -> None:
    parent = create_parent(results, max_child_runs=1)
    parent = ensure_active(results, parent, check="resume trace run before task callbacks")
    task_id = parent["steps"][0]["tasks"][0]["id"]
    parent = ensure_active(results, parent, check="resume trace run before task start")
    api(f"/api/runs/{parent['id']}/tasks/{task_id}/start", method="POST", payload={})
    parent = ensure_active(results, parent, check="resume trace run before checklist update")
    api(
        f"/api/runs/{parent['id']}/tasks/{task_id}/checklist/R1",
        method="PATCH",
        payload={"status": "done", "note": "Trace QA checklist."},
    )
    verifying_run = None
    submit_status = None
    for attempt in range(1, 5):
        parent = ensure_active(
            results, parent, check=f"resume trace run before submit attempt {attempt}"
        )
        submit = api(f"/api/runs/{parent['id']}/tasks/{task_id}/submit", method="POST", payload={})
        submit_status = submit.status
        if submit.status == 200:
            verifying_run = wait_task_status_or_none(parent["id"], task_id, "verifying")
            if verifying_run is not None:
                break
        time.sleep(1)
    record(
        results,
        "trace run submit",
        status=submit_status or 0,
        passed=verifying_run is not None,
        run_id=parent["id"],
    )
    if verifying_run is None:
        raise RuntimeError(f"Trace run {parent['id']} did not enter verifying")
    parent = ensure_active(results, verifying_run, check="resume trace run before grading")
    api(
        f"/api/runs/{parent['id']}/tasks/{task_id}/checklist/R1/grade",
        method="PUT",
        payload={"grade": "A", "grade_reason": "Trace QA grade."},
    )
    completed_trace = None
    complete_status = None
    for attempt in range(1, 5):
        parent = ensure_active(
            results, parent, check=f"resume trace run before complete attempt {attempt}"
        )
        complete = api(
            f"/api/runs/{parent['id']}/tasks/{task_id}/complete-verification",
            method="POST",
            payload={},
        )
        complete_status = complete.status
        if complete.status == 200:
            completed_trace = wait_run(
                parent["id"], lambda run: run["status"] == "completed", timeout_seconds=15
            )
            break
        time.sleep(1)
    record(
        results,
        "trace run complete verification",
        status=complete_status or 0,
        passed=completed_trace is not None,
        run_id=parent["id"],
    )
    if completed_trace is None:
        raise RuntimeError(f"Trace run {parent['id']} did not complete")
    trace = api(f"/api/runs/{parent['id']}/trace")
    body = trace.body if isinstance(trace.body, dict) else {}
    attempts = body.get("attempts", [])
    stable_shape = bool(
        body.get("run_id") == parent["id"]
        and attempts
        and "attempt" in attempts[0]
        and isinstance(attempts[0].get("phases"), list)
        and "action_log" in attempts[0]
        and "total_tokens_read" in body
        and "total_tokens_write" in body
        and "total_tokens_cache" in body
    )
    record(
        results,
        "fetch run trace shape",
        status=trace.status,
        passed=trace.status == 200 and stable_shape,
        run_id=parent["id"],
        attempts=len(attempts),
        sample_attempt=attempts[0] if attempts else None,
        token_totals={
            "read": body.get("total_tokens_read"),
            "write": body.get("total_tokens_write"),
            "cache": body.get("total_tokens_cache"),
        },
    )


def main() -> int:
    results: list[dict[str, Any]] = []
    health = api("/health")
    record(results, "health", status=health.status, body=health.body)

    parent = create_parent(results, max_child_runs=1)
    patch_parent_oversight(results, parent["id"])
    child = create_child(
        results,
        parent,
        slice_id="QA-SLICE-001",
        routine_id="qa-child-valid-evidence-live",
    )
    attempt_second_child(results, parent)
    write_valid_evidence(results, child, slice_id="QA-SLICE-001")
    evidence = api(f"/api/runs/{child['id']}/evidence")
    evidence_body = evidence.body if isinstance(evidence.body, dict) else {}
    record(
        results,
        "collect child evidence filters candidates",
        status=evidence.status,
        passed=evidence.status == 200
        and len(evidence_body.get("evidence", [])) == 1
        and evidence_body.get("invalid_evidence", []) == [],
        run_id=child["id"],
        evidence_paths=[item["path"] for item in evidence_body.get("evidence", [])],
        invalid=evidence_body.get("invalid_evidence", []),
    )
    completed_child = complete_child(results, child)
    accept_child(results, parent["id"], completed_child["id"])
    duplicate_accept = accept_child(results, parent["id"], completed_child["id"])
    record(
        results,
        "duplicate accept remains idempotent",
        status=duplicate_accept.status,
        passed=duplicate_accept.status == 200,
        run_id=completed_child["id"],
        parent_run_id=parent["id"],
    )

    invalid_parent = create_parent(results, max_child_runs=1)
    invalid_child = create_child(
        results,
        invalid_parent,
        slice_id="QA-SLICE-INVALID",
        routine_id="qa-child-invalid-evidence-live",
    )
    write_identity_mismatched_evidence(
        results,
        invalid_child,
        actual_slice_id="QA-SLICE-INVALID",
    )
    completed_invalid_child = complete_child(results, invalid_child)
    invalid_parent = ensure_active(
        results, invalid_parent, check="resume parent before invalid accept"
    )
    invalid_accept = api(
        f"/api/runs/{invalid_parent['id']}/children/{completed_invalid_child['id']}/accept",
        method="POST",
        payload={},
    )
    invalid_state = api(f"/api/runs/{invalid_parent['id']}/oversight")
    invalid_state_body = invalid_state.body if isinstance(invalid_state.body, dict) else {}
    invalid_state_text = json.dumps(invalid_state_body)
    record(
        results,
        "invalid evidence blocks acceptance",
        status=invalid_accept.status,
        passed=invalid_accept.status == 409 and "InvalidEvidence" in invalid_state_text,
        run_id=completed_invalid_child["id"],
        parent_run_id=invalid_parent["id"],
        detail=invalid_accept.body,
        invalid_evidence_recorded="InvalidEvidence" in invalid_state_text,
    )

    resolve_child_path(results)
    trace_path(results)
    record(
        results,
        "restart recovery smoke",
        status=0,
        passed=True,
        skipped=True,
        reason="Skipped because AGENTS.md says not to restart the server during agent work.",
    )

    print(json.dumps({"base_url": BASE_URL, "results": results}, indent=2, sort_keys=True))
    return 0 if all(item["pass"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
