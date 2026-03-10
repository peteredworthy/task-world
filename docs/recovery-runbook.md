# Database Recovery Runbook

## Prerequisites

- Access to the server/host where the orchestrator runs
- The JSONL event journal file (default: `.orchestrator/state/history.jsonl` relative to the DB)
- A database backup and its `.backup-meta.json` (if available)
- The `orchestrator` CLI installed (`uv run orchestrator`)

## 1. Creating Backups

Create a backup before risky operations, schema changes, or on a regular schedule.

```bash
# Basic backup (writes to .orchestrator/backups/ next to the DB)
orchestrator db create-backup

# With notes and custom backup directory
orchestrator db create-backup --notes "before schema migration" --backup-dir /mnt/backups

# JSON output (for scripting)
orchestrator --json db create-backup
```

The command copies the SQLite DB and writes a `.backup-meta.json` containing the
journal sequence marker (highest `sequence_number` in the journal at backup time).
This marker tells the replay command where the backup left off.

**Output files** (in the backup directory):
- `orchestrator-<timestamp>.db` -- the DB snapshot
- `orchestrator-<timestamp>.backup-meta.json` -- metadata with sequence marker

## 2. Recovery Procedures

### 2a. Recovery from Backup + Journal Replay

Use this when you have a backup and the journal file covers the gap.

```bash
# 1. Stop the server
kill $(pgrep -f 'uvicorn scripts.serve')

# 2. Restore the backup
orchestrator db restore-backup .orchestrator/backups/orchestrator-20260309T120000Z.backup-meta.json

# 3. Check what the replay will do (dry run)
orchestrator runs replay-journal --from-checkpoint --dry-run

# 4. Replay journal events written after the backup
orchestrator runs replay-journal --from-checkpoint

# 5. Verify (see Section 3)
orchestrator --json runs list | python -m json.tool

# 6. Restart the server
./dev.sh
```

The `--from-checkpoint` flag reads the checkpoint table in the restored DB.
On first replay after a restore, the checkpoint won't exist yet, so replay
processes all journal entries. Use `--batch-size` to control transaction size:

```bash
orchestrator runs replay-journal --from-checkpoint --batch-size 50
```

### 2b. Recovery from Journal Only (No Backup)

When no backup exists, replay the full journal against a fresh empty DB.

```bash
# 1. Stop the server
kill $(pgrep -f 'uvicorn scripts.serve')

# 2. Move the corrupt/missing DB aside
mv orchestrator.db orchestrator.db.broken 2>/dev/null

# 3. Initialize a fresh DB
uv run python scripts/seed_db.py

# 4. Replay the entire journal
orchestrator runs replay-journal --journal .orchestrator/state/history.jsonl

# 5. Verify
orchestrator --json runs list | python -m json.tool

# 6. Restart the server
./dev.sh
```

**Note:** Runs created before the journal was enabled will appear as "missing"
in the replay summary and cannot be recovered this way.

### 2c. Partial Recovery (Specific Runs)

Recover one or more specific runs without replaying the full journal.

```bash
# Replay events for a single run
orchestrator runs replay-journal --run-id abc123

# Replay events for multiple runs
orchestrator runs replay-journal --run-id abc123 --run-id def456

# Replay events for a run since a specific time
orchestrator runs replay-journal --run-id abc123 --since 2026-03-09T10:00:00Z
```

## 3. Verification

After any recovery, verify the result.

```bash
# Check total run count and statuses
orchestrator --json runs list | python3 -c "
import json, sys, collections
runs = json.load(sys.stdin)
counts = collections.Counter(r['status'] for r in runs)
print(f'Total runs: {len(runs)}')
for status, count in sorted(counts.items()):
    print(f'  {status}: {count}')
"

# Check a specific run's detail
orchestrator runs status <run-id>

# Show replay checkpoint progress
orchestrator runs replay-journal --show-checkpoint

# Dry-run replay to see if any events remain unapplied
orchestrator runs replay-journal --from-checkpoint --dry-run
```

A successful recovery shows:
- `replayed_events` matches expected count
- `missing_runs: 0` (or a known/expected number)
- `--dry-run` after replay shows `replayed_events: 0` (nothing left to apply)

## 4. Rollback

If replay produces incorrect state, restore from the backup again and retry.

```bash
# Re-restore the original backup (overwrites the bad replay)
orchestrator db restore-backup .orchestrator/backups/orchestrator-20260309T120000Z.backup-meta.json

# Retry with filters to isolate the problem
orchestrator runs replay-journal --from-checkpoint --dry-run
orchestrator runs replay-journal --run-id <problem-run-id> --dry-run
```

If the journal itself is suspect, restore the backup without replaying.
The DB will reflect state as of the backup timestamp.

To create a new clean baseline after a successful recovery:

```bash
orchestrator db create-backup --notes "post-recovery baseline"
```

## 5. Troubleshooting

### Journal file missing or corrupt

```bash
# Check journal exists and is readable
ls -la .orchestrator/state/history.jsonl

# Count valid entries
wc -l .orchestrator/state/history.jsonl

# Check for malformed lines (replay skips these, but good to know)
python3 -c "
import json
bad = 0
with open('.orchestrator/state/history.jsonl') as f:
    for i, line in enumerate(f, 1):
        try: json.loads(line)
        except: bad += 1; print(f'Line {i}: malformed')
print(f'{bad} malformed line(s)')
"
```

### Checkpoint sequence exceeds journal

This means the journal was truncated after a previous replay. The CLI will
report: `Checkpoint sequence (N) exceeds max journal sequence (M)`.

Fix: restore from a backup taken before the truncation, or delete the DB
and replay from scratch (Section 2b).

### Replay interrupted mid-batch

Safe to re-run. The `--from-checkpoint` flag resumes from the last committed
batch. All event handlers are idempotent, so replaying already-applied events
is harmless.

```bash
# Just re-run; it picks up where it left off
orchestrator runs replay-journal --from-checkpoint
```

### "Missing runs" in replay summary

Events reference runs that don't exist in the restored DB. Causes:
- Backup was taken before those runs were created
- Runs were created outside the journal window

These runs cannot be recovered from the journal alone. If the run data matters,
find an older backup that contains them.

### Server won't start after restore

Ensure the DB schema matches the code. If the backup is from an older version:

```bash
# Re-initialize schema (adds missing tables/columns via create_all)
uv run python -c "
import asyncio
from orchestrator.db.connection import create_engine, init_db
async def main():
    engine = create_engine('orchestrator.db')
    await init_db(engine)
    await engine.dispose()
asyncio.run(main())
"
```

If columns were added since the backup, you may need to delete and recreate
the DB (Section 2b) -- `create_all` does not add columns to existing tables.
