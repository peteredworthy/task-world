# JTBD and Workflows

This section captures the likely jobs to be done for Super Parent. Some items are inferred from the routine and current implementation, so open questions are called out explicitly.

## Primary JTBD

1. Start a large, underspecified goal and have the system break it into controlled child runs.
2. Understand what the parent currently believes about the work: scope, risks, ready slices, blockers, and required human input.
3. Monitor child runs without losing the connection between each child and the larger parent mission.
4. Evaluate child evidence and decide whether to accept, reject, retry, or abandon a slice.
5. Know why the parent cannot complete yet and what action would unblock it.
6. Review a final validation report that proves the intended target was addressed.

## Current User Journey

1. User creates a run and selects the Super Parent routine.
2. User provides generic routine inputs such as `instruction`, `source_artifacts`, and `max_child_runs`.
3. Parent run starts and creates or links child runs by slice.
4. User monitors the dashboard, where child and parent runs appear in the same flat list.
5. User opens the parent detail page to see a compact oversight panel.
6. User opens a child detail page to review normal run evidence, diff, and task state.
7. User returns to the parent detail page to accept a child when it reaches the merge queue.
8. User repeats until the terminal guard clears and final validation/reporting can happen.

## Desired Workflow Shape

1. Intake: capture the parent mission, source artifacts, child budget, and acceptance expectations.
2. Plan: show the target inventory and candidate slices before launching children.
3. Dispatch: launch child work with visible slice context and expected evidence.
4. Monitor: group child runs under the parent, highlight attention, and show child progress by slice.
5. Decide: review child evidence in terms of parent goals, then accept/reject/retry/abandon.
6. Validate: show final validation status, remaining unresolved inventory, and report readiness.
7. Complete: present a final summary of accepted work, unresolved items, and verification evidence.

## Open JTBD Questions

- Who is the primary operator: the original requester, a technical reviewer, or someone managing many agent runs?
- Should the parent choose and launch child runs autonomously, or should the user approve each slice before launch?
- What is the expected evidence standard for accepting a child run: tests, screenshots, code diff, logs, written report, or all of these?
- Should unresolved target inventory block completion by default, or can the user intentionally waive items?
- How often should the UI refresh oversight state automatically versus requiring an explicit refresh?
- Is the child budget primarily a cost control, a parallelism control, or a scope control?
- Should child runs inherit a specialized UI from Super Parent, or stay as normal run detail pages with parent context added?
