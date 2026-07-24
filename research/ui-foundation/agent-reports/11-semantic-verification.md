# Independent Semantic Verification

## Purpose

Independently falsify the complete Phase 1-2 semantic model before Phase 3. This
report challenges canonical entity, relationship, state, action, permission,
evidence, invariant, conflict, question, and capability claims without editing
their source artifacts. It distinguishes model defects from limitations already
represented honestly.

## Scope inspected

The approved design and Task 15 plan; all five source-demand documents; the
immutable Phase 1 source snapshot; all seven audit and three synthesis reports;
the Task 14 handoff; every canonical Phase 1-2 catalog, reality, action,
permission, evidence, invariant, and capability artifact; the validator and its
focused tests; and decisive implementation/test sources reopened for the High
findings.

## Scope and count summary

The verification covered all 132 closed scope demands and their 132 capability
adjudications, including 2 `current`, 0 `derived`, 25 `proposed`, 49 `gap`, and
56 `unknown` classifications. Canonical Phase 1 coverage was 31 `ENT`, 35 `REL`,
70 `STA` with 119 declared transitions, 7 `PER`, 71 `ACT`, 9 `EVI`, 11 `INV`,
9 `CON`, 7 `Q`, 154 evidence/command records including 41 `CMD`, and no admitted
derivation contract.

Finding counts are 0 Critical, 6 High, 2 Medium, and 0 Low. All six High
findings are blocking because they corrupt executable state vocabulary, one of
the only two current-capability admissions, or canonical settlement targets.
The two Medium findings are actual semantic defects but are non-blocking because
they understate or misnamespace evidence rather than authorize unsafe current
behavior.

## Methodology

1. Read the approved design and Task 15 plan before canonical artifacts.
2. Read all seven bounded audit reports and all three synthesis reports, then
   treated their conclusions as claims to challenge rather than authority.
3. Parsed every canonical Phase 0-2 YAML file and all 71 action roots; compared
   status distributions, cross-references, carrier bindings, transition edges,
   command declarations, and the claims projection against the registry.
4. Read the five immutable source-demand documents and checked classifications
   against each demand's actual wording and demand type.
5. Searched executable source and tests independently for state enum values,
   command reachability, response shapes, attempt foreign keys, backup carriers,
   graph MCP wiring, merge-back routing, actor handling, and validator blocking
   logic.
6. Reopened the decisive implementation and test source for every High finding.
7. Treated documented limitations as clean when the canonical item retained the
   correct gap, unknown, absence, carrier boundary, or prohibited interpretation.

## Key findings

### SV-001 - Invented graph `pending` state replaces executable states

- Severity: High
- Blocking: yes
- Affected IDs: `ENT-13`, `STA-28` through `STA-35`, `ACT-13`, `ACT-41`,
  `ACT-43`, `ACT-44`, `CAP-4`, `CAP-8`, `CAP-10`, `CAP-11`, `CAP-90`
- Claim: The canonical graph-node vocabulary and transitions describe executable
  `NodeState` values and reachable carrier-local transitions.
- Exact evidence: `research/ui-foundation/reality/state-model.yaml:482-627`
  declares `STA-28` as "Graph node pending" and has no planned, blocked, or
  retired state. Lines 1377-1396 declare `STA-28 -> STA-33|STA-34|STA-29` and
  `STA-30|STA-31|STA-32 -> STA-35`, while lines 1497-1522 assert broader source
  behavior. `src/orchestrator/graph/models.py:117-127` defines `NodeState` as
  `planned`, `blocked`, `ready`, `leased`, `running`, `suspended`, `completed`,
  `failed`, `retired`, and `cancelled`; it contains no `pending`. The actual
  decision applier accepts every nonterminal target and moves it to completed or
  failed at `src/orchestrator/graph/_commands.py:4234-4355`. Retirement emits
  `node_retired` and `node_state_changed(retired)` at
  `src/orchestrator/graph/_commands.py:4953-4960` and also occurs during
  reconciliation at lines 3541-3564. Tests prove blocked gate/authority nodes
  become completed at `tests/unit/test_graph_commands.py:8247-8343`, a running
  authority node can become completed at lines 8346-8415, and accepted patches
  expose planned and retired nodes at
  `tests/integration/test_graph_fr07_acceptance.py:147-214`.
