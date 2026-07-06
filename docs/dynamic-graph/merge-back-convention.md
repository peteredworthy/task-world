# Merge-Back Convention

This document exists because graph runs have twice been seeded from a stale
base commit (e.g. `f526cd70a`), producing worktree fixes that then had to be
manually ported to `main` plus repair commits to close the resulting gaps
(see the review's §4 P0 list). It records three conventions adopted to stop
that class of incident from recurring silently.

## 1. Every port/merge-back commit must cite its source

Any commit that ports or merges work developed in a run worktree back onto
`main` (or any other integration branch) must state, in the commit message
body:

- The **source run id** the work came from (e.g. `run r355`).
- The **base SHA** the work was developed against (i.e. what the worktree was
  seeded from — check `source_branch_sha` / `intended_seed_sha` on the run,
  not just "whatever main was recently").

Example:

```
fix: close dynamic graph p1 ledger gaps

Ported from run r357, developed against base f526cd70a (worktree seeded
before f526cd70a landed on main; see merge-back-convention.md).
```

Without this, a reviewer has no way to tell whether a port already accounts
for everything that changed on `main` between the worktree's base commit and
the port itself — which is exactly how the original stale-base incidents went
undetected until manual investigation.

## 2. Ledger closure rule applies to all future W-spec work

`docs/dynamic-graph/p1-resolution-ledger.md` established a closure rule for
P1 items: a row is not "Fixed" on the strength of prose or nearby cleanup —
only a named regression test, re-run green, closes it. That rule is adopted
as the closure rule for **all** future W-spec (and P0/P1/P2) closures, not
just the original P1 ledger. Concretely:

- No item in any dynamic-graph tracking doc may be marked done without citing
  the exact test file and test name that regression-tests the invariant.
- The cited test must be re-run on `main` (not just in the worktree it was
  authored in) before the closure claim is made, since worktree-local green
  is not evidence a merge-back succeeded.

## 3. `intended_seed_sha` recording and seed-time staleness refusal

To catch stale-base seeding automatically rather than relying on convention
alone:

- **At run creation** (`WorkflowService.create_run`), the source branch's
  current HEAD SHA is best-effort resolved in `<repos_path>/<repo_name>` and
  recorded on the run as `intended_seed_sha`. Resolution failure (missing
  repo, unknown branch, no global config) never blocks run creation — the
  field is simply left null.
- **At worktree-seed time** (`AgentRunnerExecutor._prepare_worktree_with_service`,
  fresh-creation path only — resumes are never blocked by this check), the
  source branch's *current* head SHA is resolved again and classified against
  `intended_seed_sha` via `orchestrator.git.seed.classify_seed_staleness`:

  | Classification | Meaning | Action |
  | --- | --- | --- |
  | `MATCH` | `intended_seed_sha` is null or equals the current head | Proceed silently |
  | `ADVANCED` | `intended_seed_sha` is a strict ancestor of the current head (branch moved forward) | `logger.warning`, proceed |
  | `STALE` | the current head is a strict ancestor of `intended_seed_sha` (the repo/clone is BEHIND what run creation saw — the original failure mode) | **Refuse**: `service.fail_worktree_creation(...)` with a `stale_seed_base:` reason naming both SHAs; run is paused, no worktree is created |
  | `UNRELATED` | SHAs are unrelated, or ancestry is indeterminate (git errors, shallow history) | `logger.warning`, proceed — never brick a run on infrastructure noise |

- **Escape hatch:** setting `allow_stale_base: true` in the run's `config`
  downgrades a `STALE` classification to "warn and proceed" instead of
  refusing. Use this only when the stale base is a deliberate, understood
  choice (e.g. intentionally pinning to an older commit) — not as a way to
  silence the warning by default.

See `src/orchestrator/git/seed.py` for the pure classification helper (unit
tested in `tests/unit/test_git_seed_staleness.py`) and
`src/orchestrator/runners/executor.py::decide_seed_action` for the policy
decision (unit tested in `tests/unit/test_executor_seed_decision.py`), with
end-to-end wiring covered in `tests/unit/test_worktree_seed_staleness.py`.
