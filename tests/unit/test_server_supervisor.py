"""Pure and real-object coverage for durable server supervision."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pytest

from orchestrator.cli.server_supervisor import (
    EvidenceWriter,
    LifecycleEvent,
    ProcessIdentity,
    ProcessIdentityInspection,
    SupervisorConfig,
    SupervisorState,
    active_supervisor_state,
    crash_verified_serving_child,
    inspect_supervisor_identity,
    inspect_process_identity,
    next_consecutive_failure_count,
    previous_unclean_state,
    reclaim_stale_child,
    reclaim_stale_collector,
    read_state,
    restart_backoff,
    run_server_supervisor,
    process_identity_matches,
    stale_child_identity_matches,
)


def _state(tmp_path: Path, *, pid: int, status: str = "running") -> SupervisorState:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    identity = psutil.Process(pid) if pid == os.getpid() else None
    return SupervisorState.model_validate(
        {
            "session_id": "prior-session",
            "session_dir": str(tmp_path / "prior-session"),
            "status": status,
            "started_at": now,
            "updated_at": now,
            "supervisor_pid": pid,
            "supervisor_process_group_id": os.getpgid(pid) if identity is not None else None,
            "supervisor_create_time": identity.create_time() if identity is not None else None,
            "supervisor_command": identity.cmdline() if identity is not None else None,
            "attempt": 2,
            "child_pid": 999_999_998,
            "command": ["orchestrator", "serve"],
        }
    )


def _capture_identity(pid: int) -> ProcessIdentity:
    inspection = inspect_process_identity(pid)
    assert inspection.outcome == "available"
    assert inspection.identity is not None
    return inspection.identity


def _kill_exact_process(identity: ProcessIdentity) -> None:
    inspection = inspect_process_identity(identity.pid)
    if inspection.outcome == "not_running":
        return
    assert inspection.identity is not None
    matches, detail = process_identity_matches(identity, inspection.identity)
    assert matches, detail
    os.kill(identity.pid, signal.SIGKILL)


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


def test_verified_crash_refuses_pid_reuse_identity_before_signaling(tmp_path: Path) -> None:
    child = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    child_identity = _capture_identity(child.pid)
    supervisor_identity = _capture_identity(os.getpid())
    now = datetime.now(UTC)
    state = SupervisorState(
        session_id="verified-crash",
        session_dir=str(tmp_path),
        status="running",
        started_at=now,
        updated_at=now,
        supervisor_pid=supervisor_identity.pid,
        supervisor_process_group_id=supervisor_identity.process_group_id,
        supervisor_create_time=supervisor_identity.create_time,
        supervisor_command=supervisor_identity.command,
        child_pid=child_identity.pid,
        child_process_group_id=child_identity.process_group_id,
        child_create_time=child_identity.create_time,
        command=child_identity.command,
    )
    try:
        refused = crash_verified_serving_child(
            state,
            reached_owner_pid=child.pid,
            reached_owner_create_time=child_identity.create_time + 10,
        )
        assert refused.outcome == "refused"
        assert "does not equal" in refused.detail
        assert child.poll() is None

        signaled = crash_verified_serving_child(
            state,
            reached_owner_pid=child.pid,
            reached_owner_create_time=child_identity.create_time,
        )
        assert signaled.outcome == "signaled"
        assert signaled.process_group_id == child.pid
        assert signaled.signal_number == signal.SIGKILL
        assert child.wait(timeout=2) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            _kill_exact_process(child_identity)
            child.wait(timeout=2)
    assert (
        next_consecutive_failure_count(4, child_runtime_seconds=60, stable_runtime_seconds=60) == 1
    )


def test_verified_crash_refuses_stale_official_supervisor(tmp_path: Path) -> None:
    stale_supervisor = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    serving_child = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    supervisor_identity = _capture_identity(stale_supervisor.pid)
    child_identity = _capture_identity(serving_child.pid)
    now = datetime.now(UTC)
    state = SupervisorState(
        session_id="stale-supervisor-crash-refusal",
        session_dir=str(tmp_path),
        status="running",
        started_at=now,
        updated_at=now,
        supervisor_pid=supervisor_identity.pid,
        supervisor_process_group_id=supervisor_identity.process_group_id,
        supervisor_create_time=supervisor_identity.create_time,
        supervisor_command=supervisor_identity.command,
        child_pid=child_identity.pid,
        child_process_group_id=child_identity.process_group_id,
        child_create_time=child_identity.create_time,
        command=child_identity.command,
    )
    try:
        _kill_exact_process(supervisor_identity)
        assert stale_supervisor.wait(timeout=2) == -signal.SIGKILL

        refused = crash_verified_serving_child(
            state,
            reached_owner_pid=serving_child.pid,
            reached_owner_create_time=child_identity.create_time,
        )

        assert refused.outcome == "refused"
        assert "supervisor identity is not verified" in refused.detail
        assert serving_child.poll() is None
    finally:
        if stale_supervisor.poll() is None:
            _kill_exact_process(supervisor_identity)
            stale_supervisor.wait(timeout=2)
        if serving_child.poll() is None:
            _kill_exact_process(child_identity)
            serving_child.wait(timeout=2)


def test_verified_crash_refuses_different_unofficial_process(tmp_path: Path) -> None:
    serving_child = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    unofficial = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    child_identity = _capture_identity(serving_child.pid)
    unofficial_identity = _capture_identity(unofficial.pid)
    supervisor_identity = _capture_identity(os.getpid())
    now = datetime.now(UTC)
    state = SupervisorState(
        session_id="unofficial-owner-crash-refusal",
        session_dir=str(tmp_path),
        status="running",
        started_at=now,
        updated_at=now,
        supervisor_pid=supervisor_identity.pid,
        supervisor_process_group_id=supervisor_identity.process_group_id,
        supervisor_create_time=supervisor_identity.create_time,
        supervisor_command=supervisor_identity.command,
        child_pid=child_identity.pid,
        child_process_group_id=child_identity.process_group_id,
        child_create_time=child_identity.create_time,
        command=child_identity.command,
    )
    try:
        refused = crash_verified_serving_child(
            state,
            reached_owner_pid=unofficial_identity.pid,
            reached_owner_create_time=unofficial_identity.create_time,
        )

        assert refused.outcome == "refused"
        assert "does not equal" in refused.detail
        assert serving_child.poll() is None
        assert unofficial.poll() is None
    finally:
        for process, identity in (
            (serving_child, child_identity),
            (unofficial, unofficial_identity),
        ):
            if process.poll() is None:
                _kill_exact_process(identity)
                process.wait(timeout=2)


def test_evidence_writer_appends_fsynced_json_and_replaces_state(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    state_path = tmp_path / "supervisor-state.json"
    writer = EvidenceWriter(session_dir=session_dir, state_path=state_path)
    state = _state(tmp_path, pid=999_999_999, status="stopped")
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
    observed = previous_unclean_state(state_path)
    assert observed is not None
    assert observed.status == "abrupt_supervisor_loss"
    assert observed.stop_reason == "abrupt_supervisor_loss"

    writer.write_state(_state(tmp_path, pid=999_999_999, status="stopped"))
    assert previous_unclean_state(state_path) is None


def test_live_supervisor_state_is_not_classified_as_unclean(tmp_path: Path) -> None:
    state_path = tmp_path / "supervisor-state.json"
    writer = EvidenceWriter(session_dir=tmp_path / "session", state_path=state_path)
    live = _state(tmp_path, pid=os.getpid())
    writer.write_state(live)
    assert active_supervisor_state(state_path) == live
    assert previous_unclean_state(state_path) is None
    identity_evidence = inspect_supervisor_identity(live)
    assert identity_evidence.identity_verified is True
    assert identity_evidence.liveness == "verified_live"
    assert identity_evidence.recorded_process_group_id == os.getpgid(os.getpid())
    assert identity_evidence.observed_process_group_id == os.getpgid(os.getpid())

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


def test_live_pid_with_mismatched_creation_identity_is_abrupt_loss(tmp_path: Path) -> None:
    state_path = tmp_path / "supervisor-state.json"
    writer = EvidenceWriter(session_dir=tmp_path / "session", state_path=state_path)
    mismatched = _state(tmp_path, pid=os.getpid()).model_copy(
        update={"supervisor_create_time": 1.0}
    )
    writer.write_state(mismatched)

    observed = read_state(state_path)
    assert observed is not None
    assert observed.status == "abrupt_supervisor_loss"
    assert active_supervisor_state(state_path) is None


@pytest.mark.parametrize(
    "recorded_process_group_id",
    [None, -1],
    ids=["legacy-state-without-pgid", "wrong-recorded-pgid"],
)
@pytest.mark.parametrize("status", ["running", "stopping"])
def test_live_supervisor_missing_or_wrong_recorded_group_is_abrupt_loss(
    tmp_path: Path, recorded_process_group_id: int | None, status: str
) -> None:
    state_path = tmp_path / "supervisor-state.json"
    writer = EvidenceWriter(session_dir=tmp_path / "session", state_path=state_path)
    state = _state(tmp_path, pid=os.getpid(), status=status).model_copy(
        update={"supervisor_process_group_id": recorded_process_group_id}
    )
    writer.write_state(state)

    observed = read_state(state_path)
    assert observed is not None
    assert observed.status == "abrupt_supervisor_loss"
    assert active_supervisor_state(state_path) is None
    identity_evidence = inspect_supervisor_identity(state)
    assert identity_evidence.identity_verified is False
    assert identity_evidence.recorded_process_group_id == recorded_process_group_id
    assert identity_evidence.observed_process_group_id == os.getpgid(os.getpid())
    assert identity_evidence.liveness == (
        "incomplete_recorded_identity" if recorded_process_group_id is None else "identity_mismatch"
    )


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

    assert result.outcome == "terminated", result.detail
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


def test_reclaim_stale_collector_signals_only_verified_real_pid(tmp_path: Path) -> None:
    command = (sys.executable, "-c", "import time; time.sleep(60)")
    collector = subprocess.Popen(command)
    try:
        identity = psutil.Process(collector.pid)
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "collector_pid": collector.pid,
                "collector_process_group_id": os.getpgid(collector.pid),
                "collector_create_time": identity.create_time(),
                "collector_command": command,
            }
        )
        result = reclaim_stale_collector(state, grace_seconds=1)
        collector.wait(timeout=2)
    finally:
        if collector.poll() is None:
            collector.kill()
            collector.wait(timeout=2)

    assert result.outcome == "terminated", result.detail
    assert result.signal_number == signal.SIGTERM


@pytest.mark.parametrize("persistent", [False, True])
def test_reclaim_collector_requires_exit_evidence_after_inspection_loss(
    tmp_path: Path, persistent: bool
) -> None:
    collector = subprocess.Popen((sys.executable, "-c", "import time; time.sleep(60)"))
    observations = 0

    def inspect_with_loss(pid: int) -> ProcessIdentityInspection:
        nonlocal observations
        assert pid == collector.pid
        observations += 1
        # Both inspections authorizing SIGTERM use the real process identity.
        # After delivery, model lost read access without changing the process.
        if observations >= 3 and (persistent or observations == 3):
            return ProcessIdentityInspection(
                outcome="unavailable", detail="process identity read access denied"
            )
        return inspect_process_identity(pid)

    try:
        identity = _capture_identity(collector.pid)
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "collector_pid": identity.pid,
                "collector_process_group_id": identity.process_group_id,
                "collector_create_time": identity.create_time,
                "collector_command": identity.command,
            }
        )
        result = reclaim_stale_collector(
            state, grace_seconds=0.2, inspect_identity=inspect_with_loss
        )
        collector.wait(timeout=2)
        assert result.signal_number == signal.SIGTERM
        if persistent:
            assert result.outcome == "refused"
            assert "refusing SIGKILL" in result.detail
        else:
            assert result.outcome == "terminated", result.detail
        assert observations >= 4
    finally:
        if collector.poll() is None:
            collector.kill()
        collector.wait(timeout=2)


@pytest.mark.parametrize("denied_observation", [1, 2])
def test_reclaim_collector_does_not_signal_without_fresh_identity(
    tmp_path: Path, denied_observation: int
) -> None:
    collector = subprocess.Popen((sys.executable, "-c", "import time; time.sleep(60)"))
    observations = 0

    def inspect_with_loss(pid: int) -> ProcessIdentityInspection:
        nonlocal observations
        assert pid == collector.pid
        observations += 1
        if observations >= denied_observation:
            return ProcessIdentityInspection(outcome="unavailable", detail="access denied")
        return inspect_process_identity(pid)

    try:
        identity = _capture_identity(collector.pid)
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "collector_pid": identity.pid,
                "collector_process_group_id": identity.process_group_id,
                "collector_create_time": identity.create_time,
                "collector_command": identity.command,
            }
        )
        result = reclaim_stale_collector(
            state, grace_seconds=0.2, inspect_identity=inspect_with_loss
        )
        assert result.outcome == "refused"
        assert result.signal_number is None
        assert collector.poll() is None
    finally:
        collector.kill()
        collector.wait(timeout=2)


@pytest.mark.parametrize("persistent", [False, True])
def test_reclaim_collector_requires_exit_evidence_after_sigkill(
    tmp_path: Path, persistent: bool
) -> None:
    command = (
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(60)",
    )
    collector = subprocess.Popen(command, stdout=subprocess.PIPE)
    unavailable_observations = 0

    def inspect_with_exit_loss(pid: int) -> ProcessIdentityInspection:
        nonlocal unavailable_observations
        assert pid == collector.pid
        inspection = inspect_process_identity(pid)
        if inspection.outcome == "not_running" and (persistent or unavailable_observations == 0):
            unavailable_observations += 1
            return ProcessIdentityInspection(outcome="unavailable", detail="access denied")
        return inspection

    try:
        assert collector.stdout is not None
        assert collector.stdout.readline() == b"ready\n"
        identity = _capture_identity(collector.pid)
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "collector_pid": identity.pid,
                "collector_process_group_id": identity.process_group_id,
                "collector_create_time": identity.create_time,
                "collector_command": identity.command,
            }
        )
        result = reclaim_stale_collector(
            state, grace_seconds=0.1, inspect_identity=inspect_with_exit_loss
        )
        assert collector.wait(timeout=2) == -signal.SIGKILL
        assert unavailable_observations >= 1
        assert result.signal_number == signal.SIGKILL
        if persistent:
            assert result.outcome == "failed"
            assert "exit could not be verified" in result.detail
        else:
            assert result.outcome == "killed", result.detail
    finally:
        if collector.poll() is None:
            collector.kill()
        collector.wait(timeout=2)
        if collector.stdout is not None:
            collector.stdout.close()


def test_reclaim_absent_legacy_collector_does_not_require_identity(tmp_path: Path) -> None:
    collector = subprocess.Popen((sys.executable, "-c", "pass"))
    collector_pid = collector.pid
    collector.wait(timeout=2)
    state = _state(tmp_path, pid=999_999_999).model_copy(
        update={
            "collector_pid": collector_pid,
            "collector_process_group_id": None,
            "collector_create_time": None,
            "collector_command": None,
        }
    )

    result = reclaim_stale_collector(state, grace_seconds=0)

    assert result.outcome == "not_running"
    assert result.child_pid == collector_pid
    assert result.signal_number is None


def test_reclaim_live_legacy_collector_without_identity_still_refuses(
    tmp_path: Path,
) -> None:
    collector = subprocess.Popen((sys.executable, "-c", "import time; time.sleep(60)"))
    try:
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "collector_pid": collector.pid,
                "collector_process_group_id": None,
                "collector_create_time": None,
                "collector_command": None,
            }
        )

        result = reclaim_stale_collector(state, grace_seconds=0)

        assert result.outcome == "refused"
        assert "PID is live" in result.detail
        assert collector.poll() is None
    finally:
        collector.kill()
        collector.wait(timeout=2)


@pytest.mark.parametrize("_iteration", range(3))
def test_reclaim_stale_child_refuses_when_zombie_leader_has_live_group_member(
    tmp_path: Path, _iteration: int
) -> None:
    descendant_path = tmp_path / "descendant.pid"
    code = """
