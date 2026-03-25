"""Prune operations: selectively remove changes from the run worktree.

Prune mode allows users to remove entire files, specific hunks, or individual
lines from the run branch before merging. Each prune operation creates a
dedicated commit on the run branch for auditability.

Supports three granularity levels:
- File-level: git checkout <base_sha> -- <file>
- Hunk-level: construct reverse patch for selected hunks, apply via git apply --reverse
- Line-level: construct selective reverse patch for specific line ranges
"""

import asyncio
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.git.errors import GitCommandError

# Regex to parse unified diff @@ hunk headers.
# Matches: @@ -old_start[,old_count] +new_start[,new_count] @@ [suffix]
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)")


def _run_git_sync(args: list[str], cwd: Path) -> str:
    """Run a git command synchronously and return stdout.

    Raises GitCommandError on non-zero exit.
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e


@dataclass
class FileDiffSection:
    """A per-file section extracted from a unified diff."""

    path: str
    content: str  # Full diff text including the "diff --git..." header line
    hunks: int
    lines_changed: int


@dataclass
class PruneStats:
    """Statistics and resulting diff for a prune operation."""

    resulting_diff: str
    files_affected: int
    hunks_removed: int
    lines_removed: int


@dataclass
class Hunk:
    """A single hunk parsed from a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header_suffix: str  # Text after the closing @@ on the header line
    lines: list[str] = field(default_factory=list[str])  # Content lines with prefix (+/-/ )


def _parse_diff_sections(diff_text: str) -> list[FileDiffSection]:
    """Parse a unified diff into per-file sections.

    Each section starts with a "diff --git a/... b/..." line and includes
    all subsequent lines until the next "diff --git" header.
    """
    sections: list[FileDiffSection] = []
    if not diff_text.strip():
        return sections

    lines = diff_text.splitlines(keepends=True)
    current_path: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_path is None:
            return
        content = "".join(current_lines)
        hunks = sum(1 for ln in content.splitlines() if ln.startswith("@@"))
        changed = sum(
            1
            for ln in content.splitlines()
            if (ln.startswith("+") and not ln.startswith("+++"))
            or (ln.startswith("-") and not ln.startswith("---"))
        )
        sections.append(
            FileDiffSection(path=current_path, content=content, hunks=hunks, lines_changed=changed)
        )

    for line in lines:
        if line.startswith("diff --git "):
            _flush()
            current_lines = [line]
            # Extract "b/..." path: "diff --git a/foo.py b/foo.py"
            b_part = line.rstrip().split(" b/", 1)
            current_path = b_part[1] if len(b_part) == 2 else None
        elif current_path is not None:
            current_lines.append(line)

    _flush()
    return sections


# ---------------------------------------------------------------------------
# Hunk-level and line-level patch helpers
# ---------------------------------------------------------------------------


def _parse_hunk_header(header: str) -> tuple[int, int, int, int, str]:
    """Parse ``@@ -old_start[,old_count] +new_start[,new_count] @@ [suffix]``.

    Returns ``(old_start, old_count, new_start, new_count, suffix)``.
    When the count part is absent the count defaults to 1 per the unified diff spec.
    """
    m = _HUNK_HEADER_RE.match(header.rstrip("\n"))
    if not m:
        raise ValueError(f"Invalid hunk header: {header!r}")
    old_start = int(m.group(1))
    old_count = int(m.group(2)) if m.group(2) is not None else 1
    new_start = int(m.group(3))
    new_count = int(m.group(4)) if m.group(4) is not None else 1
    return old_start, old_count, new_start, new_count, m.group(5)


def _format_hunk_header(
    old_start: int, old_count: int, new_start: int, new_count: int, suffix: str = ""
) -> str:
    """Format a unified-diff hunk header line."""
    return f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}\n"


def _parse_file_diff_hunks(diff_section: str) -> tuple[list[str], list[Hunk]]:
    """Parse a single-file diff section into file header lines and a list of Hunk objects.

    Args:
        diff_section: The complete diff text for one file (as returned by
            ``_parse_diff_sections``), including the ``diff --git`` header.

    Returns:
        ``(header_lines, hunks)`` where *header_lines* is everything before the
        first ``@@`` marker and *hunks* is the ordered list of parsed hunks.
    """
    lines = diff_section.splitlines(keepends=True)
    header_lines: list[str] = []
    hunks: list[Hunk] = []
    current_hunk: Hunk | None = None

    for line in lines:
        if line.startswith("@@"):
            old_start, old_count, new_start, new_count, suffix = _parse_hunk_header(line)
            current_hunk = Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                header_suffix=suffix,
                lines=[],
            )
            hunks.append(current_hunk)
        elif current_hunk is not None:
            current_hunk.lines.append(line)
        else:
            header_lines.append(line)

    return header_lines, hunks


