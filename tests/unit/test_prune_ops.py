"""Unit tests for prune_ops.py using real git repos."""

import subprocess
from pathlib import Path

import pytest

from orchestrator.git.errors import GitCommandError
from orchestrator.git.ops import (
    Hunk,
    apply_prune,
    preview_prune,
    prune_hunks,
    prune_lines,
    revert_file,
)
from orchestrator.git.ops.prune_ops import (
    _build_hunk_reverse_patch,
    _build_line_reverse_patch,
    _count_selected_hunk_lines,
    _count_selected_range_lines,
    _file_exists_at_ref,
    _parse_diff_sections,
    _parse_file_diff_hunks,
    _parse_hunk_header,
)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    """Initialize a git repo with a base commit on main."""
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("# Test\n")
    _git(["add", "."], cwd=path)
    _git(["commit", "-m", "Initial commit"], cwd=path)
    _git(["branch", "-M", "main"], cwd=path)


def _commit_file(path: Path, filename: str, content: str, message: str) -> str:
    """Create/modify a file and commit it. Returns the commit SHA."""
    (path / filename).write_text(content)
    _git(["add", filename], cwd=path)
    _git(["commit", "-m", message], cwd=path)
    return _git(["rev-parse", "HEAD"], cwd=path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a git repo and return (repo_path, base_sha).

    base_sha is the initial commit on main, which acts as the "base" for
    prune operations (simulating the run branch diverge point).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    base_sha = _git(["rev-parse", "HEAD"], cwd=repo)
    return repo, base_sha


# ---------------------------------------------------------------------------
# Tests for _parse_diff_sections
# ---------------------------------------------------------------------------


class TestParseDiffSections:
    def test_empty_diff_returns_empty_list(self) -> None:
        sections = _parse_diff_sections("")
        assert sections == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        sections = _parse_diff_sections("   \n\n  ")
        assert sections == []

    def test_single_file_section(self) -> None:
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "index 000000..111111 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+line1\n"
            "+line2\n"
        )
        sections = _parse_diff_sections(diff)
        assert len(sections) == 1
        s = sections[0]
        assert s.path == "foo.py"
        assert "diff --git" in s.content
        assert s.hunks == 1
        assert s.lines_changed == 2

    def test_two_file_sections(self) -> None:
        diff = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -0,0 +1 @@\n"
            "+added\n"
        )
        sections = _parse_diff_sections(diff)
        assert len(sections) == 2
        paths = {s.path for s in sections}
        assert paths == {"a.py", "b.py"}

    def test_hunk_count(self) -> None:
        diff = (
            "diff --git a/multi.py b/multi.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+line\n"
            "@@ -10,3 +11,4 @@\n"
            "+another\n"
        )
        sections = _parse_diff_sections(diff)
        assert sections[0].hunks == 2

    def test_lines_changed_counts_additions_and_deletions(self) -> None:
        diff = (
            "diff --git a/file.py b/file.py\n"
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+added\n"
            "-removed\n"
            " context\n"
        )
        sections = _parse_diff_sections(diff)
        # 1 addition + 1 deletion = 2 changed lines
        assert sections[0].lines_changed == 2

    def test_content_includes_diff_header(self) -> None:
        diff = "diff --git a/f.py b/f.py\nindex abc..def 100644\n@@ -1 +1 @@\n+x\n"
        sections = _parse_diff_sections(diff)
        assert sections[0].content.startswith("diff --git a/f.py b/f.py")


# ---------------------------------------------------------------------------
# Tests for revert_file
# ---------------------------------------------------------------------------


