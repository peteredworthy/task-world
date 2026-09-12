# Slice 1 implementation ledger

Status: complete; independent Slice 1 validation passed

Final verdict: PASS. The completed implementation and its canonical authority
resolver satisfy every Slice 1 acceptance criterion in the bounded independent
review.

Scope: canonical decision contracts and frozen selection only. This slice does
not activate decision-v1 runtime behavior, start a server, mutate live state,
resume historical runs, run a paid probe, or commit changes.

## Functional requirements

| ID | Required behavior | Acceptance / product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|
| S1-1 | Routine configuration accepts only omitted or `decision-v1`, and the compiled routine snapshot freezes that selection. | Compile fresh temporary routines for omitted/new/unknown values; round-trip snapshot records; validate an old serialized record as legacy. | Focused config/compiler tests. | Accepted | Omission remains an absent snapshot field and retains the captured legacy content hash. |
| S1-2 | One graph-owned resolver determines whether decision-v1 applies from the node contract, trusted role/stage, and the exact bound routine snapshot. | Resolve applicable and non-applicable nodes from a compiled projection; reject unknown, partial, copied, and mismatched authority. | Focused pure resolver tests. | Accepted | `initial_planning` is stamped only for newly selected decision-v1 planner heads so the resolver has one product-real applicable compiled node. Macro-created nodes without an exact snapshot binding fail closed until Slice 2 propagates that authority. The completed authority chain validates both concrete node declarations, the edge through canonical contract owners, selector-to-record agreement, exact unversioned snapshot identity, and effective edge/binding policy agreement. |
| S1-3 | Strict graph-owned Pydantic models define discovery brief, implementation plan, batch decision, correction decision, verification decision, and work result with the normative aliases and discriminators. | Validate representative authored answers; reject whitespace-only required text, invalid aliases, cross-branch/extra fields, duplicate/dangling/cyclic batch keys, and forbidden internal IDs/ops. | Model/schema unit tests. | Accepted | Bound subset/evidence applicability remains a runtime compilation concern for later slices; authored shape and topology checks are complete. |
| S1-4 | Executable check choice has one owner, reuses command-binding semantics, and generates the built-in `orchestrator.reliable-plan.decision-plan@1` declaration and submission schema; legacy plan check strings stay descriptive. | Generate declaration from the Pydantic owner; change propagation is asserted structurally; compiling a decision-v1 routine freezes it; a batch without executable check binding is rejected. | Declaration/compiler/submission-schema tests. | Accepted | None in Slice 1. |
| S1-5 | The graph owns a strict tagged `decision-submission-v1` CAS envelope and frozen request bindings; runners carry a trusted internal submission-invocation envelope while the model-facing schema remains authored `outputs`; legacy `output_records` decoding remains valid. | Round-trip the new envelope and invocation metadata; reject unknown format/schema/contract and partial bindings; render a submit schema containing no trusted metadata; decode legacy payload unchanged. | Runner/submission and graph model tests. | Accepted | Runtime staging/finalization consumption is intentionally deferred to Slice 2. |
| S1-6 | Slice 1 changes no existing runner, tool-catalog, or runtime activation behavior. | Existing legacy compiler/submission/tool-exposure flows remain unchanged in disposable tests; no runtime dispatcher consumes decision-v1 yet. | Focused legacy regressions plus static diff inspection. | Accepted | No dispatch, prompt, graph MCP, adapter or routine YAML files were edited for Slice 1. |

## Starting source hashes

Captured before Slice 1 edits. Files already named by the predecessor validation
match `docs/reviews/recovery-successor-validation-result.json` where recorded.

