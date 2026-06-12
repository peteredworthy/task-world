**Criteria Table**

| # | criterion | code evidence | test evidence | status |
|---|---|---|---|---|
| 1 | Routine maps to root node plus routine snapshot record | `compiler.py:93-140` | `test_graph_compiler.py:29-38` | MET |
| 2 | Step maps to plan/grouping projection and preserves step order | `compiler.py:66-89`, `287-300` | `test_graph_compiler.py:40-70`, `285-313` | PARTIAL |
| 3 | Task maps to task projection plus worker/verifier/check nodes as applicable | `compiler.py:190-274`, `276-344`, `434-551` | `test_graph_compiler.py:73-80`, `110-161` | MET |
| 4 | Requirement maps to requirement nodes and edges to worker/verifier ports | `compiler.py:393-432`, `241-245` | `test_graph_compiler.py:83-108` | MET |
| 5 | Auto-verify maps to check nodes | `compiler.py:247-267`, `490-551` | `test_graph_compiler.py:110-140` | MET |
| 6 | Human approval gate maps to gate node only when configured | `compiler.py:71-73`, `142-188`, `233-237` | `test_graph_compiler.py:164-191`, absent case via `245-257` | MET |
| 7 | Context/artifact dependency maps to input binding edge | `compiler.py:553-584` | `test_graph_compiler.py:194-214` | MET |
| 8 | Fan-out maps to reader nodes plus synthesis/join node | `compiler.py:204-231`, `346-391` | `test_graph_compiler.py:217-242` | PARTIAL |
| 9 | Single-task routine compiles to minimum executable graph | `compiler.py:62-91`, defaults from `models.py:244-250` | `test_graph_compiler.py:245-264`, `274-282` | MET |
| 10 | Compiler is pure and deterministic with injected clock/id generator | `compiler.py:17-27`, `642-655`, no IO/YAML/DB imports | `test_graph_compiler.py:267-271` | MET |
| 11 | Existing active routine corpus compiles with sanity counts | `test_graph_routine_compile.py:26-43` | same | MET |
| 12 | Seeded graph persists transactionally with no dispatch outbox | `seeding.py:37-47`, `store.py:32-72` | `test_graph_routine_compile.py:46-79` | PARTIAL |
| 13 | Per-node compile/seed/schedule overhead is measured and bounded | `test_graph_routine_compile.py:82-139` | reproduced: `nodes=21 events=93 events_per_node=4.43 ms_per_node=1.73` | MET |

**Findings**

| severity | type | description | location |
|---|---|---|---|
| High | executable graph | Multi-step compiled graphs block step 2, but the current kernel path does not unblock it after step 1 completes. The compiler creates required `prior_step_completion` edges, readiness requires an input binding, and callback completion only changes node state/releases the lease. I reproduced this through the pure kernel: after completing `worker-s-01-t-01`, `worker-s-02-t-02` is still deferred with `missing_required_input:prior_step_completion`. | `compiler.py:80-88`; `scheduler.py:127-131`; `commands.py:199-221`; test only covers initial block at `test_graph_compiler.py:285-313` |
| Medium | controller authority | `seed_run` appends accepted graph mutation events directly through `GraphEventStore`, not `GraphController`. That creates a second append path for graph mutation events despite PRD §28 rule 1. It uses expected-position protection and does not create outbox rows, but it bypasses the controller-owned command boundary. | `seeding.py:37-44`; `store.py:23-26`; PRD `execution-graph-prd-plus.md:1286` |
| Medium | fan-out mapping | Fan-out compiles to one `planner` reader template and uses the worker as synthesis/join. This is documented in the compiler, but it is weaker than §23.2’s “Reader nodes plus synthesis/join node” wording and does not prove per-input reader expansion. If glob expansion is intentionally slice 2.3+, this should be explicit in acceptance docs. | `compiler.py:9-12`, `204-231`, `346-391`; test `test_graph_compiler.py:217-242` |
| Medium | routine snapshot identity | The routine snapshot carries routine id/name/description/counts/agent defaults, but not a durable version/source/git SHA. Given routines are git-versioned and runs record routine snapshots, this is not yet a real versioned snapshot identity. | `compiler.py:115-140`; test only asserts `routine_id` at `test_graph_compiler.py:35-38` |
| Low | test coverage | Corpus coverage is active top-level routines plus examples: 25 paths from `routines/demo-task.yaml`, `routines/*/routine.yaml`, and `examples/routines/*.yaml`. It excludes archived routines and step-fragment YAMLs. That is reasonable if “existing routines” means active entrypoint routines, but any broader claim would be overstated. | `test_graph_routine_compile.py:26-30` |
| Low | test coverage | Gate “only when configured” is covered by the explicit gate test plus the minimal no-gate assertion, not by a dedicated paired gate/no-gate test. Adequate, but slightly indirect. | `test_graph_compiler.py:164-191`, `245-257` |

