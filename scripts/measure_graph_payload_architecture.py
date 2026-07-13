#!/usr/bin/env python3
"""Emit deterministic catalog-wide graph payload architecture metrics."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.codemods.w5_strict_payload_cutover import (
    DOMAIN_MIGRATIONS,
    DomainMigration,
    run_migration,
)
from scripts.w5_payload_ast_inventory import scan_graph_payload_architecture


CANONICAL_ROOTS = (
    Path("src/orchestrator/graph"),
    Path("src/orchestrator/graph_runtime"),
    Path("src/orchestrator/api"),
    Path("src/orchestrator/db"),
    Path("src/orchestrator/workflow"),
)

_RULE_METRICS = {
    "W5RAW_PAYLOAD_READ": "event_payload_raw_reads_in_kernel",
    "W5RAW_BOUNDARY_DICT": "raw_event_or_command_boundary_dict_annotations",
    "W5DIRECT_DICTIONARY_EVENT": "direct_dictionary_event_construction_sites",
    "W5PAYLOAD_ALLOWLIST": "hand_maintained_payload_field_allowlists",
    "W5BEFORE_PAYLOAD_NORMALIZER": "w5_legacy_payload_before_validators",
    "W5TOP_LEVEL_PAYLOAD_EXTRA": "w5_top_level_payload_extra_fields",
    "W5CENTRAL_COMMAND_HANDLERS": "central_command_handler_tables",
    "W5CENTRAL_REDUCE_EVENT_BRANCH": "central_reduce_event_name_branches",
}

EXPECTED_METRICS = {
    "registered_event_specs": 44,
    "registered_command_specs": 23,
    "event_payload_raw_reads_in_kernel": 0,
    "raw_event_or_command_boundary_dict_annotations": 0,
    "direct_dictionary_event_construction_sites": 0,
    "hand_maintained_payload_field_allowlists": 0,
    "w5_legacy_payload_before_validators": 0,
    "w5_top_level_payload_extra_fields": 0,
    "central_command_handler_tables": 0,
    "central_reduce_event_name_branches": 0,
    "eligible_ast_cst_migration_sites_remaining": 0,
    "codemod_second_run_changes": 0,
    "unclassified_dynamic_event_or_command_sites": 0,
}


def measure(
    root: Path = Path("."),
    *,
    migrations: Mapping[str, DomainMigration] | None = None,
) -> dict[str, object]:
    report = scan_graph_payload_architecture(
        [candidate for path in CANONICAL_ROOTS if (candidate := root / path).exists()]
    )
    rule_counts = Counter(fact.rule for fact in report.architecture_facts)
    unclassified = sum(
        site.classification == "unresolved"
        for site in (*report.dynamic_event_sites, *report.dynamic_command_sites)
    )
    registered_events = {
        name
        for site in report.dynamic_event_sites
        if site.classification == "typed_specification"
        for name in site.resolved_values
    }
    selected_migrations = DOMAIN_MIGRATIONS if migrations is None else migrations
    migration_results = tuple(
        run_migration(migration, root, "measure")
        for _, migration in sorted(selected_migrations.items())
    )
    eligible_sites = sum(result.eligible_sites for result in migration_results)
    second_run_changes = sum(result.second_run_changes for result in migration_results)
    metrics = {
        "registered_event_specs": len(registered_events),
        "registered_command_specs": len(report.command_names),
        **{metric: rule_counts[rule] for rule, metric in _RULE_METRICS.items()},
        "eligible_ast_cst_migration_sites_remaining": eligible_sites,
        "codemod_second_run_changes": second_run_changes,
        "unclassified_dynamic_event_or_command_sites": unclassified,
    }
    deferred_sites = [
        f"{fact.path}:{fact.line}:{fact.column}: {fact.rule}: {fact.expression}"
        for fact in report.deferred_architecture_facts
    ]
    return {
        "metrics": metrics,
        "deferred_compatibility": {
            "site_count": len(deferred_sites),
            "sites": deferred_sites,
        },
    }


def _markdown(report: dict[str, object]) -> str:
    metrics = report["metrics"]
    deferred = report["deferred_compatibility"]
    assert isinstance(metrics, dict)
    assert isinstance(deferred, dict)
    lines = [
        "# Graph Payload Architecture Metrics",
        "",
        "| Metric | Count |",
        "|---|---:|",
        *(f"| `{name}` | {value} |" for name, value in metrics.items()),
        "",
        "## Deferred D1-D6 Compatibility",
        "",
        f"Sites: {deferred['site_count']}",
        "",
    ]
    sites = deferred["sites"]
    assert isinstance(sites, list)
    lines.extend(f"- `{site}`" for site in sites)
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    report = measure()
    if args.format == "markdown":
        print(_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["metrics"] == EXPECTED_METRICS else 1


if __name__ == "__main__":
    raise SystemExit(main())
