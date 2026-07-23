# Five JTBD UI Approaches HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone seven-slide HTML presentation containing five interactive, visually dense UI approaches to Task World's complete operator JTBD loop.

**Architecture:** One self-contained HTML file owns an immutable shared scenario, a deck controller, a workspace controller, five independent concept renderers, shared visual primitives, and inline CSS/SVG. A Playwright test opens the artifact directly through a `file://` URL and verifies navigation, scenario consistency, interaction, responsive overflow, accessibility, and the absence of network dependencies.

**Tech Stack:** Semantic HTML, inline CSS, vanilla JavaScript, inline SVG, Playwright 1.58, TypeScript test files.

## Global Constraints

- Deliver `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html` as a directly openable standalone file.
- Make no external font, icon, CDN, image, script, stylesheet, or network requests.
- Use the same scenario facts in every concept; concept renderers must consume the shared model rather than duplicate facts.
- Keep human-readable names primary and generated IDs such as `R2` and `N18` secondary.
- Keep grades visible wherever attempts, requirements, or verification nodes affect interpretation.
- Represent growing dimensions vertically or through semantic aggregation; never require horizontal scrolling to reveal additional nodes, events, cases, records, or stages.
- Use proportional ribbons, compact glyphs, aligned tracks, lanes, and fixed statistic columns instead of large metric cards.
- Preserve `constraint -> evidence -> consequence -> action` as the exception-state reading order.
- Label typed steering and planner-assisted replanning as **Proposed capability**.
- Use proper modals for consequential action confirmation; never place confirm/cancel pairs inside compact rows.
- Do not modify production React UI or backend code.
- Do not commit unless the user explicitly requests a commit.

## File Structure

- Create: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
  - Owns the complete presentation, scenario model, controllers, renderers, styles, and SVG.
- Create: `ui/tests/e2e/jtbd-presentation.spec.ts`
  - Opens the HTML through a real `file://` URL and verifies behavior without route interception or mocked dependencies.
- Reference: `docs/superpowers/specs/2026-07-22-jtbd-five-ui-approaches-html-design.md`
  - Approved behavior and visual constraints.
- Reference: `docs/jtbd/evaluation-rubric.md`
  - Comparison-slide criteria and acceptance language.

## Shared Browser Interface

Expose one read-only test/debug facade after initialization:

```js
window.taskWorldPresentation = Object.freeze({
  getState: () => structuredClone(state),
  goToSlide,
  setWorkspaceState,
  selectObject,
});
```

The state shape is:

```js
{
  slide: "loop" | "cartography" | "causal" | "intervention" | "evidence" | "weave" | "comparison",
  workspaceState: "fleet" | "position" | "cause" | "action" | "outcome",
  selectedByConcept: {
    cartography: "N18",
    causal: "verdict-a2",
    intervention: "case-r314",
    evidence: "R2",
    weave: "recovery-verify-a2"
  },
  modal: null | { kind: "intervention"; concept: string; triggerSelector: string }
}
```

Concept renderers use the signature `(scenario, workspaceState, selectedId) => string`.

Every concrete renderer root must include `data-concept="<slide id>"` and
`data-state="${workspaceState}"`. Each state must alter the workspace projection:
`fleet` emphasizes triage, `position` emphasizes current work and relationships,
`cause` emphasizes evidence and causal explanation, `action` emphasizes consequence
and proposed intervention, and `outcome` emphasizes recovery, final grade, merge, and
reusable learning.

---

### Task 1: Standalone Shell, Shared Scenario, and Deck Controller

**Files:**
- Create: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
- Create: `ui/tests/e2e/jtbd-presentation.spec.ts`

**Interfaces:**
- Produces: `SCENARIO`, `SLIDES`, `WORKSPACE_STATES`, `state`, `goToSlide(id)`, `setWorkspaceState(id)`, `selectObject(concept, id)`, `render()`, and `window.taskWorldPresentation`.
- Produces DOM contracts: `[data-presentation]`, `[data-slide]`, `[data-action="previous-slide"]`, `[data-action="next-slide"]`, `[data-workspace-state]`, and `[data-live-region]`.

- [ ] **Step 1: Write the failing shell tests**

Create `ui/tests/e2e/jtbd-presentation.spec.ts` with direct-file loading and initial navigation coverage:

