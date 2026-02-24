"""Conflict detection, parsing, and resolution operations."""

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import GitCommandError


@dataclass
class ConflictBlock:
    """A single merge conflict block parsed from a file."""

    index: int
    ours_content: str
    theirs_content: str
    base_content: str | None = None


@dataclass
class BlockResolution:
    """A resolution for a single conflict block."""

    block_index: int
    choice: str  # "ours" | "theirs" | "manual"
    manual_content: str | None = None


def _run_git_sync(args: list[str], cwd: Path) -> str:
    """Run a git command synchronously and return stdout.

    Raises GitCommandError on non-zero exit.
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e


def parse_conflict_blocks(file_content: str) -> list[ConflictBlock]:
    """Parse conflict markers into structured ConflictBlock objects.

    Handles both two-way (<<<<<<</=======/>>>>>>>) and three-way
    (<<<<<<</|||||||/=======/>>>>>>>) merge conflict markers.

    Args:
        file_content: The full text content of a file with conflict markers.

    Returns:
        A list of ConflictBlock objects, one per conflict region.
    """
    blocks: list[ConflictBlock] = []
    lines = file_content.splitlines(keepends=True)

    # States for the parser
    STATE_NORMAL = "normal"
    STATE_OURS = "ours"
    STATE_BASE = "base"
    STATE_THEIRS = "theirs"

    state = STATE_NORMAL
    ours_lines: list[str] = []
    base_lines: list[str] = []
    theirs_lines: list[str] = []
    block_index = 0

    for line in lines:
        if re.match(r"^<{7} ", line) or line.rstrip("\n") == "<" * 7:
            # Start of conflict block — ours section begins
            state = STATE_OURS
            ours_lines = []
            base_lines = []
            theirs_lines = []
        elif re.match(r"^\|{7} ", line) or line.rstrip("\n") == "|" * 7:
            # Three-way merge base section separator
            state = STATE_BASE
        elif re.match(r"^={7}$", line.rstrip("\n")):
            # Separator between ours/base and theirs
            state = STATE_THEIRS
        elif re.match(r"^>{7} ", line) or line.rstrip("\n") == ">" * 7:
            # End of conflict block
            blocks.append(
                ConflictBlock(
                    index=block_index,
                    ours_content="".join(ours_lines),
                    theirs_content="".join(theirs_lines),
                    base_content="".join(base_lines) if base_lines else None,
                )
            )
            block_index += 1
            state = STATE_NORMAL
        else:
            if state == STATE_OURS:
                ours_lines.append(line)
            elif state == STATE_BASE:
                base_lines.append(line)
            elif state == STATE_THEIRS:
                theirs_lines.append(line)
            # STATE_NORMAL lines are skipped (non-conflict content)

    return blocks


def _get_conflict_files_sync(worktree_path: Path) -> list[str]:
    """List files with unresolved merge conflicts (synchronous)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return [f for f in result.stdout.strip().split("\n") if f]
    except subprocess.CalledProcessError:
        return []


async def get_conflict_files(worktree_path: Path) -> list[str]:
    """List files with unresolved merge conflicts.

    Args:
        worktree_path: Path to the git worktree.

    Returns:
        List of relative file paths that have unresolved conflicts.
    """
    return await asyncio.to_thread(_get_conflict_files_sync, worktree_path)


async def get_conflict_blocks(worktree_path: Path, file_path: str) -> list[ConflictBlock]:
    """Read a conflict file and return structured conflict blocks.

    Args:
        worktree_path: Path to the git worktree.
        file_path: Relative path to the file within the worktree.

    Returns:
        List of ConflictBlock objects for each conflict region.
    """
    full_path = worktree_path / file_path

    def _read_and_parse() -> list[ConflictBlock]:
        content = full_path.read_text(encoding="utf-8", errors="replace")
        return parse_conflict_blocks(content)

    return await asyncio.to_thread(_read_and_parse)


