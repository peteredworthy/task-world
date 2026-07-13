"""Contract tests for the tracked complete-read profiler."""

import argparse

import pytest

from orchestrator.graph import build_graph_catalog
from orchestrator.graph_runtime import validate_catalog_event_payload
from scripts.profile_graph_readback import SAMPLE_SOURCE, _synthetic_events, profile


def test_profiler_generates_catalog_valid_events_from_tracked_samples() -> None:
    catalog = build_graph_catalog()

    events = _synthetic_events(12, heavy_every=2, payload_kb=1)

    assert SAMPLE_SOURCE == "tests/unit/graph_catalog_samples.py"
    assert len(events) == 12
    for event in events:
        validate_catalog_event_payload(catalog, event)


@pytest.mark.asyncio
async def test_profiler_reports_complete_reader_payload_parity_and_memory() -> None:
    result = await profile(
        argparse.Namespace(
            events=8,
            heavy_every=2,
            payload_kb=1,
            iterations=1,
            db_path="",
        )
    )

    assert result["config"]["sample_source"] == SAMPLE_SOURCE
    assert result["profile"]["stored_rows"] == 8
    assert result["profile"]["wall_ms"] > 0
    assert result["profile"]["process_max_rss_bytes"] > 0
    assert len(result["readers"]) == 5
    baseline = result["readers"][0]
    for reader in result["readers"]:
        assert reader["rows"] == 8
        assert reader["payload_bytes"] == baseline["payload_bytes"]
        assert reader["tracemalloc_peak_bytes"] > 0
        assert reader["payload_parity"] is True
