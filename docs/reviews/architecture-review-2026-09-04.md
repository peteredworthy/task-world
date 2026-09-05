# Architecture review — 4 September 2026

The project has a sound purpose and several strong engineering foundations. Separating construction from independent verification, binding evidence to a candidate, and running checks mechanically are all worth preserving. Adaptive planning is also appropriate for large software tasks.

My assessment is that the implementation expanded the amount of orchestration an agent must get right faster than it established a reliable path through that orchestration. A run now depends on agreement among graph declarations, planner tools, prompt hydration, submission schemas, generated records, file-state witnesses, recovery, and several read models. Individual components have extensive checks, but a mismatch between them can make useful work impossible to submit and trigger expensive retries.

**The shortest path is a constrained, sequential adaptive workflow on the existing runtime: plan the next bounded batch, build it, execute checks, independently verify it, accept its snapshot, then plan again.** Keep the graph as the durable representation. Restrict how the supported workflow constructs it. Preserve the legacy execution path as a working fallback while qualifying the graph path.

This review covers current source, selected tests, saved local events and logs, and prior product evaluations. The server at localhost:8000 was unavailable. I did not start it, inspect or modify the production database, change implementation code, or run Git operations on the main checkout. This is an architectural assessment with concrete reproductions, not a complete audit of every module or a new live model trial. Historical reports are identified as historical; their closed defects are not assumed to remain open.

## 1. Strengths and weaknesses of the codebase

### Strengths

**The important conceptual boundaries exist.** The graph kernel computes changes, the controller persists them, and the runtime performs effects. `GraphController` accepts injected clocks and identifiers, computes command results outside the SQLite write transaction, then commits events and outbox work atomically. This makes many failure cases reproducible without an LLM. See [controller.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/controller.py:134).

**There is substantial investment in correctness of evidence.** Typed records, immutable grouped projections, lease generations, candidate identity, artifact hashes, and snapshot witnesses make it harder for stale or unrelated results to count as success. The replay tests compare full, incremental, and checkpointed execution at every split in their event streams. These are valuable properties to retain. See [replay tests](/Users/peter/code/task-world/tests/unit/test_graph_projection_replay_equivalence.py:43).

**Verification is more than a prompt convention.** Deterministic submission gates record command identity, exit status, output hashes, and candidate-tree identity. Verifier records must refer to a bound candidate and represented requirements. Final checks consider unresolved graph obligations. The machinery can support the original goal of mechanical verification. See [submission gate](/Users/peter/code/task-world/src/orchestrator/graph_runtime/submission_gate.py:80), [verifier validation](/Users/peter/code/task-world/src/orchestrator/graph/_commands.py:1925), and [final blockers](/Users/peter/code/task-world/src/orchestrator/graph/projections.py:3281).

**The failure evidence is unusually useful.** There are durable events, outbox records, supervisor logs, prompt summaries, and explicit failed-trial reports. The August comparison honestly records that the legacy arm succeeded and both graph arms failed. This gives a much better basis for improvement than a green test count alone.

**The existing legacy path is an asset.** It provides a simpler behavioral reference and a fallback for bounded work. The saved evaluation demonstrates one successful legacy run; it does not establish a general success rate.

### Weaknesses

**The maintenance surface is large for the core job.** A physical source-line inventory found 126,842 Python lines under `src/orchestrator`, including 55,929 in `graph` and `graph_runtime`, approximately 44% of the backend before graph-related API, database, and workflow code. The inventory includes comments and blank lines and is a size measure, not a quality score. `store.py` has 7,569 lines, `_commands.py` 7,046, `projections.py` 6,359, and `dispatch.py` 4,932. Changes to one concept commonly cross several of these files.

**Some module splits retain the original concentration of behavior.** For example, the scheduling command handlers delegate into the large `_commands.py`. Moving wrappers into smaller files helps navigation but does little to reduce the number of rules a maintainer must understand together. See [schedule handlers](/Users/peter/code/task-world/src/orchestrator/graph/commands/schedule.py:42).

