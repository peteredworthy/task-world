"""Compile, report, and apply authoritative GraphProjection query migrations."""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import textwrap
from typing import Literal

import libcst as cst
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import (
    MetadataWrapper,
    ParentNodeProvider,
    PositionProvider,
    QualifiedName,
    QualifiedNameProvider,
)
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from scripts.graph_projection_inventory import (
    AccessInventory,
    AccessKind,
    CurrentClosureIdentity,
    CurrentClosureSite,
    DiagnosticCode,
    InventorySource,
    ProjectionCallContext,
    ProjectionMigrationManifest,
    QueryMigrationManifest,
    disposition_site_key,
    current_closure_identity,
    inventory_sources,
    load_manifest,
    occurrence_id,
    query_migration_skeleton,
    source_digest,
)


SourceSnapshot = InventorySource
SiteOrigin = Literal["occurrence", "diagnostic"]
_PUBLIC_GRAPH_IMPORTS = {
    ("orchestrator.graph.clock", "FakeClock"): "FakeClock",
    ("orchestrator.graph.clock", "SequentialIdGenerator"): "SequentialIdGenerator",
    (
        "orchestrator.graph.command_bindings",
        "resolve_check_command_definition",
    ): "resolve_check_command_definition",
    ("orchestrator.graph.command_models", "AcknowledgeStartCommand"): "AcknowledgeStartCommand",
    ("orchestrator.graph.command_models", "AgentDiedCommand"): "AgentDiedCommand",
    ("orchestrator.graph.command_models", "CompleteCommand"): "CompleteCommand",
    ("orchestrator.graph.command_models", "EvaluateJoinCommand"): "EvaluateJoinCommand",
    (
        "orchestrator.graph.command_models",
        "GatekeeperVerdictCommandRow",
    ): "GatekeeperVerdictCommandRow",
    ("orchestrator.graph.command_models", "GraphCommandContext"): "GraphCommandContext",
    ("orchestrator.graph.command_models", "PatchCommandContext"): "PatchCommandContext",
    ("orchestrator.graph.command_models", "RaiseAppealCommand"): "RaiseAppealCommand",
    ("orchestrator.graph.command_models", "ReconcileCommand"): "ReconcileCommand",
    ("orchestrator.graph.command_models", "RecordDecisionCommand"): "RecordDecisionCommand",
    ("orchestrator.graph.command_models", "RecordHeartbeatCommand"): "RecordHeartbeatCommand",
    (
        "orchestrator.graph.command_models",
        "RecordRequirementRevisionCommand",
    ): "RecordRequirementRevisionCommand",
    (
        "orchestrator.graph.command_models",
        "RecordSupportEvidenceCommand",
    ): "RecordSupportEvidenceCommand",
    ("orchestrator.graph.command_models", "ScheduleTickCommand"): "ScheduleTickCommand",
    (
        "orchestrator.graph.command_models",
        "SeedCompiledEventsCommand",
    ): "SeedCompiledEventsCommand",
    ("orchestrator.graph.command_models", "SubmitCallbackCommand"): "SubmitCallbackCommand",
    ("orchestrator.graph.command_models", "SubmitPatchCommand"): "SubmitPatchCommand",
    ("orchestrator.graph.commands", "COMMAND_SPECS"): "COMMAND_SPECS",
    ("orchestrator.graph.commands", "IdGenerator"): "IdGenerator",
    ("orchestrator.graph.commands", "apply_command"): "apply_command",
    ("orchestrator.graph.commands", "event_factory"): "event_factory",
    ("orchestrator.graph.commands", "serialize_event_payload"): "serialize_event_payload",
    ("orchestrator.graph.models", "Actor"): "Actor",
    ("orchestrator.graph.models", "ActorKind"): "ActorKind",
    ("orchestrator.graph.models", "AnalysisSummaryRecord"): "AnalysisSummaryRecord",
    ("orchestrator.graph.models", "AnalysisSummaryValue"): "AnalysisSummaryValue",
    ("orchestrator.graph.models", "ArtifactReferenceRecord"): "ArtifactReferenceRecord",
    ("orchestrator.graph.models", "ArtifactReferenceValue"): "ArtifactReferenceValue",
    ("orchestrator.graph.models", "Authority"): "Authority",
    ("orchestrator.graph.models", "AuthorityDecisionRecord"): "AuthorityDecisionRecord",
    ("orchestrator.graph.models", "AuthorityRequestRecord"): "AuthorityRequestRecord",
    ("orchestrator.graph.models", "CallbackEnvelope"): "CallbackEnvelope",
    ("orchestrator.graph.models", "CandidateProjection"): "CandidateProjection",
    ("orchestrator.graph.models", "CandidateRecord"): "CandidateRecord",
    ("orchestrator.graph.models", "CheckResultRecord"): "CheckResultRecord",
    ("orchestrator.graph.models", "CheckResultValue"): "CheckResultValue",
    ("orchestrator.graph.models", "CompletionDecisionRecord"): "CompletionDecisionRecord",
    ("orchestrator.graph.models", "DecisionRecord"): "DecisionRecord",
    ("orchestrator.graph.models", "DecisionRequestRecord"): "DecisionRequestRecord",
    ("orchestrator.graph.models", "EdgeModel"): "EdgeModel",
    ("orchestrator.graph.models", "EdgeProjection"): "EdgeProjection",
    ("orchestrator.graph.models", "EventEnvelope"): "EventEnvelope",
    ("orchestrator.graph.models", "FailureRecord"): "FailureRecord",
    ("orchestrator.graph.models", "FailureRecordValue"): "FailureRecordValue",
    ("orchestrator.graph.models", "FileEntry"): "FileEntry",
    ("orchestrator.graph.models", "FileStateRecord"): "FileStateRecord",
    ("orchestrator.graph.models", "GapClassificationRecord"): "GapClassificationRecord",
    ("orchestrator.graph.models", "GapClassificationValue"): "GapClassificationValue",
    ("orchestrator.graph.models", "GraphPatchProposalRecord"): "GraphPatchProposalRecord",
    ("orchestrator.graph.models", "GraphPatchResultRecord"): "GraphPatchResultRecord",
    ("orchestrator.graph.models", "GraphRecord"): "GraphRecord",
    ("orchestrator.graph.models", "GraphRecordKind"): "GraphRecordKind",
    ("orchestrator.graph.models", "InputBinding"): "InputBinding",
    ("orchestrator.graph.models", "JoinResultRecord"): "JoinResultRecord",
    ("orchestrator.graph.models", "LeaseModel"): "LeaseModel",
    ("orchestrator.graph.models", "LeaseState"): "LeaseState",
    ("orchestrator.graph.models", "NodeKind"): "NodeKind",
    ("orchestrator.graph.models", "NodeMembership"): "NodeMembership",
    ("orchestrator.graph.models", "NodeModel"): "NodeModel",
    ("orchestrator.graph.models", "NodeState"): "NodeState",
    ("orchestrator.graph.models", "OutputRecord"): "OutputRecord",
    ("orchestrator.graph.models", "PatchEnvelope"): "PatchEnvelope",
    ("orchestrator.graph.models", "PatchOp"): "PatchOp",
    ("orchestrator.graph.models", "PlannerChainRegionPayload"): "PlannerChainRegionPayload",
    ("orchestrator.graph.models", "PortModel"): "PortModel",
    ("orchestrator.graph.models", "RecordSelector"): "RecordSelector",
    ("orchestrator.graph.models", "RecoveryPlanRecord"): "RecoveryPlanRecord",
    ("orchestrator.graph.models", "RecoveryPlanValue"): "RecoveryPlanValue",
    ("orchestrator.graph.models", "RequirementRecord"): "RequirementRecord",
    ("orchestrator.graph.models", "RequirementRecordValue"): "RequirementRecordValue",
    ("orchestrator.graph.models", "ResourceClaim"): "ResourceClaim",
    ("orchestrator.graph.models", "RoutineSnapshotRecord"): "RoutineSnapshotRecord",
    ("orchestrator.graph.models", "RoutineSnapshotValue"): "RoutineSnapshotValue",
    ("orchestrator.graph.models", "RunContextRecord"): "RunContextRecord",
    ("orchestrator.graph.models", "RunContextValue"): "RunContextValue",
    ("orchestrator.graph.models", "RunLifecycleState"): "RunLifecycleState",
    ("orchestrator.graph.models", "RunModel"): "RunModel",
    ("orchestrator.graph.models", "VerificationReportRecord"): "VerificationReportRecord",
    ("orchestrator.graph.models", "VerificationReportValue"): "VerificationReportValue",
    ("orchestrator.graph.models", "VerifierVerdictProjection"): "VerifierVerdictProjection",
    ("orchestrator.graph.patch_validator", "PatchValidationResult"): "PatchValidationResult",
    ("orchestrator.graph.patch_validator", "_resource_claim_dicts"): "resource_claim_dicts",
    ("orchestrator.graph.patch_validator", "validate_patch"): "validate_patch",
    ("orchestrator.graph.projection_queries", "node_kind"): "node_kind",
    ("orchestrator.graph.projection_queries", "node_states_view"): "node_states_view",
    ("orchestrator.graph.projection_queries", "run_state"): "run_state",
    ("orchestrator.graph.projections", "GraphProjection"): "GraphProjection",
    ("orchestrator.graph.projections", "build_projection"): "build_projection",
    ("orchestrator.graph.projections", "initial_projection"): "initial_projection",
    ("orchestrator.graph.projections", "projection_to_checkpoint"): "projection_to_checkpoint",
    ("orchestrator.graph.scenario", "run_scenario"): "run_scenario",
    ("orchestrator.graph.scheduler", "NodeScheduleInfo"): "NodeScheduleInfo",
    ("orchestrator.graph.scheduler", "ResourceClaim"): "SchedulerResourceClaim",
    ("orchestrator.graph.store", "DuplicateEventError"): "DuplicateEventError",
    ("orchestrator.graph.store", "InMemoryEventStore"): "InMemoryEventStore",
}


class AnchorRefusedError(ValueError):
    """Raised when migration evidence cannot be proved safe and exact."""


def _cst_dotted_name(node: cst.CSTNode | None) -> str | None:
    if node is None:
        return None
    rendered = cst.Module([]).code_for_node(node).strip()
    return rendered if rendered else None


class _PublicGraphImportTransformer(cst.CSTTransformer):
    """Rewrite the finite external graph-submodule import boundary."""

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom:
        module = _cst_dotted_name(original_node.module)
        if module is None or not module.startswith("orchestrator.graph."):
            return updated_node
        names = updated_node.names
        if isinstance(names, cst.ImportStar):
            raise AnchorRefusedError(f"unsupported graph submodule import: {module}")
        imported = tuple(_cst_dotted_name(alias.name) or "" for alias in names)
        unsupported = sorted(
            source_symbol
            for source_symbol in set(imported)
            if (module, source_symbol) not in _PUBLIC_GRAPH_IMPORTS
        )
        if unsupported:
            raise AnchorRefusedError(
                f"unsupported graph submodule import: {module} {unsupported!r}"
            )
        return updated_node.with_changes(
            module=cst.parse_expression("orchestrator.graph"),
            names=tuple(
                alias.with_changes(
                    name=cst.parse_expression(renamed),
                    asname=(
                        alias.asname
                        if alias.asname is not None
                        else cst.AsName(name=cst.Name(_cst_dotted_name(alias.name) or ""))
                    ),
                )
                if (renamed := _PUBLIC_GRAPH_IMPORTS[(module, _cst_dotted_name(alias.name) or "")])
                != (_cst_dotted_name(alias.name) or "")
                else alias
                for alias in names
            ),
        )

    def leave_Import(self, original_node: cst.Import, updated_node: cst.Import) -> cst.Import:
        modules = [
            module
            for alias in original_node.names
            if (module := _cst_dotted_name(alias.name)) is not None
            and module.startswith("orchestrator.graph.")
        ]
        if modules:
            raise AnchorRefusedError(f"unsupported graph submodule import: {modules!r}")
        return updated_node


def rewrite_graph_submodule_imports(source: str) -> str:
    """Mechanically route external graph-submodule imports through the public API."""
    return cst.parse_module(source).visit(_PublicGraphImportTransformer()).code


class SourceLocator(BaseModel):
    """The CST position selected for a mechanically anchored operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    line: int
    column: int


class CstAnchorEvidence(BaseModel):
    """Recomputed proof used to select one source occurrence without source policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    node_type: str
    normalized_expression: str
    same_expression_ordinal: int
    context: ProjectionCallContext | None = None


class MigrationSite(BaseModel):
    """One source-anchored migration operation derived from inventory identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    origin: SiteOrigin
    original_site_id: str
    relative_path: str
    qualified_function: str
    access_kind: AccessKind | None
    old_field_name: str | None
    diagnostic_code: DiagnosticCode | None
    normalized_expression: str
    report_context: str | None = None
    domain: str
    ordinal: int
    source_digest: str
    locator: SourceLocator
    anchor: CstAnchorEvidence
    parent_shape: str
    operation_shape: str

    @property
    def shape_key(self) -> str:
        return "|".join(
            (
                self.access_kind.value if self.access_kind is not None else "-",
                self.old_field_name or "-",
                self.diagnostic_code.value if self.diagnostic_code is not None else "-",
                self.parent_shape,
                self.operation_shape,
            )
        )


class OperationStream(BaseModel):
    """Deterministic, source-free operation stream grouped only by structural shape."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sites: tuple[MigrationSite, ...]


def require_complete_receiver_physical_context(site: MigrationSite) -> None:
    """Refuse a query transform without collector-proven physical receiver facts."""
    context = site.anchor.context
    if (
        context is None
        or not context.projection_expression.strip()
        or context.projection_role != "receiver"
        or context.physical_old_field_name is None
        or context.physical_access_kind is None
        or context.physical_operation_shape is None
    ):
        raise AnchorRefusedError(
            "reviewed query transform lacks complete receiver physical context: "
            f"{site.original_site_id}"
        )


class PlannedOperation(BaseModel):
    """One reviewed ledger disposition joined to anchored operation IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    disposition: Literal["query_transform", "approved_core", "projection_neutral"]
    reason: str
    consumed_site_ids: tuple[str, ...]
    shape_key: str

    @property
    def consumed_site_id_set(self) -> frozenset[str]:
        return frozenset(self.consumed_site_ids)

    @classmethod
    def _validate_consumed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("consumed_site_ids must be nonempty")
        if len(value) != len(frozenset(value)):
            raise ValueError("consumed_site_ids must not repeat a site")
        return value

    @field_validator("reason")
    @classmethod
    def _reason_is_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must be nonempty")
        return value

    _consumed_is_nonempty = field_validator("consumed_site_ids")(_validate_consumed)


class StructuralRuleOperation(BaseModel):
    """One finite rule application with the exact source evidence it consumed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    site_id: str
    rule_id: str
    origin: str
    shape_key: str


class StructuralQueryRuleOperation(BaseModel):
    """One generated query transform selected only from complete physical read facts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    site_id: str
    rule_id: str
    shape_key: str
    effective_old_field: str
    access_kind: str
    operation_shape: str
    evidence: tuple[tuple[str, str], ...]


class GeneratedFixtureOperation(BaseModel):
    """One deferred physical fixture operation generated by a finite rule."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    site_id: str
    rule_id: str
    shape_key: str
    evidence: tuple[tuple[str, str], ...]


class DispositionPlan(BaseModel):
    """Frozen exact-once compilation result for reviewed migration dispositions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operations: tuple[PlannedOperation, ...]
    reviewed_deferred_site_ids: tuple[str, ...]
    generated_fixture_operations: tuple[GeneratedFixtureOperation, ...]
    pending_site_ids: tuple[str, ...]
    disposition_counts: tuple[tuple[str, int], ...]
    shape_group_counts: tuple[tuple[str, int], ...]
    neutral_rule_operations: tuple[StructuralRuleOperation, ...] = ()
    rule_family_counts: tuple[tuple[str, int], ...]
    symbol_origin_counts: tuple[tuple[str, int], ...]
    generated_fixture_family_counts: tuple[tuple[str, int], ...]
    generated_query_operations: tuple[StructuralQueryRuleOperation, ...] = ()
    generated_query_family_counts: tuple[tuple[str, int], ...] = ()

    @property
    def consumed_site_ids(self) -> frozenset[str]:
        return frozenset(
            site_id for operation in self.operations for site_id in operation.consumed_site_ids
        )

    @property
    def generated_fixture_site_ids(self) -> frozenset[str]:
        return frozenset(item.site_id for item in self.generated_fixture_operations)

    @property
    def fixture_site_ids(self) -> frozenset[str]:
        return frozenset(self.reviewed_deferred_site_ids) | self.generated_fixture_site_ids

    @property
    def deferred_site_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.fixture_site_ids))

    @model_validator(mode="after")
    def _validate_total_partition(self) -> "DispositionPlan":
        consumed = [
            site_id for operation in self.operations for site_id in operation.consumed_site_ids
        ]
        if len(consumed) != len(frozenset(consumed)):
            raise ValueError("planned operation consumed-site sets overlap")
        deferred = set(self.reviewed_deferred_site_ids)
        generated_fixture_ids = [item.site_id for item in self.generated_fixture_operations]
        pending = set(self.pending_site_ids)
        if (
            len(deferred) != len(self.reviewed_deferred_site_ids)
            or len(generated_fixture_ids) != len(frozenset(generated_fixture_ids))
            or len(pending) != len(self.pending_site_ids)
        ):
            raise ValueError("deferred and pending site IDs must be unique")
        generated = set(generated_fixture_ids)
        if (
            deferred & generated
            or deferred & pending
            or generated & pending
            or self.fixture_site_ids & set(consumed)
            or pending & set(consumed)
        ):
            raise ValueError("plan partitions overlap")
        if bool(self.operations) != bool(self.disposition_counts) or bool(self.operations) != bool(
            self.shape_group_counts
        ):
            raise ValueError("derived plan counts must match operation emptiness")
        if self.disposition_counts != tuple(
            sorted(Counter(item.disposition for item in self.operations).items())
        ):
            raise ValueError("disposition counts do not match operations")
        if self.shape_group_counts != tuple(
            sorted(Counter(item.shape_key for item in self.operations).items())
        ):
            raise ValueError("shape counts do not match operations")
        rule_ids = [item.site_id for item in self.neutral_rule_operations]
        neutral_ids = {
            item.consumed_site_ids[0]
            for item in self.operations
            if item.disposition == "projection_neutral"
        }
        if len(rule_ids) != len(frozenset(rule_ids)) or (
            (not self.pending_site_ids or self.neutral_rule_operations)
            and set(rule_ids) != neutral_ids
        ):
            raise ValueError("neutral rule operations do not match neutral operations")
        if self.rule_family_counts != tuple(
            sorted(Counter(item.rule_id for item in self.neutral_rule_operations).items())
        ):
            raise ValueError("rule family counts do not match rule operations")
        if self.symbol_origin_counts != tuple(
            sorted(Counter(item.origin for item in self.neutral_rule_operations).items())
        ):
            raise ValueError("symbol origin counts do not match rule operations")
        if self.generated_fixture_family_counts != tuple(
            sorted(Counter(item.rule_id for item in self.generated_fixture_operations).items())
        ):
            raise ValueError("generated fixture family counts do not match fixture operations")
        generated_query_ids = [item.site_id for item in self.generated_query_operations]
        query_ids = {
            item.consumed_site_ids[0]
            for item in self.operations
            if item.disposition == "query_transform"
            and item.reason.startswith("structural:physical_query_read:")
        }
        if (
            len(generated_query_ids) != len(frozenset(generated_query_ids))
            or set(generated_query_ids) != query_ids
        ):
            raise ValueError("generated query operations do not match structural transforms")
        if self.generated_query_family_counts != tuple(
            sorted(Counter(item.rule_id for item in self.generated_query_operations).items())
        ):
            raise ValueError("generated query family counts do not match query operations")
        if any(
            count < 0
            for _, count in (
                *self.rule_family_counts,
                *self.symbol_origin_counts,
                *self.generated_fixture_family_counts,
            )
        ):
            raise ValueError("derived counts must be nonnegative")
        return self


class QueryCompositionGroup(BaseModel):
    """One immutable outer-CST action that consumes reviewed transform anchors."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    source_span: tuple[int, int, int, int]
    outer_action_id: str
    owner_site_id: str | None
    owner_anchor: CstAnchorEvidence
    original_outer_expression: str
    consumed_site_ids: tuple[str, ...]
    anchor_relations: tuple[tuple[str, str], ...]

    @model_validator(mode="after")
    def _validate_group(self) -> "QueryCompositionGroup":
        if not self.relative_path.strip() or not self.original_outer_expression.strip():
            raise ValueError("composition paths and expressions must be nonblank")
        start = self.source_span[:2]
        end = self.source_span[2:]
        if start[0] < 1 or end[0] < 1 or start[1] < 0 or end[1] < 0 or start >= end:
            raise ValueError("composition source span must be positive and ordered")
        if not self.outer_action_id.strip():
            raise ValueError("composition outer action owner must be nonblank")
        expected_owner = (
            f"outer:{self.relative_path}:{':'.join(str(value) for value in self.source_span)}"
        )
        if self.outer_action_id != expected_owner:
            raise ValueError("composition outer action owner must match its path and span")
        try:
            outer = cst.parse_expression(self.original_outer_expression)
        except cst.ParserSyntaxError as error:
            raise ValueError("composition outer expression must parse") from error
        if (
            type(outer).__name__ != self.owner_anchor.node_type
            or _normalized_node(outer) != self.owner_anchor.normalized_expression
            or self.owner_anchor.same_expression_ordinal != 0
        ):
            raise ValueError("composition outer anchor must match its expression")
        if (
            not self.consumed_site_ids
            or tuple(sorted(self.consumed_site_ids)) != self.consumed_site_ids
            or len(self.consumed_site_ids) != len(frozenset(self.consumed_site_ids))
            or any(not site_id.strip() for site_id in self.consumed_site_ids)
        ):
            raise ValueError(
                "composition group consumed site IDs must be canonical, nonempty and unique"
            )
        if self.owner_site_id is not None and self.owner_site_id not in self.consumed_site_ids:
            raise ValueError("composition site owner must be consumed")
        if (
            tuple(sorted(self.anchor_relations)) != self.anchor_relations
            or len(self.anchor_relations) != len(frozenset(self.anchor_relations))
            or any(
                ancestor == descendant
                or ancestor not in self.consumed_site_ids
                or descendant not in self.consumed_site_ids
                for ancestor, descendant in self.anchor_relations
            )
        ):
            raise ValueError(
                "composition anchor relations must be canonical, unique consumed ancestry pairs"
            )
        if self.owner_site_id is not None:
            # Additional actual nested relations are valid, but the outer site
            # itself must prove ownership of every other consumed anchor.
            missing = {
                (self.owner_site_id, site_id)
                for site_id in self.consumed_site_ids
                if site_id != self.owner_site_id
            } - set(self.anchor_relations)
            if missing:
                raise ValueError("a site owner must relate to every descendant anchor")
        children: dict[str, set[str]] = defaultdict(set)
        for ancestor, descendant in self.anchor_relations:
            children[ancestor].add(descendant)
        for start in self.consumed_site_ids:
            pending = list(children[start])
            seen: set[str] = set()
            while pending:
                descendant = pending.pop()
                if descendant == start:
                    raise ValueError("composition anchor relations must be acyclic")
                if descendant not in seen:
                    seen.add(descendant)
                    pending.extend(children[descendant])
        return self