def _build_hunk_reverse_patch(
    header_lines: list[str], hunks: list[Hunk], hunk_indices: list[int]
) -> str:
    """Build a patch containing only the specified hunks (0-based indices).

    The returned patch string is in the forward direction (base → HEAD) and is
    intended to be applied via ``git apply --reverse`` to selectively undo only
    the selected hunks while leaving other hunks untouched.

    Returns an empty string if no valid indices are provided or all indices are
    out of range.
    """
    selected = [hunks[i] for i in sorted(set(hunk_indices)) if 0 <= i < len(hunks)]
    if not selected:
        return ""

    parts: list[str] = list(header_lines)
    for hunk in selected:
        parts.append(
            _format_hunk_header(
                hunk.old_start,
                hunk.old_count,
                hunk.new_start,
                hunk.new_count,
                hunk.header_suffix,
            )
        )
        parts.extend(hunk.lines)
    return "".join(parts)


def _build_line_reverse_patch(
    header_lines: list[str],
    hunks: list[Hunk],
    line_ranges: list[tuple[int, int]],
) -> str:
    """Build a selective reverse patch for specific line numbers in the HEAD file.

    For each hunk, ``+`` lines whose HEAD-file line number falls within any of
    the *line_ranges* (inclusive) are kept as ``+`` lines in the output patch.
    Other ``+`` lines are converted to context (they remain in the file).
    ``-`` lines are skipped entirely (line-level prune does not restore
    deletions — only removes unwanted additions).

    The resulting patch is in the forward direction and should be applied via
    ``git apply --reverse``.  Hunk headers are recalculated to reflect only the
    selected changes.

    Args:
        header_lines: File-level diff header (``diff --git``, ``---``, ``+++``).
        hunks: Parsed hunks from the file's diff section.
        line_ranges: ``(start, end)`` pairs specifying 1-based HEAD-file line
            numbers to prune (inclusive).

    Returns:
        The patch text, or an empty string if no lines are selected.
    """

    def _in_range(n: int) -> bool:
        return any(s <= n <= e for s, e in line_ranges)

    patch_hunk_parts: list[str] = []

    for hunk in hunks:
        head_line = hunk.new_start
        modified: list[str] = []
        context_count = 0  # context lines + non-selected + lines (converted)
        selected_count = 0  # selected + lines to be reversed

        for line in hunk.lines:
            if not line:
                continue
            # "\ No newline at end of file" — attach to preceding line, no counter change
            if line.startswith("\\"):
                if modified:
                    modified.append(line)
                continue

            prefix = line[0]

            if prefix == " ":
                # Context line: keep as-is
                modified.append(line)
                context_count += 1
                head_line += 1
            elif prefix == "+":
                if _in_range(head_line):
                    # Selected: keep as + (will be deleted when patch is reversed)
                    modified.append(line)
                    selected_count += 1
                else:
                    # Not selected: convert to context so it stays in the file
                    modified.append(" " + line[1:])
                    context_count += 1
                head_line += 1
            elif prefix == "-":
                # Deletion: skip — we are not reverting deletions in line mode.
                # The line is absent from the current HEAD file so including it
                # as context would cause the patch to fail.
                pass

        if selected_count == 0:
            # Nothing selected in this hunk — omit it from the patch
            continue

        # Recalculate header counts for the modified hunk.
        # new_count = lines we expect to find in HEAD (context + selected+)
        # old_count = lines that remain after reversal (context only)
        new_count = context_count + selected_count
        old_count = context_count
        # Use new_start for both sides; git's context matching handles the rest.
        header = _format_hunk_header(
            hunk.new_start, old_count, hunk.new_start, new_count, hunk.header_suffix
        )
        patch_hunk_parts.append(header + "".join(modified))

    if not patch_hunk_parts:
        return ""

    return "".join(header_lines) + "".join(patch_hunk_parts)


