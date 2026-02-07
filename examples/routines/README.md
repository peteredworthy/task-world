# Example Routines

This directory contains example routine templates that demonstrate advanced workflow features.

## idea_to_plan.yaml

**Purpose:** Transform an initial idea into a structured, executable plan with step files suitable for agent execution.

**Demonstrates:**
- Human approval gates (Slice 9.1)
- Backward transitions with conditions (Slice 9.2)
- Artifact tracking (Slice 9.3)
- Dry-run verification step (Slice 9.4)
- Multi-artifact context injection (Slice 9.5)

**Usage:**

1. **Validate the routine:**
   ```bash
   uv run orchestrator routines validate examples/routines/idea_to_plan.yaml
   ```

2. **Copy to your project's routines directory to use:**
   ```bash
   cp examples/routines/idea_to_plan.yaml routines/
   ```

3. **Create a run:**
   ```bash
   uv run orchestrator run create idea-to-plan \
     --project ./my-project \
     --config '{"feature": "my-feature", "idea": "Add user authentication"}'
   ```

**Inputs:**
- `feature` (required): Feature name for directory structure
- `idea` (required): Initial idea or prompt
- `codebase_context` (optional): Brief description of existing codebase

**Output:**
The routine generates a complete implementation plan in `docs/{feature}/`:
- `intent.md` - Original request summary
- `plan.md` - High-level iterative plan
- `design-questions.md` - Questions and resolutions
- `architecture.md` - Technical choices
- `step-*-plan.md` - Detailed step plans
- `steps/step-*.md` - Atomic task files for execution
- `plan-summary.md` - Final execution summary

**Workflow:**
1. **S-01: Initial Plan** - Generate initial artifacts
2. **S-02: Human Review** - Review and provide feedback (human gate)
3. **S-03: Plan Refinement** - Integrate feedback, handle conflicts
4. **S-04: Step Planning** - Create detailed step plans
5. **S-05: Task Breakdown** - Generate atomic step files
6. **S-06: Dry Run** - Simulate execution to identify gaps
7. **S-07: Final Check** - Cross-check all artifacts with LLM verification
8. **S-08: Final Plan Review** - Final human approval (human gate)
9. **S-09: Execution Ready** - Generate summary

**Backward Transitions:**
- Steps S-03, S-04, and S-05 can transition back to S-02 (Human Review) if:
  - Unresolved conflicts are detected
  - Open design questions remain
- Maximum 2-3 iterations to prevent infinite loops
