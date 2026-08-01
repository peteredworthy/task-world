# Operator Loop Concept Review

Artifact: `operator-loop-concept.html`
Scenario: `operator-loop-r314-v1`
Review type: internal design walkthrough; no participant timing or usability claims

## Verification Performed

- Performed a static artifact walkthrough of the scenario, HTML, CSS, and JavaScript. No browser was opened, no runtime interaction was exercised, and no viewport was visually inspected.
- Compared nontrivial concept claims with `research/ui-foundation/DECISIONS.md`, retained reports `02-graph-runtime.md`, `04-api-actions-authority.md`, `05-evidence-telemetry.md`, and `06-ui-projections.md`, the job-to-be-done documents, and focused graph command/model source where the retained reports exposed an ambiguity.
- Parsed the HTML with Python's `HTMLParser`, checked all seven declared screens and required copy, and compiled the single inline script with Node's `Function` constructor. These are structural and syntax checks, not browser verification.
- Re-ran the existing scenario acceptance check after corrections: `Scenario fixture verified`.
- Re-ran the existing concept acceptance checks after corrections: `Concept structure verified` and `Concept JavaScript syntax verified`.
- Checked both artifacts as strict ASCII and checked the corrected executable values: `authority_request`, `gap_planner`, `graph:gap-plan-01:execute`, `authority_not_granted:gate-01`, `granted|denied|deferred`, and the REST decision route's `max_grants=0` scheduler result through position 190.

## Focused Reality Challenge

| Challenge area | Finding | Severity | Disposition |
|---|---|---|---|
| Graph selection and identity | Selected-node state may differ from the fixed `verify-02` / `verification-02` evidence anchor. The concept distinguishes them and offers `Select verify-02 evidence anchor`, which selects `verify-02` and opens Audit rather than joining identities. | Important | Corrected persistent synopsis, anchor notice, and genuine selection transition. |
| Evidence access | Structured prompt-summary metadata does not satisfy rubric task 6, which requires a reachable ground-truth packet or transcript. | Blocking | Scored Evidence access below threshold and made raw packet/transcript availability or approved-scope revision a blocker. |
| Node states and transitions | `authority` and `gap planner` were display prose in a column claiming current node kinds, but executable kinds are `authority_request` and `gap_planner`. | Important | Corrected both artifacts to the executable kind values. |
| Current action reachability and result semantics | The authority request omitted list-shaped requested authority/target fields, used approval-oriented labels, treated a decision record as a planner input, compressed a multi-event result into one step, left denial/deferral without refreshed outcomes, and omitted the route's `max_grants=0` scheduler audit. | Important | Added `requested_authority: [graph:gap-plan-01:execute]` and target, mapped Grant/Deny/Defer to `granted|denied|deferred`, represented gate-controlled readiness, expanded the Grant sequence through position 190 with `max_grants_reached` and no lease, and represented all three refreshed outcomes. |
| Ordered evidence versus causal language | The graph and event window are explicitly topology/order and bounded ordered evidence, not proof that adjacent records caused the business outcome. | No defect | Retained the causality limits and state-dependency wording. |
| Current/derived/proposed leakage | Retry information value remains Derived; typed steering and cohort comparison remain Proposed and non-executable; unavailable delivery proof is explicit. | No defect | Retained separate labels and the disabled steering control. |
| Authority attribution | Recorded decider text is provenance only and no authenticated permission or role enforcement is claimed. | No defect | Retained the single-operator attribution boundary and added that no decision-reversal command exists. |
| Event freshness and connection wording | `Live` is limited to stream connectivity; stale, rejected, and disconnected states remove current-readiness claims and retain last-loaded evidence warnings. Rejected state is position unknown with detail position 184 explicitly last-loaded. | Important | Corrected rejected projection and synopsis wording. |
| Measured, estimated, graph-scoped, and unknown cost wording | The r314 partial total lacked an explicit graph-execution scope in several visible locations. | Important | Corrected scenario, synopsis, Fleet, and Recovery wording to `$8.42` known across graph executions plus one unpriced graph execution; measured `$2.14`, unknown price, and proposed `$3.00` estimate remain distinct. |
| Lifecycle guard and recovery | A stopping run cannot receive a second cancel request while its internal sweep completes the transition. | Minor | Added the compact Current lifecycle guard to scenario and Recovery: `Cancel unavailable while stopping` is disabled with its reason. |

No Critical finding remained after the focused challenge. The corrections were limited to material factual and capability defects in the scenario and HTML; no parallel ledger or canonical model was created.

## Current-Grounded Tasks 1-6

