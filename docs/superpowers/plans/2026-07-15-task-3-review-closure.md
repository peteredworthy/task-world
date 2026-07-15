# Task 3 Review Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every Critical and Important Task 3 review finding without restoring compatibility behavior.

**Architecture:** Tighten only W5-reachable event and record contracts. Current producer paths define canonical payloads; reducers accept exact discriminators and typed nested values, while explicitly named dynamic dictionaries remain open.

**Tech Stack:** Python 3.12, Pydantic v2, pytest/pytest-asyncio, SQLAlchemy SQLite integration fixtures, Ruff, Pyright.

## Global Constraints

- Work only in `worktrees/w5-typed-payloads-completion`.
- Do not restore compatibility shims or weaken strictness.
- Use real objects and dependency injection; no mocks, monkeypatching, or suppressions.
- Do not touch database files or bypass commit hooks.
- Preserve the pre-existing unstaged `.superpowers/sdd/progress.md` change.

---

### Task 1: Exact Record And Scalar Contracts

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `tests/unit/test_w5_compatibility_removal.py`
- Modify: `tests/unit/test_patch_event_payloads.py`

**Interfaces:**
- Produces: immutable `_OUTPUT_RECORD_MODELS` and `_GENERIC_OUTPUT_RECORD_TYPES` ownership sets.
- Produces: strict integer `base_graph_position` fields for current event producers.

- [ ] Add failing tests that reject missing and unknown output discriminators, accept every explicitly named generic discriminator, reject projection mapping methods, and reject string patch positions.
- [ ] Run the focused tests and confirm failures identify fallback dispatch and coercive/string fields.
- [ ] Replace `.get(record_type, OutputRecord)` with explicit immutable ownership and return `None` for unknown/missing values.
- [ ] Change current event `base_graph_position` unions to `StrictInt | None` after producer inventory confirms integer-only output.
- [ ] Run the focused tests to GREEN.

### Task 2: Strict Nested Contracts And Canonical Decisions

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `tests/unit/test_decision_event_payloads.py`
- Modify: `tests/unit/test_node_created_event_payloads.py`
- Modify: `tests/unit/test_patch_event_payloads.py`
- Modify: `tests/unit/test_w5_compatibility_removal.py`

**Interfaces:**
- Produces: `StrictNestedModel` with `ConfigDict(extra="forbid", populate_by_name=True)`.
- Produces: canonical decision literals with no outcome/approved/verdict synthesis.

- [ ] Add failing nested-extra tests for verification values, grade rows, planner chains/regions, ports, and resource claims; add positive tests for named dynamic fields.
- [ ] Add failing decision alias tests for `outcome`, `approved`, and `verdict`-only payloads.
- [ ] Apply `StrictNestedModel` only to W5-reachable nested models and retain dynamic dict/Any fields by name.
- [ ] Remove the decision before-validator alias synthesis and type canonical decision fields as literals emitted by `_apply_record_decision`.
- [ ] Run affected model, command, decision, node-created, and patch tests to GREEN.

### Task 3: Cleanup Metadata, Producer Coverage, And Compact Retention

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph_runtime/file_state.py`
- Modify: all nine `tests/unit/test_*_event_payloads.py` Task 3 suites
- Modify: compact-read integration/unit tests identified from pre-Task-3 history

**Interfaces:**
- Produces: `FileStateRecord.cleanup_excluded_paths: list[str]`.
- Consumes: real compiler, command, and runtime producer functions.

- [ ] Add a failing cleanup producer/round-trip test proving excluded paths survive `apply_cleanup_requested` and `FileStateRecord` validation.
- [ ] Restore canonical producer tests in all nine payload suites, invoking current producer paths and comparing emitted dictionaries to model JSON dumps.
- [ ] Restore runtime retry backoff compact-retention, SQLite compact replay, hidden-oracle survival, and full/compact node-created parity tests from the parent revision; canonicalize their payloads.
- [ ] Restore `cleanup_excluded_paths` in the cleanup producer and typed record.
- [ ] Run all producer and compact-read tests to GREEN.

### Task 4: Verification, Report, Review, And Commit

**Files:**
- Modify: `.superpowers/sdd/task-3-report.md` (ignored SDD artifact)
- Modify: this design/plan documentation as needed for accurate evidence

**Interfaces:**
- Produces: one hook-verified fix commit and final report evidence.

- [ ] Run the exact Task 3 aggregate and record its count.
- [ ] Run directly affected compact-read and producer tests and record their count.
- [ ] Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright`.
- [ ] Run `uv run pytest -q` exactly once after focused gates are green.
- [ ] Self-review the diff for fallback dispatch, permissive nested models, alias synthesis, removed retention tests, mapping methods, and unrelated changes.
- [ ] Append fix details, tests, and self-review to `.superpowers/sdd/task-3-report.md`.
- [ ] Stage only intended files and commit with hooks enabled.
