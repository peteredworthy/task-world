"""Mechanically migrate internal token-accounting names to OTel vocabulary.

Provider payload keys intentionally remain wire-format strings.  This codemod
only changes Python identifiers and dictionary keys when their owner proves
they are part of an internal telemetry contract; uncertain dictionary keys are
reported for an explicit human decision.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import libcst as cst
import libcst.matchers as m
from libcst.metadata import MetadataWrapper, ParentNodeProvider, PositionProvider, ScopeProvider

FIELD_RENAMES = {
    "input_tokens": "gen_ai_usage_input_tokens",
    "output_tokens": "gen_ai_usage_output_tokens",
    "cache_read_tokens": "gen_ai_usage_cache_read_input_tokens",
    "cache_creation_tokens": "gen_ai_usage_cache_creation_input_tokens",
    "reasoning_tokens": "gen_ai_usage_reasoning_output_tokens",
    "tokens_reasoning": "gen_ai_usage_reasoning_output_tokens",
    "cache_write_tokens": "gen_ai_usage_cache_creation_input_tokens",
    "total_input_tokens": "gen_ai_usage_input_tokens",
    "total_output_tokens": "gen_ai_usage_output_tokens",
    "total_cache_read_tokens": "gen_ai_usage_cache_read_input_tokens",
    "total_cache_creation_tokens": "gen_ai_usage_cache_creation_input_tokens",
    "tokens_read": "gen_ai_usage_input_tokens",
    "tokens_write": "gen_ai_usage_output_tokens",
    "tokens_cache": "gen_ai_usage_cache_read_input_tokens",
}

# These are raw keys deliberately consumed at provider parser boundaries.  They
# document the wire-format exemption and must never be used as internal names.
PROVIDER_RAW_KEYS = frozenset(
    {
        "inputTokens",
        "input_tokens",
        "outputTokens",
        "output_tokens",
        "cacheReadInputTokens",
        "cacheCreationInputTokens",
        "reasoningOutputTokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cached_input_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
    }
)

PROVIDER_BOUNDARY_PATH_PREFIXES = (
    "src/orchestrator/runners/agents/codex/",
    "src/orchestrator/runners/agents/claude_cli/",
    "src/orchestrator/runners/agents/openhands/",
)

PROVIDER_RECEIVER_NAMES = frozenset({"payload", "response", "usage", "usage_dict"})

INTERNAL_TELEMETRY_TYPES = frozenset(
    {
        "ModelTokenUsage",
        "ModelTokenUsageSchema",
        "TurnMetrics",
        "SubAgentLog",
        "ActionLog",
        "AttemptMetrics",
        "ExecutionMetrics",
        "GatekeeperVerdictCommandRow",
        "GatekeeperCostCommandRow",
        "GatekeeperVerdictRow",
        "GatekeeperCostRecordedPayload",
        "TurnMetricsSchema",
        "ActionLogSchema",
        "GatekeeperVerdict",
        "MockBehavior",
        "RunMetricSummary",
        "InitialAttemptForRunCreate",
        "CreateTaskAttemptCommand",
        "UpdateLatestAttemptCommand",
        "AttemptUpdated",
    }
)

# These functions are internal telemetry sinks with flat interim metrics.  The
# fields remain canonical in Task 3 even though Task 4 removes some of them.
INTERNAL_METRIC_CALLS = frozenset({"merge_token_usage_into_run"})

# These literal sites deliberately describe the legacy vocabulary rather than
# use it as a live internal contract.
INTENTIONAL_LITERAL_PATHS = frozenset(
    {
        "tests/unit/test_r04_otel_vocab_codemod.py",
        # This report deliberately names the immutable cost_records SQL columns.
        "scripts/cost_report.py",
    }
)
MIGRATION_HISTORY_PATH_PREFIX = "src/orchestrator/db/migrations/versions/"

# Every entry is an internal telemetry producer or consumer reviewed in the
# Task 3 inventory.  Path membership is an additional proof; it is never
# inferred from an identifier suffix.
INTERNAL_TELEMETRY_PATH_PREFIXES = (
    "src/orchestrator/api/",
    "src/orchestrator/graph/",
    "src/orchestrator/graph_runtime/",
    "src/orchestrator/runners/execution/",
    "src/orchestrator/state/",
    "src/orchestrator/workflow/",
)
INTERNAL_TELEMETRY_PATHS = frozenset(
    {
        "src/orchestrator/runners/costs.py",
        "src/orchestrator/runners/types.py",
        "scripts/compare_carriers.py",
        "scripts/cost_report.py",
    }
)

# These names are reviewed structural proofs, not filename-wide heuristics.
# Each function owns an internal flat accumulator or interim command contract.
INTERNAL_FLAT_METRIC_FUNCTIONS = {
    "src/orchestrator/runners/agents/codex/agent.py": frozenset({"execute", "_build_metrics"}),
    "src/orchestrator/runners/agents/codex/common.py": frozenset(
        {
            "extract_token_usage_update",
            "extract_turn_usage",
            "normalize_codex_metrics",
            "build_execution_result",
        }
    ),
    "src/orchestrator/runners/agents/codex/parser.py": frozenset(
        {"_normalize_turn_usage", "_handle_message_created", "_handle_result"}
    ),
    "src/orchestrator/runners/agents/openhands/common.py": frozenset({"extract_metrics"}),
    "src/orchestrator/runners/execution/attempt_store.py": frozenset(
        {"_append_attempt_update", "store_attempt_metrics"}
    ),
    "src/orchestrator/db/access/mutations.py": frozenset({"merge_token_usage_into_run"}),
    "src/orchestrator/workflow/commands/attempt_and_fanout.py": frozenset(
        {"handle_update_latest_attempt"}
    ),
    "src/orchestrator/workflow/commands/run_lifecycle.py": frozenset(
        {"build_create_run_command", "handle_create_run"}
    ),
    "scripts/compare_carriers.py": frozenset({"run_metrics", "aggregate_bucket"}),
    "tests/unit/test_compare_carriers.py": frozenset({"_row"}),
    "tests/unit/test_token_fallback_from_entries.py": frozenset(
        {
            "_make_entry",
            "_make_run_with_action_log",
            "test_uses_aggregate_when_populated",
            "test_falls_back_to_per_entry_when_aggregate_is_zero",
            "test_real_world_1_9m_tokens_scenario",
            "test_uses_per_entry_metrics_when_aggregate_zero",
        }
    ),
    "tests/integration/test_graph_fr15_acceptance.py": frozenset({"_secret_verdict"}),
    "tests/integration/test_graph_outbox_crash_points.py": frozenset({"_secret_verdict"}),
}
RAW_METRIC_CALLEES = frozenset(
    {
        "estimate_cost",
        "_usage_fact",
        "calculate_model_usage_cost",
        "CostRecordModel",
    }
)
INTERNAL_MAPPING_RECEIVERS = frozenset({"result", "r", "turn_usage"})
RAW_STORAGE_LITERAL_CONTEXTS = {
    "scripts/compare_carriers.py": frozenset({"_fetch_aggregates", "_merge_token_metrics"}),
    "src/orchestrator/workflow/commands/run_lifecycle.py": frozenset(
        {"_snapshot_attempt_needs_update", "expand_run_snapshot_for_projection"}
    ),
}
CODEX_RAW_PROVIDER_FUNCTIONS = frozenset({"extract_token_usage_update", "extract_turn_usage"})

# Test fixtures have two deliberately separate ownership boundaries.  Raw
# provider messages keep their vendor wire keys; Task 4 owns the historical
# persisted JSON/ORM shapes.  These are exact reviewed files plus the narrow
# literal/attribute context below, never a tests/ directory exemption.
PROVIDER_RAW_FIXTURE_PATHS = frozenset(
    {
        "tests/unit/test_claude_parser.py",
        "tests/unit/test_codex_parser.py",
        "tests/unit/test_codex_server_common.py",
        "tests/unit/test_codex_server_agent.py",
        "tests/unit/test_codex_server_token_capture.py",
        "tests/unit/test_codex_server_transport.py",
        "tests/unit/test_openhands_common.py",
    }
)
HISTORICAL_PERSISTENCE_FIXTURE_PATHS = frozenset(
    {
        "tests/integration/test_cost_records.py",
        "tests/integration/test_database.py",
        "tests/integration/test_event_log_durability.py",
        "tests/integration/test_event_sourced_workflow.py",
        "tests/integration/test_graph_file_state_report_api.py",
        "tests/unit/test_command_handlers.py",
        "tests/unit/test_compare_carriers.py",
        "tests/unit/test_projectors.py",
        "tests/unit/test_pydantic_events.py",
        "tests/unit/test_run_aggregation.py",
        "tests/unit/test_token_fallback_from_entries.py",
    }
)
HISTORICAL_FIXTURE_HELPERS = frozenset({"_legacy_usage_snapshot", "_legacy_event_payload"})
TEST_INTERNAL_METRIC_FUNCTIONS = {
    "tests/integration/test_attempt_store_event_sourcing.py": frozenset(
        {"test_attempt_store_appends_events_and_projects_attempt_and_run_totals"}
    ),
    "tests/unit/test_codex_server_common.py": frozenset(
        {
            "test_normalize_metrics_values_round_trip",
            "test_extract_turn_usage_with_input_output_tokens",
            "test_extract_turn_usage_with_prompt_completion_tokens",
            "test_extract_turn_usage_without_usage_field",
            "test_extract_turn_usage_non_terminal_notification",
            "test_extract_turn_usage_empty_usage_dict",
            "test_extract_turn_usage_cache_read_input_tokens",
            "test_build_execution_result_with_tokens",
            "test_extract_token_usage_update_total_cumulative",
            "test_extract_token_usage_update_camel_and_snake",
            "test_extract_turn_usage_reasoning_folded",
        }
    ),
    "tests/unit/test_codex_server_agent.py": frozenset({"test_build_metrics_delegates_to_common"}),
    "tests/unit/test_codex_server_token_capture.py": frozenset(
        {"test_session_accumulates_token_usage", "test_extract_metrics_and_usage_nonzero_for_codex"}
    ),
    "tests/unit/test_command_handlers.py": frozenset(
        {"test_create_run_replays_initial_attempt_gap_fields"}
    ),
    "tests/unit/test_file_state_gatekeeper_event_payloads.py": frozenset(
        {"test_gatekeeper_cost_fields_survive_summary_reconstruction"}
    ),
}

# Provider fixture builders emit wire-format payloads.  This recognizes only
# their call keywords, not arbitrary constructors in the same test modules.
PROVIDER_RAW_FIXTURE_CALLS = {
    "tests/unit/test_claude_parser.py": frozenset({"_assistant_event", "_result_event"}),
}
PROVIDER_RAW_FIXTURE_ATTRIBUTE_FUNCTIONS = {
    "tests/unit/test_openhands_common.py": frozenset({"test_extract_metrics_multiple_models"}),
}

# Task 4 retains the physical ORM schema temporarily.  These are the exact
# tests that assert its historical column names; current telemetry facts are
# asserted through their canonical domain fields elsewhere.
HISTORICAL_ORM_ASSERTION_FUNCTIONS = {
    "tests/unit/test_command_handlers.py": frozenset(
        {
            "test_create_run_replays_initial_attempt_gap_fields",
            "test_create_run_snapshot_only_stores_one_event_but_projects_children",
            "test_update_latest_attempt_projects_attempt_and_task_status",
            "test_update_latest_attempt_appends_output_and_accumulates_metrics",
            "test_record_task_reverted_emits_event_and_projects_snapshot",
        }
    ),
    "tests/unit/test_projectors.py": frozenset(
        {
            "test_task_reverted_restores_task_and_attempts_from_snapshot",
            "test_run_created_snapshot_projected_by_registry_into_initial_steps_and_tasks",
            "test_attempt_updated_can_skip_run_totals_projection",
        }
    ),
    "tests/integration/test_database.py": frozenset({"test_crud_with_steps_and_tasks"}),
    "tests/integration/test_cost_records.py": frozenset(
        {
            "test_phase_handler_records_cost_and_interaction_logs_for_each_agent_execution",
            "test_phase_handler_records_recovering_cost_and_interaction_log_prompt",
            "test_phase_handler_persists_per_model_cost_usage",
        }
    ),
}
PHYSICAL_ORM_ATTRIBUTE_FUNCTIONS = {
    "src/orchestrator/db/access/mutations.py": frozenset({"update_latest_attempt"}),
    "src/orchestrator/db/access/repositories.py": frozenset({"run_model_to_domain"}),
    "src/orchestrator/db/projections/task_state.py": frozenset({"handle"}),
}


def _expression_path(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        parent = _expression_path(node.value)
        return f"{parent}.{node.attr.value}" if parent else None
    return None


def _is_provider_boundary(path: str) -> bool:
    return path.startswith(PROVIDER_BOUNDARY_PATH_PREFIXES)


def _is_literal_boundary(path: str) -> bool:
    return (
        path in INTENTIONAL_LITERAL_PATHS
        or path == "scripts/codemods/r04_otel_vocab.py"
        or path.startswith(MIGRATION_HISTORY_PATH_PREFIX)
    )


def _is_test_provider_raw_fixture(path: str, node: cst.CSTNode) -> bool:
    return path in PROVIDER_RAW_FIXTURE_PATHS and isinstance(node, cst.SimpleString)


def _is_internal_telemetry_path(path: str) -> bool:
    return path.startswith(INTERNAL_TELEMETRY_PATH_PREFIXES) or path in INTERNAL_TELEMETRY_PATHS


def _enclosing_function_name(
    node: cst.CSTNode,
    get_parent: Callable[[cst.CSTNode, cst.CSTNode | None], cst.CSTNode | None],
) -> str | None:
    parent = get_parent(node, None)
    while parent is not None:
        if isinstance(parent, cst.FunctionDef):
            return parent.name.value
        parent = get_parent(parent, None)
    return None


def _has_enclosing_function_name(
    node: cst.CSTNode,
    names: frozenset[str],
    get_parent: Callable[[cst.CSTNode, cst.CSTNode | None], cst.CSTNode | None],
) -> bool:
    parent = get_parent(node, None)
    while parent is not None:
        if isinstance(parent, cst.FunctionDef) and parent.name.value in names:
            return True
        parent = get_parent(parent, None)
    return False


def _is_historical_orm_assertion(
    node: cst.CSTNode,
    path: str,
    get_parent: Callable[[cst.CSTNode, cst.CSTNode | None], cst.CSTNode | None],
) -> bool:
    return (
        path in HISTORICAL_ORM_ASSERTION_FUNCTIONS
        and _enclosing_function_name(node, get_parent) in HISTORICAL_ORM_ASSERTION_FUNCTIONS[path]
    )


def _is_internal_flat_metric_context(
    node: cst.CSTNode,
    path: str,
    get_parent: Callable[[cst.CSTNode, cst.CSTNode | None], cst.CSTNode | None],
) -> bool:
    return _enclosing_function_name(node, get_parent) in INTERNAL_FLAT_METRIC_FUNCTIONS.get(
        path, frozenset()
    )


def _is_test_internal_metric_context(
    node: cst.CSTNode,
    path: str,
    get_parent: Callable[[cst.CSTNode, cst.CSTNode | None], cst.CSTNode | None],
) -> bool:
    return _enclosing_function_name(node, get_parent) in TEST_INTERNAL_METRIC_FUNCTIONS.get(
        path, frozenset()
    )


def _is_openhands_raw_cache_attribute(node: cst.Attribute) -> bool:
    return (
        node.attr.value == "cache_read_tokens"
        and isinstance(node.value, cst.Attribute)
        and node.value.attr.value == "accumulated_token_usage"
    )


def _callee_leaf_name(call: cst.Call) -> str | None:
    path = _expression_path(call.func)
    return path.rsplit(".", 1)[-1] if path else None


def _replace_literal(literal: str, replacement: str) -> str:
    match = re.match(r"(?is)^([rub]*)(\"\"\"|'''|\"|')", literal)
    if match is None:
        return repr(replacement)
    prefix, quote = match.groups()
    return f"{prefix}{quote}{replacement}{quote}"


def _is_telemetry_constructor(call: cst.Call) -> bool:
    """Return whether a call's name identifies an internal telemetry object."""
    if not m.matches(call.func, m.Name()):
        return False
    assert isinstance(call.func, cst.Name)
    return call.func.value in INTERNAL_TELEMETRY_TYPES


