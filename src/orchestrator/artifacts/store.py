"""Filesystem-backed content-addressed artifact storage."""

import asyncio
import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import AsyncContextManager, Protocol

from orchestrator.artifacts.errors import ArtifactIntegrityError, ArtifactNotFoundError
from orchestrator.artifacts.coordination import ArtifactRootLock
from orchestrator.artifacts.models import StoredArtifactRef

_CONTENT_HASH_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")


class ArtifactStore(Protocol):
    def publication(self) -> AsyncContextManager[None]: ...

    async def put(
        self, content: bytes, *, media_type: str, encoding: str | None = None
    ) -> StoredArtifactRef: ...

    async def read(self, ref: StoredArtifactRef) -> bytes: ...

    async def delete(self, ref: StoredArtifactRef) -> None: ...


class FilesystemArtifactStore:
    """Store immutable blobs under hash-derived, private directories."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = ArtifactRootLock(root)

    def publication(self) -> AsyncContextManager[None]:
        return self._lock.publish()

    async def put(
        self, content: bytes, *, media_type: str, encoding: str | None = None
    ) -> StoredArtifactRef:
        return await asyncio.to_thread(self._put_sync, content, media_type, encoding)

    async def read(self, ref: StoredArtifactRef) -> bytes:
        return await asyncio.to_thread(self._read_sync, ref)

    async def delete(self, ref: StoredArtifactRef) -> None:
        await asyncio.to_thread(self._delete_sync, ref)

    def _put_sync(self, content: bytes, media_type: str, encoding: str | None) -> StoredArtifactRef:
        content_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
        digest = content_hash.removeprefix("sha256:")
        blob_path = self._blob_path(digest)
        self._ensure_private_directory(self._root)
        self._ensure_private_directory(blob_path.parent.parent)
        self._ensure_private_directory(blob_path.parent)

        ref = StoredArtifactRef(
            artifact_id=content_hash,
            content_hash=content_hash,
            size_bytes=len(content),
            media_type=media_type,
            encoding=encoding,
            storage_uri=f"artifact://sha256/{digest}",
        )

        if blob_path.exists() and self._is_valid_blob(blob_path, content_hash, len(content)):
            return ref

        fd, temporary_path = tempfile.mkstemp(dir=blob_path.parent, prefix=".artifact-")
        try:
            with os.fdopen(fd, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, blob_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        return ref

    def _read_sync(self, ref: StoredArtifactRef) -> bytes:
        validated_ref = self._validate_ref(ref)
        blob_path = self._blob_path_from_ref(validated_ref)
        try:
            content = blob_path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(
                f"Artifact not found: {validated_ref.content_hash}"
            ) from exc
        self._verify_content(content, validated_ref)
        return content

    def _delete_sync(self, ref: StoredArtifactRef) -> None:
        validated_ref = self._validate_ref(ref)
        blob_path = self._blob_path_from_ref(validated_ref)
        try:
            blob_path.unlink()
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(
                f"Artifact not found: {validated_ref.content_hash}"
            ) from exc

    def _blob_path_from_ref(self, ref: StoredArtifactRef) -> Path:
        match = _CONTENT_HASH_PATTERN.fullmatch(ref.content_hash)
        if match is None:
            raise ArtifactIntegrityError("Invalid artifact content hash")
        return self._blob_path(match.group(1))

    def _blob_path(self, digest: str) -> Path:
        return self._root / "sha256" / digest[:2] / digest[2:]

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)

    @staticmethod
    def _is_valid_blob(path: Path, content_hash: str, size_bytes: int) -> bool:
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return False
        return (
            len(content) == size_bytes
            and f"sha256:{hashlib.sha256(content).hexdigest()}" == content_hash
        )

    @staticmethod
    def _validate_ref(ref: StoredArtifactRef) -> StoredArtifactRef:
        try:
            validated_ref = StoredArtifactRef.model_validate(ref.model_dump())
        except (AttributeError, TypeError, ValueError) as exc:
            raise ArtifactIntegrityError("Invalid artifact reference") from exc
        if validated_ref.artifact_id != validated_ref.content_hash:
            raise ArtifactIntegrityError("Artifact ID must equal content hash")
        return validated_ref

    @staticmethod
    def _verify_content(content: bytes, ref: StoredArtifactRef) -> None:
        if len(content) != ref.size_bytes:
            raise ArtifactIntegrityError(
                f"Artifact size mismatch: expected {ref.size_bytes}, got {len(content)}"
            )
        actual_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if actual_hash != ref.content_hash:
            raise ArtifactIntegrityError(
                f"Artifact hash mismatch: expected {ref.content_hash}, got {actual_hash}"
            )
