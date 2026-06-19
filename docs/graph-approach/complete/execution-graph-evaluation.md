# Execution Graph PRD+ — Architecture Evaluation

Evaluation of `execution-graph-prd-plus.md` against task-world's current capabilities and the
problems driving the rethink: idea-to-plan's front-loaded planning rigidity, the parent/child
delegation model's state-handling complexity, and the token-efficiency goals (lightweight models,
deterministic tools, context reuse for sub-agent follow-ups and experts).

## 1. Framing: what problem is actually being solved

Three distinct pressures motivate this design, and they pull in different directions:

1. **Adaptive plan granularity.** Idea-to-plan puts all planning weight up front. Simple tasks pay
   ceremony they don't need; complex tasks fail because the plan (and especially its validation
   routines) over-constrains implementation choices made before discovery happened.
2. **Iteration without inter-run synchronization.** The parent/child model achieves
   "plan one iteration ahead" but pays for it with two coupled run lifecycles, per-child worktrees,
   branch merges back into the parent, generation tracking, evidence envelopes, and a bespoke
   delegation policy. Measured in the current codebase this is roughly 3,400 lines of
   oversight/delegation machinery (`parent_oversight.py`, `oversight.py`, `child_templates.py`,
   `delegation/`) sitting beside the ~2,100-line workflow engine — and that count excludes the
   projections, migrations, and API surface it drags along.
3. **Token economics.** Fresh context per phase, full routine context re-injection, and
   restart-from-scratch sub-agents are all expensive. Wanted: session reuse for follow-up
   questions, long-lived experts with lifecycle control, deterministic checks instead of LLM turns.

The PRD+ addresses all three with one construct — a controller-owned execution graph — which is
both its main strength and its main risk. The evaluation below keeps returning to one question:
*is the graph kernel genuinely simpler than the sum of what it replaces, or just differently
complex?*

## 2. How far task-world already is along this path

The PRD+ is less of a clean sheet than it presents itself as. A significant fraction of the model
already exists in some form:

| PRD+ concept | Current task-world state | Gap |
|---|---|---|
| Event log as authority | `events_v2` exists, 58 event types, projections rebuilt from events (`run_state.py`, `task_state.py`); journal restore tooling proven in the DB-destruction recovery | Compatibility mutation paths still bypass it; event log is the cache of record, not the authority |
| Controller as single writer | Engine + transitions serialize most state changes | Runner callbacks and some API paths still mutate directly |
| Projections disposable | Run/task read models rebuilt from events; `restore_from_journal.py` proved it | Not all state is event-derived (prompts, agent output were lost in the incident) |
| Leases / stale-callback rejection | Heartbeat tracking and executor state machine added after the death-loop investigation; `pause_reason` discrimination | No generations, no idempotency keys, no formal lease object; staleness handled ad hoc |
| Snapshots / file-state | Per-run worktrees, run branches, `ensure_exists()` recovery | Entirely implicit: downstream work depends on dirty worktree state; no boundary classification |
| Deterministic scheduler | Engine advances `current_step_index` when all tasks terminal | Step-linear, not graph readiness; the "failed task still completes the step" wart is a symptom |
| Planner proposing structure | Parent produces routines executed by children | Whole-routine granularity, separate run lifecycle, git merge between iterations |
| Appeals / oversight | Super-parent escalation, cascade, recovery (recent hardening work) | Bespoke to parent/child; not available inside a single run |
| Retained sessions | Claude SDK / Codex server runners hold sessions | No authority separation; session liveness conflated with work validity |

This matters for the build-vs-risk calculus: the kernel's hardest parts (event sourcing,
projections, recovery-from-log) are partially proven here already. The genuinely new machinery is
leases-with-generations, file-state boundary records, the patch validator, and the readiness
scheduler.

## 3. Strengths

### 3.1 One mechanism replaces three

Today there are three structural-change mechanisms: the fixed routine engine, the parent/child
delegation layer, and the review workbench's own action model. The graph subsumes all three:
routine compilation produces the initial graph, planner patches produce iteration, and review is a
linked graph region. Every structural change flows through one validation path
(`validate_graph_patch`) instead of three differently-shaped code paths.

