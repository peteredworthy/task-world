# Architecture: Module Consolidation 3

## Purpose

This architecture note describes how the next consolidation wave should integrate with the repository’s documented module model. It is intentionally contract-first: it names the boundaries to preserve, the areas where ownership is likely still blurred, and the verification needed to prove that structural changes are complete.

The clarification record for this tranche confirms that no additional product or architecture decisions are required from a human. Remaining uncertainty is limited to execution-time discovery against the live codebase and should be handled as milestone gates rather than deferred design decisions.

## Integration Points

### 1. Top-Level Module Interfaces

The repository documentation defines nine public modules: `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, and `workflow`. Consolidation work should treat each module’s top-level package as the only supported external entry point.

Integration strategy:
- Update module `__init__.py` exports before or alongside consumer changes.
- Move internal references behind top-level exports instead of teaching callers new sub-package paths.
- Fail the milestone if a consumer still depends on an internal package that is meant to stay private.

### 2. Workflow, State, and Runner Boundaries

The existing docs describe these modules as tightly related but distinct:
- `workflow` owns execution flow, gating, phase transitions, and orchestration logic.
- `state` owns persisted run/task state models and event history concerns.
- `runners` owns agent execution backends, discovery, and per-runner model/profile behavior.

Consolidation strategy:
- Normalize ownership of runtime callbacks, action logs, and execution-time protocols so they live with the module that conceptually owns them.
- Use explicit protocols or callbacks when one module only needs a narrow interface from another.
- Treat runner decomposition and workflow boundary cleanup as the highest-risk area for circular imports.

### 3. Database and Git Access Surfaces

Documentation positions `db` as the persistence layer and `git` as repository/test/diff infrastructure. Any remaining consolidation here should preserve that split.

Consolidation strategy:
- Keep ORM/repository access behind `db` exports and avoid API or runner modules reaching into internal persistence packages.
- Keep diff/repo/test-runner utilities under `git` ownership and prevent them from becoming a backdoor dependency hub.
- Audit migration files and operational scripts whenever a path under `db` or `git` changes.

### 4. API and Config Ownership

`api` should own transport-facing schemas and route wiring; `config` should own routine/config models, enums, and profile resolution. Plans that blur those responsibilities create reverse dependencies quickly.

Consolidation strategy:
- If a workflow or runner component only needs an internal data contract, prefer a local dataclass/protocol over importing an API response model.
- Keep config validation and profile mapping in `config`, with downstream modules consuming those validated models through top-level imports.
- Treat route schemas, request/response models, and transport-only adapters as `api` responsibilities.

## Recommended Execution Pattern

1. Audit current callers for one module boundary at a time.
2. Define the canonical public import path for every moved or narrowed symbol.
3. Update exports and consumers in the same milestone.
4. Remove obsolete paths immediately after consumer updates.
5. Run the milestone verification suite before moving to the next domain.

This pattern matches the repository’s documented preference for atomic tasks, runnable checkpoints, and zero lingering shims.

## Testing Strategy

### Verification Layers

- Unit tests: cover pure boundary logic such as export resolution, protocol wiring, and validation helpers.
- Integration tests: exercise real module interactions across workflow, runners, db, git, and api boundaries without mocks.
- Smoke checks: verify that canonical imports, CLI/API entry points, scripts, and migrations still load after each milestone.

### Required Checks Per Milestone

- Import-discipline check for the affected module boundaries.
- Relevant `uv run pytest` targets for touched domains.
- `uv run pyright` and `uv run ruff check .` before final completion.
- Any existing frontend or shared-type validation only if the consolidation changes shared contracts consumed there.

### Failure Policy

- A failed consumer update is a blocker for the current milestone, not a later cleanup item.
- A temporary shim is not an acceptable “green” state.
- If discovery reveals the docs are stale, the plan must be updated before refactor execution continues.

## Execution-Time Discovery Questions

- Which documented consolidation leftovers still exist in the current codebase versus only in historical plans?
- Which scripts, migrations, or tests still import internal module paths and therefore need explicit milestone coverage?
- Are there any remaining API-schema or workflow-service imports crossing boundaries in the wrong direction?
- Does runner decomposition still require a separate sub-plan, or has enough already landed that only interface cleanup remains?

## Success Signal

This consolidation wave is architecturally complete when module ownership is clearer at the public interface level, internal packages are no longer depended on as external APIs, and verification demonstrates that the documented nine-module structure is how the repository actually operates.

That success condition assumes the clarification outcome remains unchanged: if execution-time discovery finds stale documentation, the planning artifacts should be revised, but no new human design choice is currently outstanding.
