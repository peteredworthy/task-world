import sys
from pathlib import Path

sys.path.insert(0, str(Path("/Users/peter/code/task-world") / "src"))

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource

app = create_app(
    db_path="/tmp/test_debug.db",
    routine_dirs=[
        (Path("/Users/peter/code/task-world/tests/fixtures/routines"), RoutineSource.LOCAL)
    ],
    auth_disabled=True,
)