The strongest concrete argument: **the parent/child model's complexity is mostly inter-run
synchronization, and the graph deletes the "inter-run" part.** Plan-one-iteration-ahead becomes
"planner node appends a patch to the same run's graph" — same worktree, same event log, same
lineage. No child branch merge, no evidence envelope marshaled across run boundaries, no
generation bookkeeping split across two lifecycles. The delegation policy's decision table
(`SuperParentDelegationPolicy`) collapses into patch validation rules that already have to exist
for other reasons.

### 3.2 Directly solves the plan-granularity problem

- **Simple tasks:** a routine can compile to a minimal graph — one worker node, one check node, a
  gate if configured. No mandatory planning phase. (Caveat in §4.5: the PRD should state this as
  an explicit requirement; nothing currently guarantees compilation stays minimal.)
- **Complex tasks:** planner nodes interleave with execution. Discovery happens, then the planner
  patches the *future* region of the graph while completed facts stay immutable.
  `mark_plan_region_suspect` is exactly the missing primitive for "we learned something that
  invalidates downstream assumptions" — today that situation either fails verification confusingly
  or requires a human to cancel and re-run.
- **Over-constrained validation:** the failure mode where idea-to-plan bakes implementation
  assumptions into verification gets a first-class channel: `invalid_test` appeals, versioned
  requirement nodes, and `amend_test_or_requirement` outcomes. Currently this dead-ends in a failed
  verification with no structured way to say "the test is wrong, not the code."

### 3.3 The lease model fixes observed bug classes, not theoretical ones

The executor death-loop investigation, the `no_executor_running` pauses from duplicate servers,
stale-callback ambiguity after server reload, and orphaned subprocesses are all instances of
"process-local runner state treated as authoritative." Lease generations + idempotency keys +
event-position ordering + the outbox dispatch pattern are the standard cure, and the PRD's crash
table (§12.3) covers exactly the crash points that have actually occurred. The stale-callback
table (§19) is unit-testable; the current equivalents were debugged in production.

### 3.4 File-state records target a real incident class

The DB-destruction incident chain (agent escapes worktree → git stash truncates journal → dirty
state ambiguity) and the "step completes with failed task" wart both stem from implicit file/state
boundaries. Explicit file-state records with classification, plus "dirty worktree is never a valid
downstream input," make the boundary checkable instead of conventional. The residue-classification
policy also gives a principled home for the recurring "what do we do with `.pytest_cache` /
scratch files" question.

### 3.5 Right substrate for the token-efficiency roadmap

- **Sub-agent follow-up questions:** session nodes + new lease generation is precisely the
  "re-enter the sub-agent's context with a narrow question" pattern. The 25% of calls that need
  follow-up get a resume instead of a from-scratch agent, and the lease model keeps the resumed
  session from having stale authority.
- **Experts:** an expert is a session node whose context was built by reader nodes over a graph
  region. Ports give it typed inputs/outputs; graph-packet reconstruction gives the
  compressed-restart path when the provider cache has expired. The graph also records *what the
  expert was built from*, which is what makes "is this expert stale?" answerable.
- **Deterministic checks:** check nodes are first-class and cheap — they consume zero LLM tokens
  and their results are records other nodes bind to, which displaces LLM-verifier turns.
- **Minimal context per node:** input bindings define exactly which records a node consumes, so
  prompt packets can be assembled from bound records rather than re-injecting whole-routine
  context. This is structurally better than the current "builder prompt carries everything"
  approach.
- **Lightweight models:** named agent configs with model profiles already resolve
  task→step→routine→default; node-level authority objects are the natural place to also hang
  model-tier policy (e.g., planner=frontier, check-classification=small).

### 3.6 Testability claim is credible

The pure-core API list (§27.1) matches what went wrong before: the parent/child state handling was
hard precisely because policy was interleaved with persistence, git, and runner lifecycles. The
codebase has already been moving this way (delegation policy extracted as pure decision functions
over `DelegatedWork`). The scenario-fixture format converts the pressure-test documents into
regression tests, which is a genuinely better feedback loop than the current
integration-test-heavy verification of engine behavior.

## 4. Weaknesses and risks

### 4.1 Kernel scope is large before any product payoff