import os
import sys
import time
from pathlib import Path

descendant = os.fork()
if descendant == 0:
    time.sleep(60)
    raise SystemExit(0)
target = Path(sys.argv[1])
temporary = target.with_name(target.name + ".tmp")
temporary.write_text(str(descendant), encoding="utf-8")
os.replace(temporary, target)
time.sleep(60)
"""
    command = (sys.executable, "-c", code, str(descendant_path))
    leader = subprocess.Popen(command, start_new_session=True)
    descendant_identity: ProcessIdentity | None = None
    try:
        deadline = time.monotonic() + 5
        while not descendant_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        descendant_pid = int(descendant_path.read_text(encoding="utf-8"))
        leader_identity = _capture_identity(leader.pid)
        descendant_identity = _capture_identity(descendant_pid)
        assert descendant_identity.process_group_id == leader.pid
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "child_pid": leader.pid,
                "child_process_group_id": leader.pid,
                "child_create_time": leader_identity.create_time,
                "command": leader_identity.command,
            }
        )
        os.kill(leader.pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while psutil.Process(leader.pid).status() != psutil.STATUS_ZOMBIE:
            if time.monotonic() >= deadline:
                raise AssertionError("leader did not become an unreaped zombie")
            time.sleep(0.05)

        result = reclaim_stale_child(state, grace_seconds=0)

        assert result.outcome == "refused"
        assert "still has live members" in result.detail
        assert str(descendant_pid) in result.detail
        assert inspect_process_identity(descendant_pid).outcome == "available"
    finally:
        if descendant_identity is not None:
            _kill_exact_process(descendant_identity)
        if leader.poll() is None:
            leader.kill()
        leader.wait(timeout=5)


@pytest.mark.parametrize("_iteration", range(3))
def test_reclaim_stale_collector_refuses_sigkill_after_exec_changes_identity(
    tmp_path: Path, _iteration: int
) -> None:
    ready_path = tmp_path / "collector-ready"
    changed_path = tmp_path / "collector-execed"
    code = """
