# Idea-to-Plan Improvements: Implementation Ready

**Status**: ✅ Complete design with all decisions made

---

## What We're Building

Three interconnected improvements to the idea-to-plan routine:

1. **Sub-agent infrastructure** - Break complex tasks into focused sub-agent invocations
2. **Dry-run with sub-agents** - Generate detailed gap analysis with full context per task
3. **Dry-run notes feedback loop** - Steps 5+ actively resolve gaps and track resolution

---

## Design Decisions (All Finalized)

| Decision | Answer | Impact |
|----------|--------|--------|
| Sub-agent error handling | Stop & return error to parent (like failed command) | Simple error propagation |
| Return message format | Plain string; structured output in prompt | Flexible, no coupling |
| Concurrent sub-agents | No (sequential/blocking for OpenHands) | Simpler, sufficient |
| Gap severity | REQUIRED/EXPECTED/OPTIONAL based on functionality criticality | REQUIRED/EXPECTED must be resolved |
| Gap re-validation | Manual LLM marking; re-run detects false positives | Iterative refinement |

---

## Implementation Phases

### Phase 1: Sub-Agent Infrastructure
- Create `SubAgentConfig`, `SubAgentResult`, `execute_sub_agent()`
- Add sub-agent support to OpenHands (blocking context switch + return_message tool)
- Add `--sub-agent` flag to Codex CLI
- **Files**: `agents/sub_agent.py`, modify `agents/openhands.py`, `agents/cli.py`

### Phase 2: Dry-Run Task Generation
- Generate 4 focused sub-agent prompts for dry-run validation
- Update S-06 T-01 to invoke sub-agents instead of monolithic dry-run
- Aggregate results into `dry-run-notes.md` with Gap Resolution Table
- **Files**: `workflow/dry_run_tasks.py`, modify `routines/idea-to-plan.yaml`

### Phase 3: Task Reset on Re-Entry
- Add `entry_count` to `StepState`
- Implement `reset_step_on_re_entry()` - resets checklist to OPEN, preserves repo
- Call on backward transitions (S-04 → S-02 → S-05)
- Activate `TransitionTracker` enforcement
- **Files**: modify `state/models.py`, `workflow/engine.py`, `workflow/service.py`

### Phase 4: Update Routine Instructions
- Update S-04 T-01, S-05 T-01, S-09 T-02 task contexts
- Explicitly require reading and resolving dry-run-notes.md gaps
- Update S-07 to verify gaps are resolved
- **Files**: modify `routines/idea-to-plan.yaml`

### Phase 5: Integration Testing
- E2E test: Full cycle with dry-run feedback loop
- Verify repo state continues, task state resets
- Verify gap tracking and resolution
- **Files**: `tests/integration/test_idea_to_plan_full_cycle.py`

---

## Key Design Points

✅ **Sub-agents are blocking** (context switch, not fork)
- Parent waits for `return_message` tool call
- Errors returned like failed command execution

✅ **Each sub-agent has full context**
- No truncation (unlike current 4000-token limit dry-run)
- Task-specific prompt focuses the analysis

✅ **Dry-run-notes is a living document**
- Gaps marked with severity (REQUIRED/EXPECTED/OPTIONAL)
- As S-05+ resolves gaps, they mark them with specific actions taken
- If re-running, LLM searches for gaps again and re-adds any still missing with more detail

✅ **Repo state continues**
- Backward transitions only reset task checklist items to OPEN
- Git history and file changes preserved
- Allows iterative refinement without losing context

---

## Files to Create

```
src/orchestrator/agents/sub_agent.py (new)
src/orchestrator/workflow/dry_run_tasks.py (new)
tests/unit/test_sub_agents.py (new)
tests/unit/test_dry_run_tasks.py (new)
tests/unit/test_backward_transitions.py (new)
tests/integration/test_step_reset.py (new)
tests/integration/test_idea_to_plan_full_cycle.py (new)
```

## Files to Modify

```
src/orchestrator/agents/openhands.py
src/orchestrator/agents/cli.py
src/orchestrator/state/models.py
src/orchestrator/workflow/engine.py
src/orchestrator/workflow/service.py
routines/idea-to-plan.yaml
docs/planner/templates/dry-run-notes.md (updated ✅)
docs/ARCHITECTURE.md
```

---

## Reference Documents

- **Full implementation plan**: `docs/plan-runner/idea-to-plan-implementation-plan.md`
- **Architecture decisions**: `docs/plan-runner/idea-to-plan-implementation-gaps.md`
- **Updated dry-run template**: `docs/planner/templates/dry-run-notes.md`

---

## Ready to Start?

All decisions made. Ready to implement Phase 1 (Sub-Agent Infrastructure)?

The recommended approach:
1. Implement phases sequentially (each builds on previous)
2. Write tests as we go
3. After each phase, ensure system remains runnable and tests pass
4. Full integration testing in Phase 5
