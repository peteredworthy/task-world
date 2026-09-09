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
creates. The verifier compares a correct fixture with a deliberately defective
test fixture; it does not alter a user feature. These commands do not create,
start, or resume an orchestrator run.