- Falsification: `STA-28` is not a source value or a defined conversion. It
  collapses executable `planned` and `blocked` states, omits current `retired`,
  and makes the declared decision transitions false for blocked and running
  targets. It also leaves accepted patch retirement without a canonical result
  state. The model therefore both invents a state and omits reachable states.
- Required adjudication: Replace `STA-28` with separate planned and blocked
  states, add retired, enumerate command-specific transitions from actual source
  values, and remap every affected action and capability binding. Do not treat
  `pending` as an alias unless a typed conversion is implemented and evidenced.

### SV-002 - The two current capabilities copy one false cross-command output contract

- Severity: High
- Blocking: yes
- Affected IDs: `CAP-69`, `CAP-86`, `EVD-105`, `EVD-106`, `EVD-111`, `EVD-112`
- Claim: Each current capability has a demand-specific output contract whose
  variants are directly supported by implementation and exercised tests.
- Exact evidence: `CAP-69` at
  `research/ui-foundation/capabilities/registry.yaml:3696-3748` and `CAP-86` at
  lines 4432-4487 assert the same three variants: `PatchValidationResult`,
  `RecordGraphDecisionResponse`, and `GraphPatchAttemptsResponse`. `CAP-69`
  calls all three a command validator result although
  `RecordGraphDecisionResponse` is a successful decision response, not a
  validation result. `CAP-86` calls the bundle approve/deny/defer for a gate or
  patch although its own prohibited interpretation says not to merge decision,
  validator rejection, and patch application. The actual types are distinct at
  `src/orchestrator/graph/patch_validator.py:18-23` and
  `src/orchestrator/api/routers/graph.py:228-241,402-439`. The operator patch
  route directly applies a validated patch and returns
  `SubmitGraphPatchResponse`, or HTTP 409 on rejection, at
  `src/orchestrator/api/routers/graph.py:1965-2033`; that actual action response
  is omitted from both current contracts even though `EVD-111` declares support
  for it at `research/ui-foundation/catalog/evidence.yaml:4311-4323`. The
  decision route is independently applied at
  `src/orchestrator/api/routers/graph.py:2185-2254`. `EVD-106` exercises patch
  rejection diagnostics at
  `tests/integration/test_graph_fr08_acceptance.py:245-385`; `EVD-112` exercises
  one authority-denial decision at lines 388-454. Neither test proves the copied
  three-variant equivalence or a human patch approval/defer command.
- Falsification: The only two current admissions are not independent semantic
  contracts. They reuse response shapes from three different operations as if
  the shapes proved the two demanded capabilities. Patch validation, decision
  recording, patch-attempt readback, and patch application remain distinct by
  the approved design and executable source. The current status of a narrowly
  scoped patch-validator result may survive, but these output contracts and the
  broad `CAP-86` admission do not.
- Required adjudication: Rebuild both contracts from demand-specific commands
  and outputs. Keep internal validation, decision response, patch-attempt
  readback, and patch application separate; include `SubmitGraphPatchResponse`
  only where patch application is the claimed capability. Reclassify any
  unimplemented human patch approval/defer portion as gap or unknown rather than
  preserving `current` through copied variants.

### SV-003 - Attempt-identity conflict targets the wrong relationship

- Severity: High
- Blocking: yes
- Affected IDs: `CON-1`, `Q-1`, `ENT-5`, `REL-26`, `REL-27`, `REL-29`
- Claim: `CON-1` and `Q-1` identify every canonical relationship whose meaning
  depends on the unresolved `attempts.id` versus `attempts.attempt_id` boundary.
