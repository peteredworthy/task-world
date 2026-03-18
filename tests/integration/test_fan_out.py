"""Integration tests for fan-out task expansion, script execution,
child task state management, and reset operations.

Uses real SQLite in-memory DB and real files via tmp_path. No mocking.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
import re

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.routers.tasks import get_attempt_logs, get_task as get_task_detail
from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.enums import (
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.config.models import RequirementConfig, StepConfig, TaskConfig
from orchestrator.config.models import RoutineConfig
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.db.repositories import RunRepository
from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.runners.types import ExecutionContext, ExecutionResult
from orchestrator.routines.loader import load_routine_from_path
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import (
    Attempt,
    Run,
)
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow.templates import derive_output_path, resolve_template

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as s:
        yield s


def _load_routine(name: str) -> RoutineConfig:
    """Load and validate a routine from the fixtures directory."""
    return load_routine_from_path(FIXTURES / f"{name}.yaml")


def _make_fan_out_run(
    routine: RoutineConfig,
    worktree_path: str,
    run_id: str = "run-fan-out",
) -> Run:
    """Create a run from the fan-out routine with routine_embedded set."""
    run = create_run_from_routine(
        routine,
        repo_name="proj-1",
        source_branch="main",
        routine_source=RoutineSource.LOCAL,
        id_generator=iter(
            [run_id, "step-1", "task-1", "step-2", "task-2", "step-3", "task-3"]
        ).__next__,
    )
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.status = RunStatus.ACTIVE
    run.worktree_path = worktree_path
    return run


def _make_script_run(
    routine: RoutineConfig,
    worktree_path: str,
    run_id: str = "run-script",
) -> Run:
    """Create a run from the script routine with routine_embedded set."""
    run = create_run_from_routine(
        routine,
        repo_name="proj-1",
        source_branch="main",
        routine_source=RoutineSource.LOCAL,
        id_generator=iter([run_id, "step-1", "task-1"]).__next__,
    )
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.status = RunStatus.ACTIVE
    run.worktree_path = worktree_path
    return run


class _FanOutIntegrationAgent:
    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: object,  # noqa: ARG002
        on_submit: object,
        on_output: object = None,
        on_grade: object = None,
        on_agent_metadata: object = None,  # noqa: ARG002
        on_escalation: object = None,  # noqa: ARG002
    ) -> ExecutionResult:
        if "Output file:" in context.prompt:
            match = re.search(r"^Output file: (.+)$", context.prompt, re.MULTILINE)
            assert match is not None
            output_rel = match.group(1).strip()
            output_path = Path(context.working_dir) / output_rel
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(f"processed {output_rel}")
            if on_output is not None:
                await on_output([f"wrote {output_rel}"])
            return ExecutionResult(success=True, output_lines=[f"built {output_rel}"])

        if on_output is not None:
            await on_output(["verifying fan-out parent"])
        if on_grade is not None:
            await on_grade("R1", "A", "All persisted child tasks completed successfully")
        await on_submit()
        return ExecutionResult(success=True, output_lines=["verified parent"])


class _FanOutExecutor(AgentRunnerExecutor):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(session_factory=session_factory, spawn_agents=False)
        self._agent = _FanOutIntegrationAgent()

    def _create_agent(
        self,
        agent_type: AgentRunnerType,  # noqa: ARG002
        agent_config: dict[str, object],  # noqa: ARG002
        run_id: str | None = None,  # noqa: ARG002
        phase: str = "building",  # noqa: ARG002
    ) -> _FanOutIntegrationAgent:
        return self._agent


# ---------------------------------------------------------------------------
# Fan-out expansion tests
# ---------------------------------------------------------------------------


class TestExpandFanOut:
    @pytest.mark.asyncio
    async def test_expand_fan_out_creates_children(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """Expanding a fan-out task should create child tasks for each matched file."""
        # Create files matching the glob pattern in the worktree
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "step-01.md").write_text("Content of step 01")
        (output_dir / "step-02.md").write_text("Content of step 02")
        (output_dir / "step-03.md").write_text("Content of step 03")

        routine = _load_routine("fan-out-test")
        run = _make_fan_out_run(routine, str(tmp_path))

        service = WorkflowService(session)
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        # Find the fan-out task (T-02 in step S-02)
        fan_out_task = run.steps[1].tasks[0]
        assert fan_out_task.config_id == "T-02"

        children = await service.expand_fan_out_task(run.id, fan_out_task.id)

        assert len(children) == 3
        # Verify child properties
        for i, child in enumerate(children):
            assert child.parent_task_id == fan_out_task.id
            assert child.fan_out_index == i
            assert child.status == TaskStatus.PENDING
            assert child.max_attempts == 2  # from fan_out config
            assert child.fan_out_input is not None
            assert child.fan_out_output is not None
            assert "result.md" in child.fan_out_output

        # Parent should now be FAN_OUT_RUNNING
        reloaded = await repo.get(run.id)
        parent = reloaded.steps[1].tasks[0]
        assert parent.status == TaskStatus.FAN_OUT_RUNNING

        # Children should be in the step's task list
        step_tasks = reloaded.steps[1].tasks
        assert len(step_tasks) == 4  # 1 parent + 3 children

    @pytest.mark.asyncio
    async def test_expand_fan_out_empty_glob(self, session: AsyncSession, tmp_path: Path) -> None:
        """Expanding a fan-out with no matching files returns an empty list."""
        # Create the output dir but no matching files
        (tmp_path / "output").mkdir()

        routine = _load_routine("fan-out-test")
        run = _make_fan_out_run(routine, str(tmp_path))

        service = WorkflowService(session)
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        fan_out_task = run.steps[1].tasks[0]
        children = await service.expand_fan_out_task(run.id, fan_out_task.id)

        assert children == []

        # Parent should still transition to FAN_OUT_RUNNING
        reloaded = await repo.get(run.id)
        parent = reloaded.steps[1].tasks[0]
        assert parent.status == TaskStatus.FAN_OUT_RUNNING


# ---------------------------------------------------------------------------
# Script task execution tests
# ---------------------------------------------------------------------------


class TestScriptExecution:
    @pytest.mark.asyncio
    async def test_script_task_success(self, session: AsyncSession, tmp_path: Path) -> None:
        """A script that exits 0 should mark the task COMPLETED."""
        routine = _load_routine("script-test")
        run = _make_script_run(routine, str(tmp_path))

        service = WorkflowService(session)
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        task = run.steps[0].tasks[0]
        assert task.config_id == "T-01"

        result = await service.execute_script_task(run.id, task.id)

        assert result.success is True
        assert result.new_status == TaskStatus.COMPLETED

        # Verify the task state was persisted
        reloaded = await repo.get(run.id)
        task_state = reloaded.steps[0].tasks[0]
        assert task_state.status == TaskStatus.COMPLETED
        assert len(task_state.attempts) == 1
        assert task_state.attempts[0].outcome == "passed"
        assert task_state.attempts[0].agent_output is not None
        assert "hello world" in task_state.attempts[0].agent_output

    @pytest.mark.asyncio
    async def test_script_task_failure(self, session: AsyncSession, tmp_path: Path) -> None:
        """A script that exits non-zero should mark the task FAILED and pause the run."""
        # Create a routine with a failing script
        routine = RoutineConfig(
            id="fail-script",
            name="Fail Script",
            steps=[
                {  # type: ignore[list-item]
                    "id": "S-01",
                    "title": "Fail Step",
                    "tasks": [
                        {
                            "id": "T-01",
                            "title": "Fail Task",
                            "script": "exit 1",
                            "requirements": [],
                        }
                    ],
                }
            ],
        )
        run = _make_script_run(routine, str(tmp_path), run_id="run-fail")

        service = WorkflowService(session)
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        task = run.steps[0].tasks[0]
        result = await service.execute_script_task(run.id, task.id)

        assert result.success is True
        assert result.new_status == TaskStatus.FAILED

        # Run should be paused
        reloaded = await repo.get(run.id)
        assert reloaded.status == RunStatus.PAUSED
        assert reloaded.pause_reason == "script_failed"

        # Task should be FAILED with error details
        task_state = reloaded.steps[0].tasks[0]
        assert task_state.status == TaskStatus.FAILED
        assert task_state.attempts[0].outcome == "failed"
        assert task_state.attempts[0].error is not None
        assert "exit" in task_state.attempts[0].error.lower()

    @pytest.mark.asyncio
    async def test_script_task_template_vars(self, session: AsyncSession, tmp_path: Path) -> None:
        """Script with {{variable}} placeholders should have them interpolated."""
        routine = RoutineConfig(
            id="template-script",
            name="Template Script",
            inputs=[{"name": "feature", "required": True}],  # type: ignore[list-item]
            steps=[
                {  # type: ignore[list-item]
                    "id": "S-01",
                    "title": "Template Step",
                    "tasks": [
                        {
                            "id": "T-01",
                            "title": "Template Task",
                            "script": "echo '{{feature}}'",
                            "requirements": [],
                        }
                    ],
                }
            ],
        )
        run = create_run_from_routine(
            routine,
            repo_name="proj-1",
            source_branch="main",
            config={"feature": "my-cool-feature"},
            routine_source=RoutineSource.LOCAL,
            id_generator=iter(["run-tmpl", "step-1", "task-1"]).__next__,
        )
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.status = RunStatus.ACTIVE
        run.worktree_path = str(tmp_path)

        service = WorkflowService(session)
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        task = run.steps[0].tasks[0]
        result = await service.execute_script_task(run.id, task.id)

        assert result.success is True
        assert result.new_status == TaskStatus.COMPLETED

        reloaded = await repo.get(run.id)
        task_state = reloaded.steps[0].tasks[0]
        # The script should have echoed the interpolated feature name
        assert "my-cool-feature" in task_state.attempts[0].agent_output


# ---------------------------------------------------------------------------
# Child task state updates and reset
# ---------------------------------------------------------------------------


class TestChildTaskStateManagement:
    @pytest.mark.asyncio
    async def test_update_child_task_state(self, session: AsyncSession, tmp_path: Path) -> None:
        """update_child_task_state should apply outcome, status, and auto_verify_results."""
        routine = _load_routine("fan-out-test")
        run = _make_fan_out_run(routine, str(tmp_path))

        # Create matching files so expansion works
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "step-01.md").write_text("file 1")

        service = WorkflowService(session)
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        fan_out_task = run.steps[1].tasks[0]
        children = await service.expand_fan_out_task(run.id, fan_out_task.id)
        assert len(children) == 1

        child = children[0]

        # Give the child an attempt so update_child_task_state has something to update
        reloaded = await repo.get(run.id)
        for step in reloaded.steps:
            for t in step.tasks:
                if t.id == child.id:
                    t.attempts.append(Attempt(attempt_num=1, started_at=datetime.now(timezone.utc)))
                    break
        await repo.save(reloaded)
        await session.commit()

        # Update child state
        now = datetime.now(timezone.utc)
        auto_verify = [{"id": "output_exists", "passed": True, "output": "ok"}]
        await service.update_child_task_state(
            run.id,
            child.id,
            updates={
                "outcome": "passed",
                "status": TaskStatus.COMPLETED,
                "auto_verify_results": auto_verify,
                "completed_at": now,
            },
        )

        # Verify updates were persisted
        reloaded = await repo.get(run.id)
        updated_child = None
        for step in reloaded.steps:
            for t in step.tasks:
                if t.id == child.id:
                    updated_child = t
                    break

        assert updated_child is not None
        assert updated_child.status == TaskStatus.COMPLETED
        assert len(updated_child.attempts) == 1
        assert updated_child.attempts[0].outcome == "passed"
        assert updated_child.attempts[0].auto_verify_results == auto_verify
        assert updated_child.attempts[0].completed_at == now

    @pytest.mark.asyncio
    async def test_reset_fan_out_children(self, session: AsyncSession, tmp_path: Path) -> None:
        """reset_fan_out_children should set all children to PENDING and parent to FAN_OUT_RUNNING."""
        routine = _load_routine("fan-out-test")
        run = _make_fan_out_run(routine, str(tmp_path))

        # Create matching files
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "step-01.md").write_text("file 1")
        (output_dir / "step-02.md").write_text("file 2")

        service = WorkflowService(session)
        from orchestrator.db.repositories import RunRepository

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        fan_out_task = run.steps[1].tasks[0]
        children = await service.expand_fan_out_task(run.id, fan_out_task.id)
        assert len(children) == 2

        # Manually mark children as COMPLETED and parent as FAILED
        reloaded = await repo.get(run.id)
        for step in reloaded.steps:
            for t in step.tasks:
                if t.parent_task_id == fan_out_task.id:
                    t.status = TaskStatus.COMPLETED
                if t.id == fan_out_task.id:
                    t.status = TaskStatus.FAILED
        await repo.save(reloaded)
        await session.commit()

        # Reset children
        await service.reset_fan_out_children(run.id, fan_out_task.id)

        # Verify reset
        reloaded = await repo.get(run.id)
        parent = None
        child_statuses = []
        for step in reloaded.steps:
            for t in step.tasks:
                if t.id == fan_out_task.id:
                    parent = t
                if t.parent_task_id == fan_out_task.id:
                    child_statuses.append(t.status)

        assert parent is not None
        assert parent.status == TaskStatus.FAN_OUT_RUNNING
        assert all(s == TaskStatus.PENDING for s in child_statuses)
        assert len(child_statuses) == 2


class TestFanOutRegression:
    @pytest.mark.asyncio
    async def test_fan_out_execution_persists_children_parent_attempt_and_parent_verification(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        """Fan-out execution should persist child attempts and drive parent verification."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "step-01.md").write_text("first")
        (output_dir / "step-02.md").write_text("second")

        routine = RoutineConfig(
            id="fan-out-parent-verify",
            name="Fan-out Parent Verify",
            steps=[
                StepConfig(
                    id="S-01",
                    title="Process",
                    tasks=[
                        TaskConfig(
                            id="T-01",
                            title="Process Each File",
                            requirements=[
                                RequirementConfig(id="R1", desc="All child work is complete")
                            ],
                            fan_out={
                                "input_glob": "output/step-*.md",
                                "output_pattern": "output/processed/{{item_stem}}-result.md",
                                "per_item_prompt": "Write the processed result to {{output_path}}",
                                "max_attempts": 2,
                                "max_concurrent": 2,
                                "auto_verify": {
                                    "items": [
                                        {"id": "output_exists", "cmd": "test -f {{output_path}}"}
                                    ]
                                },
                            },
                            verifier={
                                "rubric": [
                                    {
                                        "id": "R1",
                                        "text": "All persisted child tasks completed successfully.",
                                    }
                                ]
                            },
                        )
                    ],
                )
            ],
        )
        run = create_run_from_routine(
            routine,
            repo_name="proj-1",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
            id_generator=iter(["run-regression", "step-1", "task-1"]).__next__,
        )
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.status = RunStatus.ACTIVE
        run.worktree_path = str(tmp_path)
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {"command": "test-agent", "model": "test-model"}

        async with session_factory() as session:
            repo = RunRepository(session)
            await repo.save(run)
            await session.commit()

        executor = _FanOutExecutor(session_factory)

        async with session_factory() as session:
            service = WorkflowService(session)
            persisted_run = await service.get_run(run.id)
            parent_task = persisted_run.steps[0].tasks[0]
            await executor._execute_task(
                run=persisted_run,
                task_state=parent_task,
                service=service,
                agent_type=AgentRunnerType.CLI_SUBPROCESS,
                agent_config=run.agent_config,
            )

        async with session_factory() as session:
            service = WorkflowService(session)
            detail = await get_task_detail(run.id, parent_task.id, service)
            assert detail.current_attempt == 1
            assert len(detail.attempts) == 1
            assert detail.attempts[0].has_output is True
            assert detail.status == TaskStatus.VERIFYING.value
            assert len(detail.fan_out_children) == 2
            assert all(child.id is not None for child in detail.fan_out_children)
            assert all(child.is_synthetic is False for child in detail.fan_out_children)
            parent_logs = await get_attempt_logs(run.id, parent_task.id, 1, service)
            assert parent_logs.output is not None
            assert "fan-out" in parent_logs.output.lower()

        async with session_factory() as session:
            service = WorkflowService(session)
            persisted_run = await service.get_run(run.id)
            children = [
                task
                for step in persisted_run.steps
                for task in step.tasks
                if task.parent_task_id == parent_task.id
            ]
            assert len(children) == 2
            assert all(child.current_attempt == 1 for child in children)
            assert all(len(child.attempts) == 1 for child in children)
            assert all(child.attempts[0].outcome == "passed" for child in children)
            assert all(child.status == TaskStatus.COMPLETED for child in children)
            child_logs = await get_attempt_logs(run.id, children[0].id, 1, service)
            assert child_logs.output is not None
            assert "built output/processed" in child_logs.output

            parent_task = await service.get_task(run.id, parent_task.id)
            await executor._execute_task(
                run=persisted_run,
                task_state=parent_task,
                service=service,
                agent_type=AgentRunnerType.CLI_SUBPROCESS,
                agent_config=run.agent_config,
            )

        async with session_factory() as session:
            service = WorkflowService(session)
            parent = await service.get_task(run.id, parent_task.id)
            assert parent.status == TaskStatus.COMPLETED
            assert parent.current_attempt == 1
            assert len(parent.attempts) == 1
            assert parent.attempts[0].verifier_prompt is not None
            assert parent.attempts[0].grade_snapshot[0].grade == "A"
            assert parent.checklist[0].grade == "A"

    @pytest.mark.asyncio
    async def test_task_detail_does_not_synthesize_children_after_parent_execution(
        self,
        session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        """Task detail should expose missing persisted children after execution states."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "step-01.md").write_text("first")

        routine = _load_routine("fan-out-test")
        run = _make_fan_out_run(routine, str(tmp_path), run_id="run-no-children")
        run.steps[1].tasks[0].status = TaskStatus.COMPLETED

        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

        detail = await get_task_detail(run.id, run.steps[1].tasks[0].id, WorkflowService(session))
        assert detail.status == TaskStatus.COMPLETED.value
        assert detail.fan_out_children == []

    @pytest.mark.asyncio
    async def test_zero_child_fan_out_with_rubric_moves_parent_to_verifying(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        """A rubric-bearing fan-out parent should still verify when no inputs match."""
        routine = RoutineConfig(
            id="fan-out-zero-inputs",
            name="Fan-out Zero Inputs",
            steps=[
                StepConfig(
                    id="S-01",
                    title="Process",
                    tasks=[
                        TaskConfig(
                            id="T-01",
                            title="Process Each File",
                            requirements=[
                                RequirementConfig(
                                    id="R1", desc="Explain why no files were processed"
                                )
                            ],
                            fan_out={
                                "input_glob": "output/step-*.md",
                                "output_pattern": "output/processed/{{item_stem}}-result.md",
                                "per_item_prompt": "Write the processed result to {{output_path}}",
                            },
                            verifier={
                                "rubric": [
                                    {
                                        "id": "R1",
                                        "text": "Requirement is graded even when no children exist.",
                                    }
                                ]
                            },
                        )
                    ],
                )
            ],
        )
        run = create_run_from_routine(
            routine,
            repo_name="proj-1",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
            id_generator=iter(["run-zero", "step-1", "task-1"]).__next__,
        )
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.status = RunStatus.ACTIVE
        run.worktree_path = str(tmp_path)
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {"command": "test-agent", "model": "test-model"}

        async with session_factory() as session:
            repo = RunRepository(session)
            await repo.save(run)
            await session.commit()

        executor = _FanOutExecutor(session_factory)

        async with session_factory() as session:
            service = WorkflowService(session)
            persisted_run = await service.get_run(run.id)
            parent_task = persisted_run.steps[0].tasks[0]
            await executor._execute_task(
                run=persisted_run,
                task_state=parent_task,
                service=service,
                agent_type=AgentRunnerType.CLI_SUBPROCESS,
                agent_config=run.agent_config,
            )

        async with session_factory() as session:
            service = WorkflowService(session)
            parent = await service.get_task(run.id, parent_task.id)
            assert parent.status == TaskStatus.VERIFYING
            assert parent.current_attempt == 1
            assert len(parent.attempts) == 1

            detail = await get_task_detail(run.id, parent_task.id, service)
            assert detail.fan_out_children == []


# ---------------------------------------------------------------------------
# Template resolution tests (pure functions, but tested with real files)
# ---------------------------------------------------------------------------


class TestTemplateResolution:
    def test_resolve_template_with_variables(self) -> None:
        """resolve_template should substitute {{variable}} placeholders."""
        result = resolve_template(
            "Process {{feature}} in {{mode}}",
            variables={"feature": "auth", "mode": "strict"},
        )
        assert result == "Process auth in strict"

    def test_resolve_template_file_reference(self, tmp_path: Path) -> None:
        """resolve_template should read file content for {{file:path}}."""
        (tmp_path / "notes.md").write_text("Important notes here")
        result = resolve_template(
            "Context: {{file:notes.md}}",
            worktree_path=str(tmp_path),
        )
        assert result == "Context: Important notes here"

    def test_resolve_template_file_not_found(self, tmp_path: Path) -> None:
        """resolve_template should insert a placeholder for missing files."""
        result = resolve_template(
            "Context: {{file:missing.md}}",
            worktree_path=str(tmp_path),
        )
        assert "[File not found: missing.md]" in result

    def test_derive_output_path(self) -> None:
        """derive_output_path should replace {{item_stem}} with the input file stem."""
        result = derive_output_path(
            "output/processed/{{item_stem}}-result.md",
            "output/step-01.md",
        )
        assert result == "output/processed/step-01-result.md"

    def test_derive_output_path_with_variables(self) -> None:
        """derive_output_path should resolve remaining variables after item_stem."""
        result = derive_output_path(
            "output/{{version}}/{{item_stem}}.txt",
            "src/main.py",
            variables={"version": "v2"},
        )
        assert result == "output/v2/main.txt"
