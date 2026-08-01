# Task 7b Benchmark Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make graph-projection benchmark artifacts strict, comparable, and capable of enforcing every specified release gate deterministically.

**Architecture:** Keep measurement generation in `scripts/benchmark_graph_projection.py`, but model the serialized artifact with frozen strict Pydantic models and make compatibility and gate evaluation pure functions over validated documents. Each requested scenario/size becomes an independent measurement; generated n/2n probes are explicit metadata rather than inferred extrema.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, Ruff, Pyright.

## Global Constraints

- Do not create a production baseline artifact or alter the SDD progress ledger.
- Use hand-built result documents for gate mathematics; no mocks, monkeypatches, timing assertions, or private-helper wiring.
- The CLI smoke path writes and reloads a baseline but does not use noisy real timing ratios.
- Unsupported maximum-event-count discovery performs no network request and is recorded as `unsupported`.

---

### Task 1: Strict artifact schema and measurement generation

**Files:**
- Modify: `scripts/benchmark_graph_projection.py`
- Test: `tests/unit/test_benchmark_graph_projection.py`

**Interfaces:**
- Produces: `BenchmarkResult.model_dump(mode="json")` with schema/tool/source/corpus/scenario/runtime provenance and every `scenario/size` measurement.
- Produces: `benchmark(sizes, warmups, runs, api_url) -> dict[str, Any]` retaining the CLI contract.

- [ ] Write schema smoke assertions for every requested size, operation sample count, unit, role/signature, tool hash, and explicit scale probe.
- [ ] Run the focused test and confirm the old largest-size-only structure fails the assertion.
- [ ] Add frozen `extra="forbid"` Pydantic result models, stable script hash, corpus/scenario hashes, target role/signature, comparable and informational environment fields, per-size measurements, and n/2n probe measurements with startup medians.
- [ ] Replace the fictional API default with an unsupported discovery result unless an explicit operator count is supplied; validate the override as a nonnegative exact integer and label it `operator`.
- [ ] Re-run focused schema and smoke tests.

### Task 2: Pure compatibility and exact gate evaluator

**Files:**
- Modify: `scripts/benchmark_graph_projection.py`
- Test: `tests/unit/test_benchmark_graph_projection.py`

**Interfaces:**
- Produces: `gate_violations(baseline: dict[str, Any], target: dict[str, Any]) -> list[str]`, sorted deterministic diagnostics.
- Requires: baseline role `baseline` / pre-cutover signature and target role `target` / post-cutover signature.

- [ ] Write hand-built valid documents plus malformed/missing schema, tool, corpus, scenarios, requested/probe sizes, metrics, units, roles, source, runtime architecture/dependency, and warmup/run compatibility cases.
- [ ] Run those tests and confirm the current evaluator either accepts incompatible values or raises shape errors.
- [ ] Implement validation-before-math with sorted compatibility diagnostics; treat source revision and informational host/OS patch fields as provenance only, require matching Python/architecture/dependencies and an explicit warmup/run rule.
- [ ] Implement exact all-scenario/all-size boundaries: replay/memory 1.15, checkpoint 1.0, encode/decode/public-view 1.25, cold rebuild relative to baseline full replay 1.15, record-heavy target strictly below record-heavy baseline, and `(t_2n-startup)/(t_n-startup) <= 2.5` with invalid-denominator refusal.
- [ ] Re-run the pure evaluator tests.

### Task 3: Boundary matrix, CLI smoke, profiling link, and evidence

**Files:**
- Modify: `tests/unit/test_benchmark_graph_projection.py`
- Modify: `scripts/profile_graph_readback.py`
- Create: `.superpowers/sdd/task-7b-gates-report.md`

**Interfaces:**
- Verifies: just-inside, equal, and just-outside boundaries for every gate, including scale and record-heavy shrink.

- [ ] Add parametrized hand-built boundary tests and a subprocess smoke that writes/reloads a baseline without `--check-gates` ratio enforcement.
- [ ] Run the smoke test and confirm it completes below 15 seconds.
- [ ] Add one nonduplicative profile measurement/link documenting the shared projection readback relevance to the benchmark, without changing its unrelated workload.
- [ ] Run focused pytest, Ruff check/format, and Pyright; write the Task 7b report with exact commands, results, matrix, and deferred baseline concern.
- [ ] Commit the implementation and report without amendment.