1. The Fleet screen supports confirming that `r311` through `r313` show no pending human action and exposes their positive observed states. It deliberately does not satisfy the rubric's unsupported premise that they are "healthy" because no current health classifier supplies that label.
2. The Fleet explanation identifies why `r314` is prominent: one pending authority decision, two failed `R-17` outcomes, and a blocked final check.
3. Workspace exposes `R-17`, the ready `gate-01` frontier, waiting `gap-plan-01`, blocked `final-check`, scheduler buckets, and the empty active lease view.
4. Comparison states that attempt 2 still creates the fallback ID inside the retry branch and shows both grade-C reasons.
5. Comparison labels the no-information-delta judgment Derived and explicitly states that no current retry-information-delta detector exists.
6. Audit exposes only structured prompt-summary metadata, bound records, trace identifiers, verification output, file-state boundary, and usage. It does not complete the required ground-truth inspection because no raw packet or transcript is reachable; the concept correctly labels exact prompt bytes and complete transcript unavailable, but that honesty does not satisfy task 6.

These are static artifact walkthrough results. They are not participant task completions or runtime observations.

## Future-Concept Tasks 7-9

7. The Steering screen coherently specifies a proposed instruction, three evidence references, descendant scope, and a proposed `$3.00` estimate. The current authority decision is kept separate from the unavailable typed-steering command.
8. The concept cannot verify that steering reached corrective work because typed steering and delivery proof do not exist. The current Grant path only represents the separate authority decision making `gap-plan-01` ready at position 189, followed by `max_grants_reached` at position 190 with no lease; it does not establish corrective execution or instruction delivery.
9. The concept cannot show a steering outcome or compare it with prior runs. Recovery labels cohort comparison Proposed and states that no outcome comparison exists.

Tasks 7-9 are future-concept coherence checks only. They do not establish implementation readiness, delivery, outcome, or cross-run analysis capability.

## Weighted Rubric

Scores are provisional static-design judgments on the rubric's 1-5 scale. No score is based on participant behavior, elapsed time, confidence, clicks, or browser observation.

| Criterion | Weight | Score | Weighted points | Static artifact rationale |
|---|---:|---:|---:|---|
| Attention clarity | 12 | 4 | 9.6 | Fleet places the pending decision, repeated failure, and blocked final check beside the four-run comparison without assigning an invented health label. |
| Position and blast radius | 10 | 3 | 6.0 | Workspace combines the frontier, scheduler, leases, bindings, downstream order, and final gate, but it shows bounded topology rather than a computed blast-radius capability. |
| Causal comprehension | 15 | 4 | 12.0 | Comparison and Audit connect the repeated verifier reasons to cited records while repeatedly separating ordered evidence and file boundaries from causal proof. |
| Decision readiness | 15 | 3 | 9.0 | The current decision shows trigger, evidence, choices, consequence, provenance, validation, and no-reversal status, but no current action-specific expected-cost estimate or attempts-left projection exists. |
| Evidence access | 10 | 2 | 4.0 | Audit reaches metadata and records but cannot reach the raw packet or transcript required by task 6; a structured prompt summary is not ground-truth packet inspection. |
| Context continuity | 12 | 4 | 9.6 | Source encodes semantic focus restoration after screen, variant, node, and evidence-anchor rerenders; selected-node state is distinct from the fixed evidence anchor; process-local Fleet return and hash limits remain bounded. Browser focus behavior is unverified. |
| Complexity control | 10 | 3 | 6.0 | Seven purpose-specific screens, an inspector, disclosures, and a compact synopsis provide order, though global navigation and variant controls remain persistent even when they add little to a nominal task. |
| Action safety and feedback | 8 | 4 | 6.4 | The static concept represents modal confirmation, acceptance-to-confirmation distinction, consequences, and ready/blocked resulting states, but no timer-to-backend or API integration was exercised. |
| Capability honesty | 4 | 5 | 4.0 | Current, Synthetic, Derived, Proposed, Unavailable, stale, disconnected, measured, estimated, partial, and unpriced states are explicitly distinguished. |
| Responsive integrity | 4 | 3 | 2.4 | Source inspection shows no intentional hiding of decision evidence below 760px, but it does not prove rendered narrow-layout integrity without browser review. |

Arithmetic: `(12 x 4/5) + (10 x 3/5) + (15 x 4/5) + (15 x 3/5) + (10 x 2/5) + (12 x 4/5) + (10 x 3/5) + (8 x 4/5) + (4 x 5/5) + (4 x 3/5) = 9.6 + 6.0 + 12.0 + 9.0 + 4.0 + 9.6 + 6.0 + 6.4 + 4.0 + 2.4 = 69.0/100`.

## Switching And Continuity Observations