class TestRevertFile:
    @pytest.mark.asyncio
    async def test_revert_file_restores_base_state(self, git_repo: tuple[Path, str]) -> None:
        """revert_file restores a modified file to its base-branch state."""
        repo, base_sha = git_repo

        # Add a file at base, then modify it
        (repo / "service.py").write_text("original content\n")
        _git(["add", "service.py"], cwd=repo)
        _git(["commit", "-m", "Add service.py at base"], cwd=repo)
        # Update base_sha to after adding the file
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # Modify the file on the run branch
        (repo / "service.py").write_text("modified content\n")
        _git(["add", "service.py"], cwd=repo)
        _git(["commit", "-m", "Modify service.py on run"], cwd=repo)

        commit_sha = await revert_file(repo, "service.py", base_sha)

        assert len(commit_sha) == 40
        assert (repo / "service.py").read_text() == "original content\n"

    @pytest.mark.asyncio
    async def test_revert_file_creates_new_commit(self, git_repo: tuple[Path, str]) -> None:
        """revert_file creates a new commit on the branch."""
        repo, base_sha = git_repo

        sha_before = _git(["rev-parse", "HEAD"], cwd=repo)

        # Make a change and commit
        (repo / "feature.py").write_text("def foo(): pass\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "Add feature.py"], cwd=repo)

        commit_sha = await revert_file(repo, "feature.py", base_sha)

        sha_after = _git(["rev-parse", "HEAD"], cwd=repo)
        assert sha_after == commit_sha
        assert sha_after != sha_before

    @pytest.mark.asyncio
    async def test_revert_newly_added_file_removes_it(self, git_repo: tuple[Path, str]) -> None:
        """revert_file removes a newly added file if it doesn't exist at base_sha."""
        repo, base_sha = git_repo

        # Add a new file on the run branch (it doesn't exist at base_sha)
        (repo / "new_file.py").write_text("new content\n")
        _git(["add", "new_file.py"], cwd=repo)
        _git(["commit", "-m", "Add new_file.py"], cwd=repo)

        assert (repo / "new_file.py").exists()

        await revert_file(repo, "new_file.py", base_sha)

        assert not (repo / "new_file.py").exists()

    @pytest.mark.asyncio
    async def test_revert_file_already_at_base_raises(self, git_repo: tuple[Path, str]) -> None:
        """revert_file raises GitCommandError if file already matches base state."""
        repo, base_sha = git_repo

        # File doesn't exist at base_sha and no run-branch change either
        # (file doesn't exist at all - git rm would fail)
        # Instead: add and commit at base, then try to revert without any changes
        (repo / "stable.py").write_text("content\n")
        _git(["add", "stable.py"], cwd=repo)
        _git(["commit", "-m", "Add stable.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # No changes to stable.py after base_sha
        with pytest.raises(GitCommandError):
            await revert_file(repo, "stable.py", base_sha)


# ---------------------------------------------------------------------------
# Tests for preview_prune
# ---------------------------------------------------------------------------


class TestPreviewPrune:
    @pytest.mark.asyncio
    async def test_preview_does_not_modify_worktree(self, git_repo: tuple[Path, str]) -> None:
        """preview_prune is read-only: the worktree is unchanged after calling it."""
        repo, base_sha = git_repo

        (repo / "feature.py").write_text("feature content\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "Add feature"], cwd=repo)

        head_before = _git(["rev-parse", "HEAD"], cwd=repo)
        content_before = (repo / "feature.py").read_text()

        await preview_prune(repo, ["feature.py"], base_sha)

        assert _git(["rev-parse", "HEAD"], cwd=repo) == head_before
        assert (repo / "feature.py").read_text() == content_before

    @pytest.mark.asyncio
    async def test_preview_returns_correct_files_affected(self, git_repo: tuple[Path, str]) -> None:
        """files_affected matches the number of selected files with changes."""
        repo, base_sha = git_repo

        _commit_file(repo, "a.py", "a content\n", "Add a.py")
        _commit_file(repo, "b.py", "b content\n", "Add b.py")

        stats = await preview_prune(repo, ["a.py", "b.py"], base_sha)

        assert stats.files_affected == 2

    @pytest.mark.asyncio
    async def test_preview_resulting_diff_excludes_pruned_files(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """resulting_diff does not contain changes to the pruned files."""
        repo, base_sha = git_repo

        _commit_file(repo, "pruned.py", "pruned content\n", "Add pruned.py")
        _commit_file(repo, "kept.py", "kept content\n", "Add kept.py")

        stats = await preview_prune(repo, ["pruned.py"], base_sha)

        assert "pruned.py" not in stats.resulting_diff
        assert "kept.py" in stats.resulting_diff

    @pytest.mark.asyncio
    async def test_preview_empty_selection_returns_full_diff(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """Empty file_paths returns the full diff unchanged."""
        repo, base_sha = git_repo

        _commit_file(repo, "thing.py", "thing content\n", "Add thing.py")

        stats = await preview_prune(repo, [], base_sha)

        assert stats.files_affected == 0
        assert stats.hunks_removed == 0
        assert stats.lines_removed == 0
        assert "thing.py" in stats.resulting_diff

    @pytest.mark.asyncio
    async def test_preview_counts_hunks_and_lines(self, git_repo: tuple[Path, str]) -> None:
        """hunks_removed and lines_removed reflect the pruned sections."""
        repo, base_sha = git_repo

        # Add a file with 2 lines — one hunk, 2 added lines
        _commit_file(repo, "counted.py", "line1\nline2\n", "Add counted.py")

        stats = await preview_prune(repo, ["counted.py"], base_sha)

        assert stats.hunks_removed >= 1
        assert stats.lines_removed == 2

    @pytest.mark.asyncio
    async def test_preview_no_changes_returns_empty_stats(self, git_repo: tuple[Path, str]) -> None:
        """If selected file has no changes relative to base, stats are zero."""
        repo, base_sha = git_repo

        # Nothing changed after base_sha
        stats = await preview_prune(repo, ["README.md"], base_sha)

        assert stats.files_affected == 0
        assert stats.hunks_removed == 0
        assert stats.lines_removed == 0


# ---------------------------------------------------------------------------
# Tests for apply_prune
# ---------------------------------------------------------------------------


class TestApplyPrune:
    @pytest.mark.asyncio
    async def test_apply_prune_creates_commit(self, git_repo: tuple[Path, str]) -> None:
        """apply_prune creates a new commit after pruning."""
        repo, base_sha = git_repo

        _commit_file(repo, "to_prune.py", "content\n", "Add to_prune.py")
        head_before = _git(["rev-parse", "HEAD"], cwd=repo)

        commit_sha, _stats = await apply_prune(repo, ["to_prune.py"], base_sha)

        head_after = _git(["rev-parse", "HEAD"], cwd=repo)
        assert head_after == commit_sha
        assert head_after != head_before

    @pytest.mark.asyncio
    async def test_apply_prune_file_level_removes_added_file(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """apply_prune removes a newly added file from the worktree."""
        repo, base_sha = git_repo

        _commit_file(repo, "feature.py", "def foo(): pass\n", "Add feature.py")
        assert (repo / "feature.py").exists()

        await apply_prune(repo, ["feature.py"], base_sha)

        assert not (repo / "feature.py").exists()

    @pytest.mark.asyncio
    async def test_apply_prune_file_level_restores_modified_file(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """apply_prune restores a modified file to its base content."""
        repo, base_sha = git_repo

        # Add file at base
        (repo / "config.py").write_text("original = True\n")
        _git(["add", "config.py"], cwd=repo)
        _git(["commit", "-m", "Add config.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # Modify on run branch
        (repo / "config.py").write_text("modified = True\nextra = 1\n")
        _git(["add", "config.py"], cwd=repo)
        _git(["commit", "-m", "Modify config.py"], cwd=repo)

        await apply_prune(repo, ["config.py"], base_sha)

        assert (repo / "config.py").read_text() == "original = True\n"

    @pytest.mark.asyncio
    async def test_apply_prune_preserves_other_files(self, git_repo: tuple[Path, str]) -> None:
        """apply_prune leaves untouched files unchanged."""
        repo, base_sha = git_repo

        _commit_file(repo, "to_prune.py", "content\n", "Add to_prune.py")
        _commit_file(repo, "to_keep.py", "keep this\n", "Add to_keep.py")

        await apply_prune(repo, ["to_prune.py"], base_sha)

        assert not (repo / "to_prune.py").exists()
        assert (repo / "to_keep.py").exists()
        assert (repo / "to_keep.py").read_text() == "keep this\n"

    @pytest.mark.asyncio
    async def test_apply_prune_returns_correct_stats(self, git_repo: tuple[Path, str]) -> None:
        """apply_prune returns PruneStats reflecting what was removed."""
        repo, base_sha = git_repo

        _commit_file(repo, "file1.py", "a\nb\n", "Add file1.py")
        _commit_file(repo, "file2.py", "x\ny\n", "Add file2.py")

        _commit_sha, stats = await apply_prune(repo, ["file1.py", "file2.py"], base_sha)

        assert stats.files_affected == 2
        assert stats.lines_removed >= 4  # at least 4 added lines
        assert stats.resulting_diff == ""  # all changes pruned

    @pytest.mark.asyncio
    async def test_apply_prune_uses_custom_message(self, git_repo: tuple[Path, str]) -> None:
        """apply_prune uses the provided commit message."""
        repo, base_sha = git_repo

        _commit_file(repo, "msg_test.py", "content\n", "Add msg_test.py")

        await apply_prune(repo, ["msg_test.py"], base_sha, message="custom prune message")

        log = _git(["log", "--format=%s", "-1"], cwd=repo)
        assert log == "custom prune message"

    @pytest.mark.asyncio
    async def test_apply_prune_multiple_files_single_commit(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """Multiple files are pruned in a single commit."""
        repo, base_sha = git_repo

        _commit_file(repo, "a.py", "a\n", "Add a.py")
        _commit_file(repo, "b.py", "b\n", "Add b.py")
        commits_before = _git(["rev-list", "--count", "HEAD"], cwd=repo)

        await apply_prune(repo, ["a.py", "b.py"], base_sha)

        commits_after = _git(["rev-list", "--count", "HEAD"], cwd=repo)
        assert int(commits_after) == int(commits_before) + 1


# ---------------------------------------------------------------------------
# Tests for helper functions
# ---------------------------------------------------------------------------


class TestFileExistsAtRef:
    def test_existing_file_returns_true(self, git_repo: tuple[Path, str]) -> None:
        repo, base_sha = git_repo
        # README.md was committed at base_sha
        assert _file_exists_at_ref(repo, base_sha, "README.md") is True

    def test_nonexistent_file_returns_false(self, git_repo: tuple[Path, str]) -> None:
        repo, base_sha = git_repo
        assert _file_exists_at_ref(repo, base_sha, "nonexistent.py") is False

    def test_newly_added_file_not_at_base(self, git_repo: tuple[Path, str]) -> None:
        repo, base_sha = git_repo
        _commit_file(repo, "new.py", "content\n", "Add new.py")
        # new.py doesn't exist at base_sha (before it was added)
        assert _file_exists_at_ref(repo, base_sha, "new.py") is False


# ---------------------------------------------------------------------------
# Tests for hunk-parsing helpers
# ---------------------------------------------------------------------------


class TestParseHunkHeader:
    def test_with_counts(self) -> None:
        old_start, old_count, new_start, new_count, suffix = _parse_hunk_header(
            "@@ -5,3 +5,4 @@ some context"
        )
        assert old_start == 5
        assert old_count == 3
        assert new_start == 5
        assert new_count == 4
        assert suffix == " some context"

    def test_without_counts(self) -> None:
        # @@ -1 +1 @@ means count=1 each
        old_start, old_count, new_start, new_count, suffix = _parse_hunk_header("@@ -1 +1 @@")
        assert old_start == 1
        assert old_count == 1
        assert new_start == 1
        assert new_count == 1
        assert suffix == ""

    def test_zero_count(self) -> None:
        old_start, old_count, new_start, new_count, _suffix = _parse_hunk_header("@@ -0,0 +1,3 @@")
        assert old_start == 0
        assert old_count == 0
        assert new_start == 1
        assert new_count == 3

    def test_invalid_header_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_hunk_header("not a hunk header")


class TestParseFileDiffHunks:
    def test_single_hunk(self) -> None:
        diff = (
            "diff --git a/f.py b/f.py\n"
            "index 000..111 100644\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,2 +1,3 @@\n"
            " ctx\n"
            "+added\n"
            " ctx2\n"
        )
        header_lines, hunks = _parse_file_diff_hunks(diff)
        assert len(header_lines) == 4  # diff, index, ---, +++
        assert len(hunks) == 1
        h = hunks[0]
        assert h.old_start == 1
        assert h.old_count == 2
        assert h.new_start == 1
        assert h.new_count == 3
        assert " ctx\n" in h.lines
        assert "+added\n" in h.lines

    def test_two_hunks(self) -> None:
        diff = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,2 +1,3 @@\n"
            " ctx1\n"
            "+added1\n"
            " ctx2\n"
            "@@ -10,2 +11,3 @@\n"
            " ctx3\n"
            "+added2\n"
            " ctx4\n"
        )
        header_lines, hunks = _parse_file_diff_hunks(diff)
        assert len(hunks) == 2
        assert hunks[0].new_start == 1
        assert hunks[1].new_start == 11

    def test_empty_diff_returns_empty(self) -> None:
        header_lines, hunks = _parse_file_diff_hunks("")
        assert header_lines == []
        assert hunks == []


class TestBuildHunkReversePatch:
    def _make_hunk(
        self, old_start: int, old_count: int, new_start: int, new_count: int, lines: list[str]
    ) -> Hunk:
        return Hunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            header_suffix="",
            lines=lines,
        )

    def test_select_single_hunk(self) -> None:
        header = ["diff --git a/f.py b/f.py\n", "--- a/f.py\n", "+++ b/f.py\n"]
        hunk0 = self._make_hunk(1, 1, 1, 2, [" ctx\n", "+added\n"])
        hunk1 = self._make_hunk(10, 1, 11, 2, [" ctx2\n", "+added2\n"])

        patch = _build_hunk_reverse_patch(header, [hunk0, hunk1], [0])

        assert "@@ -1,1 +1,2 @@" in patch
        assert "+added\n" in patch
        # hunk1 should NOT appear
        assert "+added2\n" not in patch

    def test_select_second_hunk(self) -> None:
        header = ["--- a/f.py\n", "+++ b/f.py\n"]
        hunk0 = self._make_hunk(1, 1, 1, 2, [" ctx\n", "+added\n"])
        hunk1 = self._make_hunk(10, 1, 11, 2, [" ctx2\n", "+added2\n"])

        patch = _build_hunk_reverse_patch(header, [hunk0, hunk1], [1])

        assert "+added\n" not in patch
        assert "+added2\n" in patch

    def test_empty_selection_returns_empty_string(self) -> None:
        hunk0 = self._make_hunk(1, 1, 1, 2, [" ctx\n"])
        patch = _build_hunk_reverse_patch([], [hunk0], [])
        assert patch == ""

    def test_out_of_range_index_ignored(self) -> None:
        hunk0 = self._make_hunk(1, 1, 1, 2, [" ctx\n", "+added\n"])
        patch = _build_hunk_reverse_patch(["--- a/f.py\n"], [hunk0], [99])
        assert patch == ""

    def test_all_hunks_selected(self) -> None:
        header = ["--- a/f.py\n", "+++ b/f.py\n"]
        hunk0 = self._make_hunk(1, 1, 1, 2, ["+added_a\n"])
        hunk1 = self._make_hunk(10, 1, 11, 2, ["+added_b\n"])

        patch = _build_hunk_reverse_patch(header, [hunk0, hunk1], [0, 1])

        assert "+added_a\n" in patch
        assert "+added_b\n" in patch


class TestBuildLineReversePatch:
    def _make_hunk(self, new_start: int, lines: list[str]) -> Hunk:
        return Hunk(
            old_start=new_start,
            old_count=len([ln for ln in lines if ln[0] != "+"]),
            new_start=new_start,
            new_count=len([ln for ln in lines if ln[0] != "-"]),
            header_suffix="",
            lines=lines,
        )

    def test_select_one_of_two_additions(self) -> None:
        # File: ctx1, added_a(line2), added_b(line3), ctx2
        hunk = self._make_hunk(1, [" ctx1\n", "+added_a\n", "+added_b\n", " ctx2\n"])
        header = ["--- a/f.py\n", "+++ b/f.py\n"]

        patch = _build_line_reverse_patch(header, [hunk], [(3, 3)])

        # added_b (line 3) is selected → appears as +
        assert "+added_b\n" in patch
        # added_a (line 2) is NOT selected → converted to context
        assert " added_a\n" in patch
        assert "+added_a\n" not in patch

    def test_no_lines_in_range_returns_empty(self) -> None:
        hunk = self._make_hunk(1, [" ctx\n", "+added\n", " ctx2\n"])
        # range 99-100 doesn't overlap with any + lines
        patch = _build_line_reverse_patch([], [hunk], [(99, 100)])
        assert patch == ""

    def test_all_lines_in_range(self) -> None:
        hunk = self._make_hunk(1, ["+line1\n", "+line2\n"])
        header = ["--- a/f.py\n", "+++ b/f.py\n"]

        patch = _build_line_reverse_patch(header, [hunk], [(1, 2)])

        assert "+line1\n" in patch
        assert "+line2\n" in patch

    def test_deletion_lines_are_skipped(self) -> None:
        # Hunk has a deletion and an addition; line-mode skips the deletion
        hunk = self._make_hunk(1, [" ctx\n", "-old\n", "+new\n", " ctx2\n"])
        header = ["--- a/f.py\n", "+++ b/f.py\n"]

        # Select the + line (HEAD line 2: ctx is line1, +new is line2)
        patch = _build_line_reverse_patch(header, [hunk], [(2, 2)])

        assert "+new\n" in patch
        assert "-old\n" not in patch  # deletion was skipped


# ---------------------------------------------------------------------------
# Integration tests for prune_hunks
# ---------------------------------------------------------------------------


class TestPruneHunks:
    @pytest.mark.asyncio
    async def test_prune_hunk_removes_selected_hunk(self, git_repo: tuple[Path, str]) -> None:
        """prune_hunks removes the selected hunk while preserving other hunks."""
        repo, _ = git_repo

        # 20-line base file so changes are far enough apart for 2 hunks
        base_lines = [f"line{i}\n" for i in range(1, 21)]
        (repo / "multi.py").write_text("".join(base_lines))
        _git(["add", "multi.py"], cwd=repo)
        _git(["commit", "-m", "Add multi.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # Two additions far apart → two separate hunks
        modified_lines = (
            base_lines[:1]  # line1
            + ["added_near_top\n"]  # hunk 0
            + base_lines[1:15]  # line2 … line15
            + ["added_near_bottom\n"]  # hunk 1
            + base_lines[15:]  # line16 … line20
        )
        (repo / "multi.py").write_text("".join(modified_lines))
        _git(["add", "multi.py"], cwd=repo)
        _git(["commit", "-m", "Add two lines far apart"], cwd=repo)

        # Verify we have 2 hunks
        diff = subprocess.check_output(
            ["git", "diff", f"{base_sha}..HEAD", "--", "multi.py"],
            cwd=repo,
            text=True,
        )
        assert diff.count("@@") >= 2, "Expected at least 2 hunks"

        # Prune only hunk 0 (added_near_top)
        commit_sha, stats = await prune_hunks(repo, "multi.py", base_sha, [0])

        content = (repo / "multi.py").read_text()
        assert "added_near_top" not in content
        assert "added_near_bottom" in content
        assert len(commit_sha) == 40
        assert stats.hunks_removed == 1
        assert stats.files_affected == 1

    @pytest.mark.asyncio
    async def test_prune_hunk_preserves_other_hunks(self, git_repo: tuple[Path, str]) -> None:
        """prune_hunks leaves unselected hunks intact."""
        repo, _ = git_repo

        base_lines = [f"line{i}\n" for i in range(1, 21)]
        (repo / "multi.py").write_text("".join(base_lines))
        _git(["add", "multi.py"], cwd=repo)
        _git(["commit", "-m", "Add multi.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        modified_lines = (
            base_lines[:1]
            + ["top_addition\n"]
            + base_lines[1:15]
            + ["bottom_addition\n"]
            + base_lines[15:]
        )
        (repo / "multi.py").write_text("".join(modified_lines))
        _git(["add", "multi.py"], cwd=repo)
        _git(["commit", "-m", "Two additions"], cwd=repo)

        # Prune only hunk 1 (bottom_addition)
        await prune_hunks(repo, "multi.py", base_sha, [1])

        content = (repo / "multi.py").read_text()
        assert "top_addition" in content
        assert "bottom_addition" not in content

    @pytest.mark.asyncio
    async def test_prune_hunk_creates_commit(self, git_repo: tuple[Path, str]) -> None:
        """prune_hunks creates a new commit."""
        repo, _ = git_repo

        base_lines = [f"line{i}\n" for i in range(1, 21)]
        (repo / "multi.py").write_text("".join(base_lines))
        _git(["add", "multi.py"], cwd=repo)
        _git(["commit", "-m", "Add multi.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        modified_lines = ["new_first_line\n"] + base_lines[1:]
        (repo / "multi.py").write_text("".join(modified_lines))
        _git(["add", "multi.py"], cwd=repo)
        _git(["commit", "-m", "Modify first line"], cwd=repo)
        head_before = _git(["rev-parse", "HEAD"], cwd=repo)

        commit_sha, _stats = await prune_hunks(repo, "multi.py", base_sha, [0])

        head_after = _git(["rev-parse", "HEAD"], cwd=repo)
        assert head_after == commit_sha
        assert head_after != head_before

    @pytest.mark.asyncio
    async def test_prune_all_hunks_leaves_no_diff(self, git_repo: tuple[Path, str]) -> None:
        """Pruning all hunks leaves the file identical to base."""
        repo, _ = git_repo

        (repo / "simple.py").write_text("original\n")
        _git(["add", "simple.py"], cwd=repo)
        _git(["commit", "-m", "Add simple.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        (repo / "simple.py").write_text("original\nmodified\n")
        _git(["add", "simple.py"], cwd=repo)
        _git(["commit", "-m", "Modify simple.py"], cwd=repo)

        _commit_sha, stats = await prune_hunks(repo, "simple.py", base_sha, [0])

        assert (repo / "simple.py").read_text() == "original\n"
        assert stats.resulting_diff == ""


# ---------------------------------------------------------------------------
# Integration tests for prune_lines
# ---------------------------------------------------------------------------


class TestPruneLines:
    @pytest.mark.asyncio
    async def test_prune_lines_removes_selected_addition(self, git_repo: tuple[Path, str]) -> None:
        """prune_lines removes the selected + line and preserves surrounding lines."""
        repo, _ = git_repo

        # Base: line1, line2, line3
        (repo / "feature.py").write_text("line1\nline2\nline3\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "Base commit"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # HEAD: line1, added_a, added_b, line2, line3
        (repo / "feature.py").write_text("line1\nadded_a\nadded_b\nline2\nline3\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "Add two lines"], cwd=repo)

        # added_a is HEAD line 2, added_b is HEAD line 3
        # Prune only added_b (line 3)
        commit_sha, stats = await prune_lines(repo, "feature.py", base_sha, [(3, 3)])

        content = (repo / "feature.py").read_text()
        assert "added_a" in content
        assert "added_b" not in content
        assert "line1" in content
        assert "line2" in content
        assert "line3" in content
        assert len(commit_sha) == 40
        assert stats.lines_removed == 1
        assert stats.files_affected == 1

    @pytest.mark.asyncio
    async def test_prune_lines_preserves_surrounding_lines(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """Pruning one line in a range leaves all other lines intact."""
        repo, _ = git_repo

        (repo / "feature.py").write_text("alpha\nbeta\ngamma\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        (repo / "feature.py").write_text("alpha\nbeta\nINSERTED\ngamma\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "Insert line"], cwd=repo)

        # INSERTED is HEAD line 3
        await prune_lines(repo, "feature.py", base_sha, [(3, 3)])

        content = (repo / "feature.py").read_text()
        assert "alpha" in content
        assert "beta" in content
        assert "gamma" in content
        assert "INSERTED" not in content

    @pytest.mark.asyncio
    async def test_prune_lines_creates_commit(self, git_repo: tuple[Path, str]) -> None:
        """prune_lines creates a new commit on the branch."""
        repo, _ = git_repo

        (repo / "f.py").write_text("a\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        (repo / "f.py").write_text("a\nb\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Add b"], cwd=repo)
        head_before = _git(["rev-parse", "HEAD"], cwd=repo)

        # b is HEAD line 2
        commit_sha, _stats = await prune_lines(repo, "f.py", base_sha, [(2, 2)])

        assert commit_sha != head_before
        assert _git(["rev-parse", "HEAD"], cwd=repo) == commit_sha

    @pytest.mark.asyncio
    async def test_prune_multiple_lines_in_range(self, git_repo: tuple[Path, str]) -> None:
        """prune_lines removes all lines matching a multi-line range."""
        repo, _ = git_repo

        (repo / "f.py").write_text("keep1\nkeep2\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # HEAD: keep1, rm_a, rm_b, rm_c, keep2
        (repo / "f.py").write_text("keep1\nrm_a\nrm_b\nrm_c\nkeep2\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Add three lines"], cwd=repo)

        # Prune lines 2-4 (rm_a, rm_b, rm_c)
        _commit_sha, stats = await prune_lines(repo, "f.py", base_sha, [(2, 4)])

        content = (repo / "f.py").read_text()
        assert "keep1" in content
        assert "keep2" in content
        assert "rm_a" not in content
        assert "rm_b" not in content
        assert "rm_c" not in content
        assert stats.lines_removed == 3


# ---------------------------------------------------------------------------
# Edge cases: multi-hunk prune (prune 2+ hunks at once)
# ---------------------------------------------------------------------------


class TestPruneHunksEdgeCases:
    @pytest.mark.asyncio
    async def test_prune_multiple_hunks_at_once(self, git_repo: tuple[Path, str]) -> None:
        """Prune two hunks at once from a file with three hunks."""
        repo, _ = git_repo

        # 30-line base file to force three separate hunks
        base_lines = [f"line{i}\n" for i in range(1, 31)]
        (repo / "multi3.py").write_text("".join(base_lines))
        _git(["add", "multi3.py"], cwd=repo)
        _git(["commit", "-m", "Add multi3.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # Insert lines far apart to create three separate hunks
        modified = (
            ["add_top\n"]
            + base_lines[:9]  # lines 1-9 → after add_top, gap of 9
            + ["add_mid\n"]
            + base_lines[9:24]  # gap of 15
            + ["add_bot\n"]
            + base_lines[24:]
        )
        (repo / "multi3.py").write_text("".join(modified))
        _git(["add", "multi3.py"], cwd=repo)
        _git(["commit", "-m", "Three additions"], cwd=repo)

        diff = subprocess.check_output(
            ["git", "diff", f"{base_sha}..HEAD", "--", "multi3.py"],
            cwd=repo,
            text=True,
        )
        hunk_count = diff.count("@@")
        assert hunk_count >= 2, f"Expected at least 2 hunks, got {hunk_count}"

        # Prune hunks 0 and 2 (top and bottom), keep middle
        commit_sha, stats = await prune_hunks(repo, "multi3.py", base_sha, [0, 2])

        content = (repo / "multi3.py").read_text()
        assert "add_top" not in content
        assert "add_bot" not in content
        assert "add_mid" in content
        assert stats.hunks_removed == 2
        assert len(commit_sha) == 40

    @pytest.mark.asyncio
    async def test_prune_all_hunks_from_multi_hunk_file(self, git_repo: tuple[Path, str]) -> None:
        """Pruning all hunks from a multi-hunk file leaves it identical to base."""
        repo, _ = git_repo

        base_lines = [f"base{i}\n" for i in range(1, 21)]
        (repo / "all_hunks.py").write_text("".join(base_lines))
        _git(["add", "all_hunks.py"], cwd=repo)
        _git(["commit", "-m", "Add all_hunks.py"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        modified = (
            base_lines[:1] + ["top_add\n"] + base_lines[1:15] + ["bot_add\n"] + base_lines[15:]
        )
        (repo / "all_hunks.py").write_text("".join(modified))
        _git(["add", "all_hunks.py"], cwd=repo)
        _git(["commit", "-m", "Two additions"], cwd=repo)

        _commit_sha, stats = await prune_hunks(repo, "all_hunks.py", base_sha, [0, 1])

        content = (repo / "all_hunks.py").read_text()
        assert "top_add" not in content
        assert "bot_add" not in content
        assert stats.resulting_diff == ""

    @pytest.mark.asyncio
    async def test_prune_hunks_empty_list_raises(self, git_repo: tuple[Path, str]) -> None:
        """Empty hunk_indices list raises GitCommandError."""
        repo, _ = git_repo

        (repo / "simple.py").write_text("original\n")
        _git(["add", "simple.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        (repo / "simple.py").write_text("original\nmodified\n")
        _git(["add", "simple.py"], cwd=repo)
        _git(["commit", "-m", "Modify"], cwd=repo)

        with pytest.raises(GitCommandError):
            await prune_hunks(repo, "simple.py", base_sha, [])

    @pytest.mark.asyncio
    async def test_prune_hunks_out_of_range_index_raises(self, git_repo: tuple[Path, str]) -> None:
        """Out-of-range hunk index raises GitCommandError (no valid hunks)."""
        repo, _ = git_repo

        (repo / "simple.py").write_text("original\n")
        _git(["add", "simple.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        (repo / "simple.py").write_text("original\nmodified\n")
        _git(["add", "simple.py"], cwd=repo)
        _git(["commit", "-m", "Modify"], cwd=repo)

        with pytest.raises(GitCommandError):
            await prune_hunks(repo, "simple.py", base_sha, [99])


# ---------------------------------------------------------------------------
# Edge cases: adjacent changes in line-level prune
# ---------------------------------------------------------------------------


class TestPruneLinesEdgeCases:
    @pytest.mark.asyncio
    async def test_prune_adjacent_additions_partial(self, git_repo: tuple[Path, str]) -> None:
        """Pruning a subset of adjacent additions in one hunk works correctly."""
        repo, _ = git_repo

        (repo / "adj.py").write_text("before\nafter\n")
        _git(["add", "adj.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # HEAD: before, a1, a2, a3, after  (four adjacent added lines)
        (repo / "adj.py").write_text("before\na1\na2\na3\nafter\n")
        _git(["add", "adj.py"], cwd=repo)
        _git(["commit", "-m", "Add a1-a3"], cwd=repo)

        # Prune only a2 (HEAD line 3)
        commit_sha, stats = await prune_lines(repo, "adj.py", base_sha, [(3, 3)])

        content = (repo / "adj.py").read_text()
        assert "a1" in content
        assert "a2" not in content
        assert "a3" in content
        assert "before" in content
        assert "after" in content
        assert stats.lines_removed == 1
        assert len(commit_sha) == 40

    @pytest.mark.asyncio
    async def test_prune_adjacent_additions_all(self, git_repo: tuple[Path, str]) -> None:
        """Pruning all adjacent added lines removes them all."""
        repo, _ = git_repo

        (repo / "adj.py").write_text("before\nafter\n")
        _git(["add", "adj.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        (repo / "adj.py").write_text("before\nA\nB\nC\nafter\n")
        _git(["add", "adj.py"], cwd=repo)
        _git(["commit", "-m", "Add A B C"], cwd=repo)

        # A=line2, B=line3, C=line4
        _commit_sha, stats = await prune_lines(repo, "adj.py", base_sha, [(2, 4)])

        content = (repo / "adj.py").read_text()
        assert "A" not in content
        assert "B" not in content
        assert "C" not in content
        assert "before" in content
        assert "after" in content
        assert stats.lines_removed == 3

    @pytest.mark.asyncio
    async def test_prune_lines_empty_ranges_raises(self, git_repo: tuple[Path, str]) -> None:
        """Empty line_ranges list raises GitCommandError."""
        repo, _ = git_repo

        (repo / "f.py").write_text("line1\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        (repo / "f.py").write_text("line1\nline2\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Add line2"], cwd=repo)

        with pytest.raises(GitCommandError):
            await prune_lines(repo, "f.py", base_sha, [])

    @pytest.mark.asyncio
    async def test_prune_lines_range_outside_additions_raises(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """Line range that doesn't intersect any + lines raises GitCommandError."""
        repo, _ = git_repo

        (repo / "f.py").write_text("line1\nline2\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # Append one line; that line is HEAD line 3
        (repo / "f.py").write_text("line1\nline2\nnewline\n")
        _git(["add", "f.py"], cwd=repo)
        _git(["commit", "-m", "Add newline"], cwd=repo)

        # Range 1-2 are context lines (not +), so nothing selected
        with pytest.raises(GitCommandError):
            await prune_lines(repo, "f.py", base_sha, [(1, 2)])

    @pytest.mark.asyncio
    async def test_prune_lines_multiple_non_contiguous_ranges(
        self, git_repo: tuple[Path, str]
    ) -> None:
        """Multiple non-contiguous line ranges can be pruned in one operation."""
        repo, _ = git_repo

        base_lines = [f"base{i}\n" for i in range(1, 21)]
        (repo / "multi_range.py").write_text("".join(base_lines))
        _git(["add", "multi_range.py"], cwd=repo)
        _git(["commit", "-m", "Base"], cwd=repo)
        base_sha = _git(["rev-parse", "HEAD"], cwd=repo)

        # Insert ADD_A after base1 (HEAD line 2) and ADD_B after base15 (HEAD line ~18)
        modified = base_lines[:1] + ["ADD_A\n"] + base_lines[1:15] + ["ADD_B\n"] + base_lines[15:]
        (repo / "multi_range.py").write_text("".join(modified))
        _git(["add", "multi_range.py"], cwd=repo)
        _git(["commit", "-m", "Two inserts"], cwd=repo)

        # Compute the HEAD line numbers for ADD_A and ADD_B
        # ADD_A is at HEAD line 2, ADD_B is at HEAD line 17 (1 + 1 + 15)
        add_a_line = 2
        add_b_line = 17

        _commit_sha, stats = await prune_lines(
            repo, "multi_range.py", base_sha, [(add_a_line, add_a_line), (add_b_line, add_b_line)]
        )

        content = (repo / "multi_range.py").read_text()
        assert "ADD_A" not in content
        assert "ADD_B" not in content
        assert stats.lines_removed == 2


# ---------------------------------------------------------------------------
# Tests for _count_selected_hunk_lines and _count_selected_range_lines
# ---------------------------------------------------------------------------


class TestCountHelpers:
    def _make_hunk(self, new_start: int, lines: list[str]) -> Hunk:
        return Hunk(
            old_start=new_start,
            old_count=new_start,
            new_start=new_start,
            new_count=new_start,
            header_suffix="",
            lines=lines,
        )

    def test_count_selected_hunk_lines_counts_plus_and_minus(self) -> None:
        hunk = self._make_hunk(1, [" ctx\n", "+added\n", "-removed\n"])
        assert _count_selected_hunk_lines([hunk], [0]) == 2

    def test_count_selected_hunk_lines_skips_context(self) -> None:
        hunk = self._make_hunk(1, [" ctx1\n", " ctx2\n", "+added\n"])
        assert _count_selected_hunk_lines([hunk], [0]) == 1

    def test_count_selected_hunk_lines_empty_indices(self) -> None:
        hunk = self._make_hunk(1, ["+added\n"])
        assert _count_selected_hunk_lines([hunk], []) == 0

    def test_count_selected_hunk_lines_out_of_range_index(self) -> None:
        hunk = self._make_hunk(1, ["+added\n"])
        assert _count_selected_hunk_lines([hunk], [99]) == 0

    def test_count_selected_range_lines_counts_additions_in_range(self) -> None:
        # new_start=1: ctx(1), +add_a(2), +add_b(3), ctx(4)
        hunk = self._make_hunk(1, [" ctx\n", "+add_a\n", "+add_b\n", " ctx2\n"])
        lines, hunks = _count_selected_range_lines([hunk], [(2, 3)])
        assert lines == 2
        assert hunks == 1

    def test_count_selected_range_lines_excludes_out_of_range(self) -> None:
        hunk = self._make_hunk(1, [" ctx\n", "+add_a\n", "+add_b\n", " ctx2\n"])
        lines, hunks = _count_selected_range_lines([hunk], [(3, 3)])
        assert lines == 1
        assert hunks == 1

    def test_count_selected_range_lines_no_match_returns_zero(self) -> None:
        hunk = self._make_hunk(1, [" ctx\n", "+add_a\n"])
        lines, hunks = _count_selected_range_lines([hunk], [(99, 100)])
        assert lines == 0
        assert hunks == 0

    def test_count_selected_range_lines_multiple_hunks(self) -> None:
        # Two hunks at different positions
        hunk0 = self._make_hunk(1, ["+top\n"])  # HEAD line 1
        hunk1 = self._make_hunk(20, ["+bot\n"])  # HEAD line 20
        lines, hunks = _count_selected_range_lines([hunk0, hunk1], [(1, 1), (20, 20)])
        assert lines == 2
        assert hunks == 2


# ---------------------------------------------------------------------------
# Edge cases: apply_prune with empty selections
# ---------------------------------------------------------------------------


class TestApplyPruneEdgeCases:
    @pytest.mark.asyncio
    async def test_apply_prune_empty_list_raises(self, git_repo: tuple[Path, str]) -> None:
        """apply_prune with empty file list raises GitCommandError (nothing staged)."""
        repo, base_sha = git_repo

        _commit_file(repo, "file.py", "content\n", "Add file.py")

        with pytest.raises(GitCommandError):
            await apply_prune(repo, [], base_sha)

    @pytest.mark.asyncio
    async def test_apply_prune_no_diff_raises(self, git_repo: tuple[Path, str]) -> None:
        """apply_prune raises when selected file has no diff versus base."""
        repo, base_sha = git_repo

        # README.md exists at base_sha and hasn't changed
        with pytest.raises(GitCommandError):
            await apply_prune(repo, ["README.md"], base_sha)


# ---------------------------------------------------------------------------
# Edge cases: _build_hunk_reverse_patch and _build_line_reverse_patch
# ---------------------------------------------------------------------------


class TestBuildPatchEdgeCases:
    def _make_hunk(
        self, old_start: int, old_count: int, new_start: int, new_count: int, lines: list[str]
    ) -> Hunk:
        return Hunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            header_suffix="",
            lines=lines,
        )

    def test_build_hunk_patch_deduplicates_indices(self) -> None:
        """Duplicate indices are deduplicated and the hunk appears only once."""
        header = ["--- a/f.py\n", "+++ b/f.py\n"]
        hunk = self._make_hunk(1, 1, 1, 2, ["+added\n"])
        patch = _build_hunk_reverse_patch(header, [hunk], [0, 0, 0])
        # The hunk header should appear exactly once
        assert patch.count("@@ -1,1 +1,2 @@") == 1

    def test_build_hunk_patch_preserves_header_suffix(self) -> None:
        """The hunk header suffix (function context) is preserved."""
        hunk = Hunk(
            old_start=10,
            old_count=2,
            new_start=10,
            new_count=3,
            header_suffix=" def my_func",
            lines=[" ctx\n", "+new_line\n"],
        )
        patch = _build_hunk_reverse_patch(["--- a/f.py\n", "+++ b/f.py\n"], [hunk], [0])
        assert "@@ -10,2 +10,3 @@ def my_func" in patch

    def test_build_line_patch_newline_at_eof_marker(self) -> None:
        r"""'\\ No newline at end of file' markers are handled gracefully."""
        hunk = self._make_hunk(1, 1, 1, 1, ["+last_line", "\\ No newline at end of file\n"])
        header = ["--- a/f.py\n", "+++ b/f.py\n"]
        # Range covers line 1 (the + line)
        patch = _build_line_reverse_patch(header, [hunk], [(1, 1)])
        assert patch != ""
        assert "+last_line" in patch

    def test_build_line_patch_multiple_hunks_partial_selection(self) -> None:
        """With two hunks, only the hunk containing selected lines is emitted."""
        hunk0 = self._make_hunk(1, 1, 1, 2, [" ctx1\n", "+add0\n"])  # +add0 at HEAD line 2
        hunk1 = self._make_hunk(20, 1, 20, 2, [" ctx2\n", "+add1\n"])  # +add1 at HEAD line 21
        header = ["--- a/f.py\n", "+++ b/f.py\n"]

        # Select only add0 (line 2)
        patch = _build_line_reverse_patch(header, [hunk0, hunk1], [(2, 2)])

        assert "+add0\n" in patch
        # add1 is in hunk1 which is not selected → hunk1 should not appear
        assert "+add1\n" not in patch