```ts
import { expect, test, type Page } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const testDir = dirname(fileURLToPath(import.meta.url));
const artifactPath = resolve(
  testDir,
  '../../../outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html',
);
const artifactUrl = pathToFileURL(artifactPath).href;

async function openPresentation(page: Page, hash = '') {
  await page.goto(`${artifactUrl}${hash}`);
  await expect(page.locator('[data-presentation]')).toBeVisible();
}

test.describe('JTBD UI approaches presentation', () => {
  test('opens from the filesystem with seven addressable slides', async ({ page }) => {
    await openPresentation(page);
    await expect(page.locator('[data-slide]')).toHaveCount(7);
    await expect(page.getByRole('heading', { name: 'One operating loop, five interface models' })).toBeVisible();

    await page.keyboard.press('ArrowRight');
    await expect(page).toHaveURL(/#cartography$/);
    await expect(page.getByRole('heading', { name: 'Operational Cartography' })).toBeVisible();

    await page.reload();
    await expect(page.getByRole('heading', { name: 'Operational Cartography' })).toBeVisible();
  });

  test('changes workspace state independently of deck navigation', async ({ page }) => {
    await openPresentation(page, '#cartography');
    await page.keyboard.press('3');
    await expect(page.locator('[data-workspace-state="cause"]')).toHaveAttribute('aria-pressed', 'true');
    await expect(page).toHaveURL(/#cartography$/);
  });
});
```

