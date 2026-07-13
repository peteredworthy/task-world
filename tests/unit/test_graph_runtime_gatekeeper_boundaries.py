from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.graph import GatekeeperVerdict as DomainGatekeeperVerdict
from orchestrator.graph_runtime import GatekeeperVerdict, metadata_from_file_state_record


def _verdict_values() -> dict[str, object]:
    return {
        "path": "artifact.xml",
        "classification": "test_artifact",
        "confidence": 0.5,
        "rationale": "test output",
        "model_id": "model-1",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "wall_time_ms": 0,
    }


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_runtime_gatekeeper_verdict_accepts_confidence_boundaries(confidence: float) -> None:
    values = _verdict_values()
    values["confidence"] = confidence
    assert GatekeeperVerdict.model_validate(values).confidence == confidence


def test_runtime_exports_the_graph_domain_gatekeeper_verdict() -> None:
    assert GatekeeperVerdict is DomainGatekeeperVerdict


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("confidence", "0.5"),
        ("input_tokens", -1),
        ("input_tokens", 1.5),
        ("input_tokens", "1"),
        ("cost_usd", -0.01),
        ("cost_usd", "0.01"),
        ("wall_time_ms", -1),
        ("wall_time_ms", True),
    ],
)
def test_runtime_gatekeeper_verdict_rejects_invalid_metrics(field: str, value: object) -> None:
    values = _verdict_values()
    values[field] = value
    with pytest.raises(ValidationError):
        GatekeeperVerdict.model_validate(values)


def test_runtime_gatekeeper_verdict_rejects_empty_model_identity() -> None:
    values = _verdict_values()
    values["model_id"] = ""
    with pytest.raises(ValidationError):
        GatekeeperVerdict.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("size_bytes", -1),
        ("size_bytes", 1.5),
        ("size_bytes", "1"),
        ("size_bytes", True),
        ("entropy", -0.01),
        ("entropy", 8.01),
        ("entropy", "1.0"),
        ("entropy", False),
    ],
)
def test_metadata_extraction_rejects_invalid_numeric_values(field: str, value: object) -> None:
    entry = {
        "path": "artifact.xml",
        "needs_gatekeeper": True,
        "classification": "unknown_ignored",
        "source": "ignored",
        "matched_rule": "none",
        field: value,
    }
    with pytest.raises(ValidationError):
        metadata_from_file_state_record({"record_id": "record-1", "residue": [entry]}, max_items=1)


@pytest.mark.parametrize(
    ("record_field", "entry_field"),
    [
        ("record_id", None),
        (None, "path"),
        (None, "source"),
        (None, "classification"),
        (None, "matched_rule"),
    ],
)
def test_metadata_extraction_rejects_missing_required_metadata(
    record_field: str | None, entry_field: str | None
) -> None:
    entry: dict[str, object] = {
        "path": "artifact.xml",
        "needs_gatekeeper": True,
        "classification": "unknown_ignored",
        "source": "ignored",
        "matched_rule": "none",
        "size_bytes": None,
        "entropy": None,
    }
    record: dict[str, object] = {"record_id": "record-1", "residue": [entry]}
    if record_field is not None:
        record.pop(record_field)
    if entry_field is not None:
        entry.pop(entry_field)
    with pytest.raises(ValidationError):
        metadata_from_file_state_record(record, max_items=1)
