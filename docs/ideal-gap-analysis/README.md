# Ideal Gap Analysis

A proposed multi-phase routine step that replaces the current S5 "Dry Run" with a
tighter, cheaper loop that actually answers the right question.

---

## The Problem With the Current S5

S5 currently asks agents to "simulate execution" of a step file and identify failure modes.
This conflates two distinct questions:

1. **Completeness** — does this plan deliver everything the feature intent requires?
2. **Correctness** — will the plan work against the current codebase (right class names,
   right paths, correct wiring)?

The current prompt mixes both, which forces the agent to go read source files to answer
the correctness questions. That's why S5 children spawn Explore sub-agents despite already
having the codebase-discovery.md in shared context — the discovery doc covers signatures and
paths, but answering "will this test still pass?" or "is this call site wired?" requires
reading the actual test file, not just its name.

The correctness question is real and valuable. But the completeness question — the one that
closes the loop between intent and plan — is currently buried inside a long prompt alongside
six other concerns.

---

## The Right Question for a Dry Run

> Given this step plan, what functionality will be created? Does that match what was intended?
> If not, what is missing?

This question does **not** require reading source files. It only requires:
- The step file itself (what will be built)
- The intent document (what should be built)
- The plan document (how the steps relate to the intent)

It should be answerable from documents alone, making it fast and cheap.

---

## Ideal Architecture: Three-Phase Gap Loop

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1 — Enumerate (small model, per step, parallel)          │
│                                                                 │
│  Input:  step-XX.md (the YAML/markdown step file only)          │
│  Output: functionality-manifest.md                              │
│          - Bullet list of every distinct piece of functionality  │
│            this step will create                                │
│          - For each: "automatically tested" / "LLM verified" /  │
│            "unverified" based on what the step specifies        │
│          - Does NOT read the codebase. Static analysis only.    │
└────────────────────┬────────────────────────────────────────────┘
                     │ (per-step manifests, fast + cheap)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2 — Compare (smarter model, once across all steps)       │
│                                                                 │
│  Input:  intent.md + all functionality-manifest.md files        │
│  Output: gap-report.md                                          │
│          - Functionality in intent not covered by any step      │
│          - Functionality in steps not traceable to any intent   │
│            requirement (scope creep / drift)                    │
│          - Coverage of automated vs LLM-verified vs unverified  │
│          - Explicit list of gaps with severity                  │
└────────────────────┬────────────────────────────────────────────┘
                     │ (if gaps found)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3 — Close (coder model, targeted edits only)             │
│                                                                 │
│  Input:  gap-report.md + affected step files                    │
│  Output: updated step files with gaps addressed                 │
│          - Add missing tasks to the right step                  │
│          - Add verification requirements where unverified       │
│          - Remove scope-crept tasks                             │
│  Constraint: must not change step structure, only add/remove    │
│              tasks within existing steps                        │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
              gap-report-N.md (iteration counter)
              ────────────────
              if gaps still found → go back to Phase 2
              if no gaps         → proceed to next stage
```

### Iteration Guard

A gap loop without a termination condition is dangerous. Constraints:
- Maximum N iterations (suggest 3)
- Phase 2 on iteration N+1 must find **zero new gaps** (not zero gaps — previously
  closed gaps don't count as new)
- If max iterations reached with open gaps: emit a summary of unresolved gaps and
  proceed anyway (don't block the run indefinitely)

---

## Why This Is Better Than the Current S5

| | Current S5 | Ideal Gap Loop |
|---|---|---|
| **Question answered** | "will this plan work?" (mixed) | "does this plan cover the intent?" (focused) |
| **Source reading required** | Yes — verifying class names, paths, wiring | No — intent vs manifest comparison only |
| **Sub-agent spawning** | ~4 Explore agents per run | Zero (no source lookups needed) |
| **Phase 1 model** | Architect (expensive) | Haiku-class (cheap, enumeration only) |
| **Phase 2 model** | N/A | Sonnet-class (reasoning required) |
| **Iterative?** | No | Yes — loops until gaps are closed |
| **Gap in step files actually closed?** | No — notes written but steps not modified | Yes — Phase 3 edits the step files |
| **Coverage tracking** | None | Explicit per-requirement coverage map |

The current S5 writes dry-run notes but does not modify the step files. The gap loop
actually closes the gaps by editing the step files, which means S6/S7 work from an
already-hardened plan.

---

## Why S5 Currently Needs to Know Codebase State

(See also: why P3 in the synthesis report was wrong.)

In the `idea-to-plan-scoped` routine, S4 creates step *files* — planning documents in
`docs/{{feature}}/steps/`. **S4 does not change any source code.** There is no git diff
to inject after S4.

S5's sub-agent spawning is not about "changes from S4". It's about verifying step-file
assumptions against the actual codebase — "does `FooRepository.find_by_id` exist with
that exact signature?" The codebase-discovery.md in shared context handles the common
cases, but:

1. The discovery doc is built from the step *plans* (what the plan says will be touched),
   not from what the step *files* specify as their detailed tasks. If S4 agents refined
   the task descriptions beyond the plan, the discovery doc may not have captured those
   specific references.
2. "Will this test still pass?" questions require reading test files, which the discovery
   doc doesn't include in full.

The synthesis report's P3 proposal ("inject post-S4 git diff into S5") was based on a
misreading of what S4 does. The correct fix is either:
- Widen the codebase-discovery.md to cover what S5 actually queries (tests, more paths)
- Or adopt the gap-loop architecture above, which eliminates the need for source lookups
  in the completeness check entirely

---

## Phase 1 Prompt Sketch

```
You are given a single step file. Read it carefully.

