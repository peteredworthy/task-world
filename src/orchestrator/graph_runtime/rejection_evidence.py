"""Protected, bounded reproduction evidence for rejected graph patches."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import ArtifactStore
from orchestrator.db import EventV2Model
from orchestrator.graph import (
    BoundaryValidationError,
    Clock,
    EventEnvelope,
    IdGenerator,
    PatchCommandContext,
    StoredArtifactRef,
)
from orchestrator.graph_runtime.controller import GraphController
from orchestrator.graph_runtime.store import GraphEventStore

REJECTION_EVIDENCE_MEDIA_TYPE = "application/vnd.orchestrator.rejection-evidence+json"
MAX_REJECTION_EVIDENCE_BYTES = 512 * 1024
MAX_REJECTION_PREFIX_EVENTS = 4_096
MAX_SOURCE_BOUNDARY_BYTES = 2 * 1024 * 1024
_GRAPH_PREFIX_BYTES = 384 * 1024
_REQUEST_RESPONSE_BYTES = 96 * 1024
_GRAPH_READ_BATCH = 32
_SOURCE_PATHS = ("src/orchestrator", "routines", "pyproject.toml", "uv.lock")

RejectionEvidenceClassification = Literal[
    "exact_replay",
    "evidence_oversize",
    "graph_prefix_incomplete",
    "source_boundary_oversize",
]


class SourceIdentity(BaseModel):
    """Git and dirty-worktree identity observed at the rejected request boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    head_commit: str
    status_sha256: str
    tracked_diff_sha256: str
    untracked_content_sha256: str
    complete: bool


class RejectionEvidencePublicRef(BaseModel):
    """Safe metadata suitable for graph events and public API projections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: StoredArtifactRef
    content_hash: str
    size_bytes: int = Field(ge=0)
    classification: RejectionEvidenceClassification
    replayable: bool


class RejectionEvidenceArtifact(BaseModel):
    """Private CAS payload. Caller-controlled request text never enters public events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    classification: RejectionEvidenceClassification
    replayable: bool
    run_id: str
    proposed_by_node_id: str
    actor_role: str
    graph_position: int = Field(ge=0)
    graph_prefix_sha256: str
    graph_prefix_complete: bool
    source_identity: SourceIdentity
    request_sha256: str
    response_sha256: str
    request_size_bytes: int = Field(ge=0)
    response_size_bytes: int = Field(ge=0)
    request_response_complete: bool
    request: dict[str, Any] | None = None
    response: str | None = None
    graph_prefix: tuple[EventEnvelope, ...] | None = None


