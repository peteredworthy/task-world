"""Monitor a run and auto-answer clarification questions by selecting the first option.

Usage:
    uv run python scripts/monitor_and_answer.py <run_id>
    uv run python scripts/monitor_and_answer.py --start <routine_id> [--feature <feature>]
"""

from __future__ import annotations

import argparse
import functools
import time

import httpx

# Force unbuffered output so background monitoring is visible
print = functools.partial(print, flush=True)  # type: ignore[assignment]

BASE = "http://localhost:8000/api"
POLL_INTERVAL = 10  # seconds


def get_run(client: httpx.Client, run_id: str) -> dict:
    r = client.get(f"{BASE}/runs/{run_id}")
    r.raise_for_status()
    return r.json()


def get_pending_actions(client: httpx.Client, run_id: str) -> list[dict]:
    r = client.get(f"{BASE}/runs/{run_id}/pending-actions")
    r.raise_for_status()
    return r.json()  # list[PendingActionSchema]


def answer_clarification(
    client: httpx.Client,
    run_id: str,
    task_id: str,
    request_id: str,
    questions: list[dict],
) -> dict:
    """Auto-answer each question by selecting the first option."""
    answers = []
    for q in questions:
        answer: dict = {"question_id": q["id"]}
        qtype = q.get("question_type", "single_select")

        if qtype == "single_select" and q.get("options"):
            answer["selected_option"] = q["options"][0]
        elif qtype == "multi_select" and q.get("options"):
            answer["selected_options"] = [q["options"][0]]
        elif qtype == "free_text":
            answer["free_text"] = "Proceed with your best judgment."
        elif qtype == "number":
            answer["free_text"] = str(q.get("min", 1))
        else:
            # Fallback: if options exist, pick first
            if q.get("options"):
                answer["selected_option"] = q["options"][0]
            else:
                answer["free_text"] = "Proceed with default."

        answers.append(answer)

    r = client.post(
        f"{BASE}/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
        json={"answers": answers},
    )
    r.raise_for_status()
    return r.json()


def start_run(client: httpx.Client, routine_id: str, config: dict) -> str:
    """Create and start a new run from a routine."""
    payload = {
        "routine_id": routine_id,
        "agent_runner_type": "cli_subprocess",
        "agent_runner_config": {"command": "claude"},
        "config": config,
    }
    r = client.post(f"{BASE}/runs", json=payload)
    r.raise_for_status()
    data = r.json()
    run_id = data["id"]
    print(f"Created run {run_id}")

    # Start it
    r = client.post(f"{BASE}/runs/{run_id}/start")
    r.raise_for_status()
    print(f"Started run {run_id}")
    return run_id


def monitor(client: httpx.Client, run_id: str) -> None:
    """Poll the run until terminal state, auto-answering clarifications."""
    terminal = {"completed", "failed", "cancelled"}
    last_status = None
    last_step = None

    while True:
        try:
            run = get_run(client, run_id)
        except httpx.HTTPError as e:
            print(f"  [error fetching run: {e}]")
            time.sleep(POLL_INTERVAL)
            continue

        status = run.get("status")
        step_idx = run.get("current_step_index", 0)
        step_count = len(run.get("steps", []))
        pause_reason = run.get("pause_reason", "")

        if status != last_status or step_idx != last_step:
            print(
                f"  [{status}] step {step_idx + 1}/{step_count} | pause_reason={pause_reason or 'none'}"
            )
            last_status = status
            last_step = step_idx

        if status in terminal:
            print(f"\nRun finished: {status}")
            # Print summary
            for i, step in enumerate(run.get("steps", [])):
                tasks = step.get("tasks", [])
                statuses = [t.get("status", "?") for t in tasks]
                print(f"  Step {i + 1} ({step.get('name', '?')}): {statuses}")
            break

        # Check for pending clarifications
        if status == "paused" and "user" in (pause_reason or "").lower():
            try:
                actions = get_pending_actions(client, run_id)
                for action in actions:
                    if action.get("action_type") != "clarification":
                        continue
                    clar = action.get("clarification_request")
                    if not clar:
                        continue
                    req_id = clar["id"]
                    task_id = action["task_id"]
                    questions = clar.get("questions", [])
                    print(f"\n  >> Clarification {req_id} for task {task_id}")
                    for q in questions:
                        opts = q.get("options", [])
                        print(f"     Q: {q.get('question', '?')}")
                        if opts:
                            print(f"     Options: {opts}")
                            print(f"     -> Selecting: {opts[0]}")
                        else:
                            print("     -> Free text: 'Proceed with your best judgment.'")

                    result = answer_clarification(client, run_id, task_id, req_id, questions)
                    print(f"     Answered! Task now: {result.get('task_status', '?')}")
                    print()
            except httpx.HTTPError as e:
                print(f"  [error handling clarification: {e}]")

        # Also check for paused runs that need resuming (e.g. after clarification)
        if status == "paused" and not pause_reason:
            try:
                r = client.post(f"{BASE}/runs/{run_id}/resume")
                if r.status_code == 200:
                    print("  Resumed run (no pause reason)")
            except httpx.HTTPError:
                pass

        time.sleep(POLL_INTERVAL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor a run and auto-answer clarifications")
    parser.add_argument("run_id", nargs="?", help="Existing run ID to monitor")
    parser.add_argument("--start", metavar="ROUTINE_ID", help="Start a new run from this routine")
    parser.add_argument(
        "--feature", default="planning-routine-improvements", help="Feature name for config"
    )
    args = parser.parse_args()

    if not args.run_id and not args.start:
        parser.error("Provide a run_id or --start <routine_id>")

    client = httpx.Client(timeout=30)

    if args.start:
        config = {"feature": args.feature}
        run_id = start_run(client, args.start, config)
    else:
        run_id = args.run_id

    print(f"Monitoring run {run_id}...")
    print(f"Poll interval: {POLL_INTERVAL}s")
    print()

    try:
        monitor(client, run_id)
    except KeyboardInterrupt:
        print("\nStopped monitoring (run continues in background)")


if __name__ == "__main__":
    main()
