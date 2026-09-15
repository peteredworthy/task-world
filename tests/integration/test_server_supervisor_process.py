"""Real-process coverage of the official supervised server launch path."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import psutil
import pytest

from orchestrator.cli.server_supervisor import SupervisorState
from orchestrator.graph_runtime import (
    CRASH_BARRIER_AUTHORIZATION,
    CrashBarrierPlanConfig,
    CrashBarrierTarget,
)

pytestmark = pytest.mark.e2e


@dataclass(frozen=True)
class _TestProcessIdentity:
    pid: int
    process_group_id: int
    create_time: float
    command: tuple[str, ...]


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server supervisor exited early with {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("supervised server did not become healthy")


def _wait_for_child_state(
    state_path: Path,
    process: subprocess.Popen[bytes],
    *,
    excluded_pid: int | None = None,
) -> dict[str, object]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server supervisor exited early with {process.returncode}")
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.05)
            continue
        child_pid = state.get("child_pid")
        if isinstance(child_pid, int) and child_pid != excluded_pid:
            return state
        time.sleep(0.05)
    raise AssertionError("supervisor did not publish a new child state")


def _process_is_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, ProcessLookupError):
        return False


def _wait_for_recorded_pid(
    path: Path, process: subprocess.Popen[bytes], *, excluded_pid: int | None = None
) -> int:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server supervisor exited early with {process.returncode}")
        try:
            pid = int(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            time.sleep(0.05)
            continue
        if pid != excluded_pid and _process_is_alive(pid):
            return pid
        time.sleep(0.05)
    raise AssertionError("serving child PID was not published")


def _wait_for_serving_health(
    state_path: Path, process: subprocess.Popen[bytes], *, attempt: int
) -> dict[str, object]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = _wait_for_child_state(state_path, process)
        if state.get("attempt") == attempt and state.get("serving_process_health") == "healthy":
            return state
        time.sleep(0.05)
    raise AssertionError(f"attempt {attempt} was not recorded healthy")


def _capture_process_identity(pid: int) -> _TestProcessIdentity:
    process = psutil.Process(pid)
    with process.oneshot():
        return _TestProcessIdentity(
            pid=pid,
            process_group_id=os.getpgid(pid),
            create_time=process.create_time(),
            command=tuple(process.cmdline()),
        )


def _identity_still_matches(identity: _TestProcessIdentity) -> bool:
    try:
        process = psutil.Process(identity.pid)
        with process.oneshot():
            return (
                process.status() != psutil.STATUS_ZOMBIE
                and os.getpgid(identity.pid) == identity.process_group_id
                and abs(process.create_time() - identity.create_time) <= 0.001
                and tuple(process.cmdline()) == identity.command
            )
    except (psutil.Error, ProcessLookupError, PermissionError):
        return False


def _kill_process_group_if_alive(identity: _TestProcessIdentity | None) -> None:
    if identity is None or not _identity_still_matches(identity):
        return
    try:
        os.killpg(identity.process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _kill_process_if_alive(identity: _TestProcessIdentity | None) -> None:
    if identity is None or not _identity_still_matches(identity):
        return
    try:
        os.kill(identity.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_official_cli_health_and_graceful_shutdown_leave_exact_evidence(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_root = tmp_path / "server-logs"
    port = _unused_port()
    environment = os.environ.copy()
    environment["ORCHESTRATOR_DB_PATH"] = str(tmp_path / "orchestrator.db")
    environment["ORCHESTRATOR_SKIP_STALE_PORT_KILL"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "orchestrator.cli.main",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-reload",
            "--log-dir",
            str(log_root),
        ],
        cwd=project_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_health(port, process)
        _wait_for_serving_health(log_root / "supervisor-state.json", process, attempt=1)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    session_dir = (log_root / "latest").resolve()
    events = [
        json.loads(line)
        for line in (session_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["event"] == "supervisor_started"
    assert any(event["event"] == "child_started" and event["attempt"] == 1 for event in events)
    assert any(event["event"] == "serving_process_healthy" for event in events)
    drained = next(event for event in events if event["event"] == "log_collector_drained")
    assert drained["attempt"] == 1
    assert isinstance(drained["collector_pid"], int)
    assert drained["returncode"] == 0
    shutdown = next(event for event in events if event["event"] == "clean_shutdown")
    assert shutdown["detail"] == "supervisor_received_SIGTERM"
    assert "Server lifespan ready" in (session_dir / "process.log").read_text(encoding="utf-8")
    state = json.loads((log_root / "supervisor-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert state["stop_reason"] == "supervisor_received_SIGTERM"
    assert "--reload" not in state["command"]
    assert state["collector_health"] == "drained"


def test_cli_rejects_competing_supervisor_and_reload_restart_owners(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator.cli.main",
            "serve",
            "--reload",
            "--supervisor",
            "--port",
            str(_unused_port()),
            "--log-dir",
            str(tmp_path / "must-not-start"),
        ],
        cwd=project_root,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert b"requires --no-supervisor" in result.stderr
    assert not (tmp_path / "must-not-start").exists()


def test_server_status_cli_classifies_stale_running_state_without_starting_server(
    tmp_path: Path,
) -> None:
    log_root = tmp_path / "operator-readback"
    log_root.mkdir()
    state = {
        "version": 1,
        "session_id": "stale-session",
        "session_dir": str(log_root / "stale-session"),
        "status": "running",
        "started_at": "2026-09-02T00:00:00Z",
        "updated_at": "2026-09-02T00:01:00Z",
        "supervisor_pid": 999_999_999,
        "attempt": 4,
        "consecutive_failures": 2,
        "command": ["uvicorn", "scripts.serve:app"],
    }
    (log_root / "supervisor-state.json").write_text(json.dumps(state), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator.cli.main",
            "--json",
            "server-status",
            "--log-dir",
            str(log_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert len(result.stdout) < 4096
    readback = json.loads(result.stdout)
    assert readback["status"] == "abrupt_supervisor_loss"
    assert readback["stop_reason"] == "abrupt_supervisor_loss"
    assert readback["supervisor_pid"] == 999_999_999
    assert readback["supervisor_recorded_process_group_id"] is None
    assert readback["supervisor_observed_process_group_id"] is None
    assert readback["supervisor_identity_verified"] is False
    assert readback["supervisor_liveness"] == "not_running"
    assert readback["attempt"] == 4


def test_server_status_cli_reports_exact_live_supervisor_identity(tmp_path: Path) -> None:
    log_root = tmp_path / "operator-readback"
    log_root.mkdir()
    process = psutil.Process(os.getpid())
    process_group_id = os.getpgid(os.getpid())
    state = {
        "version": 1,
        "session_id": "live-session",
        "session_dir": str(log_root / "live-session"),
        "status": "running",
        "started_at": "2026-09-02T00:00:00Z",
        "updated_at": "2026-09-02T00:01:00Z",
        "supervisor_pid": os.getpid(),
        "supervisor_process_group_id": process_group_id,
        "supervisor_create_time": process.create_time(),
        "supervisor_command": process.cmdline(),
        "command": ["uvicorn", "scripts.serve:app"],
    }
    (log_root / "supervisor-state.json").write_text(json.dumps(state), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator.cli.main",
            "--json",
            "server-status",
            "--log-dir",
            str(log_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert len(result.stdout) < 4096
    readback = json.loads(result.stdout)
    assert readback["status"] == "running"
    assert readback["supervisor_pid"] == os.getpid()
    assert readback["supervisor_recorded_process_group_id"] == process_group_id
    assert readback["supervisor_observed_process_group_id"] == process_group_id
    assert readback["supervisor_identity_verified"] is True
    assert readback["supervisor_liveness"] == "verified_live"
    assert "all match" in readback["supervisor_identity_detail"]


def test_crash_barrier_cli_reads_and_crashes_only_reached_serving_child(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    barrier_dir = tmp_path / "barriers"
    log_root = tmp_path / "supervisor"
    log_root.mkdir()
    config = CrashBarrierPlanConfig(
        schema_version=2,
        authorization=CRASH_BARRIER_AUTHORIZATION,
        run_id="official-cli-drill",
        nonce="official_cli_nonce_1234",
        target=CrashBarrierTarget(kind="worker", semantic_stage="effectful_batch"),
        slots=("after_staging_pre_witness", "after_witness_pre_finalization"),
    )
    child_script = """
