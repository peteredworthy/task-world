"""RED/GREEN coverage for durable JSONL journal segment rotation."""

from __future__ import annotations

import json
import asyncio
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.config import JournalConfig
from orchestrator.db import (
    JsonlOutboxObserver,
    RotationOperations,
    SystemRotationOperations,
    StoredEvent,
    discover_journal_segments,
)


def _event(position: int) -> StoredEvent:
    return StoredEvent(
        position=position,
        aggregate_id="run-1",
        event_type="run_status_changed",
        payload='{"run_id": "run-1"}',
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
        version=position,
    )


def _write_from_separate_process(path_string: str) -> None:
    asyncio.run(
        JsonlOutboxObserver(Path(path_string))([_event(position) for position in range(1, 21)])
    )


class RecordingRotationOperations:
    """Records each real durable rotation operation without replacing it."""

    def __init__(self, delegate: RotationOperations) -> None:
        self.operations: list[str] = []
        self._delegate = delegate

    def link(self, active: Path, archive: Path) -> None:
        self.operations.append("link")
        self._delegate.link(active, archive)

    def fsync_parent(self, path: Path) -> None:
        self.operations.append("fsync_parent")
        self._delegate.fsync_parent(path)

    def fsync_active(self, path: Path) -> None:
        self.operations.append("fsync_active")
        self._delegate.fsync_active(path)

    def unlink(self, active: Path) -> None:
        self.operations.append("unlink")
        self._delegate.unlink(active)


class FailFirstActiveSyncOperations(RecordingRotationOperations):
    """Delegates real operations but fails the first active-file sync."""

    def __init__(self, delegate: RotationOperations) -> None:
        super().__init__(delegate)
        self._fail_next_active_sync = True

    def fsync_active(self, path: Path) -> None:
        self.operations.append("fsync_active")
        if self._fail_next_active_sync:
            self._fail_next_active_sync = False
            raise OSError("injected active journal sync failure")
        self._delegate.fsync_active(path)


def test_journal_config_defaults_to_64_mebibytes() -> None:
    assert JournalConfig().max_bytes == 64 * 1024 * 1024


def test_journal_config_clamps_small_values_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        config = JournalConfig(max_bytes=1)

    assert config.max_bytes == 1024 * 1024
    assert "1 MiB" in caplog.text


def test_journal_config_does_not_turn_negative_values_positive() -> None:
    assert JournalConfig(max_bytes=-2 * 1024 * 1024).max_bytes == 1024 * 1024


async def test_rotation_archives_exact_position_range_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    observer = JsonlOutboxObserver(path, max_bytes=1)

    await observer([_event(10)])
    await observer([_event(11)])

    archive = tmp_path / "history.10-10.jsonl"
    assert archive.exists()
    assert [json.loads(line)["position"] for line in archive.read_text().splitlines()] == [10]
    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == [11]

    path.write_text(json.dumps({"position": 10}) + "\n")
    with pytest.raises(FileExistsError):
        await JsonlOutboxObserver(path, max_bytes=1)([_event(12)])
    assert [json.loads(line)["position"] for line in archive.read_text().splitlines()] == [10]


async def test_rotation_syncs_active_then_links_fsyncs_unlinks_and_fsyncs_parent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps({"position": 1}) + "\n")
    recorder = RecordingRotationOperations(SystemRotationOperations())

    await JsonlOutboxObserver(path, max_bytes=1, rotation_operations=recorder)([_event(2)])

    assert recorder.operations[:5] == [
        "fsync_active",
        "link",
        "fsync_parent",
        "unlink",
        "fsync_parent",
    ]