def _is_telemetry_validation(call: cst.Call) -> bool:
    return (
        isinstance(call.func, cst.Attribute)
        and isinstance(call.func.value, cst.Name)
        and call.func.value.value in INTERNAL_TELEMETRY_TYPES
        and call.func.attr.value == "model_validate"
    )


def _is_telemetry_result(expression: cst.BaseExpression) -> bool:
    return isinstance(expression, cst.Call) and (
        _is_telemetry_constructor(expression) or _is_telemetry_validation(expression)
    )


def _binding_targets(
    target: cst.BaseAssignTargetExpression,
) -> Iterable[cst.BaseAssignTargetExpression]:
    if isinstance(target, (cst.Name, cst.Attribute)):
        yield target
    elif isinstance(target, (cst.Tuple, cst.List)):
        for element in target.elements:
            if isinstance(element, cst.Element):
                yield from _binding_targets(element.value)
            elif isinstance(element, cst.StarredElement):
                yield from _binding_targets(element.value)
    elif isinstance(target, cst.StarredElement):
        yield from _binding_targets(target.value)


def _match_binding_targets(pattern: cst.BaseMatchPattern) -> Iterable[cst.Name]:
    if isinstance(pattern, cst.MatchAs):
        if pattern.pattern is not None:
            yield from _match_binding_targets(pattern.pattern)
        if pattern.name is not None:
            yield pattern.name
    elif isinstance(pattern, cst.MatchStar):
        if pattern.name is not None:
            yield pattern.name
    elif isinstance(pattern, cst.MatchMapping):
        for element in pattern.elements:
            yield from _match_binding_targets(element.pattern)
        if pattern.rest is not None:
            yield pattern.rest
    elif isinstance(pattern, cst.MatchSequence):
        for nested_pattern in pattern.patterns:
            yield from _match_binding_targets(nested_pattern)
    elif isinstance(pattern, cst.MatchOr):
        for element in pattern.patterns:
            yield from _match_binding_targets(element.pattern)
    elif isinstance(pattern, cst.MatchClass):
        for nested_pattern in pattern.patterns:
            yield from _match_binding_targets(nested_pattern)
        for keyword_pattern in pattern.kwds:
            yield from _match_binding_targets(keyword_pattern.pattern)