class QueryCompositionPlan(BaseModel):
    """Frozen, exact-once source ownership partition for reviewed query transforms."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    groups: tuple[QueryCompositionGroup, ...]

    @property
    def consumed_site_ids(self) -> frozenset[str]:
        return frozenset(site_id for group in self.groups for site_id in group.consumed_site_ids)

    @model_validator(mode="after")
    def _validate_plan(self) -> "QueryCompositionPlan":
        consumed = [site_id for group in self.groups for site_id in group.consumed_site_ids]
        if len(consumed) != len(frozenset(consumed)):
            raise ValueError("composition groups overlap by consumed site ID")
        for index, group in enumerate(self.groups):
            for other in self.groups[index + 1 :]:
                if group.relative_path == other.relative_path and _spans_overlap(
                    group.source_span, other.source_span
                ):
                    raise ValueError("composition groups overlap by source action span")
        if self.groups != tuple(
            sorted(
                self.groups,
                key=lambda group: (group.relative_path, group.source_span, group.outer_action_id),
            )
        ):
            raise ValueError("composition groups must be canonically ordered")
        return self


class QueryReplacementRecipe(BaseModel):
    """One exact outer expression with only proven physical reads substituted."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    source_span: tuple[int, int, int, int]
    original_outer_expression: str
    replacement_outer_expression: str
    consumed_site_ids: tuple[str, ...]
    query_imports: tuple[str, ...]
    rule_ids: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_recipe(self) -> "QueryReplacementRecipe":
        if (
            not self.relative_path.strip()
            or not self.original_outer_expression.strip()
            or not self.replacement_outer_expression.strip()
        ):
            raise ValueError("query replacement recipe text must be nonblank")
        if self.source_span[:2] >= self.source_span[2:]:
            raise ValueError("query replacement source span must be ordered")
        if (
            not self.consumed_site_ids
            or tuple(sorted(self.consumed_site_ids)) != self.consumed_site_ids
            or len(self.consumed_site_ids) != len(frozenset(self.consumed_site_ids))
        ):
            raise ValueError("query replacement consumed IDs must be canonical and unique")
        if tuple(sorted(frozenset(self.query_imports))) != self.query_imports:
            raise ValueError("query replacement imports must be canonical and unique")
        if not self.rule_ids or tuple(sorted(self.rule_ids)) != self.rule_ids:
            raise ValueError("query replacement rule IDs must be canonical and nonempty")
        try:
            cst.parse_expression(self.original_outer_expression)
            cst.parse_expression(self.replacement_outer_expression)
        except cst.ParserSyntaxError as error:
            raise ValueError("query replacement expressions must parse") from error
        return self


class QueryMutationHandoff(BaseModel):
    """One physical mutation delegated unchanged to fixture migration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    source_span: tuple[int, int, int, int]
    original_outer_expression: str
    consumed_site_ids: tuple[str, ...]
    effective_old_field: str
    access_kind: str
    operation_shape: str
    rule_id: str

    @model_validator(mode="after")
    def _validate_handoff(self) -> "QueryMutationHandoff":
        if any(
            not value.strip()
            for value in (
                self.relative_path,
                self.original_outer_expression,
                self.effective_old_field,
                self.access_kind,
                self.operation_shape,
                self.rule_id,
            )
        ):
            raise ValueError("query mutation handoff fields must be nonblank")
        if (
            self.source_span[:2] >= self.source_span[2:]
            or not self.consumed_site_ids
            or tuple(sorted(self.consumed_site_ids)) != self.consumed_site_ids
            or len(self.consumed_site_ids) != len(frozenset(self.consumed_site_ids))
        ):
            raise ValueError("query mutation handoff span and IDs must be canonical")
        try:
            cst.parse_expression(self.original_outer_expression)
        except cst.ParserSyntaxError as error:
            raise ValueError("query mutation handoff expression must parse") from error
        return self


class QueryReplacementPlan(BaseModel):
    """Frozen exact closure of read recipes and fixture mutation handoffs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    recipes: tuple[QueryReplacementRecipe, ...]
    mutation_handoffs: tuple[QueryMutationHandoff, ...]
    unmatched_family_counts: tuple[tuple[str, int], ...]
    rule_family_counts: tuple[tuple[str, int], ...]
    query_import_counts: tuple[tuple[str, int], ...]

    @property
    def consumed_site_ids(self) -> frozenset[str]:
        return frozenset(
            site_id
            for item in (*self.recipes, *self.mutation_handoffs)
            for site_id in item.consumed_site_ids
        )

    @model_validator(mode="after")
    def _validate_plan(self) -> "QueryReplacementPlan":
        items = (*self.recipes, *self.mutation_handoffs)
        consumed = [site_id for item in items for site_id in item.consumed_site_ids]
        if len(consumed) != len(frozenset(consumed)):
            raise ValueError("query replacement consumed-site sets overlap")
        if self.unmatched_family_counts:
            raise ValueError("query replacement plan contains unmatched structural families")
        for index, item in enumerate(items):
            if any(
                item.relative_path == other.relative_path
                and _spans_overlap(item.source_span, other.source_span)
                for other in items[index + 1 :]
            ):
                raise ValueError("query replacement actions overlap by source span")
        if self.recipes != tuple(
            sorted(
                self.recipes,
                key=lambda item: (item.relative_path, item.source_span, item.consumed_site_ids),
            )
        ) or self.mutation_handoffs != tuple(
            sorted(
                self.mutation_handoffs,
                key=lambda item: (item.relative_path, item.source_span, item.consumed_site_ids),
            )
        ):
            raise ValueError("query replacement actions must be canonically ordered")
        if self.rule_family_counts != tuple(
            sorted(Counter(rule for item in self.recipes for rule in item.rule_ids).items())
        ):
            raise ValueError("query replacement rule-family counts do not match recipes")
        if self.query_import_counts != tuple(
            sorted(Counter(name for item in self.recipes for name in item.query_imports).items())
        ):
            raise ValueError("query replacement import counts do not match recipes")
        return self


class QuerySourceUpdate(BaseModel):
    """One fully validated source update produced without filesystem writes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    original_source: str
    transformed_source: str
    consumed_site_ids: tuple[str, ...]
    query_imports: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_update(self) -> "QuerySourceUpdate":
        if not self.relative_path.strip() or not self.consumed_site_ids:
            raise ValueError("query source update path and consumed IDs must be nonempty")
        if (
            tuple(sorted(self.consumed_site_ids)) != self.consumed_site_ids
            or len(self.consumed_site_ids) != len(frozenset(self.consumed_site_ids))
            or tuple(sorted(frozenset(self.query_imports))) != self.query_imports
        ):
            raise ValueError("query source update IDs and imports must be canonical")
        for source in (self.original_source, self.transformed_source):
            try:
                cst.parse_module(source)
                ast.parse(source)
            except (cst.ParserSyntaxError, SyntaxError) as error:
                raise ValueError("query source update must contain parseable Python") from error
        return self


class QuerySourceApplyPlan(BaseModel):
    """Canonical in-memory source updates ready for one validated atomic write."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    updates: tuple[QuerySourceUpdate, ...]

    @property
    def consumed_site_ids(self) -> frozenset[str]:
        return frozenset(site_id for update in self.updates for site_id in update.consumed_site_ids)

    @model_validator(mode="after")
    def _validate_apply_plan(self) -> "QuerySourceApplyPlan":
        if self.updates != tuple(sorted(self.updates, key=lambda item: item.relative_path)):
            raise ValueError("query source updates must be canonically ordered")
        paths = [item.relative_path for item in self.updates]
        consumed = [site_id for item in self.updates for site_id in item.consumed_site_ids]
        if len(paths) != len(frozenset(paths)) or len(consumed) != len(frozenset(consumed)):
            raise ValueError("query source update paths and consumed IDs must be unique")
        return self


class FixtureMutationRecipe(BaseModel):
    """One exact fixture mutation statement replaced by immutable rebinding."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    source_span: tuple[int, int, int, int]
    original_statement: str
    replacement_statement: str
    consumed_site_ids: tuple[str, ...]
    helper_import: str
    rule_id: str

    @model_validator(mode="after")
    def _validate_recipe(self) -> "FixtureMutationRecipe":
        if any(
            not value.strip()
            for value in (
                self.relative_path,
                self.original_statement,
                self.replacement_statement,
                self.helper_import,
                self.rule_id,
            )
        ):
            raise ValueError("fixture mutation recipe fields must be nonblank")
        if (
            self.source_span[:2] >= self.source_span[2:]
            or not self.consumed_site_ids
            or tuple(sorted(self.consumed_site_ids)) != self.consumed_site_ids
            or len(self.consumed_site_ids) != len(frozenset(self.consumed_site_ids))
        ):
            raise ValueError("fixture mutation recipe span and IDs must be canonical")
        for statement in (self.original_statement, self.replacement_statement):
            module = cst.parse_module(f"{statement}\n")
            if len(module.body) != 1 or not isinstance(module.body[0], cst.SimpleStatementLine):
                raise ValueError("fixture mutation recipe must contain one simple statement")
        return self


class FixtureMutationPlan(BaseModel):
    """Canonical exact-once fixture mutation recipes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    recipes: tuple[FixtureMutationRecipe, ...]

    @property
    def consumed_site_ids(self) -> frozenset[str]:
        return frozenset(site_id for item in self.recipes for site_id in item.consumed_site_ids)

    @model_validator(mode="after")
    def _validate_plan(self) -> "FixtureMutationPlan":
        if self.recipes != tuple(
            sorted(self.recipes, key=lambda item: (item.relative_path, item.source_span))
        ):
            raise ValueError("fixture mutation recipes must be canonically ordered")
        consumed = [site_id for item in self.recipes for site_id in item.consumed_site_ids]
        spans = [(item.relative_path, item.source_span) for item in self.recipes]
        if len(consumed) != len(frozenset(consumed)) or len(spans) != len(frozenset(spans)):
            raise ValueError("fixture mutation recipes must have unique IDs and spans")
        return self


class FixtureSourceUpdate(BaseModel):
    """One validated fixture source update produced without filesystem writes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    original_source: str
    transformed_source: str
    consumed_site_ids: tuple[str, ...]
    helper_imports: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_update(self) -> "FixtureSourceUpdate":
        if not self.relative_path.strip() or not self.consumed_site_ids:
            raise ValueError("fixture source update path and consumed IDs must be nonempty")
        if (
            tuple(sorted(self.consumed_site_ids)) != self.consumed_site_ids
            or len(self.consumed_site_ids) != len(frozenset(self.consumed_site_ids))
            or tuple(sorted(frozenset(self.helper_imports))) != self.helper_imports
        ):
            raise ValueError("fixture source update IDs and imports must be canonical")
        for source in (self.original_source, self.transformed_source):
            cst.parse_module(source)
            ast.parse(source)
        return self


class FixtureSourceApplyPlan(BaseModel):
    """Canonical fixture updates ready for one validated atomic write."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    updates: tuple[FixtureSourceUpdate, ...]

    @property
    def consumed_site_ids(self) -> frozenset[str]:
        return frozenset(site_id for update in self.updates for site_id in update.consumed_site_ids)

    @model_validator(mode="after")
    def _validate_apply_plan(self) -> "FixtureSourceApplyPlan":
        if self.updates != tuple(sorted(self.updates, key=lambda item: item.relative_path)):
            raise ValueError("fixture source updates must be canonically ordered")
        paths = [item.relative_path for item in self.updates]
        consumed = [site_id for item in self.updates for site_id in item.consumed_site_ids]
        if len(paths) != len(frozenset(paths)) or len(consumed) != len(frozenset(consumed)):
            raise ValueError("fixture source update paths and consumed IDs must be unique")
        return self


class QueryMigrationReportSite(BaseModel):
    """One exact baseline site linked to its structural migration outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    site_id: str
    relative_path: str
    qualified_function: str
    disposition: Literal["transformed", "approved_core", "projection_neutral", "rejected"]
    rule_id: str
    before_normalized_form: str
    replacement: str | None
    after_form: str


class CurrentTreeClosure(BaseModel):
    """Fast current-tree evidence that no generated migration work remains."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    occurrence_count: int
    diagnostic_count: int
    site_count: int
    approved_core_count: int
    projection_neutral_count: int
    identity: CurrentClosureIdentity


