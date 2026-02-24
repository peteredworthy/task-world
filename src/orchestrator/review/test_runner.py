"""Async test runner for executing auto_verify commands from the Review workbench."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from pydantic import BaseModel


class TestSummary(BaseModel):
    """Summary counts parsed from test output."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class TestRunResult(BaseModel):
    """Result of a test run."""

    test_run_id: str
    status: str  # "running" | "passed" | "failed" | "error"
    summary: TestSummary | None = None
    log_output: str = ""
    duration_ms: int | None = None
    started_at: datetime
    completed_at: datetime | None = None


class TestRunner:
    """Executes auto_verify commands in a worktree and tracks results in memory."""

    def __init__(self) -> None:
        self._results: dict[str, TestRunResult] = {}
        # Maps run_id -> active test_run_id (only for currently-running tests)
        self._active_runs: dict[str, str] = {}
        # Maps run_id -> last test_run_id (persists after completion)
        self._last_test_run_ids: dict[str, str] = {}

    def is_running(self, run_id: str) -> bool:
        """Return True if a test is currently running for the given run_id."""
        test_run_id = self._active_runs.get(run_id)
        if test_run_id is None:
            return False
        result = self._results.get(test_run_id)
        return result is not None and result.status == "running"

    async def start_test_run(
        self,
        run_id: str,
        worktree_path: str,
        commands: list[str],
        on_complete: Callable[[TestRunResult], Awaitable[None]] | None = None,
    ) -> str:
        """Start async test execution. Returns test_run_id immediately.

        Raises ValueError if a test run is already active for this run_id.
        """
        if self.is_running(run_id):
            raise ValueError(f"Test run already active for run {run_id}")

        test_run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        self._results[test_run_id] = TestRunResult(
            test_run_id=test_run_id,
            status="running",
            log_output="",
            started_at=started_at,
        )
        self._active_runs[run_id] = test_run_id
        self._last_test_run_ids[run_id] = test_run_id
        asyncio.create_task(
            self._execute_commands(
                test_run_id, run_id, worktree_path, commands, started_at, on_complete
            )
        )
        return test_run_id

    async def get_test_result(self, test_run_id: str) -> TestRunResult:
        """Get status/results for a test run.

        Raises KeyError if the test_run_id is not found.
        """
        result = self._results.get(test_run_id)
        if result is None:
            raise KeyError(test_run_id)
        return result

    def get_last_result_for_run(self, run_id: str) -> TestRunResult | None:
        """Return the most recent test result for a run, or None if no test has been run."""
        test_run_id = self._last_test_run_ids.get(run_id)
        if test_run_id is None:
            return None
        return self._results.get(test_run_id)

    async def _execute_commands(
        self,
        test_run_id: str,
        run_id: str,
        worktree_path: str,
        commands: list[str],
        started_at: datetime,
        on_complete: Callable[[TestRunResult], Awaitable[None]] | None = None,
    ) -> None:
        """Execute commands in sequence, capture output, compute summary."""
        log_parts: list[str] = []
        overall_passed = True
        error_occurred = False

        try:
            for cmd in commands:
                log_parts.append(f"$ {cmd}")
                try:
                    proc = await asyncio.create_subprocess_shell(
                        cmd,
                        cwd=worktree_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    stdout, _ = await proc.communicate()
                    output = stdout.decode("utf-8", errors="replace") if stdout else ""
                    log_parts.append(output)
                    exit_code = proc.returncode if proc.returncode is not None else 0
                    if exit_code != 0:
                        overall_passed = False
                except OSError as e:
                    log_parts.append(f"Error executing command: {e}")
                    overall_passed = False
                    error_occurred = True
                    break
                except Exception as e:
                    log_parts.append(f"Unexpected error: {e}")
                    overall_passed = False
                    error_occurred = True
                    break

        except Exception as e:
            log_parts.append(f"Fatal error during test execution: {e}")
            overall_passed = False
            error_occurred = True

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        log_output = "\n".join(log_parts)

        if error_occurred:
            final_status = "error"
        elif overall_passed:
            final_status = "passed"
        else:
            final_status = "failed"

        summary = _parse_summary(log_output)

        result = TestRunResult(
            test_run_id=test_run_id,
            status=final_status,
            summary=summary,
            log_output=log_output,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._results[test_run_id] = result

        # Remove from active runs tracking now that we're done
        self._active_runs.pop(run_id, None)

        if on_complete is not None:
            try:
                await on_complete(result)
            except Exception:
                pass  # Don't let callback errors affect test result storage


def _parse_summary(log_output: str) -> TestSummary | None:
    """Attempt to parse test summary counts from pytest-style output.

    Returns None if no recognisable summary line is found.
    """
    import re

    # Match pytest short summary line: e.g. "5 passed, 1 failed, 2 skipped in 0.12s"
    pattern = re.compile(
        r"(?P<passed>\d+)\s+passed"
        r"(?:,\s*(?P<failed>\d+)\s+failed)?"
        r"(?:,\s*(?P<skipped>\d+)\s+(?:skipped|warning))?"
        r"|(?P<failed2>\d+)\s+failed"
        r"(?:,\s*(?P<passed2>\d+)\s+passed)?"
        r"(?:,\s*(?P<skipped2>\d+)\s+(?:skipped|warning))?",
    )
    for line in reversed(log_output.splitlines()):
        m = pattern.search(line)
        if m:
            passed = int(m.group("passed") or m.group("passed2") or 0)
            failed = int(m.group("failed") or m.group("failed2") or 0)
            skipped = int(m.group("skipped") or m.group("skipped2") or 0)
            total = passed + failed + skipped
            return TestSummary(total=total, passed=passed, failed=failed, skipped=skipped)
    return None