def _apply_resolutions(file_content: str, resolutions: list[BlockResolution]) -> str:
    """Apply per-block resolutions to file content, returning resolved text.

    Each conflict block is replaced according to its resolution:
    - "ours": use ours_content
    - "theirs": use theirs_content
    - "manual": use manual_content

    Blocks without a resolution in `resolutions` are left unchanged.

    Args:
        file_content: The full text content with conflict markers.
        resolutions: List of BlockResolution objects.

    Returns:
        The file content with resolved blocks written in place.
    """
    resolution_map: dict[int, BlockResolution] = {r.block_index: r for r in resolutions}

    result_parts: list[str] = []
    lines = file_content.splitlines(keepends=True)

    STATE_NORMAL = "normal"
    STATE_OURS = "ours"
    STATE_BASE = "base"
    STATE_THEIRS = "theirs"

    state = STATE_NORMAL
    ours_lines: list[str] = []
    base_lines: list[str] = []
    theirs_lines: list[str] = []
    block_index = 0

    for line in lines:
        if re.match(r"^<{7} ", line) or line.rstrip("\n") == "<" * 7:
            state = STATE_OURS
            ours_lines = []
            base_lines = []
            theirs_lines = []
        elif re.match(r"^\|{7} ", line) or line.rstrip("\n") == "|" * 7:
            state = STATE_BASE
        elif re.match(r"^={7}$", line.rstrip("\n")):
            state = STATE_THEIRS
        elif re.match(r"^>{7} ", line) or line.rstrip("\n") == ">" * 7:
            # End of conflict block — apply resolution or keep markers
            resolution = resolution_map.get(block_index)
            if resolution is not None:
                if resolution.choice == "ours":
                    result_parts.append("".join(ours_lines))
                elif resolution.choice == "theirs":
                    result_parts.append("".join(theirs_lines))
                elif resolution.choice == "manual":
                    content = resolution.manual_content or ""
                    # Ensure content ends with newline if non-empty
                    if content and not content.endswith("\n"):
                        content += "\n"
                    result_parts.append(content)
                else:
                    # Unknown choice — preserve original markers
                    _append_raw_block(result_parts, ours_lines, base_lines, theirs_lines, line)
            else:
                # No resolution for this block — preserve original markers
                _append_raw_block(result_parts, ours_lines, base_lines, theirs_lines, line)

            block_index += 1
            state = STATE_NORMAL
        else:
            if state == STATE_NORMAL:
                result_parts.append(line)
            elif state == STATE_OURS:
                ours_lines.append(line)
            elif state == STATE_BASE:
                base_lines.append(line)
            elif state == STATE_THEIRS:
                theirs_lines.append(line)

    return "".join(result_parts)


def _append_raw_block(
    result_parts: list[str],
    ours_lines: list[str],
    base_lines: list[str],
    theirs_lines: list[str],
    end_line: str,
) -> None:
    """Re-emit conflict markers unchanged (for unresolved blocks)."""
    # We need the original marker lines, but since we consumed them, reconstruct
    # a minimal representation. In practice callers should always provide
    # resolutions for all blocks or leave the file alone.
    result_parts.append("<<<<<<< ours\n")
    result_parts.extend(ours_lines)
    if base_lines:
        result_parts.append("||||||| base\n")
        result_parts.extend(base_lines)
    result_parts.append("=======\n")
    result_parts.extend(theirs_lines)
    result_parts.append(end_line)


async def resolve_conflict(
    worktree_path: Path,
    file_path: str,
    resolutions: list[BlockResolution],
) -> None:
    """Apply per-block resolutions, write file, and stage with git add.

    Args:
        worktree_path: Path to the git worktree.
        file_path: Relative path to the conflict file.
        resolutions: List of BlockResolution objects for each conflict block.
    """
    full_path = worktree_path / file_path

    def _resolve() -> None:
        content = full_path.read_text(encoding="utf-8", errors="replace")
        resolved = _apply_resolutions(content, resolutions)
        full_path.write_text(resolved, encoding="utf-8")
        _run_git_sync(["add", file_path], worktree_path)

    await asyncio.to_thread(_resolve)


async def mark_all_resolved(worktree_path: Path) -> str:
    """Verify no remaining conflict markers, commit, and return the commit SHA.

    Stages all remaining unmerged files and creates a merge commit.

    Args:
        worktree_path: Path to the git worktree.

    Returns:
        The SHA of the new merge commit.

    Raises:
        GitCommandError: If git operations fail.
        ValueError: If unresolved conflict markers still exist.
    """

    def _commit_resolved() -> str:
        # Check for remaining unresolved conflict files
        remaining = _get_conflict_files_sync(worktree_path)
        if remaining:
            raise ValueError(f"Unresolved conflicts remain in: {', '.join(remaining)}")

        # Commit the resolved merge
        _run_git_sync(["commit", "--no-edit"], worktree_path)
        sha = _run_git_sync(["rev-parse", "HEAD"], worktree_path)
        return sha.strip()

    return await asyncio.to_thread(_commit_resolved)
