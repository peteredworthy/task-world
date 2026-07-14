"""Runtime adapters for LLM-backed residue classification.

This slice wires the protocol and event flow. ``ClaudeGatekeeperClassifier`` is
left as an import-isolated production stub: the eventual implementation should
follow ``orchestrator.runners.agents.claude_sdk`` credential conventions,
prompt only with ``ResidueMetadata`` fields, parse a verdict per path, and
return token/cost facts for the graph event stream.
"""

from __future__ import annotations

from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.graph import (
    FileStateDeclaration,
    FileStatePolicy,
    FileStateTaxonomy,
    GatekeeperVerdict,
    HydratedEvent,
    StrictFileStateRecord,
    project_pattern_library,
)


class ResidueMetadata(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    size_bytes: int | None = Field(ge=0)
    entropy: float | None = Field(ge=0, le=8)
    source: str = Field(min_length=1)
    prior_classification: str = Field(min_length=1)
    matched_rule: str = Field(min_length=1)
    record_id: str = Field(min_length=1)


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
    events: list[HydratedEvent],
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
    record: StrictFileStateRecord,
    *,
    max_items: int,
) -> list[ResidueMetadata]:
    """Extract capped metadata-only residue items from a file-state record."""
    record_id = record.record_id
    items: list[ResidueMetadata] = []
    for entry in record.residue:
        if len(items) >= max_items:
            break
        if entry.needs_gatekeeper is not True:
            continue
        if entry.classification == "secret":
            continue
        items.append(
            ResidueMetadata(
                path=entry.path,
                size_bytes=entry.size_bytes,
                entropy=entry.entropy,
                source=cast(str, entry.source),
                prior_classification=cast(str, entry.classification),
                matched_rule=cast(str, entry.matched_rule),
                record_id=record_id,
            )
        )
    return items
