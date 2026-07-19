"""Mechanically migrate internal token-accounting names to OTel vocabulary.

Provider payload keys intentionally remain wire-format strings.  This codemod
only changes Python identifiers and dictionary keys when their owner proves
they are part of an internal telemetry contract; uncertain dictionary keys are
reported for an explicit human decision.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Sequence
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

PROVIDER_RECEIVER_NAMES = frozenset({"payload", "response", "usage"})

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
    }
)


def _expression_path(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        parent = _expression_path(node.value)
        return f"{parent}.{node.attr.value}" if parent else None
    return None


def _is_provider_boundary(path: str) -> bool:
    return path.startswith(PROVIDER_BOUNDARY_PATH_PREFIXES)


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
        self, target: cst.BaseAssignTargetExpression, value: cst.BaseExpression, node: cst.CSTNode
    ) -> None:
        path = _expression_path(target)
        if path:
            key = (id(self.get_metadata(ScopeProvider, node)), path)
            position = self.get_metadata(PositionProvider, node).start
            if self._is_conditional(node):
                kind = _OwnershipEventKind.UNCERTAIN_ASSIGNMENT
            elif isinstance(value, cst.Call) and _is_telemetry_constructor(value):
                kind = _OwnershipEventKind.TELEMETRY_OWNER
            else:
                kind = _OwnershipEventKind.NON_TELEMETRY_KILL
            self.events.setdefault(key, []).append(
                _OwnershipEvent((position.line, position.column), kind)
            )

    def visit_Assign(self, node: cst.Assign) -> None:
        for target in node.targets:
            if isinstance(target.target, (cst.Name, cst.Attribute)):
                self._record(target.target, node.value, node)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if node.value is not None and isinstance(node.target, (cst.Name, cst.Attribute)):
            self._record(node.target, node.value, node)


class _OtelVocabularyTransformer(cst.CSTTransformer):
    """Apply only identifier changes whose CST owner establishes their meaning."""

    METADATA_DEPENDENCIES = (ParentNodeProvider, PositionProvider, ScopeProvider)

    def __init__(
        self,
        *,
        events: dict[tuple[int, str], list[_OwnershipEvent]],
    ) -> None:
        self.events = events

    def _is_owner(self, node: cst.CSTNode, path: str | None) -> bool:
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
            self._is_owner(original_node, _expression_path(original_node.value))
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
            and _is_telemetry_constructor(parent)
            and updated_node.keyword is not None
            and updated_node.keyword.value in FIELD_RENAMES
        ):
            return updated_node.with_changes(
                keyword=updated_node.keyword.with_changes(
                    value=FIELD_RENAMES[updated_node.keyword.value]
                )
            )
        return updated_node

    def leave_Dict(self, original_node: cst.Dict, updated_node: cst.Dict) -> cst.Dict:
        parent = self.get_metadata(ParentNodeProvider, original_node, None)
        if isinstance(parent, cst.Arg):
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        if not isinstance(parent, cst.Call) or not _is_telemetry_validation(parent):
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
        return updated_node.with_changes(elements=elements)


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
        self.diagnostics: list[str] = []

    def _diagnose(self, node: cst.CSTNode, name: str) -> None:
        position = self.get_metadata(PositionProvider, node).start
        self.diagnostics.append(
            f"{self.path}:{position.line}:{position.column}: ambiguous telemetry field {name!r}; left unchanged"
        )

    def _is_owner(self, node: cst.CSTNode, path: str | None) -> bool:
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

    def visit_Attribute(self, node: cst.Attribute) -> None:
        if node.attr.value in FIELD_RENAMES and not self._is_owner(
            node, _expression_path(node.value)
        ):
            self._diagnose(node.attr, node.attr.value)

    def visit_Arg(self, node: cst.Arg) -> None:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if (
            node.keyword is not None
            and node.keyword.value in FIELD_RENAMES
            and (not isinstance(parent, cst.Call) or not _is_telemetry_constructor(parent))
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
        if isinstance(parent, cst.Call) and _is_telemetry_validation(parent):
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
        if not (
            self.is_provider_boundary and value in PROVIDER_RAW_KEYS and is_boundary_extraction
        ):
            self._diagnose(node, value)


def transform_source(source: str, *, path: str) -> str:
    """Return *source* with proven internal telemetry vocabulary renamed."""
    del path
    module = cst.parse_module(source)
    owners = _TelemetryOwnerCollector()
    wrapper = MetadataWrapper(module)
    wrapper.visit(owners)
    return wrapper.visit(_OtelVocabularyTransformer(events=owners.events)).code


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
