# Independent Sol review prompt

Use a fresh `gpt-5.6-sol` context with high reasoning. Read `AGENTS.md`,
`docs/intent/31-decision-runtime/architecture.md`, `contracts.md`, the assigned slice in
`implementation.md`, and the current implementation ledger. Work only in
`/Users/peter/code/task-world/worktrees/recovery-stabilization`.

Review the actual diff and the actual evidence. The builder's passing summary
is not evidence that the intended behavior exists. Do not modify source or run
another test merely to reproduce an already trustworthy unchanged result.
Use a new targeted check when a concrete unresolved concern requires one; use
the prescribed UV prefix and disposable state. No paid probes, live mutations,
server starts, activation, historical resumes or commits.

Assess the assigned slice and its effects on these invariants:

1. The model answers the substantive question. Known facts and graph/lifecycle
   mechanics are derived in code, including for partially mechanical steps.
   Useful judgment and explicitly requested independent review are preserved.
2. `submit(outputs=...)` is the single answer channel. No hidden requirement for
   constructor, grade-loop or second finalization calls survives in decision-v1.
3. One owner defines each built-in answer/check shape. Custom YAML schemas keep
   their authority. Trace at least one field through schema declaration, both
   supported transport catalogs, prompt and actual authoritative validation.
4. Staging is durable but publishes no graph consequences. Runtime-controlled
   terminal closure requires no further model action. Its trusted cause,
   exact final-boundary witness and atomic finalization are required. The old
   accepted-patch-after-death shortcut cannot complete a new decision node.
   Generic interrupts cannot pass; cancellation races respect serialization.
5. Identity, read-set staleness, duplicate delivery and conflicting answers are
   enforced across restart. A stale answer cannot acquire newer authority.
   Accepted effects and completion share one transaction and existing outbox.
6. Verification follows contracts.md's exact obligation aliases, complete
   coverage, grade rules and candidate binding, with required
   passing runtime receipts. Wrong/empty/partial judgments cannot pass.
7. Budgets survive failures and restart, classification chooses the proper
   response, and missing evidence blocks further paid work. No automatic runner
   or model fallback appears.
8. The frozen contract distinguishes old and new data explicitly. Historical
   replay, legacy operator REST/MCP, supported Codex/Claude graph paths and
   unsupported-runner preflight remain correct. No unrequested adapter expansion
   or schema migration was introduced.
9. New abstractions replace a demonstrated duplication. Flag a second registry,
   scheduler, event store, mutable authority cache, generic conversion framework,
   broad rewrite or per-provider schema copy. Cross-module imports use public APIs.
10. Evidence proves production behavior and negative outcomes. Count a scripted
    transport as deterministic infrastructure proof, never as model reliability.

Return a concise verdict per applicable criterion: PASS with source/evidence,
FAIL with a concrete trigger and consequence, or NOT YET IN SCOPE naming its
assigned later slice. List blocking findings first with file/symbol references.
Do not label a required behavior deferred or out of scope merely to pass a
slice. State any exact test you ran and why existing evidence was insufficient.
For a final review, NOT YET IN SCOPE is no longer an acceptable unresolved result.
