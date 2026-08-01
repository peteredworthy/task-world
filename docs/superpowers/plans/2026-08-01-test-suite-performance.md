# Test Suite Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce every measured default unit run to at most 25 seconds and every measured full default run to at most 50 seconds without removing a currently selected test case or weakening isolation and coverage.

**Architecture:** Add opt-in diagnostic tooling first, capture a durable node-ID baseline, and then apply the five design stages in order. Every stage is an independently reviewable experiment: warm once, run three uncontended timings, compare selected node IDs, retain only repeatable improvements, and stop as soon as all six timing runs meet the targets.

**Tech Stack:** Python 3.12, pytest 9, pytest-xdist, pytest-asyncio, SQLAlchemy async, Alembic, FastAPI, Git, uv

## Global Constraints

- Unit target: every one of three runs of `uv run pytest tests/unit -q` must be at most 25 seconds wall time.
- Full target: every one of three runs of `uv run pytest -q` must be at most 50 seconds wall time.
- Do not move additional tests behind `slow` or `e2e` markers.
- Do not weaken assertions, reduce parameter matrices, or replace real objects with mocks.
- Keep function-level isolation unless a replacement gives equivalent isolation by construction.
- Production file databases must continue to run Alembic migrations through `init_db()`.
- Retain `uv run pytest` as the canonical command and preserve pre-commit parity.
- Keep `-n auto --dist loadfile` in the default pytest configuration.
- Make one measured optimization at a time and discard changes that do not improve repeatable wall time.
- New regression tests may add node IDs. Existing test function, class, and parameter identities may not disappear.
- A file split may change only a node ID's file prefix, must preserve the suffix after the first `::`, and must be recorded in the split map.
- Run timing commands sequentially on an otherwise idle machine; never run concurrent test commands during measurement.
- Never add load-sensitive timing assertions to pytest.
- Do not commit unless the user explicitly requests it. Each task below is deliberately commit-sized.

---

## File Structure

### Diagnostic And Selection Tooling

- Create `scripts/pytest_file_durations.py`: opt-in pytest plugin that aggregates setup, call, and teardown duration by file on the xdist controller.
- Create `scripts/compare_pytest_node_ids.py`: compare baseline and candidate collection output, including declared one-to-many file splits.
- Create `tests/unit/test_test_suite_tooling.py`: pure behavior tests for both diagnostic tools.
- Create `docs/superpowers/performance/2026-08-01-test-suite-results.md`: append-only measurement log containing commands, environment, node counts, stage decisions, and all final timings.
- Keep raw collection output and profiler JSON in `/tmp/task-world-test-performance/`; do not commit thousands of generated node IDs.

### Stage 1 Collection Manifest

- Create `tests/opt_in_suites.py`: exact whole-module slow/E2E manifests and pure pre-collection decision logic.
- Modify `tests/conftest.py`: delegate `pytest_ignore_collect` to the manifest and remove filename-derived FR acceptance marking.
- Modify `tests/unit/test_test_suite_configuration.py`: manifest existence, marker, completeness, mixed-module, and collector behavior regression tests.
- Modify the 14 `tests/integration/test_graph_fr*_acceptance.py` files listed in Task 3 to declare `pytestmark = pytest.mark.slow` explicitly.

### Stage 2 Fresh Database Setup

- Create `tests/integration/db_helpers.py`: one test-only `init_fresh_test_db(engine)` helper using metadata creation with `checkfirst=False`.
- Create `tests/integration/test_db_helpers.py`: complete-schema, repository-roundtrip, and misuse tests.
- Modify `tests/integration/conftest.py` and default integration test fixtures that initialize guaranteed-fresh databases.
- Retain `init_db()` in `tests/integration/test_database.py` initialization/migration tests, `tests/integration/test_event_log_durability.py` migration test, `tests/integration/test_migrations.py`, and conservatively `tests/integration/test_jsonl_bootstrap.py`.

### Stage 3 App Construction

- Create `scripts/profile_app_construction.py`: repeated cached `create_app()` profiler with explicit cleanup and variant comparison.
- Modify only the app-construction component demonstrated expensive by the profile.
- Extend `tests/integration/test_route_cache_isolation.py` for every newly cached immutable value and every per-app wrapper affected by the retained optimization.

### Stage 4 Xdist Tail

- Split only the measured final-tail file selected by Task 9.
- Put shared builders in a non-collectable helper such as `tests/unit/graph_commands_test_helpers.py`, never in another `test_*.py` module.
- Record the exact old-to-new file mapping in `/tmp/task-world-test-performance/split-map.json` and in the results document.

### Stage 5 Git Templates

- Modify the measured remaining real-Git setup files listed in Task 10 to copy `_unit_base_repo` or `_base_repo` before adding scenario-specific commits.
- Add focused copy-isolation coverage only if Stage 5 is reached.
- Retain direct initialization in `tests/integration/test_project_init.py` and unborn-repository coverage.

---

### Task 1: Add File-Duration And Node-Selection Tooling

**Files:**
- Create: `scripts/pytest_file_durations.py`
- Create: `scripts/compare_pytest_node_ids.py`
- Create: `tests/unit/test_test_suite_tooling.py`

**Interfaces:**
- Produces: `aggregate_reports(reports: Iterable[DurationReport]) -> tuple[FileDuration, ...]`
- Produces: `parse_collection_output(text: str) -> frozenset[str]`
- Produces: `compare_node_ids(before: Collection[str], after: Collection[str], split_map: Mapping[str, Collection[str]]) -> NodeIdComparison`
- Consumes later: every stage invokes these tools before deciding whether to retain its changes.

- [ ] **Step 1: Write failing aggregation tests**

Add tests that construct real frozen value objects rather than pytest report mocks:

