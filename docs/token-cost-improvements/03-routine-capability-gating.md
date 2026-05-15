# 03 - Routine Capability Gating

## Problem

The audited run selected a second child slice while the first child was still
unresolved. The routine brief expected parallel execution, but the platform
rejected `create_child_run` because only one unresolved child is currently
allowed per parent.

This is not primarily a token problem. It is a capability mismatch that caused
wasted tokens, failed calls, and a human pause.

## Proposed Rule

Routine slice-selection steps should know the platform's child-concurrency
capability before proposing work.

If child concurrency is sequential:

- do not select a second child while a linked child is unresolved
- make the next allowed action explicit: wait, accept, reject, abandon, or ask
  for human input
- mark parallel-slice plans as invalid before calling tools

If child concurrency becomes parallel later:

- declare the supported concurrency mode in the routine or platform capability
  response
- include per-child merge and acceptance constraints
- expose the maximum number of unresolved children

## Expected Impact

High reliability impact and medium cost impact. It prevents the exact dead-end
path that paused the audited run.

## Acceptance Criteria

- A parent routine cannot call `create_child_run` while blocked by an unresolved
  child unless the platform explicitly advertises concurrency support.
- The prompt includes the next valid parent action.
- The verifier checks that the selected next slice is legal under current
  platform capability.