class RejectionReplayResult(BaseModel):
    """Result of a deterministic rejection replay in an isolated store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reproduced: Literal[True] = True
    response: str
    graph_prefix_sha256: str
    source_identity: SourceIdentity


class ReliablePlanRejectionRecorder:
    """Production callable used by the controller before persisting a rejection."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        artifact_store: ArtifactStore,
        orchestrator_source_path: str | Path,
    ) -> None:
        self._session_factory = session_factory
        self._artifact_store = artifact_store
        self._orchestrator_source_path = orchestrator_source_path

    async def __call__(
        self,
        run_id: str,
        graph_position: int,
        request: dict[str, object],
        context: PatchCommandContext,
        planned_events: list[EventEnvelope],
    ) -> dict[str, object]:
        response = render_rejected_graph_patch_response(
            planned_events,
            cast(dict[str, Any], request),
        )
        if response is None:
            raise BoundaryValidationError("rejection recorder received no rejected event")
        public_ref = await capture_reliable_plan_rejection_evidence(
            session_factory=self._session_factory,
            artifact_store=self._artifact_store,
            worktree_path=self._orchestrator_source_path,
            run_id=run_id,
            proposed_by_node_id=context.proposed_by_node_id,
            actor_role=context.actor_role,
            graph_position=graph_position,
            request=cast(dict[str, Any], request),
            response=response,
        )
        return public_ref.model_dump(mode="json")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _run_git_bounded(root: Path, arguments: list[str]) -> tuple[bytes, bool]:
    process = subprocess.Popen(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    chunks: list[bytes] = []
    observed = 0
    complete = True
    while True:
        chunk = process.stdout.read(64 * 1024)
        if not chunk:
            break
        observed += len(chunk)
        if observed > MAX_SOURCE_BOUNDARY_BYTES:
            complete = False
            process.kill()
            break
        chunks.append(chunk)
    process.wait()
    return b"".join(chunks), complete and process.returncode == 0


def _hash_files_bounded(root: Path, paths: bytes) -> tuple[str, bool]:
    digest = hashlib.sha256()
    observed = 0
    for raw_path in paths.split(b"\0"):
        if not raw_path:
            continue
        digest.update(len(raw_path).to_bytes(8, "big"))
        digest.update(raw_path)
        path = root / os.fsdecode(raw_path)
        try:
            if not path.is_file():
                digest.update((0).to_bytes(8, "big"))
                continue
            size = path.stat().st_size
            observed += len(raw_path) + size
            if observed > MAX_SOURCE_BOUNDARY_BYTES:
                return f"sha256:{digest.hexdigest()}", False
            digest.update(size.to_bytes(8, "big"))
            with path.open("rb") as stream:
                while chunk := stream.read(64 * 1024):
                    digest.update(chunk)
        except OSError:
            return f"sha256:{digest.hexdigest()}", False
    return f"sha256:{digest.hexdigest()}", True


def _capture_source_identity_sync(root: Path) -> SourceIdentity:
    head, head_complete = _run_git_bounded(root, ["rev-parse", "HEAD"])
    status, status_complete = _run_git_bounded(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *_SOURCE_PATHS,
        ],
    )
    tracked_diff, diff_complete = _run_git_bounded(
        root,
        ["diff", "--binary", "--no-ext-diff", "HEAD", "--", *_SOURCE_PATHS],
    )
    untracked, untracked_complete = _run_git_bounded(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *_SOURCE_PATHS],
    )
    untracked_digest, content_complete = _hash_files_bounded(root, untracked)
    return SourceIdentity(
        head_commit=head.decode("ascii", errors="replace").strip() or "unavailable",
        status_sha256=_sha256(status),
        tracked_diff_sha256=_sha256(tracked_diff),
        untracked_content_sha256=untracked_digest,
        complete=all(
            (head_complete, status_complete, diff_complete, untracked_complete, content_complete)
        ),
    )


async def capture_source_identity(worktree_path: str | Path) -> SourceIdentity:
    """Capture HEAD plus bounded staged, unstaged, and untracked source identity."""
    try:
        return await asyncio.to_thread(_capture_source_identity_sync, Path(worktree_path))
    except (OSError, subprocess.SubprocessError):
        unavailable = _sha256(b"")
        return SourceIdentity(
            head_commit="unavailable",
            status_sha256=unavailable,
            tracked_diff_sha256=unavailable,
            untracked_content_sha256=unavailable,
            complete=False,
        )


def resolve_orchestrator_source_root() -> Path:
    """Resolve the checkout containing the executing orchestrator package."""
    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "orchestrator"
        ).is_dir():
            return candidate
    # Installed distributions may not retain repository metadata. The package
    # parent still yields an explicit incomplete source identity rather than
    # falsely identifying a target run checkout as controller source.
    return module_path.parent.parent


def _graph_prefix_hash(events: tuple[EventEnvelope, ...]) -> str:
    return _sha256(_canonical_json([event.model_dump(mode="json") for event in events]))


async def _read_bounded_graph_prefix(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    graph_position: int,
) -> tuple[EventEnvelope, ...] | None:
    if graph_position > MAX_REJECTION_PREFIX_EVENTS:
        return None
    events: list[EventEnvelope] = []
    encoded_bytes = 2
    next_position = 1
    async with session_factory() as session:
        store = GraphEventStore(session)
        while next_position <= graph_position:
            batch = await store.read_run(
                run_id,
                from_position=next_position,
                limit=min(_GRAPH_READ_BATCH, graph_position - next_position + 1),
            )
            if not batch:
                return None
            for event in batch:
                if event.position != next_position:
                    return None
                encoded_bytes += len(_canonical_json(event.model_dump(mode="json"))) + 1
                if encoded_bytes > _GRAPH_PREFIX_BYTES:
                    return None
                events.append(event)
                next_position += 1
    return tuple(events) if len(events) == graph_position else None


