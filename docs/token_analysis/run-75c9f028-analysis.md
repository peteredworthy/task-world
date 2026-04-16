# Token Analysis: Run 75c9f028 (idea-to-plan-yaml-steps)

## Run Overview

- **Run ID**: 75c9f028-f8c3-4818-8d14-098bf4deefd4
- **Routine**: `idea-to-plan-yaml-steps` (Idea to Implementation Plan — YAML Step Files)
- **Feature Planned**: Per-Model Token Accounting (`per-model-yaml`)
- **Status**: Completed
- **Total Cost**: $24.20
- **Total Duration**: ~107 minutes (6,410,353 ms)
- **Total Actions**: 913

## Cost Breakdown by Model

| Model | Cache Read Tokens | Cache Creation Tokens | Input Tokens | Output Tokens | Total Cost |
|-------|------------------|-----------------------|-------------|---------------|------------|
| claude-sonnet-4-6 | 25,666,852 | 1,213,942 | 11,497 | 252,755 | $16.08 |
| claude-opus-4-6 | 3,864,442 | 296,135 | 477 | 52,003 | $5.09 |
| claude-haiku-4-5 | 16,033,060 | 762,769 | 6,083 | 95,286 | $3.04 |
| **Total** | **45,564,354** | **2,272,846** | **18,057** | **400,044** | **$24.20** |

## Cost Distribution

- **Cache reads**: ~$11.05 (45.6% of total)
  - Sonnet: 25.7M × $0.30/M = $7.70
  - Opus: 3.9M × $0.50/M = $1.93
  - Haiku: 16.0M × $0.10/M = $1.60
- **Cache creation**: ~$7.49 (30.9% of total)
  - Sonnet: 1.2M × $3.75/M = $4.55
  - Opus: 296K × $6.25/M = $1.85
  - Haiku: 763K × $1.25/M = $0.95
- **Output tokens**: ~$5.66 (23.4% of total)
  - Sonnet: 253K × $15/M = $3.79
  - Opus: 52K × $25/M = $1.30
  - Haiku: 95K × $5/M = $0.48
- **Direct input**: ~$0.07 (0.3% of total)

## Step Structure

The run had 8 steps with significant fan-out:

| Step | Title | Tasks |
|------|-------|-------|
| S-01 | Initial Plan | 1 |
| S-02 | Requirements Gathering | 1 |
| S-03 | Step Planning | 4 (including codebase discovery + context generation) |
| S-04 | Task Breakdown | 7 (1 coordinator + 6 fan-out per step) |
| S-05 | Dry Run & Failure Mode Analysis | 9 (1 coordinator + 1 merge + 7 fan-out per step + apply-gaps) |
| S-06 | Final Check | 1 |
| S-07 | Final Plan Review | 1 (human gate) |
| S-08 | Execution Ready | 3 |

## Key Insights

### Why Context Is So Large
- **47.8M cached tokens** across the run (avg ~52K tokens cached per action)
- Each fan-out agent loads: intent.md + plan.md + architecture.md + step plans + code context = large shared context
- 913 actions across 27 tasks = ~33 actions/task average
- Agents spend significant time on codebase discovery even with `context_from` hints

### Biggest Cost Drivers
1. **Repeated context loading**: Fan-out tasks (S-04: 6 agents, S-05: 7 agents) each load overlapping documentation
2. **Cache creation overhead**: $7.49 spent just warming cache (prompt caching has fixed cost per warm-up)
3. **Opus for reasoning tasks**: Opus costs 1.67× cache-read and 1.67× cache-creation vs Sonnet
4. **Output verbosity**: 400K output tokens — verifier rubric evaluations add significant output cost

### Cache Efficiency
Despite heavy caching, the ratio is poor:
- Cache reads: 45.6M tokens at $0.30/M = $11.05
- Cache creation: 2.3M tokens at $3.75/M = $7.49
- Cache hit ratio: 45.6M / (45.6M + 2.3M) = 95% — good hit rate, but creation cost is high
- The sheer volume of context being cached is the root problem

## Target: $2.42 (10% of current cost)

To achieve 10× cost reduction:

### High-Impact Changes Required

1. **Replace file-based context loading with graph queries** (graphify)
   - Instead of loading entire files, agents query a pre-built knowledge graph
   - A query returns only the relevant nodes/edges for the specific task
   - Estimated saving: 60-80% reduction in cache read tokens

2. **Reduce fan-out agent count**
   - Each fan-out agent currently loads the full planning corpus
   - With graphify, each can get a targeted 1-2K token extract instead of 20-50K
   - Potential: drop average context from 52K to 5K per action

3. **Eliminate redundant codebase discovery**
   - S-03 does codebase discovery; S-04/S-05 agents re-discover independently
   - graphify graph built once, queried cheaply by all subsequent tasks

4. **Switch verification to auto-verify only**
   - LLM verifier rubric evaluation adds significant output token cost
   - Replace with deterministic file checks where possible

5. **Haiku-first model routing**
   - Fan-out tasks (S-04, S-05) are mechanical — use Haiku instead of Sonnet
   - 3× cheaper cache reads, 3× cheaper output

## Baseline for Comparison

Use this run as the baseline when evaluating optimized variants:
- Baseline cost: $24.20
- Baseline duration: 107 minutes  
- Baseline actions: 913
- Baseline quality: Full 8-step plan with YAML step files, dry-run analysis, human gate
