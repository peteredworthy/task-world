# Slice 1.9 Audit Report

Verdict: **BOUNCE**

## Re-Derived Acceptance Criteria

1. §17.1 Run lifecycle must permit scheduling.
2. §17.2 Only nodes in `planned` or `blocked` may become ready candidates.
3. §17.3 All required input ports must have accepted input bindings.
4. §17.4 Failed, cancelled, or pending-appeal upstream required dependencies block by default, while recovery/oversight/revision policy may explicitly consume failures.
5. §17.5 Any human gate input must be approved before successors are ready.
6. §17.6 Resource claims must be valid and compatible with active leases.
7. §17.7 Retired nodes must not be schedulable.
8. §17.8 Node-specific preconditions must pass.
9. §17 ordering must be deterministic by priority, graph region order, creation event position, then lexical node id.
10. §17 optional inputs do not block when absent, but must satisfy schema/snapshot compatibility if present.
11. §18.1 External claims must include an `external_resource_key`.
12. §18 path rule 1: paths are repository-relative POSIX paths.
13. §18 path rule 2: normalize `.`/`..` and reject root escapes.
14. §18 path rule 3: use deterministic glob handling.
15. §18 path rule 4: directory claims expand recursively.
16. §18 matrix `read x read`: compatible for same/stable snapshots.
17. §18 matrix `read x write`: conflict on overlapping live paths; snapshot read is compatible.
18. §18 matrix `read x graph_write`: compatible, controller serializes graph write.
19. §18 matrix `read x review_write`: conflict when review touches same live paths.
20. §18 matrix `read x external`: compatible unless external declaration is exclusive.
21. §18 matrix `write x read`: conflict unless requested read uses immutable snapshot.
22. §18 matrix `write x write`: conflict in same run worktree in v1.
23. §18 matrix `write x graph_write`: compatible unless patch touches active writer lease.
24. §18 matrix `write x review_write`: conflict.
25. §18 matrix `write x external`: compatible unless external declaration is exclusive.
26. §18 matrix `graph_write x read`: compatible.
27. §18 matrix `graph_write x write`: compatible unless patch touches active writer lease.
28. §18 matrix `graph_write x graph_write`: conflict/serialized.
29. §18 matrix `graph_write x review_write`: compatible unless review graph is being patched.
30. §18 matrix `graph_write x external`: compatible.
31. §18 matrix `review_write x read`: conflict if live paths overlap.
32. §18 matrix `review_write x write`: conflict.
33. §18 matrix `review_write x graph_write`: compatible unless patch touches review region.
34. §18 matrix `review_write x review_write`: conflict.
35. §18 matrix `review_write x external`: compatible unless external declaration is exclusive.
36. §18 matrix `external x read`: compatible unless external declaration is exclusive.
37. §18 matrix `external x write`: compatible unless external declaration is exclusive.
38. §18 matrix `external x graph_write`: compatible.
39. §18 matrix `external x review_write`: compatible unless external declaration is exclusive.
40. §18 matrix `external x external`: conflict by matching key when either side writes or is exclusive; read-only same-key is compatible.
41. §18.2 default policy: many readers may run over the same stable snapshot.
42. §18.2 default policy: a write node requires exclusive write lease for the run worktree.
43. §18.2 default policy: live-worktree readers cannot run while a writer is running.
44. §18.2 default policy: immutable snapshot readers may run during a writer.
45. §18.2 default policy: graph patch application is single-threaded.
46. §18.2 default policy: destructive review operations require exclusive write authority.
47. §15.6 planner `planned -> ready` when planning inputs are available.
48. §15.6 planner `ready -> leased` when scheduler grants lease.
49. §15.6 planner `leased -> running` when planner starts.
50. §15.6 planner `running -> completed` when graph patch proposal is received and processed.
51. §15.6 planner `running -> failed` on planner runtime failure.
52. §15.6 planner completion must not imply patch acceptance.
53. §15.7 review `planned -> ready` when review inputs are available.
54. §15.7 review `ready -> leased/blocked` by scheduler or human gate.
55. §15.7 review `leased -> running` when review action starts.
56. §15.7 review `running -> completed` when review record/file-state is accepted.
57. §15.7 review `running -> failed` when review action cannot complete.