- Destination changes before the current decision: the full sequential artifact path is Fleet -> Workspace -> Comparison -> Audit -> Decision, or four destination changes; direct screen controls allow a shorter static walkthrough. This is a route count, not observed clicking.
- Selection resets: zero are encoded by `setScreen` during an in-page session; selected-node state remains distinct from the fixed `verify-02` evidence anchor. This is separate from reload behavior.
- Manual reselection: if another node is selected, Comparison, Decision, and Steering identify the fixed `verify-02` / `verification-02` evidence anchor and offer `Select verify-02 evidence anchor`; the control selects `verify-02`, opens Audit, updates the hash, and then removes the distinction notice.
- Backtracks: zero are required by the sequential static path; Back to Fleet can restore a process-local scroll/focus anchor during the same page session, but that anchor does not survive reload.
- Persistent irrelevant elements: the global navigation remains useful for orientation, while the four-control demo-variant group is potentially irrelevant during a nominal walkthrough.
- One-step evidence access: the Fleet attention basis and Comparison retry basis are visible in place, and Audit is one direct destination for available metadata and records. No reachable raw packet/transcript exists, so required ground-truth evidence access fails rather than being satisfied by the summary.
- Visible action confirmation: the static concept represents all three current authority choices with modal confirmation, `accepted, applying...`, and a subsequent ready or blocked projection state. This was not observed against a backend or in a browser.
- Hash restoration is limited to screen, selected node, and variant. Attempt, pending decision, freshness, and evidence anchor are fixture/projection-derived render values rather than hash-restored state. Full-rerender focus restoration is source-encoded but browser-unverified; initial/hash load does not request focus.
- Narrow continuity: CSS does not intentionally hide the synopsis, decision evidence, or controls; rendered integrity remains pending browser review.

## Hard Rejection Gate

| Hard gate | Result | Basis |
|---|---|---|
| Decision readiness >= 3 | PASS | Provisional score is 3. |
| Evidence access >= 3 | FAIL | Score is 2 because no reachable raw packet or transcript satisfies task 6; summary metadata is insufficient. |
| Action safety and feedback >= 3 | PASS | Score is 4 because the static concept represents acceptance-to-confirmation distinctly; browser/API integration is unverified. |
| Capability honesty >= 3 | PASS | Provisional score is 5. |
| Proposed/derived behavior cannot be mistaken for current | PASS | Derived retry judgment is labeled; steering and cohort comparison are Proposed; send remains disabled and Unavailable. |
| Screen changes preserve context | PROVISIONAL PASS (static/source) | Source encodes selected-node and fixed evidence-anchor continuity, semantic focus restoration, process-local Fleet return, and hash limits; no browser behavior was verified. |
| Action feedback reaches projection-confirmed state | PROVISIONAL PASS (static representation) | The static concept represents acceptance followed by ready/blocked projection state, including Grant position 190; no browser timer or API integration was exercised. |
| Narrow layout retains decision-critical information | PENDING BROWSER REVIEW | Source shows content is not intentionally hidden, but source inspection cannot establish rendered narrow-layout integrity. |

Evidence access fails a hard threshold, so the concept is not viable under the approved evaluation scope. Action projection feedback has only a provisional static representation, and narrow-layout integrity remains pending browser review; neither can override the evidence-access failure.

## Known Limits

- No browser was opened. Controls, native dialog behavior, timer transitions, hash restoration, print mode, focus behavior, and narrow layout were not runtime-verified in this review.
- No participant session occurred. There are no participant timings, confidence ratings, click counts, observed hesitations, completion claims, or usability findings.
- The fixture is synthetic and offline; its timestamps, costs, event positions, records, and outcomes are comparison data, not production telemetry or a live run.
- The static walkthrough cannot establish visual hierarchy, overflow, contrast in rendered pixels, browser-specific dialog behavior, or practical touch target quality.
- Exact graph prompt bytes, delivery acknowledgement, model ingestion, complete transcript/tool trace, and node-exclusive file causality are unavailable current evidence.
- Hash restoration covers only screen, selected node, and variant. Fleet scroll/focus are process-local, and attempt, pending, freshness, and fixed evidence anchor are fixture/projection-derived rather than URL-restored. Focus restoration is source-encoded but browser-unverified.
- The timer is a static demonstration mechanism, not evidence of observed backend projection confirmation or API integration.
- Typed steering, steering delivery proof, intervention outcome comparison, and cohort analysis remain future concepts.
- The weighted score is evidence for deciding whether to continue review, not proof of usability or product viability by itself.

## Recommendation

`Revise before human review`

The score is `69.0/100`, and Evidence access fails its hard threshold. Blocking change: expose a reachable raw packet or transcript, which requires capability/backend evidence availability, or explicitly revise the approved evaluation scope. The unavailable structured prompt summary does not satisfy ground-truth packet or transcript inspection. After resolving that blocker, browser/API and narrow-layout verification are still required before any usability or integration claim.
