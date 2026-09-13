"""Small, read-only diagnostic for failed graph runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class _BoundaryModel(BaseModel):
    """Strictly type known API fields while tolerating additive response fields."""

    model_config = ConfigDict(extra="ignore", strict=True)


class _RunResponse(_BoundaryModel):
    id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    is_graph_backed: bool = False
    pause_reason: str | None = None
    last_error: str | None = None


class _CollectionMetadata(_BoundaryModel):
    truncated: bool = False


class _GraphResponse(_BoundaryModel):
    run_id: str | None = None
    node_states: dict[str, str]
    truncated: bool = False
    collection_meta: dict[str, _CollectionMetadata] = Field(default_factory=dict)

    def node_states_are_complete(self) -> bool:
        node_metadata = self.collection_meta.get("node_states")
        return not self.truncated and not (node_metadata is not None and node_metadata.truncated)


class _EventPayload(_BoundaryModel):
    node_id: str | None = None
    new_state: str | None = None
    reason: str | None = None


class _NodeEvent(_BoundaryModel):
    event_id: str | None = None
    position: int | None = Field(default=None, ge=0)
    event_type: str = Field(min_length=1)
    node_id: str | None = None
    payload: _EventPayload = Field(default_factory=_EventPayload)


def _empty_node_events() -> list[_NodeEvent]:
    return []


class _NodeDetail(_BoundaryModel):
    run_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    callback_history: list[_NodeEvent] = Field(default_factory=_empty_node_events)
    events: list[_NodeEvent] = Field(default_factory=_empty_node_events)


_GraphResponse.model_rebuild(_types_namespace={"_CollectionMetadata": _CollectionMetadata})
_NodeEvent.model_rebuild(_types_namespace={"_EventPayload": _EventPayload})
_NodeDetail.model_rebuild(_types_namespace={"_NodeEvent": _NodeEvent})


class FailureDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    reason: str | None = None
    event_position: int | None = Field(default=None, ge=0)


class RunDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    pause_reason: str | None = None
    summary_error: str | None = None
    failures: tuple[FailureDetail, ...] = ()
    unavailable: tuple[str, ...] = ()

    @field_validator("unavailable")
    @classmethod
    def unique_unavailable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))


RunDiagnostic.model_rebuild(_types_namespace={"FailureDetail": FailureDetail})


def _failed_node_ids(states: dict[str, str]) -> list[str]:
    return sorted(node_id for node_id, state in states.items() if state == "failed")


def _failure(node_id: str, detail: _NodeDetail) -> FailureDetail:
    candidates: list[tuple[int, int, str, int | None]] = []
    seen_ids: set[str] = set()
    seen_positions: set[int] = set()
    for index, event in enumerate((*detail.callback_history, *detail.events)):
        if event.event_type != "agent_died" and not (
            event.event_type == "node_state_changed" and event.payload.new_state == "failed"
        ):
            continue
        if (event.payload.node_id or event.node_id) != node_id:
            continue
        if (event.event_id is not None and event.event_id in seen_ids) or (
            event.position is not None and event.position in seen_positions
        ):
            continue
        if event.event_id is not None:
            seen_ids.add(event.event_id)
        if event.position is not None:
            seen_positions.add(event.position)
        reason = event.payload.reason
        if reason is not None and reason.strip():
            candidates.append(
                (
                    event.position if event.position is not None else 2**63,
                    index,
                    reason,
                    event.position,
                )
            )
    if not candidates:
        return FailureDetail(node_id=node_id)
    _, _, reason, position = min(candidates)
    return FailureDetail(node_id=node_id, reason=reason, event_position=position)


def build_diagnostic(
    run: dict[str, Any] | _RunResponse,
    graph: dict[str, Any] | _GraphResponse | None,
    node_details: tuple[dict[str, Any] | _NodeDetail, ...],
    unavailable: tuple[str, ...] = (),
) -> RunDiagnostic:
    """Build a diagnostic from strictly validated public API response data."""
    run_response = run if isinstance(run, _RunResponse) else _RunResponse.model_validate(run)
    graph_response = (
        graph
        if isinstance(graph, _GraphResponse)
        else _GraphResponse.model_validate(graph)
        if graph is not None
        else None
    )
    failed = _failed_node_ids(graph_response.node_states) if graph_response else []
    by_id: dict[str, _NodeDetail] = {}
    for raw in node_details:
        detail = raw if isinstance(raw, _NodeDetail) else _NodeDetail.model_validate(raw)
        if detail.node_id not in failed or detail.run_id != run_response.id:
            raise ValueError("node detail does not belong to this run's failed nodes")
        if detail.node_id in by_id:
            raise ValueError(f"duplicate node detail: {detail.node_id}")
        by_id[detail.node_id] = detail
    failures = tuple(
        _failure(node_id, by_id[node_id]) if node_id in by_id else FailureDetail(node_id=node_id)
        for node_id in failed
    )
    missing = tuple(f"node:{failure.node_id}" for failure in failures if failure.reason is None)
    return RunDiagnostic(
        run_id=run_response.id,
        status=run_response.status,
        pause_reason=run_response.pause_reason,
        summary_error=run_response.last_error,
        failures=failures,
        unavailable=tuple(dict.fromkeys((*unavailable, *missing))),
    )


MAX_RESPONSE_BYTES = 2_000_000
MAX_NODE_DETAILS = 10


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds 2 MB limit")
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


async def _read(run_id: str, base_url: str) -> tuple[RunDiagnostic, bool]:
    timeout = httpx.Timeout(10.0, connect=3.0, read=7.0, write=3.0, pool=3.0)
    unavailable: list[str] = []
    async with httpx.AsyncClient(
        base_url=base_url, timeout=timeout, follow_redirects=False
    ) as client:
        run = _RunResponse.model_validate(
            await _get_json(client, f"/api/runs/{quote(run_id, safe='')}")
        )
        if run.id != run_id:
            raise ValueError("run response does not match requested run")
        if not run.is_graph_backed:
            return build_diagnostic(run, None, ()), True
        try:
            graph = _GraphResponse.model_validate(
                await _get_json(client, f"/api/runs/{quote(run_id, safe='')}/graph")
            )
            if graph.run_id is not None and graph.run_id != run_id:
                raise ValueError("graph response does not match requested run")
        except (
            ValueError,
            TypeError,
            ValidationError,
            json.JSONDecodeError,
            httpx.HTTPError,
        ) as error:
            unavailable.append(f"graph:{type(error).__name__}")
            return build_diagnostic(run, None, (), tuple(unavailable)), False
        if not graph.node_states_are_complete():
            unavailable.append("graph:node_states_truncated")
        failed = _failed_node_ids(graph.node_states)
        details: list[_NodeDetail] = []
        for node_id in failed[:MAX_NODE_DETAILS]:
            try:
                detail = _NodeDetail.model_validate(
                    await _get_json(
                        client,
                        f"/api/runs/{quote(run_id, safe='')}/graph/nodes/{quote(node_id, safe='')}",
                    )
                )
                if detail.run_id != run_id or detail.node_id != node_id:
                    raise ValueError("node response does not match requested run/node")
                details.append(detail)
            except (ValueError, TypeError, ValidationError, json.JSONDecodeError, httpx.HTTPError):
                unavailable.append(f"node:{node_id}")
        unavailable.extend(f"node:{node_id}" for node_id in failed[MAX_NODE_DETAILS:])
        diagnostic = build_diagnostic(run, graph, tuple(details), tuple(unavailable))
        return diagnostic, not diagnostic.unavailable


def _base_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL must be an absolute HTTP(S) URL without query or fragment")
    return value.rstrip("/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args(argv)
    try:
        run_id = str(UUID(args.run_id))
        diagnostic, complete = asyncio.run(_read(run_id, _base_url(args.base_url)))
    except (ValueError, TypeError, ValidationError, httpx.HTTPError, json.JSONDecodeError) as error:
        print(f"diagnostic unavailable: {error}", file=sys.stderr)
        return 2
    print(diagnostic.model_dump_json())
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
