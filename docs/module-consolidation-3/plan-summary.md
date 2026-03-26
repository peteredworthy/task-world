# Execution Summary: Module Consolidation 3

## Intent Satisfaction Summary

This tranche is execution-ready for the documented nine-module orchestrator layout. The summary reflects the validated Step 1 through Step 5 execution files and preserves the public-module contract while front-loading uncertainty before any code moves. Consolidation stays limited to boundary cleanup, export cleanup, and bounded internal reorganization rather than another broad module rewrite.

Intent coverage is distributed across the five execution steps:

| Intent area | Covered by |
|---|---|
| Reality audit before refactor, uncertainty exposure, dependency gates | Step 1 |
| Canonical top-level import paths and public-interface cleanup | Step 2 |
| Bounded domain consolidation without shims or duplicate trees | Step 3 |
| High-risk caller validation for tests, scripts, migrations, and startup wiring | Step 4 |
| Final boundary proof, runnable-system verification, and intent mapping | Step 5 |

The tranche also stays aligned with the clarification outcome: there are no remaining human design decisions to resolve. The only open items are execution-time discovery checks against the live repository, and the plan treats those as explicit stop/go gates instead of hidden assumptions.

## Ordered Step List

| Step | Title | Tasks | Primary output |
|---|---|---:|---|
| 1 | Reality Audit and Gap List | 5 | `docs/module-consolidation-3/step-01-audit.md` |
| 2 | Public Interface Audit | 5 | `docs/module-consolidation-3/step-02-interface-audit.md` |
| 3 | Internal Consolidation by Domain | 6 | `docs/module-consolidation-3/step-03-batch-ledger.md` plus per-batch notes |
| 4 | High-Risk Consumer Sweep | 5 | `docs/module-consolidation-3/step-04-consumer-sweep-<batch-id>.md`, blocker log, recurring gates |
| 5 | Final Boundary Proof | 5 | `docs/module-consolidation-3/step-05-final-proof.md` |

Total: 5 steps, 26 tasks.

Execution order:
1. Step 1 verifies the live repository baseline, produces stable `F-XX` findings, and blocks execution if docs and code materially conflict.
2. Step 2 converts Step 1 findings into canonical top-level import decisions, export gaps, private leaks, and bounded cleanup batches.
3. Step 3 executes one bounded domain batch at a time in the documented order: `workflow/state`, `runners`, `db/git`, then `api/config`.
4. Step 4 runs after each completed Step 3 batch to sweep tests, scripts, migrations, startup wiring, and other operational callers before merge.
5. Step 5 reruns the tranche-wide import and verification gates, proves no temporary structure remains, and records final intent coverage.

## Key Decisions

- The public contract stays fixed at the nine documented top-level modules: `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, and `workflow`.
- Discovery is a hard prerequisite. No structural refactor starts until Step 1 produces evidence-backed findings, consumer inventories, and downstream dependency mapping.
- Canonical imports must be top-level module imports only. The plan allows adding exports in `__init__.py`, but not teaching callers new sub-package paths.
- Domain work is intentionally sequenced by risk: `workflow/state` first, then `runners`, then `db/git`, then `api/config`.
- Compatibility shims, duplicate module trees, and long-lived re-export bridges are disallowed throughout the tranche.
- Verification is behavioral, not presence-based. The plan requires `uv run` checks, caller-specific assertions, and runnable-system gates after each phase.
- Non-source consumers are first-class scope. Tests, scripts, migrations, startup wiring, and policy tooling must be inventoried and updated in the same tranche flow, not deferred.
- Root-level step mirrors and nested `steps/` files are already aligned; execution should treat the nested `steps/` path family as canonical.

## Risks and Mitigations

| Risk | Why it matters | Mitigation in plan |
|---|---|---|
| Documentation may no longer match live code | Refactor sequencing becomes invalid if the tranche starts from stale assumptions | Step 1 is a hard gate and defines stop conditions for doc/code conflicts |
| Public export cleanup may expose a larger consumer set than expected | Hidden consumers are where boundary cleanups usually fail | Step 1 inventories callers by finding; Step 2 converts them into bounded batches; Step 4 sweeps high-risk callers after each batch |
| `workflow`, `state`, and `runners` may still overlap internally | Cross-domain moves can create cycles and unclear ownership | Step 3 works one domain batch at a time and requires cycle-risk checks before export changes |
| Tests, scripts, migrations, and startup paths are easy to miss | Source imports can look clean while operational entry points still depend on private paths | Step 1 and Step 4 require explicit non-source caller coverage and named startup files |
| Final verification can look green while temporary structures remain | Passing checks alone do not prove consolidation is complete | Step 5 uses the Step 3 ledger and Step 4 blocker log as a no-shim / no-deferred-cleanup proof |

## Caveats for Execution

- Step 1 must stop on material contradiction, not summarize past it. Missing documented packages, undocumented public surfaces, or import-rule mismatches require planning-doc correction before refactors continue.
- Step 2 depends on explicit Step 1 `F-XX` findings. If a module or symbol cannot be traced to current evidence, it is out of bounds until Step 1 is refreshed.
- Step 3 batches are intentionally small: one domain issue at a time, under 5 files and roughly 500 net lines. If a move exceeds that, split the batch instead of widening scope.
- Step 3 must remove obsolete paths in the same batch that introduces the canonical path. A partial migration is a blocked batch, not acceptable progress.
- Step 4 is recurring, not one-time. It runs after each completed Step 3 batch and must either clear all inventoried high-risk callers or record a blocking reopen condition.
- Step 5 cannot declare release readiness if any blocker, compatibility bridge, duplicate public path, or deferred cleanup item remains in the Step 3 or Step 4 ledgers.
- Every execution task in the routine should keep contract-level `auto_verify`; the step files already assume verification is attached to each task rather than deferred to a later documentation-only review.
