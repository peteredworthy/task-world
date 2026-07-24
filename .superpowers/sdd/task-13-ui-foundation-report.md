# Task 13 — UI Foundation Phase 1 Canonical Normalization

## Outcome

Normalized the complete Phase 1 package without changing product code, JTBD source
documents, the foundation validator/tests, or review UI.  The final validator run
has no diagnostics.

## RED to GREEN

- **RED:** `uv run python research/ui-foundation/tools/validate.py --phase 1`
  initially reported non-`SemanticItem` domain/relationship records, unresolved
  provisional `EVI-*` evidence, unresolved `CMD-*` action commands, and missing
  canonical evidence records.
- **GREEN:** after canonical allocation, evidence/command registration, semantic
  envelope completion, state/action reference rewrites, and projection generation,
  the same command exited 0 with no output.
- **Targeted regression:** `uv run pytest tests/integration/test_ui_foundation_tools.py -q`
  — **37 passed**.

## Canonical allocation and mapping counts

`catalog/ids.yaml` is the allocation ledger.  It has 385 retained allocations and
records the next suffix for each namespace.  The canonical package contains:

| Collection / namespace | Count |
|---|---:|
| Entities (`ENT-*`) | 31 |
| Relationships (`REL-*`) | 35 |
| States (`STA-*`) | 70 |
| Permissions (`PER-*`) | 7 |
| Action contracts (`ACT-*`) | 71 (67 present; 4 intentional non-executable gaps) |
| Evidence carriers (`EVI-*`) | 9 |
| Canonical evidence/commands (`EVD-*` and `CMD-*`) | 145 catalog records |
| Invariants (`INV-*`) | 7 |
| Conflicts (`CON-*`) | 9 unresolved |
| Questions (`Q-*`) | 7 blocking/open |
| Closed scope demands | 132, each retaining its scalar audit owner and Phase 1 evidence owner |

The 71 former Task 11 high-range action filenames and their contents now use
monotonic `ACT-*` identities.  Typed state, permission, action, domain,
relationship, and evidence-carrier fields were all remapped to canonical IDs.
Terminal/rejected semantics are retained in the canonical records rather than
discarded: the four intentional action gaps remain non-executable, and terminal
states/rejections remain explicit carrier-local facts.

## Evidence and freshness

Concrete command declarations were moved from the provisional state vocabulary to
the canonical evidence catalog as reachable `CMD-*` records.  Their corresponding
implementation/test/API evidence is retained as distinct `EVD-*` records; no
command is inferred from a prose action description.

The Phase 1 snapshot now hashes 890 current decisive inputs: all tracked Python
under `src/orchestrator/`, all Python tests, all UI source TypeScript/TSX files,
and the original JTBD/design source set.  Hashes are checked by the unmodified
validator.  This is complete current source/test coverage for the audited product
areas, rather than treating the prior six document-only hashes as sufficient.

## Unresolved conflicts and questions preserved

Conflicts remain unresolved for attempt identity; SQL versus JSONL normal
authority; qualified failed terminality; authenticated action attribution;
graph-versus-legacy artifact/telemetry coverage; REST lifecycle acceptance versus
direct CLI application; stopping-row cancellation; selected activity versus a
complete graph ledger; and price subtotal presentation.

Blocking questions preserve the required settlement work: canonical attempt
identity migration, typed cross-mode selection/conversion, authority
reconciliation, live-WAL-safe backup/replay, product-role authorization,
execution-bound graph-MCP action coverage, and continuing source/test freshness
verification.  No question is settled by prose and Phase 2 classifications remain
unknown placeholders only.

## Projections and self-review

`source-map.md`, `open-questions.md`, and `status.md` are regenerated from the
canonical scope, questions/conflicts, and allocation/evidence records.  I checked
that all 132 scope entries have an unchanged scalar audit owner plus a canonical
Phase 1 evidence-owner reference; no source demand was deleted or reclassified.
I also checked that canonical semantic collections validate through
`SemanticItem`, every present action resolves a reachable command and audit
evidence, and no `DS-*`, provisional high-range IDs, or `EVI-*` evidence keys
remain in typed structured fields.

## Concerns

The detailed audit evidence remains intentionally conservative: audit-anchor
records preserve report provenance while concrete command/test/API records retain
the inspected action vocabulary.  The unresolved authority, cross-mode identity,
and complete-ledger issues are blocking canonical questions, not capability
claims.  No product behavior was changed.

