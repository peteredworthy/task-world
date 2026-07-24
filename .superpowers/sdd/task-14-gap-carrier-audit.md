# Task 14 gap carrier audit (historical report)

> **Canonical authority:** `research/ui-foundation/capabilities/registry.yaml` is the sole Task 14 source. This report is historical context only and does not regenerate or alter canonical records.

## Historical scope and rules

This is a read-only falsification of all 49 `gap` and 56 `unknown` capability
records against the completed Phase 1 canonical entity, state, evidence-carrier,
action, and permission inventories and the approved reports. `Partial` means that
one or more real carriers expose demand-relevant inputs or narrower behavior but
do not implement the demanded contract. `Absent` means that no implemented
demand carrier exists; an explicit absent action contract may still document that
absence. Inputs never establish an unimplemented aggregate, classifier, causal
claim, continuity behavior, or derivation.

The seven expected absent gaps withstand challenge: `CAP-43`, `CAP-74`,
`CAP-81`, `CAP-85`, `CAP-92`, `CAP-113`, and `CAP-116`. The remaining 42 gaps
were historically assessed as `partial`. All 56 unknowns were historically
recorded as `partial`; uncertainty, carrier splits, or unresolved identity/coverage
boundaries prevented a stronger classification.

## Historical gap findings (49/49)

### CAP-1 - Health class
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-2`, `ENT-4`, `ENT-12`, `STA-2`, `STA-9`, `STA-18`, `STA-31`, `EVI-1`, `EVI-2`.
- **Evidence:** `EVD-56`, `EVD-58`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`.
- **Individual limitation:** Run, task, graph, and node states provide health inputs, but no shared health-class producer, thresholds, or explanation record exists.
- **Prohibited interpretation:** Do not rename an execution state or recent event as Healthy, Degraded, Stalled, Runaway, or another health class.

### CAP-5 - Last-event age
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-9`, `ENT-10`, `ENT-11`, `EVI-1`, `EVI-2`.
- **Evidence:** `EVD-56`, `EVD-58`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`.
- **Individual limitation:** Both event families carry timestamps and positions, but there is no complete workflow-plus-graph last-event join, injected clock, or published age value.
- **Prohibited interpretation:** Do not call the timestamp of the latest event returned by one paginated stream the run's last-event age.

### CAP-6 - Budget pace
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-21`, `EVI-9`.
- **Evidence:** `EVD-56`, `EVD-64`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Usage and known-cost facts omit exception-terminated work and provide neither a run budget nor a time-window pace algorithm.
- **Prohibited interpretation:** Do not divide a graph-only known-cost subtotal by elapsed time and label it budget pace.

### CAP-7 - Blast radius
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-12`, `ENT-13`, `ENT-14`, `ENT-16`, `ACT-13`, `STA-54`, `EVI-2`, `EVI-3`.
- **Evidence:** `EVD-37`, `EVD-58`, `EVD-72`, `EVD-73`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Graph topology and accepted patch effects identify concrete changed elements but no tested demand-level affected-set or blast-radius projection exists.
- **Prohibited interpretation:** Do not equate patch operation count or all graph descendants with actual blast radius.

### CAP-10 - Planner horizon
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-12`, `ENT-13`, `ENT-14`, `STA-28`, `STA-29`, `STA-30`, `EVI-2`, `EVI-3`.
- **Evidence:** `EVD-58`, `EVD-72`, `EVD-73`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Nodes, edges, scheduler states, and records exist, but there is no horizon boundary algorithm or planner-horizon output.
- **Prohibited interpretation:** Do not treat every pending or reachable node as inside the planner's committed horizon.

### CAP-12 - Attempts left
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-4`, `ENT-5`, `STA-8`, `STA-9`, `STA-15`, `EVI-1`.
- **Evidence:** `EVD-49`, `EVD-50`, `EVD-51`, `EVD-54`, `EVD-57`, `EVD-69`, `EVD-70`, `EVD-71`.
- **Individual limitation:** Attempt occurrences and selected attempt limits are present, but identity is conflicted and no cross-mode remaining-attempt contract handles recovery, fan-out, and graph generations.
- **Prohibited interpretation:** Do not subtract a legacy attempt count from one configured maximum and present it as universal attempts left.

### CAP-13 - Final-invariant progress
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-7`, `ENT-8`, `ENT-12`, `ENT-15`, `ENT-16`, `EVI-3`.
- **Evidence:** `EVD-49`, `EVD-52`, `EVD-55`, `EVD-58`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Requirements, checklist items, graph records, and bindings expose pieces of completion evidence, not a stable final-invariant denominator or progress result.
- **Prohibited interpretation:** Do not present passed checklist or grade counts as percentage completion of a growing final invariant set.

### CAP-17 - Affected scope
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-13`, `ENT-14`, `ENT-15`, `ENT-16`, `ACT-13`, `EVI-8`.
- **Evidence:** `EVD-37`, `EVD-58`, `EVD-63`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Individual commands retain target and operation scope, but no common decision projection computes the full affected run/task/node/file scope.
- **Prohibited interpretation:** Do not treat a command's target identifier as proof that its consequences are confined to that target.

### CAP-20 - Downstream effect
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-12`, `ENT-13`, `ENT-14`, `ENT-16`, `ACT-13`, `EVI-2`, `EVI-3`.
- **Evidence:** `EVD-37`, `EVD-58`, `EVD-72`, `EVD-73`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Topology and post-command events show specific realized effects, but no pre-decision downstream-effect contract or complete consequence set exists.
- **Prohibited interpretation:** Do not infer causal downstream effects from graph reachability or temporal event order alone.

### CAP-21 - Reversibility
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-13`, `ACT-18`, `ACT-19`, `ACT-20`, `ACT-21`, `ACT-23`, `ACT-24`, `ACT-26`, `ACT-29`, `ACT-31`, `ACT-52`, `ACT-53`, `ACT-55`, `ACT-56`, `EVI-8`.
- **Evidence:** `EVD-11`, `EVD-20`, `EVD-29`, `EVD-37`, `EVD-45`, `EVD-61`, `EVD-63`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Canonical action contracts state action-specific inverse, compensation, or irreversibility facts, but no shared decision field/projection communicates them and many effects have no inverse.
- **Prohibited interpretation:** Do not call resume, retry, transition-back, corrective patching, or a later git operation an exact undo of the original action.

### CAP-24 - Requirement-grade changes
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-6`, `ENT-7`, `ENT-9`, `ENT-11`, `ENT-15`, `EVI-1`, `EVI-2`, `EVI-3`.
- **Evidence:** `EVD-55`, `EVD-56`, `EVD-58`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Legacy grade snapshots and graph verification records are real but lack one normalized cross-carrier requirement-grade history contract.
- **Prohibited interpretation:** Do not merge similarly named legacy requirements and graph records into one grade-change sequence without a typed identity join.

### CAP-30 - Prompt size
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-22`, `EVI-4`.
- **Evidence:** `EVD-77`, `EVD-78`, `EVD-79`.
- **Individual limitation:** Legacy prompt text can sometimes be retained and graph prompt metadata is compact, but no producer publishes canonical packet bytes, hash, or size across modes.
- **Prohibited interpretation:** Do not use model input-token usage or graph prompt-summary length as prompt packet size.