- Exact evidence: `CON-1` names `REL-27` at
  `research/ui-foundation/catalog/conflicts.yaml:5-29`, and `Q-1` repeats that
  target at `research/ui-foundation/catalog/questions.yaml:5-14`. In the
  relationship catalog, `REL-27` is Run-to-interaction-log required attribution
  and contains no attempt endpoint at
  `research/ui-foundation/reality/relationships.yaml:748-778`. The actual
  attempt-reference relationships are `REL-26` for cost records at lines
  719-747 and `REL-29` for interaction logs at lines 807-835; neither is linked
  to `CON-1` or `Q-1`. Executable schema makes both nullable FKs point to
  `attempts.id` at `src/orchestrator/db/orm/models.py:244-268,290-316`, while
  the competing nullable field is declared at lines 198-206 and
  `AttemptRecord.attempt_id` claims global identity at lines 23-35. The same FK
  target is created in
  `src/orchestrator/db/migrations/versions/aa1b2c3d4e5f_add_cost_and_interaction_log_records.py:19-70`.
  `tests/integration/test_database.py:71-102` exercises an attempt with only its
  primary `id`; `tests/integration/test_cost_records.py:190-229` exercises the
  two telemetry carriers without establishing the competing identity contract.
- Falsification: The blocking conflict is attached to a run-attribution edge and
  omits both edges that actually reference the disputed attempt identity. A
  resolver following affected IDs can edit or approve the wrong relationship
  while leaving both identity-sensitive joins apparently clean.
- Required adjudication: Remove `REL-27` from this conflict unless a separate
  proposition justifies it; add `REL-26` and `REL-29`, add reciprocal conflict
  and question links, and recheck every capability binding that relies on
  attempt-attributed cost or interaction evidence.

### SV-004 - Backup integrity question targets a model entity and omits backup carriers

- Severity: High
- Blocking: yes
- Affected IDs: `Q-4`, `ENT-28`, `ENT-29`, `ENT-30`, `ENT-31`, `REL-33`,
  `REL-34`, `REL-35`
- Claim: The blocking live-WAL-safe backup/replay question identifies the
  entities and relationships whose integrity it must settle.
- Exact evidence: `Q-4` affects `ENT-28` and `ENT-29` at
  `research/ui-foundation/catalog/questions.yaml:35-43`. `ENT-28` is Resolved
  model, unrelated to backup, at
  `research/ui-foundation/reality/domain-model.yaml:698-722`; the backup metadata,
  copied database, and journal segment are `ENT-29`, `ENT-30`, and `ENT-31` at
  lines 723-803. Their copy, marker, and conditional-import relationships are
  `REL-33` through `REL-35` at
  `research/ui-foundation/reality/relationships.yaml:921-1012`. Source confirms
  that the backup is a plain DB-file copy with a separately scanned marker in
  `src/orchestrator/db/recovery/backup.py::create_backup` and `restore_backup`.
  The decisive tests use a fake text file, copy it, and independently assert a
  journal marker at `tests/unit/test_backup.py:15-89`; they do not establish
  live SQLite/WAL consistency.
- Falsification: The question blocks an unrelated model-resolution entity while
  omitting the copied DB, journal segment, and every relationship that expresses
  the unsafe recovery cut. Its settlement cannot reliably invalidate or update
  the affected backup model.
- Required adjudication: Remove `ENT-28`; include `ENT-29`, `ENT-30`, `ENT-31`,
  and `REL-33` through `REL-35` as appropriate, then add reciprocal `Q-4` links
  before any backup/replay claim is admitted downstream.

### SV-005 - Graph MCP settlement names the merge-back command and the REST action

- Severity: High
- Blocking: yes
- Affected IDs: `Q-6`, `CMD-12`, `CMD-13`, `CMD-15`, `CMD-16`, `ACT-13`
- Claim: `Q-6` identifies the uncovered execution-bound graph MCP command and
  gives a safe settlement target.
- Exact evidence: `Q-6` says to retire `CMD-16` and affects `ACT-13` at
  `research/ui-foundation/catalog/questions.yaml:54-61`. The command ledger
  declares execution-bound graph MCP as `CMD-13` at
  `research/ui-foundation/catalog/evidence.yaml:2904-2915`; `CMD-16` is merge-back
  at lines 2939-2949. `ACT-13` binds REST graph patch `CMD-12`, not `CMD-13`, in
  `research/ui-foundation/reality/actions/act-13-graph-patch.yaml`.
  Executable MCP registration and callback routing are in
  `src/orchestrator/graph_runtime/graph_mcp_tools.py::build_graph_mcp_server` and
  `src/orchestrator/graph_runtime/dispatch.py:308-354,624-669`, not the
  `src/orchestrator/api/routers/graph.py` locator recorded for `CMD-13`.
  Merge-back is `src/orchestrator/api/routers/runs.py:1367-1430`, not the
  `review.py` locator recorded for `CMD-16`; `CMD-15` has the same wrong router
  family. `tests/unit/test_graph_mcp_tools.py:17-74` proves the execution-bound
  tool calls its closure, while
  `tests/integration/test_merge_readiness.py:158-268` independently proves the
  merge-back endpoint and gate behavior.