class _OwnershipEventKind(Enum):
    TELEMETRY_OWNER = "telemetry_owner"
    NON_TELEMETRY_KILL = "non_telemetry_kill"
    UNCERTAIN_ASSIGNMENT = "uncertain_assignment"


@dataclass(frozen=True)
class _OwnershipEvent:
    position: tuple[int, int]
    kind: _OwnershipEventKind


class _TelemetryOwnerCollector(cst.CSTVisitor):
    """Collect assignments that statically prove an expression is telemetry."""

    METADATA_DEPENDENCIES = (ParentNodeProvider, PositionProvider, ScopeProvider)

    def __init__(self) -> None:
        self.events: dict[tuple[int, str], list[_OwnershipEvent]] = {}

    def _is_conditional(self, node: cst.CSTNode) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None:
            if isinstance(parent, (cst.FunctionDef, cst.ClassDef, cst.Lambda)):
                return False
            if isinstance(
                parent,
                (cst.If, cst.For, cst.While, cst.Try, cst.With, cst.Match, cst.MatchCase),
            ):
                return True
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        return False

    def _record(
        self,
        target: cst.BaseAssignTargetExpression,
        node: cst.CSTNode,
        kind: _OwnershipEventKind,
        activation_node: cst.CSTNode | None = None,
    ) -> None:
        path = _expression_path(target)
        if path:
            key = (id(self.get_metadata(ScopeProvider, node)), path)
            position = self.get_metadata(PositionProvider, activation_node or node).end
            self.events.setdefault(key, []).append(
                _OwnershipEvent((position.line, position.column), kind)
            )

    def _record_targets(
        self,
        target: cst.BaseAssignTargetExpression,
        node: cst.CSTNode,
        kind: _OwnershipEventKind,
        activation_node: cst.CSTNode | None = None,
    ) -> None:
        for binding_target in _binding_targets(target):
            self._record(binding_target, node, kind, activation_node)

    def _assignment_kind(self, node: cst.CSTNode, value: cst.BaseExpression) -> _OwnershipEventKind:
        if self._is_conditional(node):
            return _OwnershipEventKind.UNCERTAIN_ASSIGNMENT
        if _is_telemetry_result(value):
            return _OwnershipEventKind.TELEMETRY_OWNER
        return _OwnershipEventKind.NON_TELEMETRY_KILL

    def visit_Assign(self, node: cst.Assign) -> None:
        for target in node.targets:
            kind = self._assignment_kind(node, node.value)
            if isinstance(target.target, (cst.Name, cst.Attribute)):
                self._record_targets(target.target, node, kind)
            else:
                self._record_targets(target.target, node, _OwnershipEventKind.NON_TELEMETRY_KILL)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if node.value is not None:
            self._record_targets(node.target, node, self._assignment_kind(node, node.value))

    def visit_For(self, node: cst.For) -> None:
        self._record_targets(node.target, node, _OwnershipEventKind.UNCERTAIN_ASSIGNMENT, node.iter)

    def visit_With(self, node: cst.With) -> None:
        for item in node.items:
            if item.asname is not None:
                self._record_targets(
                    item.asname.name,
                    node,
                    _OwnershipEventKind.UNCERTAIN_ASSIGNMENT,
                    item.asname,
                )

    def visit_NamedExpr(self, node: cst.NamedExpr) -> None:
        self._record_targets(node.target, node, _OwnershipEventKind.UNCERTAIN_ASSIGNMENT)

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        self._record_targets(node.target, node, _OwnershipEventKind.UNCERTAIN_ASSIGNMENT)

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> None:
        if node.name is not None:
            self._record_targets(
                node.name.name,
                node,
                _OwnershipEventKind.UNCERTAIN_ASSIGNMENT,
                node.name,
            )

    def visit_MatchCase(self, node: cst.MatchCase) -> None:
        for target in _match_binding_targets(node.pattern):
            self._record(target, node, _OwnershipEventKind.UNCERTAIN_ASSIGNMENT, node.pattern)


