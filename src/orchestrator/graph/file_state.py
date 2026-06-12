"""Pure file-state boundary classification for the execution graph."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Literal

FileStatePathKind = Literal["tracked", "untracked", "ignored"]
FileStateVerdict = Literal["captured", "rejected"]
FileStateTaxonomy = Literal[
    "tracked_change",
    "declared",
    "tool_cache",
    "build_output",
    "test_artifact",
    "secret",
    "external_artifact",
    "unknown_ignored",
    "unknown_untracked",
]


@dataclass(frozen=True)
class FileStatePath:
    path: str
    kind: FileStatePathKind
    status: str | None = None
    size_bytes: int | None = None
    entropy: float | None = None
    content_hash: str | None = None
    repo_escape: bool = False
    symlink_escape: bool = False


@dataclass(frozen=True)
class ExternalArtifactManifest:
    path: str
    hash: str
    origin: str
    retention: str

    def to_record(self) -> dict[str, str]:
        return {
            "path": self.path,
            "hash": self.hash,
            "origin": self.origin,
            "retention": self.retention,
        }


@dataclass(frozen=True)
class WorktreeStatus:
    tracked_modified: tuple[FileStatePath, ...] = ()
    untracked: tuple[FileStatePath, ...] = ()
    ignored: tuple[FileStatePath, ...] = ()


@dataclass(frozen=True)
class FileStateDeclaration:
    pattern: str
    classification: FileStateTaxonomy
    rule: str | None = None
    origin: str | None = None
    retention: str | None = None


@dataclass(frozen=True)
class FileStatePolicy:
    declarations: tuple[FileStateDeclaration, ...] = ()
    tool_cache_patterns: tuple[str, ...] = (
        "__pycache__/**",
        "**/__pycache__/**",
        ".pytest_cache/**",
        "**/.pytest_cache/**",
        "node_modules/**",
        "**/node_modules/**",
        ".ruff_cache/**",
        "**/.ruff_cache/**",
        ".venv/**",
        "**/.venv/**",
    )
    secret_name_patterns: tuple[str, ...] = (
        "*.pem",
        ".env",
        ".env*",
        "id_rsa",
        "id_rsa*",
        "*credentials*",
    )
    secret_entropy_threshold: float = 4.0


@dataclass(frozen=True)
class PathClassification:
    path: str
    source: FileStatePathKind
    classification: FileStateTaxonomy
    matched_rule: str
    status: str | None = None
    needs_gatekeeper: bool = False
    rejected: bool = False
    reason: str | None = None
    size_bytes: int | None = None
    entropy: float | None = None
    manifest: ExternalArtifactManifest | None = None

    def to_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "path": self.path,
            "source": self.source,
            "classification": self.classification,
            "matched_rule": self.matched_rule,
            "needs_gatekeeper": self.needs_gatekeeper,
            "rejected": self.rejected,
        }
        if self.status is not None:
            record["status"] = self.status
        if self.reason is not None:
            record["reason"] = self.reason
        if self.size_bytes is not None:
            record["size_bytes"] = self.size_bytes
        if self.entropy is not None:
            record["entropy"] = self.entropy
        if self.manifest is not None:
            record["manifest"] = self.manifest.to_record()
        return record


@dataclass(frozen=True)
class FileStateClassification:
    verdict: FileStateVerdict
    paths: tuple[PathClassification, ...]
    rejected_paths: tuple[PathClassification, ...] = ()
    residue: tuple[PathClassification, ...] = ()

    def to_record(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "paths": [path.to_record() for path in self.paths],
            "rejected_paths": [path.to_record() for path in self.rejected_paths],
            "residue": [path.to_record() for path in self.residue],
        }


def classify_file_state(
    status: WorktreeStatus,
    policy: FileStatePolicy,
) -> FileStateClassification:
    """Classify collected worktree state without filesystem access."""
    classified = tuple(
        sorted(
            (
                *(_classify_path(path, policy) for path in status.tracked_modified),
                *(_classify_path(path, policy) for path in status.untracked),
                *(_classify_path(path, policy) for path in status.ignored),
            ),
            key=lambda item: (item.path, item.source, item.classification, item.matched_rule),
        )
    )
    rejected = tuple(path for path in classified if path.rejected)
    residue = tuple(
        path
        for path in classified
        if path.source in {"untracked", "ignored"} or path.classification in {"external_artifact"}
    )
    return FileStateClassification(
        verdict="rejected" if rejected else "captured",
        paths=classified,
        rejected_paths=rejected,
        residue=residue,
    )


def default_file_state_policy(
    declarations: tuple[FileStateDeclaration, ...] = (),
) -> FileStatePolicy:
    return FileStatePolicy(declarations=declarations)


def secret_name_matches(path: str, policy: FileStatePolicy | None = None) -> bool:
    active_policy = policy or default_file_state_policy()
    normalized = _normalize_match_path(path)
    name = normalized.rsplit("/", maxsplit=1)[-1]
    return any(
        fnmatch(normalized, pattern) or fnmatch(name, pattern)
        for pattern in active_policy.secret_name_patterns
    )


def _classify_path(path: FileStatePath, policy: FileStatePolicy) -> PathClassification:
    declaration = _match_declaration(path.path, policy.declarations)
    if declaration is not None and declaration.classification == "external_artifact":
        manifest = _external_manifest(path, declaration)
        if manifest is None:
            return _classification(
                path,
                "external_artifact",
                declaration.rule or f"declared:{declaration.pattern}",
                rejected=True,
                reason="external_manifest_incomplete",
            )
        return _classification(
            path,
            "external_artifact",
            declaration.rule or f"declared:{declaration.pattern}",
            manifest=manifest,
        )

    if _path_escapes_repo(path):
        return _classification(
            path,
            "external_artifact",
            "repo_escape",
            rejected=True,
            reason="repo_escape",
        )
    if secret_name_matches(path.path, policy) and _secret_metadata_matches(path, policy):
        return _classification(path, "secret", "secret_detector", rejected=True, reason="secret")

    if declaration is not None:
        return _classification(
            path,
            declaration.classification,
            declaration.rule or f"declared:{declaration.pattern}",
            needs_gatekeeper=False,
        )

    if path.kind == "tracked":
        return _classification(path, "tracked_change", "git_status")

    if _matches_any(path.path, policy.tool_cache_patterns):
        return _classification(path, "tool_cache", "builtin_tool_cache")

    if path.kind == "ignored":
        return _classification(
            path,
            "unknown_ignored",
            "unmatched_ignored",
            needs_gatekeeper=True,
        )

    return _classification(
        path,
        "unknown_untracked",
        "unmatched_untracked",
        needs_gatekeeper=True,
    )


def _classification(
    path: FileStatePath,
    classification: FileStateTaxonomy,
    matched_rule: str,
    *,
    needs_gatekeeper: bool = False,
    rejected: bool = False,
    reason: str | None = None,
    manifest: ExternalArtifactManifest | None = None,
) -> PathClassification:
    return PathClassification(
        path=path.path,
        source=path.kind,
        classification=classification,
        matched_rule=matched_rule,
        status=path.status,
        needs_gatekeeper=needs_gatekeeper,
        rejected=rejected,
        reason=reason,
        size_bytes=path.size_bytes,
        entropy=path.entropy,
        manifest=manifest,
    )


def _external_manifest(
    path: FileStatePath,
    declaration: FileStateDeclaration,
) -> ExternalArtifactManifest | None:
    if path.content_hash is None or declaration.origin is None or declaration.retention is None:
        return None
    return ExternalArtifactManifest(
        path=path.path,
        hash=path.content_hash,
        origin=declaration.origin,
        retention=declaration.retention,
    )


def _path_escapes_repo(path: FileStatePath) -> bool:
    if path.repo_escape or path.symlink_escape:
        return True
    value = path.path.replace("\\", "/")
    if value.startswith("/"):
        return True
    parts = [part for part in value.split("/") if part not in {"", "."}]
    return any(part == ".." for part in parts)


def _secret_metadata_matches(path: FileStatePath, policy: FileStatePolicy) -> bool:
    if path.entropy is not None:
        return path.entropy >= policy.secret_entropy_threshold
    return bool(path.size_bytes)


def _match_declaration(
    path: str,
    declarations: tuple[FileStateDeclaration, ...],
) -> FileStateDeclaration | None:
    normalized = _normalize_match_path(path)
    for declaration in declarations:
        if _pattern_matches(normalized, declaration.pattern):
            return declaration
    return None


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = _normalize_match_path(path)
    return any(_pattern_matches(normalized, pattern) for pattern in patterns)


def _pattern_matches(path: str, pattern: str) -> bool:
    normalized_pattern = _normalize_match_path(pattern)
    return (
        fnmatch(path, normalized_pattern)
        or fnmatch(f"{path}/", normalized_pattern)
        or fnmatch(path, normalized_pattern.rstrip("/") + "/**")
    )


def _normalize_match_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")
