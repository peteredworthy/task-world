"""Simple server entry point that configures routine directories.

Usage:
    uv run uvicorn scripts.serve:app --reload --port 8000
or:
    cd /Users/peter/code/task-world && uv run python -m uvicorn scripts.serve:app --reload --port 8000
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
