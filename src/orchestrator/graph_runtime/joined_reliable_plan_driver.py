"""Deterministic decision-v1 cases through the production graph run driver."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path
import re
import subprocess
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy import func, select

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, RoutineConfig, RunStatus
from orchestrator.db import (
    GraphOutboxModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import (
    CandidateRecord,
    CheckResultRecord,
    DecisionAnswerRecord,
    FakeClock,
    GapClassificationRecord,
    SemanticArtifactRecord,
    SequentialIdGenerator,
    RunLifecycleState,
    VerificationReportRecord,
    execution_attempts_view,
    input_bindings_view,
    leases_view,
    node_payload_view,
    node_states_view,
    project_graph_projection_snapshot,
    output_record_payloads_view,
)
from orchestrator.graph_runtime.controller import GraphController
from orchestrator.graph_runtime.dispatch import (
    GraphDispatchContext,
    GraphDispatchExecutor,
    RunnerOwnedProcessRegistry,
    SelectedRunnerGraphToolCatalog,
    StaticGraphAgentFactory,
)
from orchestrator.graph_runtime.seeding import seed_run
from orchestrator.graph_runtime.store import GraphEventStore
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
    SubmissionInvocation,
    SubmitCallback,
    ensure_gitignore,
)
from orchestrator.state import create_run_from_routine


JoinedCaseId = Literal[
    "single-batch",
    "dependent-batches",
    "plan-amendment",
    "smoke",
    "correction",
    "blocked",
    "cancellation-restart",
    "defective-candidate",
    "defective-verifier",
]
_RUN_STATE_ADAPTER: TypeAdapter[RunLifecycleState | None] = TypeAdapter(RunLifecycleState | None)


class JoinedQualificationError(RuntimeError):
    """The deterministic joined case violated its declared product oracle."""


class JoinedDriverEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    outcome: Literal["completed", "blocked", "cancelled"]
    graph_state: RunLifecycleState | None
    workflow_status: RunStatus
    finalized_execution_count: int
    active_lease_count: int
    suspended_lease_count: int
    owned_process_count: int
    pending_outbox_count: int
    candidate_paths: tuple[str, ...]
    exact_candidate: bool
    clean_checkout: bool
    unfinished_node_ids: tuple[str, ...]
    intervention_recorded: bool
    outcome_cause: str
    event_type_counts: dict[str, int]
    evidence: tuple[str, ...]


class _BatchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    path: str
    expected: bytes
    depends_on: tuple[str, ...] = ()


def _case_batches(case_id: JoinedCaseId) -> tuple[_BatchSpec, ...]:
    if case_id == "dependent-batches":
        return (
            _BatchSpec(key="base", path="base.txt", expected=b"base-ok\n"),
            _BatchSpec(
                key="dependent",
                path="dependent.txt",
                expected=b"dependent-ok\n",
                depends_on=("base",),
            ),
        )
    path = {
        "single-batch": "single.txt",
        "plan-amendment": "amended.txt",
        "smoke": "stage3-smoke.txt",
        "correction": "corrected.txt",
        "blocked": "blocked.txt",
        "cancellation-restart": "cancelled.txt",
        "defective-candidate": "defective.txt",
        "defective-verifier": "verified.txt",
    }[case_id]
    expected = b"stage3-smoke-ok\n" if case_id == "smoke" else f"{path[:-4]}-ok\n".encode()
    return (_BatchSpec(key=path[:-4], path=path, expected=expected),)


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise JoinedQualificationError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _create_fixture(root: Path, case_id: JoinedCaseId) -> tuple[Path, Path, str]:
    repository = root / "repository"
    worktree = root / "worktree"
    repository.mkdir(parents=True)
    (repository / "CASE_SPEC.md").write_text(
        f"Execute the deterministic decision-v1 case {case_id}.\n", encoding="utf-8"
    )
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "Joined Qualification")
    _git(repository, "config", "user.email", "joined@example.invalid")
    _git(repository, "add", "CASE_SPEC.md")
    _git(repository, "commit", "-q", "-m", "Create joined qualification fixture")
    baseline = _git(repository, "rev-parse", "HEAD")
    _git(
        repository,
        "worktree",
        "add",
        "-q",
        "-b",
        f"orchestrator/joined-{case_id}-{uuid4().hex[:8]}",
        str(worktree),
    )
    ensure_gitignore(worktree, ".orchestrator/")
    return repository, worktree, baseline


def _oracle(root: Path, batches: tuple[_BatchSpec, ...], *, upto: int | None = None) -> Path:
    selected = batches if upto is None else batches[:upto]
    token = "final" if upto is None else str(upto)
    path = root / f"oracle-{token}.sh"
    lines = ["#!/bin/sh", "set -eu"]
    for batch in selected:
        expected = root / f"expected-{batch.key}.txt"
        expected.write_bytes(batch.expected)
        lines.extend([f"test -f {batch.path}", f"cmp -s {batch.path} {expected}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _decision_routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "dynamic-graph-feature",
            "name": "Joined decision-v1 qualification",
            "agent_interaction_contract": "decision-v1",
            "steps": [
                {
                    "id": "plan",
                    "title": "Plan and execute the joined case",
                    "kind": "planner",
                    "tasks": [
                        {
                            "id": "scope",
                            "title": "Satisfy the exact joined-case oracle",
                            "requirements": [
                                {"id": "joined_acceptance", "desc": "The exact oracle passes"}
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _assignments() -> dict[str, Any]:
    profiles = {
        "planner": "architect",
        "discovery_worker": "summarizer",
        "implementation_worker": "coder",
        "correction_worker": "coder",
        "verifier": "coder",
        "successor_planner": "architect",
    }
    return {
        "arm_id": "joined-decision-v1-scripted",
        **{
            role: {"runner_type": "codex_server", "model": "scripted", "profile": profile}
            for role, profile in profiles.items()
        },
    }


class _JoinedRunner:
    def __init__(self, factory: "_JoinedFactory", dispatch: GraphDispatchContext) -> None:
        self._factory = factory
        self._dispatch = dispatch

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name="joined-decision-v1-scripted",
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
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        self._factory.dispatches.append(self._dispatch)
        contract = context.submission_contract
        if contract is None or contract.interaction_contract != "decision-v1":
            raise JoinedQualificationError("joined qualification dispatched outside decision-v1")
        authored = [output for output in contract.outputs if output.required]
        if len(authored) != 1:
            raise JoinedQualificationError("joined decision requires exactly one authored output")
        output = authored[0]
        answer = await self._answer(context, output.semantic_role)
        submit = cast(Callable[[SubmissionInvocation], Awaitable[Any]], on_submit)
        acknowledgement = await submit(
            SubmissionInvocation(
                execution_id=context.execution_id or "missing-execution",
                answer_attempt_id="joined-answer-1",
                transport_channel="codex_dynamic_tool",
                transport_session_id=f"joined-{self._factory.case_id}",
                transport_request_id=f"request-{context.execution_id}",
                arguments={"outputs": {output.port: answer}},
            )
        )
        if acknowledgement.disposition != "durably_staged":
            raise JoinedQualificationError(acknowledgement.message)
        return ExecutionResult(success=True, completion_cause="terminal_answer_completed")

    async def _answer(self, context: ExecutionContext, family: str | None) -> dict[str, Any]:
        if family == "discovery_brief":
            return {
                "questions": ["Which exact files and dependency order satisfy this case?"],
                "rationale": "The committed fixture and mandatory checks define the boundary.",
                "focus": ["CASE_SPEC.md"],
            }
        if family == "implementation_plan":
            return self._factory.plan_answer()
        if family == "batch_decision":
            self._factory.successor_count += 1
            if self._factory.case_id == "blocked":
                return {
                    "disposition": "blocked",
                    "blocker": {
                        "reason": "Required operator input is absent.",
                        "needed_information": ["Provide the external approval token."],
                        "evidence": [],
                    },
                }
            if self._factory.case_id == "plan-amendment" and self._factory.successor_count == 1:
                return {
                    "disposition": "revise_plan",
                    "reason": "Independent review needs one additional acceptance obligation.",
                    "amendment": {
                        "refinements": [
                            {
                                "batch": "amended",
                                "acceptance": ["The amended acceptance obligation is verified."],
                            }
                        ],
                        "additional_batches": [],
                    },
                }
            return {
                "disposition": "proceed",
                "implementation_notes": "Implement the exact selected batch.",
            }
        if family == "work_result":
            await self._write_candidate(context)
            return {"status": "ready", "summary": "The bounded candidate is ready."}
        if family == "verification_decision":
            aliases = _aliases(context.prompt, "o")
            if not aliases:
                raise JoinedQualificationError("joined verifier has no obligations")
            failed = self._verification_should_fail()
            return {
                "findings": [
                    {
                        "obligation": alias,
                        "grade": "F" if failed else "A",
                        "reason": (
                            "The defective candidate or verifier negative fails this obligation."
                            if failed
                            else "The exact candidate and bound receipts satisfy this obligation."
                        ),
                        "evidence": [],
                    }
                    for alias in aliases
                ]
            }
        if family == "correction_decision":
            evidence = _aliases(context.prompt, "e")
            if not evidence:
                raise JoinedQualificationError(
                    "joined correction prompt has no offered evidence aliases"
                )
            if self._factory.case_id in {"defective-candidate", "defective-verifier"}:
                self._factory.interventions += 1
                return {
                    "disposition": "escalate",
                    "blocker": {
                        "reason": "The negative control must remain blocked.",
                        "needed_information": ["Operator disposition for the failed evidence."],
                        "evidence": evidence,
                    },
                }
            self._factory.interventions += 1
            return {
                "disposition": "corrective_work",
                "diagnosis": "The first candidate failed its exact mandatory evidence.",
                "remedy": "Repair only the selected batch output.",
                "focus": [self._factory.batches[0].path],
                "evidence": evidence,
            }
        raise JoinedQualificationError(f"unexpected joined answer family {family!r}")

    async def _write_candidate(self, context: ExecutionContext) -> None:
        stage = self._dispatch.node_payload.get("semantic_stage")
        if self._factory.case_id == "cancellation-restart":
            self._factory.worker_started.set()
            await self._factory.release_worker.wait()
        batch_id = self._dispatch.node_payload.get("declared_batch_id")
        batch = next(
            (item for item in self._factory.batches if item.key == batch_id),
            self._factory.batches[0],
        )
        defective = self._factory.case_id in {"correction", "defective-candidate"} and (
            stage != "corrective_work"
        )
        target = Path(context.working_dir) / batch.path
        await asyncio.to_thread(
            _write_bytes,
            target,
            b"defective\n" if defective else batch.expected,
        )
        if stage == "corrective_work":
            self._factory.corrected = True

    def _verification_should_fail(self) -> bool:
        stage = self._dispatch.node_payload.get("semantic_stage")
        if stage == "plan_verification":
            return False
        is_batch_verifier = (
            self._dispatch.node_payload.get("role") == "verifier" and stage == "effectful_batch"
        )
        if self._factory.case_id == "defective-verifier" and is_batch_verifier:
            return True
        if self._factory.case_id in {"correction", "defective-candidate"}:
            return is_batch_verifier and not self._factory.corrected
        return False

    async def request_terminal_answer_completion(self) -> None:
        return None

    async def cancel(self) -> None:
        self._factory.release_worker.set()

    def get_quota(self, fetcher: Any | None = None) -> Any | None:
        del fetcher
        return None


def _aliases(prompt: str, prefix: Literal["e", "o"]) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *re.findall(rf'"alias"\s*:\s*"({prefix}[1-9][0-9]*)"', prompt),
                *re.findall(rf'"({prefix}[1-9][0-9]*)"\s*:', prompt),
            ]
        )
    )


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _candidate_matches(
    worktree: Path,
    batches: tuple[_BatchSpec, ...],
    name_status: str,
    tree_entries: str,
) -> bool:
    expected_paths = tuple(batch.path for batch in batches)
    observed_adds = tuple(
        fields[1]
        for line in name_status.splitlines()
        if len(fields := line.split("\t", maxsplit=1)) == 2 and fields[0] == "A"
    )
    modes = {
        fields[3]: fields[0]
        for line in tree_entries.splitlines()
        if len(fields := line.split(maxsplit=3)) == 4 and fields[1] == "blob"
    }
    return (
        observed_adds == expected_paths
        and modes == {path: "100644" for path in expected_paths}
        and all(
            (worktree / batch.path).is_file()
            and (worktree / batch.path).read_bytes() == batch.expected
            for batch in batches
        )
    )


def _outcome_cause(
    case_id: JoinedCaseId,
    workflow_status: RunStatus,
    records: list[Any],
    events: list[Any],
    projection: Any,
) -> str:
    answers = [record for record in records if isinstance(record, DecisionAnswerRecord)]
    decisions = [record.value.answer for record in answers]
    recovery_reasons = [
        event.payload.get("reason")
        for event in events
        if event.event_type == "runner_recovery_requested"
    ]
    if case_id == "cancellation-restart":
        cancelled = any(
            event.event_type == "run_lifecycle_changed"
            and event.payload.get("to_state") == "cancelled"
            for event in events
        )
        if (
            workflow_status != RunStatus.CANCELLED
            or not cancelled
            or recovery_reasons != ["runner_died"]
        ):
            raise JoinedQualificationError(
                "cancel/restart lacks its exact durable cancellation cause"
            )
        return "runner_shutdown_recovered_then_cancelled_after_restart"
    if recovery_reasons:
        raise JoinedQualificationError(f"unrelated runner recovery observed: {recovery_reasons}")
    if case_id == "blocked":
        if workflow_status != RunStatus.PAUSED or not any(
            decision.get("disposition") == "blocked"
            and decision.get("blocker", {}).get("reason") == "Required operator input is absent."
            for decision in decisions
        ):
            raise JoinedQualificationError("blocked case lacks its exact durable blocker decision")
        return "required_operator_input_absent"
    if case_id == "correction":
        correction_answers = [
            record
            for record in answers
            if record.value.answer.get("disposition") == "corrective_work"
        ]
        causal_classifications = [
            classification
            for answer in correction_answers
            for classification in records
            for failed_check in records
            for failed_report in records
            if (
                isinstance(failed_check, CheckResultRecord)
                and failed_check.value.status == "failed"
                and (node_payload_view(projection, failed_check.producer_node_id) or {}).get(
                    "declared_batch_id"
                )
                == "corrected"
                and isinstance(failed_report, VerificationReportRecord)
                and failed_report.outcome == "failed"
                and failed_report.record_id in answer.value.bound_input_record_ids
                and isinstance(classification, GapClassificationRecord)
                and classification.producer_node_id == answer.producer_node_id
                and {
                    failed_check.record_id,
                    failed_report.record_id,
                }.issubset(set((classification.provenance or {}).get("evaluated_record_ids", [])))
            )
        ]
        accepted_corrections = [
            record
            for record in records
            if isinstance(record, CandidateRecord)
            and (node_payload_view(projection, record.producer_node_id) or {}).get("semantic_stage")
            == "corrective_work"
            and (node_payload_view(projection, record.producer_node_id) or {}).get(
                "declared_batch_id"
            )
            == "corrected"
            and (
                binding := input_bindings_view(projection)
                .get(record.producer_node_id, {})
                .get("classified_gap")
            )
            is not None
            and any(
                classification.record_id in binding.record_ids
                for classification in causal_classifications
            )
        ]
        repair_check_passed = any(
            isinstance(record, CheckResultRecord)
            and record.value.status == "passed"
            and any(
                candidate.record_id in record.candidate_record_ids
                for candidate in accepted_corrections
            )
            for record in records
        )
        if (
            workflow_status != RunStatus.COMPLETED
            or not causal_classifications
            or not repair_check_passed
        ):
            raise JoinedQualificationError("correction lacks failed evidence and accepted repair")
        return "failed_check_repaired_by_accepted_corrective_work"
    if case_id in {"defective-candidate", "defective-verifier"}:
        escalation_records = [
            record
            for record in answers
            if record.value.answer.get("disposition") == "escalate"
            and record.value.answer.get("blocker", {}).get("reason")
            == "The negative control must remain blocked."
        ]
        batch_id = "defective" if case_id == "defective-candidate" else "verified"
        expected_check_status = "failed" if case_id == "defective-candidate" else "passed"
        expected_failure = any(
            isinstance(report, VerificationReportRecord)
            and report.outcome == "failed"
            and report.record_id in escalation.value.bound_input_record_ids
            and (node_payload_view(projection, report.producer_node_id) or {}).get(
                "declared_batch_id"
            )
            == batch_id
            and isinstance(check, CheckResultRecord)
            and check.value.status == expected_check_status
            and check.record_id in report.evaluated_record_ids
            and (node_payload_view(projection, check.producer_node_id) or {}).get(
                "declared_batch_id"
            )
            == batch_id
            and bool(set(check.candidate_record_ids) & set(report.candidate_record_ids))
            for escalation in escalation_records
            for report in records
            for check in records
        )
        if workflow_status != RunStatus.PAUSED or not expected_failure:
            raise JoinedQualificationError(f"{case_id} lacks its exact failure and escalation")
        return (
            "mandatory_candidate_check_failed_and_escalated"
            if case_id == "defective-candidate"
            else "independent_verifier_failed_and_escalated"
        )
    if workflow_status != RunStatus.COMPLETED:
        raise JoinedQualificationError(f"{case_id} did not reach completed workflow status")
    if case_id == "plan-amendment":
        amended_plans = [
            record
            for record in records
            if isinstance(record, SemanticArtifactRecord)
            and record.value.semantic_role == "implementation_plan"
            and record.value.supersedes_record_id is not None
        ]
        amendment_verified = False
        for amended in amended_plans:
            for report in records:
                if not isinstance(report, VerificationReportRecord):
                    continue
                binding = (
                    input_bindings_view(projection)
                    .get(report.producer_node_id, {})
                    .get("semantic_artifact")
                )
                if (
                    report.outcome == "passed"
                    and amended.record_id in report.evaluated_record_ids
                    and binding is not None
                    and tuple(binding.record_ids) == (amended.record_id,)
                ):
                    amendment_verified = True
        if (
            not any(decision.get("disposition") == "revise_plan" for decision in decisions)
            or not amendment_verified
        ):
            raise JoinedQualificationError("plan amendment lacks its durable revise-plan decision")
        return "revised_plan_independently_verified_and_completed"
    return "typed_plan_completed_without_intervention"


class _JoinedFactory:
    def __init__(
        self,
        case_id: JoinedCaseId,
        batches: tuple[_BatchSpec, ...],
        batch_oracles: tuple[Path, ...],
    ) -> None:
        self.case_id = case_id
        self.batches = batches
        self.batch_oracles = batch_oracles
        self.dispatches: list[GraphDispatchContext] = []
        self.successor_count = 0
        self.interventions = 0
        self.corrected = False
        self.worker_started = asyncio.Event()
        self.release_worker = asyncio.Event()
        self._building: GraphDispatchContext | None = None
        self._static = StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            {"model": "scripted", "reasoning_effort": "low"},
            graph_tool_catalog=SelectedRunnerGraphToolCatalog(
                AgentRunnerType.CODEX_SERVER,
                {"model": "scripted", "reasoning_effort": "low"},
            ),
            runner_builder=self._build,
        )

    def plan_answer(self) -> dict[str, Any]:
        return {
            "summary": f"Execute {self.case_id} through bounded decision-v1 batches.",
            "batches": [
                {
                    "key": batch.key,
                    "objective": f"Create {batch.path} with the exact expected bytes.",
                    "scope": [batch.path],
                    "requirements": ["r1"],
                    "depends_on": list(batch.depends_on),
                    "acceptance": [f"The exact oracle for {batch.path} passes."],
                    "checks": [
                        {
                            "name": f"exact oracle for {batch.path}",
                            "command_definition": {
                                "id": f"joined-{batch.key}-oracle",
                                "cmd": str(self.batch_oracles[index]),
                            },
                        }
                    ],
                    "review_points": [f"Only the declared {batch.path} scope is changed."],
                }
                for index, batch in enumerate(self.batches)
            ],
        }

    def preflight(
        self,
        context: GraphDispatchContext,
        execution_context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None:
        self._static.preflight(context, execution_context, graph_mcp_available=graph_mcp_available)

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        self._building = context
        try:
            return self._static.create_runner(context)
        finally:
            self._building = None

    def _build(
        self,
        agent_runner_type: AgentRunnerType,
        agent_runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> AgentRunner:
        del agent_runner_config, run_id, phase
        if agent_runner_type != AgentRunnerType.CODEX_SERVER or self._building is None:
            raise JoinedQualificationError("joined runner factory lost its dispatch")
        return _JoinedRunner(self, self._building)


async def run_joined_driver_case(root: Path, case_id: JoinedCaseId) -> JoinedDriverEvidence:
    """Execute one canonical joined case on disposable Git and SQLite state."""
    from orchestrator.workflow import GraphRunDriver, SignalConsumer, WorkflowService

    case_root = root / f"{case_id}-{uuid4().hex[:8]}"
    case_root.mkdir(parents=True)
    _repository, worktree, baseline = await asyncio.to_thread(_create_fixture, case_root, case_id)
    batches = _case_batches(case_id)
    batch_oracles_list: list[Path] = []
    for index in range(1, len(batches) + 1):
        batch_oracles_list.append(await asyncio.to_thread(_oracle, case_root, batches, upto=index))
    batch_oracles = tuple(batch_oracles_list)
    final_oracle = await asyncio.to_thread(_oracle, case_root, batches)
    engine = create_engine(case_root / "joined.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    registry = RunnerOwnedProcessRegistry()
    factory = _JoinedFactory(case_id, batches, batch_oracles)
    run_id = f"joined-{case_id}-{uuid4().hex[:10]}"
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    artifacts = FilesystemArtifactStore(case_root / "artifacts")
    executor = GraphDispatchExecutor(
        sessions,
        controller,
        factory,
        worktree_path=worktree,
        artifact_store=artifacts,
        process_registry=registry,
    )

    async def create_service(session: Any) -> WorkflowService:
        return WorkflowService(session)

    def runtime_builder(*args: Any, **kwargs: Any) -> tuple[GraphController, GraphDispatchExecutor]:
        del args, kwargs
        return controller, executor

    driver = GraphRunDriver(
        sessions,
        create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
        process_registry=registry,
    )
    outcome_ready: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

    async def graph_runner(target_run_id: str) -> None:
        try:
            outcome_ready.set_result(await driver.run(target_run_id))
        except asyncio.CancelledError:
            if not outcome_ready.done():
                outcome_ready.cancel()
            raise
        except BaseException as exc:
            if not outcome_ready.done():
                outcome_ready.set_exception(exc)
            raise

    consumer = SignalConsumer(
        sessions,
        create_service,
        graph_runner=graph_runner,
        graph_execution_quiescence_preparer=registry.prepare_run_quiescence,
        graph_execution_quiescer=registry.quiesce_run,
        graph_safe_effect_drainer=driver.quiesce_run,
        graph_owner_checker=registry.has_run_owners,
        poll_interval=0.01,
        liveness_clock=clock,
    )
    consumer_started = False
    restart_consumer: SignalConsumer | None = None
    try:
        routine = _decision_routine()
        feature_spec_content = await asyncio.to_thread(
            (worktree / "CASE_SPEC.md").read_text,
            encoding="utf-8",
        )
        run_config = {
            "feature_spec_path": "CASE_SPEC.md",
            "feature_spec_content": feature_spec_content,
            "acceptance_command": str(final_oracle),
            "hidden_oracle_command": str(final_oracle),
            "acceptance_command_timeout_seconds": 10,
        }
        seed_config = {
            **run_config,
            "patch_budget": 8,
            "max_rejected_plan_proposals_per_planner": 2,
            "max_planner_executions_per_node": 1,
            "gap_policy_profile": "standard",
            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
            "reliable_plan_selected_runner_type": "codex_server",
            "reliable_plan_one_horizon_authorized": True,
            "reliable_plan_remaining_horizons": max(8, len(batches)),
            "reliable_plan_qualification_evidence_hash": "sha256:" + "d" * 64,
            "reliable_plan_model_assignments": _assignments(),
        }
        run = create_run_from_routine(
            routine,
            repo_name=case_root.name,
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
            source_path="joined-decision-v1",
            run_config=seed_config,
        )
        position = await controller.current_position(run_id)
        accepted = await controller.handle_command(run_id, position, "accept_run", {})
        await controller.handle_command(run_id, accepted.projection_position, "start", {})
        await consumer.start()
        consumer_started = True

        if case_id == "cancellation-restart":
            await asyncio.wait_for(factory.worker_started.wait(), timeout=20)
            await consumer.stop()
            consumer_started = False
            async with sessions() as session:
                await WorkflowService(session).cancel_run(run_id, reason="joined restart fence")
            before_restart_attempts = len(
                execution_attempts_view(await controller.read_projection(run_id))
            )
            restart_consumer = SignalConsumer(
                sessions,
                create_service,
                graph_runner=graph_runner,
                graph_execution_quiescence_preparer=registry.prepare_run_quiescence,
                graph_execution_quiescer=registry.quiesce_run,
                graph_safe_effect_drainer=driver.quiesce_run,
                graph_owner_checker=registry.has_run_owners,
                poll_interval=0.01,
                liveness_clock=clock,
            )
            await restart_consumer.start()
            for _ in range(500):
                async with sessions() as session:
                    if (
                        await WorkflowService(session).get_run(run_id)
                    ).status == RunStatus.CANCELLED:
                        break
                await asyncio.sleep(0.01)
            else:
                raise JoinedQualificationError(
                    "restart did not redeliver cancel to terminal workflow state"
                )
            await restart_consumer.stop()
            restart_consumer = None
            after_restart_attempts = len(
                execution_attempts_view(await controller.read_projection(run_id))
            )
            if after_restart_attempts != before_restart_attempts:
                raise JoinedQualificationError("restart redispatched a cancelled execution")
            outcome = None
        else:
            outcome = await asyncio.wait_for(outcome_ready, timeout=120)

        await executor.wait_for_all(timeout_seconds=10)
        fresh_controller = GraphController(
            sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
        )
        projection = await fresh_controller.read_projection(run_id)
        async with sessions() as session:
            workflow_run = await WorkflowService(session).get_run(run_id)
            store = GraphEventStore(session)
            events = await store.read_run(run_id)
            durable_projection, _, _ = await store.load_projection_with_tail(run_id)
            runtime_facts = await store.read_bounded_runtime_projection_facts(run_id)
            pending_outbox_count = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(GraphOutboxModel)
                        .where(
                            GraphOutboxModel.run_id == run_id,
                            GraphOutboxModel.status.in_(("pending", "dispatching")),
                        )
                    )
                ).scalar_one()
            )
        public_snapshot = project_graph_projection_snapshot(
            runtime_facts or [], projection=durable_projection
        )
        status_text = await asyncio.to_thread(
            _git, worktree, "status", "--porcelain", "--untracked-files=all"
        )
        name_status, tree_entries = await asyncio.gather(
            asyncio.to_thread(_git, worktree, "diff", "--name-status", baseline, "HEAD"),
            asyncio.to_thread(
                _git,
                worktree,
                "ls-tree",
                "-r",
                "HEAD",
                "--",
                *(batch.path for batch in batches),
            ),
        )
        candidate_paths = tuple(
            fields[1]
            for line in name_status.splitlines()
            if len(fields := line.split("\t", maxsplit=1)) == 2
        )
        exact_candidate = await asyncio.to_thread(
            _candidate_matches,
            worktree,
            batches,
            name_status,
            tree_entries,
        )
        graph_state = _RUN_STATE_ADAPTER.validate_python(public_snapshot.run_state)
        unfinished = tuple(
            sorted(
                node_id
                for node_id, state in node_states_view(projection).items()
                if state not in {"completed", "retired"}
            )
        )
        attempts = execution_attempts_view(projection).values()
        finalized = sum(attempt.state == "finalized" for attempt in attempts)
        active = sum(lease.state == "active" for lease in leases_view(projection).values())
        suspended = sum(lease.state == "suspended" for lease in leases_view(projection).values())
        counts = Counter(event.event_type for event in events)
        check_statuses = {
            record.producer_node_id: record.value.status
            for record in output_record_payloads_view(projection).values()
            if isinstance(record, CheckResultRecord)
        }
        records = list(output_record_payloads_view(projection).values())
        outcome_cause = _outcome_cause(
            case_id,
            workflow_run.status,
            records,
            events,
            projection,
        )
        dependency_order = "not_applicable"
        if case_id == "dependent-batches":
            base_reports = [
                record
                for record in records
                if isinstance(record, VerificationReportRecord)
                and record.outcome == "passed"
                and (node_payload_view(projection, record.producer_node_id) or {}).get(
                    "declared_batch_id"
                )
                == "base"
            ]
            report_positions = [
                event.position
                for event in events
                if event.event_type == "output_record_accepted"
                and any(
                    event.payload.get("record_id") == report.record_id for report in base_reports
                )
            ]
            dependent_positions = [
                event.position
                for event in events
                if event.event_type == "node_created"
                and event.payload.get("declared_batch_id") == "dependent"
                and event.payload.get("semantic_stage") == "effectful_batch"
                and event.payload.get("role") == "implementer"
            ]
            if (
                not report_positions
                or not dependent_positions
                or min(dependent_positions) <= max(report_positions)
            ):
                raise JoinedQualificationError(
                    "dependent worker existed before the exact passing predecessor report"
                )
            dependency_order = "base_report_before_dependent_worker"
        candidate_commit = await asyncio.to_thread(_git, worktree, "rev-parse", "HEAD")
        candidate_tree = await asyncio.to_thread(_git, worktree, "rev-parse", "HEAD^{tree}")
        observed_outcome: Literal["completed", "blocked", "cancelled"]
        if workflow_run.status == RunStatus.COMPLETED:
            observed_outcome = "completed"
        elif workflow_run.status == RunStatus.CANCELLED:
            observed_outcome = "cancelled"
        elif workflow_run.status == RunStatus.PAUSED:
            observed_outcome = "blocked"
        else:
            raise JoinedQualificationError(
                f"joined case ended in unsupported workflow state {workflow_run.status.value}"
            )
        evidence = (
            "create_start_path=workflow-service+signal-consumer",
            f"decision_answers_staged={counts['runner_submission_staged']}",
            f"executions_finalized={finalized}",
            f"graph_state={graph_state}",
            f"workflow_status={workflow_run.status.value}",
            f"candidate_paths={','.join(candidate_paths) or 'none'}",
            f"candidate_name_status={name_status or 'none'}",
            f"candidate_modes={tree_entries or 'none'}",
            f"outcome_cause={outcome_cause}",
            f"dependency_order={dependency_order}",
            f"active_ownership={active + suspended + registry.run_owner_count(run_id)}",
            f"pending_outbox={pending_outbox_count}",
            f"database_path={case_root / 'joined.db'}",
            f"worktree_path={worktree}",
            f"candidate_commit={candidate_commit}",
            f"candidate_tree={candidate_tree}",
            f"mandatory_checks={dict(sorted(check_statuses.items()))}",
        )
        del outcome
        return JoinedDriverEvidence(
            run_id=run_id,
            outcome=observed_outcome,
            graph_state=graph_state,
            workflow_status=workflow_run.status,
            finalized_execution_count=finalized,
            active_lease_count=active,
            suspended_lease_count=suspended,
            owned_process_count=registry.run_owner_count(run_id),
            pending_outbox_count=pending_outbox_count,
            candidate_paths=candidate_paths,
            exact_candidate=exact_candidate,
            clean_checkout=not bool(status_text),
            unfinished_node_ids=unfinished,
            intervention_recorded=outcome_cause
            in {
                "failed_check_repaired_by_accepted_corrective_work",
                "required_operator_input_absent",
                "runner_shutdown_recovered_then_cancelled_after_restart",
                "mandatory_candidate_check_failed_and_escalated",
                "independent_verifier_failed_and_escalated",
            },
            outcome_cause=outcome_cause,
            event_type_counts=dict(sorted(counts.items())),
            evidence=evidence,
        )
    finally:
        factory.release_worker.set()
        if consumer_started:
            await consumer.stop()
        if restart_consumer is not None:
            await restart_consumer.stop()
        if registry.has_run_owners(run_id):
            await registry.quiesce_run(run_id, runner_loss=False, retry_after_recovery=False)
            await executor.wait_for_all(timeout_seconds=10)
        await engine.dispose()


__all__ = ["JoinedDriverEvidence", "run_joined_driver_case"]
