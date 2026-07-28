"""Strict ownership-manifest loading and bounded access collection."""

import ast
import argparse
import hashlib
import io
import os
import subprocess
import tokenize
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Iterable, Literal

import libcst as cst
from libcst.metadata import (
    MetadataWrapper,
    ParentNodeProvider,
    PositionProvider,
    QualifiedName,
    QualifiedNameProvider,
    ScopeProvider,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
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

    @model_validator(mode="after")
    def node_creation_ownership_is_complete(self) -> "ProjectionMigrationManifest":
        ownership_fields = tuple(ownership.field_name for ownership in self.node_creation_ownership)
        if len(ownership_fields) != len(frozenset(ownership_fields)):
            raise ValueError("duplicate node creation ownership")
        if frozenset(ownership_fields) != self.node_creation_fields:
            raise ValueError("node creation fields and ownership differ")
        return self


def load_manifest(path: Path) -> ProjectionMigrationManifest:
    """Load and strictly validate a projection migration manifest."""
    return ProjectionMigrationManifest.model_validate(yaml.safe_load(path.read_text()))


class AccessKind(StrEnum):
    """Supported legacy GraphProjection access families."""

    LITERAL_SUBSCRIPT_READ = "literal_subscript_read"
    GET = "get"
    MEMBERSHIP = "membership"
    KEYS = "keys"
    VALUES = "values"
    ITEMS = "items"
    DIRECT_ITERATION = "direct_iteration"
    DIRECT_ASSIGNMENT = "direct_assignment"
    NESTED_ASSIGNMENT = "nested_assignment"
    SETDEFAULT = "setdefault"
    APPEND_EXTEND = "append_extend"
    DELETE_POP = "delete_pop"
    UNPACK_CAST = "unpack_cast"
    FIXTURE_CONSTRUCTION = "fixture_construction"
    UNTYPED_ESCAPE = "untyped_escape"


class ProjectionCallContext(BaseModel):
    """Exact collector-owned context for one proven projection site."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    callee_origin: str | None = None
    receiver_type_origin: str | None = None
    projection_role: Literal["receiver", "positional", "keyword", "ambiguous", "derived_value"]
    projection_expression: str
    argument_star: Literal["*", "**"] | None = None
    preceding_star: Literal["*", "**"] | None = None
    positional_index: int | None = None
    keyword_name: str | None = None
    physical_old_field_name: str | None = None
    physical_access_kind: AccessKind | None = None
    physical_operation_shape: str | None = None

    @model_validator(mode="after")
    def has_exact_projection_role(self) -> "ProjectionCallContext":
        if not self.projection_expression.strip():
            raise ValueError("projection expression must be nonempty")
        if self.projection_role == "positional":
            if self.positional_index is None or self.keyword_name is not None:
                raise ValueError("positional projection context requires only its exact index")
            if self.positional_index < 0:
                raise ValueError("positional projection index must be nonnegative")
        elif self.projection_role == "keyword":
            if self.keyword_name is None or self.positional_index is not None:
                raise ValueError("keyword projection context requires only its exact name")
        elif self.positional_index is not None or self.keyword_name is not None:
            raise ValueError(
                "receiver, ambiguous, or derived-value projection context cannot name an argument slot"
            )
        if self.physical_old_field_name is not None and self.physical_access_kind is None:
            raise ValueError("physical projection field requires access-kind evidence")
        if self.physical_access_kind is None and self.physical_operation_shape is not None:
            raise ValueError("physical operation shape requires access-kind evidence")
        if self.physical_access_kind is not None and self.physical_operation_shape is None:
            raise ValueError("physical access-kind requires operation shape evidence")
        if self.projection_role == "ambiguous" and (self.argument_star is None) == (
            self.preceding_star is None
        ):
            raise ValueError("ambiguous projection context requires exactly one star fact")
        if self.projection_role != "ambiguous" and (self.argument_star or self.preceding_star):
            raise ValueError("only ambiguous projection context can retain star evidence")
        return self


class DiagnosticCode(StrEnum):
    COMPUTED_KEY = "computed_key"
    UNKNOWN_FIELD = "unknown_field"
    PARSE_ERROR = "parse_error"
    REFLECTION = "reflection"
    PROJECTION_UNPACKING = "projection_unpacking"
    UNSUPPORTED_CALL = "unsupported_call"
    UNSUPPORTED_BINDING = "unsupported_binding"
    UNSUPPORTED_CONSTRUCTION = "unsupported_construction"
    UNSUPPORTED_COMPARISON = "unsupported_comparison"
    UNSUPPORTED_MUTATION = "unsupported_mutation"


class AccessOccurrence(BaseModel):
    """One supported access to a manifest-owned legacy projection field."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    occurrence_id: str
    relative_path: str
    qualified_function: str
    normalized_expression: str
    same_expression_ordinal: int
    old_field_name: str | None
    kind: AccessKind
    line: int
    column: int
    ordering_sensitivity_disposition: Literal[
        "not_applicable", "insensitive", "sorted", "explicit_index"
    ]
    context: ProjectionCallContext | None = None


class InventoryDiagnostic(BaseModel):
    """A fail-closed source construct that requires manual migration first."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    qualified_function: str = "<module>"
    line: int
    column: int
    code: DiagnosticCode
    message: str
    normalized_source_pattern: str = "<unknown>"
    same_pattern_ordinal: int = 0
    source_node_type: str = "<unknown>"
    normalized_cst_expression: str = "<unknown>"
    remediation: str = "replace this dynamic projection access with a typed GraphProjection flow"
    context: ProjectionCallContext | None = None


class SourceInventory(BaseModel):
    """Deterministic collection result for one source file."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    baseline_revision: str
    occurrences: tuple[AccessOccurrence, ...]
    diagnostics: tuple[InventoryDiagnostic, ...]


class InventorySource(BaseModel):
    """An in-memory, source-independent input to the inventory collector."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    source: str


class SourceDigest(BaseModel):
    """The blank-line-insensitive source identity used by the operation compiler."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    digest: str


class AccessInventory(BaseModel):
    """Deterministic aggregate of every bounded source inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    baseline_revision: str
    occurrences: tuple[AccessOccurrence, ...]
    diagnostics: tuple[InventoryDiagnostic, ...]
    source_digests: tuple[SourceDigest, ...] = ()


class IncompleteMigrationDispositionError(ValueError):
    """Raised when a migration manifest does not cover its requested inventory scope."""

    def __init__(self, remaining_counts: dict[str, int]) -> None:
        self.remaining_counts = remaining_counts
        super().__init__(f"unclassified graph projection sites: {remaining_counts}")


CanonicalSiteKey = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class MigrationDisposition(BaseModel):
    """One exact, reviewable disposition for a legacy projection inventory site."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    site_key: CanonicalSiteKey
    disposition: Literal["query_transform", "approved_core", "projection_neutral", "rejected"]
    relative_path: str
    qualified_function: str
    normalized_source_pattern: str
    diagnostic_code: DiagnosticCode | None = None
    reason: str

    @field_validator("relative_path", "qualified_function", "normalized_source_pattern", "reason")
    @classmethod
    def required_text_is_nonblank(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def requires_exact_policy_details(self) -> "MigrationDisposition":
        if not self.reason.strip():
            raise ValueError("migration disposition requires a reason")
        if self.disposition == "projection_neutral" and self.diagnostic_code is None:
            raise ValueError("projection_neutral requires an exact diagnostic code")
        if (
            self.disposition == "approved_core"
            and self.relative_path not in _APPROVED_CORE_STORAGE_FILES
        ):
            raise ValueError("approved_core is limited to the exact five storage files")
        return self

    @field_serializer("site_key")
    def serialize_site_key(self, site_key: CanonicalSiteKey) -> tuple[str, ...]:
        return tuple(site_key[index : index + 8] for index in range(0, len(site_key), 8))


class UnclassifiedMigrationSite(BaseModel):
    """A mechanically generated site awaiting an explicit human disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    site_key: CanonicalSiteKey
    relative_path: str
    qualified_function: str
    normalized_source_pattern: str
    diagnostic_code: DiagnosticCode | None = None
    domain: str

    @field_validator("relative_path", "qualified_function", "normalized_source_pattern", "domain")
    @classmethod
    def required_text_is_nonblank(cls, value: str) -> str:
        return _nonblank(value)

    @field_serializer("site_key")
    def serialize_site_key(self, site_key: CanonicalSiteKey) -> tuple[str, ...]:
        return tuple(site_key[index : index + 8] for index in range(0, len(site_key), 8))


class QueryMigrationManifest(BaseModel):
    """Strict disposition ledger for the query-boundary source migration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    baseline_revision: str
    dispositions: tuple[MigrationDisposition, ...]
    unclassified_sites: tuple[UnclassifiedMigrationSite, ...] = ()

    @field_validator("baseline_revision")
    @classmethod
    def baseline_revision_is_nonblank(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def has_unique_site_keys(self) -> "QueryMigrationManifest":
        keys = tuple(item.site_key for item in (*self.dispositions, *self.unclassified_sites))
        if len(keys) != len(frozenset(keys)):
            raise ValueError("duplicate migration disposition site key")
        return self


def load_query_migration_manifest(path: Path) -> QueryMigrationManifest:
    """Load a strict query migration ledger or its generated partial skeleton."""
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("query migration manifest must be a mapping")
    normalized = dict(raw)
    for collection_name in ("dispositions", "unclassified_sites"):
        collection = normalized.get(collection_name, ())
        if not isinstance(collection, list):
            raise ValueError(f"{collection_name} must be a YAML list")
        normalized[collection_name] = tuple(
            _normalize_loaded_migration_site(item) for item in collection
        )
    return QueryMigrationManifest.model_validate(normalized)


_APPROVED_CORE_STORAGE_FILES = frozenset(
    {
        "src/orchestrator/graph/projection_models.py",
        "src/orchestrator/graph/projection_collections.py",
        "src/orchestrator/graph/projection_queries.py",
        "src/orchestrator/graph/projection_codec.py",
        "src/orchestrator/graph/projections.py",
    }
)


def disposition_site_key(
    *,
    baseline_revision: str,
    relative_path: str,
    qualified_function: str,
    normalized_source_pattern: str,
    diagnostic_code: DiagnosticCode | str | None,
    same_pattern_ordinal: int = 0,
) -> str:
    """Return position-independent identity for a diagnostic disposition site."""
    diagnostic_value = (
        diagnostic_code.value if isinstance(diagnostic_code, DiagnosticCode) else diagnostic_code
    )
    payload = "\0".join(
        (
            baseline_revision,
            relative_path,
            qualified_function,
            normalized_source_pattern,
            diagnostic_value or "occurrence",
            str(same_pattern_ordinal),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _normalize_loaded_migration_site(raw_site: object) -> dict[str, object]:
    """Convert only YAML's ledger containers and eight-part canonical site keys."""
    if not isinstance(raw_site, dict):
        raise ValueError("migration site must be a mapping")
    normalized = dict(raw_site)
    site_key = normalized.get("site_key")
    if isinstance(site_key, list):
        if len(site_key) != 8 or any(
            not isinstance(part, str)
            or len(part) != 8
            or any(character not in "0123456789abcdef" for character in part)
            for part in site_key
        ):
            raise ValueError("site_key YAML chunks must be eight lowercase hex groups")
        normalized["site_key"] = "".join(site_key)
    diagnostic_code = normalized.get("diagnostic_code")
    if isinstance(diagnostic_code, str):
        normalized["diagnostic_code"] = DiagnosticCode(diagnostic_code)
    return normalized


def _diagnostic_source_pattern(diagnostic: InventoryDiagnostic) -> str:
    """Return collector-captured diagnostic evidence without rereading source."""
    return diagnostic.normalized_source_pattern


def _diagnostic_site_key(baseline_revision: str, diagnostic: InventoryDiagnostic) -> str:
    return disposition_site_key(
        baseline_revision=baseline_revision,
        relative_path=diagnostic.relative_path,
        qualified_function=diagnostic.qualified_function,
        normalized_source_pattern=_diagnostic_source_pattern(diagnostic),
        diagnostic_code=diagnostic.code,
        same_pattern_ordinal=diagnostic.same_pattern_ordinal,
    )


def _diagnostic_site_keys(inventory: AccessInventory) -> dict[int, str]:
    """Return diagnostic keys from collector-captured source evidence."""
    keys: dict[int, str] = {}
    for diagnostic in inventory.diagnostics:
        keys[id(diagnostic)] = _diagnostic_site_key(
            inventory.baseline_revision,
            diagnostic,
        )
    return keys


def _site_domain(
    relative_path: str,
    old_field_name: str | None = None,
    normalized_source_pattern: str = "",
) -> str:
    """Assign a deterministic bounded domain for partial migration reporting."""
    if relative_path in _APPROVED_CORE_STORAGE_FILES:
        return "approved_core"
    if (
        old_field_name in {"run_state", "completion_decision_passed"}
        or "run_state" in normalized_source_pattern
        or "completion_decision_passed" in normalized_source_pattern
        or relative_path.endswith("/commands/lifecycle.py")
    ):
        return "lifecycle"
    if relative_path.endswith("/graph_runtime/dispatch.py") and (
        old_field_name == "file_state_records" or "file_state_records" in normalized_source_pattern
    ):
        return "record_file_state"
    if relative_path.endswith("/graph_runtime/dispatch.py") and (
        old_field_name == "input_bindings" or "input_bindings" in normalized_source_pattern
    ):
        return "node_task_edge_binding"
    if relative_path.startswith("tests/"):
        return "test_fixture"
    if relative_path.endswith("/_commands.py"):
        return "verification_recovery"
    if relative_path.endswith("/callbacks.py"):
        return "cleanup_callback"
    if relative_path.endswith("/patch_validator.py"):
        return "governance_requirements"
    if relative_path.endswith("/graph_runtime/prompts.py"):
        return "planning_session"
    if relative_path.endswith("/graph_runtime/dispatch.py"):
        return "lease"
    if relative_path.endswith("/graph_runtime/recovery.py"):
        return "verification_recovery"
    if relative_path.endswith("/graph_runtime/store.py"):
        return "record_file_state"
    return "node_task_edge_binding"


def validate_query_migration_manifest(
    manifest: QueryMigrationManifest,
    inventory: AccessInventory,
    root: Path,
    *,
    domain: str | None = None,
) -> dict[str, int]:
    """Require exact one-to-one dispositions for a fresh inventory or one bounded domain."""
    if manifest.baseline_revision != inventory.baseline_revision:
        raise ValueError("migration manifest and inventory baseline revisions differ")

    expected: dict[str, tuple[str, str, str, DiagnosticCode | None, str]] = {}
    for occurrence in inventory.occurrences:
        expected[occurrence.occurrence_id] = (
            occurrence.relative_path,
            occurrence.qualified_function,
            occurrence.normalized_expression,
            None,
            _site_domain(
                occurrence.relative_path,
                occurrence.old_field_name,
                occurrence.normalized_expression,
            ),
        )
    diagnostic_keys = _diagnostic_site_keys(inventory)
    for diagnostic in inventory.diagnostics:
        pattern = _diagnostic_source_pattern(diagnostic)
        expected[diagnostic_keys[id(diagnostic)]] = (
            diagnostic.relative_path,
            diagnostic.qualified_function,
            pattern,
            diagnostic.code,
            _site_domain(diagnostic.relative_path, normalized_source_pattern=pattern),
        )

    scoped_expected = {
        site_key: site for site_key, site in expected.items() if domain is None or site[4] == domain
    }
    all_supplied = {item.site_key: item for item in manifest.dispositions}
    all_unclassified = {item.site_key: item for item in manifest.unclassified_sites}
    stale = set(all_supplied) - set(expected)
    stale_unclassified = set(all_unclassified) - set(expected)
    if stale or stale_unclassified:
        raise ValueError(
            f"stale migration disposition site keys: {sorted(stale | stale_unclassified)}"
        )
    supplied = {
        site_key: item for site_key, item in all_supplied.items() if site_key in scoped_expected
    }
    unclassified = {
        site_key: item for site_key, item in all_unclassified.items() if site_key in scoped_expected
    }
    for site_key, disposition in supplied.items():
        path, function, pattern, code, _ = scoped_expected[site_key]
        if (path, function, pattern, code) != (
            disposition.relative_path,
            disposition.qualified_function,
            disposition.normalized_source_pattern,
            disposition.diagnostic_code,
        ):
            raise ValueError(f"migration disposition details differ for {site_key}")

    remaining = set(scoped_expected) - set(supplied)
    for site_key, site in unclassified.items():
        path, function, pattern, code, domain_name = scoped_expected[site_key]
        if (path, function, pattern, code, domain_name) != (
            site.relative_path,
            site.qualified_function,
            site.normalized_source_pattern,
            site.diagnostic_code,
            site.domain,
        ):
            raise ValueError(f"generated migration skeleton details differ for {site_key}")
    if remaining:
        counts: dict[str, int] = {}
        for site_key in remaining:
            domain_name = scoped_expected[site_key][4]
            counts[domain_name] = counts.get(domain_name, 0) + 1
        raise IncompleteMigrationDispositionError(dict(sorted(counts.items())))
    return {
        domain_name: sum(site[4] == domain_name for site in scoped_expected.values())
        for domain_name in sorted({site[4] for site in scoped_expected.values()})
    }


def query_migration_skeleton(
    inventory: AccessInventory, root: Path | None = None
) -> QueryMigrationManifest:
    """Mechanically generate a complete, unclassified disposition ledger from inventory."""
    del root
    sites = [
        UnclassifiedMigrationSite(
            site_key=occurrence.occurrence_id,
            relative_path=occurrence.relative_path,
            qualified_function=occurrence.qualified_function,
            normalized_source_pattern=occurrence.normalized_expression,
            domain=_site_domain(
                occurrence.relative_path,
                occurrence.old_field_name,
                occurrence.normalized_expression,
            ),
        )
        for occurrence in inventory.occurrences
    ]
    diagnostic_keys = _diagnostic_site_keys(inventory)
    sites.extend(
        UnclassifiedMigrationSite(
            site_key=diagnostic_keys[id(diagnostic)],
            relative_path=diagnostic.relative_path,
            qualified_function=diagnostic.qualified_function,
            normalized_source_pattern=_diagnostic_source_pattern(diagnostic),
            diagnostic_code=diagnostic.code,
            domain=_site_domain(
                diagnostic.relative_path,
                normalized_source_pattern=_diagnostic_source_pattern(diagnostic),
            ),
        )
        for diagnostic in inventory.diagnostics
    )
    return QueryMigrationManifest(
        baseline_revision=inventory.baseline_revision,
        dispositions=(),
        unclassified_sites=tuple(sites),
    )


def classify_lifecycle_domain(skeleton: QueryMigrationManifest) -> QueryMigrationManifest:
    """Apply the reviewed lifecycle-domain dispositions to a generated skeleton."""
    classified_sites = tuple(
        site for site in skeleton.unclassified_sites if site.domain == "lifecycle"
    )
    dispositions = tuple(
        MigrationDisposition(
            site_key=site.site_key,
            disposition=(
                "query_transform"
                if site.diagnostic_code is None or 'projection["' in site.normalized_source_pattern
                else "projection_neutral"
            ),
            relative_path=site.relative_path,
            qualified_function=site.qualified_function,
            normalized_source_pattern=site.normalized_source_pattern,
            diagnostic_code=site.diagnostic_code,
            reason=(
                "Replace this direct lifecycle projection read with the permanent query API."
                if site.diagnostic_code is None or 'projection["' in site.normalized_source_pattern
                else "The exact source invokes a query or preserves type provenance without a physical projection storage read."
            ),
        )
        for site in classified_sites
    )
    return QueryMigrationManifest(
        baseline_revision=skeleton.baseline_revision,
        dispositions=(*skeleton.dispositions, *dispositions),
        unclassified_sites=tuple(
            site for site in skeleton.unclassified_sites if site.domain != "lifecycle"
        ),
    )


def classify_node_task_edge_binding_and_lease_domains(
    skeleton: QueryMigrationManifest,
    reviewed_dispositions: tuple[MigrationDisposition, ...],
) -> QueryMigrationManifest:
    """Apply only the closed, reviewed target-domain disposition keys.

    The migration skeleton is deliberately broader than the reviewed ledger:
    a newly discovered target-domain site must remain unclassified until a
    reviewer adds its exact site key and disposition to the ledger.
    """
    target_domains = frozenset(
        {
            "cleanup_callback",
            "governance_requirements",
            "lease",
            "node_task_edge_binding",
            "planning_session",
            "record_file_state",
            "approved_core",
        }
    )
    reviewed_by_key = {
        disposition.site_key: disposition
        for disposition in reviewed_dispositions
        if disposition.site_key
        and disposition.disposition
        in {"approved_core", "query_transform", "projection_neutral", "rejected"}
    }
    classified_sites = tuple(
        site
        for site in skeleton.unclassified_sites
        if site.domain in target_domains and site.site_key in reviewed_by_key
    )
    dispositions = tuple(reviewed_by_key[site.site_key] for site in classified_sites)
    classified_keys = {site.site_key for site in classified_sites}
    return QueryMigrationManifest(
        baseline_revision=skeleton.baseline_revision,
        dispositions=(*skeleton.dispositions, *dispositions),
        unclassified_sites=tuple(
            site for site in skeleton.unclassified_sites if site.site_key not in classified_keys
        ),
    )


def occurrence_id(
    baseline_revision: str,
    relative_path: str,
    qualified_function: str,
    normalized_expression: str,
    same_expression_ordinal: int,
) -> str:
    """Create position-independent identity for an inventory occurrence."""
    payload = "\0".join(
        (
            baseline_revision,
            relative_path,
            qualified_function,
            normalized_expression,
            str(same_expression_ordinal),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _manifest_fields() -> dict[str, FieldOwnership]:
    manifest_path = Path(__file__).parent / "codemods" / "graph_projection_manifest.yaml"
    return {field.old_name: field for field in load_manifest(manifest_path).fields}


def _name(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return node.attr.value
    return None


def _attribute_key(node: cst.Attribute) -> str | None:
    """Return a stable dotted key without rendering a detached CST fragment."""
    if isinstance(node.value, cst.Name):
        return f"{node.value.value}.{node.attr.value}"
    if isinstance(node.value, cst.Attribute):
        prefix = _attribute_key(node.value)
        return f"{prefix}.{node.attr.value}" if prefix is not None else None
    return None


def _literal_key(node: cst.BaseExpression) -> str | None:
    if not isinstance(node, cst.SimpleString):
        return None
    value = cst.parse_expression(node.value)
    if isinstance(value, cst.SimpleString):
        return value.evaluated_value
    return None


def _remediation(code: DiagnosticCode) -> str:
    return {
        DiagnosticCode.UNSUPPORTED_CALL: "replace the dynamic call with a typed projection query",
        DiagnosticCode.UNSUPPORTED_COMPARISON: "compare an explicit typed projection field",
        DiagnosticCode.UNSUPPORTED_BINDING: "retain the GraphProjection annotation through this binding",
        DiagnosticCode.REFLECTION: "replace reflection with an explicit typed projection field",
    }.get(code, "replace this dynamic projection access with a typed GraphProjection flow")


_SUPPORTED_PROJECTION_METHODS = frozenset(
    {"get", "pop", "setdefault", "keys", "values", "items", "append", "extend"}
)

# These are intentionally tables, rather than inferred method names.  A matching
# receiver must carry the exact annotation named here in the current scope.
_PROJECTION_PRODUCERS = {
    ("GraphController", "read_projection"): "value",
    ("GraphEventStore", "load_projection_with_tail"): "first_tuple_item",
}
_PROJECTION_FIELDS = {
    "GraphDispatchContext": frozenset({"graph_projection"}),
    "GraphProjectionCheckpoint": frozenset({"projection"}),
}
_CONTAINS_PROJECTION = "<contains GraphProjection>"
_UNRESOLVED_PROJECTION = "<unresolved GraphProjection>"
_GRAPH_PROJECTION_TYPE_ORIGINS = frozenset(
    {
        "orchestrator.graph.GraphProjection",
        "orchestrator.graph._commands.GraphProjection",
        "orchestrator.graph.projections.GraphProjection",
    }
)

# A producer is trusted only when its imported origin is listed here.  Local
# producers are separately admitted from an exact, resolved return annotation.
_APPROVED_PRODUCER_ORIGINS = frozenset(
    {
        "orchestrator.graph.initial_projection",
        "orchestrator.graph.build_projection",
        "orchestrator.graph.reduce_event",
        "orchestrator.graph_runtime.controller.rebuild_projection",
    }
)
_CONTEXT_PRODUCER_ORIGINS = _APPROVED_PRODUCER_ORIGINS | frozenset(
    {"orchestrator.graph.projections.reduce_event"}
)
_DERIVED_VALUE_SINK_ORIGINS = frozenset({"orchestrator.graph.scheduler.NodeScheduleInfo"})

_APPROVED_SYMBOLS = frozenset(
    {
        "orchestrator.graph.GraphProjection",
        "orchestrator.graph.GraphController",
        "orchestrator.graph.GraphEventStore",
        "orchestrator.graph.GraphDispatchContext",
        "orchestrator.graph.GraphProjectionCheckpoint",
        "orchestrator.graph.projections.GraphProjection",
        "orchestrator.graph_runtime.controller.GraphController",
        "orchestrator.graph_runtime.store.GraphEventStore",
        "typing.cast",
        "typing.Any",
        "typing.Callable",
        "builtins.object",
    }
)


@dataclass(frozen=True)
class _CallableSignature:
    positional: tuple[tuple[str, str | None, bool], ...]
    keyword_only: tuple[tuple[str, str | None, bool], ...]
    positional_only: frozenset[str]
    has_varargs: bool
    has_kwargs: bool
    return_annotation: str | None

    def bind(self, args: tuple[cst.Arg, ...]) -> tuple[str | None, ...] | None:
        """Bind arguments conservatively; None means malformed or variadic."""
        if self.has_varargs or self.has_kwargs or any(arg.star for arg in args):
            return None
        positional = list(self.positional)
        positional_annotations = {name: annotation for name, annotation, _ in positional}
        keywords = {name: annotation for name, annotation, _ in self.keyword_only}
        bound: list[str | None] = []
        consumed: set[str] = set()
        position = 0
        for arg in args:
            if arg.keyword is None:
                if position >= len(positional):
                    return None
                name, annotation, _ = positional[position]
                position += 1
            else:
                name = arg.keyword.value
                if name in consumed or name in self.positional_only:
                    return None
                annotation = positional_annotations.get(name, keywords.get(name))
                if (
                    annotation is None
                    and name not in positional_annotations
                    and name not in keywords
                ):
                    return None
            consumed.add(name)
            bound.append(annotation)
        required = {
            name for name, _, is_required in (*self.positional, *self.keyword_only) if is_required
        }
        if not required <= consumed:
            return None
        return tuple(bound)


@dataclass(frozen=True)
class _ModuleSymbols:
    """The deliberately small, deterministic namespace understood by the collector."""

    names: dict[str, str]
    unresolved_projection_names: frozenset[str]
    class_fields: dict[str, frozenset[str]]
    call_symbols: dict[str, str]
    signatures: dict[str, _CallableSignature]
    declaration_annotations: dict[tuple[int, int], str | None]
    require_declaration_facts: bool = False

    @classmethod
    def from_source(
        cls,
        source: str,
        *,
        allow_implicit_graph_projection: bool = False,
        module_name: str | None = None,
        require_declaration_facts: bool = False,
    ) -> "_ModuleSymbols":
        names: dict[str, str] = (
            {
                "GraphProjection": "orchestrator.graph.GraphProjection",
                "GraphController": "orchestrator.graph.GraphController",
                "GraphEventStore": "orchestrator.graph.GraphEventStore",
                "GraphDispatchContext": "orchestrator.graph.GraphDispatchContext",
                "GraphProjectionCheckpoint": "orchestrator.graph.GraphProjectionCheckpoint",
                "initial_projection": "orchestrator.graph.initial_projection",
                "build_projection": "orchestrator.graph.build_projection",
                "reduce_event": "orchestrator.graph.reduce_event",
            }
            if allow_implicit_graph_projection
            else {}
        )
        class_fields: dict[str, frozenset[str]] = dict(_PROJECTION_FIELDS)
        call_symbols: dict[str, str] = {}
        signatures: dict[str, _CallableSignature] = {}
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return cls(
                names,
                frozenset(),
                class_fields,
                call_symbols,
                signatures,
                {},
                require_declaration_facts,
            )
        declaration_annotations = cls._declaration_annotations(
            tree,
            source=source,
            initial_names=dict(names),
            module_name=module_name,
        )
        unresolved_projection_names: set[str] = set()

        def clear_local_binding(local: str) -> None:
            names.pop(local, None)
            unresolved_projection_names.discard(local)
            class_fields.pop(local, None)
            signatures.pop(local, None)

        for node in tree.body:
            if isinstance(node, ast.Import):
                for imported in node.names:
                    local = imported.asname or imported.name.split(".")[0]
                    clear_local_binding(local)
                    if imported.name in {"typing", "orchestrator.graph"}:
                        names[local] = imported.name
            elif isinstance(node, ast.ImportFrom):
                for imported in node.names:
                    if imported.name == "*":
                        continue
                    local = imported.asname or imported.name
                    clear_local_binding(local)
                    module = _resolve_import_module(node, module_name)
                    if module is None:
                        continue
                    resolved = f"{module}.{imported.name}"
                    if resolved in _APPROVED_SYMBOLS | _APPROVED_PRODUCER_ORIGINS:
                        names[local] = resolved
                    elif local == "GraphProjection" or "GraphProjection" in imported.name:
                        unresolved_projection_names.add(local)
            if isinstance(node, ast.ClassDef):
                fields = frozenset(
                    child.target.id
                    for child in node.body
                    if isinstance(child, ast.AnnAssign)
                    and isinstance(child.target, ast.Name)
                    and cls._annotation(child.annotation, names, unresolved_projection_names)
                    == "GraphProjection"
                )
                clear_local_binding(node.name)
                if fields:
                    class_fields[node.name] = fields
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                positional_arguments = (*node.args.posonlyargs, *node.args.args)
                positional_required_count = len(positional_arguments) - len(node.args.defaults)
                positional = tuple(
                    (
                        argument.arg,
                        cls._annotation(argument.annotation, names, unresolved_projection_names),
                        index < positional_required_count,
                    )
                    for index, argument in enumerate(positional_arguments)
                )
                keyword_only = tuple(
                    (
                        argument.arg,
                        cls._annotation(argument.annotation, names, unresolved_projection_names),
                        default is None,
                    )
                    for argument, default in zip(
                        node.args.kwonlyargs, node.args.kw_defaults, strict=True
                    )
                )
                return_annotation = cls._annotation(
                    node.returns, names, unresolved_projection_names
                )
                clear_local_binding(node.name)
                signatures[node.name] = _CallableSignature(
                    positional,
                    keyword_only,
                    frozenset(argument.arg for argument in node.args.posonlyargs),
                    node.args.vararg is not None,
                    node.args.kwarg is not None,
                    return_annotation,
                )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                for target in targets:
                    for name in _ast_target_names(target):
                        clear_local_binding(name)
        for local, resolved in names.items():
            if resolved == "typing.cast":
                call_symbols[local] = resolved
        for local, resolved in names.items():
            owner = cls._projection_symbol(resolved)
            if owner in _PROJECTION_FIELDS:
                class_fields[owner] = _PROJECTION_FIELDS[owner]
        return cls(
            names,
            frozenset(unresolved_projection_names),
            class_fields,
            call_symbols,
            signatures,
            declaration_annotations,
            require_declaration_facts,
        )

    @classmethod
    def _declaration_annotations(
        cls,
        tree: ast.Module,
        *,
        source: str,
        initial_names: dict[str, str],
        module_name: str | None,
    ) -> dict[tuple[int, int], str | None]:
        """Resolve declaration annotations against bindings visible at their source position."""

        facts: dict[tuple[int, int], str | None] = {}

        def bind_import(
            node: ast.Import | ast.ImportFrom,
            names: dict[str, str],
            unresolved: set[str],
        ) -> None:
            if isinstance(node, ast.Import):
                for imported in node.names:
                    local = imported.asname or imported.name.split(".")[0]
                    names.pop(local, None)
                    unresolved.discard(local)
                    if imported.name in {"typing", "orchestrator.graph"}:
                        names[local] = imported.name
                    elif _projection_shaped_import(imported.name, local):
                        unresolved.add(local)
                return
            module = _resolve_import_module(node, module_name)
            for imported in node.names:
                if imported.name == "*":
                    continue
                local = imported.asname or imported.name
                names.pop(local, None)
                unresolved.discard(local)
                if module is None:
                    continue
                resolved = f"{module}.{imported.name}"
                if resolved in _APPROVED_SYMBOLS | _APPROVED_PRODUCER_ORIGINS:
                    names[local] = resolved
                elif _projection_shaped_import(imported.name, local):
                    unresolved.add(local)

        def visit_statements(
            statements: list[ast.stmt], names: dict[str, str], unresolved: set[str]
        ) -> None:
            for statement in statements:
                if isinstance(statement, (ast.Import, ast.ImportFrom)):
                    bind_import(statement, names, unresolved)
                elif isinstance(statement, ast.AnnAssign):
                    record_annotation(statement.annotation, names, unresolved)
                    clear_targets((statement.target,), names, unresolved)
                elif isinstance(statement, ast.Assign):
                    clear_targets(statement.targets, names, unresolved)
                elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    record_function_annotations(statement, names, unresolved)
                    names.pop(statement.name, None)
                    unresolved.discard(statement.name)
                    body_names = dict(names)
                    body_unresolved = set(unresolved)
                    shadow_function_parameters(statement, body_names, body_unresolved)
                    visit_statements(statement.body, body_names, body_unresolved)
                elif isinstance(statement, ast.ClassDef):
                    body_names = dict(names)
                    body_unresolved = set(unresolved)
                    visit_statements(statement.body, body_names, body_unresolved)
                    names.pop(statement.name, None)
                    unresolved.discard(statement.name)
                else:
                    blocks = _lexical_statement_blocks(statement)
                    if not blocks:
                        continue
                    branch_states = [(dict(names), set(unresolved))]
                    for block in blocks:
                        branch_names = dict(names)
                        branch_unresolved = set(unresolved)
                        visit_statements(block, branch_names, branch_unresolved)
                        branch_states.append((branch_names, branch_unresolved))
                    merge_control_flow_bindings(names, unresolved, branch_states)

        def clear_targets(
            targets: Iterable[ast.expr], names: dict[str, str], unresolved: set[str]
        ) -> None:
            for target in targets:
                for local in _ast_target_names(target):
                    names.pop(local, None)
                    unresolved.discard(local)

        def record_annotation(
            annotation: ast.expr, names: dict[str, str], unresolved: set[str]
        ) -> None:
            facts[_ast_character_position(annotation, source)] = cls._annotation(
                annotation, names, unresolved
            )

        def record_function_annotations(
            node: ast.FunctionDef | ast.AsyncFunctionDef,
            names: dict[str, str],
            unresolved: set[str],
        ) -> None:
            parameters = (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                *((node.args.vararg,) if node.args.vararg is not None else ()),
                *((node.args.kwarg,) if node.args.kwarg is not None else ()),
            )
            for parameter in parameters:
                if parameter.annotation is not None:
                    record_annotation(parameter.annotation, names, unresolved)
            if node.returns is not None:
                record_annotation(node.returns, names, unresolved)

        def shadow_function_parameters(
            node: ast.FunctionDef | ast.AsyncFunctionDef,
            names: dict[str, str],
            unresolved: set[str],
        ) -> None:
            for parameter in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                *((node.args.vararg,) if node.args.vararg is not None else ()),
                *((node.args.kwarg,) if node.args.kwarg is not None else ()),
            ):
                names.pop(parameter.arg, None)
                unresolved.discard(parameter.arg)

        def merge_control_flow_bindings(
            names: dict[str, str],
            unresolved: set[str],
            branch_states: list[tuple[dict[str, str], set[str]]],
        ) -> None:
            """Retain only bindings certain on every path; projection-shaped joins fail closed."""
            all_locals = set().union(
                *(
                    set(branch_names) | unresolved_names
                    for branch_names, unresolved_names in branch_states
                )
            )
            for local in all_locals:
                resolved = tuple(branch_names.get(local) for branch_names, _ in branch_states)
                branch_unresolved = any(
                    local in unresolved_names for _, unresolved_names in branch_states
                )
                if not branch_unresolved and all(
                    symbol == resolved[0] and symbol is not None for symbol in resolved
                ):
                    names[local] = resolved[0]
                    unresolved.discard(local)
                    continue
                names.pop(local, None)
                if branch_unresolved or any(
                    symbol is not None and symbol.endswith(".GraphProjection")
                    for symbol in resolved
                ):
                    unresolved.add(local)
                else:
                    unresolved.discard(local)

        visit_statements(tree.body, dict(initial_names), set())
        return facts

    @staticmethod
    def _annotation(
        node: ast.expr | None,
        names: dict[str, str],
        unresolved_projection_names: set[str] | frozenset[str] = frozenset(),
    ) -> str | None:
        """Normalize annotations identically across AST and CST callers."""
        if node is None:
            return None
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return _ModuleSymbols._merge_annotation_members(
                tuple(
                    _ModuleSymbols._annotation(element, names, unresolved_projection_names)
                    for element in node.elts
                ),
                nested=True,
            )
        if isinstance(node, ast.Subscript):
            return _ModuleSymbols._merge_annotation_members(
                (
                    _ModuleSymbols._annotation(node.value, names, unresolved_projection_names),
                    *_ModuleSymbols._annotation_members(
                        node.slice, names, unresolved_projection_names
                    ),
                ),
                nested=True,
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return _ModuleSymbols._merge_annotation_members(
                (
                    _ModuleSymbols._annotation(node.left, names, unresolved_projection_names),
                    _ModuleSymbols._annotation(node.right, names, unresolved_projection_names),
                ),
                nested=True,
            )
        if isinstance(node, ast.Name):
            if node.id in unresolved_projection_names:
                return _UNRESOLVED_PROJECTION
            return _ModuleSymbols._projection_symbol(names.get(node.id, node.id))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in unresolved_projection_names:
                return _UNRESOLVED_PROJECTION
            prefix = names.get(node.value.id)
            resolved = f"{prefix}.{node.attr}" if prefix else ""
            if node.attr == "GraphProjection" and resolved not in _APPROVED_SYMBOLS:
                return _UNRESOLVED_PROJECTION
            return _ModuleSymbols._projection_symbol(resolved)
        return None

    @staticmethod
    def _annotation_members(
        node: ast.expr,
        names: dict[str, str],
        unresolved_projection_names: set[str] | frozenset[str],
    ) -> tuple[str | None, ...]:
        if isinstance(node, ast.Tuple):
            return tuple(
                _ModuleSymbols._annotation(element, names, unresolved_projection_names)
                for element in node.elts
            )
        return (_ModuleSymbols._annotation(node, names, unresolved_projection_names),)

    @staticmethod
    def _merge_annotation_members(
        annotations: tuple[str | None, ...], *, nested: bool
    ) -> str | None:
        if _UNRESOLVED_PROJECTION in annotations:
            return _UNRESOLVED_PROJECTION
        if _CONTAINS_PROJECTION in annotations or (nested and "GraphProjection" in annotations):
            return _CONTAINS_PROJECTION
        return next((annotation for annotation in annotations if annotation is not None), None)

    def annotation_name(self, node: cst.BaseExpression) -> str | None:
        try:
            expression = ast.parse(cst.Module([]).code_for_node(node), mode="eval").body
        except SyntaxError:
            return None
        return self._annotation(expression, self.names, self.unresolved_projection_names)

    def declaration_annotation_name(
        self, node: cst.BaseExpression, position: tuple[int, int]
    ) -> str | None:
        """Use ordered AST provenance for an annotation declaration when available."""
        if position in self.declaration_annotations:
            return self.declaration_annotations[position]
        if self.require_declaration_facts:
            return _UNRESOLVED_PROJECTION
        return self.annotation_name(node)

    @staticmethod
    def _projection_symbol(resolved: str) -> str:
        if resolved in {
            "GraphProjection",
            "GraphController",
            "GraphEventStore",
            "GraphDispatchContext",
            "GraphProjectionCheckpoint",
        }:
            return ""
        if resolved not in _APPROVED_SYMBOLS:
            return resolved
        return resolved.rsplit(".", maxsplit=1)[-1]


def _ast_target_names(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for element in node.elts for name in _ast_target_names(element))
    return ()


def _ast_character_position(node: ast.expr, source: str) -> tuple[int, int]:
    """Convert AST's UTF-8 byte column into LibCST's character column."""
    line = source.splitlines()[node.lineno - 1]
    return node.lineno, len(line.encode("utf-8")[: node.col_offset].decode("utf-8"))


def _projection_shaped_import(imported_name: str, local_name: str) -> bool:
    """Recognize foreign imports that could deceptively denote GraphProjection."""
    return local_name == "GraphProjection" or "GraphProjection" in imported_name.split(".")


def _lexical_statement_blocks(statement: ast.stmt) -> tuple[list[ast.stmt], ...]:
    """Return nested statement suites that retain their enclosing lexical scope."""
    if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return statement.body, statement.orelse
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return (statement.body,)
    if isinstance(statement, (ast.Try, ast.TryStar)):
        return (
            statement.body,
            *(handler.body for handler in statement.handlers),
            statement.orelse,
            statement.finalbody,
        )
    if isinstance(statement, ast.Match):
        return tuple(case.body for case in statement.cases)
    return ()


def _module_symbols(
    source: str,
    *,
    allow_implicit_graph_projection: bool = False,
    module_name: str | None = None,
    require_declaration_facts: bool = False,
) -> _ModuleSymbols:
    return _ModuleSymbols.from_source(
        source,
        allow_implicit_graph_projection=allow_implicit_graph_projection,
        module_name=module_name,
        require_declaration_facts=require_declaration_facts,
    )


def _resolve_import_module(node: ast.ImportFrom, module_name: str | None) -> str | None:
    if node.level == 0:
        return node.module
    if module_name is None:
        return None
    package = module_name.split(".")[:-1]
    if node.level > len(package):
        return None
    prefix = package[: len(package) - (node.level - 1)]
    return ".".join((*prefix, *(node.module or "").split("."))).rstrip(".")


def _module_name(relative_path: str) -> str | None:
    path = Path(relative_path)
    if path.suffix != ".py" or path.parts[:1] != ("src",):
        return None
    return ".".join(path.with_suffix("").parts[1:])


class _Collector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (
        PositionProvider,
        ParentNodeProvider,
        QualifiedNameProvider,
        ScopeProvider,
    )

    def __init__(
        self,
        relative_path: str,
        baseline_revision: str,
        fields: dict[str, FieldOwnership],
        symbols: _ModuleSymbols | None = None,
        source: str = "",
    ) -> None:
        self.relative_path = relative_path
        self.baseline_revision = baseline_revision
        self.fields = fields
        self.symbols = symbols or _module_symbols("")
        self.source_lines = source.splitlines()
        self.tracked_attributes: dict[int, set[str]] = {}
        self.typed_fields = self.symbols.class_fields
        self.call_symbols = self.symbols.call_symbols
        self.lexical_names: list[str] = []
        self.aliases: dict[int, set[str]] = {}
        self.known_aliases: dict[int, set[str]] = {}
        self.possible_aliases: dict[int, set[str]] = {}
        self.receiver_types: dict[int, dict[str, str]] = {}
        self.binding_types: dict[int, dict[str, str | None]] = {}
        self.shadowed_symbols: dict[int, set[str]] = {}
        self.return_annotations: list[str | None] = []
        self.records: list[
            tuple[str, str, str | None, AccessKind, int, int, ProjectionCallContext | None]
        ] = []
        self.diagnostics: list[
            tuple[
                str,
                DiagnosticCode,
                str,
                str,
                str,
                str,
                int,
                int,
                ProjectionCallContext | None,
            ]
        ] = []
        self.diagnostic_keys: set[tuple[int, DiagnosticCode]] = set()
        self.handled: set[int] = set()

    def visit_Module(self, node: cst.Module) -> None:
        """Seed module scope so declarations and flows use the same tables as functions."""
        scope_id = id(self.get_metadata(ScopeProvider, node))
        self.aliases.setdefault(scope_id, set())
        self.known_aliases.setdefault(scope_id, set())
        self.possible_aliases.setdefault(scope_id, set())
        self.receiver_types.setdefault(scope_id, {})
        self.binding_types.setdefault(scope_id, {})
        self.shadowed_symbols.setdefault(scope_id, set())

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        if self.lexical_names:
            self._shadow(node.name)
        variadic = tuple(
            parameter
            for parameter in (node.params.star_arg, node.params.star_kwarg)
            if isinstance(parameter, cst.Param)
        )
        seeds = {
            parameter.name.value
            for parameter in (
                *node.params.posonly_params,
                *node.params.params,
                *node.params.kwonly_params,
                *variadic,
            )
            if parameter.annotation is not None
            and self._declaration_annotation_name(parameter.annotation.annotation)
            == "GraphProjection"
        }
        scope_id = id(self.get_metadata(ScopeProvider, node.body))
        self.aliases[scope_id] = seeds
        self.known_aliases[scope_id] = set(seeds)
        self.possible_aliases[scope_id] = set()
        self.receiver_types[scope_id] = {
            parameter.name.value: self._declaration_annotation_name(parameter.annotation.annotation)
            for parameter in (
                *node.params.posonly_params,
                *node.params.params,
                *node.params.kwonly_params,
                *variadic,
            )
            if parameter.annotation is not None
            and self._declaration_annotation_name(parameter.annotation.annotation) is not None
        }
        for parameter in (
            *node.params.posonly_params,
            *node.params.params,
            *node.params.kwonly_params,
        ):
            if (
                parameter.annotation is not None
                and (owner := self._declaration_annotation_name(parameter.annotation.annotation))
                in self.typed_fields
            ):
                self.tracked_attributes.setdefault(scope_id, set()).update(
                    f"{parameter.name.value}.{field}" for field in self.typed_fields[owner]
                )
        self.binding_types[scope_id] = {
            parameter.name.value: self._declaration_annotation_name(parameter.annotation.annotation)
            for parameter in (
                *node.params.posonly_params,
                *node.params.params,
                *node.params.kwonly_params,
            )
            if parameter.annotation is not None
        }
        self.shadowed_symbols[scope_id] = {
            parameter.name.value
            for parameter in (
                *node.params.posonly_params,
                *node.params.params,
                *node.params.kwonly_params,
                *variadic,
            )
        }
        self.return_annotations.append(
            self._declaration_annotation_name(node.returns.annotation)
            if node.returns is not None
            else None
        )
        for parameter in (
            *node.params.posonly_params,
            *node.params.params,
            *node.params.kwonly_params,
            *variadic,
        ):
            if (
                parameter.annotation is not None
                and self._declaration_annotation_name(parameter.annotation.annotation)
                == _UNRESOLVED_PROJECTION
            ):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING,
                    "projection-shaped imported annotation is unresolved",
                    parameter,
                    qualified=".".join((*self.lexical_names, node.name.value)),
                )

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.return_annotations.pop()

    def visit_FunctionDef_body(self, node: cst.FunctionDef) -> None:
        self.lexical_names.append(node.name.value)

    def leave_FunctionDef_body(self, original_node: cst.FunctionDef) -> None:
        self.lexical_names.pop()

    def visit_ClassDef_body(self, node: cst.ClassDef) -> None:
        self.lexical_names.append(node.name.value)

    def leave_ClassDef_body(self, original_node: cst.ClassDef) -> None:
        self.lexical_names.pop()

    def _tracked(self, node: cst.BaseExpression) -> bool:
        if isinstance(node, cst.Name):
            return node.value in self.aliases.get(id(self.get_metadata(ScopeProvider, node)), set())
        return isinstance(node, cst.Attribute) and _attribute_key(
            node
        ) in self.tracked_attributes.get(id(self.get_metadata(ScopeProvider, node)), set())

    def _known_projection_value(self, node: cst.BaseExpression) -> bool:
        if self._tracked(node):
            return True
        if isinstance(node, cst.Await):
            return self._known_projection_value(node.expression)
        if self._producer_shape(node) == "value":
            return True
        if not isinstance(node, cst.Call):
            return False
        symbol = self._call_symbol(node.func)
        if symbol in _APPROVED_PRODUCER_ORIGINS:
            return True
        if not isinstance(node.func, cst.Name) or self._symbol_is_shadowed(node.func):
            return False
        signature = self.symbols.signatures.get(node.func.value)
        return signature is not None and signature.return_annotation == "GraphProjection"

    def _producer_shape(self, node: cst.BaseExpression) -> str | None:
        """Return an explicit producer result shape, never a name-based guess."""
        if isinstance(node, cst.Await):
            return self._producer_shape(node.expression)
        if not isinstance(node, cst.Call) or not isinstance(node.func, cst.Attribute):
            return None
        if not isinstance(node.func.value, cst.Name):
            return None
        scope_id = id(self.get_metadata(ScopeProvider, node.func.value))
        receiver_type = self.receiver_types.get(scope_id, {}).get(node.func.value.value)
        return _PROJECTION_PRODUCERS.get((receiver_type, node.func.attr.value))

    def _call_symbol(self, node: cst.BaseExpression) -> str | None:
        """Resolve only imported aliases or already-qualified callable symbols."""
        if isinstance(node, cst.Name):
            if self._symbol_is_shadowed(node):
                return None
            return self.call_symbols.get(node.value) or self.symbols.names.get(node.value)
        if not isinstance(node, cst.Attribute) or not isinstance(node.value, cst.Name):
            return None
        if self._symbol_is_shadowed(node.value):
            return None
        prefix = self.symbols.names.get(node.value.value)
        return f"{prefix}.{node.attr.value}" if prefix else None

    def _annotation_name(self, node: cst.BaseExpression) -> str | None:
        if isinstance(node, cst.Name) and self._symbol_is_shadowed(node):
            return None
        if (
            isinstance(node, cst.Attribute)
            and isinstance(node.value, cst.Name)
            and self._symbol_is_shadowed(node.value)
        ):
            return None
        return self.symbols.annotation_name(node)

    def _declaration_annotation_name(self, node: cst.BaseExpression) -> str | None:
        position = self.get_metadata(PositionProvider, node).start
        return self.symbols.declaration_annotation_name(node, (position.line, position.column))

    def _symbol_is_shadowed(self, node: cst.Name) -> bool:
        return node.value in self.shadowed_symbols.get(
            id(self.get_metadata(ScopeProvider, node)), set()
        )

    def _shadow(self, node: cst.Name) -> None:
        self.shadowed_symbols.setdefault(id(self.get_metadata(ScopeProvider, node)), set()).add(
            node.value
        )

    def _shadow_in_scope(self, node: cst.CSTNode, name: str) -> None:
        self.shadowed_symbols.setdefault(id(self.get_metadata(ScopeProvider, node)), set()).add(
            name
        )

    @staticmethod
    def _is_unbounded_annotation(annotation: str | None) -> bool:
        return annotation in {
            "Any",
            "Callable",
            "typing.Any",
            "typing.Callable",
            "object",
        }

    def _tracks_reflection_argument(self, node: cst.Call) -> bool:
        return bool(node.args) and self._projection_derived(node.args[0].value)

    def _is_reflective_attribute(self, node: cst.Attribute) -> bool:
        return node.attr.value == "__dict__" and self._projection_derived(node.value)

    def _unpack_first_producer_target(self, node: cst.Assign) -> cst.Name | None:
        if self._producer_shape(node.value) != "first_tuple_item" or len(node.targets) != 1:
            return None
        target = node.targets[0].target
        if not isinstance(target, cst.Tuple) or not target.elements:
            return None
        first = target.elements[0]
        return first.value if isinstance(first.value, cst.Name) else None

    def _known_alias(self, node: cst.Name) -> bool:
        return node.value in self.known_aliases.get(
            id(self.get_metadata(ScopeProvider, node)), set()
        )

    def _possible_alias(self, node: cst.Name) -> bool:
        return node.value in self.possible_aliases.get(
            id(self.get_metadata(ScopeProvider, node)), set()
        )

    def _projection_operand(self, node: cst.BaseExpression) -> bool:
        if self._tracked(node) or self._tracked_field_subscript(node) is not None:
            return True
        return (
            isinstance(node, cst.Call)
            and isinstance(node.func, cst.Attribute)
            and node.func.attr.value == "get"
            and self._tracked(node.func.value)
        )

    def _projection_derived(self, node: cst.BaseExpression) -> bool:
        if self._tracked(node) or self._is_projection_method_call(node):
            return True
        return isinstance(node, (cst.Attribute, cst.Subscript)) and self._projection_derived(
            node.value
        )

    def _is_projection_method_call(self, node: cst.BaseExpression) -> bool:
        if not isinstance(node, cst.Call) or not isinstance(node.func, cst.Attribute):
            return False
        if node.func.attr.value not in _SUPPORTED_PROJECTION_METHODS:
            return False
        return self._projection_derived(node.func.value)

    def _is_tracked_get_call(self, node: cst.BaseExpression) -> bool:
        return (
            isinstance(node, cst.Call)
            and isinstance(node.func, cst.Attribute)
            and node.func.attr.value == "get"
            and self._tracked(node.func.value)
        )

    def _tracked_field_subscript(self, node: cst.BaseExpression) -> cst.Subscript | None:
        """Return the root literal field subscript for a tracked subscript chain."""
        current = node
        while isinstance(current, cst.Subscript):
            if self._tracked(current.value):
                return current
            current = current.value
        return None

    def _handle_subscript_chain(self, node: cst.Subscript) -> None:
        self._handle_projection_derived(node)

    def _handle_projection_derived(self, node: cst.BaseExpression) -> None:
        self.handled.add(id(node))
        if isinstance(node, cst.Call) and isinstance(node.func, cst.Attribute):
            self._handle_projection_derived(node.func.value)
        elif isinstance(node, (cst.Attribute, cst.Subscript)):
            self._handle_projection_derived(node.value)

    def _projection_target_subscripts(
        self, node: cst.BaseAssignTargetExpression
    ) -> tuple[cst.Subscript, ...]:
        if isinstance(node, cst.Subscript):
            return (node,) if self._tracked_field_subscript(node) is not None else ()
        if isinstance(node, cst.StarredElement):
            return self._projection_target_subscripts(node.value)
        if isinstance(node, (cst.Tuple, cst.List)):
            return tuple(
                subscript
                for element in node.elements
                if element is not None
                for subscript in self._projection_target_subscripts(element.value)
            )
        return ()

    def _discard_alias(self, node: cst.Name) -> None:
        scope_id = id(self.get_metadata(ScopeProvider, node))
        self.aliases.get(scope_id, set()).discard(node.value)
        self.known_aliases.get(scope_id, set()).discard(node.value)
        self.possible_aliases.get(scope_id, set()).discard(node.value)

    def _discard_live_alias(self, node: cst.Name) -> None:
        self.aliases.get(id(self.get_metadata(ScopeProvider, node)), set()).discard(node.value)

    def _add_alias(self, node: cst.Name) -> None:
        scope_id = id(self.get_metadata(ScopeProvider, node))
        self.aliases.setdefault(scope_id, set()).add(node.value)
        self.known_aliases.setdefault(scope_id, set()).add(node.value)

    def _add_possible_alias(self, node: cst.Name) -> None:
        scope_id = id(self.get_metadata(ScopeProvider, node))
        self.aliases.setdefault(scope_id, set()).discard(node.value)
        self.known_aliases.setdefault(scope_id, set()).add(node.value)
        self.possible_aliases.setdefault(scope_id, set()).add(node.value)

    def _inside_control_flow(self, node: cst.CSTNode) -> bool:
        current: cst.CSTNode | None = node
        while current is not None:
            if isinstance(
                current,
                (cst.If, cst.For, cst.While, cst.Try, cst.With, cst.Match, cst.ExceptHandler),
            ):
                return True
            if isinstance(current, (cst.Module, cst.FunctionDef, cst.ClassDef)):
                return False
            current = self.get_metadata(ParentNodeProvider, current, None)
        return False

    def _unresolved_control_binding(
        self, target: cst.Name, value: cst.BaseExpression | None, node: cst.CSTNode
    ) -> bool:
        if not self._inside_control_flow(node) or not (
            (value is not None and self._known_projection_value(value))
            or self._known_alias(target)
            or self._possible_alias(target)
        ):
            return False
        was_possible = self._possible_alias(target)
        self._add_possible_alias(target)
        if not was_possible:
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING,
                "control-flow projection binding is unresolved",
                node,
            )
        return True

    def _target_names(self, node: cst.BaseAssignTargetExpression) -> tuple[cst.Name, ...]:
        if isinstance(node, cst.Name):
            return (node,)
        if isinstance(node, cst.StarredElement):
            return self._target_names(node.value)
        if isinstance(node, (cst.Tuple, cst.List)):
            return tuple(
                name
                for element in node.elements
                if element is not None
                for name in self._target_names(element.value)
            )
        return ()

    def _expression(self, node: cst.CSTNode) -> str:
        return ast.unparse(ast.parse(cst.Module([]).code_for_node(node)))

    def _diagnostic_expression(self, node: cst.CSTNode) -> str:
        try:
            return self._expression(node)
        except SyntaxError:
            return cst.Module([]).code_for_node(node).strip()

    def _qualified_import_origin(self, node: cst.CSTNode) -> str | None:
        """Return one exact imported qualified name, never a spelling-derived guess."""
        resolved = self.get_metadata(QualifiedNameProvider, node, frozenset())
        names = resolved() if callable(resolved) else resolved
        if not isinstance(names, set) or len(names) != 1:
            return None
        name = next(iter(names))
        if not isinstance(name, QualifiedName) or name.source.name != "IMPORT":
            return None
        approved_modules = frozenset(
            {
                "orchestrator.graph",
                "orchestrator.graph.callbacks",
                "orchestrator.graph._commands",
                "orchestrator.graph.patch_validator",
                "orchestrator.graph.projections",
                "orchestrator.graph.projection_queries",
                "orchestrator.graph.scheduler",
                "orchestrator.graph_runtime",
                "orchestrator.graph_runtime.controller",
                "orchestrator.graph_runtime.dispatch",
            }
        )
        return name.name if name.name.rpartition(".")[0] in approved_modules else None

    def _call_context(self, node: cst.CSTNode) -> ProjectionCallContext | None:
        """Capture one collector-proven call role without performing new dataflow."""
        if not isinstance(node, cst.Call):
            return None
        callee_origin = self._qualified_import_origin(node.func)
        if isinstance(node.func, cst.Attribute) and self._tracked(node.func.value):
            return ProjectionCallContext(
                callee_origin=callee_origin,
                receiver_type_origin="orchestrator.graph.GraphProjection",
                projection_role="receiver",
                projection_expression=self._expression(node.func.value),
            )
        roles: list[ProjectionCallContext] = []
        positional_index = 0
        preceding_star: Literal["*", "**"] | None = None
        for argument in node.args:
            if argument.star:
                if self._known_projection_value(argument.value):
                    roles.append(
                        ProjectionCallContext(
                            callee_origin=callee_origin,
                            projection_role="ambiguous",
                            projection_expression=self._expression(argument.value),
                            argument_star=argument.star,
                        )
                    )
                preceding_star = argument.star
                continue
            if not self._known_projection_value(argument.value):
                if argument.keyword is None:
                    positional_index += 1
                continue
            if argument.keyword is not None:
                roles.append(
                    ProjectionCallContext(
                        callee_origin=callee_origin,
                        projection_role="keyword",
                        keyword_name=argument.keyword.value,
                        projection_expression=self._expression(argument.value),
                    )
                )
            elif preceding_star:
                roles.append(
                    ProjectionCallContext(
                        callee_origin=callee_origin,
                        projection_role="ambiguous",
                        projection_expression=self._expression(argument.value),
                        preceding_star=preceding_star,
                    )
                )
            else:
                roles.append(
                    ProjectionCallContext(
                        callee_origin=callee_origin,
                        projection_role="positional",
                        positional_index=positional_index,
                        projection_expression=self._expression(argument.value),
                    )
                )
            if argument.keyword is None:
                positional_index += 1
        return roles[0] if len(roles) == 1 else None

    def _context(self, node: cst.CSTNode) -> ProjectionCallContext | None:
        """Return context already proved while classifying this collector site."""
        call_context = self._call_context(node)
        if call_context is not None:
            return call_context
        if isinstance(node, cst.Param) and node.annotation is not None:
            annotation = self._qualified_import_origin(node.annotation.annotation)
            if annotation in _GRAPH_PROJECTION_TYPE_ORIGINS:
                return ProjectionCallContext(
                    receiver_type_origin=annotation,
                    projection_role="receiver",
                    projection_expression=self._expression(node.name),
                )
        if isinstance(node, cst.Comparison):
            nested: list[ProjectionCallContext] = []

            class Visitor(cst.CSTVisitor):
                def visit_Call(_, call: cst.Call) -> None:
                    context = self._call_context(call)
                    if context is not None:
                        nested.append(context)

            node.visit(Visitor())
            if len(nested) == 1:
                return nested[0]
        if isinstance(node, cst.Call) and isinstance(node.func, cst.Attribute):
            if field_subscript := self._tracked_field_subscript(node.func.value):
                field = (
                    _literal_key(field_subscript.slice[0].slice.value)
                    if len(field_subscript.slice) == 1
                    and isinstance(field_subscript.slice[0].slice, cst.Index)
                    else None
                )
                return ProjectionCallContext(
                    callee_origin=self._qualified_import_origin(node.func),
                    receiver_type_origin="orchestrator.graph.GraphProjection",
                    projection_role="receiver",
                    projection_expression=self._expression(node.func.value),
                    physical_old_field_name=field if field in self.fields else None,
                    physical_access_kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                    physical_operation_shape=AccessKind.LITERAL_SUBSCRIPT_READ.value,
                )
        if (
            isinstance(node, cst.Call)
            and (origin := self._qualified_import_origin(node.func)) in _DERIVED_VALUE_SINK_ORIGINS
        ):
            derived_arguments = [
                argument.value for argument in node.args if self._projection_derived(argument.value)
            ]
            if derived_arguments:
                return ProjectionCallContext(
                    callee_origin=origin,
                    projection_role="derived_value",
                    projection_expression=self._expression(derived_arguments[0]),
                )
        value = node.value if isinstance(node, (cst.Assign, cst.AnnAssign, cst.Return)) else None
        if (
            isinstance(value, cst.Call)
            and (origin := self._qualified_import_origin(value.func)) in _DERIVED_VALUE_SINK_ORIGINS
        ):
            derived_arguments = [
                argument.value
                for argument in value.args
                if self._projection_derived(argument.value)
            ]
            if derived_arguments:
                return ProjectionCallContext(
                    callee_origin=origin,
                    projection_role="derived_value",
                    projection_expression=self._expression(derived_arguments[0]),
                )
        if (
            isinstance(value, cst.Call)
            and (origin := self._qualified_import_origin(value.func)) in _CONTEXT_PRODUCER_ORIGINS
        ):
            return ProjectionCallContext(
                callee_origin=origin,
                projection_role="receiver",
                projection_expression=self._expression(value),
            )
        if value is not None and self._known_projection_value(value):
            if isinstance(value, cst.Call):
                return ProjectionCallContext(
                    callee_origin=self._qualified_import_origin(value.func),
                    receiver_type_origin=(
                        "orchestrator.graph.GraphProjection"
                        if self._qualified_import_origin(value.func) is None
                        else None
                    ),
                    projection_role="receiver",
                    projection_expression=self._expression(value),
                )
            return ProjectionCallContext(
                receiver_type_origin="orchestrator.graph.GraphProjection",
                projection_role="receiver",
                projection_expression=self._expression(value),
            )
        nested_physical: list[ProjectionCallContext] = []

        class PhysicalVisitor(cst.CSTVisitor):
            def visit_Subscript(_, subscript: cst.Subscript) -> None:
                field_subscript = self._tracked_field_subscript(subscript)
                if (
                    field_subscript is None
                    or len(field_subscript.slice) != 1
                    or not isinstance(field_subscript.slice[0].slice, cst.Index)
                ):
                    return
                field = _literal_key(field_subscript.slice[0].slice.value)
                if field not in self.fields:
                    return
                nested_physical.append(
                    ProjectionCallContext(
                        receiver_type_origin="orchestrator.graph.GraphProjection",
                        projection_role="receiver",
                        projection_expression=self._expression(subscript.value),
                        physical_old_field_name=field,
                        physical_access_kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                        physical_operation_shape=AccessKind.LITERAL_SUBSCRIPT_READ.value,
                    )
                )

        node.visit(PhysicalVisitor())
        unique_physical = {item.model_dump_json(): item for item in nested_physical}
        if len(unique_physical) == 1:
            return next(iter(unique_physical.values()))
        return None

    def _physical_context(
        self, kind: AccessKind, field: str | None, node: cst.CSTNode
    ) -> ProjectionCallContext:
        call_context = self._call_context(node)
        receiver = (
            node.func.value
            if isinstance(node, cst.Call) and isinstance(node.func, cst.Attribute)
            else node.target.value
            if isinstance(node, cst.Del) and isinstance(node.target, cst.Subscript)
            else node.value
            if isinstance(node, cst.Subscript)
            else node
        )
        return ProjectionCallContext(
            callee_origin=call_context.callee_origin if call_context is not None else None,
            receiver_type_origin="orchestrator.graph.GraphProjection",
            projection_role="receiver",
            projection_expression=self._expression(receiver),
            physical_old_field_name=field,
            physical_access_kind=kind,
            physical_operation_shape=kind.value,
        )

    def _record(self, kind: AccessKind, field: str | None, node: cst.CSTNode) -> None:
        qualified = ".".join(self.lexical_names) or "<module>"
        position = self.get_metadata(PositionProvider, node).start
        self.records.append(
            (
                qualified,
                self._expression(node),
                field,
                kind,
                position.line,
                position.column,
                self._physical_context(kind, field, node),
            )
        )

    def _diagnostic(
        self,
        code: DiagnosticCode,
        message: str,
        node: cst.CSTNode,
        *,
        qualified: str | None = None,
    ) -> None:
        key = (id(node), code)
        if key in self.diagnostic_keys:
            return
        self.diagnostic_keys.add(key)
        position = self.get_metadata(PositionProvider, node).start
        self.diagnostics.append(
            (
                qualified or ".".join(self.lexical_names) or "<module>",
                code,
                message,
                " ".join(self.source_lines[position.line - 1].strip().split())
                if position.line <= len(self.source_lines)
                else cst.Module([]).code_for_node(node).strip(),
                type(node).__name__,
                self._diagnostic_expression(node),
                position.line,
                position.column,
                self._context(node),
            )
        )

    def _field_from_subscript(self, node: cst.Subscript) -> str | None:
        if not self._tracked(node.value):
            return None
        if len(node.slice) != 1 or not isinstance(node.slice[0].slice, cst.Index):
            self._diagnostic(
                DiagnosticCode.COMPUTED_KEY, "projection key must be one literal string", node
            )
            return None
        field = _literal_key(node.slice[0].slice.value)
        if field is None:
            self._diagnostic(
                DiagnosticCode.COMPUTED_KEY, "projection key must be one literal string", node
            )
        elif field not in self.fields:
            self._diagnostic(
                DiagnosticCode.UNKNOWN_FIELD, f"unknown projection field: {field}", node
            )
        return field if field in self.fields else None

    def _field_from_get_call(self, node: cst.Call) -> str | None:
        if not self._valid_method_shape("get", node.args):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL,
                "invalid projection.get call shape",
                node,
            )
            return None
        field = _literal_key(node.args[0].value)
        if field is None:
            self._diagnostic(
                DiagnosticCode.COMPUTED_KEY,
                "projection key must be a literal string",
                node,
            )
        elif field not in self.fields:
            self._diagnostic(
                DiagnosticCode.UNKNOWN_FIELD, f"unknown projection field: {field}", node
            )
        return field if field in self.fields else None

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        annotation = self._declaration_annotation_name(node.annotation.annotation)
        if (
            node.value is not None
            and (
                self._is_unbounded_annotation(annotation)
                or annotation in {_CONTAINS_PROJECTION, _UNRESOLVED_PROJECTION}
            )
            and self._known_projection_value(node.value)
        ):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING,
                "projection escapes through an unbounded annotation",
                node,
            )
        return

    def leave_AnnAssign(self, original_node: cst.AnnAssign) -> None:
        node = original_node
        if not isinstance(node.target, cst.Name):
            if node.value is not None and self._tracked(node.value):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "unsupported projection binding", node
                )
            return
        scope = self.aliases.get(id(self.get_metadata(ScopeProvider, node.target)))
        if scope is None:
            return
        scope_id = id(self.get_metadata(ScopeProvider, node.target))
        annotation = self._declaration_annotation_name(node.annotation.annotation)
        self.binding_types.setdefault(scope_id, {})[node.target.value] = annotation
        if annotation in self.typed_fields:
            self.receiver_types.setdefault(scope_id, {})[node.target.value] = annotation
        else:
            self.receiver_types.setdefault(scope_id, {}).pop(node.target.value, None)
        if annotation == "GraphProjection":
            if not self._unresolved_control_binding(node.target, node.value, node):
                self._add_alias(node.target)
        else:
            if node.value is not None and self._known_projection_value(node.value):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING,
                    "annotated assignment loses projection type",
                    node,
                )
            self._discard_alias(node.target)

    def visit_Return(self, node: cst.Return) -> None:
        if (
            node.value is not None
            and self._known_projection_value(node.value)
            and (not self.return_annotations or self.return_annotations[-1] != "GraphProjection")
        ):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING,
                "projection escapes through an unresolved return annotation",
                node,
            )

    def _discard_attributes_for(self, node: cst.Name) -> None:
        scope_id = id(self.get_metadata(ScopeProvider, node))
        prefix = f"{node.value}."
        attributes = self.tracked_attributes.get(scope_id, set())
        attributes.difference_update(
            {attribute for attribute in attributes if attribute.startswith(prefix)}
        )

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        if isinstance(node.target, cst.Subscript):
            field_subscript = self._tracked_field_subscript(node.target)
            if field_subscript is not None:
                self._field_from_subscript(field_subscript)
                self._handle_subscript_chain(node.target)
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_MUTATION,
                    "augmented projection mutation is unsupported",
                    node,
                )
                return
        if (isinstance(node.target, cst.Name) and self._known_alias(node.target)) or self._tracked(
            node.value
        ):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING, "augmented projection binding", node
            )

    def leave_AugAssign(self, original_node: cst.AugAssign) -> None:
        if isinstance(original_node.target, cst.Name) and self._known_alias(original_node.target):
            self._discard_live_alias(original_node.target)

    def visit_Assign(self, node: cst.Assign) -> None:
        for target in node.targets:
            for name in self._target_names(target.target):
                self._shadow(name)
        for target in node.targets:
            if not isinstance(target.target, (cst.Tuple, cst.List)):
                continue
            for subscript in self._projection_target_subscripts(target.target):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING,
                    "destructured projection assignment is unsupported",
                    subscript,
                )
                self._handle_subscript_chain(subscript)

    def leave_Assign(self, original_node: cst.Assign) -> None:
        node = original_node
        has_destructured_projection_target = any(
            isinstance(target.target, (cst.Tuple, cst.List))
            and self._projection_target_subscripts(target.target)
            for target in node.targets
        )
        if len(node.targets) == 1 and isinstance(node.targets[0].target, cst.Attribute):
            target = node.targets[0].target
            attribute = _attribute_key(target)
            if attribute is not None and isinstance(target.value, cst.Name):
                scope_id = id(self.get_metadata(ScopeProvider, target))
                attributes = self.tracked_attributes.setdefault(scope_id, set())
                attributes.discard(attribute)
                receiver_type = self.receiver_types.get(scope_id, {}).get(target.value.value)
                if (
                    self._known_projection_value(node.value)
                    and receiver_type in self.typed_fields
                    and target.attr.value in self.typed_fields[receiver_type]
                ):
                    attributes.add(attribute)
                elif self._known_projection_value(node.value):
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_BINDING,
                        "projection assignment requires a recognized receiver type and field",
                        node,
                    )
            return
        if producer_target := self._unpack_first_producer_target(node):
            self._add_alias(producer_target)
            return
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0].target, cst.Name)
            and isinstance(node.value, cst.Call)
            and (owner := self._annotation_name(node.value.func)) in self.typed_fields
        ):
            scope_id = id(self.get_metadata(ScopeProvider, node.targets[0].target))
            self._discard_attributes_for(node.targets[0].target)
            self.receiver_types.setdefault(scope_id, {})[node.targets[0].target.value] = owner
            self.binding_types.setdefault(scope_id, {})[node.targets[0].target.value] = owner
            for argument in node.value.args:
                if (
                    argument.keyword is not None
                    and argument.keyword.value in self.typed_fields[owner]
                    and self._known_projection_value(argument.value)
                ):
                    self.tracked_attributes.setdefault(scope_id, set()).add(
                        f"{node.targets[0].target.value}.{argument.keyword.value}"
                    )
            return
        if len(node.targets) != 1 or not isinstance(node.targets[0].target, cst.Name):
            target_names = tuple(
                name for target in node.targets for name in self._target_names(target.target)
            )
            if not has_destructured_projection_target and (
                self._tracked(node.value) or any(self._known_alias(name) for name in target_names)
            ):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "unsupported projection binding", node
                )
            for name in target_names:
                self._discard_live_alias(name)
            return
        scope = self.aliases.get(id(self.get_metadata(ScopeProvider, node.targets[0].target)))
        if scope is None:
            return
        target = node.targets[0].target
        self.receiver_types.setdefault(id(self.get_metadata(ScopeProvider, target)), {}).pop(
            target.value, None
        )
        binding_types = self.binding_types.setdefault(
            id(self.get_metadata(ScopeProvider, target)), {}
        )
        binding_type = binding_types.pop(target.value, None)
        if self._known_projection_value(node.value) and binding_type in {
            "Any",
            "Callable",
            "typing.Any",
            "typing.Callable",
            "object",
        }:
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING,
                "projection escapes through a previously unbounded binding",
                node,
            )
            self._discard_alias(target)
            return
        self._discard_attributes_for(target)
        if self._unresolved_control_binding(target, node.value, node):
            return
        if self._known_projection_value(node.value):
            self._add_alias(target)
        else:
            self._discard_alias(target)

    def visit_Import(self, node: cst.Import) -> None:
        if not self.lexical_names:
            return
        for alias in node.names:
            name = alias.asname.name.value if alias.asname is not None else alias.name.value
            self._shadow_in_scope(node, name)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if not self.lexical_names:
            return
        if isinstance(node.names, cst.ImportStar):
            return
        for alias in node.names:
            name = alias.asname.name.value if alias.asname is not None else alias.name.value
            self._shadow_in_scope(node, name)

    def visit_For(self, node: cst.For) -> None:
        for target in self._target_names(node.target):
            if self._known_alias(target):
                self._add_possible_alias(target)
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "loop rebinds projection alias", node
                )
        if self._tracked(node.iter):
            self._record(AccessKind.DIRECT_ITERATION, None, node.iter)

    def visit_NamedExpr(self, node: cst.NamedExpr) -> None:
        if isinstance(node.target, cst.Name):
            if self._known_alias(node.target):
                self._add_possible_alias(node.target)
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING,
                    "assignment expression rebinds projection alias",
                    node,
                )

    def visit_With(self, node: cst.With) -> None:
        for item in node.items:
            if item.asname is not None and self._known_alias(item.asname.name):
                self._add_possible_alias(item.asname.name)
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "with target rebinds projection alias", node
                )

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> None:
        if node.name is not None and self._known_alias(node.name.name):
            self._add_possible_alias(node.name.name)
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING,
                "exception target rebinds projection alias",
                node,
            )

    def visit_Call(self, node: cst.Call) -> None:
        if id(node) in self.handled:
            return
        if any(
            isinstance(argument.value, (cst.List, cst.Tuple, cst.Set, cst.Dict))
            and self._nested_projection_value(argument.value)
            for argument in node.args
        ):
            for argument in node.args:
                if isinstance(argument.value, (cst.List, cst.Tuple, cst.Set, cst.Dict)):
                    self.handled.add(id(argument.value))
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL,
                "projection collection escapes through a callable",
                node,
            )
            return
        if any(
            argument.star in {"*", "**"} and self._tracked(argument.value) for argument in node.args
        ):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING,
                "unpacking GraphProjection is unsupported",
                node,
            )
            return
        if _name(node.func) in {"getattr", "setattr", "vars"} and self._tracks_reflection_argument(
            node
        ):
            self._diagnostic(
                DiagnosticCode.REFLECTION, "reflection on GraphProjection is unsupported", node
            )
            return
        if _name(node.func) == "dict" and node.args and self._tracked(node.args[0].value):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING, "dict(GraphProjection) is unsupported", node
            )
            return
        if isinstance(node.func, cst.Attribute):
            method = node.func.attr.value
            receiver = node.func.value
            if self._is_tracked_get_call(receiver):
                self.handled.add(id(receiver))
                if method not in {"append", "extend"}:
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"projection.get result method {method} is unsupported",
                        node,
                    )
                elif not self._valid_method_shape(method, node.args):
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"invalid projection.{method} call shape",
                        node,
                    )
                else:
                    field = self._field_from_get_call(receiver)
                    if field is not None:
                        self._record(AccessKind.APPEND_EXTEND, field, node)
                return
            if self._tracked(receiver) and method in {
                "get",
                "keys",
                "values",
                "items",
                "setdefault",
                "pop",
            }:
                if not self._valid_method_shape(method, node.args):
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"invalid projection.{method} call shape",
                        node,
                    )
                    self.handled.add(id(receiver))
                    return
                field = None
                if method in {"get", "setdefault", "pop"}:
                    if not node.args:
                        self._diagnostic(
                            DiagnosticCode.UNSUPPORTED_CALL,
                            f"projection.{method} requires a literal key",
                            node,
                        )
                        return
                    field = _literal_key(node.args[0].value)
                    if field is None:
                        self._diagnostic(
                            DiagnosticCode.COMPUTED_KEY,
                            "projection key must be a literal string",
                            node,
                        )
                        return
                    if field not in self.fields:
                        self._diagnostic(
                            DiagnosticCode.UNKNOWN_FIELD, f"unknown projection field: {field}", node
                        )
                        return
                kind = AccessKind.DELETE_POP if method == "pop" else AccessKind(method)
                self._record(kind, field, node)
                self.handled.add(id(node))
                return
            if self._tracked(receiver):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_CALL, f"projection.{method} is unsupported", node
                )
                return
            field_subscript = self._tracked_field_subscript(receiver)
            if field_subscript is not None:
                field = self._field_from_subscript(field_subscript)
                self._handle_subscript_chain(receiver) if isinstance(
                    receiver, cst.Subscript
                ) else None
                if method not in {"append", "extend"}:
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"projection field method {method} is unsupported",
                        node,
                    )
                elif not self._valid_method_shape(method, node.args):
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"invalid projection.{method} call shape",
                        node,
                    )
                elif field is not None:
                    self._record(AccessKind.APPEND_EXTEND, field, node)
                return
        if (
            self._call_symbol(node.func) == "typing.cast"
            and len(node.args) == 2
            and not any(argument.star or argument.keyword is not None for argument in node.args)
            and isinstance(node.args[1].value, cst.Subscript)
        ):
            field_subscript = self._tracked_field_subscript(node.args[1].value)
            field = self._field_from_subscript(field_subscript) if field_subscript else None
            if field is not None:
                self._record(AccessKind.UNPACK_CAST, field, node)
                self._handle_subscript_chain(node.args[1].value)
            return
        if self._call_symbol(node.func) == "typing.cast" and any(
            self._projection_operand(arg.value) for arg in node.args
        ):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL, "invalid cast projection call shape", node
            )
            for argument in node.args:
                if isinstance(argument.value, cst.Subscript):
                    self._handle_subscript_chain(argument.value)
            return
        if self._projection_derived(node.func):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL,
                "calling a projection-derived value is unsupported",
                node,
            )
            if isinstance(node.func, cst.Subscript):
                self._handle_subscript_chain(node.func)
            else:
                self._handle_projection_derived(node.func)
            return
        if self._tracked(node.func):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL, "calling GraphProjection is unsupported", node
            )
            return
        if self._annotation_name(node.func) == "GraphProjection":
            for argument in node.args:
                if argument.keyword is not None:
                    field = argument.keyword.value
                    if field in self.fields:
                        self._record(AccessKind.FIXTURE_CONSTRUCTION, field, node)
                        if self._projection_operand(argument.value):
                            self._record(AccessKind.UNTYPED_ESCAPE, None, argument.value)
                    else:
                        self._diagnostic(
                            DiagnosticCode.UNKNOWN_FIELD,
                            f"unknown projection field: {field}",
                            argument,
                        )
                else:
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CONSTRUCTION,
                        "GraphProjection construction must use literal keyword fields",
                        argument,
                    )
            return
        if _name(node.func) == "callback" and any(
            self._known_projection_value(arg.value) for arg in node.args
        ):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL,
                "projection escapes through an unknown callback",
                node,
            )
            return
        if (
            isinstance(node.func, cst.Name)
            and not self._symbol_is_shadowed(node.func)
            and node.func.value in self.symbols.signatures
        ):
            bound = self.symbols.signatures[node.func.value].bind(node.args)
            tracked_arguments = tuple(
                self._projection_value(argument.value) and id(argument.value) not in self.handled
                for argument in node.args
            )
            if any(tracked_arguments):
                if bound is not None and all(
                    not tracked or annotation == "GraphProjection"
                    for tracked, annotation in zip(tracked_arguments, bound, strict=True)
                ):
                    return
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_CALL,
                    "projection escapes through a non-projection or ambiguous callable parameter",
                    node,
                )
                return
        if any(self._projection_derived(argument.value) for argument in node.args):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL,
                "projection escapes through an unrecognized callable",
                node,
            )
            for argument in node.args:
                if self._projection_derived(argument.value):
                    self._handle_projection_derived(argument.value)

    def visit_Attribute(self, node: cst.Attribute) -> None:
        if self._is_reflective_attribute(node):
            self._diagnostic(
                DiagnosticCode.REFLECTION, "__dict__ on GraphProjection is unsupported", node
            )

    def _nested_projection_value(self, node: cst.BaseExpression) -> bool:
        if self._known_projection_value(node):
            return True
        if isinstance(node, (cst.List, cst.Tuple, cst.Set)):
            return any(
                element is not None and self._nested_projection_value(element.value)
                for element in node.elements
            )
        if isinstance(node, cst.Dict):
            return any(
                isinstance(element, cst.DictElement)
                and self._nested_projection_value(element.value)
                for element in node.elements
            )
        return False

    def _projection_value(self, node: cst.BaseExpression) -> bool:
        return self._nested_projection_value(node)

    def _collection_escape(self, node: cst.BaseExpression) -> None:
        if id(node) in self.handled:
            return
        parent = self.get_metadata(ParentNodeProvider, node)
        if isinstance(parent, (cst.List, cst.Tuple, cst.Set, cst.Dict, cst.DictElement)):
            return
        if not self._nested_projection_value(node):
            return
        if isinstance(parent, (cst.Assign, cst.AnnAssign, cst.Return)):
            if isinstance(parent, cst.Assign) and (
                len(parent.targets) != 1 or not isinstance(parent.targets[0].target, cst.Name)
            ):
                return
            self.handled.add(id(node))
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING,
                "projection escapes through a collection constructor",
                node,
            )
        elif isinstance(parent, cst.Arg):
            self.handled.add(id(node))
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_CALL,
                "projection collection escapes through a callable",
                node,
            )

    def visit_List(self, node: cst.List) -> None:
        self._collection_escape(node)

    def visit_Tuple(self, node: cst.Tuple) -> None:
        self._collection_escape(node)

    def visit_Set(self, node: cst.Set) -> None:
        self._collection_escape(node)

    def visit_Dict(self, node: cst.Dict) -> None:
        self._collection_escape(node)

    @staticmethod
    def _valid_method_shape(method: str, args: tuple[cst.Arg, ...]) -> bool:
        if any(argument.star or argument.keyword is not None for argument in args):
            return False
        arities = {
            "keys": {0},
            "values": {0},
            "items": {0},
            "get": {1, 2},
            "pop": {1, 2},
            "setdefault": {1, 2},
            "append": {1},
            "extend": {1},
        }
        return len(args) in arities[method]

    def visit_StarredElement(self, node: cst.StarredElement) -> None:
        parent = self.get_metadata(ParentNodeProvider, node)
        if isinstance(parent, (cst.Tuple, cst.List)) and isinstance(
            self.get_metadata(ParentNodeProvider, parent), cst.AssignTarget
        ):
            return
        if self._tracked(node.value):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING,
                "unpacking GraphProjection is unsupported",
                node,
            )

    def visit_StarredDictElement(self, node: cst.StarredDictElement) -> None:
        if self._tracked(node.value):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING,
                "unpacking GraphProjection is unsupported",
                node,
            )

    def visit_Comparison(self, node: cst.Comparison) -> None:
        operands = (node.left, *(comparison.comparator for comparison in node.comparisons))
        if len(node.comparisons) != 1:
            projection_operands = tuple(
                operand for operand in operands if self._projection_operand(operand)
            )
            if projection_operands:
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_COMPARISON,
                    "chained projection comparison is unsupported",
                    node,
                )
                for operand in projection_operands:
                    if isinstance(operand, cst.Subscript):
                        self._handle_subscript_chain(operand)
                    elif isinstance(operand, cst.Call):
                        self.handled.add(id(operand))
            return
        target = node.comparisons[0]
        if isinstance(target.operator, (cst.In, cst.NotIn)) and self._tracked(target.comparator):
            field = _literal_key(node.left)
            if field is None:
                self._diagnostic(
                    DiagnosticCode.COMPUTED_KEY,
                    "projection membership requires a literal string",
                    node,
                )
            elif field not in self.fields:
                self._diagnostic(
                    DiagnosticCode.UNKNOWN_FIELD, f"unknown projection field: {field}", node
                )
            else:
                self._record(AccessKind.MEMBERSHIP, field, node)
            return
        projection_operands = tuple(
            operand for operand in operands if self._projection_operand(operand)
        )
        if projection_operands:
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_COMPARISON,
                "projection comparison is unsupported",
                node,
            )
            for operand in projection_operands:
                if isinstance(operand, cst.Subscript):
                    self._handle_subscript_chain(operand)
                elif isinstance(operand, cst.Call):
                    self.handled.add(id(operand))

    def visit_CompFor(self, node: cst.CompFor) -> None:
        if self._tracked(node.iter):
            self._record(AccessKind.DIRECT_ITERATION, None, node.iter)

    def visit_Del(self, node: cst.Del) -> None:
        if isinstance(node.target, (cst.Tuple, cst.List)):
            for subscript in self._projection_target_subscripts(node.target):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_MUTATION,
                    "multi-target projection deletion is unsupported",
                    subscript,
                )
                self._handle_subscript_chain(subscript)
            return
        if isinstance(node.target, cst.Subscript):
            field_subscript = self._tracked_field_subscript(node.target)
            if field_subscript is None:
                return
            field = self._field_from_subscript(field_subscript)
            self._handle_subscript_chain(node.target)
            if field is not None:
                self._record(AccessKind.DELETE_POP, field, node)

    def visit_Subscript(self, node: cst.Subscript) -> None:
        if id(node) in self.handled:
            return
        field_subscript = self._tracked_field_subscript(node)
        if field_subscript is None:
            return
        field = self._field_from_subscript(field_subscript)
        if field is None:
            return
        self._handle_subscript_chain(node)
        parent = self.get_metadata(ParentNodeProvider, node)
        if isinstance(parent, cst.AssignTarget) or (
            isinstance(parent, cst.AnnAssign) and parent.target is node
        ):
            kind = (
                AccessKind.NESTED_ASSIGNMENT
                if field_subscript is not node
                else AccessKind.DIRECT_ASSIGNMENT
            )
            self._record(kind, field, node)
        elif isinstance(parent, cst.Assign) and isinstance(
            parent.targets[0].target, (cst.Tuple, cst.List)
        ):
            self._record(AccessKind.UNPACK_CAST, field, node)
        else:
            self._record(AccessKind.LITERAL_SUBSCRIPT_READ, field, node)

    def result(self) -> SourceInventory:
        counted: dict[tuple[str, str], int] = {}
        occurrences: list[AccessOccurrence] = []
        for qualified, expression, field, kind, line, column, context in self.records:
            key = (qualified, expression)
            ordinal = counted.get(key, 0)
            counted[key] = ordinal + 1
            occurrences.append(
                AccessOccurrence(
                    occurrence_id=occurrence_id(
                        self.baseline_revision, self.relative_path, qualified, expression, ordinal
                    ),
                    relative_path=self.relative_path,
                    qualified_function=qualified,
                    normalized_expression=expression,
                    same_expression_ordinal=ordinal,
                    old_field_name=field,
                    kind=kind,
                    line=line,
                    column=column,
                    ordering_sensitivity_disposition=self.fields[field].ordering
                    if field
                    else "not_applicable",
                    context=context,
                )
            )
        diagnostic_records = sorted(
            self.diagnostics,
            key=lambda item: (item[6], item[7], item[1]),
        )
        diagnostic_ordinals: dict[tuple[str, DiagnosticCode, str], int] = {}
        diagnostics_list: list[InventoryDiagnostic] = []
        for (
            qualified,
            code,
            message,
            pattern,
            node_type,
            cst_expression,
            line,
            column,
            context,
        ) in diagnostic_records:
            identity = (qualified, code, pattern)
            ordinal = diagnostic_ordinals.get(identity, 0)
            diagnostic_ordinals[identity] = ordinal + 1
            diagnostics_list.append(
                InventoryDiagnostic(
                    relative_path=self.relative_path,
                    qualified_function=qualified,
                    line=line,
                    column=column,
                    code=code,
                    message=message,
                    normalized_source_pattern=pattern,
                    same_pattern_ordinal=ordinal,
                    source_node_type=node_type,
                    normalized_cst_expression=cst_expression,
                    remediation=_remediation(code),
                    context=context,
                )
            )
        diagnostics = tuple(diagnostics_list)
        return SourceInventory(
            relative_path=self.relative_path,
            baseline_revision=self.baseline_revision,
            occurrences=tuple(
                sorted(
                    occurrences,
                    key=lambda item: (
                        item.relative_path,
                        item.qualified_function,
                        item.line,
                        item.column,
                        item.kind,
                    ),
                )
            ),
            diagnostics=diagnostics,
        )