class QueryMigrationReport(BaseModel):
    """Deterministic exact linkage from historical sites to migration outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    baseline_revision: str
    baseline_site_count: int
    disposition_counts: tuple[tuple[str, int], ...]
    rule_counts: tuple[tuple[str, int], ...]
    sites: tuple[QueryMigrationReportSite, ...]
    current_closure: CurrentTreeClosure | None = None

    @model_validator(mode="after")
    def _validate_report(self) -> "QueryMigrationReport":
        if self.baseline_site_count != len(self.sites):
            raise ValueError("baseline report count does not match site linkage")
        if tuple(sorted(self.sites, key=lambda item: item.site_id)) != self.sites:
            raise ValueError("baseline report sites must be canonically ordered")
        ids = [item.site_id for item in self.sites]
        if len(ids) != len(frozenset(ids)):
            raise ValueError("baseline report site IDs must be unique")
        if self.disposition_counts != tuple(
            sorted(Counter(item.disposition for item in self.sites).items())
        ):
            raise ValueError("baseline report disposition counts do not match sites")
        if self.rule_counts != tuple(sorted(Counter(item.rule_id for item in self.sites).items())):
            raise ValueError("baseline report rule counts do not match sites")
        return self


def _spans_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    return left[:2] < right[2:] and right[:2] < left[2:]


def _outer_action(node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]) -> cst.CSTNode:
    """Walk all CST bridge nodes to the enclosing statement action boundary."""
    outer = node if isinstance(node, cst.BaseExpression) else None
    current = node
    while (parent := parents.get(current)) is not None:
        if isinstance(parent, cst.BaseStatement):
            if outer is None:
                break
            return outer
        # LibCST bridge nodes (Arg, Element, DictElement, SubscriptElement,
        # Index, ComparisonTarget and comprehension clauses) deliberately do
        # not terminate the walk; their enclosing expression is the action.
        if isinstance(parent, cst.BaseExpression):
            outer = parent
        current = parent
    raise AnchorRefusedError(f"unsupported outer action boundary: {type(current).__name__}")


def _is_ancestor(
    ancestor: cst.CSTNode,
    descendant: cst.CSTNode,
    parents: dict[cst.CSTNode, cst.CSTNode],
) -> bool:
    current = parents.get(descendant)
    while current is not None:
        if current is ancestor:
            return True
        current = parents.get(current)
    return False


def _reanchor_operation_stream_site(
    site: MigrationSite,
    *,
    occurrence_nodes: tuple[cst.CSTNode, ...] | None,
    diagnostic_nodes: tuple[cst.CSTNode, ...] | None,
    parents: dict[cst.CSTNode, cst.CSTNode],
    positions: dict[cst.CSTNode, object],
    qualified_names: dict[cst.CSTNode, object],
) -> cst.CSTNode:
    """Reanchor one stream identity using the same origin-specific proof as collection."""
    if site.origin == "occurrence":
        if site.access_kind is None or occurrence_nodes is None:
            raise AnchorRefusedError(f"occurrence lacks access kind: {site.original_site_id}")
        if site.ordinal >= len(occurrence_nodes):
            raise AnchorRefusedError(f"missing occurrence CST anchor: {site.original_site_id}")
        node = occurrence_nodes[site.ordinal]
    else:
        if diagnostic_nodes is None or site.ordinal >= len(diagnostic_nodes):
            raise AnchorRefusedError(f"missing diagnostic CST anchor: {site.original_site_id}")
        node = diagnostic_nodes[site.ordinal]
        position = positions[node].start
        if (
            position.line != site.locator.line
            or type(node).__name__ != site.anchor.node_type
            or (_normalized_node(node) or cst.Module([]).code_for_node(node).strip())
            != site.anchor.normalized_expression
        ):
            raise AnchorRefusedError(f"diagnostic identity mismatch: {site.original_site_id}")
    if (
        _anchor_evidence(
            node,
            normalized_expression=site.anchor.normalized_expression,
            ordinal=site.anchor.same_expression_ordinal,
            stored_context=site.anchor.context,
            qualified_names=qualified_names,
            parents=parents,
            expected_access_kind=site.access_kind,
        )
        != site.anchor
    ):
        raise AnchorRefusedError(f"query rewrite anchor evidence mismatch: {site.original_site_id}")
    return node


def _reanchor_operation_stream_sites(
    sources: Iterable[SourceSnapshot], sites: Iterable[MigrationSite]
) -> dict[
    str, tuple[cst.CSTNode, dict[cst.CSTNode, cst.CSTNode], dict[cst.CSTNode, object], cst.Module]
]:
    """Prove stream identities against snapshots for every consumer of stream anchors."""
    sites = tuple(sites)
    snapshots = _source_map(sources)
    grouped: dict[str, list[MigrationSite]] = defaultdict(list)
    for site in sites:
        grouped[site.relative_path].append(site)
    anchored: dict[
        str,
        tuple[cst.CSTNode, dict[cst.CSTNode, cst.CSTNode], dict[cst.CSTNode, object], cst.Module],
    ] = {}
    for path, path_sites in grouped.items():
        snapshot = snapshots.get(path)
        if snapshot is None or source_digest(snapshot.source) != path_sites[0].source_digest:
            raise AnchorRefusedError(f"digest mismatch: {path}")
        if any(site.source_digest != path_sites[0].source_digest for site in path_sites):
            raise AnchorRefusedError(f"inconsistent stream source digest: {path}")
        module = cst.parse_module(snapshot.source)
        candidates, parents, positions, qualified, qualified_names = _node_candidates(module)
        scope_lines = _scope_lines(module, positions, qualified)
        for site in path_sites:
            occurrence_nodes: tuple[cst.CSTNode, ...] | None = None
            diagnostic_nodes: tuple[cst.CSTNode, ...] | None = None
            if site.origin == "occurrence":
                peers = [
                    item
                    for item in path_sites
                    if item.origin == "occurrence"
                    and item.qualified_function == site.qualified_function
                    and item.normalized_expression == site.normalized_expression
                ]
                nodes = _matching_occurrence_nodes(
                    candidates=candidates,
                    parents=parents,
                    qualified_function=site.qualified_function,
                    normalized_expression=site.normalized_expression,
                    access_kinds=tuple(
                        item.access_kind for item in peers if item.access_kind is not None
                    ),
                )
                if sorted(item.ordinal for item in peers) != list(range(len(nodes))):
                    raise AnchorRefusedError(
                        f"ambiguous occurrence anchor: {site.original_site_id}"
                    )
                occurrence_nodes = nodes
            else:
                if site.diagnostic_code is None:
                    raise AnchorRefusedError(f"diagnostic lacks code: {site.original_site_id}")
                peers = [
                    item
                    for item in path_sites
                    if item.origin == "diagnostic"
                    and item.qualified_function == site.qualified_function
                    and item.diagnostic_code is site.diagnostic_code
                    and item.normalized_expression == site.normalized_expression
                ]
                diagnostic_nodes = _matching_diagnostic_nodes(
                    source=snapshot.source,
                    module=module,
                    positions=positions,
                    scope_lines=scope_lines,
                    qualified_function=site.qualified_function,
                    code=site.diagnostic_code,
                    normalized_source_pattern=site.normalized_expression,
                    signatures=tuple(
                        (item.anchor.node_type, item.anchor.normalized_expression) for item in peers
                    ),
                )
                if sorted(item.ordinal for item in peers) != list(range(len(diagnostic_nodes))):
                    raise AnchorRefusedError(
                        f"ambiguous diagnostic anchor: {site.original_site_id}"
                    )
            node = _reanchor_operation_stream_site(
                site,
                occurrence_nodes=occurrence_nodes,
                diagnostic_nodes=diagnostic_nodes,
                parents=parents,
                positions=positions,
                qualified_names=qualified_names,
            )
            if site.origin == "diagnostic" and qualified[id(node)] != site.qualified_function:
                raise AnchorRefusedError(f"diagnostic scope mismatch: {site.original_site_id}")
            anchored[site.original_site_id] = (node, parents, positions, module)
    if len(anchored) != len(sites):
        raise AnchorRefusedError("duplicate stream site identity during reanchoring")
    return anchored


def compile_query_composition_plan(
    sources: Iterable[SourceSnapshot], stream: OperationStream, plan: DispositionPlan
) -> QueryCompositionPlan:
    """Reanchor reviewed transforms and partition their recognized outer CST actions."""
    sites = {site.original_site_id: site for site in stream.sites}
    if len(sites) != len(stream.sites):
        raise AnchorRefusedError("duplicate query composition operation-stream site identity")
    ids = tuple(
        sorted(
            site_id
            for operation in plan.operations
            if operation.disposition == "query_transform"
            for site_id in operation.consumed_site_ids
        )
    )
    if len(ids) != len(frozenset(ids)) or any(site_id not in sites for site_id in ids):
        raise AnchorRefusedError("query composition disposition IDs are missing or overlapping")
    # Reanchor the complete stream: occurrence cardinality is an identity proof
    # over all like candidates, not merely the disposition-selected subset.
    anchored = _reanchor_operation_stream_sites(sources, stream.sites)
    actions: list[tuple[str, tuple[int, int, int, int], cst.CSTNode, str]] = []
    for site_id in ids:
        node, parents, positions, _ = anchored[site_id]
        outer = _outer_action(node, parents)
        position = positions[outer]
        actions.append(
            (
                sites[site_id].relative_path,
                (
                    position.start.line,
                    position.start.column,
                    position.end.line,
                    position.end.column,
                ),
                outer,
                site_id,
            )
        )
    components: list[list[tuple[str, tuple[int, int, int, int], cst.CSTNode, str]]] = []
    for action in sorted(actions, key=lambda item: (item[0], item[1], item[3])):
        matching = [
            component
            for component in components
            if any(
                member[0] == action[0] and _spans_overlap(member[1], action[1])
                for member in component
            )
        ]
        if not matching:
            components.append([action])
        else:
            merged = [action, *(member for component in matching for member in component)]
            components = [component for component in components if component not in matching]
            components.append(merged)
    groups: list[QueryCompositionGroup] = []
    for component in components:
        path = component[0][0]
        spans = {item[1] for item in component}
        if len(spans) != 1:
            raise AnchorRefusedError("incomparable overlapping outer actions")
        span = next(iter(spans))
        outer = component[0][2]
        if any(item[2] is not outer for item in component):
            raise AnchorRefusedError("ambiguous outer action identity")
        consumed = tuple(sorted(item[3] for item in component))
        node_by_id = {site_id: anchored[site_id][0] for site_id in consumed}
        owner = next((site_id for site_id in consumed if node_by_id[site_id] is outer), None)
        relations = tuple(
            sorted(
                (ancestor, descendant)
                for ancestor, ancestor_node in node_by_id.items()
                for descendant, descendant_node in node_by_id.items()
                if ancestor != descendant
                and _is_ancestor(ancestor_node, descendant_node, anchored[ancestor][1])
            )
        )
        _, _, _, module = anchored[consumed[0]]
        groups.append(
            QueryCompositionGroup(
                relative_path=path,
                source_span=span,
                outer_action_id=f"outer:{path}:{':'.join(str(value) for value in span)}",
                owner_site_id=owner,
                owner_anchor=CstAnchorEvidence(
                    node_type=type(outer).__name__,
                    normalized_expression=(
                        _normalized_node(outer) or module.code_for_node(outer).strip()
                    ),
                    same_expression_ordinal=0,
                ),
                original_outer_expression=module.code_for_node(outer).strip(),
                consumed_site_ids=consumed,
                anchor_relations=relations,
            )
        )
    result = QueryCompositionPlan(groups=tuple(groups))
    if (ids and not result.groups) or result.consumed_site_ids != frozenset(ids):
        raise AnchorRefusedError("query composition groups do not close reviewed IDs")
    return result


_MAPPING_QUERY_BY_FIELD = {
    "approval_decisions": "approval_decisions_view",
    "authority_decisions": "authority_decisions_view",
    "accepted_graph_patches_by_node": "accepted_graph_patches_by_node_view",
    "accepted_no_successor_patches_by_node": "accepted_no_successor_patches_by_node_view",
    "accepted_output_records_by_node_port": "accepted_output_records_by_node_port_view",
    "accepted_record_summaries_by_id": "accepted_record_summaries_by_id_view",
    "active_requirement_versions": "active_requirement_versions_view",
    "callback_idempotency_events": "callback_idempotency_events_view",
    "check_results": "check_results_view",
    "cleanup_applied_ids": "cleanup_applied_ids_view",
    "cleanup_requested_events": "cleanup_requested_events_view",
    "decision_request_details": "decision_request_details_view",
    "edges": "edges_view",
    "environment_failures": "environment_failures_view",
    "execution_count_by_node_kind": "execution_count_by_node_kind_view",
    "failed_verification_candidate_ids": "failed_verification_candidate_ids_view",
    "failed_verification_results_by_record_id": "failed_verification_results_by_record_id_view",
    "file_state_records": "file_state_records_view",
    "input_bindings": "input_bindings_view",
    "invalid_test_blocks": "invalid_test_blocks_view",
    "last_deferred_reasons": "last_deferred_reasons_view",
    "latency_ms_by_node_kind": "latency_ms_by_node_kind_view",
    "leases": "leases_view",
    "node_attempts": "node_attempts_view",
    "node_allowed_actions": "node_allowed_actions_view",
    "node_command_definitions": "node_command_definitions_view",
    "node_creation_payloads": "node_creation_payloads_view",
    "node_creation_positions": "node_creation_positions_view",
    "node_gate_decisions": "node_gate_decisions_view",
    "node_failed_candidates": "node_failed_candidates_view",
    "node_kinds": "node_kinds_view",
    "node_output_ports": "node_output_ports_view",
    "node_pending_appeals": "node_pending_appeals_view",
    "node_preconditions": "node_preconditions_view",
    "node_resource_claims": "node_resource_claims_view",
    "node_roles": "node_roles_view",
    "node_states": "node_states_view",
    "node_task_regions": "node_task_regions_view",
    "output_records_by_node_port": "output_records_by_node_port_view",
    "output_record_payloads": "output_record_payloads_view",
    "passed_verification_results_by_record_id": "passed_verification_results_by_record_id_view",
    "planner_generations": "planner_generations_view",
    "planner_session_carryovers": "planner_session_carryovers_view",
    "planner_sessions": "planner_sessions_view",
    "recorded_node_usage_keys": "recorded_node_usage_keys_view",
    "recovery_nodes_by_record_id": "recovery_nodes_by_record_id_view",
    "requirement_revisions": "requirement_revisions_view",
    "retry_not_before_by_node": "retry_not_before_by_node_view",
    "task_candidates": "task_candidates_view",
    "task_states": "task_states_view",
    "support_evidence": "support_evidence_view",
    "tokens_by_node": "tokens_by_node_view",
    "tokens_by_node_kind": "tokens_by_node_kind_view",
    "verifier_verdicts": "verifier_verdicts_view",
}
_SEQUENCE_QUERY_BY_FIELD = {
    "passed_verification_candidate_ids": "passed_verification_candidate_ids_view",
    "ready_nodes": "ready_nodes_view",
}
_SCALAR_QUERY_BY_FIELD = {
    "completion_decision_passed": "completion_decision_passed",
    "latest_routine_snapshot_record": "latest_routine_snapshot_record",
    "planner_generation_budget": "planner_generation_budget",
    "run_state": "run_state",
}
_QUERY_REPLACEMENT_REGISTRY = {
    **{
        (field, AccessKind.LITERAL_SUBSCRIPT_READ, "literal_subscript_read"): (
            "mapping_snapshot",
            query,
        )
        for field, query in _MAPPING_QUERY_BY_FIELD.items()
    },
    **{
        (field, AccessKind.GET, "get"): ("mapping_snapshot", query)
        for field, query in _MAPPING_QUERY_BY_FIELD.items()
    },
    **{
        (field, AccessKind.LITERAL_SUBSCRIPT_READ, "literal_subscript_read"): (
            "sequence_snapshot",
            query,
        )
        for field, query in _SEQUENCE_QUERY_BY_FIELD.items()
    },
    **{
        (field, AccessKind.LITERAL_SUBSCRIPT_READ, "literal_subscript_read"): (
            "scalar_read",
            query,
        )
        for field, query in _SCALAR_QUERY_BY_FIELD.items()
    },
    **{
        (field, AccessKind.GET, "get"): ("scalar_read", query)
        for field, query in _SCALAR_QUERY_BY_FIELD.items()
    },
}


def _physical_nodes_for_context(
    outer: cst.CSTNode,
    context: ProjectionCallContext,
) -> tuple[cst.CSTNode, ...]:
    matches: list[cst.CSTNode] = []

    class Visitor(cst.CSTVisitor):
        def on_visit(self, node: cst.CSTNode) -> bool:
            is_subscript = (
                isinstance(node, cst.Subscript)
                and _literal_subscript_field(node) == context.physical_old_field_name
                and context.projection_expression
                in {_normalized_node(node), _normalized_node(node.value)}
                and context.physical_access_kind
                in {AccessKind.LITERAL_SUBSCRIPT_READ, AccessKind.DIRECT_ASSIGNMENT}
                and context.physical_operation_shape == context.physical_access_kind.value
            )
            is_get = (
                isinstance(node, cst.Call)
                and isinstance(node.func, cst.Attribute)
                and node.func.attr.value == "get"
                and _normalized_node(node.func.value) == context.projection_expression
                and _literal_argument_field(node.args) == context.physical_old_field_name
                and context.physical_access_kind is AccessKind.GET
                and context.physical_operation_shape == AccessKind.GET.value
            )
            if is_subscript or is_get:
                matches.append(node)
            return True

    outer.visit(Visitor())
    return tuple(matches)


def _physical_receiver_code(node: cst.CSTNode, module: cst.Module) -> str:
    if isinstance(node, cst.Subscript):
        return module.code_for_node(node.value)
    if isinstance(node, cst.Call) and isinstance(node.func, cst.Attribute):
        return module.code_for_node(node.func.value)
    raise AnchorRefusedError(f"unknown physical query receiver: {type(node).__name__}")


def _replace_physical_nodes(
    outer: cst.CSTNode, replacements: dict[cst.CSTNode, cst.BaseExpression]
) -> cst.CSTNode:
    replacements_by_id = {id(node): replacement for node, replacement in replacements.items()}

    class Transformer(cst.CSTTransformer):
        def on_leave(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> cst.CSTNode:
            return replacements_by_id.get(id(original_node), updated_node)

    return outer.visit(Transformer())


def compile_query_replacement_plan(
    sources: Iterable[SourceSnapshot],
    stream: OperationStream,
    disposition_plan: DispositionPlan,
    composition_plan: QueryCompositionPlan,
) -> QueryReplacementPlan:
    """Substitute exact physical descendants inside approved outer CST expressions."""
    sites = {site.original_site_id: site for site in stream.sites}
    if len(sites) != len(stream.sites):
        raise AnchorRefusedError("duplicate query replacement operation-stream site identity")
    expected_ids = frozenset(
        site_id
        for operation in disposition_plan.operations
        if operation.disposition == "query_transform"
        for site_id in operation.consumed_site_ids
    )
    if (
        sum(
            len(operation.consumed_site_ids)
            for operation in disposition_plan.operations
            if operation.disposition == "query_transform"
        )
        != len(expected_ids)
        or expected_ids != composition_plan.consumed_site_ids
        or any(site_id not in sites for site_id in expected_ids)
    ):
        raise AnchorRefusedError("query replacement inputs do not have exact ID closure")
    anchored = _reanchor_operation_stream_sites(sources, stream.sites)
    recipes: list[QueryReplacementRecipe] = []
    handoffs: list[QueryMutationHandoff] = []
    unmatched: Counter[str] = Counter()

    for group in composition_plan.groups:
        first_node, parents, positions, module = anchored[group.consumed_site_ids[0]]
        outer = _outer_action(first_node, parents)
        position = positions[outer]
        actual_span = (
            position.start.line,
            position.start.column,
            position.end.line,
            position.end.column,
        )
        if (
            sites[group.consumed_site_ids[0]].relative_path != group.relative_path
            or actual_span != group.source_span
            or module.code_for_node(outer).strip() != group.original_outer_expression
        ):
            raise AnchorRefusedError("query replacement composition evidence is stale")

        node_ids: dict[cst.CSTNode, set[str]] = defaultdict(set)
        contexts: dict[cst.CSTNode, ProjectionCallContext] = {}
        for site_id in group.consumed_site_ids:
            site = sites[site_id]
            require_complete_receiver_physical_context(site)
            context = site.anchor.context
            assert context is not None
            anchored_node = anchored[site_id][0]
            anchored_signature = _physical_signature(anchored_node, parents)
            matches = (
                (anchored_node,)
                if site.origin == "occurrence"
                and (anchored_node is outer or _is_ancestor(outer, anchored_node, parents))
                and anchored_signature
                == (
                    context.projection_expression,
                    context.physical_old_field_name,
                    context.physical_access_kind,
                    context.physical_operation_shape,
                )
                else _physical_nodes_for_context(outer, context)
            )
            if len(matches) != 1:
                raise AnchorRefusedError(
                    "query replacement physical descendant requires exactly one source match: "
                    f"{context.physical_old_field_name}|{context.physical_access_kind}|"
                    f"{context.physical_operation_shape}|{context.projection_expression}|"
                    f"{group.original_outer_expression}|{len(matches)}"
                )
            matched_node = matches[0]
            node = (
                _root_subscript(matched_node)
                if isinstance(matched_node, cst.Subscript)
                else matched_node
            )
            previous = contexts.get(node)
            if previous is not None and (
                previous.physical_old_field_name != context.physical_old_field_name
                or previous.physical_access_kind is not context.physical_access_kind
                or previous.physical_operation_shape != context.physical_operation_shape
            ):
                raise AnchorRefusedError("query replacement descendant contexts disagree")
            contexts[node] = context
            node_ids[node].add(site_id)

        mutations = [
            node
            for node, context in contexts.items()
            if context.physical_access_kind
            not in {AccessKind.LITERAL_SUBSCRIPT_READ, AccessKind.GET}
        ]
        if mutations:
            if len(mutations) != len(contexts):
                raise AnchorRefusedError("query replacement group mixes reads and mutations")
            for node in mutations:
                context = contexts[node]
                family = "|".join(
                    (
                        context.physical_old_field_name or "-",
                        context.physical_access_kind.value,
                        context.physical_operation_shape or "-",
                    )
                )
                if (
                    context.physical_access_kind is not AccessKind.DIRECT_ASSIGNMENT
                    or context.physical_operation_shape != "direct_assignment"
                ):
                    unmatched[family] += len(node_ids[node])
                    continue
                handoffs.append(
                    QueryMutationHandoff(
                        relative_path=group.relative_path,
                        source_span=group.source_span,
                        original_outer_expression=group.original_outer_expression,
                        consumed_site_ids=tuple(sorted(node_ids[node])),
                        effective_old_field=context.physical_old_field_name or "",
                        access_kind=context.physical_access_kind.value,
                        operation_shape=context.physical_operation_shape,
                        rule_id="fixture_direct_assignment",
                    )
                )
            continue

        replacements: dict[cst.CSTNode, cst.BaseExpression] = {}
        imports: set[str] = set()
        rules: list[str] = []
        for node, context in contexts.items():
            field = context.physical_old_field_name
            access_kind = context.physical_access_kind
            physical_shape = context.physical_operation_shape
            key = (field or "", access_kind, physical_shape or "")
            selected = _QUERY_REPLACEMENT_REGISTRY.get(key)
            if selected is None:
                unmatched[
                    "|".join((key[0], access_kind.value if access_kind else "-", key[2]))
                ] += len(node_ids[node])
                continue
            rule_id, query_api = selected
            receiver = _physical_receiver_code(node, module)
            replacements[node] = cst.parse_expression(f"{query_api}({receiver})")
            imports.add(query_api)
            rules.append(rule_id)
        if len(replacements) != len(contexts):
            continue
        replacement_node = _replace_physical_nodes(outer, replacements)
        replacement = module.code_for_node(replacement_node).strip()
        parsed = cst.parse_expression(replacement)
        parsed_module = cst.Module([cst.SimpleStatementLine([cst.Expr(parsed)])])
        parsed_candidates, parsed_parents, _, _, _ = _node_candidates(parsed_module)
        consumed_fields = {context.physical_old_field_name for context in contexts.values()}
        residual = [
            node
            for candidates in parsed_candidates.values()
            for node in candidates
            if (signature := _physical_signature(node, parsed_parents)) is not None
            and signature[1] in consumed_fields
        ]
        if residual:
            raise AnchorRefusedError(
                f"query replacement retains direct physical projection access: {replacement}"
            )
        recipes.append(
            QueryReplacementRecipe(
                relative_path=group.relative_path,
                source_span=group.source_span,
                original_outer_expression=group.original_outer_expression,
                replacement_outer_expression=replacement,
                consumed_site_ids=group.consumed_site_ids,
                query_imports=tuple(sorted(imports)),
                rule_ids=tuple(sorted(rules)),
            )
        )

    if unmatched:
        raise AnchorRefusedError(
            f"unmatched query replacement structural families: {tuple(sorted(unmatched.items()))!r}"
        )
    recipes.sort(key=lambda item: (item.relative_path, item.source_span, item.consumed_site_ids))
    handoffs.sort(key=lambda item: (item.relative_path, item.source_span, item.consumed_site_ids))
    result = QueryReplacementPlan(
        recipes=tuple(recipes),
        mutation_handoffs=tuple(handoffs),
        unmatched_family_counts=(),
        rule_family_counts=tuple(
            sorted(Counter(rule for item in recipes for rule in item.rule_ids).items())
        ),
        query_import_counts=tuple(
            sorted(Counter(name for item in recipes for name in item.query_imports).items())
        ),
    )
    if result.consumed_site_ids != expected_ids:
        raise AnchorRefusedError("query replacement plan does not close reviewed IDs")
    return result


def _expression_counts(module: cst.Module) -> Counter[str]:
    counts: Counter[str] = Counter()

    class Visitor(cst.CSTVisitor):
        def on_visit(self, node: cst.CSTNode) -> bool:
            if isinstance(node, cst.BaseExpression):
                expression = _normalized_node(node)
                if expression is not None:
                    counts[expression] += 1
            return True

    module.visit(Visitor())
    return counts


def _query_import_aliases(source: str, imports: tuple[str, ...]) -> dict[str, str]:
    tree = ast.parse(source)
    bound = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    } | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    occupied = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | bound
    aliases: dict[str, str] = {}
    for name in imports:
        if name not in bound:
            continue
        alias = f"query_{name}"
        while alias in occupied:
            alias = f"_{alias}"
        aliases[name] = alias
        occupied.add(alias)
    return aliases


def _aliased_replacement_expression(
    recipe: QueryReplacementRecipe, aliases: dict[str, str]
) -> cst.BaseExpression:
    expression = cst.parse_expression(recipe.replacement_outer_expression)

    class Transformer(cst.CSTTransformer):
        def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
            if isinstance(original_node.func, cst.Name) and original_node.func.value in aliases:
                return updated_node.with_changes(func=cst.Name(aliases[original_node.func.value]))
            return updated_node

    transformed = expression.visit(Transformer())
    assert isinstance(transformed, cst.BaseExpression)
    return transformed


def _apply_source_recipes(
    source: SourceSnapshot, recipes: tuple[QueryReplacementRecipe, ...]
) -> QuerySourceUpdate:
    module = cst.parse_module(source.source)
    by_span = {recipe.source_span: recipe for recipe in recipes}
    if len(by_span) != len(recipes):
        raise AnchorRefusedError("query source recipes repeat an outer source span")
    matched: set[tuple[int, int, int, int]] = set()
    imports = tuple(sorted({name for recipe in recipes for name in recipe.query_imports}))
    aliases = _query_import_aliases(source.source, imports)
    replacements = {
        recipe.source_span: _aliased_replacement_expression(recipe, aliases) for recipe in recipes
    }

    class Transformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (PositionProvider,)

        def on_leave(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> cst.CSTNode:
            if not isinstance(original_node, cst.BaseExpression):
                return updated_node
            position = self.get_metadata(PositionProvider, original_node)
            span = (
                position.start.line,
                position.start.column,
                position.end.line,
                position.end.column,
            )
            recipe = by_span.get(span)
            if recipe is None:
                return updated_node
            if module.code_for_node(original_node).strip() != recipe.original_outer_expression:
                raise AnchorRefusedError(
                    f"query source recipe does not match exact outer expression: "
                    f"{source.relative_path}:{span}"
                )
            matched.add(span)
            return replacements[span]

    transformed = MetadataWrapper(module).visit(Transformer())
    missing = set(by_span) - matched
    if missing:
        replacement_counts = _expression_counts(transformed)
        expected_replacements = Counter(
            _normalized_node(replacements[recipe.source_span]) for recipe in recipes
        )
        already_applied = not matched and all(
            expression is not None and replacement_counts[expression] >= count
            for expression, count in expected_replacements.items()
        )
        if not already_applied:
            raise AnchorRefusedError(
                f"query source recipe does not match exact outer expression: "
                f"{source.relative_path}:{tuple(sorted(missing))!r}"
            )

    import_module = (
        "orchestrator.graph.projection_queries"
        if source.relative_path.startswith("src/orchestrator/graph/")
        else "orchestrator.graph"
    )
    context = CodemodContext()
    for name in imports:
        AddImportsVisitor.add_needed_import(context, import_module, name, asname=aliases.get(name))
    transformed = AddImportsVisitor(context).transform_module(transformed)
    transformed_source = transformed.code
    ast.parse(transformed_source)
    parsed = cst.parse_module(transformed_source)
    final_counts = _expression_counts(parsed)
    expected_final = Counter(
        _normalized_node(replacements[recipe.source_span]) for recipe in recipes
    )
    if any(
        expression is None or final_counts[expression] < count
        for expression, count in expected_final.items()
    ):
        raise AnchorRefusedError("query source apply retains a consumed physical read")
    return QuerySourceUpdate(
        relative_path=source.relative_path,
        original_source=source.source,
        transformed_source=transformed_source,
        consumed_site_ids=tuple(
            sorted(site_id for recipe in recipes for site_id in recipe.consumed_site_ids)
        ),
        query_imports=imports,
    )


def apply_query_replacement_plan(
    sources: Iterable[SourceSnapshot], plan: QueryReplacementPlan
) -> QuerySourceApplyPlan:
    """Validate and produce all recipe source updates without filesystem writes."""
    snapshots = tuple(sources)
    by_path = {source.relative_path: source for source in snapshots}
    if len(by_path) != len(snapshots):
        raise AnchorRefusedError("query source apply received duplicate source paths")
    grouped: dict[str, list[QueryReplacementRecipe]] = defaultdict(list)
    for recipe in plan.recipes:
        grouped[recipe.relative_path].append(recipe)
    missing_paths = set(grouped) - by_path.keys()
    if missing_paths:
        raise AnchorRefusedError(
            f"query source apply is missing recipe snapshots: {tuple(sorted(missing_paths))!r}"
        )
    updates = tuple(
        _apply_source_recipes(by_path[path], tuple(grouped[path])) for path in sorted(grouped)
    )
    result = QuerySourceApplyPlan(updates=updates)
    expected_read_ids = frozenset(
        site_id for recipe in plan.recipes for site_id in recipe.consumed_site_ids
    )
    if result.consumed_site_ids != expected_read_ids:
        raise AnchorRefusedError("query source apply does not close recipe read IDs")
    return result


def write_query_source_apply_plan(root: Path, plan: QuerySourceApplyPlan) -> tuple[str, ...]:
    """Write a fully validated apply plan with atomic per-file replacements."""
    root = root.resolve()
    targets: list[tuple[QuerySourceUpdate, Path]] = []
    for update in plan.updates:
        relative = Path(update.relative_path)
        target = (root / relative).resolve()
        if relative.is_absolute() or root not in target.parents:
            raise AnchorRefusedError("query source apply path escapes the repository root")
        if not target.is_file() or target.read_text() != update.original_source:
            raise AnchorRefusedError(
                f"query source changed before atomic apply: {update.relative_path}"
            )
        targets.append((update, target))

    temporary_paths: list[tuple[str, Path]] = []
    try:
        for update, target in targets:
            descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(update.transformed_source)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, target.stat().st_mode)
            temporary_paths.append((update.relative_path, temporary))
        for (_, target), (_, temporary) in zip(targets, temporary_paths, strict=True):
            os.replace(temporary, target)
        return tuple(path for path, _ in temporary_paths)
    finally:
        for _, temporary in temporary_paths:
            if temporary.exists():
                temporary.unlink()


def _fixture_small_statement(
    node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]
) -> cst.BaseSmallStatement:
    current = node
    while not isinstance(current, cst.BaseSmallStatement):
        parent = parents.get(current)
        if parent is None or isinstance(parent, cst.BaseStatement):
            raise AnchorRefusedError("fixture mutation has no simple statement boundary")
        current = parent
    return current


def _fixture_subscript_parts(
    node: cst.BaseExpression,
) -> tuple[cst.Name, tuple[cst.BaseExpression, ...]]:
    parts: list[cst.BaseExpression] = []
    current = node
    while isinstance(current, cst.Subscript):
        if len(current.slice) != 1 or not isinstance(current.slice[0].slice, cst.Index):
            raise AnchorRefusedError("fixture mutation requires simple subscript indexes")
        parts.append(current.slice[0].slice.value)
        current = current.value
    if not isinstance(current, cst.Name):
        raise AnchorRefusedError("fixture mutation requires a writable Name receiver")
    parts.reverse()
    if not parts:
        raise AnchorRefusedError("fixture mutation requires a physical field subscript")
    return current, tuple(parts)


def _fixture_string_literal(node: cst.BaseExpression, *, label: str) -> str:
    if not isinstance(node, cst.SimpleString):
        raise AnchorRefusedError(f"fixture mutation {label} must be a string literal")
    value = ast.literal_eval(node.value)
    if not isinstance(value, str):
        raise AnchorRefusedError(f"fixture mutation {label} must be a string literal")
    return value


def _fixture_key_code(node: cst.BaseExpression, module: cst.Module) -> str:
    if isinstance(node, cst.Name):
        return node.value
    _fixture_string_literal(node, label="key")
    return module.code_for_node(node)


def _fixture_call_argument(call: cst.Call) -> cst.BaseExpression:
    if len(call.args) != 1 or call.args[0].keyword is not None or call.args[0].star != "":
        raise AnchorRefusedError("fixture mutation call requires one positional argument")
    return call.args[0].value


def _compile_fixture_statement(
    statement: cst.BaseSmallStatement,
    module: cst.Module,
    operation: GeneratedFixtureOperation,
) -> tuple[str, str]:
    helper: str
    replacement: str
    if isinstance(statement, cst.Assign):
        if len(statement.targets) != 1:
            raise AnchorRefusedError("fixture mutation assignment requires one target")
        receiver, parts = _fixture_subscript_parts(statement.targets[0].target)
        field = _fixture_string_literal(parts[0], label="field")
        value = module.code_for_node(statement.value)
        if len(parts) == 1 and operation.rule_id == "literal_field_update_mutation":
            helper = "projection_fixture_replace"
            replacement = f"{receiver.value} = {helper}({receiver.value}, {field!r}, {value})"
        elif len(parts) > 1 and operation.rule_id == "physical_nested_assignment":
            keys = tuple(_fixture_key_code(key, module) for key in parts[1:])
            key_tuple = f"({', '.join(keys)}{',' if len(keys) == 1 else ''})"
            helper = "projection_fixture_set"
            replacement = (
                f"{receiver.value} = {helper}({receiver.value}, {field!r}, {key_tuple}, {value})"
            )
        else:
            raise AnchorRefusedError("fixture mutation assignment disagrees with its rule")
        return helper, replacement

    if not isinstance(statement, cst.Expr) or not isinstance(statement.value, cst.Call):
        raise AnchorRefusedError("fixture mutation requires assignment or bare call")
    call = statement.value
    if not isinstance(call.func, cst.Attribute) or not isinstance(call.func.attr, cst.Name):
        raise AnchorRefusedError("fixture mutation requires a named method call")
    receiver, parts = _fixture_subscript_parts(call.func.value)
    if len(parts) != 1:
        raise AnchorRefusedError("fixture mutation method requires a field receiver")
    field = _fixture_string_literal(parts[0], label="field")
    argument = _fixture_call_argument(call)
    argument_code = module.code_for_node(argument)
    if call.func.attr.value == "update" and operation.rule_id == "literal_field_update_mutation":
        helper = "projection_fixture_update"
        return helper, f"{receiver.value} = {helper}({receiver.value}, {field!r}, {argument_code})"
    if call.func.attr.value == "append" and operation.rule_id == "physical_append_extend":
        helper = "projection_fixture_append"
        return helper, f"{receiver.value} = {helper}({receiver.value}, {field!r}, {argument_code})"
    if call.func.attr.value == "extend" and operation.rule_id == "physical_append_extend":
        if not isinstance(argument, (cst.Tuple, cst.List)) or any(
            not isinstance(element, cst.Element) for element in argument.elements
        ):
            raise AnchorRefusedError("fixture extend requires a finite tuple or list literal")
        helper = "projection_fixture_append"
        expression = receiver.value
        for element in argument.elements:
            assert isinstance(element, cst.Element)
            value = module.code_for_node(element.value)
            expression = f"{helper}({expression}, {field!r}, {value})"
        return helper, f"{receiver.value} = {expression}"
    raise AnchorRefusedError("fixture mutation method disagrees with its rule")


def compile_fixture_mutation_plan(
    sources: Iterable[SourceSnapshot],
    stream: OperationStream,
    operations: Iterable[GeneratedFixtureOperation],
) -> FixtureMutationPlan:
    """Compile generated fixture operations into exact immutable rebinding recipes."""
    operations = tuple(operations)
    operation_ids = [item.site_id for item in operations]
    sites = {site.original_site_id: site for site in stream.sites}
    if len(operation_ids) != len(frozenset(operation_ids)) or any(
        site_id not in sites for site_id in operation_ids
    ):
        raise AnchorRefusedError("fixture mutation inputs do not have exact ID closure")
    selected_sites = tuple(sites[site_id] for site_id in operation_ids)
    anchored = _reanchor_operation_stream_sites(sources, selected_sites)
    recipes: list[FixtureMutationRecipe] = []
    for operation in operations:
        site = sites[operation.site_id]
        if _generated_fixture_rule(site) != operation:
            raise AnchorRefusedError("fixture mutation operation evidence is stale")
        node, parents, positions, module = anchored[operation.site_id]
        statement = _fixture_small_statement(node, parents)
        position = positions[statement]
        span = (
            position.start.line,
            position.start.column,
            position.end.line,
            position.end.column,
        )
        original = module.code_for_node(statement).strip()
        helper, replacement = _compile_fixture_statement(statement, module, operation)
        recipes.append(
            FixtureMutationRecipe(
                relative_path=site.relative_path,
                source_span=span,
                original_statement=original,
                replacement_statement=replacement,
                consumed_site_ids=(operation.site_id,),
                helper_import=helper,
                rule_id=operation.rule_id,
            )
        )
    recipes.sort(key=lambda item: (item.relative_path, item.source_span))
    result = FixtureMutationPlan(recipes=tuple(recipes))
    if result.consumed_site_ids != frozenset(operation_ids):
        raise AnchorRefusedError("fixture mutation plan does not close generated IDs")
    return result


def _fixture_import_aliases(source: str, imports: tuple[str, ...]) -> dict[str, str]:
    tree = ast.parse(source)
    existing = {
        alias.name: alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "tests.unit.graph_test_utils"
        for alias in node.names
        if alias.asname is not None
    }
    bound = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    } | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    occupied = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | bound
    aliases: dict[str, str] = {}
    for name in imports:
        if name in existing:
            aliases[name] = existing[name]
            continue
        if name not in bound:
            continue
        alias = f"fixture_{name}"
        while alias in occupied:
            alias = f"_{alias}"
        aliases[name] = alias
        occupied.add(alias)
    return aliases


def _aliased_fixture_statement(statement: str, aliases: dict[str, str]) -> cst.BaseSmallStatement:
    parsed = cst.parse_statement(f"{statement}\n")
    assert isinstance(parsed, cst.SimpleStatementLine)

    class Transformer(cst.CSTTransformer):
        def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
            if isinstance(original_node.func, cst.Name) and original_node.func.value in aliases:
                return updated_node.with_changes(func=cst.Name(aliases[original_node.func.value]))
            return updated_node

    transformed = parsed.body[0].visit(Transformer())
    assert isinstance(transformed, cst.BaseSmallStatement)
    return transformed


def _apply_fixture_source_recipes(
    source: SourceSnapshot, recipes: tuple[FixtureMutationRecipe, ...]
) -> FixtureSourceUpdate:
    module = cst.parse_module(source.source)
    by_span = {recipe.source_span: recipe for recipe in recipes}
    if len(by_span) != len(recipes):
        raise AnchorRefusedError("fixture mutation recipes repeat a source span")
    imports = tuple(sorted({recipe.helper_import for recipe in recipes}))
    aliases = _fixture_import_aliases(source.source, imports)
    replacements = {
        recipe.source_span: _aliased_fixture_statement(recipe.replacement_statement, aliases)
        for recipe in recipes
    }
    matched: set[tuple[int, int, int, int]] = set()

    class Transformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (PositionProvider,)

        def on_leave(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> cst.CSTNode:
            if not isinstance(original_node, cst.BaseSmallStatement):
                return updated_node
            position = self.get_metadata(PositionProvider, original_node)
            span = (
                position.start.line,
                position.start.column,
                position.end.line,
                position.end.column,
            )
            recipe = by_span.get(span)
            if recipe is None:
                return updated_node
            if module.code_for_node(original_node).strip() != recipe.original_statement:
                raise AnchorRefusedError(
                    f"fixture mutation recipe does not match exact statement: "
                    f"{source.relative_path}:{span}"
                )
            matched.add(span)
            return replacements[span]

    transformed = MetadataWrapper(module).visit(Transformer())
    if set(by_span) != matched:
        raise AnchorRefusedError("fixture mutation recipe does not match exact statement")

    context = CodemodContext()
    for name in imports:
        AddImportsVisitor.add_needed_import(
            context, "tests.unit.graph_test_utils", name, asname=aliases.get(name)
        )
    transformed = AddImportsVisitor(context).transform_module(transformed)
    transformed_source = transformed.code
    ast.parse(transformed_source)
    return FixtureSourceUpdate(
        relative_path=source.relative_path,
        original_source=source.source,
        transformed_source=transformed_source,
        consumed_site_ids=tuple(
            sorted(site_id for recipe in recipes for site_id in recipe.consumed_site_ids)
        ),
        helper_imports=imports,
    )


def apply_fixture_mutation_plan(
    sources: Iterable[SourceSnapshot], plan: FixtureMutationPlan
) -> FixtureSourceApplyPlan:
    """Validate every fixture recipe and produce updates without filesystem writes."""
    snapshots = tuple(sources)
    by_path = {source.relative_path: source for source in snapshots}
    if len(by_path) != len(snapshots):
        raise AnchorRefusedError("fixture mutation apply received duplicate source paths")
    grouped: dict[str, list[FixtureMutationRecipe]] = defaultdict(list)
    for recipe in plan.recipes:
        grouped[recipe.relative_path].append(recipe)
    if set(grouped) - by_path.keys():
        raise AnchorRefusedError("fixture mutation apply is missing recipe snapshots")
    result = FixtureSourceApplyPlan(
        updates=tuple(
            _apply_fixture_source_recipes(by_path[path], tuple(grouped[path]))
            for path in sorted(grouped)
        )
    )
    if result.consumed_site_ids != plan.consumed_site_ids:
        raise AnchorRefusedError("fixture mutation apply does not close recipe IDs")
    return result


def write_fixture_source_apply_plan(root: Path, plan: FixtureSourceApplyPlan) -> tuple[str, ...]:
    """Write a fully validated fixture apply plan with atomic replacements."""
    root = root.resolve()
    targets: list[tuple[FixtureSourceUpdate, Path]] = []
    for update in plan.updates:
        relative = Path(update.relative_path)
        target = (root / relative).resolve()
        if relative.is_absolute() or root not in target.parents:
            raise AnchorRefusedError("fixture source apply path escapes the repository root")
        if not target.is_file() or target.read_text() != update.original_source:
            raise AnchorRefusedError(
                f"fixture source changed before atomic apply: {update.relative_path}"
            )
        targets.append((update, target))

    temporary_paths: list[tuple[str, Path]] = []
    try:
        for update, target in targets:
            descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(update.transformed_source)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, target.stat().st_mode)
            temporary_paths.append((update.relative_path, temporary))
        for (_, target), (_, temporary) in zip(targets, temporary_paths, strict=True):
            os.replace(temporary, target)
        return tuple(path for path, _ in temporary_paths)
    finally:
        for _, temporary in temporary_paths:
            if temporary.exists():
                temporary.unlink()


_GRAPH_ORIGIN = "orchestrator.graph"
_PROJECTION_FACTORIES = frozenset(
    {
        "orchestrator.graph.initial_projection",
        "orchestrator.graph.build_projection",
        "orchestrator.graph.reduce_event",
        "orchestrator.graph.projection_from_checkpoint",
        "orchestrator.graph_runtime.controller.rebuild_projection",
        "orchestrator.graph.projections.reduce_event",
    }
)
_PUBLIC_PROJECTION_ARGUMENT_POSITIONS = {
    "orchestrator.graph.callbacks.validate_callback": frozenset({1}),
    "orchestrator.graph.commands.apply_command": frozenset({0}),
    "orchestrator.graph.patch_validator.validate_patch": frozenset({3}),
    "orchestrator.graph.projections.final_invariant_blockers_for_events": frozenset({1}),
    "orchestrator.graph_runtime.store.GraphEventStore.persist_projection_snapshot": frozenset({1}),
}
_PUBLIC_PROJECTION_CALLS = frozenset(
    {
        "orchestrator.graph.verifier_verdict",
        "orchestrator.graph.apply_command",
        "orchestrator.graph.commands.apply_command",
        "orchestrator.graph.recovery_nodes_for_record",
        "orchestrator.graph.invalid_test_blocks",
        "orchestrator.graph.check_results",
        "orchestrator.graph.passed_verification_result",
        "orchestrator.graph.failed_verification_result",
        "orchestrator.graph.node_usage_recorded",
        "orchestrator.graph.recovery_nodes",
        "orchestrator.graph.passed_verification_results",
        "orchestrator.graph.latest_routine_snapshot_record",
        "orchestrator.graph.failed_verification_results",
        "orchestrator.graph.accepted_output_records_for_node_port",
        "orchestrator.graph.check_result",
        "orchestrator.graph.invalid_test_block",
        "orchestrator.graph.failed_verification_candidate_ids",
        "orchestrator.graph.authority_revision_blocker",
        "orchestrator.graph.gate_decision",
        "orchestrator.graph.node_gate_decision",
        "orchestrator.graph.decision_request",
        "orchestrator.graph.configured_gates",
        "orchestrator.graph.node_states",
        "orchestrator.graph.task_states",
        "orchestrator.graph.passed_verification_candidate_ids",
        "orchestrator.graph.oversight_decision",
        "orchestrator.graph.accepted_output_records",
        "orchestrator.graph.environment_failure",
        "orchestrator.graph.support_evidence",
        "orchestrator.graph.accepted_no_successor_patch_id",
        "orchestrator.graph.accepted_no_successor_patch_ids",
        "orchestrator.graph.environment_failures",
        "orchestrator.graph.planner_generation_budget",
        "orchestrator.graph.accepted_graph_patch_ids",
        "orchestrator.graph.requirement_revision",
        "orchestrator.graph.project_leases",
        "orchestrator.graph.project_node_states",
        "orchestrator.graph.run_state",
        "orchestrator.graph.project_scheduler_view",
        "orchestrator.graph.completion_decision_passed",
        "orchestrator.graph.projection_to_checkpoint",
        "orchestrator.graph.project_node_metadata",
        "orchestrator.graph.project_lease_view",
        "orchestrator.graph.project_final_invariant_blockers",
        "orchestrator.graph.project_run_state",
        "orchestrator.graph.project_task_states",
        "orchestrator.graph.project_ready_nodes",
        "orchestrator.graph.project_decision_view_from_projection",
        "orchestrator.graph.projection_queries.resource_claims_for_node",
        "orchestrator.graph.project_graph_projection_snapshot",
        "orchestrator.graph.project_decision_view",
        "orchestrator.graph.callbacks.validate_callback",
        "orchestrator.graph.patch_validator.validate_patch",
        "orchestrator.graph.projections.final_invariant_blockers_for_events",
        "orchestrator.graph_runtime.store.GraphEventStore.persist_projection_snapshot",
    }
) | frozenset(
    origin
    for query_api in {
        *_MAPPING_QUERY_BY_FIELD.values(),
        *_SCALAR_QUERY_BY_FIELD.values(),
        *_SEQUENCE_QUERY_BY_FIELD.values(),
    }
    for origin in (
        f"orchestrator.graph.{query_api}",
        f"orchestrator.graph.projection_queries.{query_api}",
    )
)
_DERIVED_VALUE_SINKS = frozenset({"orchestrator.graph.scheduler.NodeScheduleInfo"})
_FIXTURE_MUTATION_HELPERS = frozenset(
    {
        "projection_fixture_append",
        "projection_fixture_replace",
        "projection_fixture_set",
        "projection_fixture_update",
    }
)
_APPROVED_CORE_PATHS = frozenset(
    {
        "src/orchestrator/graph/projection_models.py",
        "src/orchestrator/graph/projection_collections.py",
        "src/orchestrator/graph/projection_queries.py",
        "src/orchestrator/graph/projection_codec.py",
        "src/orchestrator/graph/projections.py",
    }
)
_GRAPH_PROJECTION_ORIGINS = frozenset(
    {
        "orchestrator.graph.GraphProjection",
        "orchestrator.graph._commands.GraphProjection",
        "orchestrator.graph.projections.GraphProjection",
    }
)
_APPROVED_CORE_READ_SHAPES = frozenset(
    {
        "subscript_read",
        "literal_subscript_read",
        "map_get",
        "keys_iteration",
        "values_iteration",
        "items_iteration",
        "membership",
        "nested_get",
        "items",
        "values",
    }
)


def _approved_import_origin(name: QualifiedName | None) -> str | None:
    if name is None or name.source.name != "IMPORT":
        return None
    if name.name.rpartition(".")[0] in {
        "orchestrator.graph",
        "orchestrator.graph.callbacks",
        "orchestrator.graph._commands",
        "orchestrator.graph.commands",
        "orchestrator.graph.patch_validator",
        "orchestrator.graph.projections",
        "orchestrator.graph.projection_queries",
        "orchestrator.graph.scheduler",
        "orchestrator.graph_runtime",
        "orchestrator.graph_runtime.controller",
        "orchestrator.graph_runtime.dispatch",
    }:
        return name.name
    return None


def _context_call_origin(name: QualifiedName | None) -> str | None:
    imported = _approved_import_origin(name)
    if imported is not None:
        return imported
    if name is not None and name.source.name == "IMPORT" and name.name == "typing.cast":
        return name.name
    if (
        name is not None
        and name.source.name == "LOCAL"
        and name.name.startswith("GraphEventStore.")
        and name.name.endswith(".<locals>.self.persist_projection_snapshot")
    ):
        return "orchestrator.graph_runtime.store.GraphEventStore.persist_projection_snapshot"
    return None


def _is_projection_factory(origin: str | None) -> bool:
    return origin in _PROJECTION_FACTORIES


def _resolved_qualified_names(
    node: cst.CSTNode, qualified_names: dict[cst.CSTNode, object]
) -> frozenset[QualifiedName]:
    value = qualified_names.get(node, frozenset())
    resolved = value() if callable(value) else value
    if not isinstance(resolved, set):
        return frozenset()
    return frozenset(item for item in resolved if isinstance(item, QualifiedName))


def _one_qualified_name(
    node: cst.CSTNode, qualified_names: dict[cst.CSTNode, object]
) -> QualifiedName | None:
    names = _resolved_qualified_names(node, qualified_names)
    return next(iter(names)) if len(names) == 1 else None


def _literal_subscript_field(node: cst.Subscript) -> str | None:
    if (
        len(node.slice) != 1
        or not isinstance((element := node.slice[0]).slice, cst.Index)
        or not isinstance(element.slice.value, cst.SimpleString)
    ):
        return None
    return element.slice.value.evaluated_value


def _literal_argument_field(arguments: tuple[cst.Arg, ...]) -> str | None:
    if not arguments or not isinstance(arguments[0].value, cst.SimpleString):
        return None
    return arguments[0].value.evaluated_value


def _root_subscript(node: cst.Subscript) -> cst.Subscript:
    current = node
    while isinstance(current.value, cst.Subscript):
        current = current.value
    return current


def _is_physical_mutation_descendant(
    node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]
) -> bool:
    current = node
    while (parent := parents.get(current)) is not None:
        if isinstance(parent, (cst.AssignTarget, cst.Del, cst.AugAssign)) or (
            isinstance(parent, cst.AnnAssign) and parent.target is current
        ):
            return current is not node
        if (
            isinstance(parent, cst.Attribute)
            and parent.value is current
            and parent.attr.value
            in {"append", "clear", "extend", "pop", "remove", "setdefault", "update"}
        ):
            return True
        if isinstance(parent, cst.BaseStatement):
            return False
        current = parent
    return False


def _physical_signature(
    node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]
) -> tuple[str, str | None, AccessKind, str] | None:
    """Derive one physical operation from its exact CST action and receiver."""
    if isinstance(node, cst.Del) and isinstance(node.target, cst.Subscript):
        physical_target = _root_subscript(node.target)
        field = _literal_subscript_field(physical_target)
        receiver = _normalized_node(node.target.value)
        if field is not None and receiver is not None:
            return receiver, field, AccessKind.DELETE_POP, AccessKind.DELETE_POP.value
        return None
    if isinstance(node, cst.Comparison) and len(node.comparisons) == 1:
        comparison = node.comparisons[0]
        if isinstance(comparison.operator, (cst.In, cst.NotIn)):
            receiver = _normalized_node(comparison.comparator)
            if isinstance(node.left, cst.SimpleString) and receiver is not None:
                return (
                    receiver,
                    node.left.evaluated_value,
                    AccessKind.MEMBERSHIP,
                    AccessKind.MEMBERSHIP.value,
                )
    if isinstance(node, cst.Subscript):
        if isinstance(parents[node], cst.Subscript) and parents[node].value is node:
            return None
        if isinstance(parents[node], cst.Del) or _is_physical_mutation_descendant(node, parents):
            return None
        field = _literal_subscript_field(_root_subscript(node))
        receiver = _normalized_node(_root_subscript(node).value)
        if field is None or receiver is None:
            return None
        parent = parents[node]
        if isinstance(parent, cst.AssignTarget) or (
            isinstance(parent, cst.AnnAssign) and parent.target is node
        ):
            kind = (
                AccessKind.NESTED_ASSIGNMENT
                if isinstance(node.value, cst.Subscript)
                else AccessKind.DIRECT_ASSIGNMENT
            )
        else:
            kind = AccessKind.LITERAL_SUBSCRIPT_READ
        return receiver, field, kind, kind.value
    if not isinstance(node, cst.Call) or not isinstance(node.func, cst.Attribute):
        return None
    method = node.func.attr.value
    receiver = node.func.value
    receiver_expression = _normalized_node(receiver)
    if receiver_expression is None:
        return None
    if isinstance(receiver, cst.Subscript) and method not in {"append", "extend"}:
        field = _literal_subscript_field(_root_subscript(receiver))
        if field is not None:
            return (
                receiver_expression,
                field,
                AccessKind.LITERAL_SUBSCRIPT_READ,
                AccessKind.LITERAL_SUBSCRIPT_READ.value,
            )
    direct_methods = {
        "get": AccessKind.GET,
        "pop": AccessKind.DELETE_POP,
        "setdefault": AccessKind.SETDEFAULT,
        "keys": AccessKind.KEYS,
        "values": AccessKind.VALUES,
        "items": AccessKind.ITEMS,
    }
    if method in direct_methods:
        field = (
            None if method in {"keys", "values", "items"} else _literal_argument_field(node.args)
        )
        if method in {"keys", "values", "items"} or field is not None:
            kind = direct_methods[method]
            return receiver_expression, field, kind, kind.value
        return None
    if method not in {"append", "extend"}:
        return None
    if isinstance(receiver, cst.Subscript):
        field = _literal_subscript_field(receiver)
    elif (
        isinstance(receiver, cst.Call)
        and isinstance(receiver.func, cst.Attribute)
        and receiver.func.attr.value == "get"
    ):
        field = _literal_argument_field(receiver.args)
    else:
        field = None
    if field is None:
        return None
    return receiver_expression, field, AccessKind.APPEND_EXTEND, AccessKind.APPEND_EXTEND.value


def _reanchor_context(
    node: cst.CSTNode,
    stored: ProjectionCallContext | None,
    qualified_names: dict[cst.CSTNode, object],
    parents: dict[cst.CSTNode, cst.CSTNode],
    expected_access_kind: AccessKind | None = None,
) -> ProjectionCallContext | None:
    """Revalidate stored collector context without discovering projection values."""
    if stored is None:
        return None
    if stored.physical_access_kind is not None:
        if stored.projection_role != "receiver":
            raise AnchorRefusedError("inventory physical context does not match CST anchor")
        signatures = [signature for signature in (_physical_signature(node, parents),) if signature]

        class PhysicalVisitor(cst.CSTVisitor):
            def on_visit(_, child: cst.CSTNode) -> bool:
                if (
                    child is not node
                    and (signature := _physical_signature(child, parents)) is not None
                ):
                    signatures.append(signature)
                return True

        node.visit(PhysicalVisitor())
        if not signatures:
            raise AnchorRefusedError("inventory physical context does not match CST anchor")
        matching_signatures = [
            signature
            for signature in signatures
            if signature[0] == stored.projection_expression
            and signature[1] == stored.physical_old_field_name
            and signature[2] is stored.physical_access_kind
            and signature[3] == stored.physical_operation_shape
        ]
        if len(matching_signatures) == 1:
            receiver, field, access_kind, operation_shape = matching_signatures[0]
            if expected_access_kind is not None and expected_access_kind is not access_kind:
                raise AnchorRefusedError("inventory physical access kind does not match CST anchor")
            return stored
        receiver_matches = [
            signature for signature in signatures if signature[0] == stored.projection_expression
        ]
        if not receiver_matches:
            raise AnchorRefusedError("inventory projection expression does not match CST anchor")
        if len(receiver_matches) != 1:
            raise AnchorRefusedError("inventory physical context does not match CST anchor")
        _, field, access_kind, operation_shape = receiver_matches[0]
        if (
            expected_access_kind is not None
            and expected_access_kind is not access_kind
            or stored.physical_access_kind is not access_kind
        ):
            raise AnchorRefusedError("inventory physical access kind does not match CST anchor")
        if stored.physical_old_field_name != field:
            raise AnchorRefusedError("inventory physical context does not match CST anchor")
        if stored.physical_operation_shape != operation_shape:
            raise AnchorRefusedError("inventory physical operation shape does not match CST anchor")
        raise AnchorRefusedError("inventory physical context does not match CST anchor")
    if isinstance(node, cst.Param):
        annotation = node.annotation.annotation if node.annotation is not None else None
        name = _one_qualified_name(annotation, qualified_names) if annotation is not None else None
        origin = _approved_import_origin(name)
        if stored.receiver_type_origin != origin:
            raise AnchorRefusedError("inventory type context does not match CST anchor")
        if stored.projection_expression != _normalized_node(node.name):
            raise AnchorRefusedError("inventory projection expression does not match CST anchor")
        return stored
    direct_call = (
        node
        if isinstance(node, cst.Call)
        else node.value
        if isinstance(node, (cst.Assign, cst.AnnAssign, cst.Return))
        and isinstance(node.value, cst.Call)
        else None
    )
    calls = [direct_call] if direct_call is not None else []
    if isinstance(node, cst.Comparison):

        class CallVisitor(cst.CSTVisitor):
            def visit_Call(self, call: cst.Call) -> None:
                calls.append(call)

        node.visit(CallVisitor())
    if not calls:
        if stored.callee_origin is not None or stored.projection_role != "receiver":
            raise AnchorRefusedError("inventory call context does not match CST anchor")
        receiver = (
            node.value
            if isinstance(node, (cst.Subscript, cst.Return)) and node.value is not None
            else node
        )
        if stored.projection_expression != _normalized_node(receiver):
            raise AnchorRefusedError("inventory projection expression does not match CST anchor")
        return stored
    matching_calls = []
    for call in calls:
        name = _one_qualified_name(call.func, qualified_names)
        origin = _context_call_origin(name)
        if origin == stored.callee_origin:
            matching_calls.append(call)
    if len(matching_calls) != 1:
        raise AnchorRefusedError(
            "inventory callee context does not match CST anchor: "
            f"{stored.callee_origin!r} at {cst.Module([]).code_for_node(node).strip()!r}"
        )
    call = matching_calls[0]
    if stored.projection_role == "receiver":
        receiver = call.func.value if isinstance(call.func, cst.Attribute) else call
        if stored.projection_expression != _normalized_node(receiver):
            raise AnchorRefusedError("inventory receiver context does not match CST anchor")
        return stored
    elif stored.projection_role == "positional":
        positional_arguments = [
            argument for argument in call.args if argument.keyword is None and not argument.star
        ]
        if (
            stored.positional_index is None
            or stored.positional_index >= len(positional_arguments)
            or any(
                argument.star == "*"
                for argument in call.args[
                    : call.args.index(positional_arguments[stored.positional_index])
                ]
            )
        ):
            raise AnchorRefusedError("inventory positional context does not match CST anchor")
        if stored.projection_expression != _normalized_node(
            positional_arguments[stored.positional_index].value
        ):
            raise AnchorRefusedError("inventory positional expression does not match CST anchor")
    elif stored.projection_role == "keyword":
        matching_arguments = [
            argument
            for argument in call.args
            if argument.keyword is not None and argument.keyword.value == stored.keyword_name
        ]
        if len(matching_arguments) != 1 or stored.projection_expression != _normalized_node(
            matching_arguments[0].value
        ):
            raise AnchorRefusedError("inventory keyword context does not match CST anchor")
    elif stored.projection_role == "ambiguous":
        matching_arguments = (
            [
                argument
                for argument in call.args
                if argument.star == stored.argument_star
                and stored.projection_expression == _normalized_node(argument.value)
            ]
            if stored.argument_star
            else [
                argument
                for index, argument in enumerate(call.args)
                if not argument.star
                and stored.projection_expression == _normalized_node(argument.value)
                and any(item.star == stored.preceding_star for item in call.args[:index])
            ]
        )
        if len(matching_arguments) != 1:
            raise AnchorRefusedError("inventory ambiguous context does not match CST anchor")
    elif stored.projection_role == "derived_value":
        matching_arguments = [
            argument
            for argument in call.args
            if stored.projection_expression == _normalized_node(argument.value)
        ]
        if len(matching_arguments) != 1:
            raise AnchorRefusedError("inventory derived-value context does not match CST anchor")
    return stored


def plan_reviewed_dispositions(
    stream: OperationStream, manifest: QueryMigrationManifest
) -> DispositionPlan:
    """Compile reviewed ledger records to exact-once in-memory operations.

    This boundary deliberately uses ledger identities only to reconcile them to
    the already-anchored stream; it selects no transformation policy.
    """
    stream_by_id = {site.original_site_id: site for site in stream.sites}
    if len(stream_by_id) != len(stream.sites):
        raise AnchorRefusedError("duplicate anchored operation-stream site identity")
    reviewed_ids = {item.site_key for item in manifest.dispositions}
    missing = reviewed_ids - stream_by_id.keys()
    if missing:
        raise AnchorRefusedError(f"reviewed disposition has no anchored site: {sorted(missing)!r}")
    operations: list[PlannedOperation] = []
    for disposition in sorted(manifest.dispositions, key=lambda item: item.site_key):
        site = stream_by_id[disposition.site_key]
        if disposition.disposition == "rejected":
            raise AnchorRefusedError(
                f"reviewed disposition is not compilable: {disposition.disposition}"
            )
        if disposition.disposition == "query_transform":
            require_complete_receiver_physical_context(site)
        operations.append(
            PlannedOperation(
                disposition=disposition.disposition,
                reason=disposition.reason,
                consumed_site_ids=(site.original_site_id,),
                shape_key=site.shape_key,
            )
        )
    deferred = tuple(sorted(site.site_key for site in manifest.unclassified_sites))
    pending = tuple(sorted(set(stream_by_id) - reviewed_ids - set(deferred)))
    if (
        any(site.domain != "test_fixture" for site in manifest.unclassified_sites)
        or any(site_id not in stream_by_id for site_id in deferred)
        or reviewed_ids & set(deferred)
        or set(stream_by_id) != reviewed_ids | set(deferred) | set(pending)
    ):
        raise AnchorRefusedError("deferred fixture ledger does not match anchored stream")
    disposition_counts = tuple(sorted(Counter(item.disposition for item in operations).items()))
    shape_group_counts = tuple(sorted(Counter(item.shape_key for item in operations).items()))
    return DispositionPlan(
        operations=tuple(operations),
        reviewed_deferred_site_ids=deferred,
        generated_fixture_operations=(),
        pending_site_ids=pending,
        disposition_counts=disposition_counts,
        shape_group_counts=shape_group_counts,
        rule_family_counts=(),
        symbol_origin_counts=(),
        generated_fixture_family_counts=(),
    )


def _neutral_rule(site: MigrationSite) -> tuple[str, str] | None:
    """Return one finite structural rule and its proven origin, or fail closed."""
    anchor = site.anchor
    context = anchor.context
    if (
        site.diagnostic_code is DiagnosticCode.UNSUPPORTED_CALL
        and context is not None
        and context.callee_origin == "typing.cast"
        and context.projection_role == "positional"
        and context.positional_index == 1
        and context.physical_access_kind is None
    ):
        try:
            expression = cst.parse_expression(anchor.normalized_expression)
        except cst.ParserSyntaxError:
            expression = None
        if (
            isinstance(expression, cst.Call)
            and isinstance(expression.func, cst.Name)
            and expression.func.value == "cast"
            and len(expression.args) == 2
            and not expression.args[1].star
            and expression.args[1].keyword is None
            and _normalized_node(expression.args[1].value) == context.projection_expression
        ):
            return "projection_cast", "typing.cast"
    if site.domain == "test_fixture" and site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING:
        try:
            statement = cst.parse_statement(f"{site.normalized_expression}\n")
        except cst.ParserSyntaxError:
            statement = None
        if isinstance(statement, cst.SimpleStatementLine) and len(statement.body) == 1:
            assignment = statement.body[0]
            if (
                isinstance(assignment, cst.Assign)
                and len(assignment.targets) == 1
                and isinstance(assignment.targets[0].target, cst.Name)
            ):
                receiver = assignment.targets[0].target.value
                call = assignment.value
                helpers: list[str] = []
                while isinstance(call, cst.Call) and isinstance(call.func, cst.Name):
                    helper = call.func.value.lstrip("_")
                    if helper.startswith("fixture_"):
                        helper = helper.removeprefix("fixture_")
                    if helper not in _FIXTURE_MUTATION_HELPERS or not call.args:
                        break
                    helpers.append(helper)
                    call = call.args[0].value
                if helpers and isinstance(call, cst.Name) and call.value == receiver:
                    return (
                        "fixture_mutation_helper",
                        f"tests.unit.graph_test_utils.{helpers[0]}",
                    )
    if (
        site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
        and site.parent_shape == "return"
        and site.operation_shape == "typed_pass_through"
    ):
        return "typed_projection_return", "collector"
    if (
        site.diagnostic_code is DiagnosticCode.UNSUPPORTED_COMPARISON
        and context is None
        and site.operation_shape == "comparison"
    ):
        return "handled_projection_comparison", "collector"
    if (
        site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
        and context is not None
        and context.receiver_type_origin
        in {
            "orchestrator.graph.GraphProjection",
            "orchestrator.graph._commands.GraphProjection",
            "orchestrator.graph.projections.GraphProjection",
        }
    ):
        return "typed_projection_binding", context.receiver_type_origin
    if (
        site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
        and context is not None
        and _is_projection_factory(context.callee_origin)
    ):
        return "typed_projector_binding", context.callee_origin
    if (
        context is not None
        and _is_projection_factory(context.callee_origin)
        and context.projection_role == "receiver"
    ):
        return "typed_projector_binding", context.callee_origin
    if (
        context is not None
        and context.receiver_type_origin is not None
        and context.projection_role == "keyword"
        and context.keyword_name is not None
        and context.physical_access_kind is None
    ):
        return "typed_projection_field_constructor", context.receiver_type_origin
    if (
        site.domain == "test_fixture"
        and context is not None
        and context.physical_access_kind is None
        and context.projection_role == "keyword"
        and context.keyword_name in {"projection", "graph_projection"}
    ):
        return "fixture_projection_keyword", context.callee_origin or "collector"
    if (
        site.domain == "test_fixture"
        and context is not None
        and context.physical_access_kind is None
        and context.projection_role == "positional"
        and context.positional_index is not None
    ):
        return "fixture_projection_argument", context.callee_origin or "collector"
    if context is not None and context.physical_access_kind is not None:
        return None
    if (
        context is not None
        and context.callee_origin in _DERIVED_VALUE_SINKS
        and context.projection_role == "derived_value"
    ):
        return "derived_value_sink", context.callee_origin
    if (
        site.domain == "test_fixture"
        and context is not None
        and context.physical_access_kind is None
        and context.callee_origin is not None
        and context.callee_origin.startswith("orchestrator.graph.")
        and (
            context.projection_role == "positional"
            and context.positional_index == 0
            or context.projection_role == "keyword"
            and context.keyword_name == "projection"
        )
    ):
        return "fixture_public_graph_call", context.callee_origin
    if (
        context is not None
        and context.callee_origin in _PUBLIC_PROJECTION_CALLS
        and (
            context.projection_role == "keyword"
            and context.keyword_name == "projection"
            or context.projection_role == "positional"
            and context.positional_index
            in _PUBLIC_PROJECTION_ARGUMENT_POSITIONS.get(context.callee_origin, frozenset({0}))
        )
    ):
        return "public_graph_call", context.callee_origin
    if context is not None and _is_projection_factory(context.callee_origin):
        return "projector_fixture_flow", context.callee_origin
    return None


def _generated_fixture_rule(site: MigrationSite) -> GeneratedFixtureOperation | None:
    """Recognize only the approved physical mutation families from anchor facts."""
    context = site.anchor.context
    if (
        site.domain != "test_fixture"
        or context is None
        or context.projection_role != "receiver"
        or context.physical_access_kind is None
        or context.physical_old_field_name is None
        or context.physical_operation_shape is None
    ):
        return None
    facts = (
        ("access_kind", context.physical_access_kind.value),
        ("field", context.physical_old_field_name),
        ("operation_shape", context.physical_operation_shape),
        ("parent_shape", site.parent_shape),
    )
    rule_id: str | None = None
    if (
        context.physical_access_kind is AccessKind.NESTED_ASSIGNMENT
        and site.operation_shape == "assignment"
    ):
        rule_id = "physical_nested_assignment"
    elif context.physical_access_kind in {
        AccessKind.DIRECT_ASSIGNMENT,
        AccessKind.LITERAL_SUBSCRIPT_READ,
    } and site.operation_shape in {
        "assignment",
        "update",
        "literal_field_update",
        "literal_field_mutation",
    }:
        rule_id = "literal_field_update_mutation"
    elif context.physical_access_kind is AccessKind.APPEND_EXTEND and site.operation_shape in {
        "append",
        "extend",
        "append_extend",
        "call",
    }:
        rule_id = "physical_append_extend"
    if rule_id is None:
        return None
    return GeneratedFixtureOperation(
        site_id=site.original_site_id,
        rule_id=rule_id,
        shape_key=site.shape_key,
        evidence=facts,
    )


def _generated_query_rule(site: MigrationSite) -> StructuralQueryRuleOperation | None:
    """Recognize one pending physical read without consuming its neutral outer flow."""
    context = site.anchor.context
    if (
        context is None
        or context.projection_role != "receiver"
        or context.physical_old_field_name is None
        or context.physical_access_kind not in {AccessKind.GET, AccessKind.LITERAL_SUBSCRIPT_READ}
        or context.physical_operation_shape != context.physical_access_kind.value
        or site.parent_shape in {"assignment", "assignment_target", "deletion", "mutation"}
        or site.operation_shape
        in {
            "append",
            "append_extend",
            "assignment",
            "extend",
            "literal_field_mutation",
            "literal_field_update",
        }
        or (site.operation_shape == "update" and site.origin != "diagnostic")
    ):
        return None
    rule_id = f"physical_{context.physical_access_kind.value}"
    return StructuralQueryRuleOperation(
        site_id=site.original_site_id,
        rule_id=rule_id,
        shape_key=site.shape_key,
        effective_old_field=context.physical_old_field_name,
        access_kind=context.physical_access_kind.value,
        operation_shape=context.physical_operation_shape,
        evidence=(
            ("access_kind", context.physical_access_kind.value),
            ("field", context.physical_old_field_name),
            ("operation_shape", context.physical_operation_shape),
            ("parent_shape", site.parent_shape),
        ),
    )


def _approved_core_rule(site: MigrationSite) -> bool:
    """Prove a reviewed core site is one allowlisted physical projection read."""
    context = site.anchor.context
    return (
        site.relative_path in _APPROVED_CORE_PATHS
        and context is not None
        and context.projection_role == "receiver"
        and context.receiver_type_origin in _GRAPH_PROJECTION_ORIGINS
        and context.physical_access_kind is not None
        and context.physical_operation_shape == context.physical_access_kind.value
        and context.physical_operation_shape in _APPROVED_CORE_READ_SHAPES
        and site.parent_shape not in {"assignment", "deletion", "mutation"}
    )


def plan_structural_dispositions(
    stream: OperationStream, manifest: QueryMigrationManifest
) -> DispositionPlan:
    """Close unchanged dispositions through imported-origin and CST argument evidence."""
    initial = plan_reviewed_dispositions(stream, manifest)
    by_id = {site.original_site_id: site for site in stream.sites}
    physical_occurrence_evidence = {
        (
            site.relative_path,
            site.qualified_function,
            context.physical_old_field_name,
            context.physical_access_kind,
            context.physical_operation_shape,
            expression,
            line,
        )
        for site in stream.sites
        if site.origin == "occurrence"
        and (context := site.anchor.context) is not None
        and context.physical_access_kind is not None
        for expression, line in {
            (site.normalized_expression, None),
            (context.projection_expression, site.locator.line),
        }
    }
    operations: list[PlannedOperation] = []
    rule_operations: list[StructuralRuleOperation] = []
    generated_query_operations: list[StructuralQueryRuleOperation] = []
    generated_fixture_operations: list[GeneratedFixtureOperation] = []

    for operation in initial.operations:
        site_id = operation.consumed_site_ids[0]
        site = by_id[site_id]
        if operation.disposition == "approved_core":
            if not _approved_core_rule(site):
                raise AnchorRefusedError(
                    "approved core is not an allowlisted physical storage operation"
                )
            operations.append(operation)
            continue
        if operation.disposition != "projection_neutral":
            operations.append(operation)
            continue
        rule = _neutral_rule(site)
        if rule is None:
            raise AnchorRefusedError(
                f"reviewed projection-neutral site has no structural rule: {site_id}"
            )
        family, origin = rule
        operations.append(operation.model_copy(update={"reason": f"structural:{family}:{origin}"}))
        rule_operations.append(
            StructuralRuleOperation(
                site_id=site_id, rule_id=family, origin=origin, shape_key=site.shape_key
            )
        )

    structural_site_ids = tuple(
        sorted({*initial.reviewed_deferred_site_ids, *initial.pending_site_ids})
    )
    for site_id in structural_site_ids:
        site = by_id[site_id]
        if _approved_core_rule(site):
            operations.append(
                PlannedOperation(
                    disposition="approved_core",
                    reason="structural:approved_core_query",
                    consumed_site_ids=(site_id,),
                    shape_key=site.shape_key,
                )
            )
            continue
        fixture_operation = _generated_fixture_rule(site)
        if fixture_operation is not None:
            generated_fixture_operations.append(fixture_operation)
            continue
        context = site.anchor.context
        if (
            site.origin == "diagnostic"
            and context is not None
            and context.physical_access_kind is not None
            and (
                (
                    site.relative_path,
                    site.qualified_function,
                    context.physical_old_field_name,
                    context.physical_access_kind,
                    context.physical_operation_shape,
                    context.projection_expression,
                    None,
                )
                in physical_occurrence_evidence
                or (
                    site.relative_path,
                    site.qualified_function,
                    context.physical_old_field_name,
                    context.physical_access_kind,
                    context.physical_operation_shape,
                    context.projection_expression,
                    site.locator.line,
                )
                in physical_occurrence_evidence
            )
        ):
            operations.append(
                PlannedOperation(
                    disposition="projection_neutral",
                    reason="structural:physical_read_outer:collector",
                    consumed_site_ids=(site_id,),
                    shape_key=site.shape_key,
                )
            )
            rule_operations.append(
                StructuralRuleOperation(
                    site_id=site_id,
                    rule_id="physical_read_outer",
                    origin="collector",
                    shape_key=site.shape_key,
                )
            )
            continue
        query_operation = _generated_query_rule(site)
        if query_operation is not None:
            operations.append(
                PlannedOperation(
                    disposition="query_transform",
                    reason=f"structural:physical_query_read:{query_operation.rule_id}",
                    consumed_site_ids=(site_id,),
                    shape_key=site.shape_key,
                )
            )
            generated_query_operations.append(query_operation)
            continue
        if (
            site.origin == "diagnostic"
            and context is not None
            and context.physical_access_kind is not None
        ):
            operations.append(
                PlannedOperation(
                    disposition="projection_neutral",
                    reason="structural:handled_physical_diagnostic:collector",
                    consumed_site_ids=(site_id,),
                    shape_key=site.shape_key,
                )
            )
            rule_operations.append(
                StructuralRuleOperation(
                    site_id=site_id,
                    rule_id="handled_physical_diagnostic",
                    origin="collector",
                    shape_key=site.shape_key,
                )
            )
            continue
        rule = _neutral_rule(site)
        if rule is None:
            raise AnchorRefusedError(
                "pending site has no finite neutral or generated fixture rule: "
                f"{site_id}:{site.shape_key}"
            )
        family, origin = rule
        operations.append(
            PlannedOperation(
                disposition="projection_neutral",
                reason=f"structural:{family}:{origin}",
                consumed_site_ids=(site_id,),
                shape_key=site.shape_key,
            )
        )
        rule_operations.append(
            StructuralRuleOperation(
                site_id=site_id, rule_id=family, origin=origin, shape_key=site.shape_key
            )
        )

    operations.sort(key=lambda operation: operation.consumed_site_ids)
    generated_fixture_operations.sort(key=lambda item: item.site_id)
    generated_query_operations.sort(key=lambda item: item.site_id)
    disposition_counts = tuple(sorted(Counter(item.disposition for item in operations).items()))
    shape_group_counts = tuple(sorted(Counter(item.shape_key for item in operations).items()))
    rule_family_counts = tuple(sorted(Counter(item.rule_id for item in rule_operations).items()))
    symbol_origin_counts = tuple(sorted(Counter(item.origin for item in rule_operations).items()))
    generated_fixture_family_counts = tuple(
        sorted(Counter(item.rule_id for item in generated_fixture_operations).items())
    )
    generated_query_family_counts = tuple(
        sorted(Counter(item.rule_id for item in generated_query_operations).items())
    )
    if len(operations) + len(generated_fixture_operations) != len(stream.sites):
        raise AnchorRefusedError(
            "structural disposition partition does not match the approved counts"
        )
    return DispositionPlan(
        operations=tuple(operations),
        reviewed_deferred_site_ids=(),
        generated_fixture_operations=tuple(generated_fixture_operations),
        pending_site_ids=(),
        disposition_counts=disposition_counts,
        shape_group_counts=shape_group_counts,
        neutral_rule_operations=tuple(sorted(rule_operations, key=lambda item: item.site_id)),
        rule_family_counts=rule_family_counts,
        symbol_origin_counts=symbol_origin_counts,
        generated_fixture_family_counts=generated_fixture_family_counts,
        generated_query_operations=tuple(generated_query_operations),
        generated_query_family_counts=generated_query_family_counts,
    )


def _refuse_unknown_shape(node: cst.CSTNode) -> AnchorRefusedError:
    return AnchorRefusedError(f"unknown structural shape: {type(node).__name__}")


def _normalized_node(node: cst.CSTNode) -> str | None:
    try:
        return ast.unparse(ast.parse(cst.Module([]).code_for_node(node)))
    except SyntaxError:
        return None


def _qualified_functions(module: cst.Module) -> dict[int, str]:
    names: dict[int, str] = {}

    class Visitor(cst.CSTVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def on_visit(self, node: cst.CSTNode) -> bool:
            names[id(node)] = ".".join(self.stack) or "<module>"
            if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
                self.stack.append(node.name.value)
            return True

        def on_leave(self, original_node: cst.CSTNode) -> None:
            if isinstance(original_node, (cst.FunctionDef, cst.ClassDef)):
                self.stack.pop()

    module.visit(Visitor())
    return names


def _transparent_parent(node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]) -> cst.CSTNode:
    parent = parents[node]
    while isinstance(parent, (cst.Expr, cst.SimpleStatementLine, cst.ParenthesizedWhitespace)):
        parent = parents[parent]
    return parent


def _report_context(
    node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode], module: cst.Module
) -> str | None:
    """Return the enclosing statement header or simple statement for report rendering."""
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, cst.SimpleStatementLine):
            return module.code_for_node(current).strip()
        if isinstance(current, cst.If):
            return f"if {module.code_for_node(current.test).strip()}:"
        if isinstance(current, cst.For):
            asynchronous = "async " if current.asynchronous is not None else ""
            target = module.code_for_node(current.target).strip()
            iterable = module.code_for_node(current.iter).strip()
            return f"{asynchronous}for {target} in {iterable}:"
        if isinstance(current, cst.While):
            return f"while {module.code_for_node(current.test).strip()}:"
        if isinstance(current, cst.With):
            asynchronous = "async " if current.asynchronous is not None else ""
            items = ", ".join(module.code_for_node(item).strip() for item in current.items)
            return f"{asynchronous}with {items}:"
    return None


def _parent_shape(node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]) -> str:
    if isinstance(node, cst.Del):
        return "deletion"
    parent = parents[node]
    if isinstance(parent, (cst.Expr, cst.SimpleStatementLine)):
        return "bare_expression"
    parent = _transparent_parent(node, parents)
    if isinstance(parent, cst.Return):
        return "return"
    if isinstance(parent, cst.AssignTarget):
        return "assignment_target"
    if isinstance(parent, (cst.Assign, cst.AnnAssign, cst.AugAssign)):
        return "assignment_value"
    if isinstance(parent, cst.Del):
        return "deletion"
    if isinstance(parent, (cst.For, cst.CompFor)):
        return "iterable"
    if isinstance(parent, (cst.If, cst.While, cst.Assert, cst.CompIf)):
        return "condition"
    if isinstance(parent, (cst.Comparison, cst.ComparisonTarget)):
        return "comparison_membership"
    if isinstance(parent, cst.Arg):
        return "call_argument"
    if isinstance(parent, cst.Call):
        return "call_receiver"
    if isinstance(parent, cst.Attribute):
        return "attribute_receiver"
    if isinstance(parent, cst.Subscript):
        return "nested_receiver"
    if isinstance(parent, (cst.DictElement, cst.DictComp)):
        return "dict_element"
    if isinstance(parent, cst.Annotation):
        return "annotation"
    if isinstance(parent, cst.Parameters):
        return "typed_parameter"
    if isinstance(parent, (cst.BooleanOperation, cst.IfExp, cst.UnaryOperation)):
        return "boolean_expression"
    if isinstance(parent, (cst.Tuple, cst.List, cst.Set, cst.Element)):
        return "collection_element"
    if isinstance(parent, (cst.Await, cst.Yield)):
        return "yield_await"
    raise _refuse_unknown_shape(parent)


def _operation_shape(node: cst.CSTNode, access_kind: AccessKind | None) -> str:
    if access_kind is not None:
        if access_kind is AccessKind.MEMBERSHIP:
            return "membership"
        if access_kind in {AccessKind.ITEMS, AccessKind.VALUES, AccessKind.KEYS}:
            return f"{access_kind.value}_iteration"
        if access_kind in {AccessKind.DIRECT_ASSIGNMENT, AccessKind.NESTED_ASSIGNMENT}:
            return "assignment"
        if access_kind is AccessKind.APPEND_EXTEND:
            return "append_extend"
        if access_kind is AccessKind.DELETE_POP:
            return "deletion"
        if access_kind is AccessKind.FIXTURE_CONSTRUCTION:
            return "fixture_construction"
        if access_kind is AccessKind.UNTYPED_ESCAPE:
            return "typed_pass_through"
        if access_kind is AccessKind.GET:
            return "map_get"
        if access_kind is AccessKind.LITERAL_SUBSCRIPT_READ:
            return "subscript_read"
        return access_kind.value
    if isinstance(node, cst.Call):
        return "call"
    if isinstance(node, cst.Comparison):
        return "comparison"
    raise _refuse_unknown_shape(node)


def _diagnostic_operation_shape(node: cst.CSTNode, code: DiagnosticCode) -> str:
    if isinstance(node, cst.Call):
        if isinstance(node.func, cst.Attribute):
            if node.func.attr.value == "get" and isinstance(node.func.value, cst.Subscript):
                return "nested_get"
            if node.func.attr.value in {
                "items",
                "values",
                "keys",
                "update",
                "append",
                "extend",
                "pop",
                "setdefault",
            }:
                return node.func.attr.value
        return "call"
    if isinstance(node, cst.Comparison):
        return "comparison"
    if isinstance(node, cst.Del):
        return "deletion"
    if isinstance(node, cst.Subscript):
        return "subscript"
    if isinstance(
        node,
        (cst.Param, cst.Name, cst.Tuple, cst.AnnAssign, cst.Assign, cst.FunctionDef, cst.Return),
    ):
        return "typed_pass_through"
    raise AnchorRefusedError(f"unknown diagnostic operation: {code.value}:{type(node).__name__}")


def _node_candidates(
    module: cst.Module,
) -> tuple[
    dict[tuple[str, str], list[cst.CSTNode]],
    dict[cst.CSTNode, cst.CSTNode],
    dict[cst.CSTNode, object],
    dict[int, str],
    dict[cst.CSTNode, object],
]:
    wrapper = MetadataWrapper(module)
    metadata = wrapper.resolve_many((ParentNodeProvider, PositionProvider))
    parents = metadata[ParentNodeProvider]
    positions = metadata[PositionProvider]
    qualified = _qualified_functions(wrapper.module)
    candidates: dict[tuple[str, str], list[cst.CSTNode]] = defaultdict(list)

    class Visitor(cst.CSTVisitor):
        def on_visit(self, node: cst.CSTNode) -> bool:
            if not isinstance(node, (cst.BaseExpression, cst.Del)):
                return True
            expression = _normalized_node(node)
            if expression is not None:
                candidates[(qualified[id(node)], expression)].append(node)
            return True

    wrapper.visit(Visitor())
    for nodes in candidates.values():
        nodes.sort(key=lambda node: (positions[node].start.line, positions[node].start.column))
    return (
        candidates,
        parents,
        positions,
        qualified,
        wrapper.resolve(QualifiedNameProvider),
    )


def _source_map(sources: Iterable[SourceSnapshot]) -> dict[str, SourceSnapshot]:
    snapshots = tuple(sources)
    result = {source.relative_path: source for source in snapshots}
    if len(result) != len(snapshots):
        raise AnchorRefusedError("source snapshots contain duplicate paths")
    return result


def _expected_digest_map(inventory: AccessInventory) -> dict[str, str]:
    return {item.relative_path: item.digest for item in inventory.source_digests}


def _skeleton_sites(skeleton: QueryMigrationManifest) -> dict[str, object]:
    return {site.site_key: site for site in (*skeleton.dispositions, *skeleton.unclassified_sites)}


def _matches_access_kind(
    node: cst.CSTNode,
    kind: AccessKind,
    parents: dict[cst.CSTNode, cst.CSTNode],
) -> bool:
    signature = _physical_signature(node, parents)
    if signature is not None:
        return signature[2] is kind
    parent = parents[node]
    if kind is AccessKind.DIRECT_ITERATION:
        return isinstance(parent, (cst.For, cst.CompFor))
    if kind in {AccessKind.FIXTURE_CONSTRUCTION, AccessKind.UNPACK_CAST}:
        return isinstance(node, cst.Call)
    if kind is AccessKind.UNTYPED_ESCAPE:
        return isinstance(node, cst.BaseExpression)
    return False


def _scope_lines(
    module: cst.Module,
    positions: dict[cst.CSTNode, object],
    qualified: dict[int, str],
) -> dict[int, str]:
    ranges = [
        (
            position.start.line,
            position.end.line,
            ".".join(part for part in (qualified[id(node)], node.name.value) if part != "<module>")
            or node.name.value,
        )
        for node, position in positions.items()
        if isinstance(node, cst.FunctionDef)
    ]
    return {
        line: max(
            (item for item in ranges if item[0] <= line <= item[1]),
            key=lambda item: item[0],
            default=(0, 0, "<module>"),
        )[2]
        for line in range(1, len(module.code.splitlines()) + 1)
    }


def _matching_occurrence_nodes(
    *,
    candidates: dict[tuple[str, str], list[cst.CSTNode]],
    parents: dict[cst.CSTNode, cst.CSTNode],
    qualified_function: str,
    normalized_expression: str,
    access_kinds: tuple[AccessKind, ...],
) -> tuple[cst.CSTNode, ...]:
    """Return the exact candidate set used by every occurrence anchor consumer."""

    def inside_comparison(node: cst.CSTNode) -> bool:
        current = node
        while (parent := parents.get(current)) is not None:
            if isinstance(parent, cst.Comparison):
                return True
            if isinstance(parent, cst.BaseStatement):
                return False
            current = parent
        return False

    nodes = tuple(
        node
        for node in candidates.get((qualified_function, normalized_expression), ())
        if any(_matches_access_kind(node, kind, parents) for kind in access_kinds)
    )
    if len(nodes) > len(access_kinds):
        nodes = tuple(node for node in nodes if not inside_comparison(node))
    if not access_kinds or len(nodes) != len(access_kinds):
        raise AnchorRefusedError(
            "ambiguous occurrence anchor: "
            f"{qualified_function}:{normalized_expression}:"
            f"expected={len(access_kinds)}:matched={len(nodes)}"
        )
    return nodes


def _matching_diagnostic_nodes(
    *,
    source: str,
    module: cst.Module,
    positions: dict[cst.CSTNode, object],
    scope_lines: dict[int, str],
    qualified_function: str,
    code: DiagnosticCode,
    normalized_source_pattern: str,
    signatures: tuple[tuple[str, str], ...],
) -> tuple[cst.CSTNode, ...]:
    """Return the exact candidate set used by every diagnostic anchor consumer."""
    matching_lines = {
        index + 1
        for index, line in enumerate(source.splitlines())
        if " ".join(line.strip().split()) == normalized_source_pattern
        and scope_lines.get(index + 1) == qualified_function
    }
    signature_counts = Counter(signatures)
    nodes_by_signature: dict[tuple[str, str], tuple[cst.CSTNode, ...]] = {}
    for signature, expected_count in signature_counts.items():
        nodes = tuple(
            node
            for node, position in positions.items()
            if position.start.line in matching_lines
            and type(node).__name__ == signature[0]
            and (_normalized_node(node) or module.code_for_node(node).strip()) == signature[1]
        )
        if len(nodes) != expected_count:
            raise AnchorRefusedError(f"ambiguous {code.value} diagnostic anchor")
        nodes_by_signature[signature] = nodes
    return tuple(
        sorted(
            (candidate for values in nodes_by_signature.values() for candidate in values),
            key=lambda candidate: (
                positions[candidate].start.line,
                positions[candidate].start.column,
                type(candidate).__name__,
            ),
        )
    )


def _diagnostic_node(
    nodes: list[cst.CSTNode], source_node_type: str, normalized_cst_expression: str
) -> cst.CSTNode:
    matching = [
        node
        for node in nodes
        if type(node).__name__ == source_node_type
        and (_normalized_node(node) or cst.Module([]).code_for_node(node).strip())
        == normalized_cst_expression
    ]
    if len(matching) != 1:
        raise AnchorRefusedError("ambiguous diagnostic CST anchor")
    return matching[0]


def _anchor_evidence(
    node: cst.CSTNode,
    *,
    normalized_expression: str,
    ordinal: int,
    stored_context: ProjectionCallContext | None,
    qualified_names: dict[cst.CSTNode, object],
    parents: dict[cst.CSTNode, cst.CSTNode],
    expected_access_kind: AccessKind | None = None,
) -> CstAnchorEvidence:
    return CstAnchorEvidence(
        node_type=type(node).__name__,
        normalized_expression=normalized_expression,
        same_expression_ordinal=ordinal,
        context=_reanchor_context(
            node, stored_context, qualified_names, parents, expected_access_kind
        ),
    )


def compile_operation_stream(
    sources: Iterable[SourceSnapshot],
    inventory: AccessInventory,
    skeleton: QueryMigrationManifest,
) -> OperationStream:
    """Anchor every authoritative occurrence and diagnostic exactly once in source snapshots."""
    if skeleton.baseline_revision != inventory.baseline_revision:
        raise AnchorRefusedError("inventory and skeleton baseline revisions differ")
    snapshots = _source_map(sources)
    expected_digests = _expected_digest_map(inventory)
    if not expected_digests:
        raise AnchorRefusedError("inventory has no source digests")
    for relative_path, expected_digest in expected_digests.items():
        source = snapshots.get(relative_path)
        if source is None:
            raise AnchorRefusedError(f"missing source snapshot: {relative_path}")
        if source_digest(source.source) != expected_digest:
            raise AnchorRefusedError(f"digest mismatch: {relative_path}")

    skeleton_by_id = _skeleton_sites(skeleton)
    diagnostics_by_path: dict[str, list[object]] = defaultdict(list)
    diagnostics_by_path_raw: dict[str, list[object]] = defaultdict(list)
    for diagnostic in inventory.diagnostics:
        diagnostics_by_path_raw[diagnostic.relative_path].append(diagnostic)
    for relative_path, diagnostics in diagnostics_by_path_raw.items():
        diagnostics_by_path[relative_path].extend(diagnostics)

    sites: list[MigrationSite] = []
    occurrences_by_path: dict[str, list[object]] = defaultdict(list)
    for occurrence in inventory.occurrences:
        occurrences_by_path[occurrence.relative_path].append(occurrence)
    for relative_path in sorted({*occurrences_by_path, *diagnostics_by_path}):
        snapshot = snapshots.get(relative_path)
        if snapshot is None:
            raise AnchorRefusedError(f"missing source snapshot: {relative_path}")
        module = cst.parse_module(snapshot.source)
        candidates, parents, positions, qualified, qualified_names = _node_candidates(module)
        scope_lines = _scope_lines(module, positions, qualified)
        for occurrence in occurrences_by_path[relative_path]:
            matching_occurrences = tuple(
                item
                for item in occurrences_by_path[relative_path]
                if item.qualified_function == occurrence.qualified_function
                and item.normalized_expression == occurrence.normalized_expression
            )
            nodes = _matching_occurrence_nodes(
                candidates=candidates,
                parents=parents,
                qualified_function=occurrence.qualified_function,
                normalized_expression=occurrence.normalized_expression,
                access_kinds=tuple(item.kind for item in matching_occurrences),
            )
            identities = {
                occurrence_id(
                    inventory.baseline_revision,
                    relative_path,
                    occurrence.qualified_function,
                    occurrence.normalized_expression,
                    ordinal,
                ): node
                for ordinal, node in enumerate(nodes)
            }
            if occurrence.occurrence_id not in identities:
                raise AnchorRefusedError(f"identity mismatch: {occurrence.occurrence_id}")
            node = identities[occurrence.occurrence_id]
            skeleton_site = skeleton_by_id.get(occurrence.occurrence_id)
            if skeleton_site is None or skeleton_site.site_key != occurrence.occurrence_id:
                raise AnchorRefusedError(
                    f"missing occurrence skeleton identity: {occurrence.occurrence_id}"
                )
            position = positions[node].start
            if _normalized_node(node) != occurrence.normalized_expression:
                raise AnchorRefusedError(f"identity mismatch: {occurrence.occurrence_id}")
            sites.append(
                MigrationSite(
                    origin="occurrence",
                    original_site_id=occurrence.occurrence_id,
                    relative_path=relative_path,
                    qualified_function=occurrence.qualified_function,
                    access_kind=occurrence.kind,
                    old_field_name=occurrence.old_field_name,
                    diagnostic_code=None,
                    normalized_expression=occurrence.normalized_expression,
                    report_context=_report_context(node, parents, module),
                    domain=skeleton_site.domain,
                    ordinal=next(
                        ordinal for ordinal, candidate in enumerate(nodes) if candidate is node
                    ),
                    source_digest=source_digest(snapshot.source),
                    locator=SourceLocator(line=position.line, column=position.column),
                    anchor=_anchor_evidence(
                        node,
                        normalized_expression=occurrence.normalized_expression,
                        ordinal=next(
                            ordinal for ordinal, candidate in enumerate(nodes) if candidate is node
                        ),
                        stored_context=occurrence.context,
                        qualified_names=qualified_names,
                        parents=parents,
                        expected_access_kind=occurrence.kind,
                    ),
                    parent_shape=_parent_shape(node, parents),
                    operation_shape=_operation_shape(node, occurrence.kind),
                )
            )
        for diagnostic in diagnostics_by_path[relative_path]:
            pattern = diagnostic.normalized_source_pattern
            group = [
                item
                for item in diagnostics_by_path[relative_path]
                if item.qualified_function == diagnostic.qualified_function
                and item.code is diagnostic.code
                and item.normalized_source_pattern == pattern
            ]
            signature = (diagnostic.source_node_type, diagnostic.normalized_cst_expression)
            all_nodes = _matching_diagnostic_nodes(
                source=snapshot.source,
                module=module,
                positions=positions,
                scope_lines=scope_lines,
                qualified_function=diagnostic.qualified_function,
                code=diagnostic.code,
                normalized_source_pattern=pattern,
                signatures=tuple(
                    (item.source_node_type, item.normalized_cst_expression) for item in group
                ),
            )
            if diagnostic.same_pattern_ordinal >= len(all_nodes):
                raise AnchorRefusedError("missing diagnostic CST anchor")
            ordinal = diagnostic.same_pattern_ordinal
            node = all_nodes[ordinal]
            if (
                type(node).__name__ != signature[0]
                or (_normalized_node(node) or cst.Module([]).code_for_node(node).strip())
                != signature[1]
            ):
                raise AnchorRefusedError("diagnostic identity mismatch")
            diagnostic_key = disposition_site_key(
                baseline_revision=inventory.baseline_revision,
                relative_path=relative_path,
                qualified_function=diagnostic.qualified_function,
                normalized_source_pattern=pattern,
                diagnostic_code=diagnostic.code,
                same_pattern_ordinal=ordinal,
            )
            skeleton_site = skeleton_by_id.get(diagnostic_key)
            if skeleton_site is None or skeleton_site.site_key != diagnostic_key:
                raise AnchorRefusedError("missing diagnostic skeleton identity")
            line = positions[node].start.line
            nodes = [node]
            if len(nodes) != 1:
                raise AnchorRefusedError("ambiguous diagnostic CST anchor")
            node = _diagnostic_node(
                nodes, diagnostic.source_node_type, diagnostic.normalized_cst_expression
            )
            sites.append(
                MigrationSite(
                    origin="diagnostic",
                    original_site_id=diagnostic_key,
                    relative_path=relative_path,
                    qualified_function=diagnostic.qualified_function,
                    access_kind=None,
                    old_field_name=None,
                    diagnostic_code=diagnostic.code,
                    normalized_expression=pattern,
                    report_context=_report_context(node, parents, module),
                    domain=skeleton_site.domain,
                    ordinal=ordinal,
                    source_digest=source_digest(snapshot.source),
                    locator=SourceLocator(line=line, column=diagnostic.column),
                    anchor=_anchor_evidence(
                        node,
                        normalized_expression=(
                            _normalized_node(node) or cst.Module([]).code_for_node(node).strip()
                        ),
                        ordinal=ordinal,
                        stored_context=diagnostic.context,
                        qualified_names=qualified_names,
                        parents=parents,
                    ),
                    parent_shape=_parent_shape(node, parents),
                    operation_shape=_diagnostic_operation_shape(node, diagnostic.code),
                )
            )
    expected_ids = {item.occurrence_id for item in inventory.occurrences} | {
        item.site_key for item in skeleton_by_id.values() if item.diagnostic_code is not None
    }
    actual_ids = {site.original_site_id for site in sites}
    if actual_ids != expected_ids or len(sites) != len(expected_ids):
        raise AnchorRefusedError(
            "operation stream does not adapt every inventory site exactly once"
        )
    result = OperationStream(
        sites=tuple(
            sorted(
                sites,
                key=lambda site: (
                    site.relative_path,
                    site.locator.line,
                    site.locator.column,
                    site.original_site_id,
                ),
            )
        )
    )
    return result


def _compile_current_operation_stream_path(
    input: tuple[SourceSnapshot, AccessInventory],
) -> tuple[MigrationSite, ...]:
    """Compile one current source's exact stream in an isolated worker."""
    snapshot, inventory = input
    return compile_operation_stream(
        (snapshot,), inventory, query_migration_skeleton(inventory)
    ).sites


