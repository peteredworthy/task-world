from pathlib import Path

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.graph import StoredArtifactRef
from orchestrator.graph_runtime import hydrate_artifact_excerpt
from orchestrator.graph_runtime.prompts import _tail_only_prompt_record_payload


@pytest.mark.asyncio
async def test_explicit_hydration_decodes_and_bounds_artifact_excerpt(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = await store.put(b"prefix\nabcdef", media_type="text/plain", encoding="utf-8")

    excerpt = await hydrate_artifact_excerpt(store, ref, max_chars=6)

    assert excerpt == "prefix"


@pytest.mark.asyncio
async def test_explicit_hydration_requires_a_typed_reference(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    malformed_ref = StoredArtifactRef.model_construct(
        artifact_id="sha256:" + "0" * 64,
        content_hash="sha256:" + "0" * 64,
        size_bytes=0,
        media_type="text/plain",
        encoding="utf-8",
        storage_uri="artifact://sha256/" + "0" * 64,
    )

    with pytest.raises(ValueError, match="max_chars"):
        await hydrate_artifact_excerpt(store, malformed_ref, max_chars=0)


def test_default_prompt_payload_keeps_check_output_tails_without_references() -> None:
    record = {
        "record_type": "check_result",
        "value": {
            "stdout_tail": "last stdout",
            "stdout_ref": {"content_hash": "sha256:" + "a" * 64},
            "stderr_tail": "last stderr",
            "stderr_ref": {"content_hash": "sha256:" + "b" * 64},
        },
    }

    prompt_payload = _tail_only_prompt_record_payload(record)

    assert prompt_payload["value"] == {
        "stdout_tail": "last stdout",
        "stderr_tail": "last stderr",
    }
    assert record["value"]["stdout_ref"] is not None