For each task in this step, list exactly what new functionality will exist
after the task completes. Be specific and concrete:
  - "A new method `Foo.bar(x: int) -> str` in `src/foo.py`"
  - "The route `POST /api/items` will accept a new field `color`"
  - "Existing test `test_foo.py::test_bar` will pass"

Do NOT paraphrase the task description. Enumerate what will concretely exist.

For each piece of functionality, mark its verification tier:
  - AUTO: covered by an auto_verify item in this task
  - LLM: covered by the verifier rubric but not auto_verify
  - NONE: not verified by anything in this step

Step file:
{{item_content}}

Write your output as a structured list to {{output_path}}.
Do not read any source files. Do not use any tools.
```

No tool calls means no sub-agent spawning. This runs in a single turn.

---

## Phase 2 Prompt Sketch

```
You have a feature intent document and a set of per-step functionality manifests.
Your job is to identify gaps.

A gap is:
  - A requirement in the intent that is not covered by any task in any step
  - A piece of functionality in a step that does not trace to any intent requirement
  - Functionality marked NONE (no verification) for a critical intent requirement

Format your output as gap-report.md with:
  - Section 1: Missing coverage (intent req → "not found in steps")
  - Section 2: Scope drift (step functionality → "no matching intent req")
  - Section 3: Verification gaps (critical requirements with no AUTO or LLM check)
  - Section 4: Summary — total gap count, severity, recommended action per gap

If there are no gaps, write "NO GAPS FOUND" and stop.

Intent:
{{context.intent}}

Functionality manifests:
{{context.manifests}}
```

---

## Phase 3 Prompt Sketch

```
You are given a gap report and the step files it refers to.
Your only job is to edit step files to close the listed gaps.

Rules:
  - Only add or remove tasks within existing steps. Do not add new steps.
  - For each gap, add the minimum task necessary to close it.
  - For each verification gap, add an auto_verify item or strengthen the verifier rubric.
  - For each scope-drift item, either justify it (add a note linking it to an intent req)
    or remove it.
  - After editing, re-read each changed step file and confirm the gap is closed.

Gap report:
{{context.gap_report}}

Step files to edit:
{{context.affected_steps}}
```

---

## Implementation Notes (for when this is built)

- Phase 1 uses `fan_out` over `steps/step-*-plan.md` with `max_turns: 1` and no tools.
  Model should be the cheapest available (Haiku). Output is a manifest per step.

- Phase 2 uses `context_from` to aggregate all manifests + intent. Single task, no fan-out.
  Model should be Sonnet or better (reasoning over alignment required).

- Phase 3 uses `fan_out` over affected steps only (derived from gap-report.md). Coder model.

- The loop condition can be implemented as a routine `condition` on the Phase 2 task:
  something like `condition: { file_contains: { path: "gap-report.md", text: "NO GAPS FOUND" } }`
  or a small auto_verify check script.

- Phase 1 token cost estimate: ~5K per step × 4 steps = 20K tokens total (vs ~500K for
  current S5 sub-agent spawning per step).

- The codebase-correctness check (are the names/paths right?) is a separate concern from
  completeness and is better handled by making the codebase-discovery.md more comprehensive
  rather than by having S5 agents read source files live.