import os
import signal
import sys
import time
from pathlib import Path

def replace_process(_signum, _frame):
    Path(sys.argv[2]).write_text("execed", encoding="utf-8")
    os.execv(sys.executable, [sys.executable, "-c", "import time; time.sleep(60)"])

signal.signal(signal.SIGTERM, replace_process)
Path(sys.argv[1]).write_text("ready", encoding="utf-8")
time.sleep(60)
"""
    command = (sys.executable, "-c", code, str(ready_path), str(changed_path))
    collector = subprocess.Popen(command)
    cleanup_identity: ProcessIdentity | None = None
    try:
        deadline = time.monotonic() + 5
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        original_identity = _capture_identity(collector.pid)
        state = _state(tmp_path, pid=999_999_999).model_copy(
            update={
                "collector_pid": collector.pid,
                "collector_process_group_id": original_identity.process_group_id,
                "collector_create_time": original_identity.create_time,
                "collector_command": original_identity.command,
            }
        )

        result = reclaim_stale_collector(state, grace_seconds=0.3)

        assert changed_path.exists()
        assert result.outcome == "refused"
        assert result.signal_number == signal.SIGTERM
        assert "identity changed" in result.detail
        assert "refusing SIGKILL" in result.detail or "awaiting SIGTERM" in result.detail
        cleanup_identity = _capture_identity(collector.pid)
    finally:
        if cleanup_identity is None and collector.poll() is None:
            cleanup_identity = _capture_identity(collector.pid)
        if cleanup_identity is not None:
            _kill_exact_process(cleanup_identity)
        collector.wait(timeout=5)


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
    drained = [event for event in events if event["event"] == "log_collector_drained"]
    assert len(drained) == 2
    assert [event["attempt"] for event in drained] == [1, 2]
    assert all(isinstance(event["collector_pid"], int) for event in drained)
    assert all(event["returncode"] == 0 for event in drained)
    exits = [event for event in events if event["event"] == "unexpected_child_exit"]
    assert [event["exit_code"] for event in exits] == [7, 7]
    assert events[-1]["event"] == "crash_loop_exhausted"
    process_lines = (session_dir / "process.log").read_text(encoding="utf-8").splitlines()
    assert process_lines[0].startswith("[202")
    assert process_lines[0].endswith("child diagnostic")
    assert read_state(tmp_path / "logs" / "supervisor-state.json").status == "crash_loop"