Checks run fresh:

- `uv run pytest tests/unit/test_graph_compiler.py tests/integration/test_graph_routine_compile.py -q`: 40 passed in 3.29s
- `uv run pytest tests/unit -q`: 2578 passed in 14.50s
- kernel subset exact command: 161 passed in 1.37s, tool wall time 2.34s, under 5s
- `uv run ruff check src tests`: passed

**Verdict: BOUNCE**

The compiler covers most §23.2 mapping rows and the minimal single-task graph is genuinely exact and schedulable. However, the compiled multi-step graph is not currently executable past the first step because step-order edges require bindings that are never produced by the tested kernel path. That is a core execution-graph invariant, not just a missing assertion. I would bounce until step-order completion binding is implemented or the compiler uses a readiness mechanism that actually unblocks downstream steps after upstream terminal nodes complete.
tokens used
131,119
**Re-Audit Verdict: BOUNCE**

| finding | fix evidence | test evidence | status |
|---|---|---|---|
| HIGH-1 multi-step deadlock | Step-order edges now compile as `dependency_type="state_dependency"` in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:89); scheduler skips record binding for those but requires upstream completion/failure checks in [scheduler.py](/Users/peter/code/task-world/src/orchestrator/graph/scheduler.py:128). | I reproduced pure-kernel success and failure. Step 2 leases after step 1 callback-completes; step 2 blocks on step 1 failed. Existing tests cover this in [test_graph_compiler.py](/Users/peter/code/task-world/tests/unit/test_graph_compiler.py:341) and controller SQLite in [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:94). Demo traversal exists at [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:188). | CLOSED |
| MEDIUM-1 controller authority | `seed_run` now calls `GraphController.handle_command(..., "seed_compiled_events")` in [seeding.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/seeding.py:47); pure command validates topology-only seed events in [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:142). Controller expected-position guard is intact in [controller.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/controller.py:63). | Seeding integration asserts rebuild parity and `outbox_count == 0` in [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:48). Static search found no production `GraphEventStore.append_events` mutation path outside controller, except read-only recovery and tests. | CLOSED |
| MEDIUM-2 fan-out | Compiler emits distinct reader and join nodes in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:217), with reader → join → worker edges. Runtime glob expansion deferral is documented in the compiler module docstring. | Unit test asserts reader template, distinct join template, and both edges in [test_graph_compiler.py](/Users/peter/code/task-world/tests/unit/test_graph_compiler.py:233). | CLOSED |
| MEDIUM-3 snapshot identity | Snapshot now carries deterministic SHA-256 content hash plus `source_path` and `source_ref` in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:140); hash canonicalization is in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:770). | Unit hash same/different coverage in [test_graph_compiler.py](/Users/peter/code/task-world/tests/unit/test_graph_compiler.py:41); integration source threading in [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:82). | CLOSED |

**New Findings**

