# Task 4 Provenance Interpreter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the GraphProjection boundary collector's ad hoc statement traversal with a bounded AST-only forward abstract interpreter.

**Architecture:** A single mergeable `_FlowState` represents all runtime name bindings: exact module paths, projection certainty, receiver-type candidates, runtime field certainty, and local function return bindings. Static class field declarations remain separate. Expressions evaluate in Python order and statements produce explicit normal, raised, returned, broken, and continued outcomes; joins use absent/definite/possible semantics for every state component.

**Tech Stack:** Python 3.12 AST, Pydantic, pytest, Ruff, Pyright.

## Global Constraints

- Preserve `ProjectionProvenanceFact`, `projection_provenance`, `projection_provenance_seed_tokens`, checker integration, finite origin tables, and exact fact expressions.
- Keep the collector AST-only; do not import migration, LibCST, YAML, manifest, or report machinery.
- Do not modify `.superpowers/sdd/progress.md`.
- Run required RED families before replacing collector internals and commit a new commit without amendment.

---

### Task 1: Add focused failing interpreter contracts

**Files:**
- Modify: `tests/unit/test_graph_projection_boundaries.py`

**Interfaces:**
- Consumes: `projection_provenance(source, relative_path=...)` and `check_projection_boundaries(root, paths=...)`.
- Produces: RED regressions for named expressions, try outcomes, type/field joins, exact imports, and mutation semantics.

- [ ] **Step 1: Add named-expression and diagnostic tests**

Add tests proving `(alias := projection)["set"]` records its exact expression, `(alias := other)["kill"]` does not, short-circuit paths retain possible provenance where feasible, and the boundary checker emits the matching diagnostics.

- [ ] **Step 2: Add try and outcome tests**

Add tests proving a handler receives state from operations before a later overwrite, typed receiver state is possible after divergent paths, `else` executes only from normal try completion, and `finally` affects every outgoing outcome.

- [ ] **Step 3: Add type, import, and mutation tests**

Add tests proving receiver/field set-kill branch joins, graph/runtime sibling isolation and exact imports, root rebinding revocation, and attribute/subscript mutations retaining a receiver while typed-field mutation only kills that field.

- [ ] **Step 4: Run RED families**

Run: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q`

Expected: the new contracts fail under the current mutable walker while existing contracts remain collected.

### Task 2: Replace collector internals with bounded flow analysis

**Files:**
- Modify: `scripts/graph_projection_boundary_provenance.py`

**Interfaces:**
- Consumes: exact origin constants and parsed `ast.Module`.
- Produces: unchanged public facts using a `_FlowState`, `_Outcomes`, expression evaluator, and one transfer function per statement family.

- [ ] **Step 1: Define state lattice and joins**

Replace `_Scope` with `_FlowState` that joins every component across absent/definite/possible values. Store static class declarations outside state and preserve exact module bindings independently from projection aliases.

- [ ] **Step 2: Implement ordered expression evaluation**

Implement expression transfers that evaluate children in Python order, propagate conservative raised states, bind `NamedExpr` before recording it, and branch/join feasible BoolOp and IfExp paths.

- [ ] **Step 3: Implement statement outcome transfers**

Implement one transfer per compound statement; blocks feed only normal paths into later statements. Model return, raise, break, and continue explicitly. Route intermediate exceptional states into try handlers, normal completion into else, and every outgoing path through finally.

- [ ] **Step 4: Implement exact imports and independent typed fields**

Bind imports only to exact authorized module paths; preserve aliases, revoke bindings after rebinding, and never infer sibling access. Apply declared/runtime field set-kill joins without rebinding attribute or subscript receivers.

- [ ] **Step 5: Run focused GREEN suite**

Run: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q`

Expected: all existing and new boundary tests pass.

### Task 3: Verify, report, and commit

**Files:**
- Modify: `.superpowers/sdd/closure-task-4-report.md`

**Interfaces:**
- Consumes: implementation and test evidence.
- Produces: an architecture-reset and RED/GREEN report section.

- [ ] **Step 1: Run permanent guard and static checks**

Run: `uv run python scripts/check_graph_projection_boundaries.py && uv run ruff check scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py && uv run ruff format --check scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py && uv run pyright scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py`

Expected: all commands succeed.

- [ ] **Step 2: Append evidence report**

Append a section naming the architecture reset, each RED family and observed failure, GREEN command results, conservative-analysis boundary, and confirmation that progress was untouched.

- [ ] **Step 3: Commit without amendment**

Run: `git add scripts/graph_projection_boundary_provenance.py tests/unit/test_graph_projection_boundaries.py .superpowers/sdd/closure-task-4-report.md docs/superpowers/plans/2026-08-01-task-4-provenance-interpreter.md && git commit -m "refactor(graph): model boundary provenance flow"`

Expected: normal hooks pass and create one new commit.

---

### Task 4: Close bounded-interpreter review blockers

**Files:**
- Modify: `tests/unit/test_graph_projection_boundaries.py`
- Modify: `scripts/graph_projection_boundary_provenance.py`
- Modify: `.superpowers/sdd/closure-task-4-report.md`

**Interfaces:**
- Consumes: `_FlowState`, `_Outcomes`, `projection_provenance(source, relative_path=...)`.
- Produces: scope-isolated comprehensions, finite candidate-set provenance joins,
  Python-ordered chained assignment and dictionary-comprehension transfers, and
  conservative `with`/`async with` exception suppression outcomes.

- [x] **Step 1: Add review-blocker RED contracts**

  Add direct source-level contracts proving: a comprehension target shadows a
  `GraphProjection` parameter only inside the comprehension and the outer
  access remains definite; approved factory/receiver/function candidates join
  without string encoding and mixed approved/foreign candidates are possible;
  a first chained-assignment target's walrus affects the second target; a dict
  comprehension key walrus affects its value; and a body-raised `with` or
  `async with` state can possibly continue after an unresolved exit method.

- [x] **Step 2: Run and capture RED evidence**

  Run: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q`

  Expected: the added contracts fail specifically for leaking comprehension
  state, heterogeneous pipe-string joins, target/value ordering, or dropped
  suppressed-exception continuation.

- [x] **Step 3: Implement the smallest transfer corrections**

  Store exact origin, receiver, and function candidates as immutable finite
  sets; compute definite provenance only when every candidate is approved.
  Interpret comprehension bindings in a copied local state and return outer
  state after the element expression. Evaluate chained targets sequentially,
  assigning each completed target before evaluating the next. Evaluate dict
  comprehension keys before values. Preserve every body-raised `with` outcome
  and add a copy as a possible normal continuation after context exit.

- [x] **Step 4: Run GREEN boundary and quality gates**

  Run: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q && uv run python scripts/check_graph_projection_boundaries.py && uv run ruff check scripts/graph_projection_boundary_provenance.py tests/unit/test_graph_projection_boundaries.py && uv run ruff format --check scripts/graph_projection_boundary_provenance.py tests/unit/test_graph_projection_boundaries.py && uv run pyright scripts/graph_projection_boundary_provenance.py tests/unit/test_graph_projection_boundaries.py`

  Expected: all commands pass, including all added contracts.

- [x] **Step 5: Record evidence and commit normally**

  Append exact RED/GREEN command outcomes, conservative-analysis limits, and
  confirmation that `.superpowers/sdd/progress.md` was untouched to the Task 4
  report. Stage only the implementation, tests, report, and this plan, then
  run a normal `git commit` without amendment so configured hooks execute.