**Type safety is strongest at selected boundaries and weaker between them.** There are good Pydantic models, but runtime contexts and many adapters still pass `dict[str, Any]`, interpret role strings, and reconstruct port semantics. A valid node model does not guarantee that the runner can supply the outputs the callback expects. The reproduced submission defect below is a concrete consequence.

**Two execution systems and several representations need reconciliation.** Graph lifecycle and workflow run status are related but separately maintained. The driver contains explicit handling for an active run row paired with a failed kernel, including an operator-reopen marker. This is careful recovery code, but it exposes the coordination burden. Derived diagnostic projections add another availability boundary. See [lifecycle reconciliation](/Users/peter/code/task-world/src/orchestrator/workflow/graph_driver.py:88).

**The default quality gate does not establish graph completion.** Both `make test` and pre-commit invoke pytest with defaults that exclude `slow` and `e2e`. The deterministic dynamic graph completion suite is marked `e2e` despite using scripted agents. Thus a normal green gate can coexist with broken completion scenarios. Separately, the UI hook expression `test ... && npm ... || echo ...` can turn a real lint or typecheck failure into a successful “Skipping” message. These are specific gaps in what a green gate means. See [pytest configuration](/Users/peter/code/task-world/pyproject.toml:65), [dynamic E2E harness](/Users/peter/code/task-world/tests/integration/test_graph_dynamic_e2e.py:55), and [hooks](/Users/peter/code/task-world/.pre-commit-config.yaml:57).

**Operational compatibility needs an explicit boundary.** The repository intentionally has no database schema-upgrade contract. That is a valid development policy, but self-iteration cannot safely assume that new server code will operate against an old database. Use fresh isolated databases for candidate versions now; define compatibility or an explicit export/import process before making upgrades routine.

**Documentation contains overlapping claims of completion.** The graph status ledger declares earlier functional requirements validated, while later incident reports identify missing plan semantics and unsuccessful live runs. Those reports are useful, but “validated” needs a source version, supported execution profile, and named scenario to prevent an old result from being read as a current product guarantee.

## 2. Strengths and weaknesses of the dynamic graph concept

### Strengths

**It permits planning when information becomes available.** A planner can describe distant milestones loosely, execute discovery or a bounded implementation stage, and then refine the next stage using accepted results. This directly addresses the limitation you encountered with fully precomputed task sequences.

**Dependencies can represent knowledge as well as ordering.** A worker can consume a verified plan, a verifier can consume a particular candidate, and corrective work can consume exact failed grades. This is more expressive than advancing a stage counter.

**Correction and branching can remain explicit.** The graph can preserve failed attempts and their evidence while representing a replacement attempt. Independent branches can eventually run concurrently when their workspaces and contracts justify it.

**A graph can make completion explainable.** Requirements, candidates, checks, and unresolved obligations can be queried together. A completion decision can identify precisely which evidence establishes each requirement.

### Weaknesses and necessary limits

**A valid graph can still describe a poor plan.** Port compatibility and acyclicity cannot establish that the planner chose sensible stages or understood the feature. Meaning still requires judgment. Mechanical checks should establish observable behavior and evidence identity; independent review should assess adequacy where no complete oracle exists.

**Dynamic mutation expands the failure space.** Replacing a producer raises questions about already-bound inputs, old verification, candidate freshness, resource ownership, and completion. A revision is more than adding another node. These rules need an explicit model even if execution remains sequential.

**Planner authority can undermine acceptance unless its scope is bounded.** The agent doing decomposition should be able to add work and stronger checks. It should not silently weaken the user's acceptance criteria to make the graph complete. Amendments need explicit provenance and the appropriate authority.

**Verification overhead can outweigh its benefit.** Independent contexts reduce shared assumptions, but they also repeat context and can lose discoveries during handoff. For very small tasks, multiple planning and gap-planning sessions may cost more than the implementation. The unit of work should be a meaningful batch with a measurable outcome.

**The full generality is optional.** Your requirement needs rolling planning horizons. It does not initially require arbitrary graph surgery, concurrent writers, recursive recovery planners, or many specialized executable node kinds. A sequence of bounded, independently accepted regions supplies much of the benefit with fewer interactions.

## 3. Strengths and weaknesses of the implementation

### What is already working in its favor

