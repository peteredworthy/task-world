"""Persistence helpers for attempt data (output, prompts, metrics, metadata).

Extracted from ``AgentRunnerExecutor`` -- every method preserves the original
session-handling semantics (opens its own session unless one is provided).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from orchestrator.state.models import ActionLog, ModelTokenUsage
from orchestrator.db import RunModel
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
                from orchestrator.db import RunRepository

                repo = RunRepository(session)
                merged_action_log = action_log
                if action_log is not None:
                    run = await repo.get(run_id)
                    for step in run.steps:
                        for task in step.tasks:
                            if task.id == task_id and task.attempts:
                                if task.attempts[-1].action_log is not None:
                                    merged_action_log = self._merge_action_logs(
                                        task.attempts[-1].action_log,
                                        action_log,
                                    )
                                break
                kwargs: dict[str, Any] = {
                    "output_lines": output_lines,
                    "error": error,
                }
                if action_log is not None:
                    kwargs["action_log"] = merged_action_log
                await repo.update_latest_attempt(task_id, **kwargs)
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
        from orchestrator.db import RunRepository

        async def _do_store(s: "AsyncSession") -> None:
            repo = RunRepository(s)
            await repo.update_latest_attempt(
                task_id,
                builder_prompt=builder_prompt,
                verifier_prompt=verifier_prompt,
            )
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
        *,
        token_usage_by_model: list[ModelTokenUsage] | None = None,
    ) -> None:
        """Store execution metrics on the current attempt and accumulate into run totals."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db import RunRepository

                repo = RunRepository(session)
                await repo.update_latest_attempt(
                    task_id,
                    metrics=metrics,
                    token_usage_by_model=token_usage_by_model,
                )
                await session.commit()
                return
        except Exception:
            logger.debug(f"Failed to store attempt metrics for {task_id}", exc_info=True)

    async def persist_agent_metadata(
        self,
        run_id: str,
        agent_metadata: dict[str, Any],
    ) -> None:
        """Persist agent metadata (PID, container_id, etc.) to run.agent_runner_config immediately.

        This should be called right after creating the agent process so that if the
        orchestrator crashes or the agent dies, we can still check if it's alive
        via AgentRunnerMonitor.check_agent_alive().
        """
        if not agent_metadata:
            return

        try:
            async with self._session_factory() as session:
                run_model = await session.get(RunModel, run_id)
                if run_model is None:
                    return
                run_model.runner_config = {**(run_model.runner_config or {}), **agent_metadata}
                run_model.updated_at = datetime.now(timezone.utc)
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
