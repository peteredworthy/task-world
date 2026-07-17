from __future__ import annotations

import os
import asyncio
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.api.auth import AuthConfig, create_token
from orchestrator.artifacts import (
    ArtifactGarbageCollectionError,
    ArtifactGarbageCollector,
    ArtifactNotFoundError,
    ArtifactRootLock,
    FilesystemArtifactStore,
    StoredArtifactRef,
)
from orchestrator.db import SqliteEventStore, init_db
from orchestrator.config.global_config import GlobalConfig, PathsConfig
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state import Run
from orchestrator.state import RunNotFoundError
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
        service = await app.state.service_factory(session)  # type: ignore[union-attr]
        try:
            await service.get_run(run_id)
        except RunNotFoundError:
            await service.create_run(
                Run(
                    id=run_id,
                    repo_name="artifact-api",
                    worktree_path=str(app.state.artifact_test_worktree),  # type: ignore[union-attr]
                )
            )
        await GraphEventStore(session).append_events(run_id, 0, [event])
        await session.commit()


@pytest.fixture
async def artifact_client(
    tmp_path: Path,
) -> tuple[AsyncClient, object, FilesystemArtifactStore, str]:
    auth_config = AuthConfig(auth_disabled=False, jwt_secret="artifact-api-secret")
    project = tmp_path / "project"
    project.mkdir()
    _init_repo(project)
    worktree = tmp_path / "worktrees" / "artifact-api"
    worktree.parent.mkdir()
    _git(["worktree", "add", "-b", "artifact-api", str(worktree)], cwd=project)
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
        artifact_project_root=project,
    )
    app.state.artifact_test_worktree = worktree
    app.state.artifact_test_project = project
    await init_db(app.state.engine)
    store = FilesystemArtifactStore(project / ".orchestrator" / "artifacts")
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
    artifact_root = app.state.artifact_test_project / ".orchestrator" / "artifacts" / "sha256"  # type: ignore[union-attr]
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


@pytest.mark.asyncio
async def test_multi_project_artifact_read_and_delete_gc_use_the_run_project_root(
    tmp_path: Path,
) -> None:
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    _init_repo(project_a)
    _init_repo(project_b)
    run_worktree = tmp_path / "worktrees" / "project-b-run"
    run_worktree.parent.mkdir()
    _git(["worktree", "add", "-b", "project-b-run", str(run_worktree)], cwd=project_b)
    auth_config = AuthConfig(auth_disabled=False, jwt_secret="multi-project-artifact-secret")
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
        artifact_project_root=project_a,
    )
    await init_db(app.state.engine)
    project_b_store = FilesystemArtifactStore(project_b / ".orchestrator" / "artifacts")
    project_a_store = FilesystemArtifactStore(project_a / ".orchestrator" / "artifacts")
    ref = await project_b_store.put(b"project-b artifact", media_type="text/plain")
    project_a_orphan = await project_a_store.put(b"project-a orphan", media_type="text/plain")
    project_b_orphan = await project_b_store.put(b"project-b orphan", media_type="text/plain")
    now = datetime.now(UTC)
    for root, orphan in ((project_a, project_a_orphan), (project_b, project_b_orphan)):
        blob = (
            root
            / ".orchestrator"
            / "artifacts"
            / "sha256"
            / orphan.content_hash[7:9]
            / orphan.content_hash[9:]
        )
        old = (now - timedelta(days=2)).timestamp()
        os.utime(blob, (old, old))
    async with app.state.session_factory() as session:
        service = await app.state.service_factory(session)
        await service.create_run(
            Run(id="project-b-run", repo_name="project-b", worktree_path=str(run_worktree))
        )
        await session.commit()
    await _seed_reference(app, "project-b-run", ref)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    try:
        response = await client.get(
            f"/api/runs/project-b-run/artifacts/{ref.content_hash.removeprefix('sha256:')}?offset=8&limit=1",
            headers={"Authorization": f"Bearer {create_token(auth_config)}"},
        )
        assert response.status_code == 206
        assert response.content == b"b"
        async with app.state.session_factory() as session:
            service = await app.state.service_factory(session)
            await service.delete_run("project-b-run")
            await session.commit()
        assert await project_a_store.read(project_a_orphan) == b"project-a orphan"
        with pytest.raises(ArtifactNotFoundError):
            await project_b_store.read(project_b_orphan)
    finally:
        await client.aclose()
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_deduplicated_publication_blocks_gc_until_real_event_append(
    artifact_client: tuple[AsyncClient, object, FilesystemArtifactStore, str],
) -> None:
    _, app, store, _ = artifact_client
    root = app.state.artifact_test_project / ".orchestrator" / "artifacts"  # type: ignore[union-attr]
    ref = await store.put(b"deduplicated durable output", media_type="text/plain")
    now = datetime(2026, 1, 2, tzinfo=UTC)
    blob = root / "sha256" / ref.content_hash[7:9] / ref.content_hash[9:]
    old = (now - timedelta(days=2)).timestamp()
    os.utime(blob, (old, old))

    async def load_events() -> list[EventEnvelope]:
        async with app.state.session_factory() as session:  # type: ignore[union-attr]
            return await GraphEventStore(session).read_run("publication-run")

    async with ArtifactRootLock(root).publish():
        assert await store.put(b"deduplicated durable output", media_type="text/plain") == ref
        collecting = asyncio.create_task(
            ArtifactGarbageCollector(root, grace_seconds=0).collect_after_mark(load_events, now)
        )
        await asyncio.sleep(0)
        assert not collecting.done()
        await _seed_reference(app, "publication-run", ref)

    assert await collecting == frozenset()
    assert await store.read(ref) == b"deduplicated durable output"