Honest accounting of net-new machinery: lease lifecycle with generations and expiry events, the
outbox dispatcher, the patch validator with eight rule classes, the resource-claim conflict matrix
with path normalization and symlink policy, the file-state classifier with five snapshot types and
six residue classifications, readiness evaluation, and ~15 node kinds with per-kind lifecycle
tables. The PRD's own V1 cut (§29) still includes appeals, recovery nodes, clarification,
review-as-graph, and patch bundles.

This is the same trap the parent/child model fell into — a coherent design whose state handling
grows past the team's appetite — except the blast radius is the whole execution core rather than
one feature. The §28 restrictions and §31 module boundaries mitigate but don't eliminate it. See
§7 for a smaller cut.

**Accepted position:** the kernel cost is taken as a deliberate expense. Every piece of it —
event-sourced log, optimistic concurrency, outbox dispatch, lease fencing — is a well-trodden
pattern with known failure modes, not novel design. And the pure core makes it unusually
TDD-friendly: the §27.3 fixture format means correctness requirements can be written as failing
tests *before* the reducers exist, which is exactly the build loop that was impossible for the
parent/child layer (where policy was entangled with persistence, git, and runner lifecycles). The
residual risk is therefore scope creep in node kinds and policies, not implementation difficulty —
managed by slice discipline, not by avoiding the kernel.

### 4.2 v1 buys correctness, not capability

Single-writer policy means no parallel implementation throughput; review stays a linked graph
doing what the workbench already does; routine compilation reproduces existing builder/verifier
semantics. A user watching a run sees roughly today's behavior. All v1 gains are internal
(replayability, stale-callback safety, test coverage). That's a legitimate choice, but it means
the *motivating* problems — adaptive planning and token efficiency — are v2 features riding on a
v1 bet. If v1 stalls, nothing user-visible was gained. The migration plan should pull at least one
motivating capability (most plausibly minimal-graph compilation for simple tasks, or session-reuse
for follow-up questions) into the first shippable slice.

### 4.3 File-state strictness will fight real agent behavior

Reject-undeclared-residue-by-default is correct in principle but agents produce scratch files,
exploratory test outputs, and tool droppings constantly. Strict mode at launch likely means a
high boundary-failure rate, each one burning a recovery/cleanup cycle — directly opposing the
token-efficiency goal. The classifier needs a *warn-and-capture* mode first (classify, record,
allow, surface in UI) with rejection opt-in per routine, and the declared-pattern vocabulary will
need seeding from observed runs before strictness is viable. The PRD acknowledges "v1 can be
conservative" but conservative-reject and conservative-allow are opposite policies; it should pick
warn-mode explicitly.

*Resolved by amendment — see §6.3 (warn-and-capture launch plus small-model gatekeeper for
unmatched residue).*

### 4.4 Patch staleness rules tax the planner

Rejecting patches on stale `base_graph_position` unless purely append-only-and-unchanged means
that in an active graph (checks completing, leases churning — every one advances the position),
planner patches race the event log. Each rejection forces a replan, and replans are the most
expensive token operation in the system. The deterministic-revalidation escape hatch helps, but
the revalidation rules deserve as much design attention as the patch ops themselves — they
determine whether planners replan 2% or 40% of the time. Worth defining: which event types
actually invalidate which patch ops (a `lease_renewed` event should invalidate almost nothing).

*Expanded with a concrete mechanism in §6.2 (semantic revalidation via per-op read-sets).*

### 4.5 Nothing guarantees minimal graphs for simple tasks

The rigidity complaint about idea-to-plan can re-emerge inside the graph: if routine compilation
always produces worker+verifier+check+gate per task, plus boundary classification and lease
round-trips per node, a one-shot-able task now pays graph ceremony instead of routine ceremony.
Per-node overhead (lease grant → dispatch → callback → boundary check → bind → schedule tick) is
fine for substantial nodes and punitive for trivial ones. The PRD needs an explicit requirement:
*a single-task routine compiles to the minimum executable graph, and the controller round-trip
cost per node is bounded*. Otherwise the fix for over-planning becomes over-orchestration.

### 4.6 The "single planning/execution loop" is implicit, not designed

