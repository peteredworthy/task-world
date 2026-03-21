# DB-Backed Coordination: Worker Claims & Heartbeats

## Goal

Make the orchestrator **correct** when two server processes share the same database — preventing the executor death loop caused by divergent in-memory state — without adding new infrastructure.

The core change: move the "who owns this run's execution" contract from in-process memory to the database.

---

## Root Cause Recap

The death loop (`docs/executor-death-loop-investigation.md`) happened because:

1. Two uvicorn processes shared `orchestrator.db`
2. Each had its own `executor._running_tasks`, `_heartbeats`, and `InMemoryLockManager`
3. Server A paused a run; Server B's recovery loop re-spawned it
4. Both servers issued `pause_run()` in sequence → `no_executor_running` spiral

The DB was the source of truth for run *state*, but not for *who is executing* that run.

---

## Design

### Worker Identity

Each server process gets a random UUID at startup:

```python
# app.py
app.state.worker_id = str(uuid.uuid4())
```

This ID is attached to every run the process owns. It survives request boundaries and is visible across processes via the DB.

### Claim Columns

Two new columns on the `runs` table:

| Column | Type | Description |
|---|---|---|
| `worker_id` | `VARCHAR(36) NULL` | UUID of the worker process currently executing this run |
| `worker_heartbeat_at` | `DATETIME NULL` | Last heartbeat from the owning worker |

A run is **live-claimed** when `worker_id IS NOT NULL AND worker_heartbeat_at > (now - heartbeat_timeout)`.

A run is **orphaned** when `worker_id IS NOT NULL AND worker_heartbeat_at <= (now - heartbeat_timeout)`.

A run is **unclaimed** when `worker_id IS NULL`.

### Heartbeat Timeout

Default: **60 seconds**. Heartbeat interval: **15 seconds**. This gives 4 missed heartbeats before a run is considered orphaned — enough to survive a brief GC pause or DB hiccup, short enough to recover quickly.

---

## Changes Required

### 1. Alembic Migration

```python
# alembic/versions/XXXX_add_worker_claim_columns.py

def upgrade():
    op.add_column('runs', sa.Column('worker_id', sa.String(36), nullable=True))
    op.add_column('runs', sa.Column('worker_heartbeat_at', sa.DateTime(), nullable=True))
    op.create_index('ix_runs_worker_id', 'runs', ['worker_id'])

def downgrade():
    op.drop_index('ix_runs_worker_id', 'runs')
    op.drop_column('runs', 'worker_heartbeat_at')
    op.drop_column('runs', 'worker_id')
```

### 2. ORM Model (`db/models.py`)

```python
class RunModel(Base):
    # ... existing columns ...
    worker_id = Column(String(36), nullable=True, index=True)
    worker_heartbeat_at = Column(DateTime(), nullable=True)
```

### 3. Domain Model (`state/models.py`)

No change needed — `worker_id` and `worker_heartbeat_at` are coordination metadata, not workflow state. They live only on the ORM model and are never loaded into `Run`.

### 4. Executor: Claim on Start (`runners/executor.py`)

Replace the current `start_run_with_agent()` with a version that atomically claims the run:

```python
async def start_run_with_agent(self, run_id: str, service: WorkflowService) -> bool:
    """
    Claim this run for this worker and start executing.
    Returns False if another live worker already owns it.
    """
    async with get_db_session() as session:
        # Atomic claim: only succeed if run is unclaimed or orphaned
        now = datetime.utcnow()
        orphan_cutoff = now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)

        result = await session.execute(
            update(RunModel)
            .where(
                RunModel.id == run_id,
                or_(
                    RunModel.worker_id == None,
                    RunModel.worker_heartbeat_at < orphan_cutoff,
                    RunModel.worker_id == self.worker_id,  # re-entrant: already ours
                )
            )
            .values(worker_id=self.worker_id, worker_heartbeat_at=now)
            .returning(RunModel.id)
        )
        claimed = result.scalar_one_or_none()

    if claimed is None:
        logger.warning(f"run {run_id}: claim rejected — owned by another live worker")
        return False

    # Proceed with existing start logic
    await service.start_run()
    asyncio.create_task(self._run_agent_loop(run_id, ...))
    return True
```

> **Note on SQLite:** SQLite doesn't support `SELECT FOR UPDATE`, but the `UPDATE ... WHERE ... RETURNING` pattern is atomic for single-row updates in WAL mode. For Postgres, prefer `SELECT ... FOR UPDATE SKIP LOCKED` for stronger guarantees.

### 5. Executor: Heartbeat Loop (`runners/executor.py`)

A background task that runs alongside `_run_agent_loop`:

```python
async def _heartbeat_loop(self, run_id: str) -> None:
    """
    Publish a heartbeat every HEARTBEAT_INTERVAL_SECONDS.
    Exits when the run is no longer ours (claimed by another worker or terminal).
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)  # 15s
        async with get_db_session() as session:
            result = await session.execute(
                update(RunModel)
                .where(
                    RunModel.id == run_id,
                    RunModel.worker_id == self.worker_id,  # only update if still ours
                )
                .values(worker_heartbeat_at=datetime.utcnow())
                .returning(RunModel.id)
            )
            still_ours = result.scalar_one_or_none()

        if still_ours is None:
            logger.info(f"run {run_id}: heartbeat stopped — no longer our run")
            return
```

