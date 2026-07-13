#!/usr/bin/env python3
"""Route non-D1-D6 EventEnvelope field reads through typed serialization."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import libcst as cst


_EXEMPT_FUNCTIONS = {
    "src/orchestrator/graph/_commands.py": {"apply_command"},
    "src/orchestrator/graph/callbacks.py": {"_history_payload_value"},
    "src/orchestrator/graph/projections.py": {
        "reduce_compact_output_record_accepted",
        "reduce_d3_legacy_record_replay",
        "_add_record_summary_positions",
        "project_gatekeeper_report",
        "_latest_lease_generation",
    },
    "src/orchestrator/graph_runtime/dispatch.py": {
        "_record_start_heartbeat",
        "_dispatch_snapshot_cleanup",
        "_bound_file_state_snapshot",
    },
    "src/orchestrator/graph_runtime/store.py": {
        "_is_callback_history_event",
        "_lease_update_ids",
        "_input_bound_edge_ids_needing_ports",
    },
}


def _event_payload(node: cst.BaseExpression) -> bool:
    return (
        isinstance(node, cst.Attribute)
        and isinstance(node.value, cst.Name)
        and node.value.value == "event"
        and isinstance(node.attr, cst.Name)
        and node.attr.value == "payload"
    )


class _Transformer(cst.CSTTransformer):
    def __init__(self, path: str) -> None:
        self._path = path
        self._functions: list[str] = []
        self.changes = 0

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._functions.append(node.name.value)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        self._functions.pop()
        return updated_node

    def _exempt(self) -> bool:
        return bool(
            self._functions and self._functions[-1] in _EXEMPT_FUNCTIONS.get(self._path, set())
        )

    def _serialized_payload(self) -> cst.Call:
        return cst.Call(cst.Name("event_payload_json"), (cst.Arg(cst.Name("event")),))

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if (
            not self._exempt()
            and isinstance(original_node.value, cst.Attribute)
            and _event_payload(original_node.value)
            and original_node.attr.value == "get"
        ):
            self.changes += 1
            return updated_node.with_changes(value=self._serialized_payload())
        return updated_node

    def leave_Subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> cst.BaseExpression:
        if not self._exempt() and _event_payload(original_node.value):
            self.changes += 1
            return updated_node.with_changes(value=self._serialized_payload())
        return updated_node


def transform_source(source: str, path: str) -> tuple[str, int]:
    transformer = _Transformer(path)
    transformed = cst.parse_module(source).visit(transformer).code
    return transformed, transformer.changes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--assert-clean", action="store_true")
    args = parser.parse_args(argv)
    if args.apply == args.assert_clean:
        parser.error("choose exactly one of --apply or --assert-clean")
    root = Path(".")
    changed: list[str] = []
    for base in (root / "src/orchestrator/graph", root / "src/orchestrator/graph_runtime"):
        for path in sorted(base.rglob("*.py")):
            source = path.read_text()
            if "event.payload.get" not in source and "event.payload[" not in source:
                continue
            relative = path.relative_to(root).as_posix()
            transformed, changes = transform_source(source, relative)
            if changes and transformed != source:
                changed.append(relative)
                if args.apply:
                    path.write_text(transformed)
    if changed:
        print("\n".join(changed))
    return 1 if args.assert_clean and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
