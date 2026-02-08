# Planner: Idea to Implementation Plan

Transform an initial idea into a structured, executable plan through a systematic 9-stage workflow with human review gates.

## Overview

The Planner guides LLMs (and humans) through structured planning, producing artifacts that can be executed by coding agents. It uses human review gates at critical decision points and supports conflict-based routing when issues arise.

## Core Principles

1. **Functionality over Description** - Deliverables must be runnable/executable, not just documentation
2. **Progressive Usability** - Each stage produces verifiable outputs
3. **Contract-First Planning** - Define inputs/outputs/errors before implementation
4. **Structured Verification** - Auto-verify for structure, verifier for content quality
5. **Runnable System** - System must remain runnable after each task

## The 9 Stages

| Stage | Name | Purpose | Output |
|-------|------|---------|--------|
| 1 | Initial Plan | Create foundational artifacts | intent.md, plan.md, design-questions.md, architecture.md |
| 2 | Human Review | Pause for human feedback | [HUMAN] annotations in artifacts |
| 3 | Plan Refinement | Integrate feedback, resolve conflicts | Updated artifacts, CONFLICTS.md (if needed) |
| 4 | Step Planning | Create detailed contracts per step | step-XX-plan.md files |
| 5 | Task Breakdown | Produce atomic tasks | step-XX.md files in steps/ |
| 6 | Dry Run | Simulate execution to find gaps | dry-run-notes.md |
| 7 | Final Check | Cross-check all artifacts | verification-report.md |
| 8 | Final Review | Human approval before execution | Human approval |
| 9 | Execution Ready | Generate summary | plan-summary.md |

## Quick Start

1. Create a run with the `idea-to-plan` routine
2. Provide: `feature` (name), `idea` (description), optional `codebase_context`
3. Agent generates initial artifacts (Stage 1)
4. Human reviews and adds `[HUMAN]` notes (Stage 2)
5. Agent refines based on feedback (Stage 3)
6. Continue through stages 4-9
7. Result: Executable step files in `docs/{feature}/steps/`

## Documentation

- [Process Details](process.md) - Detailed stage-by-stage breakdown
- [Artifact Specifications](artifacts.md) - What each artifact contains
- [Templates](templates/) - Templates for each artifact type

## Related

- See `examples/routines/idea_to_plan.yaml` for the routine definition
- See `routines/` for other example routines
