# Intent: Module Consolidation 3

## Original Request

Implement `docs/module-consolidation-3/intent.md` as the next planning tranche for module consolidation, using only documented repository context and process guidance.

## Goal

- Produce an execution-ready consolidation plan for the current nine-module orchestrator layout that reduces remaining boundary ambiguity without reintroducing shims, undocumented coupling, or top-level API drift. [I-01 → S-01/T-01/R4, S-02/T-01/R4, S-03/T-01/R4, S-04/T-01/R3, S-05/T-01/R4]
- Front-load uncertainty by identifying the audits, dependency checks, and sequencing gates that must happen before any structural refactor begins. [I-02 → S-01/T-01/R1, S-01/T-01/R4]
- Define a consolidation path that preserves the documented public-module contract: external code imports from `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, and `workflow` top levels only. [I-03 → S-02/T-01/R2, S-02/T-01/R3, S-03/T-01/R4, S-05/T-01/R2]

## Scope

### In Scope

- Audit the existing nine-module structure against the documented top-level import rule and capture the specific boundary checks that must precede code moves. [I-04 → S-01/T-01/R1, S-01/T-01/R2, S-02/T-01/R1]
- Plan a narrow set of consolidation milestones focused on remaining internal decomposition, public API cleanup, and removal of any still-documented cross-module leakage. [I-05 → S-02/T-01/R4, S-03/T-01/R1, S-03/T-01/R4]
- Define how the work will treat high-risk areas called out in repository docs: runner composition, workflow coordination, database access boundaries, and API/schema ownership. [I-06 → S-03/T-01/R2, S-03/T-01/R3, S-04/T-01/R1]
- Specify verification expectations for each milestone, including import-path checks, test execution, and runnable-system gates after every phase. [I-07 → S-02/T-01/R5, S-03/T-01/R5, S-04/T-01/R3, S-05/T-01/R3]
- Record the unresolved questions that must be answered during execution-time discovery rather than hidden inside later implementation steps. [I-08 → S-01/T-01/R2, S-01/T-01/R4]

### Out of Scope

- New end-user features, workflow behavior changes, or UI redesign unrelated to module boundaries. [I-09 → NO-REQ: excluded by scope, not assigned to a consolidation execution step]
- Database schema changes or migrations unless a documented consolidation dependency proves they are unavoidable. [I-10 → NO-REQ: excluded by scope unless later discovery changes the tranche]
- Temporary compatibility shims, duplicate module trees, or long-lived re-export files used to mask incomplete moves. [I-11 → S-03/T-01/R4, S-05/T-01/R4]
- Replanning the full 19-to-9 consolidation history; this document only covers the next actionable wave from the current documented architecture. [I-12 → NO-REQ: historical replanning is explicitly outside this tranche]

## Constraints

- Treat documented architecture and process references as the source of truth for this planning pass; do not assume undocumented module layouts or hidden implementation details. [I-13 → S-01/T-01/R1, S-05/T-01/R1]
- Sequence work so each milestone leaves the repository runnable, with verification strong enough to prove behavior rather than file presence. [I-14 → S-03/T-01/R5, S-04/T-01/R3, S-05/T-01/R3]
- Keep tasks atomic enough for builder/verifier execution, favoring bounded moves over broad “cleanup” phases. [I-15 → S-02/T-01/R4, S-03/T-01/R1]
- Preserve the repository rule that module consumers import from top-level module interfaces, adding exports where needed instead of normalizing sub-package imports. [I-16 → S-02/T-01/R2, S-02/T-01/R3, S-03/T-01/R4, S-05/T-01/R2]
- Surface uncertainty explicitly before implementation by requiring discovery checkpoints for scripts, tests, migrations, and external callers that may still reference old paths. [I-17 → S-01/T-01/R3, S-01/T-01/R4, S-04/T-01/R1, S-04/T-01/R2]
- Respect project testing discipline: no mocking-based validation strategy, real-object integration where module boundaries are exercised, and `uv run` commands for Python checks. [I-18 → S-02/T-01/R5, S-03/T-01/R5, S-04/T-01/R3, S-05/T-01/R3]

## Clarification Status

The clarification review recorded in `clarifications.md` closed all human-input design questions for this planning tranche. The only remaining unknowns are execution-time discovery items that must be verified against the live codebase before refactors begin; they are sequencing and audit inputs, not open product or architecture choices.

## Definition of Complete

- [ ] `intent.md`, `plan.md`, and `architecture.md` exist in `docs/module-consolidation-3/` and describe the same consolidation slice without conflicting scope or ordering. [I-19 → NO-REQ: planning-artifact integrity requirement already satisfied outside the execution steps]
- [ ] The intent identifies concrete goals, in-scope work, out-of-scope work, and constraints for the next consolidation wave rather than generic refactor guidance. [I-20 → NO-REQ: intent quality gate for the planning docs, not an execution-step deliverable]
- [ ] Every implementation milestone in the plan has a stated purpose, entry condition, and verification outcome tied to the documented module architecture. [I-21 → S-01/T-01/R4, S-02/T-01/R4, S-03/T-01/R1, S-04/T-01/R5, S-05/T-01/R1]
- [ ] The architecture document names the affected subsystem boundaries and explains how import cleanup, public exports, and testing will be handled. [I-22 → NO-REQ: architecture quality gate already expressed in the existing planning artifacts]
- [ ] All intent goal, scope, constraint, and Definition of Complete lines carry sequential `[I-XX]` identifiers with no gaps or duplicates. [I-23 → NO-REQ: identifier hygiene is a document authoring constraint, not a future execution step]
- [ ] Open questions and uncertainty hotspots are exposed early enough that a later builder can investigate them before moving files. [I-24 → S-01/T-01/R2, S-01/T-01/R4]
