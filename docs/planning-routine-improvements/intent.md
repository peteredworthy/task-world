# Intent: Idea-to-Plan Routine Optimization

## Goal

Reduce the cost, latency, and duplicate work of the `idea-to-plan` routine by applying seven recommendations (R1-R7) identified through token usage analysis of production runs. The target is a 60-70% cost reduction ($18 -> $5-7) and 65% wall-clock reduction (70 min -> 20-25 min) without sacrificing plan quality. [S-06/T-02/R1, S-06/T-02/R3]

## Scope

### In Scope

- **R1: Add `context_from` to every task** -- Inject previously-generated artifacts into task prompts via `context_from` declarations so agents don't waste tool calls rediscovering files. Tasks S-04/T-01, S-05/T-01, S-06/T-01, S-08/T-01, and S-08/T-02 currently lack `context_from` and will receive it. Note: When M4 converts S-04/T-01 and S-05/T-01 to fan_out tasks, their `context_from` entries are superseded by `shared_context` (since `context_from` is ignored at runtime for fan_out tasks). [S-01/T-01/R2, S-05/T-01/R4]
- **R2: Fan-out Create Step Files** -- Convert S-04/T-01 from sequential to parallel execution using `fan_out` over `docs/{{feature}}/step-*-plan.md`, with each sub-agent processing one step plan independently. [S-05/T-01/R1, S-05/T-01/R2]
- **R3: Fan-out Simulate Execution** -- Restructure S-05 from `dry_run` step type to standard step with `fan_out` over `docs/{{feature}}/steps/step-*.md`. Each sub-agent simulates one step file with per-item context from `{{item_content}}` and shared context (intent, plan, architecture). A merge task (T-02) synthesises cross-step risks. This replaces the `dry_run` type's `target_steps`, `context_limit`, and `report_path` config with fan-out parallelism. [S-05/T-02/R1, S-05/T-02/R2, S-05/T-02/R4]
- **R4: Profile-based model routing** -- Add `profile` fields to each task in the routine YAML to route mechanical tasks (step file creation, summary, YAML generation) to cheaper models (Sonnet/Haiku) while keeping architectural reasoning tasks on Opus. [S-03/T-01/R1, S-03/T-01/R2]
- **R5: Drop LLM verification on mechanical tasks** -- Remove `verifier.rubric` from tasks where auto-verify commands can fully validate output (S-07/T-01 Human Approval, S-08/T-01 Generate Summary). Set `verifier_model` to Sonnet for remaining tasks. [S-02/T-01/R1, S-02/T-01/R2]
- **R6: Embed reference docs in prompts** -- Use `context_from` to inject stable reference documents (`idea_to_plan_stripped.md`, `step-files.md`) that agents currently discover by reading files. [S-01/T-01/R3]
- **R7: Suppress source code exploration** -- Add prompt instructions to S-01/T-01 discouraging source code reads, since the `codebase_context` input and reference docs are sufficient. [S-01/T-01/R4]
- **Routine YAML creation** -- The optimized routine lives at `routines/idea-to-plan-optimized/routine.yaml`. The original routine at `routines/idea-to-plan/routine.yaml` is preserved unchanged for A/B comparison. [S-01/T-01/R1, S-01/T-01/R5]
- **Engine enhancement: Two-pass template resolution** -- Modify `src/orchestrator/workflow/templates.py` `resolve_template()` to resolve plain variables first (e.g., `{{feature}}`, `{{item_stem}}`), then resolve `{{file:...}}` references in a second pass. Currently, resolution is single-pass, so `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` fails because the regex matches `{{file:docs/{{feature}}` as the first placeholder. Two-pass resolution enables fan-out `per_item_prompt` templates to read per-item context files dynamically. This is a small, targeted change (~10 lines). [S-04/T-01/R1, S-04/T-01/R2]
- **Engine enhancement: Pass run variables to shared_context resolution** -- Modify `src/orchestrator/runners/executor.py` fan-out execution (line ~1206) to pass the run variables dict to `resolve_template()` when resolving `shared_context` entries. Currently, `shared_context` is resolved without variables, so `{{file:docs/{{feature}}/intent.md}}` in `shared_context` fails to resolve `{{feature}}`. This is a one-line fix (add `variables=variables` to the `resolve_template` call). [S-04/T-02/R1, S-04/T-02/R2]