The stated goal is one loop that plans and executes with strong boundaries. The PRD delivers the
boundaries but the loop is emergent: scheduler ticks + episodic planner leases. What's missing is
the planner's *cadence policy* — when does a planner node get re-leased? After every completed
region? On `mark_plan_region_suspect`? On verification failure? This is the actual control loop
and it's unspecified. Without it, the design risks either a planner that runs once (recreating
idea-to-plan's front-loading inside the graph) or one that runs every tick (token waste). Related:
whether the planner is a retained session (cheap re-entry, accumulating context — effectively the
parent agent reborn) or fresh per lease (expensive, stateless) is deferred along with retained
sessions generally, but for the planner specifically it changes the economics by an order of
magnitude. This should be promoted from "deferred" to a v1.5 decision.

*Resolved by amendment — see §6.1 (recursive horizon planning makes the loop structural).*

### 4.7 Expert/session lifecycle is deferred but is a primary driver

Token-efficient experts need: context compression policy, the resume-vs-rebuild decision
(provider cache TTL economics — resume is cheap inside the cache window, rebuild-from-compressed
may be cheaper outside it), and staleness invalidation when the graph region the expert was built
from changes. The PRD defers all of this (§34) while listing session retention as a product goal
(§3.3). The graph model is *compatible* with experts but contributes nothing yet beyond "session
nodes exist." Fine for v1 sequencing, but the PRD should at least reserve the event types
(`session_compressed`, `session_invalidated_by_region_change`) so the kernel doesn't need schema
surgery when this lands.

### 4.8 Cost accounting and interaction logs are missing from the record model

Token efficiency is a stated driver, yet no record type carries token/cost data, and agent
interaction logs appear only as a retention footnote (§20.5). Task-world already records both —
per-attempt token metrics and full agent interaction logs — so this is a carryover requirement,
not new scope. The DB-destruction incident is the cautionary tale for getting this wrong: prompts,
agent output, and action logs were the unrecoverable losses precisely because they lived outside
the event-backed state. Cost records also want the same lease/execution identity scaffolding the
kernel is building anyway, and are what makes the efficiency claims *measurable* — without them
there's no way to demonstrate that graph-packet context assembly beats whole-routine injection, or
that session resume beats fresh spawn.

*Resolved by amendment — see §6.5 (per-execution cost records and event-referenced interaction
logs as v1 carryover requirements).*

### 4.9 Projection debuggability shifts burden to UI

`blocked_invalid_test`, candidate-id-scoped verifier results, and attempt lineage are more truthful
than a mutable task status, but "why is my task in this state?" now requires walking
attempt → candidate → verification → appeal chains. The PRD requires the UI to link projections to
facts (§26) but underestimates the work: the current UI's task cards assume mutable status, and the
projection formula in §14 has six states whose causes span four node kinds. Budget a real
"explain this projection" view — derived from the same reducer, showing which facts produced the
state — or users will trust the system less than they trust today's simpler-but-lying status field.

### 4.10 Event store durability needs hardening first

The event log becomes the *only* authority, and the current journal (`.orchestrator/state/history.jsonl`)
is a git-tracked file that has already been truncated once by an agent's `git stash`. Authority
concentration raises the stakes: projection loss is now recoverable by design, but log loss is
total. Moving the authoritative log fully into the DB-backed `events_v2` store (with the journal
as a secondary sink), plus backup-before-migration policy, should be an explicit precondition in
the migration plan rather than assumed.

## 5. Graph vs parent/child — direct comparison

| Dimension | Parent/child (current) | Execution graph (proposed) |
|---|---|---|
| Iteration unit | Whole child routine + run | Graph patch (nodes/edges) |
| State sync | Two run lifecycles, generations, evidence envelopes across run boundary | One event log, one position counter |
| File flow between iterations | Git merge child branch → parent | Same worktree; file-state records sequence access |
| Failure escalation | Bespoke escalation/cascade/recovery loop | Appeal/oversight nodes, same validation path as everything else |
| Plan lookahead | One child-routine ahead | One patched region ahead, with `mark_plan_region_suspect` for invalidation |
| Code footprint | ~3,400 lines bespoke + engine | Kernel shared by *all* execution, not just delegation |
| Testability | Policy extracted, but integration-heavy around run sync and merges | Pure reducers/validators by construction |
| Conceptual model | Two special things (parent, child) with a relationship | One thing (graph) with authority rules |