async def capture_reliable_plan_rejection_evidence(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    artifact_store: ArtifactStore,
    worktree_path: str | Path,
    run_id: str,
    proposed_by_node_id: str,
    actor_role: str,
    graph_position: int,
    request: dict[str, Any],
    response: str,
) -> RejectionEvidencePublicRef:
    """Persist exact replay evidence when bounded, or a truthful omission manifest."""
    request_bytes = _canonical_json(request)
    response_bytes = response.encode("utf-8")
    source_identity = await capture_source_identity(worktree_path)
    classification: RejectionEvidenceClassification = "exact_replay"
    request_response_complete = len(request_bytes) + len(response_bytes) <= _REQUEST_RESPONSE_BYTES
    if not request_response_complete:
        classification = "evidence_oversize"
    graph_prefix: tuple[EventEnvelope, ...] | None = None
    graph_prefix = await _read_bounded_graph_prefix(session_factory, run_id, graph_position)
    if graph_prefix is None and classification == "exact_replay":
        classification = "graph_prefix_incomplete"
    if not source_identity.complete and classification == "exact_replay":
        classification = "source_boundary_oversize"

    prefix_hash = _graph_prefix_hash(graph_prefix or ())
    artifact = RejectionEvidenceArtifact(
        classification=classification,
        replayable=classification == "exact_replay",
        run_id=run_id,
        proposed_by_node_id=proposed_by_node_id,
        actor_role=actor_role,
        graph_position=graph_position,
        graph_prefix_sha256=prefix_hash,
        graph_prefix_complete=graph_prefix is not None,
        source_identity=source_identity,
        request_sha256=_sha256(request_bytes),
        response_sha256=_sha256(response_bytes),
        request_size_bytes=len(request_bytes),
        response_size_bytes=len(response_bytes),
        request_response_complete=request_response_complete,
        request=(request if request_response_complete else None),
        response=(response if request_response_complete else None),
        graph_prefix=graph_prefix,
    )
    content = _canonical_json(artifact.model_dump(mode="json"))
    if len(content) > MAX_REJECTION_EVIDENCE_BYTES:
        artifact = artifact.model_copy(
            update={
                "classification": "evidence_oversize",
                "replayable": False,
                "graph_prefix": None,
                "graph_prefix_complete": False,
            }
        )
        content = _canonical_json(artifact.model_dump(mode="json"))
        if len(content) > MAX_REJECTION_EVIDENCE_BYTES:
            artifact = artifact.model_copy(update={"request": None, "response": None})
            content = _canonical_json(artifact.model_dump(mode="json"))
    async with artifact_store.publication():
        ref = await artifact_store.put(
            content,
            media_type=REJECTION_EVIDENCE_MEDIA_TYPE,
            encoding="utf-8",
        )
    return RejectionEvidencePublicRef(
        artifact_ref=ref,
        content_hash=ref.content_hash,
        size_bytes=ref.size_bytes,
        classification=artifact.classification,
        replayable=artifact.replayable,
    )


def render_rejected_graph_patch_response(
    events: list[EventEnvelope],
    request: dict[str, Any],
    fallback_diagnostics: dict[str, Any] | None = None,
) -> str | None:
    """Render the stable safe response for a rejected controller result."""
    rejection = next(
        (
            event
            for event in events
            if event.event_type in {"graph_patch_rejected", "command_rejected"}
        ),
        None,
    )
    if rejection is None:
        return None
    reason = rejection.payload.get("reason") or "unknown rejection"
    patch_id = rejection.payload.get("patch_id", request.get("patch_id", "unknown"))
    event_diagnostics = rejection.payload.get("diagnostics")
    diagnostics = (
        cast(dict[str, Any], event_diagnostics)
        if isinstance(event_diagnostics, dict)
        else fallback_diagnostics
    )
    if diagnostics is not None:
        rendered = json.dumps(diagnostics, sort_keys=True, separators=(",", ":"))
        return (
            f"graph patch {patch_id} rejected: {reason}; graph_patch_rejected; "
            f"validation_diagnostics={rendered}"
        )
    return f"graph patch {patch_id} rejected: {reason}"


