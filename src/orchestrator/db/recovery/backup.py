"""Database backup and restore with journal replay markers."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class BackupMetadata:
    """Metadata captured alongside a database backup."""

    backup_timestamp: datetime
    db_path: str
    journal_path: str | None
    journal_sequence_marker: int  # max sequence_number in journal at backup time
    backup_id: str  # unique identifier for this backup
    notes: str = ""


class BackupError(Exception):
    """Raised when backup or restore operations fail."""


async def create_backup(
    db_path: Path,
    backup_dir: Path,
    journal_path: Path | None = None,
    notes: str = "",
) -> BackupMetadata:
    """Create a database backup with journal replay marker.

    Copies the database file and writes a .backup-meta.json alongside it
    containing the journal sequence marker for replay start point.

    Args:
        db_path: Path to the SQLite database file.
        backup_dir: Directory to write the backup into.
        journal_path: Path to the JSONL journal file.
        notes: Optional notes about this backup.

    Returns:
        BackupMetadata with the backup details.

    Raises:
        BackupError: If the database file doesn't exist or backup fails.
    """
    if not db_path.exists():
        raise BackupError(f"Database file not found: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)

    # Generate backup ID from timestamp
    now = datetime.now(timezone.utc)
    backup_id = now.strftime("%Y%m%dT%H%M%SZ")

    # Copy database
    backup_db_path = backup_dir / f"orchestrator-{backup_id}.db"
    shutil.copy2(str(db_path), str(backup_db_path))

    # Read max sequence from journal
    journal_sequence_marker = -1
    if journal_path and journal_path.exists():
        journal_sequence_marker = scan_max_sequence(journal_path)

    metadata = BackupMetadata(
        backup_timestamp=now,
        db_path=str(backup_db_path),
        journal_path=str(journal_path) if journal_path else None,
        journal_sequence_marker=journal_sequence_marker,
        backup_id=backup_id,
        notes=notes,
    )

    # Write metadata file
    meta_path = backup_dir / f"orchestrator-{backup_id}.backup-meta.json"
    meta_dict = {
        "backup_timestamp": metadata.backup_timestamp.isoformat(),
        "db_path": metadata.db_path,
        "journal_path": metadata.journal_path,
        "journal_sequence_marker": metadata.journal_sequence_marker,
        "backup_id": metadata.backup_id,
        "notes": metadata.notes,
    }
    meta_path.write_text(json.dumps(meta_dict, indent=2))

    return metadata


async def restore_backup(
    backup_meta_path: Path,
    target_db_path: Path,
) -> BackupMetadata:
    """Restore a database from backup.

    Reads the backup metadata, copies the backup DB to the target location.

    Args:
        backup_meta_path: Path to the .backup-meta.json file.
        target_db_path: Where to restore the database.

    Returns:
        BackupMetadata for use in determining replay start point.

    Raises:
        BackupError: If backup files are missing or corrupt.
    """
    if not backup_meta_path.exists():
        raise BackupError(f"Backup metadata not found: {backup_meta_path}")

    try:
        meta_dict = json.loads(backup_meta_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise BackupError(f"Failed to read backup metadata: {e}") from e

    backup_db_path = Path(meta_dict["db_path"])
    if not backup_db_path.exists():
        # Try relative to metadata file
        backup_db_path = backup_meta_path.parent / backup_db_path.name
        if not backup_db_path.exists():
            raise BackupError(f"Backup database not found: {backup_db_path}")

    # Copy backup to target
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(backup_db_path), str(target_db_path))

    return BackupMetadata(
        backup_timestamp=datetime.fromisoformat(meta_dict["backup_timestamp"]),
        db_path=meta_dict["db_path"],
        journal_path=meta_dict.get("journal_path"),
        journal_sequence_marker=meta_dict.get("journal_sequence_marker", -1),
        backup_id=meta_dict.get("backup_id", "unknown"),
        notes=meta_dict.get("notes", ""),
    )


def scan_max_sequence(journal_path: Path) -> int:
    """Scan journal file for highest sequence_number."""
    max_seq = -1
    try:
        with open(journal_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    seq = entry.get("sequence_number", 0)
                    if seq > max_seq:
                        max_seq = seq
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return max_seq