```python
import pytest

from scripts.pytest_file_durations import DurationReport, aggregate_reports


def test_aggregate_reports_sums_phases_and_sorts_by_total() -> None:
    reports = (
        DurationReport("tests/unit/test_b.py::test_b", "setup", 0.2),
        DurationReport("tests/unit/test_b.py::test_b", "call", 0.5),
        DurationReport("tests/unit/test_b.py::test_b", "teardown", 0.1),
        DurationReport("tests/unit/test_a.py::test_a[x]", "call", 0.3),
        DurationReport("tests/unit/test_a.py::test_a[y]", "call", 0.4),
    )

    result = aggregate_reports(reports)

    assert [item.path for item in result] == [
        "tests/unit/test_b.py",
        "tests/unit/test_a.py",
    ]
    assert result[0].setup == 0.2
    assert result[0].call == 0.5
    assert result[0].teardown == 0.1
    assert result[0].total == pytest.approx(0.8)
    assert result[0].tests == 1
    assert result[1].tests == 2
```

Also test stable path ordering when totals tie and reject report phases outside `setup`, `call`, and `teardown`.

- [ ] **Step 2: Write failing node-ID comparison tests**

```python
from scripts.compare_pytest_node_ids import compare_node_ids, parse_collection_output


def test_parse_collection_output_ignores_pytest_noise() -> None:
    text = """
tests/unit/test_a.py::test_one
tests/unit/test_a.py::test_matrix[value]
[boundary-check] collection+AST: 0.010s | files_checked=2 ast_parsed=2
2 tests collected in 0.05s
"""
    assert parse_collection_output(text) == frozenset(
        {
            "tests/unit/test_a.py::test_one",
            "tests/unit/test_a.py::test_matrix[value]",
        }
    )


def test_compare_node_ids_allows_additions_but_not_removals() -> None:
    result = compare_node_ids(
        {"tests/unit/test_a.py::test_one"},
        {
            "tests/unit/test_a.py::test_one",
            "tests/unit/test_a.py::test_new",
        },
        {},
    )
    assert result.removed == ()
    assert result.added == ("tests/unit/test_a.py::test_new",)


def test_compare_node_ids_accepts_unique_split_remap() -> None:
    result = compare_node_ids(
        {"tests/unit/test_old.py::TestGroup::test_matrix[value]"},
        {"tests/unit/test_new_a.py::TestGroup::test_matrix[value]"},
        {"tests/unit/test_old.py": ("tests/unit/test_new_a.py", "tests/unit/test_new_b.py")},
    )
    assert result.removed == ()
    assert result.remapped == (
        (
            "tests/unit/test_old.py::TestGroup::test_matrix[value]",
            "tests/unit/test_new_a.py::TestGroup::test_matrix[value]",
        ),
    )
```

Add cases for a changed parameter ID, duplicate destination suffix, malformed collection lines, Windows separators, and a genuinely missing node.

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```bash
uv run pytest -n 0 tests/unit/test_test_suite_tooling.py -q
```

Expected: collection fails because the two scripts do not exist.

- [ ] **Step 4: Implement the pure duration model and pytest plugin**

Implement `scripts/pytest_file_durations.py` with frozen dataclasses, no timing assertions, and controller-only output:

```python
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import pytest
from _pytest.reports import TestReport
from _pytest.terminal import TerminalReporter

Phase = Literal["setup", "call", "teardown"]


@dataclass(frozen=True)
class DurationReport:
    nodeid: str
    phase: Phase
    duration: float


@dataclass(frozen=True)
class FileDuration:
    path: str
    setup: float
    call: float
    teardown: float
    total: float
    tests: int


def _node_path(nodeid: str) -> str:
    return nodeid.replace("\\", "/").split("::", 1)[0]


def aggregate_reports(reports: Iterable[DurationReport]) -> tuple[FileDuration, ...]:
    phases: dict[str, dict[str, float]] = defaultdict(
        lambda: {"setup": 0.0, "call": 0.0, "teardown": 0.0}
    )
    nodeids: dict[str, set[str]] = defaultdict(set)
    for report in reports:
        if report.phase not in {"setup", "call", "teardown"}:
            raise ValueError(f"Unsupported pytest phase: {report.phase}")
        path = _node_path(report.nodeid)
        phases[path][report.phase] += report.duration
        nodeids[path].add(report.nodeid)

    result = tuple(
        FileDuration(
            path=path,
            setup=values["setup"],
            call=values["call"],
            teardown=values["teardown"],
            total=sum(values.values()),
            tests=len(nodeids[path]),
        )
        for path, values in phases.items()
    )
    return tuple(sorted(result, key=lambda item: (-item.total, item.path)))


class _FileDurationPlugin:
    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self._reports: list[DurationReport] = []

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: TestReport) -> None:
        if report.when in {"setup", "call", "teardown"}:
            self._reports.append(
                DurationReport(report.nodeid, report.when, report.duration)
            )

    @pytest.hookimpl
    def pytest_terminal_summary(self, terminalreporter: TerminalReporter) -> None:
        if hasattr(self._config, "workerinput"):
            return
        rows = aggregate_reports(self._reports)
        limit = self._config.getoption("--file-duration-limit")
        terminalreporter.write_sep("=", "aggregate durations by file")
        for row in rows[:limit]:
            terminalreporter.write_line(
                f"{row.total:8.3f}s {row.path} "
                f"(setup={row.setup:.3f} call={row.call:.3f} "
                f"teardown={row.teardown:.3f} tests={row.tests})"
            )
        output = self._config.getoption("--file-duration-json")
        if output:
            Path(output).write_text(
                json.dumps([asdict(row) for row in rows], indent=2) + "\n"
            )


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("file durations")
    group.addoption("--file-duration-limit", type=int, default=20)
    group.addoption("--file-duration-json")


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(_FileDurationPlugin(config), "file-duration-aggregator")
```

- [ ] **Step 5: Implement collection parsing and split-aware comparison**

Implement `scripts/compare_pytest_node_ids.py` around these exact rules:

