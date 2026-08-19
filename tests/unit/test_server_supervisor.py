"""Pure and real-object coverage for durable server supervision."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psutil

from orchestrator.cli.server_supervisor import (
    EvidenceWriter,
    LifecycleEvent,
    ProcessIdentity,
    SupervisorConfig,
    SupervisorState,
    active_supervisor_state,
    next_consecutive_failure_count,
    previous_unclean_state,
    reclaim_stale_child,
    read_state,
    restart_backoff,
    run_server_supervisor,
    stale_child_identity_matches,
)


def _state(tmp_path: Path, *, pid: int, status: str = "running") -> SupervisorState:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    return SupervisorState.model_validate(
        {
            "session_id": "prior-session",
            "session_dir": str(tmp_path / "prior-session"),
            "status": status,
            "started_at": now,
            "updated_at": now,
            "supervisor_pid": pid,
            "attempt": 2,
            "child_pid": 999_999_998,
            "command": ["orchestrator", "serve"],
        }
    )


def test_restart_backoff_is_exponential_and_capped() -> None:
    values = [
        restart_backoff(attempt, initial_seconds=0.5, maximum_seconds=2.0)
        for attempt in range(1, 6)
    ]
    assert values == [0.5, 1.0, 2.0, 2.0, 2.0]


def test_stable_runtime_resets_old_crash_count_before_counting_latest_exit() -> None:
    assert (
        next_consecutive_failure_count(4, child_runtime_seconds=59, stable_runtime_seconds=60) == 5
    )
    assert (
        next_consecutive_failure_count(4, child_runtime_seconds=60, stable_runtime_seconds=60) == 1
    )


def test_evidence_writer_appends_fsynced_json_and_replaces_state(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    state_path = tmp_path / "supervisor-state.json"
    writer = EvidenceWriter(session_dir=session_dir, state_path=state_path)
    state = _state(tmp_path, pid=999_999_999)
    writer.write_state(state)
    writer.append(
        LifecycleEvent(
            timestamp=datetime(2026, 8, 16, tzinfo=UTC),
            event="child_started",
            session_id="session",
            supervisor_pid=123,
            child_pid=456,
            attempt=1,
            command=("uvicorn", "scripts.serve:app"),
        )
    )

    assert read_state(state_path) == state
    event = json.loads((session_dir / "lifecycle.jsonl").read_text(encoding="utf-8"))
    assert event["event"] == "child_started"
    assert event["command"] == ["uvicorn", "scripts.serve:app"]


def test_previous_unclean_state_requires_unterminated_dead_supervisor(tmp_path: Path) -> None:
    state_path = tmp_path / "supervisor-state.json"
    writer = EvidenceWriter(session_dir=tmp_path / "session", state_path=state_path)
    stale = _state(tmp_path, pid=999_999_999)
    writer.write_state(stale)
    assert previous_unclean_state(state_path) == stale

    writer.write_state(_state(tmp_path, pid=999_999_999, status="stopped"))
    assert previous_unclean_state(state_path) is None


def test_live_supervisor_state_is_not_classified_as_unclean(tmp_path: Path) -> None:
    state_path = tmp_path / "supervisor-state.json"
    writer = EvidenceWriter(session_dir=tmp_path / "session", state_path=state_path)
    live = _state(tmp_path, pid=os.getpid())
    writer.write_state(live)
    assert active_supervisor_state(state_path) == live
    assert previous_unclean_state(state_path) is None

    config = SupervisorConfig(
        command=(sys.executable, "-c", "raise AssertionError('must not launch')"),
        cwd=tmp_path,
        log_root=tmp_path,
    )
    try:
        run_server_supervisor(config)
    except RuntimeError as exc:
        assert "already running" in str(exc)
    else:
        raise AssertionError("second supervisor was not rejected")


def test_stale_child_identity_requires_pid_group_start_time_and_command(tmp_path: Path) -> None:
    command = (sys.executable, "-c", "import time; time.sleep(60)")
    state = _state(tmp_path, pid=456).model_copy(
        update={
            "child_pid": 456,
            "child_process_group_id": 456,
            "child_create_time": 1234.5,
            "command": command,
        }
    )
    identity = ProcessIdentity(
        pid=456,
        process_group_id=456,
        create_time=1234.5,
        command=command,
    )

    assert stale_child_identity_matches(state, identity)[0] is True
    reused_pid = identity.model_copy(update={"create_time": 1235.5})
    matches, detail = stale_child_identity_matches(state, reused_pid)
    assert matches is False
    assert "creation time" in detail


def test_reclaim_stale_child_terminates_verified_real_process_group(tmp_path: Path) -> None:
    command = (sys.executable, "-c", "import time; time.sleep(60)")
    child = subprocess.Popen(command, start_new_session=True)
    try:
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "child_pid": child.pid,
                "child_process_group_id": os.getpgid(child.pid),
                "child_create_time": psutil.Process(child.pid).create_time(),
                "command": command,
            }
        )
        result = reclaim_stale_child(state, grace_seconds=1)
        child.wait(timeout=2)
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)

    assert result.outcome == "terminated"
    assert result.signal_number == signal.SIGTERM


def test_reclaim_stale_child_refuses_live_pid_without_start_identity(tmp_path: Path) -> None:
    command = (sys.executable, "-c", "import time; time.sleep(60)")
    child = subprocess.Popen(command, start_new_session=True)
    try:
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={"child_pid": child.pid, "command": command}
        )
        result = reclaim_stale_child(state, grace_seconds=0)
        assert child.poll() is None
    finally:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=2)

    assert result.outcome == "refused"
    assert "lacks process-group or process-start" in result.detail


def test_supervisor_records_exact_exit_and_stops_at_crash_loop_bound(tmp_path: Path) -> None:
    exit_code = run_server_supervisor(
        SupervisorConfig(
            command=(
                sys.executable,
                "-c",
                "import sys; print('child diagnostic', flush=True); sys.exit(7)",
            ),
            cwd=tmp_path,
            log_root=tmp_path / "logs",
            max_attempts=2,
            initial_backoff_seconds=0,
            maximum_backoff_seconds=0,
        )
    )

    assert exit_code == 7
    session_dir = (tmp_path / "logs" / "latest").resolve()
    events = [
        json.loads(line)
        for line in (session_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events].count("child_started") == 2
    exits = [event for event in events if event["event"] == "unexpected_child_exit"]
    assert [event["exit_code"] for event in exits] == [7, 7]
    assert events[-1]["event"] == "crash_loop_exhausted"
    process_lines = (session_dir / "process.log").read_text(encoding="utf-8").splitlines()
    assert process_lines[0].startswith("[202")
    assert process_lines[0].endswith("child diagnostic")
    assert read_state(tmp_path / "logs" / "supervisor-state.json").status == "crash_loop"
