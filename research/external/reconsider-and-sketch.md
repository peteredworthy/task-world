# External Evidence: "Reconsider" and "Sketch" as First-Class Agent Operations

> Research digest compiled 2026-07-07 (third pass). Confidence: **High** =
> primary source with data; **Med** = primary, qualitative or single-venue;
> **Low** = secondary/vendor. Full link list in [../sources.md](../sources.md).
>
> Motivating observation (operator's): two things strong developers do that
> are rarely handed to coding agents as available moves — (a) **reconsider**:
> commit the current state to a side branch and deliberately try a different
> approach; (b) **sketch**: before building, form a design model — parts,
> responsibilities, names, and the encapsulation tradeoffs — and only then
> implement. This digest collects what's measured around each mechanism and
> which systems implement anything close.

## 1. Reconsider — abandoning a path deliberately

### 1.1 The bias is real, and structural help beats exhortation

- **Escalation of commitment in LLMs** (arXiv 2508.01545, 2025; Med-High):
  in isolated decisions LLMs show near-rational cost-benefit behavior, but
  in multi-agent deliberation escalation of commitment to failing courses
  of action jumps — 46.2% under asymmetric hierarchy, **99.2% under
  symmetric peer deliberation**. *Sunk-cost persistence is context-dependent
  and can be near-universal in exactly the collaborative topologies an
  orchestrator creates. Don't rely on an agent noticing it should give up;
  make abandonment a structural option triggered by external signals.*
- SWE-Search's stated motivation (below) is the same diagnosis from the
  systems side: current agents "follow linear, sequential processes that
  prevent backtracking and exploration of alternative solutions."

### 1.2 Fresh attempts have large measured headroom

- **Large Language Monkeys** (arXiv 2407.21787, 2024; High): coverage
  (pass@k) scales log-linearly over four orders of magnitude of samples;
  SWE-bench Lite resolution with DeepSeek-Coder-V2 goes **15.9% → 56% at
  250 independent attempts**, beating the then-SOTA single-attempt 43%.
  The binding constraint is **selection**: without an execution oracle,
  majority voting / reward scoring plateau past ~100 samples. *Independent
  re-attempts are among the best-measured levers in the field; "reconsider"
  is the sequential, artifact-preserving version of the same lever, and it
  inherits the same requirement — a verifier signal to decide which branch
  wins.*
- Repair-vs-resample economics (already digested in
  [verification-evals-routing.md](verification-evals-routing.md) §2): two
  repair rounds capture 76-95% of self-repair gains; beyond that, a fresh
  attempt beats a third repair, especially for weaker models. *R03's
  "attempt 3 = fresh attempt, escalated tier" is a special case of
  reconsider — same-approach retry exhausted, switch approach.*
- Context-poisoning literature (digested in
  [context-engineering.md](context-engineering.md)) supplies the mechanism:
  a trajectory that has gone wrong contaminates subsequent generation.
  A reconsider that starts a **fresh context carrying a distilled
  "why the last approach failed" note** (not the transcript) combines the
  measured benefits of fresh contexts with Manus's keep-the-errors lesson.

### 1.3 Systems that implement backtracking over solution attempts

- **SWE-Search** (arXiv 2410.20285, ICLR 2025; High): MCTS over agent
  states with a hybrid LLM value function plus a discriminator-debate
  step; **+23% relative** over the same agents without search, across five
  models on SWE-bench Lite; performance scales with search depth
  (inference compute), no bigger model needed.
- **LATS** (arXiv 2310.04406, ICML 2024; High): MCTS with explicit
  backtracking and self-reflection on failed trajectories; 94.4%
  HumanEval pass@1 with GPT-4 — early proof that revert-and-re-expand
  beats linear ReAct-style execution.
- **AIDE** (arXiv 2502.13138, 2025; High): the closest existing system to
  the git-branch mental model. Every attempt is a node in a **solution
  tree**; operators are Draft (new approach from root), Debug (fix a
  broken node), Improve (refine a working one); greedy search over the
  tree. SOTA on MLE-bench at the time (~3× the medals of the runner-up).
  Its own ablation insight: keeping each node a complete, runnable
  artifact makes discarding failures cheap and each LLM call local.
  *Caveat: domain is single-script ML pipelines with a scalar metric —
  the cheap value signal our multi-file coding nodes usually lack.*
- **Products**: Claude Code checkpoints + `/rewind` (v2.0, Sep 2025) —
  automatic pre-edit snapshots, restore code/conversation independently;
  reported as the most-requested feature (Med — vendor docs). Cursor has
  equivalent checkpoint-restore. LangGraph checkpoints support time-travel
  **forking** from any prior node programmatically. Git-worktree-per-
  approach is a converging practitioner pattern for comparing alternative
  implementations side by side (Low — blog ecosystem, but many independent
  writeups). *In every product, rewind/branch is **human-triggered**. The
  research systems (SWE-Search, LATS, AIDE) give the *search harness* the
  trigger. Nobody found gives the **agent itself** a first-class
  "checkpoint this and pivot" action inside an orchestrator — the gap the
  reconsider idea targets.*

### 1.4 Design constraints the evidence imposes

1. **A value signal is mandatory.** Every working backtracking system has
   one (test execution, scalar metric, hybrid LLM value fn). Reconsider
   without a verifier verdict degenerates into the selection plateau from
   Monkeys. Ties into R02 (execution-first verification).
2. **Branch budget.** Search systems cap width/depth; loop-safety digest
   says the same. A reconsider event should carry a per-node
   alternatives budget (2-3), then escalate to human.
3. **Preserve the artifact, distill the lesson.** Side-branch commit keeps
   the failed attempt inspectable and revivable (AIDE's tree; GSD's
   revertable commits); the successor node's brief gets failed-approach
   summary + failed requirement IDs, not the transcript (repair-economics
   finding on noisy feedback).

## 2. Sketch — design model before building

### 2.1 Decomposition-sketches have strong measurements

- **Self-planning code generation** (arXiv 2303.06689, 2023; High):
  plan-then-implement beats direct generation by double-digit relative
  pass@1 gains across models — the earliest clean measurement that an
  intermediate NL plan helps even single-function tasks.
- **Parsel** (arXiv 2212.10561, NeurIPS 2023; High): decompose into
  hierarchical natural-language **function descriptions** first, then
  search over per-function implementations validated by tests; HumanEval
  pass@1 **67% → 85%**. The sketch here is exactly "names +
  responsibilities": a function-level responsibility map with contracts.
- **CodeChain** (arXiv 2310.08992, ICLR 2024; High): instructing modular
  generation and revising by reusing representative sub-modules improves
  APPS/CodeContests substantially — evidence that **modularity itself**
  (clear part boundaries) is a quality lever, not just style.
- **Sketch-and-Verify** (arXiv 2605.08658, 2026; Med): inference-time
  scaling via program sketching — generate high-level skeleton, verify
  properties on the partial program, then fill in; consistent gains on
  HumanEval/MBPP/EvalPlus over direct generation. Revives the classic
  Solar-Lezama program-sketching lineage in LLM form.
- **AlphaCodium** (arXiv 2401.08500, 2024; High): "problem reflection"
  stage — restate goals, inputs, outputs, constraints — before any code,
  then test-based iteration; GPT-4 pass@5 on CodeContests **19% → 44%**.
  The sketch of the *problem* (not the code) carried much of the gain.
- **Aider architect/editor split** (already in sources; High for
  benchmark, self-run): a reasoning model proposing the approach and a
  separate editor model implementing it topped Aider's leaderboard,
  including the R1+Sonnet 14× cost result. *Sketch and build are
  separable roles with different model requirements — matches our
  profile→model resolution design.*

### 2.2 The governance angle: sketches record decisions agents currently bury

- **Architecture Without Architects** (arXiv 2604.04990, 2026; Med —
  position paper + illustrative case): "vibe architecting" — agents make
  implicit architectural decisions through task decomposition, defaults,
  and scaffolds; the same chatbot task prompted three ways produced
  **141-827 LOC across 2-6 files** with divergent structures, and no
  rationale on record anywhere. *The sketch artifact is precisely the
  missing governance object: named parts, assigned responsibilities,
  chosen boundaries, and rejected alternatives, written down before code
  exists.*
- HULA (workflow digest §5; High): the human gate engineers actually used
  was **plan approval** (82% approved) — reviewing a design-level artifact
  is where human attention pays, not diff review after the fact.
- Cognition's "implicit decision conflicts" (orchestration digest): the
  classic multi-agent failure is two workers making incompatible implicit
  choices. A shared sketch with fixed names/interfaces is the cheapest
  known coherence anchor across fresh per-node contexts.

### 2.3 What's unmeasured

- No study found that isolates **naming quality**, **responsibility
  assignment**, or **data-encapsulation level** (the tradeoff register the
  operator's sketch practice actually deliberates) as variables in agent
  code quality. Evidence covers decomposition granularity and
  plan-before-code; the finer design registers are folklore. Treat a
  sketch phase's naming/encapsulation content as plausible-but-unpriced —
  cheap to include, unproven in isolation.
- Frameworks digest already covers plan-first *process* claims
  (§§2-5 there); the distinction here: those plans sequence **steps**,
  a sketch fixes **structure** (parts, names, contracts). Spec Kit / BMAD
  artifacts blur the two; none measure the structural half separately.

## 3. Synthesis for this repo

1. **Both ideas are mechanism-backed but system-novel.** Backtracking
   search and plan/sketch-first each have multiple High-confidence
   results; no found system exposes either to the agent as a first-class
   orchestrator operation. Handing the *agent* a "reconsider" move and
   making "sketch" a typed, gated artifact are genuinely under-occupied
   design points — consistent with the frameworks digest finding that the
   ecosystem reimplements mechanisms at the prompt layer while our kernel
   can own them as state.
2. **Reconsider = event + branch + fresh node.** Natural fit to the
   existing kernel: park the attempt (side-branch commit, tag with node
   id), emit a reconsider event carrying a distilled failure note, spawn a
   sibling attempt node with fresh context. Preconditions already on the
   roadmap: verifier signal (R02) to trigger it, revision/escalation
   policy (R03) to bound it — reconsider slots in as the approach-level
   tier above R03's attempt-level ladder, with its own small budget.
3. **Sketch = planner output contract, human-gated.** A typed sketch
   artifact (components, responsibilities, interfaces/names,
   alternatives-considered-with-tradeoffs) produced before graph
   expansion, gated by the human plan-approval path (the known-missing
   graph human gate — HULA says this is *the* high-value gate), then
   pinned into every builder node's brief (R05 pinning) as the shared
   vocabulary. The alternatives-considered section doubles as
   pre-computed plan B's, making reconsider cheaper when triggered.
4. **Order of operations**: sketch needs only the human-gate work already
   on the bugs list plus a payload type (W5-adjacent) — low risk.
   Reconsider depends on R02/R03 landing first; without an execution
   oracle it will select badly (Monkeys plateau). Prototype sketch first,
   reconsider second.