- [ ] **Step 2: Run the tests and confirm the artifact is absent**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts` from `ui/`.

Expected: FAIL because `05-five-approach-interactive-comparison.html` does not exist or `[data-presentation]` is absent.

- [ ] **Step 3: Create the standalone shell and immutable scenario**

Create the HTML document with semantic deck controls, all seven slide containers, the common state rail, and this scenario model:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Task World: Five JTBD UI Approaches</title>
  <style>
    :root {
      --ink: #dce8f1; --muted: #7890a3; --ground: #06121a; --panel: #091923;
      --line: #284354; --verified: #38bda8; --blocking: #fb7185;
      --waiting: #eeb25a; --context: #416074; --focus: #8ee8d8;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: var(--ground); color: var(--ink); }
    body { font-family: Inter, ui-sans-serif, system-ui, sans-serif; overflow-x: hidden; }
    button { font: inherit; }
    button:focus-visible, [tabindex]:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
    [hidden] { display: none !important; }
    .presentation { min-height: 100vh; display: grid; grid-template-rows: 42px 1fr 38px; }
    .slide { min-height: 0; overflow: auto; padding: 18px; }
    .deck-nav, .deck-footer { display: flex; align-items: center; justify-content: space-between; padding: 0 14px; border-color: var(--line); background: #081721; }
    .deck-nav { border-bottom: 1px solid var(--line); }
    .deck-footer { border-top: 1px solid var(--line); }
    .state-rail { display: flex; gap: 4px; }
    .state-rail button[aria-pressed="true"] { color: var(--ink); border-color: var(--focus); }
    @media (max-width: 720px) { .slide { padding: 8px; } .state-rail { overflow-x: auto; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; } }
  </style>
</head>
<body>
  <main class="presentation" data-presentation aria-label="Task World UI concept presentation">
    <header class="deck-nav">
      <strong>TASK WORLD / JTBD INTERFACE STUDY</strong>
      <nav aria-label="Slide navigation">
        <button type="button" data-action="previous-slide">Previous</button>
        <button type="button" data-action="next-slide">Next</button>
      </nav>
    </header>
    <div id="slides"></div>
    <footer class="deck-footer"><span id="slide-position"></span><span>←/→ slides · 1–5 workspace state</span></footer>
    <p class="sr-only" data-live-region aria-live="polite"></p>
  </main>
  <script>
    'use strict';
    const WORKSPACE_STATES = Object.freeze(['fleet', 'position', 'cause', 'action', 'outcome']);
    const SLIDES = Object.freeze(['loop', 'cartography', 'causal', 'intervention', 'evidence', 'weave', 'comparison']);
    const SCENARIO = Object.freeze({
      fleet: Object.freeze({ active: 10, attention: 2, progressing: 7, waiting: 1, pricedCoverage: 94 }),
      run: Object.freeze({ id: 'r314', name: 'Suspension replay recovery', health: 'degraded', cost: 4.82, retryCost: 1.05, attemptsLeft: 1, blockedSuccessors: 3 }),
      requirement: Object.freeze({ id: 'R2', name: 'Recovery resumes suspended work exactly once after executor restart', required: true, grades: Object.freeze(['C', 'C']) }),
      nodes: Object.freeze([
        Object.freeze({ id: 'N14', name: 'Implement replay boundary', kind: 'builder', attempt: 1, grade: 'C', files: 8, newEvidence: 0, cost: 0.72 }),
        Object.freeze({ id: 'N15', name: 'Verify suspension replay', kind: 'verifier', attempt: 1, grade: 'C', files: null, newEvidence: 0, cost: 0.19 }),
        Object.freeze({ id: 'N17', name: 'Revise recovery path', kind: 'builder', attempt: 2, grade: 'C', files: 3, newEvidence: 0, cost: 1.05 }),
        Object.freeze({ id: 'N18', name: 'Recheck replay proof', kind: 'verifier', attempt: 2, grade: 'C', files: null, newEvidence: 0, cost: 0.21 }),
        Object.freeze({ id: 'N24', name: 'Add incident evidence', kind: 'builder', attempt: 3, grade: null, files: 0, newEvidence: 2, cost: 0.62, proposed: true }),
      ]),
      evidence: Object.freeze({ missing: Object.freeze(['Deterministic suspension replay', 'Incident record INC-042']), changedFiles: 3, additions: 84, deletions: 21 }),
      outcome: Object.freeze({ finalGrade: 'A', merged: true, avoidedRetryCost: 1.05, learning: 'Promote restart replay fixture into the routine packet' }),
    });
    const state = { slide: 'loop', workspaceState: 'fleet', selectedByConcept: { cartography: 'N18', causal: 'verdict-a2', intervention: 'case-r314', evidence: 'R2', weave: 'recovery-verify-a2' }, modal: null };
    const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[character]);
    const stateRail = () => `<nav class="state-rail" aria-label="Operating loop state">${WORKSPACE_STATES.map((id, index) => `<button type="button" data-workspace-state="${id}" aria-pressed="${state.workspaceState === id}">${index + 1} ${id === 'cause' ? 'Cause / Evidence' : id[0].toUpperCase() + id.slice(1)}</button>`).join('')}</nav>`;
    const renderLoop = () => `<section class="slide" data-slide="loop"><h1>One operating loop, five interface models</h1><p>Notice → position → decide or explain → verify → act → learn → compare.</p></section>`;
    const renderPlaceholderConcept = (id, title) => `<section class="slide" data-slide="${id}"><header><h1>${title}</h1>${stateRail()}</header><div class="concept-workspace" data-concept="${id}"></div></section>`;
    const renderComparison = () => `<section class="slide" data-slide="comparison"><h1>Compare architectural trade-offs</h1></section>`;
    function announce(message) { document.querySelector('[data-live-region]').textContent = message; }
    function goToSlide(id) { if (!SLIDES.includes(id)) return; state.slide = id; location.hash = id; render(); announce(`Slide: ${id}`); }
    function setWorkspaceState(id) { if (!WORKSPACE_STATES.includes(id)) return; state.workspaceState = id; render(); announce(`Workspace state: ${id}`); }
    function selectObject(concept, id) { state.selectedByConcept[concept] = id; render(); announce(`Selected ${id}`); }
    function render() {
      const markup = [renderLoop(), renderPlaceholderConcept('cartography', 'Operational Cartography'), renderPlaceholderConcept('causal', 'Causal Spine'), renderPlaceholderConcept('intervention', 'Intervention Desk'), renderPlaceholderConcept('evidence', 'Evidence Workbench'), renderPlaceholderConcept('weave', 'Mission Weave'), renderComparison()].join('');
      document.querySelector('#slides').innerHTML = markup;
      document.querySelectorAll('[data-slide]').forEach((slide) => { slide.hidden = slide.dataset.slide !== state.slide; });
      document.querySelector('#slide-position').textContent = `${SLIDES.indexOf(state.slide) + 1} / ${SLIDES.length}`;
      document.querySelectorAll('[data-workspace-state]').forEach((button) => button.addEventListener('click', () => setWorkspaceState(button.dataset.workspaceState)));
    }
    document.querySelector('[data-action="previous-slide"]').addEventListener('click', () => goToSlide(SLIDES[Math.max(0, SLIDES.indexOf(state.slide) - 1)]));
    document.querySelector('[data-action="next-slide"]').addEventListener('click', () => goToSlide(SLIDES[Math.min(SLIDES.length - 1, SLIDES.indexOf(state.slide) + 1)]));
    addEventListener('keydown', (event) => { if (event.key === 'ArrowLeft') goToSlide(SLIDES[Math.max(0, SLIDES.indexOf(state.slide) - 1)]); if (event.key === 'ArrowRight') goToSlide(SLIDES[Math.min(SLIDES.length - 1, SLIDES.indexOf(state.slide) + 1)]); if (/^[1-5]$/.test(event.key)) setWorkspaceState(WORKSPACE_STATES[Number(event.key) - 1]); });
    state.slide = SLIDES.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'loop';
    window.taskWorldPresentation = Object.freeze({ getState: () => structuredClone(state), goToSlide, setWorkspaceState, selectObject });
    try { render(); } catch (error) { document.body.innerHTML = `<main role="alert"><h1>Presentation could not start</h1><pre>${escapeHtml(error instanceof Error ? error.message : error)}</pre></main>`; }
  </script>
</body>
</html>
```

