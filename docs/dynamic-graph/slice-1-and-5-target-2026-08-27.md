# Slice 1 and Slice 5 implementation target — 2026-08-27

Source: `reliable-plan-execution-contract.md`, written after failed dogfood run
`fff4f6b7-bf33-475f-8280-31ff5e1ef7ca` (Luna planning legacy-workflow removal).
That run scheduled correctly but lost plan semantics: generic workers, a
discovery node with unrestricted write authority, no typed
discovery→implementation edge, worker packets with no bounded objective, and
corrective work that compounded in the same dirty worktree after failure.

This doc is the pre-loop target brief for a `mind-the-gap` implementation
pass on Slice 1 (worker contracts + prompt hydration) then Slice 5 (recovery
semantics). It exists so the Planner/Gap-Finder role does not have to
re-derive the audit from scratch; it still owns picking and ordering the
actual chunks and confirming exact mechanisms in code.

## Findings audit (2026-08-27, verified against merged main `2553748e3`)

- Full suite baseline: **5454 passed, 5 skipped, 4 warnings, 75s**
  (`uv run pytest tests/ -q -n auto --dist worksteal`). Ruff/pyright clean per
  prior ledgers. This is the regression baseline every chunk must preserve.
- Contract doc's 6 slices, verified implementation status:
  - Slice 1 (worker contracts, hydration): **partial**. `work_mode: str | None`
    exists as an untyped optional field (`graph/models.py:1676`); `objective`
    is not a typed field at all — read opportunistically from an untyped node
    dict (`graph_runtime/prompts.py:347`). `scope`, `prohibited_actions`,
    `invariants`, `acceptance`, `bound_requirement_ids` have no typed
    representation. Patch validator (`graph/patch_validator.py`) performs no
    semantic checks on any of these. Hydration of bound records into worker
    packets already exists (`graph_runtime/prompts.py:754`
    `_hydrated_bound_record`) and prompt-summary evidence already exists
    (`graph_runtime/prompts.py:216` `_prompt_summary_for_node`) — these two
    pieces of Slice 1 do not need rebuilding, only wiring to the new typed
    fields once they exist.
  - Slice 5 (recovery semantics): **partial**. `FailureRecord`/`RecoveryPlan`
    types exist with `error_class`, `retryable`, `lease_id`, `attempt_number`,
    `max_attempts` fields, but `error_class` has no typed/enforced values —
    repo-wide grep found exactly one literal use of
    `"verification_failure"` (`graph/scheduler.py:408`) and zero occurrences
    of `infrastructure_failure` or `invalid_plan_failure`. Lease revocation
    was hardened in `80d74390f` (already merged) but does not yet classify
    *why* an execution disappeared before deciding whether/how to retry.
  - Slice 6 (dogfood regression): **not started** — zero references to
    `fff4f6b7` anywhere in `tests/`.
- Prompt surface (context, not in scope for these two slices): almost
  entirely hardcoded Python strings (`graph_runtime/prompts.py:186-201` planner
  mutation contract, `runners/agents/codex/common.py:1157+` tool
  instructions). Only per-agent `system_prompt` is DB-swappable
  (`runners/profiles/models.py:18`). Out of scope here; noted for a later
  externalization pass once Slice 1's typed contract exists to externalize
  *onto*.

## Slice 1 target: worker contracts and prompt hydration

Acceptance criteria (from the contract doc, scoped to what's buildable now):

1. Executable node payloads (worker, corrective-worker, discovery role
   variants) carry typed fields: `objective` (required, non-empty str),
   `work_mode` (`Literal["read_only", "write"]`, required), `scope`
   (required), `bound_requirement_ids` (list, may be empty but must be
   present), `acceptance` (required — deterministic command(s) or verifier
   obligation reference), `invariants` (optional list), `prohibited_actions`
   (optional list).
2. Patch validation rejects `create_node`/`patch` operations that create an
   executable node missing `objective`, `work_mode`, or `acceptance`, with a
   precise error message in the style already established by `ce9e43c7c`
   (report exactly which field is missing on which node, not a generic
   validation failure).
3. A node with `role` indicating discovery cannot declare `work_mode="write"`
   without an explicit, separately-flagged override; default discovery
   `work_mode` is `read_only`. The Planner/Gap-Finder must determine the
   actual enforcement point in code (likely resource-claims / tool-routing in
   `graph/compiler.py` or `runners/graph_tool_routing.py`, not just the typed
   field) before implementing — the doc's finding was that the failed run's
   discovery node had literal write authority, not just a mislabeled field.
4. Worker prompt construction reads `objective`/`scope`/`prohibited_actions`/
   `invariants`/`acceptance` from the new typed fields (not the loose dict
   access at `prompts.py:347-372`) and surfaces them as a distinct section of
   the worker packet.
5. Regression coverage for contract-doc scenarios #1 (read-only discovery
   cannot obtain write authority) and #4 (worker prompts contain their bound
   requirement/objective fields) at minimum. Scenario #3 (staged plan cannot
   collapse to one generic worker without an accepted amendment) is stretch —
   defer explicitly with a recorded reason if the Planner judges it too large
   for this pass.

Non-goals for this pass: semantic artifact envelope (Slice 2), progressive
horizon enforcement (Slice 3), candidate/accepted snapshot isolation
(Slice 4), the full Luna dogfood regression conversion (Slice 6).

## Slice 5 target: recovery semantics

Acceptance criteria:

1. A typed `FailureClass` (or equivalent enum/literal) distinguishing at
   least `infrastructure_failure` (execution/runner disappeared, no
   callback), `verification_failure` (ran, produced a graded failure), and
   `invalid_plan_failure` (patch/plan itself was rejected) — replacing the
   single untyped `error_class` string.
2. Missing-callback / disappeared-execution handling classifies the failure
   as `infrastructure_failure` before deciding on retry, and the retry
   decision states which snapshot the retry will use and why a repeat attempt
   is expected to behave differently (contract doc requirement — "rapidly
   recreating the same execution against the same repository state is not
   recovery").
3. Lease revocation on a missing callback is conclusive: no state where a
   paused run reports an active lease with no callback pending recovery
   action.
4. Regression coverage for contract-doc scenario #9 (a missing callback ends
   with either a healthy retry or a conclusively revoked lease and typed
   recovery state) at minimum.

Non-goals: health-check-based runner probing before retry (mentioned in the
contract doc's item 7.3) unless the Planner finds it cheap given what
`80d74390f` already added — otherwise defer with a recorded reason.

## Process

Each slice runs as a `mind-the-gap` loop: fresh Planner/Gap-Finder picks the
next small chunk against this target and the current verified state; fresh
Builder implements only that chunk; fresh, independent Validator checks it
(relevant tests must pass; full suite must stay green) before it's marked
verified. Durable state (verified facts, decisions, evidence, remaining gaps)
is tracked in `docs/dynamic-graph/slice-1-and-5-progress-ledger-2026-08-27.md`
and updated after every validated chunk. Each slice merges to `main` only
after its full acceptance criteria are validated and the full suite is green.
