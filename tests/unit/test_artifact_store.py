import hashlib
from pathlib import Path

import pytest

from orchestrator.artifacts import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    FilesystemArtifactStore,
)
from orchestrator.graph import StoredArtifactRef


@pytest.mark.asyncio
async def test_put_deduplicates_content_and_returns_opaque_reference(tmp_path: Path) -> None:
    store_root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(store_root)
    content = b"same content"

    first = await store.put(content, media_type="text/plain", encoding="utf-8")
    digest = first.content_hash.removeprefix("sha256:")
    blob_path = store_root / "sha256" / digest[:2] / digest[2:]
    first_stat = blob_path.stat()
    second = await store.put(content, media_type="text/plain", encoding="utf-8")

    assert first == second
    assert first.artifact_id == first.content_hash
    assert first.content_hash == f"sha256:{hashlib.sha256(content).hexdigest()}"
    assert first.storage_uri == f"artifact://sha256/{hashlib.sha256(content).hexdigest()}"
    assert not first.storage_uri.startswith("/")
    assert blob_path.stat().st_ino == first_stat.st_ino
    assert await store.read(first) == content


@pytest.mark.asyncio
async def test_store_uses_private_hash_directories(tmp_path: Path) -> None:
    store_root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(store_root)

    ref = await store.put(b"private", media_type="application/octet-stream")
    digest = ref.content_hash.removeprefix("sha256:")

    assert store_root.stat().st_mode & 0o777 == 0o700
    assert (store_root / "sha256").stat().st_mode & 0o777 == 0o700
    assert (store_root / "sha256" / digest[:2]).stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_read_rejects_missing_and_corrupt_artifacts(tmp_path: Path) -> None:
    store_root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(store_root)
    content = b"integrity matters"
    ref = await store.put(content, media_type="text/plain")
    digest = ref.content_hash.removeprefix("sha256:")
    blob_path = store_root / "sha256" / digest[:2] / digest[2:]

    blob_path.unlink()
    with pytest.raises(ArtifactNotFoundError):
        await store.read(ref)

    await store.put(content, media_type="text/plain")
    blob_path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError):
        await store.read(ref)

    await store.put(content, media_type="text/plain")
    blob_path.write_bytes(b"x" * len(content))
    with pytest.raises(ArtifactIntegrityError):
        await store.read(ref)


@pytest.mark.asyncio
async def test_store_rejects_traversal_reference(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    malformed = StoredArtifactRef.model_construct(
        artifact_id="sha256:../escape",
        content_hash="sha256:../escape",
        size_bytes=0,
        media_type="text/plain",
        encoding=None,
        storage_uri="artifact://sha256/../escape",
    )

    with pytest.raises(ArtifactIntegrityError):
        await store.read(malformed)


@pytest.mark.asyncio
async def test_delete_removes_artifact(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = await store.put(b"delete me", media_type="text/plain")

    await store.delete(ref)

    with pytest.raises(ArtifactNotFoundError):
        await store.read(ref)
