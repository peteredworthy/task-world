**Re-Derived Criteria**
1. Collect tracked and untracked git status before accepting worker/check/verifier output.
2. Collect ignored paths, because ignored files are not automatically safe.
3. Classify every tracked, untracked, and ignored path through a pure deterministic `classify_file_state` API.
4. `tool_cache`: known cache patterns may be captured/classified as ephemeral and not restored downstream.
5. `build_output`: captured only when declared or explicitly ephemeral.
6. `test_artifact`: captured only when declared by a check/verifier node.
7. `secret`: hard reject, never capture into snapshot storage, and do not expose raw content to a model.
8. `unknown_ignored`: warn-and-capture, not hard reject, with `needs_gatekeeper=true`.
9. `external_artifact`: capture by manifest with path/hash/origin/retention, or hard reject repo escapes.
10. Warn-and-capture amendment: non-secret/non-escaping residue is recorded and captured; hard rejection is only secret-suspect or repo-escaping paths.
11. Boundary emits durable file-state records with classifications/residue/rejections; residue report is rebuilt from stored events.
12. Accepted boundary snapshots use git plumbing refs, not `patch_bundle`, and hooks never fire.
13. Accepted file-state records bind to downstream inputs; success must depend on accepted callback plus accepted boundary/file-state record.
14. Replay/projections are deterministic and never rerun git, filesystem scans, classifier side effects, or model gatekeeper.
15. File-state records obey callback provenance rules: a worker cannot submit a file-state record for another node.

**Criteria Table**

| # | criterion | code evidence | test evidence | status |
|---:|---|---|---|---|
| 1 | Collect tracked/untracked git status | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:41) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:156) | Covered, not executed |
| 2 | Collect ignored paths | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:41) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:158) | Covered, not executed |
| 3 | Pure deterministic classifier | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:124) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:144) | Covered, not executed |
| 4 | `tool_cache` row | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:193) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:66) | Partial: classified, downstream non-restore untested |
| 5 | `build_output` row | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:181) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:72) | Covered, not executed |
| 6 | `test_artifact` row | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:181) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:88) | Covered, not executed |
| 7 | `secret` hard reject/no snapshot | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:178), [runtime](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:80) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:177) | Partial: root secret covered; nested ignored secret gap |
| 8 | `unknown_ignored` warn-capture + gatekeeper flag | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:196) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:112) | Covered, not executed |
| 9 | `external_artifact` manifest or repo escape reject | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:170) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:101) | UNMET for manifest path/hash/origin/retention |
| 10 | Reject only secret/escape; capture other residue | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:145) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:132) | Partial |
| 11 | Durable records and event-sourced residue report | [runtime](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:124), [projection](/Users/peter/code/task-world/src/orchestrator/graph/projections.py:266) | [e2e](/Users/peter/code/task-world/tests/integration/test_graph_runner_e2e.py:379) | Covered, not executed |
| 12 | Git plumbing snapshot, no patch bundle/hooks | [snapshot.py](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:37), [snapshot.py](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:74) | [snapshot test](/Users/peter/code/task-world/tests/unit/test_git_snapshot.py:149) | Existing covered; new force/exclude untested |
| 13 | Bind file-state downstream | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:445) | No dedicated file-state binding test | UNMET |
| 14 | Replay deterministic; no git/classifier rerun | [projection](/Users/peter/code/task-world/src/orchestrator/graph/projections.py:266) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:162) | Covered, not executed |
| 15 | File-state provenance validation | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:339) | No dedicated forged `file_state` test | UNMET |

**Findings**