```python
from __future__ import annotations

import argparse
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NodeIdComparison:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    remapped: tuple[tuple[str, str], ...]


def _normalize(nodeid: str) -> str:
    return nodeid.strip().replace("\\", "/")


def _parts(nodeid: str) -> tuple[str, str]:
    path, separator, suffix = _normalize(nodeid).partition("::")
    if not separator or not path.endswith(".py") or not suffix:
        raise ValueError(f"Malformed pytest node ID: {nodeid!r}")
    return path, suffix


def parse_collection_output(text: str) -> frozenset[str]:
    nodeids: set[str] = set()
    for raw_line in text.splitlines():
        line = _normalize(raw_line)
        if "::" not in line or not line.split("::", 1)[0].endswith(".py"):
            continue
        _parts(line)
        if line in nodeids:
            raise ValueError(f"Duplicate pytest node ID: {line}")
        nodeids.add(line)
    return frozenset(nodeids)


def compare_node_ids(
    before: Collection[str],
    after: Collection[str],
    split_map: Mapping[str, Collection[str]],
) -> NodeIdComparison:
    normalized_before = {_normalize(nodeid) for nodeid in before}
    normalized_after = {_normalize(nodeid) for nodeid in after}
    unmatched_after = set(normalized_after)
    removed: list[str] = []
    remapped: list[tuple[str, str]] = []

    for old_nodeid in sorted(normalized_before):
        if old_nodeid in unmatched_after:
            unmatched_after.remove(old_nodeid)
            continue
        old_path, suffix = _parts(old_nodeid)
        destinations = tuple(path.replace("\\", "/") for path in split_map.get(old_path, ()))
        matches = [f"{path}::{suffix}" for path in destinations if f"{path}::{suffix}" in unmatched_after]
        if len(matches) > 1:
            raise ValueError(f"Split mapping is ambiguous for {old_nodeid}: {matches}")
        if matches:
            unmatched_after.remove(matches[0])
            remapped.append((old_nodeid, matches[0]))
        else:
            removed.append(old_nodeid)

    return NodeIdComparison(
        added=tuple(sorted(unmatched_after)),
        removed=tuple(removed),
        remapped=tuple(remapped),
    )
```

Add a CLI that reads two collection-output files, accepts optional `--split-map <json>`, prints counts plus every added/removed/remapped node, and exits `1` when `removed` is non-empty. Validate that every split-map source and destination is a normalized `.py` path and that each destination list is non-empty:

```python
def _load_split_map(path: Path | None) -> dict[str, tuple[str, ...]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Split map must be a JSON object")
    result: dict[str, tuple[str, ...]] = {}
    for source, destinations in raw.items():
        if not isinstance(source, str) or not source.endswith(".py"):
            raise ValueError(f"Invalid split source: {source!r}")
        if not isinstance(destinations, list) or not destinations:
            raise ValueError(f"Split destinations must be a non-empty list: {source}")
        normalized = tuple(_normalize(destination) for destination in destinations)
        if any(not destination.endswith(".py") for destination in normalized):
            raise ValueError(f"Invalid split destination for {source}: {destinations!r}")
        result[_normalize(source)] = normalized
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--split-map", type=Path)
    args = parser.parse_args(argv)
    comparison = compare_node_ids(
        parse_collection_output(args.before.read_text()),
        parse_collection_output(args.after.read_text()),
        _load_split_map(args.split_map),
    )
    print(f"added: {len(comparison.added)}")
    print(f"removed: {len(comparison.removed)}")
    print(f"remapped: {len(comparison.remapped)}")
    for nodeid in comparison.added:
        print(f"+ {nodeid}")
    for nodeid in comparison.removed:
        print(f"- {nodeid}")
    for old_nodeid, new_nodeid in comparison.remapped:
        print(f"~ {old_nodeid} -> {new_nodeid}")
    return 1 if comparison.removed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run focused verification**

Run:

```bash
uv run pytest -n 0 tests/unit/test_test_suite_tooling.py -q
uv run ruff check scripts/pytest_file_durations.py scripts/compare_pytest_node_ids.py tests/unit/test_test_suite_tooling.py
uv run pyright scripts/pytest_file_durations.py scripts/compare_pytest_node_ids.py tests/unit/test_test_suite_tooling.py
```

Expected: all tests and checks pass.

### Task 2: Capture The Baseline And Measurement Log

**Files:**
- Create: `docs/superpowers/performance/2026-08-01-test-suite-results.md`
- Generate locally: `/tmp/task-world-test-performance/unit.before.txt`
- Generate locally: `/tmp/task-world-test-performance/full.before.txt`
- Generate locally: `/tmp/task-world-test-performance/unit-stage-0-durations.json`
- Generate locally: `/tmp/task-world-test-performance/full-stage-0-durations.json`

**Interfaces:**
- Produces: immutable baseline collection files used by every later stage.
- Produces: measurement-log schema: stage, revision/diff label, command, node count, wall times, pytest times, slowest aggregate files, decision.

- [ ] **Step 1: Create the local measurement directory**

Run `ls /tmp/task-world-test-performance`; if absent, verify `/tmp` and then run:

```bash
mkdir /tmp/task-world-test-performance
```

- [ ] **Step 2: Capture deterministic default collection output**

Run sequentially:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -n 0 --collect-only -q tests/unit > /tmp/task-world-test-performance/unit.before.txt
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -n 0 --collect-only -q > /tmp/task-world-test-performance/full.before.txt
```

Use `parse_collection_output()` to record exact unit and full node counts in the results document. Preserve these two files until final verification.

- [ ] **Step 3: Warm and profile Stage 0**

Run the unit suite once, then the full suite once. After warming, run each profiler command once:

```bash
uv run pytest tests/unit -q -p scripts.pytest_file_durations --file-duration-limit=20 --file-duration-json=/tmp/task-world-test-performance/unit-stage-0-durations.json
uv run pytest -q -p scripts.pytest_file_durations --file-duration-limit=20 --file-duration-json=/tmp/task-world-test-performance/full-stage-0-durations.json
```

- [ ] **Step 4: Record three uncontended Stage 0 timings**

Run each command three times, one command at a time, using `/usr/bin/time -p`. Record all `real` values and pytest-reported durations verbatim in the results document.

```bash
/usr/bin/time -p uv run pytest tests/unit -q
/usr/bin/time -p uv run pytest tests/unit -q
/usr/bin/time -p uv run pytest tests/unit -q
/usr/bin/time -p uv run pytest -q
/usr/bin/time -p uv run pytest -q
/usr/bin/time -p uv run pytest -q
```

- [ ] **Step 5: Write the results document**

