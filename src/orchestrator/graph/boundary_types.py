"""Reusable strict transport validation for runner execution boundaries."""

from __future__ import annotations

from hashlib import sha256
from json import dumps
from math import isfinite
from typing import Any, cast

MAX_CALLBACK_DEPTH = 100
MAX_CALLBACK_ITEMS = 10_000
MAX_CALLBACK_BYTES = 256 * 1024
MAX_RECOVERY_PATH_ITEMS = 10_000
MAX_RECOVERY_PATH_BYTES = 256 * 1024
MAX_BOUNDARY_MANIFEST_ITEMS = 10_000
MAX_BOUNDARY_MANIFEST_BYTES = 256 * 1024
MAX_CACHE_ROOT_ITEMS = 1_024
MAX_CACHE_ROOT_BYTES = 64 * 1024
MAX_BOUNDARY_STATUS_CHARS = 128
SNAPSHOT_REF_PREFIX = "refs/orchestrator/snapshots/"
# Authoritative persistence and replay limit for one complete EventEnvelope.
# This is deliberately an envelope limit, rather than a payload-only limit, so
# producers and consumers agree on the exact bytes that cross the boundary.
MAX_EVENT_ENVELOPE_BYTES = 32 * 1024


class BoundaryValidationError(ValueError):
    """A bounded, canonical runner-boundary value was invalid."""


def validate_repo_relative_path(value: str) -> str:
    if not value or value in {".", ".."} or value.startswith("/") or value.endswith("/"):
        raise BoundaryValidationError("path must be a non-empty normalized repo-relative path")
    if "\\" in value or "//" in value or any(ord(char) < 32 for char in value):
        raise BoundaryValidationError(
            "path contains a non-canonical separator or control character"
        )
    if any(part in {"", ".", ".."} or part.casefold() == ".git" for part in value.split("/")):
        raise BoundaryValidationError("path contains a non-canonical component")
    return value


def validate_sha256(value: str) -> str:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise BoundaryValidationError("value must be sha256:<64 lowercase hex>")
    digest = value.removeprefix("sha256:")
    if any(char not in "0123456789abcdef" for char in digest):
        raise BoundaryValidationError("value must be sha256:<64 lowercase hex>")
    return value


def validate_git_oid(value: str) -> str:
    if len(value) not in {40, 64} or any(char not in "0123456789abcdef" for char in value):
        raise BoundaryValidationError(
            "Git object ID must be a 40- or 64-character lowercase hex OID"
        )
    return value


def validate_snapshot_ref(value: str, snapshot_id: str) -> str:
    """Validate the exact private ref owned by one captured snapshot.

    Snapshot ids alone are not safe deletion authority: the outbox must carry
    the fully-qualified ref and the tree it was captured from.
    """
    if value != f"{SNAPSHOT_REF_PREFIX}{snapshot_id}":
        raise BoundaryValidationError("snapshot_ref must be the exact snapshot id ref")
    return value


def validate_callback_json(value: dict[str, Any] | None) -> tuple[dict[str, Any] | None, int]:
    """Validate canonical JSON recursively and return its bounded byte size."""
    items = 0

    def walk(item: object, depth: int = 0) -> None:
        nonlocal items
        if depth > MAX_CALLBACK_DEPTH:
            raise BoundaryValidationError(f"callback payload exceeds depth {MAX_CALLBACK_DEPTH}")
        items += 1
        if items > MAX_CALLBACK_ITEMS:
            raise BoundaryValidationError(f"callback payload exceeds {MAX_CALLBACK_ITEMS} items")
        item_type = type(item)
        if item is None or item_type in {bool, int, str}:
            return
        if item_type is float:
            if not isfinite(cast(float, item)):
                raise BoundaryValidationError("callback payload floats must be finite")
            return
        if item_type is list:
            for child in cast(list[object], item):
                walk(child, depth + 1)
            return
        if item_type is dict:
            for key, child in cast(dict[object, object], item).items():
                if type(key) is not str:
                    raise BoundaryValidationError("callback payload object keys must be strings")
                walk(child, depth + 1)
            return
        raise BoundaryValidationError(f"callback payload contains non-JSON {item_type.__name__}")

    if value is None:
        return None, 0
    walk(value)
    try:
        encoded = dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    except (TypeError, ValueError) as exc:
        raise BoundaryValidationError("callback payload is not canonical JSON") from exc
    if len(encoded) > MAX_CALLBACK_BYTES:
        raise BoundaryValidationError(f"callback payload exceeds {MAX_CALLBACK_BYTES} bytes")
    return value, len(encoded)