The implementation has deterministic readiness and resource-conflict logic, typed port contracts, constrained graph macros, candidate-bound checks, durable dispatch, and staged runner completion. These are useful foundations for a constrained production path.

Recent work has also repaired several earlier semantic omissions. Current worker prompts include a `work_contract`, bound evidence, declared outputs, and prior-attempt failure details. Current runtime code creates a separate execution checkout for applicable read-only semantic workers. It would be inaccurate to repeat the August report's missing worker evidence or shared-worktree discovery behavior as unchanged current defects. See [worker packets](/Users/peter/code/task-world/src/orchestrator/graph_runtime/prompts.py:400) and [read-only execution setup](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:1670).

Shared-worktree executions are deliberately serialized from baseline capture through submission. That is a reasonable reliability choice. It also means that graph-level scheduling generality currently exceeds the concurrency this execution path can safely deliver.

### Confirmed current defect: an impossible mixed-output submission

I reconstructed the accepted node declaration for `worker-reliable-plan-semantic-revision` in saved run `1bb308dc-4292-4a1b-a274-49fc4b238d33` and passed schema-valid semantic content through the current submission functions. This reproduction performs no runner execution or database writes.

| Boundary | Observed behavior |
|---|---|
| Accepted node declaration | Requires `candidate` and `semantic_artifact` |
| Runner submit-tool schema | Allows the agent to author only `semantic_artifact` |
| Semantic submit conversion | Produces only the semantic record |
| Callback preflight | Rejects the missing required `candidate` |
| Attempt to provide `candidate` explicitly | Rejects it as an unknown authored output port |

The callback chooses supplied semantic records **instead of** the controller-generated records used by ordinary workers. It then validates against the complete declared output list. This is an adapter defect that additional model effort cannot resolve. The repair should compose valid controller-owned outputs with agent-authored outputs according to one resolved contract, while preserving identity ownership and rejecting duplicates. It should not make required outputs optional or expose trusted identity fields for the agent to fabricate.

Source chain: [runner schema](/Users/peter/code/task-world/src/orchestrator/runners/submission.py:11), [semantic conversion](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:482), [submit routing](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:1830), [record selection and preflight](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:2499).

The September 3 server log contains 17 corresponding preflight warnings, from 21:09 to 22:34 UTC. The journal records seven retry-scheduled events for the run and eventually a paused run with missing verification and semantic-artifact inputs. The event sequence supports the connection between the rejection loop and blocked downstream work; it does not prove that this was the run's only defect. A bounded copy of the relevant declarations and status evidence is saved in [review evidence](/Users/peter/code/task-world/docs/reviews/architecture-review-2026-09-04-evidence.json).

### Retry policy does not reliably distinguish an impossible contract from a transient failure

The Codex adapter returns a rejected submit to the same session so the agent can correct it. That is useful for repairable payload mistakes. In this incident, the model was told to correct something its tool contract prohibited.

Runtime recovery then has another retry layer. `handle_complete_runner_recovery` enforces the attempt ceiling only when `max_attempts > 0`; zero therefore supplies no ceiling on that path. The driver also has an orphan-recovery budget, but that does not cover every managed recovery or in-session submit rejection. An execution budget must survive restarts and cover all these routes. See [submit rejection handling](/Users/peter/code/task-world/src/orchestrator/runners/agents/codex/agent.py:746) and [recovery ceiling](/Users/peter/code/task-world/src/orchestrator/graph/commands/boundary.py:779).

### Read-model protection has become an execution dependency

The controller needs a valid projection to accept commands. Missing or invalid checkpoints can be recovered only within a bounded event window; exceeding it raises `GraphReadModelUnavailable`. Bounded reads are appropriate, particularly given the large historical journals, but there must be a reliable maintenance path that restores the execution projection without asking an agent to retry its work.

During the isolated happy-path test rerun, the log began with rejected planner submissions and later repeatedly reported `graph_projection_checkpoint (recovery_tail_exceeds_bounded_cap)`. This demonstrates a failure cascade in the test path, not proof that checkpoint recovery is the original cause of the live incident. See [projection loading](/Users/peter/code/task-world/src/orchestrator/graph_runtime/store.py:4987).

### Evaluation-specific machinery has entered the product control path