### CAP-38 - Retry information delta
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-5`, `ENT-6`, `EVI-4`, `EVI-5`, `EVI-7`, `EVI-9`.
- **Evidence:** `EVD-49`, `EVD-51`, `EVD-54`, `EVD-55`, `EVD-77`, `EVD-78`, `EVD-79`, `EVD-80`, `EVD-81`, `EVD-82`, `EVD-87`, `EVD-88`, `EVD-89`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Attempts, grades, prompts, traces, files, and usage provide heterogeneous comparison inputs, but no normalized information-delta algorithm or output exists.
- **Prohibited interpretation:** Do not infer zero or positive information gain merely because an attempt number, grade, file list, or token count changed.

### CAP-42 - Authority
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-10`, `ACT-11`, `ACT-12`, `PER-1`, `PER-2`, `PER-3`, `PER-4`, `PER-5`, `EVI-8`.
- **Evidence:** `EVD-27`, `EVD-38`, `EVD-39`, `EVD-40`, `EVD-41`, `EVD-42`, `EVD-61`, `EVD-63`, `EVD-90`, `EVD-91`.
- **Conflicts/questions:** `CON-4`, `Q-5`.
- **Individual limitation:** Optional bearer authentication, graph actor/domain checks, requested-authority records, and tool exposure exist, but routed mutations enforce no subject-bound product role, scope, ownership, or action permission.
- **Prohibited interpretation:** Do not present fixed/caller-supplied actor text, graph eligibility, or MCP tool allowlisting as enforced human authorization.

### CAP-43 - Intervention budget
- **Required status:** `gap`; `implementation_status: absent`; `epistemic_status: observed`.
- **Decisive carriers:** none; `EVI-9` is only disqualifying cost/usage input, not an implementation carrier.
- **Evidence:** `EVD-56`, `EVD-64`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Planner generation and runner action limits are operational controls, while usage facts lack the operator intervention taxonomy and budget contract demanded here.
- **Prohibited interpretation:** Do not relabel action limits, attempt limits, or observed spend as an intervention budget.

### CAP-44 - Intervention reversibility
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-13`, `ACT-18`, `ACT-19`, `ACT-20`, `ACT-21`, `ACT-31`, `ACT-32`, `ACT-33`, `ACT-52`, `ACT-53`, `ACT-55`, `ACT-56`, `EVI-8`.
- **Evidence:** `EVD-11`, `EVD-20`, `EVD-29`, `EVD-37`, `EVD-45`, `EVD-61`, `EVD-63`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Intervention-like actions document distinct compensation boundaries, but there is no unified intervention classification or visible reversibility result.
- **Prohibited interpretation:** Do not generalize the existence of one compensating action into reversibility for all interventions.

### CAP-47 - Unpriced share
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-21`, `EVI-9`.
- **Evidence:** `EVD-64`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Conflicts/questions:** `CON-9`; no open question is required.
- **Individual limitation:** Graph rollups expose missing-rate counts and recorded denominators, but absent/exception usage lies outside that denominator and no share field or complete contract exists.
- **Prohibited interpretation:** Do not compute a fleet-wide unpriced share from graph returned-execution rows or treat unpriced as zero cost.

### CAP-48 - Prompt size
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-22`, `EVI-4`.
- **Evidence:** `EVD-77`, `EVD-78`, `EVD-79`.
- **Individual limitation:** J7 has the same carrier split as J5: retained legacy text and graph summary metadata do not provide one size fact for every execution.
- **Prohibited interpretation:** Do not compare usage input tokens across models as if they were directly comparable prompt byte sizes.

### CAP-49 - Retries without new information
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-5`, `ENT-6`, `ACT-31`, `ACT-34`, `ACT-38`, `EVI-1`, `EVI-4`, `EVI-5`, `EVI-7`.
- **Evidence:** `EVD-14`, `EVD-44`, `EVD-45`, `EVD-54`, `EVD-55`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-77`, `EVD-78`, `EVD-79`, `EVD-80`, `EVD-81`, `EVD-82`, `EVD-87`, `EVD-88`, `EVD-89`.
- **Individual limitation:** Retry actions and potential before/after evidence exist, but no retry taxonomy and no implemented new-information test spans those carriers.
- **Prohibited interpretation:** Do not classify a retry as waste merely because it repeats a command or produces the same grade.

### CAP-50 - Repeated tools and work
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `EVI-5`, `EVI-1`.
- **Evidence:** `EVD-56`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-80`, `EVD-81`, `EVD-82`.
- **Individual limitation:** Legacy structured traces and carrier-specific output expose some repetitions, while OpenHands repetition windows and verdicts are process-local and not durable cross-run findings.
- **Prohibited interpretation:** Do not treat repeated tool names or similar output lines as a persisted repeated-work detector result.

### CAP-51 - Verifier churn
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-5`, `ENT-6`, `ENT-7`, `ENT-15`, `EVI-1`, `EVI-2`, `EVI-3`.
- **Evidence:** `EVD-54`, `EVD-55`, `EVD-56`, `EVD-58`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Requirement grades, reasons, attempts, and candidates are available in split carriers, but no churn window, threshold, aggregation, or finding identity exists.
- **Prohibited interpretation:** Do not label any grade reversal or repeated verification as verifier churn without the missing classifier contract.

### CAP-52 - Comparable cohort
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-1`, `ENT-2`, `ENT-27`, `ENT-28`, `EVI-9`.
- **Evidence:** `EVD-49`, `EVD-56`, `EVD-68`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Routine, run, profile, model, and graph usage dimensions are possible cohort inputs, but no eligibility algorithm, comparison endpoint, or explanation contract exists.
- **Prohibited interpretation:** Do not call runs comparable merely because routine IDs, model names, or dates match.

### CAP-57 - Price coverage
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-21`, `EVI-9`.
- **Evidence:** `EVD-64`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Conflicts/questions:** `CON-9`; no open question is required.
- **Individual limitation:** Missing-rate flags survive in selected per-model and graph rollups, but positive matches can omit rate categories and unreported executions are outside coverage.
- **Prohibited interpretation:** Do not treat `rate_missing: false` as a complete rate card or graph coverage as fleet-wide price coverage.

### CAP-58 - Patch count
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-13`, `ACT-45`, `STA-54`, `STA-55`, `STA-64`, `EVI-2`, `EVI-8`.
- **Evidence:** `EVD-37`, `EVD-72`, `EVD-73`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Submitted, accepted, and rejected graph patch attempts are retained, but no demand-level count defines inclusion, deduplication, scope, or cross-mode meaning.
- **Prohibited interpretation:** Do not count topology events as patches or count one patch once per emitted operation event.

