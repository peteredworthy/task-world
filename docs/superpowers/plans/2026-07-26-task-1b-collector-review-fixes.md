# Task 1b Collector Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining fail-closed `GraphProjection` collector review findings without changing production consumers.

**Architecture:** Retain the LibCST visitor and add narrowly scoped helpers for tracked projection-field chains, comparison operands, delayed rebinding, and execution-scope qualification. Tests exercise each syntax shape through `collect_source()` and directly validate strict inventory models and deterministic sort keys.

**Tech Stack:** Python 3.12, LibCST metadata, Pydantic v2, pytest, Ruff, Pyright.

## Global Constraints

- Use `uv run` for all Python commands and `apply_patch` for edits.
- No mocks or monkeypatching; preserve the bounded single-source collector scope.
- Every changed behavior starts with a focused failing test.
- Run focused tests, Ruff, Pyright, then `make test`; commit once without amending.

---

### Task 1: Add review-regression fixtures

**Files:**
- Modify: `tests/unit/test_graph_projection_inventory.py`

- [ ] Add focused source fixtures for tracked-only subscript methods, deep reads and writes, RHS-before-rebind reads, stale normal aliases, exact calls/construction, comparisons, `CompFor`, metadata execution scopes, strict models, and sorting.
- [ ] Run `uv run pytest tests/unit/test_graph_projection_inventory.py -q` and confirm the new expectations fail against the current collector.

### Task 2: Correct collector receiver identity and traversal state

**Files:**
- Modify: `scripts/graph_projection_inventory.py`

- [ ] Add helpers which recognize a literal field subscript only when its chain roots in a tracked alias, suppress every node in a handled chain, and identify tracked comparison operands including `.get()` calls.
- [ ] Defer assignment and annotation alias updates to leave callbacks so RHS collection sees the pre-assignment environment; remove both live and historical aliases on normal rebinding.
- [ ] Make call, construction, comparison, comprehension, and lexical-name behavior use the new tracked identity helpers and exact supported shapes.
- [ ] Run the focused test file until all fixtures pass.

### Task 3: Verify and document evidence

**Files:**
- Modify: `.superpowers/sdd/task-1b-report.md`

- [ ] Run focused tests, Ruff, Pyright, and `make test`.
- [ ] Append exact RED/GREEN evidence, fixes, and remaining bounded-scope concerns to the Task 1b report.
- [ ] Inspect status/diff/log, then create one non-amended commit containing only Task 1b files.
