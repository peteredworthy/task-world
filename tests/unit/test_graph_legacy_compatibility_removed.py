"""Task 13 guard for the retired graph compatibility register."""

from __future__ import annotations

import ast
from pathlib import Path


def test_graph_sources_do_not_retain_retired_compatibility_names() -> None:
    root = Path(__file__).parents[2] / "src" / "orchestrator"
    retired_names = {
        "lease_suspended",
        "graph_patch_proposed",
        "requirement_revision_proposed",
        "authority_resolution_recorded",
        "environment_failure_accepted",
        "check_result_classified",
        "reduce_legacy_event",
        "_graph_patch_payload_for_event",
        "_open_proposal_blockers",
        "_checkpoint_output_record_payload",
        "_parse_output_record_payload",
        "_generic_output_record_payload",
        "_legacy_output_record_payload",
        "_verification_payload_outcome",
        "_check_result_payload_status",
        "_gap_classification_payload_classification",
        "_authority_revision_blockers",
        "_requires_authority_resolution",
        "LegacyEventPayload",
        "source_schema_version",
        "_D3_LEGACY_RECORD_EVENT_TYPES",
        "LegacyFutureCommandEffects",
        "Task 9 deletion seam",
    }
    source = "\n".join(
        path.read_text()
        for package in ("graph", "graph_runtime")
        for path in (root / package).rglob("*.py")
    )

    assert not {name for name in retired_names if name in source}


def test_graph_sources_do_not_define_legacy_adapter_classes() -> None:
    root = Path(__file__).parents[2] / "src" / "orchestrator"
    offenders: list[str] = []
    for package in ("graph", "graph_runtime"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text())
            offenders.extend(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)
                and node.name.startswith("Legacy")
                and node.name.endswith(("Adapter", "Effects", "Compatibility", "Shim", "Wrapper"))
            )

    assert offenders == []


def test_strict_payload_does_not_offer_d_series_mapping_methods() -> None:
    root = Path(__file__).parents[2] / "src" / "orchestrator" / "graph" / "payloads.py"
    payload_source = root.read_text()

    assert "def __getitem__" not in payload_source
    assert "def get(" not in payload_source
    assert "def items(" not in payload_source


def test_graph_sources_do_not_retain_retired_payload_adapter_patterns() -> None:
    root = Path(__file__).parents[2] / "src" / "orchestrator"
    source = "\n".join(
        path.read_text()
        for package in ("graph", "graph_runtime")
        for path in (root / package).rglob("*.py")
    )

    retired_adapter_patterns = {
        "_output_record_model_for_payload",
        "_normalized_output_record_payload",
        "fallback = _",
        'port in {"graph_patch_proposal", "graph_patch"}',
    }

    assert not {pattern for pattern in retired_adapter_patterns if pattern in source}