### CAP-59 - Retry count
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-5`, `ACT-31`, `ACT-34`, `ACT-38`, `EVI-1`, `EVI-2`.
- **Evidence:** `EVD-14`, `EVD-44`, `EVD-45`, `EVD-49`, `EVD-51`, `EVD-54`, `EVD-57`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`.
- **Conflicts/questions:** `CON-1`, `Q-1`.
- **Individual limitation:** Attempt identity is conflicted and retry means several distinct workflow recovery, fan-out, run recovery, and graph generation behaviors; no canonical count unifies them.
- **Prohibited interpretation:** Do not use attempt rows, attempt numbers, retry commands, and graph generations as interchangeable count units.

### CAP-60 - Grade churn
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-6`, `ENT-7`, `ENT-15`, `EVI-1`, `EVI-2`, `EVI-3`.
- **Evidence:** `EVD-55`, `EVD-56`, `EVD-58`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Grade histories can be reconstructed only within carrier-specific identity boundaries; no churn metric, window, normalization, or threshold is implemented.
- **Prohibited interpretation:** Do not equate grade-change count with grade churn or compare unmatched requirement identities.

### CAP-63 - Prompt pressure
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `EVI-4`, `EVI-9`, `ENT-27`, `ENT-28`.
- **Evidence:** `EVD-49`, `EVD-56`, `EVD-77`, `EVD-78`, `EVD-79`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Prompt metadata, input-token usage, model, and profile are inputs, but packet size, context-window denominator, threshold, and pressure result are absent.
- **Prohibited interpretation:** Do not label high input-token use as prompt pressure without packet and model-window semantics.

### CAP-64 - Final-gate effect
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-12`, `ENT-13`, `ENT-14`, `ENT-15`, `ENT-16`, `STA-36`, `STA-37`, `EVI-3`, `EVI-8`.
- **Evidence:** `EVD-27`, `EVD-58`, `EVD-63`, `EVD-74`, `EVD-75`, `EVD-76`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Gate decisions and topology can reveal realized outcomes, but no before-action projection explains an intervention's effect on the final gate set.
- **Prohibited interpretation:** Do not infer final-gate effect from immediate target-node completion or one released successor.

### CAP-66 - Explicit empty needs-you state
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `STA-11`, `STA-36`, `ENT-19`, `EVI-8`.
- **Evidence:** `EVD-13`, `EVD-27`, `EVD-53`, `EVD-63`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Non-empty clarification and graph decision wait states exist, but no explicit positive empty-state carrier says that nothing currently needs the user.
- **Prohibited interpretation:** Do not infer a durable empty needs-you state from an empty response, hidden panel, or lack of pending rows in one projection.

### CAP-67 - No runaway signal
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `EVI-1`, `EVI-2`, `EVI-5`, `EVI-9`.
- **Evidence:** `EVD-56`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-80`, `EVD-81`, `EVD-82`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Activity, traces, and usage provide possible detector inputs, but no runaway classifier exists, so a negative classifier result cannot be produced.
- **Prohibited interpretation:** Do not treat the absence of a runaway event as evidence that the run is not runaway.

### CAP-68 - Decision wait age
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-19`, `ENT-20`, `STA-11`, `STA-36`, `STA-37`, `EVI-1`, `EVI-2`, `EVI-8`.
- **Evidence:** `EVD-13`, `EVD-27`, `EVD-63`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Request, decision, and event timestamps exist, but no canonical wait-start precedence, current-clock rule, paused-time policy, or age projection exists.
- **Prohibited interpretation:** Do not subtract an arbitrary request timestamp from wall-clock now and label the result canonical decision wait age.

### CAP-71 - Cost of another attempt
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-5`, `ENT-21`, `ENT-27`, `ENT-28`, `EVI-9`.
- **Evidence:** `EVD-49`, `EVD-54`, `EVD-56`, `EVD-64`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Historical returned-execution cost is incomplete and no comparable cohort, phase estimator, uncertainty rule, or approximate next-attempt output exists.
- **Prohibited interpretation:** Do not use the previous attempt's known subtotal as the predicted cost of another attempt.

### CAP-72 - Candidate delta
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-15`, `ENT-23`, `ENT-24`, `EVI-3`, `EVI-6`, `EVI-7`.
- **Evidence:** `EVD-56`, `EVD-58`, `EVD-65`, `EVD-74`, `EVD-75`, `EVD-76`, `EVD-83`, `EVD-84`, `EVD-85`, `EVD-86`, `EVD-87`, `EVD-88`, `EVD-89`.
- **Individual limitation:** Candidate-related records, artifact references, commits, and whole-worktree snapshots lack one canonical candidate-content identity and delta algorithm.
- **Prohibited interpretation:** Do not call a changed snapshot, commit, or artifact list a candidate-exclusive delta.

### CAP-73 - Causal gap
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `EVI-1`, `EVI-2`, `EVI-3`, `EVI-4`, `EVI-5`, `EVI-7`.
- **Evidence:** `EVD-56`, `EVD-58`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-74`, `EVD-75`, `EVD-76`, `EVD-77`, `EVD-78`, `EVD-79`, `EVD-80`, `EVD-81`, `EVD-82`, `EVD-87`, `EVD-88`, `EVD-89`.
- **Individual limitation:** Ordered and attributed evidence helps investigation but establishes no causal mechanism or causal-gap detector.
- **Prohibited interpretation:** Do not convert temporal adjacency, producer attribution, or graph edges into proof of causation.

### CAP-74 - Directive binding
- **Required status:** `gap`; `implementation_status: absent`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-15` (explicit absent contract); `EVI-4` is disqualifying prompt evidence, not a directive-binding implementation.
- **Evidence:** `EVD-56`, `EVD-61`, `EVD-77`, `EVD-78`, `EVD-79`.
- **Individual limitation:** No typed directive identity, steering command, binding producer, packet hash, or model-receipt evidence exists.
- **Prohibited interpretation:** Do not use stored context, graph prompt summaries, rationale records, or successful patching as proof that a directive was bound or delivered.

### CAP-77 - Missing node attribution
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-13`, `ENT-17`, `EVI-2`, `EVI-9`.
- **Evidence:** `EVD-58`, `EVD-72`, `EVD-73`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Usage facts identify nodes that reported usage, but no expected-execution denominator distinguishes legitimate zero, absent telemetry, and exception-terminated missing facts.
- **Prohibited interpretation:** Do not label every node absent from usage rollup as a missing-telemetry offender.

### CAP-78 - Detector drill-through evidence
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `EVI-1`, `EVI-2`, `EVI-5`, `EVI-7`, `EVI-9`.
- **Evidence:** `EVD-56`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-80`, `EVD-81`, `EVD-82`, `EVD-87`, `EVD-88`, `EVD-89`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Potential detector inputs are queryable in separate carriers, but named cross-run detector findings, input windows, thresholds, and durable drill-through identities do not exist.
- **Prohibited interpretation:** Do not present raw logs or charts as evidence for a detector verdict that was never produced.