class _OtelVocabularyTransformer(cst.CSTTransformer):
    """Apply only identifier changes whose CST owner establishes their meaning."""

    METADATA_DEPENDENCIES = (ParentNodeProvider, PositionProvider, ScopeProvider)

    def __init__(
        self,
        *,
        events: dict[tuple[int, str], list[_OwnershipEvent]],
        path: str,
    ) -> None:
        self.events = events
        self.path = path
        self.is_internal_telemetry_path = _is_internal_telemetry_path(path)
        self.is_provider_boundary = _is_provider_boundary(path)

    def _is_internal_metric_context(self, node: cst.CSTNode) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None and not isinstance(parent, cst.Call):
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        return (
            isinstance(parent, cst.Call) and _expression_path(parent.func) in INTERNAL_METRIC_CALLS
        )

    def _is_flat_metric_context(self, node: cst.CSTNode) -> bool:
        return _is_internal_flat_metric_context(
            node,
            self.path,
            lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
        )

    def _is_test_internal_metric_context(self, node: cst.CSTNode) -> bool:
        return _is_test_internal_metric_context(
            node,
            self.path,
            lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
        )

    def _is_flat_metric_callee(self, call: cst.Call) -> bool:
        return _callee_leaf_name(call) in INTERNAL_FLAT_METRIC_FUNCTIONS.get(self.path, frozenset())

    def _is_internal_mapping_subscript(self, node: cst.SimpleString) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if isinstance(parent, cst.Arg):
            call = self.get_metadata(ParentNodeProvider, parent, None)
            return (
                isinstance(call, cst.Call)
                and isinstance(call.func, cst.Attribute)
                and call.func.attr.value == "get"
                and isinstance(call.func.value, cst.Name)
                and call.func.value.value in INTERNAL_MAPPING_RECEIVERS
            )
        if not isinstance(parent, cst.Index):
            return False
        element = self.get_metadata(ParentNodeProvider, parent, None)
        subscript = self.get_metadata(ParentNodeProvider, element, None)
        return (
            isinstance(subscript, cst.Subscript)
            and isinstance(subscript.value, cst.Name)
            and subscript.value.value in INTERNAL_MAPPING_RECEIVERS
        )

    def _is_test_internal_mapping_subscript(self, node: cst.SimpleString) -> bool:
        if not self._is_test_internal_metric_context(node):
            return False
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if isinstance(parent, cst.Arg):
            call = self.get_metadata(ParentNodeProvider, parent, None)
            return (
                isinstance(call, cst.Call)
                and isinstance(call.func, cst.Attribute)
                and call.func.attr.value == "get"
                and isinstance(call.func.value, cst.Name)
                and call.func.value.value in INTERNAL_MAPPING_RECEIVERS | {"payload"}
            )
        if not isinstance(parent, cst.Index):
            return False
        element = self.get_metadata(ParentNodeProvider, parent, None)
        subscript = self.get_metadata(ParentNodeProvider, element, None)
        return (
            isinstance(subscript, cst.Subscript)
            and isinstance(subscript.value, cst.Name)
            and subscript.value.value in INTERNAL_MAPPING_RECEIVERS | {"payload"}
        )

    def _is_test_internal_event_expectation(self, node: cst.Dict) -> bool:
        if not self._is_test_internal_metric_context(node):
            return False
        parent = self.get_metadata(ParentNodeProvider, node, None)
        call = self.get_metadata(ParentNodeProvider, parent, None)
        return (
            isinstance(parent, cst.Arg)
            and isinstance(call, cst.Call)
            and _callee_leaf_name(call) == "_assert_latest_event"
        )

    def _is_test_internal_event_payload(self, node: cst.Dict) -> bool:
        if not self._is_test_internal_metric_context(node):
            return False
        parent = self.get_metadata(ParentNodeProvider, node, None)
        return (
            isinstance(parent, cst.Assign)
            and len(parent.targets) == 1
            and isinstance(parent.targets[0].target, cst.Name)
            and parent.targets[0].target.value == "payload"
        )

    def _is_owner(self, node: cst.CSTNode, path: str | None) -> bool:
        if isinstance(node, cst.Attribute) and _is_telemetry_result(node.value):
            return True
        if path is None:
            return False
        scope = self.get_metadata(ScopeProvider, node, None)
        if scope is None:
            return False
        key = (id(scope), path)
        position = self.get_metadata(PositionProvider, node).start
        preceding_events = [
            event
            for event in self.events.get(key, [])
            if event.position < (position.line, position.column)
        ]
        return (
            bool(preceding_events)
            and max(preceding_events, key=lambda event: event.position).kind
            is _OwnershipEventKind.TELEMETRY_OWNER
        )

    def _is_class_field(self, node: cst.CSTNode) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None:
            if isinstance(parent, cst.FunctionDef):
                return False
            if isinstance(parent, cst.ClassDef):
                return parent.name.value in INTERNAL_TELEMETRY_TYPES
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        return False

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        if (
            self._is_class_field(original_node)
            and isinstance(updated_node.target, cst.Name)
            and updated_node.target.value in FIELD_RENAMES
        ):
            return updated_node.with_changes(
                target=updated_node.target.with_changes(
                    value=FIELD_RENAMES[updated_node.target.value]
                )
            )
        return updated_node

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.Attribute:
        if (
            (
                self._is_owner(original_node, _expression_path(original_node.value))
                or self._is_internal_metric_context(original_node)
                or self._is_test_internal_metric_context(original_node)
            )
            or self._is_flat_metric_context(original_node)
        ) and (
            not _is_openhands_raw_cache_attribute(original_node)
            and not _is_historical_orm_assertion(
                original_node,
                self.path,
                lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
            )
            and updated_node.attr.value in FIELD_RENAMES
        ):
            return updated_node.with_changes(
                attr=updated_node.attr.with_changes(value=FIELD_RENAMES[updated_node.attr.value])
            )
        return updated_node

    def leave_Arg(self, original_node: cst.Arg, updated_node: cst.Arg) -> cst.Arg:
        parent = self.get_metadata(ParentNodeProvider, original_node, None)
        if (
            isinstance(parent, cst.Call)
            and (
                _is_telemetry_constructor(parent)
                or _expression_path(parent.func) in INTERNAL_METRIC_CALLS
                or (
                    self._is_flat_metric_context(original_node)
                    and _expression_path(parent.func) not in RAW_METRIC_CALLEES
                )
                or self._is_test_internal_metric_context(original_node)
                or self._is_flat_metric_callee(parent)
            )
            and _callee_leaf_name(parent) not in RAW_METRIC_CALLEES
            and updated_node.keyword is not None
            and updated_node.keyword.value in FIELD_RENAMES
        ):
            return updated_node.with_changes(
                keyword=updated_node.keyword.with_changes(
                    value=FIELD_RENAMES[updated_node.keyword.value]
                )
            )
        return updated_node

    def leave_Dict(self, original_node: cst.Dict, updated_node: cst.Dict) -> cst.BaseExpression:
        parent = self.get_metadata(ParentNodeProvider, original_node, None)
        if isinstance(parent, cst.Arg):
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        if not (
            (isinstance(parent, cst.Call) and _is_telemetry_validation(parent))
            or self._is_flat_metric_context(original_node)
            or self._is_test_internal_event_expectation(original_node)
            or self._is_test_internal_event_payload(original_node)
        ):
            return updated_node
        elements: list[cst.BaseDictElement] = []
        for original_element, updated_element in zip(
            original_node.elements, updated_node.elements, strict=True
        ):
            if (
                isinstance(original_element, cst.DictElement)
                and isinstance(updated_element, cst.DictElement)
                and isinstance(original_element.key, cst.SimpleString)
                and isinstance(original_element.key.evaluated_value, str)
                and original_element.key.evaluated_value in FIELD_RENAMES
            ):
                elements.append(
                    updated_element.with_changes(
                        key=cst.SimpleString(
                            _replace_literal(
                                original_element.key.value,
                                FIELD_RENAMES[original_element.key.evaluated_value],
                            )
                        )
                    )
                )
            else:
                elements.append(updated_element)
        result = updated_node.with_changes(elements=elements)
        return result

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        parent = self.get_metadata(ParentNodeProvider, original_node, None)
        if (
            updated_node.value in FIELD_RENAMES
            and self._is_flat_metric_context(original_node)
            and not (isinstance(parent, cst.Attribute) and parent.attr is original_node)
            and not (isinstance(parent, cst.Arg) and parent.keyword is original_node)
        ):
            return updated_node.with_changes(value=FIELD_RENAMES[updated_node.value])
        return updated_node

    def leave_SimpleString(
        self, original_node: cst.SimpleString, updated_node: cst.SimpleString
    ) -> cst.SimpleString:
        value = original_node.evaluated_value
        if (
            isinstance(value, str)
            and value in FIELD_RENAMES
            and (
                (
                    self._is_flat_metric_context(original_node)
                    and self._is_internal_mapping_subscript(original_node)
                )
                or self._is_test_internal_mapping_subscript(original_node)
            )
        ):
            return cst.SimpleString(_replace_literal(original_node.value, FIELD_RENAMES[value]))
        return updated_node


