from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.api.auth import AuthConfig, create_token
from orchestrator.artifacts import FilesystemArtifactStore, StoredArtifactRef
from orchestrator.db import init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from tests.integration.git_helpers import _git, _init_repo
from tests.unit.graph_test_utils import canonical_event_payload


def _check_result_payload(ref: StoredArtifactRef) -> dict[str, object]:
    return {
        "record_id": "check-1",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "check-node",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "candidate-1",
        "task_region_id": "region-1",
        "attempt_number": 1,
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": "check-command",
            "command_text": "true",
            "command": {"id": "check-command", "cmd": "true", "timeout_seconds": 1},
            "worktree_path": "/tmp/worktree",
            "base_snapshot_id": "snapshot-1",
            "execution_id": "execution-1",
            "duration_ms": 1,
            "stdout_tail": "tail",
            "stdout_ref": ref.model_dump(mode="json"),
            "stderr_tail": "",
            "stderr_ref": None,
            "stdout_truncated": True,
            "stderr_truncated": False,
            "timeout_seconds": 1,
            "environment_policy": {"cwd": "/tmp/worktree", "env": "inherited"},
        },
    }


async def _seed_reference(app: object, run_id: str, ref: StoredArtifactRef) -> None:
    event = EventEnvelope(
        event_id="check-result-1",
        run_id=run_id,
        position=1,
        event_type="output_record_accepted",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload("output_record_accepted", _check_result_payload(ref)),
    )
    session_factory = app.state.session_factory  # type: ignore[union-attr]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, [event])
        await session.commit()


