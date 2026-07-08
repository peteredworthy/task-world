# External Evidence: Structural Topology Navigation over Flat-Text Repository Context

> Research digest compiled 2026-07-07 (fourth pass). Confidence: **High** =
> primary source with data; **Med** = primary, qualitative or single-venue;
> **Low** = secondary/vendor. Full link list in [../sources.md](../sources.md).
>
> Motivating observation (operator's): monolithic, linear text processing
> fails at repository-scale architecture work. Three candidate mechanisms —
> (a) **dual-process split**: separate architect-level design from
> worker-level implementation; (b) **abstract skeletonization**: expose
> interfaces/signatures, hide implementation bodies; (c) **graph-bounded
> tooling**: force navigation along explicit structural edges instead of
> linear file reads. All three are now being formalized in the 2025-26
> SWE-agent literature. All six papers below were verified against arXiv
> (2026-07-07); IDs and numbers below come from the papers/abstracts, not
> the secondary summary that prompted this digest.

## 1. Dual-process split (architect vs worker)

### 1.1 CodeTeam — competing design sketches → frozen contract → bounded workers

- **CodeTeam** (arXiv 2606.22082, Jun 2026; Med — very recent preprint,
  proxy metric): NL2Repo framework. Multiple **Architect** agents draft
  competing "Software Design Sketches" (SDSs), optionally grounded by
  retrieved design references. A **CTO** agent selects and normalizes the
  winning SDS into a **machine-checkable contract** — file ownership,
  public interfaces, dependency constraints. Only then do **Developer**
  agents implement individual files under a dependency-aware scheduler
  with bounded context and Git-based coordination; a QA agent runs tests
  and drives repairs. Reported gains: +4.1 (PE) / +2.9 (SFT) absolute
  **SketchBLEU** over corresponding CODES variants. *Caveat: SketchBLEU is
  a design-similarity metric, not an execution pass rate — treat as
  evidence for the mechanism shape, not for end-task quality.*
- *Connection: this is the "sketch" operation from
  [reconsider-and-sketch.md](reconsider-and-sketch.md) §2 pushed one step
  further — the sketch becomes a typed, checkable artifact that bounds
  every downstream context. Best-of-n over sketches (competing SDSs +
  selector) mirrors the best-of-n + verifier pattern in
  [verification-evals-routing.md](verification-evals-routing.md).*

### 1.2 Decoupled Intelligence — planner/worker formalized outside coding

- **Decoupled Intelligence** (arXiv 2605.27685, May 2026; Med — non-coding
  domain, weak transfer): traffic-scenario generation in SUMO. Decouples
  the pipeline into role-restricted agents (Planner, Builder, Demand,
  Runner, Analyst) under a **state-persistent orchestrator** using MCP for
  data handover. Role-ablation studies show the multi-agent split beats
  single-agent baselines on task success and **parameter consistency** in
  long-horizon tasks. *Value here is the ablation design (roles removed
  one at a time), not the domain numbers. Consistent with the Aider
  architect/editor cost win and Anthropic's orchestrator-workers pattern
  already digested in
  [orchestration-topologies.md](orchestration-topologies.md).*

## 2. Abstract skeletonization (interfaces without bodies)

### 2.1 Hydra — structure-aware indexing beats chunk-RAG

- **Hydra** (arXiv 2602.11671, "Do Not Treat Code as Natural Language",
  Feb 2026; High): premise — chunking-based indexing and similarity
  retrieval, borrowed from NLP, break code coherence and miss functional
  dependencies (helpers, classes, globals) that lack lexical overlap.
  Hydra: (i) structure-aware index — repository as hierarchical tree of
  functions/classes/variables; (ii) **Dependency-Aware Retriever (DAR)**
  that retrieves the *true* dependencies of a target function as
  interfaces, stripping implementation bodies; (iii) hybrid DAR +
  similarity retrieval. **>5% Pass@1 over strongest baseline**; smaller
  models with Hydra match or beat much larger models on existing
  retrievers. *The smaller-model result is the economically interesting
  one: structure-aware context is a substitute for model capability —
  same lever as routing (R04/R07 cost work).*

### 2.2 OpenClassGen — skeletons as generation specs, with a ceiling

- **OpenClassGen** (arXiv 2504.15564, Apr 2025, accepted EASE 2026; High —
  dataset paper): 324,843 real Python classes from 2,970 engineered
  projects, each paired with its **self-contained skeleton** (class/method
  signatures + docstrings) as the generation spec, plus 27 static metrics.
  On a curated executable subset (300 classes, test suites at 58% branch
  coverage): CodeBERTScore-F3 0.89 but **pass rate only 0.33** for
  GPT-o4-mini / Claude-4-Sonnet / Qwen-3-Coder. *Two readings: skeletons
  keep context bounded and give high surface fidelity, but signatures +
  docstrings alone under-specify behaviour — a skeleton is a context
  format, not a correctness guarantee. Note: the secondary summary that
  prompted this digest claimed an "~85% → ~25%" isolated-function vs
  project-context drop; that figure was not verifiable from the
  abstract/searches and is not relied on here.*

## 3. Graph-bounded tooling (navigation along structural edges)

### 3.1 CodeCompass — the Navigation Paradox

- **CodeCompass** (arXiv 2602.20048, Feb 2026; Med — single author,
  self-built 30-task benchmark, 258 trials): names the **Navigation
  Paradox** — growing context windows shift the failure mode from
  retrieval *capacity* to navigational *salience*; flat ingestion loses
  the overall picture. CodeCompass is an MCP server exposing the exact
  1-hop structural neighborhood (IMPORTS / INHERITS / INSTANTIATES edges
  from static AST analysis) that the agent must call instead of reading
  files linearly. On hidden-dependency tasks (no lexical overlap between
  task text and the dependency): **99.4% vs 76.2% vanilla / 78.2% BM25 —
  +23.2pp**. Secondary finding: tool *adoption* required prompt
  engineering (checklist-at-end formatting → 100% MCP adoption). *Caveat:
  benchmark built by the same author to demonstrate the tool; the
  hidden-dependency slice is exactly where graph navigation must win by
  construction. Direction credible, magnitude unpriced.*

### 3.2 LARGER — graph evidence inside the lexical loop, not a separate tool

- **LARGER** (arXiv 2605.16352, May 2026; Med-High): formalizes
  localization as lexically anchored structural search over an AST-derived
  heterogeneous graph (typed nodes: directory/file/class/function). Key
  design choice — **no separate graph tool**: the agent's own lexical
  (grep-style) queries are anchored into the graph, and confidence-filtered
  1-hop expansion is injected into the *same search output*. Across four
  benchmarks (localization, test generation, codebase understanding):
  **+13.9 file-level Acc@5 on LocBench** tuned, +11.8 untuned.
- *Tension worth tracking: CodeCompass says force a dedicated graph tool
  (and had to fight for adoption); LARGER says dedicated graph tools go
  unused and evidence should ride inside the search results the agent
  already reads. LARGER's delivery mechanism + CodeCompass's edge
  taxonomy are compatible; the adoption data favours LARGER's packaging.*

## 4. What this changes for task-world

1. **The SDS-contract pattern upgrades R06.** CodeTeam's machine-checkable
   contract (file ownership, public interfaces, dependency constraints) is
   a concrete candidate shape for the typed handoff contract (R06) between
   planner and executor nodes — and it doubles as the "sketch" artifact
   from the third-pass digest.
2. **Skeletonized context is an R05 lever.** Hydra/OpenClassGen suggest
   context assembly for worker nodes should prefer interface-level
   dependency slices over raw file bodies — bounded, and per Hydra it lets
   cheaper models punch up. But OpenClassGen's 0.33 pass rate warns that
   skeleton-only specs under-constrain; pair with execution verification
   (R02), not in place of it.
3. **Graph-bounded navigation is about *code* topology, not task
   topology.** The task-world graph kernel already gives structural
   topology at the orchestration layer; none of these papers cover that.
   The applicable idea is at the *runner* layer: what the coding agent
   sees when it works inside a repo. LARGER's embed-in-search packaging is
   the cheaper experiment (no new tool-adoption problem).
4. **Adoption is a first-class failure mode.** CodeCompass needed prompt
   surgery to get its own tool used. Any structural-context tooling added
   to runner prompts needs adoption instrumentation, not just capability.

## 5. Caveats

- Four of six papers are 2026 preprints (2602-2606 range); none replicated
  independently yet. Directions probably robust, numbers indicative.
- CodeTeam's gains are in SketchBLEU (design similarity), not execution.
- CodeCompass benchmark is author-built and tool-aligned.
- Decoupled Intelligence is a traffic-simulation domain; transfer to
  repository coding is assumed, not shown.
- The "~85% → ~25%" OpenClassGen drop quoted in the prompting summary was
  not verified; use the paper's own 0.33 pass rate / 0.89 CodeBERTScore.
