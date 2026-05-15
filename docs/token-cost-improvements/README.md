# Token and Cost Improvement Options

This directory collects options for reducing token usage, model cost, and
unnecessary agent calls in orchestrator runs.

The first pass is based on the token/call audit of run
`14758f82-82d6-4e20-9d2f-c3c85c65d29f`, where the parent run reached a pause
after spending roughly 7.4M parent tokens, 222 parent tool calls, and 235 parent
turns.

## Summary

The five improvement buckets can be summarized as:

1. **Reduce initial and repeated context size.**
   Oversight state is the easiest high-impact target because it is repeatedly
   carried through fresh parent phases.
2. **Include child state in the child-result handoff.**
   This is probably a smaller win, but it is easy to combine with the broader
   state-choice fixes because evidence readiness and terminal readiness were
   queried separately.
3. **Fix routines that attempt impossible actions.**
   The audited run planned parallel child execution even though the platform
   currently allows only one unresolved child per parent.
4. **Improve canonical tool guidance to avoid failed calls.**
   Audit guidance for conflicts, pick one canonical place for tool contracts,
   and keep routines/prompts aligned with it.
5. **Route work to cheaper models where appropriate.**
   This mostly saves money. It may also save some tokens because higher-end
   models often produce longer reasoning and status output for mechanical work.

## Option Notes

- [01 - Reduce Context Size](01-reduce-context-size.md)
- [02 - Child Result State Handoff](02-child-result-state-handoff.md)
- [03 - Routine Capability Gating](03-routine-capability-gating.md)
- [04 - Canonical Tool Guidance](04-canonical-tool-guidance.md)
- [05 - Model Routing](05-model-routing.md)

## Suggested Order

1. Start with routine capability gating because it prevents the specific pause
   mode from recurring.
2. In the same slice, add child-state handoff fields so the parent does not need
   to rediscover simple state.
3. Compress oversight state into a compact machine ledger and keep Markdown as
   human-readable audit material.
4. Audit tool guidance and make the canonical source explicit.
5. Add model routing after the shape of the work is stable.

