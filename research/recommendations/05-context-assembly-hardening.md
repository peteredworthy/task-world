# R05 — Context Assembly: Pinning, Budgets, Pointers, Cache Order

**Priority: P2 (P1 for constraint pinning, which is cheap). Effort: medium,
incremental.**

## Problem

Prompt assembly (`graph_runtime/prompts.py`) has coarse global caps (60K
chars) but no per-section discipline, no protection for constraints under
compaction, and no cache-aware ordering. The 28.8GB journal incident was the
payload-size version of the same missing discipline.

External evidence (all in
[../external/context-engineering.md](../external/context-engineering.md)):

- Constraints lost to summarization raise violation rates from ~5-10% to
  40-70%; **pinning restores baseline** (arXiv 2606.22528, High).
- Pointers + just-in-time retrieval beat pre-loaded content (Anthropic,
  Manus; High/Med); per-block size limits are the schema-level fix (Letta).
- Byte-stable prefix ordering and deterministic serialization are what make
  fresh-context-per-phase affordable under prompt caching (Manus, High).
- Recitation (objective restated near the context tail) fights
  lost-in-the-middle (Manus, Med).

## Proposed change

1. **Pin and recite constraints** (cheap, do first): acceptance criteria and
   requirement text are re-injected verbatim from typed state into every
   attempt's prompt, and the objective + acceptance criteria are *also*
   recited in a short block near the end of the assembled prompt. Never
   include them in any summarized/compacted section.
2. **Per-field token budgets in the payload schema**: as W5 typed-payload
   families land, each free-text field gets a max size enforced at
   validation, with overflow stored as a filesystem/artifact pointer
   (reversible compression — keep the reference, drop the content). This is
   the structural fix for both prompt bloat and journal bloat.
3. **Pointer-first hydration**: default `prompt_hydration_policy` for
   file-state and artifact records becomes digest + path + SHA (content
   fetchable by the agent's own tools), full content only where the edge
   explicitly opts in.
4. **Cache-aware ordering + deterministic serialization**: assemble prompts
   most-stable → most-volatile (role preamble → contract/spec → step context
   → per-attempt feedback); sort keys, no timestamps in stable sections.
   Measure before optimizing further (OQ-10 — subscription runners may see
   only latency wins).
5. **Test the assembler**: golden-file tests for representative node kinds
   (worker/verifier/planner) pinning section order, budget enforcement, and
   truncation behavior — currently the weakest-covered load-bearing module.

## Expected benefit

- Fewer constraint violations on long/multi-attempt tasks (the strongest
  quantitative result in the context literature).
- Structural immunity to the payload-bloat incident class.
- Cache savings where runners are API-metered; smaller prompts everywhere.

## Cost / complexity

Incremental; rides W5 for schemas. The assembler reordering is the riskiest
part purely because the module is untested today — hence item 5 lands first.

## Risks

- Pointer-first hydration assumes the agent will fetch content when needed;
  weak models may not. Mitigate: keep full-content opt-in per edge, use for
  the models that handle it.
- Over-aggressive field budgets could truncate real signal (verbatim errors
  must stay verbatim — allocate them their own generous budget).

## Validation

- Golden-file assembler tests; prompt-size distribution before/after from
  event data; constraint-violation proxy (verifier fails citing a stated
  requirement the builder ignored) on the R07 suite.

## Dependencies

W5 slices (schema budgets); R07 for outcome measurement.
