"""Durable process supervision for the local Orchestrator server.

The supervisor deliberately lives outside the FastAPI process.  Its evidence
therefore survives import failures, fatal signals, and failures that happen
before the application journal or database are available.
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Literal

import psutil
from pydantic import BaseModel, ConfigDict, Field


class SupervisorConfig(BaseModel):
    """Configuration for one bounded server-supervisor session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...]
    cwd: Path
    log_root: Path
    environment: dict[str, str] = Field(default_factory=dict)
    max_attempts: int = Field(default=5, ge=1)
    initial_backoff_seconds: float = Field(default=0.5, ge=0)
    maximum_backoff_seconds: float = Field(default=8.0, ge=0)
    stable_runtime_seconds: float = Field(default=60.0, ge=0)
    graceful_shutdown_seconds: float = Field(default=30.0, ge=0)


class LifecycleEvent(BaseModel):
    """One append-only supervisor observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    event: str
    session_id: str
    supervisor_pid: int
    attempt: int | None = None
    child_pid: int | None = None
    child_process_group_id: int | None = None
    collector_pid: int | None = None
    command: tuple[str, ...] | None = None
    returncode: int | None = None
    exit_code: int | None = None
    signal_number: int | None = None
    signal_name: str | None = None
    backoff_seconds: float | None = None
    previous_session_id: str | None = None
    detail: str | None = None


class SupervisorState(BaseModel):
    """Atomic latest-known state used to classify an interrupted supervisor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    session_id: str
    session_dir: str
    status: Literal["running", "stopping", "stopped", "crash_loop"]
    started_at: datetime
    updated_at: datetime
    supervisor_pid: int
    child_pid: int | None = None
    child_process_group_id: int | None = None
    child_create_time: float | None = None
    collector_pid: int | None = None
    attempt: int = 0
    consecutive_failures: int = 0
    command: tuple[str, ...]
    stop_reason: str | None = None


class ProcessIdentity(BaseModel):
    """Kernel-observed facts that distinguish a child from a reused PID."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pid: int
    process_group_id: int
    create_time: float
    command: tuple[str, ...]


class ProcessIdentityInspection(BaseModel):
    """Result of inspecting a PID without assuming it still names our child."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["available", "not_running", "unavailable"]
    identity: ProcessIdentity | None = None
    detail: str


class StaleChildReclaimResult(BaseModel):
    """Auditable outcome of attempting to reclaim one stale process group."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["not_running", "terminated", "killed", "refused", "failed"]
    child_pid: int | None
    process_group_id: int | None = None
    signal_number: int | None = None
    detail: str


class CollectorDrainResult(BaseModel):
    """Outcome of bounded output draining after a child leader exits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    timed_out: bool
    process_group_id: int
    remaining_group_members: tuple[int, ...] = ()
    signal_number: int | None = None
    detail: str


class ProcessGroupInspectionError(RuntimeError):
    """Raised when the OS will not expose members of a process group."""


def utc_now() -> datetime:
    """Return a timezone-aware timestamp (a dependency callers may replace)."""
    return datetime.now(UTC)


def restart_backoff(
    completed_attempts: int,
    *,
    initial_seconds: float,
    maximum_seconds: float,
) -> float:
    """Return capped exponential delay after ``completed_attempts`` failures."""
    if completed_attempts < 1 or initial_seconds <= 0:
        return 0.0
    return min(initial_seconds * (2 ** (completed_attempts - 1)), maximum_seconds)


def next_consecutive_failure_count(
    previous_failures: int, *, child_runtime_seconds: float, stable_runtime_seconds: float
) -> int:
    """Count a crash, forgetting older crashes after a stable child interval."""
    if child_runtime_seconds >= stable_runtime_seconds:
        return 1
    return previous_failures + 1