Reliable-plan qualification uses a canonical scenario manifest, controller-recorded qualification evidence, an opaque single-use grant, a run-creation binding, and validation before seeding. This guards against fabricated evaluation claims, but it also couples production creation to a particular evaluation apparatus. Keep product invariants in the runtime and qualify releases in an external test harness. Any remaining admission policy should have a product reason independent of a named experiment. See [qualification API](/Users/peter/code/task-world/src/orchestrator/api/routers/runs.py:659) and [qualification service](/Users/peter/code/task-world/src/orchestrator/graph_runtime/reliable_plan_qualification.py:24).

### Product results remain weaker than component evidence

The saved August 28 comparison reports:

| Arm | Result | Reported tokens | Actions |
|---|---|---:|---:|
| Graph, Luna workers | Manually paused after a long worker turn without a callback | 10,823,845 | 145 |
| Graph, alternate workers | Paused as quiescent with missing corrective verification | 8,579,453 | 211 |
| Legacy plan-then-execute | Completed; three rubric grades A | 2,094,915 | 49 |

These were three runs with different model assignments and live fixes during the trial. They do not isolate graph overhead or establish comparative success probabilities. They do establish that the deterministic qualification's 10/10 result was insufficient to predict successful live completion. Source: [dogfood evaluation](/Users/peter/code/task-world/docs/dynamic-graph/dogfood-reliable-plan-evaluation.md:44).

## 4. Shortest path to useful self-iteration

I would authorize a stabilization effort around the following order. Each step has an observable exit condition; the full graph requirements backlog is not the acceptance criterion.

| Order | Change | Exit condition |
|---|---|---|
| 1 | Reproduce and repair the mixed-output submission defect. Test through the runner-facing tool schema, callback, staging, and finalization. | A worker requiring both a semantic artifact and a candidate can submit once, complete, and unblock its verifier. Wrong or missing semantic content still fails. |
| 2 | Establish one supported sequential graph profile using existing macros and runtime facilities. Materialize only the next bounded work region. Preserve user-selected runner/model configuration. | One batch and a second adaptively planned batch complete from the normal API path without manual graph edits. |
| 3 | Put finite durable ceilings on submit repair, execution retry, and corrective cycles. Classify permanent contract/configuration failures separately from transient transport failures. | An impossible contract stops with the original cause and a concrete operator action; it never consumes repeated equivalent model sessions. |
| 4 | Repair the deterministic product-path completion suite and include its offline cases in the normal merge gate. | Happy path, one correction, two horizons, cancellation, restart, and impossible-output cases finish within explicit time bounds on fresh test storage. |
| 5 | Run a small live qualification using the chosen supported runner, then use the harness for bounded changes to itself. | Several real runs complete checks and independent verification without manual state repair; one restart and one forced correction are exercised. |

The supported workflow should be:

```text
Goal and fixed acceptance obligations
    → plan the next bounded batch from accepted evidence
    → build in an isolated worktree
    → execute deterministic checks on the candidate
    → verify in fresh agent context
    → accept the candidate snapshot, or issue a bounded correction
    → plan the next batch, or execute final acceptance
```

For that first profile, use one effectful region at a time. Have the controller create the standard builder/check/verifier edges and identities. Ask the planner for a bounded work contract and the next milestone, rather than making it maintain arbitrary low-level topology. An empty correction branch should not need model activity to establish that there is nothing to correct.

Make the existing acceptance command the authoritative check for the final candidate, with batch-specific checks where appropriate. Keep both verification layers: executable checks prove the behaviors they cover; a fresh verifier assesses requirement coverage, unintended changes, and evidence adequacy. A typed report with valid IDs is necessary but insufficient evidence of correct software.

For self-iteration, run a known-good controller version while candidate code changes in a run worktree. Test candidate servers against fresh disposable databases and separate ports. Do not reload the supervising server into the candidate under evaluation. Initially, keep deployment or merge under operator review; the useful milestone is autonomously producing an independently verified change ready for review.

As an initial qualification target, I would require five bounded real software tasks to complete consecutively without manual graph edits or state repair, including a genuine corrective cycle and a restart exercise. Record the source/routine version, selected models, final snapshot, check receipts, costs, and wall time. Five runs are a practical entry gate, not a statistical reliability claim.