## Commit

Canonical artifact commit: `48a86f7f8` (`docs: normalize UI foundation Phase 1`).

## Review-rejection remediation (2026-07-24)

The rejected semantic/data-quality review was addressed in a follow-up commit.
The validator initially permitted a one-sentence conflict title, delegation-plan
ownership as demand evidence, and a `documentation_status: conflicting` semantic
item without a canonical conflict/question link.  Focused integration tests were
added first and observed RED (three failures), then the unmodified validation
principles were strengthened to reject those contracts; the focused suite is now
GREEN at 40 passing tests.

- Each `CON-1` through `CON-9` now has two distinct, source-specific
  propositions, per-claim approved-audit evidence and path/heading, affected
  canonical IDs, decisive source/evidence, explicit settlement method, and
  unresolved status.  Affected entities, relationships, states, permissions,
  actions, and invariants link back through `conflict_ids`/`question_ids`.
- The public immutable `EVD-01` through `EVD-06` records were added to the ID
  ledger without renumbering.  The Phase 0 snapshot is retained immutably beside
  the recomputed Phase 1 source/test snapshot; every evidence record declares its
  applicable snapshot and direct records also name their hash-snapshot path.
- The invariant catalog now retains the material graph patch restrictions
  (stale, role, hidden command, resource, active-node retirement), explicit
  rejection outcomes, replay/rebuild idempotency and compact parity, durable
  action audit events, and legacy idempotency/state-validation conditions as
  separately reviewable canonical invariants.
- `Q-7` is resolved: Phase 1 now covers every `src/orchestrator` Python source,
  repository Python test, and UI source TS/TSX file.  The remaining questions use
  specific implementation/test settlement criteria.
- All 132 scope demands now map to an approved substantive audit finding record
  rather than the delegation-plan ownership entry.  Canonical-record projections
  were regenerated.

Follow-up checks: `uv run python research/ui-foundation/tools/validate.py --phase
1` exits without diagnostics and `uv run pytest
tests/integration/test_ui_foundation_tools.py -q` reports `40 passed`.

## Second re-review remediation

Added exact affected-ID/backlink validation for unresolved conflicts and blocking
questions, including admission blocking for affected semantic current/derived
records. Evidence inventory is included in this check. Q7 now has a direct
snapshot-coverage record and is resolved only after the 890-file Phase 1 snapshot
and evidence snapshot-path membership are checked. Command test evidence is
limited to direct exercised test records; commands without one are explicitly
unexercised, and invariants without direct test records were downgraded. The
validator regression suite is GREEN at 41 focused tests.

## Final coverage/admission remediation

Actions affected by unresolved lifecycle/graph conflicts or questions are now
classified `unknown` while retaining independently observed implementation and
reachability. The validator rejects current/derived affected action contracts.
The Phase 1 snapshot has an explicit include-pattern coverage attestation
(`EVD-154`) linked to Q7, and direct evidence uses snapshot IDs/path linkage.
Focused validator regression coverage is GREEN at 42 tests.

## Technical snapshot-coverage correction

Replaced the fabricated `EVD-154` attestation with allocated `EVD-113`; the next
EVD suffix is 114. `validate_source_snapshot_coverage` now expands canonical
include patterns, derives expected current paths, checks coverage/counts, and is
called during source-hash validation. The Phase 1 derived coverage count is
recorded in the canonical snapshot and attestation. Focused coverage regression
tests are GREEN at 43 tests.

## Allocation-ledger correction

Added a RED/GREEN validator regression for duplicate allocation ledger IDs and
suffixes. The ledger now retains one `EVD-113` allocation and next EVD suffix
114; duplicate historical allocation entries were removed. Focused tests are
GREEN at 44.

## Fresh-fixer direct-evidence and validation correction (2026-07-24)

The earlier references to a **890-file** Phase 1 snapshot are superseded. The
current canonical snapshot and `EVD-113` attestation both declare **902**
covered entries and identical required include patterns.

- `validate.py` now type-checks the allocation ledger with explicit JSON
  mapping guards and validates both duplicate canonical IDs and duplicate
  namespace/numeric suffixes without suppressions.