def _apply_reverse_patch_sync(worktree_path: Path, patch_text: str) -> None:
    """Apply a unified-diff patch in reverse, also staging the result.

    Runs ``git apply --reverse --index`` with the patch fed via stdin.  The
    ``--index`` flag stages the change so that a subsequent ``git commit`` picks
    it up without a separate ``git add``.

    Raises:
        GitCommandError: If ``git apply`` exits non-zero (patch does not apply).
    """
    cmd = ["git", "apply", "--reverse", "--index"]
    result = subprocess.run(
        cmd,
        cwd=worktree_path,
        input=patch_text,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitCommandError(" ".join(cmd), result.returncode, result.stderr)


def _count_selected_hunk_lines(hunks: list[Hunk], indices: list[int]) -> int:
    """Count the number of changed lines (+/-) in the selected hunks."""
    total = 0
    for i in indices:
        if 0 <= i < len(hunks):
            for line in hunks[i].lines:
                if line and not line.startswith("\\") and line[0] in ("+", "-"):
                    total += 1
    return total


def _count_selected_range_lines(
    hunks: list[Hunk], line_ranges: list[tuple[int, int]]
) -> tuple[int, int]:
    """Count lines and affected hunks for the given HEAD-file line ranges.

    Returns ``(lines_removed, hunks_affected)`` where *hunks_affected* is the
    number of hunks that contain at least one selected line.
    """

    def _in_range(n: int) -> bool:
        return any(s <= n <= e for s, e in line_ranges)

    lines_removed = 0
    hunks_affected = 0

    for hunk in hunks:
        head_line = hunk.new_start
        hunk_has_selection = False
        for line in hunk.lines:
            if not line or line.startswith("\\"):
                continue
            prefix = line[0]
            if prefix == "+":
                if _in_range(head_line):
                    lines_removed += 1
                    hunk_has_selection = True
                head_line += 1
            elif prefix == " ":
                head_line += 1
        if hunk_has_selection:
            hunks_affected += 1

    return lines_removed, hunks_affected


def _get_file_diff_sync(worktree_path: Path, file_path: str, base_sha: str) -> str:
    """Return the unified diff for a single file relative to base_sha."""
    return _run_git_sync(
        ["diff", f"{base_sha}..HEAD", "--", file_path],
        cwd=worktree_path,
    )


def _prune_hunks_sync(
    worktree_path: Path,
    file_path: str,
    base_sha: str,
    hunk_indices: list[int],
    message: str,
) -> tuple[str, PruneStats]:
    """Apply hunk-level prune and create a commit.

    Extracts the specified hunks from the current diff, builds a forward patch
    containing only those hunks, and applies it in reverse via
    ``git apply --reverse``.  Creates a commit with the given message.

    Returns ``(commit_sha, PruneStats)``.
    """
    diff_text = _get_file_diff_sync(worktree_path, file_path, base_sha)
    if not diff_text.strip():
        raise GitCommandError("git diff", 0, f"No diff for file '{file_path}' relative to base")

    sections = _parse_diff_sections(diff_text)
    if not sections:
        raise GitCommandError("git diff", 0, f"No diff sections found for '{file_path}'")

    header_lines, hunks = _parse_file_diff_hunks(sections[0].content)
    if not hunks:
        raise GitCommandError("parse diff", 0, f"No hunks found in diff for '{file_path}'")

    patch = _build_hunk_reverse_patch(header_lines, hunks, hunk_indices)
    if not patch:
        raise GitCommandError("build patch", 0, "No valid hunk indices provided")

    valid_indices = sorted({i for i in hunk_indices if 0 <= i < len(hunks)})
    lines_removed = _count_selected_hunk_lines(hunks, valid_indices)

    _apply_reverse_patch_sync(worktree_path, patch)

    staged = _run_git_sync(["diff", "--cached", "--name-only"], cwd=worktree_path)
    if not staged.strip():
        raise GitCommandError(
            "git diff --cached",
            0,
            "Nothing staged after reverse patch — patch may have applied with no effect",
        )

    _run_git_sync(["commit", "-m", message], cwd=worktree_path)
    commit_sha = _run_git_sync(["rev-parse", "HEAD"], cwd=worktree_path).strip()

    resulting_diff = _run_git_sync(["diff", f"{base_sha}..HEAD"], cwd=worktree_path)

    return commit_sha, PruneStats(
        resulting_diff=resulting_diff,
        files_affected=1,
        hunks_removed=len(valid_indices),
        lines_removed=lines_removed,
    )


def _prune_lines_sync(
    worktree_path: Path,
    file_path: str,
    base_sha: str,
    line_ranges: list[tuple[int, int]],
    message: str,
) -> tuple[str, PruneStats]:
    """Apply line-level prune and create a commit.

    Builds a selective reverse patch that only touches the ``+`` lines within
    the requested HEAD-file line ranges and applies it via
    ``git apply --reverse``.  Creates a commit with the given message.

    Returns ``(commit_sha, PruneStats)``.
    """
    diff_text = _get_file_diff_sync(worktree_path, file_path, base_sha)
    if not diff_text.strip():
        raise GitCommandError("git diff", 0, f"No diff for file '{file_path}' relative to base")

    sections = _parse_diff_sections(diff_text)
    if not sections:
        raise GitCommandError("git diff", 0, f"No diff sections found for '{file_path}'")

    header_lines, hunks = _parse_file_diff_hunks(sections[0].content)
    if not hunks:
        raise GitCommandError("parse diff", 0, f"No hunks found in diff for '{file_path}'")

    patch = _build_line_reverse_patch(header_lines, hunks, line_ranges)
    if not patch:
        raise GitCommandError(
            "build patch", 0, "No lines within the specified ranges found in diff"
        )

    lines_removed, hunks_affected = _count_selected_range_lines(hunks, line_ranges)

    _apply_reverse_patch_sync(worktree_path, patch)

    staged = _run_git_sync(["diff", "--cached", "--name-only"], cwd=worktree_path)
    if not staged.strip():
        raise GitCommandError(
            "git diff --cached",
            0,
            "Nothing staged after reverse patch — patch may have applied with no effect",
        )

    _run_git_sync(["commit", "-m", message], cwd=worktree_path)
    commit_sha = _run_git_sync(["rev-parse", "HEAD"], cwd=worktree_path).strip()

    resulting_diff = _run_git_sync(["diff", f"{base_sha}..HEAD"], cwd=worktree_path)

    return commit_sha, PruneStats(
        resulting_diff=resulting_diff,
        files_affected=1,
        hunks_removed=hunks_affected,
        lines_removed=lines_removed,
    )


def _file_exists_at_ref(worktree_path: Path, ref: str, file_path: str) -> bool:
    """Return True if file_path exists at the given git ref."""
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{file_path}"],
        cwd=worktree_path,
        capture_output=True,
    )
    return result.returncode == 0


