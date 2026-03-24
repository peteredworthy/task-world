# Module Consolidation: Design Clarifications

## Status: No Open Questions

After thorough review of the intent, plan, and architecture documents, no open design questions require human input. All key decisions have been made and documented:

### Decisions Already Resolved in Planning Artifacts

1. **Target module count and structure** — 9 modules fully specified in architecture.md with complete file layouts
2. **Execution order** — 11 phases (0-10), dependency-ordered: couplings first, then dead code deletion, then absorptions, then internal restructuring, then interface narrowing
3. **Coupling resolutions (C1-C6)** — Each has a concrete fix strategy with specific files listed
4. **Shim policy** — Zero tolerance; no backward-compatibility stubs, re-exports, or deprecation period
5. **Migration strategy** — Phase-by-phase with full test suite verification after each phase
6. **BroadcastCallback approach** — Protocol in `runners/types.py` (structural subtyping)
7. **Sub-package access discipline** — External callers use top-level module imports only, enforced by `__all__`
8. **RunService/ReviewService extraction** — Explicitly deferred (out of scope)
9. **`__all__` enforcement** — Manual declaration + code review; linting rule is a future follow-up
10. **Interface narrowing scope** — Specific symbols identified for privatization/hiding, with fallback if `RunWorkflow` consumers resist

### Risks Acknowledged (Not Questions)

The plan's "Risks and Unknowns" table documents potential issues (circular imports, missed import paths, ORM model access patterns) with concrete mitigations. These are implementation risks to monitor, not design decisions requiring input.