Start it alongside the agent loop:

```python
heartbeat_task = asyncio.create_task(self._heartbeat_loop(run_id))
self._running_tasks[run_id] = (agent_task, heartbeat_task)
```

### 6. Executor: Release Claim on Completion/Pause

When a run reaches a terminal state or is paused, release the claim:

```python
async def _release_claim(self, run_id: str) -> None:
    async with get_db_session() as session:
        await session.execute(
            update(RunModel)
            .where(RunModel.id == run_id, RunModel.worker_id == self.worker_id)
            .values(worker_id=None, worker_heartbeat_at=None)
        )
        await session.commit()
```

Call this in `_run_agent_loop`'s `finally` block, after `pause_run()` or `complete_run()`.

### 7. Startup Recovery (`api/app.py`)

Update the recovery logic to respect live claims:

```python
async def recover_runs_on_startup(worker_id: str, executor, service_factory):
    now = datetime.utcnow()
    orphan_cutoff = now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)

    async with get_db_session() as session:
        active_runs = await session.execute(
            select(RunModel).where(RunModel.status == RunStatus.ACTIVE)
        )
        runs = active_runs.scalars().all()

    for run in runs:
        is_live_claimed = (
            run.worker_id is not None
            and run.worker_heartbeat_at is not None
            and run.worker_heartbeat_at > orphan_cutoff
            and run.worker_id != worker_id  # different worker (not us)
        )

        if is_live_claimed:
            logger.info(f"run {run.id}: skipping recovery — owned by live worker {run.worker_id}")
            continue

        # Orphaned or unclaimed ACTIVE run — recover it
        logger.info(f"run {run.id}: recovering orphaned run (was worker {run.worker_id})")
        service = service_factory(run.id)
        await executor.start_run_with_agent(run.id, service)
```

This replaces the current logic that recovers all ACTIVE runs indiscriminately.

### 8. Replace InMemoryLockManager

The current `InMemoryLockManager` has the same multi-process flaw — locks exist only in one server's memory. Replace it with a DB-backed version:

```python
class DBLockManager:
    """
    Task-level locking using the tasks table.
    Adds locked_by / locked_at columns to task_attempts or tasks.
    """
    async def acquire(self, task_id: str, agent_id: str, session) -> bool:
        now = datetime.utcnow()
        orphan_cutoff = now - timedelta(seconds=LOCK_TIMEOUT_SECONDS)  # 300s

        result = await session.execute(
            update(TaskModel)
            .where(
                TaskModel.id == task_id,
                or_(
                    TaskModel.locked_by == None,
                    TaskModel.locked_at < orphan_cutoff,
                )
            )
            .values(locked_by=agent_id, locked_at=now)
            .returning(TaskModel.id)
        )
        return result.scalar_one_or_none() is not None

    async def release(self, task_id: str, agent_id: str, session) -> bool:
        result = await session.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id, TaskModel.locked_by == agent_id)
            .values(locked_by=None, locked_at=None)
            .returning(TaskModel.id)
        )
        return result.scalar_one_or_none() is not None
```

---

## State Invariants After This Change

| Scenario | Behavior |
|---|---|
| Single server, normal operation | Claims run on start, heartbeats every 15s, releases on pause/complete |
| Server restart | New server sees own runs as unclaimed (released in finally block), recovers them |
| Crash (no finally) | Runs show as orphaned after 60s; next startup or any live server can recover |
| Two servers accidentally started | Second server's recovery skips runs with live heartbeats from first server |
| Developer restarts uvicorn | `server_shutdown` pause + claim release; new process recovers after startup |

---

## What This Does NOT Solve

- **True horizontal scaling**: Runs are still claimed exclusively by one worker. This is correct for stateful long-running agents — you don't want two workers both executing the same Claude agent loop. If you want parallelism across runs, you get it naturally (each server claims different runs).
- **Cross-server WebSocket events**: If clients connect to Server B but their run executes on Server A, they won't receive WebSocket events. Fix: use a shared pub/sub (Redis, Postgres NOTIFY) for events. Out of scope here.
- **Global run queue**: Work discovery (which runs to start) is still triggered by API calls, not a pull-based queue. See the SKIP LOCKED queue pattern if you need workers to proactively pull work.

---

## Implementation Order

1. Write Alembic migration
2. Add ORM columns
3. Add `worker_id` to `AppState` and pass to executor
4. Implement `_release_claim()` and add to finally blocks
5. Implement `_heartbeat_loop()` and start alongside agent loop
6. Update `start_run_with_agent()` to claim atomically
7. Update startup recovery to respect live claims
8. Implement `DBLockManager` and wire in place of `InMemoryLockManager`
9. Update tests: multi-worker claim contention, orphan recovery, heartbeat expiry

---

## Estimated Scope

- 1 migration file
- ~200 lines of executor changes
- ~100 lines of new `DBLockManager`
- ~50 lines of startup recovery changes
- Test coverage for new invariants
