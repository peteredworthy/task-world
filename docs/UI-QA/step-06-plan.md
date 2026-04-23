# Step Plan: CI Integration & Documentation (M4)

## Purpose

Wire the BDD test suite into CI so tests run automatically on every push. Update documentation with complete instructions for running, extending, and debugging the test suite. Verify the < 3-minute CI time budget is met.

## Prerequisites

- Steps 01-05 complete: all feature files, step definitions, fixtures, and page objects are in place and passing locally.

## Functional Contract

### Inputs

- All BDD test artifacts from Steps 01-05.
- Existing CI configuration (GitHub Actions or equivalent).
- Existing `ui/tests/README.md` from Step 01 (initial documentation).

### Outputs

- CI configuration updated (e.g., `.github/workflows/test.yml` or equivalent) to:
  - Install Playwright browsers
  - Run `npm run test:bdd` with `--workers=4`
  - Report results and upload trace artifacts on failure
  - Run in parallel with existing Vitest and visual regression suites
- BDD suite verified to complete in < 3 minutes in CI environment.
- `ui/tests/README.md` updated with:
  - How to run BDD tests locally (`npm run test:bdd`, `npm run test:bdd:ui`)
  - How to add a new workflow feature file
  - How to add a new edge-case scenario
  - Fixture patterns: factories, route handlers, FakeWS, FakeSSE
  - Debugging tips: Playwright trace viewer, headed mode, step-through
  - Page object conventions
  - Scenario Outline patterns for state transition matrices
- Coverage summary table: which pages/components have workflow-level coverage, which are missing.

### Error Cases

- CI runner lacks Playwright browsers — workflow must include `npx playwright install --with-deps` step.
- BDD suite exceeds 3-minute budget in CI — profile slow tests, optimize or increase parallelism.
- CI caching issues with Playwright browser binaries — configure cache keys correctly.

## Tasks

1. Update or create CI workflow configuration for BDD test suite.
2. Add Playwright browser install step to CI.
3. Configure trace artifact upload on test failure.
4. Run BDD suite in CI, measure execution time.
5. If time exceeds 3 minutes, profile and optimize (increase workers, split slow features, reduce unnecessary waits).
6. Update `ui/tests/README.md` with comprehensive documentation.
7. Create coverage summary table (page → feature file mapping).
8. Verify CI pipeline runs green end-to-end.

## Verification Approach

### Auto-Verify

- CI pipeline passes with BDD suite.
- BDD suite execution time < 3 minutes (measured in CI logs).
- README.md contains all required sections.

### Manual Verification

- CI run log shows all feature files executing.
- Trace artifacts available for download on failure.
- README instructions can be followed by a new contributor to run and extend tests.

## Context & References

- Plan: `docs/UI-QA/plan.md` — M4 specification
- Architecture: `docs/UI-QA/architecture.md` — CI integration section, config patterns
- Clarification Q5: CI budget < 3 minutes for BDD suite (stricter target)
- Intent traces: [I-02], [I-19], [I-20], [I-21], [I-26], [I-33], [I-34]