```text
c44c79e3416f467f101e7a9b21eb9a84d90f60be766518642e60348ea11541d9  src/orchestrator/graph/contracts.py
8927f43e0955bec55509f1476e39054fb77afd1a79e8c9a46f719fcc0896d465  src/orchestrator/graph/models.py
d43a965e2ce6c7e97016df48b86a2c6737db279cbb09e91c47909469413bdabc  src/orchestrator/graph/compiler.py
415a0e61df212027d320c5c27317e74c85673016a9c7d8750e7a5c1446431136  src/orchestrator/graph/semantic_artifacts.py
550fabba523fb7fdf8289cb09a657923649e458c6203ec18b8c911ac778322a3  src/orchestrator/graph/macros.py
55906e4a61b403fc02772457f6829c0d519bd797b262370f2332618c3fc7ccd3  src/orchestrator/graph/command_bindings.py
513c93d98f94d1930df49da046b888af438aa303ee96079031cfa128e3e91dfa  src/orchestrator/config/models.py
741699a22f12b6471dd7bda5c2b319247705251c81dac030f934377b77f6a747  src/orchestrator/runners/types.py
803d0b95e57007851a16b91a3b51b55376ec56295a12879ae5ee882e47b29782  src/orchestrator/runners/submission.py
204ffde0ce6325ebb7046206e4a747a5f98ebe91847422fe174708f89120af10  src/orchestrator/graph/__init__.py
c5ed2776b55088bfc43cde6d6d30ece41b0b95d8939d40c8985afb5c0c161d40  src/orchestrator/config/__init__.py
0ae6b8ff201fdfa609e97626465a5fc19efa1a7bed8f451ccd68f97b743701fa  src/orchestrator/runners/__init__.py
```

## Builder changes

- `config/models.py` and its public export now own the optional validated
  `agent_interaction_contract`. Omission is legacy.
- `graph/models.py` keeps historical `RoutineSnapshotRecord` values valid while
  admitting the frozen decision-v1 selection. The `initial_planning` semantic
  stage is emitted only for a decision-v1 compiled planner head; no runtime
  consumer was activated.
- New `graph/decisions.py` owns strict authored answer families, aliases,
  discriminators, executable `CheckChoice`, generated decision-plan declaration,
  exact-snapshot applicability resolution, the tagged CAS envelope, canonical
  answer hash and explicit-contract legacy decoder.
- `graph/compiler.py` freezes the selection, keeps omitted-selection content
  hashes stable, emits the generated declaration exactly once, and rejects a
  conflicting authored claim to the built-in identity.
- The macro-local `ReliablePlanCheckDecision` class and its handwritten schema
  helper were removed. `graph/macros.py` re-exports compatibility aliases backed
  by the new single owner, so existing tool consumers did not change.
- `runners/types.py` adds frozen trusted `SubmissionInvocation` delivery
  metadata to the existing callback union. `runners/submission.py` was not
  changed; the model-facing schema remains authored `outputs` only.
- Public graph/config/runner exports and focused contract tests were added.
- The correction pass added the exported typed
  `DecisionContractResolutionError`, made recognized decision-capable stages
  fail closed on missing or malformed snapshot authority, checked bound
  positions against the canonical record/binding authority, and rejected a
  decision-v1 snapshot on an unrecognized role/stage. Pre-store compiler output
  admits only its exact `record=None`, `record_bound=-1`, `bound_at=0` sentinel;
  durable authority requires
  `0 <= record.graph_position <= record_bound_position == bound_at_position`.
- Snapshot selection is now resolved through one exact-binding helper before
  target applicability is evaluated. A node carrying an authenticated
  decision-v1 snapshot cannot turn an invalid target role or canonical contract
  into legacy-style non-applicability; a valid legacy snapshot still resolves
  to `None`.
- Exact snapshot provenance additionally requires the binding edge's source
  port to equal the canonical `RoutineSnapshotRecord.port`. The resolver still
  admits both contract-valid snapshot port spellings, but it cannot combine a
  record authored on one with an edge claiming the other. Its producer kind
  must resolve through the registry to the canonical routine-snapshot contract,
  its explicit role must be allowed by that contract, and the authoritative
  edge must be an `input_binding`, never a state-only dependency.
