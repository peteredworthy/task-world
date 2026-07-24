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
