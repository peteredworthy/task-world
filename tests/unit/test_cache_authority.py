"""Focused phase-1 cache-authority compiler and policy contracts."""

import pytest

from orchestrator.config import RoutineConfig
from orchestrator.graph import (
    CacheAuthorityDeclaration,
    CacheAuthorityPolicy,
    CacheScanBudget,
    BUILTIN_TOOL_CACHE_PATTERNS,
    FileStateDeclaration,
    FileStatePath,
    FileStatePolicy,
    WorktreeStatus,
    RunnerCacheRoot,
    classify_file_state,
    FakeClock,
    SequentialIdGenerator,
    cache_authority_hash,
    cache_authority_binding,
    canonicalize_cache_authority,
    derive_cache_roots,
    first_authorized_cache_root,
    validate_authorized_cache_roots,
    compile_routine,
    initial_projection,
)


def _routine(policy: dict[str, object] | None = None) -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "cache-policy",
            "name": "Cache policy",
            "file_state_policy": policy,
            "steps": [{"id": "s", "title": "S", "tasks": [{"id": "t", "title": "T"}]}],
        }
    )


def test_cache_authority_hash_is_canonical_across_declaration_order() -> None:
    first = CacheAuthorityPolicy(
        declarations=(
            CacheAuthorityDeclaration(
                pattern="z/cache/**", classification="tool_cache", source_kinds=("ignored",)
            ),
            CacheAuthorityDeclaration(
                pattern="a/cache/**", classification="tool_cache", source_kinds=("untracked",)
            ),
        ),
        scan_budget=CacheScanBudget(max_entries=3, max_bytes=4),
    )
    second = CacheAuthorityPolicy(
        declarations=tuple(reversed(first.declarations)), scan_budget=first.scan_budget
    )
    assert canonicalize_cache_authority(first) == canonicalize_cache_authority(second)
    assert cache_authority_hash(first) == cache_authority_hash(second)


def test_compiler_binds_snapshot_and_every_node_to_one_policy_hash() -> None:
    routine = _routine(
        {
            "declarations": [
                {
                    "pattern": ".tool-cache/**",
                    "classification": "tool_cache",
                    "source_kinds": ["ignored"],
                }
            ],
            "scan_budget": {"max_entries": 5, "max_bytes": 8},
        }
    )
    events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-cache",
    )
    snapshot = next(
        event
        for event in events
        if event.event_type == "node_created" and event.payload["node_id"] == "routine-snapshot"
    )
    digest = snapshot.payload["snapshot"]["cache_authority_hash"]
    assert isinstance(digest, str)
    assert all(
        event.payload["cache_authority_hash"] == digest
        for event in events
        if event.event_type == "node_created"
    )


@pytest.mark.parametrize("pattern", ["*", "**", "../cache/**", ".git/cache/**"])
def test_file_state_policy_rejects_overbroad_or_control_patterns(pattern: str) -> None:
    with pytest.raises(ValueError):
        _routine(
            {
                "declarations": [
                    {
                        "pattern": pattern,
                        "classification": "tool_cache",
                        "source_kinds": ["ignored"],
                    }
                ]
            }
        )


def test_v1_rejects_self_consistent_replacement_builtins() -> None:
    with pytest.raises(ValueError, match="tool_cache_patterns are frozen"):
        CacheAuthorityPolicy(tool_cache_patterns=("replacement/**",))
    assert CacheAuthorityPolicy().tool_cache_patterns == BUILTIN_TOOL_CACHE_PATTERNS


@pytest.mark.parametrize(
    "pattern",
    ("*.egg-info", "build/**"),
)
def test_authority_pattern_grammar_accepts_canonical_forms(pattern: str) -> None:
    CacheAuthorityDeclaration(pattern=pattern, classification="build_output")


@pytest.mark.parametrize(
    "pattern",
    ("*", "name*", "a*b", "a/**/b", "a/**/**", "[ab]", "a?b", ".GIT/**"),
)
def test_authority_pattern_grammar_rejects_aliases_and_unsafe_forms(pattern: str) -> None:
    with pytest.raises(ValueError):
        CacheAuthorityDeclaration(pattern=pattern, classification="build_output")


def test_empty_projection_is_explicit_legacy_binding() -> None:
    assert cache_authority_binding(initial_projection()).policy == CacheAuthorityPolicy()


def test_exact_authority_pattern_does_not_authorize_descendants() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration(
                pattern="build", classification="build_output", source_kinds=("untracked",)
            ),
        )
    )
    result = classify_file_state(
        WorktreeStatus(untracked=(FileStatePath("build/output", "untracked"),)), policy
    )
    assert result.paths[0].classification == "unknown_untracked"


def test_suffix_glob_is_one_segment_only() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration(
                pattern="*.egg-info", classification="build_output", source_kinds=("untracked",)
            ),
        )
    )
    result = classify_file_state(
        WorktreeStatus(
            untracked=(
                FileStatePath("package.egg-info", "untracked"),
                FileStatePath("nested/package.egg-info", "untracked"),
            )
        ),
        policy,
    )
    assert {item.path: item.classification for item in result.paths} == {
        "package.egg-info": "build_output",
        "nested/package.egg-info": "unknown_untracked",
    }


def test_typed_roots_are_shallow_kind_bound_and_exactly_derived() -> None:
    policy = CacheAuthorityPolicy(
        declarations=(
            CacheAuthorityDeclaration(
                pattern="custom/cache/**",
                classification="tool_cache",
                source_kinds=("ignored",),
            ),
        )
    )
    status = WorktreeStatus(
        tracked_modified=(FileStatePath("custom/cache/tracked", "tracked"),),
        untracked=(FileStatePath("custom/cache/untracked", "untracked"),),
        ignored=(FileStatePath("custom/cache/deep/file", "ignored"),),
    )
    assert first_authorized_cache_root(status.tracked_modified[0], policy) is None
    assert first_authorized_cache_root(status.untracked[0], policy) is None
    roots = derive_cache_roots(status, policy)
    assert roots == (RunnerCacheRoot(path="custom/cache", kind="ignored"),)
    assert validate_authorized_cache_roots(roots, policy, status=status) == roots


def test_derived_roots_deduplicate_files_under_the_same_cache() -> None:
    status = WorktreeStatus(
        ignored=(
            FileStatePath(".pytest_cache/CACHEDIR.TAG", "ignored"),
            FileStatePath(".pytest_cache/v/cache/nodeids", "ignored"),
        )
    )

    assert derive_cache_roots(status, CacheAuthorityPolicy()) == (
        RunnerCacheRoot(path=".pytest_cache", kind="ignored"),
    )


@pytest.mark.parametrize(
    "roots",
    [
        [
            {"path": ".pytest_cache", "kind": "ignored"},
            {"path": ".pytest_cache/v", "kind": "ignored"},
        ],
        [
            {"path": ".pytest_cache", "kind": "ignored"},
            {"path": ".pytest_cache", "kind": "untracked"},
        ],
    ],
)
def test_typed_roots_reject_ambiguous_authority(roots: list[dict[str, str]]) -> None:
    with pytest.raises(ValueError, match="cache roots must not"):
        validate_authorized_cache_roots(roots, CacheAuthorityPolicy())
