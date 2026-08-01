# Dynamic Graph Operator Loop Concept Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one offline clickable concept that carries an operator from fleet triage through dynamic-graph diagnosis, evidence review, a current decision, proposed steering, recovery confirmation, and postscript.

**Architecture:** A concise Markdown scenario is the factual fixture and citation ledger. One standalone HTML file embeds that fixture and implements seven linked screen states with persistent selection, capability labels, state variants, a proper action modal, and responsive behavior. A final Markdown review records a rubric walkthrough and static verification honestly as internal design evidence, not user-research results.

**Tech Stack:** Markdown, semantic HTML, inline CSS, minimal vanilla JavaScript, `file://` operation, Python standard-library structural checks, Node.js JavaScript syntax checks.

## Global Constraints

- Create only the three files named by the approved spec under `research/ui-foundation/mockups/`.
- Use `r311`, `r312`, `r313`, and `r314`; `r314` is the degrading-run focus.
- Distinguish `current`, `derived`, and `proposed` claims visually and in text.
- Graph selection is one `node_id` scoped to a run; graph nodes are not legacy tasks.
- Do not display a health classifier, retry-information-value detector, causal diagnosis, exact graph prompt, complete transcript, node-exclusive file delta, typed steering, or comparable cohort as current.
- Actor strings are provenance labels, not authenticated identities.
- Current decision feedback must progress from `accepted, applying...` to projection-confirmed state; never show optimistic success.
- Proposed steering must remain visibly non-executable.
- Consequential current actions must use a centered modal with backdrop, consequence copy, Cancel, and a clearly labeled confirmation action.
- Preserve run synopsis, selected node, attempt/time context, pending action, freshness, and return context across screen changes.
- The HTML must open directly through `file://` with no build step, external asset, or network request.
- Desktop and narrow layouts must preserve decision-critical context.
- Use ASCII in source files; HTML entities may represent typographic punctuation.
- Do not create catalogs, schemas, validators, generators, source snapshots, feedback importers, or production UI/backend changes.
- Do not run git commands or commit unless the user explicitly requests it.

---

### Task 1: Create The Versioned Scenario Fixture

**Files:**
- Create: `research/ui-foundation/mockups/operator-loop-scenario.md`

**Interfaces:**
- Consumes: `research/ui-foundation/DECISIONS.md`, `research/ui-foundation/agent-reports/02-graph-runtime.md`, `04-api-actions-authority.md`, `05-evidence-telemetry.md`, `06-ui-projections.md`, and `docs/jtbd/`.
- Produces: scenario version `operator-loop-r314-v1` and the exact labels, values, identities, events, capability statuses, expected answers, and citations embedded by Task 2.

- [ ] **Step 1: Run the missing-file acceptance check**

Run:

```bash
uv run python -c 'from pathlib import Path; p=Path("research/ui-foundation/mockups/operator-loop-scenario.md"); assert p.exists()'
```

Expected: FAIL with `AssertionError` because the fixture does not exist.

- [ ] **Step 2: Create the scenario fixture**

Create a readable Markdown document with these exact sections:

```markdown
# Operator Loop Scenario: r314

Scenario version: `operator-loop-r314-v1`
Purpose: Compare one complete operator-loop concept using implementation-shaped synthetic data.

## Capability Legend
## Expected Operator Answers
## Fleet
## Graph For r314
## Repeated Requirement And Attempts
## Evidence Inventory
## Current Decision
## Proposed Steering
## Event Window
## Usage And Cost
## State Variants
## Screen Contract
## Evidence Sources
```

Use this fleet fixture:

| Run | Observed state | Frontier / final gate | Freshness | Human wait | Usage |
|---|---|---|---|---|---|
| `r311` | active; lease on `api-contracts` | frontier emitting; final gate waiting on downstream work | event 24s ago | none | `$1.84`, graph executions, fully priced |
| `r312` | active; `verify-schema` running | verifier running; final gate not ready | event 51s ago | none | `$3.06`, graph executions, fully priced |
| `r313` | completed | final invariant passed | settled 12m ago | none | `$5.72`, graph executions, 92% priced |
| `r314` | active; no active lease | authority gate `gate-01` ready; `final-check` blocked | event 2m 14s ago | one decision | `$8.42` known plus one unpriced execution |

Do not assign fleet health labels. State the selection reason as observed facts:
`r314 has one pending authority decision, two failed verification outcomes for R-17, and a blocked final check.`

Use these eight graph nodes:

| Node ID | Kind | State | Meaning |
|---|---|---|---|
| `plan-01` | planner | completed | initial graph proposal accepted |
| `build-01` | worker | completed | attempt 1 produced `candidate-01` |
| `verify-01` | verifier | completed | `R-17` graded C |
| `build-02` | worker | completed | attempt 2 produced `candidate-02` |
| `verify-02` | verifier | completed | `R-17` graded C again |
| `gate-01` | authority | ready | asks whether to permit one constrained recovery attempt |
| `gap-plan-01` | gap planner | blocked | requires the recorded gate decision |
| `final-check` | check | blocked | requires `R-17` to pass |