class _AmbiguousDictionaryVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (ParentNodeProvider, PositionProvider, ScopeProvider)

    def __init__(
        self,
        path: str,
        events: dict[tuple[int, str], list[_OwnershipEvent]],
    ) -> None:
        self.path = path
        self.events = events
        self.is_provider_boundary = _is_provider_boundary(path)
        self.is_literal_boundary = _is_literal_boundary(path)
        self.is_internal_telemetry_path = _is_internal_telemetry_path(path)
        self.diagnostics: list[str] = []

    def _diagnose(self, node: cst.CSTNode, name: str) -> None:
        if self.is_literal_boundary or self._is_historical_persistence_expression(node):
            return
        position = self.get_metadata(PositionProvider, node).start
        self.diagnostics.append(
            f"{self.path}:{position.line}:{position.column}: ambiguous telemetry field {name!r}; left unchanged"
        )

    def _is_owner(self, node: cst.CSTNode, path: str | None) -> bool:
        if isinstance(node, cst.Attribute) and _is_telemetry_result(node.value):
            return True
        if path is None:
            return False
        scope = self.get_metadata(ScopeProvider, node, None)
        if scope is None:
            return False
        key = (id(scope), path)
        position = self.get_metadata(PositionProvider, node).start
        preceding_events = [
            event
            for event in self.events.get(key, [])
            if event.position < (position.line, position.column)
        ]
        return (
            bool(preceding_events)
            and max(preceding_events, key=lambda event: event.position).kind
            is _OwnershipEventKind.TELEMETRY_OWNER
        )

    def _is_internal_metric_context(self, node: cst.CSTNode) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None and not isinstance(parent, cst.Call):
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        return (
            isinstance(parent, cst.Call) and _expression_path(parent.func) in INTERNAL_METRIC_CALLS
        )

    def _is_flat_metric_context(self, node: cst.CSTNode) -> bool:
        return _is_internal_flat_metric_context(
            node,
            self.path,
            lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
        )

    def _is_test_internal_metric_context(self, node: cst.CSTNode) -> bool:
        return _is_test_internal_metric_context(
            node,
            self.path,
            lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
        )

    def _is_internal_mapping_subscript(self, node: cst.SimpleString) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if isinstance(parent, cst.Arg):
            call = self.get_metadata(ParentNodeProvider, parent, None)
            return (
                isinstance(call, cst.Call)
                and isinstance(call.func, cst.Attribute)
                and call.func.attr.value == "get"
                and isinstance(call.func.value, cst.Name)
                and call.func.value.value in INTERNAL_MAPPING_RECEIVERS
            )
        if not isinstance(parent, cst.Index):
            return False
        element = self.get_metadata(ParentNodeProvider, parent, None)
        subscript = self.get_metadata(ParentNodeProvider, element, None)
        return (
            isinstance(subscript, cst.Subscript)
            and isinstance(subscript.value, cst.Name)
            and subscript.value.value in INTERNAL_MAPPING_RECEIVERS
        )

    def _is_raw_storage_literal_context(self, node: cst.CSTNode) -> bool:
        return _enclosing_function_name(
            node,
            lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
        ) in RAW_STORAGE_LITERAL_CONTEXTS.get(self.path, frozenset())

    def _is_provider_fixture_raw_dictionary(self, node: cst.Dict) -> bool:
        """Recognize only nested provider usage dictionary fixture shapes."""
        if self.path not in PROVIDER_RAW_FIXTURE_PATHS:
            return False
        current: cst.CSTNode | None = node
        while current is not None:
            if isinstance(current, cst.Dict) and any(
                isinstance(element, cst.DictElement)
                and isinstance(element.key, cst.SimpleString)
                and element.key.evaluated_value in {"usage", "total_token_usage"}
                for element in current.elements
            ):
                return True
            current = self.get_metadata(ParentNodeProvider, current, None)
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if isinstance(parent, cst.Arg) and parent.keyword is not None:
            return parent.keyword.value == "usage"
        return False

    def _is_test_internal_event_payload(self, node: cst.Dict) -> bool:
        if not self._is_test_internal_metric_context(node):
            return False
        parent = self.get_metadata(ParentNodeProvider, node, None)
        return (
            isinstance(parent, cst.Assign)
            and len(parent.targets) == 1
            and isinstance(parent.targets[0].target, cst.Name)
            and parent.targets[0].target.value == "payload"
        )

    def _is_historical_persistence_expression(self, node: cst.CSTNode) -> bool:
        """Allow only storage-shaped Task 4 facts, never a fixture file wholesale."""
        parent = self.get_metadata(ParentNodeProvider, node, None)
        expression = parent if isinstance(parent, cst.Attribute) else node
        enclosing_function = _enclosing_function_name(
            node,
            lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
        )
        if (
            isinstance(node, cst.SimpleString)
            and self.path == "src/orchestrator/db/projections/run_state.py"
            and (
                enclosing_function == "_merge_token_usage_by_model"
                or enclosing_function == "_canonicalize_usage_entry"
                or self._is_legacy_usage_alias_declaration(node)
            )
        ):
            return True
        if (
            isinstance(node, cst.SimpleString)
            and self.path == "src/orchestrator/db/projections/task_state.py"
            and enclosing_function == "_attempt_values_from_snapshot"
        ):
            return True
        if self._is_provider_fixture_builder_keyword(node):
            return True
        if isinstance(node, cst.SimpleString) and self._is_historical_fixture_helper_access(node):
            return True
        if (
            isinstance(expression, cst.Attribute)
            and self.path in HISTORICAL_ORM_ASSERTION_FUNCTIONS
            and enclosing_function in HISTORICAL_ORM_ASSERTION_FUNCTIONS[self.path]
        ):
            return True
        if isinstance(
            expression, cst.Attribute
        ) and enclosing_function in PHYSICAL_ORM_ATTRIBUTE_FUNCTIONS.get(self.path, frozenset()):
            return True
        if (
            isinstance(expression, cst.Attribute)
            and self.path in PROVIDER_RAW_FIXTURE_ATTRIBUTE_FUNCTIONS
            and _has_enclosing_function_name(
                node,
                PROVIDER_RAW_FIXTURE_ATTRIBUTE_FUNCTIONS[self.path],
                lambda child, default: self.get_metadata(ParentNodeProvider, child, default),
            )
        ):
            return True
        if self.path == "src/orchestrator/db/orm/models.py":
            if isinstance(node, cst.Name):
                return (
                    isinstance(parent, cst.AnnAssign)
                    and isinstance(parent.value, cst.Call)
                    and _callee_leaf_name(parent.value) == "mapped_column"
                )
        if isinstance(node, cst.Name) and isinstance(parent, cst.Arg):
            call = self.get_metadata(ParentNodeProvider, parent, None)
            return isinstance(call, cst.Call) and _callee_leaf_name(call) in {
                "AttemptModel",
                "CostRecordModel",
            }
        if self.path not in HISTORICAL_PERSISTENCE_FIXTURE_PATHS:
            return False
        current: cst.CSTNode | None = node
        while current is not None:
            if (
                isinstance(current, cst.Call)
                and _callee_leaf_name(current) in HISTORICAL_FIXTURE_HELPERS
            ):
                return True
            current = self.get_metadata(ParentNodeProvider, current, None)
        return False

    def _is_legacy_usage_alias_declaration(self, node: cst.SimpleString) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None and not isinstance(parent, cst.Assign):
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        return (
            isinstance(parent, cst.Assign)
            and len(parent.targets) == 1
            and isinstance(parent.targets[0].target, cst.Name)
            and parent.targets[0].target.value == "_LEGACY_USAGE_ALIASES"
        )

    def _is_historical_fixture_helper_access(self, node: cst.SimpleString) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if not isinstance(parent, cst.Index):
            return False
        element = self.get_metadata(ParentNodeProvider, parent, None)
        subscript = self.get_metadata(ParentNodeProvider, element, None)
        return (
            isinstance(subscript, cst.Subscript)
            and isinstance(subscript.value, cst.Call)
            and _callee_leaf_name(subscript.value) in HISTORICAL_FIXTURE_HELPERS
        )

    def _is_provider_fixture_builder_keyword(self, node: cst.CSTNode) -> bool:
        if not isinstance(node, cst.Name) or self.path not in PROVIDER_RAW_FIXTURE_CALLS:
            return False
        parent = self.get_metadata(ParentNodeProvider, node, None)
        call = self.get_metadata(ParentNodeProvider, parent, None)
        return (
            isinstance(parent, cst.Arg)
            and parent.keyword is node
            and isinstance(call, cst.Call)
            and _callee_leaf_name(call) in PROVIDER_RAW_FIXTURE_CALLS[self.path]
        )

    def _is_codex_raw_provider_literal(self, node: cst.CSTNode) -> bool:
        if self.path != "src/orchestrator/runners/agents/codex/common.py":
            return False
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None:
            if (
                isinstance(parent, cst.FunctionDef)
                and parent.name.value in CODEX_RAW_PROVIDER_FUNCTIONS
            ):
                return True
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        return False

    def visit_Attribute(self, node: cst.Attribute) -> None:
        if (
            node.attr.value in FIELD_RENAMES
            and not self._is_owner(node, _expression_path(node.value))
            and not self._is_internal_metric_context(node)
            and not self._is_flat_metric_context(node)
            and not _is_openhands_raw_cache_attribute(node)
            and not self._is_test_internal_metric_context(node)
        ):
            self._diagnose(node.attr, node.attr.value)

    def visit_Arg(self, node: cst.Arg) -> None:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if (
            node.keyword is not None
            and node.keyword.value in FIELD_RENAMES
            and (
                not isinstance(parent, cst.Call)
                or (
                    not _is_telemetry_constructor(parent)
                    and _expression_path(parent.func) not in INTERNAL_METRIC_CALLS
                    and (
                        not self._is_flat_metric_context(node)
                        or _expression_path(parent.func) in RAW_METRIC_CALLEES
                    )
                )
            )
            and (
                not isinstance(parent, cst.Call)
                or _callee_leaf_name(parent) not in RAW_METRIC_CALLEES
            )
        ):
            self._diagnose(node.keyword, node.keyword.value)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if not isinstance(node.target, cst.Name) or node.target.value not in FIELD_RENAMES:
            return
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None and not isinstance(parent, (cst.ClassDef, cst.FunctionDef)):
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        if (
            not isinstance(parent, cst.ClassDef)
            or parent.name.value not in INTERNAL_TELEMETRY_TYPES
        ):
            self._diagnose(node.target, node.target.value)

    def visit_Dict(self, node: cst.Dict) -> None:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if isinstance(parent, cst.Arg):
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        if (isinstance(parent, cst.Call) and _is_telemetry_validation(parent)) or (
            self._is_flat_metric_context(node)
            or self._is_test_internal_event_payload(node)
            or self._is_provider_fixture_raw_dictionary(node)
        ):
            return
        for element in node.elements:
            if isinstance(element, cst.DictElement) and isinstance(element.key, cst.SimpleString):
                value = element.key.evaluated_value
                if isinstance(value, str) and value in FIELD_RENAMES:
                    self._diagnose(element.key, value)

    def visit_SimpleString(self, node: cst.SimpleString) -> None:
        value = node.evaluated_value
        if not isinstance(value, str) or value not in FIELD_RENAMES:
            return
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if isinstance(parent, cst.DictElement):
            return
        is_boundary_extraction = False
        if isinstance(parent, cst.Arg):
            call = self.get_metadata(ParentNodeProvider, parent, None)
            is_boundary_extraction = (
                isinstance(call, cst.Call)
                and isinstance(call.func, cst.Attribute)
                and call.func.attr.value == "get"
                and isinstance(call.func.value, cst.Name)
                and call.func.value.value in PROVIDER_RECEIVER_NAMES
            )
        elif isinstance(parent, cst.Index):
            subscript = self.get_metadata(ParentNodeProvider, parent, None)
            if isinstance(subscript, cst.SubscriptElement):
                subscript = self.get_metadata(ParentNodeProvider, subscript, None)
            is_boundary_extraction = (
                isinstance(subscript, cst.Subscript)
                and isinstance(subscript.value, cst.Name)
                and subscript.value.value in PROVIDER_RECEIVER_NAMES
            )
        if self._is_codex_raw_provider_literal(node):
            return
        if (
            not (
                self.is_provider_boundary and value in PROVIDER_RAW_KEYS and is_boundary_extraction
            )
            and not (
                self._is_flat_metric_context(node) and self._is_internal_mapping_subscript(node)
            )
            and not self._is_raw_storage_literal_context(node)
        ):
            self._diagnose(node, value)


