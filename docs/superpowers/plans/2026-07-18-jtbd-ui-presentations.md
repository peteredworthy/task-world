# JTBD Grounding and UI Concept Presentations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a canonical JTBD documentation section and four comparable PowerPoint mockup decks for the Task World UI.

**Architecture:** A shared evidence ledger drives both the Markdown documentation and all four decks. The decks hold scenario facts constant while varying interface architecture, making clarity and complexity management directly comparable.

**Tech Stack:** Markdown, JavaScript ES modules, `@oai/artifact-tool`, LibreOffice/Poppler-based slide rendering, and the presentation skill’s QA utilities.

## Global Constraints

- Use the supplied blueprint as the primary JTBD and journey source.
- Distinguish current, derivable, and missing capabilities.
- Use one shared `r314` scenario and one evaluation rubric across all decks.
- Produce four distinct interface architectures as full-screen product mockups, not four cosmetic themes.
- Each deck contains five screens: fleet, diagnosis, evidence, steering, and recovery.
- Do not include title, architecture, strategy, or evaluation slides.
- Keep evidence, consequences, and actions together at decision points.
- Do not perform git operations from the main working tree.

---

### Task 1: Canonical JTBD documentation

**Files:**

- Create: `docs/jtbd/README.md`
- Create: `docs/jtbd/jobs.md`
- Create: `docs/jtbd/journeys.md`
- Create: `docs/jtbd/decision-information.md`
- Create: `docs/jtbd/information-architecture.md`
- Create: `docs/jtbd/evaluation-rubric.md`
- Modify: `docs/intent/README.md`

**Interfaces:**

- Consumes: the source blueprint, current intent documents, architecture documentation, and current UI/API inventory.
- Produces: stable JTBD IDs `J1`–`J8`, journeys `A`–`E`, health-state definitions, information requirements, and an evaluation rubric used verbatim by Task 2.

- [ ] **Step 1: Write the documentation section with source-status annotations and cross-links.**
- [ ] **Step 2: Check all eight jobs and five journeys are present and internally consistent.**
- [ ] **Step 3: Search for placeholders and remove ambiguous or unsupported claims.**

Verification:

```bash
rg -n '^## J[1-8]|^## Journey [A-E]' docs/jtbd
rg -n 'TBD|TODO|FIXME' docs/jtbd
```

Expected: eight job headings, five journey headings, and no placeholder matches.

### Task 2: Four high-fidelity interface mockup presentations

**Files:**

- Create: `outputs/jtbd-ui-directions/01-persistent-inspector-control-room.pptx`
- Create: `outputs/jtbd-ui-directions/02-event-spine-case-file.pptx`
- Create: `outputs/jtbd-ui-directions/03-exception-queue-intervention-desk.pptx`
- Create: `outputs/jtbd-ui-directions/04-focus-context-evidence-map.pptx`
- Create under external scratch only: builder module, previews, layout JSON, and QA records.

**Interfaces:**

- Consumes: the jobs, journeys, health model, decision-information matrix, evaluation rubric, and shared `r314` scenario from Task 1.
- Produces: four editable five-slide PowerPoint decks with consistent facts and distinct interface architectures.

- [ ] **Step 1: Initialize the artifact-tool workspace outside the repository.**
- [ ] **Step 2: Create one JavaScript module with shared product chrome, scenario facts, and four interface architectures.**
- [ ] **Step 3: Export all decks, per-slide PNGs, layout JSON, and montages.**
- [ ] **Step 4: Inspect every slide at full size and correct layout defects.**

Verification:

```bash
uv run python /ABSOLUTE/SKILL_DIR/container_tools/render_slides.py /ABSOLUTE/DECK.pptx
uv run python /ABSOLUTE/SKILL_DIR/container_tools/slides_test.py /ABSOLUTE/DECK.pptx
```

Expected: all four decks render, every deck contains five full-screen UI mockups, and all overflow tests pass.

### Task 3: Cross-deliverable consistency and handoff

**Files:**

- Verify: `docs/jtbd/*.md`
- Verify: `outputs/jtbd-ui-directions/*.pptx`

**Interfaces:**

- Consumes: Task 1 and Task 2 outputs.
- Produces: a consistency audit covering scenario values, terminology, capability-status labels, and rubric dimensions.

- [ ] **Step 1: Compare deck text snapshots for scenario drift.**
- [ ] **Step 2: Confirm each deck communicates trigger, diagnosis, evidence, consequence, action, and recovery.**
- [ ] **Step 3: Confirm the four architectures are distinguishable without relying on color.**
- [ ] **Step 4: Report final file links and concise distinctions.**

Verification:

```bash
find outputs/jtbd-ui-directions -maxdepth 1 -name '*.pptx' -size +0 -print
git diff --check -- docs/jtbd docs/intent/README.md docs/superpowers
```

Expected: four non-empty PowerPoint files and no whitespace errors.
