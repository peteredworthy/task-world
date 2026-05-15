# 04 - Canonical Tool Guidance

## Problem

The audited run included a failed clarification call because the tool argument
shape was wrong. More broadly, agents can receive overlapping guidance from:

- repository instructions
- routine prompts
- MCP tool descriptions
- generated slice briefs
- historical agent behavior

When these conflict, the agent spends calls discovering the actual contract.

## Canonical Guidance Location

Use one canonical source for tool contracts and routine action constraints:

- **Tool schemas:** generated from the actual MCP/API schema.
- **Routine constraints:** stored in routine definitions and surfaced in the
  task prompt as compact capability facts.
- **Repository guidance:** high-level policy only. It should not duplicate
  exact argument schemas that can drift.

## Proposed Work

1. Audit instructions for conflicting or stale tool guidance.
2. Remove duplicated argument-shape prose where generated schema can be used.
3. Add a preflight validator for high-risk MCP calls.
4. Make error messages name the canonical source to update.

## Expected Impact

Small token reduction, medium call reduction, and better reliability. This is
especially useful for clarification, child creation, evidence retrieval, and
state-transition tools.