- [ ] **Step 4: Run the shell tests**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts` from `ui/`.

Expected: PASS for direct-file opening, seven slides, hash restoration, arrow navigation, and number-key workspace state.

- [ ] **Step 5: Review the shell at three widths**

Open the file directly and inspect at `1440×900`, `1024×768`, and `390×844`. Confirm the deck controls remain visible, there is no page-level horizontal scroll, and the state rail remains operable.

---

### Task 2: Operational Cartography Workspace

**Files:**
- Modify: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
- Modify: `ui/tests/e2e/jtbd-presentation.spec.ts`

**Interfaces:**
- Consumes: `SCENARIO`, `state.workspaceState`, `state.selectedByConcept.cartography`, `selectObject()`.
- Produces: `renderCartography(scenario, workspaceState, selectedId)` and DOM markers `[data-node-id]`, `[data-requirement-id]`, `[data-node-stat-row]`, `.fleet-ribbon`, `.graph-route`, and `.capability--proposed`.

- [ ] **Step 1: Add the failing cartography test**

Append this test:

```ts
test('cartography joins topology, readable requirements, grades, and vertical node statistics', async ({ page }) => {
  await openPresentation(page, '#cartography');
  await page.keyboard.press('3');

  await expect(page.getByText('Recovery resumes suspended work exactly once after executor restart')).toBeVisible();
  await expect(page.getByText('R2', { exact: true })).toBeVisible();
  await expect(page.locator('[data-node-stat-row]')).toHaveCount(5);
  await expect(page.locator('[data-node-stat-row]').first()).toContainText('Implement replay boundary');
  await expect(page.locator('[data-node-stat-row]').first()).toContainText('C');
  await expect(page.locator('.fleet-ribbon')).toHaveAttribute('aria-label', /2 need attention, 7 progressing, 1 waiting/);

  await page.locator('.graph-node[data-node-id="N14"]').click();
  await expect(page.locator('[data-selected-object]')).toContainText('Implement replay boundary');
  await expect(page.locator('.capability--proposed')).toContainText('Proposed capability');
});
```

- [ ] **Step 2: Run the cartography test and confirm it fails**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "cartography joins"` from `ui/`.

Expected: FAIL because the cartography workspace is empty.

- [ ] **Step 3: Implement the cartography renderer**

Replace the temporary cartography shell with `renderCartography()`. The renderer must produce:

```js
function renderNodeRows(nodes) {
  return `<div class="node-stat-table" role="table" aria-label="Nodes touching selected requirement">
    <div class="node-stat-head" role="row"><span role="columnheader">Node / attempt</span><span role="columnheader">Grade</span><span role="columnheader">Files</span><span role="columnheader">New evidence</span><span role="columnheader">Cost</span></div>
    ${nodes.map((node) => `<button type="button" class="node-stat-row" role="row" data-node-stat-row data-node-id="${node.id}">
      <span><strong>${escapeHtml(node.name)}</strong><small>${node.id} · ${node.kind} · attempt ${node.attempt}</small></span>
      <span class="grade grade--${(node.grade || 'pending').toLowerCase()}">${node.grade || '—'}</span>
      <span>${node.files ?? '—'}</span><span>${node.newEvidence > 0 ? `+${node.newEvidence}` : node.newEvidence}</span><span>$${node.cost.toFixed(2)}</span>
    </button>`).join('')}
  </div>`;
}

function renderCartography(scenario, workspaceState, selectedId) {
  const selected = scenario.nodes.find((node) => node.id === selectedId) || scenario.nodes[3];
  return `<section class="concept-workspace cartography" data-concept="cartography" data-state="${workspaceState}">
    <aside class="fleet-rail"><div class="fleet-ribbon" role="img" aria-label="${scenario.fleet.attention} need attention, ${scenario.fleet.progressing} progressing, ${scenario.fleet.waiting} waiting"><i style="--share:${scenario.fleet.attention}">2</i><i style="--share:${scenario.fleet.progressing}">7</i><i style="--share:${scenario.fleet.waiting}">1</i></div><ol><li><b>${scenario.run.id} ${scenario.run.name}</b><span>same failure ×2 · ${scenario.run.blockedSuccessors} blocked</span></li></ol></aside>
    <div class="graph-map" aria-label="Issue neighborhood for ${escapeHtml(scenario.requirement.name)}">
      <svg class="graph-routes" viewBox="0 0 800 500" aria-hidden="true"><path class="graph-route route--verified" d="M90 160 C190 160 210 230 315 230"/><path class="graph-route route--blocking" d="M315 230 C470 160 520 150 650 160"/><path class="graph-route route--blocking" d="M315 230 C470 280 520 330 650 340"/><path class="graph-route route--proposed" d="M315 230 C330 330 360 390 430 420"/></svg>
      ${scenario.nodes.map((node, index) => `<button type="button" class="graph-node ${node.id === selected.id ? 'is-selected' : ''}" data-node-id="${node.id}" style="--x:${[8,34,66,68,36][index]}%;--y:${[25,38,20,58,75][index]}%"><small>${node.id} · ${node.kind}</small><strong>${escapeHtml(node.name)}</strong><span class="grade grade--${(node.grade || 'pending').toLowerCase()}">${node.grade || '—'}</span></button>`).join('')}
    </div>
    <aside class="selection-inspector" data-selected-object><small>Selected node · ${selected.id}</small><h2>${escapeHtml(selected.name)}</h2><p data-requirement-id="${scenario.requirement.id}"><b>${scenario.requirement.id} · required</b> ${escapeHtml(scenario.requirement.name)}</p>${renderNodeRows(scenario.nodes)}<p class="capability capability--proposed">Proposed capability · bind replay fixture and incident evidence</p></aside>
  </section>`;
}
```

