"""Simple server entry point that configures routine directories.

Usage:
    uv run uvicorn scripts.serve:app --reload --port 8000
or:
    cd /Users/peter/code/task-world && uv run python -m uvicorn scripts.serve:app --reload --port 8000
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent

# Load .env file from project root (for OPENAI_API_KEY, etc.)
load_dotenv(_ROOT / ".env")

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
