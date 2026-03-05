# Step 12: Context summarization with critical-aspect preservation (A13)

**Milestone:** M4 — Schema & Architecture Extensions
**Plan:** [step-12-plan.md](../step-12-plan.md)
**Architecture:** [architecture.md](../architecture.md) §2 (Config Models, A13) and §4 (Prompt Builder, A13)
**Intent:** [intent.md](../intent.md) — Completion Criteria #9
**Clarification:** Q4 in [clarifications.md](../clarifications.md) — configurable model with cheap default

## Tasks

### Task 12.1: Extend ContextFromConfig schema for summarization

Add `summarize: bool = False`, `critical: str | None = None`, and
`summarize_model: str | None = None` to `ContextFromConfig`.

**Files:** `src/orchestrator/config/models.py`
**LOC estimate:** ~15
**Verify:** Unit tests — schema accepts new fields; defaults are correct;
validation passes.

### Task 12.2: Implement summary cache

Create `summary_cache.py` with a dict-based cache keyed by
`(artifact_path, content_hash)`. Cache lifetime is the run duration.

**Files:** `src/orchestrator/workflow/summary_cache.py` (new)
**LOC estimate:** ~40
**Verify:** Unit tests — cache stores and retrieves summaries; different
content hash produces cache miss.

### Task 12.3: Integrate summarization into prompt assembly

In `prompts.py`, when `context_from` has `summarize: true`:
1. Check summary cache
2. If miss, call summarization model (configurable, default cheap model)
3. If `critical` set, verify critical aspects preserved; re-summarize up to
   2 times if missing
4. Cache result
5. Fall back to full content on model failure

**Files:** `src/orchestrator/workflow/prompts.py`
**LOC estimate:** ~80
**Verify:** Unit tests — summary generated; cache hit skips model call;
missing critical triggers re-summarization; model failure falls back to full
content. Integration test — end-to-end prompt with summarized context.