async def test_rotation_retry_syncs_before_link_and_preserves_single_event(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps({"position": 1}) + "\n")
    operations = FailFirstActiveSyncOperations(SystemRotationOperations())
    observer = JsonlOutboxObserver(path, max_bytes=1, rotation_operations=operations)

    with pytest.raises(OSError, match="injected active journal sync failure"):
        await observer([_event(1)])
    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == [1]
    assert not list(tmp_path.glob("history.*-*.jsonl"))

    await observer([_event(1)])

    assert operations.operations == [
        "fsync_active",
        "fsync_active",
        "link",
        "fsync_parent",
        "unlink",
        "fsync_parent",
    ]
    archive = tmp_path / "history.1-1.jsonl"
    assert [json.loads(line)["position"] for line in archive.read_text().splitlines()] == [1]
    assert not path.exists()


async def test_linked_rotation_recovery_syncs_before_and_after_unlink(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps({"position": 1}) + "\n")
    archive = tmp_path / "history.1-1.jsonl"
    archive.hardlink_to(path)
    recorder = RecordingRotationOperations(SystemRotationOperations())

    await JsonlOutboxObserver(path, rotation_operations=recorder)([])

    assert recorder.operations == ["fsync_parent", "unlink", "fsync_parent"]


async def test_duplicate_retry_syncs_existing_active_record_before_succeeding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    operations = FailFirstActiveSyncOperations(SystemRotationOperations())
    observer = JsonlOutboxObserver(path, rotation_operations=operations)

    with pytest.raises(OSError, match="injected active journal sync failure"):
        await observer([_event(1)])
    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == [1]

    await observer([_event(1)])

    assert operations.operations == ["fsync_active", "fsync_active", "fsync_parent"]
    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == [1]


async def test_restart_deduplicates_archived_positions_with_bounded_active_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    observer = JsonlOutboxObserver(path, max_bytes=1)
    await observer([_event(1)])
    await observer([_event(2)])

    restarted = JsonlOutboxObserver(path, max_bytes=1)
    await restarted([_event(1), _event(2), _event(3)])

    assert [segment.first_position for segment in discover_journal_segments(path)] == [1, 2]
    assert restarted._written == {3}


async def test_rotation_failure_propagates(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps({"position": 1}) + "\n")
    (tmp_path / "history.1-1.jsonl").mkdir()

    with pytest.raises(FileExistsError):
        await JsonlOutboxObserver(path, max_bytes=1)([_event(2)])


async def test_rotation_recovers_linked_active_file_before_appending(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps({"position": 1}) + "\n")
    archive = tmp_path / "history.1-1.jsonl"
    archive.hardlink_to(path)

    await JsonlOutboxObserver(path)([_event(2)])

    assert not path.samefile(archive)
    assert [json.loads(line)["position"] for line in archive.read_text().splitlines()] == [1]
    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == [2]


async def test_boolean_archive_position_does_not_deduplicate_integer(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    (tmp_path / "history.1-1.jsonl").write_text(json.dumps({"position": True}) + "\n")
    await JsonlOutboxObserver(path)([_event(1)])
    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == [1]


async def test_archive_range_is_only_a_candidate_index_for_gaps(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    (tmp_path / "history.1-3.jsonl").write_text(
        "\n".join(json.dumps({"position": value}) for value in [1, 3]) + "\n"
    )

    await JsonlOutboxObserver(path)([_event(2)])

    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == [2]


async def test_concurrent_same_path_observers_preserve_one_copy_of_each_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    events = [_event(position) for position in range(1, 21)]

    await asyncio.gather(*[JsonlOutboxObserver(path)(events) for _ in range(8)])

    positions = [json.loads(line)["position"] for line in path.read_text().splitlines()]
    assert positions == list(range(1, 21))


def test_separate_process_writers_preserve_one_copy_of_each_event(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    context = multiprocessing.get_context("spawn")
    writers = [
        context.Process(target=_write_from_separate_process, args=(str(path),)) for _ in range(2)
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=15)
        assert writer.exitcode == 0

    assert [json.loads(line)["position"] for line in path.read_text().splitlines()] == list(
        range(1, 21)
    )