import asyncio, os
from pathlib import Path
from orchestrator.graph_runtime import CrashBarrierObservation, crash_barrier_from_environment
barrier = crash_barrier_from_environment(os.environ, state_dir=Path(os.environ['BARRIER_DIR']), reconcile_process_loss=True)
observation = CrashBarrierObservation(run_id='official-cli-drill', node_id='effectful-1', execution_id='execution-1', lease_id='lease-1', lease_generation=1, node_kind='worker', node_role='builder', semantic_stage='effectful_batch', point='after_staging_pre_witness', attempt_state='submission_staged')
asyncio.run(barrier.wait_if_armed(run_id=observation.run_id, execution_id=observation.execution_id, point=observation.point, observation=observation))
"""
    environment = {
        **os.environ,
        "ORCHESTRATOR_GRAPH_CRASH_BARRIER": config.model_dump_json(),
        "BARRIER_DIR": str(barrier_dir),
    }
    child = subprocess.Popen(
        [sys.executable, "-c", child_script],
        cwd=project_root,
        env=environment,
        start_new_session=True,
    )
    try:
        state_path = barrier_dir / f"{config.barrier_id}.json"
        while True:
            if child.poll() is not None:
                raise AssertionError(f"serving child exited early with {child.returncode}")
            try:
                barrier_state = json.loads(state_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.02)
                continue
            if barrier_state["slots"][0]["status"] == "reached":
                break
            time.sleep(0.02)

        child_identity = _capture_process_identity(child.pid)
        supervisor_identity = _capture_process_identity(os.getpid())
        now = "2026-09-02T00:00:00Z"
        supervisor_state = SupervisorState.model_validate(
            {
                "session_id": "official-cli-test",
                "session_dir": str(log_root),
                "status": "running",
                "started_at": now,
                "updated_at": now,
                "supervisor_pid": supervisor_identity.pid,
                "supervisor_process_group_id": supervisor_identity.process_group_id,
                "supervisor_create_time": supervisor_identity.create_time,
                "supervisor_command": supervisor_identity.command,
                "child_pid": child_identity.pid,
                "child_process_group_id": child_identity.process_group_id,
                "child_create_time": child_identity.create_time,
                "command": child_identity.command,
            }
        )
        (log_root / "supervisor-state.json").write_text(
            supervisor_state.model_dump_json(), encoding="utf-8"
        )

        status = subprocess.run(
            [
                sys.executable,
                "-m",
                "orchestrator.cli.main",
                "--json",
                "crash-barrier-status",
                "--state-dir",
                str(barrier_dir),
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            timeout=5,
            check=False,
        )
        assert status.returncode == 0, status.stderr.decode()
        assert len(status.stdout) < 4096
        readback = json.loads(status.stdout)
        assert readback["slots"][0]["status"] == "reached"
        assert readback["slots"][0]["owner_pid"] == child.pid
        assert "release_token" not in status.stdout.decode()

        crash = subprocess.run(
            [
                sys.executable,
                "-m",
                "orchestrator.cli.main",
                "--json",
                "crash-barrier-crash",
                "--slot",
                "1",
                "--state-dir",
                str(barrier_dir),
                "--log-dir",
                str(log_root),
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            timeout=5,
            check=False,
        )
        assert crash.returncode == 0, crash.stderr.decode()
        assert json.loads(crash.stdout)["child_pid"] == child.pid
        assert child.wait(timeout=2) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)


@pytest.mark.timeout(90)
def test_official_supervisor_performs_ordered_two_slot_crash_drill(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    port = _unused_port()
    barrier_dir = tmp_path / "barriers"
    log_root = tmp_path / "supervisor"
    config = CrashBarrierPlanConfig(
        schema_version=2,
        authorization=CRASH_BARRIER_AUTHORIZATION,
        run_id="official-two-slot-drill",
        nonce="official_two_slot_nonce",
        target=CrashBarrierTarget(kind="worker", semantic_stage="effectful_batch"),
        slots=("after_staging_pre_witness", "after_witness_pre_finalization"),
    )
    child_script = """
