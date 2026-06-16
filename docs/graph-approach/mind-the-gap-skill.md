# Mind the Gap Skill

Use this skill when a clear implementation target should be completed through
repeated planner/gap-finder, builder, and validator cycles while preserving
orchestrator context. Do not use it for vague goals that need specification
first.

Use when the implementation target is already clear. If the goal, constraints,
or success criteria are vague, clarify or create a spec first.

Before starting, establish the test baseline. The loop requires that each
validated chunk leaves all relevant tests passing. If existing tests already
fail, record the known failures so new work is not credited with causing or
fixing them.

Implement in repeated verified chunks while protecting orchestrator context.

## Core Pattern

The orchestrator owns durable state. Sub-agents focus on one role and protect
the orchestrator's context.

Loop:

1. Planner / Gap Finder compares the target with the current verified state and
   selects the next small, independently verifiable chunk.
2. Builder implements only that chunk.
3. Validator independently checks the chunk against the intended behavior and
   verification conditions. Relevant tests must pass for a chunk to be
   validated. A chunk is not valid if tests fail because they still assert
   obsolete behavior; update those tests, or explicitly justify removing or
   skipping them.
4. If validation fails, return the Validator's specific correction to the
   Builder.
5. Repeat Builder / Validator until pass, retry limit, or escalation. Default
   retry limit is 5.
6. On pass, update durable state with verified behavior, evidence, decisions,
   risks, and remaining gaps.
7. Return to Planner / Gap Finder for the next chunk.

Use fresh Builder and Validator agents for each chunk. Replace the Planner / Gap
Finder when it approaches 50% of the model context limit.

## Routing

If available, route messages directly between Builder and Validator. Otherwise,
the orchestrator passes messages between agents.

Direct routing is an optimization only. The orchestrator must still review the
validation evidence and record the verified result before the next planning
pass.

## Context Discipline

Pass sub-agents only the target slice, relevant verified state, constraints, and
validation conditions they need.

Keep durable state compact. Preserve verified facts, decisions, validation
evidence, risks, and remaining gaps. Discard verbose logs, stale plans, failed
attempt detail, and full sub-agent transcripts unless they explain a current
constraint.

## Cost And Tool Discipline

For each role, use the cheapest model, reasoning effort, permissions, tools, and
MCPs capable of doing the job well.

Planner / Gap Finder may need stronger reasoning. Builder needs edit access only
for the assigned chunk. Validator should be independent and preferably
read/test-only.

Escalate instead of thrashing when requirements conflict, validation repeatedly
fails, required access is missing, or the next step is risky or irreversible.
