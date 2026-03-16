# Clarifications: Idea-to-Plan Routine Optimization

## Status: RESOLVED

The following design questions were identified by comparing the planning artifacts (intent.md, plan.md, architecture.md) against the actual routine YAML (`routines/idea-to-plan/routine.yaml`). All have been resolved.

---

## Q1: Step Numbering Mismatch

**Question:** The plan/architecture docs use a condensed 8-item numbering (S-01 through S-08) that skips gate steps, but the actual routine YAML has 9 steps (S-01 through S-09) including gates at S-02 and S-08. For example, the plan says "S-04/T-01 Create Step Files" but in the YAML that is S-05/T-01, and "S-05/T-01 Simulate Execution" is actually S-06/T-01.

**Context:** This mismatch affects every recommendation (R1-R7) since they all reference step IDs. Getting this wrong means applying changes to the wrong tasks.

**Mapping (plan docs -> actual YAML):**

| Plan/Arch Reference | Actual YAML Step | YAML Title |
|---|---|---|
| S-01/T-01 Generate Initial Artifacts | S-01/T-01 | Generate Initial Artifacts |
| S-02/T-01 Gather Requirements | S-02 (gate) + S-03/T-01 | Human Review + Plan Refinement |
| S-03/T-01 Create Step Plans | S-04/T-01 | Create Step Plans |
| S-04/T-01 Create Step Files | S-05/T-01 | Create Step Files |
| S-05/T-01 Simulate Execution | S-06/T-01 | Simulate Execution |
| S-06/T-01 Cross-Check | S-07/T-01 | Cross-Check All Artifacts |
| S-07/T-01 Human Final Approval | S-08 (gate) | Human Final Approval |
| S-08/T-01 Generate Summary | S-09/T-01 | Generate Summary |
| S-08/T-02 Create Routine YAML | S-09/T-02 | Create and Validate Routine YAML |

**Options:**
- (a) Update plan docs to use actual YAML step IDs (S-01 through S-09)
- (b) Keep logical numbering in docs and add an explicit mapping table

**Answer:** Moot — the actual routine YAML has 8 steps (S-01 through S-08), matching the planning docs. The premise of 9 steps was incorrect. Confirmed via Q4: docs corrected to match actual routine. No numbering changes needed.

---

## Q2: Routine File Location

**Question:** Should we modify the existing routine file (`examples/routines/idea_to_plan.yaml`) in place, or create a new optimized variant so the original is preserved for comparison?

**Context:** Having the original available makes A/B cost comparison easier during validation.

**Options:**
- (a) Modify `examples/routines/idea_to_plan.yaml` in place
- (b) Create a new variant file (e.g., `examples/routines/idea_to_plan_v2.yaml`), keep original unchanged
- (c) Copy original to a backup, then modify in place

**Answer:** (b) Create a new variant. See Q3 in orchestrator clarifications below — new variant `idea-to-plan-optimized` will be created.

---

## Q3: Fan-Out Scope (M4)

**Question:** The plan proposes fan-out (R2, R3) for Create Step Files and Simulate Execution. Fan-out is the most complex change (M4, estimated 2-3 hours) and adds risk around naming, context isolation, and cross-step dependencies. For a planning routine that typically produces 3-8 steps, the wall-clock savings may be modest. Should we include fan-out in this optimization, or defer it?

**Context:** M1 (context injection) alone is projected to save ~40% cost. Fan-out adds parallelism but also complexity. The plan already notes M4 is "optional if parallelism is not needed."

**Options:**
- (a) Include fan-out (full M4 implementation)
- (b) Defer fan-out -- focus on M1+M2+M3 only
- (c) Include fan-out for Create Step Files only, skip Simulate Execution

**Answer:** (a) Include fan-out (full M4 implementation). See Q1 in orchestrator clarifications below — all 4 milestones included.

---

## Q4: Model Profile Assignments

**Question:** What model assignments should be used for each profile tier?