Define directed edges as `plan-01 -> build-01 -> verify-01 -> build-02 -> verify-02 -> gate-01 -> gap-plan-01 -> final-check`. Describe this as topology/order, not proven causality.

Use requirement `R-17: Preserve request identity across retries` with:

- attempt 1: grade C; verifier reason `Retry creates a fresh request identity after the first transport failure.`;
- attempt 2: grade C; verifier reason `The generated fallback ID is still regenerated inside the retry branch.`;
- `candidate-01`: changed `graph.py`; preserved payload but not request identity;
- `candidate-02`: changed `graph.py` and `dispatch.py`; added a fallback ID at the wrong lifecycle boundary;
- file-state boundaries are whole-worktree observations at callback time, not node-exclusive causal deltas.

Use one current decision:

- question: `Permit one constrained recovery attempt after recording the request-identity requirement?`;
- choices: Approve, Deny, Defer;
- recorded decider text is provenance only;
- confirmation action: `Approve recovery attempt`;
- result sequence: `accepted, applying...` then `Decision recorded; gap-plan-01 is ready.`;
- stale variant: `Graph advanced from position 184 to 186. Refresh before deciding.`;
- rejection variant: `Decision rejected: authority request is no longer pending.`.

Use one proposed steering concept:

- instruction: `Preserve the original request_id outside the retry loop and prove both attempts share it.`;
- evidence references: `verification-02`, `candidate-02`, `file-state-02`;
- scope: `gap-plan-01 and its future descendants`;
- correction budget: `$3.00 estimated, proposed`;
- primary control text: `Send to planner - not available` and disabled;
- delivery proof is explicitly unavailable because typed steering is not implemented.

Include a compact event window at graph positions 176-186 with node completion, verification record acceptance, gate creation/readiness, decision acceptance, and projection-confirmed readiness. Label the sequence ordered evidence, not a complete causal ledger.

Include two focal usage facts: `build-02` measured at `$2.14`; `verify-02` has tokens and latency but an unknown price. Never render unknown as `$0`.

Define four selectable demo variants: `Nominal`, `Stale proposal`, `Validation rejected`, and `Stream disconnected`. `Live` means event-stream connected only.

For each of the seven screens, state the operator question and expected answer. End with direct report/JTBD path citations supporting identity, topology, action feedback, evidence limits, cost honesty, capability gaps, continuity, and evaluation rules.

- [ ] **Step 3: Verify scenario structure and required facts**

Run:

```bash
uv run python -c 'from pathlib import Path; p=Path("research/ui-foundation/mockups/operator-loop-scenario.md"); t=p.read_text(); required=("operator-loop-r314-v1","## Fleet","## Graph For r314","## Current Decision","## Proposed Steering","## State Variants","R-17","gate-01","gap-plan-01","accepted, applying...","Send to planner - not available","unknown price","ordered evidence, not a complete causal ledger"); assert all(x in t for x in required); assert t.count("| `r31") == 4; assert all(f"`{node}`" in t for node in ("plan-01","build-01","verify-01","build-02","verify-02","gate-01","gap-plan-01","final-check")); print("Scenario fixture verified")'
```

Expected: `Scenario fixture verified`.

---

### Task 2: Build The Seven-State Clickable Concept

**Files:**
- Create: `research/ui-foundation/mockups/operator-loop-concept.html`

**Interfaces:**
- Consumes: scenario `operator-loop-r314-v1` from Task 1.
- Produces: one offline application with root hooks `[data-screen]`, `[data-screen-control]`, `[data-node]`, `[data-variant-control]`, `[data-action-status]`, and dialog `#decision-dialog`.

- [ ] **Step 1: Run the missing-file acceptance check**

Run:

```bash
uv run python -c 'from pathlib import Path; p=Path("research/ui-foundation/mockups/operator-loop-concept.html"); assert p.exists()'
```

Expected: FAIL with `AssertionError` because the concept does not exist.

- [ ] **Step 2: Create the semantic application shell**

Build one self-contained HTML document with this persistent structure:

```html
<header data-run-synopsis>...</header>
<nav aria-label="Operator loop">...</nav>
<main>
  <section data-screen="fleet">...</section>
  <section data-screen="workspace" hidden>...</section>
  <section data-screen="comparison" hidden>...</section>
  <section data-screen="audit" hidden>...</section>
  <section data-screen="decision" hidden>...</section>
  <section data-screen="steering" hidden>...</section>
  <section data-screen="recovery" hidden>...</section>
</main>
<dialog id="decision-dialog">...</dialog>
<div role="status" aria-live="polite" data-live-status></div>
```