def collect_source(source: str, *, relative_path: str, baseline_revision: str) -> SourceInventory:
    """Collect supported GraphProjection accesses from one source string.

    Syntax outside the bounded supported family produces diagnostics instead of a partial claim.
    """
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as error:
        return SourceInventory(
            relative_path=relative_path,
            baseline_revision=baseline_revision,
            occurrences=(),
            diagnostics=(
                InventoryDiagnostic(
                    relative_path=relative_path,
                    qualified_function="<module>",
                    line=error.raw_line,
                    column=error.raw_column,
                    code=DiagnosticCode.PARSE_ERROR,
                    message=str(error),
                    normalized_source_pattern=(
                        " ".join(source.splitlines()[error.raw_line - 1].strip().split())
                        if error.raw_line <= len(source.splitlines())
                        else str(error)
                    ),
                    same_pattern_ordinal=0,
                    source_node_type="ParseError",
                    normalized_cst_expression=str(error),
                ),
            ),
        )
    symbols = _module_symbols(source, allow_implicit_graph_projection=True)
    collector = _Collector(
        relative_path,
        baseline_revision,
        _manifest_fields(),
        symbols=symbols,
        source=source,
    )
    MetadataWrapper(module).visit(collector)
    return collector.result()


def source_digest(source: str) -> str:
    """Return a token digest that ignores only layout-only blank lines."""
    try:
        tokens = tuple(
            (token.type, token.string)
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if not (token.type == tokenize.NL and not token.string.strip())
        )
    except tokenize.TokenError:
        tokens = ((tokenize.ERRORTOKEN, source),)
    return hashlib.sha256(repr(tokens).encode()).hexdigest()