Add CSS that gives `.concept-workspace.cartography` a three-column layout, makes `.graph-map` the largest region, positions `.graph-node` from `--x/--y`, uses semantic route colors, gives `.node-stat-table` a vertically scrollable body with a sticky `.node-stat-head`, and stacks fleet/map/inspector at narrow widths. Add one delegated click handler for `[data-concept="cartography"] [data-node-id]` that calls `selectObject('cartography', id)`.

- [ ] **Step 4: Run the cartography test**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "cartography joins"` from `ui/`.

Expected: PASS.

- [ ] **Step 5: Review all five cartography states**

Open `#cartography`, use keys `1` through `5`, and verify the same workspace re-proportions and updates its emphasis for fleet, position, cause/evidence, action, and outcome without replacing human-readable labels or grades.

---

### Task 3: Causal Spine Workspace

**Files:**
- Modify: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
- Modify: `ui/tests/e2e/jtbd-presentation.spec.ts`

**Interfaces:**
- Consumes: shared scenario and workspace controller.
- Produces: `renderCausalSpine(scenario, workspaceState, selectedId)`, `[data-event-id]`, `.causal-track`, `.event-branch`, and `[data-causal-detail]`.

- [ ] **Step 1: Add the failing causal-spine test**

```ts
test('causal spine preserves parallel branches and opens evidence in place', async ({ page }) => {
  await openPresentation(page, '#causal');
  await page.keyboard.press('3');
  await expect(page.locator('.causal-track')).toHaveCount(3);
  await expect(page.getByText('Retry did not add evidence')).toBeVisible();
  await page.locator('[data-event-id="verdict-a1"]').click();
  await expect(page.locator('[data-causal-detail]')).toContainText('Attempt 1 verifier verdict');
  await expect(page.locator('[data-causal-detail]')).toContainText('C');
});
```

- [ ] **Step 2: Run the causal test and confirm it fails**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "causal spine"` from `ui/`.

Expected: FAIL because no causal tracks exist.

- [ ] **Step 3: Implement the causal renderer**

Add an event list derived from shared nodes plus retry, decision, and outcome events. Render three tracks named `Recovery work`, `Verification`, and `Operator / gate`; place events by causal sequence rather than absolute clock width. Use branch connectors for builder-to-verifier and verdict-to-retry relationships. The selected event detail must show its human label, node/attempt metadata, grade, evidence delta, consequence, and source record links. Fleet state uses one compact pulse strip per run; action state inserts the proposed directive into the operator track; outcome state extends the same tracks through final grade `A` and merge.

Use this event contract:

```js
const causalEvents = Object.freeze([
  { id: 'build-a1', track: 'work', label: 'Implement replay boundary', nodeId: 'N14', sequence: 1 },
  { id: 'verdict-a1', track: 'verify', label: 'Attempt 1 verifier verdict', nodeId: 'N15', sequence: 2, grade: 'C' },
  { id: 'retry', track: 'operator', label: 'Retry authorized', sequence: 3 },
  { id: 'build-a2', track: 'work', label: 'Revise recovery path', nodeId: 'N17', sequence: 4 },
  { id: 'verdict-a2', track: 'verify', label: 'Attempt 2 verifier verdict', nodeId: 'N18', sequence: 5, grade: 'C' },
  { id: 'directive', track: 'operator', label: 'Bind replay and incident evidence', nodeId: 'N24', sequence: 6, proposed: true },
  { id: 'final-a', track: 'verify', label: 'Recovery invariant verified', sequence: 7, grade: 'A' },
  { id: 'merge', track: 'operator', label: 'Run merged', sequence: 8 },
]);
```

Add delegated event selection through `selectObject('causal', eventId)`.

- [ ] **Step 4: Run the causal test**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "causal spine"` from `ui/`.

Expected: PASS.

---

### Task 4: Intervention Desk Workspace

**Files:**
- Modify: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
- Modify: `ui/tests/e2e/jtbd-presentation.spec.ts`

**Interfaces:**
- Produces: `renderInterventionDesk(scenario, workspaceState, selectedId)`, `[data-case-id]`, `.case-queue`, `.decision-packet`, and `[data-action="review-intervention"]`.

- [ ] **Step 1: Add the failing intervention test**

```ts
test('intervention desk ranks exceptions and keeps consequence beside action', async ({ page }) => {
  await openPresentation(page, '#intervention');
  await expect(page.locator('[data-case-id="case-r314"]')).toContainText('3 successors blocked');
  await page.locator('[data-case-id="case-r314"]').click();
  await expect(page.locator('.decision-packet')).toContainText('Another unchanged retry');
  await expect(page.locator('.decision-packet')).toContainText('$1.05');
  await expect(page.locator('.decision-packet')).toContainText('1 attempt remains');
  await expect(page.getByRole('button', { name: 'Review proposed intervention' })).toBeVisible();
});
```

