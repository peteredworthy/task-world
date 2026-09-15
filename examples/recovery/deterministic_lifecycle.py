"""Run the Stage 3 tiny lifecycle with deterministic injected agents.

No model or live server is used.  The production graph compiler, controller,
outbox dispatcher, managed runner finalization, Git snapshotting, mechanical
checks, final audit, and final gate remain in the path under test.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import re
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, load_routine_from_path
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    CheckResultRecord,
    CompletionDecisionRecord,
    FakeClock,
    ReliablePlanContractIdentity,
    SequentialIdGenerator,
    execution_attempts_view,
    leases_view,
    output_record_payloads_view,
    project_graph_projection_snapshot,
    node_states_view,
    task_states_view,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    RunnerOwnedProcessRegistry,
    SelectedRunnerGraphToolCatalog,
    StaticGraphAgentFactory,
    seed_run,
)
from orchestrator.runners import (
    AgentMetadataCallback,
    AgentRunner,
    AgentRunnerInfo,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
    SubmissionInvocation,
    ensure_gitignore,
)
from orchestrator.state import create_run_from_routine
from orchestrator.workflow import GraphRunDriver, SignalConsumer, WorkflowService


ROOT = Path(__file__).resolve().parents[2]
ROUTINE_PATH = ROOT / "routines" / "dynamic-graph-feature" / "routine.yaml"
EXPECTED_BYTES = b"stage3-smoke-ok\n"


class LifecyclePhaseCounts(BaseModel):
    """Observed agent-phase counts; no fixed phase budget is implied."""

    model_phases: int = Field(ge=0)
    finalized_executions: int = Field(ge=0)
    by_node_kind: dict[str, int]


class LifecyclePublicReadback(BaseModel):
    """Public explanation assembled from the accepted lifecycle projection."""

    accepted: bool
    graph_state: str | None
    workflow_status: str
    candidate_paths: list[str]
    candidate_bytes_sha256: str
    candidate_mode: str
    clean_checkout: bool
    exact_candidate: bool
    check_statuses: dict[str, str]
    completion_status: str | None
    finalized_execution_count: int
    active_lease_count: int
    suspended_lease_count: int
    owned_process_count: int
    pending_outbox_count: int
    intentionally_unexecuted_node_ids: list[str]
    unfinished_node_ids: list[str]
    explanation: str


class LifecycleEvidence(BaseModel):
    schema_version: int = 1
    qualification_contract_identity: ReliablePlanContractIdentity = ReliablePlanContractIdentity()
    status: Literal["passed", "failed"]
    run_id: str
    graph_state: str | None
    phase_counts: LifecyclePhaseCounts
    exact_candidate: bool
    changed_paths: list[str]
    dispatch_node_ids: list[str]
    verifier_instance_ids: list[str]
    event_type_counts: dict[str, int]
    finalized_execution_count: int
    active_lease_count: int
    owned_process_count: int
    pending_outbox_count: int
    check_statuses: dict[str, str]
    completion_status: str | None
    task_states: dict[str, str]
    remaining_node_states: dict[str, str]
    outcome_completed: bool
    outcome_blocked_reason: str | None
    workflow_status: str
    source_commit: str
    source_tree: str
    source_dirty: bool
    harness_sha256: str
    routine_sha256: str
    fixture_commit: str
    fixture_tree: str
    candidate_commit: str
    candidate_tree: str
    candidate_mode: str
    public_readback: LifecyclePublicReadback


class LifecycleProbeFailure(RuntimeError):
    """The deterministic lifecycle violated a required probe boundary."""


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, check=False, capture_output=True, text=True)


def run_lifecycle_git(cwd: Path, *args: str) -> str:
    result = _run(["git", *args], cwd)
    if result.returncode != 0:
        raise LifecycleProbeFailure(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_lifecycle_fixture(workspace: Path) -> tuple[Path, Path, str]:
    repository = workspace / "fixture"
    worktree = workspace / "run-worktree"
    repository.mkdir()
    (repository / "SMOKE_SPEC.md").write_text(
        "Create stage3-smoke.txt with exact bytes stage3-smoke-ok followed by a newline.\n",
        encoding="utf-8",
    )
    run_lifecycle_git(repository, "init", "-b", "main")
    run_lifecycle_git(repository, "config", "user.name", "Recovery Lifecycle")
    run_lifecycle_git(repository, "config", "user.email", "recovery-lifecycle@example.invalid")
    run_lifecycle_git(repository, "add", "SMOKE_SPEC.md")
    run_lifecycle_git(repository, "commit", "-m", "Create Stage 3 fixture")
    baseline = run_lifecycle_git(repository, "rev-parse", "HEAD")
    run_lifecycle_git(repository, "worktree", "add", "-b", "orchestrator/run-stage3", str(worktree))
    ensure_gitignore(worktree, ".orchestrator/")
    runtime_dir = worktree / ".orchestrator" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "scaffolding.json").write_text("{}\n", encoding="utf-8")
    return repository, worktree, baseline


def create_lifecycle_oracle(workspace: Path, baseline: str) -> Path:
    expected = workspace / "expected-stage3-smoke.txt"
    expected.write_bytes(EXPECTED_BYTES)
    oracle = workspace / "stage3_oracle.sh"
    oracle.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"baseline={shlex.quote(baseline)}\n"
        f"expected={shlex.quote(str(expected))}\n"
        'changed=$(git diff --name-status "$baseline" HEAD)\n'
        'test "$changed" = "A\tstage3-smoke.txt"\n'
        'test -z "$(git status --porcelain --untracked-files=all)"\n'
        "entry=$(git ls-tree HEAD -- stage3-smoke.txt)\n"
        "case \"$entry\" in '100644 blob '*) ;; *) exit 1 ;; esac\n"
        'cmp -s stage3-smoke.txt "$expected"\n',
        encoding="utf-8",
    )
    oracle.chmod(0o755)
    return oracle


def lifecycle_assignments() -> dict[str, Any]:
    profiles = {
        "planner": "architect",
        "discovery_worker": "summarizer",
        "implementation_worker": "coder",
        "correction_worker": "coder",
        "verifier": "coder",
        "successor_planner": "architect",
    }
    return {
        "arm_id": "stage3-deterministic-lifecycle",
        **{
            role: {"runner_type": "codex_server", "model": "scripted", "profile": profile}
            for role, profile in profiles.items()
        },
    }


class _ScriptedRunner:
    def __init__(self, factory: "ScriptedLifecycleFactory", dispatch: GraphDispatchContext) -> None:
        self._factory = factory
        self._dispatch = dispatch
        self.instance_id = f"scripted-{len(factory.instance_ids) + 1}"
        factory.instance_ids.append(self.instance_id)
        if dispatch.node_kind == "verifier":
            factory.verifier_instance_ids.append(self.instance_id)

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name="deterministic-stage3-lifecycle",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        del on_checklist_update, on_output, on_agent_metadata, on_escalation
        if (
            context.submission_contract is not None
            and context.submission_contract.interaction_contract == "decision-v1"
        ):
            await self._decision_v1(context, on_submit)
            return ExecutionResult(success=True, completion_cause="terminal_answer_completed")
        submit_without_args = cast(Callable[[], Awaitable[Any]], on_submit)
        submit_with_args = cast(Callable[[dict[str, Any]], Awaitable[Any]], on_submit)
        self._factory.execution_contexts.append(context)
        if self._dispatch.node_kind == "planner":
            await self._plan(context, on_submit)
        elif (
            self._dispatch.node_kind == "worker"
            and self._dispatch.node_payload.get("semantic_stage") == "discovery"
        ):
            await submit_with_args(
                {
                    "outputs": {
                        "semantic_artifact": {
                            "summary": "One exact Stage 3 smoke batch.",
                            "batches": [
                                {
                                    "batch_id": "stage3-smoke",
                                    "objective": "Create the exact smoke file.",
                                    "scope": ["stage3-smoke.txt"],
                                    "requirement_ids": ["dynamic_feature_acceptance"],
                                    "acceptance": ["the independent oracle passes"],
                                    "checks": [str(self._factory.oracle)],
                                }
                            ],
                        }
                    }
                }
            )
        elif self._dispatch.node_kind == "worker":
            (Path(context.working_dir) / "stage3-smoke.txt").write_bytes(EXPECTED_BYTES)
            await submit_without_args()
        elif self._dispatch.node_kind == "verifier":
            if on_grade is None:
                raise LifecycleProbeFailure("verifier dispatch did not receive grade callback")
            for requirement in context.requirements:
                requirement_id = requirement.partition(":")[0]
                await on_grade(requirement_id, "A", "Bound candidate and check receipts pass.")
            await submit_without_args()
        else:
            raise LifecycleProbeFailure(f"unexpected scripted node kind {self._dispatch.node_kind}")
        return ExecutionResult(success=True)

    async def _decision_v1(self, context: ExecutionContext, on_submit: SubmitCallback) -> None:
        contract = context.submission_contract
        if contract is None or len(contract.outputs) != 1:
            raise LifecycleProbeFailure("decision-v1 dispatch has no single authored output")
        output = contract.outputs[0]
        family = output.semantic_role
        if family == "discovery_brief":
            answer: dict[str, Any] = {
                "questions": ["Which exact file and checks satisfy the smoke requirement?"],
                "rationale": "The repository and acceptance boundary must be inspected.",
                "focus": ["SMOKE_SPEC.md"],
            }
        elif family == "implementation_plan":
            answer = {
                "summary": "Implement and independently verify the exact smoke candidate.",
                "batches": [
                    {
                        "key": "stage3-smoke",
                        "objective": "Create the exact smoke file.",
                        "scope": ["stage3-smoke.txt"],
                        "requirements": ["r1"],
                        "depends_on": [],
                        "acceptance": ["The independent Stage 3 oracle passes."],
                        "checks": [
                            {
                                "name": "stage3 exact-file oracle",
                                "command_definition": {
                                    "id": "stage3-exact-file-oracle",
                                    "cmd": str(self._factory.oracle),
                                },
                            }
                        ],
                        "review_points": ["Only stage3-smoke.txt changes."],
                    }
                ],
            }
        elif family == "batch_decision":
            answer = {
                "disposition": "proceed",
                "implementation_notes": "Implement the exact selected smoke batch.",
            }
        elif family == "work_result":
            (Path(context.working_dir) / "stage3-smoke.txt").write_bytes(EXPECTED_BYTES)
            answer = {"status": "ready", "summary": "The exact smoke file is committed."}
        elif family == "verification_decision":
            aliases = list(
                dict.fromkeys(re.findall(r'"alias"\s*:\s*"(o[1-9][0-9]*)"', context.prompt))
            )
            if not aliases:
                raise LifecycleProbeFailure("decision verifier prompt has no obligations")
            answer = {
                "findings": [
                    {
                        "obligation": alias,
                        "grade": "A",
                        "reason": "The exact candidate and bound receipts satisfy this obligation.",
                        "evidence": [],
                    }
                    for alias in aliases
                ]
            }
        else:
            raise LifecycleProbeFailure(f"unexpected decision-v1 family {family!r}")
        submit = cast(Callable[[SubmissionInvocation], Awaitable[Any]], on_submit)
        acknowledgement = await submit(
            SubmissionInvocation(
                execution_id=context.execution_id or "missing-execution",
                answer_attempt_id="scripted-answer-1",
                transport_channel="codex_dynamic_tool",
                transport_session_id="deterministic-lifecycle",
                transport_request_id=f"request-{context.execution_id}",
                arguments={"outputs": {output.port: answer}},
            )
        )
        if acknowledgement.disposition != "durably_staged":
            raise LifecycleProbeFailure(acknowledgement.message)

    async def request_terminal_answer_completion(self) -> None:
        return None

    async def _plan(self, context: ExecutionContext, on_submit: SubmitCallback) -> None:
        if context.graph_patch_callback is None:
            raise LifecycleProbeFailure("planner dispatch is missing graph patch callback")
        initial = context.node_id == "planner-s-01"
        payload = {
            "patch_id": "stage3-initial-plan" if initial else "stage3-effectful-plan",
            "base_graph_position": self._dispatch.graph_position,
            "macro_invocations": [
                {
                    "macro": "construct_reliable_plan_region",
                    "args": {
                        "operation_key": "stage3-discovery" if initial else "stage3-smoke",
                        "scope": "SMOKE_SPEC.md" if initial else "stage3-smoke",
                        "objective": (
                            "Discover one exact smoke batch."
                            if initial
                            else "Create stage3-smoke.txt with the required exact bytes."
                        ),
                        "requirement_ids": ["dynamic_feature_acceptance"],
                        "dependencies": [],
                        "acceptance": ["the independent Stage 3 oracle passes"],
                        "checks": [
                            {
                                "name": "stage3 exact-file oracle",
                                "command_definition": {
                                    "id": "stage3-exact-file-oracle",
                                    "cmd": str(self._factory.oracle),
                                },
                            }
                        ],
                        "rubric": ["Only stage3-smoke.txt changes and its bytes are exact."],
                    },
                }
            ],
        }
        feedback = await context.graph_patch_callback(payload)
        if "accepted" not in feedback.lower():
            raise LifecycleProbeFailure(feedback)
        await cast(Callable[[], Awaitable[Any]], on_submit)()

    async def cancel(self) -> None:
        return None

    def get_quota(self, fetcher: Any = None) -> None:
        del fetcher
        return None


class ScriptedLifecycleFactory:
    def __init__(self, oracle: Path) -> None:
        self.oracle = oracle
        self.dispatch_contexts: list[GraphDispatchContext] = []
        self.execution_contexts: list[ExecutionContext] = []
        self.instance_ids: list[str] = []
        self.verifier_instance_ids: list[str] = []
        self._building_context: GraphDispatchContext | None = None
        self._static = StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            {"model": "scripted", "reasoning_effort": "low"},
            graph_tool_catalog=SelectedRunnerGraphToolCatalog(
                AgentRunnerType.CODEX_SERVER,
                {"model": "scripted", "reasoning_effort": "low"},
            ),
            runner_builder=self._build_runner,
        )

    def preflight(
        self,
        context: GraphDispatchContext,
        execution_context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None:
        self._static.preflight(
            context,
            execution_context,
            graph_mcp_available=graph_mcp_available,
        )

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        self.dispatch_contexts.append(context)
        self._building_context = context
        try:
            return self._static.create_runner(context)
        finally:
            self._building_context = None

    def _build_runner(
        self,
        agent_runner_type: AgentRunnerType,
        agent_runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> AgentRunner:
        del agent_runner_config, run_id, phase
        if agent_runner_type != AgentRunnerType.CODEX_SERVER or self._building_context is None:
            raise LifecycleProbeFailure("scripted runner factory lost its dispatch context")
        return _ScriptedRunner(self, self._building_context)


async def run_lifecycle(
    workspace: Path,
    *,
    interaction_contract: Literal["legacy", "decision-v1"] = "decision-v1",
) -> LifecycleEvidence:
    workspace = workspace.resolve(strict=True)
    source_commit, source_tree, source_status = await asyncio.to_thread(
        lambda: (
            run_lifecycle_git(ROOT, "rev-parse", "HEAD"),
            run_lifecycle_git(ROOT, "rev-parse", "HEAD^{tree}"),
            run_lifecycle_git(ROOT, "status", "--porcelain", "--untracked-files=no"),
        )
    )
    repository, worktree, baseline = await asyncio.to_thread(create_lifecycle_fixture, workspace)
    oracle = await asyncio.to_thread(create_lifecycle_oracle, workspace, baseline)
    fixture_tree = await asyncio.to_thread(
        run_lifecycle_git, repository, "rev-parse", f"{baseline}^{{tree}}"
    )
    run_id = f"stage3-deterministic-{uuid4().hex[:12]}"
    engine = create_engine(workspace / "lifecycle.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    registry = RunnerOwnedProcessRegistry()
    factory = ScriptedLifecycleFactory(oracle)
    executor: GraphDispatchExecutor | None = None
    consumer: SignalConsumer | None = None
    try:
        routine = load_routine_from_path(ROUTINE_PATH)
        if interaction_contract == "decision-v1":
            routine = routine.model_copy(update={"agent_interaction_contract": "decision-v1"})
        run_config = {
            "feature_spec_path": "SMOKE_SPEC.md",
            "feature_spec_content": (worktree / "SMOKE_SPEC.md").read_text(),
            "acceptance_command": str(oracle),
            "acceptance_command_timeout_seconds": 10,
            "patch_budget": 2,
            "max_rejected_plan_proposals_per_planner": 2,
            "max_planner_executions_per_node": 1,
            "gap_policy_profile": "standard",
            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
            "reliable_plan_selected_runner_type": "codex_server",
            "reliable_plan_one_horizon_authorized": True,
            "reliable_plan_remaining_horizons": 1,
            "reliable_plan_qualification_evidence_hash": "sha256:" + "d" * 64,
            "reliable_plan_model_assignments": lifecycle_assignments(),
        }
        run = create_run_from_routine(
            routine,
            repo_name=repository.name,
            source_branch="main",
            config=run_config,
        )
        run.id = run_id
        run.execution_mode = "graph"
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.worktree_path = str(worktree)
        run.worktree_enabled = True
        run.agent_runner_type = AgentRunnerType.CODEX_SERVER
        async with sessions() as session:
            service = WorkflowService(session)
            await service.create_run(run)
            await service.start_run(run_id)
        await seed_run(
            sessions,
            routine,
            run_id=run_id,
            clock=clock,
            id_gen=ids,
            source_path=str(ROUTINE_PATH),
            run_config=run_config,
        )
        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        position = await controller.current_position(run_id)
        accepted = await controller.handle_command(run_id, position, "accept_run", {})
        await controller.handle_command(run_id, accepted.projection_position, "start", {})
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            factory,
            worktree_path=worktree,
            artifact_store=FilesystemArtifactStore(workspace / "artifacts"),
            process_registry=registry,
        )
        dispatcher = OutboxDispatcher(sessions, executor, clock)

        async def unused_service(_session: Any) -> Any:
            raise RuntimeError("workflow service is not used by the isolated driver loop")

        async def read_projection(_run_id: str) -> Any:
            async with sessions() as session:
                store = GraphEventStore(session)
                projection, _, _ = await store.load_projection_with_tail(_run_id)
                facts = await store.read_bounded_runtime_projection_facts(_run_id)
            return project_graph_projection_snapshot(facts or [], projection=projection)

        driver = GraphRunDriver(sessions, unused_service, clock=clock, id_gen=ids)
        outcome_ready: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

        async def graph_runner(_run_id: str) -> None:
            try:
                driven = await driver.drive_to_quiescence(
                    _run_id,
                    controller=controller,
                    dispatcher=dispatcher,
                    executor=executor,
                    read_projection=read_projection,
                )
                if driven.completed:
                    async with sessions() as session:
                        await WorkflowService(session).finalize_graph_run_completion(_run_id)
                outcome_ready.set_result(driven)
            except BaseException as exc:
                if not outcome_ready.done():
                    outcome_ready.set_exception(exc)
                raise

        async def create_service(session: Any) -> WorkflowService:
            return WorkflowService(session)

        consumer = SignalConsumer(
            sessions,
            create_service,
            graph_runner=graph_runner,
            graph_execution_quiescence_preparer=registry.prepare_run_quiescence,
            graph_execution_quiescer=registry.quiesce_run,
            graph_owner_checker=registry.has_run_owners,
            poll_interval=0.01,
            liveness_clock=clock,
        )
        await consumer.start()
        outcome = await asyncio.wait_for(outcome_ready, timeout=50)
        pending = await dispatcher.dispatch_pending(run_id=run_id)
        await executor.wait_for_all()
        async with sessions() as session:
            finalized_run = await WorkflowService(session).get_run(run_id)
        final_snapshot = await read_projection(run_id)
        projection = await controller.read_projection(run_id)
        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
        records = list(output_record_payloads_view(projection).values())
        checks: dict[str, str] = {
            record.producer_node_id: record.value.status
            for record in records
            if isinstance(record, CheckResultRecord)
        }
        completion = next(
            (record for record in records if isinstance(record, CompletionDecisionRecord)), None
        )
        attempts = list(execution_attempts_view(projection).values())
        (
            status_text,
            name_status,
            candidate_commit,
            candidate_tree,
            candidate_entry,
        ) = await asyncio.to_thread(
            lambda: (
                run_lifecycle_git(worktree, "status", "--porcelain", "--untracked-files=all"),
                run_lifecycle_git(worktree, "diff", "--name-status", baseline, "HEAD"),
                run_lifecycle_git(worktree, "rev-parse", "HEAD"),
                run_lifecycle_git(worktree, "rev-parse", "HEAD^{tree}"),
                run_lifecycle_git(worktree, "ls-tree", "HEAD", "--", "stage3-smoke.txt"),
            )
        )
        status_lines = status_text.splitlines()
        changed_paths = [
            line.split("\t", 1)[1] for line in name_status.splitlines() if "\t" in line
        ]
        candidate_mode = candidate_entry.partition(" ")[0]
        candidate_path = worktree / "stage3-smoke.txt"
        candidate_bytes = await asyncio.to_thread(
            lambda: candidate_path.read_bytes() if candidate_path.exists() else b""
        )
        oracle_passed = (await asyncio.to_thread(_run, [str(oracle)], worktree)).returncode == 0
        exact_candidate = (
            name_status == "A\tstage3-smoke.txt"
            and changed_paths == ["stage3-smoke.txt"]
            and not status_lines
            and candidate_bytes == EXPECTED_BYTES
            and candidate_mode == "100644"
            and oracle_passed
        )
        counts = Counter(event.event_type for event in events)
        finalized_execution_count = sum(attempt.state == "finalized" for attempt in attempts)
        active_lease_count = sum(
            lease.state == "active" for lease in leases_view(projection).values()
        )
        suspended_lease_count = sum(
            lease.state == "suspended" for lease in leases_view(projection).values()
        )
        owned_process_count = registry.run_owner_count(run_id)
        remaining_node_states = {
            node_id: state
            for node_id, state in node_states_view(projection).items()
            if state not in {"completed", "retired"}
        }
        accepted = (
            outcome.completed
            and exact_candidate
            and final_snapshot.run_state == "completed"
            and all(attempt.state == "finalized" for attempt in attempts)
            and active_lease_count == 0
            and suspended_lease_count == 0
            and owned_process_count == 0
            and not pending
            and bool(checks)
            and set(checks.values()) == {"passed"}
            and completion is not None
            and completion.value.status == "passed"
            and finalized_run.status.value == "completed"
            and not {
                "agent_died",
                "callback_rejected_conflict",
                "runner_recovery_requested",
            }.intersection(counts)
        )
        phase_counts = LifecyclePhaseCounts(
            model_phases=len(factory.dispatch_contexts),
            finalized_executions=finalized_execution_count,
            by_node_kind=dict(
                sorted(Counter(context.node_kind for context in factory.dispatch_contexts).items())
            ),
        )
        explanation = (
            f"Accepted result: graph={final_snapshot.run_state}, workflow="
            f"{finalized_run.status.value}, candidate_paths={changed_paths}, "
            f"candidate_mode={candidate_mode}, oracle={'passed' if oracle_passed else 'failed'}, "
            f"checks={dict(sorted(checks.items()))}, finalized_executions="
            f"{finalized_execution_count}, active_leases={active_lease_count}, "
            f"suspended_leases={suspended_lease_count}, "
            f"owned_processes={owned_process_count}, pending_outbox={len(pending)}."
            if accepted
            else (
                f"Result not accepted: graph={final_snapshot.run_state}, "
                f"workflow={finalized_run.status.value}, candidate_paths={changed_paths}, "
                f"oracle={'passed' if oracle_passed else 'failed'}, "
                f"unfinished_nodes={sorted(remaining_node_states)}."
            )
        )
        public_readback = LifecyclePublicReadback(
            accepted=accepted,
            graph_state=final_snapshot.run_state,
            workflow_status=finalized_run.status.value,
            candidate_paths=changed_paths,
            candidate_bytes_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            candidate_mode=candidate_mode,
            clean_checkout=not status_lines,
            exact_candidate=exact_candidate,
            check_statuses=checks,
            completion_status=(completion.value.status if completion else None),
            finalized_execution_count=finalized_execution_count,
            active_lease_count=active_lease_count,
            suspended_lease_count=suspended_lease_count,
            owned_process_count=owned_process_count,
            pending_outbox_count=len(pending),
            intentionally_unexecuted_node_ids=[],
            unfinished_node_ids=sorted(remaining_node_states),
            explanation=explanation,
        )
        evidence = LifecycleEvidence(
            qualification_contract_identity=ReliablePlanContractIdentity.for_interaction(
                interaction_contract
            ),
            status="passed" if accepted else "failed",
            run_id=run_id,
            graph_state=final_snapshot.run_state,
            phase_counts=phase_counts,
            exact_candidate=exact_candidate,
            changed_paths=changed_paths,
            dispatch_node_ids=[context.node_id for context in factory.dispatch_contexts],
            verifier_instance_ids=factory.verifier_instance_ids,
            event_type_counts=dict(sorted(counts.items())),
            finalized_execution_count=finalized_execution_count,
            active_lease_count=active_lease_count,
            owned_process_count=owned_process_count,
            pending_outbox_count=len(pending),
            check_statuses=checks,
            completion_status=(completion.value.status if completion else None),
            task_states=task_states_view(projection),
            remaining_node_states=remaining_node_states,
            outcome_completed=outcome.completed,
            outcome_blocked_reason=outcome.blocked_reason,
            workflow_status=finalized_run.status.value,
            source_commit=source_commit,
            source_tree=source_tree,
            source_dirty=bool(source_status),
            harness_sha256=_sha256(Path(__file__)),
            routine_sha256=_sha256(ROUTINE_PATH),
            fixture_commit=baseline,
            fixture_tree=fixture_tree,
            candidate_commit=candidate_commit,
            candidate_tree=candidate_tree,
            candidate_mode=candidate_mode,
            public_readback=public_readback,
        )
        return evidence
    finally:
        try:
            if consumer is not None:
                await consumer.stop()
        finally:
            if registry.has_run_owners(run_id):
                await registry.quiesce_run(
                    run_id,
                    runner_loss=False,
                    retry_after_recovery=False,
                )
                if executor is not None:
                    await executor.wait_for_all()
            await engine.dispose()


async def run_legacy_lifecycle(workspace: Path) -> LifecycleEvidence:
    """Retain the source-bound pre-decision compatibility smoke."""
    return await run_lifecycle(workspace, interaction_contract="legacy")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.workspace is not None:
            args.workspace.mkdir(parents=True, exist_ok=True)
            evidence = asyncio.run(asyncio.wait_for(run_lifecycle(args.workspace), timeout=60))
        else:
            canonical_temp = Path(tempfile.gettempdir()).resolve(strict=True)
            with tempfile.TemporaryDirectory(
                prefix="recovery-stage3-deterministic-", dir=canonical_temp
            ) as raw:
                evidence = asyncio.run(asyncio.wait_for(run_lifecycle(Path(raw)), timeout=60))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:2000],
                },
                sort_keys=True,
            )
        )
        return 2
    print(evidence.model_dump_json())
    return 0 if evidence.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