| severity | type | description | location |
|---|---|---|---|
| High | Security | Ignored directories are force-included as whole pathspecs. If git reports `! secrets/`, a nested `secrets/key.pem` is never individually classified, then `git add -f -- secrets/` can capture it into the snapshot. This violates “secret-like files are never captured,” especially when other residue is force-included. | [runtime collect](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:45), [force include](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:99), [snapshot add](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:40) |
| High | Liveness | On `file_state_rejected`, dispatch submits `complete_node=False`, records rejection, then the runner task exits successfully. The projection keeps the worker `running` and lease `active`; there is no immediate cleanup/retry path in this flow. Recovery appears to depend on later restart/reconcile or agent death, not on the rejection itself. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:229), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:307), [test assertion](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:177) |
| Medium | Validation | Accepted `file_state` records probably inherit generic output-record provenance checks, but there is no dedicated forged-file-state test. `file_state_rejected` payloads are weaker: `node_id` is only `setdefault`, so a payload-supplied mismatched node id is not overwritten or rejected. | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:360) |
| Medium | Spec gap | The §20.3 `external_artifact` row requires manifest metadata with path/hash/origin/retention. Current code models only entries/classifications and tests only repo-escape rejection. | [models.py](/Users/peter/code/task-world/src/orchestrator/graph/models.py:188), [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:101) |
| Medium | Test gap | Secret “not captured” is not asserted against the actual git tree object. The integration test asserts no `file_state_accepted` for a root `fake_key.pem`, but it does not inspect snapshot refs and does not cover nested ignored secret files. | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:197) |
| Low | Test determinism | The secret fixture uses `os.urandom(128)`. It is overwhelmingly likely to exceed entropy threshold, but deterministic slice fixtures should use fixed bytes. | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:113) |
| Low | Snapshot tests | `force_include_paths`/`exclude_paths` are additive and use `--`, so leading `-` option injection is mitigated, but there is no test for leading-dash paths or pathspec magic. | [snapshot.py](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:46), [safe pathspecs](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:210) |

**Checks Run**
`uv run pytest ...` failed immediately because the sandbox cannot open `/Users/peter/.cache/uv`. Fallback `.venv/bin/pytest ...` also failed before collection because Python has no writable temp directory in this read-only session, so kernel timing is unavailable. `.venv/bin/ruff check src tests` passed. Purity import grep for `subprocess`, `os`, and `pathlib` in `src/orchestrator/graph/file_state.py` returned no matches. No `unittest.mock`, `MagicMock`, `patch`, or `monkeypatch` usage was found in the slice tests.

**Verdict: BOUNCE**

The slice has the right broad shape, but I would not accept it yet. The ignored-directory force-include path can plausibly snapshot nested secret-like files without ever classifying them, and the rejection flow leaves a managed worker in a running/active-lease state after the process has exited. Those are boundary safety and recovery issues, not punchlist polish.
tokens used
131,883
**Re-Derived Criteria**
1. Collect tracked and untracked git status before accepting worker/check/verifier output.
2. Collect ignored paths, because ignored files are not automatically safe.
3. Classify every tracked, untracked, and ignored path through a pure deterministic `classify_file_state` API.
4. `tool_cache`: known cache patterns may be captured/classified as ephemeral and not restored downstream.
5. `build_output`: captured only when declared or explicitly ephemeral.
6. `test_artifact`: captured only when declared by a check/verifier node.
7. `secret`: hard reject, never capture into snapshot storage, and do not expose raw content to a model.
8. `unknown_ignored`: warn-and-capture, not hard reject, with `needs_gatekeeper=true`.
9. `external_artifact`: capture by manifest with path/hash/origin/retention, or hard reject repo escapes.
10. Warn-and-capture amendment: non-secret/non-escaping residue is recorded and captured; hard rejection is only secret-suspect or repo-escaping paths.
11. Boundary emits durable file-state records with classifications/residue/rejections; residue report is rebuilt from stored events.
12. Accepted boundary snapshots use git plumbing refs, not `patch_bundle`, and hooks never fire.
13. Accepted file-state records bind to downstream inputs; success must depend on accepted callback plus accepted boundary/file-state record.
14. Replay/projections are deterministic and never rerun git, filesystem scans, classifier side effects, or model gatekeeper.
15. File-state records obey callback provenance rules: a worker cannot submit a file-state record for another node.

**Criteria Table**