@pytest.fixture
async def artifact_client(
    tmp_path: Path,
) -> tuple[AsyncClient, object, FilesystemArtifactStore, str]:
    auth_config = AuthConfig(auth_disabled=False, jwt_secret="artifact-api-secret")
    app = create_app(db_path=":memory:", auth_disabled=False, jwt_secret=auth_config.jwt_secret)
    await init_db(app.state.engine)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    app.state.artifact_store = store
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    client = AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client, app, store, create_token(auth_config)
    finally:
        await client.aclose()
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_artifact_endpoint_requires_auth_and_run_reference(
    artifact_client: tuple[AsyncClient, object, FilesystemArtifactStore, str],
) -> None:
    client, app, store, token = artifact_client
    ref = await store.put(b"abcdefgh", media_type="text/plain", encoding="utf-8")
    await _seed_reference(app, "run-one", ref)
    digest = ref.content_hash.removeprefix("sha256:")

    unauthenticated = await client.get(f"/api/runs/run-one/artifacts/{digest}")
    unauthorized_run = await client.get(
        f"/api/runs/run-two/artifacts/{digest}", headers={"Authorization": f"Bearer {token}"}
    )
    authorized = await client.get(
        f"/api/runs/run-one/artifacts/{digest}?offset=2&limit=3",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unauthenticated.status_code == 401
    assert unauthorized_run.status_code == 404
    assert authorized.status_code == 206
    assert authorized.content == b"cde"
    assert authorized.headers["content-range"] == "bytes 2-4/8"


@pytest.mark.asyncio
async def test_artifact_endpoint_validates_range_and_hash(
    artifact_client: tuple[AsyncClient, object, FilesystemArtifactStore, str],
) -> None:
    client, app, store, token = artifact_client
    ref = await store.put(b"abcdefgh", media_type="text/plain", encoding="utf-8")
    await _seed_reference(app, "run-one", ref)
    digest = ref.content_hash.removeprefix("sha256:")
    headers = {"Authorization": f"Bearer {token}"}

    negative_offset = await client.get(
        f"/api/runs/run-one/artifacts/{digest}?offset=-1", headers=headers
    )
    zero_limit = await client.get(f"/api/runs/run-one/artifacts/{digest}?limit=0", headers=headers)
    excessive_limit = await client.get(
        f"/api/runs/run-one/artifacts/{digest}?limit=1048577", headers=headers
    )
    uppercase_hash = await client.get(
        f"/api/runs/run-one/artifacts/{digest.upper()}", headers=headers
    )

    assert negative_offset.status_code == 422
    assert zero_limit.status_code == 422
    assert excessive_limit.status_code == 422
    assert uppercase_hash.status_code == 422


@pytest.mark.asyncio
async def test_artifact_endpoint_reports_missing_and_integrity_failures(
    artifact_client: tuple[AsyncClient, object, FilesystemArtifactStore, str],
    tmp_path: Path,
) -> None:
    client, app, store, token = artifact_client
    missing_ref = await store.put(b"missing", media_type="text/plain", encoding="utf-8")
    corrupt_ref = await store.put(b"corrupt", media_type="text/plain", encoding="utf-8")
    await _seed_reference(app, "run-missing", missing_ref)
    await _seed_reference(app, "run-corrupt", corrupt_ref)
    missing_digest = missing_ref.content_hash.removeprefix("sha256:")
    corrupt_digest = corrupt_ref.content_hash.removeprefix("sha256:")
    artifact_root = tmp_path / "artifacts" / "sha256"
    (artifact_root / missing_digest[:2] / missing_digest[2:]).unlink()
    (artifact_root / corrupt_digest[:2] / corrupt_digest[2:]).write_bytes(b"tampered")
    headers = {"Authorization": f"Bearer {token}"}

    missing = await client.get(f"/api/runs/run-missing/artifacts/{missing_digest}", headers=headers)
    corrupt = await client.get(f"/api/runs/run-corrupt/artifacts/{corrupt_digest}", headers=headers)

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Artifact blob not found"}
    assert corrupt.status_code == 409
    assert corrupt.json() == {"detail": "Artifact blob failed integrity verification"}


@pytest.mark.asyncio
async def test_artifact_endpoint_rejects_ranges_at_or_past_eof_after_verification(
    artifact_client: tuple[AsyncClient, object, FilesystemArtifactStore, str],
) -> None:
    client, app, store, token = artifact_client
    ref = await store.put(b"abcdefgh", media_type="text/plain", encoding="utf-8")
    empty_ref = await store.put(b"", media_type="text/plain", encoding="utf-8")
    await _seed_reference(app, "run-eof", ref)
    await _seed_reference(app, "run-empty", empty_ref)
    digest = ref.content_hash.removeprefix("sha256:")
    empty_digest = empty_ref.content_hash.removeprefix("sha256:")
    headers = {"Authorization": f"Bearer {token}"}

    at_eof = await client.get(f"/api/runs/run-eof/artifacts/{digest}?offset=8", headers=headers)
    past_eof = await client.get(f"/api/runs/run-eof/artifacts/{digest}?offset=9", headers=headers)
    empty = await client.get(f"/api/runs/run-empty/artifacts/{empty_digest}", headers=headers)

    assert at_eof.status_code == 416
    assert at_eof.headers["content-range"] == "bytes */8"
    assert past_eof.status_code == 416
    assert past_eof.headers["content-range"] == "bytes */8"
    assert empty.status_code == 416
    assert empty.headers["content-range"] == "bytes */0"


@pytest.mark.asyncio
async def test_app_composes_artifacts_at_injected_main_project_root_from_non_project_cwd(
    tmp_path: Path,
) -> None:
    main_project = tmp_path / "main-project"
    main_project.mkdir()
    _init_repo(main_project)
    linked_worktree = tmp_path / "worktrees" / "artifact-api"
    linked_worktree.parent.mkdir()
    _git(["worktree", "add", "-b", "artifact-api", str(linked_worktree)], cwd=main_project)
    launch_directory = tmp_path / "not-a-project"
    launch_directory.mkdir()
    original_cwd = Path.cwd()
    os.chdir(launch_directory)
    try:
        app = create_app(db_path=":memory:", artifact_project_root=main_project)
    finally:
        os.chdir(original_cwd)

    try:
        ref = await app.state.artifact_store.put(b"root-proof", media_type="text/plain")
        digest = ref.content_hash.removeprefix("sha256:")

        assert (
            main_project / ".orchestrator" / "artifacts" / "sha256" / digest[:2] / digest[2:]
        ).exists()
        assert not (linked_worktree / ".orchestrator" / "artifacts").exists()
        assert not (launch_directory / ".orchestrator" / "artifacts").exists()
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_app_resolves_artifacts_at_main_project_root_from_linked_worktree_cwd(
    tmp_path: Path,
) -> None:
    main_project = tmp_path / "main-project"
    main_project.mkdir()
    _init_repo(main_project)
    linked_worktree = tmp_path / "worktrees" / "artifact-api"
    linked_worktree.parent.mkdir()
    _git(["worktree", "add", "-b", "artifact-api", str(linked_worktree)], cwd=main_project)
    original_cwd = Path.cwd()
    os.chdir(linked_worktree)
    try:
        app = create_app(db_path=":memory:")
    finally:
        os.chdir(original_cwd)

    try:
        ref = await app.state.artifact_store.put(b"implicit-root-proof", media_type="text/plain")
        digest = ref.content_hash.removeprefix("sha256:")

        assert (
            main_project / ".orchestrator" / "artifacts" / "sha256" / digest[:2] / digest[2:]
        ).exists()
        assert not (linked_worktree / ".orchestrator" / "artifacts").exists()
    finally:
        await app.state.engine.dispose()
