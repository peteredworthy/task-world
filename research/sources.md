# Sources

External sources consulted (July 2026). Grouped by thread; annotations note
what each contributed. Digests: [external/](external/).

## Orchestration & topology

| Source | Date | Contribution |
|---|---|---|
| [Anthropic — Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | Dec 2024 | Canonical taxonomy; orchestrator-workers for unpredictable subtasks |
| [Anthropic — How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | Jun 2025 | +90.2% at ~15× tokens; handoff-brief failures; spawn-explosion fix |
| [Anthropic — Building agents with the Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk) | Sep 2025 | Subagents = context isolation |
| [Anthropic — Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents) | Apr 2026 | Brain/hands/session split; wake(sessionId) replay resumption |
| [Cognition — Don't Build Multi-Agents](https://cognition.com/blog/dont-build-multi-agents) | Jun 2025 | Implicit-decision conflicts; single-threaded writes |
| [Cognition — Multi-Agents: What's Actually Working](https://cognition.com/blog/multi-agents-working) | Apr 2026 | Code-review loop (2 bugs/PR, 58% severe), smart friend, map-reduce; "intelligence, not actions" |
| [OpenAI Agents SDK — Handoffs](https://openai.github.io/openai-agents-python/handoffs/) | 2025-26 | Full-history default + input filters + typed payloads |
| [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) | Oct 2025 | Checkpoint-per-node, interrupt/resume |
| [Temporal — Durable execution meets AI](https://temporal.io/blog/durable-execution-meets-ai-why-temporal-is-the-perfect-foundation-for-ai) | 2025 | Deterministic orchestration + LLM calls as retryable activities |
| [Aider — architect/editor](https://aider.chat/2024/09/26/architect.html), [R1+Sonnet SOTA](https://aider.chat/2025/01/24/r1-sonnet.html) | 2024-25 | Role-split model pairing; 14× cost win |
| [SWE-agent (arXiv:2405.15793)](https://arxiv.org/abs/2405.15793) | 2024 | Agent-computer interface > scaffold complexity |
| [OpenHands SDK (arXiv:2511.03690)](https://arxiv.org/html/2511.03690v1) | Nov 2025 | Event-sourced single agent: −61% system failures |
| [Factory GA](https://factory.ai/news/factory-is-ga), [Terminal-Bench](https://factory.ai/news/terminal-bench) | 2025 | Plan quality dominates |
| [NeuralTrust — A2A loops](https://neuraltrust.ai/blog/a2a-loop) | 2025-26 | Layered hard limits for loop safety |
| [Cogent — orchestration failure playbook](https://cogentinfo.com/resources/when-ai-agents-collide-multi-agent-orchestration-failure-playbook-for-2026) | 2026 | Failure-mode inventory |

## Context engineering

| Source | Date | Contribution |
|---|---|---|
| [Anthropic — Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Sep 2025 | Attention budget; just-in-time retrieval; 1-2K subagent summaries |
| [Anthropic/Claude — Context management](https://claude.com/blog/context-management) | Sep 2025 | Tool-result clearing +29%; +memory +39%; 84% token cut |
| [Claude docs — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | current | 0.1× reads / 1.25-2× writes economics |
| [Manus — Context engineering lessons](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | Jul 2025 | KV-cache-first design; file-system memory; recitation; keep errors |
| [Chroma — Context rot](https://www.trychroma.com/research/context-rot) | Jul 2025 | Accuracy degrades with length, 18 models |
| [Breunig — How contexts fail](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html) / [fixes](https://www.dbreunig.com/2025/06/26/how-to-fix-your-context.html) | Jun 2025 | Poisoning/distraction/confusion/clash taxonomy |
| [Letta — Memory blocks](https://www.letta.com/blog/memory-blocks/) | 2025 | Labeled size-limited DB-persisted blocks |
| [Mem0 (arXiv 2504.19413)](https://arxiv.org/abs/2504.19413) | 2025 | Extracted memory vs full replay: cost/latency/accuracy |
| [Governance decay (arXiv 2606.22528)](https://arxiv.org/pdf/2606.22528) | Jun 2026 | Compaction → 40-70% constraint violations; pinning restores |
| [Structured eviction (arXiv 2605.08580)](https://arxiv.org/html/2605.08580); [Slipstream (arXiv 2606.11213)](https://arxiv.org/pdf/2606.11213) | 2026 | Summary lossiness; validated compaction +8.8pp SWE-bench-V |
| [Long-horizon ablation (arXiv 2606.10209)](https://arxiv.org/html/2606.10209) | Jun 2026 | last-5 + rolling summary: 91.6% vs 71% full history |
| [Confucius Code Agent (arXiv 2512.10398)](https://arxiv.org/html/2512.10398v6) | 2026 | ~8M tokens / 154 turns per SWE problem |

## Verification, evals, observability, routing

| Source | Date | Contribution |
|---|---|---|
| [LLM-judge bias audit (arXiv 2604.16790)](https://arxiv.org/html/2604.16790v1) | 2026 | 12 biases; position/style swings; execution fallback rule |
| [Requirement misjudgment (arXiv 2508.12358)](https://arxiv.org/pdf/2508.12358) | 2025 | Overcorrection; richer judge prompts worsen |
| [Self-verification survey (arXiv 2508.16665)](https://arxiv.org/pdf/2508.16665); [ReVeal (arXiv 2506.11442)](https://arxiv.org/pdf/2506.11442) | 2025 | Self-grading weakest; execution strongest |
| [SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/); [tessl.io on retirement](https://tessl.io/blog/openai-moves-beyond-swe-bench-verified-as-coding-benchmarks-saturate/) | 2024/2026 | Annotation rubric; saturation |
| [Agentic verifier best-of-n (arXiv 2602.04254)](https://arxiv.org/pdf/2602.04254); [FineVerify (arXiv 2606.00660)](https://arxiv.org/pdf/2606.00660) | 2026 | +10-15% Best@K via discriminative test generation |
| [Self-repair economics (arXiv 2604.10508)](https://arxiv.org/html/2604.10508) | 2026 | 76-95% of gains in 2 rounds; repair vs resample by capability |
| [False-success detection (arXiv 2606.09863)](https://arxiv.org/pdf/2606.09863) | 2026 | 75.8% false successes; judges 0.54-0.65 AUROC vs deterministic 0.83-0.95 |
| [Confident AI agent-eval guide](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide); [Braintrust framework](https://www.braintrust.dev/articles/ai-agent-evaluation-framework); [Adaline 2026 guide](https://www.adaline.ai/blog/complete-guide-llm-ai-agent-evaluation-2026) | 2025-26 | Three-layer evals; frozen versioned suites |
| [OTel GenAI spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/); [OTel GenAI blog](https://opentelemetry.io/blog/2026/genai-observability/) | 2026 | Attribute vocabulary; span hierarchy |
| [Langfuse observability docs](https://langfuse.com/docs/observability/overview); [Langflow comparison](https://www.langflow.org/blog/llm-observability-explained-feat-langfuse-langsmith-and-langwatch) | 2025-26 | Minimum per-call record |
| [RouteLLM (arXiv 2506.06579)](https://arxiv.org/pdf/2506.06579); [routing survey (arXiv 2603.04445)](https://arxiv.org/html/2603.04445v2) | 2025-26 | Router results; weak transfer to coding |
| [Unblocked — model routing for coding agents](https://getunblocked.com/blog/model-routing-coding-agents/) | 2025 | Cheap-first can cost more |
| [LiteLLM Anthropic effort docs](https://docs.litellm.ai/docs/providers/anthropic_effort); [Claude Opus 4.6 announcement](https://www.anthropic.com/news/claude-opus-4-6) | 2025-26 | Effort knobs; default shift medium→high |
| [RelayPlane runaway costs](https://relayplane.com/blog/agent-runaway-costs-2026); [MLflow gateway](https://mlflow.org/blog/agent-costs-mlflow-gateway/); [AgentGuard](https://bmdpat.com/blog/ai-agent-cost-control-agentguard-python) | 2025-26 | Budget chokepoints; ALERT vs REJECT |

## Workflow frameworks for larger work (added 2026-07-07)

| Source | Date | Contribution |
|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers); [author's intro](https://blog.fsck.com/2025/10/09/superpowers/) | Oct 2025- | Skills-as-methodology mechanism; enforced phase gates |
| [Superpowers eval request #1462](https://github.com/obra/superpowers/issues/1462) | 2026 | Eval framework closed "not planned" — no in-project measurement |
| [MindStudio Superpowers benchmark](https://www.mindstudio.ai/blog/5-claude-code-skills-cut-token-costs-70-percent-benchmarked) | 2026 | 6-vs-6 session comparison (9% cheaper, 14% fewer tokens) — vendor, tiny n |
| [gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done); [GSD docs](https://gsd-build-get-shit-done.mintlify.app/) | Dec 2025- | Atomic plans sized to ~50% fresh context; wave parallelism; revertable commits |
| [codecentric GSD anatomy](https://www.codecentric.de/en/knowledge-hub/blog/the-anatomy-of-claude-code-workflows-turning-slash-commands-into-an-ai-development-system) | 2026 | Mechanism deep-dive, independent of vendor |
| [Ewan Mak — Superpowers/GSD/gstack constraints](https://medium.com/@tentenco/superpowers-gsd-and-gstack-what-each-claude-code-framework-actually-constrains-12a1560960ad) | 2026 | Process vs context vs decision-perspective framing; anecdote inventory |
| [From Prompt to Process (arXiv 2606.04967)](https://arxiv.org/pdf/2606.04967) | Jun 2026 | Six-dimension taxonomy of 6 frameworks; "absent benchmarks for complete processes" |
| [BMAD vs Spec Kit vs OpenSpec (Reenbit)](https://reenbit.com/bmad-vs-spec-kit-vs-openspec-choosing-your-spec-driven-ai-framework/) | May 2026 | Token/cost figures per framework; n=1 build-time comparison — vendor |
| [METR RCT (arXiv 2507.09089)](https://arxiv.org/abs/2507.09089) | Jul 2025 | 19% measured slowdown vs 20% perceived speedup; overhead mechanism |
| [Agentless (arXiv 2407.01489)](https://arxiv.org/abs/2407.01489) | 2024 | Fixed pipeline beat agent scaffolds: 27.33% @ $0.34 |
| [SWE-Effi (arXiv 2509.09853)](https://arxiv.org/pdf/2509.09853) | 2025 | Resolution vs token-efficiency divergence across scaffolds |
| [DirectSolve/LCLM (arXiv 2505.08120)](https://arxiv.org/pdf/2505.08120) | 2025 | Scaffold-free long-context beat Agentless +6% pass@1 |
| [HULA (arXiv 2411.12924, ICSE 2025)](https://arxiv.org/abs/2411.12924) | 2024-25 | Industrial funnel: 663 issues → 8% merged; plan-approval gate data |
| [DORA 2025 report](https://dora.dev/dora-report-2025/) | Sep 2025 | AI ↑ throughput, ↓ stability; amplifier thesis (survey, correlational) |
| [CURRANTE registered report (arXiv 2601.03878)](https://arxiv.org/html/2601.03878v1) | Jan 2026 | Peer-reviewed protocol for spec→test→function study; results pending |
| [Skill evaluation survey (arXiv 2606.11435)](https://arxiv.org/pdf/2606.11435) | 2026 | Skill evals are binary pass/fail; no cost/latency comparisons exist |

## Reconsider & sketch operations (added 2026-07-07, third pass)

| Source | Date | Contribution |
|---|---|---|
| [Escalation of commitment in LLMs (arXiv 2508.01545)](https://arxiv.org/abs/2508.01545) | 2025 | Sunk-cost bias: 99.2% escalation in peer deliberation, 46.2% in hierarchy, near-rational solo |
| [Large Language Monkeys (arXiv 2407.21787)](https://arxiv.org/abs/2407.21787) | 2024 | pass@k scaling; SWE-bench Lite 15.9%→56% @250 samples; selection plateau without oracle |
| [SWE-Search (arXiv 2410.20285, ICLR 2025)](https://arxiv.org/abs/2410.20285) | 2024-25 | MCTS over agent states, hybrid value fn: +23% relative across 5 models |
| [LATS (arXiv 2310.04406, ICML 2024)](https://arxiv.org/abs/2310.04406) | 2023-24 | MCTS + reflection + backtracking; 94.4% HumanEval |
| [AIDE (arXiv 2502.13138)](https://arxiv.org/html/2502.13138v1) | 2025 | Solution-tree search (Draft/Debug/Improve operators); MLE-bench SOTA; closest system to branch-and-pivot |
| [Claude Code checkpointing docs](https://code.claude.com/docs/en/checkpointing) | 2025 | Product rewind: auto pre-edit snapshots, human-triggered only |
| [Augment — worktrees for parallel agents](https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution) | 2025-26 | Practitioner pattern: worktree per alternative approach (Low, blog ecosystem) |
| [Self-planning codegen (arXiv 2303.06689)](https://arxiv.org/pdf/2303.06689) | 2023 | NL plan before code: double-digit relative pass@1 gains |
| [Parsel (arXiv 2212.10561, NeurIPS 2023)](https://arxiv.org/abs/2212.10561) | 2022-23 | Function-responsibility decomposition + tests: HumanEval 67→85 pass@1 |
| [CodeChain (arXiv 2310.08992, ICLR 2024)](https://arxiv.org/pdf/2310.08992) | 2023-24 | Modularity as quality lever; sub-module reuse in revisions |
| [Sketch-and-Verify (arXiv 2605.08658)](https://arxiv.org/pdf/2605.08658) | 2026 | Skeleton-first + partial-program verification beats direct generation |
| [AlphaCodium (arXiv 2401.08500)](https://arxiv.org/abs/2401.08500) | 2024 | Problem-reflection stage; CodeContests pass@5 19→44 |
| [Architecture Without Architects (arXiv 2604.04990)](https://arxiv.org/html/2604.04990v1) | 2026 | "Vibe architecting"; same task 141-827 LOC / 2-6 files by prompt wording; no rationale recorded (position paper) |

## Structural code navigation (added 2026-07-07, fourth pass)

| Source | Date | Contribution |
|---|---|---|
| [CodeTeam (arXiv 2606.22082)](https://arxiv.org/abs/2606.22082) | Jun 2026 | Competing design sketches → CTO-normalized machine-checkable contract → bounded developer agents; +4.1 SketchBLEU (proxy metric) |
| [Decoupled Intelligence (arXiv 2605.27685)](https://arxiv.org/abs/2605.27685) | May 2026 | Planner/worker role split + state-persistent orchestrator; role-ablation design; non-coding domain (SUMO) |
| [Hydra — Do Not Treat Code as Natural Language (arXiv 2602.11671)](https://arxiv.org/abs/2602.11671) | Feb 2026 | Structure-aware index + Dependency-Aware Retriever; >5% Pass@1 over best baseline; smaller models match larger ones |
| [OpenClassGen (arXiv 2504.15564)](https://arxiv.org/abs/2504.15564) | Apr 2025 / EASE 2026 | 325K real Python class-skeleton pairs; skeleton specs → 0.89 CodeBERTScore but 0.33 pass rate |
| [CodeCompass (arXiv 2602.20048)](https://arxiv.org/abs/2602.20048) | Feb 2026 | Navigation Paradox; 1-hop AST-edge MCP tool; +23.2pp on hidden-dependency tasks; tool adoption needed prompt surgery |
| [LARGER (arXiv 2605.16352)](https://arxiv.org/abs/2605.16352) | May 2026 | Graph evidence injected into lexical search output, no separate graph tool; +13.9 Acc@5 LocBench |

## Caveats

- arXiv IDs with 26xx prefixes are 2026 preprints; several (governance decay,
  false-success detection, repair economics) are recent and not yet widely
  replicated — treat their *numbers* as indicative, their *directions* as
  probably robust.
- Vendor blog claims (Factory, Confident AI, Adaline, Unblocked) are tagged
  as such in the digests; used for patterns, not numbers.
- Secondary sources (CTOL, decodeclaude.com) were used only for framing.
- Workflow-framework section: star counts and adoption claims come from
  project READMEs and secondary blogs (unverified); the only
  framework-vs-baseline comparisons found are a 6-vs-6-session vendor
  benchmark and an n=1 build-time case — treat every framework efficacy
  number as anecdote. The measured evidence in that section (METR, HULA,
  Agentless family, DORA) is about underlying mechanisms, not the
  frameworks themselves.