def _stage_file_revert(worktree_path: Path, file_path: str, base_sha: str) -> None:
    """Stage a file revert: restore to base state or remove if newly added.

    After this call the change is staged (in the index) ready for commit.
    """
    if _file_exists_at_ref(worktree_path, base_sha, file_path):
        # File exists at base — restore working tree + index to that state
        _run_git_sync(["checkout", base_sha, "--", file_path], cwd=worktree_path)
    else:
        # File was newly added on the run branch — stage its removal
        _run_git_sync(["rm", "-f", "--", file_path], cwd=worktree_path)


def _compute_prune_preview(
    worktree_path: Path,
    file_paths: set[str],
    base_sha: str,
) -> PruneStats:
    """Compute what the diff would look like after pruning the given files.

    Pure read operation — does not modify the worktree.
    """
    diff_text = _run_git_sync(["diff", f"{base_sha}..HEAD"], cwd=worktree_path)
    sections = _parse_diff_sections(diff_text)

    files_affected = 0
    hunks_removed = 0
    lines_removed = 0
    kept: list[FileDiffSection] = []

    for sec in sections:
        if sec.path in file_paths:
            files_affected += 1
            hunks_removed += sec.hunks
            lines_removed += sec.lines_changed
        else:
            kept.append(sec)

    resulting_diff = "".join(s.content for s in kept)
    return PruneStats(
        resulting_diff=resulting_diff,
        files_affected=files_affected,
        hunks_removed=hunks_removed,
        lines_removed=lines_removed,
    )


def _revert_file_sync(worktree_path: Path, file_path: str, base_sha: str) -> str:
    """Revert a single file to base state and create a commit.

    Returns the commit SHA of the new prune commit.
    """
    _stage_file_revert(worktree_path, file_path, base_sha)

    # Verify something was actually staged
    staged = _run_git_sync(["diff", "--cached", "--name-only"], cwd=worktree_path)
    if not staged.strip():
        raise GitCommandError(
            "git diff --cached",
            0,
            f"File '{file_path}' already matches base state — nothing to revert",
        )

    _run_git_sync(
        ["commit", "-m", f"prune: revert {file_path} to base state"],
        cwd=worktree_path,
    )
    return _run_git_sync(["rev-parse", "HEAD"], cwd=worktree_path).strip()