Start the document with the machine description, logical CPU count, worker formula (`max(1, cpu_count - 2)`), baseline node counts, the six observed Stage 0 timings, and the top 20 aggregate files from each JSON report. Do not invent or round measurements beyond the precision emitted by the tools.

### Task 3: Skip Existing Whole-Module Opt-In Suites Before Import

**Files:**
- Create: `tests/opt_in_suites.py`
- Modify: `tests/conftest.py:117-194`
- Modify: `tests/unit/test_test_suite_configuration.py`
- Modify: `tests/integration/test_graph_fr01_fr13_fr18_acceptance.py`
- Modify: `tests/integration/test_graph_fr02_acceptance.py`
- Modify: `tests/integration/test_graph_fr03_acceptance.py`
- Modify: `tests/integration/test_graph_fr06_acceptance.py`
- Modify: `tests/integration/test_graph_fr07_acceptance.py`
- Modify: `tests/integration/test_graph_fr08_acceptance.py`
- Modify: `tests/integration/test_graph_fr09_acceptance.py`
- Modify: `tests/integration/test_graph_fr10_acceptance.py`
- Modify: `tests/integration/test_graph_fr11_acceptance.py`
- Modify: `tests/integration/test_graph_fr12_acceptance.py`
- Modify: `tests/integration/test_graph_fr14_final_gate_acceptance.py`
- Modify: `tests/integration/test_graph_fr15_acceptance.py`
- Modify: `tests/integration/test_graph_fr16_acceptance.py`
- Modify: `tests/integration/test_graph_fr17_acceptance.py`

**Interfaces:**
- Produces: `WHOLE_MODULE_SLOW: frozenset[Path]`
- Produces: `WHOLE_MODULE_E2E: frozenset[Path]`
- Produces: `should_ignore_opt_in_path(relative: Path, *, run_slow: bool, run_e2e: bool) -> bool`
- Consumes: `pytest_ignore_collect` calls the pure helper before importing test modules.

- [ ] **Step 1: Add failing manifest and collector tests**

Extend `test_test_suite_configuration.py` to verify:

1. Every manifest path exists and ends in `.py`.
2. Every slow entry's `pytestmark` assignment contains `pytest.mark.slow`.
3. Every E2E entry's `pytestmark` assignment contains `pytest.mark.e2e`.
4. The manifest equals the repository-wide set of explicit whole-module slow/E2E markers under `tests/unit` and `tests/integration`.
5. Mixed files `test_codex_server_transport.py`, `test_fixture_corpus.py`, `test_git_snapshot.py`, `test_jsonl_rotation.py`, and `test_r04_otel_vocab_codemod.py` are absent.
6. Default decisions ignore every manifest entry; `--run-slow` and `--run-e2e` restore only their category.
7. A `pytester` collection smoke test creates one manifest-named slow module and one manifest-named E2E module, proving default omission and flag-enabled collection without importing the real expensive suites.

Run:

```bash
uv run pytest -n 0 tests/unit/test_test_suite_configuration.py -q
```

Expected: failure because `tests.opt_in_suites` does not exist and FR acceptance files do not declare module markers.

- [ ] **Step 2: Add the exact pre-collection manifest**

In `tests/opt_in_suites.py`, define paths relative to `tests/`. The slow set must contain the five unit files, 24 explicitly marked integration files, and 14 FR acceptance files found during design mapping. The E2E set must contain the two integration files.

```python
from pathlib import Path

WHOLE_MODULE_SLOW = frozenset(
    Path(path)
    for path in (
        "unit/test_graph_journal_configuration.py",
        "unit/test_graph_projection_performance.py",
        "unit/test_graph_public_exports.py",
        "unit/test_worktree_commit_events.py",
        "unit/test_worktree_reset_events.py",
        "integration/test_api_agents.py",
        "integration/test_check_output_artifacts.py",
        "integration/test_claude_sdk_removal.py",
        "integration/test_cli.py",
        "integration/test_conditional_steps.py",
        "integration/test_conflict_api.py",
        "integration/test_event_log_durability.py",
        "integration/test_fan_out.py",
        "integration/test_graph_activity_stream.py",
        "integration/test_graph_api.py",
        "integration/test_graph_default_carrier.py",
        "integration/test_graph_file_state_boundary.py",
        "integration/test_graph_gatekeeper_flow.py",
        "integration/test_graph_outbox_crash_points.py",
        "integration/test_graph_parent_child_flow.py",
        "integration/test_graph_planner_flow.py",
        "integration/test_graph_planner_session_flow.py",
        "integration/test_graph_routine_compile.py",
        "integration/test_graph_run_driver.py",
        "integration/test_graph_startup_recovery.py",
        "integration/test_migrations.py",
        "integration/test_prune_api.py",
        "integration/test_review_test_runner.py",
        "integration/test_worktree.py",
        "integration/test_graph_fr01_fr13_fr18_acceptance.py",
        "integration/test_graph_fr02_acceptance.py",
        "integration/test_graph_fr03_acceptance.py",
        "integration/test_graph_fr06_acceptance.py",
        "integration/test_graph_fr07_acceptance.py",
        "integration/test_graph_fr08_acceptance.py",
        "integration/test_graph_fr09_acceptance.py",
        "integration/test_graph_fr10_acceptance.py",
        "integration/test_graph_fr11_acceptance.py",
        "integration/test_graph_fr12_acceptance.py",
        "integration/test_graph_fr14_final_gate_acceptance.py",
        "integration/test_graph_fr15_acceptance.py",
        "integration/test_graph_fr16_acceptance.py",
        "integration/test_graph_fr17_acceptance.py",
    )
)

WHOLE_MODULE_E2E = frozenset(
    {
        Path("integration/test_graph_dynamic_e2e.py"),
        Path("integration/test_graph_runner_e2e.py"),
    }
)


def should_ignore_opt_in_path(
    relative: Path, *, run_slow: bool, run_e2e: bool
) -> bool:
    if relative.parts and relative.parts[0] == "slow":
        return not run_slow
    if relative.parts and relative.parts[0] == "e2e":
        return not run_e2e
    if relative in WHOLE_MODULE_SLOW:
        return not run_slow
    if relative in WHOLE_MODULE_E2E:
        return not run_e2e
    return False
```

