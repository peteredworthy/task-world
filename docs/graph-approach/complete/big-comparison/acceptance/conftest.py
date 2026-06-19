"""Hidden acceptance harness — graders only. Not shared with the arms.

Drives an arm's app purely through its public HTTP API via FastAPI TestClient.
Between tests the filesystem store is wiped and re-seeded to a known state, and
the `main` module is reloaded so any in-memory metadata caches rebuild from the
clean on-disk store. This keeps the suite independent of each arm's internals.
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SEED = {
    "readme.txt": "root readme contents\n",
    "Documents/notes.txt": "alpha beta gamma\n",
    "Documents/welcome.txt": "welcome to the desktop\n",
}
SEED_DIRS = ["Pictures"]


def _seed(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in SEED.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    for d in SEED_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def client():
    import main  # arm's app, imported from arm cwd

    root = getattr(main, "DESKTOP_FS_ROOT", Path("desktop_fs"))
    root = Path(root)
    _seed(root)
    main = importlib.reload(main)
    root = Path(getattr(main, "DESKTOP_FS_ROOT", root))
    _seed(root)
    with TestClient(main.app) as c:
        yield c
