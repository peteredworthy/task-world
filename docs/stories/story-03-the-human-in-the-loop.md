# Story 03: The Human in the Loop

*The agent gets stuck on a design question, Maya answers it, and then a step gate forces her to review before the agent moves on to the scary part.*

---

Maya's running the `database-migration` routine. It has two steps:

1. **Design** -- the agent proposes the schema change (one task, no gate)
2. **Implement** -- the agent writes the migration and updates the ORM (two tasks, human approval gate)

The approval gate on step 2 is deliberate. Schema migrations can destroy data. Maya's team doesn't let agents push those through unreviewed.

### The Agent Has a Question

The agent is building the first task (propose the schema change). It reads the existing models, looks at the requirements, and realizes the routine says "add user preferences" but doesn't specify whether preferences should be a JSON column or a normalized table.

The agent could guess. Instead, it asks:

```
POST /api/runs/{id}/tasks/propose-schema/clarifications
{
  "questions": [
    "Should user preferences be stored as a JSON column on the users table, or as a separate preferences table with key-value rows? JSON is simpler but harder to query. Normalized is more flexible but adds joins."
  ]
}
→ 201 { "clarification_id": "clr-9a2b", ... }
```

The task pauses:

```
[10:15:33] Task propose-schema: status → PENDING_USER_ACTION
[10:15:33] Clarification requested: "Should user preferences be stored as..."
```

Maya gets a notification in the UI. She sees the agent's question, thinks for a moment, and responds:

```
POST /api/runs/{id}/tasks/propose-schema/clarifications/clr-9a2b/respond
{
  "response": "JSON column. We only ever read the whole blob, never query individual preferences. Keep it simple."
}
→ 200
```

The task resumes:

```
[10:22:07] Clarification clr-9a2b: response received
[10:22:07] Task propose-schema: status → BUILDING
```

The agent gets a fresh builder prompt that now includes the clarification exchange -- Maya's answer is part of the context. It designs the schema with a JSON column, marks the checklist, submits. Verification passes on the first attempt. Step 1 complete.

### The Gate

Step 2 has a human approval gate: `gate: { type: "human_approval" }`. Before any tasks in step 2 can begin, Maya has to sign off.

```
[10:24:15] Step design: completed
[10:24:15] Step implement: waiting for human approval
```

The run doesn't pause (it's still ACTIVE) but the agent has nothing to do. It's waiting. Maya gets another notification.

She opens the run detail view and sees the agent's proposed schema from step 1 -- a clean diff adding a `preferences JSONB` column to the users table with a default of `{}`. She reads it, checks the migration is reversible, and approves:

```
POST /api/runs/{id}/steps/implement/approve
{ "comment": "Looks good. Make sure the migration is reversible." }
→ 200
```

Her comment becomes part of the context for step 2's tasks. The agent picks it up:

```
[10:31:44] Step implement: approved by Maya
[10:31:44] Task write-migration: status → BUILDING
```

The agent writes the Alembic migration, notes that Maya asked for reversibility, and makes sure the downgrade function drops the column cleanly. It handles the second task (update ORM models) in sequence. Both pass verification.

```
[10:35:12] Step implement: completed
[10:35:12] Run: status → COMPLETED
```

### What If She'd Rejected?

If Maya had rejected the step instead of approving:

```
POST /api/runs/{id}/steps/implement/reject
{ "comment": "The schema proposal doesn't handle the case where preferences exceed 1MB. Add a size constraint." }
```

The first step's task would have re-entered BUILDING with her feedback. The agent would get a fresh prompt including the rejection reason, revise the design, and re-submit. The gate would ask Maya again. No forward progress until she's satisfied.

This is the point of gates. The agent can do a lot of work autonomously, but there are moments where a human looking at the actual output is worth the interruption.

---

*This story covers: clarification requests, PENDING_USER_ACTION status, clarification responses, step approval gates, human approval, rejection flow, approval comments in context, multi-step routines, task sequencing within steps.*
