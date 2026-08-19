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
from pathlib import Path


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 20
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
    deadline = time.monotonic() + 20
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
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill_process_group_if_alive(pid: int | None) -> None:
    if pid is None or not _process_is_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _kill_process_if_alive(pid: int | None) -> None:
    if pid is None or not _process_is_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGKILL)
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
    shutdown = next(event for event in events if event["event"] == "clean_shutdown")
    assert shutdown["detail"] == "supervisor_received_SIGTERM"
    assert "Server lifespan ready" in (session_dir / "process.log").read_text(encoding="utf-8")
    state = json.loads((log_root / "supervisor-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert state["stop_reason"] == "supervisor_received_SIGTERM"


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
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("child_pid") and ready_path.exists():
                    break
            time.sleep(0.05)
        else:
            raise AssertionError("supervisor child did not install its SIGTERM handler")
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 128 + signal.SIGTERM
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


def test_relaunch_reclaims_child_orphaned_by_supervisor_sigkill(tmp_path: Path) -> None:
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
    first = subprocess.Popen(
        command,
        cwd=project_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    second: subprocess.Popen[bytes] | None = None
    stale_child_pid: int | None = None
    stale_collector_pid: int | None = None
    try:
        _wait_for_health(port, first)
        first_state = _wait_for_child_state(state_path, first)
        stale_child_pid = int(first_state["child_pid"])
        stale_collector_pid = int(first_state["collector_pid"])
        assert first_state["child_process_group_id"] == stale_child_pid
        assert isinstance(first_state["child_create_time"], float)
        assert _process_is_alive(stale_collector_pid)
        first.send_signal(signal.SIGKILL)
        assert first.wait(timeout=5) == -signal.SIGKILL
        assert _process_is_alive(stale_child_pid)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            assert response.status == 200

        second = subprocess.Popen(
            command,
            cwd=project_root,
            env=environment,
            stdout=subprocess.DEVNULL,
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
        _kill_process_group_if_alive(stale_child_pid)
        _kill_process_if_alive(stale_collector_pid)


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
    process = subprocess.run(
        [sys.executable, "-c", wrapper, str(log_root)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        timeout=5,
        check=False,
    )

    assert process.returncode == 7
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
