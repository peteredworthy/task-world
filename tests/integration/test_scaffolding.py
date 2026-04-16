"""Integration tests for scaffolding module."""

import shutil
from pathlib import Path

import pytest

from orchestrator.runners import copy_scaffolding, ensure_gitignore

from tests.integration.git_helpers import _git


@pytest.fixture
def repo_with_scaffolding(tmp_path: Path, _base_repo: Path) -> tuple[Path, str, str]:
    """Create a git repo with a routine that has scaffolding.

    Returns: (repo_path, routine_path, commit_sha)
    """
    repo = Path(shutil.copytree(str(_base_repo), str(tmp_path / "repo")))

    # Create routine with scaffolding
    routine_dir = repo / "routines" / "my-routine"
    routine_dir.mkdir(parents=True)

    # Routine file
    routine_yaml = """id: my-routine
name: My Routine
description: Test routine with scaffolding
inputs: []
steps:
  - id: S-01
    title: Step One
    tasks:
      - id: T-01
        title: Task One
        task_context: Do the task
        requirements:
          - id: R-01
            desc: Do something
            priority: critical
        artifacts: []
"""
    (routine_dir / "routine.yaml").write_text(routine_yaml)

    # Scaffolding files
    scaffolding_dir = routine_dir / "scaffolding"
    scaffolding_dir.mkdir()
    (scaffolding_dir / "template.md").write_text("# Template File\n")

    # Nested scaffolding
    templates_dir = scaffolding_dir / "templates"
    templates_dir.mkdir()
    (templates_dir / "intent.md").write_text("# Intent Document\n")
    (templates_dir / "design.md").write_text("# Design Document\n")

    # Commit
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "Add routine with scaffolding"], cwd=repo)
    commit = _git(["rev-parse", "HEAD"], cwd=repo)

    return repo, "routines/my-routine/routine.yaml", commit


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """Create a worktree directory."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    return wt


class TestCopyScaffolding:
    def test_copies_all_files(
        self, repo_with_scaffolding: tuple[Path, str, str], worktree: Path
    ) -> None:
        """Copies all scaffolding files to worktree."""
        repo, routine_path, commit = repo_with_scaffolding

        result = copy_scaffolding(repo, routine_path, commit, worktree)

        assert result.files_copied == 3  # template.md + templates/intent.md + templates/design.md
        assert (worktree / ".orchestrator" / "scaffolding" / "template.md").exists()
        assert (worktree / ".orchestrator" / "scaffolding" / "templates" / "intent.md").exists()
        assert (worktree / ".orchestrator" / "scaffolding" / "templates" / "design.md").exists()

    def test_preserves_file_content(
        self, repo_with_scaffolding: tuple[Path, str, str], worktree: Path
    ) -> None:
        """File content is preserved correctly."""
        repo, routine_path, commit = repo_with_scaffolding

        copy_scaffolding(repo, routine_path, commit, worktree)

        content = (worktree / ".orchestrator" / "scaffolding" / "template.md").read_text()
        assert content == "# Template File\n"

        intent_content = (
            worktree / ".orchestrator" / "scaffolding" / "templates" / "intent.md"
        ).read_text()
        assert intent_content == "# Intent Document\n"

    def test_creates_gitignore(
        self, repo_with_scaffolding: tuple[Path, str, str], worktree: Path
    ) -> None:
        """Creates .gitignore with .orchestrator/ entry."""
        repo, routine_path, commit = repo_with_scaffolding

        result = copy_scaffolding(repo, routine_path, commit, worktree)

        assert result.gitignore_updated is True
        gitignore = worktree / ".gitignore"
        assert gitignore.exists()
        assert ".orchestrator/" in gitignore.read_text()

    def test_appends_to_existing_gitignore(
        self, repo_with_scaffolding: tuple[Path, str, str], worktree: Path
    ) -> None:
        """Appends to existing .gitignore without duplicating."""
        repo, routine_path, commit = repo_with_scaffolding
        (worktree / ".gitignore").write_text("*.pyc\n")

        result = copy_scaffolding(repo, routine_path, commit, worktree)

        assert result.gitignore_updated is True
        content = (worktree / ".gitignore").read_text()
        assert "*.pyc" in content
        assert ".orchestrator/" in content

    def test_no_duplicate_gitignore_entry(
        self, repo_with_scaffolding: tuple[Path, str, str], worktree: Path
    ) -> None:
        """Doesn't duplicate .orchestrator/ entry in .gitignore."""
        repo, routine_path, commit = repo_with_scaffolding
        (worktree / ".gitignore").write_text(".orchestrator/\n")

        result = copy_scaffolding(repo, routine_path, commit, worktree)

        assert result.gitignore_updated is False
        content = (worktree / ".gitignore").read_text()
        assert content.count(".orchestrator/") == 1

    def test_custom_target_dir(
        self, repo_with_scaffolding: tuple[Path, str, str], worktree: Path
    ) -> None:
        """Uses custom target directory."""
        repo, routine_path, commit = repo_with_scaffolding

        result = copy_scaffolding(
            repo, routine_path, commit, worktree, target_dir="custom/scaffolding"
        )

        assert result.target_path == str(worktree / "custom" / "scaffolding")
        assert (worktree / "custom" / "scaffolding" / "template.md").exists()

    def test_empty_scaffolding(self, tmp_path: Path, worktree: Path, _base_repo: Path) -> None:
        """Handles routine with empty scaffolding directory."""
        repo = Path(shutil.copytree(str(_base_repo), str(tmp_path / "repo")))

        # Routine with empty scaffolding
        routine_dir = repo / "routines" / "empty-scaffold"
        routine_dir.mkdir(parents=True)
        (routine_dir / "routine.yaml").write_text("id: empty-scaffold\nname: Empty\n")
        (routine_dir / "scaffolding").mkdir()

        _git(["add", "."], cwd=repo)
        _git(["commit", "-m", "Add routine with empty scaffolding"], cwd=repo)
        commit = _git(["rev-parse", "HEAD"], cwd=repo)

        result = copy_scaffolding(repo, "routines/empty-scaffold/routine.yaml", commit, worktree)

        assert result.files_copied == 0
        # Directory still gets created
        assert (worktree / ".orchestrator" / "scaffolding").exists()

    def test_no_scaffolding_directory(
        self, tmp_path: Path, worktree: Path, _base_repo: Path
    ) -> None:
        """Handles routine without scaffolding directory gracefully."""
        repo = Path(shutil.copytree(str(_base_repo), str(tmp_path / "repo")))

        # Routine without scaffolding
        routine_dir = repo / "routines" / "no-scaffold"
        routine_dir.mkdir(parents=True)
        (routine_dir / "routine.yaml").write_text("id: no-scaffold\nname: No Scaffold\n")

        _git(["add", "."], cwd=repo)
        _git(["commit", "-m", "Add routine without scaffolding"], cwd=repo)
        commit = _git(["rev-parse", "HEAD"], cwd=repo)

        result = copy_scaffolding(repo, "routines/no-scaffold/routine.yaml", commit, worktree)

        # No files copied, but no error
        assert result.files_copied == 0


