"""Environment file snapshot storage."""

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.config.models import EnvFileSpec
from orchestrator.envfiles.errors import SnapshotNotFoundError
from orchestrator.envfiles.models import (
    SnapshotManifest,
    SnapshotPoint,
    SnapshotPointType,
)
from orchestrator.envfiles.security import (
    set_restricted_permissions,
    validate_env_file_path,
    validate_env_file_size,
)


class EnvFileStore:
    """Manages environment file snapshots on disk."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or Path.home() / ".orchestrator" / "env-store"
        self._base.mkdir(parents=True, exist_ok=True)
        set_restricted_permissions(self._base)

    def run_dir(self, run_id: str) -> Path:
        return self._base / run_id

    def snapshot_dir(self, run_id: str, snapshot_id: str) -> Path:
        return self.run_dir(run_id) / snapshot_id

    def canonical_dir(self, repo_name: str) -> Path:
        return self._base / "canonical" / repo_name

    def _manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    # --- Manifest ---

    def save_manifest(self, manifest: SnapshotManifest) -> None:
        """Atomically write manifest to disk."""
        path = self._manifest_path(manifest.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        set_restricted_permissions(path.parent)
        data = manifest.model_dump(mode="json")
        _atomic_write_json(path, data)

    def load_manifest(self, run_id: str) -> SnapshotManifest:
        """Load manifest or raise SnapshotNotFoundError."""
        path = self._manifest_path(run_id)
        if not path.exists():
            raise SnapshotNotFoundError(run_id=run_id, snapshot_id="manifest")
        data = json.loads(path.read_text())
        return SnapshotManifest.model_validate(data)

    # --- Snapshotting ---

    def capture_snapshot(
        self,
        run_id: str,
        snapshot_id: str,
        point_type: SnapshotPointType,
        worktree_path: Path,
        env_specs: list[EnvFileSpec],
        task_id: str | None = None,
    ) -> SnapshotPoint:
        """Copy declared env files from worktree into snapshot store."""
        snap_dir = self.snapshot_dir(run_id, snapshot_id)
        snap_dir.mkdir(parents=True, exist_ok=True)
        set_restricted_permissions(snap_dir)

        captured: list[str] = []
        for spec in env_specs:
            validate_env_file_path(spec.relative_path)
            src = worktree_path / spec.relative_path
            if src.exists():
                validate_env_file_size(src)
                dst = snap_dir / spec.relative_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                captured.append(spec.relative_path)

        return SnapshotPoint(
            snapshot_id=snapshot_id,
            point_type=point_type,
            run_id=run_id,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc),
            files=captured,
        )

    def restore_snapshot(
        self,
        run_id: str,
        snapshot_id: str,
        worktree_path: Path,
        files: list[str] | None = None,
    ) -> list[str]:
        """Copy files from a snapshot back into the worktree.

        Args:
            files: Specific files to restore. None = all files in snapshot.

        Returns:
            List of relative paths that were restored.
        """
        snap_dir = self.snapshot_dir(run_id, snapshot_id)
        if not snap_dir.exists():
            raise SnapshotNotFoundError(run_id=run_id, snapshot_id=snapshot_id)

        manifest = self.load_manifest(run_id)
        point = next((s for s in manifest.snapshots if s.snapshot_id == snapshot_id), None)
        if point is None:
            raise SnapshotNotFoundError(run_id=run_id, snapshot_id=snapshot_id)

        to_restore = files or point.files
        restored: list[str] = []
        for rel_path in to_restore:
            src = snap_dir / rel_path
            if src.exists():
                dst = worktree_path / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored.append(rel_path)

        return restored

    # --- Ingest from source directory ---

    def ingest_source(
        self,
        run_id: str,
        source_dir: Path,
        env_specs: list[EnvFileSpec],
    ) -> list[str]:
        """Copy env files from a user-provided source directory into
        the run_start snapshot. Called at run creation time.

        Returns:
            List of relative paths that were ingested.
        """
        snap_dir = self.snapshot_dir(run_id, "run_start")
        snap_dir.mkdir(parents=True, exist_ok=True)
        set_restricted_permissions(snap_dir)

        ingested: list[str] = []
        for spec in env_specs:
            validate_env_file_path(spec.relative_path)
            src = source_dir / spec.relative_path
            if src.exists():
                validate_env_file_size(src)
                dst = snap_dir / spec.relative_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                ingested.append(spec.relative_path)

        return ingested

    # --- Inject into worktree ---

    def inject_into_worktree(
        self,
        run_id: str,
        snapshot_id: str,
        worktree_path: Path,
    ) -> list[str]:
        """Copy files from a snapshot into the worktree. Used at run/task start."""
        return self.restore_snapshot(run_id, snapshot_id, worktree_path)

    # --- Canonical (promote/load) ---

    def promote_to_canonical(
        self,
        run_id: str,
        repo_name: str,
        env_specs: list[EnvFileSpec],
    ) -> list[str]:
        """Copy promote_on_success files from run_end snapshot to canonical store."""
        snap_dir = self.snapshot_dir(run_id, "run_end")
        canon_dir = self.canonical_dir(repo_name)
        canon_dir.mkdir(parents=True, exist_ok=True)
        set_restricted_permissions(canon_dir)

        promoted: list[str] = []
        for spec in env_specs:
            if not spec.promote_on_success:
                continue
            src = snap_dir / spec.relative_path
            if src.exists():
                dst = canon_dir / spec.relative_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                promoted.append(spec.relative_path)

        return promoted

    def load_canonical(
        self,
        repo_name: str,
        env_specs: list[EnvFileSpec],
        worktree_path: Path,
    ) -> list[str]:
        """Inject canonical env files into a worktree (used when no source_dir provided)."""
        canon_dir = self.canonical_dir(repo_name)
        if not canon_dir.exists():
            return []

        loaded: list[str] = []
        for spec in env_specs:
            src = canon_dir / spec.relative_path
            if src.exists():
                dst = worktree_path / spec.relative_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                loaded.append(spec.relative_path)

        return loaded

    # --- Copy-back to user target ---

    def copy_back(
        self,
        run_id: str,
        snapshot_id: str,
        target_dir: Path,
        files: list[str] | None = None,
    ) -> list[str]:
        """Copy files from a snapshot to a user-specified target directory.

        Args:
            target_dir: Where to write the files. Does not need to match original source.
            files: Specific files to copy. None = all files in snapshot.

        Returns:
            List of relative paths copied.
        """
        snap_dir = self.snapshot_dir(run_id, snapshot_id)
        if not snap_dir.exists():
            raise SnapshotNotFoundError(run_id=run_id, snapshot_id=snapshot_id)

        manifest = self.load_manifest(run_id)
        point = next((s for s in manifest.snapshots if s.snapshot_id == snapshot_id), None)
        to_copy = files or (point.files if point else [])

        copied: list[str] = []
        for rel_path in to_copy:
            src = snap_dir / rel_path
            if src.exists():
                dst = target_dir / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(rel_path)

        return copied

    # --- Cleanup ---

    def delete_run_snapshots(self, run_id: str) -> None:
        """Remove all snapshots for a run."""
        run_dir = self.run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir)


def _atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """Write JSON atomically via temp file + os.replace."""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