- Falsification: Following the canonical settlement text would retire an
  unrelated, tested merge-back command and leave `CMD-13` untouched. The one
  affected action is the REST patch contract, not the missing execution-bound
  MCP action contract. False command source locators further conceal the swap.
- Required adjudication: Change the command target to `CMD-13`; either create a
  dedicated action contract or explicitly record why execution-bound tooling is
  not a standalone UI action. Keep `ACT-13`/`CMD-12` separate, and correct the
  direct command source locators for `CMD-13`, `CMD-15`, and `CMD-16`.

### SV-006 - Blocking authority question is linked but does not block current admission

- Severity: High
- Blocking: yes
- Affected IDs: `CON-4`, `Q-5`, `PER-1` through `PER-7`, `CAP-42`, `CAP-86`,
  and authority-sensitive current action contracts
- Claim: Open blocking authority questions prevent a linked capability from
  being classified current until the authority boundary is settled.
- Exact evidence: `CON-4` and `Q-5` affect only `PER-1`, `PER-2`, and `PER-3` at
  `research/ui-foundation/catalog/conflicts.yaml:79-102` and
  `research/ui-foundation/catalog/questions.yaml:44-53`, despite `PER-4`,
  `PER-5`, and `PER-7` each recording absent enforced authorization at
  `research/ui-foundation/reality/permissions.yaml:83-125,150-179`. `CAP-42`
  and current `CAP-86` explicitly link `Q-5`; `CAP-86` does so at
  `research/ui-foundation/capabilities/registry.yaml:4432-4457`. The validator
  constructs decisive capability questions only from a question's
  `affected_ids` at `research/ui-foundation/tools/validate.py:720-735`, then
  checks only that derived set at lines 1278-1288. Thus `CAP-86` can link an open
  blocking question and still pass current admission. The graph decision route
  hard-codes command-context actor `human-operator` while accepting the request's
  caller-supplied decider at `src/orchestrator/api/routers/graph.py:2190-2218`.
  `tests/integration/test_graph_fr08_acceptance.py:388-454` supplies `alice` and
  proves denial behavior, but performs no subject authorization.
- Falsification: Canonical backlinks and validator semantics disagree. The same
  authority uncertainty is declared relevant by `CAP-86` but omitted from the
  question's affected set, so the blocking invariant is mechanically bypassed.
  The omission also excludes graph, scoped-MCP, and administration permission
  boundaries named by the question's settlement method.
- Required adjudication: Decide whether `Q-5` is decisive for each linked
  capability/action. If yes, add complete affected IDs and reciprocal links or
  make any linked open blocking question sufficient to block admission. If no,
  remove the misleading question link and state the narrower capability boundary.
  Re-evaluate `CAP-86` after the link semantics are corrected.

### SV-007 - A non-entity taxonomy was allocated an entity ID

- Severity: Medium
- Blocking: no
- Affected IDs: `ENT-26`
- Claim: Every `ENT-*` item is an entity with an identity boundary, ownership,
  persistence, and lifecycle, even when one of those is explicitly unknown.
- Exact evidence: `ENT-26` at
  `research/ui-foundation/reality/domain-model.yaml:648-673` is titled "Artifact
  carrier taxonomy", sets identity, ownership, persistence, and lifecycle all to
  `none`, and explicitly prohibits interpretation as an entity identity. The
  approved design's domain contract requires those entity boundaries at
  `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md:296-313`.
  No relationship or capability carrier binding references `ENT-26`.
- Falsification: A classification vocabulary with no identity or lifecycle was
  minted in the entity namespace while simultaneously declaring that it is not
  an entity. The prohibition does not repair the namespace contradiction.
- Required adjudication: Remove the taxonomy from the `ENT` collection while
  preserving its carrier distinctions as metadata, or define a real identity
  boundary before retaining an entity ID. Preserve the retired allocation in the
  ID ledger if the item is rejected.

