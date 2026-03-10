"""Tests for database backup and restore with journal replay markers."""

import json

import pytest

from orchestrator.db.backup import (
    BackupError,
    BackupMetadata,
    create_backup,
    restore_backup,
)


@pytest.fixture()
def fake_db(tmp_path):
    """Create a fake SQLite database file."""
    db_path = tmp_path / "orchestrator.db"
    db_path.write_text("fake-sqlite-data")
    return db_path


@pytest.fixture()
def fake_journal(tmp_path):
    """Create a fake JSONL journal with sequence numbers."""
    journal_path = tmp_path / ".orchestrator" / "state" / "history.jsonl"
    journal_path.parent.mkdir(parents=True)
    entries = [
        {"sequence_number": 0, "event_type": "run_created", "run_id": "r1"},
        {"sequence_number": 1, "event_type": "task_started", "run_id": "r1"},
        {"sequence_number": 2, "event_type": "task_completed", "run_id": "r1"},
    ]
    journal_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return journal_path


@pytest.mark.asyncio()
async def test_create_backup_copies_db_and_writes_metadata(fake_db, tmp_path):
    backup_dir = tmp_path / "backups"

    meta = await create_backup(fake_db, backup_dir)

    assert isinstance(meta, BackupMetadata)
    assert meta.journal_sequence_marker == -1  # no journal provided
    assert meta.notes == ""

    # Verify backup DB exists and has correct content
    backup_db = backup_dir / f"orchestrator-{meta.backup_id}.db"
    assert backup_db.exists()
    assert backup_db.read_text() == "fake-sqlite-data"

    # Verify metadata JSON exists
    meta_file = backup_dir / f"orchestrator-{meta.backup_id}.backup-meta.json"
    assert meta_file.exists()
    meta_dict = json.loads(meta_file.read_text())
    assert meta_dict["backup_id"] == meta.backup_id
    assert meta_dict["journal_sequence_marker"] == -1


@pytest.mark.asyncio()
async def test_create_backup_with_journal_captures_sequence(fake_db, fake_journal, tmp_path):
    backup_dir = tmp_path / "backups"

    meta = await create_backup(
        fake_db, backup_dir, journal_path=fake_journal, notes="before migration"
    )

    assert meta.journal_sequence_marker == 2
    assert meta.notes == "before migration"
    assert meta.journal_path == str(fake_journal)


@pytest.mark.asyncio()
async def test_restore_backup_copies_db_back(fake_db, tmp_path):
    backup_dir = tmp_path / "backups"
    meta = await create_backup(fake_db, backup_dir)

    # Delete original
    fake_db.unlink()
    assert not fake_db.exists()

    # Restore
    meta_file = backup_dir / f"orchestrator-{meta.backup_id}.backup-meta.json"
    restored_meta = await restore_backup(meta_file, fake_db)

    assert fake_db.exists()
    assert fake_db.read_text() == "fake-sqlite-data"
    assert restored_meta.backup_id == meta.backup_id
    assert restored_meta.journal_sequence_marker == -1


@pytest.mark.asyncio()
async def test_create_backup_missing_db_raises_error(tmp_path):
    missing_db = tmp_path / "nonexistent.db"
    backup_dir = tmp_path / "backups"

    with pytest.raises(BackupError, match="Database file not found"):
        await create_backup(missing_db, backup_dir)


@pytest.mark.asyncio()
async def test_restore_backup_missing_meta_raises_error(tmp_path):
    missing_meta = tmp_path / "nonexistent.backup-meta.json"
    target = tmp_path / "restored.db"

    with pytest.raises(BackupError, match="Backup metadata not found"):
        await restore_backup(missing_meta, target)
