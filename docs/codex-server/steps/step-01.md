# Step 01: Research + Integration Contract

Lock the Codex integration contract before implementation starts. This step converts clarified decisions into enforceable documentation and creates explicit implementation constraints that every later step must reference.

## Intent Verification
**Original Intent**: `docs/codex-server/intent.md` requires Codex local + remote agents aligned to Codex app server baseline, callback parity (REST + MCP), strict callback-tool allow-list, and dual-variant release gating.

**Functionality to Produce**:
- Contract baseline documented once and reused by all build steps
- Architecture and plan docs contain no conflicting decisions
- Open risks are explicitly listed with impact and owner

**Final Verification Criteria**:
- Step plans 02-06 reference this contract as prerequisite context
- Human can confirm no unresolved ambiguity on interface/auth/tools/release gate

---

## Task 1: Build a contract matrix from clarified decisions

**Description**: Create a dedicated contract artifact that turns clarifications into implementation rules.

**Implementation Plan (Do These Steps)**
- [ ] Create `docs/codex-server/context/contract-matrix.md`.
- [ ] Add sections: baseline interface, auth model, callback channels, tool allow-list, compatibility policy, release gate.
- [ ] For each section, include: decision, source (clarification ID/question), implementation impact, non-go conditions.
- [ ] Add one "out of scope in v1" section explicitly excluding non-callback experimental tools.

**References**
- `docs/codex-server/clarifications.md`
- `docs/codex-server/plan.md`
- `docs/codex-server/architecture.md`

**Constraints**
- [ ] Atomicity budget: change <=2 files and <=250 LOC.
- [ ] No code changes in `src/` for this task.

**Functionality (Expected Outcomes)**
- [ ] Contract decisions are traceable to specific clarification answers.
- [ ] A later implementer can derive config/auth/tool behavior without guessing.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `rg -n "Baseline|Auth|Callback|Allow-list|Compatibility|Release gate" docs/codex-server/context/contract-matrix.md` returns all sections.
- [ ] `rg -n "Clarification" docs/codex-server/context/contract-matrix.md` shows source traceability.

---

## Task 2: Align plan and architecture docs to the contract matrix

**Description**: Remove drift and make the contract enforceable in planning docs.

**Implementation Plan (Do These Steps)**
- [ ] Update `docs/codex-server/plan.md` to reference `context/contract-matrix.md` as the normative contract source.
- [ ] Update `docs/codex-server/architecture.md` to include explicit "contract constraints" and "unsupported in v1" callouts matching Task 1.
- [ ] Add a short "contract mismatch handling" subsection that blocks implementation when assumptions diverge from matrix.

**References**
- `docs/codex-server/context/contract-matrix.md`
- `docs/codex-server/plan.md`
- `docs/codex-server/architecture.md`

**Constraints**
- [ ] Atomicity budget: change <=3 files and <=300 LOC.
- [ ] Keep all existing milestone order unchanged.

**Functionality (Expected Outcomes)**
- [ ] `plan.md` and `architecture.md` reflect identical contract decisions.
- [ ] There is one clear source-of-truth for compatibility and rollout gating.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `rg -n "contract-matrix" docs/codex-server/plan.md docs/codex-server/architecture.md` confirms cross-reference.
- [ ] Manual diff shows no contradictory statements on auth, callback parity, tool scope, compatibility, or release policy.

---

## Task 3: Record implementation risks as blockers or explicit follow-ups

**Description**: Capture unresolved engineering risks so step execution can stop cleanly when blocked.

**Implementation Plan (Do These Steps)**
- [ ] Create `docs/codex-server/context/open-risks.md` with columns: risk, trigger, affected step(s), mitigation, block/non-block classification.
- [ ] Include at least: Codex payload drift risk, remote transport timeout behavior risk, callback channel parity risk.
- [ ] Add links from each risk entry to the step plan(s) it affects.

**References**
- `docs/codex-server/step-02-plan.md`
- `docs/codex-server/step-03-plan.md`
- `docs/codex-server/step-04-plan.md`
- `docs/codex-server/step-05-plan.md`
- `docs/codex-server/step-06-plan.md`

**Constraints**
- [ ] Atomicity budget: change <=2 files and <=200 LOC.
- [ ] No speculative implementation details without explicit source links.

**Functionality (Expected Outcomes)**
- [ ] Each upcoming step has documented blockers/fallbacks.
- [ ] Unknowns are converted into concrete verification checkpoints.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `rg -n "step-0[2-6]-plan" docs/codex-server/context/open-risks.md` returns linked dependencies.
- [ ] Human review confirms risks are actionable and not ambiguous.