def inventory_sources(
    sources: Iterable[InventorySource],
    manifest: ProjectionMigrationManifest,
    *,
    allow_implicit_graph_projection: bool = False,
    require_declaration_facts: bool = False,
) -> AccessInventory:
    """Collect a sorted inventory from supplied source snapshots without filesystem access."""
    inventories: list[SourceInventory] = []
    snapshots = tuple(sorted(sources, key=lambda item: item.relative_path))
    if len({item.relative_path for item in snapshots}) != len(snapshots):
        raise ValueError("inventory sources must have unique relative paths")
    for snapshot in snapshots:
        source = snapshot.source
        relative_path = snapshot.relative_path
        if not any(
            token in source
            for token in (
                "GraphProjection",
                "GraphController",
                "GraphEventStore",
                "GraphDispatchContext",
                "initial_projection",
                "build_projection",
                "reduce_event",
            )
        ):
            inventories.append(
                SourceInventory(
                    relative_path=relative_path,
                    baseline_revision=manifest.baseline_revision,
                    occurrences=(),
                    diagnostics=(),
                )
            )
            continue
        try:
            module = cst.parse_module(source)
        except cst.ParserSyntaxError:
            inventories.append(
                collect_source(
                    source,
                    relative_path=relative_path,
                    baseline_revision=manifest.baseline_revision,
                )
            )
            continue
        symbols = _module_symbols(
            source,
            allow_implicit_graph_projection=allow_implicit_graph_projection,
            module_name=_module_name(relative_path),
            require_declaration_facts=require_declaration_facts,
        )
        collector = _Collector(
            relative_path,
            manifest.baseline_revision,
            {field.old_name: field for field in manifest.fields},
            symbols,
            source,
        )
        MetadataWrapper(module).visit(collector)
        inventories.append(collector.result())
    return AccessInventory(
        baseline_revision=manifest.baseline_revision,
        occurrences=tuple(
            sorted(
                (item for inventory in inventories for item in inventory.occurrences),
                key=lambda item: (
                    item.relative_path,
                    item.qualified_function,
                    item.line,
                    item.column,
                    item.kind,
                ),
            )
        ),
        diagnostics=tuple(
            sorted(
                (item for inventory in inventories for item in inventory.diagnostics),
                key=lambda item: (item.relative_path, item.line, item.column, item.code),
            )
        ),
        source_digests=tuple(
            SourceDigest(relative_path=item.relative_path, digest=source_digest(item.source))
            for item in snapshots
        ),
    )


