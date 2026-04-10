# Idea to Implementation Plan Routine

A structured workflow for transforming an initial idea into a detailed, executable implementation plan through 9 stages with human review gates.

## Directory Structure

```
idea-to-plan/
├── routine.yaml                 # Main routine definition
├── scaffolding/                 # Template files for planning artifacts
│   ├── intent.md               # Template for original request & scope
│   ├── plan.md                 # Template for high-level plan & milestones
│   ├── design-questions.md     # Template for open design questions
│   ├── architecture.md         # Template for architecture & tech choices
│   ├── CONFLICTS.md            # Template for conflict tracking
│   ├── step-plan.md            # Template for detailed step planning
│   ├── step-tasks.md           # Template for atomic task breakdown
│   ├── dry-run-notes.md        # Template for execution simulation notes
│   ├── verification-report.md  # Template for consistency verification
│   └── plan-summary.md         # Template for completion summary
│   └── routine-yaml-format.md  # Notes for generating/validating routine.yaml outputs
└── README.md                    # This file
```

## Workflow Stages

1. **S-01: Initial Plan** - Create foundational planning artifacts
2. **S-02: Human Review** - Human reviews and provides feedback
3. **S-03: Plan Refinement** - Integrate feedback and resolve conflicts
4. **S-04: Step Planning** - Create detailed step plans with contracts
5. **S-05: Task Breakdown** - Convert steps into atomic, executable tasks
6. **S-06: Dry Run** - Simulate execution to identify gaps
7. **S-07: Final Check** - Cross-check all artifacts for consistency
8. **S-08: Final Plan Review** - Human final approval before execution
9. **S-09: Execution Ready** - Generate summary and mark planning complete

## Input Parameters

- `feature` (required): Feature name for directory structure (e.g., "auth-system")
- `idea` (required): Initial idea, request, or prompt to plan
- `codebase_context` (optional): Brief description of existing codebase architecture

## Generated Artifacts

The routine generates planning documents in `docs/{feature}/`:

- `intent.md` - Goal, scope, and definition of complete
- `plan.md` - Milestones and implementation order
- `design-questions.md` - Open questions with context and options
- `architecture.md` - Technical choices and testing strategy
- `step-XX-plan.md` - Detailed contracts for each step
- `steps/step-XX.md` - Atomic, executable tasks
- `dry-run-notes.md` - Execution simulation results
- `verification-report.md` - Consistency and completeness verification
- `plan-summary.md` - Completion summary with risks and next steps
- `routine-yaml-format.md` - Local notes used while generating routine YAML
- `routines/{feature}/routine.yaml` - Validated routine generated from the plan

## Using This Routine

### Create a run:

```bash
uv run orchestrator run create idea-to-plan \
  --project /path/to/your/repo \
  --config '{
    "feature": "auth-system",
    "idea": "Implement OAuth2-based authentication...",
    "codebase_context": "Python FastAPI backend with React frontend..."
  }'
```

### Start the run:

```bash
uv run orchestrator run start <run-id> --agent <agent-type>
```

## Scaffolding Templates

The `scaffolding/` directory contains markdown templates used as starting points for the planning artifacts. These templates provide structure and guidance for:

- Defining project scope and acceptance criteria
- Planning implementation milestones
- Tracking design decisions and alternatives
- Documenting architecture and technical choices
- Breaking down work into executable steps
- Simulating execution to identify gaps
- Verifying consistency and completeness

Templates support variable substitution with `{{feature}}`, `{{idea}}`, and other context variables that are replaced when artifacts are generated.

## See Also

- `docs/plan-runner/idea_to_plan_process.md` - Planning process principles and guidance
- `docs/plan-runner/step-files.md` - Step file format and verification guidance
- `docs/plan-runner/routine-yaml-format.md` - Routine YAML format and validation guide
- `docs/planner/templates/` - Additional reference templates
- `examples/routines/` - Other example routines demonstrating workflow features