### CAP-81 - Restore prior ranking, filter, and scroll position
- **Required status:** `gap`; `implementation_status: absent`; `epistemic_status: observed`.
- **Decisive carriers:** none; no canonical selection-return-state entity, state, action, or evidence carrier exists.
- **Evidence:** `EVD-53`.
- **Individual limitation:** The UI projection audit found no persisted return-state contract for ranking, filter, and scroll coordinates.
- **Prohibited interpretation:** Do not infer restoration from browser history, component survival, or preservation of only a run route parameter.

### CAP-85 - Ignore or keep watching
- **Required status:** `gap`; `implementation_status: absent`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-17` (explicit absent contract).
- **Evidence:** `EVD-53`, `EVD-61`.
- **Individual limitation:** No command records item identity, operator choice, scope, expiry, or later attention state without resolving the condition.
- **Prohibited interpretation:** Do not treat closing a view, taking no action, or leaving an item unresolved as a durable watch decision.

### CAP-92 - Steer with new context
- **Required status:** `gap`; `implementation_status: absent`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-15` (explicit absent contract).
- **Evidence:** `EVD-61`.
- **Individual limitation:** No reachable typed directive/context-injection command, durable directive record, or future-packet binding path exists.
- **Prohibited interpretation:** Do not relabel clarification answers, recovery guidance, prompt edits, or raw graph patches as live-run steering.

### CAP-93 - Apply a steering patch
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-13`, `ACT-16` (explicit absent typed-steering contract), `STA-54`, `STA-55`, `STA-64`, `PER-4`, `EVI-8`.
- **Evidence:** `EVD-37`, `EVD-41`, `EVD-61`, `EVD-90`, `EVD-91`, `EVD-105` (only the narrow raw graph patch-validation implementation).
- **Individual limitation:** Raw graph patch submission and validation are implemented, but steering proposal identity, new-context provenance, directive binding, and steering-specific result semantics are absent.
- **Prohibited interpretation:** Do not call every accepted graph topology patch a steering patch or use patch validation as directive-delivery evidence.

### CAP-106 - Next expected system activity
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `STA-2`, `STA-3`, `STA-9`, `STA-10`, `STA-18`, `STA-29`, `STA-30`, `EVI-1`, `EVI-2`, `EVI-8`.
- **Evidence:** `EVD-7`, `EVD-8`, `EVD-12`, `EVD-24`, `EVD-57`, `EVD-63`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`, `EVD-90`, `EVD-91`.
- **Individual limitation:** Current lifecycle and scheduler states constrain possible next work, but action responses do not consistently publish one expected-next-activity contract.
- **Prohibited interpretation:** Do not map a current state mechanically to one guaranteed next activity when queues, gates, races, or failures can intervene.

### CAP-108 - Evidence convergence
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-7`, `ENT-15`, `ENT-16`, `EVI-3`.
- **Evidence:** `EVD-56`, `EVD-58`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Requirement-support freshness and verification records provide one current input family, but no convergence rule, time window, confidence rule, or health output exists.
- **Prohibited interpretation:** Do not equate fresh support evidence, more records, or repeated agreement with evidence convergence.

### CAP-110 - Degraded classification
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-5`, `ENT-6`, `STA-15`, `STA-24`, `STA-34`, `STA-41`, `STA-55`, `EVI-1`, `EVI-2`.
- **Evidence:** `EVD-10`, `EVD-16`, `EVD-22`, `EVD-26`, `EVD-28`, `EVD-37`, `EVD-56`, `EVD-58`.
- **Individual limitation:** Failures, retries, grade changes, and patch rejections are available as inputs, but no shared degraded threshold or classifier result exists.
- **Prohibited interpretation:** Do not label every failed node, rejected patch, or low grade as a degraded run.

### CAP-111 - Stalled classification
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-17`, `ENT-18`, `STA-26`, `STA-30`, `STA-31`, `STA-32`, `EVI-1`, `EVI-2`.
- **Evidence:** `EVD-20`, `EVD-23`, `EVD-24`, `EVD-56`, `EVD-58`, `EVD-69`, `EVD-70`, `EVD-71`, `EVD-72`, `EVD-73`.
- **Individual limitation:** Heartbeat, lease, event, node, and outbox facts can indicate inactivity, but no persisted last-successful-event join, timeout policy, or stalled result exists.
- **Prohibited interpretation:** Do not call a suspended node, failed outbox row, quiet output stream, or old event independently a stalled run.

### CAP-112 - Runaway classification
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `EVI-5`, `EVI-9`, `ENT-5`, `ENT-17`.
- **Evidence:** `EVD-54`, `EVD-56`, `EVD-58`, `EVD-80`, `EVD-81`, `EVD-82`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`.
- **Individual limitation:** Repetition inputs, attempts, leases, action limits, and usage are incomplete and no combined spend/repetition/pace detector produces a runaway finding.
- **Prohibited interpretation:** Do not label high spend, many attempts, or repeated output alone as runaway.

### CAP-113 - Steered classification
- **Required status:** `gap`; `implementation_status: absent`; `epistemic_status: observed`.
- **Decisive carriers:** `ACT-15` (explicit absent steering contract); no classifier carrier exists.
- **Evidence:** `EVD-56`, `EVD-61`, `EVD-77`, `EVD-78`, `EVD-79`.
- **Individual limitation:** Because typed steering and directive binding are absent, there is no safe fact from which a steered classifier could be produced.
- **Prohibited interpretation:** Do not classify a run as steered because its prompt, guidance, topology, or files changed.

### CAP-116 - Active comparison target
- **Required status:** `gap`; `implementation_status: absent`; `epistemic_status: observed`.
- **Decisive carriers:** none; `ENT-2` identifies runs but no comparison-target carrier or action exists.
- **Evidence:** `EVD-53`.
- **Individual limitation:** UI selection is route/local-state specific and no canonical second-run comparison target identity persists across projections.
- **Prohibited interpretation:** Do not treat a recently viewed run, cost-rollup group, or browser tab as the active canonical comparison target.

### CAP-117 - Freshness and capability annotations persist with selection
- **Required status:** `gap`; `implementation_status: partial`; `epistemic_status: observed`.
- **Decisive carriers:** `ENT-2`, `ENT-7`, `ENT-15`, `EVI-3`.
- **Evidence:** `EVD-53`, `EVD-56`, `EVD-58`, `EVD-74`, `EVD-75`, `EVD-76`.
- **Individual limitation:** Some requirement evidence has freshness semantics and run identity can remain selected, but annotations are not bound to a persistent selection context across projections.
- **Prohibited interpretation:** Do not assume an annotation remains fresh or attached merely because the same run ID is still in the route.

