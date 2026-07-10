# Task 2 Report: Lifecycle, Callback, Retry, and Dispatch Intent

## Outcome

Implemented ten strict lifecycle/callback/retry/dispatch event specifications and eleven
strict command specifications. Catalog command execution now receives the exact typed command,
the current graph projection, historical events, and universal execution context explicitly.
Converted Task 2 outcomes are `HydratedEvent`; effects awaiting Tasks 3/4/6 specifications use
one named mixed-result compatibility bridge scheduled for deletion in Task 9.

## TDD evidence

- Strict payload RED covered valid samples plus forbidden extras and mistyped required scalars
  for all ten event payloads; reducer RED required concrete payload classes and neutral audit
  participation. GREEN is included in the 276-test focused slice.
- Codemod RED covered the complete 10-event/11-command route inventory, direct envelope
  conversion, bridge registry removal, duplicate import prevention, repeated relocation, and
  second-apply idempotency. GREEN: `31 passed`.
- Final placeholder/ownership RED ran three tests: acknowledgement returned no event, callback
  rejected the context-owned `run_id` before reaching its placeholder, and converted bodies
  remained under their `_apply_*` legacy names. All three failed for those expected reasons.
- GREEN implemented projection/history-aware handlers. The five focused framework/behavior/
  ownership tests passed, followed by `276 passed in 2.79s` for the required slice plus codemod.
- Full-unit RED exposed compact projection loss of callback `idempotency_key` and `payload`;
  adding both projection-required fields made the direct regression `4 passed` and the full
  unit suite `3350 passed`.
- Integration RED exposed cancellation losing legacy lease/node side effects on typed dispatch.
  Routing lifecycle outcomes through the narrow mixed bridge restored those effects; the exact
  integration regression passed.
- Serial integration then exposed strict agent-death retry fields omitted from its command and
  compact node-detail lifecycle events missing required `to_state`. The seven failing tests
  passed after adding producer-owned retry fields and the compact allowlist entry.

## Automation sequence and evidence

The inherited automation sequence was preserved: inventory/preview, one structural apply,
manual semantics, assert-clean, domain check, and repeated apply. The recovery run repeated
`--assert-clean`, `--check-domain lifecycle`, and two consecutive `--apply` invocations; all
exited 0 and neither apply produced a further change. This confirms single-apply convergence,
repeat idempotency, and no reversal/race between manual semantics and the mechanical pass.

The mixed inventory surface remains exactly 44 events and 23 commands: 34/13 future-domain raw
sites plus 10/10 converted lifecycle sites. Heartbeat remains visible at the temporary lease
renewal bridge, accounting for the eleventh typed command without hiding its Task 4 raw effect.
The legacy-only `--check-baseline` intentionally reports converted names absent; its inventory
contract suite passed `20 passed`, and `--check-domain lifecycle` is the authoritative cutover
check for this slice. Dynamic future-domain emissions remain exposed in inventory output.

## Interface and compatibility decisions

- Projection and historical events are explicit handler inputs and never command payload data.
  Run ID, position, clock, ID generation, and actor stay on `CommandExecutionContext`.
- `CommandResult` is a temporary internal `HydratedEvent | EventEnvelope` bridge. The union is
  confined to specification/dispatcher and named conversion adapters.
- Strict callback and lifecycle outcomes hydrate through named specifications. Node, lease,
  output, file-state, and session effects remain envelopes until Tasks 3/4/6 provide specs.
- Controller payloads no longer inject universal `run_id` into strict command models.
- Callback validation preserves stale/conflict/duplicate idempotency behavior, nullable business
  payloads, acknowledgement identity checks, completion effects, and cancellation side effects.
- Comments at both bridge boundaries identify the Task 3/4/6 dependencies and Task 9 deletion.

## Verification

- Lifecycle codemod `--assert-clean`: exit 0.
- Inventory `--check-domain lifecycle`: exit 0.
- Second codemod apply: zero changes.
- Focused lifecycle/callback/framework/outbox/codemod suite: `276 passed`.
- Codemod suite: `31 passed`; inventory suite: `20 passed`.
- Full unit suite: `3350 passed`, with three existing SQLite datetime-adapter warnings.
- Full serial integration suite: `1283 passed, 5 skipped in 360.02s`.
- `tests/e2e` and `tests/slow` contain no collected tests (pytest exit 5: no tests ran).
- Pyright: 0 errors, 0 warnings.
- Ruff check/format: clean before final commit; commit hooks provide the final complete check.

## Self-review

- Confirmed all ten event and eleven command specifications are catalog-owned and strict.
- Confirmed converted outcomes reject wrong payload classes and do not leak raw dictionaries.
- Confirmed typed callback and acknowledgement paths execute real behavior with projection/history.
- Confirmed lifecycle cancellation retains lease revocation and node cancellation effects.
- Confirmed compact replay retains callback idempotency inputs.
- Confirmed future-domain raw emissions remain inventoried rather than silently cast away.
- Confirmed `.superpowers/sdd/progress.md` remains controller scratch and will not be staged.

## Concern

The deliberately narrow mixed-result adapter remains until Tasks 3/4/6 define the remaining
effect specifications and Task 9 deletes the compatibility union. No converted Task 2 outcome
uses the raw result path.