- Submission requests now select authority by requiring exactly one
  `routine_snapshot` port row, then require that row to name the protected
  snapshot ID and carry the fully typed unversioned `RoutineSnapshot` contract.
  The same record may be bound to a different port without being mistaken for
  a second snapshot authority; exact duplicate port/record identities still
  reject. Authored answers are deeply
  frozen with the graph's existing JSON primitives while retaining their
  canonical dump and digest. Executable argv interpretation is again delegated
  exclusively to `check_command_invocation`, preserving legacy macro behavior.
- `docs/ARCHITECTURE.md` now lists `graph/decisions.py` in the graph directory
  map, as required for a new module.
- The comprehensive authority closure reuses `validate_node_payload`,
  `validate_edge_payload`, `record_selector_matches` and
  `binding_policy_for_edge` rather than creating parallel graph semantics. It
  requires a concrete required `routine_snapshot` input on the target and the
  matching graph-record output on the producer, a required input-binding edge,
  a valid selector matching the canonical record, cardinality-compatible equal
  effective policies, and an exact unversioned `RoutineSnapshotRecord`.
  `gap_planning` is admitted as a declared semantic stage so every stage owned
  by the decision-family resolver can be represented and validated, without a
  runtime consumer.

Files already dirty before this slice were preserved. In particular, unrelated
recovery hunks already present in `graph/models.py`, `graph/compiler.py`,
`graph/macros.py`, `graph/__init__.py` and `runners/__init__.py` were not reverted
or attributed to Slice 1.

## Accepted implementation choices

- Legacy is represented by omission/`None`, not a new serialized `legacy`
  routine value. The explicit decoder receives trusted resolved authority as
  either `legacy` or `decision-v1`; it never guesses from payload shape.
- Hash fields use the repository's canonical `sha256:<64 lowercase hex>` form.
- A bound input requires the schema-version field even when its value is `null`,
  preserving exact unversioned historical records without treating a missing
  field as complete.
- Nested command definitions keep the existing extensible command boundary;
  the outer answer/check models forbid extras.
- `initial_planning` was essential to prove resolver applicability through the
  real compiler, so it is stamped only under the new frozen selection and has no
  runtime consumer in this slice.

## Final source hashes

```text
6644ef75a112e0d4a26541453d63964ef07cbbb8d82422680c43d0d2f8f38663  src/orchestrator/config/models.py
5bd05ead6faed0e3d48c1b92e173fdb21a5a77b567048eb37e99e2d7bdcefcff  src/orchestrator/config/__init__.py
901220bf407b8a5c820a603d97a3b3afa8bab6ed48ab551b480fb0817cd9e91e  src/orchestrator/graph/models.py
6b86a9b1d769e665448ca6d4e6c0e166f6c967595568e0ed32c714c92c813e86  src/orchestrator/graph/compiler.py
7f8371106e513c8cd8abe727299315a4bbcb137692dfbab9fa00c1ae9f9a997b  src/orchestrator/graph/macros.py
affe517dc2a03a57feb4467d5809cfebc394a78f0c25fe45735a31bf877f83d5  src/orchestrator/graph/decisions.py
93512fa2e2bf0fe563bb86439ed4aad822dd3a8dcb2e1a6ab49ec890172cbd0b  src/orchestrator/graph/__init__.py
8310eeebae90de12a0bd5342f61c73b6564c97cf2414332965e4af97dbf16a26  src/orchestrator/runners/types.py
ed98c64cb3af3ffb5a12fd519def3585e14c73a8b48a087cf066f49321d69d96  src/orchestrator/runners/__init__.py
5de61e82c761af29413ea2f072776da634c59147cdf74ce1a47a0ea09362dc32  tests/unit/test_graph_decisions.py
d846b43974780cd51dc7411b12d7b556583c72226697920b82a7ed720320ad22  docs/ARCHITECTURE.md
```

The ledger hash is intentionally captured only after independent review edits
are complete, avoiding a self-referential entry.

## Focused validation evidence

All Python commands used the required
`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync` prefix.