## Former-derived correction (12 capability records)

No current derivation exists for these records. The 12 records below correspond
to 11 superseded historical derivation allocations because prompt size was a
shared semantic derivation candidate. Their status is based on observed partial
inputs or unresolved coverage, never on an existing derivation. `EVD-105` is not
relevant to any of them; it proves only raw graph patch validation.

| CAP | Correct status | Epistemic status | Actual evidence, conflicts, and questions | Replacement wording |
|---|---|---|---|---|
| `CAP-5` | `gap` / `partial` | `observed` | `EVD-56`, `EVD-58`, `EVD-69`-`EVD-73`; no conflict or question | Event timestamps exist in split streams, but no complete last-event join, clock rule, or age producer implements last-event age. |
| `CAP-12` | `gap` / `partial` | `observed` | `EVD-49`, `EVD-50`, `EVD-51`, `EVD-54`, `EVD-57`; `CON-1`, `Q-1` qualify attempt identity | Attempt and limit inputs exist, but no cross-mode remaining-attempt contract implements attempts left. |
| `CAP-22` | `unknown` / `partial` | `unknown` | `EVD-56`, `EVD-58`, `EVD-69`-`EVD-73`; `CON-8`; no open question | Workflow and graph ordering are real within their carriers, but the complete public cross-stream chronology remains unresolved. |
| `CAP-24` | `gap` / `partial` | `observed` | `EVD-55`, `EVD-56`, `EVD-58`, `EVD-69`-`EVD-76`; no conflict or question | Grade facts exist in legacy and graph carriers, but no normalized requirement-grade change history implements the demand. |
| `CAP-30` | `gap` / `partial` | `observed` | `EVD-77`, `EVD-78`, `EVD-79`; no conflict or question | Legacy text and graph packet summaries are incomplete inputs; no canonical prompt-size producer exists. |
| `CAP-46` | `unknown` / `partial` | `unknown` | `EVD-64`, `EVD-92`, `EVD-93`, `EVD-94`, `EVD-95`; `CON-9`; no open question | Graph returned-execution usage can group by node kind, but legacy and missing/exception executions prevent resolution of the broader spend-and-token demand. |
| `CAP-47` | `gap` / `partial` | `observed` | `EVD-64`, `EVD-92`-`EVD-95`; `CON-9`; no open question | Missing-rate counts are inputs, but no complete-denominator unpriced-share field or algorithm is implemented. |
| `CAP-48` | `gap` / `partial` | `observed` | `EVD-77`, `EVD-78`, `EVD-79`; no conflict or question | Carrier-specific prompt evidence is incomplete and no J7 prompt-size output is implemented. |
| `CAP-57` | `gap` / `partial` | `observed` | `EVD-64`, `EVD-92`-`EVD-95`; `CON-9`; no open question | Missing-rate signals exist, but no complete rate-card and execution denominator implements price coverage. |
| `CAP-58` | `gap` / `partial` | `observed` | `EVD-37`, `EVD-72`, `EVD-73`, `EVD-90`, `EVD-91`; no conflict or question | Patch attempts and events exist, but no scoped, deduplicated patch-count contract implements the demand. |
| `CAP-59` | `gap` / `partial` | `observed` | `EVD-14`, `EVD-44`, `EVD-45`, `EVD-49`, `EVD-51`, `EVD-54`, `EVD-57`, `EVD-69`-`EVD-73`; `CON-1`, `Q-1` | Several retry and attempt carriers exist, but identity and taxonomy prevent a canonical retry count. |
| `CAP-68` | `gap` / `partial` | `observed` | `EVD-13`, `EVD-27`, `EVD-63`, `EVD-69`-`EVD-73`, `EVD-90`, `EVD-91`; no conflict or question | Decision timestamps are inputs, but no wait-start, clock, or age projection implements decision wait age. |

## Historical audit index

The YAML block is historical audit output only; the canonical registry is authoritative. Carrier lists are
demand-specific decisive canonical IDs; it does not prescribe registry carrier assignments or claim that each carrier implements
the whole capability. Empty carriers on absent records are intentional except
where an explicit absent `ACT` contract records the absence.

