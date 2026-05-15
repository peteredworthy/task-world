# 01 - Reduce Context Size

## Problem

Parent runs accumulate large oversight snapshots, slice briefs, verification
notes, and audit Markdown. With fresh context per phase, that material gets
re-read repeatedly. In the audited run, cache-read tokens dominated the parent
bill: about 6.7M of 7.4M parent tokens.

## Easy Target: Oversight State

Oversight state should be split into:

- **Machine ledger:** compact, structured state used by the next phase.
- **Human audit docs:** rich Markdown for review, debugging, and provenance.

The agent prompt should receive the machine ledger by default. Rich Markdown
should be fetched only when the current task needs narrative detail.

## Candidate Ledger Fields

- active child run id
- parent slice id
- child evidence readiness
- child terminal status
- merge queue size
- accepted/rejected/abandoned child ids
- unresolved inventory ids
- next allowed parent action
- current blocker, if any
- compact evidence digest

## Expected Impact

High token reduction. This targets repeated cache reads rather than one-time
prompt input.

## Risks

- Over-compression can hide reasoning needed for verification.
- The ledger must be the source of truth for control flow; Markdown should not
  become a second state model.