## Criteria Table

| # | criterion | code evidence | test evidence | status |
|---:|---|---|---|---|
| 1 | Run lifecycle permits scheduling | `evaluate_readiness` returns `run_not_active` at `src/orchestrator/graph/scheduler.py:113`; schedule tick uses projection run state at `src/orchestrator/graph/commands.py:297` | `tests/unit/test_scheduler.py:79`; `tests/fixtures/graph/readiness.yaml:69` | MET |
| 2 | Node state must be `planned`/`blocked` | `src/orchestrator/graph/scheduler.py:115`; schedule tick considers planned/blocked/ready at `src/orchestrator/graph/commands.py:290` | `tests/unit/test_scheduler.py:72`; `tests/unit/test_graph_commands.py:309`; fixture `tests/fixtures/graph/invariants.yaml:48` | MET |
| 3 | Required inputs must be bound | `src/orchestrator/graph/projections.py:163`, `:403`; readiness checks `satisfied_input_ports` at `src/orchestrator/graph/scheduler.py:119` | `tests/unit/test_scheduler.py:111`; `tests/unit/test_graph_commands.py:339`; fixture `tests/fixtures/graph/invariants.yaml:35` | MET |
| 4 | Failed/cancelled/pending-appeal upstream blocks unless recovery policy allows | `src/orchestrator/graph/scheduler.py:124`; recovery/oversight/revision exception at `src/orchestrator/graph/scheduler.py:329` | `tests/unit/test_scheduler.py:129`, `:144`, `:160`, `:176`; adversarial probe observed `upstream_failed:producer-1` and recovery/oversight ready | MET |
| 5 | Human gate input must be approved | gate decisions reduced at `src/orchestrator/graph/projections.py:361`; readiness blocks at `src/orchestrator/graph/scheduler.py:134` | `tests/unit/test_scheduler.py:192`, `:208`; `tests/unit/test_graph_commands.py:365`, `:392`; fixtures `tests/fixtures/graph/invariants.yaml:116`, `:130` | MET |
| 6 | Resource claims valid and compatible | compatibility implemented in `src/orchestrator/graph/scheduler.py:79`; active claims wired at `src/orchestrator/graph/commands.py:277` | compatibility tests `tests/unit/test_scheduler.py:256`, `:294`, `:329`, `:337`, `:345`; validity for external key missing has no test | PARTIAL |
| 7 | Retired nodes not schedulable | state gate in `src/orchestrator/graph/scheduler.py:115`; retired projection in `src/orchestrator/graph/projections.py:159` | fixture `tests/fixtures/graph/readiness.yaml:60`; schedule/evaluate indirectly rejects via state | MET |
| 8 | Node-specific preconditions pass | no general node-specific precondition field or evaluator found in `NodeScheduleInfo` (`src/orchestrator/graph/scheduler.py:43`) or `evaluate_readiness` (`src/orchestrator/graph/scheduler.py:107`) | no targeted test/fixture for criterion 8 | UNMET |
| 9 | Scheduling order deterministic | sort key at `src/orchestrator/graph/scheduler.py:166` | `tests/unit/test_scheduler.py:235`, `:244` | MET |
| 10 | Optional inputs do not block | optional edges skipped at `src/orchestrator/graph/scheduler.py:119` and `:124` | `tests/unit/test_scheduler.py:120`; adversarial probe observed ready | MET |
| 11 | External claims require `external_resource_key` | not enforced; `_external_claims_conflict` returns compatible when key is `None` at `src/orchestrator/graph/scheduler.py:218`; Pydantic model has optional key at `src/orchestrator/graph/models.py:77` | no test; adversarial probe observed missing-key external claims compatible | UNMET |
| 12 | POSIX repo-relative paths | `posixpath.normpath` used at `src/orchestrator/graph/scheduler.py:250`; absolute paths invalid at `:247` | path tests `tests/unit/test_scheduler.py:310`, `:317` | MET |
| 13 | Normalize dot/dotdot and reject escapes | invalid escape detection at `src/orchestrator/graph/scheduler.py:253`; invalid claims conflict at `:209` | `tests/unit/test_scheduler.py:310`, `:317`; adversarial probe observed `../outside` conflicting | MET |
| 14 | Deterministic glob handling | fnmatch/normalized overlap at `src/orchestrator/graph/scheduler.py:264`, `:276`, `:290` | `tests/unit/test_scheduler.py:302`, `:306`; adversarial probe observed `src/**` overlap and disjoint roots | MET |
| 15 | Directory claims recursive | literal prefix overlap at `src/orchestrator/graph/scheduler.py:307` | `tests/unit/test_scheduler.py:321`; probe `src/**` vs `src/a/b/c.py` conflicts | MET |
| 16-40 | All 25 §18 matrix cells | `claims_conflict` dispatches modes at `src/orchestrator/graph/scheduler.py:79`; review at `:315`; external at `:218` | all 25 cells listed in `tests/unit/test_scheduler.py:256`; adversarial probes covered required high-risk cells | MET except external-key validity criterion |
| 41 | Many stable snapshot readers may run | read/read returns compatible at `src/orchestrator/graph/scheduler.py:101` | `tests/unit/test_scheduler.py:102`, `:358`; fixture `tests/fixtures/graph/readiness.yaml:41` | MET |
| 42 | Write requires exclusive worktree write lease | write/write conflict at `src/orchestrator/graph/scheduler.py:94` | `tests/unit/test_scheduler.py:256`, `:362` | MET |
| 43 | No live reader during writer | read/write snapshot checks at `src/orchestrator/graph/scheduler.py:96` | `tests/unit/test_scheduler.py:337`; adversarial live read/write conflicted | MET |
| 44 | Snapshot reader may run during writer | snapshot checks at `src/orchestrator/graph/scheduler.py:98`, `:100` | `tests/unit/test_scheduler.py:329`; adversarial snapshot read/write compatible | MET |
| 45 | Graph patch application serialized | graph_write/graph_write conflict at `src/orchestrator/graph/scheduler.py:85`; patch command single output path at `src/orchestrator/graph/commands.py:221` | `tests/unit/test_scheduler.py:256`; adversarial graph_write/graph_write conflicted | MET |
| 46 | Destructive review requires exclusive write authority | review_write conflict logic at `src/orchestrator/graph/scheduler.py:315` | `tests/unit/test_scheduler.py:256`; adversarial review_write/write conflicted | MET |
| 47 | Planner planned -> ready | projection can store ready via `node_state_changed` at `src/orchestrator/graph/projections.py:154` | fixture `tests/fixtures/graph/node_lifecycle_planner.yaml:1` | MET as fixture evidence only |
| 48 | Planner ready -> leased | schedule tick grants lease at `src/orchestrator/graph/commands.py:323` | fixture `tests/fixtures/graph/node_lifecycle_planner.yaml:10` | MET |
| 49 | Planner leased -> running | projection stores state change at `src/orchestrator/graph/projections.py:154` | fixture `tests/fixtures/graph/node_lifecycle_planner.yaml:20` injects state change | MET as fixture evidence only |
| 50 | Planner running -> completed | callback command emits completed state at `src/orchestrator/graph/commands.py:195` | fixture `tests/fixtures/graph/node_lifecycle_planner.yaml:29` | MET |
| 51 | Planner running -> failed | callback command accepts `new_state` at `src/orchestrator/graph/commands.py:203` | fixture `tests/fixtures/graph/node_lifecycle_planner.yaml:40` | MET |
| 52 | Planner completion independent of patch acceptance | patch rejection emits only `graph_patch_rejected` at `src/orchestrator/graph/commands.py:242`; planner state unchanged by reducer | fixture `tests/fixtures/graph/node_lifecycle_planner.yaml:51`; adversarial probe observed `planner_state=completed` and rejection event present | MET |
| 53 | Review planned -> ready | projection can store ready via `node_state_changed` at `src/orchestrator/graph/projections.py:154` | fixture `tests/fixtures/graph/node_lifecycle_review.yaml:1` | MET as fixture evidence only |
| 54 | Review ready -> leased/blocked | scheduler grants lease at `src/orchestrator/graph/commands.py:323`; blocked state projection at `src/orchestrator/graph/projections.py:154` | fixtures `tests/fixtures/graph/node_lifecycle_review.yaml:10`, `:20` | MET |
| 55 | Review leased -> running | projection stores state change at `src/orchestrator/graph/projections.py:154` | fixture `tests/fixtures/graph/node_lifecycle_review.yaml:28` injects state change | MET as fixture evidence only |
| 56 | Review running -> completed | callback command emits completed state at `src/orchestrator/graph/commands.py:195` | fixture `tests/fixtures/graph/node_lifecycle_review.yaml:37` | MET |
| 57 | Review running -> failed | callback command accepts `new_state` at `src/orchestrator/graph/commands.py:203` | fixture `tests/fixtures/graph/node_lifecycle_review.yaml:48` | MET |