class TestEnsureGitignore:
    def test_creates_new_gitignore(self, worktree: Path) -> None:
        """Creates .gitignore if it doesn't exist."""
        result = ensure_gitignore(worktree, ".orchestrator/")

        assert result is True
        content = (worktree / ".gitignore").read_text()
        assert ".orchestrator/" in content

    def test_appends_to_existing(self, worktree: Path) -> None:
        """Appends to existing .gitignore."""
        (worktree / ".gitignore").write_text("*.log\n")

        result = ensure_gitignore(worktree, ".orchestrator/")

        assert result is True
        content = (worktree / ".gitignore").read_text()
        assert "*.log" in content
        assert ".orchestrator/" in content

    def test_no_duplicate(self, worktree: Path) -> None:
        """Doesn't add duplicate entry."""
        (worktree / ".gitignore").write_text(".orchestrator/\n")

        result = ensure_gitignore(worktree, ".orchestrator/")

        assert result is False
        content = (worktree / ".gitignore").read_text()
        assert content.count(".orchestrator/") == 1

    def test_handles_trailing_slash_variants(self, worktree: Path) -> None:
        """Handles entry with/without trailing slash."""
        (worktree / ".gitignore").write_text(".orchestrator\n")

        result = ensure_gitignore(worktree, ".orchestrator/")

        assert result is False  # .orchestrator (without slash) is already there


