"""Unit tests for the routine-files copier."""

import shutil
import subprocess
from pathlib import Path

import pytest

from orchestrator.runners import (
    copy_routine_files_local,
    copy_routine_files_git,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# LOCAL copy tests
# ---------------------------------------------------------------------------


class TestCopyRoutineFilesLocal:
    def test_copies_scripts_and_scaffolding(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")

        scripts = source / "scripts"
        scripts.mkdir()
        (scripts / "run.sh").write_text("#!/bin/bash\necho hi\n")

        scaffolding = source / "scaffolding"
        scaffolding.mkdir()
        (scaffolding / "template.md").write_text("# Template\n")

        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_local(source, wt)

        assert result.files_copied == 2
        assert (wt / ".orchestrator" / "routine-files" / "scripts" / "run.sh").exists()
        assert (wt / ".orchestrator" / "routine-files" / "scaffolding" / "template.md").exists()

    def test_skips_routine_yaml(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")
        (source / "routine.yml").write_text("id: test\n")
        scripts = source / "scripts"
        scripts.mkdir()
        (scripts / "check.py").write_text("print('ok')\n")

        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_local(source, wt)

        assert result.files_copied == 1
        target = wt / ".orchestrator" / "routine-files"
        assert not (target / "routine.yaml").exists()
        assert not (target / "routine.yml").exists()
        assert (target / "scripts" / "check.py").exists()

    def test_skips_root_readme(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")
        (source / "README.md").write_text("# Docs\n")

        # README inside a subdirectory should NOT be skipped
        docs = source / "docs"
        docs.mkdir()
        (docs / "README.md").write_text("# Nested readme\n")

        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_local(source, wt)

        assert result.files_copied == 1
        target = wt / ".orchestrator" / "routine-files"
        assert not (target / "README.md").exists()
        assert (target / "docs" / "README.md").exists()

    def test_preserves_nested_structure(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")

        deep = source / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("deep\n")

        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_local(source, wt)

        assert result.files_copied == 1
        assert (
            wt / ".orchestrator" / "routine-files" / "a" / "b" / "c" / "deep.txt"
        ).read_text() == "deep\n"

    def test_empty_routine_dir(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")

        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_local(source, wt)

        assert result.files_copied == 0

    def test_missing_source_dir(self, tmp_path: Path) -> None:
        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_local(tmp_path / "nonexistent", wt)

        assert result.files_copied == 0

    def test_ensures_gitignore(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")
        scripts = source / "scripts"
        scripts.mkdir()
        (scripts / "run.sh").write_text("echo\n")

        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_local(source, wt)

        assert result.gitignore_updated is True
        assert ".orchestrator/" in (wt / ".gitignore").read_text()

    def test_no_duplicate_gitignore(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")

        wt = tmp_path / "worktree"
        wt.mkdir()
        (wt / ".gitignore").write_text(".orchestrator/\n")

        result = copy_routine_files_local(source, wt)

        assert result.gitignore_updated is False

    def test_preserves_file_content(self, tmp_path: Path) -> None:
        source = tmp_path / "routine-dir"
        source.mkdir()
        (source / "routine.yaml").write_text("id: test\n")

        scripts = source / "scripts"
        scripts.mkdir()
        content = "#!/usr/bin/env python3\nimport sys\nprint(sys.argv)\n"
        (scripts / "tool.py").write_text(content)

        wt = tmp_path / "worktree"
        wt.mkdir()

        copy_routine_files_local(source, wt)

        assert (
            wt / ".orchestrator" / "routine-files" / "scripts" / "tool.py"
        ).read_text() == content


# ---------------------------------------------------------------------------
# GIT copy tests
# ---------------------------------------------------------------------------


class TestCopyRoutineFilesGit:
    @pytest.fixture
    def repo_with_routine(self, tmp_path: Path, _unit_base_repo: Path) -> tuple[Path, str, str]:
        repo = Path(shutil.copytree(str(_unit_base_repo), str(tmp_path / "repo")))

        routine_dir = repo / "routines" / "my-routine"
        routine_dir.mkdir(parents=True)
        (routine_dir / "routine.yaml").write_text("id: my-routine\nname: Test\n")

        scripts = routine_dir / "scripts"
        scripts.mkdir()
        (scripts / "check.py").write_text("print('check')\n")

        scaffolding = routine_dir / "scaffolding"
        scaffolding.mkdir()
        (scaffolding / "template.md").write_text("# Template\n")

        (routine_dir / "README.md").write_text("# Docs\n")

        _git(["add", "."], cwd=repo)
        _git(["commit", "-m", "Add routine"], cwd=repo)
        commit = _git(["rev-parse", "HEAD"], cwd=repo)

        return repo, "routines/my-routine/routine.yaml", commit

    def test_copies_all_non_yaml_files(
        self, repo_with_routine: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        repo, routine_path, commit = repo_with_routine
        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_git(repo, routine_path, commit, wt)

        assert (
            result.files_copied == 2
        )  # scripts/check.py + scaffolding/template.md (README skipped)
        target = wt / ".orchestrator" / "routine-files"
        assert (target / "scripts" / "check.py").exists()
        assert (target / "scaffolding" / "template.md").exists()
        assert not (target / "routine.yaml").exists()
        assert not (target / "README.md").exists()

    def test_preserves_content(
        self, repo_with_routine: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        repo, routine_path, commit = repo_with_routine
        wt = tmp_path / "worktree"
        wt.mkdir()

        copy_routine_files_git(repo, routine_path, commit, wt)

        content = (wt / ".orchestrator" / "routine-files" / "scripts" / "check.py").read_text()
        assert content == "print('check')\n"

    def test_ensures_gitignore(
        self, repo_with_routine: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        repo, routine_path, commit = repo_with_routine
        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_git(repo, routine_path, commit, wt)

        assert result.gitignore_updated is True
        assert ".orchestrator/" in (wt / ".gitignore").read_text()

    def test_empty_routine_dir(self, tmp_path: Path, _unit_base_repo: Path) -> None:
        repo = Path(shutil.copytree(str(_unit_base_repo), str(tmp_path / "repo")))

        routine_dir = repo / "routines" / "empty"
        routine_dir.mkdir(parents=True)
        (routine_dir / "routine.yaml").write_text("id: empty\n")

        _git(["add", "."], cwd=repo)
        _git(["commit", "-m", "Empty routine"], cwd=repo)
        commit = _git(["rev-parse", "HEAD"], cwd=repo)

        wt = tmp_path / "worktree"
        wt.mkdir()

        result = copy_routine_files_git(
            repo,
            routine_path="routines/empty/routine.yaml",
            routine_commit=commit,
            worktree_path=wt,
        )

        assert result.files_copied == 0
