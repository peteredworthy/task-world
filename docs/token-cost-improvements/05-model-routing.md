# 05 - Model Routing

## Problem

The audited run used a high-end model for many mechanical turns: checklist
updates, grade submissions, evidence summaries, and retry bookkeeping. Those
turns do not need the same model as planning or defect diagnosis.

## Summary

Changing models mostly saves money. It can also save some tokens because
frontier models often produce longer reasoning and more verbose status output
for simple orchestration work.

## Proposed Routing

- **Architect/frontier model:** initial planning, ambiguous failures, design
  tradeoffs, root-cause analysis.
- **Coder model:** implementation and verification logic.
- **Summarizer/cheap model:** status summaries, checklist updates, evidence
  digesting, routine bookkeeping.
- **Strict deterministic path:** schema validation, allowed-action checks, and
  state summarization where code can do the work without an LLM.

## Expected Impact

High cost reduction, modest token reduction.

## Risks

- A cheaper model may miss subtle state-machine issues if used for diagnosis.
- Routing rules must be explicit enough that the runner does not oscillate
  between models for the same task.

## Acceptance Criteria

- Routine phases declare a model profile or work class.
- Mechanical orchestration phases default to a cheaper profile.
- The final audit reports token and cost split by model profile.

