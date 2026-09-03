"""Independent output collector for a supervised server child.

The collector is a separate process so it keeps draining the server's stdout
when the supervisor itself is killed.  It exits naturally when every writer in
the server process group closes the pipe.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO


def collect_server_output(
    source: BinaryIO,
    process_log: BinaryIO,
    terminal: BinaryIO | None,
) -> bool:
    """Drain, timestamp, persist, and optionally tee server output until EOF."""
    traceback_seen = False
    for line in iter(source.readline, b""):
        timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").encode("ascii")
        logged_line = b"[" + timestamp + b"] " + line
        if not logged_line.endswith(b"\n"):
            logged_line += b"\n"
        if b"Traceback (most recent call last):" in line:
            traceback_seen = True
        process_log.write(logged_line)
        process_log.flush()
        os.fsync(process_log.fileno())
        if terminal is not None:
            try:
                terminal.write(line)
                terminal.flush()
            except (BrokenPipeError, OSError):
                # A detached or closed terminal must never stop durable capture.
                terminal = None
    return traceback_seen


def _signal_ready(raw_fd: str) -> None:
    """Acknowledge that the durable destination is open before the child runs freely."""
    try:
        ready_fd = int(raw_fd)
    except ValueError as exc:
        raise RuntimeError("collector readiness file descriptor must be an integer") from exc
    try:
        os.write(ready_fd, b"R")
    finally:
        os.close(ready_fd)


def main() -> int:
    """Collect stdin into the process-log path supplied on the command line."""
    if len(sys.argv) not in (2, 3):
        print(
            "usage: python -m orchestrator.cli.server_log_collector PROCESS_LOG [READY_FD]",
            file=sys.stderr,
        )
        return 2
    process_log_path = Path(sys.argv[1])
    destination = getattr(sys.stdout, "buffer", None)
    with process_log_path.open("ab", buffering=0) as process_log:
        if len(sys.argv) == 3:
            _signal_ready(sys.argv[2])
        collect_server_output(sys.stdin.buffer, process_log, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
