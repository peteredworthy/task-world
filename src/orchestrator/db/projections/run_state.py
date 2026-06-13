"""RunStateProjector: maintains runs, steps read-model tables from events."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

import json

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus
from orchestrator.db.orm.models import RunModel, StepModel
from orchestrator.workflow import (
    AgentChangedEvent,
    AttemptUpdated,
    AutoVerifyCompleted,
    ChecklistGateEvaluated,
    ClarificationResponded,
    GradesEvaluated,
    HealthCheckEvent,
    ParentOversightFactsUpdated,
    RunCreated,
    RunDeleted,
    RunMetadataUpdated,
    RunStatusChanged,
    RunStepBackward,
    RunWorktreeCommitCompleted,
    RunWorktreeCommitFailed,
    RunWorktreeCommitRequested,
    RunWorktreeCreationFailed,
    RunWorktreeCreationRequested,
    RunWorktreeResetCompleted,
    RunWorktreeResetFailed,
    RunWorktreeResetRequested,
    RunWorktreeUpdated,
    StepCompleted,
    StepCreated,
    StepHumanApprovalRecorded,
    StepIndexRewound,
    StepSkipped,
    TaskStatusChanged,
    WorkflowEvent,
)
from orchestrator.workflow.oversight_facts import (
    APPEND_ONLY_OVERSIGHT_LIST_KEYS,
    SET_UNION_OVERSIGHT_LIST_KEYS,
)
from orchestrator.time_utils import format_utc_datetime

logger = logging.getLogger(__name__)

_LIST_LIMIT = 100


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _datetime_param(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    return format_utc_datetime(parsed) if parsed is not None else None


def _json_dump(value: Any) -> str:
    return json.dumps(value)


def _merge_token_usage_by_model(
    existing: list[dict[str, Any]] | None,
    delta: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not delta:
        return existing

    merged: list[dict[str, Any]] = [dict(entry) for entry in (existing or [])]
    idx_by_model = {entry["model"]: index for index, entry in enumerate(merged) if "model" in entry}
    for usage in delta:
        usage_dict = dict(usage)
        model_name = usage_dict["model"]
        if model_name in idx_by_model:
            previous = merged[idx_by_model[model_name]]
            merged[idx_by_model[model_name]] = {
                **previous,
                "input_tokens": previous.get("input_tokens", 0) + usage_dict.get("input_tokens", 0),
                "output_tokens": previous.get("output_tokens", 0)
                + usage_dict.get("output_tokens", 0),
                "cache_read_tokens": previous.get("cache_read_tokens", 0)
                + usage_dict.get("cache_read_tokens", 0),
                "cache_creation_tokens": previous.get("cache_creation_tokens", 0)
                + usage_dict.get("cache_creation_tokens", 0),
            }
        else:
            idx_by_model[model_name] = len(merged)
            merged.append(usage_dict)
    return merged


def merge_oversight_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a patch dict into oversight state using append-only list semantics."""
    result = dict(state)
    for key, value in patch.items():
        if key in APPEND_ONLY_OVERSIGHT_LIST_KEYS and isinstance(value, list):
            existing = result.get(key)
            current_items: list[Any] = (
                list(cast(list[Any], existing)) if isinstance(existing, list) else []
            )
            for item in cast(list[Any], value):
                if item not in current_items:
                    current_items.append(item)
            result[key] = current_items[-_LIST_LIMIT:]
        elif key in SET_UNION_OVERSIGHT_LIST_KEYS and isinstance(value, list):
            existing = result.get(key)
            current_strings: set[str] = (
                {item for item in cast(list[Any], existing) if isinstance(item, str)}
                if isinstance(existing, list)
                else set()
            )
            current_strings.update(item for item in cast(list[Any], value) if isinstance(item, str))
            result[key] = sorted(current_strings)
        elif key == "delegated_work" and isinstance(value, dict):
            raw_work = result.get("delegated_work")
            merged_work: dict[str, Any] = (
                dict(cast(dict[str, Any], raw_work)) if isinstance(raw_work, dict) else {}
            )
            merged_work.update(cast(dict[str, Any], value))
            result[key] = merged_work
        else:
            result[key] = value
    return result


