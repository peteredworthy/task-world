# Plan: Module Consolidation 3

## Overview

This plan assumes the repository already operates around the documented nine top-level modules and that prior consolidation work established the public-module rule. The next wave should tighten remaining boundaries, not restart the earlier 19-to-9 migration. Execution should begin with discovery that validates current reality against the docs, then proceed through small refactor milestones that keep the system runnable after each phase.

The clarification record for this tranche resolves the design posture up front: no additional human architecture choices are pending, and execution should treat all remaining unknowns as discovery gates against the live codebase.

## Milestones

### M0: Reality Audit and Gap List

**Goal:** Establish a documented baseline before any file movement.
**Entry condition:** Planning docs are approved as the source of truth, and the execution team accepts that current-reality validation must happen before any code moves.

**Deliverables:**
- Inventory remaining consolidation targets from the current docs: boundary leaks, public API gaps, runner decomposition follow-through, and database/workflow internal structure concerns.
- Confirm which risks are still relevant in the current codebase rather than inherited from older plans.
- Produce a short gap list that separates verified problems from assumptions.

**Verification:**
- Discovery notes identify each candidate move, why it exists, and what evidence will prove it still matters.
- No implementation milestone starts without an explicit dependency list.

### M1: Public Interface Audit

**Goal:** Make the top-level module contract executable.
**Entry condition:** M0 has produced a verified gap list with evidence for each candidate boundary issue and a consumer inventory for each affected module.

**Deliverables:**
- Audit all documented cross-module integrations for imports that should be routed through module `__init__.py` exports.
- Identify missing public exports and internal-only symbols that should stop leaking across modules.
- Define the order for interface cleanup so consumers can be updated in one bounded pass per module.

**Verification:**
- For each affected module, the plan names expected consumer categories: runtime code, tests, scripts, migrations, and API surface.
- Exit criteria include grep- or AST-based checks for forbidden sub-package imports.

### M2: Internal Consolidation by Domain

**Goal:** Finish one domain at a time instead of mixing unrelated restructures.
**Entry condition:** M1 has defined the canonical top-level import paths and identified which consumers must migrate for each targeted symbol.

**Implementation order:**
1. `workflow` and `state`: event, signaling, and runtime coordination boundaries.
2. `runners`: agent packages, detector/factory ownership, and execution helpers.
3. `db` and `git`: persistence/repository boundaries and any remaining shared utility leakage.
4. `api` and `config`: schema ownership, routine/profile resolution, and endpoint-facing imports.

**Deliverables:**
- One milestone plan per domain with explicit entry prerequisites.
- For each domain, a list of symbols that stay public versus symbols that move behind service/repository interfaces.

**Verification:**
- Each domain milestone ends with import smoke checks and the relevant unit/integration suites.
- Old paths are removed in the same milestone that introduces the new canonical path.

### M3: High-Risk Consumer Sweep

**Goal:** Catch callers that commonly break after structural refactors.
**Entry condition:** At least one domain milestone from M2 has landed with its canonical import paths, so consumer validation can run against real changed boundaries instead of assumptions.

**Deliverables:**
- A dedicated validation pass for tests, scripts, migrations, and run-time startup wiring.
- A checklist of “must inspect before merge” consumers for each domain milestone.
- A rule that no consolidation phase is complete until non-source callers have been checked.

**Verification:**
- The step plans include specific commands for scripts, test modules, and migration imports.
- Any caller that cannot be updated in the same phase becomes a blocker, not a deferred TODO.

### M4: Final Boundary Proof

**Goal:** Prove the consolidation is complete instead of merely plausible.
**Entry condition:** All planned domain milestones and consumer sweeps have completed without deferred import cleanups or temporary compatibility layers.

**Deliverables:**
- Final import-discipline audit across the codebase.
- Full verification matrix covering Python tests, type/lint gates, and any documented frontend/shared-type checks touched by the work.
- Completion notes mapping each intent item to the milestone that satisfies it.

**Verification:**
- `uv run` command set is defined up front and reused across milestones.
- Completion requires zero temporary shims, zero duplicate module trees, and passing automated checks.

## Implementation Notes

### Ordering Rationale

- Discovery comes first because this planning slice is intentionally not allowed to rely on source inspection during authoring; execution must start by validating the documented assumptions.
- Public-interface cleanup precedes deep file moves so the refactor can converge on stable import contracts before internal packages shift again.
- Domain-based milestones reduce blast radius and make verifier grading easier because each phase has a bounded set of affected modules.

### Expected Step Expansion

The eventual execution plan should expand each milestone into step files with:
- a short context section,
- explicit prerequisites,
- atomic tasks,
- final verification commands,
- and a stop condition when new uncertainty appears.

## Risks and Unknowns

No unresolved human-input decisions remain for this tranche. The items below match the clarification record and are execution-time discovery risks that must be audited before or during the relevant milestone.

| Risk | Why it matters | Planned mitigation |
|------|----------------|-------------------|
| Documented structure may no longer match implementation reality | A refactor plan built on stale assumptions will sequence work incorrectly | Make M0 a hard gate before any move plan is approved |
| Public export cleanup can uncover many hidden consumers at once | Large consumer sweeps are where structural plans fail | Split M1 and M3 so high-risk callers are checked deliberately |
| Domain boundaries may overlap, especially around `workflow`, `runners`, and `api` | Mixed moves create circular imports and confusing ownership | Require explicit entry/exit criteria for each domain milestone |
| Test and script callers are easy to miss | Structural work can pass local imports but still break operational tools | Treat scripts, migrations, and test modules as first-class consumers in every phase |

## References

- [intent.md](intent.md)
- [architecture.md](architecture.md)
- [clarifications.md](clarifications.md)
- [docs/ARCHITECTURE.md](/Users/peter/code/task-world/worktrees/r51/docs/ARCHITECTURE.md)
- [docs/plan-runner/idea_to_plan_process.md](/Users/peter/code/task-world/worktrees/r51/docs/plan-runner/idea_to_plan_process.md)