def compile_current_operation_stream(
    sources: Iterable[SourceSnapshot], inventory: AccessInventory
) -> OperationStream:
    """Anchor current closure sites independently without changing their evidence."""
    snapshots = {source.relative_path: source for source in sources}
    source_digests = {item.relative_path: item for item in inventory.source_digests}
    grouped_occurrences: dict[str, list[object]] = defaultdict(list)
    grouped_diagnostics: dict[str, list[object]] = defaultdict(list)
    for occurrence in inventory.occurrences:
        grouped_occurrences[occurrence.relative_path].append(occurrence)
    for diagnostic in inventory.diagnostics:
        grouped_diagnostics[diagnostic.relative_path].append(diagnostic)
    inputs: list[tuple[SourceSnapshot, AccessInventory]] = []
    for relative_path in sorted({*grouped_occurrences, *grouped_diagnostics}):
        snapshot = snapshots.get(relative_path)
        digest = source_digests.get(relative_path)
        if snapshot is None or digest is None:
            raise AnchorRefusedError(f"missing current source snapshot: {relative_path}")
        inputs.append(
            (
                snapshot,
                AccessInventory(
                    baseline_revision=inventory.baseline_revision,
                    occurrences=tuple(grouped_occurrences[relative_path]),
                    diagnostics=tuple(grouped_diagnostics[relative_path]),
                    source_digests=(digest,),
                ),
            )
        )
    if len(inputs) < 4:
        streams = tuple(map(_compile_current_operation_stream_path, inputs))
    else:
        worker_count = min(8, len(inputs), os.cpu_count() or 1)
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            streams = tuple(executor.map(_compile_current_operation_stream_path, inputs))
    return OperationStream(
        sites=tuple(
            sorted(
                (site for stream in streams for site in stream),
                key=lambda site: (
                    site.relative_path,
                    site.locator.line,
                    site.locator.column,
                    site.original_site_id,
                ),
            )
        )
    )