1. Initial contract run: `pytest -q tests/unit/test_graph_decisions.py` reported
   3 failures and 9 passes (fixture hash, immutable mapping comparison and strict
   tuple JSON normalization). Those three causes were fixed; the next run
   reported 12 passed.
2. First lint pass found one compatibility re-export import; it was converted
   to an explicit re-export alias. Focused `ruff check` then passed.
3. Legacy/compiler regression bundle:
   `pytest -q tests/unit/test_reliable_plan_tool_exposure.py
   tests/unit/test_graph_compiler.py tests/unit/test_graph_models.py
   tests/unit/test_codex_server_transport.py` reported 200 passed.
4. Additional legacy/schema bundle:
   `pytest -q tests/unit/test_reliable_plan_execution_semantics.py
   tests/unit/test_agent_types.py tests/unit/test_cli_agent.py
   tests/unit/test_graph_mcp_tools.py` reported 125 passed with 8 existing
   Pydantic JSON-schema warnings.
5. The first focused pyright invocation found five unknown-list annotations;
   typed factories/casts fixed them. A later full pyright pass found one unknown
   command-argument iterator after the final validator tightening; it was fixed.
6. Final combined regression run across all nine focused test files reported
   **339 passed** with the same 8 warnings. Focused ruff passed. Because that
   command then stopped at the single pyright diagnostic, only the changed
   decision tests and failed/static checks were repeated.
7. Final correction run: decision contract tests **14 passed**, focused ruff
   passed, full pyright reported **0 errors, 0 warnings**, and
   `scripts/check_graph_projection_boundaries.py` passed with no output.
8. `git diff --check` passed. No full repository gate was run, as required for
   this intermediate slice.
9. Correction-focused decision contract tests reported **23 passed**. The
   expanded nine-file Slice 1 regression bundle reported **348 passed** with
   the same 8 Pydantic JSON-schema warnings.
10. Correction-focused ruff passed, full pyright reported **0 errors, 0
    warnings**, the graph projection boundary checker passed with no output,
    and `git diff --check` passed.
11. The final position-authority correction run reported **24 passed** for
    `tests/unit/test_graph_decisions.py`. Focused ruff passed, focused pyright
    reported **0 errors, 0 warnings**, the graph projection boundary checker
    passed with no output, and `git diff --check` passed. Coverage now rejects
    arbitrary negative pre-store record positions while accepting both the
    exact compiler sentinel and the durable one-cardinality binding invariant.
12. The snapshot-row correction run reported **26 passed** for
    `tests/unit/test_graph_decisions.py`. It selects the authoritative row by
    `routine_snapshot` port, rejects zero or multiple such rows and a mismatched
    protected record ID, while accepting the same record on a distinct port.
    Focused ruff passed, focused pyright reported **0 errors, 0 warnings**, the
    graph projection boundary checker passed with no output, and
    `git diff --check` passed.
13. The exact provenance correction run reported **28 passed** for
    `tests/unit/test_graph_decisions.py`. Its parameterized regression changes
    either the canonical snapshot record port or the binding edge source port
    to the other individually valid spelling and proves both mismatches raise
    `DecisionContractResolutionError`. Focused ruff passed, focused pyright
    reported **0 errors, 0 warnings**, the graph projection boundary checker
    passed with no output, and `git diff --check` passed.
14. The fail-closed authority correction run reported **31 passed** for
    `tests/unit/test_graph_decisions.py`. Replay regressions prove that an
    authenticated decision-v1 binding rejects an invalid target role, a
    snapshot producer role outside its canonical registered contract, and a
    negative durable record position; valid legacy selection still resolves to
    `None`. Focused ruff passed, focused pyright reported **0 errors, 0
    warnings**, the graph projection boundary checker passed with no output,
    and `git diff --check` passed. Independent Slice 1 revalidation remains
    pending.
