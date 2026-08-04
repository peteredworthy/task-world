"""Immutable, hash-addressed cache authority policy facts.

This module deliberately has no runtime or pattern-library dependencies.  The
value compiled into a routine snapshot is the complete authority decision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from orchestrator.graph.file_state import FileStatePath, FileStatePolicy, WorktreeStatus


POLICY_VERSION = "cache-authority-v1"
BUILTIN_TOOL_CACHE_PATTERNS = (
    "__pycache__/**",
    "**/__pycache__/**",
    ".pytest_cache/**",
    "**/.pytest_cache/**",
    ".hypothesis/**",
    "**/.hypothesis/**",
    "node_modules/**",
    "**/node_modules/**",
    ".ruff_cache/**",
    "**/.ruff_cache/**",
    ".venv/**",
    "**/.venv/**",
    ".mypy_cache/**",
    "**/.mypy_cache/**",
    ".claude/**",
    "**/.claude/**",
    ".worktree-manifest.json",
)
BUILTIN_SECRET_NAME_PATTERNS = ("*.pem", ".env", ".env*", "id_rsa", "id_rsa*", "*credentials*")
BUILTIN_SECRET_ENTROPY_THRESHOLD = 4.0


def _declaration_pattern(declaration: "CacheAuthorityDeclaration") -> str:
    return declaration.pattern


class _FrozenPolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CacheAuthorityDeclaration(_FrozenPolicyModel):
    pattern: str
    classification: Literal[
        "declared", "tool_cache", "build_output", "test_artifact", "secret", "external_artifact"
    ]
    source_kinds: tuple[Literal["tracked", "untracked", "ignored"], ...] = ()
    rule: str | None = None
    origin: str | None = None
    retention: str | None = None

    @field_validator("pattern")
    @classmethod
    def _canonical_pattern(cls, value: str) -> str:
        return canonical_authority_pattern(value)

    @field_validator("source_kinds", mode="before")
    @classmethod
    def _canonical_sources(cls, value: object) -> tuple[object, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("source_kinds must be a sequence")
        return tuple(sorted(cast(list[str] | tuple[str, ...], value)))


class CacheScanBudget(_FrozenPolicyModel):
    max_entries: int = Field(default=10_000, ge=1)
    max_bytes: int = Field(default=1_073_741_824, ge=1)


class CacheAuthorityPolicy(_FrozenPolicyModel):
    version: Literal["cache-authority-v1"] = POLICY_VERSION
    declarations: tuple[CacheAuthorityDeclaration, ...] = ()
    scan_budget: CacheScanBudget = Field(default_factory=CacheScanBudget)
    tool_cache_patterns: tuple[str, ...] = BUILTIN_TOOL_CACHE_PATTERNS
    secret_name_patterns: tuple[str, ...] = BUILTIN_SECRET_NAME_PATTERNS
    secret_entropy_threshold: float = BUILTIN_SECRET_ENTROPY_THRESHOLD

    @model_validator(mode="after")
    def _v1_builtins_are_frozen(self) -> "CacheAuthorityPolicy":
        if self.tool_cache_patterns != BUILTIN_TOOL_CACHE_PATTERNS:
            raise ValueError("cache-authority-v1 tool_cache_patterns are frozen")
        if self.secret_name_patterns != BUILTIN_SECRET_NAME_PATTERNS:
            raise ValueError("cache-authority-v1 secret_name_patterns are frozen")
        if self.secret_entropy_threshold != BUILTIN_SECRET_ENTROPY_THRESHOLD:
            raise ValueError("cache-authority-v1 secret_entropy_threshold is frozen")
        return self

    @field_validator("declarations", mode="before")
    @classmethod
    def _canonical_declarations(cls, value: object) -> tuple[object, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("declarations must be a sequence")
        raw_declarations = cast(list[object] | tuple[object, ...], value)
        declarations: tuple[CacheAuthorityDeclaration, ...] = tuple(
            CacheAuthorityDeclaration.model_validate(item) for item in raw_declarations
        )
        # Pattern is the identity: an ambiguous first-match policy is never
        # compiled into authority.
        patterns = [item.pattern for item in declarations]
        if len(set(patterns)) != len(patterns):
            raise ValueError("cache authority declarations must not repeat patterns")
        return tuple(sorted(declarations, key=_declaration_pattern))


class CacheAuthorityBinding(_FrozenPolicyModel):
    """Verified routine-snapshot authority returned by public projection queries."""

    policy: CacheAuthorityPolicy
    preimage: str
    hash: str


class RunnerCacheRoot(_FrozenPolicyModel):
    """A concrete, policy-authorized ephemeral worktree subtree.

    The source kind is evidence, not decoration: an ignored-only declaration
    must never authorize an otherwise identical untracked path.
    """

    path: str
    kind: Literal["untracked", "ignored"]

    @field_validator("path")
    @classmethod
    def _canonical_path(cls, value: str) -> str:
        from orchestrator.graph.boundary_types import validate_repo_relative_path

        return validate_repo_relative_path(value)


class CacheStatusEvidence(_FrozenPolicyModel):
    """One observed non-tracked path used to derive cache-root authority."""

    path: str
    kind: Literal["untracked", "ignored"]

    @field_validator("path")
    @classmethod
    def _canonical_path(cls, value: str) -> str:
        from orchestrator.graph.boundary_types import validate_repo_relative_path

        return validate_repo_relative_path(value)


def canonicalize_cache_roots(
    roots: Iterable[object],
) -> tuple[RunnerCacheRoot, ...]:
    """Return bounded canonical roots, rejecting overlapping authority.

    A root is an exclusion boundary.  Allowing an ancestor and descendant (or
    two source kinds for the same path) would make recovery authority depend on
    event ordering, so it is rejected rather than silently collapsed.
    """
    from orchestrator.graph.boundary_types import (
        MAX_CACHE_ROOT_BYTES,
        MAX_CACHE_ROOT_ITEMS,
        BoundaryValidationError,
    )

    values = tuple(RunnerCacheRoot.model_validate(root) for root in roots)
    if len(values) > MAX_CACHE_ROOT_ITEMS:
        raise BoundaryValidationError(f"cache roots exceed {MAX_CACHE_ROOT_ITEMS} items")
    ordered = tuple(sorted(values, key=lambda root: (root.path, root.kind)))
    if len(ordered) != len({(root.path, root.kind) for root in ordered}):
        raise ValueError("cache roots must not repeat path/kind")
    paths = [root.path for root in ordered]
    if len(paths) != len(set(paths)):
        raise ValueError("cache roots must not repeat paths across source kinds")
    for index, root in enumerate(ordered):
        if any(root.path.startswith(f"{prior.path}/") for prior in ordered[:index]):
            raise ValueError("cache roots must not contain ancestor/descendant paths")
    encoded = json.dumps(
        [root.model_dump(mode="json") for root in ordered],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    if len(encoded) > MAX_CACHE_ROOT_BYTES:
        raise BoundaryValidationError(f"cache roots exceed {MAX_CACHE_ROOT_BYTES} bytes")
    return ordered


def latest_cache_root_union(
    *observations: Iterable[object],
) -> tuple[RunnerCacheRoot, ...]:
    """Select the latest source kind for each path across validated phases."""
    selected: dict[str, RunnerCacheRoot] = {}
    for observation in observations:
        for root in canonicalize_cache_roots(observation):
            selected[root.path] = root
    return canonicalize_cache_roots(selected.values())


def canonicalize_cache_status_evidence(
    evidence: Iterable[object],
) -> tuple[CacheStatusEvidence, ...]:
    """Canonicalize bounded non-tracked status evidence before persistence."""
    from orchestrator.graph.boundary_types import (
        MAX_CACHE_ROOT_BYTES,
        MAX_CACHE_ROOT_ITEMS,
        BoundaryValidationError,
    )

    values = tuple(CacheStatusEvidence.model_validate(item) for item in evidence)
    ordered = tuple(sorted(values, key=lambda item: (item.path, item.kind)))
    if len(ordered) > MAX_CACHE_ROOT_ITEMS:
        raise BoundaryValidationError(f"cache status evidence exceeds {MAX_CACHE_ROOT_ITEMS} items")
    if len(ordered) != len({(item.path, item.kind) for item in ordered}):
        raise BoundaryValidationError("cache status evidence must not repeat path/kind")
    encoded = json.dumps(
        [item.model_dump(mode="json") for item in ordered],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    if len(encoded) > MAX_CACHE_ROOT_BYTES:
        raise BoundaryValidationError(f"cache status evidence exceeds {MAX_CACHE_ROOT_BYTES} bytes")
    return ordered


def first_authorized_cache_root(
    path: "FileStatePath", policy: CacheAuthorityPolicy
) -> RunnerCacheRoot | None:
    """Return the first shallow policy-authorized cache ancestor for ``path``.

    Only immutable built-ins and snapshot declarations participate.  Learned
    classifier output is intentionally absent from this API.
    """
    if path.kind == "tracked":
        return None
    from orchestrator.graph.file_state import authority_pattern_matches

    parts = path.path.replace("\\", "/").strip("/").split("/")
    for index in range(1, len(parts) + 1):
        candidate = "/".join(parts[:index])
        for declaration in policy.declarations:
            if declaration.classification != "tool_cache":
                continue
            if declaration.source_kinds and path.kind not in declaration.source_kinds:
                continue
            if _root_pattern_matches(candidate, declaration.pattern, authority_pattern_matches):
                return RunnerCacheRoot(path=candidate, kind=path.kind)
        if any(
            _root_pattern_matches(candidate, pattern, authority_pattern_matches)
            for pattern in policy.tool_cache_patterns
        ):
            return RunnerCacheRoot(path=candidate, kind=path.kind)
    return None


def derive_cache_roots(
    status: "WorktreeStatus | Iterable[object]", policy: CacheAuthorityPolicy
) -> tuple[RunnerCacheRoot, ...]:
    """Derive all concrete roots from actual non-tracked worktree status."""
    evidence = _cache_status_evidence(status)
    return canonicalize_cache_roots(
        root
        for item in evidence
        if (root := first_authorized_cache_root(_as_file_state_path(item), policy)) is not None
    )


def validate_authorized_cache_roots(
    roots: Iterable[RunnerCacheRoot | dict[str, object]],
    policy: CacheAuthorityPolicy,
    *,
    status: "WorktreeStatus | Iterable[object] | None" = None,
) -> tuple[RunnerCacheRoot, ...]:
    """Validate roots against immutable policy, optionally exact status derivation."""
    canonical = canonicalize_cache_roots(roots)
    from orchestrator.graph.file_state import FileStatePath

    for root in canonical:
        probe = FileStatePath(path=root.path, kind=root.kind)
        if first_authorized_cache_root(probe, policy) != root:
            raise ValueError(f"cache root {root.path!r} is not authorized for {root.kind}")
    if status is not None and canonical != derive_cache_roots(status, policy):
        raise ValueError("cache roots do not exactly match worktree status derivation")
    return canonical


def _cache_status_evidence(
    status: "WorktreeStatus | Iterable[object]",
) -> tuple["FileStatePath | CacheStatusEvidence", ...]:
    from orchestrator.graph.file_state import WorktreeStatus

    if isinstance(status, WorktreeStatus):
        return (*status.untracked, *status.ignored)
    return canonicalize_cache_status_evidence(status)


def _as_file_state_path(item: "FileStatePath | CacheStatusEvidence") -> "FileStatePath":
    if not isinstance(item, CacheStatusEvidence):
        return item
    from orchestrator.graph.file_state import FileStatePath

    return FileStatePath(path=item.path, kind=item.kind)


def _root_pattern_matches(candidate: str, pattern: str, matcher: object) -> bool:
    """Match a concrete subtree root with the authority glob grammar."""
    from typing import Callable

    matches = cast(Callable[[str, str], bool], matcher)
    if pattern.endswith("/**"):
        root = pattern[:-3]
        return candidate == root or matches(f"{candidate}/.cache-authority-probe", pattern)
    return matches(candidate, pattern)


def canonicalize_cache_authority(policy: CacheAuthorityPolicy) -> str:
    """Return the deterministic JSON preimage for a cache-authority policy."""
    return json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def cache_authority_hash(policy: CacheAuthorityPolicy) -> str:
    return hashlib.sha256(canonicalize_cache_authority(policy).encode("utf-8")).hexdigest()


def has_cache_authority_carrier(
    node_hash_present: bool, lease_hashes: Iterable[str | None]
) -> bool:
    return node_hash_present or any(value is not None for value in lease_hashes)


def canonical_authority_pattern(value: str) -> str:
    """Validate the small, segment-aware authority glob language."""
    if not value or value != value.strip() or value.startswith("/") or "\\" in value:
        raise ValueError("authority pattern must be a non-empty canonical repo-relative path")
    if any(ord(char) < 32 for char in value):
        raise ValueError("authority pattern must not contain control characters")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts):
        raise ValueError("authority pattern contains an unsafe path segment")
    previous_recursive = False
    for index, part in enumerate(parts):
        if any(token in part for token in ("?", "[", "]")):
            raise ValueError("authority patterns do not support character classes or ?")
        if part == "**":
            if len(parts) == 1:
                raise ValueError("authority pattern must not be repository-wide **")
            if previous_recursive:
                raise ValueError("authority patterns must not contain consecutive ** segments")
            previous_recursive = True
            continue
        previous_recursive = False
        if "*" not in part:
            continue
        if not (part.startswith("*.") and part.count("*") == 1 and len(part) > 2):
            raise ValueError("authority glob segments are limited to *.suffix")
        if part[1:].casefold() == ".git":
            raise ValueError("authority pattern must not match .git")
        if index != len(parts) - 1:
            raise ValueError("authority suffix glob must be the final segment")
    if "**" in parts and parts[-1] != "**":
        raise ValueError("authority recursive glob must be an explicit trailing /** subtree")
    return value


def file_state_policy_from_authority(policy: CacheAuthorityPolicy) -> "FileStatePolicy":
    """Materialize runtime policy only from a verified immutable authority fact."""
    from orchestrator.graph.file_state import (
        FileStateDeclaration,
        FileStatePolicy,
        FileStateScanBudget,
    )

    return FileStatePolicy(
        declarations=tuple(
            FileStateDeclaration(
                pattern=item.pattern,
                classification=item.classification,
                rule=item.rule,
                origin=item.origin,
                retention=item.retention,
                source_kinds=item.source_kinds or None,
            )
            for item in policy.declarations
        ),
        tool_cache_patterns=policy.tool_cache_patterns,
        secret_name_patterns=policy.secret_name_patterns,
        secret_entropy_threshold=policy.secret_entropy_threshold,
        scan_budget=FileStateScanBudget(
            max_entries=policy.scan_budget.max_entries,
            max_bytes=policy.scan_budget.max_bytes,
        ),
    )


# This constant intentionally does not call FileStatePolicy/default helpers.
# Future mutable runtime defaults therefore cannot reinterpret old histories.
LEGACY_CACHE_AUTHORITY_V1 = CacheAuthorityPolicy()
