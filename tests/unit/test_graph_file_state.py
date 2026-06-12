from __future__ import annotations

from typing import Any, cast

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    FileStateDeclaration,
    FileStatePath,
    FileStatePathKind,
    FileStatePolicy,
    WorktreeStatus,
    classify_file_state,
    project_residue_report,
)


def _path(
    path: str,
    kind: str,
    *,
    entropy: float | None = None,
    content_hash: str | None = None,
    repo_escape: bool = False,
    symlink_escape: bool = False,
) -> FileStatePath:
    return FileStatePath(
        path=path,
        kind=cast(FileStatePathKind, kind),
        status="M" if kind == "tracked" else None,
        size_bytes=128,
        entropy=entropy,
        content_hash=content_hash,
        repo_escape=repo_escape,
        symlink_escape=symlink_escape,
    )


def _classifications(status: WorktreeStatus, policy: FileStatePolicy | None = None) -> list[str]:
    result = classify_file_state(status, policy or FileStatePolicy())
    return [entry.classification for entry in result.paths]


def test_tracked_changes_are_captured_as_tracked_change() -> None:
    result = classify_file_state(
        WorktreeStatus(tracked_modified=(_path("src/app.py", "tracked"),)),
        FileStatePolicy(),
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "tracked_change"
    assert result.paths[0].matched_rule == "git_status"


def test_learned_patterns_apply_only_to_untracked_or_ignored_sources() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration(
                "*.py",
                "tool_cache",
                rule="pattern_library:*.py",
                source_kinds=("untracked", "ignored"),
            ),
        )
    )

    result = classify_file_state(
        WorktreeStatus(
            tracked_modified=(_path("foo.py", "tracked"),),
            untracked=(_path("bar.py", "untracked"),),
        ),
        policy,
    )

    by_path = {entry.path: entry for entry in result.paths}
    assert by_path["foo.py"].classification == "tracked_change"
    assert by_path["foo.py"].matched_rule == "git_status"
    assert by_path["bar.py"].classification == "tool_cache"
    assert by_path["bar.py"].matched_rule == "pattern_library:*.py"


def test_untracked_residue_is_captured_and_needs_gatekeeper() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("notes/tmp.txt", "untracked"),)),
        FileStatePolicy(),
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "unknown_untracked"
    assert result.paths[0].needs_gatekeeper is True


def test_known_ignored_tool_cache_row() -> None:
    assert _classifications(
        WorktreeStatus(ignored=(_path("__pycache__/app.cpython-312.pyc", "ignored"),))
    ) == ["tool_cache"]


def test_declared_build_output_row() -> None:
    policy = FileStatePolicy(
        declarations=(FileStateDeclaration("dist/**", "build_output", rule="routine:build-output"),)
    )

    result = classify_file_state(
        WorktreeStatus(ignored=(_path("dist/app.js", "ignored"),)),
        policy,
    )

    assert result.paths[0].classification == "build_output"
    assert result.paths[0].matched_rule == "routine:build-output"


def test_declared_test_artifact_row() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration("reports/**", "test_artifact", rule="verifier:test-report"),
        )
    )

    assert _classifications(
        WorktreeStatus(ignored=(_path("reports/junit.xml", "ignored"),)),
        policy,
    ) == ["test_artifact"]


def test_external_artifact_row_rejects_repo_escape() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("../outside.bin", "untracked", repo_escape=True),)),
        FileStatePolicy(),
    )

    assert result.verdict == "rejected"
    assert result.rejected_paths[0].classification == "external_artifact"
    assert result.rejected_paths[0].reason == "repo_escape"


def test_declared_external_artifact_row_carries_manifest() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration(
                "../artifacts/report.bin",
                "external_artifact",
                rule="routine:external-report",
                origin="worker_output",
                retention="retain_30_days",
            ),
        )
    )

    result = classify_file_state(
        WorktreeStatus(
            untracked=(
                _path(
                    "../artifacts/report.bin",
                    "untracked",
                    content_hash="sha256:abc123",
                    repo_escape=True,
                ),
            )
        ),
        policy,
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "external_artifact"
    assert result.paths[0].manifest is not None
    assert result.paths[0].manifest.to_record() == {
        "path": "../artifacts/report.bin",
        "hash": "sha256:abc123",
        "origin": "worker_output",
        "retention": "retain_30_days",
    }


def test_unknown_ignored_row_is_captured_with_gatekeeper_flag() -> None:
    result = classify_file_state(
        WorktreeStatus(ignored=(_path("scratch/local.bin", "ignored"),)),
        FileStatePolicy(),
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "unknown_ignored"
    assert result.paths[0].needs_gatekeeper is True


def test_secret_like_name_and_high_entropy_rejects() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("fake_key.pem", "untracked", entropy=7.2),)),
        FileStatePolicy(),
    )

    assert result.verdict == "rejected"
    assert result.rejected_paths[0].classification == "secret"
    assert result.rejected_paths[0].reason == "secret"


def test_symlink_escape_rejects() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("linked", "untracked", symlink_escape=True),)),
        FileStatePolicy(),
    )

    assert result.verdict == "rejected"
    assert result.rejected_paths[0].reason == "repo_escape"


def test_classification_is_deterministic_and_stably_ordered() -> None:
    status = WorktreeStatus(
        tracked_modified=(_path("b.py", "tracked"),),
        untracked=(_path("a.tmp", "untracked"),),
        ignored=(_path(".pytest_cache/v/cache", "ignored"),),
    )

    first = classify_file_state(status, FileStatePolicy())
    second = classify_file_state(status, FileStatePolicy())

    assert first == second
    assert [entry.path for entry in first.paths] == [
        ".pytest_cache/v/cache",
        "a.tmp",
        "b.py",
    ]


def test_project_residue_report_from_accepted_file_state_events() -> None:
    events = [
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "producer_node_id": "worker-1",
                "residue": [
                    {
                        "path": "tmp.out",
                        "source": "untracked",
                        "classification": "unknown_untracked",
                        "matched_rule": "unmatched_untracked",
                        "needs_gatekeeper": True,
                    }
                ],
            },
        )
    ]

    assert project_residue_report(events) == {
        "tmp.out": [
            {
                "path": "tmp.out",
                "classification": "unknown_untracked",
                "matched_rule": "unmatched_untracked",
                "needs_gatekeeper": True,
                "run_id": "run-1",
                "node_id": "worker-1",
                "record_id": "file-state-1",
                "source": "untracked",
            }
        ]
    }


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_type,
        run_id="run-1",
        position=1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
