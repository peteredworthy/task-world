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

## Caveats

- arXiv IDs with 26xx prefixes are 2026 preprints; several (governance decay,
  false-success detection, repair economics) are recent and not yet widely
  replicated — treat their *numbers* as indicative, their *directions* as
  probably robust.
- Vendor blog claims (Factory, Confident AI, Adaline, Unblocked) are tagged
  as such in the digests; used for patterns, not numbers.
- Secondary sources (CTOL, decodeclaude.com) were used only for framing.
