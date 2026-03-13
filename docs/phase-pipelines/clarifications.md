# Clarifications: Configurable Phase Pipelines

This document records the design questions identified in the planning artifacts and
their resolutions. No additional human Q&A was required — all questions were resolved
by the planning team during intent/plan/architecture authoring and are captured here
for traceability.

---

## Q1: How should `TaskStatus` enum handle new phase types?

**Question (from idea.md):** With arbitrary phase types, `TaskStatus` needs rethinking.
Two approaches were identified:
1. Keep existing statuses (`BUILDING`, `VERIFYING`) and map phase types to them
2. Add a generic `PHASE_ACTIVE` status and track phase type separately

**Answer:** Option 1 — keep existing `TaskStatus` values unchanged. Map all agent-based
phases (`plan`, `build`, `summarize`, `gap_check`, `script`) to `BUILDING`; map
verification phases (`verify`, `auto_verify`) to `VERIFYING`; map `human_review`
to `PENDING_USER_ACTION`. Add `current_phase_type` as a separate field on
`TaskDetailResponse` for fine-grained display.

**Rationale:** Zero DB enum migration; API consumers relying on `BUILDING`/`VERIFYING`
continue working without change.

---

## Q2: What does phase synthesis produce for `task_context` with no verifier and no auto_verify?

**Question:** The idea.md factory section listed three synthesis cases but did not cover
the case where a task has `task_context` but no `verifier` rubric and no `auto_verify`
items.

**Answer:** Synthesize `[build]` — a single build phase with no verification. This
matches the current behavior for such tasks (they complete after the build phase with
no verification step).

**Rationale:** Backward compatibility; such tasks already exist and currently show
`BUILDING` then transition to completed without a verification step.

---

## Q3: Is `phases` mutually exclusive with `fan_out`?

**Question:** Should `phases` be allowed on fan-out tasks?

**Answer:** `phases` is mutually exclusive with `fan_out`. Fan-out subtask phase support
is deferred. During phase synthesis, fan-out tasks skip synthesis entirely (no
`phases_config` set).

**Rationale:** Fan-out uses a separate executor path; mixing phase pipelines with
fan-out adds complexity without a clear use case right now.

---

## Q4: Where should `retry_target` validation live?

**Question:** `PhaseConfig.retry_target` requires knowing the position of the phase
within the pipeline to validate (`retry_target` must be < current phase index). Where
does this validation belong?

**Answer:** Validation at `TaskConfig` level (not `PhaseConfig` level), since the full
phase list context is needed to check the bound.

---

## Q5: How are `phase_outputs` keys handled in JSON serialization?

**Question:** `phase_outputs: dict[int, str]` uses integer keys, but JSON only supports
string keys. How should this be handled?

**Answer:** Pydantic serializes `dict[int, str]` to JSON with string keys (`"0"`, `"1"`,
etc.) and deserializes back to int keys. The API schema also uses `dict[int, str]`, so
both backend and frontend receive string-keyed JSON. The frontend type definition uses
`Record<number, string>` which TypeScript handles from JSON string keys.

No additional changes needed — standard Pydantic behavior.

---

## Summary

All design questions were resolved during planning without requiring additional human
input. The planning documents (intent.md, plan.md, architecture.md) are consistent and
complete. Implementation may proceed directly.
