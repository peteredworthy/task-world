# Graph Node Visibility Workspace Implementation Plan

> **For Peter:** Use `superpowers:executing-plans` to implement this plan task by task.

**Goal:** Create one browser-reviewed prototype that demonstrates the approved node information hierarchy, layered branching graph grammar, attached preview, stable inspector, and separate destination.

**Architecture:** Build a single self-contained HTML artifact from one explicit graph fixture. Render node cards as measured HTML elements in a layered CSS grid, route SVG edges between explicit source and target ports after layout, and keep the inspector outside the horizontally scrolling graph canvas. Implement only enough interaction to judge the visibility contract: hover/focus preview, persistent selection, local disclosure, and a contextual separate destination.

**Tech Stack:** HTML, CSS, vanilla JavaScript, inline SVG, browser-native `<details>` and dialog semantics.

---

## Scope Guardrails

- Create exactly one prototype artifact.
- Do not recreate the rejected operator-loop screens or navigation model.
- Do not add a system-wide node-field catalog, graph engine, component library, or production persistence.
- Do not add a written review report as a substitute for browser review.
- Use a realistic fixture with parallel branches, joins, dynamic expansion, and a retired path.
- Treat visible hierarchy, edge legibility, preview attachment, and layout stability as blocking criteria.
- Stop after the first browser-reviewable implementation. Do not polish past unresolved visual feedback.
- Do not commit the prototype until it has passed human visual review.

## Task 1: Build the Browser-Reviewable Workspace

**Files:**
- Create: `research/ui-foundation/mockups/graph-node-visibility-workspace.html`

### Step 1: Establish the failing artifact check

Run:

```bash
test -f research/ui-foundation/mockups/graph-node-visibility-workspace.html
```

Expected: FAIL because the prototype does not exist.

### Step 2: Create the one-file shell and explicit fixture

Create a self-contained HTML document with:

- A restrained workspace header identifying this as a node-visibility prototype.
- A two-column workspace body: horizontal graph scroller on the left, stable inspector on the right.
- A layered graph stage containing an SVG edge layer and HTML node layer.
- One explicit fixture with approximately 10-12 nodes spanning the approved
  planner fan-out, two parallel worker branches, verifier failure, retired or
  superseded path, human gate, dynamically added corrective branch, multi-input
  join, and final check.
- Node records with only prototype-level fields:

```js
{
  id,
  title,
  kind,
  archetype,
  rank,
  lane,
  alwaysVisible,
  preview,
  inspector,
  details,
  destination
}
```

- Edge records with explicit endpoints:

```js
{ id, source, target, state }
```

Use the fixture as the single source of rendered node and inspector content. Do not duplicate node data in hand-written markup.

### Step 3: Render Class 1 information with clear hierarchy

Render each node as a focusable button-like card placed by `rank` and `lane` in a CSS grid. Let the HTML content determine the measured card height rather than assigning per-node absolute coordinates.

Each node must show only:

- identity,
- kind,
- no more than three operational signals.

Differentiate the four operational archetypes without relying on color alone:

- Active: active marker plus current progress or phase.
- Waiting/Blocked: pause marker plus blocker or dependency.
- Failed/Attention: alert marker plus concise failure state.
- Settled: completion marker plus final outcome.

Keep typography and spacing strong enough that identity is read before metadata. Retired nodes and edges remain legible but visually recede.

### Step 4: Route explicit graph edges after layout

After the browser lays out the nodes:

- Measure every node element.
- Place a visible source port at the right edge and target port at the left edge.
- Draw monotonic left-to-right SVG paths between those ports.
- Use orthogonal or gently rounded elbow paths that preserve branching and joining structure.
- Recalculate paths with `ResizeObserver` and window resize.
- Ensure edge states are distinguishable and retired edges recede.

Do not use a single straight-line chain. The fixture must visibly communicate branching, convergence, and expansion at the initial viewport.

### Step 5: Implement attached hover and keyboard preview

On pointer hover or keyboard focus:

- Show one compact preview attached to the corresponding node by a visible stem.
- Show only Class 2 summary information needed before selection.
- Prefer placement above the node, then below.
- Clamp the preview inside the graph stage.
- Reject placements that overlap another node or an edge segment.
- If neither candidate is clear, suppress the preview rather than obscuring graph structure.
- Hide the preview on pointer leave or blur.
- Close the preview immediately when a node is selected.
- Suppress all hover and focus previews while the inspector is open.

The preview must not reflow the graph, move the inspector, or create page-level scrolling.

### Step 6: Implement persistent selection and stable inspector

On click or keyboard activation:

- Persist the selected node independently of hover.
- Update a right-side inspector that is a sibling of the graph scroller.
- Keep the graph position and workspace geometry stable.
- Visually connect the selected node and inspector through consistent selection styling.
- Show Class 2 information in the inspector with identity and operational summary first.
- Put Class 3 supporting information inside locally expandable `<details>` sections.
- Allow the inspector itself to scroll vertically only when its content exceeds the viewport.

On narrow screens, preserve the graph as a horizontally scrollable canvas and present the inspector as a right-side overlay or drawer without changing the interaction hierarchy.

### Step 7: Implement the Class 4 separate destination

Add one clearly labeled inspector action such as `Open task context` that opens a full-workspace contextual panel or native dialog containing the node's Class 4 information.

The destination must:

- preserve the selected node,
- preserve run, attempt or time, graph viewport, zoom, and scroll context,
- identify the inspector action the user came from,
- provide an explicit return action,
- restore the same graph and inspector context on return.

This is a contextual destination, not a second application screen or a new navigation system.

### Step 8: Verify structural constraints

Run:

```bash
test -f research/ui-foundation/mockups/graph-node-visibility-workspace.html
```

Expected: PASS.

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

path = Path("research/ui-foundation/mockups/graph-node-visibility-workspace.html")
text = path.read_text()
required = [
    'class="graph-scroll"',
    'class="inspector"',
    '<svg',
    '<details',
    'ResizeObserver',
    'aria-label=',
]
missing = [value for value in required if value not in text]
assert not missing, f"Missing structural markers: {missing}"
print(f"verified {path}")
PY
```

Expected: PASS and print the verified path.

These checks only catch missing implementation structure. They do not establish visual quality.

### Step 9: Run the blocking browser review

Open the prototype in a browser and review it at desktop and narrow viewport widths.

Confirm visually and interactively:

- The graph reads immediately as a layered DAG with parallel branches and joins.
- Node identity dominates secondary signals.
- Every archetype is distinguishable without color alone.
- Hover/focus preview remains attached and does not obscure nodes or edges.
- Selection does not move nodes, reset graph scroll, or cause region swapping.
- Inspector remains stable beside the graph on desktop.
- Class 3 expands locally without affecting graph geometry.
- Class 4 opens separately and returns to the same selected node and graph position.
- Only the graph canvas scrolls horizontally.
- Narrow layout remains usable without collapsing into screen switching.

Expected: the artifact is ready for human visual feedback.

Stop here and present the browser-reviewable artifact. Do not claim completion, write a review report, add more artifacts, or commit until the human visual review passes.

### Step 10: Commit only after explicit visual approval

After approval, inspect the diff and stage only the approved artifact:

```bash
git diff -- research/ui-foundation/mockups/graph-node-visibility-workspace.html
git add research/ui-foundation/mockups/graph-node-visibility-workspace.html
git commit -m "feat(ui-foundation): prototype graph node visibility"
```

Expected: pre-commit checks pass and the commit contains only the approved prototype.