- [ ] **Step 2: Run the intervention test and confirm it fails**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "intervention desk"` from `ui/`.

Expected: FAIL because the case queue and packet are absent.

- [ ] **Step 3: Implement the intervention renderer**

Render a proportional fleet ribbon above a vertically ranked case queue. Give every case a compact urgency line, age, blocked scope, reversibility marker, and confidence. The selected `r314` packet must render in this order: trigger, evidence, consequence, options, authority, validation, action. Use shape and aligned measures rather than individual cards. Healthy runs appear only as the progressing portion of the fleet ribbon.

Define the primary case from shared facts:

```js
const interventionCase = Object.freeze({
  id: 'case-r314', runId: SCENARIO.run.id, title: 'Repeated recovery verdict',
  trigger: `${SCENARIO.requirement.name} graded C twice`,
  consequence: `${SCENARIO.run.blockedSuccessors} successors blocked; another unchanged retry costs $${SCENARIO.run.retryCost.toFixed(2)}`,
  authority: 'Repository operator approval required', reversible: true,
  confidence: 'High · two matching verdicts and zero evidence delta',
});
```

Selection calls `selectObject('intervention', caseId)`. The action button calls `openDecisionModal('intervention', '[data-action="review-intervention"]')`; Task 7 supplies that function and the shared modal shell.

- [ ] **Step 4: Run the intervention test**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "intervention desk"` from `ui/`.

Expected: PASS.

---

### Task 5: Evidence Workbench Workspace

**Files:**
- Modify: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
- Modify: `ui/tests/e2e/jtbd-presentation.spec.ts`

**Interfaces:**
- Produces: `renderEvidenceWorkbench(scenario, workspaceState, selectedId)`, `[data-claim-id]`, `.evidence-matrix`, `.packet-delta`, and `.graph-locator`.

- [ ] **Step 1: Add the failing evidence-workbench test**

```ts
test('evidence workbench uses node rows and fixed statistic columns', async ({ page }) => {
  await openPresentation(page, '#evidence');
  await page.keyboard.press('3');
  const matrix = page.locator('.evidence-matrix');
  await expect(matrix.getByRole('columnheader')).toHaveCount(5);
  await expect(matrix.locator('[data-node-stat-row]')).toHaveCount(5);
  await expect(matrix).toContainText('Recovery resumes suspended work exactly once after executor restart');
  await expect(page.locator('.packet-delta')).toContainText('Deterministic suspension replay');
  await expect(page.locator('.packet-delta')).toContainText('Incident record INC-042');
  await expect(page.locator('.graph-locator')).toHaveAttribute('aria-label', /3 blocked successors/);
});
```

- [ ] **Step 2: Run the evidence test and confirm it fails**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "evidence workbench"` from `ui/`.

Expected: FAIL because the matrix and locator are absent.

- [ ] **Step 3: Implement the evidence renderer**

Render requirements as a narrow selectable index, the selected claim and node lineage as the dominant matrix, packet and file deltas as aligned evidence bands, and topology as a compact locator. Reuse `renderNodeRows(SCENARIO.nodes)` so growth direction and values cannot diverge from Cartography. The matrix column labels are exactly `Node / attempt`, `Grade`, `Files`, `New evidence`, and `Cost`. Full prompt, transcript, and diff links expose metadata in the main view but open detail in an in-place evidence layer.

Use the shared requirement text as the heading and the generated ID as secondary metadata:

```js
function renderEvidenceWorkbench(scenario, workspaceState, selectedId) {
  return `<section class="concept-workspace evidence-workbench" data-concept="evidence" data-state="${workspaceState}">
    <nav class="claim-index"><button type="button" data-claim-id="${scenario.requirement.id}" aria-pressed="true"><b>${escapeHtml(scenario.requirement.name)}</b><small>${scenario.requirement.id} · required · C → C</small></button></nav>
    <main class="evidence-matrix"><h2>${escapeHtml(scenario.requirement.name)}</h2><small>${scenario.requirement.id} · node lineage</small>${renderNodeRows(scenario.nodes)}<div class="packet-delta"><b>Missing in both attempts</b>${scenario.evidence.missing.map((item) => `<span>${escapeHtml(item)}</span>`).join('')}<b>Changed implementation</b><span>${scenario.evidence.changedFiles} files · +${scenario.evidence.additions}/−${scenario.evidence.deletions}</span></div></main>
    <aside class="graph-locator" aria-label="Selected requirement with ${scenario.run.blockedSuccessors} blocked successors"><strong>Constraint locator</strong><svg viewBox="0 0 220 150" aria-hidden="true"><path d="M20 75 L95 75 L175 25 M95 75 L175 75 M95 75 L175 125"/><circle cx="95" cy="75" r="10"/></svg></aside>
  </section>`;
}
```

- [ ] **Step 4: Run the evidence test**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "evidence workbench"` from `ui/`.