If graph stabilization does not reach the second-batch exit condition promptly, use the proven legacy loop for bounded batches and replan between runs. This is a temporary fallback using existing execution machinery. Avoid building a third general-purpose runtime.

## 5. Long-term changes

**Separate adaptive planning from graph mechanics.** Expose a small set of work operations such as propose batch, accept evidence, request correction, and plan successor. Compile these into the graph. Treat raw patch operations as an internal representation or advanced diagnostic surface. This retains late planning while reducing the topology burden on agents.

**Resolve one execution contract before dispatch.** Admission, prompt construction, tool schema generation, output assembly, callback validation, and readback should consume the same resolved contract. Include input hydration, output ownership, accepted snapshot, checks, and retry policy. Add a contract-feasibility test: every required output must be producible by either the agent schema or a controller provider. Test mixed outputs and optional semantic outputs as well as single-output nodes.

**Reduce independently maintained lifecycle state.** Establish an explicit authority for each fact: run lifecycle, node attempt, accepted candidate, and pending side effect. Derive UI state from those facts. Consolidate duplicate interpretations incrementally, protected by replay tests, rather than replacing event sourcing wholesale.

**Separate execution availability from diagnostic maintenance.** Keep canonical append and the minimal execution projection dependable. Build heavier topology, archival, and evidence views asynchronously. A stale diagnostic view should explain its position without causing an otherwise valid task to fail. Provide an explicit bounded repair path for execution checkpoints and test it after schema changes, corruption, and interrupted maintenance.

**Make accepted snapshots the planning boundary.** A planner should know which snapshot is accepted, which failed candidate it is correcting, and what evidence belongs to each. Preserve failed work for inspection without silently promoting it into the next accepted baseline. Only add concurrent writers once per-attempt workspaces and candidate integration are proven worthwhile.

**Make recovery smaller and causally explicit.** Distinguish payload repair within a session, transient execution retry, semantic correction, checkpoint maintenance, and operator intervention. Give each one an owner and durable budget. Preserve the first causal error through the final blocked-state explanation.

**Reduce special-case product machinery.** Move evaluation manifests and receipts out of ordinary run admission where they do not serve a product requirement. Consolidate role aliases, generic fallback outputs, and duplicated graph/legacy adapters after the constrained path is stable. Retire the legacy carrier only when the replacement has repeatable product evidence.

**Use architecture simplification to delete responsibilities.** Splitting the four largest files is useful only if it also establishes smaller owners: contract resolution, record acceptance, scheduling, effect execution, and projection maintenance. Preserve the current pure-kernel/effectful-runtime distinction and the immutable replay guarantees.

**Measure successful software delivery.** Track unattended completion, accepted changes, intervention count, corrective cycles, time blocked by the harness, and cost per accepted task. Separate model time from orchestration and validation time. A server returning HTTP 200 and a growing event position do not establish useful progress.

## Validation performed for this review

The mixed-output defect was reproduced with the current source and the saved accepted declaration. No model call was needed. The exact generated/allowed/missing ports are recorded in the evidence file.

The following command stopped after three failures:

```bash
uv run pytest --run-e2e -n 0 \
  tests/integration/test_graph_dynamic_e2e.py \
  tests/integration/test_graph_runner_e2e.py -q --maxfail=3
```

Result: **2 passed, 3 failed**, all three failures being 30-second timeouts in the dynamic completion scenarios. The second file was not reached before the failure limit. A diagnostic rerun of `test_dynamic_full_happy_path_completes` with a 60-second timeout also timed out, beginning with rejected planner submissions and later repeated bounded-checkpoint-tail errors. The old scripted patch fixtures omit fields that current worker admission requires, so fixture drift is a concrete concern. The timeout alone does not identify every defect or establish the behavior of a live model.

A separate run of projection replay equivalence, projection immutability, driver logic, and submission-gate tests reported **242 passed, 1 failed**. The failure was the disposable-environment dependency test trying to fetch `hatchling` from PyPI; DNS/network access was unavailable in this environment. It is not evidence of a failed graph assertion. The test also illustrates that the current `tests/unit` directory includes dependency-install integration behavior.