def process_is_alive(pid: int) -> bool:
    """Return whether a process currently exists without changing it."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def inspect_process_identity(pid: int) -> ProcessIdentityInspection:
    """Read PID identity from the kernel, including its non-reusable start time."""
    if pid <= 0:
        return ProcessIdentityInspection(
            outcome="not_running",
            detail=f"PID {pid} is not a valid process identifier",
        )
    try:
        process = psutil.Process(pid)
        with process.oneshot():
            create_time = process.create_time()
            command = tuple(process.cmdline())
            status = process.status()
        process_group_id = os.getpgid(pid)
    except (psutil.NoSuchProcess, ProcessLookupError):
        return ProcessIdentityInspection(
            outcome="not_running",
            detail=f"PID {pid} is no longer running",
        )
    except (psutil.AccessDenied, PermissionError, OSError) as exc:
        return ProcessIdentityInspection(
            outcome="unavailable",
            detail=f"could not inspect PID {pid}: {type(exc).__name__}: {exc}",
        )
    if status == psutil.STATUS_ZOMBIE:
        return ProcessIdentityInspection(
            outcome="not_running",
            detail=f"PID {pid} has exited and is awaiting reaping",
        )
    return ProcessIdentityInspection(
        outcome="available",
        identity=ProcessIdentity(
            pid=pid,
            process_group_id=process_group_id,
            create_time=create_time,
            command=command,
        ),
        detail=f"inspected PID {pid}",
    )


def stale_child_identity_matches(
    state: SupervisorState, identity: ProcessIdentity
) -> tuple[bool, str]:
    """Verify all persisted identity facts before signaling a stale PID."""
    if state.child_pid is None:
        return False, "previous state does not record a child PID"
    if state.child_process_group_id is None or state.child_create_time is None:
        return False, "previous state lacks process-group or process-start identity evidence"
    if identity.pid != state.child_pid:
        return False, f"observed PID {identity.pid} does not match recorded PID {state.child_pid}"
    if identity.process_group_id != state.child_process_group_id:
        return (
            False,
            f"PID {identity.pid} now belongs to process group {identity.process_group_id}, "
            f"not recorded group {state.child_process_group_id}",
        )
    if state.child_process_group_id != state.child_pid:
        return False, "recorded child was not the leader of its isolated process group"
    if abs(identity.create_time - state.child_create_time) > 0.001:
        return False, "PID creation time differs from the recorded child creation time"
    if identity.command != state.command:
        return False, "PID command line differs from the recorded child command"
    return True, "PID, process group, creation time, and command line all match"


def _live_process_group_members(process_group_id: int) -> tuple[int, ...]:
    members: list[int] = []
    try:
        for process in psutil.process_iter(("pid", "status")):
            try:
                pid = int(process.info["pid"])
                if process.info["status"] == psutil.STATUS_ZOMBIE:
                    continue
                if os.getpgid(pid) == process_group_id:
                    members.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
                continue
    except (psutil.AccessDenied, PermissionError, OSError) as exc:
        raise ProcessGroupInspectionError(
            f"could not inspect process group {process_group_id}: {type(exc).__name__}: {exc}"
        ) from exc
    return tuple(members)


def reclaim_stale_child(state: SupervisorState, *, grace_seconds: float) -> StaleChildReclaimResult:
    """Safely terminate a verified child process group left by a dead supervisor."""
    if state.child_pid is None:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=None,
            detail="previous state has no child PID; refusing an unverified launch overlap",
        )
    inspection = inspect_process_identity(state.child_pid)
    if inspection.outcome == "not_running":
        return StaleChildReclaimResult(
            outcome="not_running",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail=inspection.detail,
        )
    if inspection.outcome == "unavailable" or inspection.identity is None:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail=f"identity inspection unavailable; {inspection.detail}",
        )
    matches, detail = stale_child_identity_matches(state, inspection.identity)
    if not matches:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=inspection.identity.process_group_id,
            detail=f"identity verification failed; {detail}",
        )

    process_group_id = inspection.identity.process_group_id
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return StaleChildReclaimResult(
            outcome="not_running",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            detail="verified stale child exited before SIGTERM was delivered",
        )
    except PermissionError as exc:
        return StaleChildReclaimResult(
            outcome="failed",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            detail=f"SIGTERM permission denied: {exc}",
        )

    try:
        deadline = time.monotonic() + grace_seconds
        while _live_process_group_members(process_group_id) and time.monotonic() < deadline:
            time.sleep(0.05)
        graceful_survivors = _live_process_group_members(process_group_id)
    except ProcessGroupInspectionError as exc:
        return StaleChildReclaimResult(
            outcome="failed",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGTERM,
            detail=f"SIGTERM sent but exit could not be verified: {exc}",
        )
    if not graceful_survivors:
        return StaleChildReclaimResult(
            outcome="terminated",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGTERM,
            detail=f"verified stale process group exited after SIGTERM; {detail}",
        )

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return StaleChildReclaimResult(
            outcome="terminated",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGTERM,
            detail="verified stale process group exited before SIGKILL was delivered",
        )
    except PermissionError as exc:
        return StaleChildReclaimResult(
            outcome="failed",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGTERM,
            detail=f"SIGKILL permission denied after graceful timeout: {exc}",
        )

    try:
        kill_deadline = time.monotonic() + max(1.0, grace_seconds)
        while _live_process_group_members(process_group_id) and time.monotonic() < kill_deadline:
            time.sleep(0.05)
        survivors = _live_process_group_members(process_group_id)
    except ProcessGroupInspectionError as exc:
        return StaleChildReclaimResult(
            outcome="failed",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGKILL,
            detail=f"SIGKILL sent but exit could not be verified: {exc}",
        )
    if survivors:
        return StaleChildReclaimResult(
            outcome="failed",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGKILL,
            detail=f"process group still has live members after SIGKILL: {survivors}",
        )
    return StaleChildReclaimResult(
        outcome="killed",
        child_pid=state.child_pid,
        process_group_id=process_group_id,
        signal_number=signal.SIGKILL,
        detail=f"verified stale process group required SIGKILL; {detail}",
    )


def read_state(path: Path) -> SupervisorState | None:
    """Read a state document, treating partial/corrupt evidence as unavailable."""
    try:
        return SupervisorState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def previous_unclean_state(path: Path) -> SupervisorState | None:
    """Return a stale running state whose owning supervisor is now dead."""
    state = read_state(path)
    if state is None or state.status not in ("running", "stopping"):
        return None
    if process_is_alive(state.supervisor_pid):
        return None
    return state


def active_supervisor_state(path: Path) -> SupervisorState | None:
    """Return the current state when its owning supervisor is still alive."""
    state = read_state(path)
    if state is None or state.status not in ("running", "stopping"):
        return None
    if not process_is_alive(state.supervisor_pid):
        return None
    return state


class EvidenceWriter:
    """Write atomic state plus an append-only, fsynced lifecycle stream."""

    def __init__(self, *, session_dir: Path, state_path: Path) -> None:
        self.session_dir = session_dir
        self.state_path = state_path
        self.lifecycle_path = session_dir / "lifecycle.jsonl"
        self._lock = threading.Lock()
        session_dir.mkdir(parents=True, exist_ok=False)

    def append(self, event: LifecycleEvent) -> None:
        payload = event.model_dump_json(exclude_none=True) + "\n"
        with self._lock, self.lifecycle_path.open("a", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def write_state(self, state: SupervisorState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        data = state.model_dump_json(indent=2) + "\n"
        with self._lock:
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
            directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)


def _session_id(now: datetime) -> str:
    return f"{now.astimezone(UTC).strftime('%Y%m%dT%H%M%S.%fZ')}-{os.getpid()}"


def _update_latest_link(log_root: Path, session_dir: Path) -> None:
    latest = log_root / "latest"
    temporary = log_root / f".latest.{os.getpid()}.tmp"
    try:
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(session_dir.name, target_is_directory=True)
        os.replace(temporary, latest)
    finally:
        temporary.unlink(missing_ok=True)


def _exit_fields(returncode: int) -> tuple[int | None, int | None, str | None]:
    if returncode >= 0:
        return returncode, None, None
    number = -returncode
    try:
        name = signal.Signals(number).name
    except ValueError:
        name = f"SIGNAL_{number}"
    return None, number, name


def _terminate_process_group(child: subprocess.Popen[bytes], *, grace_seconds: float) -> None:
    """Bound cleanup after an internal supervisor failure."""
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        child.wait()
        return
    deadline = time.monotonic() + grace_seconds
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    child.wait()


def _stop_log_collector(collector: subprocess.Popen[bytes], *, grace_seconds: float) -> None:
    """Bound cleanup for a collector whose input pipe should already be at EOF."""
    try:
        collector.wait(timeout=max(1.0, grace_seconds))
        return
    except subprocess.TimeoutExpired:
        collector.terminate()
    try:
        collector.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        collector.kill()
        collector.wait()


def _drain_log_collector(
    collector: subprocess.Popen[bytes],
    *,
    process_group_id: int,
    grace_seconds: float,
) -> CollectorDrainResult:
    """Wait boundedly for EOF, reclaiming pipe-holding group descendants."""
    eof_grace = min(2.0, max(0.5, grace_seconds))
    try:
        returncode = collector.wait(timeout=eof_grace)
        return CollectorDrainResult(
            returncode=returncode,
            timed_out=False,
            process_group_id=process_group_id,
            detail="collector drained child output through EOF",
        )
    except subprocess.TimeoutExpired:
        pass

    signal_number: int | None = None
    try:
        members = _live_process_group_members(process_group_id)
    except ProcessGroupInspectionError:
        members = ()
    if members:
        signal_number = signal.SIGTERM
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            members = ()
        if members:
            deadline = time.monotonic() + grace_seconds
            while time.monotonic() < deadline:
                try:
                    members = _live_process_group_members(process_group_id)
                except ProcessGroupInspectionError:
                    break
                if not members:
                    break
                time.sleep(0.05)
        if members:
            signal_number = signal.SIGKILL
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                members = ()

    _stop_log_collector(collector, grace_seconds=1.0)
    try:
        remaining_members = _live_process_group_members(process_group_id)
    except ProcessGroupInspectionError:
        remaining_members = members
    return CollectorDrainResult(
        returncode=collector.returncode if collector.returncode is not None else 1,
        timed_out=True,
        process_group_id=process_group_id,
        remaining_group_members=remaining_members,
        signal_number=signal_number,
        detail=(
            "collector did not receive EOF after the child leader exited; "
            f"remaining process-group members: {remaining_members}"
        ),
    )


def _process_log_segment_contains(path: Path, *, offset: int, marker: bytes) -> bool:
    """Search only one launch attempt's durable output segment."""
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            return marker in stream.read()
    except OSError:
        return False


