# Recovery examples

## Run diagnostic

Explain failed graph nodes using public read APIs:

```bash
uv run python examples/recovery/run_diagnostic.py RUN_UUID --base-url http://localhost:8000
```

The command prints one JSON report. Exit status `0` means the available evidence is
complete, `1` means it is partial or unknown, and `2` means the run could not be read
or the arguments were invalid. Missing, malformed, identity-mismatched, or truncated
graph/node evidence is always partial. A present, complete, empty `node_states` mapping
is valid complete evidence.

## Deterministic lifecycle proof

Exercise the full one-file graph lifecycle without starting a server or invoking a
model:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  examples/recovery/deterministic_lifecycle.py
```

The bounded JSON result covers initial and successor planning, controller and outbox
dispatch, SQLite persistence, Git worktree submission, mechanical checks, fresh
verifier executions, final audit, run finalization, and quiescent cleanup. A passing
candidate is a clean committed diff that adds only `stage3-smoke.txt` with the exact
bytes `stage3-smoke-ok\n`.

## Isolated model-phase probes

After the deterministic recovery gate passes, run at most one paid Luna phase per
invocation:

```bash
uv run python examples/recovery/model_phase_probe.py planner
uv run python examples/recovery/model_phase_probe.py verifier
```

Each command creates disposable Git/SQLite fixtures, fixes the model to
`gpt-5.6-luna` at medium reasoning, enforces a 180-second wall limit, performs no
automatic retry, and prints one bounded JSON evidence object. The planner uses the
real graph dispatch and Codex dynamic-tool path but never schedules the region it
creates. It sets the proposal and execution caps explicitly to two rejected proposals
and one execution, and rejected plans use the production automatic evidence recorder.
The verifier receives neutrally named candidates and no expected grade mapping. A
pass requires current-turn Codex command-completion receipts for both exact oracle
commands before the corresponding grades and submission. These commands do not
create, start, or resume an orchestrator run.

## Isolated successor-planner probe

Exercise the successor boundary without model transport:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python -m \
  examples.recovery.successor_planner_probe deterministic \
  --evidence-root /private/tmp/recovery-successor-evidence
```

The harness reaches a production-created successor through scripted initial
planning, discovery, and plan verification, then runs only that successor through
an injected Codex transport. It uses the same sealed Luna-medium assignment, prompt,
dynamic tools, controller, outbox, and finalization path as a paid call. Passing
requires one execution, no more than two rejected proposals, a completed plain
submission, exact final-horizon topology, retained and replayed private rejection
evidence, no downstream dispatch, and quiescent ownership. Scripted success proves
the infrastructure contract; it does not establish model reliability.

Every invocation gets a distinct private artifact directory outside its disposable
workspace. It retains the bounded successor prompt and tool schema, each received
Codex tool request/response, controller rejection artifacts, and
`probe-result.json`. Cleanup after the 180-second model deadline is measured
separately and drains without a second timeout because worktree ownership must not
be abandoned.

A paid call is a separate command and requires the explicit opt-in flag. It performs
one successor execution and never retries automatically:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python -m \
  examples.recovery.successor_planner_probe paid \
  --confirm-one-paid-successor \
  --evidence-root /private/tmp/recovery-successor-evidence
```

Do not run the paid command until the deterministic command passes and its evidence
has been reviewed. Any paid rejection must have complete private transport evidence;
controller rejections must also replay under the recorded orchestrator source
identity before another paid execution is considered. An upstream rejection whose
arguments were not received is incomplete evidence and stops the experiment.

Replay retained evidence without a model using the per-invocation result path:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python -m \
  examples.recovery.replay_successor_probe RESULT_JSON_PATH
```

Replay success describes the evidence check. It does not turn a failed source
experiment into a successful model observation or authorize another invocation.
