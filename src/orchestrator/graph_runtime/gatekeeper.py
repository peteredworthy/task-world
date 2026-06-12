"""Runtime adapters for LLM-backed residue classification.

This slice wires the protocol and event flow. ``ClaudeGatekeeperClassifier`` is
left as an import-isolated production stub: the eventual implementation should
follow ``orchestrator.runners.agents.claude_sdk`` credential conventions,
prompt only with ``ResidueMetadata`` fields, parse a verdict per path, and
return token/cost facts for the graph event stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from orchestrator.graph import (
    EventEnvelope,
    FileStateDeclaration,
    FileStatePolicy,
    FileStateTaxonomy,
    GatekeeperTaxonomy,
    project_pattern_library,
)


@dataclass(frozen=True)
class ResidueMetadata:
    path: str
    size_bytes: int | None
    entropy: float | None
    source: str
    prior_classification: str
    matched_rule: str
    record_id: str


@dataclass(frozen=True)
class GatekeeperVerdict:
    path: str
    classification: GatekeeperTaxonomy
    confidence: float
    rationale: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    wall_time_ms: int = 0

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "classification": self.classification,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost_usd": self.cost_usd,
            "wall_time_ms": self.wall_time_ms,
        }


class ResidueClassifier(Protocol):
    def classify(self, items: list[ResidueMetadata]) -> list[GatekeeperVerdict]: ...


class ClaudeGatekeeperClassifier:
    """Small-model classifier adapter placeholder.

    The adapter is intentionally not imported or constructed by default, so
    tests and replay never load an LLM SDK. Production wiring should inject this
    class only when explicit runner configuration requests it.
    """

    def __init__(self, model_id: str = "claude-haiku-4-5") -> None:
        self.model_id = model_id

    def classify(self, items: list[ResidueMetadata]) -> list[GatekeeperVerdict]:
        raise NotImplementedError(
            "Claude gatekeeper API wiring is deferred; inject a ResidueClassifier instead."
        )


def policy_with_pattern_library(
    events: list[EventEnvelope],
    base_policy: FileStatePolicy | None = None,
) -> FileStatePolicy:
    """Return a policy extended with deterministic pattern-library declarations."""
    active = base_policy or FileStatePolicy()
    library = project_pattern_library(events)
    declarations: list[FileStateDeclaration] = []
    for path, entry in library["paths"].items():
        declarations.append(
            FileStateDeclaration(
                pattern=str(path),
                classification=cast(FileStateTaxonomy, entry["classification"]),
                rule=f"pattern_library:{path}",
                source_kinds=("untracked", "ignored"),
            )
        )
    for pattern, entry in library["patterns"].items():
        declarations.append(
            FileStateDeclaration(
                pattern=str(pattern),
                classification=cast(FileStateTaxonomy, entry["classification"]),
                rule=f"pattern_library:{pattern}",
                source_kinds=("untracked", "ignored"),
            )
        )
    return FileStatePolicy(
        declarations=(*declarations, *active.declarations),
        tool_cache_patterns=active.tool_cache_patterns,
        secret_name_patterns=active.secret_name_patterns,
        secret_entropy_threshold=active.secret_entropy_threshold,
    )


def metadata_from_file_state_record(
    record: dict[str, object],
    *,
    max_items: int,
) -> list[ResidueMetadata]:
    """Extract capped metadata-only residue items from a file-state record."""
    record_id = str(record.get("record_id", ""))
    residue = record.get("residue")
    if not isinstance(residue, list):
        return []
    items: list[ResidueMetadata] = []
    for raw_entry in cast(list[object], residue):
        if len(items) >= max_items:
            break
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, object], raw_entry)
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        if entry.get("needs_gatekeeper") is not True:
            continue
        if entry.get("classification") == "secret":
            continue
        items.append(
            ResidueMetadata(
                path=path,
                size_bytes=_optional_int(entry.get("size_bytes")),
                entropy=_optional_float(entry.get("entropy")),
                source=str(entry.get("source", "")),
                prior_classification=str(entry.get("classification", "")),
                matched_rule=str(entry.get("matched_rule", "")),
                record_id=record_id,
            )
        )
    return items


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