def _apply_prune_sync(
    worktree_path: Path,
    file_paths: set[str],
    base_sha: str,
    message: str,
) -> tuple[str, PruneStats]:
    """Apply file-level prune and create a commit.

    Returns (commit_sha, PruneStats) where PruneStats reflects what was removed.
    """
    # Compute stats based on current diff before applying changes
    stats = _compute_prune_preview(worktree_path, file_paths, base_sha)

    # Stage reverts for all selected files
    for file_path in sorted(file_paths):
        _stage_file_revert(worktree_path, file_path, base_sha)

    # Verify something was actually staged
    staged = _run_git_sync(["diff", "--cached", "--name-only"], cwd=worktree_path)
    if not staged.strip():
        raise GitCommandError(
            "git diff --cached",
            0,
            "No changes staged for prune commit — selected files already match base state",
        )

    _run_git_sync(["commit", "-m", message], cwd=worktree_path)
    commit_sha = _run_git_sync(["rev-parse", "HEAD"], cwd=worktree_path).strip()

    return commit_sha, stats


async def revert_file(worktree_path: Path, file_path: str, base_sha: str) -> str:
    """Revert a single file to its base-branch state and create a commit.

    Uses ``git checkout <base_sha> -- <file>`` to restore the file, then
    commits the result. If the file was newly added on the run branch (not
    present at ``base_sha``), it is removed instead.

    Args:
        worktree_path: Path to the git worktree.
        file_path: Path of the file to revert, relative to the worktree root.
        base_sha: The base commit SHA to revert the file to.

    Returns:
        The SHA of the newly created prune commit.

    Raises:
        GitCommandError: If the git operation fails or the file already matches
            the base state.
    """
    return await asyncio.to_thread(_revert_file_sync, worktree_path, file_path, base_sha)


async def preview_prune(
    worktree_path: Path,
    file_paths: list[str],
    base_sha: str,
) -> PruneStats:
    """Preview the result of a file-level prune without modifying the worktree.

    Computes the diff that would remain after reverting the specified files to
    their base state, along with counts of files, hunks, and lines that would
    be removed.  This is a read-only operation.

    Args:
        worktree_path: Path to the git worktree.
        file_paths: File paths (relative to worktree root) to prune.
        base_sha: The base commit SHA for diff computation.

    Returns:
        PruneStats containing the resulting diff and removal counts.
    """
    return await asyncio.to_thread(_compute_prune_preview, worktree_path, set(file_paths), base_sha)


async def apply_prune(
    worktree_path: Path,
    file_paths: list[str],
    base_sha: str,
    message: str = "prune: remove selected changes",
) -> tuple[str, PruneStats]:
    """Apply file-level prune selections and create a commit on the run branch.

    For each specified file, restores it to its state at ``base_sha`` (or
    removes it if it was newly added).  All changes are committed together
    in a single prune commit.

    Args:
        worktree_path: Path to the git worktree.
        file_paths: File paths (relative to worktree root) to prune.
        base_sha: The base commit SHA for computing reverts.
        message: Commit message for the prune commit.

    Returns:
        Tuple of ``(commit_sha, PruneStats)`` where ``commit_sha`` is the SHA
        of the newly created commit and ``PruneStats`` describes what was
        removed.

    Raises:
        GitCommandError: If the git operation fails or nothing changed.
    """
    return await asyncio.to_thread(
        _apply_prune_sync, worktree_path, set(file_paths), base_sha, message
    )


async def prune_hunks(
    worktree_path: Path,
    file_path: str,
    base_sha: str,
    hunk_indices: list[int],
    message: str = "prune: remove selected hunks",
) -> tuple[str, PruneStats]:
    """Prune specific hunks from a file and create a commit on the run branch.

    Extracts the selected hunks (identified by 0-based index in the file's
    current diff) from the diff and applies them in reverse via
    ``git apply --reverse``.  All other hunks in the file are left untouched.

    Args:
        worktree_path: Path to the git worktree.
        file_path: File path (relative to worktree root) whose hunks to prune.
        base_sha: The base commit SHA used for diff computation.
        hunk_indices: 0-based indices of the hunks to remove.
        message: Commit message for the prune commit.

    Returns:
        Tuple of ``(commit_sha, PruneStats)``.

    Raises:
        GitCommandError: If the diff cannot be obtained, the patch cannot be
            built, or ``git apply --reverse`` fails.
    """
    return await asyncio.to_thread(
        _prune_hunks_sync, worktree_path, file_path, base_sha, hunk_indices, message
    )


