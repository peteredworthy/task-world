"""Durable process supervision for the local Orchestrator server.

The supervisor deliberately lives outside the FastAPI process.  Its evidence
therefore survives import failures, fatal signals, and failures that happen
before the application journal or database are available.
"""

from __future__ import annotations

import fcntl
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Literal

import psutil
from pydantic import BaseModel, ConfigDict, Field


_LOG_COLLECTOR_READY_TIMEOUT_SECONDS = 30.0


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
    healthcheck_url: str | None = None
    healthcheck_interval_seconds: float = Field(default=1.0, gt=0)
    healthcheck_timeout_seconds: float = Field(default=1.0, gt=0)
    healthcheck_failure_threshold: int = Field(default=5, ge=1)
    healthcheck_startup_grace_seconds: float = Field(default=30.0, ge=0)


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
    healthcheck_url: str | None = None
    consecutive_health_failures: int | None = None


class SupervisorState(BaseModel):
    """Atomic latest-known state used to classify an interrupted supervisor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    session_id: str
    session_dir: str
    status: Literal["running", "stopping", "stopped", "crash_loop", "abrupt_supervisor_loss"]
    started_at: datetime
    updated_at: datetime
    supervisor_pid: int
    supervisor_process_group_id: int | None = None
    supervisor_create_time: float | None = None
    supervisor_command: tuple[str, ...] | None = None
    child_pid: int | None = None
    child_process_group_id: int | None = None
    child_create_time: float | None = None
    collector_pid: int | None = None
    collector_process_group_id: int | None = None
    collector_create_time: float | None = None
    collector_command: tuple[str, ...] | None = None
    collector_health: Literal["running", "drained", "failed", "unknown"] = "unknown"
    serving_process_health: Literal[
        "starting", "healthy", "unhealthy", "not_configured", "unknown"
    ] = "unknown"
    last_health_check_at: datetime | None = None
    consecutive_health_failures: int = 0
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


class SupervisorIdentityEvidence(BaseModel):
    """Bounded operator evidence for the persisted supervisor identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded_process_group_id: int | None
    observed_process_group_id: int | None
    identity_verified: bool
    liveness: Literal[
        "verified_live",
        "not_running",
        "identity_mismatch",
        "inspection_unavailable",
        "incomplete_recorded_identity",
    ]
    detail: str


class StaleChildReclaimResult(BaseModel):
    """Auditable outcome of attempting to reclaim one stale process group."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["not_running", "terminated", "killed", "refused", "failed"]
    child_pid: int | None
    process_group_id: int | None = None
    signal_number: int | None = None
    detail: str


class VerifiedServingChildCrashResult(BaseModel):
    """Auditable result of an operator-authorized serving-child crash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["signaled", "refused"]
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


