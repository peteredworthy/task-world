# External Evidence: Agent Structures, Orchestration Topologies, Handoffs

> Research digest compiled 2026-07-07 from primary sources. Each claim is
> tagged with confidence. Full link list in [../sources.md](../sources.md).

## 1. Single-agent vs multi-agent — how the debate resolved

- **Anthropic's taxonomy** ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), Dec 2024; consensus): prefer simple
  workflows; orchestrator-workers is for tasks whose subtasks can't be
  predicted up front. *Our typed graph with horizon planning is exactly that
  regime — not over-engineering.*
- **Multi-agent won +90.2% over single Opus 4 on research evals — at ~15×
  tokens**, and token spend explained ~80% of variance
  ([multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system), Jun 2025; strong, single-vendor).
  Same post: "most coding tasks involve fewer truly parallelizable tasks than
  research". *Fan-out is a paid upgrade justified only for genuinely
  independent subtasks — mostly read-only work.*
- **Cognition "Don't Build Multi-Agents"** (Jun 2025; consensus among
  coding-agent builders): parallel subagents fail because actions carry
  implicit decisions that conflict; share full traces or stay single-threaded.
- **Cognition's Apr 2026 revision** ([Multi-Agents: What's Actually Working](https://cognition.com/blog/multi-agents-working); strong — production stats):
  three patterns work: (1) **Code-Review Loop** — generator + verifier with
  *deliberately clean* context (reviewer sees only the diff); Devin Review
  catches ~2 bugs/PR, ~58% severe; (2) **Smart Friend** — fork full context to
  a stronger model for advice; (3) **Map-Reduce-and-Manage**. Unifying rule:
  **writes stay single-threaded; extra agents contribute intelligence, not
  actions**. Still failing: parallel-writer swarms, unstructured peer
  negotiation, weak models as primaries.
- Synthesis: both camps converged on "context engineering is the #1 job"; the
  disagreement was task shape (parallelizable read-heavy vs interdependent
  write-heavy). *A typed graph should carry a read/write annotation per node
  and derive allowed parallelism from it.*

**Bottom line for us: the builder/verifier fresh-context loop is the
best-evidenced production pattern of 2026. Don't add parallel writers.**

## 2. Topologies that shipped in coding agents

- **Aider architect/editor** (Sep 2024 / Jan 2025; strong, public benchmark):
  reasoning model describes the change, cheaper editor emits edits —
  R1-architect + Sonnet-editor at 14× lower cost than the o1 SOTA it
  displaced. *Role-specialized model profiles per phase have hard benchmark
  support, including strong-planner + cheap-executor pairings.*
- Cognition caveat (Jun 2025; anecdote): edit-apply pipelines were fragile
  when the applier had to *interpret* instructions. *Plan→execute handoff
  artifacts must be decision-complete (exact edits/specs), not intent prose.*
- **SWE-agent** (arXiv:2405.15793, 2024; strong): the agent-computer interface
  matters as much as the model — a single agent with a good ACI beat more
  elaborate scaffolds. *Tool/interface ergonomics can outperform topology
  investment.*
- **OpenHands SDK rewrite** (arXiv:2511.03690, Nov 2025; strong): single
  agent, event-sourced state, deterministic replay, immutable per-run config →
  **61% reduction in system-attributable failures** over 15 days of
  production; event-sourcing overhead negligible. *Independent validation of
  our storage design; "immutable config prevents drift" → pin model profiles
  per run.*
- **Factory** (2025; vendor anecdote): persona-specialized droids; "a droid is
  only as good as its plan"; a single Code Droid topped Terminal-Bench.
  *Plan quality dominates — a gatekeeper on the plan node is higher-leverage
  than more parallel builders.*
- **Anthropic Managed Agents** (Apr 2026; strong, production infra): brain /
  hands / durable append-only session log as independently failing
  components; crashed harnesses resume via `wake(sessionId)` replay. *The
  journal-as-source-of-truth is the right durability primitive; the gap worth
  closing is agent resumability purely from the event log.*

## 3. Frameworks and durability

- **OpenAI Agents SDK handoffs** (official docs, 2025-26): receiving agent
  gets the entire prior conversation *by default*, but input filters
  (`remove_all_tools`) and typed `input_type` payloads are first-class. *Even
  the "pass everything" framework ships pruning + typed-payload hooks.*
- **LangGraph 1.0** (Oct 2025) and the durable-execution wave (Temporal, DBOS,
  AWS, Cloudflare, Vercel; 2025-26; consensus): deterministic orchestration +
  nondeterministic LLM calls as retryable activities; checkpoint-per-node
  resumption; interrupt/resume as a first-class node state. *Industry
  converged on our shape. The differentiator worth stealing is
  interrupt/resume as a node state, not a run-level pause.*
- **Claude Agent SDK** guidance (Sep 2025; consensus): subagents exist
  primarily for **context isolation** — burn tokens in a throwaway window,
  return distilled findings. *Model subagent value as context-window
  arbitrage: spawn when expected garbage-context tokens exceed
  summary-fidelity loss.*

## 4. Handoff mechanics — what to pass

Three regimes with evidence (Cognition Apr 2026; Anthropic Jun 2025):

| Regime | When | Why |
|---|---|---|
| Full trace / fork | Write-continuity; "smart friend" consults | Implicit decisions preserved |
| Clean context + artifact only (the diff) | Verifiers | Information *hiding* is the feature — review isn't anchored by builder rationalizations |
| Structured summary + filesystem artifacts | Fan-out workers | Distilled findings; plans persisted before context exhaustion |

- Anthropic's early multi-agent failures were **handoff failures**: vague
  briefs → duplicated/gapped work. Fix: every subagent brief specifies
  objective, output format, tool guidance, explicit boundaries (Jun 2025;
  strong). *A typed task schema should require objective + boundaries +
  output contract, validated at graph-patch admission — enforceable in our
  kernel, unlike prompt-only systems.*
- *For builder→builder continuation (attempt N → N+1), pass decision traces,
  not just the task spec — losing implicit decisions is the best-documented
  failure.*

## 5. Loop-safety in dynamic graphs

- No elegant theory exists. Production practice is **layered hard limits**:
  max delegation depth, per-pair delegation counters, token/cost budgets,
  no-progress detection, timeouts, dead-letter queues (NeuralTrust, Cogent,
  2025-26; consensus). One principled addition: a **scope-reduction
  invariant** — every delegation must declare strictly smaller scope than its
  parent (sound but speculative).
- Anthropic's spawn-explosion failure (50 subagents for a trivial query) was
  fixed with prompt-level effort scaling, not architecture (Jun 2025; strong).
  *Pair kernel-level budget caps with planner-prompt effort calibration; we
  already do the latter (single-task routine → minimal graph).*

## Five most decision-relevant takeaways

1. Our core topology is the 2026 consensus winner; don't add parallel writers.
2. Derive parallelism policy from read/write task type.
3. Enforce handoff contracts in the type system (objective/boundaries/output
   contract; decision-complete plan artifacts).
4. Loop-safety = kernel-enforced budgets + scope-reduction at patch admission.
5. Close the event-log-as-read-path gap; make every agent resumable from the
   journal (OpenHands −61% failures; Managed Agents `wake()`).