### Out of Scope

- **Agent died / server stability** -- The 20 restarts observed in b46dbe62 are a server issue, not a routine design issue. The `server_shutdown` auto-resume mechanism handles this separately. [NO-REQ: server infrastructure, not routine optimization]
- **Within-task context window eviction** -- LLM context window limitations cause re-reads within a single task. This is mitigated partially by fan-out (R2, R3) but not directly addressable via routine config. [NO-REQ: LLM infrastructure limitation, partially mitigated by S-05/T-01/R1, S-05/T-02/R2]
- **ToolSearch cold-start overhead** -- 32 ToolSearch calls per fresh agent session are Claude Code infrastructure overhead, not controllable from routine YAML. [NO-REQ: Claude Code infrastructure, not controllable from routine config]
- **Variable plan sizes** -- A plan with 8 steps costs more than one with 3. This is proportional to work, not waste. [NO-REQ: inherent scaling, not waste]
- **New orchestrator features beyond template/executor fixes** -- The two-pass template resolution and shared_context variable fix are the only engine modifications. No new config schema fields, API endpoints, or execution flow changes are needed. [NO-REQ: scope boundary — engine changes limited to S-04/T-01, S-04/T-02]
- **Other routines** -- This effort targets only `idea-to-plan`. Lessons learned may apply to other routines but that is a separate effort. [NO-REQ: explicit scope exclusion]

## Actual Routine Structure (8 steps)

The existing routine at `routines/idea-to-plan/routine.yaml` has 8 steps: [NO-REQ: informational context, structure preserved by S-01/T-01/R5]

| Step | Title | Tasks |
|------|-------|-------|
| S-01 | Initial Plan | T-01: Generate Initial Artifacts |
| S-02 | Requirements Gathering | T-01: Gather Requirements and Update Docs |
| S-03 | Step Planning | T-01: Create Step Plans |
| S-04 | Task Breakdown | T-01: Create Step Files |
| S-05 | Dry Run & Failure Mode Analysis | T-01: Simulate Execution and Analyze Failure Modes |
| S-06 | Final Check | T-01: Cross-Check All Artifacts |
| S-07 | Final Plan Review | Gate (human_approval) + T-01: Human Final Approval |
| S-08 | Execution Ready | T-01: Generate Summary, T-02: Create and Validate Routine YAML |

## Model Profile Mappings

For the CLI_SUBPROCESS agent runner: [S-03/T-01/R2]
- `architect` -> `claude-opus-4-6` (reasoning-heavy tasks: initial artifacts, requirements, step planning, simulation) [S-03/T-01/R2]
- `coder` -> `claude-sonnet-4-6` (structured output tasks: step files, cross-check, routine YAML) [S-03/T-01/R2]
- `summarizer` -> `claude-haiku-4-5` (mechanical tasks: approval acknowledgment, summary, merge) [S-03/T-01/R2]

## Completion Criteria