15. The edge-type authority correction run reported **32 passed** for
    `tests/unit/test_graph_decisions.py`. Its replay regression first resolves
    the untouched compiled decision-v1 graph, then changes only the exact
    snapshot edge from `input_binding` to `state_dependency` and proves the
    resolver raises `DecisionContractResolutionError`. Focused ruff passed,
    focused pyright reported **0 errors, 0 warnings**, the graph projection
    boundary checker passed with no output, and `git diff --check` passed.
16. The comprehensive authority-chain correction run reported **64 passed**
    for `tests/unit/test_graph_decisions.py`. The validated replay matrix now
    covers absent, wrong-ID and incompatible selectors; optional and
    non-input-binding edges; invalid one-cardinality policy; missing or
    malformed target and producer concrete port declarations; non-null routine
    snapshot schema versions; and every decision target stage with both a
    malformed kind and malformed role while its binding is absent. Positive
    decision-v1, explicit valid binding-policy and valid legacy controls pass.
    The nine-file Slice 1 regression bundle reported **325 passed, 45
    deselected**, with one existing Pydantic serialization warning. Focused
    ruff passed, full pyright reported **0 errors, 0 warnings**, the graph
    projection boundary checker passed with no output, and `git diff --check`
    passed.
17. A fresh independent closure validator returned **PASS** with no material
    Slice 1 blocker. It independently ran the nine-file bounded suite (**325
    passed, 45 deselected**, one existing serialization warning), probed missing
    authenticated stages, wrong edge endpoints and projected-policy mismatch,
    and confirmed the complete malformed-authority matrix fails closed. It also
    confirmed valid legacy/nondecision resolution, one `CheckChoice` owner, and
    unchanged runtime/catalog/prompt/adapter/routine hashes. A final root run of
    the same suite produced the same **325 passed, 45 deselected** result.

## Regression and product-real evidence

- A real compiled decision-v1 routine produces a frozen snapshot, generated
  declaration and exact input binding; the central resolver selects only its
  trusted `initial_planning` node. The same compiled routine without selection
  resolves legacy/inapplicable, while a corrupted bound record identity or an
  invalid selected target role rejects after exact snapshot selection.
  Record and edge snapshot ports must identify the same producer output even
  though both historical spellings remain valid in their owning contracts. The
  producer kind must resolve to the registry's canonical snapshot contract and
  its role must be explicitly allowed by that contract. A state-dependency edge
  cannot authenticate the snapshot input even if every identity and position
  field otherwise matches. The exact edge must also remain required, declare a
  valid selector that matches the bound canonical record, and carry a binding
  policy compatible with the target's one-record cardinality and its projected
  binding. Both endpoints must concretely declare the matching
  `RoutineSnapshot` ports, and a versioned snapshot record is rejected.
- Exact duplicate built-in declaration claims compile to one accepted record;
  a different schema under the same ID/version rejects.
- The generated plan declaration embeds the exact `CheckChoice` schema, and the
  unchanged shared runner submission renderer embeds that same plan schema.
- Submission request validation identifies snapshot authority by port and then
  verifies the protected ID and exact record contract; an unrelated port that
  binds the same record no longer causes a false duplicate-snapshot rejection.
- Legacy custom schemas with descriptive string checks remain unchanged and do
  not acquire the built-in identity; the typed plan rejects prose in `checks`
  and rejects a missing executable definition.
- Strict answers reject whitespace-only required text, branch/internal extras,
  invalid grades and invalid batch topology. The envelope rejects wrong tags,
  hashes, compiler versions and partial bindings.
- Existing tool-schema, macro, graph compiler, graph model, Codex transport,
  Claude CLI, runner type and semantic execution tests remain passing.

## Remaining concerns and next boundary

- Decision-v1 applicability intentionally remains fail-closed for macro-created
  reliable-plan nodes because current legacy macros do not propagate the exact
  routine snapshot binding. Slice 2 must propagate that bound authority when it
  introduces the decision compiler; it must not copy a mutable node field.
- The tagged envelope and invocation carrier are defined and tested but not yet
  consumed by dispatch/staging/finalization. Activating them belongs to Slice 2.
- No model reliability claim is made from these deterministic contract tests.