class RunStateProjector:
    """Maintains runs and steps tables from run-lifecycle events."""

    handled_events: frozenset[type] = frozenset(
        {
            RunCreated,
            StepCreated,
            RunStatusChanged,
            RunWorktreeCreationFailed,
            RunWorktreeCreationRequested,
            RunWorktreeUpdated,
            RunMetadataUpdated,
            AgentChangedEvent,
            AttemptUpdated,
            TaskStatusChanged,
            StepCompleted,
            StepHumanApprovalRecorded,
            StepSkipped,
            RunStepBackward,
            GradesEvaluated,
            AutoVerifyCompleted,
            ChecklistGateEvaluated,
            ClarificationResponded,
            HealthCheckEvent,
            StepIndexRewound,
            ParentOversightFactsUpdated,
            RunDeleted,
        }
    )

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        match event:
            case RunCreated():
                if event.run_snapshot:
                    await self._insert_run_from_snapshot(event, session)
                    return
                await session.execute(
                    text(
                        "INSERT OR IGNORE INTO runs"
                        " (id, repo_name, status, pause_reason, last_error,"
                        " execution_mode, config, routine_id, parent_run_id, parent_task_id,"
                        " routine_sha, routine_source, routine_embedded,"
                        " routine_path, routine_commit, parent_slice_id,"
                        " runner_type, runner_config, verifier_model,"
                        " worktree_enabled, worktree_path, delete_worktree_on_completion,"
                        " source_branch, source_branch_sha, merge_strategy,"
                        " oversight_state, env_file_specs, env_source_dir,"
                        " current_step_index, transition_tracker,"
                        " total_tokens_read, total_tokens_write, total_tokens_cache,"
                        " total_duration_ms, total_num_actions,"
                        " token_usage_by_model,"
                        " created_at, updated_at, started_at, completed_at, runner_started_at)"
                        " VALUES (:id, :repo_name, :status, :pause_reason, :last_error,"
                        " :execution_mode, :config, :routine_id,"
                        " :parent_run_id, :parent_task_id,"
                        " :routine_sha, :routine_source, :routine_embedded,"
                        " :routine_path, :routine_commit, :parent_slice_id,"
                        " :runner_type, :runner_config, :verifier_model,"
                        " :worktree_enabled, :worktree_path, :delete_worktree_on_completion,"
                        " :source_branch, :source_branch_sha, :merge_strategy,"
                        " :oversight_state, :env_file_specs, :env_source_dir,"
                        " :current_step_index, :transition_tracker,"
                        " :total_tokens_read, :total_tokens_write, :total_tokens_cache,"
                        " :total_duration_ms, :total_num_actions,"
                        " :token_usage_by_model,"
                        " :created_at, :updated_at, :started_at, :completed_at, :runner_started_at)"
                    ),
                    {
                        "id": event.run_id,
                        "repo_name": event.repo_name,
                        "status": getattr(event.status, "value", event.status),
                        "pause_reason": event.pause_reason,
                        "last_error": event.last_error,
                        "execution_mode": event.execution_mode,
                        "config": json.dumps(event.config),
                        "routine_id": event.routine_id or None,
                        "parent_run_id": event.parent_run_id,
                        "parent_task_id": event.parent_task_id,
                        "routine_sha": event.routine_sha,
                        "routine_source": event.routine_source,
                        "routine_embedded": _json_dump(event.routine_embedded),
                        "routine_path": event.routine_path,
                        "routine_commit": event.routine_commit,
                        "parent_slice_id": event.parent_slice_id,
                        "runner_type": event.runner_type,
                        "runner_config": _json_dump(event.runner_config),
                        "verifier_model": event.verifier_model,
                        "worktree_enabled": 1 if event.worktree_enabled else 0,
                        "worktree_path": event.worktree_path,
                        "delete_worktree_on_completion": 1
                        if event.delete_worktree_on_completion
                        else 0,
                        "source_branch": event.source_branch,
                        "source_branch_sha": event.source_branch_sha,
                        "merge_strategy": event.merge_strategy,
                        "oversight_state": _json_dump(event.oversight_state),
                        "env_file_specs": _json_dump(event.env_file_specs),
                        "env_source_dir": event.env_source_dir,
                        "current_step_index": event.current_step_index,
                        "transition_tracker": _json_dump(event.transition_tracker)
                        if event.transition_tracker is not None
                        else None,
                        "total_tokens_read": event.total_tokens_read,
                        "total_tokens_write": event.total_tokens_write,
                        "total_tokens_cache": event.total_tokens_cache,
                        "total_duration_ms": event.total_duration_ms,
                        "total_num_actions": event.total_num_actions,
                        "token_usage_by_model": _json_dump(event.token_usage_by_model),
                        "created_at": _datetime_param(event.created_at)
                        or _datetime_param(event.timestamp),
                        "updated_at": _datetime_param(event.updated_at)
                        or _datetime_param(event.timestamp),
                        "started_at": _datetime_param(event.started_at),
                        "completed_at": _datetime_param(event.completed_at),
                        "runner_started_at": _datetime_param(event.agent_runner_started_at),
                    },
                )
            case StepCreated():
                await session.execute(
                    text(
                        "INSERT OR IGNORE INTO steps"
                        " (id, run_id, config_id, title, order_index, completed,"
                        " human_approval, skipped, skip_reason, condition)"
                        " VALUES (:id, :run_id, :config_id, :title, :order_index,"
                        " :completed, :human_approval, :skipped, :skip_reason,"
                        " :condition)"
                    ),
                    {
                        "id": event.step_id,
                        "run_id": event.run_id,
                        "config_id": event.config_id,
                        "title": event.title,
                        "order_index": event.order_index,
                        "completed": 1 if event.completed else 0,
                        "human_approval": _json_dump(event.human_approval),
                        "skipped": 1 if event.skipped else 0,
                        "skip_reason": event.skip_reason,
                        "condition": _json_dump(event.condition),
                    },
                )
            case RunDeleted():
                model = await session.get(RunModel, event.run_id)
                if model is not None:
                    await session.delete(model)
            case RunStatusChanged():
                old_status = getattr(event.old_status, "value", event.old_status)
                new_status = getattr(event.new_status, "value", event.new_status)
                values: dict[str, Any] = {
                    "status": new_status,
                    "pause_reason": event.pause_reason,
                    "last_error": event.last_error,
                }
                if old_status == RunStatus.DRAFT.value and new_status == RunStatus.ACTIVE.value:
                    values["started_at"] = event.timestamp
                if new_status in (RunStatus.FAILED.value, RunStatus.COMPLETED.value):
                    values["completed_at"] = event.timestamp
                else:
                    values["completed_at"] = None
                await session.execute(
                    update(RunModel).where(RunModel.id == event.run_id).values(**values)
                )
            case RunWorktreeUpdated():
                values: dict[str, Any] = {"worktree_path": event.worktree_path}
                if event.source_branch_sha is not None:
                    values["source_branch_sha"] = event.source_branch_sha
                await session.execute(
                    update(RunModel).where(RunModel.id == event.run_id).values(**values)
                )
            case (
                RunWorktreeCreationRequested()
                | RunWorktreeCreationFailed()
                | RunWorktreeCommitRequested()
                | RunWorktreeCommitCompleted()
                | RunWorktreeCommitFailed()
                | RunWorktreeResetRequested()
                | RunWorktreeResetCompleted()
                | RunWorktreeResetFailed()
            ):
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(updated_at=event.timestamp)
                )
            case RunMetadataUpdated():
                row = await session.execute(
                    select(RunModel.runner_config).where(RunModel.id == event.run_id)
                )
                current_config = dict(row.scalar_one_or_none() or {})
                current_config.update(event.runner_config_delta)
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(runner_config=current_config, updated_at=event.timestamp)
                )
            case AgentChangedEvent():
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(
                        runner_type=event.new_agent.value,
                        runner_config=event.new_agent_runner_config,
                    )
                )
            case ClarificationResponded():
                if event.run_config_delta:
                    row = await session.execute(
                        select(RunModel.config).where(RunModel.id == event.run_id)
                    )
                    current_config = dict(row.scalar_one_or_none() or {})
                    current_config.update(event.run_config_delta)
                    await session.execute(
                        update(RunModel)
                        .where(RunModel.id == event.run_id)
                        .values(config=current_config, updated_at=event.timestamp)
                    )
            case AttemptUpdated():
                if not event.apply_to_run_totals:
                    return
                values: dict[str, Any] = {}
                if event.tokens_read is not None:
                    values["total_tokens_read"] = RunModel.total_tokens_read + event.tokens_read
                if event.tokens_write is not None:
                    values["total_tokens_write"] = RunModel.total_tokens_write + event.tokens_write
                if event.tokens_cache is not None:
                    values["total_tokens_cache"] = RunModel.total_tokens_cache + event.tokens_cache
                if event.duration_ms is not None:
                    values["total_duration_ms"] = RunModel.total_duration_ms + event.duration_ms
                if event.num_actions is not None:
                    values["total_num_actions"] = RunModel.total_num_actions + event.num_actions
                if event.token_usage_by_model is not None:
                    row = await session.execute(
                        select(RunModel.token_usage_by_model).where(RunModel.id == event.run_id)
                    )
                    values["token_usage_by_model"] = _merge_token_usage_by_model(
                        row.scalar_one_or_none(),
                        event.token_usage_by_model,
                    )
                if values:
                    await session.execute(
                        update(RunModel).where(RunModel.id == event.run_id).values(**values)
                    )
            case StepCompleted():
                await session.execute(
                    update(StepModel).where(StepModel.id == event.step_id).values(completed=True)
                )
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(current_step_index=event.step_index + 1)
                )
            case StepHumanApprovalRecorded():
                await session.execute(
                    update(StepModel)
                    .where(StepModel.id == event.step_id)
                    .values(
                        human_approval={
                            "approved_by": event.approved_by,
                            "approved_at": format_utc_datetime(event.approved_at),
                            "comment": event.comment,
                        }
                    )
                )
            case StepSkipped():
                await session.execute(
                    update(StepModel)
                    .where(StepModel.id == event.step_id)
                    .values(
                        skipped=True,
                        skip_reason=event.skip_reason,
                        completed=event.completed,
                    )
                )
                current_step_index_after = event.current_step_index_after
                if current_step_index_after is None:
                    current_step_index_after = event.step_index + 1
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(current_step_index=current_step_index_after)
                )
            case RunStepBackward():
                values: dict[str, Any] = {"current_step_index": event.to_step_index}
                if event.transition_tracker_delta:
                    row = await session.execute(
                        select(RunModel.transition_tracker).where(RunModel.id == event.run_id)
                    )
                    raw_tracker = row.scalar_one_or_none()
                    tracker: dict[str, Any] = dict(raw_tracker if raw_tracker else {"counts": {}})
                    raw_counts = tracker.get("counts")
                    counts: dict[str, int] = dict(
                        cast(dict[str, int], raw_counts) if raw_counts else {}
                    )
                    for key, delta in event.transition_tracker_delta.items():
                        counts[key] = int(counts.get(key, 0)) + delta
                    tracker["counts"] = counts
                    values["transition_tracker"] = tracker
                await session.execute(
                    update(RunModel).where(RunModel.id == event.run_id).values(**values)
                )
                await session.execute(
                    update(StepModel)
                    .where(
                        StepModel.run_id == event.run_id,
                        StepModel.order_index >= event.to_step_index,
                        StepModel.order_index <= event.from_step_index,
                    )
                    .values(completed=False)
                )
            case StepIndexRewound():
                await session.execute(
                    update(RunModel)
                    .where(
                        RunModel.id == event.run_id,
                        RunModel.current_step_index > event.target_step_index,
                    )
                    .values(current_step_index=event.target_step_index)
                )
            case ParentOversightFactsUpdated():
                row = await session.execute(
                    select(RunModel.oversight_state).where(RunModel.id == event.run_id)
                )
                current_state: dict[str, Any] = dict(row.scalar_one_or_none() or {})
                merged = merge_oversight_patch(current_state, event.patch)
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(oversight_state=merged)
                )
            case _:
                pass  # GradesEvaluated, AutoVerifyCompleted, ChecklistGateEvaluated,
                # HealthCheckEvent, TaskStatusChanged — no run-table mutation needed here

    async def _insert_run_from_snapshot(
        self,
        event: RunCreated,
        session: AsyncSession,
    ) -> None:
        snapshot = event.run_snapshot
        await session.execute(
            text(
                "INSERT OR IGNORE INTO runs"
                " (id, repo_name, status, pause_reason, last_error,"
                " execution_mode, routine_id, routine_sha, routine_source, routine_embedded,"
                " routine_path, routine_commit, parent_run_id, parent_task_id, parent_slice_id,"
                " oversight_state, runner_type, runner_config, verifier_model,"
                " worktree_enabled, worktree_path, delete_worktree_on_completion,"
                " source_branch, source_branch_sha, merge_strategy, config,"
                " env_file_specs, env_source_dir, current_step_index, transition_tracker,"
                " created_at, updated_at, started_at, completed_at,"
                " runner_started_at, scheduled_resume_at, total_tokens_read, total_tokens_write,"
                " total_tokens_cache, total_duration_ms, total_num_actions,"
                " token_usage_by_model)"
                " VALUES (:id, :repo_name, :status, :pause_reason, :last_error,"
                " :execution_mode, :routine_id, :routine_sha, :routine_source, :routine_embedded,"
                " :routine_path, :routine_commit, :parent_run_id, :parent_task_id,"
                " :parent_slice_id,"
                " :oversight_state, :runner_type, :runner_config, :verifier_model,"
                " :worktree_enabled, :worktree_path, :delete_worktree_on_completion,"
                " :source_branch, :source_branch_sha, :merge_strategy, :config,"
                " :env_file_specs, :env_source_dir, :current_step_index, :transition_tracker,"
                " :created_at, :updated_at, :started_at, :completed_at,"
                " :runner_started_at, :scheduled_resume_at, :total_tokens_read, :total_tokens_write,"
                " :total_tokens_cache, :total_duration_ms, :total_num_actions,"
                " :token_usage_by_model)"
            ),
            {
                "id": snapshot.get("id") or event.run_id,
                "repo_name": snapshot.get("repo_name") or event.repo_name,
                "status": snapshot.get("status") or getattr(event.status, "value", event.status),
                "pause_reason": snapshot.get("pause_reason"),
                "last_error": snapshot.get("last_error"),
                "execution_mode": snapshot.get("execution_mode") or event.execution_mode,
                "routine_id": snapshot.get("routine_id") or event.routine_id or None,
                "routine_sha": snapshot.get("routine_sha"),
                "routine_source": snapshot.get("routine_source"),
                "routine_embedded": _json_dump(snapshot.get("routine_embedded")),
                "routine_path": snapshot.get("routine_path"),
                "routine_commit": snapshot.get("routine_commit"),
                "parent_run_id": snapshot.get("parent_run_id") or event.parent_run_id,
                "parent_task_id": snapshot.get("parent_task_id") or event.parent_task_id,
                "parent_slice_id": snapshot.get("parent_slice_id"),
                "oversight_state": _json_dump(snapshot.get("oversight_state") or {}),
                "runner_type": snapshot.get("agent_runner_type"),
                "runner_config": _json_dump(snapshot.get("agent_runner_config") or {}),
                "verifier_model": snapshot.get("verifier_model"),
                "worktree_enabled": 1 if snapshot.get("worktree_enabled", True) else 0,
                "worktree_path": snapshot.get("worktree_path"),
                "delete_worktree_on_completion": 1
                if snapshot.get("delete_worktree_on_completion", False)
                else 0,
                "source_branch": snapshot.get("source_branch"),
                "source_branch_sha": snapshot.get("source_branch_sha"),
                "merge_strategy": snapshot.get("merge_strategy"),
                "config": _json_dump(snapshot.get("config") or event.config),
                "env_file_specs": _json_dump(snapshot.get("env_file_specs") or []),
                "env_source_dir": snapshot.get("env_source_dir"),
                "current_step_index": snapshot.get("current_step_index", 0),
                "transition_tracker": _json_dump(snapshot.get("transition_tracker"))
                if snapshot.get("transition_tracker") is not None
                else None,
                "created_at": _datetime_param(snapshot.get("created_at"))
                or _datetime_param(event.timestamp),
                "updated_at": _datetime_param(snapshot.get("updated_at"))
                or _datetime_param(event.timestamp),
                "started_at": _datetime_param(snapshot.get("started_at")),
                "completed_at": _datetime_param(snapshot.get("completed_at")),
                "runner_started_at": _datetime_param(snapshot.get("agent_runner_started_at")),
                "scheduled_resume_at": _datetime_param(snapshot.get("scheduled_resume_at")),
                "total_tokens_read": snapshot.get("total_tokens_read", 0),
                "total_tokens_write": snapshot.get("total_tokens_write", 0),
                "total_tokens_cache": snapshot.get("total_tokens_cache", 0),
                "total_duration_ms": snapshot.get("total_duration_ms", 0),
                "total_num_actions": snapshot.get("total_num_actions", 0),
                "token_usage_by_model": _json_dump(snapshot.get("token_usage_by_model")),
            },
        )

    async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:
        for event in events:
            if type(event) in self.handled_events:
                await self.handle(event, session)