| severity | finding | evidence |
|---|---|---|
| HIGH | Generic callback output-record acceptance can forge another node’s output and bind downstream required inputs. `_accepted_output_record_events` only defaults `producer_node_id`; it does not require it to equal the callback lease node, and `_input_bound_events_for_record` binds by producer/port only, with no schema/edge-selector/authority validation in [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:273). I reproduced an active `verifier-evil` lease submitting an output record with `producer_node_id="worker-1"` and wrong schema; the kernel emitted `callback_accepted`, `output_record_accepted`, and `input_bound`, then scheduled the consumer while `worker-1` was still `planned`. This violates the controller validation model in §19/§21 and can bypass required data provenance. |

**Checks Run**

- `uv run pytest tests/unit -q`: 2586 passed, 3 warnings in 16.54s
- `uv run pytest tests/integration/test_graph_routine_compile.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_event_store.py -q`: 46 passed in 4.79s
- `uv run ruff check src tests`: passed
- Kernel/fixture subset: `uv run --no-sync pytest ...`: 139 passed in 1.25s
- Adversarial required-data edge without binding: still blocks with `missing_required_input:candidate`

Final verdict is **BOUNCE**. The original fixer claims are substantively closed, including the multi-step deadlock, but the newly added generic callback output-record path creates a higher-risk provenance hole: a valid lease can fabricate another node’s output and cause downstream input binding/scheduling without the producing node completing or the record satisfying an edge selector.
tokens used
148,834
**Re-Audit Verdict: BOUNCE**

| finding | fix evidence | test evidence | status |
|---|---|---|---|
| HIGH-1 multi-step deadlock | Step-order edges now compile as `dependency_type="state_dependency"` in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:89); scheduler skips record binding for those but requires upstream completion/failure checks in [scheduler.py](/Users/peter/code/task-world/src/orchestrator/graph/scheduler.py:128). | I reproduced pure-kernel success and failure. Step 2 leases after step 1 callback-completes; step 2 blocks on step 1 failed. Existing tests cover this in [test_graph_compiler.py](/Users/peter/code/task-world/tests/unit/test_graph_compiler.py:341) and controller SQLite in [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:94). Demo traversal exists at [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:188). | CLOSED |
| MEDIUM-1 controller authority | `seed_run` now calls `GraphController.handle_command(..., "seed_compiled_events")` in [seeding.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/seeding.py:47); pure command validates topology-only seed events in [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:142). Controller expected-position guard is intact in [controller.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/controller.py:63). | Seeding integration asserts rebuild parity and `outbox_count == 0` in [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:48). Static search found no production `GraphEventStore.append_events` mutation path outside controller, except read-only recovery and tests. | CLOSED |
| MEDIUM-2 fan-out | Compiler emits distinct reader and join nodes in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:217), with reader → join → worker edges. Runtime glob expansion deferral is documented in the compiler module docstring. | Unit test asserts reader template, distinct join template, and both edges in [test_graph_compiler.py](/Users/peter/code/task-world/tests/unit/test_graph_compiler.py:233). | CLOSED |
| MEDIUM-3 snapshot identity | Snapshot now carries deterministic SHA-256 content hash plus `source_path` and `source_ref` in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:140); hash canonicalization is in [compiler.py](/Users/peter/code/task-world/src/orchestrator/graph/compiler.py:770). | Unit hash same/different coverage in [test_graph_compiler.py](/Users/peter/code/task-world/tests/unit/test_graph_compiler.py:41); integration source threading in [test_graph_routine_compile.py](/Users/peter/code/task-world/tests/integration/test_graph_routine_compile.py:82). | CLOSED |

**New Findings**

| severity | finding | evidence |
|---|---|---|
| HIGH | Generic callback output-record acceptance can forge another node’s output and bind downstream required inputs. `_accepted_output_record_events` only defaults `producer_node_id`; it does not require it to equal the callback lease node, and `_input_bound_events_for_record` binds by producer/port only, with no schema/edge-selector/authority validation in [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:273). I reproduced an active `verifier-evil` lease submitting an output record with `producer_node_id="worker-1"` and wrong schema; the kernel emitted `callback_accepted`, `output_record_accepted`, and `input_bound`, then scheduled the consumer while `worker-1` was still `planned`. This violates the controller validation model in §19/§21 and can bypass required data provenance. |