1. The optimized routine YAML (`routines/idea-to-plan-optimized/routine.yaml`) has context injection on all tasks that consume prior artifacts: `context_from` for non-fan_out tasks (S-06/T-01, S-08/T-01, S-08/T-02, plus reference doc injection on S-01/T-01), and `shared_context` for fan_out tasks (S-04/T-01, S-05/T-01). [S-01/T-01/R2, S-05/T-01/R1, S-05/T-01/R4, S-05/T-02/R2]
2. S-04/T-01 uses `fan_out` over step-plan files with `max_concurrent: 4` and per-item auto-verify. [S-05/T-01/R1]
3. S-05 is restructured from `dry_run` type to standard step: S-05/T-01 uses `fan_out` over step files, S-05/T-02 is a merge task using `profile: "summarizer"`. [S-05/T-02/R1, S-05/T-02/R2, S-05/T-02/R4]
4. Every task has an appropriate `profile` field (`architect`, `coder`, or `summarizer`). [S-03/T-01/R1]
5. S-07/T-01 and S-08/T-01 have no `verifier.rubric` (auto-verify only). [S-02/T-01/R1, S-02/T-01/R2]
6. S-01/T-01 task_context includes a directive not to read source code files. [S-01/T-01/R4]
7. S-01/T-01 has `context_from` entries for `idea_to_plan_stripped.md` and `idea_to_plan_detailed.md`. [S-01/T-01/R3]
8. The optimized routine YAML passes `uv run orchestrator --json routines validate`. [S-01/T-01/R6, S-06/T-01/R1]
9. All existing auto-verify commands still work with the restructured tasks. [S-06/T-01/R3, S-06/T-01/R4]
10. A live test run (using Claude CLI) of the optimized routine on a small idea completes successfully with measurably lower cost than the baseline ($18.28). [S-06/T-02/R1, S-06/T-02/R3]
11. `templates.py` supports two-pass resolution (variables first, then `{{file:...}}`), enabling per-item context in fan-out prompts. [S-04/T-01/R1, S-04/T-01/R4]
12. `executor.py` passes run variables to `shared_context` resolution, enabling `{{feature}}` in shared_context file paths. [S-04/T-02/R1, S-04/T-02/R3]
13. The original routine at `routines/idea-to-plan/routine.yaml` is unchanged. [S-01/T-01/R5, S-06/T-01/R2]

## Key Unknowns and Risks

| Unknown | Risk | Mitigation |
|---------|------|------------|
| Fan-out `output_pattern` naming | `item_stem` for `step-03-plan.md` yields `step-03-plan`, not `step-03` -- output files may have unexpected names | Test with a 2-step plan first; adjust `output_pattern` or use `per_item_prompt` to specify exact output filename [S-05/T-01/R1, S-06/T-02/R1] |
| Fan-out sub-agent context isolation | Sub-agents do NOT inherit `context_from` from parent task (confirmed by code review) | Use `shared_context` for common files; use two-pass template resolution for per-item `{{file:...}}` references in `per_item_prompt` [S-05/T-01/R4, S-04/T-01/R1] |
| Profile-to-model mapping configuration | Profile fields in YAML have no effect unless agent runner has matching model mappings configured | Document required agent settings; verify profile resolution works before full run [S-03/T-01/R2, S-06/T-02/R1] |
| Removing verifier on S-08/T-01 | Auto-verify may miss quality issues that LLM verification would catch | Keep auto-verify checks for file existence + section headers; accept trade-off since this is a summary task [S-02/T-01/R2] |
| Cross-step risk synthesis in S-05/T-02 | Merge task may miss dependencies between steps that sequential analysis would catch | Include `intent.md` and `plan.md` in merge task context; add cross-step risk as an explicit section requirement [S-05/T-02/R4] |
| `context_from` token overhead | Injecting all artifacts into every task may push some tasks past context limits | Monitor token counts; largest tasks (S-06, S-08/T-02) already read these files, so net effect should be neutral or positive [S-01/T-01/R2, S-06/T-02/R1] |
| S-05 dry_run removal | Losing `context_limit` and `target_steps` semantics when converting to fan_out | Fan-out achieves the same simulation goal with better parallelism; context control moves to `per_item_prompt` and `shared_context` [S-05/T-02/R1] |
| `context_from` ignored during fan_out | Schema allows both fields on a task, but executor skips `context_from` when running fan_out children | Use `shared_context` for common artifacts; two-pass template resolution (M4) enables per-item context via `{{file:...}}` in `per_item_prompt` [S-05/T-01/R3, S-05/T-02/R3] |
| Two-pass template resolution | Could cause unexpected behavior if a resolved variable value contains `{{file:...}}` patterns | Second pass only processes `{{file:...}}` patterns, not arbitrary placeholders -- limits blast radius. Add unit tests for edge cases. [S-04/T-01/R4] |