Expected: PASS.

---

### Task 6: Mission Weave Workspace

**Files:**
- Modify: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
- Modify: `ui/tests/e2e/jtbd-presentation.spec.ts`

**Interfaces:**
- Produces: `renderMissionWeave(scenario, workspaceState, selectedId)`, `[data-weave-segment]`, `.weave-lane`, `.rework-loop`, and `.final-invariant`.

- [ ] **Step 1: Add the failing weave test**

```ts
test('mission weave shows dynamic branches, rework, and final convergence', async ({ page }) => {
  await openPresentation(page, '#weave');
  await page.keyboard.press('2');
  await expect(page.locator('.weave-lane')).toHaveCount(5);
  await expect(page.locator('.rework-loop')).toBeVisible();
  await expect(page.locator('.final-invariant')).toContainText('Recovery invariants');
  await page.keyboard.press('4');
  await expect(page.locator('[data-weave-segment="corrective-evidence"]')).toContainText('Proposed capability');
  await page.keyboard.press('5');
  await expect(page.locator('.final-invariant')).toContainText('A · merged');
});
```

- [ ] **Step 2: Run the weave test and confirm it fails**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "mission weave"` from `ui/`.

Expected: FAIL because weave lanes are absent.

- [ ] **Step 3: Implement the weave renderer**

Create five horizontal lanes named `Plan`, `Build`, `Verify`, `Gate`, and `Settle`. Render workstreams vertically within those lanes so additional stages extend downward rather than widening the page. Use SVG paths for branch joins and the rework loop from verifier `C` back to the second builder. In action state, insert a dashed amber corrective segment with `data-weave-segment="corrective-evidence"`; in outcome state, resolve that segment through grade `A`, the final invariant, and merge.

Use this segment model:

```js
const weaveSegments = Object.freeze([
  { id: 'plan-recovery', lane: 'plan', label: 'Recovery region planned', row: 1, status: 'verified' },
  { id: 'build-a1', lane: 'build', label: 'Implement replay boundary', row: 1, status: 'verified' },
  { id: 'verify-a1', lane: 'verify', label: 'Suspension replay · C', row: 1, status: 'blocking' },
  { id: 'build-a2', lane: 'build', label: 'Revise recovery path', row: 2, status: 'verified' },
  { id: 'recovery-verify-a2', lane: 'verify', label: 'Replay proof · C', row: 2, status: 'blocking' },
  { id: 'corrective-evidence', lane: 'build', label: 'Bind replay + incident evidence', row: 3, status: 'proposed' },
  { id: 'verify-correction', lane: 'verify', label: 'Recovery invariant · A', row: 3, status: 'verified' },
  { id: 'final-gate', lane: 'gate', label: 'Recovery invariants', row: 3, status: 'verified' },
  { id: 'merge', lane: 'settle', label: 'Merged', row: 3, status: 'verified' },
]);
```

Add a compact miniature weave per fleet row and delegated segment selection through `selectObject('weave', segmentId)`.

- [ ] **Step 4: Run the weave test**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "mission weave"` from `ui/`.

Expected: PASS.

---

### Task 7: Shared Decision Modal, Comparison Slide, Responsive and Accessibility Closure

**Files:**
- Modify: `outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`
- Modify: `ui/tests/e2e/jtbd-presentation.spec.ts`

**Interfaces:**
- Consumes all concept renderers and shared state.
- Produces: `renderDecisionModal()`, `openDecisionModal(concept, trigger)`, `closeDecisionModal()`, focus restoration, `.comparison-matrix`, and final responsive behavior.

- [ ] **Step 1: Add the failing closure tests**

Append these tests:

```ts
test('decision confirmation is modal, labeled proposed, and restores focus', async ({ page }) => {
  await openPresentation(page, '#intervention');
  const trigger = page.getByRole('button', { name: 'Review proposed intervention' });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: 'Review corrective intervention' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Proposed capability');
  await expect(dialog).toContainText('3 successors');
  await expect(dialog).toContainText('$0.62');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test('comparison uses rubric language without fabricated observed scores', async ({ page }) => {
  await openPresentation(page, '#comparison');
  await expect(page.locator('.comparison-matrix')).toContainText('Causal comprehension');
  await expect(page.locator('.comparison-matrix')).toContainText('Decision readiness');
  await expect(page.locator('.comparison-matrix')).toContainText('Expected strength');
  await expect(page.getByText(/user-tested score/i)).toHaveCount(0);
});

test('artifact makes no external requests and avoids horizontal overflow', async ({ page }) => {
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    if (!request.url().startsWith('file:')) externalRequests.push(request.url());
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await openPresentation(page, '#cartography');
  await page.keyboard.press('3');
  expect(externalRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expect(page.locator('.metric-card')).toHaveCount(0);
});

test('every concept exposes all five operating-loop states in place', async ({ page }) => {
  const concepts = ['cartography', 'causal', 'intervention', 'evidence', 'weave'];
  const states = ['fleet', 'position', 'cause', 'action', 'outcome'];
  for (const concept of concepts) {
    await openPresentation(page, `#${concept}`);
    for (const [index, state] of states.entries()) {
      await page.keyboard.press(String(index + 1));
      await expect(page.locator(`[data-concept="${concept}"][data-state="${state}"]`)).toBeVisible();
      await expect(page.locator(`[data-workspace-state="${state}"]`)).toHaveAttribute('aria-pressed', 'true');
    }
  }
});
```

- [ ] **Step 2: Run the closure tests and confirm they fail**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts -g "decision confirmation|comparison uses|artifact makes|every concept exposes"` from `ui/`.

