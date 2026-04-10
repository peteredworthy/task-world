"""Cleanup utilities for stale env file snapshots."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone

from orchestrator.envfiles.store import EnvFileStore


class EnvFileCleanup:
    """Manages cleanup of orphaned and stale env file snapshots."""

    def __init__(self, store: EnvFileStore, retention: timedelta = timedelta(days=30)) -> None:
        self._store = store
        self._retention = retention

    def cleanup_deleted_runs(self, active_run_ids: set[str]) -> int:
        """Remove snapshot directories for runs that no longer exist.

        Never removes the 'canonical' directory.
        Returns count of removed directories.
        """
        removed = 0
        base = self._store._base  # type: ignore[reportPrivateUsage]
        if not base.exists():
            return 0
        for entry in base.iterdir():
            if entry.name == "canonical" or not entry.is_dir():
                continue
            if entry.name not in active_run_ids:
                shutil.rmtree(entry)
                removed += 1
        return removed

    def cleanup_old_snapshots(self) -> int:
        """Remove snapshots older than retention period.

        Checks the last snapshot timestamp in each manifest.
        Never removes the 'canonical' directory.
        Returns count of removed directories.
        """
        removed = 0
        cutoff = datetime.now(timezone.utc) - self._retention
        base = self._store._base  # type: ignore[reportPrivateUsage]
        if not base.exists():
            return 0
        for entry in base.iterdir():
            if entry.name == "canonical" or not entry.is_dir():
                continue
            manifest_path = entry / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                snapshots = manifest.get("snapshots", [])
                if snapshots:
                    last_ts = max(s["timestamp"] for s in snapshots)
                    if datetime.fromisoformat(last_ts) < cutoff:
                        shutil.rmtree(entry)
                        removed += 1
        return removed