## Fresh Test Run

Command:

```bash
UV_CACHE_DIR=/private/tmp/task-world-uv-cache uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q
```

Result: `133 passed in 1.27s`; shell wall time recorded as `1` second. The first attempt without `UV_CACHE_DIR` failed before test execution due to `/Users/peter/.cache/uv` permission denial.

## Adversarial Probes

| attack | observed result |
|---|---|
| required input port unbound | `ready=False`, reason `missing_required_input:candidate` |
| optional input unbound | `ready=True`, reason empty |
| upstream required dependency failed | `ready=False`, reason `upstream_failed:producer-1` |
| recovery/oversight node consuming same failure | both `ready=True` |
| gate undecided | `ready=False`, reason `gate_not_approved:gate-1` |
| gate rejected | `ready=False`, reason `gate_not_approved:gate-1` |
| gate approved | `ready=True` |
| glob overlap `write src/**` vs live `read src/foo.py` | conflict `True` |
| same glob overlap with reader `snapshot_id=S0` | compatible `False` conflict |
| `src/**` vs `docs/**` | no conflict |
| path escape `../outside` | treated conflicting |
| external same key, one exclusive | conflict |
| external different keys | compatible |
| `review_write` vs `write` | conflict |
| `graph_write` vs `graph_write` | conflict |
| `graph_write` vs `write` | compatible |
| planner completed but patch rejected | output `graph_patch_rejected`; planner projection remains `completed` |
| 1.8 configured undecided gate blocks §14 accepted | task remains `pending` |
| 1.8 snapshot mismatch | callback rejected stale with reason `snapshot_incompatible` |
| extra: external claim missing key | missing-key external claims are compatible instead of rejected/conservative |