@pytest.mark.asyncio
async def test_removed_linked_worktree_keeps_api_and_gc_on_main_project_cas(tmp_path: Path) -> None:
    repos = tmp_path / "repos"
    repos.mkdir()
    project = repos / "project-b"
    project.mkdir()
    _init_repo(project)
    worktree = tmp_path / "worktrees" / "run"
    worktree.parent.mkdir()
    _git(["worktree", "add", "-b", "artifact-run", str(worktree)], cwd=project)
    secret = "removed-worktree-secret"
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=secret,
        global_config=GlobalConfig(paths=PathsConfig(repos_dir=str(repos))),
        artifact_project_root=project,
    )
    await init_db(app.state.engine)
    store = FilesystemArtifactStore(project / ".orchestrator" / "artifacts")
    retained = await store.put(b"retained", media_type="text/plain")
    orphan = await store.put(b"orphan", media_type="text/plain")
    orphan_path = (
        project
        / ".orchestrator"
        / "artifacts"
        / "sha256"
        / orphan.content_hash[7:9]
        / orphan.content_hash[9:]
    )
    old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(orphan_path, (old, old))
    async with app.state.session_factory() as session:
        service = await app.state.service_factory(session)
        for run_id in ("delete-me", "retain-me"):
            await service.create_run(
                Run(id=run_id, repo_name="project-b", worktree_path=str(worktree))
            )
        await session.commit()
    await _seed_reference(app, "retain-me", retained)
    _git(["worktree", "remove", "--force", str(worktree)], cwd=project)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        response = await client.get(
            f"/api/runs/retain-me/artifacts/{retained.content_hash.removeprefix('sha256:')}",
            headers={
                "Authorization": f"Bearer {create_token(AuthConfig(auth_disabled=False, jwt_secret=secret))}"
            },
        )
        assert response.status_code == 206
        assert response.content == b"retained"
        async with app.state.session_factory() as session:
            service = await app.state.service_factory(session)
            await service.delete_run("delete-me")
            await session.commit()
        assert await store.read(retained) == b"retained"
        with pytest.raises(ArtifactNotFoundError):
            await store.read(orphan)
    finally:
        await client.aclose()
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_unavailable_provisioned_project_raises_after_durable_delete_tombstone(
    tmp_path: Path,
) -> None:
    repos = tmp_path / "repos"
    repos.mkdir()
    project = repos / "project"
    project.mkdir()
    _init_repo(project)
    worktree = tmp_path / "worktrees" / "run"
    worktree.parent.mkdir()
    _git(["worktree", "add", "-b", "unavailable-run", str(worktree)], cwd=project)
    app = create_app(
        db_path=":memory:",
        global_config=GlobalConfig(paths=PathsConfig(repos_dir=str(repos))),
        artifact_project_root=project,
    )
    await init_db(app.state.engine)
    try:
        async with app.state.session_factory() as session:
            service = await app.state.service_factory(session)
            await service.create_run(
                Run(id="unavailable-run", repo_name="project", worktree_path=str(worktree))
            )
            await session.commit()
        _git(["worktree", "remove", "--force", str(worktree)], cwd=project)
        shutil.rmtree(project)
        async with app.state.session_factory() as session:
            service = await app.state.service_factory(session)
            with pytest.raises(
                ArtifactGarbageCollectionError, match="cannot resolve artifact root"
            ):
                await service.delete_run("unavailable-run")
            events = await SqliteEventStore(session).get_stream("unavailable-run")
        assert [event.event_type for event in events].count("run_deleted") == 1
    finally:
        await app.state.engine.dispose()