def shape_summary(stream: OperationStream) -> dict[str, int]:
    """Return deterministic structural grouping counts without site or source policy."""
    return dict(sorted(Counter(site.shape_key for site in stream.sites).items()))


def _git_environment() -> dict[str, str]:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}


def load_git_python_sources(root: Path, revision: str) -> tuple[SourceSnapshot, ...]:
    """Load tracked Python sources from one git tree without checking it out."""
    try:
        result = subprocess.run(
            (
                "git",
                "-c",
                "core.pager=cat",
                "-c",
                "core.quotepath=false",
                "-C",
                str(root),
                "archive",
                "--format=tar",
                revision,
            ),
            check=True,
            capture_output=True,
            env=_git_environment(),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.decode(errors="replace").strip()
            if isinstance(error, subprocess.CalledProcessError) and error.stderr
            else str(error)
        )
        raise AnchorRefusedError(f"cannot load baseline git tree {revision}: {detail}") from error
    sources: list[SourceSnapshot] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
            for member in sorted(archive.getmembers(), key=lambda item: item.name):
                path = Path(member.name)
                if not member.isfile() or path.suffix != ".py":
                    continue
                if path.parts[:1] not in {("src",), ("tests",), ("scripts",)}:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise AnchorRefusedError(
                        f"baseline git archive omitted bytes for {member.name}"
                    )
                sources.append(
                    SourceSnapshot(
                        relative_path=path.as_posix(),
                        source=extracted.read().decode("utf-8"),
                    )
                )
    except (tarfile.TarError, UnicodeDecodeError) as error:
        raise AnchorRefusedError(f"cannot decode baseline git tree {revision}") from error
    return tuple(sources)