class HealthcheckResult(BaseModel):
    """One bounded HTTP health observation made outside the serving process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    healthy: bool
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
        status = process.status()
        if status == psutil.STATUS_ZOMBIE:
            return ProcessIdentityInspection(
                outcome="not_running",
                detail=f"PID {pid} has exited and is awaiting reaping",
            )
        create_time = process.create_time()
        if process.status() == psutil.STATUS_ZOMBIE:
            return ProcessIdentityInspection(
                outcome="not_running",
                detail=f"PID {pid} has exited and is awaiting reaping",
            )
        command = tuple(process.cmdline())
        process_group_id = os.getpgid(pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
        return ProcessIdentityInspection(
            outcome="not_running",
            detail=f"PID {pid} is no longer running",
        )
    except psutil.AccessDenied as exc:
        cause = exc.__cause__
        if cause is not None and type(cause).__name__ == "ZombieProcessError":
            return ProcessIdentityInspection(
                outcome="not_running",
                detail=f"PID {pid} has exited and is awaiting reaping",
            )
        for _attempt in range(5):
            try:
                if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                    return ProcessIdentityInspection(
                        outcome="not_running",
                        detail=f"PID {pid} has exited and is awaiting reaping",
                    )
            except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
                return ProcessIdentityInspection(
                    outcome="not_running",
                    detail=f"PID {pid} is no longer running",
                )
            except (psutil.AccessDenied, PermissionError, OSError):
                pass
            time.sleep(0.01)
        return ProcessIdentityInspection(
            outcome="unavailable",
            detail=f"could not inspect PID {pid}: {type(exc).__name__}: {exc}",
        )
    except (PermissionError, OSError) as exc:
        return ProcessIdentityInspection(
            outcome="unavailable",
            detail=f"could not inspect PID {pid}: {type(exc).__name__}: {exc}",
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


def process_identity_matches(
    expected: ProcessIdentity, observed: ProcessIdentity
) -> tuple[bool, str]:
    """Compare every kernel/process fact used to authorize a signal."""
    if observed.pid != expected.pid:
        return False, f"observed PID {observed.pid} does not match recorded PID {expected.pid}"
    if observed.process_group_id != expected.process_group_id:
        return False, (
            f"PID {observed.pid} now belongs to process group {observed.process_group_id}, "
            f"not recorded group {expected.process_group_id}"
        )
    if abs(observed.create_time - expected.create_time) > 0.001:
        return False, "PID creation time differs from the recorded process creation time"
    if observed.command != expected.command:
        return False, "PID command line differs from the recorded process command"
    return True, "PID, process group, creation time, and command line all match"


def inspect_supervisor_identity(state: SupervisorState) -> SupervisorIdentityEvidence:
    """Compare the live supervisor identity only with persisted identity facts."""
    inspection = inspect_process_identity(state.supervisor_pid)
    observed_process_group_id = (
        inspection.identity.process_group_id if inspection.identity is not None else None
    )
    if inspection.outcome == "not_running":
        return SupervisorIdentityEvidence(
            recorded_process_group_id=state.supervisor_process_group_id,
            observed_process_group_id=observed_process_group_id,
            identity_verified=False,
            liveness="not_running",
            detail=inspection.detail,
        )
    if inspection.outcome == "unavailable" or inspection.identity is None:
        return SupervisorIdentityEvidence(
            recorded_process_group_id=state.supervisor_process_group_id,
            observed_process_group_id=observed_process_group_id,
            identity_verified=False,
            liveness="inspection_unavailable",
            detail=inspection.detail,
        )
    if (
        state.supervisor_process_group_id is None
        or state.supervisor_create_time is None
        or state.supervisor_command is None
    ):
        return SupervisorIdentityEvidence(
            recorded_process_group_id=state.supervisor_process_group_id,
            observed_process_group_id=observed_process_group_id,
            identity_verified=False,
            liveness="incomplete_recorded_identity",
            detail="persisted supervisor process-group, creation-time, or command evidence is missing",
        )
    expected = ProcessIdentity(
        pid=state.supervisor_pid,
        process_group_id=state.supervisor_process_group_id,
        create_time=state.supervisor_create_time,
        command=state.supervisor_command,
    )
    matches, detail = process_identity_matches(expected, inspection.identity)
    return SupervisorIdentityEvidence(
        recorded_process_group_id=state.supervisor_process_group_id,
        observed_process_group_id=observed_process_group_id,
        identity_verified=matches,
        liveness="verified_live" if matches else "identity_mismatch",
        detail=detail,
    )


def stale_child_identity_matches(
    state: SupervisorState, identity: ProcessIdentity
) -> tuple[bool, str]:
    """Verify all persisted identity facts before signaling a stale PID."""
    if state.child_pid is None:
        return False, "previous state does not record a child PID"
    if state.child_process_group_id is None or state.child_create_time is None:
        return False, "previous state lacks process-group or process-start identity evidence"
    if state.child_process_group_id != state.child_pid:
        return False, "recorded child was not the leader of its isolated process group"
    expected = ProcessIdentity(
        pid=state.child_pid,
        process_group_id=state.child_process_group_id,
        create_time=state.child_create_time,
        command=state.command,
    )
    return process_identity_matches(expected, identity)


def crash_verified_serving_child(
    state: SupervisorState,
    *,
    reached_owner_pid: int,
    reached_owner_create_time: float,
) -> VerifiedServingChildCrashResult:
    """SIGKILL only the reached barrier's exactly verified serving child group."""
    if state.status != "running":
        return VerifiedServingChildCrashResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail="official supervisor state is not running",
        )
    supervisor = inspect_supervisor_identity(state)
    if not supervisor.identity_verified:
        return VerifiedServingChildCrashResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail=f"official supervisor identity is not verified: {supervisor.detail}",
        )
    if (
        state.child_pid is None
        or state.child_process_group_id is None
        or state.child_create_time is None
        or state.child_pid != state.child_process_group_id
    ):
        return VerifiedServingChildCrashResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail="official serving-child identity is incomplete or not group-isolated",
        )
    if state.child_pid != reached_owner_pid or (
        abs(state.child_create_time - reached_owner_create_time) > 0.001
    ):
        return VerifiedServingChildCrashResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail="reached barrier owner does not equal the official serving child identity",
        )
    inspection = inspect_process_identity(state.child_pid)
    if inspection.outcome != "available" or inspection.identity is None:
        return VerifiedServingChildCrashResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail=f"serving child cannot be verified: {inspection.detail}",
        )
    matches, detail = stale_child_identity_matches(state, inspection.identity)
    if not matches:
        return VerifiedServingChildCrashResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail=f"serving child identity mismatch: {detail}",
        )
    try:
        os.killpg(state.child_process_group_id, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        return VerifiedServingChildCrashResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=state.child_process_group_id,
            detail=f"verified serving child could not be signaled: {type(exc).__name__}: {exc}",
        )
    return VerifiedServingChildCrashResult(
        outcome="signaled",
        child_pid=state.child_pid,
        process_group_id=state.child_process_group_id,
        signal_number=signal.SIGKILL,
        detail="sent SIGKILL to the exactly verified serving-child process group",
    )


