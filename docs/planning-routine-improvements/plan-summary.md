# Plan Summary: Idea-to-Plan Routine Optimization

## Intent Satisfaction

This plan addresses all seven recommendations (R1-R7) from the token usage analysis of the `idea-to-plan` routine. The target is a 60-70% cost reduction ($18.28 baseline to $5-7) and 65% wall-clock time reduction (70 min to 20-25 min). All 13 completion criteria from intent.md are covered across 6 implementation steps, verified by traceability audit.

| Recommendation | Description | Milestone | Status |
|---|---|---|---|
| R1 | Add `context_from` to every task | M1 (Step 1) | Planned |
| R2 | Fan-out Create Step Files | M4 (Step 5) | Planned |
| R3 | Fan-out Simulate Execution | M4 (Step 5) | Planned |
| R4 | Profile-based model routing | M3 (Step 3) | Planned |
| R5 | Drop LLM verification on mechanical tasks | M2 (Step 2) | Planned |
| R6 | Embed reference docs in prompts | M1 (Step 1) | Planned |
| R7 | Suppress source code exploration | M1 (Step 1) | Planned |

## Ordered Step List

| Step | Title | Tasks | Milestone | Estimated Impact |
|------|-------|-------|-----------|-----------------|
| 1 | Context Injection | 1 | M1 (R1, R6, R7) | ~40% cost reduction |
| 2 | Verification Optimization | 1 | M2 (R5) | ~$3-5 savings |
| 3 | Profile-Based Model Routing | 1 | M3 (R4) | ~$5-7 savings |
| 4 | Engine Enhancements (M4 prereqs) | 2 | M4 prereqs | Enables fan-out |
| 5 | Fan-Out Parallelism | 2 | M4 (R2, R3) | ~65% wall-clock savings |
| 6 | Validation and Live Test | 2 | All | Confirms savings |

**Total: 6 steps, 9 tasks.**

### Step Details

**Step 1 — Context Injection (M1):** Copy original routine to `routines/idea-to-plan-optimized/routine.yaml`. Add `context_from` to S-04/T-01, S-05/T-01, S-06/T-01, S-08/T-01, S-08/T-02. Inject reference docs (`idea_to_plan_stripped.md`, `idea_to_plan_detailed.md`) into S-01/T-01 and format guide (`step-files.md`) into S-04/T-01. Add source code suppression directive to S-01/T-01. Zero risk — purely additive.

**Step 2 — Verification Optimization (M2):** Remove `verifier.rubric` from S-07/T-01 and S-08/T-01. Add structural auto-verify to S-08/T-01 (file existence + section headers). Eliminates unnecessary LLM verifier spawns.

**Step 3 — Profile-Based Model Routing (M3):** Add `profile` field to all tasks: `architect` (Opus) for S-01, S-02, S-03, S-05/T-01; `coder` (Sonnet) for S-04, S-06, S-08/T-02; `summarizer` (Haiku) for S-07, S-08/T-01, S-05/T-02.

**Step 4 — Engine Enhancements:** Task 1: Two-pass template resolution in `templates.py` — Pass 1 resolves plain `{{variable}}` using `[^{]+?` regex, Pass 2 resolves `{{file:...}}` references (~10 lines). Task 2: Pass run variables to `shared_context` resolution in `executor.py` (~3 lines). Both are prerequisites for fan-out per-item context.

**Step 5 — Fan-Out Parallelism:** Task 1: Convert S-04/T-01 to `fan_out` over `step-*-plan.md` files with `max_concurrent: 4`, `shared_context`, and per-item auto-verify. Task 2: Restructure S-05 from `dry_run` type to standard step with fan-out T-01 (per-step simulation) + merge T-02 (synthesize `dry-run-notes.md`).

**Step 6 — Validation and Live Test:** Task 1: Schema validation (`uv run orchestrator --json routines validate`), unit tests, integration tests, verify original routine unchanged. Task 2: Live test using Claude CLI on a small idea, compare cost (<$12 gate), time, and tool calls to baseline.

## Key Decisions

