"""Strict ownership-manifest loading for the graph projection migration."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml


class FieldOwnership(BaseModel):
    """The approved destination and migration policy for one flat field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    old_name: str
    new_path: str | None
    group: str | None
    disposition: Literal["canonical", "index", "derived", "removed"]
    value_type: str
    default_policy: str
    merge_policy: str
    ordering: Literal["not_applicable", "insensitive", "sorted", "explicit_index"]
    checkpoint_policy: Literal["canonical", "id_only", "derived", "omitted"]
    public_output_keys: tuple[str, ...] = ()


class NodeCreationFieldOwnership(BaseModel):
    """The explicit destination or removal of one node-creation field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str
    new_path: str | None = None
    removal_reason: str | None = None

    @model_validator(mode="after")
    def has_exactly_one_disposition(self) -> "NodeCreationFieldOwnership":
        if (self.new_path is None) == (self.removal_reason is None):
            message = "node creation field requires one destination or removal reason"
            raise ValueError(message)
        return self


class ProjectionMigrationManifest(BaseModel):
    """Validated ownership manifest for the complete flat projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_revision: str
    fields: tuple[FieldOwnership, ...] = Field(min_length=73, max_length=73)
    node_creation_fields: frozenset[str]
    node_creation_ownership: tuple[NodeCreationFieldOwnership, ...]


def load_manifest(path: Path) -> ProjectionMigrationManifest:
    """Load and strictly validate a projection migration manifest."""
    return ProjectionMigrationManifest.model_validate(yaml.safe_load(path.read_text()))
