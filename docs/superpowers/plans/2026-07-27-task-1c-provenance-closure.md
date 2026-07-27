# Task 1c Provenance Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the GraphProjection inventory provenance-strict, Python-call-aware, recursively collection-safe, and artifact-verified.

**Architecture:** Preserve the LibCST collector and source positions. Replace permissive name-tail recognition with immutable AST-derived per-module facts for approved origins and local callable signatures; use those facts plus LibCST scope metadata to invalidate shadowed symbols. Centralize recursive projection-bearing value detection and outer-boundary diagnostic suppression.

**Tech Stack:** Python 3.12, `ast`, LibCST metadata scopes, Pydantic, pytest, Ruff, Pyright.

## Global Constraints

- Trust only approved fully-qualified graph origins and `typing.cast`; never infer from a matching terminal name.
- Preserve lexical shadowing and emit diagnostics rather than applying general type inference.
- Use `uv run` for Python commands and retain the existing report ordering/format.
- Do not modify the pre-existing `.superpowers/sdd/progress.md` worktree change.

---

### Task 1: Add failing provenance and call-binding regressions

**Files:**
- Modify: `tests/unit/test_graph_projection_inventory.py`

**Interfaces:**
- Consumes: `inventory_paths(paths, manifest, root=None) -> AccessInventory`
- Produces: adversarial requirements for origin trust, shadowing, exact parameter binding, and one outer diagnostic per collection escape.

- [ ] **Step 1: Write failing test fixtures**

Add source fixtures importing foreign `GraphProjection` and `cast`, then locally redefining approved producer/constructor/cast names. Add local functions with reordered positional, keyword, object/Any, malformed, and variadic parameter bindings. Assert only approved non-shadowed uses are trusted and all unsupported bindings produce their expected diagnostic code.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `uv run pytest tests/unit/test_graph_projection_inventory.py -q`

Expected: the new provenance/call-binding assertions fail because current same-tail and pass-through logic is permissive.

### Task 2: Build strict immutable module facts and Python call binding

**Files:**
- Modify: `scripts/graph_projection_inventory.py`
- Test: `tests/unit/test_graph_projection_inventory.py`

**Interfaces:**
- Produces immutable module symbol records for approved origins, field owners, `typing.cast`, and callable parameter signatures.
- Produces a call-binding result mapping actual argument indexes/keywords to declared parameters or an ambiguity/error state.

- [ ] **Step 1: Implement immutable approved-origin and signature records**

Replace tail-name acceptance with frozen records whose values are explicitly approved fully-qualified names. Record exact parameter kinds and each parameter annotated by the approved `GraphProjection` symbol. Resolve annotations/callees only through those records and invalidate a name when a scope binds it as a parameter, local definition, or assignment.

- [ ] **Step 2: Implement bounded Python argument binding**

Bind positional and keyword arguments against the recorded signature. Permit a tracked value only for an exact projection parameter; emit an unsupported-call/binding diagnostic for object/Any/other parameters, duplicate/missing parameter configurations, stars, and variadic ambiguity.

- [ ] **Step 3: Run focused tests to verify pass**

Run: `uv run pytest tests/unit/test_graph_projection_inventory.py -q`

Expected: all existing and new provenance/binding tests pass.

### Task 3: Enforce recursive collection escape boundaries

**Files:**
- Modify: `scripts/graph_projection_inventory.py`
- Modify: `tests/unit/test_graph_projection_inventory.py`

**Interfaces:**
- Produces one outer `InventoryDiagnostic` for a recursive collection containing a tracked projection at assignment, annotation, return, call/constructor, or nested collection boundary.

- [ ] **Step 1: Write failing boundary tests**

Add lists, tuples, sets, and dictionaries nested through each other at plain/annotated assignment, return, callable/constructor arguments, and nested literal values. Assert a single outer diagnostic and no descendant diagnostic for each escaped aggregate.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `uv run pytest tests/unit/test_graph_projection_inventory.py -q`

Expected: current collector misses return/call/annotation boundaries or emits child duplicates.

- [ ] **Step 3: Implement recursive value classification and suppression**

Centralize recursive literal traversal and boundary ownership. Mark the outermost handled collection expression before visiting children; report it according to its enclosing assignment, return, or call boundary and suppress nested child reports.

- [ ] **Step 4: Run focused tests to verify pass**

Run: `uv run pytest tests/unit/test_graph_projection_inventory.py -q`

Expected: one deterministic outer diagnostic per collection escape and no regressions.

### Task 4: Verify and regenerate the authoritative report

**Files:**
- Modify: `tests/unit/test_graph_projection_inventory.py`
- Modify: `docs/graph-projection-inventory-diagnostics.md`
- Modify: `.superpowers/sdd/task-1c-report.md`
- Create: `.superpowers/sdd/task-1c-provenance-closure-report.md`

**Interfaces:**
- Consumes: `uv run python scripts/graph_projection_inventory.py --diagnose`
- Produces: exact checked-in report equal to generated diagnostic output and an accurate Task 1c history.

- [ ] **Step 1: Add artifact equality regression**

Generate the repository report via `inventory_repository`/`diagnostic_report` and assert exact equality with `docs/graph-projection-inventory-diagnostics.md`.

- [ ] **Step 2: Regenerate the artifact and correct claims**

Run the required `--diagnose` command, capture its full output into the diagnostics artifact, and revise Task 1c history so it describes the prior partial provenance pass and this final strict closure accurately. Append a concise evidence report with commands, outputs, artifact count, and scope.

- [ ] **Step 3: Run required verification and commit**

Run: `uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py && uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py && uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py && uv run python scripts/graph_projection_inventory.py --diagnose; uv run pytest`

Expected: style/type checks and full suite pass; diagnose exits 1 only because its checked-in unresolved diagnostics are intentional and artifact-equal.

Commit all intended files with: `git commit -m "fix: close task 1c provenance gaps"`.
