# Token Analysis

Cost and efficiency analysis for idea-to-plan runs. Goal: reduce from ~$24/run to ~$2.40/run (10×).

## Contents

- [run-75c9f028-analysis.md](run-75c9f028-analysis.md) — Baseline cost breakdown for run 75c9f028 (idea-to-plan-yaml-steps, $24.20)

## Active Planning Runs

| Run ID | Feature | Approach | Status |
|--------|---------|----------|--------|
| f0ec5f91 | token-efficient-planning | Structural optimizations (context targeting, Haiku routing, auto-verify) | active |
| a0becef2 | graphify-planning | Uses graphify knowledge graph to replace file-based context loading | paused (queued) |

## Key Findings from Baseline

The $24.20 cost is dominated by context volume, not output:
- **Cache reads**: $11.05 (45.6M tokens — repeated context loading across fan-out agents)
- **Cache creation**: $7.49 (2.3M tokens at $3.75–6.25/M)
- **Output tokens**: $5.66 (400K tokens — verifier rubric evaluations)

Graphify claims 71.5× fewer tokens per query vs raw file reads.
If fan-out agents query the graph instead of loading files, cache reads could drop from 45.6M → ~637K tokens.