import asyncio, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from orchestrator.graph_runtime import CrashBarrierObservation, CrashBarrierRecoveryProof, crash_barrier_from_environment
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *args):
        pass
class ReusableServer(ThreadingHTTPServer):
    allow_reuse_address = True
server = ReusableServer(('127.0.0.1', int(os.environ['DRILL_PORT'])), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
barrier = crash_barrier_from_environment(os.environ, state_dir=Path(os.environ['BARRIER_DIR']), reconcile_process_loss=True)
first = CrashBarrierObservation(run_id='official-two-slot-drill', node_id='effectful-1', execution_id='execution-1', lease_id='lease-1', lease_generation=1, node_kind='worker', node_role='builder', semantic_stage='effectful_batch', point='after_staging_pre_witness', attempt_state='submission_staged')
asyncio.run(barrier.wait_if_armed(run_id=first.run_id, execution_id=first.execution_id, point=first.point, observation=first))
proof = CrashBarrierRecoveryProof(node_id='effectful-1', execution_id='execution-1', lease_generation=1, state='recovered', completion_disposition='restored_unwitnessed', retry_authorized=True)
second = CrashBarrierObservation(run_id='official-two-slot-drill', node_id='effectful-1', execution_id='execution-2', lease_id='lease-2', lease_generation=2, node_kind='worker', node_role='builder', semantic_stage='effectful_batch', point='after_witness_pre_finalization', attempt_state='completion_witnessed', recovered_attempts=(proof,))
asyncio.run(barrier.wait_if_armed(run_id=second.run_id, execution_id=second.execution_id, point=second.point, observation=second))
threading.Event().wait()
"""
    wrapper = """
import os, sys
from pathlib import Path
from orchestrator.cli.server_supervisor import SupervisorConfig, run_server_supervisor
config = SupervisorConfig(command=(sys.executable, '-c', os.environ['CHILD_SCRIPT']), cwd=Path(os.environ['PROJECT_ROOT']), log_root=Path(os.environ['LOG_ROOT']), environment={'ORCHESTRATOR_GRAPH_CRASH_BARRIER': os.environ['ORCHESTRATOR_GRAPH_CRASH_BARRIER'], 'BARRIER_DIR': os.environ['BARRIER_DIR'], 'DRILL_PORT': os.environ['DRILL_PORT']}, max_attempts=5, initial_backoff_seconds=0.01, maximum_backoff_seconds=0.02, stable_runtime_seconds=60, graceful_shutdown_seconds=1, healthcheck_url='http://127.0.0.1:' + os.environ['DRILL_PORT'] + '/health', healthcheck_interval_seconds=0.05, healthcheck_timeout_seconds=0.2, healthcheck_failure_threshold=10, healthcheck_startup_grace_seconds=30)
raise SystemExit(run_server_supervisor(config))
"""
    environment = {
        **os.environ,
        "ORCHESTRATOR_GRAPH_CRASH_BARRIER": config.model_dump_json(),
        "BARRIER_DIR": str(barrier_dir),
        "DRILL_PORT": str(port),
        "PROJECT_ROOT": str(project_root),
        "LOG_ROOT": str(log_root),
        "CHILD_SCRIPT": child_script,
    }
    supervisor = subprocess.Popen(
        [sys.executable, "-c", wrapper], cwd=project_root, env=environment
    )

    def wait_for_slot(slot_index: int, status: str) -> dict[str, object]:
        path = barrier_dir / f"{config.barrier_id}.json"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if supervisor.poll() is not None:
                raise AssertionError(f"supervisor exited early: {supervisor.returncode}")
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.02)
                continue
            if state["slots"][slot_index]["status"] == status:
                return state
            time.sleep(0.02)
        raise AssertionError(f"slot {slot_index + 1} never reached {status}")

    def crash_slot(slot: int) -> dict[str, object]:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "orchestrator.cli.main",
                "--json",
                "crash-barrier-crash",
                "--slot",
                str(slot),
                "--state-dir",
                str(barrier_dir),
                "--log-dir",
                str(log_root),
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()
        return json.loads(result.stdout)

    try:
        _wait_for_health(port, supervisor)
        first = wait_for_slot(0, "reached")
        first_pid = first["slots"][0]["owner_pid"]
        assert crash_slot(1)["child_pid"] == first_pid

        second = wait_for_slot(1, "reached")
        second_pid = second["slots"][1]["owner_pid"]
        assert second_pid != first_pid
        assert second["slots"][0]["status"] == "consumed_after_process_loss"
        assert second["slots"][1]["node_id"] == second["slots"][0]["node_id"]
        assert second["slots"][1]["lease_generation"] > second["slots"][0]["lease_generation"]
        assert crash_slot(2)["child_pid"] == second_pid

        final = wait_for_slot(1, "consumed_after_process_loss")
        assert final["slots"][0]["status"] == "consumed_after_process_loss"
        _wait_for_health(port, supervisor)
        supervisor.send_signal(signal.SIGTERM)
        assert supervisor.wait(timeout=10) == 0
        lifecycle = (
            Path(json.loads((log_root / "supervisor-state.json").read_text())["session_dir"])
            / "lifecycle.jsonl"
        ).read_text()
        assert lifecycle.count('"event":"child_started"') == 3
    finally:
        if supervisor.poll() is None:
            supervisor.send_signal(signal.SIGTERM)
            supervisor.wait(timeout=10)


def test_supervisor_force_kills_unresponsive_child_group_after_grace_period(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_root = tmp_path / "forced-logs"
    ready_path = tmp_path / "unresponsive-child-ready"
    wrapper = """
import signal
import sys
from pathlib import Path
from orchestrator.cli.server_supervisor import SupervisorConfig, run_server_supervisor

child = (
    sys.executable,
    "-c",
    "import signal,sys,time; from pathlib import Path; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "Path(sys.argv[1]).write_text('ready', encoding='utf-8'); time.sleep(60)",
    sys.argv[2],
)
raise SystemExit(run_server_supervisor(SupervisorConfig(
    command=child,
    cwd=Path(sys.argv[1]),
    log_root=Path(sys.argv[1]),
    graceful_shutdown_seconds=0.2,
)))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", wrapper, str(log_root), str(ready_path)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        state_path = log_root / "supervisor-state.json"
        _wait_for_child_state(state_path, process)
        while not ready_path.exists():
            if process.poll() is not None:
                raise AssertionError(f"server supervisor exited early with {process.returncode}")
            time.sleep(0.05)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 128 + signal.SIGTERM
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    events = [
        json.loads(line)
        for line in ((log_root / "latest").resolve() / "lifecycle.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(event["event"] == "graceful_shutdown_timeout" for event in events)
    forced = next(event for event in events if event["event"] == "forced_shutdown")
    assert forced["returncode"] == -signal.SIGKILL
    assert forced["signal_name"] == "SIGKILL"


@pytest.mark.timeout(90)
def test_relaunch_reclaims_child_orphaned_by_supervisor_sigkill(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_root = tmp_path / "recovery-logs"
    state_path = log_root / "supervisor-state.json"
    port = _unused_port()
    environment = os.environ.copy()
    environment["ORCHESTRATOR_DB_PATH"] = str(tmp_path / "orchestrator.db")
    environment["ORCHESTRATOR_SKIP_STALE_PORT_KILL"] = "1"
    command = [
        sys.executable,
        "-m",
        "orchestrator.cli.main",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-reload",
        "--log-dir",
        str(log_root),
    ]
    first_output_path = tmp_path / "first-supervisor-output.log"
    second_output_path = tmp_path / "second-supervisor-output.log"
    with first_output_path.open("wb") as output:
        first = subprocess.Popen(
            command,
            cwd=project_root,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    second: subprocess.Popen[bytes] | None = None
    stale_child_pid: int | None = None
    stale_collector_pid: int | None = None
    stale_child_identity: _TestProcessIdentity | None = None
    stale_collector_identity: _TestProcessIdentity | None = None
    try:
        _wait_for_health(port, first)
        first_state = _wait_for_child_state(state_path, first)
        stale_child_pid = int(first_state["child_pid"])
        stale_collector_pid = int(first_state["collector_pid"])
        stale_child_identity = _capture_process_identity(stale_child_pid)
        stale_collector_identity = _capture_process_identity(stale_collector_pid)
        assert first_state["child_process_group_id"] == stale_child_pid
        assert isinstance(first_state["child_create_time"], float)
        assert _process_is_alive(stale_collector_pid)
        first.send_signal(signal.SIGKILL)
        assert first.wait(timeout=5) == -signal.SIGKILL
        assert _process_is_alive(stale_child_pid)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            assert response.status == 200

        with second_output_path.open("wb") as output:
            second = subprocess.Popen(
                command,
                cwd=project_root,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        second_state = _wait_for_child_state(
            state_path,
            second,
            excluded_pid=stale_child_pid,
        )
        replacement_pid = int(second_state["child_pid"])
        assert replacement_pid != stale_child_pid
        _wait_for_health(port, second)

        deadline = time.monotonic() + 5
        while _process_is_alive(stale_child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _process_is_alive(stale_child_pid)
        deadline = time.monotonic() + 5
        while _process_is_alive(stale_collector_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _process_is_alive(stale_collector_pid)

        events = [
            json.loads(line)
            for line in ((log_root / "latest").resolve() / "lifecycle.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert any(event["event"] == "previous_unclean_exit" for event in events)
        reclaimed = next(event for event in events if event["event"] == "stale_child_reclaimed")
        assert reclaimed["child_pid"] == stale_child_pid
        assert reclaimed["collector_pid"] == stale_collector_pid
        assert reclaimed["signal_name"] in ("SIGTERM", "SIGKILL")

        second.send_signal(signal.SIGTERM)
        assert second.wait(timeout=10) == 0
    except (AssertionError, OSError, subprocess.TimeoutExpired) as exc:
        for evidence_path in (
            first_output_path,
            second_output_path,
            state_path,
            log_root / "latest" / "lifecycle.jsonl",
        ):
            if evidence_path.exists():
                exc.add_note(
                    f"{evidence_path}:\n"
                    + evidence_path.read_text(encoding="utf-8", errors="replace")[-16_000:]
                )
        raise
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=5)
        if second is not None and second.poll() is None:
            second.send_signal(signal.SIGTERM)
            try:
                second.wait(timeout=5)
            except subprocess.TimeoutExpired:
                second.kill()
                second.wait(timeout=5)
        _kill_process_group_if_alive(stale_child_identity)
        _kill_process_if_alive(stale_collector_identity)


def test_fatal_python_exception_records_traceback_and_bounded_crash_evidence(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_root = tmp_path / "fatal-logs"
    wrapper = """
import sys
from pathlib import Path
from orchestrator.cli.server_supervisor import SupervisorConfig, run_server_supervisor

child = (
    sys.executable,
    "-c",
    "import time; time.sleep(0.1); raise RuntimeError('fatal probe marker')",
)
raise SystemExit(run_server_supervisor(SupervisorConfig(
    command=child,
    cwd=Path(sys.argv[1]),
    log_root=Path(sys.argv[1]),
    max_attempts=2,
    initial_backoff_seconds=0,
    maximum_backoff_seconds=0,
)))
"""
    process = subprocess.run(
        [sys.executable, "-c", wrapper, str(log_root)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )

    assert process.returncode == 1
    session_dir = (log_root / "latest").resolve()
    events = [
        json.loads(line)
        for line in (session_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events].count("fatal_python_exception") == 2
    exits = [event for event in events if event["event"] == "unexpected_child_exit"]
    assert [event["exit_code"] for event in exits] == [1, 1]
    assert any(event["event"] == "restart_scheduled" for event in events)
    assert events[-1]["event"] == "crash_loop_exhausted"
    process_log = (session_dir / "process.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last):" in process_log
    assert "RuntimeError: fatal probe marker" in process_log


@pytest.mark.timeout(90)
def test_child_exit_with_pipe_holding_descendant_has_bounded_collector_drain(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_root = tmp_path / "descendant-logs"
    wrapper = """
import sys
from pathlib import Path
from orchestrator.cli.server_supervisor import SupervisorConfig, run_server_supervisor

child = (
    sys.executable,
    "-c",
    "import subprocess,sys; "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "raise SystemExit(7)",
)
raise SystemExit(run_server_supervisor(SupervisorConfig(
    command=child,
    cwd=Path(sys.argv[1]),
    log_root=Path(sys.argv[1]),
    max_attempts=1,
    graceful_shutdown_seconds=0.2,
)))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", wrapper, str(log_root)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_child_state(log_root / "supervisor-state.json", process)
        assert process.wait(timeout=10) == 7
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    events = [
        json.loads(line)
        for line in ((log_root / "latest").resolve() / "lifecycle.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    timeout_event = next(
        event for event in events if event["event"] == "log_collector_drain_timeout"
    )
    assert timeout_event["signal_name"] in ("SIGTERM", "SIGKILL")
    assert "remaining process-group members: ()" in timeout_event["detail"]


@pytest.mark.timeout(90)
def test_health_supervision_restarts_live_reloader_after_serving_child_dies(
    tmp_path: Path,
) -> None:
    """A live parent cannot hide its dead/zombie HTTP-serving child."""
    project_root = Path(__file__).resolve().parents[2]
    log_root = tmp_path / "health-logs"
    serving_pid_path = tmp_path / "serving.pid"
    port = _unused_port()
    child_code = """
import subprocess
import sys
import time

server_code = '''
import http.server
import os
import sys
from pathlib import Path

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass

Path(sys.argv[2]).write_text(str(os.getpid()), encoding="utf-8")
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
'''
subprocess.Popen([sys.executable, "-c", server_code, sys.argv[1], sys.argv[2]])
while True:
    time.sleep(60)
"""
    supervisor_code = """
import sys
from pathlib import Path
from orchestrator.cli.server_supervisor import SupervisorConfig, run_server_supervisor

child = (sys.executable, "-c", sys.argv[4], sys.argv[2], sys.argv[3])
raise SystemExit(run_server_supervisor(SupervisorConfig(
    command=child,
    cwd=Path(sys.argv[1]),
    log_root=Path(sys.argv[1]),
    max_attempts=3,
    initial_backoff_seconds=0,
    maximum_backoff_seconds=0,
    graceful_shutdown_seconds=0.3,
    healthcheck_url=f"http://127.0.0.1:{sys.argv[2]}/health",
    healthcheck_interval_seconds=0.1,
    healthcheck_timeout_seconds=0.1,
    healthcheck_failure_threshold=2,
    healthcheck_startup_grace_seconds=30.0,
)))
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            supervisor_code,
            str(log_root),
            str(port),
            str(serving_pid_path),
            child_code,
        ],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    first_serving_pid: int | None = None
    replacement_serving_pid: int | None = None
    first_serving_identity: _TestProcessIdentity | None = None
    replacement_serving_identity: _TestProcessIdentity | None = None
    try:
        _wait_for_health(port, process)
        _wait_for_serving_health(
            log_root / "supervisor-state.json",
            process,
            attempt=1,
        )
        first_serving_pid = _wait_for_recorded_pid(serving_pid_path, process)
        first_serving_identity = _capture_process_identity(first_serving_pid)
        os.kill(first_serving_pid, signal.SIGKILL)

        replacement_serving_pid = _wait_for_recorded_pid(
            serving_pid_path,
            process,
            excluded_pid=first_serving_pid,
        )
        replacement_serving_identity = _capture_process_identity(replacement_serving_pid)
        _wait_for_health(port, process)
        state = _wait_for_serving_health(
            log_root / "supervisor-state.json",
            process,
            attempt=2,
        )
        assert state["attempt"] == 2
        assert state["serving_process_health"] == "healthy"

        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        _kill_process_if_alive(first_serving_identity)
        _kill_process_if_alive(replacement_serving_identity)

    events = [
        json.loads(line)
        for line in ((log_root / "latest").resolve() / "lifecycle.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(event["event"] == "serving_process_health_bound_exhausted" for event in events)
    terminated = next(event for event in events if event["event"] == "unhealthy_child_terminated")
    assert terminated["signal_name"] in ("SIGTERM", "SIGKILL")
    assert [event["event"] for event in events].count("child_started") == 2
