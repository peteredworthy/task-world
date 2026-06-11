"""Persistence helpers for attempt data (output, prompts, metrics, metadata).

Extracted from ``AgentRunnerExecutor`` -- every method preserves the original
session-handling semantics (opens its own session unless one is provided).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from orchestrator.runners.types import ExecutionMetrics
from orchestrator.state.models import ActionLog, ModelTokenUsage

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

    async def _latest_attempt_id(
        self, session: "AsyncSession", run_id: str, task_id: str
    ) -> str | None:
        from orchestrator.db import RunRepository

        run = await RunRepository(session).get(run_id)
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    if task.attempts:
                        return task.attempts[-1].id
                    return None
        return None

    async def _latest_attempt_context(
        self, session: "AsyncSession", run_id: str, task_id: str
    ) -> dict[str, Any] | None:
        from orchestrator.db import RunRepository

        run = await RunRepository(session).get(run_id)
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    if not task.attempts:
                        return None
                    attempt = task.attempts[-1]
                    return {
                        "attempt_id": attempt.id,
                        "attempt_num": attempt.attempt_num,
                        "builder_prompt": attempt.builder_prompt,
                        "verifier_prompt": attempt.verifier_prompt,
                    }
        return None

    async def _append_attempt_update(
        self,
        session: "AsyncSession",
        *,
        run_id: str,
        task_id: str,
        output_lines: list[str] | None = None,
        error: str | None = None,
        action_log: Any = None,
        builder_prompt: str | None = None,
        verifier_prompt: str | None = None,
        tokens_read: int | None = None,
        tokens_write: int | None = None,
        tokens_cache: int | None = None,
        duration_ms: int | None = None,
        num_actions: int | None = None,
        token_usage_by_model: list[dict[str, Any]] | None = None,
    ) -> bool:
        from orchestrator.db import commit_with_event_outbox, create_wired_event_store_v2
        from orchestrator.workflow import AttemptUpdated

        attempt_id = await self._latest_attempt_id(session, run_id, task_id)
        if attempt_id is None:
            return False
        await create_wired_event_store_v2(session).append(
            [
                AttemptUpdated(
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    output_lines=output_lines,
                    error=error,
                    action_log=self._json_value(action_log) if action_log is not None else None,
                    builder_prompt=builder_prompt,
                    verifier_prompt=verifier_prompt,
                    tokens_read=tokens_read,
                    tokens_write=tokens_write,
                    tokens_cache=tokens_cache,
                    duration_ms=duration_ms,
                    num_actions=num_actions,
                    token_usage_by_model=token_usage_by_model,
                )
            ]
        )
        await commit_with_event_outbox(session)
        return True

    async def store_attempt_output(
        self,
        run_id: str,
        task_id: str,
        output_lines: list[str],
        error: str | None = None,
        action_log: Any = None,
        *,
        phase: str | None = None,
        agent_runner_type: str | None = None,
    ) -> None:
        """Store agent output, error, and optional structured action log on the current attempt."""
        attempt_num: int | str = "unknown"
        try:
            async with self._session_factory() as session:
                from orchestrator.db import RunRepository

                run = await RunRepository(session).get(run_id)
                current_task = None
                for step in run.steps:
                    for task in step.tasks:
                        if task.id == task_id:
                            current_task = task
                            if task.attempts:
                                attempt_num = task.attempts[-1].attempt_num
                            break
                    if current_task is not None:
                        break
                merged_action_log = action_log
                if action_log is not None and current_task is not None and current_task.attempts:
                    if current_task.attempts[-1].action_log is not None:
                        merged_action_log = self._merge_action_logs(
                            current_task.attempts[-1].action_log,
                            action_log,
                        )
                await self._append_attempt_update(
                    session,
                    run_id=run_id,
                    task_id=task_id,
                    output_lines=output_lines,
                    error=error,
                    action_log=merged_action_log if action_log is not None else None,
                )
                if phase is not None and agent_runner_type is not None:
                    await self._upsert_interaction_log_artifact(
                        session,
                        run_id=run_id,
                        task_id=task_id,
                        phase=phase,
                        agent_runner_type=agent_runner_type,
                        output_text="\n".join(output_lines),
                        action_log=merged_action_log if action_log is not None else None,
                    )
                return
        except Exception:
            logger.warning(
                "Failed to store attempt output "
                "run_id=%s task_id=%s attempt=%s phase=%s agent_runner_type=%s",
                run_id,
                task_id,
                attempt_num,
                phase or "unspecified",
                agent_runner_type or "unspecified",
                exc_info=True,
            )

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

        async def _do_store(s: "AsyncSession") -> None:
            await self._append_attempt_update(
                s,
                run_id=run_id,
                task_id=task_id,
                builder_prompt=builder_prompt,
                verifier_prompt=verifier_prompt,
            )
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
        phase: str | None = None,
        agent_runner_type: str | None = None,
        model_name: str | None = None,
        mode_tag: str | None = None,
    ) -> None:
        """Store execution metrics on the current attempt and accumulate into run totals."""
        attempt_num: int | str = "unknown"
        try:
            async with self._session_factory() as session:
                attempt_context = await self._latest_attempt_context(session, run_id, task_id)
                if attempt_context is not None:
                    attempt_num = int(attempt_context["attempt_num"])
                await self._append_attempt_update(
                    session,
                    run_id=run_id,
                    task_id=task_id,
                    tokens_read=metrics.tokens_read,
                    tokens_write=metrics.tokens_write,
                    tokens_cache=metrics.tokens_cache,
                    duration_ms=metrics.duration_ms,
                    num_actions=metrics.num_actions,
                    token_usage_by_model=self._dump_token_usage(token_usage_by_model),
                )
                if phase is not None and agent_runner_type is not None:
                    await self._upsert_cost_record(
                        session,
                        run_id=run_id,
                        task_id=task_id,
                        metrics=metrics,
                        token_usage_by_model=token_usage_by_model,
                        phase=phase,
                        agent_runner_type=agent_runner_type,
                        model_name=model_name,
                        mode_tag=mode_tag,
                    )
                return
        except Exception:
            logger.warning(
                "Failed to store attempt metrics "
                "run_id=%s task_id=%s attempt=%s phase=%s agent_runner_type=%s",
                run_id,
                task_id,
                attempt_num,
                phase or "unspecified",
                agent_runner_type or "unspecified",
                exc_info=True,
            )

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
                from orchestrator.db import commit_with_event_outbox, create_wired_event_store_v2
                from orchestrator.workflow import (
                    UpdateRunMetadataCommand,
                    handle_update_run_metadata,
                )

                await handle_update_run_metadata(
                    UpdateRunMetadataCommand(
                        run_id=run_id,
                        runner_config_delta=agent_metadata,
                    ),
                    create_wired_event_store_v2(session),
                    session,
                )
                await commit_with_event_outbox(session)
                logger.info(f"Run {run_id}: persisted agent metadata {list(agent_metadata.keys())}")
        except Exception as e:
            logger.warning(f"Failed to persist agent metadata for {run_id}: {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _json_value(value: Any) -> Any:
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else value

    @staticmethod
    def _stable_execution_id(
        prefix: str,
        *,
        run_id: str,
        task_id: str,
        attempt_num: int,
        agent_runner_type: str,
        phase: str,
    ) -> str:
        return f"{prefix}:{run_id}:{task_id}:{attempt_num}:{agent_runner_type}:{phase}"

    @classmethod
    def _dump_token_usage(
        cls, token_usage_by_model: list[ModelTokenUsage] | None
    ) -> list[dict[str, Any]] | None:
        if token_usage_by_model is None:
            return None
        return [cls._json_value(usage) for usage in token_usage_by_model]

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

    async def _upsert_interaction_log_artifact(
        self,
        session: "AsyncSession",
        *,
        run_id: str,
        task_id: str,
        phase: str,
        agent_runner_type: str,
        output_text: str,
        action_log: Any = None,
    ) -> None:
        from orchestrator.db import InteractionLogArtifactModel

        attempt = await self._latest_attempt_context(session, run_id, task_id)
        if attempt is None:
            return
        attempt_num = int(attempt["attempt_num"])
        prompt_text = (
            attempt["verifier_prompt"]
            if phase in {"verifying", "recovering"}
            else attempt["builder_prompt"]
        ) or ""
        await session.merge(
            InteractionLogArtifactModel(
                id=self._stable_execution_id(
                    "interaction-log",
                    run_id=run_id,
                    task_id=task_id,
                    attempt_num=attempt_num,
                    agent_runner_type=agent_runner_type,
                    phase=phase,
                ),
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt["attempt_id"],
                attempt_num=attempt_num,
                agent_runner_type=agent_runner_type,
                phase=phase,
                prompt_text=prompt_text,
                output_text=output_text,
                action_log_json=self._json_value(action_log) if action_log is not None else None,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    async def _upsert_cost_record(
        self,
        session: "AsyncSession",
        *,
        run_id: str,
        task_id: str,
        metrics: ExecutionMetrics,
        token_usage_by_model: list[ModelTokenUsage] | None,
        phase: str,
        agent_runner_type: str,
        model_name: str | None,
        mode_tag: str | None,
    ) -> None:
        from orchestrator.db import CostRecordModel, InteractionLogArtifactModel

        attempt = await self._latest_attempt_context(session, run_id, task_id)
        if attempt is None:
            return

        usage = token_usage_by_model or []
        if usage:
            input_tokens = sum(item.input_tokens for item in usage)
            output_tokens = sum(item.output_tokens for item in usage)
            cache_read_tokens = sum(item.cache_read_tokens for item in usage)
            cache_write_tokens = sum(item.cache_creation_tokens for item in usage)
            cost_usd = sum(item.total_cost_usd for item in usage)
        else:
            input_tokens = metrics.tokens_read
            output_tokens = metrics.tokens_write
            cache_read_tokens = metrics.tokens_cache
            cache_write_tokens = 0
            cost_usd = 0.0

        attempt_num = int(attempt["attempt_num"])
        cost_record_id = self._stable_execution_id(
            "cost",
            run_id=run_id,
            task_id=task_id,
            attempt_num=attempt_num,
            agent_runner_type=agent_runner_type,
            phase=phase,
        )
        await session.merge(
            CostRecordModel(
                id=cost_record_id,
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt["attempt_id"],
                attempt_num=attempt_num,
                agent_runner_type=agent_runner_type,
                phase=phase,
                mode_tag=mode_tag or "default",
                model_name=model_name or (usage[0].model if usage else "unknown"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                wall_time_ms=metrics.duration_ms,
                cost_usd=cost_usd,
                token_usage_by_model=self._dump_token_usage(token_usage_by_model),
                created_at=datetime.now(timezone.utc),
            )
        )
        artifact = await session.get(
            InteractionLogArtifactModel,
            self._stable_execution_id(
                "interaction-log",
                run_id=run_id,
                task_id=task_id,
                attempt_num=attempt_num,
                agent_runner_type=agent_runner_type,
                phase=phase,
            ),
        )
        if artifact is not None:
            artifact.cost_record_id = cost_record_id
        await session.commit()