def inventory_paths(
    paths: Iterable[Path],
    manifest: ProjectionMigrationManifest,
    *,
    root: Path | None = None,
    allow_implicit_graph_projection: bool = False,
    require_declaration_facts: bool = False,
) -> AccessInventory:
    """Collect a sorted aggregate from explicitly selected Python paths."""
    python_paths = tuple(sorted({path for path in paths if path.suffix == ".py"}, key=str))
    if root is None:
        root = (
            Path(os.path.commonpath(tuple(str(path.parent) for path in python_paths)))
            if python_paths
            else Path.cwd()
        )
    return inventory_sources(
        (
            InventorySource(
                relative_path=path.relative_to(root).as_posix(), source=path.read_text()
            )
            for path in python_paths
        ),
        manifest,
        allow_implicit_graph_projection=allow_implicit_graph_projection,
        require_declaration_facts=require_declaration_facts,
    )


def inventory_repository(
    root: Path,
    manifest: ProjectionMigrationManifest,
    *,
    tracked_paths: Iterable[Path] | None = None,
) -> AccessInventory:
    """Collect only injected or git-tracked Python source paths."""
    excluded = {"worktrees", "vendor", ".venv", "venv", "__pycache__"}
    if tracked_paths is None:
        tracked_paths = tuple(
            root / path
            for path in subprocess.run(
                ("git", "-C", str(root), "ls-files", "--", "*.py"),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
    paths = (
        path
        for path in tracked_paths
        if path.suffix == ".py"
        and path.is_relative_to(root)
        and path.relative_to(root).parts[:1] in {("src",), ("tests",), ("scripts",)}
        and not any(part in excluded for part in path.relative_to(root).parts)
    )
    return inventory_paths(
        paths,
        manifest,
        root=root,
        allow_implicit_graph_projection=False,
        require_declaration_facts=True,
    )


def diagnostic_report(inventory: AccessInventory) -> str:
    """Render the deterministic checked remediation report used by ``--diagnose``."""
    counts = {
        code: sum(diagnostic.code == code for diagnostic in inventory.diagnostics)
        for code in sorted({diagnostic.code for diagnostic in inventory.diagnostics})
    }
    summary = [f"Unresolved GraphProjection flows: {len(inventory.diagnostics)}"]
    summary.extend(f"{code}: {count}" for code, count in counts.items())
    sites = [
        (
            f"{diagnostic.relative_path}:{diagnostic.line}:{diagnostic.column}: "
            f"{diagnostic.qualified_function}: {diagnostic.code}: {diagnostic.message}; "
            f"{diagnostic.remediation}"
        )
        for diagnostic in sorted(
            inventory.diagnostics,
            key=lambda item: (item.relative_path, item.line, item.column, item.code),
        )
    ]
    return "\n".join((*summary, "", *sites, ""))


def diagnostic_artifact(inventory: AccessInventory) -> str:
    """Render the full checked-in repository diagnostic artifact."""
    return (
        "# GraphProjection Inventory Diagnostic Fixture\n\n"
        "> **Authoritative:** This generated fixture is the complete, sorted record of "
        "unresolved tracked GraphProjection flows for the manifest baseline.\n\n"
        "Generated from the tracked repository with the diagnostic command.\n"
        "The command intentionally exits nonzero while unresolved flows remain.\n\n"
        "## Complete sorted diagnostics\n\n"
        "```text\n"
        f"{diagnostic_report(inventory)}```\n"
    )


def main() -> int:
    """Print diagnostics or mechanically write the reviewed migration skeleton."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--write-query-migration-skeleton", action="store_true")
    args = parser.parse_args()
    if args.diagnose == args.write_query_migration_skeleton:
        parser.error("choose exactly one inventory action")
    root = Path(__file__).parents[1]
    manifest = load_manifest(root / "scripts/codemods/graph_projection_manifest.yaml")
    inventory = inventory_repository(root, manifest)
    if args.write_query_migration_skeleton:
        target = root / "scripts/codemods/graph_projection_query_migration.yaml"
        reviewed = load_query_migration_manifest(target)
        ledger = classify_node_task_edge_binding_and_lease_domains(
            classify_lifecycle_domain(query_migration_skeleton(inventory, root)),
            reviewed.dispositions,
        )
        target.write_text(yaml.safe_dump(ledger.model_dump(mode="json"), sort_keys=False))
        return 0
    print(diagnostic_artifact(inventory), end="")
    return 1 if inventory.diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