Use a distinctive operations-workbench visual language: warm off-white canvas, dark ink, oxidized orange for attention, teal for current evidence, blue for derived calculations, violet for proposed capability, compact mono labels, and serif display headings. Do not imitate a generic SaaS dashboard or the process-spec page.

The persistent synopsis must show `r314`, active state, graph position 184, selected `verify-02`, attempt 2, final check blocked, one pending decision, event age, and graph-scoped cost coverage. It remains present on screens 2-7 and collapses to a sticky strip on narrow screens.

- [ ] **Step 3: Implement all seven screen states**

Implement these exact responsibilities:

1. `fleet`: four rows; positive observed facts for quiet runs; `r314` selected by observed exception facts; no health label; row activation enters `workspace` while preserving fleet return state.
2. `workspace`: eight-node dynamic graph, directed connectors, frontier/blocked/readiness legend, selected-node inspector, final-gate relationship, and full-topology disclosure. Nodes are buttons keyed by run-scoped `node_id`.
3. `comparison`: `R-17` across two attempts with grades, verifier reasons, candidate changes, file-state caveat, measured/unknown cost, and a visible statement that retry value is not a current detector.
4. `audit`: selected `verify-02` with bound records, prompt summary, partial trace, output verification record, file-state boundary, and usage. Show exact prompt and complete transcript as unavailable, not empty.
5. `decision`: current authority request with why-now, evidence, consequence, choices, provenance, validation status, and button opening `#decision-dialog`. Include stale/rejected variants selected by the global demo-state control.
6. `steering`: proposed instruction, evidence references, scope, proposed correction budget, validation route, and disabled `Send to planner - not available` control. Make the entire screen visibly proposed and non-executable.
7. `recovery`: action receipt timeline with `accepted, applying...`, projection confirmation, `gap-plan-01` ready, corrective frontier, and lightweight postscript. Cross-run cohort comparison remains labeled proposed.

Add Previous/Next controls, direct screen controls, `Back to fleet`, and keyboard-visible focus. Changing screens must not reset selected node, attempt context, demo variant, pending decision, or return context.

- [ ] **Step 4: Implement interaction and state variants**

Use one local state object and these function names:

```javascript
const state = {
  screen: 'fleet',
  selectedRun: 'r314',
  selectedNode: 'verify-02',
  variant: 'nominal',
  actionStatus: 'idle',
  returnContext: 'fleet-exceptions'
};

function setScreen(screen) {}
function selectNode(nodeId) {}
function setVariant(variant) {}
function openDecisionDialog() {}
function confirmDecision() {}
function render() {}
```

`confirmDecision()` must close the dialog, set `actionStatus` to `applying`, render `accepted, applying...`, and use a short demo timer to set `actionStatus` to `confirmed` with `Decision recorded; gap-plan-01 is ready.`. The timer demonstrates projection observation; copy must not imply the click itself was success.

Use the native `<dialog>` element. Cancel closes without mutation. The confirmation button is unavailable for stale and rejected variants. Escape closes the dialog. Do not put inline confirm/cancel pairs inside compact cards or graph nodes.

The demo-state control changes all relevant copies:

- `nominal`: connected, pending decision, action enabled;
- `stale`: graph position 186, stale warning, confirmation disabled;
- `rejected`: rejection reason and safe recovery guidance;
- `disconnected`: connection badge says `Stream disconnected`; persisted facts remain visible with freshness warning.

Persist only screen, selected node, and variant in the URL hash. Do not use a backend or external storage.

- [ ] **Step 5: Implement responsive, accessibility, offline, and print behavior**

At desktop widths, use fleet/workspace context plus a persistent inspector where appropriate. Below 760px, stack the selected context before focus content, keep a compact sticky synopsis, make graph nodes a readable vertical dependency sequence, and keep decision evidence visible before action controls.

Include:

- `prefers-reduced-motion` handling;
- visible `:focus-visible` treatment;
- semantic headings and landmarks;
- `aria-current="step"` on active screen control;
- `aria-pressed` on variant controls and selected nodes;
- one centralized live region;
- complete-spec print mode with all screens visible and controls/dialog hidden;
- no external fonts, images, stylesheets, modules, or network URLs.

- [ ] **Step 6: Run structural and JavaScript verification**

Run:

```bash
uv run python -c 'from html.parser import HTMLParser; from pathlib import Path; import re; p=Path("research/ui-foundation/mockups/operator-loop-concept.html"); t=p.read_text(); HTMLParser().feed(t); assert t.startswith("<!doctype html>"); assert len(re.findall(r"data-screen=", t)) == 7; assert all(f"data-screen=\"{s}\"" in t for s in ("fleet","workspace","comparison","audit","decision","steering","recovery")); assert all(x in t for x in ("operator-loop-r314-v1","decision-dialog","accepted, applying...","Decision recorded; gap-plan-01 is ready.","Send to planner - not available","retry information value is not a current detector","Stream disconnected","prefers-reduced-motion")); assert "https://" not in t and "http://" not in t; print("Concept structure verified")'
```

