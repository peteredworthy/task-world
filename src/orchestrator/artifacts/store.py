"""Filesystem-backed content-addressed artifact storage."""

import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import AsyncContextManager, Protocol, cast

from orchestrator.artifacts.errors import ArtifactIntegrityError, ArtifactNotFoundError
from orchestrator.artifacts.coordination import ArtifactRootLock
from orchestrator.artifacts.models import StoredArtifactRef

_CONTENT_HASH_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")
_CHECKPOINT_SUFFIX = ".checkpoint.json"


class ArtifactStore(Protocol):
    def publication(self) -> AsyncContextManager[None]: ...

    async def put(
        self, content: bytes, *, media_type: str, encoding: str | None = None
    ) -> StoredArtifactRef: ...

    async def read(self, ref: StoredArtifactRef) -> bytes: ...

    async def read_range(
        self, ref: StoredArtifactRef, *, offset: int, limit: int
    ) -> tuple[bytes, int]: ...

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

    async def read_range(
        self,
        ref: StoredArtifactRef,
        *,
        offset: int,
        limit: int,
    ) -> tuple[bytes, int]:
        """Return a range after checking a durable verified blob identity.

        A complete SHA-256 is recorded at publication and rechecked when the
        filesystem identity changes.  Stable immutable blobs therefore cost a
        stat plus the requested bytes, while truncation or replacement still
        forces a full integrity check before any range is served.
        """
        return await asyncio.to_thread(self._read_range_sync, ref, offset, limit)

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
            self._write_checkpoint(blob_path, ref)
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
        self._write_checkpoint(blob_path, ref)
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
        self._write_checkpoint(blob_path, validated_ref)
        return content

    def _read_range_sync(
        self,
        ref: StoredArtifactRef,
        offset: int,
        limit: int,
    ) -> tuple[bytes, int]:
        if offset < 0 or limit < 1:
            raise ValueError("artifact range must have non-negative offset and positive limit")
        validated_ref = self._validate_ref(ref)
        blob_path = self._blob_path_from_ref(validated_ref)
        checkpoint = self._verified_checkpoint(blob_path, validated_ref)
        for _ in range(2):
            before = self._file_identity(blob_path, validated_ref)
            if not self._checkpoint_matches(checkpoint, before, validated_ref):
                checkpoint = self._verify_and_checkpoint(blob_path, validated_ref)
                before = self._file_identity(blob_path, validated_ref)
            try:
                with blob_path.open("rb") as blob:
                    blob.seek(offset)
                    content = blob.read(limit)
            except FileNotFoundError as exc:
                raise ArtifactNotFoundError(
                    f"Artifact not found: {validated_ref.content_hash}"
                ) from exc
            after = self._file_identity(blob_path, validated_ref)
            if before == after and self._checkpoint_matches(checkpoint, after, validated_ref):
                return content, validated_ref.size_bytes
        raise ArtifactIntegrityError("Artifact changed while reading requested range")

    def _delete_sync(self, ref: StoredArtifactRef) -> None:
        validated_ref = self._validate_ref(ref)
        blob_path = self._blob_path_from_ref(validated_ref)
        try:
            blob_path.unlink()
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(
                f"Artifact not found: {validated_ref.content_hash}"
            ) from exc
        try:
            self._checkpoint_path(blob_path).unlink()
        except FileNotFoundError:
            pass

    def _blob_path_from_ref(self, ref: StoredArtifactRef) -> Path:
        match = _CONTENT_HASH_PATTERN.fullmatch(ref.content_hash)
        if match is None:
            raise ArtifactIntegrityError("Invalid artifact content hash")
        return self._blob_path(match.group(1))

    def _blob_path(self, digest: str) -> Path:
        return self._root / "sha256" / digest[:2] / digest[2:]

    @staticmethod
    def _checkpoint_path(blob_path: Path) -> Path:
        return blob_path.with_name(f"{blob_path.name}{_CHECKPOINT_SUFFIX}")

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

    def _verified_checkpoint(self, blob_path: Path, ref: StoredArtifactRef) -> dict[str, object]:
        checkpoint = self._read_checkpoint(blob_path)
        if checkpoint is not None:
            try:
                identity = self._file_identity(blob_path, ref)
            except ArtifactNotFoundError:
                raise
            if self._checkpoint_matches(checkpoint, identity, ref):
                return checkpoint
        return self._verify_and_checkpoint(blob_path, ref)

    def _verify_and_checkpoint(self, blob_path: Path, ref: StoredArtifactRef) -> dict[str, object]:
        try:
            content = blob_path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"Artifact not found: {ref.content_hash}") from exc
        self._verify_content(content, ref)
        return self._write_checkpoint(blob_path, ref)

    def _read_checkpoint(self, blob_path: Path) -> dict[str, object] | None:
        try:
            value: object = json.loads(self._checkpoint_path(blob_path).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return cast(dict[str, object], value) if isinstance(value, dict) else None

    def _write_checkpoint(self, blob_path: Path, ref: StoredArtifactRef) -> dict[str, object]:
        identity = self._file_identity(blob_path, ref)
        checkpoint: dict[str, object] = {
            "format": 1,
            "content_hash": ref.content_hash,
            "size_bytes": ref.size_bytes,
            **identity,
        }
        checkpoint_path = self._checkpoint_path(blob_path)
        fd, temporary_path = tempfile.mkstemp(
            dir=checkpoint_path.parent, prefix=".artifact-checkpoint-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                json.dump(checkpoint, temporary_file, sort_keys=True, separators=(",", ":"))
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, checkpoint_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        return checkpoint

    @staticmethod
    def _file_identity(blob_path: Path, ref: StoredArtifactRef) -> dict[str, int]:
        try:
            file_stat = blob_path.stat(follow_symlinks=False)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"Artifact not found: {ref.content_hash}") from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise ArtifactIntegrityError("Artifact blob is not a regular file")
        return {
            "device": file_stat.st_dev,
            "inode": file_stat.st_ino,
            "size": file_stat.st_size,
            "mtime_ns": file_stat.st_mtime_ns,
            "ctime_ns": file_stat.st_ctime_ns,
        }

    @staticmethod
    def _checkpoint_matches(
        checkpoint: dict[str, object],
        identity: dict[str, int],
        ref: StoredArtifactRef,
    ) -> bool:
        if checkpoint.get("format") != 1:
            return False
        if checkpoint.get("content_hash") != ref.content_hash:
            return False
        if checkpoint.get("size_bytes") != ref.size_bytes:
            return False
        if identity["size"] != ref.size_bytes:
            return False
        return all(checkpoint.get(key) == value for key, value in identity.items())

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