I used a writable temporary uv cache after the default cache produced a sandbox permission error. I did not weaken assertions, edit tests, or alter source to obtain these results. No full-suite or fresh live-run success is claimed. The report and bounded evidence are the only project deliverables from this review.

## Resolution status — 5 September 2026

The review above is preserved as the point-in-time assessment. The following
matrix records what changed afterward; it does not rewrite the historical test
results or promote offline evidence into a live reliability claim.

| Review issue | Status on 2026-09-05 | Current implementation and exact regression evidence | Remaining proof |
|---|---|---|---|
| Impossible mixed-output submission | Resolved | Controller-owned candidate/file-state outputs are composed with agent-authored semantic outputs through the resolved dispatch contract. `tests/integration/test_reliable_plan_product_path_qualification.py::test_codex_product_seam_composes_mixed_owned_outputs_and_unblocks_verifier` exercises schema, callback, staging, and finalization; ownership and duplicate rejection remain enforced in `src/orchestrator/graph_runtime/dispatch.py`. | No known immediate gap. |
| Supported bounded sequential profile | Resolved offline | The controller-owned discovery, plan verification, successor, effectful-batch, check, verifier, final-audit, and final-gate macros execute through the public create/start API in `tests/integration/test_graph_sequential_product_path.py::test_api_start_serializes_two_bounded_horizons_with_durable_signals`. Model/profile assignments are persisted and observed by runner construction. | Five consecutive live software runs remain open. |
| Durable finite retry for impossible semantic output | Resolved offline | `src/orchestrator/graph/retry_policy.py` centralizes the attempt semantics. `tests/integration/test_graph_sequential_product_path.py::test_oversized_discovery_exhausts_bounded_retries_and_blocks_publicly` proves three discovery attempts, two durable retries, the original event-envelope cause in `graph_blocked`, no downstream dispatch, and no active owner or lease. | No live-model claim is made. |
| Default gate omitted completion coverage | Resolved | `tests/integration/test_graph_sequential_product_path.py` is default-collected and contains five joined cases: two-horizon completion, correction, cancel, restart, and oversized-output exhaustion. The stale `tests/integration/test_graph_dynamic_e2e.py` was removed. `.pre-commit-config.yaml` now preserves real UI lint/typecheck failures while still reporting an intentional dependency absence. | Keep the five-case module in default collection. |
| Lifecycle cancellation and restart ownership | Resolved offline | `SignalConsumer.stop` now uses the same registry-backed lifecycle fence as pause/cancel: runner cancellation, safe recovery drain, zero-owner/zero-active-lease proof, then `PAUSED/server_shutdown`. Exact API and restart proofs are `test_api_cancel_waits_for_runner_recovery_before_terminal_state` and `test_server_restart_recovers_before_redispatch_without_duplicate_records` in the joined module. | Exercise one live restart during the five-run qualification. |
| Execution read-model dependency | Open | Runtime reads remain checkpoint-plus-bounded-tail and explicit `graph_read_model_unavailable` behavior remains in `src/orchestrator/graph_runtime/store.py` and `src/orchestrator/workflow/graph_driver.py`. Existing maintenance and replay checks reduce risk but do not remove execution's dependency on this projection. | Demonstrate bounded repair after corruption/schema change without rerunning model work, then decide whether execution state can be smaller than diagnostic state. |
| Evaluation-specific admission machinery | Open | The single-use qualification reference is still issued by `POST /api/runs/reliable-plan-qualification`, consumed during run creation in `src/orchestrator/api/routers/runs.py`, and revalidated by `src/orchestrator/graph_runtime/reliable_plan_qualification.py`. This remains stronger coupling than the recommended product-only admission rule. | Replace named-experiment admission with stable product capability/version invariants, or document the qualification as an intentional product policy. |
| Five-run live qualification | Open | Offline joined and component evidence is now substantially stronger, but no new live five-run sequence is claimed here. | Complete five bounded real tasks consecutively with no manual graph edit/state repair, including a genuine correction and restart, and record versions, models, snapshots, receipts, costs, and wall time. |