def recovery_proof_hash(
    *,
    execution_id: str,
    recovery_id: str,
    node_id: str,
    lease_id: str,
    lease_generation: int,
    baseline_snapshot_id: str,
    baseline_tree_sha: str,
    requested_paths: tuple[str, ...],
    restored_paths: tuple[str, ...],
    removed_paths: tuple[str, ...],
    recovery_scope: str = "selective",
) -> str:
    """Hash the complete, ordered pure recovery accounting record."""
    payload = {
        "execution_id": execution_id,
        "recovery_id": recovery_id,
        "node_id": node_id,
        "lease_id": lease_id,
        "lease_generation": lease_generation,
        "baseline_snapshot_id": baseline_snapshot_id,
        "baseline_tree_sha": baseline_tree_sha,
        "requested_paths": requested_paths,
        "restored_paths": restored_paths,
        "removed_paths": removed_paths,
    }
    if recovery_scope != "selective":
        payload["recovery_scope"] = recovery_scope
    encoded = dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def validate_recovery_paths(*values: list[str]) -> None:
    """Bound the complete serialized recovery path accounting transport."""
    flattened = [path for value in values for path in value]
    for path in flattened:
        validate_repo_relative_path(path)
    if len(flattened) > MAX_RECOVERY_PATH_ITEMS:
        raise BoundaryValidationError(f"recovery paths exceed {MAX_RECOVERY_PATH_ITEMS} items")
    encoded = dumps(flattened, separators=(",", ":"), ensure_ascii=True).encode()
    if len(encoded) > MAX_RECOVERY_PATH_BYTES:
        raise BoundaryValidationError(f"recovery paths exceed {MAX_RECOVERY_PATH_BYTES} bytes")