The earlier fear — that controlled graph modification over-complicates versus a fixed model — was
reasonable when the alternative was *just* the fixed model. But the system no longer is the fixed
model: parent/child already introduced dynamic structure, and did it with a mechanism that
duplicates run lifecycle, worktree, and merge machinery per iteration. Given that dynamic
structure is now a requirement rather than an option, the graph is the cheaper way to have it:
its complexity is concentrated in a unit-testable kernel rather than smeared across two
synchronized run lifecycles and a git merge path. The fear should be restated, though: the graph
is simpler *per capability*, but only pays off if the kernel stays small — which is a discipline
problem, not a design property.

## 6. Design amendments (agreed after review)

These resolve weaknesses §4.3, §4.4, §4.6, and §4.8 with concrete design decisions, and replace
one PRD mechanism (patch bundles) with a simpler git-native one.

### 6.1 Recursive horizon planning — the explicit single loop

The planning/execution loop is made structural rather than policy-driven. The pattern:

A planner node emits **one patch containing two things**: (a) an executable region covering the
next *horizon* — worker/verifier/check/gate nodes for as much work as can be planned without
predicting what implementation will discover — and (b) **one or more successor planner nodes
inside the same patch**, whose required input ports bind (via edge selectors) to milestone records
of that region: the region's final accepted file-state, its verification reports, and any
outstanding failure or suspect records.

The loop is then just graph readiness. When the region completes, the successor planner's inputs
bind, it becomes ready, the scheduler leases it, and it plans the next horizon — including its own
successor. No scheduler cadence policy, no special planner re-entry rules, no persistent
orchestrating process. The "single loop" is the graph extending itself.

Properties:

- **Horizon sizing is the planner's judgment call**, guided by routine hints. The working
  heuristic: plan up to the next point where implementation discovery could plausibly change the
  plan (an uncertainty boundary), not a fixed node count. This is exactly the tradeoff between
  many over-short cycles (planner token overhead, §4.4 exposure) and over-prediction (the
  idea-to-plan failure mode). The horizon can legitimately be "the whole task" for simple work —
  which is how minimal graphs (§4.5) fall out naturally: a confident planner emits no successor.
- **Termination is checkable.** The final planner emits a region with no successor planner. Run
  completion invariant: no pending planner nodes and all task projections accepted.
- **Adaptation is the normal path, not an exception.** The successor planner consumes the region's
  outcomes *including failures and suspect marks*, so replanning after surprise is just the next
  iteration. For mid-region surprises, oversight/appeal outcomes may retire the unstarted
  remainder of a region and ready the successor planner early.
- **Runaway extension is bounded** by a planner-generation budget (same shape as retry/appeal
  budgets); exhaustion routes to a human gate.
- **Planner should be a retained session.** The planner chain is one logical planning context;
  resuming it per generation (new lease generation each time, per §19) keeps accumulated
  understanding of the run cheap to re-enter, with compression between generations. This promotes
  the retained-session decision from "deferred" to "required for the planner role" while leaving
  it optional for workers.
- **Parent/child maps directly:** the parent becomes the planner chain, child routines become
  horizon regions — with no second run lifecycle, no child worktree, no merge step.

Kept deliberately small for v1: a single planner chain (no parallel planners); successor input
bindings limited to region-summary artifact + last accepted file-state + outstanding
failure/suspect records.

### 6.2 Semantic patch revalidation (the staleness fix)

The mechanics of the §4.4 tax, spelled out: `position` advances on *every* accepted event —
lease grants, renewals, heartbeat-driven expiry ticks, input bindings, check completions — so an
active run advances tens of positions per minute. A planner's LLM turn takes minutes. Therefore
**every planner patch arrives with a stale `base_graph_position`, always**. The PRD's rule
(reject unless append-only and all referenced things unchanged) is sound, but if "unchanged" is
evaluated coarsely — any event since base position counts as change — then every patch is
rejected, every rejection forces a full replan (the most expensive token operation in the
system), and the replanned patch is stale again by submission time: planner livelock.