def load_current_python_sources(root: Path) -> tuple[SourceSnapshot, ...]:
    """Load the current bytes for tracked Python sources in migration scope."""
    try:
        paths = subprocess.run(
            (
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--",
                "src/*.py",
                "tests/*.py",
                "scripts/*.py",
            ),
            check=True,
            capture_output=True,
            env=_git_environment(),
        ).stdout.split(b"\0")
    except (OSError, subprocess.CalledProcessError) as error:
        raise AnchorRefusedError("cannot list current tracked Python sources") from error
    sources: list[SourceSnapshot] = []
    for raw_path in paths:
        if not raw_path:
            continue
        try:
            relative_path = raw_path.decode("utf-8")
            source = (root / relative_path).read_text()
        except (OSError, UnicodeDecodeError) as error:
            raise AnchorRefusedError("cannot load current tracked Python sources") from error
        sources.append(SourceSnapshot(relative_path=relative_path, source=source))
    return tuple(sorted(sources, key=lambda item: item.relative_path))


def _empty_query_ledger(revision: str) -> QueryMigrationManifest:
    return QueryMigrationManifest(
        baseline_revision=revision,
        dispositions=(),
        unclassified_sites=(),
    )


def _report_after_form(
    site: MigrationSite,
    replacement: str | None,
    *,
    original_outer_expression: str | None = None,
) -> str:
    """Preserve the anchored statement context around a transformed expression."""
    if replacement is None:
        return site.report_context or site.normalized_expression
    anchor = (
        _normalized_node(cst.parse_expression(original_outer_expression))
        if original_outer_expression is not None
        else site.anchor.normalized_expression
    )
    if anchor is None:
        raise AnchorRefusedError(
            f"report replacement outer expression is not normalizable: {site.original_site_id}"
        )
    normalized_context = site.report_context or site.normalized_expression
    if re.match(
        r"^(for|if|while|with|try|except|elif|else|finally)\b", normalized_context
    ) and not (normalized_context.rstrip().endswith(":")):
        normalized_context += ":"
    body = textwrap.indent(normalized_context, "    ")
    placeholder = "__codemod_report_placeholder__"
    has_incomplete_compound = body.rstrip().endswith(":")
    if has_incomplete_compound:
        body = f"{body}\n        {placeholder}"
    try:
        module = cst.parse_module(f"def _report_context() -> None:\n{body}\n")
    except cst.ParserSyntaxError as error:
        raise AnchorRefusedError(
            f"report site has an unparseable normalized context: {site.original_site_id}"
        ) from error

    class ReplaceAnchor(cst.CSTTransformer):
        def __init__(self) -> None:
            self.matches = 0

        def on_leave(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> cst.CSTNode:
            if (
                isinstance(original_node, cst.BaseExpression)
                and _normalized_node(original_node) == anchor
            ):
                self.matches += 1
                return cst.parse_expression(replacement)
            return updated_node

    transformer = ReplaceAnchor()
    transformed = module.visit(transformer)
    if transformer.matches != 1:
        raise AnchorRefusedError(
            f"report site cannot uniquely replace anchored expression: {site.original_site_id}"
        )
    transformed_body = transformed.code.splitlines()[1:]
    if has_incomplete_compound:
        if transformed_body[-1].strip() != placeholder:
            raise AnchorRefusedError("report compound statement placeholder was not preserved")
        transformed_body.pop()
    return textwrap.dedent("\n".join(transformed_body)).strip()


def compile_query_migration_report(
    sources: Iterable[SourceSnapshot],
    manifest: ProjectionMigrationManifest,
    *,
    current_closure: CurrentTreeClosure | None = None,
) -> QueryMigrationReport:
    """Compile every baseline site to one deterministic structural report row."""
    snapshots = tuple(sources)
    inventory = inventory_sources(snapshots, manifest, require_declaration_facts=True)
    stream = compile_operation_stream(snapshots, inventory, query_migration_skeleton(inventory))
    disposition = plan_structural_dispositions(
        stream, _empty_query_ledger(manifest.baseline_revision)
    )
    composition = compile_query_composition_plan(snapshots, stream, disposition)
    replacements = compile_query_replacement_plan(snapshots, stream, disposition, composition)
    fixture_mutations = compile_fixture_mutation_plan(
        snapshots, stream, disposition.generated_fixture_operations
    )

    operations = {
        site_id: operation
        for operation in disposition.operations
        for site_id in operation.consumed_site_ids
    }
    neutral_rules = {item.site_id: item.rule_id for item in disposition.neutral_rule_operations}
    query_rules = {item.site_id: item.rule_id for item in disposition.generated_query_operations}
    query_recipes = {
        site_id: recipe for recipe in replacements.recipes for site_id in recipe.consumed_site_ids
    }
    query_recipes_by_outer = {
        (
            recipe.relative_path,
            recipe.source_span[0],
            _normalized_node(cst.parse_expression(recipe.original_outer_expression)),
        ): recipe
        for recipe in replacements.recipes
    }
    stream_by_id = {site.original_site_id: site for site in stream.sites}
    query_recipes_by_physical_context: dict[
        tuple[str, str, str | None, AccessKind | None, str | None],
        list[QueryReplacementRecipe],
    ] = defaultdict(list)
    for recipe in replacements.recipes:
        for consumed_id in recipe.consumed_site_ids:
            consumed_site = stream_by_id[consumed_id]
            context = consumed_site.anchor.context
            if context is None:
                continue
            key = (
                consumed_site.relative_path,
                consumed_site.qualified_function,
                context.physical_old_field_name,
                context.physical_access_kind,
                context.physical_operation_shape,
            )
            if recipe not in query_recipes_by_physical_context[key]:
                query_recipes_by_physical_context[key].append(recipe)
    fixture_recipes = {
        site_id: recipe
        for recipe in fixture_mutations.recipes
        for site_id in recipe.consumed_site_ids
    }
    rows: list[QueryMigrationReportSite] = []
    for site in stream.sites:
        site_id = site.original_site_id
        replacement: str | None = None
        original_outer_expression: str | None = None
        replacement_is_statement = False
        if site_id in fixture_recipes:
            recipe = fixture_recipes[site_id]
            report_disposition: Literal["transformed", "approved_core", "projection_neutral"] = (
                "transformed"
            )
            rule_id = recipe.rule_id
            replacement = recipe.replacement_statement
            replacement_is_statement = True
        else:
            operation = operations.get(site_id)
            if operation is None:
                raise AnchorRefusedError(f"baseline report has no disposition for {site_id}")
            if operation.disposition == "query_transform":
                recipe = query_recipes.get(site_id)
                rule_id = query_rules.get(site_id)
                if recipe is None or rule_id is None:
                    raise AnchorRefusedError(f"baseline query site has no exact recipe: {site_id}")
                report_disposition = "transformed"
                replacement = recipe.replacement_outer_expression
                original_outer_expression = recipe.original_outer_expression
            elif operation.disposition == "approved_core":
                report_disposition = "approved_core"
                rule_id = "approved_core"
            elif operation.disposition == "projection_neutral":
                rule_id = neutral_rules.get(site_id, "")
                if not rule_id:
                    raise AnchorRefusedError(f"baseline neutral site has no finite rule: {site_id}")
                if site.anchor.context is not None and site.anchor.context.physical_access_kind:
                    recipe = query_recipes_by_outer.get(
                        (
                            site.relative_path,
                            site.locator.line,
                            site.anchor.normalized_expression,
                        )
                    )
                    context = site.anchor.context
                    if recipe is None and context is not None:
                        candidates = [
                            candidate
                            for candidate in query_recipes_by_physical_context.get(
                                (
                                    site.relative_path,
                                    site.qualified_function,
                                    context.physical_old_field_name,
                                    context.physical_access_kind,
                                    context.physical_operation_shape,
                                ),
                                [],
                            )
                            if candidate.source_span[0]
                            <= site.locator.line
                            <= candidate.source_span[2]
                        ]
                        if len(candidates) > 1:
                            raise AnchorRefusedError(
                                "baseline physical diagnostic has ambiguous transformed outer recipe"
                            )
                        recipe = candidates[0] if candidates else None
                    if recipe is None:
                        raise AnchorRefusedError(
                            f"baseline physical diagnostic has no transformed outer recipe: {site_id}"
                        )
                    report_disposition = "transformed"
                    rule_id = "physical_wrapper:" + "+".join(recipe.rule_ids)
                    replacement = recipe.replacement_outer_expression
                    original_outer_expression = recipe.original_outer_expression
                else:
                    report_disposition = "projection_neutral"
            else:
                raise AnchorRefusedError(f"baseline report rejects disposition for {site_id}")
        rows.append(
            QueryMigrationReportSite(
                site_id=site_id,
                relative_path=site.relative_path,
                qualified_function=site.qualified_function,
                disposition=report_disposition,
                rule_id=rule_id,
                before_normalized_form=site.normalized_expression,
                replacement=replacement,
                after_form=(
                    replacement
                    if replacement_is_statement
                    else _report_after_form(
                        site,
                        replacement,
                        original_outer_expression=original_outer_expression,
                    )
                ),
            )
        )
    rows.sort(key=lambda item: item.site_id)
    return QueryMigrationReport(
        baseline_revision=manifest.baseline_revision,
        baseline_site_count=len(rows),
        disposition_counts=tuple(sorted(Counter(item.disposition for item in rows).items())),
        rule_counts=tuple(sorted(Counter(item.rule_id for item in rows).items())),
        sites=tuple(rows),
        current_closure=current_closure,
    )


def compile_current_tree_closure(
    sources: Iterable[SourceSnapshot], manifest: ProjectionMigrationManifest
) -> CurrentTreeClosure:
    """Prove that current tracked sources contain no generated migration work."""
    snapshots = tuple(sources)
    inventory = inventory_sources(snapshots, manifest, require_declaration_facts=True)
    stream = compile_current_operation_stream(snapshots, inventory)
    disposition = plan_structural_dispositions(
        stream, _empty_query_ledger(manifest.baseline_revision)
    )
    noncore_occurrences = tuple(
        occurrence.relative_path
        for occurrence in inventory.occurrences
        if occurrence.relative_path not in _APPROVED_CORE_PATHS
    )
    if noncore_occurrences:
        raise AnchorRefusedError(
            "current sources still require migration: "
            f"physical occurrences escape approved core {tuple(sorted(noncore_occurrences))!r}"
        )
    if (
        disposition.pending_site_ids
        or disposition.reviewed_deferred_site_ids
        or disposition.generated_fixture_operations
        or any(operation.disposition == "query_transform" for operation in disposition.operations)
    ):
        raise AnchorRefusedError("current tree retains generated migration work")
    counts = dict(disposition.disposition_counts)
    operations = {
        site_id: operation
        for operation in disposition.operations
        for site_id in operation.consumed_site_ids
    }
    neutral_rules = {item.site_id: item.rule_id for item in disposition.neutral_rule_operations}
    evidence = tuple(
        CurrentClosureSite(
            site_id=site.original_site_id,
            origin=site.origin,
            relative_path=site.relative_path,
            qualified_function=site.qualified_function,
            disposition=operations[site.original_site_id].disposition,
            rule_id=(
                "approved_core"
                if operations[site.original_site_id].disposition == "approved_core"
                else neutral_rules[site.original_site_id]
            ),
        )
        for site in stream.sites
    )
    return CurrentTreeClosure(
        occurrence_count=len(inventory.occurrences),
        diagnostic_count=len(inventory.diagnostics),
        site_count=len(stream.sites),
        approved_core_count=counts.get("approved_core", 0),
        projection_neutral_count=counts.get("projection_neutral", 0),
        identity=current_closure_identity(inventory, evidence),
    )


def compile_current_source_apply_plans(
    sources: Iterable[SourceSnapshot], manifest: ProjectionMigrationManifest
) -> tuple[QuerySourceApplyPlan, FixtureSourceApplyPlan]:
    """Compile every current-tree source rewrite without touching the filesystem."""
    snapshots = tuple(sources)
    inventory = inventory_sources(snapshots, manifest, require_declaration_facts=True)
    stream = compile_operation_stream(snapshots, inventory, query_migration_skeleton(inventory))
    disposition = plan_structural_dispositions(
        stream, _empty_query_ledger(manifest.baseline_revision)
    )
    composition = compile_query_composition_plan(snapshots, stream, disposition)
    replacements = compile_query_replacement_plan(snapshots, stream, disposition, composition)
    fixture_mutations = compile_fixture_mutation_plan(
        snapshots, stream, disposition.generated_fixture_operations
    )
    query_apply = apply_query_replacement_plan(snapshots, replacements)
    fixture_apply = apply_fixture_mutation_plan(snapshots, fixture_mutations)
    duplicate_paths = {update.relative_path for update in query_apply.updates} & {
        update.relative_path for update in fixture_apply.updates
    }
    if duplicate_paths:
        raise AnchorRefusedError(
            f"current query and fixture source plans overlap: {tuple(sorted(duplicate_paths))!r}"
        )
    query_updates = {update.relative_path: update for update in query_apply.updates}
    fixture_updates = {update.relative_path: update for update in fixture_apply.updates}
    for source in snapshots:
        if source.relative_path.startswith("src/orchestrator/graph/"):
            continue
        query_update = query_updates.get(source.relative_path)
        fixture_update = fixture_updates.get(source.relative_path)
        current_source = (
            query_update.transformed_source
            if query_update is not None
            else fixture_update.transformed_source
            if fixture_update is not None
            else source.source
        )
        transformed_source = rewrite_graph_submodule_imports(current_source)
        if transformed_source == current_source:
            continue
        import_site_id = f"public-graph-import:{source.relative_path}"
        if query_update is not None:
            query_updates[source.relative_path] = query_update.model_copy(
                update={
                    "transformed_source": transformed_source,
                    "consumed_site_ids": tuple(
                        sorted((*query_update.consumed_site_ids, import_site_id))
                    ),
                }
            )
        elif fixture_update is not None:
            fixture_updates[source.relative_path] = fixture_update.model_copy(
                update={
                    "transformed_source": transformed_source,
                    "consumed_site_ids": tuple(
                        sorted((*fixture_update.consumed_site_ids, import_site_id))
                    ),
                }
            )
        else:
            query_updates[source.relative_path] = QuerySourceUpdate(
                relative_path=source.relative_path,
                original_source=source.source,
                transformed_source=transformed_source,
                consumed_site_ids=(import_site_id,),
                query_imports=(),
            )
    return (
        QuerySourceApplyPlan(
            updates=tuple(sorted(query_updates.values(), key=lambda item: item.relative_path))
        ),
        FixtureSourceApplyPlan(
            updates=tuple(sorted(fixture_updates.values(), key=lambda item: item.relative_path))
        ),
    )


def apply_source_updates_in_memory(
    sources: Iterable[SourceSnapshot],
    query_apply: QuerySourceApplyPlan,
    fixture_apply: FixtureSourceApplyPlan,
) -> tuple[SourceSnapshot, ...]:
    """Return source snapshots after independently validated non-overlapping updates."""
    updates = {
        update.relative_path: update for update in (*query_apply.updates, *fixture_apply.updates)
    }
    snapshots = tuple(sources)
    if len(updates) != len(query_apply.updates) + len(fixture_apply.updates):
        raise AnchorRefusedError("current source updates have duplicate paths")
    return tuple(
        source.model_copy(update={"source": updates[source.relative_path].transformed_source})
        if source.relative_path in updates
        else source
        for source in snapshots
    )


def query_migration_report_json(report: QueryMigrationReport) -> bytes:
    """Return canonical report JSON bytes with a trailing newline."""
    return (
        json.dumps(
            report.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode()


def write_query_migration_report(
    target: Path,
    report: QueryMigrationReport,
    *,
    expected_bytes: bytes | None = None,
) -> None:
    """Atomically write one validated report after checking expected current bytes."""
    if expected_bytes is not None and (
        not target.is_file() or target.read_bytes() != expected_bytes
    ):
        raise AnchorRefusedError("query migration report changed before atomic apply")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(query_migration_report_json(report))
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            os.chmod(temporary, target.stat().st_mode)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_repository_migration_apply(
    root: Path,
    query_apply: QuerySourceApplyPlan,
    fixture_apply: FixtureSourceApplyPlan,
    report_path: Path,
    report: QueryMigrationReport,
    *,
    expected_report_bytes: bytes | None,
) -> None:
    """Atomically replace all prevalidated source updates and the checked report."""
    root = root.resolve()
    source_updates = (*query_apply.updates, *fixture_apply.updates)
    targets: list[tuple[Path, str, int]] = []
    for update in source_updates:
        relative = Path(update.relative_path)
        target = (root / relative).resolve()
        if relative.is_absolute() or root not in target.parents:
            raise AnchorRefusedError("repository migration source path escapes the repository root")
        if not target.is_file() or target.read_text() != update.original_source:
            raise AnchorRefusedError(
                f"repository migration source changed before atomic apply: {update.relative_path}"
            )
        targets.append((target, update.transformed_source, target.stat().st_mode))
    if expected_report_bytes is None:
        if report_path.exists():
            raise AnchorRefusedError("query migration report changed before atomic apply")
    elif not report_path.is_file() or report_path.read_bytes() != expected_report_bytes:
        raise AnchorRefusedError("query migration report changed before atomic apply")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    targets.append((report_path, query_migration_report_json(report).decode(), 0o644))
    temporary_paths: list[tuple[Path, Path]] = []
    try:
        for target, contents, mode in targets:
            descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            temporary_paths.append((target, temporary))
        for target, temporary in temporary_paths:
            os.replace(temporary, target)
    finally:
        for _, temporary in temporary_paths:
            if temporary.exists():
                temporary.unlink()


def run_query_migration_mode(
    root: Path,
    manifest: ProjectionMigrationManifest,
    mode: Literal["check", "apply", "assert-clean"],
    *,
    report_path: Path,
) -> QueryMigrationReport | CurrentTreeClosure:
    """Execute one whole-tree migration mode against injected repository paths."""
    current_sources = load_current_python_sources(root)
    if mode == "assert-clean":
        # Current-tree verification deliberately does not compile the historical
        # baseline. Historical linkage is owned by inventory --check and
        # the migration gate; this mode proves only that no current edit remains
        # and that the canonical report authenticates this exact current closure.
        closure = compile_current_tree_closure(current_sources, manifest)
        if not report_path.exists():
            raise AnchorRefusedError("checked query migration report is missing")
        raw = report_path.read_bytes()
        try:
            report = QueryMigrationReport.model_validate_json(raw)
        except ValueError as error:
            raise AnchorRefusedError("checked query migration report is invalid") from error
        if (
            query_migration_report_json(report) != raw
            or report.current_closure != closure
            or report.baseline_revision != manifest.baseline_revision
        ):
            raise AnchorRefusedError("checked query migration report bytes or closure are stale")
        return closure
    query_apply, fixture_apply = compile_current_source_apply_plans(current_sources, manifest)
    transformed_current_sources = apply_source_updates_in_memory(
        current_sources, query_apply, fixture_apply
    )
    closure = compile_current_tree_closure(transformed_current_sources, manifest)
    report = compile_query_migration_report(
        load_git_python_sources(root, manifest.baseline_revision),
        manifest,
        current_closure=closure,
    )
    if mode == "apply":
        expected = report_path.read_bytes() if report_path.exists() else None
        if load_current_python_sources(root) != current_sources:
            raise AnchorRefusedError("current tracked sources changed before atomic apply")
        write_repository_migration_apply(
            root,
            query_apply,
            fixture_apply,
            report_path,
            report,
            expected_report_bytes=expected,
        )
    elif mode != "check":
        raise AnchorRefusedError(f"unknown query migration mode: {mode}")
    return report


def main(argv: Iterable[str] | None = None) -> int:
    """Run the whole-tree query migration report contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--assert-clean", action="store_true")
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    mode: Literal["check", "apply", "assert-clean"] = (
        "check" if args.check else "apply" if args.apply else "assert-clean"
    )
    root = Path(__file__).parents[2]
    manifest = load_manifest(root / "scripts/codemods/graph_projection_manifest.yaml")
    report_path = root / "tests/fixtures/graph_projection_migration/query_migration_report.json"
    try:
        result = run_query_migration_mode(
            root,
            manifest,
            mode,
            report_path=report_path,
        )
    except (AnchorRefusedError, OSError, ValueError) as error:
        print(f"query migration {mode} failed: {error}", file=sys.stderr)
        return 1
    count = (
        result.baseline_site_count
        if isinstance(result, QueryMigrationReport)
        else result.site_count
    )
    print(f"query migration {mode} passed: {count} sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
