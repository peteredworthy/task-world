"""Inject explicit graph catalogs at mechanical replay call sites."""

from __future__ import annotations

import argparse
from pathlib import Path

import libcst as cst


TARGETS = {"GraphEventStore": 1, "reduce_event": 2, "rebuild_projection": 1, "build_projection": 1}
PROJECT_TARGETS = {
    "project_decision_view",
    "project_final_invariant_blockers",
    "project_graph_topology",
    "project_leases",
    "project_lease_view",
    "project_node_metadata",
    "project_node_states",
    "project_planner_chain",
    "project_planner_freshness_packet",
    "project_planner_session",
    "project_ready_nodes",
    "project_requirement_freshness_facts",
    "project_requirement_revisions",
    "project_residue_report",
    "project_run_state",
    "project_scheduler_view",
    "project_support_evidence_freshness",
    "project_task_states",
}


class CatalogInjector(cst.CSTTransformer):
    def __init__(self) -> None:
        self.changed = False

    def leave_Call(self, original: cst.Call, updated: cst.Call) -> cst.Call:
        if not isinstance(updated.func, cst.Name):
            return updated
        if updated.func.value == "GraphEventStore" and len(updated.args) == 2:
            first = updated.args[0].value
            if (
                isinstance(first, cst.Call)
                and isinstance(first.func, cst.Name)
                and first.func.value == "build_graph_catalog"
            ):
                self.changed = True
                return updated.with_changes(args=(updated.args[1], updated.args[0]))
        expected = TARGETS.get(updated.func.value)
        mechanical = expected is not None and len(updated.args) == expected
        positional = [arg for arg in updated.args if arg.keyword is None]
        project_call = updated.func.value in PROJECT_TARGETS and len(positional) == 1
        if not mechanical and not project_call:
            return updated
        self.changed = True
        catalog = cst.Arg(cst.Call(cst.Name("build_graph_catalog")))
        if updated.func.value == "GraphEventStore":
            return updated.with_changes(args=(*updated.args, catalog))
        return updated.with_changes(args=(catalog, *updated.args))


def transform(source: str) -> tuple[str, bool]:
    module = cst.parse_module(source)
    injector = CatalogInjector()
    changed = module.visit(injector)
    if not injector.changed:
        return source, False
    body = list(changed.body)
    import_line = cst.parse_statement("from orchestrator.graph import build_graph_catalog\n")
    if "build_graph_catalog" not in source:
        insert_at = next(
            (i for i, node in enumerate(body) if not isinstance(node, cst.SimpleStatementLine)), 0
        )
        body.insert(insert_at, import_line)
        changed = changed.with_changes(body=tuple(body))
    return changed.code, True


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--assert-clean", action="store_true")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    dirty: list[Path] = []
    for root in args.paths:
        paths = root.rglob("*.py") if root.is_dir() else (root,)
        for path in paths:
            source = path.read_text()
            output, changed = transform(source)
            if not changed:
                continue
            dirty.append(path)
            if args.apply:
                path.write_text(output)
    if not args.apply:
        for path in dirty:
            print(path)
    return 1 if args.assert_clean and dirty else 0


if __name__ == "__main__":
    raise SystemExit(main())
