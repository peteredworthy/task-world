"""Run one bounded, isolated Luna planner or verifier probe.

This utility is deliberately not an orchestrator run launcher.  Each invocation
creates disposable Git/SQLite fixtures and performs exactly one model execution.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, ChecklistStatus, load_routine_from_path
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    RunnerOwnedProcessRegistry,
    StaticGraphAgentFactory,
    seed_run,
)
from orchestrator.runners import (
    AgentRunner,
    CodexServerAgent,
    ExecutionContext,
    ExecutionResult,
    SubmissionAcknowledgement,
)


MODEL = "gpt-5.6-luna"
EFFORT = "medium"
DEFAULT_TIMEOUT_SECONDS = 180.0
PLANNER_TOOL = "construct_reliable_plan_region"
ROOT = Path(__file__).resolve().parents[2]
ROUTINE_PATH = ROOT / "routines" / "dynamic-graph-feature" / "routine.yaml"

RunnerBuilder = Callable[..., AgentRunner]
CliRunner = Callable[[str, float], Coroutine[Any, Any, tuple["ProbeEvidence", int]]]

_PLAIN_SUBMIT_EVENT_TYPES = (
    "runner_submission_staged",
    "runner_completion_witnessed",
    "runner_execution_finalized",
    "callback_accepted",
    "lease_released",
)
_RUNNER_FAILURE_EVENT_TYPES = frozenset(
    {
        "agent_died",
        "agent_error",
        "file_state_rejected",
        "runner_boundary_mismatch",
        "runner_recovery_completed",
        "runner_recovery_requested",
        "runtime_retry_scheduled",
    }
)


class ProbeEvidence(BaseModel):
    """Bounded machine-readable evidence for one paid phase execution."""

    schema_version: Literal[1] = 1
    probe_id: str
    phase: Literal["planner", "verifier"]
    status: Literal["passed", "failed", "incomplete", "error"]
    model: Literal["gpt-5.6-luna"] = MODEL
    reasoning_effort: Literal["medium"] = EFFORT
    timeout_seconds: float = Field(gt=0, le=180)
    limit_policy: str = "operator-enforced wall timeout; no native token/action limit"
    source_commit: str
    source_tree: str
    source_dirty: bool
    harness_sha256: str
    fixture_commit: str
    fixture_tree: str
    fixture_sha256: str
    fixture_unchanged: bool
    setup_duration_ms: int
    model_duration_ms: int
    total_duration_ms: int
    timed_out: bool
    incomplete_reason: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(default_factory=dict)


class ProbeFailure(RuntimeError):
    """A deterministic probe setup or execution-boundary failure."""


def _run_command(
    argv: list[str], cwd: Path, *, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
    )


async def _command(
    argv: list[str], cwd: Path, *, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(_run_command, argv, cwd, timeout=timeout)


async def _git(repo: Path, *args: str) -> str:
    result = await _command(["git", *args], repo)
    if result.returncode != 0:
        raise ProbeFailure(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


async def _init_repo(repo: Path, files: dict[str, str]) -> tuple[str, str]:
    repo.mkdir(parents=True)
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    await _git(repo, "init", "-b", "main")
    await _git(repo, "config", "user.email", "recovery-probe@example.invalid")
    await _git(repo, "config", "user.name", "Recovery Probe")
    await _git(repo, "add", ".")
    await _git(repo, "commit", "-m", "Create isolated recovery probe fixture")
    commit = await _git(repo, "rev-parse", "HEAD")
    tree = await _git(repo, "rev-parse", "HEAD^{tree}")
    return commit, tree


async def _source_identity() -> tuple[str, str, bool]:
    commit = await _git(ROOT, "rev-parse", "HEAD")
    tree = await _git(ROOT, "rev-parse", "HEAD^{tree}")
    dirty = bool(await _git(ROOT, "status", "--porcelain", "--untracked-files=no"))
    return commit, tree, dirty


def _files_sha256(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _argv_sha256(argv: list[str]) -> str:
    return hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest()


def _metrics(result: ExecutionResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    metrics = result.metrics
    return {
        "duration_ms": metrics.duration_ms,
        "num_actions": metrics.num_actions,
        "input_tokens": metrics.gen_ai_usage_input_tokens,
        "output_tokens": metrics.gen_ai_usage_output_tokens,
        "cache_read_input_tokens": metrics.gen_ai_usage_cache_read_input_tokens,
        "reasoning_output_tokens": result.gen_ai_usage_reasoning_output_tokens,
        "finish_reasons": result.gen_ai_response_finish_reasons,
    }


def _model_assignments() -> dict[str, Any]:
    profiles = {
        "planner": "architect",
        "discovery_worker": "summarizer",
        "implementation_worker": "coder",
        "correction_worker": "coder",
        "verifier": "coder",
        "successor_planner": "architect",
    }
    return {
        "arm_id": "recovery-stage2-isolated-luna",
        **{
            role: {"runner_type": "codex_server", "model": MODEL, "profile": profile}
            for role, profile in profiles.items()
        },
    }


async def run_planner_probe(
    workspace: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    runner_builder: RunnerBuilder | None = None,
) -> ProbeEvidence:
    """Execute one real planner dispatch against a disposable qualified graph."""

    total_started = time.monotonic()
    setup_started = total_started
    source_commit, source_tree, source_dirty = await _source_identity()
    probe_id = f"stage2-planner-{uuid4()}"
    repo = workspace / "planner-repo"
    fixture_files = {
        "README.md": (
            "# Isolated planner fixture\n\n"
            "Plan exactly one read-only diagnostic region. Do not edit this repository.\n"
        )
    }
    fixture_commit, fixture_tree = await _init_repo(repo, fixture_files)
    engine = create_engine(workspace / "planner.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    result_holder: list[ExecutionResult] = []

    async def capture_usage(_context: Any, result: ExecutionResult) -> None:
        result_holder.append(result)

    try:
        routine = load_routine_from_path(ROUTINE_PATH)
        await seed_run(
            sessions,
            routine,
            run_id=probe_id,
            clock=clock,
            id_gen=ids,
            source_path=str(ROUTINE_PATH),
            run_config={
                "feature_spec_path": "README.md",
                "feature_spec_content": (
                    "Create one read-only discovery decision for the supplied fixture. "
                    "Call construct_reliable_plan_region exactly once with a valid explicit "
                    "command_definition whose cmd is 'true', then call submit and stop."
                ),
                "acceptance_command": "true",
                "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                "reliable_plan_selected_runner_type": "codex_server",
                "reliable_plan_one_horizon_authorized": True,
                "reliable_plan_remaining_horizons": 1,
                "reliable_plan_qualification_evidence_hash": "sha256:" + "c" * 64,
                "reliable_plan_model_assignments": _model_assignments(),
                "patch_budget": 1,
            },
        )
        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        accepted = await controller.handle_command(
            probe_id, await controller.current_position(probe_id), "accept_run", {}
        )
        started = await controller.handle_command(
            probe_id, accepted.projection_position, "start", {}
        )
        scheduled = await controller.handle_command(
            probe_id,
            started.projection_position,
            "schedule_tick",
            {"max_grants": 1, "lease_seconds": 240, "base_snapshot_id": "fixture-baseline"},
        )
        if sum(item.kind == "agent_dispatch" for item in scheduled.outbox_items) != 1:
            raise ProbeFailure("planner setup did not create exactly one dispatch")
        registry = RunnerOwnedProcessRegistry()
        factory_kwargs: dict[str, Any] = {}
        if runner_builder is not None:
            factory_kwargs["runner_builder"] = runner_builder
        factory = StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            {"model": MODEL, "reasoning_effort": EFFORT, "restrictions": "managed"},
            **factory_kwargs,
        )
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            factory,
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(workspace / "planner-artifacts"),
            process_registry=registry,
            on_agent_usage=capture_usage,
        )
        dispatcher = OutboxDispatcher(sessions, executor, clock)
        setup_duration_ms = int((time.monotonic() - setup_started) * 1000)
        model_started = time.monotonic()
        await dispatcher.dispatch_pending(run_id=probe_id)
        await executor.wait_for_all(timeout_seconds=timeout_seconds)
        timed_out = registry.has_run_owners(probe_id)
        if timed_out:
            await registry.quiesce_run(probe_id, runner_loss=False, retry_after_recovery=False)
            await executor.wait_for_all()
        model_duration_ms = int((time.monotonic() - model_started) * 1000)

        async with sessions() as session:
            events = await GraphEventStore(session).read_run(probe_id)
        event_type_counts = Counter(event.event_type for event in events)
        accepted_patches = [event for event in events if event.event_type == "graph_patch_accepted"]
        planner_leases = [
            event.payload.get("node_id") for event in events if event.event_type == "lease_granted"
        ]
        dispatch_nodes = [
            event.payload.get("node_id")
            for event in events
            if event.event_type == "agent_dispatch_requested"
        ]
        fixture_unchanged = (
            await _git(repo, "rev-parse", "HEAD") == fixture_commit
            and await _git(repo, "rev-parse", "HEAD^{tree}") == fixture_tree
            and not await _git(repo, "status", "--porcelain")
        )
        result = result_holder[0] if len(result_holder) == 1 else None
        plain_submit_counts = {
            event_type: event_type_counts[event_type] for event_type in _PLAIN_SUBMIT_EVENT_TYPES
        }
        failed_event_types = sorted(_RUNNER_FAILURE_EVENT_TYPES.intersection(event_type_counts))
        plain_submit_finalized = all(count == 1 for count in plain_submit_counts.values())
        passed = (
            not timed_out
            and len(result_holder) == 1
            and result is not None
            and result.success
            and len(accepted_patches) == 1
            and len(planner_leases) == 1
            and len(dispatch_nodes) == 1
            and plain_submit_finalized
            and not failed_event_types
            and fixture_unchanged
            and registry.run_owner_count(probe_id) == 0
        )
        accepted_event = accepted_patches[0] if accepted_patches else None
        return ProbeEvidence(
            probe_id=probe_id,
            phase="planner",
            status="passed" if passed else "incomplete" if timed_out else "failed",
            timeout_seconds=timeout_seconds,
            source_commit=source_commit,
            source_tree=source_tree,
            source_dirty=source_dirty,
            harness_sha256=_file_sha256(Path(__file__)),
            fixture_commit=fixture_commit,
            fixture_tree=fixture_tree,
            fixture_sha256=_files_sha256(fixture_files),
            fixture_unchanged=fixture_unchanged,
            setup_duration_ms=setup_duration_ms,
            model_duration_ms=model_duration_ms,
            total_duration_ms=int((time.monotonic() - total_started) * 1000),
            timed_out=timed_out,
            incomplete_reason=("operator wall timeout expired" if timed_out else None),
            metrics=_metrics(result),
            observations={
                "macro_name": PLANNER_TOOL,
                "accepted_patch_id": (
                    accepted_event.payload.get("patch_id") if accepted_event else None
                ),
                "accepted_position": accepted_event.position if accepted_event else None,
                "graph_event_ids": [event.event_id for event in events],
                "lease_node_ids": planner_leases,
                "dispatch_node_ids": dispatch_nodes,
                "downstream_lease_count": max(0, len(planner_leases) - 1),
                "downstream_dispatch_count": max(0, len(dispatch_nodes) - 1),
                "owned_process_count_after": registry.run_owner_count(probe_id),
                "execution_result_count": len(result_holder),
                "execution_result_success": result.success if result is not None else None,
                "plain_submit_event_counts": plain_submit_counts,
                "plain_submit_finalized": plain_submit_finalized,
                "runner_failure_event_types": failed_event_types,
                "routine_sha256": _file_sha256(ROUTINE_PATH),
                "declared_check": {
                    "command_definition": {"cmd": "true"},
                    "command_sha256": hashlib.sha256(b"true").hexdigest(),
                    "executed": False,
                },
            },
        )
    finally:
        await engine.dispose()


def _verifier_files() -> dict[str, str]:
    common = "import json, sys\ngraph = json.loads(open(sys.argv[1], encoding='utf-8').read())\n"
    return {
        "graph-missing.json": "{}\n",
        "candidate-good.py": common
        + "complete = isinstance(graph.get('node_states'), dict)\n"
        + "print(json.dumps({'complete': complete}))\n"
        + "raise SystemExit(0 if complete else 1)\n",
        "candidate-bad.py": common
        + "print(json.dumps({'complete': True}))\n"
        + "raise SystemExit(0)\n",
        "oracle.py": (
            "import json, subprocess, sys\n"
            "result = subprocess.run([sys.executable, sys.argv[1], 'graph-missing.json'], "
            "capture_output=True, text=True, check=False)\n"
            "payload = json.loads(result.stdout)\n"
            "ok = result.returncode == 1 and payload == {'complete': False}\n"
            "print(json.dumps({'candidate': sys.argv[1], 'detects_missing_node_states': ok}))\n"
            "raise SystemExit(0 if ok else 1)\n"
        ),
    }


async def run_verifier_probe(
    workspace: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    agent_factory: Callable[[], CodexServerAgent] | None = None,
) -> ProbeEvidence:
    """Execute one fresh verifier against good and deliberately defective fixtures."""

    total_started = time.monotonic()
    setup_started = total_started
    source_commit, source_tree, source_dirty = await _source_identity()
    probe_id = f"stage2-verifier-{uuid4()}"
    repo = workspace / "verifier-repo"
    fixture_files = _verifier_files()
    fixture_commit, fixture_tree = await _init_repo(repo, fixture_files)
    python = sys.executable
    good_command = [python, "oracle.py", "candidate-good.py"]
    bad_command = [python, "oracle.py", "candidate-bad.py"]
    good_started = time.monotonic()
    good_result = await _command(good_command, repo)
    good_duration_ms = int((time.monotonic() - good_started) * 1000)
    bad_started = time.monotonic()
    bad_result = await _command(bad_command, repo)
    bad_duration_ms = int((time.monotonic() - bad_started) * 1000)
    if good_result.returncode != 0 or bad_result.returncode == 0:
        raise ProbeFailure("independent verifier fixtures do not separate good and defective")
    setup_duration_ms = int((time.monotonic() - setup_started) * 1000)

    grades: list[tuple[str, str, str | None]] = []
    submissions: list[bool] = []

    async def checklist(_req_id: str, _status: ChecklistStatus, _note: str | None) -> None:
        return None

    async def grade(req_id: str, value: str, reason: str | None) -> None:
        grades.append((req_id, value, reason))

    async def submit(_args: dict[str, Any] | None = None) -> SubmissionAcknowledgement:
        submissions.append(True)
        return SubmissionAcknowledgement(
            disposition="durably_staged", message="isolated verifier observation captured"
        )

    agent = (
        agent_factory()
        if agent_factory is not None
        else CodexServerAgent(
            model=MODEL,
            reasoning_effort=EFFORT,
            restrictions="managed",
        )
    )
    prompt = f"""You are the fresh verifier for one isolated recovery probe.
