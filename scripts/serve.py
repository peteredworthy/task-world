"""Simple server entry point that configures routine directories.

Usage:
    uv run orchestrator serve --reload
or:
    cd /Users/peter/code/task-world && uv run python -m uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8000
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent

# --- Worktree startup guard ---
# If .git is a file (not a directory), we're inside a git worktree.
# Refuse to start on the main server port to prevent shadowing.
_git_path = _ROOT / ".git"
if _git_path.is_file():
    _manifest_path = _ROOT / ".worktree-manifest.json"
    _manifest: dict = {}
    if _manifest_path.exists():
        try:
            _manifest = json.loads(_manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    _assigned_port = _manifest.get("assigned_port")
    _worktree_name = _manifest.get("worktree_name", "unknown")

    # Check if --port was passed on the command line (uvicorn passes it)
    _requested_port: int | None = None
    for _i, _arg in enumerate(sys.argv):
        if _arg == "--port" and _i + 1 < len(sys.argv):
            try:
                _requested_port = int(sys.argv[_i + 1])
            except ValueError:
                pass

    if _requested_port is None or _requested_port == 8000:
        print(
            f"\n  ERROR: This is worktree '{_worktree_name}' — refusing to start on port 8000.\n"
            f"  Port 8000 belongs to the main server.\n",
            file=sys.stderr,
        )
        if _assigned_port:
            print(
                f"  Use the assigned port instead:\n"
                f"    uv run uvicorn scripts.serve:app --port {_assigned_port}\n",
                file=sys.stderr,
            )
        else:
            print(
                "  No manifest found. Use a port other than 8000.\n",
                file=sys.stderr,
            )
        sys.exit(1)
    elif _assigned_port and _requested_port != _assigned_port:
        print(
            f"  WARNING: Worktree '{_worktree_name}' assigned port is {_assigned_port}, "
            f"but starting on {_requested_port}.",
            file=sys.stderr,
        )


# --- Kill stale uvicorn processes sharing the same port ---
# Two uvicorn processes on the same port share connections via SO_REUSEPORT.
# They have separate in-memory executors but share the same DB, causing
# "no_executor_running" pauses when requests get routed to the wrong server.
def _kill_stale_port_holders(port: int) -> None:
    """Kill any existing processes listening on *port* (except ourselves).

    Skips our own PID and parent PID (the uvicorn reload-watcher parent
    that spawned us also holds the socket).
    """
    import signal
    import subprocess
    import time

    my_pid = os.getpid()
    my_ppid = os.getppid()
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return

    pids = set()
    for line in result.stdout.strip().splitlines():
        try:
            pid = int(line.strip())
            if pid not in (my_pid, my_ppid):
                pids.add(pid)
        except ValueError:
            continue

    if not pids:
        return

    print(
        f"  WARNING: Killing stale process(es) on port {port}: {pids}\n"
        f"  (Duplicate servers cause executor death loops)\n",
        file=sys.stderr,
    )
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(1)

    # Force-kill stragglers
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


# Only kill stale processes for main server (port 8000), not worktree servers.
# The ppid exclusion in _kill_stale_port_holders prevents the uvicorn reload
# child from killing its own watcher parent.
_target_port: int | None = None
for _i, _arg in enumerate(sys.argv):
    if _arg == "--port" and _i + 1 < len(sys.argv):
        try:
            _target_port = int(sys.argv[_i + 1])
        except ValueError:
            pass
if os.environ.get("ORCHESTRATOR_SKIP_STALE_PORT_KILL") != "1" and (
    _target_port is None or _target_port == 8000
):
    _kill_stale_port_holders(8000)

# Load .env file from project root (for OPENAI_API_KEY, etc.)
load_dotenv(_ROOT / ".env")

# Prevent openhands SDK from adding a duplicate RichHandler to the root logger.
# openhands' setup_logging() checks isinstance(h, logging.StreamHandler) to detect
# existing handlers, but RichHandler inherits from logging.Handler (not StreamHandler),
# so the check always returns False and a second RichHandler gets added on top of the
# one FastMCP already installed via logging.basicConfig(). This disables that auto-config
# since our server already has logging configured.
os.environ.setdefault("LOG_AUTO_CONFIG", "false")

# Add src to path
sys.path.insert(0, str(_ROOT / "src"))

from orchestrator.api.app import create_app  # noqa: E402
from orchestrator.config.enums import RoutineSource  # noqa: E402

app = create_app(
    db_path=str(_ROOT / "orchestrator.db"),
    routine_dirs=[
        (_ROOT / "routines", RoutineSource.LOCAL),
        (_ROOT / "tests" / "fixtures" / "routines", RoutineSource.LOCAL),
    ],
    auth_disabled=True,
)
