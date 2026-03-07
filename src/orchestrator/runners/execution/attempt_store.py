"""Persistence helpers for attempt data (output, prompts, metrics, metadata).

Extracted from ``AgentRunnerExecutor`` -- every method preserves the original
session-handling semantics (opens its own session unless one is provided).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from orchestrator.runners.action_log import ActionLog
from orchestrator.runners.types import ExecutionMetrics

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class AttemptStore:
    """Read/write helpers for attempt-level data on a run."""

    def __init__(self, session_factory: "async_sessionmaker[AsyncSession]") -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Public API (names drop the underscore prefix)
    # ------------------------------------------------------------------

    async def store_attempt_output(
        self,
        run_id: str,
        task_id: str,
        output_lines: list[str],
        error: str | None = None,
        action_log: Any = None,
    ) -> None:
        """Store agent output, error, and optional structured action log on the current attempt."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db.repositories import RunRepository

                repo = RunRepository(session)
                run = await repo.get(run_id)
                # Find the task and its latest attempt
                for step in run.steps:
                    for task in step.tasks:
                        if task.id == task_id and task.attempts:
                            attempt = task.attempts[-1]
                            if output_lines:
                                # Append phase output (builder + verifier) and keep tail.
                                new_text = "\n".join(output_lines)
                                if attempt.agent_output:
                                    combined = f"{attempt.agent_output}\n{new_text}"
                                    attempt.agent_output = "\n".join(combined.splitlines()[-10000:])
                                else:
                                    attempt.agent_output = "\n".join(output_lines[-10000:])
                            if error:
                                attempt.error = error
                            if action_log is not None:
                                if attempt.action_log is None:
                                    attempt.action_log = action_log
                                else:
                                    attempt.action_log = self._merge_action_logs(
                                        attempt.action_log, action_log
                                    )
                            await repo.save(run)
                            await session.commit()
                            return
        except Exception:
            logger.debug(f"Failed to store attempt output for {task_id}", exc_info=True)

    async def store_attempt_prompt(
        self,
        run_id: str,
        task_id: str,
        builder_prompt: str | None = None,
        verifier_prompt: str | None = None,
        session: "AsyncSession | None" = None,
    ) -> None:
        """Store builder or verifier prompt on the current attempt.

        This should be called BEFORE agent execution so the prompt is
        available even if the agent crashes.

        If a session is provided, it is used directly (and committed) rather
        than opening a new one.  This avoids StaticPool concurrency issues in
        tests where all sessions share the same underlying connection.
        """
        from orchestrator.db.repositories import RunRepository

        async def _do_store(s: "AsyncSession") -> None:
            repo = RunRepository(s)
            run = await repo.get(run_id)
            for step in run.steps:
                for task in step.tasks:
                    if task.id == task_id and task.attempts:
                        attempt = task.attempts[-1]
                        if builder_prompt is not None:
                            attempt.builder_prompt = builder_prompt
                        if verifier_prompt is not None:
                            attempt.verifier_prompt = verifier_prompt
                        await repo.save(run)
                        await s.commit()
                        return

        try:
            if session is not None:
                await _do_store(session)
            else:
                async with self._session_factory() as new_session:
                    await _do_store(new_session)
        except Exception:
            logger.debug(f"Failed to store attempt prompt for {task_id}", exc_info=True)

    async def store_attempt_metrics(
        self,
        run_id: str,
        task_id: str,
        metrics: ExecutionMetrics,
    ) -> None:
        """Store execution metrics on the current attempt and accumulate into run totals."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db.repositories import RunRepository

                repo = RunRepository(session)
                run = await repo.get(run_id)
                for step in run.steps:
                    for task in step.tasks:
                        if task.id == task_id and task.attempts:
                            attempt = task.attempts[-1]
                            attempt.metrics.tokens_read += metrics.tokens_read
                            attempt.metrics.tokens_write += metrics.tokens_write
                            attempt.metrics.tokens_cache += metrics.tokens_cache
                            attempt.metrics.duration_ms += metrics.duration_ms
                            attempt.metrics.num_actions += metrics.num_actions
                            # Accumulate into run totals
                            run.total_tokens_read += metrics.tokens_read
                            run.total_tokens_write += metrics.tokens_write
                            run.total_tokens_cache += metrics.tokens_cache
                            run.total_duration_ms += metrics.duration_ms
                            run.total_num_actions += metrics.num_actions
                            await repo.save(run)
                            await session.commit()
                            return
        except Exception:
            logger.debug(f"Failed to store attempt metrics for {task_id}", exc_info=True)

    async def persist_agent_metadata(
        self,
        run_id: str,
        agent_metadata: dict[str, Any],
    ) -> None:
        """Persist agent metadata (PID, container_id, etc.) to run.agent_config immediately.

        This should be called right after creating the agent process so that if the
        orchestrator crashes or the agent dies, we can still check if it's alive
        via AgentRunnerMonitor.check_agent_alive().
        """
        if not agent_metadata:
            return

        try:
            async with self._session_factory() as session:
                from orchestrator.db.repositories import RunRepository

                repo = RunRepository(session)
                run = await repo.get(run_id)
                # Merge new metadata with existing config
                run.agent_config = {**run.agent_config, **agent_metadata}
                run.updated_at = datetime.now(timezone.utc)
                await repo.save(run)
                await session.commit()
                logger.info(f"Run {run_id}: persisted agent metadata {list(agent_metadata.keys())}")
        except Exception as e:
            logger.warning(f"Failed to persist agent metadata for {run_id}: {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_action_logs(first: ActionLog, second: ActionLog) -> ActionLog:
        """Merge builder + verifier action logs for a single attempt."""
        merged = first.model_copy(deep=True)
        seq_offset = merged.entries[-1].sequence_num if merged.entries else 0

        for idx, entry in enumerate(second.entries, start=1):
            adjusted = entry.model_copy(deep=True)
            adjusted.sequence_num = seq_offset + idx
            merged.entries.append(adjusted)

        if not merged.session_id:
            merged.session_id = second.session_id
        if not merged.agent_model:
            merged.agent_model = second.agent_model
        if second.tools_available:
            merged.tools_available = list(
                dict.fromkeys(merged.tools_available + second.tools_available)
            )

        merged.total_turns += second.total_turns
        merged.total_cost_usd += second.total_cost_usd
        merged.total_duration_ms += second.total_duration_ms
        merged.total_input_tokens += second.total_input_tokens
        merged.total_output_tokens += second.total_output_tokens
        merged.total_cache_read_tokens += second.total_cache_read_tokens
        merged.total_cache_creation_tokens += second.total_cache_creation_tokens
        return merged