def _reap_child_if_owned(pid: int) -> None:
    """Reap a terminated process when this process happens to be its parent."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, ProcessLookupError):
        pass


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


def check_http_health(url: str, *, timeout_seconds: float) -> HealthcheckResult:
    """Perform one bounded HTTP request, accepting only a 2xx response."""
    request = urllib.request.Request(url, headers={"Connection": "close"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        return HealthcheckResult(
            healthy=False,
            detail=f"{type(exc).__name__}: {exc}",
        )
    if 200 <= status < 300:
        return HealthcheckResult(healthy=True, detail=f"HTTP {status}")
    return HealthcheckResult(healthy=False, detail=f"HTTP {status}")


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
        if state.child_process_group_id is None:
            return StaleChildReclaimResult(
                outcome="refused",
                child_pid=state.child_pid,
                detail=(
                    f"{inspection.detail}; previous state has no process-group identity, "
                    "so descendant liveness cannot be checked"
                ),
            )
        try:
            live_members = _live_process_group_members(state.child_process_group_id)
        except ProcessGroupInspectionError as exc:
            return StaleChildReclaimResult(
                outcome="refused",
                child_pid=state.child_pid,
                process_group_id=state.child_process_group_id,
                detail=f"{inspection.detail}; descendant liveness is unavailable: {exc}",
            )
        if live_members:
            return StaleChildReclaimResult(
                outcome="refused",
                child_pid=state.child_pid,
                process_group_id=state.child_process_group_id,
                detail=(
                    f"{inspection.detail}, but recorded process group "
                    f"{state.child_process_group_id} still has live members {live_members}; "
                    "leader identity cannot authorize signaling those descendants"
                ),
            )
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
            _reap_child_if_owned(state.child_pid)
            time.sleep(0.05)
        _reap_child_if_owned(state.child_pid)
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

    escalation = inspect_process_identity(state.child_pid)
    if escalation.outcome == "not_running":
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGTERM,
            detail=(
                f"leader identity disappeared after SIGTERM while recorded group "
                f"still has live members {graceful_survivors}; refusing SIGKILL"
            ),
        )
    if escalation.outcome != "available" or escalation.identity is None:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGTERM,
            detail=(
                "leader identity inspection unavailable immediately before SIGKILL; "
                f"{escalation.detail}"
            ),
        )
    escalation_matches, escalation_detail = stale_child_identity_matches(state, escalation.identity)
    if not escalation_matches:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.child_pid,
            process_group_id=process_group_id,
            signal_number=signal.SIGTERM,
            detail=(f"leader identity changed immediately before SIGKILL; {escalation_detail}"),
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
            _reap_child_if_owned(state.child_pid)
            time.sleep(0.05)
        _reap_child_if_owned(state.child_pid)
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


def reclaim_stale_collector(
    state: SupervisorState, *, grace_seconds: float
) -> StaleChildReclaimResult:
    """Terminate an orphaned collector PID without signaling its shared process group."""
    if state.collector_pid is None:
        return StaleChildReclaimResult(
            outcome="not_running",
            child_pid=None,
            detail="previous state has no collector PID",
        )
    # Inspect the recorded PID before requiring historical identity metadata.
    # Legacy state may legitimately lack that metadata; if the kernel proves
    # the PID is already absent, there is nothing to signal and therefore no
    # identity ambiguity to fail closed on. Live or uninspectable processes
    # still require the complete identity before any signal is permitted.
    initial_inspection = inspect_process_identity(state.collector_pid)
    if initial_inspection.outcome == "not_running":
        return StaleChildReclaimResult(
            outcome="not_running",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            detail=initial_inspection.detail,
        )
    if initial_inspection.outcome != "available" or initial_inspection.identity is None:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            detail=(
                "collector identity inspection unavailable before reclaim; "
                f"{initial_inspection.detail}"
            ),
        )
    if (
        state.collector_process_group_id is None
        or state.collector_create_time is None
        or state.collector_command is None
    ):
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            detail=("collector PID is live but identity evidence is unavailable or incomplete"),
        )
    expected = ProcessIdentity(
        pid=state.collector_pid,
        process_group_id=state.collector_process_group_id,
        create_time=state.collector_create_time,
        command=state.collector_command,
    )

    def inspect_expected(*, before_signal: str) -> tuple[ProcessIdentity | None, str]:
        inspection = inspect_process_identity(expected.pid)
        if inspection.outcome == "not_running":
            return None, inspection.detail
        if inspection.outcome != "available" or inspection.identity is None:
            raise ProcessGroupInspectionError(
                f"collector identity inspection unavailable {before_signal}; {inspection.detail}"
            )
        matches, match_detail = process_identity_matches(expected, inspection.identity)
        if not matches:
            raise ProcessGroupInspectionError(
                f"collector identity changed {before_signal}; {match_detail}"
            )
        return inspection.identity, match_detail

    try:
        inspection_identity, detail = inspect_expected(before_signal="immediately before SIGTERM")
    except ProcessGroupInspectionError as exc:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            detail=str(exc),
        )
    if inspection_identity is None:
        return StaleChildReclaimResult(
            outcome="not_running",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            detail=detail,
        )
    try:
        os.kill(state.collector_pid, signal.SIGTERM)
    except ProcessLookupError:
        return StaleChildReclaimResult(
            outcome="not_running",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            detail="verified stale collector exited before SIGTERM was delivered",
        )
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            observed_identity, observed_detail = inspect_expected(
                before_signal="while awaiting SIGTERM"
            )
        except ProcessGroupInspectionError as exc:
            return StaleChildReclaimResult(
                outcome="refused",
                child_pid=state.collector_pid,
                process_group_id=state.collector_process_group_id,
                signal_number=signal.SIGTERM,
                detail=f"SIGTERM was delivered, but {exc}",
            )
        if observed_identity is None:
            return StaleChildReclaimResult(
                outcome="terminated",
                child_pid=state.collector_pid,
                process_group_id=state.collector_process_group_id,
                signal_number=signal.SIGTERM,
                detail=(
                    f"verified stale collector exited after SIGTERM; {detail}; {observed_detail}"
                ),
            )
        time.sleep(0.05)
    try:
        kill_identity, kill_detail = inspect_expected(before_signal="immediately before SIGKILL")
    except ProcessGroupInspectionError as exc:
        return StaleChildReclaimResult(
            outcome="refused",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            signal_number=signal.SIGTERM,
            detail=f"SIGTERM was delivered, but {exc}; refusing SIGKILL",
        )
    if kill_identity is None:
        return StaleChildReclaimResult(
            outcome="terminated",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            signal_number=signal.SIGTERM,
            detail=f"verified stale collector exited before SIGKILL; {kill_detail}",
        )
    try:
        os.kill(state.collector_pid, signal.SIGKILL)
    except ProcessLookupError:
        return StaleChildReclaimResult(
            outcome="terminated",
            child_pid=state.collector_pid,
            process_group_id=state.collector_process_group_id,
            signal_number=signal.SIGTERM,
            detail="verified stale collector exited before SIGKILL was delivered",
        )
    kill_deadline = time.monotonic() + max(1.0, grace_seconds)
    while time.monotonic() < kill_deadline:
        try:
            observed_identity, observed_detail = inspect_expected(
                before_signal="while awaiting SIGKILL"
            )
        except ProcessGroupInspectionError as exc:
            return StaleChildReclaimResult(
                outcome="refused",
                child_pid=state.collector_pid,
                process_group_id=state.collector_process_group_id,
                signal_number=signal.SIGKILL,
                detail=f"SIGKILL was delivered, but {exc}",
            )
        if observed_identity is None:
            return StaleChildReclaimResult(
                outcome="killed",
                child_pid=state.collector_pid,
                process_group_id=state.collector_process_group_id,
                signal_number=signal.SIGKILL,
                detail=(f"verified stale collector required SIGKILL; {detail}; {observed_detail}"),
            )
        time.sleep(0.05)
    return StaleChildReclaimResult(
        outcome="failed",
        child_pid=state.collector_pid,
        process_group_id=state.collector_process_group_id,
        signal_number=signal.SIGKILL,
        detail="verified stale collector remained live after SIGKILL",
    )


def read_state(path: Path) -> SupervisorState | None:
    """Read and verify state, classifying dead/reused supervisors as abrupt loss."""
    try:
        state = SupervisorState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if state.status not in ("running", "stopping"):
        return state
    identity_evidence = inspect_supervisor_identity(state)
    if identity_evidence.identity_verified:
        return state
    return state.model_copy(
        update={
            "status": "abrupt_supervisor_loss",
            "stop_reason": "abrupt_supervisor_loss",
            "serving_process_health": "unknown",
            "collector_health": "unknown",
        }
    )


def previous_unclean_state(path: Path) -> SupervisorState | None:
    """Return a stale running state whose owning supervisor is now dead."""
    state = read_state(path)
    if state is None or state.status != "abrupt_supervisor_loss":
        return None
    return state


def active_supervisor_state(path: Path) -> SupervisorState | None:
    """Return state only when the supervisor's complete identity is verified."""
    state = read_state(path)
    if state is None or state.status not in ("running", "stopping"):
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