- [ ] **Step 3: Wire the manifest into pytest collection**

Import `should_ignore_opt_in_path` in `tests/conftest.py` and reduce `pytest_ignore_collect` to path normalization plus:

```python
return should_ignore_opt_in_path(
    relative,
    run_slow=config.getoption("--run-slow"),
    run_e2e=config.getoption("--run-e2e"),
)
```

Remove only the filename-derived marker block at current lines 187-190. Keep `pytest_collection_modifyitems` skip markers because `make test-changed` clears the marker expression.

- [ ] **Step 4: Add explicit markers to FR acceptance modules**

In each of the 14 listed files, add `import pytest` if absent and place this assignment after imports:

```python
pytestmark = pytest.mark.slow
```

Do not move files or change test bodies.

- [ ] **Step 5: Run Stage 1 behavior checks**

```bash
uv run pytest -n 0 tests/unit/test_test_suite_configuration.py -q
uv run pytest --run-slow -n 0 tests/unit/test_graph_projection_performance.py tests/integration/test_migrations.py
uv run pytest --run-e2e -n 0 tests/integration/test_graph_dynamic_e2e.py
```

Expected: all pass; default collection omits manifest modules before import and each opt-in flag restores its category.

- [ ] **Step 6: Compare selected cases and measure Stage 1**

Capture `unit-stage-1.txt` and `full-stage-1.txt` with the Task 2 collection commands. Compare both against baseline with `compare_pytest_node_ids.py`; expected removals: zero. New configuration tests are allowed additions.

Warm once, profile once, and run three unit plus three full timings. Append results and the keep/discard decision. Retain Stage 1 only if repeatable wall time improves; otherwise remove the manifest wiring and FR marker edits together.

- [ ] **Step 7: Apply the stop condition**

If all three unit runs are at most 25 seconds and all three full runs are at most 50 seconds, skip Tasks 4-9 and proceed to Task 10. Otherwise continue to Task 4.

### Task 4: Add Guaranteed-Fresh Database Initialization

**Files:**
- Create: `tests/integration/db_helpers.py`
- Create: `tests/integration/test_db_helpers.py`

**Interfaces:**
- Consumes: `AsyncEngine` and public `orchestrator.db.Base`.
- Produces: `async def init_fresh_test_db(engine: AsyncEngine) -> None`.

- [ ] **Step 1: Write the three failing helper tests**

```python
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from orchestrator.db import Base, RunRepository, create_engine, create_session_factory, save_run
from orchestrator.state import Run
from tests.integration.db_helpers import init_fresh_test_db


async def test_init_fresh_test_db_creates_complete_metadata_schema() -> None:
    engine = create_engine(":memory:")
    try:
        await init_fresh_test_db(engine)
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
        assert tables == set(Base.metadata.tables)
    finally:
        await engine.dispose()


async def test_init_fresh_test_db_supports_repository_roundtrip() -> None:
    engine = create_engine(":memory:")
    try:
        await init_fresh_test_db(engine)
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            await save_run(session, Run(id="helper-run", repo_name="helper-repo"))
            await session.commit()
            loaded = await RunRepository(session).get("helper-run")
        assert loaded.repo_name == "helper-repo"
    finally:
        await engine.dispose()


async def test_init_fresh_test_db_fails_when_reused() -> None:
    engine = create_engine(":memory:")
    try:
        await init_fresh_test_db(engine)
        with pytest.raises(OperationalError, match="already exists"):
            await init_fresh_test_db(engine)
    finally:
        await engine.dispose()
```

If `RunRepository`, `save_run`, or `Run` has a different public export in the current branch, use only its top-level module export and adjust the import without changing the test behavior.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest -n 0 tests/integration/test_db_helpers.py -q
```

Expected: import failure because `tests.integration.db_helpers` does not exist.

- [ ] **Step 3: Implement the helper exactly once**

```python
from sqlalchemy.ext.asyncio import AsyncEngine

from orchestrator.db import Base


async def init_fresh_test_db(engine: AsyncEngine) -> None:
    """Create metadata in a database guaranteed empty by its owning test."""
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                checkfirst=False,
            )
        )
