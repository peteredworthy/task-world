"""Standalone worker entry point.

Starts the executor loop without importing or depending on the FastAPI app.
Reads ORCHESTRATOR_DB env var for DB path.

Usage::

    ORCHESTRATOR_DB=/path/to/orchestrator.db python scripts/worker.py
    # or
    ORCHESTRATOR_DB=/path/to/orchestrator.db uv run python scripts/worker.py

The worker polls the pending_signals table and drives executor loops for
active runs.  It writes a periodic heartbeat to the DB to prove liveness.
On SIGTERM it drains the current signal batch and shuts down gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heartbeat helpers
# ---------------------------------------------------------------------------

_HEARTBEAT_TABLE = "worker_heartbeat"
_HEARTBEAT_INTERVAL = 10  # seconds


async def _write_heartbeat(session_factory: object) -> None:
    """Write a heartbeat row to the DB to prove worker liveness."""
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: F401

        async with session_factory() as session:  # type: ignore[operator]
            # Use a simple key/value style: upsert worker_id="default"
            stmt = text(
                "INSERT INTO worker_heartbeat (worker_id, last_seen) "
                "VALUES ('default', :ts) "
                "ON CONFLICT(worker_id) DO UPDATE SET last_seen = excluded.last_seen"
            )
            await session.execute(stmt, {"ts": datetime.now(timezone.utc).isoformat()})
            await session.commit()
    except Exception:
        logger.debug("Worker: could not write DB heartbeat (table may not exist yet)")


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------


async def _poll_and_spawn(
    session_factory: object,
    executor: object,
) -> None:
    """Check for ACTIVE runs with no executor loop and spawn them."""
    from orchestrator.config.enums import AgentRunnerType, RunStatus

    managed_types = {
        AgentRunnerType.CLI_SUBPROCESS,
        AgentRunnerType.OPENHANDS_LOCAL,
        AgentRunnerType.OPENHANDS_DOCKER,
        AgentRunnerType.CODEX_SERVER,
        AgentRunnerType.CLAUDE_SDK,
    }

    async with session_factory() as session:  # type: ignore[operator]
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        active_runs = await repo.list_by_status(RunStatus.ACTIVE)

    for run in active_runs:
        if run.agent_type not in managed_types:
            continue
        from orchestrator.runners.executor import AgentRunnerExecutor

        ex: AgentRunnerExecutor = executor  # type: ignore[assignment]
        if not ex.is_running(run.id):
            spawned = ex.spawn_for_run(run.id, run.agent_type, run.agent_config)
            if spawned:
                logger.info(
                    f"Worker: spawned executor loop for active run {run.id} "
                    f"({run.agent_type.value})"
                )


# ---------------------------------------------------------------------------
# Main worker coroutine
# ---------------------------------------------------------------------------


async def _worker_main() -> None:
    """Main worker coroutine — polls DB and drives executor loops."""
    db_path = os.environ.get("ORCHESTRATOR_DB")
    if not db_path:
        logger.error("ORCHESTRATOR_DB environment variable is not set")
        sys.exit(1)

    logger.info(f"Worker: starting with DB={db_path}")

    # ------------------------------------------------------------------
    # Initialise DB
    # ------------------------------------------------------------------
    from orchestrator.db.connection import create_engine, create_session_factory, init_db

    db_url = f"sqlite+aiosqlite:///{db_path}" if not db_path.startswith("sqlite") else db_path
    engine = create_engine(db_url)
    session_factory = create_session_factory(engine)

    await init_db(engine)

    # ------------------------------------------------------------------
    # Create executor (no FastAPI app required)
    # ------------------------------------------------------------------
    from orchestrator.config.global_config import load_global_config
    from orchestrator.runners.executor import AgentRunnerExecutor
    from orchestrator.workflow.locks import InMemoryLockManager
    from orchestrator.workflow.service import SubmitEventRegistry

    global_config = load_global_config()
    lock_manager = InMemoryLockManager()
    submit_event_registry = SubmitEventRegistry()

    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        global_config=global_config,
        lock_manager=lock_manager,
        submit_event_registry=submit_event_registry,
        connection_manager=None,  # no WebSocket broadcasting in standalone worker
        spawn_agents=True,
    )

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------
    shutdown_event = asyncio.Event()

    def _handle_sigterm(signum: int, frame: object) -> None:
        logger.info(f"Worker: received signal {signum}, initiating graceful shutdown")
        asyncio.get_event_loop().call_soon_threadsafe(shutdown_event.set)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    logger.info("Worker: running — polling for active runs every 2 s")

    heartbeat_counter = 0

    while not shutdown_event.is_set():
        try:
            await _poll_and_spawn(session_factory, executor)
        except Exception:
            logger.exception("Worker: error in poll cycle")

        # Write heartbeat every N cycles
        heartbeat_counter += 1
        if heartbeat_counter >= (_HEARTBEAT_INTERVAL // 2):
            heartbeat_counter = 0
            await _write_heartbeat(session_factory)

        # Wait 2 s (or until shutdown)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    # ------------------------------------------------------------------
    # Drain: wait for any in-flight executor tasks to finish or be cancelled
    # ------------------------------------------------------------------
    logger.info("Worker: shutdown requested — draining in-flight executor tasks")

    running_tasks = list(executor._running_tasks.values())  # type: ignore[attr-defined]
    if running_tasks:
        logger.info(f"Worker: waiting for {len(running_tasks)} task(s) to complete")
        # Give tasks a chance to finish the current signal batch before cancelling
        done, pending = await asyncio.wait(running_tasks, timeout=5.0)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    await engine.dispose()
    logger.info("Worker: shutdown complete")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_worker_main())
