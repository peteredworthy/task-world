"""Export one canonical graph stream as a sanitized, hash-manifested fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from orchestrator.graph import EventEnvelope


EXPORT_SCHEMA = "orchestrator.graph.canonical-event-export.v1"
_LOCAL_HOME = re.compile(r"/Users/([^/\s`'\"]+)")


def _sanitized_local_home(match: re.Match[str]) -> str:
    """Replace only a macOS home username without changing its byte length."""
    username = match.group(1)
    pseudonym = ("user" + ("x" * len(username)))[: len(username)]
    return f"/Users/{pseudonym}"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"


def _sanitize(
    value: Any,
    *,
    position: int,
    path: tuple[str, ...] = (),
) -> tuple[Any, list[dict[str, Any]]]:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        changes: list[dict[str, Any]] = []
        for key, item in value.items():
            sanitized, nested = _sanitize(item, position=position, path=(*path, key))
            output[key] = sanitized
            changes.extend(nested)
        return output, changes
    if isinstance(value, list):
        output_list: list[Any] = []
        changes = []
        for index, item in enumerate(value):
            sanitized, nested = _sanitize(
                item,
                position=position,
                path=(*path, str(index)),
            )
            output_list.append(sanitized)
            changes.extend(nested)
        return output_list, changes
    if not isinstance(value, str):
        return value, []
    sanitized, replacement_count = _LOCAL_HOME.subn(_sanitized_local_home, value)
    applied = ["local_home_username"] if replacement_count else []
    if sanitized == value:
        return value, []
    return sanitized, [
        {
            "position": position,
            "json_pointer": "/"
            + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path),
            "rules": applied,
            "source_value_sha256": _sha256(value),
            "exported_value_sha256": _sha256(sanitized),
            "source_utf8_bytes": len(value.encode()),
            "exported_utf8_bytes": len(sanitized.encode()),
        }
    ]


def export_fixture(history_path: Path, output_path: Path, run_id: str) -> None:
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        wrapper = json.loads(line)
        if wrapper.get("aggregate_id") != f"graph:{run_id}":
            continue
        event = wrapper.get("payload")
        if not isinstance(event, dict):
            raise ValueError("selected graph history row has no event envelope payload")
        EventEnvelope.model_validate(event)
        selected.append((wrapper, event))
    positions = [event["position"] for _, event in selected]
    if positions != list(range(1, 456)):
        raise ValueError(f"expected exact positions 1..455, got {positions[:1]}..{positions[-1:]}")

    exported_events: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    sanitizations: list[dict[str, Any]] = []
    source_events: list[dict[str, Any]] = []
    source_wrappers: list[dict[str, Any]] = []
    for wrapper, source_event in selected:
        position = int(source_event["position"])
        exported_event, changes = _sanitize(source_event, position=position)
        assert isinstance(exported_event, dict)
        EventEnvelope.model_validate(exported_event)
        source_events.append(source_event)
        source_wrappers.append(wrapper)
        exported_events.append(exported_event)
        sanitizations.extend(changes)
        entries.append(
            {
                "position": position,
                "event_id": source_event["event_id"],
                "event_type": source_event["event_type"],
                "source_event_sha256": _sha256(source_event),
                "source_payload_sha256": _sha256(source_event["payload"]),
                "exported_event_sha256": _sha256(exported_event),
                "exported_payload_sha256": _sha256(exported_event["payload"]),
            }
        )

    document = {
        "schema": EXPORT_SCHEMA,
        "source": {
            "kind": "local_secondary_journal_read_only",
            "path": ".orchestrator/state/history.jsonl",
            "aggregate_id": f"graph:{run_id}",
            "run_id": run_id,
            "event_count": len(source_events),
            "first_graph_position": 1,
            "last_graph_position": 455,
            "first_journal_position": selected[0][0].get("position"),
            "last_journal_position": selected[-1][0].get("position"),
            "last_source_timestamp": selected[-1][0].get("timestamp"),
            "source_event_stream_sha256": _sha256(source_events),
            "source_wrapper_stream_sha256": _sha256(source_wrappers),
        },
        "sanitization": {
            "policy": "replace only the local home-directory username in free-form text",
            "replacement_preserves_utf8_length": True,
            "change_count": len(sanitizations),
            "changes": sanitizations,
        },
        "manifest": {
            "event_count": len(exported_events),
            "positions_sha256": _sha256(positions),
            "event_types_sha256": _sha256([event["event_type"] for event in exported_events]),
            "exported_event_stream_sha256": _sha256(exported_events),
            "entries": entries,
        },
        "events": exported_events,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    export_fixture(args.history, args.output, args.run_id)


if __name__ == "__main__":
    main()