Do not edit files. Inspect candidate-good.py, candidate-bad.py, graph-missing.json,
and oracle.py. Run these exact independent commands:
1. {json.dumps(good_command)}
2. {json.dumps(bad_command)}

Grade R-GOOD A only if candidate-good correctly reports missing node_states as
incomplete/nonzero. Grade R-MISSING-NODE-STATES D or F only if candidate-bad has
the known defect: it falsely reports complete/exit 0 for graph {{}} without
node_states. The defective grade reason must explicitly mention missing
node_states. Call grade once for each ID, then call submit once and stop.
"""
    context = ExecutionContext(
        run_id=probe_id,
        task_id="verifier-fixture-comparison",
        working_dir=str(repo),
        prompt=prompt,
        requirements=[
            "R-GOOD: good control rejects missing node_states",
            "R-MISSING-NODE-STATES: defective control must be detected",
        ],
        node_id="verifier-fixture-comparison",
        node_kind="verifier",
        node_role="verifier",
        work_mode="oversight",
    )
    model_started = time.monotonic()
    execution_task = asyncio.create_task(
        agent.execute(
            context,
            checklist,
            submit,
            on_grade=grade,
        )
    )
    result: ExecutionResult | None = None
    timed_out = False
    cancellation_requested = False
    try:
        result = await asyncio.wait_for(asyncio.shield(execution_task), timeout_seconds)
    except TimeoutError:
        timed_out = True
        cancellation_requested = True
        await agent.cancel()
        execution_task.cancel()
        await asyncio.gather(execution_task, return_exceptions=True)
    model_duration_ms = int((time.monotonic() - model_started) * 1000)
    fixture_unchanged = (
        await _git(repo, "rev-parse", "HEAD") == fixture_commit
        and await _git(repo, "rev-parse", "HEAD^{tree}") == fixture_tree
        and not await _git(repo, "status", "--porcelain")
    )
    grade_counts = Counter(req_id for req_id, _value, _reason in grades)
    grades_by_id = {req_id: (value, reason) for req_id, value, reason in grades}
    good_grade = grades_by_id.get("R-GOOD")
    bad_grade = grades_by_id.get("R-MISSING-NODE-STATES")
    bad_reason = (bad_grade[1] or "").lower() if bad_grade else ""
    passed = (
        not timed_out
        and result is not None
        and result.success
        and len(submissions) == 1
        and len(grades) == 2
        and grade_counts == {"R-GOOD": 1, "R-MISSING-NODE-STATES": 1}
        and good_grade is not None
        and good_grade[0] == "A"
        and bad_grade is not None
        and bad_grade[0] in {"D", "F"}
        and "node_states" in bad_reason
        and fixture_unchanged
    )
    return ProbeEvidence(
        probe_id=probe_id,
        phase="verifier",
        status="passed" if passed else "incomplete" if timed_out else "failed",
        timeout_seconds=timeout_seconds,
        source_commit=source_commit,
        source_tree=source_tree,
        source_dirty=source_dirty,
        harness_sha256=_file_sha256(Path(__file__)),
        fixture_commit=fixture_commit,
        fixture_tree=fixture_tree,
        fixture_sha256=_files_sha256(fixture_files),
        fixture_unchanged=fixture_unchanged,
        setup_duration_ms=setup_duration_ms,
        model_duration_ms=model_duration_ms,
        total_duration_ms=int((time.monotonic() - total_started) * 1000),
        timed_out=timed_out,
        incomplete_reason=("operator wall timeout expired" if timed_out else None),
        metrics=_metrics(result),
        observations={
            "grades": [
                {"req_id": req_id, "grade": value, "reason": reason}
                for req_id, value, reason in grades
            ],
            "submit_count": len(submissions),
            "execution_result_success": result.success if result is not None else None,
            "cancellation_requested": cancellation_requested,
            "execution_task_drained": execution_task.done(),
            "independent_commands": [
                {
                    "argv": good_command,
                    "command_sha256": _argv_sha256(good_command),
                    "returncode": good_result.returncode,
                    "duration_ms": good_duration_ms,
                    "stdout_sha256": hashlib.sha256(good_result.stdout.encode()).hexdigest(),
                },
                {
                    "argv": bad_command,
                    "command_sha256": _argv_sha256(bad_command),
                    "returncode": bad_result.returncode,
                    "duration_ms": bad_duration_ms,
                    "stdout_sha256": hashlib.sha256(bad_result.stdout.encode()).hexdigest(),
                },
            ],
        },
    )


async def _run_cli(phase: str, timeout_seconds: float) -> tuple[ProbeEvidence, int]:
    if timeout_seconds <= 0 or timeout_seconds > DEFAULT_TIMEOUT_SECONDS:
        raise ProbeFailure("timeout must be greater than zero and at most 180 seconds")
    with tempfile.TemporaryDirectory(prefix=f"recovery-{phase}-probe-") as raw_workspace:
        workspace = Path(raw_workspace)
        evidence = (
            await run_planner_probe(workspace, timeout_seconds=timeout_seconds)
            if phase == "planner"
            else await run_verifier_probe(workspace, timeout_seconds=timeout_seconds)
        )
    return evidence, 0 if evidence.status == "passed" else 1


def main(argv: list[str] | None = None, *, run_cli: CliRunner = _run_cli) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("planner", "verifier"))
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        evidence, exit_code = asyncio.run(run_cli(args.phase, args.timeout_seconds))
    except Exception as exc:
        source_commit = "unavailable"
        source_tree = "unavailable"
        try:
            source_commit = _run_command(["git", "rev-parse", "HEAD"], ROOT).stdout.strip()
            source_tree = _run_command(["git", "rev-parse", "HEAD^{tree}"], ROOT).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        payload = {
            "schema_version": 1,
            "phase": args.phase,
            "status": "error",
            "model": MODEL,
            "reasoning_effort": EFFORT,
            "source_commit": source_commit,
            "source_tree": source_tree,
            "harness_sha256": _file_sha256(Path(__file__)),
            "error": str(exc)[:2048],
        }
        print(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        return 2
    print(evidence.model_dump_json(exclude_none=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