**Context:** The architecture doc suggests architect=opus, coder=sonnet, summarizer=haiku. These determine the cost savings from R4 (profile-based model routing).

**Options:**
- (a) architect=claude-opus-4-6, coder=claude-sonnet-4-6, summarizer=claude-haiku-4-5
- (b) architect=claude-sonnet-4-6, coder=claude-sonnet-4-6, summarizer=claude-haiku-4-5
- (c) Use whatever is currently configured in the agent runner profiles (just add the `profile` field, don't prescribe models)

**Answer:** (a) architect=claude-opus-4-6, coder=claude-sonnet-4-6, summarizer=claude-haiku-4-5. See Q2 in orchestrator clarifications below.

---

## Q5: Dry Run Step Type Conflict

**Question:** S-06 in the YAML is a special `dry_run` step type with `target_steps`, `context_limit`, and `report_path` config. The plan proposes converting its task to fan-out, but this would conflict with the dry_run step type semantics. How should this be handled?

**Context:** The dry_run step type has special semantics that fan-out would lose. The plan does not address this interaction.

**Options:**
- (a) Remove `dry_run` type, convert to regular step with fan-out
- (b) Keep `dry_run` type as-is, only add `context_from` (skip fan-out for this step)
- (c) Remove `dry_run` type, convert to regular step but skip fan-out too

**Answer:** Restructure for fan-out. Remove `dry_run` type, convert S-05 to standard step with fan_out over step files. See Q6 in orchestrator clarifications below for full details on per-item context approach.

---

## Q6: Validation Scope

**Question:** Do you want a test run of the optimized routine as part of this task, or should validation be limited to YAML schema validation?

**Context:** Completion criterion #10 says "a test run completes with measurably lower cost." Running the routine requires an active idea, configured agent runner, and API keys.

**Options:**
- (a) Schema validation only -- test run is a separate follow-up
- (b) Include a test run if agent runner is available
- (c) Schema validation plus a dry-run simulation (no actual agent execution)

**Answer:** Live test using Claude CLI (already set up, no key needed). See Q5 in orchestrator clarifications below.

---

## Q7: Cross-Check Verifier (S-07)

**Question:** The current S-07 (Cross-Check All Artifacts) has a detailed verifier rubric with grade_scale [A-F] and submission_template. The plan proposes keeping LLM verification here but using a cheaper verifier model. Should the rubric/grade_scale be preserved as-is, simplified, or removed?

**Context:** This is the quality gate before human approval. Removing the verifier here risks missing consistency issues, but it is one of the more expensive verification steps.

**Options:**
- (a) Keep rubric and grade_scale as-is, just set verifier profile to summarizer
- (b) Simplify rubric (fewer criteria), keep grade_scale
- (c) Remove LLM verifier, rely on auto-verify + human review at S-08 gate

**Answer:** (a) Keep rubric and grade_scale as-is, just set verifier profile to summarizer. The cross-check is the quality gate — preserving the rubric ensures consistency checking. Cost savings come from using a cheaper verifier model (Sonnet), not removing verification.
## Clarification 1 (Step 44386181-ee59-4e64-b6e8-cccf8ab9ba34, Attempt 1)
**Requested:** 2026-03-16T19:35:46.201479+00:00

### Q1: Should all 4 milestones be implemented, or should M4 (fan-out parallelism) be deferred?
**Context:** The plan says M4 is optional and the most complex change (2-3 hours). M1-M3 alone achieve ~60% cost savings. M4 adds ~65% wall-clock time savings but requires restructuring S-04 and S-05.
**Options:**
1. All 4 milestones (M1-M4)
2. M1-M3 only (defer fan-out)
3. M1-M2 only (context + verification)
4. M1 only (context injection)

**Answer:** All 4 milestones (M1-M4)
**Answered by:** user
**Answered at:** 2026-03-16T19:57:13.477612+00:00

### Q2: What profile-to-model mappings should be used for the CLI_SUBPROCESS runner?
**Context:** The architecture suggests: architect=opus, coder=sonnet, summarizer=haiku. These mappings directly control cost savings.
**Options:**
1. Use suggested mappings (opus/sonnet/haiku)
2. All tasks on Opus (no cost optimization)
3. architect=opus, everything else=sonnet
4. Custom mapping

**Answer:** Use suggested mappings (opus/sonnet/haiku)
**Answered by:** user
**Answered at:** 2026-03-16T19:57:13.477678+00:00

### Q3: Should the existing routine be modified in-place, or should a new variant be created?
**Context:** Current routine at routines/idea-to-plan/routine.yaml. Options: modify in-place, create new variant, or keep both versions.
**Options:**
1. Modify in-place
2. New variant (idea-to-plan-optimized)
3. Keep both versions

**Answer:** New variant (idea-to-plan-optimized)
**Answered by:** user
**Answered at:** 2026-03-16T19:57:13.477686+00:00

### Q4: Planning docs reference 9 stages but actual routine has 8. Should docs be corrected to match actual routine?
**Context:** The task-to-stage mapping in intent.md, plan.md, and architecture.md references wrong stage numbers. S-07 is actually Final Plan Review gate, S-08 has Summary+Routine YAML. S-09 does not exist.
**Options:**
1. Yes, correct docs to match actual routine
2. No, docs define target structure

**Answer:** Yes, correct docs to match actual routine
**Answered by:** user
**Answered at:** 2026-03-16T19:57:13.477690+00:00

### Q5: How should the test run validation (completion criterion #10) be handled?
**Context:** Running a full test requires active agent runner and API keys. Options range from YAML validation only to full live test.
**Options:**
1. YAML validation only (defer live testing)
2. Single live test after all changes
3. Live test not needed

**Answer:** (custom) Live test, use Claude CLI. It is already setup, no key needs to be provided.
**Answered by:** user
**Answered at:** 2026-03-16T19:57:13.477695+00:00

### Q6: For S-05 dry run step: add context_from while keeping dry_run type, or restructure to fan_out?
**Context:** S-05 uses dry_run type with special config (target_steps, context_limit, report_path). Converting to fan_out would lose these. Adding context_from to existing structure is lower risk.
**Options:**
1. Keep dry_run type, just add context_from
2. Convert to fan_out plus merge task
3. Keep dry_run, add fan_out to S-04 only

**Answer:** (custom) Restructure for fan-out. Determine how to achieve appropriate context_from for each. This seems like it should be a common requirement. If it is not currently possible include in the plan work to enable having the context_from either be the files that were used for the fan out or provide a method for the output that drives the fan out to also provide things like unique contexts for each of the items.

Carryout the research into what is available now so that you can ask follow up questions if necesary.
**Answered by:** user
**Answered at:** 2026-03-16T19:57:13.477700+00:00

**Research findings (per-item context in fan-out):**
- `FanOutConfig` (in `src/orchestrator/config/models.py`) has: `input_glob`, `output_pattern`, `per_item_prompt`, `shared_context: list[str]`, `max_attempts`, `max_concurrent`, `auto_verify`
- Fan-out children get variables: `{{item_content}}`, `{{item_stem}}`, `{{output_path}}`, plus run config vars
- `shared_context` injects the same files into all children — no per-item variation
- `context_from` on the parent task is NOT inherited by fan-out children (confirmed via code review of `executor.py`)
- `resolve_template()` in `templates.py` is **single-pass** — `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` fails because the non-greedy regex `\{\{(.+?)\}\}` matches `{{file:docs/{{feature}}` as the first placeholder
- **Solution included in plan:** Two-pass template resolution — resolve plain variables first, then `{{file:...}}` references. This enables per-item context via `{{file:path/with/{{item_stem}}.md}}` in `per_item_prompt`. ~10 lines of code in `templates.py`.
