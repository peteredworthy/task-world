# Dynamic Graph Mockup Process Spec HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Present the approved dynamic-graph mockup process spec as an offline HTML review surface optimized for rapid ingestion and selectable detail.

**Architecture:** Create one self-contained HTML document that reorganizes the Markdown spec into an executive summary, process map, scenario, concept states, evaluation gates, and stop rules. A global depth selector controls summary, standard, and full content; local disclosures, topic navigation, and persisted browser state allow readers to choose detail without losing orientation.

**Tech Stack:** Semantic HTML, inline CSS, minimal vanilla JavaScript, `localStorage`, `file://` operation.

## Global Constraints

- The HTML must open directly through `file://` with no build step or network dependency.
- Preserve the approved meaning of `docs/superpowers/specs/2026-07-26-dynamic-graph-mockup-process-design.md`.
- Make the recommendation and stop conditions understandable in under one minute.
- Support `summary`, `standard`, and `full` global detail levels plus local disclosures.
- Persist the selected detail level in `localStorage`.
- Preserve keyboard navigation, visible focus, semantic controls, and narrow-screen readability.
- Do not recreate catalogs, validators, generated research IDs, or feedback infrastructure.
- Do not run git commands from the main working tree.

---

### Task 1: Build And Open The Interactive Spec

**Files:**
- Create: `research/ui-foundation/reviews/dynamic-graph-mockup-process-spec.html`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-26-dynamic-graph-mockup-process-design.md`
- Produces: one standalone HTML document with `[data-depth-control]`, `[data-detail]`, `[data-topic]`, and `[data-section]` hooks.

- [ ] **Step 1: Run the acceptance check before implementation**

Run:

```bash
uv run python -c 'from pathlib import Path; p=Path("research/ui-foundation/reviews/dynamic-graph-mockup-process-spec.html"); assert p.exists()'
```

Expected: FAIL with `AssertionError` because the HTML does not exist.

- [ ] **Step 2: Create the self-contained HTML**

The document must contain:

- a masthead stating the recommendation and its purpose;
- a “60-second read” with the structural diagnosis, replacement principle, six process stages, seven concept states, three deliverables, and hard stop rules;
- a sticky orientation rail linking to overview, process, scenario, concept deck, evaluation, and stop conditions;
- global `Summary`, `Standard`, and `Full` controls using `aria-pressed`;
- topic controls for `All`, `Process`, `Product`, `Evidence`, and `Evaluation`;
- `data-detail="standard"` and `data-detail="full"` blocks hidden at shallower levels;
- local `<details>` elements for citations, rationale, error states, and exact verification steps;
- a seven-state journey strip with concise operator questions;
- current, derived, and proposed capability markers with plain-language definitions;
- persistent detail state under `localStorage` key `dynamic-graph-mockup-process-spec:depth:v1`;
- URL hash navigation and active-section highlighting;
- responsive layout and print styles;
- no external fonts, images, scripts, or stylesheets.

The script must set `document.documentElement.dataset.depth`, update all depth-control `aria-pressed` values, store the selected depth, filter topic cards without hiding structural section headings, and update the active navigation item through `IntersectionObserver`.

- [ ] **Step 3: Run structural verification**

Run:

```bash
uv run python -c 'from pathlib import Path; import re; p=Path("research/ui-foundation/reviews/dynamic-graph-mockup-process-spec.html"); t=p.read_text(); assert t.startswith("<!doctype html>"); assert "dynamic-graph-mockup-process-spec:depth:v1" in t; assert len(re.findall(r"data-depth-control=", t)) == 3; assert all(f"data-section=\"{s}\"" in t for s in ("overview", "process", "scenario", "deck", "evaluation", "stops")); assert "https://" not in t and "http://" not in t; print("HTML structure verified")'
```

Expected: `HTML structure verified`.

- [ ] **Step 4: Open and inspect the artifact**

Run:

```bash
open research/ui-foundation/reviews/dynamic-graph-mockup-process-spec.html
```

Expected: the default browser opens the HTML. Confirm that depth controls, topic filters, disclosures, navigation, and narrow-screen layout work without network access.
