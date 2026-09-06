"""Authoritative graph submission quality-gate contracts."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
from time import perf_counter

import pytest

from orchestrator.graph import build_projection, node_payload_view
from orchestrator.graph_runtime import (
    PROJECT_SUBMISSION_GATE_TIMEOUT_SECONDS,
    SUBMISSION_GATE_OUTPUT_BYTES,
    SubmissionGateCommand,
    SubmissionQualityGateError,
    bind_submission_gate_witness,
    capture_submission_gate_baseline,
    cleanup_read_only_execution_workspace,
    enforce_submission_quality_gate,
    gate_rejection_evidence,
    prepare_read_only_execution_workspace,
    resolve_submission_gate_commands,
    resolve_submission_gate_applicability,
    submission_gate_commands_from_baseline,
    submission_gate_failure_fingerprint,
)
from tests.unit.graph_test_utils import event


def _snapshot_identity(repo: Path) -> tuple[str, str]:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "gate@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Gate Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "fixture"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return commit, tree


def test_malformed_project_config_structure_fails_closed(tmp_path: Path) -> None:
    config_dir = tmp_path / ".task-world"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("[]\n", encoding="utf-8")

    with pytest.raises(SubmissionQualityGateError, match="must contain a YAML object"):
        resolve_submission_gate_commands(
            node_payload={},
            dynamic_feature=None,
            worktree_path=tmp_path,
        )


def test_read_only_semantic_gate_policy_returns_before_malformed_project_config(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".task-world"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("not: [valid", encoding="utf-8")
    node = {
        "kind": "worker",
        "access_mode": "read_only",
        "semantic_stage": "discovery",
        "effect_contract": "read_only_semantic",
        "acceptance_commands": ["exit 99"],
    }

    applicability = resolve_submission_gate_applicability(node)
    commands = resolve_submission_gate_commands(
        node_payload=node,
        dynamic_feature={"acceptance_command": "exit 98"},
        worktree_path=tmp_path,
    )

    assert applicability.execute_commands is False
    assert applicability.legacy_normalized is False
    assert commands == ()


@pytest.mark.asyncio
async def test_read_only_semantic_baseline_and_report_persist_empty_contract(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".task-world"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("not: [valid", encoding="utf-8")
    node = {
        "kind": "worker",
        "access_mode": "read_only",
        "semantic_stage": "discovery",
        "effect_contract": "read_only_semantic",
    }
    authority = {
        "run_id": "run-read-only",
        "node_id": "worker-discovery",
        "execution_id": "exec-discovery",
        "lease_id": "lease-discovery",
        "lease_generation": 1,
        "base_snapshot_id": "baseline-discovery",
        "base_tree_sha": "a" * 40,
    }
    baseline = await capture_submission_gate_baseline(
        **authority,
        node_payload=node,
        dynamic_feature={"acceptance_command": "exit 98"},
        worktree_path=tmp_path,
    )
    report = await enforce_submission_quality_gate(
        **authority,
        node_payload=node,
        dynamic_feature={"acceptance_command": "exit 98"},
        worktree_path=tmp_path,
        baseline=baseline,
    )

    assert baseline.status == "no_configured_commands"
    assert baseline.results == ()
    assert report.status == "no_configured_commands"
    assert report.results == ()


def test_legacy_live_discovery_contract_normalizes_narrowly() -> None:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "worker-discovery-retry-1",
                    "kind": "worker",
                    "role": "discovery",
                    "state": "ready",
                    "access_mode": "read_only",
                    "semantic_stage": "discovery",
                },
                position=215,
            )
        ]
    )
    replayed = node_payload_view(projection, "worker-discovery-retry-1")
    assert replayed is not None
    applicability = resolve_submission_gate_applicability(replayed)

    assert applicability.effect_contract == "read_only_semantic"
    assert applicability.execute_commands is False
    assert applicability.legacy_normalized is True


def test_legacy_normalization_rejects_ambiguous_worker_contract() -> None:
    with pytest.raises(SubmissionQualityGateError, match="effect_contract is missing"):
        resolve_submission_gate_applicability(
            {
                "kind": "worker",
                "access_mode": "read_only",
                "semantic_stage": "corrective_work",
            }
        )


@pytest.mark.parametrize(
    "node",
    [
        {"kind": "worker", "access_mode": "write"},
        {
            "kind": "worker",
            "access_mode": "write",
            "semantic_stage": "discovery",
            "effect_contract": "effectful_write",
        },
        {
            "kind": "worker",
            "access_mode": "read_only",
            "semantic_stage": "discovery",
            "effect_contract": "effectful_write",
        },
    ],
)
def test_gate_policy_fails_closed_for_missing_or_inconsistent_effect_contract(
    node: dict[str, object],
) -> None:
    with pytest.raises(
        SubmissionQualityGateError,
        match="effect contract|effect_contract|effectful_write",
    ):
        resolve_submission_gate_applicability(node)


def test_source_specific_timeouts_are_validated_and_project_default_is_long(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".task-world"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text('test_command: "printf project"\n')
    node = {
        "kind": "worker",
        "access_mode": "write",
        "effect_contract": "effectful_write",
        "acceptance_commands": ["printf node"],
        "acceptance_command_timeout_seconds": 17,
    }
    commands = resolve_submission_gate_commands(
        node_payload=node,
        dynamic_feature={
            "acceptance_command": "printf dynamic",
            "acceptance_command_timeout_seconds": 29,
        },
        worktree_path=tmp_path,
    )
    assert [command.timeout_seconds for command in commands] == [
        17,
        29,
        PROJECT_SUBMISSION_GATE_TIMEOUT_SECONDS,
    ]

    for invalid in (True, 0, 3601, "30"):
        with pytest.raises(SubmissionQualityGateError, match="timeout"):
            resolve_submission_gate_commands(
                node_payload={**node, "acceptance_command_timeout_seconds": invalid},
                dynamic_feature=None,
                worktree_path=tmp_path,
            )


@pytest.mark.asyncio
async def test_read_only_execution_workspace_is_exact_disposable_and_isolated(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    commit, tree = _snapshot_identity(repo)
    (repo / "tracked.txt").write_text("leased\n", encoding="utf-8")

    workspace = await prepare_read_only_execution_workspace(
        source_worktree=repo,
        snapshot_commit_sha=commit,
        snapshot_tree_sha=tree,
    )
    root = workspace.root
    try:
        assert (workspace.checkout / "tracked.txt").read_text(encoding="utf-8") == "baseline\n"
        (workspace.checkout / "tracked.txt").write_text("runner-dirty\n", encoding="utf-8")
        (workspace.checkout / "ignored-residue").write_text("residue\n", encoding="utf-8")
        assert (repo / "tracked.txt").read_text(encoding="utf-8") == "leased\n"
        assert (repo / "ignored-residue").exists() is False
    finally:
        await cleanup_read_only_execution_workspace(
            source_worktree=repo,
            workspace=workspace,
        )
    assert root.exists() is False


def test_gate_resolution_uses_contract_sources_and_deduplicates(tmp_path: Path) -> None:
    config_dir = tmp_path / ".task-world"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        'test_command: "printf project"\ntest_command_timeout_seconds: 23\n',
        encoding="utf-8",
    )

    commands = resolve_submission_gate_commands(
        node_payload={
            "acceptance_commands": ["printf node", "printf shared"],
            "acceptance_command_timeout_seconds": 7,
            # Agent-authored prose is deliberately not a baseline exemption.
            "baseline_failures": ["all failures are unrelated"],
        },
        dynamic_feature={
            "acceptance_command": "printf shared",
            "acceptance_command_timeout_seconds": 11,
        },
        worktree_path=tmp_path,
    )

    assert [(command.command, command.source) for command in commands] == [
        ("printf node", "node_acceptance_commands"),
        ("printf shared", "node_acceptance_commands"),
        ("printf project", "project_test_command"),
    ]
    assert [command.timeout_seconds for command in commands] == [7, 7, 23]


@pytest.mark.asyncio
async def test_no_configured_commands_is_explicit_and_does_not_invent_default(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".task-world"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text('test_command: ""\n', encoding="utf-8")
    commit, tree = _snapshot_identity(tmp_path)
    report = await enforce_submission_quality_gate(
        run_id="run-1",
        node_id="worker-1",
        execution_id="exec-1",
        lease_id="lease-1",
        lease_generation=2,
        base_snapshot_id="base-1",
        base_tree_sha=tree,
        node_payload={},
        dynamic_feature={"acceptance_command": ""},
        worktree_path=tmp_path,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
    )

    assert report.status == "no_configured_commands"
    assert report.results == ()


@pytest.mark.asyncio
async def test_failure_is_actionable_and_stops_before_later_command(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-run"
    commit, tree = _snapshot_identity(tmp_path)
    with pytest.raises(SubmissionQualityGateError) as caught:
        await enforce_submission_quality_gate(
            run_id="run-1",
            node_id="worker-1",
            execution_id="exec-1",
            lease_id="lease-1",
            lease_generation=1,
            base_snapshot_id="base-1",
            base_tree_sha=tree,
            node_payload={
                "acceptance_commands": [
                    "printf 'specific failure' >&2; exit 7",
                    f"touch {marker}",
                ]
            },
            dynamic_feature=None,
            worktree_path=tmp_path,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )

    assert "exit code 7" in str(caught.value)
    assert "specific failure" in str(caught.value)
    assert "submit again in this session" in str(caught.value)
    assert marker.exists() is False
    assert caught.value.report is not None
    assert caught.value.report.status == "failed"
    assert caught.value.report.exit_code == 7


@pytest.mark.asyncio
async def test_output_is_streamed_to_bounded_tail_with_complete_hash(tmp_path: Path) -> None:
    output_bytes = SUBMISSION_GATE_OUTPUT_BYTES + 4096
    commit, tree = _snapshot_identity(tmp_path)
    report = await enforce_submission_quality_gate(
        run_id="run-1",
        node_id="worker-1",
        execution_id="exec-1",
        lease_id="lease-1",
        lease_generation=1,
        base_snapshot_id="base-1",
        base_tree_sha=tree,
        node_payload={"acceptance_commands": [f"head -c {output_bytes} /dev/zero"]},
        dynamic_feature=None,
        worktree_path=tmp_path,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
    )

    (result,) = report.results
    assert result.status == "passed"
    assert result.stdout_bytes == output_bytes
    assert result.stdout_truncated is True
    assert len(result.stdout_tail.encode("utf-8")) == SUBMISSION_GATE_OUTPUT_BYTES
    assert result.stdout_sha256 == hashlib.sha256(bytes(output_bytes)).hexdigest()


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_reported(tmp_path: Path) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    with pytest.raises(SubmissionQualityGateError) as caught:
        await enforce_submission_quality_gate(
            run_id="run-1",
            node_id="worker-1",
            execution_id="exec-1",
            lease_id="lease-1",
            lease_generation=1,
            base_snapshot_id="base-1",
            base_tree_sha=tree,
            node_payload={
                "acceptance_commands": ["sleep 5"],
                "acceptance_command_timeout_seconds": 0.05,
            },
            dynamic_feature=None,
            worktree_path=tmp_path,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )

    assert "timed out" in str(caught.value)
    assert caught.value.report is not None
    assert caught.value.report.status == "timeout"
    assert caught.value.report.exit_code is None


@pytest.mark.asyncio
async def test_matching_timeout_is_never_baseline_exempted(tmp_path: Path) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    authority = {
        "run_id": "run-timeout",
        "node_id": "worker-timeout",
        "execution_id": "exec-timeout",
        "lease_id": "lease-timeout",
        "lease_generation": 1,
        "base_snapshot_id": "base-timeout",
        "base_tree_sha": tree,
    }
    node_payload = {
        "acceptance_commands": ["sleep 5"],
        "acceptance_command_timeout_seconds": 0.05,
    }
    baseline = await capture_submission_gate_baseline(
        **authority,
        node_payload=node_payload,
        dynamic_feature=None,
        worktree_path=tmp_path,
        snapshot_commit_sha=commit,
    )

    with pytest.raises(SubmissionQualityGateError) as caught:
        await enforce_submission_quality_gate(
            **authority,
            node_payload={
                **node_payload,
                "accepted_baseline_failure_fingerprints": list(baseline.failure_fingerprints),
            },
            dynamic_feature=None,
            worktree_path=tmp_path,
            baseline=baseline,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )

    assert baseline.results[0].status == "timeout"
    assert caught.value.report is not None
    assert caught.value.report.status == "timeout"


@pytest.mark.asyncio
async def test_passed_report_binds_exact_staged_boundary_identity(tmp_path: Path) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    report = await enforce_submission_quality_gate(
        run_id="run-1",
        node_id="worker-1",
        execution_id="exec-1",
        lease_id="lease-1",
        lease_generation=3,
        base_snapshot_id="base-1",
        base_tree_sha=tree,
        node_payload={"acceptance_commands": ["printf passed"]},
        dynamic_feature=None,
        worktree_path=tmp_path,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
    )
    witness = bind_submission_gate_witness(
        report,
        snapshot_id="snapshot-1",
        snapshot_ref="refs/orchestrator/snapshots/snapshot-1",
        commit_sha="a" * 40,
        tree_sha="b" * 40,
        boundary_hash="sha256:" + "c" * 64,
    )

    assert witness.disposition == "passed"
    assert witness.run_id == "run-1"
    assert witness.node_id == "worker-1"
    assert witness.execution_id == "exec-1"
    assert witness.lease_id == "lease-1"
    assert witness.lease_generation == 3
    assert witness.base_snapshot_id == "base-1"
    assert witness.validated_boundary.tree_sha == "b" * 40
    assert witness.validated_boundary.boundary_hash == "sha256:" + "c" * 64
    assert witness.commands[0].command_sha256 == hashlib.sha256(b"printf passed").hexdigest()


@pytest.mark.asyncio
async def test_unchanged_base_tree_failure_is_explicitly_exempted(tmp_path: Path) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    authority = {
        "run_id": "run-1",
        "node_id": "worker-1",
        "execution_id": "exec-1",
        "lease_id": "lease-1",
        "lease_generation": 4,
        "base_snapshot_id": "base-1",
        "base_tree_sha": tree,
    }
    node_payload = {
        "acceptance_commands": [
            "printf 'FAILED tests/unit/test_known.py::test_red - AssertionError\\n' >&2; exit 8"
        ]
    }
    baseline = await capture_submission_gate_baseline(
        **authority,
        node_payload=node_payload,
        dynamic_feature=None,
        worktree_path=tmp_path,
        snapshot_commit_sha=commit,
    )

    report = await enforce_submission_quality_gate(
        **authority,
        node_payload={
            **node_payload,
            "accepted_baseline_failure_fingerprints": list(baseline.failure_fingerprints),
        },
        dynamic_feature=None,
        worktree_path=tmp_path,
        baseline=baseline,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
    )

    assert baseline.status == "failed"
    assert len(baseline.failure_fingerprints) == 1
    assert report.status == "baseline_exempted"
    assert report.baseline_failure_fingerprints == baseline.failure_fingerprints


@pytest.mark.asyncio
async def test_unchanged_project_failure_is_typed_as_environment_blockage(
    tmp_path: Path,
) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    authority = {
        "run_id": "run-project-blocked",
        "node_id": "worker-project-blocked",
        "execution_id": "exec-project-blocked",
        "lease_id": "lease-project-blocked",
        "lease_generation": 1,
        "base_snapshot_id": "base-project-blocked",
        "base_tree_sha": tree,
    }
    commands = (
        SubmissionGateCommand(
            command=(
                "printf 'FAILED tests/integration/test_env.py::test_service - unavailable\\n' "
                ">&2; exit 1"
            ),
            source="project_test_command",
        ),
    )
    baseline = await capture_submission_gate_baseline(
        **authority,
        node_payload={},
        dynamic_feature=None,
        worktree_path=tmp_path,
        snapshot_commit_sha=commit,
        resolved_commands=commands,
    )

    with pytest.raises(SubmissionQualityGateError) as caught:
        await enforce_submission_quality_gate(
            **authority,
            node_payload={},
            dynamic_feature=None,
            worktree_path=tmp_path,
            baseline=baseline,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
            resolved_commands=commands,
        )

    result = caught.value.report
    assert result is not None
    assert result.failure_category == "validation_environment_blockage"
    assert result.failed_test_ids == ("tests/integration/test_env.py::test_service",)


@pytest.mark.asyncio
async def test_changed_failure_fingerprint_is_not_exempted(tmp_path: Path) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    authority = {
        "run_id": "run-1",
        "node_id": "worker-1",
        "execution_id": "exec-1",
        "lease_id": "lease-1",
        "lease_generation": 4,
        "base_snapshot_id": "base-1",
        "base_tree_sha": tree,
    }
    baseline = await capture_submission_gate_baseline(
        **authority,
        node_payload={
            "acceptance_commands": [
                "printf 'FAILED tests/unit/test_before.py::test_red - before\\n' >&2; exit 8"
            ]
        },
        dynamic_feature=None,
        worktree_path=tmp_path,
        snapshot_commit_sha=commit,
    )

    with pytest.raises(SubmissionQualityGateError, match="exit code 8"):
        await enforce_submission_quality_gate(
            **authority,
            node_payload={
                "acceptance_commands": [
                    "printf 'FAILED tests/unit/test_after.py::test_red - after\\n' >&2; exit 8"
                ]
            },
            dynamic_feature=None,
            worktree_path=tmp_path,
            baseline=baseline,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )


@pytest.mark.asyncio
async def test_semantic_failure_identity_ignores_incidental_pytest_output(tmp_path: Path) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    authority = {
        "run_id": "run-semantic",
        "node_id": "worker-semantic",
        "execution_id": "exec-semantic",
        "lease_id": "lease-semantic",
        "lease_generation": 1,
        "base_snapshot_id": "base-semantic",
        "base_tree_sha": tree,
    }
    baseline = await capture_submission_gate_baseline(
        **authority,
        node_payload={
            "acceptance_commands": [
                "printf '/tmp/pytest-1 .F 1.02s\\n"
                "FAILED tests/unit/test_same.py::test_red - first details\\n' >&2; exit 1"
            ]
        },
        dynamic_feature=None,
        worktree_path=tmp_path,
        snapshot_commit_sha=commit,
    )
    command = baseline.results[0].command
    candidate = await capture_submission_gate_baseline(
        **authority,
        node_payload={
            "acceptance_commands": [
                command.replace(
                    "/tmp/pytest-1 .F 1.02s", "/tmp/pytest-99 12 passed .F 8.77s"
                ).replace("first details", "different assertion rendering")
            ]
        },
        dynamic_feature=None,
        worktree_path=tmp_path,
        snapshot_commit_sha=commit,
    )

    assert baseline.results[0].stderr_sha256 != candidate.results[0].stderr_sha256
    # Command identity remains an integrity/authority input, so compare parsed
    # semantic evidence using otherwise identical command contracts.
    adjusted = candidate.results[0].model_copy(
        update={
            "command": baseline.results[0].command,
            "command_sha256": baseline.results[0].command_sha256,
        }
    )
    assert submission_gate_failure_fingerprint(baseline.results[0]) == (
        submission_gate_failure_fingerprint(adjusted)
    )


@pytest.mark.asyncio
async def test_added_failure_changes_semantic_identity_and_missing_test_is_candidate(
    tmp_path: Path,
) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    common = {
        "run_id": "run-added",
        "node_id": "worker-added",
        "execution_id": "exec-added",
        "lease_id": "lease-added",
        "lease_generation": 1,
        "base_snapshot_id": "base-added",
        "base_tree_sha": tree,
        "dynamic_feature": None,
        "worktree_path": tmp_path,
        "snapshot_commit_sha": commit,
    }
    one = await capture_submission_gate_baseline(
        **common,
        node_payload={
            "acceptance_commands": ["printf 'FAILED tests/a.py::test_one - red\\n' >&2; exit 1"]
        },
    )
    two = one.results[0].model_copy(
        update={
            "failed_test_ids": ("tests/a.py::test_one", "tests/b.py::test_two"),
            "failed_test_evidence": (
                "FAILED:tests/a.py::test_one",
                "FAILED:tests/b.py::test_two",
            ),
        }
    )
    missing = await capture_submission_gate_baseline(
        **common,
        node_payload={
            "acceptance_commands": [
                "printf 'ERROR: file or directory not found: tests/new_feature.py\\n' >&2; exit 4"
            ]
        },
    )
    assert submission_gate_failure_fingerprint(one.results[0]) != (
        submission_gate_failure_fingerprint(two)
    )
    assert missing.results[0].failure_category == "candidate_check_failure"
    assert missing.results[0].failed_test_ids == ("tests/new_feature.py",)
    assert missing.failure_fingerprints


@pytest.mark.asyncio
async def test_rejection_evidence_keeps_late_summary_and_integrity_hashes(tmp_path: Path) -> None:
    commit, tree = _snapshot_identity(tmp_path)
    with pytest.raises(SubmissionQualityGateError) as caught:
        await enforce_submission_quality_gate(
            run_id="run-feedback",
            node_id="worker-feedback",
            execution_id="exec-feedback",
            lease_id="lease-feedback",
            lease_generation=1,
            base_snapshot_id="base-feedback",
            base_tree_sha=tree,
            node_payload={
                "acceptance_commands": [
                    "head -c 6000 /dev/zero | tr '\\0' .; "
                    "printf '\\nFAILED tests/unit/test_late.py::test_summary - useful diagnostic\\n' "
                    ">&2; exit 1"
                ]
            },
            dynamic_feature=None,
            worktree_path=tmp_path,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )

    assert caught.value.report is not None
    evidence = gate_rejection_evidence(caught.value.report)
    assert evidence.category == "candidate_check_failure"
    assert evidence.exit_code == 1
    assert evidence.failed_test_ids == ("tests/unit/test_late.py::test_summary",)
    assert "useful diagnostic" in evidence.final_diagnostic
    assert evidence.stdout_sha256
    assert evidence.stderr_sha256
    assert evidence.semantic_failure_fingerprint
    assert evidence.durable_audit_reference is None


@pytest.mark.asyncio
async def test_gate_uses_exact_snapshot_and_sanitized_disposable_environment(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "version.txt").write_text("committed\n", encoding="utf-8")
    commit, tree = _snapshot_identity(repo)
    (repo / "version.txt").write_text("leased-worktree\n", encoding="utf-8")
    hostile_journal = repo / "tmp" / ".orchestrator" / "state" / "history.jsonl"
    command = (
        'test "$(cat version.txt)" = committed && '
        'test "$FEATURE_GATE_VALUE" = required-value && '
        'test -z "${GIT_DIR:-}" && '
        'test -z "${ORCHESTRATOR_EVENT_JOURNAL_PATH:-}" && '
        "touch gate-created && "
        'printf \'%s\\n\' "$HOME" "$TMPDIR" "$UV_CACHE_DIR" '
        '"$XDG_STATE_HOME" "$VIRTUAL_ENV"'
    )
    report = await enforce_submission_quality_gate(
        run_id="run-hermetic",
        node_id="worker-hermetic",
        execution_id="exec-hermetic",
        lease_id="lease-hermetic",
        lease_generation=1,
        base_snapshot_id="base-hermetic",
        base_tree_sha=tree,
        node_payload={"acceptance_commands": [command]},
        dynamic_feature=None,
        worktree_path=repo,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
        host_environment={
            "PATH": os.environ["PATH"],
            "HOME": str(repo),
            "FEATURE_GATE_VALUE": "required-value",
            "GIT_DIR": str(repo / ".git"),
            "PYTEST_ADDOPTS": "--must-not-leak",
            "ORCHESTRATOR_EVENT_JOURNAL_PATH": str(hostile_journal),
        },
    )

    assert report.status == "passed"
    paths = [Path(value) for value in report.results[0].stdout_tail.splitlines()]
    assert len(paths) == 5
    runtime_root = paths[0].parent
    assert all(path.is_relative_to(runtime_root) for path in paths)
    assert all(not path.exists() for path in paths)
    assert (repo / "gate-created").exists() is False
    assert hostile_journal.exists() is False
    assert (repo / "version.txt").read_text(encoding="utf-8") == "leased-worktree\n"


@pytest.mark.asyncio
async def test_gate_preserves_arbitrary_inputs_but_rejects_hostile_path_entries(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "snapshot_probe.py").write_text('VALUE = "committed"\n', encoding="utf-8")
    hostile_bin = repo / "hostile-bin"
    hostile_bin.mkdir()
    (hostile_bin / "python").write_text(
        "#!/bin/sh\nprintf hostile-path\nexit 91\n", encoding="utf-8"
    )
    (hostile_bin / "python").chmod(0o755)
    commit, tree = _snapshot_identity(repo)
    (repo / "src" / "snapshot_probe.py").write_text(
        'VALUE = "dirty-leased-worktree"\n', encoding="utf-8"
    )

    report = await enforce_submission_quality_gate(
        run_id="run-path",
        node_id="worker-path",
        execution_id="exec-path",
        lease_id="lease-path",
        lease_generation=1,
        base_snapshot_id="base-path",
        base_tree_sha=tree,
        node_payload={
            "acceptance_commands": [
                "python -c 'import os, snapshot_probe; "
                'assert snapshot_probe.VALUE == "committed"; '
                'assert os.environ["PROJECT_GATE_TOKEN"] == "kept"; '
                'print(os.path.realpath(os.environ["VIRTUAL_ENV"]))\''
            ]
        },
        dynamic_feature=None,
        worktree_path=repo,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
        host_environment={
            "PATH": f"{hostile_bin}{os.pathsep}{os.environ['PATH']}",
            "PROJECT_GATE_TOKEN": "kept",
        },
    )

    assert report.status == "passed"
    assert Path(report.results[0].stdout_tail.strip()).name == "venv"
    assert hostile_bin.as_posix() not in report.results[0].stdout_tail


@pytest.mark.asyncio
async def test_concurrent_gate_workspaces_are_unique_and_fully_removed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    commit, tree = _snapshot_identity(repo)

    async def run(execution_id: str):
        return await enforce_submission_quality_gate(
            run_id="run-concurrent",
            node_id="worker-concurrent",
            execution_id=execution_id,
            lease_id=f"lease-{execution_id}",
            lease_generation=1,
            base_snapshot_id="base-concurrent",
            base_tree_sha=tree,
            node_payload={"acceptance_commands": ["printf '%s' \"$HOME\""]},
            dynamic_feature=None,
            worktree_path=repo,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )

    first, second = await asyncio.gather(run("one"), run("two"))
    first_home = Path(first.results[0].stdout_tail)
    second_home = Path(second.results[0].stdout_tail)
    assert first_home != second_home
    assert first_home.exists() is False
    assert second_home.exists() is False


@pytest.mark.asyncio
async def test_cancelled_gate_kills_process_group_and_cleans_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    commit, tree = _snapshot_identity(repo)
    reached = tmp_path / "gate-reached"
    task = asyncio.create_task(
        enforce_submission_quality_gate(
            run_id="run-cancel",
            node_id="worker-cancel",
            execution_id="exec-cancel",
            lease_id="lease-cancel",
            lease_generation=1,
            base_snapshot_id="base-cancel",
            base_tree_sha=tree,
            node_payload={
                "acceptance_commands": [
                    f"printf '%s %s' $$ \"$HOME\" > {shlex.quote(str(reached))}; sleep 30"
                ]
            },
            dynamic_feature=None,
            worktree_path=repo,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )
    )
    for _ in range(300):
        if reached.exists():
            break
        await asyncio.sleep(0.05)
    assert reached.exists()
    pid_text, home_text = reached.read_text(encoding="utf-8").split(" ", 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_text), 0)
    assert Path(home_text).exists() is False


@pytest.mark.asyncio
async def test_gate_setup_is_low_cost_and_command_timeout_remains_bounded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    commit, tree = _snapshot_identity(repo)
    started = perf_counter()
    with pytest.raises(SubmissionQualityGateError, match="timed out"):
        await enforce_submission_quality_gate(
            run_id="run-bounded",
            node_id="worker-bounded",
            execution_id="exec-bounded",
            lease_id="lease-bounded",
            lease_generation=1,
            base_snapshot_id="base-bounded",
            base_tree_sha=tree,
            node_payload={
                "acceptance_commands": ["sleep 5"],
                "acceptance_command_timeout_seconds": 0.05,
            },
            dynamic_feature=None,
            worktree_path=repo,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )
    assert perf_counter() - started < 2


@pytest.mark.asyncio
async def test_baseline_binds_commands_against_later_config_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / ".task-world" / "config.yaml"
    config.parent.mkdir()
    config.write_text('test_command: "printf A"\n', encoding="utf-8")
    commit, tree = _snapshot_identity(repo)
    authority = {
        "run_id": "run-contract",
        "node_id": "worker-contract",
        "execution_id": "exec-contract",
        "lease_id": "lease-contract",
        "lease_generation": 1,
        "base_snapshot_id": "base-contract",
        "base_tree_sha": tree,
    }
    baseline = await capture_submission_gate_baseline(
        **authority,
        node_payload={},
        dynamic_feature=None,
        worktree_path=repo,
        snapshot_commit_sha=commit,
    )
    config.write_text('test_command: "printf B"\n', encoding="utf-8")

    report = await enforce_submission_quality_gate(
        **authority,
        node_payload={},
        dynamic_feature=None,
        worktree_path=repo,
        baseline=baseline,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
        resolved_commands=submission_gate_commands_from_baseline(baseline),
    )

    assert baseline.results[0].stdout_tail == "A"
    assert report.results[0].command == "printf A"
    assert report.results[0].stdout_tail == "A"


@pytest.mark.asyncio
async def test_gate_unlocks_its_exact_checkout_before_cleanup(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    commit, tree = _snapshot_identity(repo)

    with pytest.raises(SubmissionQualityGateError, match="exit code 9"):
        await enforce_submission_quality_gate(
            run_id="run-locked",
            node_id="worker-locked",
            execution_id="exec-locked",
            lease_id="lease-locked",
            lease_generation=1,
            base_snapshot_id="base-locked",
            base_tree_sha=tree,
            node_payload={
                "acceptance_commands": ["git worktree lock --reason validator .; exit 9"]
            },
            dynamic_feature=None,
            worktree_path=repo,
            candidate_tree_sha=tree,
            snapshot_commit_sha=commit,
        )

    registrations = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    registered_paths = {
        Path(line.removeprefix("worktree ")).resolve()
        for line in registrations.splitlines()
        if line.startswith("worktree ")
    }
    assert registered_paths == {repo.resolve()}


@pytest.mark.asyncio
async def test_uv_installs_project_only_dependency_inside_disposable_environment(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    dependency = repo / "vendor" / "gate_dep"
    package = dependency / "src" / "gate_dep"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('VALUE = "project-only"\n', encoding="utf-8")
    (dependency / "pyproject.toml").write_text(
        '[project]\nname = "gate-dep"\nversion = "0.1.0"\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/gate_dep"]\n',
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "gate-root"\nversion = "0.1.0"\n'
        'dependencies = ["gate-dep"]\n'
        '[tool.uv.sources]\ngate-dep = { path = "vendor/gate_dep" }\n',
        encoding="utf-8",
    )
    commit, tree = _snapshot_identity(repo)

    report = await enforce_submission_quality_gate(
        run_id="run-dependency",
        node_id="worker-dependency",
        execution_id="exec-dependency",
        lease_id="lease-dependency",
        lease_generation=1,
        base_snapshot_id="base-dependency",
        base_tree_sha=tree,
        node_payload={
            "acceptance_commands": ["uv run python -c 'import gate_dep; print(gate_dep.VALUE)'"],
            "acceptance_command_timeout_seconds": 30,
        },
        dynamic_feature=None,
        worktree_path=repo,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
    )

    assert report.status == "passed"
    assert report.results[0].stdout_tail.strip() == "project-only"