1. **All 4 milestones implemented** — M4 (fan-out parallelism) included despite being the most complex change, because it adds ~65% wall-clock savings on top of M1-M3's cost savings.

2. **New variant, not in-place modification** — Optimized routine at `routines/idea-to-plan-optimized/routine.yaml`; original preserved for A/B comparison.

3. **Profile-to-model mappings** — `architect` -> `claude-opus-4-6`, `coder` -> `claude-sonnet-4-6`, `summarizer` -> `claude-haiku-4-5`. Must be configured on the CLI_SUBPROCESS agent runner.

4. **S-05 restructured for fan-out** — Converted from `dry_run` step type to standard step with fan-out + merge. Two-pass template resolution enables per-item context via `{{file:docs/{{feature}}/{{item_stem}}.md}}` in `per_item_prompt`.

5. **Docs corrected to match actual routine** — 8 steps (S-01 through S-08), not 9. S-07 is Final Plan Review gate, S-08 has Summary + Routine YAML.

6. **Live test via Claude CLI** — Already configured, no API key setup needed. Primary gate: cost < $12.

7. **`context_from` `as:` values use `context.` prefix** — GAP-17 fix: the prompt generator resolves `as: "context.plan"` to `{{context.plan}}` in task_context templates.

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Reference docs (`docs/plan-runner/*.md`) may not exist at runtime | MEDIUM | Step 1 includes dependency check with existence test and fallback instructions |
| Fan-out `item_stem` naming — `step-03-plan.md` yields stem `step-03-plan`, not `step-03` | HIGH | GAP-09 applied: use `{{item_stem}}.md` not `{{item_stem}}-plan.md` to avoid double-plan naming |
| `fan_out` and `task_context` are mutually exclusive (ValueError) | CRITICAL | GAP-08 applied: step 5 explicitly removes `task_context` when adding `fan_out` |
| Two-pass template regex — original `.+?` fails on nested `{{}}` | CRITICAL | GAP-05 applied: Pass 1 uses `[^{]+?` character class that cannot match across `{{` boundaries |
| `shared_context` bare paths produce literal strings, not file contents | HIGH | GAP-10 applied: all `shared_context` entries use `{{file:...}}` format |
| Profile mappings not configured — silent fallback to default model | MEDIUM | Step 6 includes pre-flight environment check for profile mapping verification |
| Cross-step risk synthesis in S-05/T-02 may miss inter-step dependencies | MEDIUM | Merge task receives intent + plan context; cross-step risk is an explicit required section |
| `context_from` token overhead pushing tasks past context limits | LOW | Net effect neutral or positive — tasks already read these files via tool calls |

## Caveats for Execution

1. **Engine changes (Step 4) must complete before Step 5.** Fan-out per-item context depends on two-pass template resolution and shared_context variable passing. Steps 1-3 are independent and can be validated without engine changes.

2. **Profile mappings are runtime configuration, not YAML.** Adding `profile` fields to the routine (Step 3) has no effect unless the agent runner has corresponding model mappings configured. Step 6 includes a pre-flight check but the mappings must be set up manually via the Agents UI or API before the live test.

3. **The `dry_run` step type is removed from S-05.** This is a one-way change for the optimized variant. The `dry_run` type's `target_steps`, `context_limit`, and `report_path` config is replaced by fan-out parallelism. If fan-out proves problematic, reverting requires restoring `type: dry_run` configuration.

4. **Live test cost depends on plan complexity.** The $12 pass gate assumes a small test idea. A complex idea with 6+ steps will cost more due to fan-out spawning more sub-agents, though per-step cost should still be lower than baseline.

5. **Four non-critical documentation inconsistencies exist** in `architecture.md` and `step-05-plan.md` (stale regex notation, wrong mutual exclusivity claim, double-plan naming in examples). Step files have the correct specifications. These should be fixed during implementation but are not blocking.

6. **No new database migrations or state model changes.** All changes are routine YAML config and two small engine function fixes. No persistence impact.

7. **Original routine must remain byte-identical.** Step 6 validates this explicitly. Any accidental modification to `routines/idea-to-plan/routine.yaml` is a test failure.
