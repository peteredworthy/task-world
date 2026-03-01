"""Unit tests for conflict_ops: parsing and resolution logic."""

from orchestrator.git.conflict_ops import (
    BlockResolution,
    _apply_resolutions,
    parse_conflict_blocks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_CONFLICT = """\
line before
<<<<<<< HEAD
ours content
=======
theirs content
>>>>>>> feature-branch
line after
"""

THREE_WAY_CONFLICT = """\
<<<<<<< HEAD
ours content
||||||| base-branch
base content
=======
theirs content
>>>>>>> feature-branch
"""

MULTI_BLOCK_CONFLICT = """\
first line
<<<<<<< HEAD
block 0 ours
=======
block 0 theirs
>>>>>>> branch
middle line
<<<<<<< HEAD
block 1 ours
=======
block 1 theirs
>>>>>>> branch
last line
"""


# ---------------------------------------------------------------------------
# parse_conflict_blocks tests
# ---------------------------------------------------------------------------


class TestParseConflictBlocksSimple:
    def test_returns_one_block(self) -> None:
        blocks = parse_conflict_blocks(SIMPLE_CONFLICT)
        assert len(blocks) == 1

    def test_block_index_zero(self) -> None:
        blocks = parse_conflict_blocks(SIMPLE_CONFLICT)
        assert blocks[0].index == 0

    def test_ours_content(self) -> None:
        blocks = parse_conflict_blocks(SIMPLE_CONFLICT)
        assert blocks[0].ours_content == "ours content\n"

    def test_theirs_content(self) -> None:
        blocks = parse_conflict_blocks(SIMPLE_CONFLICT)
        assert blocks[0].theirs_content == "theirs content\n"

    def test_base_content_is_none(self) -> None:
        blocks = parse_conflict_blocks(SIMPLE_CONFLICT)
        assert blocks[0].base_content is None


class TestParseConflictBlocksThreeWay:
    def test_returns_one_block(self) -> None:
        blocks = parse_conflict_blocks(THREE_WAY_CONFLICT)
        assert len(blocks) == 1

    def test_ours_content(self) -> None:
        blocks = parse_conflict_blocks(THREE_WAY_CONFLICT)
        assert blocks[0].ours_content == "ours content\n"

    def test_theirs_content(self) -> None:
        blocks = parse_conflict_blocks(THREE_WAY_CONFLICT)
        assert blocks[0].theirs_content == "theirs content\n"

    def test_base_content(self) -> None:
        blocks = parse_conflict_blocks(THREE_WAY_CONFLICT)
        assert blocks[0].base_content == "base content\n"


class TestParseMultipleBlocks:
    def test_returns_two_blocks(self) -> None:
        blocks = parse_conflict_blocks(MULTI_BLOCK_CONFLICT)
        assert len(blocks) == 2

    def test_indices_are_sequential(self) -> None:
        blocks = parse_conflict_blocks(MULTI_BLOCK_CONFLICT)
        assert blocks[0].index == 0
        assert blocks[1].index == 1

    def test_first_block_ours(self) -> None:
        blocks = parse_conflict_blocks(MULTI_BLOCK_CONFLICT)
        assert blocks[0].ours_content == "block 0 ours\n"

    def test_second_block_theirs(self) -> None:
        blocks = parse_conflict_blocks(MULTI_BLOCK_CONFLICT)
        assert blocks[1].theirs_content == "block 1 theirs\n"

    def test_no_conflict_returns_empty(self) -> None:
        blocks = parse_conflict_blocks("no conflicts here\n")
        assert blocks == []

    def test_empty_string_returns_empty(self) -> None:
        blocks = parse_conflict_blocks("")
        assert blocks == []


# ---------------------------------------------------------------------------
# _apply_resolutions (resolution logic) tests
# ---------------------------------------------------------------------------


class TestResolveOursRemovesMarkers:
    def test_ours_content_written(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="ours")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "ours content" in result

    def test_markers_removed(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="ours")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "<<<<<<" not in result
        assert "=======" not in result
        assert ">>>>>>>" not in result

    def test_theirs_content_absent(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="ours")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "theirs content" not in result

    def test_surrounding_lines_preserved(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="ours")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "line before\n" in result
        assert "line after\n" in result


class TestResolveTheirsRemovesMarkers:
    def test_theirs_content_written(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="theirs")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "theirs content" in result

    def test_markers_removed(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="theirs")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "<<<<<<" not in result
        assert ">>>>>>>" not in result

    def test_ours_content_absent(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="theirs")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "ours content" not in result


class TestResolveManualWritesCustomContent:
    def test_manual_content_written(self) -> None:
        resolutions = [
            BlockResolution(block_index=0, choice="manual", manual_content="custom content\n")
        ]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "custom content" in result

    def test_markers_removed(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="manual", manual_content="custom\n")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "<<<<<<" not in result
        assert ">>>>>>>" not in result

    def test_neither_ours_nor_theirs_present(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="manual", manual_content="custom\n")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "ours content" not in result
        assert "theirs content" not in result

    def test_empty_manual_content_writes_empty(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="manual", manual_content="")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "ours content" not in result
        assert "theirs content" not in result

    def test_newline_appended_if_missing(self) -> None:
        resolutions = [BlockResolution(block_index=0, choice="manual", manual_content="no newline")]
        result = _apply_resolutions(SIMPLE_CONFLICT, resolutions)
        assert "no newline\n" in result


class TestResolveMultipleBlocks:
    def test_resolve_first_ours_second_theirs(self) -> None:
        resolutions = [
            BlockResolution(block_index=0, choice="ours"),
            BlockResolution(block_index=1, choice="theirs"),
        ]
        result = _apply_resolutions(MULTI_BLOCK_CONFLICT, resolutions)
        assert "block 0 ours" in result
        assert "block 1 theirs" in result
        assert "block 0 theirs" not in result
        assert "block 1 ours" not in result
        assert "<<<<<<" not in result

    def test_surrounding_content_preserved(self) -> None:
        resolutions = [
            BlockResolution(block_index=0, choice="ours"),
            BlockResolution(block_index=1, choice="ours"),
        ]
        result = _apply_resolutions(MULTI_BLOCK_CONFLICT, resolutions)
        assert "first line\n" in result
        assert "middle line\n" in result
        assert "last line\n" in result