```

Do not accept a path, inspect the schema, catch duplicate-table errors, or fall back to Alembic.

- [ ] **Step 4: Verify helper behavior**

```bash
uv run pytest -n 0 tests/integration/test_db_helpers.py -q
uv run ruff check tests/integration/db_helpers.py tests/integration/test_db_helpers.py
uv run pyright tests/integration/db_helpers.py tests/integration/test_db_helpers.py
```

Expected: all pass.

### Task 5: Adopt Fast Schema Creation In Default Integration Fixtures

**Files:**
- Modify: `tests/integration/conftest.py`
- Modify the guaranteed-fresh default modules listed below.
- Do not modify migration/bootstrap-retention files except non-migration calls explicitly identified below.

**Interfaces:**
- Consumes: `init_fresh_test_db(engine)` from Task 4.
- Preserves: every fixture's scope, engine ownership, session factory, teardown, and database path.

- [ ] **Step 1: Convert the shared app fixture first**

Replace `from orchestrator.db import init_db` with `from tests.integration.db_helpers import init_fresh_test_db` in `tests/integration/conftest.py`, and replace:

```python
await init_db(app.state.engine)
```

with:

```python
await init_fresh_test_db(app.state.engine)
```

Run all default tests using `_shared_app_fixture` through the existing integration conftest; at minimum run:

```bash
uv run pytest tests/integration/test_api_runs.py tests/integration/test_api_branch_ops.py -q
```

- [ ] **Step 2: Convert guaranteed-fresh in-memory fixtures**

In each file below, import `init_fresh_test_db` from `tests.integration.db_helpers`, replace only calls whose engine/app was just created with `:memory:`, and remove `init_db` imports when no retained call remains:

```text
tests/integration/test_agent_executor.py
tests/integration/test_agent_logs.py
tests/integration/test_agent_monitor.py
tests/integration/test_agent_overrides.py
tests/integration/test_api_activity.py
tests/integration/test_api_agent_configs.py
tests/integration/test_api_approval.py
tests/integration/test_api_auth.py
tests/integration/test_api_backward_transitions.py
tests/integration/test_api_branch_ops.py
tests/integration/test_api_clarifications.py
tests/integration/test_api_escalation.py
tests/integration/test_api_full_lifecycle.py
tests/integration/test_api_human_approval.py
tests/integration/test_api_max_recent_runs.py
tests/integration/test_api_model_profiles.py
tests/integration/test_api_repos_validation.py
tests/integration/test_api_review_validation.py
tests/integration/test_api_routines.py
tests/integration/test_api_runs_codex_agent_types.py
tests/integration/test_api_runs_envfiles.py
tests/integration/test_api_runs_recover.py
tests/integration/test_api_tasks.py
tests/integration/test_approval_workflow.py
tests/integration/test_artifact_api.py
tests/integration/test_attempt_store_event_sourcing.py
tests/integration/test_auto_verify_timing.py
tests/integration/test_auto_verify_workflow.py
tests/integration/test_check_and_apply_methods.py
tests/integration/test_clarification_repository.py
tests/integration/test_clarification_workflow.py
tests/integration/test_codex_lifecycle.py
tests/integration/test_completion_integration.py
tests/integration/test_cost_records.py
tests/integration/test_database.py
tests/integration/test_event_sourced_workflow.py
tests/integration/test_event_store.py
tests/integration/test_event_store_wiring.py
tests/integration/test_executor_loop_invariant.py
tests/integration/test_graph_event_store.py
tests/integration/test_graph_node_detail_read_models.py
tests/integration/test_graph_read_models.py
tests/integration/test_graph_usage_persistence.py
tests/integration/test_idempotency.py
tests/integration/test_jsonl_rotation_recovery.py
tests/integration/test_mcp.py
tests/integration/test_mcp_server.py
tests/integration/test_mcp_sse.py
tests/integration/test_mock_agent_workflow.py
tests/integration/test_output_batching.py
tests/integration/test_parity_linear.py
tests/integration/test_parity_pause_resume.py
tests/integration/test_parity_recovery.py
tests/integration/test_parity_revision.py
tests/integration/test_parity_skip.py
tests/integration/test_project_routines.py
tests/integration/test_projection_recovery.py
tests/integration/test_prompt_agent_system_prompt.py
tests/integration/test_repeat_for_edge_cases.py
tests/integration/test_repositories.py
tests/integration/test_route_cache_isolation.py
tests/integration/test_scaffolding.py
tests/integration/test_signal_events.py
tests/integration/test_signal_queue.py
tests/integration/test_skip_step_api.py
tests/integration/test_stopping_state.py
tests/integration/test_verifier_model_pinning.py
tests/integration/test_workflow_service.py
tests/integration/test_workflow_smoke.py
```

Also replace the existing direct `Base.metadata.create_all` calls in `test_parity_recovery.py` with the helper. Do not alter fixture scopes.

- [ ] **Step 3: Convert guaranteed-fresh default temporary-file setup**

Replace only first initialization of newly allocated temp files in:

```text
tests/integration/test_auto_verify_workflow.py
tests/integration/test_cost_records.py
tests/integration/test_database.py
tests/integration/test_full_persistence.py
tests/integration/test_graph_controller_transactions.py
tests/integration/test_graph_event_store.py
tests/integration/test_graph_run_start_routing.py
tests/integration/test_graph_usage_persistence.py
tests/integration/test_jsonl_rotation_recovery.py
tests/integration/test_output_batching.py
```

For persistence/restart tests, initialize the file once with `init_fresh_test_db`; never call the helper after reopening that file.

- [ ] **Step 4: Preserve production-initialization coverage**

Keep `init_db()` for these exact behaviors:

```text
tests/integration/test_database.py::test_init_db_creates_tables
tests/integration/test_database.py::test_events_v2_alembic_schema_and_retry_identity
tests/integration/test_event_log_durability.py::test_events_v2_migration_schema_and_retry_identity
tests/integration/test_migrations.py::test_init_db_adds_execution_mode_column
tests/integration/test_migrations.py::test_init_db_adds_graph_outbox_backoff_schema
tests/integration/test_jsonl_bootstrap.py session fixture
```

Keep production `_lifespan()` and all `src/orchestrator` code unchanged.

- [ ] **Step 5: Run focused database and app checks**

```bash
uv run pytest -n 0 tests/integration/test_db_helpers.py tests/integration/test_database.py tests/integration/test_full_persistence.py tests/integration/test_route_cache_isolation.py -q
uv run pytest --run-slow -n 0 tests/integration/test_migrations.py -q
```

Expected: all pass, including natural failure on helper reuse and retained Alembic behavior.

- [ ] **Step 6: Compare selected cases and measure Stage 2**

Repeat collection comparison, warm/profile runs, and all six timings. Expected removed baseline cases: zero. Record the before/after aggregate database-heavy files and retain this stage only if wall-time improvement is repeatable.

- [ ] **Step 7: Apply the stop condition**

If all six runs meet targets, skip Tasks 6-9 and proceed to Task 10. Otherwise continue to Task 6.

### Task 6: Profile Repeated Cached App Construction

**Files:**
- Create: `scripts/profile_app_construction.py`
- Modify only after profile: `tests/integration/conftest.py`, a measured app-construction module, or one immutable production descriptor module.
- Test only after profile: `tests/integration/test_route_cache_isolation.py`

**Interfaces:**
- Produces: profiles for cached default construction, explicit global config, explicit artifact root, and cache-disabled construction.
- Preserves: fresh engines, session factories, transports, registries, managers, locks, caches, and background state per app.

- [ ] **Step 1: Implement a diagnostic profiler with cleanup**

The script must:

1. Accept `--iterations` with default `100` and `--output` for cProfile stats.
2. Warm one app before measuring.
3. Construct each app with `db_path=":memory:"`, `routine_dirs=[]`, and a real `GlobalConfig()`.
4. Compare implicit and explicit `artifact_project_root` variants.
5. Compare route cache enabled and disabled variants.
6. Dispose every created engine with `await engine.dispose()` after the measured construction loop.
7. Print total and per-app time but never assert a threshold.
8. Sort cProfile output by cumulative and self time so `resolve_main_worktree`, `_mount_mcp_sse`, engine construction, env-file setup, agent discovery, and route registration are attributable.

Run:

```bash
uv run python scripts/profile_app_construction.py --iterations 100 --output /tmp/task-world-test-performance/create-app-stage-3.prof
```

- [ ] **Step 2: Select only a demonstrated immutable optimization**

Use this decision order:

1. If passing an explicit artifact root removes a material repeated `resolve_main_worktree` cost, resolve the immutable project-root `Path` once in integration session fixtures and pass it through the existing `artifact_project_root` argument. Do not cache artifact stores, resolvers, garbage collectors, or locks.
2. If repeated agent package scanning dominates, cache only a sorted immutable tuple of discovered package names; still import into and use fresh/process-owned registries exactly as before.
3. If FastMCP metadata generation dominates, do not share `OrchestratorMCPServer`, `FastMCP`, `ToolManager`, tool objects, transports, dispatchers, or ASGI apps. Proceed only after extracting a deeply immutable descriptor tuple with fresh per-app wrappers.
4. If the only material savings require shared mutable app state, reject Stage 3 and continue to Task 7.

- [ ] **Step 3: Add identity and mutation-isolation tests for the selected candidate**

For every retained cache or pre-resolved value, test all of the following without mocks:

1. Equal configuration reuses only the immutable compiled value by identity.
2. Different configuration does not reuse it.
3. Mutation is impossible by construction.
4. Per-app wrappers and operational state remain distinct.
5. Mutating app A's wrapper/state does not change app B.
6. `TW_NO_ROUTE_CACHE=1` or the selected diagnostic cache switch produces behaviorally equivalent routes and OpenAPI.
7. The existing database, lock manager, connection manager, graph MCP registry, runner executor, tool detector, summary cache, MCP server, and scoped dispatcher identities remain distinct.

Do not add broad route-cache behavior not needed by the selected optimization.

- [ ] **Step 4: Measure and decide**

Run the profile again, then the standard collection comparison and six timing runs. Keep only the measured candidate; discard it if the microbenchmark gain does not improve repeatable suite wall time.

- [ ] **Step 5: Apply the stop condition**

If all six runs meet targets, skip Tasks 7-9 and proceed to Task 10. If Stage 3 was rejected or targets remain unmet, continue to Task 7.

### Task 7: Identify The Measured Xdist Tail Split

**Files:**
- Read: `/tmp/task-world-test-performance/unit-stage-3-durations.json`
- Read: `/tmp/task-world-test-performance/full-stage-3-durations.json`
- Create locally: `/tmp/task-world-test-performance/split-map.json`
- Modify: exactly one measured tail file in Task 8.

**Interfaces:**
- Produces: one exact old file and behavior-based destination list.
- Consumes: aggregate setup/call/teardown totals plus observed xdist completion order.

- [ ] **Step 1: Run three profiled warm measurements**

For unit and full suites, collect three JSON aggregate reports after a warm run. Keep controller output so the last-completing files can be correlated with aggregate totals. A candidate must consistently appear in the final tail, not merely have many node IDs.

- [ ] **Step 2: Exclude files with valuable module setup**

Do not split these initial candidates:

```text
tests/integration/test_graph_event_store.py
tests/integration/test_graph_read_models.py
tests/integration/test_graph_node_detail_read_models.py
tests/unit/test_agent_system_prompt.py
```

Their module-scoped database setup would be duplicated.

- [ ] **Step 3: Select one behavior-based split**

Choose the first file demonstrated in the tail from this static-safe shortlist:

```text
tests/unit/test_graph_commands.py
tests/unit/test_graph_projection_integrity.py
tests/unit/test_graph_projection_boundaries.py
tests/unit/test_codex_server_common.py
tests/unit/test_graph_models.py
tests/unit/test_pydantic_events.py
tests/unit/test_prompt_generation.py
tests/unit/test_condition_evaluator.py
tests/unit/test_patch_validator.py
tests/unit/test_scheduler.py
tests/integration/test_api_runs.py
tests/integration/test_workflow_service.py
tests/integration/test_api_agent_configs.py
```

If no shortlisted file is a measured tail contributor, record that Stage 4 has no safe candidate and continue to Task 9.

- [ ] **Step 4: Capture exact pre-split nodes**

Collect the selected file serially and preserve its output. Define destination filenames by behavior, list them in `split-map.json`, and verify every old suffix after `::` is unique before moving code.

### Task 8: Split One Measured Tail File

**Files:**
- Modify/Delete: the one source selected in Task 7.
- Create: behavior-named destination test files selected in Task 7.
- Create if needed: one focused non-collectable helper module beside those tests.

**Interfaces:**
- Preserves: every test function/class/parameter suffix exactly.
- Preserves: fixture scope and setup semantics.
- Produces: more than one xdist `loadfile` scheduling unit.

- [ ] **Step 1: Move shared builders before tests**

Move only builders/constants imported by multiple destinations into a non-`test_*.py` helper. Keep test bodies and parameter IDs unchanged. Do not import shared values from another collectable test module.

- [ ] **Step 2: Move tests by behavior**

Move complete tests and their behavior-specific constants into destination files. Do not rename functions, classes, parameter IDs, assertions, or fixtures. Do not divide a parameter matrix by arbitrary index ranges.

- [ ] **Step 3: Verify exact node preservation**

Collect the destination files and run `compare_pytest_node_ids.py` with `/tmp/task-world-test-performance/split-map.json`. Expected removals: zero; expected additions: zero for the selected file; every old node must appear in `remapped` exactly once.

- [ ] **Step 4: Verify focused behavior and aggregate work**

Run all destination files together with `-n 0`, then with default xdist settings. Compare total setup/call/teardown work against the pre-split file. Discard the split if duplicated setup or import work offsets the scheduling gain.

- [ ] **Step 5: Measure and decide**

Run the standard collection comparison and six timings. Keep the split only if repeatable wall time improves. Record the exact old-to-new mapping in the results document.

- [ ] **Step 6: Apply the stop condition**

If all targets are met, skip Task 9 and proceed to Task 10. Otherwise continue to Task 9.

### Task 9: Consolidate Remaining Default Real-Git Setup

**Files:**
- Modify in measured order: `tests/unit/test_git_snapshot.py`
- Modify in measured order: `tests/integration/test_artifact_api.py`
- Modify in measured order: `tests/unit/test_git_autocommit_hook_retry.py`
- Modify in measured order: `tests/unit/test_worktree_seed_staleness.py`
- Modify in measured order: `tests/unit/test_git_wrapper.py`
- Modify in measured order: `tests/integration/test_workflow_service.py`
- Modify only if measured: `tests/unit/test_git_contamination.py`
- Modify only if measured: `tests/unit/test_graph_dispatch_on_output.py`
- Test: `tests/unit/test_git_repo_template.py`
- Test: `tests/integration/test_git_repo_template.py`

**Interfaces:**
- Consumes: `_unit_base_repo: Path` and `_base_repo: Path` session fixtures.
- Produces: independent `shutil.copytree` repository under each test's `tmp_path`.
- Preserves: direct Git initialization in repository-initialization and unborn-repository tests.

- [ ] **Step 1: Add focused copy-isolation tests**

For both unit and integration templates, copy the template twice under `tmp_path`, mutate and commit only copy A, create a branch in A, and assert:

1. Both `.git` directories are distinct.
2. Template, A, and B initially have equal HEADs.
3. Template and B remain clean after A changes.
4. Template and B retain the original HEAD, refs, local config, and `README.md`.
5. Both copies are descendants of the current test's temporary directory.

Use real `_git` helpers and real copies; do not mock subprocesses.

- [ ] **Step 2: Convert `test_git_snapshot.py`**

Change `_make_repo` to accept `_unit_base_repo`, copy it to a unique `tmp_path` child, and add only each snapshot scenario's files, index state, refs, and commits. Preserve the direct `git init` path for the individually marked slow unborn-repository case if its expected behavior depends on no HEAD.

- [ ] **Step 3: Convert `test_artifact_api.py`**

Replace each `_init_repo` call at the artifact fixture and multi-project/linked-worktree scenarios with a `copytree` of `_base_repo`. Keep every copy under that test's `tmp_path` or test-local repositories directory. Remove `_init_repo` import if no direct initialization remains.

- [ ] **Step 4: Convert remaining measured default candidates one file at a time**

For each file, copy the session template and then add only scenario history:

```text
tests/unit/test_git_autocommit_hook_retry.py: install each hook into the copied .git/hooks.
tests/unit/test_worktree_seed_staleness.py: add tracked.txt and create scenario commits A/B after copying.
tests/unit/test_git_wrapper.py: exercise wrapper commands against independent copies.
tests/integration/test_workflow_service.py: add work.txt as the scenario start commit.
tests/unit/test_git_contamination.py: create the linked-worktree scenario from a copy.
tests/unit/test_graph_dispatch_on_output.py: copy for package/dependency snapshot setup; retain the unborn-repository test's direct init.
```

After each file, run its focused tests and one three-run suite measurement. Stop converting files once targets are met; do not migrate opt-in slow/E2E setup merely for consistency.

- [ ] **Step 5: Preserve direct-init coverage**

Do not change `tests/integration/test_project_init.py`. Do not replace a test-local direct `git init` when the test proves initialization or requires an unborn repository.

- [ ] **Step 6: Compare selection and make the Stage 5 decision**

Expected baseline removals: zero. Keep each file conversion only when the focused tests pass and the cumulative stage has repeatable wall-time benefit.

### Task 10: Run Final Verification And Report All Evidence

**Files:**
- Modify: `docs/superpowers/performance/2026-08-01-test-suite-results.md`

**Interfaces:**
- Consumes: baseline and final collection outputs, optional split map, profiler output, and all retained-stage timing records.
- Produces: final pass/fail evidence for selection, opt-in collection, checks, and six timing gates.

- [ ] **Step 1: Capture and compare final selected node IDs**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -n 0 --collect-only -q tests/unit > /tmp/task-world-test-performance/unit.final.txt
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -n 0 --collect-only -q > /tmp/task-world-test-performance/full.final.txt
uv run python scripts/compare_pytest_node_ids.py /tmp/task-world-test-performance/unit.before.txt /tmp/task-world-test-performance/unit.final.txt --split-map /tmp/task-world-test-performance/split-map.json
uv run python scripts/compare_pytest_node_ids.py /tmp/task-world-test-performance/full.before.txt /tmp/task-world-test-performance/full.final.txt --split-map /tmp/task-world-test-performance/split-map.json
```

