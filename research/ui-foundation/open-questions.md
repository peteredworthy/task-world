# Open questions

- **Q-1 — Choose and migrate canonical attempt identity** (open; blocking=True): Adopt one persisted attempt primary identity, migrate nullable attempt_id references, and pass a repository round-trip plus uniqueness regression test.
- **Q-2 — Define typed cross-mode conversion and selection contracts** (open; blocking=True): Publish typed task/region/node/attempt conversion contracts and pass cross-mode selection/readback tests for every declared join.
- **Q-3 — Reconcile JSONL authority documentation with executable SQL authority** (open; blocking=True): Revise the authority documentation and recovery implementation so one normal-write authority is named, then pass durable append/bootstrap recovery tests.
- **Q-4 — Define a live-WAL-safe backup and replay contract** (open; blocking=True): Implement SQLite-consistent backup including WAL/SHM handling, replay marker validation, and a live-write restore/replay integration test.
- **Q-5 — Define product-role authorization before treating actor text as authority** (open; blocking=True): Bind authenticated subject claims to per-action role/scope/ownership checks and pass allow/deny integration tests for each mutating route family.
- **Q-6 — Decide whether execution-bound graph MCP patch macros need an action contract** (open; blocking=True): Either add a reachable execution-bound graph MCP action contract with route/tool tests or explicitly retire CMD-16 from selectable current surfaces.
- **Q-7 — Hash-guard decisive implementation and test evidence** (resolved; blocking=False): Resolved: the Phase 1 snapshot hashes every current src/orchestrator Python file, repository Python test, and UI source TS/TSX file; direct evidence records name a snapshot path.