def boundary_manifest_hash(
    tree_sha: str,
    entries: list[Any] | tuple[Any, ...],
    cache_status_evidence: list[Any] | tuple[Any, ...] = (),
    cache_authority_hash: str | None = None,
) -> str:
    """Return the canonical identity of one immutable runner filesystem boundary.

    ``tree_sha`` is the exact prepared accepted-output snapshot tree and is
    part of the digest. Runtime capture excludes authorized ephemeral roots
    before preparing staged/final snapshots, so cache-only writes do not alter
    this identity while a non-cache TOCTOU mutation cannot be accepted.
    """
    validate_git_oid(tree_sha)
    normalized = sorted(
        (_boundary_entry_json(entry) for entry in entries), key=lambda entry: str(entry["path"])
    )
    _validate_boundary_manifest(normalized)
    from orchestrator.graph.cache_authority import canonicalize_cache_status_evidence

    evidence = canonicalize_cache_status_evidence(cache_status_evidence)
    if cache_authority_hash is not None and (
        len(cache_authority_hash) != 64
        or any(char not in "0123456789abcdef" for char in cache_authority_hash)
    ):
        raise BoundaryValidationError("cache_authority_hash must be 64 lowercase hex characters")
    payload: dict[str, object] = {"tree_sha": tree_sha, "entries": normalized}
    # Exact old preimages remain valid only when the event has neither new
    # identity carrier. New runtime events always populate both facts.
    if evidence or cache_authority_hash is not None:
        payload["cache_status_evidence"] = [item.model_dump(mode="json") for item in evidence]
        payload["cache_authority_hash"] = cache_authority_hash
    encoded = dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def derive_recovery_paths(
    baseline_entries: list[Any] | tuple[Any, ...],
    staged_entries: list[Any] | tuple[Any, ...],
    final_entries: list[Any] | tuple[Any, ...],
    authorized_cache_roots: list[Any] | tuple[Any, ...],
    legacy_cache_root_paths: list[str] | tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Derive exactly the paths whose complete state differs across boundaries."""
    baseline: dict[str, dict[str, object]] = {
        cast(str, item["path"]): item for item in _manifest_map(baseline_entries)
    }
    staged: dict[str, dict[str, object]] = {
        cast(str, item["path"]): item for item in _manifest_map(staged_entries)
    }
    final: dict[str, dict[str, object]] = {
        cast(str, item["path"]): item for item in _manifest_map(final_entries)
    }
    from orchestrator.graph.cache_authority import canonicalize_cache_roots

    typed_roots = canonicalize_cache_roots(authorized_cache_roots)
    roots = [root.path for root in typed_roots]
    validate_cache_roots(list(legacy_cache_root_paths))
    roots.extend(legacy_cache_root_paths)
    paths: set[str] = set(baseline) | set(staged) | set(final) | set(roots)
    result: tuple[str, ...] = tuple(
        path
        for path in sorted(paths)
        if path in roots
        or len(
            {
                dumps(state, sort_keys=True) if state is not None else None
                for state in (baseline.get(path), staged.get(path), final.get(path))
            }
        )
        > 1
    )
    validate_recovery_paths(list(result))
    return result


def _boundary_entry_json(entry: Any) -> dict[str, object]:
    value = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else dict(entry)
    return {
        "path": value["path"],
        "kind": value["kind"],
        "status": value["status"],
        "fingerprint": value["fingerprint"],
        "file_type": value["file_type"],
    }


def _manifest_map(entries: list[Any] | tuple[Any, ...]) -> list[dict[str, object]]:
    normalized = [_boundary_entry_json(entry) for entry in entries]
    _validate_boundary_manifest(normalized)
    return normalized


def _validate_boundary_manifest(entries: list[dict[str, object]]) -> None:
    if len(entries) > MAX_BOUNDARY_MANIFEST_ITEMS:
        raise BoundaryValidationError("boundary manifest exceeds item limit")
    paths = [str(entry["path"]) for entry in entries]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise BoundaryValidationError("boundary manifest paths must be sorted and unique")
    for entry in entries:
        validate_repo_relative_path(cast(str, entry["path"]))
        validate_sha256(cast(str, entry["fingerprint"]))
        if entry["kind"] not in {"tracked", "untracked", "ignored"}:
            raise BoundaryValidationError("boundary kind is invalid")
        if entry["file_type"] not in {"file", "directory", "symlink", "missing"}:
            raise BoundaryValidationError("boundary file type is invalid")
        if not isinstance(entry["status"], str) or len(entry["status"]) > MAX_BOUNDARY_STATUS_CHARS:
            raise BoundaryValidationError("boundary status exceeds 128 characters")
    if (
        len(dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
        > MAX_BOUNDARY_MANIFEST_BYTES
    ):
        raise BoundaryValidationError("boundary manifest exceeds byte limit")


def validate_cache_roots(roots: list[str] | tuple[str, ...]) -> None:
    """Validate one bounded, unique cache-root transport list."""
    if len(roots) > MAX_CACHE_ROOT_ITEMS:
        raise BoundaryValidationError(f"cache roots exceed {MAX_CACHE_ROOT_ITEMS} items")
    for root in roots:
        validate_repo_relative_path(root)
    if len(set(roots)) != len(roots):
        raise BoundaryValidationError("cache roots must be unique")
    if (
        len(dumps(list(roots), separators=(",", ":"), ensure_ascii=True).encode())
        > MAX_CACHE_ROOT_BYTES
    ):
        raise BoundaryValidationError(f"cache roots exceed {MAX_CACHE_ROOT_BYTES} bytes")


def normalize_recovery_paths(paths: list[str]) -> tuple[str, ...]:
    """Validate, sort, and collapse paths covered by another requested ancestor."""
    validate_recovery_paths(paths)
    ordered = sorted(set(paths))
    return tuple(
        path
        for path in ordered
        if not any(path.startswith(f"{ancestor}/") for ancestor in ordered if ancestor != path)
    )