Omit `--split-map` if Stage 4 was not retained. Expected removed nodes: zero. Explain every added regression node and list every path remap.

- [ ] **Step 2: Run required static and behavioral checks**

Run sequentially in the foreground:

```bash
uv run ruff check .
uv run pyright
uv run pytest tests/unit -q
uv run pytest -q
uv run pytest --run-slow -n 0 tests/unit/test_graph_projection_performance.py tests/integration/test_migrations.py
uv run pytest --run-e2e -n 0 tests/integration/test_graph_dynamic_e2e.py
```

Expected: every command exits zero.

- [ ] **Step 3: Run the final timing gate**

Warm unit once and full once. Then run the canonical unit command three times and canonical full command three times with `/usr/bin/time -p`, sequentially on an otherwise idle machine.

Expected:

- Every unit `real` value is at most `25.00` seconds.
- Every full `real` value is at most `50.00` seconds.

- [ ] **Step 4: Complete the measurement report**

Record all six wall times, all six pytest times, final node counts, additions, split remaps, retained/rejected stages, final slowest aggregate files, and exact outputs of the opt-in checks. State failure rather than averaging if any individual timing exceeds its target.

- [ ] **Step 5: Inspect the final diff**

Verify that no test was moved behind a marker, no assertion or parameter matrix was weakened, production `init_db()` behavior is unchanged, no per-app mutable service is shared, and no Git template is mutated directly. Leave the worktree uncommitted unless the user explicitly asks for a commit.