@dataclass
class FileSelectionEntry:
    """Input descriptor for a single file's prune selection."""

    path: str
    mode: str  # "file" | "hunk" | "line"
    hunk_indices: list[int] | None = None
    line_ranges: list[tuple[int, int]] | None = None


def _compute_mixed_preview(
    worktree_path: Path,
    selections: list[FileSelectionEntry],
    base_sha: str,
) -> PruneStats:
    """Compute preview stats for a mixed file/hunk/line selection.

    Read-only: does not modify the worktree.  For file-level selections the
    ``resulting_diff`` accurately reflects what would remain; for hunk/line
    selections only the statistics are computed (the resulting diff still
    shows the full current diff minus any file-level removals).
    """
    diff_text = _run_git_sync(["diff", f"{base_sha}..HEAD"], cwd=worktree_path)
    sections = _parse_diff_sections(diff_text)
    sections_by_path = {s.path: s for s in sections}

    file_prune_paths: set[str] = set()
    total_files_affected = 0
    total_hunks_removed = 0
    total_lines_removed = 0

    for entry in selections:
        if entry.mode == "file":
            file_prune_paths.add(entry.path)
            if entry.path in sections_by_path:
                sec = sections_by_path[entry.path]
                total_files_affected += 1
                total_hunks_removed += sec.hunks
                total_lines_removed += sec.lines_changed
        elif entry.mode == "hunk" and entry.hunk_indices:
            if entry.path in sections_by_path:
                sec = sections_by_path[entry.path]
                _header, hunks = _parse_file_diff_hunks(sec.content)
                valid_indices = [i for i in entry.hunk_indices if 0 <= i < len(hunks)]
                if valid_indices:
                    total_files_affected += 1
                    total_hunks_removed += len(valid_indices)
                    total_lines_removed += _count_selected_hunk_lines(hunks, valid_indices)
        elif entry.mode == "line" and entry.line_ranges:
            if entry.path in sections_by_path:
                sec = sections_by_path[entry.path]
                _header, hunks = _parse_file_diff_hunks(sec.content)
                lines_removed, hunks_affected = _count_selected_range_lines(
                    hunks, entry.line_ranges
                )
                if lines_removed > 0:
                    total_files_affected += 1
                    total_hunks_removed += hunks_affected
                    total_lines_removed += lines_removed

    kept_parts = [s.content for s in sections if s.path not in file_prune_paths]
    resulting_diff = "".join(kept_parts)

    return PruneStats(
        resulting_diff=resulting_diff,
        files_affected=total_files_affected,
        hunks_removed=total_hunks_removed,
        lines_removed=total_lines_removed,
    )


async def compute_selection_preview(
    worktree_path: Path,
    selections: list[FileSelectionEntry],
    base_sha: str,
) -> PruneStats:
    """Preview stats for a mixed file/hunk/line prune selection.

    Read-only: does not modify the worktree.

    Args:
        worktree_path: Path to the git worktree.
        selections: List of ``FileSelectionEntry`` describing what to prune.
        base_sha: The base commit SHA for diff computation.

    Returns:
        PruneStats with removal counts and resulting diff (file-level accurate).
    """
    return await asyncio.to_thread(_compute_mixed_preview, worktree_path, selections, base_sha)


async def prune_lines(
    worktree_path: Path,
    file_path: str,
    base_sha: str,
    line_ranges: list[tuple[int, int]],
    message: str = "prune: remove selected lines",
) -> tuple[str, PruneStats]:
    """Prune specific lines from a file and create a commit on the run branch.

    Constructs a selective reverse patch that only removes the ``+`` (added)
    lines whose 1-based HEAD-file line number falls within any of the specified
    *line_ranges*.  The patch is applied via ``git apply --reverse`` so
    surrounding lines and other hunks remain intact.

    Line-level prune only removes additions; it does not restore deleted lines.

    Args:
        worktree_path: Path to the git worktree.
        file_path: File path (relative to worktree root) to prune lines from.
        base_sha: The base commit SHA used for diff computation.
        line_ranges: List of ``(start, end)`` tuples with 1-based, inclusive
            HEAD-file line numbers to remove.
        message: Commit message for the prune commit.

    Returns:
        Tuple of ``(commit_sha, PruneStats)``.

    Raises:
        GitCommandError: If the diff cannot be obtained, no matching lines are
            found, or ``git apply --reverse`` fails.
    """
    return await asyncio.to_thread(
        _prune_lines_sync, worktree_path, file_path, base_sha, line_ranges, message
    )