### SV-008 - Evidence dimensions are mechanically defaulted instead of adjudicated

- Severity: Medium
- Blocking: no
- Affected IDs: `REL-1` through `REL-35`, `STA-1` through `STA-70`, `ACT-1`
  through `ACT-71`, `EVI-1` through `EVI-9`, `INV-2` through `INV-7`
- Claim: Orthogonal implementation, test, documentation, capability, and
  epistemic statuses reflect each item's actual evidence rather than a family
  template.
- Exact evidence: All 35 relationships are simultaneously
  `implementation_status: unknown`, `test_status: unknown`,
  `documentation_status: unknown`, and `capability_status: unknown`, while all
  35 are `epistemic_status: observed` and cite implementation audits in
  `research/ui-foundation/reality/relationships.yaml`. All 70 states are present
  but unexercised even where exact tests are named; all 71 action roots are
  unexercised, including tested graph patch, decision, lifecycle, clarification,
  and requeue paths. All nine evidence carriers have unknown test,
  documentation, capability, and epistemic status even though their
  `current_availability` text repeatedly says implemented and covered by
  inspected tests in `research/ui-foundation/reality/evidence/inventory.yaml`.
  `INV-2` through `INV-7` say `test_status: unexercised` while their confidence
  basis is "Approved test adjudication" and `EVD-97` points to the executable
  invariant index at
  `research/ui-foundation/agent-reports/07-tests-documentation.md:68-98`.
- Falsification: The exact all-item distributions and contradictions between
  status fields and item prose show family-wide defaults, not orthogonal
  evidence adjudication. This does not invent current behavior, but downstream
  consumers cannot tell a genuinely unknown relationship/test from one directly
  demonstrated by executable schema or tests.
- Required adjudication: Recompute each dimension from direct evidence. Where
  direct canonical evidence is insufficient, retain unknown and narrow the
  prose/confidence basis; where implementation or tests are decisive, use
  present/exercised. Do not bulk-promote capability status merely because a
  carrier exists.

## Zero-findings checks

- Critical findings: zero.
- Unsupported causality: zero additional defects. Relationship and evidence
  contracts consistently prohibit deriving causality from temporal order, and
  candidate/file-state limitations retain observer rather than author causality.
- Active derivations: zero findings because there are zero admitted `derived`
  capabilities; superseded `DRV` allocations are not presented as active.
- Typed steering leakage: zero findings. `CAP-92`, `CAP-93`, `ACT-15`, and
  `ACT-16` remain gap/non-executable and are not represented as current steering.
- Present actions without command IDs: zero. All 67 present action roots bind a
  declared present command; `SV-005` concerns a missing standalone action and
  wrong settlement identity, not an action root with a null command.
- Unpriced-as-zero semantic leakage: zero additional defects. The canonical
  evidence inventory preserves missing-rate and denominator limitations.
- Degradation-scenario overfitting: zero additional defects. Repeated-failure,
  churn, prompt-pressure, information-delta, degraded, stalled, and runaway
  demands remain gap or unknown rather than being manufactured from the Journey
  C scenario.
- Proposed/current UI leakage: zero additional defects outside `SV-002`. Rubric,
  honesty, continuity, responsive, and one-step evidence demands remain proposed
  or gap rather than current product behavior.
- Slash-separated aliases: zero additional defects. Entity alias arrays remain
  empty and graph/core conversion remains blocked; `SV-001` is a state
  substitution, not a declared slash alias.

## Important uncertainties

- The verifier did not execute product behavior. Source and test bodies were read
  to falsify contracts; cited tests establish executable constructions, while
  the Task 14 handoff records the latest suite run.
- `CAP-86` may retain a narrower current graph-decision capability after
  adjudication because graph approval/authority values include defer. This does
  not validate its current copied patch/validator output contract or establish a
  separate human patch-approval command.
- Conservative unknown status is not itself a defect. `SV-008` is limited to
  exact family-wide default patterns that contradict the same records' evidence
  prose or cited test adjudication.
- The report is not part of `snapshot-2026-07-24-phase-1`; adding this verifier
  output does not mutate that immutable source snapshot.