## Laziness Check

- Matrix cells without dedicated test: 0 of 25 if `tests/unit/test_scheduler.py:256` is accepted as the dedicated matrix-table test. Additional focused tests cover snapshot read/write, live read/write, review/external, path, and glob cases. However, `tests/fixtures/graph/COVERAGE.md` has 0 rows for §18, so the fixture coverage index does not record the matrix coverage.
- §15.6/§15.7 table rows without a fixture: 0 missing by count. Planner has 6 fixture scenarios for 5 table rows plus the independent patch-acceptance rule. Review has 6 scenarios for 5 rows, splitting `ready -> leased/blocked`.
- Readiness reasons asserted only as truthy: no. Exact strings are asserted in `tests/unit/test_scheduler.py:117`, `:141`, `:157`, `:205`, `:374`, and `tests/unit/test_graph_commands.py:360`, `:387`.
- `node_deferred`/`node_ready` events emitted but never reduced or asserted: emitted at `src/orchestrator/graph/commands.py:306`, `:328`, `:352`; asserted in `tests/unit/test_graph_commands.py:301`, `:331`, `:360`, `:387`, `:415` and fixtures `tests/fixtures/graph/invariants.yaml:38`, `:50`, `:119`, `:132`. They are not independently reduced by `reduce_event`; projection state comes from accompanying `node_state_changed`.
- Glob shortcuts: implementation uses normalized POSIX paths plus `fnmatch`; `src/**` vs `src/a/b/c.py` conflicts and `src/**` vs `docs/**` does not. `src/*.py` also conflicts with `src/a/b.py`, which is conservative rather than false-compatible.
- COVERAGE.md spot-checks: §15.6 rows 52-57 match actual planner fixture names; §15.7 rows 58-63 match review fixture names; §17 rows 71-78 exist but readiness.yaml scenarios are mostly projection-only state injections, not criterion-specific command behavior; §19 snapshot row 84 points to a real command fixture in `invariants.yaml`; §18 has no rows despite matrix tests.