class TestScaffoldingIntegration:
    """Integration tests for scaffolding in the workflow."""

    @pytest.mark.asyncio
    async def test_scaffolding_copied_on_worktree_creation(
        self, tmp_path: Path, _base_repo: Path
    ) -> None:
        """Scaffolding is copied when worktree is created during run start."""

        from orchestrator.runners.executor import AgentRunnerExecutor
        from orchestrator.config import AgentRunnerType, RoutineSource
        from orchestrator.config.global_config import GlobalConfig, PathsConfig
        from orchestrator.db import create_engine, create_session_factory, init_db
        from orchestrator.db import EventStore
        from orchestrator.db import RunRepository
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow import LocalAutoVerifyRunner
        from orchestrator.workflow import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        # Create a test repo with routine and scaffolding
        (tmp_path / "repos").mkdir()
        repo = Path(shutil.copytree(str(_base_repo), str(tmp_path / "repos" / "test-repo")))

        # Create routine with scaffolding
        routine_dir = repo / "routines" / "test-routine"
        routine_dir.mkdir(parents=True)

        routine_yaml = """id: test-routine
name: Test Routine
description: Test routine with scaffolding
inputs: []
steps:
  - id: S-01
    title: Step One
    tasks:
      - id: T-01
        title: Task One
        task_context: Do the task
        requirements:
          - id: R-01
            desc: Do something
            priority: critical
        artifacts: []
"""
        (routine_dir / "routine.yaml").write_text(routine_yaml)

        # Scaffolding files
        scaffolding_dir = routine_dir / "scaffolding"
        scaffolding_dir.mkdir()
        (scaffolding_dir / "template.md").write_text("# Template File\n")
        (scaffolding_dir / "guide.md").write_text("# Guide\n")

        # Commit
        _git(["add", "."], cwd=repo)
        _git(["commit", "-m", "Add routine with scaffolding"], cwd=repo)
        _git(["rev-parse", "HEAD"], cwd=repo)

        # Setup database
        engine = create_engine(":memory:")
        await init_db(engine)
        session_factory = create_session_factory(engine)

        # Setup global config with paths
        repos_dir = tmp_path / "repos"
        worktrees_dir = tmp_path / "worktrees"
        worktrees_dir.mkdir(parents=True)

        global_config = GlobalConfig(
            paths=PathsConfig(
                repos_dir=str(repos_dir),
                worktrees_dir=str(worktrees_dir),
            )
        )

        # Create executor
        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            global_config=global_config,
            spawn_agents=False,
        )

        # Create run
        async with session_factory() as session:
            from orchestrator.config import discover_routines_in_repo

            # For PROJECT routines, use discover_routines_in_repo which finds directory-based routines
            project_routines = discover_routines_in_repo(repo, "main")
            routine = next((r for r in project_routines if r.config.id == "test-routine"), None)
            assert routine is not None, (
                f"Routine not found. Available: {[r.config.id for r in project_routines]}"
            )

            run = create_run_from_routine(
                routine=routine.config,
                repo_name="test-repo",
                source_branch="main",
                routine_source=RoutineSource.PROJECT,
            )
            run.routine_embedded = routine.config.model_dump(mode="json")
            # For PROJECT routines, path is already relative to repo root
            run.routine_path = routine.path
            run.routine_commit = routine.commit
            run.agent_type = AgentRunnerType.USER_MANAGED
            run.worktree_enabled = True

            repo_db = RunRepository(session)
            event_store = EventStore(session)
            emitter = PersistentEventEmitter(event_store)
            service = WorkflowService(
                session=session,
                repo=repo_db,
                event_store=event_store,
                event_emitter=emitter,
                auto_verify_runner=LocalAutoVerifyRunner(),
            )

            await service.create_run(run)
            run_id = run.id

            # Start run (this should create worktree and copy scaffolding)
            await executor.start_run_with_agent(run_id, service)
            await session.commit()

        # Verify scaffolding was copied
        async with session_factory() as session:
            repo_db = RunRepository(session)
            run = await repo_db.get(run_id)

            assert run.worktree_path is not None
            worktree_path = Path(run.worktree_path)
            assert worktree_path.exists()

            # Check routine files were copied to .orchestrator/routine-files/
            routine_files_path = worktree_path / ".orchestrator" / "routine-files"
            assert routine_files_path.exists()
            assert (routine_files_path / "scaffolding" / "template.md").exists()
            assert (routine_files_path / "scaffolding" / "guide.md").exists()

            # Verify content
            assert (
                routine_files_path / "scaffolding" / "template.md"
            ).read_text() == "# Template File\n"
            assert (routine_files_path / "scaffolding" / "guide.md").read_text() == "# Guide\n"

            # Verify .gitignore was updated
            gitignore = worktree_path / ".gitignore"
            assert gitignore.exists()
            assert ".orchestrator/" in gitignore.read_text()

        # Cleanup
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_scaffolding_optional_if_missing(self, tmp_path: Path, _base_repo: Path) -> None:
        """Run should succeed even if routine has no scaffolding."""
        from orchestrator.runners.executor import AgentRunnerExecutor
        from orchestrator.config import AgentRunnerType, RoutineSource
        from orchestrator.config.global_config import GlobalConfig, PathsConfig
        from orchestrator.db import create_engine, create_session_factory, init_db
        from orchestrator.db import EventStore
        from orchestrator.db import RunRepository
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow import LocalAutoVerifyRunner
        from orchestrator.workflow import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        # Create a test repo with routine but NO scaffolding
        (tmp_path / "repos").mkdir()
        repo = Path(shutil.copytree(str(_base_repo), str(tmp_path / "repos" / "test-repo")))

        # Create routine WITHOUT scaffolding
        routine_dir = repo / "routines" / "no-scaffold"
        routine_dir.mkdir(parents=True)

        routine_yaml = """id: no-scaffold
name: No Scaffold Routine
description: Routine without scaffolding
inputs: []
steps:
  - id: S-01
    title: Step One
    tasks:
      - id: T-01
        title: Task One
        task_context: Do the task
        requirements:
          - id: R-01
            desc: Do something
            priority: critical
        artifacts: []
"""
        (routine_dir / "routine.yaml").write_text(routine_yaml)

        # Commit
        _git(["add", "."], cwd=repo)
        _git(["commit", "-m", "Add routine without scaffolding"], cwd=repo)
        _git(["rev-parse", "HEAD"], cwd=repo)

        # Setup database
        engine = create_engine(":memory:")
        await init_db(engine)
        session_factory = create_session_factory(engine)

        # Setup global config with paths
        repos_dir = tmp_path / "repos"
        worktrees_dir = tmp_path / "worktrees"
        worktrees_dir.mkdir(parents=True)

        global_config = GlobalConfig(
            paths=PathsConfig(
                repos_dir=str(repos_dir),
                worktrees_dir=str(worktrees_dir),
            )
        )

        # Create executor
        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            global_config=global_config,
            spawn_agents=False,
        )

        # Create run
        async with session_factory() as session:
            from orchestrator.config import discover_routines_in_repo

            # For PROJECT routines, use discover_routines_in_repo which finds directory-based routines
            project_routines = discover_routines_in_repo(repo, "main")
            routine = next((r for r in project_routines if r.config.id == "no-scaffold"), None)
            assert routine is not None, (
                f"Routine not found. Available: {[r.config.id for r in project_routines]}"
            )

            run = create_run_from_routine(
                routine=routine.config,
                repo_name="test-repo",
                source_branch="main",
                routine_source=RoutineSource.PROJECT,
            )
            run.routine_embedded = routine.config.model_dump(mode="json")
            # For PROJECT routines, path is already relative to repo root
            run.routine_path = routine.path
            run.routine_commit = routine.commit
            run.agent_type = AgentRunnerType.USER_MANAGED
            run.worktree_enabled = True

            repo_db = RunRepository(session)
            event_store = EventStore(session)
            emitter = PersistentEventEmitter(event_store)
            service = WorkflowService(
                session=session,
                repo=repo_db,
                event_store=event_store,
                event_emitter=emitter,
                auto_verify_runner=LocalAutoVerifyRunner(),
            )

            await service.create_run(run)
            run_id = run.id

            # Start run (this should create worktree but NOT fail on missing scaffolding)
            await executor.start_run_with_agent(run_id, service)
            await session.commit()

        # Verify run succeeded and worktree was created
        async with session_factory() as session:
            repo_db = RunRepository(session)
            run = await repo_db.get(run_id)

            assert run.worktree_path is not None
            worktree_path = Path(run.worktree_path)
            assert worktree_path.exists()

            # Scaffolding directory may or may not exist, but run should succeed
            # (copy_scaffolding creates the target directory even if no files copied)

        # Cleanup
        await engine.dispose()
