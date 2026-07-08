# External Evidence: Workflow Frameworks for Managing Larger Agentic Work

> Research digest compiled 2026-07-07 (added after the initial 2026-07-07
> pass). Confidence: **High** = primary source with data; **Med** = primary,
> qualitative; **Low** = secondary/inferred/vendor. Full link list in
> [../sources.md](../sources.md).
>
> **Epistemic headline first:** the popular frameworks themselves
> (Superpowers, GSD, BMAD, Spec Kit, …) have essentially **no controlled
> measurements** behind them. The one peer-track paper that surveys them
> (arXiv 2606.04967) lists "absent benchmarks for complete processes" as a
> field-level gap, and Superpowers' own tracker closed a request for an
> evaluation framework as "not planned" (issue #1462). What *does* exist is
> indirect: measurements of the underlying mechanisms these frameworks
> package (fresh contexts, plan-first, simple-vs-complex scaffolds,
> human-gated plans). §5 collects those. §§2-4 describe the frameworks with
> adoption/anecdote claims tagged as such.

## 1. The landscape

A cluster of open-source "process layers" emerged 2025-2026 that sit on top
of coding agents (mostly Claude Code) and constrain *how* work happens
rather than *what model* runs:

- **Superpowers** (obra/Jesse Vincent, Oct 2025) — composable Markdown
  skills enforcing a mandatory methodology: brainstorm → spec → plan → TDD →
  subagent dev → review → finalize.
- **GSD "Get Shit Done"** (TÂCHES/glittercowboy, Dec 2025) — context
  engineering: atomic plans executed in fresh subagent contexts, spec-driven
  discuss → plan → execute → verify → ship.
- **GitHub Spec Kit** (Sep 2025) — spec-driven templates
  (constitution/specify/plan/tasks) portable across 24+ agent CLIs.
- **BMAD-METHOD** — heavyweight agile simulation: persona agents (analyst,
  PM, architect, dev, QA) producing PRD/architecture artifacts.
- **OpenSpec** (Fission-AI) — lightweight spec-change proposals as the unit
  of work.
- **gstack** — 23+ role-based skills; constrains decision *perspective*
  (who decides what) rather than process or context.
- **Agent OS** (Builder Methods), **Taskmaster** (PRD → task orchestration),
  **CCPM** (GitHub-issues-as-PM) — same family, smaller mindshare.

Adoption is real even if efficacy is unmeasured: Superpowers ~225K GitHub
stars by Jun 2026 and accepted into the Anthropic plugin marketplace
Jan 2026 (Low — secondary reporting); GSD ~59K stars, 138 contributors,
14 runtimes (Low — vendor/secondary); Spec Kit 80K+ stars (Low). *Star
counts measure resonance with a pain point, not outcomes.*

## 2. Superpowers — enforced methodology as skills

- Mechanism (Med — primary docs/author blog): skills are Markdown files
  with trigger descriptions; a meta-skill ("using-superpowers") forces
  skill lookup before any response; process skills gate each other
  (brainstorming before code, TDD before implementation, verification
  before completion claims, subagent-driven development for execution).
  The bet: methodology enforcement at the prompt layer stabilizes output
  quality more than model choice.
- Evidence status: one vendor benchmark (MindStudio, 2026; **Low**): 12
  Claude Code sessions, 6 with/6 without, identical prompts — reported 9%
  cheaper, 14% fewer tokens, higher rubric scores on correctness/structure/
  test coverage. n=6 per arm, no methodology publication, vendor blog.
- The project itself declined to build an evaluation harness
  (obra/superpowers#1462, closed "not planned"; High — primary tracker).
- Circulating success stories (chardet "41× faster", Shopify "53% rendering
  improvement") are **anecdotes** — single cases, no baselines, reported
  via secondary blogs.
- *For us: we already run Superpowers skills in-session (`.superpowers/`,
  plan docs under `docs/superpowers/plans/`). Treat it as a UX for the
  human-driven outer loop; its structural ideas (mandatory phase gates,
  verification-before-completion) are things our graph enforces at the
  runtime layer with actual state, which is strictly stronger than prompt
  exhortation.*

## 3. GSD — context engineering as the product

- Mechanism (Med — primary docs): break projects into phases, phases into
  **atomic plans of 2-3 tasks sized to fit ~50% of a fresh context
  window**; each plan executes in a fresh subagent (clean 200K context)
  while the orchestrating session stays at 30-40% usage; independent plans
  run in parallel waves; every task ends in an independently revertable
  commit; specs/research/plans persist as files between sessions.
- Its justifying claim — quality degrades sharply past ~50% context usage,
  hallucinations past ~70% — is **community folklore with plausible
  direction**: the real backing is the Chroma context-rot data (already
  digested in [context-engineering.md](context-engineering.md)), which
  shows degradation but not those specific thresholds. (Low for the
  numbers, High for the direction.)
- README adoption claims ("engineers at Amazon, Google, Shopify") are
  self-reported and unverified (Low).
- Recurring criticism (Med — multiple independent reviews): spec-driven
  layers are a partial return to waterfall; overhead is net-negative for
  exploration and small tasks.
- *For us: GSD is the closest external analogue to our architecture — its
  fresh-subagent-per-atomic-plan + persistent-artifact design is what our
  graph kernel does with events and typed state instead of Markdown files.
  Two transferable specifics: (a) an explicit **task-sizing rule** stated
  in context terms ("node's brief + expected work fits in ~half a fresh
  window") as a planner heuristic; (b) wave-style parallelism of
  independent nodes is validated by convergent evolution. Our
  "single-task routine → minimal graph" gotcha is the same lesson as the
  waterfall criticism: process depth must scale with task size.*

## 4. What the frameworks converge on — and the one paper that maps them

- **From Prompt to Process** (arXiv 2606.04967, Jun 2026; Med — peer-track
  survey, single author): compares Spec Kit, OpenSpec, BMAD, GSD, Spec
  Kitty, Reversa along six dimensions (specification, context, roles,
  execution, validation, portability). Findings: persistent artifacts,
  work contracts, traceability, and human review are the recurring
  ambiguity-reduction mechanisms; **no framework covers all six
  dimensions** (process depth trades against portability); recurring risks
  are spec-to-code drift, over-reliance on generated artifacts, and
  **absent benchmarks for complete processes**.
- Convergent structure across all of them: (1) plan/spec before code,
  (2) persistent artifacts outside the context window, (3) fresh context
  per work unit, (4) explicit human approval gates, (5) a verification
  phase distinct from generation. *These five are exactly the mechanisms
  our system implements natively; the external ecosystem converging on
  them from the prompt side is independent validation of the
  architecture, not a source of new mechanisms.*
- Process weight varies an order of magnitude: reported BMAD usage
  ~31.7K tokens per workflow run; one single-case comparison put the same
  CRM-dashboard build at 12 min (OpenSpec) / 90 min (Spec Kit) / 5.5 h
  (BMAD) (Low — vendor comparison, n=1). *Direction matches METR (§5):
  process overhead is real and can dominate on small tasks.*

## 5. Actual measurements that bear on the frameworks' claims

The frameworks assert: structure helps, plans help, fresh contexts help,
human gates help. Independent measurements, strongest first:

- **METR RCT** (arXiv 2507.09089, Jul 2025; **High** — randomized
  controlled trial): 16 experienced OSS maintainers, 246 real issues,
  AI-allowed vs not. Developers forecast 24% speedup, self-reported 20%
  speedup, measured **19% slowdown**. *Two lessons: (a) self-reported
  productivity gains — the entire evidence base for these frameworks — can
  be wrong in sign; (b) overhead (prompting, reviewing, integrating) is
  the mechanism, which is exactly what heavyweight process layers add more
  of.*
- **Agentless** (arXiv 2407.01489, 2024; High): a fixed three-phase
  pipeline (localize → repair → validate) beat all contemporary agentic
  scaffolds on SWE-bench Lite — 27.33% resolved at $0.34/issue. **SWE-Effi**
  (arXiv 2509.09853, 2025; High): resolution rate vs token cost diverge —
  Agentless-style leads resolution (48% w/ Qwen3-32B) at heavy token cost;
  simpler AutoCodeRover hits 38% with only ~55K input tokens/issue.
  **DirectSolve** (arXiv 2505.08120, 2025; High): with long-context models,
  dropping the scaffold entirely beat Agentless by 6% pass@1. *Scaffold
  structure is a depreciating asset as models improve; invest in
  verification and state, not elaborate role choreography — supports R08's
  consolidation instinct and argues against importing BMAD-style persona
  casts.*
- **HULA at Atlassian** (arXiv 2411.12924, ICSE 2025; **High** — industrial
  deployment, 663 real JIRA issues): plan generated 79% → plan approved by
  engineer 82% → code generated 87% → **PR raised only 25% → 59% of raised
  PRs merged → 8% end-to-end**. 67% of surveyed engineers disagreed the
  agent "completely solved the task" without human involvement. *The funnel
  collapses after code generation, at human-facing quality; and
  plan-approval is the gate engineers actually used. Directly supports our
  missing graph human-gate approval path (known open bug) being at the
  **plan** stage, not just final review.*
- **DORA 2025** (dora.dev, Sep 2025; Med — large survey, correlational):
  AI adoption now positively associated with delivery throughput (reversal
  from 2024) but still **negatively with delivery stability**; gains
  concentrate in teams with strong platforms/testing/feedback loops ("AI is
  an amplifier"). *Framework-agnostic support for the claim that control
  systems (tests, gates, small revertable changes) — not the process
  wrapper brand — are the active ingredient.*
- **CURRANTE registered report** (arXiv 2601.03878, SANER 2026; Med —
  protocol peer-reviewed, results pending): first controlled study design
  for spec→test→function human-in-the-loop workflows; will produce
  pass-rate/time-to-pass measurements. *Watch for Stage 2 — first direct
  test of the spec-driven claim.*
- **Agent skill evaluation survey** (arXiv 2606.11435, 2026; Med): skill
  eval today is mostly binary pass/fail, ignoring token cost, latency, and
  error type — the measurement infrastructure to compare frameworks
  doesn't exist yet.

## 6. Synthesis for this repo

1. **Nothing to import wholesale.** The frameworks are prompt-layer
   reimplementations of mechanisms our kernel already owns (typed state,
   phase gates, fresh per-node contexts, persistent specs, verification
   nodes). Their popularity is convergent validation, not a gap list.
2. **Transferable specifics:** GSD's context-budget task-sizing rule as a
   planner heuristic (§3); HULA's evidence that the plan-approval human
   gate carries the value (§5 → strengthens the case and placement for the
   graph human-gate work already on the open-bugs list).
3. **Calibrate process weight to task size.** METR + the BMAD cost data +
   the waterfall criticism all point the same way; we already learned this
   ("single-task routine → minimal graph").
4. **Don't add role choreography.** Agentless/DirectSolve/SWE-Effi:
   structure beyond localize-work-verify buys little and depreciates as
   models improve; spend on verification (R02) and evals (R07) instead.
5. **Distrust the ecosystem's numbers.** Best available framework
   "benchmarks" are n≤6 vendor runs and n=1 case studies; the field's own
   survey says complete-process benchmarks are absent. If we ever want to
   compare our orchestrator against these frameworks, R07's eval harness
   is a precondition — and would be genuinely novel.