def transform_source(source: str, *, path: str) -> str:
    """Return *source* with proven internal telemetry vocabulary renamed."""
    module = cst.parse_module(source)
    owners = _TelemetryOwnerCollector()
    wrapper = MetadataWrapper(module)
    wrapper.visit(owners)
    return wrapper.visit(_OtelVocabularyTransformer(events=owners.events, path=path)).code


def diagnose_source(source: str, *, path: str) -> tuple[str, ...]:
    """Return deterministic diagnostics for dictionary keys requiring review."""
    module = cst.parse_module(source)
    owners = _TelemetryOwnerCollector()
    wrapper = MetadataWrapper(module)
    wrapper.visit(owners)
    visitor = _AmbiguousDictionaryVisitor(path, owners.events)
    wrapper.visit(visitor)
    return tuple(visitor.diagnostics)


@dataclass(frozen=True)
class _SourceChange:
    path: Path
    transformed: str
    diagnostics: tuple[str, ...]


def _python_sources(root: Path) -> Iterable[Path]:
    for directory in (root / "src", root / "scripts", root / "tests"):
        if directory.exists():
            yield from sorted(
                path for path in directory.rglob("*.py") if "__pycache__" not in path.parts
            )


def _changes(root: Path) -> list[_SourceChange]:
    changes: list[_SourceChange] = []
    for file_path in _python_sources(root):
        source = file_path.read_text(encoding="utf-8")
        relative_path = file_path.relative_to(root).as_posix()
        transformed = transform_source(source, path=relative_path)
        diagnostics = diagnose_source(source, path=relative_path)
        if transformed != source or diagnostics:
            changes.append(_SourceChange(file_path, transformed, diagnostics))
    return changes


def _report(changes: Sequence[_SourceChange], root: Path) -> None:
    for change in changes:
        if change.transformed != change.path.read_text(encoding="utf-8"):
            print(f"EDIT {change.path.relative_to(root)}")
        for diagnostic in change.diagnostics:
            print(f"DIAGNOSTIC {diagnostic}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bounded codemod inventory, application, or repository guard."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report proposed edits without writing")
    mode.add_argument("--apply", action="store_true", help="write proven identifier changes")
    mode.add_argument(
        "--assert-clean", action="store_true", help="fail when edits or diagnostics remain"
    )
    arguments = parser.parse_args(argv)

    root = Path.cwd()
    changes = _changes(root)
    _report(changes, root)
    if arguments.apply:
        for change in changes:
            if change.transformed != change.path.read_text(encoding="utf-8"):
                change.path.write_text(change.transformed, encoding="utf-8")
    return 1 if arguments.assert_clean and changes else 0


if __name__ == "__main__":
    raise SystemExit(main())