def _terminate_verified_process_group(
    child: subprocess.Popen[bytes],
    *,
    identity: ProcessIdentity,
    grace_seconds: float,
) -> tuple[bool, int | None, str]:
    """Terminate a child group only after its non-reusable identity still matches."""
    inspection = inspect_process_identity(child.pid)
    if inspection.outcome == "not_running":
        child.wait()
        return True, None, inspection.detail
    if inspection.outcome != "available" or inspection.identity is None:
        return False, None, f"identity inspection unavailable; {inspection.detail}"
    matches, detail = process_identity_matches(identity, inspection.identity)
    if not matches or identity.process_group_id != identity.pid:
        return False, None, f"identity verification failed; {detail}"
    try:
        os.killpg(identity.process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        child.wait()
        return True, None, "verified child exited before SIGTERM was delivered"
    deadline = time.monotonic() + grace_seconds
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if child.poll() is not None:
        child.wait()
        return True, signal.SIGTERM, f"verified child group terminated; {detail}"
    escalation = inspect_process_identity(child.pid)
    if escalation.outcome != "available" or escalation.identity is None:
        return (
            False,
            signal.SIGTERM,
            "child identity could not be reverified immediately before SIGKILL; "
            f"{escalation.detail}",
        )
    escalation_matches, escalation_detail = process_identity_matches(identity, escalation.identity)
    if not escalation_matches:
        return (
            False,
            signal.SIGTERM,
            "child identity changed immediately before SIGKILL; " + escalation_detail,
        )
    try:
        os.killpg(identity.process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        child.wait()
        return True, signal.SIGTERM, "verified child exited before SIGKILL was delivered"
    child.wait()
    return True, signal.SIGKILL, f"verified child group required SIGKILL; {detail}"


def _stop_log_collector(collector: subprocess.Popen[bytes], *, grace_seconds: float) -> int | None:
    """Bound cleanup for a collector and return the signal we delivered, if any."""
    try:
        collector.wait(timeout=max(1.0, grace_seconds))
        return None
    except subprocess.TimeoutExpired:
        collector.terminate()
    try:
        collector.wait(timeout=1.0)
        return signal.SIGTERM
    except subprocess.TimeoutExpired:
        collector.kill()
        collector.wait()
        return signal.SIGKILL


def _await_log_collector_ready(
    collector: subprocess.Popen[bytes], ready_fd: int, *, timeout_seconds: float
) -> None:
    """Wait for the collector to open its durable sink before releasing child stdout."""
    with selectors.DefaultSelector() as selector:
        selector.register(ready_fd, selectors.EVENT_READ)
        if not selector.select(timeout=max(1.0, timeout_seconds)):
            raise RuntimeError("log collector did not acknowledge durable readiness")
        marker = os.read(ready_fd, 1)
    if marker != b"R":
        returncode = collector.poll()
        raise RuntimeError(
            "log collector closed its readiness channel before acknowledgement"
            + (f" (returncode={returncode})" if returncode is not None else "")
        )


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

    collector_signal = _stop_log_collector(collector, grace_seconds=1.0)
    if signal_number is None:
        signal_number = collector_signal
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
    supervisor_inspection = inspect_process_identity(supervisor_pid)
    if supervisor_inspection.outcome != "available" or supervisor_inspection.identity is None:
        raise RuntimeError(f"could not capture supervisor identity: {supervisor_inspection.detail}")
    supervisor_identity = supervisor_inspection.identity
    base_state = SupervisorState(
        session_id=session_id,
        session_dir=str(session_dir),
        status="running",
        started_at=started_at,
        updated_at=started_at,
        supervisor_pid=supervisor_pid,
        supervisor_process_group_id=supervisor_identity.process_group_id,
        supervisor_create_time=supervisor_identity.create_time,
        supervisor_command=supervisor_identity.command,
        serving_process_health=("starting" if config.healthcheck_url else "not_configured"),
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
                detail=(
                    f"abrupt_supervisor_loss: previous supervisor PID "
                    f"{stale.supervisor_pid} identity is no longer live"
                ),
            )
        )

    child: subprocess.Popen[bytes] | None = None
    child_identity: ProcessIdentity | None = None
    collector: subprocess.Popen[bytes] | None = None
    requested_signal: int | None = None

    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        nonlocal requested_signal
        requested_signal = signum

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
            collector_reclaim: StaleChildReclaimResult | None = None
            if reclaim.outcome not in ("refused", "failed"):
                collector_reclaim = reclaim_stale_collector(
                    stale,
                    grace_seconds=config.graceful_shutdown_seconds,
                )
                evidence.append(
                    LifecycleEvent(
                        timestamp=utc_now(),
                        event=(
                            "stale_collector_reclaimed"
                            if collector_reclaim.outcome in ("terminated", "killed")
                            else (
                                "stale_collector_not_running"
                                if collector_reclaim.outcome == "not_running"
                                else "stale_collector_reclaim_refused"
                            )
                        ),
                        session_id=session_id,
                        supervisor_pid=supervisor_pid,
                        previous_session_id=stale.session_id,
                        collector_pid=collector_reclaim.child_pid,
                        signal_number=collector_reclaim.signal_number,
                        signal_name=(
                            signal.Signals(collector_reclaim.signal_number).name
                            if collector_reclaim.signal_number is not None
                            else None
                        ),
                        detail=collector_reclaim.detail,
                    )
                )
            unsafe_reclaim = reclaim if reclaim.outcome in ("refused", "failed") else None
            if (
                unsafe_reclaim is None
                and collector_reclaim is not None
                and collector_reclaim.outcome in ("refused", "failed")
            ):
                unsafe_reclaim = collector_reclaim
            if unsafe_reclaim is not None:
                component = "child" if unsafe_reclaim is reclaim else "collector"
                reason = f"stale_{component}_reclaim_{unsafe_reclaim.outcome}"
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
            child_identity = None
            assert child.stdout is not None
            ready_read_fd, ready_write_fd = os.pipe()
            try:
                collector = subprocess.Popen(
                    (
                        sys.executable,
                        "-m",
                        "orchestrator.cli.server_log_collector",
                        str(process_log_path),
                        str(ready_write_fd),
                    ),
                    cwd=config.cwd,
                    env=environment,
                    stdin=child.stdout,
                    pass_fds=(ready_write_fd,),
                )
            finally:
                os.close(ready_write_fd)
            try:
                _await_log_collector_ready(
                    collector,
                    ready_read_fd,
                    timeout_seconds=_LOG_COLLECTOR_READY_TIMEOUT_SECONDS,
                )
            except RuntimeError:
                child.stdout.close()
                _terminate_process_group(
                    child,
                    grace_seconds=config.graceful_shutdown_seconds,
                )
                _stop_log_collector(
                    collector,
                    grace_seconds=config.graceful_shutdown_seconds,
                )
                raise
            finally:
                os.close(ready_read_fd)
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
            collector_inspection = inspect_process_identity(collector.pid)
            collector_identity = collector_inspection.identity
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
                    "collector_process_group_id": (
                        collector_identity.process_group_id
                        if collector_identity is not None
                        else None
                    ),
                    "collector_create_time": (
                        collector_identity.create_time if collector_identity is not None else None
                    ),
                    "collector_command": (
                        collector_identity.command if collector_identity is not None else None
                    ),
                    "collector_health": "running",
                    "serving_process_health": (
                        "starting" if config.healthcheck_url else "not_configured"
                    ),
                    "last_health_check_at": None,
                    "consecutive_health_failures": 0,
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
            health_failure_triggered = False
            health_failure_detail: str | None = None
            health_failures = 0
            health_was_healthy = False
            health_has_been_healthy = False
            next_healthcheck = child_started_monotonic
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
                    if child_identity is None:
                        evidence.append(
                            LifecycleEvent(
                                timestamp=utc_now(),
                                event="child_signal_refused",
                                session_id=session_id,
                                supervisor_pid=supervisor_pid,
                                attempt=launch_attempt,
                                child_pid=child.pid,
                                child_process_group_id=child.pid,
                                detail="collector failed and child identity is unavailable",
                            )
                        )
                        return 1
                    terminated, _delivered_signal, detail = _terminate_verified_process_group(
                        child,
                        identity=child_identity,
                        grace_seconds=config.graceful_shutdown_seconds,
                    )
                    if not terminated:
                        evidence.append(
                            LifecycleEvent(
                                timestamp=utc_now(),
                                event="child_signal_refused",
                                session_id=session_id,
                                supervisor_pid=supervisor_pid,
                                attempt=launch_attempt,
                                child_pid=child.pid,
                                child_process_group_id=child.pid,
                                detail=detail,
                            )
                        )
                        return 1
                    break
                if requested_signal is not None:
                    if child_identity is None:
                        evidence.append(
                            LifecycleEvent(
                                timestamp=utc_now(),
                                event="child_signal_refused",
                                session_id=session_id,
                                supervisor_pid=supervisor_pid,
                                attempt=launch_attempt,
                                child_pid=child.pid,
                                child_process_group_id=child.pid,
                                detail="shutdown requested but child identity is unavailable",
                            )
                        )
                        return 1
                    else:
                        terminated, delivered_signal, detail = _terminate_verified_process_group(
                            child,
                            identity=child_identity,
                            grace_seconds=config.graceful_shutdown_seconds,
                        )
                        if not terminated:
                            evidence.append(
                                LifecycleEvent(
                                    timestamp=utc_now(),
                                    event="child_signal_refused",
                                    session_id=session_id,
                                    supervisor_pid=supervisor_pid,
                                    attempt=launch_attempt,
                                    child_pid=child.pid,
                                    child_process_group_id=child.pid,
                                    detail=detail,
                                )
                            )
                            return 1
                    if delivered_signal == signal.SIGKILL:
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
                        forced_shutdown = True
                    break
                now_monotonic = time.monotonic()
                if config.healthcheck_url is not None and now_monotonic >= next_healthcheck:
                    health = check_http_health(
                        config.healthcheck_url,
                        timeout_seconds=config.healthcheck_timeout_seconds,
                    )
                    checked_at = utc_now()
                    within_startup_grace = (
                        not health_has_been_healthy
                        and now_monotonic - child_started_monotonic
                        < config.healthcheck_startup_grace_seconds
                    )
                    if health.healthy:
                        health_failures = 0
                        running_state = running_state.model_copy(
                            update={
                                "updated_at": checked_at,
                                "serving_process_health": "healthy",
                                "last_health_check_at": checked_at,
                                "consecutive_health_failures": 0,
                            }
                        )
                        evidence.write_state(running_state)
                        if not health_was_healthy:
                            evidence.append(
                                LifecycleEvent(
                                    timestamp=checked_at,
                                    event="serving_process_healthy",
                                    session_id=session_id,
                                    supervisor_pid=supervisor_pid,
                                    attempt=launch_attempt,
                                    child_pid=child.pid,
                                    child_process_group_id=child.pid,
                                    healthcheck_url=config.healthcheck_url,
                                    detail=health.detail,
                                )
                            )
                        health_was_healthy = True
                        health_has_been_healthy = True
                    elif not within_startup_grace:
                        health_failures += 1
                        health_was_healthy = False
                        running_state = running_state.model_copy(
                            update={
                                "updated_at": checked_at,
                                "serving_process_health": "unhealthy",
                                "last_health_check_at": checked_at,
                                "consecutive_health_failures": health_failures,
                            }
                        )
                        evidence.write_state(running_state)
                        evidence.append(
                            LifecycleEvent(
                                timestamp=checked_at,
                                event="serving_process_health_failed",
                                session_id=session_id,
                                supervisor_pid=supervisor_pid,
                                attempt=launch_attempt,
                                child_pid=child.pid,
                                child_process_group_id=child.pid,
                                healthcheck_url=config.healthcheck_url,
                                consecutive_health_failures=health_failures,
                                detail=health.detail,
                            )
                        )
                        if health_failures >= config.healthcheck_failure_threshold:
                            health_failure_triggered = True
                            health_failure_detail = health.detail
                            evidence.append(
                                LifecycleEvent(
                                    timestamp=checked_at,
                                    event="serving_process_health_bound_exhausted",
                                    session_id=session_id,
                                    supervisor_pid=supervisor_pid,
                                    attempt=launch_attempt,
                                    child_pid=child.pid,
                                    child_process_group_id=child.pid,
                                    healthcheck_url=config.healthcheck_url,
                                    consecutive_health_failures=health_failures,
                                    detail=health.detail,
                                )
                            )
                            if child_identity is None:
                                evidence.append(
                                    LifecycleEvent(
                                        timestamp=utc_now(),
                                        event="health_restart_signal_refused",
                                        session_id=session_id,
                                        supervisor_pid=supervisor_pid,
                                        attempt=launch_attempt,
                                        child_pid=child.pid,
                                        child_process_group_id=child.pid,
                                        detail="unhealthy child identity is unavailable",
                                    )
                                )
                                return 1
                            else:
                                terminated, delivered_signal, detail = (
                                    _terminate_verified_process_group(
                                        child,
                                        identity=child_identity,
                                        grace_seconds=config.graceful_shutdown_seconds,
                                    )
                                )
                                if not terminated:
                                    evidence.append(
                                        LifecycleEvent(
                                            timestamp=utc_now(),
                                            event="health_restart_signal_refused",
                                            session_id=session_id,
                                            supervisor_pid=supervisor_pid,
                                            attempt=launch_attempt,
                                            child_pid=child.pid,
                                            child_process_group_id=child.pid,
                                            detail=detail,
                                        )
                                    )
                                    return 1
                                evidence.append(
                                    LifecycleEvent(
                                        timestamp=utc_now(),
                                        event="unhealthy_child_terminated",
                                        session_id=session_id,
                                        supervisor_pid=supervisor_pid,
                                        attempt=launch_attempt,
                                        child_pid=child.pid,
                                        child_process_group_id=child.pid,
                                        signal_number=delivered_signal,
                                        signal_name=(
                                            signal.Signals(delivered_signal).name
                                            if delivered_signal is not None
                                            else None
                                        ),
                                        detail=detail,
                                    )
                                )
                            break
                    next_healthcheck = now_monotonic + config.healthcheck_interval_seconds
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
            running_state = running_state.model_copy(
                update={
                    "collector_health": (
                        "drained" if not drain.timed_out and drain.returncode == 0 else "failed"
                    )
                }
            )
            evidence.append(
                LifecycleEvent(
                    timestamp=utc_now(),
                    event="log_collector_drained",
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
            child_identity = None
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
                    "serving_process_unhealthy"
                    if health_failure_triggered
                    else (
                        "log_collector_exited_early"
                        if collector_exited_early
                        else "unexpected_child_exit"
                    )
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
                    detail=(
                        f"{stop_reason}: {health_failure_detail}"
                        if health_failure_detail is not None
                        else stop_reason
                    ),
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
                        "collector_process_group_id": None,
                        "collector_create_time": None,
                        "collector_command": None,
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
                        "collector_process_group_id": None,
                        "collector_create_time": None,
                        "collector_command": None,
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
            if child_identity is not None:
                _terminate_verified_process_group(
                    child,
                    identity=child_identity,
                    grace_seconds=config.graceful_shutdown_seconds,
                )
        if collector is not None:
            _stop_log_collector(collector, grace_seconds=config.graceful_shutdown_seconds)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()