- Direct evidence is now a general rule: records marked `provenance_role:
  direct`, and records with direct implementation/test/API/command/executable-
  schema/invariant-check source kinds, must provide nonempty `path`, `symbol`,
  `snapshot_id`, and `snapshot_path`; the paths must match and the snapshot
  path must be declared by that snapshot.
- Historic `EVD-7` through `EVD-48` entries were correctly reclassified as
  audit-report synthesis evidence with unreachable/unknown test status. Their
  labels are audit summaries rather than direct inspected source locations;
  direct current records and command declarations retain exact locations.
- Phase 1 validation now rejects missing required coverage patterns, count or
  file coverage mismatches, and an invalid resolved `Q-7`/`EVD-113` coverage
  attestation. Focused negative tests cover each direct locator field, path
  mismatch, snapshot membership mismatch, coverage pattern, count, file, and
  Q7-attestation failure.

Final pre-commit evidence: `uv run python research/ui-foundation/tools/validate.py
--phase 1` exited 0 with no diagnostics; `uv run pytest
tests/integration/test_ui_foundation_tools.py -q` passed **49 tests**; `uv run
ruff check .` reported **All checks passed!**; and `uv run pyright
research/ui-foundation/tools/validate.py` reported **0 errors, 0 warnings**.

## Semantic-admission and synthesis correction (2026-07-24)

- Exercised semantic records now require linked, exercised direct test evidence
  with a valid locator and snapshot membership. Current semantic and action
  records require direct, reachable implementation evidence. Unsupported
  historical classifications were downgraded conservatively to `unexercised`
  or `unknown`; directly evidenced graph invariants retain exercised status.
- `EVD-7` through `EVD-48` are now genuine synthesis records: their authority
  is an exact `agent-reports/...#Key findings` audit anchor, their `symbol` is
  that report section, `provenance_role` is `synthesis`, and the former
  direct-looking text is retained only as `source_label`.
- Phase 1 snapshot coverage treats absent or malformed include patterns, file
  lists, and expected/covered counts as errors. A resolved Q7 also requires a
  structurally valid coverage snapshot. Allocation suffix comparison uses its
  numeric value, so zero-padded variants collide.
- The 902-entry snapshot count remains current; snapshot hashes for the
  validator and focused test suite were refreshed after these changes.

Final pre-commit evidence for this correction: `uv run python
research/ui-foundation/tools/validate.py --phase 1` exited 0; `uv run pytest
tests/integration/test_ui_foundation_tools.py -q` passed **53 tests**; `uv run
ruff check .` reported **All checks passed!**; and standalone Pyright reported
**0 errors, 0 warnings**.

## Synthesis-anchor audit correction (2026-07-24)

Every `EVD-7` through `EVD-48` record was individually compared with the
approved workflow-state, graph-runtime, and API-actions reports. Each now names
the report containing its finding, a real Markdown heading slug, and the most
specific table row, claim key, or test label available in `symbol`. In
particular, EVD-13 and EVD-14 now point to the legacy task/clarification/recovery
capability table, while EVD-19 points to the workflow report's legacy-versus-
graph-mode section. The former direct-looking source text remains `source_label`
only; every record remains synthesis evidence with its existing honest status.

The validator now rejects unresolved report-heading anchors and source-label
report mismatches for synthesis/audit-report records. Existing audit records
were normalized to real `key-findings` anchors where their former anchors named
non-heading table keys. Snapshot hashes were refreshed. Final pre-commit
evidence: Phase 1 validation exited 0, the focused suite passed **56 tests**,
Ruff passed, and standalone Pyright reported **0 errors, 0 warnings**.

## Synthesis-evidence field-contract correction (2026-07-24)

Every audit-report or synthesis-provenance record now requires nonempty
`path`, `symbol`, `source_label`, `snapshot_id`, and `snapshot_path`. Its path
must contain a heading anchor; `snapshot_path` must equal the report portion of
that path and the report must be declared by the selected snapshot. Missing
fields, missing anchors, report/snapshot mismatches, unresolved snapshot paths,
and source-label/report mismatches produce distinct validation issues. Historic
audit records were completed with their report/heading source labels, synthesis
claim symbols, and matching snapshot paths without changing their provenance or
honest status.

Final pre-commit evidence: Phase 1 validation exited 0, the focused suite
passed **58 tests**, Ruff passed, and standalone Pyright reported **0 errors,
0 warnings**.
