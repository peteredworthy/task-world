# Step 3: Profile-Based Model Routing (M3)

Add `profile` fields to every task in the optimized routine YAML to route tasks to appropriate model tiers. Architectural reasoning tasks use Opus (`architect`), structured output tasks use Sonnet (`coder`), and mechanical tasks use Haiku (`summarizer`). This saves ~$5-7 per run.

## Intent Verification
**Original Intent**: R4 (profile-based model routing) from intent.md
**Functionality to Produce**:
- Every task in the optimized routine has a `profile` field
- Profile assignments: architect (S-01/T-01, S-02/T-01, S-03/T-01, S-05/T-01), coder (S-04/T-01, S-06/T-01, S-08/T-02), summarizer (S-07/T-01, S-08/T-01)
**Final Verification Criteria**:
- Routine YAML passes schema validation with `profile` fields accepted
- Every task has exactly one `profile` field

---

## Task 1: Add Profile Fields to All Tasks

**Description**: Add `profile` fields to all 9 tasks in the optimized routine, mapping each task to the appropriate model tier based on its cognitive demands.

**Implementation Plan (Do These Steps)**

Profile fields are a simple addition to each task definition. The agent runner resolves profiles to concrete models via its configured mappings.

- [ ] In `routines/idea-to-plan-optimized/routine.yaml`, add `profile: "architect"` to these tasks:
  - S-01/T-01 (Generate Initial Artifacts) — reasoning-heavy, creates foundational docs
  - S-02/T-01 (Gather Requirements) — reasoning-heavy, resolves design questions
  - S-03/T-01 (Create Step Plans) — reasoning-heavy, breaks plan into contracts
  - S-05/T-01 (Simulate Execution) — reasoning-heavy, failure mode analysis
- [ ] Add `profile: "coder"` to these tasks:
  - S-04/T-01 (Create Step Files) — structured output, follows format guide
  - S-06/T-01 (Cross-Check Artifacts) — structured analysis, consistency checking
  - S-08/T-02 (Create Routine YAML) — structured output, follows schema
- [ ] Add `profile: "summarizer"` to these tasks:
  - S-07/T-01 (Human Final Approval) — trivial acknowledgment task
  - S-08/T-01 (Generate Summary) — mechanical summary generation

**Dependencies**
- [ ] Step 01 completed — optimized routine exists at `routines/idea-to-plan-optimized/routine.yaml`

**References**
- Step plan: `docs/planning-routine-improvements/step-03-plan.md`
- Intent: `docs/planning-routine-improvements/intent.md` — R4, Model Profile Mappings section
- Plan: `docs/planning-routine-improvements/plan.md` — M3 section
- Architecture: `docs/planning-routine-improvements/architecture.md` — section 3 (profile-based model routing)

**Constraints**
- Profile values must be valid `ModelProfile` enum values: `architect`, `coder`, `summarizer`, `designer`
- Profile fields have no effect unless the agent runner has matching profile-to-model defaults configured
- Do not modify the profile-to-model mapping configuration — that is a runtime setup step, not a YAML change

**Functionality (Expected Outcomes)**
- [ ] Every task in the routine has a `profile` field
- [ ] S-01/T-01, S-02/T-01, S-03/T-01, S-05/T-01 have `profile: "architect"`
- [ ] S-04/T-01, S-06/T-01, S-08/T-02 have `profile: "coder"`
- [ ] S-07/T-01, S-08/T-01 have `profile: "summarizer"`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` exits 0
- [ ] Count `profile:` occurrences in the YAML — must equal the number of tasks (9)
- [ ] Verify each task's profile assignment matches the mapping above by searching the YAML