Expected: FAIL because the modal and comparison matrix are incomplete and narrow-layout closure has not been verified.

- [ ] **Step 3: Implement the shared modal**

Render the modal only when `state.modal` is non-null. Store a stable trigger selector rather than a DOM reference because `render()` replaces the slide markup. Focus the first modal button after render, trap Tab within the dialog, close on Escape, restore focus by querying the newly rendered trigger, and lock body scrolling while open.

Use these modal state functions:

```js
function openDecisionModal(concept, triggerSelector) {
  state.modal = { kind: 'intervention', concept, triggerSelector };
  document.body.classList.add('modal-open');
  render();
  document.querySelector('[role="dialog"] button')?.focus();
}

function closeDecisionModal() {
  const triggerSelector = state.modal?.triggerSelector;
  state.modal = null;
  document.body.classList.remove('modal-open');
  render();
  if (triggerSelector) document.querySelector(triggerSelector)?.focus();
}
```

Trap Tab by collecting enabled buttons within `[role="dialog"]` and wrapping focus from last to first and first to last. The dialog content is:

```html
<div class="modal-backdrop" data-modal-backdrop>
  <section role="dialog" aria-modal="true" aria-labelledby="decision-title" class="decision-modal">
    <small class="capability capability--proposed">Proposed capability</small>
    <h2 id="decision-title">Review corrective intervention</h2>
    <p>Bind the deterministic suspension replay and incident record INC-042 to one corrective builder node.</p>
    <dl><dt>Scope</dt><dd>Recovery region · 3 blocked successors</dd><dt>Budget</dt><dd>$0.62 correction cap</dd><dt>Authority</dt><dd>Repository operator approval</dd><dt>Reversibility</dt><dd>Withdraw before corrective lease starts</dd><dt>Validation</dt><dd>Patch valid; final-invariant path preserved</dd></dl>
    <footer><button type="button" data-action="cancel-decision">Cancel</button><button type="button" data-action="confirm-decision">Authorize proposed correction</button></footer>
  </section>
</div>
```

Confirmation moves the workspace to `outcome` and shows an auditable accepted-command/result marker; it does not imply a backend call occurred.

- [ ] **Step 4: Implement the comparison slide**

Render one compact matrix with concepts as rows and the ten rubric criteria grouped into `Orient`, `Explain`, `Act`, and `Sustain`. Cells contain only `Expected strength`, `Trade-off`, or `Risk`; adjacent text names the specific reason. Add a combinations strip naming three hypotheses: `Cartography + Evidence Workbench`, `Intervention Desk + Causal Spine`, and `Mission Weave as fleet/run synopsis`. Do not display numeric scores.

- [ ] **Step 5: Close responsive and accessibility behavior**

At widths below `1100px`, re-proportion concept layouts to two columns and place the persistent synopsis above the focus surface. Below `720px`, stack context and focus, keep the state rail horizontally operable, keep fixed table columns visible by shortening labels, and allow only vertical scrolling inside growing sets. Add `.sr-only`, non-color status labels, minimum `36px` touch targets, and `aria-current="page"` on the active slide indicator.

- [ ] **Step 6: Run the complete presentation test file**

Run: `npm run test:e2e -- jtbd-presentation.spec.ts` from `ui/`.

Expected: all tests PASS in Chromium with zero external requests.

- [ ] **Step 7: Run frontend checks**

Run from `ui/`:

```bash
npm run typecheck
npm run lint
```

Expected: both commands exit `0` with no TypeScript or ESLint errors.

- [ ] **Step 8: Perform full visual review**

Open every slide at `1440×900`, `1024×768`, and `390×844`. For each concept, activate all five workspace states and verify:

- no clipped text or page-level horizontal overflow;
- human-readable names precede generated IDs;
- grades remain visible;
- growing sets expand vertically or aggregate semantically;
- no low-information metric cards remain;
- every chart has an obvious domain meaning;
- the exception reading order is constraint, evidence, consequence, action;
- capability labels distinguish current, derivable, and proposed behavior;
- selection persists while changing state;
- the modal traps focus and restores it after close.

- [ ] **Step 9: Run repository diff checks**

Run from the repository root:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` exits `0`; status shows only the intended presentation/test/spec/plan files plus pre-existing unrelated changes. Do not stage or modify unrelated files.