## Conflicts found

The six High findings are verifier conflicts requiring canonical adjudication.
They are not canonical `CON-*` records because this verifier is prohibited from
editing catalogs. Until accepted, rejected with qualifying evidence, or
registered as canonical conflicts/questions, their blocking state remains open.

The two Medium findings are semantic normalization defects, not evidence that
the represented implementation behavior is absent. `SV-007` is currently
unreferenced; `SV-008` primarily underclaims evidence status. They should not be
inflated into current capability admissions during correction.

## Decisions required

- Adjudicate `SV-001` before any Phase 3 state or action review uses graph-node
  state labels or transitions.
- Adjudicate `SV-002` before either current capability is shown as verified
  capability truth.
- Correct or reject the exact canonical-target findings `SV-003` through
  `SV-006`; unresolved findings must become blocking `CON-*` or `Q-*` records
  with reciprocal links.
- Resolve `SV-007` and `SV-008` as normalization corrections without promoting
  unsupported current/derived capabilities.

## Artifact paths

- Created only:
  `research/ui-foundation/agent-reports/11-semantic-verification.md`
- Canonical catalogs, reality files, capability files, source, tests, status,
  progress, product files, and JTBD documents were read-only.

## Opened sources

- Approved inputs: `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`
  and Task 15 in `docs/superpowers/plans/2026-07-23-ui-foundation-phase-0-3.md`.
- Source demands: all five files under `docs/jtbd/` named by the approved design.
- Reports: `research/ui-foundation/agent-reports/00-delegation-plan.md` through
  `10-evidence-synthesis.md`, plus `.superpowers/sdd/task-14-ui-foundation-report.md`.
- Canonical artifacts: every file in `research/ui-foundation/catalog/`, the four
  primary `reality/*.yaml` contracts, all 71 `reality/actions/*.yaml` files,
  `reality/evidence/inventory.yaml`, `capabilities/registry.yaml`, and
  `capabilities/gaps.md`.
- Validator and focused validation tests:
  `research/ui-foundation/tools/validate.py` and
  `tests/integration/test_ui_foundation_tools.py`.
- Decisive implementation: `src/orchestrator/graph/models.py`,
  `graph/_commands.py`, `graph/patch_validator.py`,
  `graph_runtime/dispatch.py`, `graph_runtime/graph_mcp_tools.py`,
  `api/routers/graph.py`, `api/routers/runs.py`, `db/orm/models.py`, DB attempt
  migrations, and `db/recovery/backup.py`.
- Decisive tests: `tests/unit/test_graph_commands.py`,
  `tests/unit/test_graph_mcp_tools.py`, `tests/unit/test_backup.py`,
  `tests/integration/test_graph_fr07_acceptance.py`,
  `tests/integration/test_graph_fr08_acceptance.py`,
  `tests/integration/test_database.py`, `tests/integration/test_cost_records.py`,
  and `tests/integration/test_merge_readiness.py`.

## Evidence pointers

Canonical evidence was checked against immutable snapshot
`snapshot-2026-07-24-phase-1` in
`research/ui-foundation/catalog/evidence.yaml`. The decisive direct evidence IDs
for the current-capability challenge are `EVD-105`, `EVD-106`, `EVD-111`, and
`EVD-112`. Exact implementation/test paths and symbols for every High finding
are embedded in `SV-001` through `SV-006`; canonical IDs are the stable finding
targets and source line numbers are navigation aids.

## Verification limits

- Only the report validator is in Task 15's verifier write scope. Phase 2
  semantic validation after adjudication belongs to the orchestrator because it
  requires canonical edits this verifier may not make.
- No canonical hash or source-snapshot record was refreshed. This report itself
  is intentionally outside the immutable Phase 1 snapshot.
- No finding is based only on plausibility. Each High finding was reopened in
  implementation and tests; Medium findings use complete canonical-family counts
  or an explicit namespace contradiction.

## Recommended next delegation

Delegate one canonical adjudication pass to accept each finding by correcting
the affected contracts, reject it only with qualifying executable evidence, or
register it as a blocking conflict/question. Then rerun
`uv run python research/ui-foundation/tools/validate.py --phase 2` and regenerate
projections before selecting Phase 3 review items.
