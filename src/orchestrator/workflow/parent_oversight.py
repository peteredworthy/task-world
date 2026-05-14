"""Application boundary for parent oversight workflow operations."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus
from orchestrator.config.global_config import GlobalConfig
from orchestrator.db import RunRepository
from orchestrator.git import ParentChildMergeResult, merge_child_into_parent
from orchestrator.git.utils import get_head_commit
from orchestrator.state import Run
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.delegation import (
    DelegateCommand,
    DelegatedWork,
    DelegationDecision,
    DelegationRecorder,
    SuperParentDelegationPolicy,
    apply_delegate_command,
    result_from_child_evidence,
    work_from_child_run,
)
from orchestrator.workflow.engine import Clock
from orchestrator.workflow.engine.errors import InvalidTransitionError
from orchestrator.workflow.events import BufferingEmitter, RunStatusChanged
from orchestrator.workflow.events.logger import PersistentEventEmitter
from orchestrator.workflow.oversight import (
    ACCEPTANCE_OUTCOMES,
    FinalValidationMarker,
    REVISION_OUTCOMES,
    RunEvidenceBundle,
    TargetInventoryItem,
    validate_run_evidence_items,
)
from orchestrator.workflow.oversight_projection import (
    delegation_decision_from_parent_snapshot,
    project_parent_oversight,
)
from orchestrator.workflow.oversight_facts import extract_parent_oversight_facts
from orchestrator.workflow.signals.signals import (
    DbSignalTransport,
    SignalQueue,
    SignalTransport,
    WorkflowSignal,
)


@dataclass(frozen=True)
class ChildRunResolutionResult:
    """Result of a parent decision to close a child without merging it."""

    parent_run_id: str
    child_run_id: str
    resolution: Literal["reject", "abandon"]
    reason: str
    resolved_at: datetime


class ParentOversightService:
    """Coordinate parent/child oversight state, projection, and terminal guards."""

    def __init__(
        self,
        session: AsyncSession,
        repo: RunRepository,
        event_emitter: PersistentEventEmitter,
        clock: Clock,
        *,
        global_config: GlobalConfig | None = None,
        super_parent_policy: SuperParentDelegationPolicy | None = None,
        signal_transport: SignalTransport | None = None,
    ) -> None:
        self._session = session
        self._repo = repo
        self._event_emitter = event_emitter
        self._clock = clock
        self._global_config = global_config
        self._super_parent_policy = super_parent_policy or SuperParentDelegationPolicy()
        self._signal_transport = signal_transport
        self._delegation_recorder = DelegationRecorder(clock)

    def _get_signal_queue(self) -> SignalQueue:
        """Return a SignalQueue backed by the injected transport or the default DbSignalTransport."""
        transport = self._signal_transport or DbSignalTransport(self._session)
        return SignalQueue(transport)

    async def get_parent_oversight(self, parent_run_id: str) -> dict[str, Any]:
        """Return current deterministic oversight state for a parent run."""
        parent = await self._repo.get(parent_run_id)
        return await self.compute_parent_oversight_state(parent)

    def strip_computed_oversight_for_persist(self, run: Run) -> Run:
        """Keep only durable oversight facts before generic run persistence."""
        if self.is_oversight_parent_run(run):
            run.oversight_state = extract_parent_oversight_facts(run.oversight_state)
        return run

    async def hydrate_if_parent(self, run: Run) -> Run:
        """Attach computed oversight to parent runs before returning API data."""
        if self.is_oversight_parent_run(run):
            run.oversight_state = await self.compute_parent_oversight_state(run)
        return run

    async def update_parent_oversight(
        self,
        parent_run_id: str,
        *,
        current_understanding: dict[str, Any] | None = None,
        target_inventory: list[dict[str, Any]] | None = None,
        final_validation: dict[str, Any] | None = None,
        decisions: list[dict[str, Any]] | None = None,
    ) -> Run:
        """Persist parent-authored oversight facts, then recompute derived state."""
        parent = await self._repo.get(parent_run_id)
        if parent.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (parent is terminal)",
            )

        state: dict[str, Any] = dict(parent.oversight_state)
        if current_understanding is not None:
            state["current_understanding"] = current_understanding
        if target_inventory is not None:
            state["target_inventory"] = [
                TargetInventoryItem.model_validate(item).model_dump(mode="json")
                for item in target_inventory
            ]
        if final_validation is not None:
            state["final_validation"] = self._verify_final_validation_marker(
                parent,
                final_validation,
            ).model_dump(mode="json")
        if decisions is not None:
            existing_decisions = self._state_dict_list(state.get("decisions"))
            existing_decisions.extend(dict(item) for item in decisions)
            state["decisions"] = existing_decisions

        parent.oversight_state = self.drop_stale_final_validation(parent, state)
        await self.refresh_parent_oversight_without_commit(parent_run_id, parent=parent)
        await self._session.commit()
        return parent

    def _verify_final_validation_marker(
        self,
        parent: Run,
        final_validation: dict[str, Any],
    ) -> FinalValidationMarker:
        """Stamp final validation only after checking deterministic worktree facts."""
        marker = FinalValidationMarker.model_validate(final_validation).model_copy(
            update={"service_verified": False}
        )
        worktree = self._final_validation_worktree(parent)
        head_commit = get_head_commit(worktree)
        if head_commit is None:
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation requires git worktree)",
            )
        if head_commit != marker.integrated_commit_sha:
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation commit does not match parent HEAD)",
            )
        if marker.passed and any(command.exit_code != 0 for command in marker.commands_run):
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation command failed)",
            )

        self._resolve_final_validation_artifact(parent, worktree, marker.report_path)
        for evidence_file in marker.evidence_files:
            self._resolve_final_validation_artifact(parent, worktree, evidence_file)

        return marker.model_copy(update={"service_verified": True})

    def _final_validation_worktree(self, parent: Run) -> Path:
        if parent.worktree_path is None:
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation requires parent worktree)",
            )
        worktree = Path(parent.worktree_path).resolve()
        if not worktree.is_dir():
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation requires parent worktree)",
            )
        return worktree

    def _resolve_final_validation_artifact(
        self,
        parent: Run,
        worktree: Path,
        raw_path: str,
    ) -> Path:
        if (
            raw_path != raw_path.strip()
            or PurePosixPath(raw_path).is_absolute()
            or (len(raw_path) >= 2 and raw_path[1] == ":")
            or ".." in PurePosixPath(raw_path).parts
            or "\\" in raw_path
            or re.search(r"[\x00-\x1f]", raw_path)
        ):
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation artifact path invalid)",
            )

        resolved = (worktree / raw_path).resolve()
        if resolved != worktree and worktree not in resolved.parents:
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation artifact path invalid)",
            )
        if not resolved.is_file():
            raise InvalidTransitionError(
                parent.status.value,
                "update_parent_oversight (final validation artifact missing)",
            )
        return resolved

    def drop_stale_final_validation(
        self,
        parent: Run,
        oversight_state: dict[str, Any],
    ) -> dict[str, Any]:
        state = dict(oversight_state)
        raw_marker = state.get("final_validation")
        if not isinstance(raw_marker, dict):
            return state
        try:
            marker = FinalValidationMarker.model_validate(raw_marker)
        except ValidationError:
            return state
        if not marker.service_verified:
            return state
        if parent.worktree_path is None:
            state["final_validation"] = None
            return state

        head_commit = get_head_commit(Path(parent.worktree_path))
        if head_commit != marker.integrated_commit_sha:
            state["final_validation"] = None
        return state

    async def refresh_parent_oversight(self, parent_run_id: str) -> Run:
        """Recompute and persist the parent oversight snapshot from child state."""
        parent = await self.refresh_parent_oversight_without_commit(parent_run_id)
        await self._session.commit()
        return parent

    async def refresh_parent_oversight_without_commit(
        self,
        parent_run_id: str,
        *,
        parent: Run | None = None,
    ) -> Run:
        """Recompute and save parent oversight state without committing."""
        parent = parent or await self._repo.get(parent_run_id)
        return await self.persist_parent_oversight_state(
            parent,
            parent.oversight_state,
            commit=False,
        )

    async def compute_parent_oversight_state(self, parent: Run) -> dict[str, Any]:
        """Compute parent oversight from persisted parent facts plus current children."""
        parent_run_id = parent.id
        children = await self._repo.list_child_runs(parent_run_id, include_action_logs=False)
        evidence_by_run_id = await self._collect_child_evidence(children)
        parent_for_reduce = parent.model_copy(
            deep=True,
            update={
                "oversight_state": extract_parent_oversight_facts(
                    self.drop_stale_final_validation(
                        parent,
                        parent.oversight_state,
                    )
                )
            },
        )
        return project_parent_oversight(
            parent_for_reduce,
            children,
            evidence_by_run_id,
            max_child_runs=self.max_child_runs_for_parent(parent_for_reduce),
        )

    async def persist_parent_oversight_state(
        self,
        parent: Run,
        state: dict[str, Any],
        *,
        commit: bool,
    ) -> Run:
        """Persist durable parent facts and hydrate the computed projection."""
        durable_facts = extract_parent_oversight_facts(
            self.drop_stale_final_validation(parent, state)
        )
        merged_facts = await self._repo.update_parent_oversight_facts(parent.id, durable_facts)
        parent.oversight_state = merged_facts
        children = await self._repo.list_child_runs(parent.id, include_action_logs=False)
        evidence_by_run_id = await self._collect_child_evidence(children)
        parent_for_projection = parent.model_copy(
            deep=True,
            update={"oversight_state": merged_facts},
        )
        projected_state = project_parent_oversight(
            parent_for_projection,
            children,
            evidence_by_run_id,
            max_child_runs=self.max_child_runs_for_parent(parent_for_projection),
        )
        if commit:
            await self._session.commit()
        parent.oversight_state = projected_state
        return parent

    def max_child_runs_for_parent(self, parent: Run) -> int:
        """Resolve the configured child-run limit for a parent run."""
        for source in (parent.oversight_state, parent.config):
            value = source.get("max_child_runs")
            if isinstance(value, int) and value > 0:
                return value
            if isinstance(value, str):
                try:
                    parsed = int(value)
                except ValueError:
                    continue
                if parsed > 0:
                    return parsed
        return 20

    async def collect_run_evidence(self, run_id: str) -> list[dict[str, Any]]:
        """Collect run.evidence.v1 bundles from a run worktree."""
        run = await self._repo.get(run_id)
        if not run.worktree_path:
            return []

        worktree = Path(run.worktree_path).resolve()
        if not worktree.is_dir():
            return []

        def is_evidence_json_path(path: Path) -> bool:
            if path.suffix != ".json":
                return False
            return "evidence" in path.name.lower() or any(
                "evidence" in part.lower() for part in path.parts
            )

        def changed_evidence_paths() -> list[Path] | None:
            if not run.source_branch_sha:
                return None
            try:
                diff = subprocess.run(
                    [
                        "git",
                        "diff",
                        "--name-only",
                        "--diff-filter=ACMRT",
                        f"{run.source_branch_sha}..HEAD",
                    ],
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                untracked = subprocess.run(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError:
                return None

            rel_paths = {
                line.strip()
                for output in (diff.stdout, untracked.stdout)
                for line in output.splitlines()
                if line.strip()
            }
            return [
                worktree / rel_path
                for rel_path in sorted(rel_paths)
                if is_evidence_json_path(Path(rel_path))
            ]

        def scan() -> list[dict[str, Any]]:
            bundles: list[dict[str, Any]] = []
            candidate_paths = changed_evidence_paths()
            paths = (
                candidate_paths
                if candidate_paths is not None
                else [
                    path for path in sorted(worktree.rglob("*.json")) if is_evidence_json_path(path)
                ]
            )
            for path in paths:
                if len(bundles) >= 100:
                    break
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if not resolved.is_file() or worktree not in resolved.parents:
                    continue
                try:
                    if resolved.stat().st_size > 1_000_000:
                        continue
                    raw = resolved.read_text(encoding="utf-8")
                    data = json.loads(raw)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                bundle = cast(dict[str, Any], data)
                if bundle.get("schema_version") != "run.evidence.v1":
                    continue
                bundles.append(
                    {
                        "path": str(resolved.relative_to(worktree)),
                        "bundle": bundle,
                    }
                )
            return bundles

        return await asyncio.to_thread(scan)

    async def _collect_child_evidence(
        self, child_runs: list[Run]
    ) -> dict[str, list[dict[str, Any]]]:
        evidence_by_run_id: dict[str, list[dict[str, Any]]] = {}
        for child in child_runs:
            evidence_by_run_id[child.id] = await self.collect_run_evidence(child.id)
        return evidence_by_run_id

    async def apply_oversight_terminal_guard(
        self,
        run: Run,
        state: SessionStateManager,
        buffer: BufferingEmitter,
        *,
        emit_status_change: bool = True,
    ) -> None:
        children = await self._repo.list_child_runs(run.id, include_action_logs=False)
        if not children and not self.is_oversight_parent_run(run):
            return

        evidence_by_run_id = await self._collect_child_evidence(children)
        fact_state = extract_parent_oversight_facts(
            self.drop_stale_final_validation(run, run.oversight_state)
        )
        run.oversight_state = fact_state
        oversight_state = project_parent_oversight(
            run,
            children,
            evidence_by_run_id,
            max_child_runs=self.max_child_runs_for_parent(run),
        )
        terminal_guard = oversight_state.get("terminal_guard", {})
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED) and not terminal_guard.get(
            "can_complete",
            False,
        ):
            policy_decision = delegation_decision_from_parent_snapshot(oversight_state)
            fact_state = self._delegation_recorder.record_decision(
                fact_state,
                policy_decision,
            )
            run.oversight_state = extract_parent_oversight_facts(fact_state)
            old_status = run.status
            run.status = RunStatus.PAUSED
            run.pause_reason = "oversight_children_unresolved"
            blocking_reasons = terminal_guard.get("blocking_reasons", [])
            run.last_error = (
                "Parent run cannot complete while child oversight is unresolved: "
                + "; ".join(str(reason) for reason in blocking_reasons)
            )
            run.completed_at = None
            if emit_status_change:
                buffer.emit(
                    RunStatusChanged(
                        timestamp=self._clock.now(),
                        run_id=run.id,
                        event_type="run_status_changed",
                        old_status=old_status,
                        new_status=RunStatus.PAUSED,
                    )
                )
        else:
            run.oversight_state = fact_state
        state.update_run(run)

    def resolved_child_run_ids(self, parent: Run) -> set[str]:
        """Return child IDs that the parent has explicitly resolved."""
        state = parent.oversight_state
        resolved: set[str] = set()
        for key in (
            "accepted_child_run_ids",
            "rejected_child_run_ids",
            "abandoned_child_run_ids",
            "closed_child_run_ids",
        ):
            resolved.update(self._state_str_list(state.get(key)))
        for item in self._state_dict_list(state.get("accepted_children")):
            child_id = item.get("child_run_id") or item.get("run_id")
            if isinstance(child_id, str):
                resolved.add(child_id)
        return resolved

    def delegation_work_for_child_command(self, parent: Run, child: Run) -> Any:
        live_work = work_from_child_run(
            child,
            resolved=child.id in self.resolved_child_run_ids(parent),
        ).model_copy(update={"owner_token": self.delegation_owner_token(parent)})
        raw_work = parent.oversight_state.get("delegated_work")
        if not isinstance(raw_work, dict):
            return live_work
        delegated_work = cast(dict[str, Any], raw_work)
        raw_child_work = delegated_work.get(child.id)
        if not isinstance(raw_child_work, dict):
            return live_work
        existing = DelegatedWork.model_validate(raw_child_work)
        status = existing.status
        if existing.status == "requested" and live_work.status in ("running", "waiting"):
            status = live_work.status
        if existing.status in ("requested", "running", "waiting") and live_work.status in (
            "terminal",
            "review",
        ):
            status = live_work.status
        return live_work.model_copy(
            update={
                "generation": existing.generation,
                "status": status,
                "owner_token": existing.owner_token or live_work.owner_token,
                "idempotency_keys": existing.idempotency_keys,
            }
        )

    def delegation_owner_token(self, parent: Run) -> str:
        token = parent.oversight_state.get("delegation_owner_token")
        if isinstance(token, str) and token:
            return token
        return f"run:{parent.id}"

    def delegation_command_key(
        self,
        parent_run_id: str,
        child_run_id: str,
        action: str,
    ) -> str:
        return f"{parent_run_id}:{child_run_id}:{action}"

    async def accept_child_run(
        self,
        parent_run_id: str,
        child_run_id: str,
        *,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
        owner_token: str | None = None,
    ) -> ParentChildMergeResult:
        """Accept a completed child by merging it into the parent run branch."""
        parent = await self._repo.get(parent_run_id)
        child = await self._repo.get(child_run_id)
        if child.parent_run_id != parent_run_id:
            raise InvalidTransitionError(child.status.value, "accept_child_run (wrong parent)")
        if child.status != RunStatus.COMPLETED:
            raise InvalidTransitionError(
                child.status.value,
                "accept_child_run (requires completed child)",
            )
        if not parent.worktree_path:
            raise InvalidTransitionError(
                parent.status.value,
                "accept_child_run (parent missing worktree)",
            )
        if not child.worktree_path:
            raise InvalidTransitionError(
                child.status.value,
                "accept_child_run (child missing worktree)",
            )

        state = dict(parent.oversight_state)
        work = self.delegation_work_for_child_command(parent, child)
        command_key = idempotency_key or self.delegation_command_key(
            parent_run_id,
            child.id,
            "integrate",
        )
        command_owner_token = owner_token or self.delegation_owner_token(parent)
        integrate_command = DelegateCommand(
            kind="integrate",
            work_id=child.id,
            owner_id=parent.id,
            idempotency_key=command_key,
            expected_generation=expected_generation
            if expected_generation is not None
            else work.generation,
            owner_token=command_owner_token,
        )
        accepted_ids = set(self._state_str_list(state.get("accepted_child_run_ids")))
        for item in self._state_dict_list(state.get("accepted_children")):
            accepted_child_id = item.get("child_run_id") or item.get("run_id")
            if isinstance(accepted_child_id, str):
                accepted_ids.add(accepted_child_id)
        command_work, integrate_decision = apply_delegate_command(work, integrate_command)
        if child.id in accepted_ids:
            state = self._delegation_recorder.record_decision(
                state,
                integrate_decision,
                idempotency_key=integrate_command.idempotency_key,
                expected_generation=integrate_command.expected_generation,
                owner_token=integrate_command.owner_token,
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            accepted_child = next(
                (
                    item
                    for item in self._state_dict_list(state.get("accepted_children"))
                    if item.get("child_run_id") == child.id
                ),
                None,
            )
            merge_commit_sha = (
                accepted_child.get("merge_commit_sha") if accepted_child is not None else None
            )
            return ParentChildMergeResult(
                status="clean",
                parent_branch=f"orchestrator/run-{parent_run_id}",
                child_branch=f"orchestrator/run-{child_run_id}",
                merge_commit_sha=merge_commit_sha if isinstance(merge_commit_sha, str) else None,
            )
        if integrate_decision.kind != "integrate":
            state = self._delegation_recorder.record_decision(
                state,
                integrate_decision,
                idempotency_key=integrate_command.idempotency_key,
                expected_generation=integrate_command.expected_generation,
                owner_token=integrate_command.owner_token,
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            raise InvalidTransitionError(
                child.status.value,
                "accept_child_run (stale delegation command)",
            )

        child_evidence = await self.collect_run_evidence(child_run_id)
        try:
            child_outcomes = await self._validate_child_evidence_for_acceptance(
                child,
                child_evidence,
            )
        except InvalidTransitionError as err:
            state = self._delegation_recorder.record_review_state(
                parent.oversight_state,
                work_id=child.id,
                stable_state="InvalidEvidence",
                reason="child_evidence_invalid",
                payload={"message": str(err), "evidence_count": len(child_evidence)},
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            raise
        if not child_outcomes & ACCEPTANCE_OUTCOMES:
            state = self._delegation_recorder.record_review_state(
                parent.oversight_state,
                work_id=child.id,
                stable_state="InvalidEvidence",
                reason="child_acceptance_evidence_missing",
                payload={"evidence_count": len(child_evidence)},
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            raise InvalidTransitionError(
                child.status.value,
                "accept_child_run (requires verified_fix or behavior_already_correct evidence)",
            )

        result = await asyncio.to_thread(
            merge_child_into_parent,
            Path(parent.worktree_path),
            parent_run_id,
            child_run_id,
            child_worktree_path=Path(child.worktree_path),
            abort_on_conflict=False,
        )

        result_envelope = result_from_child_evidence(
            child.id,
            child_outcomes,
            generation=expected_generation if expected_generation is not None else work.generation,
        )
        if result.status == "clean":
            state, _, _ = self._delegation_recorder.apply_command(
                state,
                work,
                integrate_command,
            )
            self._record_child_acceptance(parent, child, result, state)
            state = self._delegation_recorder.record_result(
                state,
                result_envelope,
                DelegationDecision(kind="integrate", work_id=child.id),
            )
        else:
            self._record_child_merge_conflict(parent, child, result, state)
            state = self._delegation_recorder.record_work(
                state,
                (command_work or work).model_copy(update={"status": "review"}),
            )
            state = self._delegation_recorder.record_result(
                state,
                result_envelope.model_copy(
                    update={
                        "integration_ready": False,
                        "reasons": (
                            "merge_conflict",
                            *result.conflict_files,
                        ),
                    }
                ),
                DelegationDecision(
                    kind="conflict",
                    work_id=child.id,
                    reason="child_merge_conflict",
                    stable_state="MergeConflict",
                    payload={
                        "conflict_files": result.conflict_files,
                        "conflict_count": result.conflict_count,
                    },
                ),
            )

        await self.persist_parent_oversight_state(parent, state, commit=True)
        return result

    async def resolve_child_run(
        self,
        parent_run_id: str,
        child_run_id: str,
        *,
        resolution: Literal["reject", "abandon"],
        reason: str,
    ) -> ChildRunResolutionResult:
        """Record a parent decision that closes a child without merging it."""
        parent = await self._repo.get(parent_run_id)
        child = await self._repo.get(child_run_id)
        if child.parent_run_id != parent_run_id:
            raise InvalidTransitionError(child.status.value, "resolve_child_run (wrong parent)")
        if child.status in (RunStatus.DRAFT, RunStatus.ACTIVE, RunStatus.STOPPING):
            raise InvalidTransitionError(
                child.status.value,
                "resolve_child_run (requires paused, completed, or failed child)",
            )
        if resolution not in ("reject", "abandon"):
            raise InvalidTransitionError(
                parent.status.value,
                "resolve_child_run (invalid resolution)",
            )
        clean_reason = reason.strip()
        if not clean_reason:
            raise InvalidTransitionError(
                parent.status.value,
                "resolve_child_run (requires reason)",
            )

        state: dict[str, Any] = dict(parent.oversight_state)
        accepted_ids = set(self._state_str_list(state.get("accepted_child_run_ids")))
        for item in self._state_dict_list(state.get("accepted_children")):
            child_id = item.get("child_run_id") or item.get("run_id")
            if isinstance(child_id, str):
                accepted_ids.add(child_id)
        if child.id in accepted_ids:
            raise InvalidTransitionError(
                child.status.value,
                "resolve_child_run (child already accepted)",
            )

        rejected_ids = set(self._state_str_list(state.get("rejected_child_run_ids")))
        abandoned_ids = set(self._state_str_list(state.get("abandoned_child_run_ids")))
        if child.id in rejected_ids and resolution == "reject":
            state = self._delegation_recorder.record_decision(
                state,
                DelegationDecision(
                    kind="stale_command_ignored",
                    work_id=child.id,
                    reason="duplicate_child_resolution",
                    stable_state="StaleCommandIgnored",
                ),
                idempotency_key=self.delegation_command_key(parent_run_id, child.id, resolution),
                expected_generation=0,
                owner_token=self.delegation_owner_token(parent),
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            return ChildRunResolutionResult(
                parent_run_id=parent_run_id,
                child_run_id=child.id,
                resolution=resolution,
                reason=clean_reason,
                resolved_at=self._clock.now(),
            )
        if child.id in abandoned_ids and resolution == "abandon":
            state = self._delegation_recorder.record_decision(
                state,
                DelegationDecision(
                    kind="stale_command_ignored",
                    work_id=child.id,
                    reason="duplicate_child_resolution",
                    stable_state="StaleCommandIgnored",
                ),
                idempotency_key=self.delegation_command_key(parent_run_id, child.id, resolution),
                expected_generation=0,
                owner_token=self.delegation_owner_token(parent),
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            return ChildRunResolutionResult(
                parent_run_id=parent_run_id,
                child_run_id=child.id,
                resolution=resolution,
                reason=clean_reason,
                resolved_at=self._clock.now(),
            )
        if child.id in rejected_ids and resolution == "abandon":
            raise InvalidTransitionError(
                child.status.value,
                "resolve_child_run (child already rejected)",
            )
        if child.id in abandoned_ids and resolution == "reject":
            raise InvalidTransitionError(
                child.status.value,
                "resolve_child_run (child already abandoned)",
            )

        now = self._clock.now()
        if resolution == "reject":
            rejected_ids.add(child.id)
            abandoned_ids.discard(child.id)
        else:
            abandoned_ids.add(child.id)
            rejected_ids.discard(child.id)
        state["rejected_child_run_ids"] = sorted(rejected_ids)
        state["abandoned_child_run_ids"] = sorted(abandoned_ids)
        state["merge_conflicts"] = [
            item
            for item in self._state_dict_list(state.get("merge_conflicts"))
            if item.get("child_run_id") != child.id
        ]
        decisions = self._state_dict_list(state.get("decisions"))
        decisions.append(
            {
                "kind": "child_resolution",
                "action": resolution,
                "child_run_id": child.id,
                "slice_id": child.parent_slice_id,
                "reason": clean_reason,
                "decided_at": now.isoformat(),
            }
        )
        state["decisions"] = decisions
        work = self.delegation_work_for_child_command(parent, child)
        state, _, _ = self._delegation_recorder.apply_command(
            state,
            work,
            DelegateCommand(
                kind=resolution,
                work_id=child.id,
                owner_id=parent.id,
                idempotency_key=self.delegation_command_key(parent_run_id, child.id, resolution),
                expected_generation=work.generation,
                owner_token=self.delegation_owner_token(parent),
            ),
        )

        await self.persist_parent_oversight_state(parent, state, commit=True)
        return ChildRunResolutionResult(
            parent_run_id=parent_run_id,
            child_run_id=child.id,
            resolution=resolution,
            reason=clean_reason,
            resolved_at=now,
        )

    async def create_child_run(
        self,
        parent_run_id: str,
        child_run: Run,
        *,
        parent_slice_id: str,
        next_action_decision: str,
    ) -> Run:
        """Persist a child run and record it in the parent's oversight history."""
        parent = await self._repo.lock_run_for_coordination(parent_run_id)
        if child_run.id == parent_run_id:
            raise InvalidTransitionError(parent.status.value, "create_child_run (self-parent)")

        existing_children = await self._repo.list_child_runs(
            parent_run_id, include_action_logs=False
        )
        create_decision = self._super_parent_policy.decision_for_create_child(
            parent,
            existing_children,
            child_run_id=child_run.id,
            max_child_runs=self.max_child_runs_for_parent(parent),
            resolved_child_run_ids=self.resolved_child_run_ids(parent),
        )
        if create_decision.kind == "stale_command_ignored":
            state = self._delegation_recorder.record_decision(
                parent.oversight_state,
                create_decision,
                idempotency_key=self.delegation_command_key(parent_run_id, child_run.id, "launch"),
                expected_generation=0,
                owner_token=self.delegation_owner_token(parent),
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            existing = next(child for child in existing_children if child.id == child_run.id)
            return existing
        if create_decision.reason == "parent_not_active":
            state = self._delegation_recorder.record_decision(
                parent.oversight_state,
                create_decision,
                idempotency_key=self.delegation_command_key(parent_run_id, child_run.id, "launch"),
                expected_generation=0,
                owner_token=self.delegation_owner_token(parent),
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            raise InvalidTransitionError(
                parent.status.value,
                "create_child_run (requires active parent)",
            )
        if create_decision.reason == "unresolved_child_already_exists":
            state = self._delegation_recorder.record_decision(
                parent.oversight_state,
                create_decision,
                idempotency_key=self.delegation_command_key(parent_run_id, child_run.id, "launch"),
                expected_generation=0,
                owner_token=self.delegation_owner_token(parent),
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            raise InvalidTransitionError(
                parent.status.value,
                "create_child_run (unresolved child already exists)",
            )
        if create_decision.reason == "max_child_run_limit_reached":
            state = self._delegation_recorder.record_decision(
                parent.oversight_state,
                create_decision,
                idempotency_key=self.delegation_command_key(parent_run_id, child_run.id, "launch"),
                expected_generation=0,
                owner_token=self.delegation_owner_token(parent),
            )
            await self.persist_parent_oversight_state(parent, state, commit=True)
            raise InvalidTransitionError(
                parent.status.value,
                "create_child_run (max child run limit reached)",
            )
        blocking_children = [
            child
            for child in existing_children
            if child.id not in self.resolved_child_run_ids(parent)
        ]
        if blocking_children:
            raise InvalidTransitionError(
                parent.status.value,
                "create_child_run (unresolved child already exists)",
            )
        max_child_runs = self.max_child_runs_for_parent(parent)
        if len(existing_children) >= max_child_runs:
            raise InvalidTransitionError(
                parent.status.value,
                "create_child_run (max child run limit reached)",
            )

        child_run.parent_run_id = parent_run_id
        child_run.parent_slice_id = parent_slice_id

        state: dict[str, Any] = dict(parent.oversight_state)
        work = self.delegation_work_for_child_command(parent, child_run)
        state, _, _ = self._delegation_recorder.apply_command(
            state,
            work,
            DelegateCommand(
                kind="launch",
                work_id=child_run.id,
                owner_id=parent.id,
                idempotency_key=self.delegation_command_key(parent_run_id, child_run.id, "launch"),
                expected_generation=work.generation,
                owner_token=self.delegation_owner_token(parent),
            ),
        )
        slices = list(state.get("slices", []))
        now = self._clock.now()
        slices.append(
            {
                "slice_id": parent_slice_id,
                "child_run_id": child_run.id,
                "routine_id": child_run.routine_id,
                "decision": next_action_decision,
                "created_at": now.isoformat(),
            }
        )
        state["slices"] = slices
        state["last_child_run_id"] = child_run.id
        state["last_decision"] = next_action_decision
        await self._repo.save(child_run)
        await self._repo.update_parent_oversight_facts(
            parent_run_id,
            extract_parent_oversight_facts(state),
        )
        queue = self._get_signal_queue()
        await queue.enqueue(child_run.id, WorkflowSignal.RUN_START)
        await self._session.commit()
        return child_run

    def _record_child_acceptance(
        self,
        parent: Run,
        child: Run,
        result: ParentChildMergeResult,
        state: dict[str, Any],
    ) -> None:
        accepted_ids = sorted(
            {*self._state_str_list(state.get("accepted_child_run_ids")), child.id}
        )
        accepted_children = self._state_dict_list(state.get("accepted_children"))
        accepted_children = [
            item for item in accepted_children if item.get("child_run_id") != child.id
        ]
        accepted_children.append(
            {
                "child_run_id": child.id,
                "parent_slice_id": child.parent_slice_id,
                "merge_commit_sha": result.merge_commit_sha,
                "merged_at": self._clock.now().isoformat(),
            }
        )
        state["accepted_child_run_ids"] = accepted_ids
        state["accepted_children"] = accepted_children
        state["last_accepted_child_run_id"] = child.id
        state["last_child_merge_commit_sha"] = result.merge_commit_sha
        state["merge_conflicts"] = [
            item
            for item in self._state_dict_list(state.get("merge_conflicts"))
            if item.get("child_run_id") != child.id
        ]
        parent.pause_reason = None
        parent.last_error = None

    def _record_child_merge_conflict(
        self,
        parent: Run,
        child: Run,
        result: ParentChildMergeResult,
        state: dict[str, Any],
    ) -> None:
        conflicts = self._state_dict_list(state.get("merge_conflicts"))
        conflicts = [item for item in conflicts if item.get("child_run_id") != child.id]
        conflicts.append(
            {
                "child_run_id": child.id,
                "parent_slice_id": child.parent_slice_id,
                "conflict_files": result.conflict_files,
                "conflict_count": result.conflict_count,
                "detected_at": self._clock.now().isoformat(),
            }
        )
        state["merge_conflicts"] = conflicts
        if parent.status == RunStatus.ACTIVE:
            parent.status = RunStatus.PAUSED
            parent.pause_reason = "child_merge_conflict"
        parent.last_error = (
            f"Accepting child run {child.id} produced merge conflicts: "
            + ", ".join(result.conflict_files)
        )

    async def record_child_wait_observation(
        self,
        parent_run_id: str,
        child_run_id: str,
        *,
        observed_status: RunStatus,
        phase: Literal["started", "observed"],
        timeout_seconds: float,
        expected_generation: int | None = None,
        owner_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> Run:
        """Persist parent wait intent/observation for child-run recovery."""
        parent = await self._repo.get(parent_run_id)
        state = dict(parent.oversight_state)
        children = await self._repo.list_child_runs(parent_run_id, include_action_logs=False)
        child = next((item for item in children if item.id == child_run_id), None)
        work = self.delegation_work_for_child_command(parent, child) if child else None
        generation = (
            expected_generation
            if expected_generation is not None
            else (work.generation if work else 0)
        )
        state, _, wait_decision = self._delegation_recorder.apply_command(
            state,
            work,
            DelegateCommand(
                kind="observe",
                work_id=child_run_id,
                owner_id=parent.id,
                idempotency_key=idempotency_key
                or self.delegation_command_key(
                    parent_run_id,
                    child_run_id,
                    f"wait:{phase}:{observed_status.value}",
                ),
                expected_generation=generation,
                owner_token=owner_token or self.delegation_owner_token(parent),
            ),
        )
        if (
            wait_decision.kind == "stale_command_ignored"
            or wait_decision.reason == "delegated_work_not_found"
        ):
            return await self.persist_parent_oversight_state(parent, state, commit=True)
        waits = self._state_dict_list(state.get("child_waits"))
        waits.append(
            {
                "child_run_id": child_run_id,
                "phase": phase,
                "observed_status": observed_status.value,
                "timeout_seconds": timeout_seconds,
                "recorded_at": self._clock.now().isoformat(),
            }
        )
        state["child_waits"] = waits[-50:]
        return await self.persist_parent_oversight_state(parent, state, commit=True)

    async def _validate_child_evidence_for_acceptance(
        self,
        child: Run,
        child_evidence: list[dict[str, Any]],
    ) -> set[str]:
        """Validate run evidence bundles and return all reported outcomes."""
        child_status = child.status
        valid_evidence, invalid_evidence = validate_run_evidence_items(
            child_evidence,
            expected_slice_id=child.parent_slice_id,
            expected_routine_id=child.routine_id,
        )
        if invalid_evidence:
            first_invalid = invalid_evidence[0]
            details = "; ".join(f"{error.field}: {error.message}" for error in first_invalid.errors)
            action = f"accept_child_run (invalid run.evidence.v1 bundle) {first_invalid.path}"
            if details:
                action = f"{action}: {details}"
            raise InvalidTransitionError(child_status.value, action)

        outcomes: set[str] = set()
        for raw in valid_evidence:
            try:
                bundle = RunEvidenceBundle.model_validate(raw["bundle"])
            except ValidationError as err:
                raise InvalidTransitionError(
                    child_status.value,
                    "accept_child_run (invalid run.evidence.v1 bundle)",
                ) from err
            outcomes.add(bundle.outcome)
        if outcomes & REVISION_OUTCOMES or outcomes - ACCEPTANCE_OUTCOMES:
            raise InvalidTransitionError(
                child_status.value,
                "accept_child_run (evidence contains non-acceptance outcome)",
            )
        return outcomes

    def is_oversight_parent_run(self, run: Run) -> bool:
        """Return whether a run is meant to use super-parent terminal guards."""
        if run.routine_id == "super-parent":
            return True
        if (
            isinstance(run.routine_embedded, dict)
            and run.routine_embedded.get("id") == "super-parent"
        ):
            return True
        oversight_keys = {
            "current_understanding",
            "target_inventory",
            "final_validation",
            "slices",
            "accepted_child_run_ids",
            "rejected_child_run_ids",
            "abandoned_child_run_ids",
            "closed_child_run_ids",
            "max_child_runs",
        }
        return bool(oversight_keys & set(run.oversight_state.keys()))

    def _state_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in cast(list[Any], value) if isinstance(item, str)]

    def _state_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            cast(dict[str, Any], item) for item in cast(list[Any], value) if isinstance(item, dict)
        ]