```yaml
schema_version: 1
audit_scope: current-gap-and-unknown
records:
  CAP-1: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-2, ENT-4, ENT-12, STA-2, STA-9, STA-18, STA-31, EVI-1, EVI-2], evidence: [EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73]}
  CAP-2: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-2, ENT-4, ENT-12, STA-2, STA-9, STA-18, EVI-1, EVI-2], evidence: [EVD-57, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73]}
  CAP-3: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, STA-11, STA-36, EVI-8], evidence: [EVD-13, EVD-27, EVD-57, EVD-63, EVD-90, EVD-91]}
  CAP-4: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-12, ENT-13, ENT-17, ENT-18, STA-28, STA-29, STA-30, STA-31, STA-32, EVI-2], evidence: [EVD-24, EVD-58, EVD-72, EVD-73]}
  CAP-5: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-9, ENT-10, ENT-11, EVI-1, EVI-2], evidence: [EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73]}
  CAP-6: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-21, EVI-9], evidence: [EVD-56, EVD-64, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-7: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-12, ENT-13, ENT-14, ENT-16, ACT-13, STA-54, EVI-2, EVI-3], evidence: [EVD-37, EVD-58, EVD-72, EVD-73, EVD-74, EVD-75, EVD-76]}
  CAP-8: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-3, ENT-13, STA-2, STA-8, STA-9, STA-18, STA-28, STA-29, STA-30, STA-31], evidence: [EVD-49, EVD-52, EVD-53, EVD-58]}
  CAP-9: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-12, ENT-14, ENT-16], evidence: [EVD-58]}
  CAP-10: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-12, ENT-13, ENT-14, STA-28, STA-29, STA-30, EVI-2, EVI-3], evidence: [EVD-58, EVD-72, EVD-73, EVD-74, EVD-75, EVD-76]}
  CAP-11: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-2, ENT-4, ENT-12, STA-3, STA-11, STA-26, STA-28, STA-32], evidence: [EVD-8, EVD-13, EVD-23, EVD-24, EVD-57, EVD-58]}
  CAP-12: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-4, ENT-5, STA-8, STA-9, STA-15, EVI-1], evidence: [EVD-49, EVD-50, EVD-51, EVD-54, EVD-57, EVD-69, EVD-70, EVD-71], conflicts: [CON-1], questions: [Q-1]}
  CAP-13: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-7, ENT-8, ENT-12, ENT-15, ENT-16, EVI-3], evidence: [EVD-49, EVD-52, EVD-55, EVD-58, EVD-74, EVD-75, EVD-76]}
  CAP-14: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, STA-11, STA-36, EVI-8], evidence: [EVD-13, EVD-27, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-15: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, ENT-20, EVI-1, EVI-2, EVI-8], evidence: [EVD-57, EVD-63, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-90, EVD-91]}
  CAP-16: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, ENT-20, EVI-8], evidence: [EVD-49, EVD-61, EVD-63, EVD-90, EVD-91], conflicts: [CON-4], questions: [Q-5]}
  CAP-17: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-13, ENT-14, ENT-15, ENT-16, ACT-13, EVI-8], evidence: [EVD-37, EVD-58, EVD-63, EVD-90, EVD-91]}
  CAP-18: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [EVI-8], evidence: [EVD-56, EVD-63, EVD-90, EVD-91]}
  CAP-19: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, ACT-10, ACT-11, ACT-12, EVI-8], evidence: [EVD-27, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-20: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-12, ENT-13, ENT-14, ENT-16, ACT-13, EVI-2, EVI-3], evidence: [EVD-37, EVD-58, EVD-72, EVD-73, EVD-74, EVD-75, EVD-76]}
  CAP-21: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ACT-13, ACT-18, ACT-19, ACT-20, ACT-21, ACT-23, ACT-24, ACT-26, ACT-29, ACT-31, ACT-52, ACT-53, ACT-55, ACT-56, EVI-8], evidence: [EVD-11, EVD-20, EVD-29, EVD-37, EVD-45, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-22: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-9, ENT-11, EVI-1, EVI-2], evidence: [EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73], conflicts: [CON-8]}
  CAP-23: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-4, ENT-5, EVI-1], evidence: [EVD-49, EVD-51, EVD-54, EVD-69, EVD-70, EVD-71], conflicts: [CON-1], questions: [Q-1]}
  CAP-24: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-6, ENT-7, ENT-9, ENT-11, ENT-15, EVI-1, EVI-2, EVI-3], evidence: [EVD-55, EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-74, EVD-75, EVD-76]}
  CAP-25: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-13, ACT-45, STA-54, STA-55, STA-64, EVI-2, EVI-8], evidence: [EVD-37, EVD-58, EVD-72, EVD-73, EVD-90, EVD-91]}
  CAP-26: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [STA-1, STA-2, STA-3, STA-4, STA-8, STA-9, STA-10, STA-11, STA-16, STA-18, STA-20, STA-22, STA-23, EVI-1, EVI-2], evidence: [EVD-7, EVD-8, EVD-12, EVD-17, EVD-18, EVD-20, EVD-21, EVD-57, EVD-58]}
  CAP-27: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-5, ACT-24, ACT-25, ACT-31, ACT-34, ACT-38, ACT-45, EVI-1, EVI-2, EVI-8], evidence: [EVD-12, EVD-14, EVD-37, EVD-44, EVD-45, EVD-54, EVD-57, EVD-58]}
  CAP-28: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-15, ENT-16, EVI-3, EVI-4], evidence: [EVD-56, EVD-58, EVD-74, EVD-75, EVD-76, EVD-77, EVD-78, EVD-79]}
  CAP-29: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [EVI-4], evidence: [EVD-56, EVD-77, EVD-78, EVD-79]}
  CAP-30: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-22, EVI-4], evidence: [EVD-77, EVD-78, EVD-79]}
  CAP-31: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-22, EVI-5], evidence: [EVD-56, EVD-80, EVD-81, EVD-82]}
  CAP-32: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-22, EVI-5], evidence: [EVD-56, EVD-80, EVD-81, EVD-82]}
  CAP-33: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-23, ENT-24, ENT-25, ENT-26, EVI-6], evidence: [EVD-49, EVD-54, EVD-56, EVD-65, EVD-83, EVD-84, EVD-85, EVD-86], conflicts: [CON-5]}
  CAP-34: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [EVI-7], evidence: [EVD-56, EVD-87, EVD-88, EVD-89]}
  CAP-35: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-15, ENT-22, ENT-23, ENT-24, EVI-3, EVI-5, EVI-6], evidence: [EVD-49, EVD-56, EVD-74, EVD-75, EVD-76, EVD-80, EVD-81, EVD-82, EVD-83, EVD-84, EVD-85, EVD-86]}
  CAP-36: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-21, EVI-9], evidence: [EVD-56, EVD-64, EVD-92, EVD-93, EVD-94, EVD-95], conflicts: [CON-9]}
  CAP-37: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [STA-6, STA-15, STA-24, STA-26, STA-34, STA-41, STA-55, EVI-1, EVI-2], evidence: [EVD-10, EVD-16, EVD-22, EVD-23, EVD-26, EVD-28, EVD-37, EVD-57, EVD-58]}
  CAP-38: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-5, ENT-6, EVI-4, EVI-5, EVI-7, EVI-9], evidence: [EVD-49, EVD-51, EVD-54, EVD-55, EVD-77, EVD-78, EVD-79, EVD-80, EVD-81, EVD-82, EVD-87, EVD-88, EVD-89, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-39: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-10, ACT-11, ACT-12, ACT-13, ACT-18, ACT-19, ACT-20, ACT-21, ACT-31, ACT-32, ACT-33, ACT-14, EVI-8], evidence: [EVD-11, EVD-14, EVD-20, EVD-23, EVD-27, EVD-37, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-40: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-10, ACT-11, ACT-12, ACT-13, ACT-14, ACT-18, ACT-20, EVI-8], evidence: [EVD-11, EVD-20, EVD-23, EVD-27, EVD-37, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-41: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-2, ENT-4, ENT-13, ENT-18, ACT-10, ACT-13, ACT-14, EVI-8], evidence: [EVD-23, EVD-27, EVD-37, EVD-49, EVD-58, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-42: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ACT-10, ACT-11, ACT-12, PER-1, PER-2, PER-3, PER-4, PER-5, EVI-8], evidence: [EVD-27, EVD-38, EVD-39, EVD-40, EVD-41, EVD-42, EVD-61, EVD-63, EVD-90, EVD-91], conflicts: [CON-4], questions: [Q-5]}
  CAP-43: {status: gap, implementation_status: absent, epistemic_status: observed, carriers: [], disqualifying_inputs: [EVI-9], evidence: [EVD-56, EVD-64, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-44: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ACT-13, ACT-18, ACT-19, ACT-20, ACT-21, ACT-31, ACT-32, ACT-33, ACT-52, ACT-53, ACT-55, ACT-56, EVI-8], evidence: [EVD-11, EVD-20, EVD-29, EVD-37, EVD-45, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-45: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-13, ACT-45, PER-3, PER-4, PER-6, PER-7, STA-54, STA-55, STA-61], evidence: [EVD-37, EVD-40, EVD-41, EVD-46, EVD-61]}
  CAP-46: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-13, ENT-21, EVI-9], evidence: [EVD-58, EVD-64, EVD-92, EVD-93, EVD-94, EVD-95], conflicts: [CON-9]}
  CAP-47: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-21, EVI-9], evidence: [EVD-64, EVD-92, EVD-93, EVD-94, EVD-95], conflicts: [CON-9]}
  CAP-48: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-22, EVI-4], evidence: [EVD-77, EVD-78, EVD-79]}
  CAP-49: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-5, ENT-6, ACT-31, ACT-34, ACT-38, EVI-1, EVI-4, EVI-5, EVI-7], evidence: [EVD-14, EVD-44, EVD-45, EVD-54, EVD-55, EVD-69, EVD-70, EVD-71, EVD-77, EVD-78, EVD-79, EVD-80, EVD-81, EVD-82, EVD-87, EVD-88, EVD-89]}
  CAP-50: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [EVI-1, EVI-5], evidence: [EVD-56, EVD-69, EVD-70, EVD-71, EVD-80, EVD-81, EVD-82]}
  CAP-51: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-5, ENT-6, ENT-7, ENT-15, EVI-1, EVI-2, EVI-3], evidence: [EVD-54, EVD-55, EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-74, EVD-75, EVD-76]}
  CAP-52: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-1, ENT-2, ENT-27, ENT-28, EVI-9], evidence: [EVD-49, EVD-56, EVD-68, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-53: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-1, ENT-2], evidence: [EVD-49]}
  CAP-54: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-27, ENT-28, EVI-9], evidence: [EVD-49, EVD-56, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-55: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-5, ENT-21, EVI-9], evidence: [EVD-54, EVD-56, EVD-64, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-56: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-21, EVI-9], evidence: [EVD-56, EVD-64, EVD-92, EVD-93, EVD-94, EVD-95], conflicts: [CON-9]}
  CAP-57: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-21, EVI-9], evidence: [EVD-64, EVD-92, EVD-93, EVD-94, EVD-95], conflicts: [CON-9]}
  CAP-58: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ACT-13, ACT-45, STA-54, STA-55, STA-64, EVI-2, EVI-8], evidence: [EVD-37, EVD-72, EVD-73, EVD-90, EVD-91]}
  CAP-59: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-5, ACT-31, ACT-34, ACT-38, EVI-1, EVI-2], evidence: [EVD-14, EVD-44, EVD-45, EVD-49, EVD-51, EVD-54, EVD-57, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73], conflicts: [CON-1], questions: [Q-1]}
  CAP-60: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-6, ENT-7, ENT-15, EVI-1, EVI-2, EVI-3], evidence: [EVD-55, EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-74, EVD-75, EVD-76]}
  CAP-61: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-10, ACT-11, ACT-12, ACT-13, ACT-14, ACT-18, ACT-19, ACT-20, ACT-21, ACT-31, ACT-32, ACT-33, EVI-8], evidence: [EVD-11, EVD-14, EVD-20, EVD-23, EVD-27, EVD-37, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-62: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-2, ENT-4, ENT-5, ENT-13, STA-5, STA-6, STA-7, STA-14, STA-15, STA-23, STA-24, STA-25, STA-33, STA-34, STA-35, EVI-1, EVI-2], evidence: [EVD-9, EVD-10, EVD-11, EVD-12, EVD-16, EVD-20, EVD-21, EVD-22, EVD-25, EVD-26, EVD-57]}
  CAP-63: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-27, ENT-28, EVI-4, EVI-9], evidence: [EVD-49, EVD-56, EVD-77, EVD-78, EVD-79, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-64: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-12, ENT-13, ENT-14, ENT-15, ENT-16, STA-36, STA-37, EVI-3, EVI-8], evidence: [EVD-27, EVD-58, EVD-63, EVD-74, EVD-75, EVD-76, EVD-90, EVD-91]}
  CAP-65: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-9, ENT-11, EVI-1, EVI-2], evidence: [EVD-53, EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73], conflicts: [CON-8]}
  CAP-66: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-19, STA-11, STA-36, EVI-8], evidence: [EVD-13, EVD-27, EVD-53, EVD-63, EVD-90, EVD-91]}
  CAP-67: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [EVI-1, EVI-2, EVI-5, EVI-9], evidence: [EVD-56, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-80, EVD-81, EVD-82, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-68: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-19, ENT-20, STA-11, STA-36, STA-37, EVI-1, EVI-2, EVI-8], evidence: [EVD-13, EVD-27, EVD-63, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-90, EVD-91]}
  CAP-70: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, ENT-20, STA-37, STA-52, STA-53, EVI-8], evidence: [EVD-13, EVD-27, EVD-36, EVD-49, EVD-63, EVD-90, EVD-91], conflicts: [CON-4], questions: [Q-5]}
  CAP-71: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-5, ENT-21, ENT-27, ENT-28, EVI-9], evidence: [EVD-49, EVD-54, EVD-56, EVD-64, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-72: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-15, ENT-23, ENT-24, EVI-3, EVI-6, EVI-7], evidence: [EVD-56, EVD-58, EVD-65, EVD-74, EVD-75, EVD-76, EVD-83, EVD-84, EVD-85, EVD-86, EVD-87, EVD-88, EVD-89], conflicts: [CON-5]}
  CAP-73: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [EVI-1, EVI-2, EVI-3, EVI-4, EVI-5, EVI-7], evidence: [EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-74, EVD-75, EVD-76, EVD-77, EVD-78, EVD-79, EVD-80, EVD-81, EVD-82, EVD-87, EVD-88, EVD-89]}
  CAP-74: {status: gap, implementation_status: absent, epistemic_status: observed, carriers: [ACT-15], disqualifying_inputs: [EVI-4], evidence: [EVD-56, EVD-61, EVD-77, EVD-78, EVD-79]}
  CAP-75: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-5, ENT-13, ENT-17, EVI-1, EVI-2], evidence: [EVD-49, EVD-51, EVD-54, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73], conflicts: [CON-1], questions: [Q-1, Q-2]}
  CAP-76: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [EVI-7], evidence: [EVD-56, EVD-87, EVD-88, EVD-89]}
  CAP-77: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-13, ENT-17, EVI-2, EVI-9], evidence: [EVD-58, EVD-72, EVD-73, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-78: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [EVI-1, EVI-2, EVI-5, EVI-7, EVI-9], evidence: [EVD-56, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-80, EVD-81, EVD-82, EVD-87, EVD-88, EVD-89, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-79: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-2, ENT-3, ENT-4, ENT-5, ENT-13, ENT-15], evidence: [EVD-49, EVD-51, EVD-53, EVD-54, EVD-58], conflicts: [CON-1], questions: [Q-1, Q-2]}
  CAP-80: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-2, ENT-5, ENT-13, ENT-19, ENT-20, EVI-8], evidence: [EVD-49, EVD-51, EVD-53, EVD-54, EVD-58, EVD-63, EVD-90, EVD-91], conflicts: [CON-1], questions: [Q-1, Q-2]}
  CAP-81: {status: gap, implementation_status: absent, epistemic_status: observed, carriers: [], evidence: [EVD-53]}
  CAP-85: {status: gap, implementation_status: absent, epistemic_status: observed, carriers: [ACT-17], evidence: [EVD-53, EVD-61]}
  CAP-87: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, ENT-20, ACT-29, ACT-30, STA-11, STA-52, EVI-8], evidence: [EVD-13, EVD-61, EVD-62, EVD-63, EVD-90, EVD-91]}
  CAP-88: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-31, ACT-34, ACT-38, ACT-39, ACT-40, EVI-8], evidence: [EVD-14, EVD-44, EVD-45, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-89: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-18, ACT-19, ACT-20, ACT-21, STA-2, STA-3, STA-4, STA-7, STA-18, STA-20, STA-22, STA-25, EVI-8], evidence: [EVD-7, EVD-8, EVD-11, EVD-17, EVD-19, EVD-20, EVD-38, EVD-39, EVD-40, EVD-61], conflicts: [CON-6, CON-7]}
  CAP-90: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-13, PER-4, EVI-8], evidence: [EVD-37, EVD-41, EVD-61, EVD-63, EVD-90, EVD-91], questions: [Q-6]}
  CAP-91: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-18, ACT-14, STA-26, STA-27, PER-4, EVI-8], evidence: [EVD-23, EVD-41, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-92: {status: gap, implementation_status: absent, epistemic_status: observed, carriers: [ACT-15], evidence: [EVD-61]}
  CAP-93: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ACT-13, ACT-16, STA-54, STA-55, STA-64, PER-4, EVI-8], evidence: [EVD-37, EVD-41, EVD-61, EVD-90, EVD-91, EVD-105]}
  CAP-94: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-1, ACT-66, ACT-67, ACT-68, ACT-69, ACT-70, ACT-71, STA-47, STA-48, STA-66, STA-67, STA-68, STA-69, PER-7], evidence: [EVD-32, EVD-33, EVD-49, EVD-61]}
  CAP-102: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [STA-54, STA-55, STA-61, EVI-8], evidence: [EVD-37, EVD-46, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-103: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-13, ACT-45, ACT-65, STA-54, STA-55, STA-61, EVI-8], evidence: [EVD-37, EVD-46, EVD-58, EVD-63, EVD-90, EVD-91]}
  CAP-104: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-9, ENT-11, ENT-15, EVI-1, EVI-2, EVI-8], evidence: [EVD-49, EVD-56, EVD-58, EVD-63, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-90, EVD-91], conflicts: [CON-8]}
  CAP-105: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [STA-2, STA-3, STA-4, STA-7, STA-9, STA-14, STA-15, STA-18, STA-22, STA-23, STA-24, STA-25, STA-33, STA-34, STA-35, STA-37, STA-54, STA-55, EVI-8], evidence: [EVD-7, EVD-8, EVD-11, EVD-12, EVD-16, EVD-18, EVD-20, EVD-21, EVD-22, EVD-25, EVD-26, EVD-27, EVD-37, EVD-57, EVD-63, EVD-90, EVD-91]}
  CAP-106: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [STA-2, STA-3, STA-9, STA-10, STA-18, STA-29, STA-30, EVI-1, EVI-2, EVI-8], evidence: [EVD-7, EVD-8, EVD-12, EVD-24, EVD-57, EVD-63, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-90, EVD-91]}
  CAP-107: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ACT-13, ACT-14, ACT-29, ACT-31, ACT-34, ACT-38, EVI-8], evidence: [EVD-13, EVD-14, EVD-23, EVD-37, EVD-44, EVD-45, EVD-61, EVD-63, EVD-90, EVD-91]}
  CAP-108: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-7, ENT-15, ENT-16, EVI-3], evidence: [EVD-56, EVD-58, EVD-74, EVD-75, EVD-76]}
  CAP-109: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-19, STA-11, STA-36, EVI-8], evidence: [EVD-13, EVD-27, EVD-57, EVD-63, EVD-90, EVD-91]}
  CAP-110: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-5, ENT-6, STA-15, STA-24, STA-34, STA-41, STA-55, EVI-1, EVI-2], evidence: [EVD-10, EVD-16, EVD-22, EVD-26, EVD-28, EVD-37, EVD-56, EVD-58]}
  CAP-111: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-17, ENT-18, STA-26, STA-30, STA-31, STA-32, EVI-1, EVI-2], evidence: [EVD-20, EVD-23, EVD-24, EVD-56, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73]}
  CAP-112: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-5, ENT-17, EVI-5, EVI-9], evidence: [EVD-54, EVD-56, EVD-58, EVD-80, EVD-81, EVD-82, EVD-92, EVD-93, EVD-94, EVD-95]}
  CAP-113: {status: gap, implementation_status: absent, epistemic_status: observed, carriers: [ACT-15], evidence: [EVD-56, EVD-61, EVD-77, EVD-78, EVD-79]}
  CAP-114: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [STA-5, STA-14, STA-23, STA-33, EVI-1, EVI-2], evidence: [EVD-9, EVD-12, EVD-21, EVD-25, EVD-57]}
  CAP-115: {status: unknown, implementation_status: partial, epistemic_status: unknown, carriers: [ENT-2, ENT-3, ENT-4, ENT-5, ENT-13, ENT-15, EVI-1, EVI-2], evidence: [EVD-49, EVD-51, EVD-58, EVD-69, EVD-70, EVD-71, EVD-72, EVD-73, EVD-96], conflicts: [CON-1], questions: [Q-1, Q-2]}
  CAP-116: {status: gap, implementation_status: absent, epistemic_status: observed, carriers: [], evidence: [EVD-53]}
  CAP-117: {status: gap, implementation_status: partial, epistemic_status: observed, carriers: [ENT-2, ENT-7, ENT-15, EVI-3], evidence: [EVD-53, EVD-56, EVD-58, EVD-74, EVD-75, EVD-76]}
counts:
  audited_records: 105
  gap: 49
  unknown: 56
  gap_implementation_partial: 42
  gap_implementation_absent: 7
  unknown_implementation_partial: 56
  former_derived_records_corrected: 12
  former_derived_gap: 10
  former_derived_unknown: 2
  evd_105_former_derived_references: 0
  evd_105_narrow_patch_validation_references: 1
```

## Final counts and conclusion

- Audited: **105** records: **49 gap** and **56 unknown**.
- Gap implementation status: **42 partial**, **7 absent**.
- Unknown implementation status: **56 partial**, **0 absent**.
- Former-derived corrections: **12 capability records**: **10 gap**, **2 unknown**; all are `observed` or `unknown`, not `deterministically-derived`.
- `EVD-105`: **0** former-derived references; **1** narrow relevance to raw patch validation under `CAP-93`.
- Referenced canonical IDs were checked against the Phase 1 inventories and evidence ledger; no unresolved ID is intentionally cited.