Expected: `Concept structure verified`.

Run:

```bash
node -e 'const fs=require("fs"); const h=fs.readFileSync("research/ui-foundation/mockups/operator-loop-concept.html","utf8"); const s=[...h.matchAll(/<script>([\s\S]*?)<\/script>/g)]; if(s.length!==1) throw new Error(`expected one script, got ${s.length}`); new Function(s[0][1]); console.log("Concept JavaScript syntax verified")'
```

Expected: `Concept JavaScript syntax verified`.

---

### Task 3: Challenge, Evaluate, And Open The Concept

**Files:**
- Create: `research/ui-foundation/mockups/operator-loop-review.md`
- Verify: `research/ui-foundation/mockups/operator-loop-concept.html`
- Verify: `research/ui-foundation/mockups/operator-loop-scenario.md`

**Interfaces:**
- Consumes: scenario and concept from Tasks 1-2 plus `docs/jtbd/evaluation-rubric.md`.
- Produces: an honest internal review record with finding disposition, provisional rubric scores, hard-gate result, and a continue/revise/stop recommendation.

- [ ] **Step 1: Run the missing-file acceptance check**

Run:

```bash
uv run python -c 'from pathlib import Path; p=Path("research/ui-foundation/mockups/operator-loop-review.md"); assert p.exists()'
```

Expected: FAIL with `AssertionError` because the review does not exist.

- [ ] **Step 2: Run one focused implementation-reality challenge**

Review every nontrivial claim in the HTML against the scenario and retained reports. Check exactly:

- graph selection and identity;
- node states and transitions;
- current action reachability and result semantics;
- ordered evidence versus causal language;
- current/derived/proposed leakage;
- authority attribution;
- event freshness and connection wording;
- measured, estimated, graph-scoped, and unknown cost wording.

Correct the scenario or HTML directly for every Critical or Important finding before writing the review. Do not create another finding ledger or canonical model.

- [ ] **Step 3: Create the review record**

Create these exact sections:

```markdown
# Operator Loop Concept Review

Artifact: `operator-loop-concept.html`
Scenario: `operator-loop-r314-v1`
Review type: internal design walkthrough; no participant timing or usability claims

## Verification Performed
## Focused Reality Challenge
## Current-Grounded Tasks 1-6
## Future-Concept Tasks 7-9
## Weighted Rubric
## Switching And Continuity Observations
## Hard Rejection Gate
## Known Limits
## Recommendation
```

Score all ten weighted rubric criteria from 1-5 and compute the weighted total out of 100. Every score must include a one-sentence rationale tied to visible concept behavior. Do not invent task-completion times, participant confidence, or observed user behavior.

Record tasks 1-6 as current-grounded walkthroughs. Record tasks 7-9 as future-concept coherence checks, not implementation readiness. Record destination changes, selection resets, manual reselection, backtracks, persistent irrelevant elements, one-step evidence access, and visible action confirmation as design observations from the artifact.

The Hard Rejection Gate must explicitly check:

- decision readiness >= 3;
- evidence access >= 3;
- action safety and feedback >= 3;
- capability honesty >= 3;
- proposed/derived behavior cannot be mistaken for current;
- screen changes preserve context;
- action feedback reaches projection-confirmed state;
- narrow layout retains decision-critical information.

Use `Continue to human visual review` as the recommendation only if all hard gates pass. Otherwise use `Revise before human review` and list the blocking changes.

- [ ] **Step 4: Verify all three deliverables**

Run:

```bash
uv run python -c 'from pathlib import Path; root=Path("research/ui-foundation/mockups"); paths=[root/"operator-loop-scenario.md",root/"operator-loop-concept.html",root/"operator-loop-review.md"]; assert all(p.exists() and p.stat().st_size > 0 for p in paths); review=paths[2].read_text(); required=("internal design walkthrough; no participant timing or usability claims","## Weighted Rubric","## Hard Rejection Gate","## Known Limits","## Recommendation"); assert all(x in review for x in required); assert all(marker not in review for marker in ("TO"+"DO","TB"+"D")); print("All operator-loop deliverables verified")'
```

Expected: `All operator-loop deliverables verified`.

- [ ] **Step 5: Open the concept**

Run:

```bash
open research/ui-foundation/mockups/operator-loop-concept.html
```

Expected: the default browser opens the Fleet screen. Exercise all seven screen controls, node selection, all four variants, the current decision modal, applying/confirmed action states, proposed steering boundary, disclosures, hash restoration, and representative narrow layout.