The fix is to make staleness semantic rather than positional:

1. **Per-op read-sets.** For each patch op, the validator derives the set of things it actually
   depends on: referenced node ids, record ids, requirement versions, authority scopes, target
   region. The patch is valid iff no *invalidating* event has touched its read-set since the base
   position. This is optimistic concurrency with row-level versioning instead of a table lock.
2. **Event classification.** Invalidating: node retired/cancelled/superseded, requirement amended,
   authority narrowed, candidate superseded, region marked suspect. Neutral: heartbeats, lease
   renewals, cost/log records, progress in unrelated regions. Neutral events never reject a patch.
3. **Horizon patches are structurally safe.** Under §6.1, planner patches are append-only into a
   future region the planner itself owns. Their read-sets are the milestone records they consumed
   as inputs — already accepted and immutable. Expected revalidation pass rate approaches 100%;
   genuine rejections only occur on real conflicts (oversight retired the region mid-plan, a
   requirement was amended).
4. **Structured rejection.** When a patch is rejected, return the conflicting events and read-set
   diff, so the planner replans incrementally against the delta rather than from scratch.
5. **Fixture coverage.** Required tests: patch submitted N positions stale with only neutral
   events → accepted; patch stale with a requirement amendment in its read-set → rejected with
   delta; patch targeting a retired region → rejected.

### 6.3 File-state: warn-and-capture launch, small-model gatekeeper

v1 boundary policy: **classify and record everything, reject nearly nothing.** Undeclared residue
is captured into the file-state record with its classification and surfaced in the UI; only
secret-suspects and repo-escaping paths are hard-rejected. Per-routine opt-in to strict
rejection comes later, once the pattern library is seeded from observed runs.

For residue that matches no established pattern, a **small-model LLM gatekeeper** classifies it
into the §20.3 taxonomy (`tool_cache`, `build_output`, `test_artifact`, `secret`,
`external_artifact`, `unknown_ignored`). Design constraints that keep this compatible with the
deterministic kernel:

- The deterministic classifier runs first; the gatekeeper is only consulted on misses, and calls
  are capped per boundary check.
- The gatekeeper's verdict is recorded as an accepted classification event. Replay reads the
  recorded decision — it never re-asks the model — so projection determinism is preserved. The
  gatekeeper is an effectful node like any check, not logic inside the classifier.
- Secret-suspect handling: the gatekeeper sees path, size, and entropy/shape metadata only — never
  raw content — so potential secrets are not shipped to a model.
- Accepted classifications feed the pattern library, so the deterministic hit rate rises over time
  and gatekeeper traffic decays toward zero. This is also a first concrete instance of the
  "lightweight models for narrow decisions" efficiency goal.

### 6.4 Git-native snapshots replace patch bundles

The `patch_bundle` machinery (§11.2, §20.1) is unnecessary. Git can already capture working-tree
state — including untracked files — without running hooks and without committing to the branch,
using plumbing:

```text
GIT_INDEX_FILE=<tmp> git add -A          # stage everything into a throwaway index
GIT_INDEX_FILE=<tmp> git write-tree      # content-addressed tree object
git commit-tree <tree> -p <base-commit>  # snapshot commit, parented on base; hooks never fire
git update-ref refs/orchestrator/snapshots/<snapshot_id> <commit>
```

Hooks only run via porcelain `git commit`, so hook failures stop being a snapshot failure mode
entirely — hooks gate merge-back and review, not state capture. The snapshot never touches HEAD,
the real index, or the working tree; trees are content-addressed (identical states dedupe for
free); the ref protects objects from GC; downstream consumers restore via `git restore --source`
or `read-tree`.

One caution: this should be plumbing, **not the stash stack**. `git stash create` produces the
same kind of dangling commit, but the stash stack is mutable shared state — pops and clears
destroy entries, and an agent's `git stash` has already truncated the journal once in this
project. If stash is used at all, `stash create` + immediate `update-ref` is the only safe form,
at which point the plumbing path is the same thing with fewer moving parts.

