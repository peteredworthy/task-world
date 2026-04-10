"""Database backup and restore commands."""

import asyncio
import json
import sys
from pathlib import Path

import click

from orchestrator.db import BackupError, create_backup, restore_backup
from orchestrator.db import resolve_default_journal_path


@click.group()
def db() -> None:
    """Database backup and restore."""
    pass


@db.command("create-backup")
@click.option("--notes", default="", help="Optional notes for this backup")
@click.option(
    "--backup-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for backup files",
)
@click.pass_context
def create_backup_cmd(ctx: click.Context, notes: str, backup_dir: Path | None) -> None:
    """Create a database backup with journal sequence marker."""

    async def _create_backup() -> None:
        db_path = Path(ctx.obj["db"])
        as_json = ctx.obj["json"]

        if not db_path.exists():
            click.echo(f"Error: Database file not found: {db_path}", err=True)
            sys.exit(1)

        # Default backup dir: .orchestrator/backups/ relative to the DB directory
        resolved_backup_dir = backup_dir or (db_path.parent / ".orchestrator" / "backups")

        # Resolve journal path
        journal_path = resolve_default_journal_path(str(db_path))

        try:
            metadata = await create_backup(
                db_path=db_path,
                backup_dir=resolved_backup_dir,
                journal_path=journal_path,
                notes=notes,
            )
        except BackupError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        result = {
            "backup_path": metadata.db_path,
            "metadata_path": str(
                resolved_backup_dir / f"orchestrator-{metadata.backup_id}.backup-meta.json"
            ),
            "journal_sequence_marker": metadata.journal_sequence_marker,
            "backup_id": metadata.backup_id,
            "backup_timestamp": metadata.backup_timestamp.isoformat(),
            "notes": metadata.notes,
        }

        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Backup created: {result['backup_path']}")
            click.echo(f"Metadata: {result['metadata_path']}")
            click.echo(f"Journal sequence marker: {result['journal_sequence_marker']}")
            if notes:
                click.echo(f"Notes: {notes}")

    asyncio.run(_create_backup())


@db.command("restore-backup")
@click.argument("backup_meta_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--target-db",
    type=click.Path(path_type=Path),
    default=None,
    help="Target DB path (default: orchestrator.db)",
)
@click.pass_context
def restore_backup_cmd(ctx: click.Context, backup_meta_path: Path, target_db: Path | None) -> None:
    """Restore a database from backup.

    BACKUP_META_PATH is the path to the .backup-meta.json file.
    """

    async def _restore_backup() -> None:
        as_json = ctx.obj["json"]
        resolved_target = target_db or Path(ctx.obj["db"])

        try:
            metadata = await restore_backup(
                backup_meta_path=backup_meta_path,
                target_db_path=resolved_target,
            )
        except BackupError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        result = {
            "restored_db_path": str(resolved_target),
            "backup_id": metadata.backup_id,
            "backup_timestamp": metadata.backup_timestamp.isoformat(),
            "journal_sequence_marker": metadata.journal_sequence_marker,
            "journal_path": metadata.journal_path,
            "notes": metadata.notes,
        }

        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Restored database to: {result['restored_db_path']}")
            click.echo(f"Backup ID: {result['backup_id']}")
            click.echo(f"Backup timestamp: {result['backup_timestamp']}")
            click.echo(
                f"Journal sequence marker: {result['journal_sequence_marker']} "
                f"(replay events after this sequence)"
            )
            if metadata.journal_path:
                click.echo(f"Journal path: {metadata.journal_path}")

    asyncio.run(_restore_backup())