def run_server_supervisor(config: SupervisorConfig) -> int:
    """Run the configured child until clean shutdown or the crash-loop bound."""
    started_at = utc_now()
    session_id = _session_id(started_at)
    log_root = config.log_root.resolve()
    log_root.mkdir(parents=True, exist_ok=True)
    lock_stream = (log_root / "supervisor.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_stream.close()
        raise RuntimeError("another server supervisor owns the log directory") from exc
    state_path = log_root / "supervisor-state.json"
    active = active_supervisor_state(state_path)
    if active is not None:
        lock_stream.close()
        raise RuntimeError(
            f"server supervisor is already running with PID {active.supervisor_pid} "
            f"(session {active.session_id})"
        )
    stale = previous_unclean_state(state_path)
    session_dir = log_root / session_id
    evidence = EvidenceWriter(session_dir=session_dir, state_path=state_path)
    _update_latest_link(log_root, session_dir)

    environment = os.environ.copy()
    environment.update(config.environment)
    environment["ORCHESTRATOR_SERVER_SESSION_DIR"] = str(session_dir)
    environment["ORCHESTRATOR_SERVER_LIFECYCLE_LOG"] = str(evidence.lifecycle_path)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONFAULTHANDLER"] = "1"
    environment.setdefault("LOG_AUTO_CONFIG", "false")

    supervisor_pid = os.getpid()
    base_state = SupervisorState(
        session_id=session_id,
        session_dir=str(session_dir),
        status="running",
        started_at=started_at,
        updated_at=started_at,
        supervisor_pid=supervisor_pid,
        command=config.command,
    )
    evidence.append(
        LifecycleEvent(
            timestamp=started_at,
            event="supervisor_started",
            session_id=session_id,
            supervisor_pid=supervisor_pid,
            command=config.command,
        )
    )
    if stale is not None:
        evidence.append(
            LifecycleEvent(
                timestamp=utc_now(),
                event="previous_unclean_exit",
                session_id=session_id,
                supervisor_pid=supervisor_pid,
                previous_session_id=stale.session_id,
                child_pid=stale.child_pid,
                collector_pid=stale.collector_pid,
                attempt=stale.attempt,
                detail=f"previous supervisor PID {stale.supervisor_pid} is not running",
            )
        )

    child: subprocess.Popen[bytes] | None = None
    collector: subprocess.Popen[bytes] | None = None
    requested_signal: int | None = None
    shutdown_requested_at: float | None = None

    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        nonlocal requested_signal, shutdown_requested_at
        requested_signal = signum
        if shutdown_requested_at is None:
            shutdown_requested_at = time.monotonic()
        active_child = child
        if active_child is not None and active_child.poll() is None:
            try:
                os.killpg(active_child.pid, signum)
            except ProcessLookupError:
                pass

    previous_handlers = {
        signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    for signum in previous_handlers:
        signal.signal(signum, request_shutdown)

    try:
        if stale is not None:
            reclaim = reclaim_stale_child(
                stale,
                grace_seconds=config.graceful_shutdown_seconds,
            )
            if reclaim.outcome in ("terminated", "killed"):
                reclaim_event = "stale_child_reclaimed"
            elif reclaim.outcome == "not_running":
                reclaim_event = "stale_child_not_running"
            else:
                reclaim_event = "stale_child_reclaim_refused"
            evidence.append(
                LifecycleEvent(
                    timestamp=utc_now(),
                    event=reclaim_event,
                    session_id=session_id,
                    supervisor_pid=supervisor_pid,
                    previous_session_id=stale.session_id,
                    child_pid=reclaim.child_pid,
                    child_process_group_id=reclaim.process_group_id,
                    collector_pid=stale.collector_pid,
                    signal_number=reclaim.signal_number,
                    signal_name=(
                        signal.Signals(reclaim.signal_number).name
                        if reclaim.signal_number is not None
                        else None
                    ),
                    detail=reclaim.detail,
                )
            )
            if reclaim.outcome in ("refused", "failed"):
                reason = f"stale_child_reclaim_{reclaim.outcome}"
                stopped = base_state.model_copy(
                    update={
                        "status": "stopped",
                        "updated_at": utc_now(),
                        "stop_reason": reason,
                    }
                )
                evidence.write_state(stopped)
                evidence.append(
                    LifecycleEvent(
                        timestamp=utc_now(),
                        event="supervisor_start_aborted",
                        session_id=session_id,
                        supervisor_pid=supervisor_pid,
                        previous_session_id=stale.session_id,
                        child_pid=reclaim.child_pid,
                        detail=reason,
                    )
                )
                return 1

        evidence.write_state(base_state)
        process_log_path = session_dir / "process.log"
        launch_attempt = 0
        consecutive_failures = 0
        while True:
            if requested_signal is not None:
                break
            launch_attempt += 1
            now = utc_now()
            child_started_monotonic = time.monotonic()
            attempt_log_offset = process_log_path.stat().st_size if process_log_path.exists() else 0
            child = subprocess.Popen(
                config.command,
                cwd=config.cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            assert child.stdout is not None
            collector = subprocess.Popen(
                (
                    sys.executable,
                    "-m",
                    "orchestrator.cli.server_log_collector",
                    str(process_log_path),
                ),
                cwd=config.cwd,
                env=environment,
                stdin=child.stdout,
            )
            # Only the independent collector may retain the pipe's read end.
            # Closing this copy is what lets it survive a supervisor SIGKILL.
            child.stdout.close()
            identity_inspection = inspect_process_identity(child.pid)
            if identity_inspection.outcome == "unavailable":
                _terminate_process_group(
                    child,
                    grace_seconds=config.graceful_shutdown_seconds,
                )
                _stop_log_collector(
                    collector,
                    grace_seconds=config.graceful_shutdown_seconds,
                )
                child = None
                collector = None
                stopped = base_state.model_copy(
                    update={
                        "status": "stopped",
                        "updated_at": utc_now(),
                        "stop_reason": "child_identity_capture_failed",
                    }
                )
                evidence.write_state(stopped)
                evidence.append(
                    LifecycleEvent(
                        timestamp=utc_now(),
                        event="child_identity_capture_failed",
                        session_id=session_id,
                        supervisor_pid=supervisor_pid,
                        attempt=launch_attempt,
                        detail=identity_inspection.detail,
                    )
                )
                return 1
            child_identity = identity_inspection.identity
            running_state = base_state.model_copy(
                update={
                    "updated_at": now,
                    "attempt": launch_attempt,
                    "consecutive_failures": consecutive_failures,
                    "child_pid": child.pid,
                    "child_process_group_id": (
                        child_identity.process_group_id if child_identity is not None else None
                    ),
                    "child_create_time": (
                        child_identity.create_time if child_identity is not None else None
                    ),
                    "collector_pid": collector.pid,
                }
            )
            evidence.write_state(running_state)
            evidence.append(
                LifecycleEvent(
                    timestamp=now,
                    event="child_started",
                    session_id=session_id,
                    supervisor_pid=supervisor_pid,
                    attempt=launch_attempt,
                    child_pid=child.pid,
                    child_process_group_id=(
                        child_identity.process_group_id if child_identity is not None else None
                    ),
                    collector_pid=collector.pid,
                    command=config.command,
                )
            )
            forced_shutdown = False
            collector_exited_early = False
            while child.poll() is None:
                if collector.poll() is not None:
                    collector_exited_early = True
                    evidence.append(
                        LifecycleEvent(
                            timestamp=utc_now(),
                            event="log_collector_exited_early",
                            session_id=session_id,
                            supervisor_pid=supervisor_pid,
                            attempt=launch_attempt,
                            child_pid=child.pid,
                            child_process_group_id=child.pid,
                            collector_pid=collector.pid,
                            returncode=collector.returncode,
                            detail="collector exited while the server child was still running",
                        )
                    )
                    _terminate_process_group(
                        child,
                        grace_seconds=config.graceful_shutdown_seconds,
                    )
                    break
                if requested_signal is not None and shutdown_requested_at is not None:
                    shutdown_elapsed = time.monotonic() - shutdown_requested_at
                    if shutdown_elapsed >= config.graceful_shutdown_seconds:
                        evidence.append(
                            LifecycleEvent(
                                timestamp=utc_now(),
                                event="graceful_shutdown_timeout",
                                session_id=session_id,
                                supervisor_pid=supervisor_pid,
                                attempt=launch_attempt,
                                child_pid=child.pid,
                                signal_number=signal.SIGKILL,
                                signal_name=signal.Signals(signal.SIGKILL).name,
                                detail=(
                                    f"child process group exceeded "
                                    f"{config.graceful_shutdown_seconds}s grace period"
                                ),
                            )
                        )
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        forced_shutdown = True
                        break
                time.sleep(0.05)
            returncode = child.wait()
            process_group_id = (
                child_identity.process_group_id if child_identity is not None else child.pid
            )
            drain = _drain_log_collector(
                collector,
                process_group_id=process_group_id,
                grace_seconds=config.graceful_shutdown_seconds,
            )
            if drain.timed_out:
                evidence.append(
                    LifecycleEvent(
                        timestamp=utc_now(),
                        event="log_collector_drain_timeout",
                        session_id=session_id,
                        supervisor_pid=supervisor_pid,
                        attempt=launch_attempt,
                        child_pid=child.pid,
                        child_process_group_id=process_group_id,
                        collector_pid=collector.pid,
                        returncode=drain.returncode,
                        signal_number=drain.signal_number,
                        signal_name=(
                            signal.Signals(drain.signal_number).name
                            if drain.signal_number is not None
                            else None
                        ),
                        detail=drain.detail,
                    )
                )
            elif drain.returncode != 0 and not collector_exited_early:
                evidence.append(
                    LifecycleEvent(
                        timestamp=utc_now(),
                        event="log_collector_failed",
                        session_id=session_id,
                        supervisor_pid=supervisor_pid,
                        attempt=launch_attempt,
                        child_pid=child.pid,
                        child_process_group_id=process_group_id,
                        collector_pid=collector.pid,
                        returncode=drain.returncode,
                        detail="collector exited non-zero after draining server output",
                    )
                )
            child = None
            collector = None
            exit_code, signal_number, signal_name = _exit_fields(returncode)

            child_runtime = time.monotonic() - child_started_monotonic
            fatal_python_traceback_seen = _process_log_segment_contains(
                process_log_path,
                offset=attempt_log_offset,
                marker=b"Traceback (most recent call last):",
            )
            if requested_signal is None and fatal_python_traceback_seen:
                evidence.append(
                    LifecycleEvent(
                        timestamp=utc_now(),
                        event="fatal_python_exception",
                        session_id=session_id,
                        supervisor_pid=supervisor_pid,
                        attempt=launch_attempt,
                        returncode=returncode,
                        exit_code=exit_code,
                        signal_number=signal_number,
                        signal_name=signal_name,
                        detail="child exited after emitting a Python traceback",
                    )
                )
            if requested_signal is not None:
                if forced_shutdown:
                    event_name = "forced_shutdown"
                    stop_reason = "graceful_shutdown_timeout"
                else:
                    event_name = "clean_shutdown"
                    stop_reason = f"supervisor_received_{signal.Signals(requested_signal).name}"
            else:
                event_name = "unexpected_child_exit"
                stop_reason = (
                    "log_collector_exited_early"
                    if collector_exited_early
                    else "unexpected_child_exit"
                )
            evidence.append(
                LifecycleEvent(
                    timestamp=utc_now(),
                    event=event_name,
                    session_id=session_id,
                    supervisor_pid=supervisor_pid,
                    attempt=launch_attempt,
                    returncode=returncode,
                    exit_code=exit_code,
                    signal_number=signal_number,
                    signal_name=signal_name,
                    detail=stop_reason,
                )
            )

            if requested_signal is not None:
                stopped = running_state.model_copy(
                    update={
                        "status": "stopped",
                        "updated_at": utc_now(),
                        "child_pid": None,
                        "child_process_group_id": None,
                        "child_create_time": None,
                        "collector_pid": None,
                        "stop_reason": stop_reason,
                    }
                )
                evidence.write_state(stopped)
                # Uvicorn deliberately re-raises its captured signal after
                # completing lifespan shutdown, so a negative return code
                # can still represent a clean, fully drained stop. Preserve
                # that exact code in evidence while reporting success to
                # the operator unless the grace deadline forced SIGKILL.
                return 128 + requested_signal if forced_shutdown else 0

            was_stable = child_runtime >= config.stable_runtime_seconds
            if was_stable:
                if consecutive_failures:
                    evidence.append(
                        LifecycleEvent(
                            timestamp=utc_now(),
                            event="crash_counter_reset",
                            session_id=session_id,
                            supervisor_pid=supervisor_pid,
                            attempt=launch_attempt,
                            detail=f"child remained up for {child_runtime:.3f}s",
                        )
                    )
            consecutive_failures = next_consecutive_failure_count(
                consecutive_failures,
                child_runtime_seconds=child_runtime,
                stable_runtime_seconds=config.stable_runtime_seconds,
            )

            if consecutive_failures >= config.max_attempts:
                crashed = running_state.model_copy(
                    update={
                        "status": "crash_loop",
                        "updated_at": utc_now(),
                        "child_pid": None,
                        "child_process_group_id": None,
                        "child_create_time": None,
                        "collector_pid": None,
                        "consecutive_failures": consecutive_failures,
                        "stop_reason": "maximum_restart_attempts_exhausted",
                    }
                )
                evidence.write_state(crashed)
                evidence.append(
                    LifecycleEvent(
                        timestamp=utc_now(),
                        event="crash_loop_exhausted",
                        session_id=session_id,
                        supervisor_pid=supervisor_pid,
                        attempt=launch_attempt,
                        returncode=returncode,
                        exit_code=exit_code,
                        signal_number=signal_number,
                        signal_name=signal_name,
                    )
                )
                return returncode if returncode > 0 else 1

            delay = restart_backoff(
                consecutive_failures,
                initial_seconds=config.initial_backoff_seconds,
                maximum_seconds=config.maximum_backoff_seconds,
            )
            evidence.append(
                LifecycleEvent(
                    timestamp=utc_now(),
                    event="restart_scheduled",
                    session_id=session_id,
                    supervisor_pid=supervisor_pid,
                    attempt=launch_attempt,
                    backoff_seconds=delay,
                )
            )
            deadline = time.monotonic() + delay
            while requested_signal is None and time.monotonic() < deadline:
                time.sleep(min(0.1, deadline - time.monotonic()))

        stopped = base_state.model_copy(
            update={
                "status": "stopped",
                "updated_at": utc_now(),
                "stop_reason": "shutdown_before_child_start",
            }
        )
        evidence.write_state(stopped)
        evidence.append(
            LifecycleEvent(
                timestamp=utc_now(),
                event="clean_shutdown",
                session_id=session_id,
                supervisor_pid=supervisor_pid,
                signal_number=requested_signal,
                signal_name=(
                    signal.Signals(requested_signal).name if requested_signal is not None else None
                ),
            )
        )
        return 0
    finally:
        if child is not None and child.poll() is None:
            _terminate_process_group(child, grace_seconds=config.graceful_shutdown_seconds)
        if collector is not None:
            _stop_log_collector(collector, grace_seconds=config.graceful_shutdown_seconds)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()
