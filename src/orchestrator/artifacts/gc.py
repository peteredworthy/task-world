"""Typed mark-and-sweep collection for filesystem artifact blobs."""

import asyncio
import re
import stat
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from orchestrator.artifacts.models import StoredArtifactRef
from orchestrator.graph import EVENT_PAYLOAD_MODELS, EventEnvelope

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ArtifactGarbageCollectionError(Exception):
    """Raised when post-tombstone artifact collection cannot complete."""


class ArtifactGarbageCollector:
    """Coordinates typed marking with sweeping a single injected artifact root."""

    def __init__(self, root: Path, grace_seconds: int = 86400) -> None:
        self._root = root
        self._grace_seconds = grace_seconds

    async def collect(self, events: Iterable[Any], now: datetime) -> frozenset[str]:
        retained_hashes = collect_artifact_refs(events)
        try:
            return await sweep_artifacts(
                self._root,
                now,
                retained_hashes,
                self._grace_seconds,
            )
        except OSError as exc:
            raise ArtifactGarbageCollectionError("Artifact garbage collection failed") from exc


def collect_artifact_refs(events: Iterable[Any]) -> frozenset[str]:
    """Collect content hashes from actual typed artifact-reference model values."""
    refs: set[str] = set()
    for event in events:
        _collect_from_value(event, refs)
    return frozenset(refs)


def _collect_from_value(value: Any, refs: set[str]) -> None:
    if isinstance(value, EventEnvelope):
        payload_model = EVENT_PAYLOAD_MODELS.get(value.event_type)
        if payload_model is not None:
            _collect_from_value(payload_model.model_validate(value.payload), refs)
        return
    if isinstance(value, StoredArtifactRef):
        refs.add(value.content_hash)
        return
    if isinstance(value, BaseModel):
        for field_name in value.__class__.model_fields:
            _collect_from_value(getattr(value, field_name), refs)
        return
    if isinstance(value, Mapping):
        for nested in cast(Mapping[Any, Any], value).values():
            _collect_from_value(nested, refs)
        return
    if isinstance(value, (list, tuple, frozenset, set)):
        for nested in cast(Iterable[Any], value):
            _collect_from_value(nested, refs)


async def sweep_artifacts(
    root: Path,
    now: datetime,
    retained_hashes: frozenset[str],
    grace_seconds: int = 86400,
) -> frozenset[str]:
    """Delete unmarked CAS blobs older than the exact grace period."""
    return await asyncio.to_thread(
        _sweep_sync,
        root,
        now,
        retained_hashes,
        grace_seconds,
    )


def _sweep_sync(
    root: Path,
    now: datetime,
    retained_hashes: frozenset[str],
    grace_seconds: int,
) -> frozenset[str]:
    if grace_seconds < 0:
        raise ValueError("grace_seconds must be non-negative")
    cutoff = now.astimezone(UTC) - timedelta(seconds=grace_seconds)
    digest_root = root / "sha256"
    if not digest_root.is_dir():
        return frozenset()
    deleted: set[str] = set()
    for prefix in digest_root.iterdir():
        if not prefix.is_dir() or re.fullmatch(r"[0-9a-f]{2}", prefix.name) is None:
            continue
        for blob in prefix.iterdir():
            digest = prefix.name + blob.name
            if _DIGEST.fullmatch(digest) is None:
                continue
            try:
                file_stat = blob.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                continue
            content_hash = f"sha256:{digest}"
            modified_at = datetime.fromtimestamp(file_stat.st_mtime, tz=UTC)
            if content_hash in retained_hashes or modified_at >= cutoff:
                continue
            try:
                blob.unlink()
            except FileNotFoundError:
                continue
            deleted.add(content_hash)
    return frozenset(deleted)
