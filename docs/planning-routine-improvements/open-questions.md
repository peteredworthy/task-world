# Open Design Questions for Idea-to-Plan Routine Optimization

These questions were identified by reviewing intent.md, plan.md, and architecture.md.
They require human input before the planning documents can be finalized.

## Q1: Milestone Scope

**Context:** The plan defines 4 milestones. M1-M3 are YAML-only changes (context injection,
verification optimization, profile routing). M4 (fan-out parallelism) is described as "optional
if parallelism is not needed" and is the most complex change (2-3 hr effort).

**Question:** Should all 4 milestones be implemented, or should M4 be deferred?

**Options:**
- All 4 milestones (full cost + time reduction)
- M1-M3 only (simpler, ~$8-10 cost target instead of $5-7)
- M1 only as a first pass, then iterate

## Q2: Missing Reference Documents

**Context:** R6 (embed reference docs) and the current routine YAML reference several files
that don't exist in the repository:
- `docs/plan-runner/idea_to_plan_stripped.md`
- `docs/plan-runner/idea_to_plan_detailed.md`
- `docs/plan-runner/step-files.md`
- `docs/planner/templates/*.md` (template directory is empty)

These are referenced in S-01/T-01's task_context and are targets for `context_from` injection.

**Question:** Where do these files live? Should they be created as part of this effort,
or do they exist in a different location/branch?

## Q3: Profile-to-Model Mappings

**Context:** M3 proposes adding `profile` fields to every task:
- `architect` -> claude-opus-4-6 (S-01, S-02, S-03, S-05)
- `coder` -> claude-sonnet-4-6 (S-04, S-06, S-08/T-02)
- `summarizer` -> claude-haiku-4-5 (S-07, S-08/T-01)

**Question:** Are these model assignments correct? Specifically:
- Is Haiku sufficient for S-08/T-01 (Generate Summary)? This produces the plan-summary.md
  which is a key output artifact.
- Is Sonnet sufficient for S-08/T-02 (Create Routine YAML)? This is the most structurally
  complex output (must pass schema validation, include contract-level auto_verify, etc.)

## Q4: S-05 Fan-Out vs Dry-Run Conflict

**Context:** S-05 currently has `type: dry_run` with config:
```yaml
dry_run:
  target_steps: ["S-08"]
  context_limit: 4000
  report_path: "docs/{{feature}}/dry-run-notes.md"
```

The plan proposes converting S-05/T-01 to fan-out (parallel per-step simulation). However:
- The current dry-run task does **holistic cross-step analysis** (persistence mapping audit,
  cross-step failure modes, integration test assertion quality)
- Fan-out would isolate each step's simulation, losing cross-step visibility
- The plan adds a merge task (T-02) to synthesize, but a summarizer-profile agent may miss
  subtle cross-step dependencies

**Question:** Should S-05 be converted to fan-out, or remain sequential? If fan-out,
should the merge task use `architect` profile instead of `summarizer` to preserve
analytical depth?

## Q5: Fan-Out Output Naming Convention

**Context:** For S-04 fan-out over `step-*-plan.md` files:
- Input: `docs/{{feature}}/step-03-plan.md`
- `item_stem` = `step-03-plan`
- Output with current pattern: `docs/{{feature}}/steps/step-03-plan.md`
- But current convention expects: `docs/{{feature}}/steps/step-03.md`

All downstream tasks (S-05, S-06) reference `steps/step-*.md` which would match either,
but the exact filenames would differ from current behavior.

**Question:** Accept the longer output names (`step-03-plan.md`), or instruct sub-agents
to output with the shorter convention (`step-03.md`)? The latter requires `per_item_prompt`
to explicitly name the output file.

## Q6: Verifier Model Configuration

**Context:** M2 recommends setting `verifier_model` to `claude-sonnet-4-6` for remaining
tasks (those that keep LLM verification). This is a run-creation parameter, not a routine
YAML field.

**Question:** How should this be specified?
- Document as a required run configuration parameter
- Add a routine-level `defaults` section (if supported by schema)
- Accept that verifier model is controlled at run creation time

## Q7: Test Validation Plan

**Context:** Completion criterion #10 requires "A test run of the updated routine on a small
idea completes successfully with measurably lower cost than the baseline ($18.28)."

**Question:** What feature/idea should be used for the validation test run? Should it be
the same idea used for the baseline analysis (run b46dbe62), or a new small idea?