async def replay_reliable_plan_rejection(
    *,
    artifact_store: ArtifactStore,
    evidence_ref: StoredArtifactRef,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    clock: Clock,
    id_gen: IdGenerator,
    worktree_path: str | Path,
) -> RejectionReplayResult:
    """Restore captured authority into an empty store and reproduce its rejection."""
    content = await artifact_store.read(evidence_ref)
    artifact = RejectionEvidenceArtifact.model_validate_json(content)
    if not artifact.replayable or artifact.classification != "exact_replay":
        raise BoundaryValidationError(
            f"rejection evidence is non-replayable: {artifact.classification}"
        )
    if (
        not artifact.request_response_complete
        or not artifact.graph_prefix_complete
        or artifact.request is None
        or artifact.response is None
        or artifact.graph_prefix is None
    ):
        raise BoundaryValidationError("replayable rejection evidence is incomplete")
    if _sha256(_canonical_json(artifact.request)) != artifact.request_sha256:
        raise BoundaryValidationError("rejection request identity mismatch")
    if _sha256(artifact.response.encode("utf-8")) != artifact.response_sha256:
        raise BoundaryValidationError("rejection response identity mismatch")
    if _graph_prefix_hash(artifact.graph_prefix) != artifact.graph_prefix_sha256:
        raise BoundaryValidationError("rejection graph prefix identity mismatch")
    observed_source = await capture_source_identity(worktree_path)
    if observed_source != artifact.source_identity:
        raise BoundaryValidationError("rejection orchestrator source identity mismatch")

    async with isolated_session_factory() as session:
        store = GraphEventStore(session)
        graph_event_count = await session.scalar(
            select(func.count(EventV2Model.position)).where(
                EventV2Model.aggregate_id.like("graph:%")
            )
        )
        if int(graph_event_count or 0) != 0:
            raise BoundaryValidationError("isolated replay graph store is not empty")
        if artifact.graph_prefix:
            await store.append_events(artifact.run_id, 0, list(artifact.graph_prefix))
            await session.commit()
    isolated_controller = GraphController(
        isolated_session_factory,
        clock,
        id_gen,
        auto_dispatch=False,
    )
    result = await isolated_controller.handle_command(
        artifact.run_id,
        artifact.graph_position,
        "submit_patch",
        dict(artifact.request),
        context=PatchCommandContext(
            run_id=artifact.run_id,
            current_graph_position=artifact.graph_position,
            proposed_by_node_id=artifact.proposed_by_node_id,
            actor_role=artifact.actor_role,
        ),
    )
    response = render_rejected_graph_patch_response(result.events, artifact.request)
    if response is None or response != artifact.response:
        raise BoundaryValidationError("captured controller rejection was not reproduced")
    return RejectionReplayResult(
        response=response,
        graph_prefix_sha256=artifact.graph_prefix_sha256,
        source_identity=observed_source,
    )


__all__ = [
    "MAX_REJECTION_EVIDENCE_BYTES",
    "MAX_REJECTION_PREFIX_EVENTS",
    "REJECTION_EVIDENCE_MEDIA_TYPE",
    "RejectionEvidenceArtifact",
    "RejectionEvidencePublicRef",
    "RejectionReplayResult",
    "ReliablePlanRejectionRecorder",
    "SourceIdentity",
    "capture_reliable_plan_rejection_evidence",
    "capture_source_identity",
    "render_rejected_graph_patch_response",
    "resolve_orchestrator_source_root",
    "replay_reliable_plan_rejection",
]