| # | criterion | code evidence | test evidence | status |
|---:|---|---|---|---|
| 1 | Collect tracked/untracked git status | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:41) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:156) | Covered, not executed |
| 2 | Collect ignored paths | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:41) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:158) | Covered, not executed |
| 3 | Pure deterministic classifier | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:124) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:144) | Covered, not executed |
| 4 | `tool_cache` row | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:193) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:66) | Partial: classified, downstream non-restore untested |
| 5 | `build_output` row | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:181) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:72) | Covered, not executed |
| 6 | `test_artifact` row | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:181) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:88) | Covered, not executed |
| 7 | `secret` hard reject/no snapshot | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:178), [runtime](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:80) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:177) | Partial: root secret covered; nested ignored secret gap |
| 8 | `unknown_ignored` warn-capture + gatekeeper flag | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:196) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:112) | Covered, not executed |
| 9 | `external_artifact` manifest or repo escape reject | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:170) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:101) | UNMET for manifest path/hash/origin/retention |
| 10 | Reject only secret/escape; capture other residue | [file_state.py](/Users/peter/code/task-world/src/orchestrator/graph/file_state.py:145) | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:132) | Partial |
| 11 | Durable records and event-sourced residue report | [runtime](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:124), [projection](/Users/peter/code/task-world/src/orchestrator/graph/projections.py:266) | [e2e](/Users/peter/code/task-world/tests/integration/test_graph_runner_e2e.py:379) | Covered, not executed |
| 12 | Git plumbing snapshot, no patch bundle/hooks | [snapshot.py](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:37), [snapshot.py](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:74) | [snapshot test](/Users/peter/code/task-world/tests/unit/test_git_snapshot.py:149) | Existing covered; new force/exclude untested |
| 13 | Bind file-state downstream | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:445) | No dedicated file-state binding test | UNMET |
| 14 | Replay deterministic; no git/classifier rerun | [projection](/Users/peter/code/task-world/src/orchestrator/graph/projections.py:266) | [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:162) | Covered, not executed |
| 15 | File-state provenance validation | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:339) | No dedicated forged `file_state` test | UNMET |

**Findings**

| severity | type | description | location |
|---|---|---|---|
| High | Security | Ignored directories are force-included as whole pathspecs. If git reports `! secrets/`, a nested `secrets/key.pem` is never individually classified, then `git add -f -- secrets/` can capture it into the snapshot. This violates “secret-like files are never captured,” especially when other residue is force-included. | [runtime collect](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:45), [force include](/Users/peter/code/task-world/src/orchestrator/graph_runtime/file_state.py:99), [snapshot add](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:40) |
| High | Liveness | On `file_state_rejected`, dispatch submits `complete_node=False`, records rejection, then the runner task exits successfully. The projection keeps the worker `running` and lease `active`; there is no immediate cleanup/retry path in this flow. Recovery appears to depend on later restart/reconcile or agent death, not on the rejection itself. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:229), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:307), [test assertion](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:177) |
| Medium | Validation | Accepted `file_state` records probably inherit generic output-record provenance checks, but there is no dedicated forged-file-state test. `file_state_rejected` payloads are weaker: `node_id` is only `setdefault`, so a payload-supplied mismatched node id is not overwritten or rejected. | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:360) |
| Medium | Spec gap | The §20.3 `external_artifact` row requires manifest metadata with path/hash/origin/retention. Current code models only entries/classifications and tests only repo-escape rejection. | [models.py](/Users/peter/code/task-world/src/orchestrator/graph/models.py:188), [unit test](/Users/peter/code/task-world/tests/unit/test_graph_file_state.py:101) |
| Medium | Test gap | Secret “not captured” is not asserted against the actual git tree object. The integration test asserts no `file_state_accepted` for a root `fake_key.pem`, but it does not inspect snapshot refs and does not cover nested ignored secret files. | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:197) |
| Low | Test determinism | The secret fixture uses `os.urandom(128)`. It is overwhelmingly likely to exceed entropy threshold, but deterministic slice fixtures should use fixed bytes. | [boundary test](/Users/peter/code/task-world/tests/integration/test_graph_file_state_boundary.py:113) |
| Low | Snapshot tests | `force_include_paths`/`exclude_paths` are additive and use `--`, so leading `-` option injection is mitigated, but there is no test for leading-dash paths or pathspec magic. | [snapshot.py](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:46), [safe pathspecs](/Users/peter/code/task-world/src/orchestrator/git/snapshot.py:210) |

**Checks Run**
`uv run pytest ...` failed immediately because the sandbox cannot open `/Users/peter/.cache/uv`. Fallback `.venv/bin/pytest ...` also failed before collection because Python has no writable temp directory in this read-only session, so kernel timing is unavailable. `.venv/bin/ruff check src tests` passed. Purity import grep for `subprocess`, `os`, and `pathlib` in `src/orchestrator/graph/file_state.py` returned no matches. No `unittest.mock`, `MagicMock`, `patch`, or `monkeypatch` usage was found in the slice tests.

**Verdict: BOUNCE**

The slice has the right broad shape, but I would not accept it yet. The ignored-directory force-include path can plausibly snapshot nested secret-like files without ever classifying them, and the rejection flow leaves a managed worker in a running/active-lease state after the process has exited. Those are boundary safety and recovery issues, not punchlist polish.
