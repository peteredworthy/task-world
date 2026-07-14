#!/usr/bin/env python3
"""Route non-D1-D6 EventEnvelope field reads through typed serialization."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Sequence

import libcst as cst
from libcst.helpers import get_full_name_for_node


def _event_payload(node: cst.BaseExpression) -> bool:
    return (
        isinstance(node, cst.Attribute)
        and isinstance(node.attr, cst.Name)
        and node.attr.value == "payload"
    )


class _Transformer(cst.CSTTransformer):
    def __init__(self, path: str) -> None:
        del path
        self.changes = 0

    def _serialized_payload(self) -> cst.Call:
        return cst.Call(cst.Name("event_payload_json"), (cst.Arg(cst.Name("event")),))

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if (
            isinstance(original_node.value, cst.Attribute)
            and _event_payload(original_node.value)
            and isinstance(original_node.value.value, cst.Name)
            and original_node.value.value.value == "event"
            and original_node.attr.value == "get"
        ):
            self.changes += 1
            return updated_node.with_changes(value=self._serialized_payload())
        return updated_node

    def leave_Subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> cst.BaseExpression:
        if (
            _event_payload(original_node.value)
            and isinstance(original_node.value.value, cst.Name)
            and original_node.value.value.value == "event"
        ):
            self.changes += 1
            return updated_node.with_changes(value=self._serialized_payload())
        return updated_node


def _event_envelope_names(source: str) -> frozenset[str]:
    """Return names declared as raw storage envelopes in a test module.

    The Task 13 migration is intentionally fail-closed for corruption fixtures:
    an explicit ``EventEnvelope`` annotation identifies a deliberate JSON
    carrier, rather than a hydrated event whose strict payload needs a JSON
    boundary for a mapping assertion.
    """

    tree = ast.parse(source)
    names: set[str] = set()

    def is_event_envelope(annotation: ast.expr | None) -> bool:
        if isinstance(annotation, ast.Name):
            return annotation.id == "EventEnvelope"
        if isinstance(annotation, ast.Attribute):
            return annotation.attr == "EventEnvelope"
        return False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                if is_event_envelope(argument.annotation):
                    names.add(argument.arg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if is_event_envelope(node.annotation):
                names.add(node.target.id)
    return frozenset(names)


def _is_raw_event_expression(expression: cst.BaseExpression, raw_names: frozenset[str]) -> bool:
    return isinstance(expression, cst.Name) and expression.value in raw_names


def _mapping_aliases(source: str) -> frozenset[str]:
    """Find local names subsequently consumed through mapping operations."""
    tree = ast.parse(source)
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            aliases.add(node.value.id)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "items"}
            and isinstance(node.func.value, ast.Name)
        ):
            aliases.add(node.func.value.id)
    return frozenset(aliases)


class _TestPayloadReadTransformer(cst.CSTTransformer):
    """Move hydrated test assertions across the explicit JSON boundary."""

    def __init__(self, raw_event_names: frozenset[str], mapping_aliases: frozenset[str]) -> None:
        self.raw_event_names = raw_event_names
        self.mapping_aliases = mapping_aliases
        self.changes = 0

    @staticmethod
    def _serialized_payload(event: cst.BaseExpression) -> cst.Call:
        return cst.Call(cst.Name("event_payload_json"), (cst.Arg(event),))

    def _is_current_payload(self, node: cst.BaseExpression) -> bool:
        return _event_payload(node) and not _is_raw_event_expression(
            node.value, self.raw_event_names
        )

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> cst.BaseSmallStatement:
        """Serialize a hydrated payload when a test binds it as a mapping.

        A whole-payload alias is a JSON-boundary assertion just as a direct
        subscript is.  Keep explicitly annotated raw ``EventEnvelope``
        corruption carriers unchanged so those tests can still exercise bad
        persisted JSON directly.
        """
        if len(original_node.targets) != 1 or not isinstance(
            original_node.targets[0].target, cst.Name
        ):
            return updated_node
        target_name = original_node.targets[0].target.value
        if (
            target_name in self.mapping_aliases
            and isinstance(original_node.value, cst.Call)
            and isinstance(original_node.value.func, cst.Name)
            and original_node.value.func.value == "next"
            and len(original_node.value.args) == 1
            and isinstance(original_node.value.args[0].value, cst.GeneratorExp)
            and self._is_current_payload(original_node.value.args[0].value.elt)
            and isinstance(updated_node.value, cst.Call)
            and isinstance(updated_node.value.args[0].value, cst.GeneratorExp)
        ):
            generator = updated_node.value.args[0].value
            self.changes += 1
            return updated_node.with_changes(
                value=updated_node.value.with_changes(
                    args=(
                        updated_node.value.args[0].with_changes(
                            value=generator.with_changes(
                                elt=self._serialized_payload(generator.elt.value)
                            )
                        ),
                        *updated_node.value.args[1:],
                    )
                )
            )
        if self._is_current_payload(original_node.value):
            self.changes += 1
            return updated_node.with_changes(
                value=self._serialized_payload(original_node.value.value)
            )
        return updated_node

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if (
            isinstance(original_node.value, cst.Attribute)
            and self._is_current_payload(original_node.value)
            and original_node.attr.value in {"get", "items"}
        ):
            self.changes += 1
            return updated_node.with_changes(
                value=self._serialized_payload(original_node.value.value)
            )
        return updated_node

    def leave_Subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> cst.BaseExpression:
        if self._is_current_payload(original_node.value):
            self.changes += 1
            return updated_node.with_changes(
                value=self._serialized_payload(original_node.value.value)
            )
        return updated_node


class _EnsureJsonBoundaryImport(cst.CSTTransformer):
    def __init__(self) -> None:
        self.found_graph_import = False

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom:
        if (
            updated_node.module is None
            or get_full_name_for_node(updated_node.module) != "orchestrator.graph"
            or isinstance(updated_node.names, cst.ImportStar)
        ):
            return updated_node
        self.found_graph_import = True
        if any(
            isinstance(alias, cst.ImportAlias)
            and isinstance(alias.name, cst.Name)
            and alias.name.value == "event_payload_json"
            for alias in updated_node.names
        ):
            return updated_node
        return updated_node.with_changes(
            names=(*updated_node.names, cst.ImportAlias(cst.Name("event_payload_json")))
        )


def transform_test_source(source: str, path: str) -> tuple[str, int]:
    """Rewrite only hydrated/current test payload mapping reads.

    Test assertions that need mapping behavior serialize hydrated events through
    ``event_payload_json``.  Explicit raw ``EventEnvelope`` carriers and
    already-typed nested attributes are left alone.
    """

    if not path.startswith("tests/"):
        return source, 0
    transformer = _TestPayloadReadTransformer(
        _event_envelope_names(source), _mapping_aliases(source)
    )
    module = cst.parse_module(source).visit(transformer)
    if not transformer.changes:
        return source, 0
    import_transformer = _EnsureJsonBoundaryImport()
    module = module.visit(import_transformer)
    if not import_transformer.found_graph_import:
        insert_at = _after_future_imports(module.body)
        boundary_import = cst.SimpleStatementLine(
            body=(
                cst.ImportFrom(
                    module=cst.Attribute(cst.Name("orchestrator"), cst.Name("graph")),
                    names=(cst.ImportAlias(cst.Name("event_payload_json")),),
                ),
            )
        )
        module = module.with_changes(
            body=(*module.body[:insert_at], boundary_import, *module.body[insert_at:])
        )
    return module.code, transformer.changes


def _after_future_imports(body: Sequence[cst.BaseStatement]) -> int:
    insert_at = 0
    if (
        body
        and isinstance(body[0], cst.SimpleStatementLine)
        and len(body[0].body) == 1
        and isinstance(body[0].body[0], cst.Expr)
        and isinstance(body[0].body[0].value, cst.SimpleString)
    ):
        insert_at = 1
    for statement in body[insert_at:]:
        if not (
            isinstance(statement, cst.SimpleStatementLine)
            and len(statement.body) == 1
            and isinstance(statement.body[0], cst.ImportFrom)
            and isinstance(statement.body[0].module, cst.Name)
            and statement.body[0].module.value == "__future__"
        ):
            break
        insert_at += 1
    return insert_at


def normalize_test_imports(source: str) -> str:
    """Move a standalone boundary import behind a future import, if present."""

    module = cst.parse_module(source)
    boundary_imports: list[cst.SimpleStatementLine] = []
    body: list[cst.BaseStatement] = []
    for statement in module.body:
        if (
            isinstance(statement, cst.SimpleStatementLine)
            and len(statement.body) == 1
            and isinstance(statement.body[0], cst.ImportFrom)
            and get_full_name_for_node(statement.body[0].module) == "orchestrator.graph"
            and not isinstance(statement.body[0].names, cst.ImportStar)
            and len(statement.body[0].names) == 1
            and isinstance(statement.body[0].names[0].name, cst.Name)
            and statement.body[0].names[0].name.value == "event_payload_json"
        ):
            boundary_imports.append(statement)
        else:
            body.append(statement)
    if not boundary_imports:
        return source
    insert_at = _after_future_imports(body)
    return module.with_changes(body=(*body[:insert_at], *boundary_imports, *body[insert_at:])).code


def transform_source(source: str, path: str) -> tuple[str, int]:
    transformer = _Transformer(path)
    transformed = cst.parse_module(source).visit(transformer).code
    return transformed, transformer.changes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply", action="store_true")
    action.add_argument("--assert-clean", action="store_true")
    action.add_argument("--test-apply", action="store_true")
    action.add_argument("--test-normalize-imports", action="store_true")
    args = parser.parse_args(argv)
    root = Path(".")
    changed: list[str] = []
    bases = (
        (root / "tests",)
        if args.test_apply or args.test_normalize_imports
        else (root / "src/orchestrator/graph", root / "src/orchestrator/graph_runtime")
    )
    for base in bases:
        for path in sorted(base.rglob("*.py")):
            source = path.read_text()
            if not args.test_normalize_imports and ".payload" not in source:
                continue
            relative = path.relative_to(root).as_posix()
            transformed, changes = (
                transform_test_source(source, relative)
                if args.test_apply
                else (
                    (normalize_test_imports(source), 1)
                    if args.test_normalize_imports
                    else transform_source(source, relative)
                )
            )
            if changes and transformed != source:
                changed.append(relative)
                if args.apply or args.test_apply or args.test_normalize_imports:
                    path.write_text(transformed)
    if changed:
        print("\n".join(changed))
    return 1 if args.assert_clean and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
