# External Evidence: Verification, Evals, Observability, Model Routing & Cost

> Research digest compiled 2026-07-07. Confidence tags per claim.
> Full link list in [../sources.md](../sources.md).

## 1. Verifier design

- **LLM judges of code are strongly position/style-biased** (arXiv
  2604.16790, 2026; High): 12 prompt-induced biases; style cues shifted
  CodeRepair judgments by ±20-70 points depending on answer position;
  test-generation judging most fragile (50-70% consistency). *Never do
  pairwise diff comparison without position swapping; per-requirement binary
  rubric verdicts are structurally safer than holistic scores.*
- **LLMs misjudge code against NL requirements; richer judge prompts make it
  worse** (arXiv 2508.12358, 2025; High): correct code frequently flagged
  non-compliant ("overcorrection"); asking for explanations/corrections raises
  misjudgment. *Keep verifier prompts minimal per requirement; treat a
  verifier "fail" against a passing test suite as suspect — likely a
  contributor to revision-loop churn.*
- **Self-verification is the weakest configuration; execution is the
  strongest signal** (arXiv 2508.16665 survey; ReVeal 2506.11442; High).
  *Builder must never self-grade (we already enforce this); verifier model
  should differ from builder model where feasible.*
- **Fall back to execution when judge consistency is low** (~<75% →
  prefer lightweight tests/compilation checks; 2604.16790; Med). *Classify
  each requirement at graph-build time as execution-checkable vs
  judgment-only; route the former to test execution.*
- **SWE-bench Verified's durable lesson is the annotation rubric** ("is the
  requirement well-specified?", "do the tests reject valid solutions?")
  (OpenAI 2024; High). OpenAI retired it Feb 2026 for saturation and moved to
  partly-private harder suites. *Those two checks belong in our planner/
  gatekeeper before a task enters the build phase.*
- **Verifier-in-the-loop best-of-n**: agentic verifiers that generate
  discriminative test inputs gained +10-15% absolute Best@K and keep scaling;
  score-based Best-of-N plateaus (arXiv 2602.04254, 2606.00660, 2026;
  Med-High). *For high-stakes nodes, 2-3 candidates + differential test
  execution beats 1 candidate + N revision loops — only where a runnable
  oracle exists; too expensive as default.*

## 2. Revision-loop economics

- **Two repair rounds capture 76-95% of achievable self-repair gains** (arXiv
  2604.10508, 2026; High): marginal gain <2pp/attempt after round 2.
- **Noisy/verbose error feedback degrades later repairs** (same + 2025-26
  self-debugging literature; Med): adaptive early-stop when the same fix is
  attempted repeatedly. *Revision prompts carry distilled verdicts (failed
  requirement IDs + minimal evidence), not full transcripts; detect
  duplicate-diff retries and short-circuit.*
- **Capable models: repair > resample; weak models: resample > repair** (same;
  Med). *Escalation policy: attempts 1-2 = same coder model with repair;
  attempt 3 = escalate model tier with a fresh attempt, not a third repair.*
- **Cheap-first cascades can cost more for coding** ("almost right" output
  triggers rework exceeding one frontier call; Unblocked 2025 + SO survey;
  Med). *Route by task class (complexity/blast-radius tag on the node), not
  blanket cheap-first; strong model directly for architect/high-risk nodes.*

## 3. Evals for the orchestrator itself

- **Three-layer standard**: end-to-end task completion, trajectory/trace
  evals, component evals; versioned regression gates on every prompt/model
  change (Confident AI, Braintrust, 2025-26; High-for-pattern, vendor).
  *Our event journal already IS a trajectory record: minimal harness =
  replay N frozen seed tasks through the graph and assert event-sequence
  invariants (verifier ran, no false-pass, attempt count, cost ceiling).*
- **False success is the dominant silent failure and LLM judges barely detect
  it** (arXiv 2606.09863, 2026; High): 75.8% of failures among self-assessing
  coding agents were false successes; LLM judges 0.54-0.65 AUROC (they key on
  confident language); lightweight state-based detectors 0.83-0.95 AUROC at
  3300× speed. *Gate completion on environment facts checked by code (tests
  ran, diff non-empty, changed files match plan) before any LLM verdict.*
- **Solo-scale strategy**: 10-20 frozen tasks with known-good outcomes,
  re-run on prompt-template or profile changes; don't build a leaderboard
  (Adaline 2026; Med, vendor).

## 4. Observability

- **OTel GenAI semantic conventions**: still "Development" status (May 2026)
  but the shape has settled — `invoke_agent` span → child `chat` spans →
  `execute_tool` spans; `gen_ai.request.model`, `gen_ai.usage.input_tokens`/
  `output_tokens`, `gen_ai.response.finish_reasons`; content opt-in (OTel
  spec + blog 2026; High). *Don't adopt OTel wholesale; adopt its attribute
  vocabulary inside W5 typed payloads so future export is a mapping, not a
  migration.*
- **Minimum viable per-call record** (Langfuse/LangSmith/OTel consensus;
  High): prompt + response (or hash/pointer), model + params,
  input/output/**reasoning** token counts, latency, **finish_reason**, cost,
  hierarchical parent, error/status. *Our gaps map directly: finish_reason and
  reasoning tokens explain cost anomalies and truncation-caused verifier
  failures; store large content by pointer (post-bloat-incident rule).*

## 5. Model routing and cost control

- **Trained routers** (RouteLLM lineage; High for result, Low for transfer):
  ~95% frontier quality at 14-26% strong-model calls — but on chat-preference
  data, not agentic coding. *Don't build a learned router at solo scale; the
  static profile mapping is the appropriate mechanism.*
- **Effort/reasoning-budget knobs are the main intra-model cost lever**
  (OpenAI `reasoning.effort`; Anthropic effort levels — note the default
  moved medium→high, silently raising cost; 2025-26; High). *Add per-profile
  effort settings: low for summarizer/rubric checks, high only for architect.
  Cheaper than model switching and orthogonal to it.*
- **Cost-guardrail consensus** (RelayPlane, MLflow gateway, AgentGuard,
  2025-26; Med-High): enforce at a chokepoint the agent can't bypass; hard
  dollar/token budget per scope, loop detection (repeated identical calls),
  wall-clock timeout; ALERT vs REJECT policy split. *We already record cost
  per attempt; add per-run and per-node budget checks in the drive loop
  before each dispatch — our natural chokepoint — plus duplicate-diff loop
  detection.*

## Five most decision-relevant takeaways

1. Hard-cap revision loops at 2, then escalate model tier with a fresh
   attempt.
2. Split requirements at planning time into execution-checkable vs
   judgment-only; tests as oracle wherever possible.
3. Gate "task complete" on deterministic environment facts before any LLM
   verdict.
4. Fix token capture around the OTel GenAI vocabulary now, inside W5 typed
   payloads.
5. Cheapest high-leverage cost controls: per-profile effort settings +
   per-run/node budgets in the drive loop + duplicate-attempt detection —
   not a learned router.
