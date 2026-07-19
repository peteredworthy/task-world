"""Mechanically migrate internal token-accounting names to OTel vocabulary.

Provider payload keys intentionally remain wire-format strings.  This codemod
only changes Python identifiers and dictionary keys when their owner proves
they are part of an internal telemetry contract; uncertain dictionary keys are
reported for an explicit human decision.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import libcst as cst
import libcst.matchers as m
from libcst.metadata import MetadataWrapper, ParentNodeProvider, PositionProvider

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
    }
)

PROVIDER_BOUNDARY_PATH_PREFIXES = (
    "src/orchestrator/runners/agents/codex/",
    "src/orchestrator/runners/agents/claude_cli/",
    "src/orchestrator/runners/agents/openhands/",
)

_TELEMETRY_VARIABLES = frozenset({"telemetry", "usage", "metrics", "token_usage"})


def _is_provider_boundary(path: str) -> bool:
    return path.startswith(PROVIDER_BOUNDARY_PATH_PREFIXES)


def _is_telemetry_constructor(call: cst.Call) -> bool:
    """Return whether a call's name identifies an internal telemetry object."""
    if not m.matches(call.func, m.Name()):
        return False
    assert isinstance(call.func, cst.Name)
    return call.func.value.endswith(("Usage", "Metrics", "Cost"))


def _is_telemetry_attribute(attribute: cst.Attribute) -> bool:
    """Return whether an attribute receiver conventionally owns usage fields."""
    return isinstance(attribute.value, cst.Name) and attribute.value.value in _TELEMETRY_VARIABLES


def _dict_is_telemetry_contract(node: cst.Dict) -> bool:
    """Require multiple canonical candidates before changing string dictionary keys."""
    keys = [
        element.key.evaluated_value
        for element in node.elements
        if isinstance(element, cst.DictElement)
        and isinstance(element.key, cst.SimpleString)
        and isinstance(element.key.evaluated_value, str)
        and element.key.evaluated_value in FIELD_RENAMES
    ]
    return len(keys) >= 2


class _OtelVocabularyTransformer(cst.CSTTransformer):
    """Apply only identifier changes whose CST owner establishes their meaning."""

    METADATA_DEPENDENCIES = (ParentNodeProvider,)

    def __init__(self, *, is_provider_boundary: bool) -> None:
        self.is_provider_boundary = is_provider_boundary

    def _is_class_field(self, node: cst.CSTNode) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None:
            if isinstance(parent, cst.FunctionDef):
                return False
            if isinstance(parent, cst.ClassDef):
                return True
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
        if _is_telemetry_attribute(original_node) and updated_node.attr.value in FIELD_RENAMES:
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
        if self.is_provider_boundary or not _dict_is_telemetry_contract(original_node):
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
                            f"{original_element.key.value[-1]}"
                            f"{FIELD_RENAMES[original_element.key.evaluated_value]}"
                            f"{original_element.key.value[-1]}"
                        )
                    )
                )
            else:
                elements.append(updated_element)
        return updated_node.with_changes(elements=elements)


class _AmbiguousDictionaryVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, path: str) -> None:
        self.path = path
        self.is_provider_boundary = _is_provider_boundary(path)
        self.diagnostics: list[str] = []

    def visit_Dict(self, node: cst.Dict) -> None:
        if self.is_provider_boundary or _dict_is_telemetry_contract(node):
            return
        for element in node.elements:
            if (
                isinstance(element, cst.DictElement)
                and isinstance(element.key, cst.SimpleString)
                and isinstance(element.key.evaluated_value, str)
                and element.key.evaluated_value in FIELD_RENAMES
            ):
                position = self.get_metadata(PositionProvider, element.key).start
                self.diagnostics.append(
                    f"{self.path}:{position.line}:{position.column}: ambiguous telemetry dictionary key "
                    f"{element.key.evaluated_value!r}; left unchanged"
                )


def transform_source(source: str, *, path: str) -> str:
    """Return *source* with proven internal telemetry vocabulary renamed."""
    wrapper = MetadataWrapper(cst.parse_module(source))
    return wrapper.visit(
        _OtelVocabularyTransformer(is_provider_boundary=_is_provider_boundary(path))
    ).code


def diagnose_source(source: str, *, path: str) -> tuple[str, ...]:
    """Return deterministic diagnostics for dictionary keys requiring review."""
    wrapper = MetadataWrapper(cst.parse_module(source))
    visitor = _AmbiguousDictionaryVisitor(path)
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