## Lies Check

- Builder claim `133 passed in 1.27s`: verified by fresh run with `UV_CACHE_DIR`.
- Builder claim matrix completion: mostly verified by the 25-case test and probes, but external claim validity is missing and §18 is absent from `COVERAGE.md`.
- Builder claim criteria 3-5 with explicit reasons: verified by grep and probes. Required input, upstream failed, and gate-not-approved reasons are exact.
- Determinism grep over `src/orchestrator/graph` for `filesystem|glob.glob|os.walk|datetime.now|random|uuid`: no matches. Pure `posixpath`/`fnmatch` use is present and acceptable.

## Testing Standards

- No `patch`, `MagicMock`, or monkeypatching in the focused new graph tests. Grep only matched the helper named `_patch` in `test_patch_validator.py`.
- Focused suite is pure/in-memory and under 5 seconds: `133 passed in 1.27s`.
- No DB, HTTP, agents, or filesystem walks are used by the graph kernel tests inspected.

## Findings

| severity | type | description | location |
|---|---|---|---|
| HIGH | Spec gap | §17 criterion 8 has no implementation surface or test evidence. `evaluate_readiness` has no node-specific precondition field/callback/predicate, so the criterion cannot fail closed when a node kind has a required precondition. | `src/orchestrator/graph/scheduler.py:43`, `src/orchestrator/graph/scheduler.py:107`; no matching test |
| MEDIUM | Spec gap | §18 says external claims must include `external_resource_key`, but both the graph Pydantic model and scheduler helper allow missing keys. Two missing-key external claims are treated compatible, not rejected or conservative. | `src/orchestrator/graph/models.py:77`, `src/orchestrator/graph/scheduler.py:218` |
| LOW | Coverage drift | `COVERAGE.md` has no §18 rows, despite the audit target requiring every matrix cell. This makes the coverage index incomplete for the resource matrix. | `tests/fixtures/graph/COVERAGE.md:1` |
| LOW | Fixture weakness | Several planner/review lifecycle fixtures still inject the terminal `node_state_changed` they assert with `when_command: null`. They prove projection storage and fixture presence, not command behavior for those rows. | `tests/fixtures/graph/node_lifecycle_planner.yaml:20`, `tests/fixtures/graph/node_lifecycle_review.yaml:28` |
| LOW | Event reduction ambiguity | `node_ready` and `node_deferred` are emitted and asserted, but not reduced. This is acceptable only if they are intended as activity/audit events rather than projection facts. | `src/orchestrator/graph/commands.py:306`, `src/orchestrator/graph/projections.py:119` |

## Verdict

**BOUNCE**. The major 1.9 behavior paths are real: the focused suite passes, adversarial probes confirm required/optional inputs, failed dependencies, gate approval, snapshot-aware reads, path normalization, matrix conflicts, planner patch rejection independence, and the 1.8 regression checks. However, two acceptance-derived criteria are not actually satisfied: node-specific readiness preconditions have no implementation/test surface, and §18 external resource claim validity is not enforced. The coverage index also omits §18 entirely. These are small fixes, but they are acceptance gaps, so this should bounce to the fixer rather than be accepted with a punchlist.