Consequences for the PRD: drop the `patch_bundle` snapshot type; every consumable file-state
record references either a branch commit or a snapshot ref; `no_commit_reason` shrinks to
`verification_only` / `empty_change`; the §11.2 v1 decision ("hooks fail + no patch bundle →
cannot complete") is deleted rather than solved.

### 6.5 Cost records and interaction logs carry over from task-world

Task-world already records per-attempt token metrics and full agent interaction logs. These carry
into the graph model as v1 requirements, not future work:

- A **cost record per execution** (tokens in/out, cache read/write, model, wall time), keyed by
  `execution_id`/lease, emitted at the node boundary alongside output and file-state records.
- **Interaction logs as artifact-store records** with stable record ids referenced from execution
  nodes — making them event-backed, which is exactly what the DB-destruction incident showed was
  missing (prompts, agent output, and action logs were the unrecoverable losses).
- Reserve session-lifecycle event types now (`session_compressed`,
  `session_invalidated_by_region_change`) so expert lifecycle work later needs no kernel schema
  surgery.

Cost records are also the measurement substrate for the efficiency roadmap: packet assembly vs
whole-context injection, session resume vs fresh spawn, and the expert resume-vs-rebuild
cache-economics decision all become answerable from recorded data.

## 7. Recommendations

1. **Adopt the model; build the kernel fixtures-first.** The kernel is accepted cost (§4.1) —
   standard patterns, TDD-able via the §27.3 fixture format with correctness requirements written
   as failing fixtures before reducers exist. Still shrink the first slice: compile one existing
   routine → worker/verifier/check nodes, leases with generations, event-sourced projections,
   stale-callback rejection, warn-mode file-state. Defer appeals, recovery, clarification-as-graph,
   review-as-graph to follow-on slices.
2. **Make "simple task compiles to minimal graph" an acceptance criterion** alongside §35's list,
   with a measured ceiling on per-node controller overhead. Under §6.1 this is the "confident
   planner emits no successor" case — test it explicitly.
3. **Write horizon planning (§6.1) into the PRD** as the planner contract: patch = region +
   successor planner(s); planner-as-retained-session required for the planner role;
   planner-generation budget; single chain in v1.
4. **Specify revalidation as per-op read-sets with event classification (§6.2)**, including the
   neutral-event fixtures. This determines whether planners replan 2% or 40% of the time.
5. **Launch file-state in warn-and-capture mode with the LLM gatekeeper (§6.3)**; strictness
   becomes per-routine opt-in once the pattern library is seeded.
6. **Replace patch bundles with git plumbing snapshots (§6.4)** and delete the
   hooks-block-completion failure mode.
7. **Carry over cost records and event-referenced interaction logs (§6.5)** into v1.
8. **Harden event-store durability before authority migration**: authoritative log in
   `events_v2`/DB, journal demoted to sink, backups before migration steps.
9. **Use parent/child as the graph's first validation case.** Re-express one super-parent scenario
   as a planner chain over horizon regions (§6.1) and run it through the fixture format. If the
   graph can't cleanly express the thing it's meant to replace, that's the cheapest possible time
   to find out — and if it can, the ~3,400-line oversight layer becomes deletable, which is the
   single largest simplification available in the codebase.

## 8. Verdict

The architecture is sound and is the right successor — not because graphs are elegant, but because
task-world has already paid for dynamic structure twice (parent/child, review workbench) and is
partway through paying for event sourcing a third time. The PRD+ consolidates all three payments
into one mechanism whose correctness is unit-testable, and its lease/file-state machinery
addresses bug classes this project has actually hit rather than hypothetical ones.

The risks are sequencing risks, not design flaws: a kernel that grows past its v1 cut, strictness
policies that fight real agent behavior, and the motivating capabilities (adaptive planning
cadence, session/expert economics) arriving too late to justify the kernel investment. The §6
amendments close the largest of these: the single loop is now structural (recursive horizon
planning), patch staleness is handled by semantic read-sets rather than positional rejection,
file-state launches in warn-and-capture mode with a gatekeeper, snapshots use git plumbing instead
of bespoke patch bundles, and cost/log recording carries over from day one. What remains is slice
discipline on the kernel — accepted as a deliberate, TDD-able expense.
