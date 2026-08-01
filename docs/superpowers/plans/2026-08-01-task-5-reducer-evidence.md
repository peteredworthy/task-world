# Task 5 Reducer Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Task 5 evidence with public reducer regression coverage, current performance evidence, and a single accurate closure report.

**Architecture:** Exercise the `output_record_accepted` reducer only through `orchestrator.graph` public exports. Compare its stored projected record and checkpoint serialization with `project_record()` for fan-out records, and verify malformed event data is rejected by the canonical event payload model before projection. Keep the existing private reducer optimization private and do not change production code.

**Tech Stack:** Python 3.12, pytest, Pydantic v2, immutable graph projection models.

## Global Constraints

- Use public `orchestrator.graph` APIs only; do not import or export the internal reducer helper.
- Do not modify production APIs or `progress.md`.
- Keep the two-worker `loadgroup` contract in all current report language.
- Run the direct performance gate twice against the final committed code, record both outputs and medians, run focused regression tests, and allow normal commit hooks to run.

---

### Task 1: Add public reducer characterization regressions

**Files:**
- Modify: `tests/unit/test_graph_projected_records.py`

**Interfaces:**
- Consumes: `orchestrator.graph.EventEnvelope`, `FakeClock`, `Actor`, `ActorKind`, `initial_projection`, `reduce_event`, `project_record`, `projection_to_checkpoint`, and `OutputRecordAcceptedPayload`.
- Produces: regression tests that prove reducer conversion equals public conversion or correctly uses its fallback.

- [ ] **Step 1: Write reducer tests before production changes**

```python
source = OutputRecord.model_validate({
    **_fan_out_payload(),
    "candidate_id": None,
    "task_region_id": None,
    "attempt_number": None,
    "file_state_record_id": None,
    "file_state_record_ids": [],
    "payload": {},
    "provenance": {},
})
projection = reduce_event(initial_projection(), _accepted_record_event(source.model_dump(...)))
assert projection.records.by_id[source.record_id].model_dump(...) == project_record(source).model_dump(...)
```

Add two further tests: a native-JSON value nested more than 100 levels that compares reducer failure to `project_record()`, and a missing required canonical field that raises `ValidationError` from the event payload validation path.

- [ ] **Step 2: Run the three new tests to capture RED or characterization evidence**

Run: `uv run pytest tests/unit/test_graph_projected_records.py -q`

Expected: Either a behavior-specific failure requiring a minimal test-support adjustment, or passing characterization tests documenting that the existing reducer behavior already matches the public path.

- [ ] **Step 3: Make only a necessary test-support adjustment**

Do not change `src/orchestrator/graph`. If a test fixture is needed, keep it private to the test module and construct canonical `EventEnvelope` values with public graph models.

- [ ] **Step 4: Re-run reducer coverage**

Run: `uv run pytest tests/unit/test_graph_projected_records.py -q`

Expected: PASS.

### Task 2: Replace the closure report with final evidence

**Files:**
- Modify: `.superpowers/sdd/closure-task-5-report.md`

**Interfaces:**
- Consumes: current test results, direct gate output, git log, and the public/internal conversion contract.
- Produces: one current Task 5 report with historical samples explicitly labelled.

- [ ] **Step 1: Replace contradictory historical wording**

State that pytest defaults and hooks use two-worker `loadgroup` everywhere. List all Task 5 commits through this evidence commit placeholder, mark prior output samples historical, and distinguish public `project_record()` normalization/validation from the private reducer-only validated native fast path and its fallbacks.

- [ ] **Step 2: Add current regression and performance evidence**

Include the three public reducer regressions, both final direct gate outputs, their current per-scenario medians, focused test output, and normal hook output.

### Task 3: Verify and commit final evidence

**Files:**
- Modify: `tests/unit/test_graph_projected_records.py`
- Modify: `.superpowers/sdd/closure-task-5-report.md`

- [ ] **Step 1: Run focused regression suite**

Run: `uv run pytest tests/unit/test_graph_projected_records.py tests/unit/test_graph_projection_codec.py tests/unit/test_graph_projection_duplicate_ids.py tests/unit/test_graph_projection_performance.py -q`

Expected: PASS.

- [ ] **Step 2: Run the direct performance test twice on final source**

Run twice: `uv run pytest tests/unit/test_graph_projection_performance.py -q`

Expected: three rows pass on each run; record each command’s exact summary and test-emitted medians.

- [ ] **Step 3: Inspect intended changes and commit without amendment**

Run: `git status --short && git diff --check && git diff -- tests/unit/test_graph_projected_records.py .superpowers/sdd/closure-task-5-report.md`

Run: `git add tests/unit/test_graph_projected_records.py .superpowers/sdd/closure-task-5-report.md docs/superpowers/plans/2026-08-01-task-5-reducer-evidence.md && git commit -m "test(graph): add reducer conversion regressions"`

Expected: normal pre-commit hooks pass; do not use `--no-verify` or amend.
