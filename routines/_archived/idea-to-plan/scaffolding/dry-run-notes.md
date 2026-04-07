# Dry Run Notes: {{feature}}

## Execution Simulation

<!-- Walk through each task mentally and document what would happen -->

## Assumptions

<!-- Key assumptions being made during the planning -->

-

## Persistence Mapping Audit

<!-- For any step that adds fields to state models (TaskState, StepState, Run, etc.),
     trace the full persistence path. The field existing on the model is not enough —
     it must also be read and written by the repository layer, and have a DB column
     if it needs to survive server restarts.

     Fill in every cell. Any "MISSING" blocks the verification report. -->

| State Model Field | DB Column (model.py) | Repo Write (_to_model) | Repo Read (_to_state) | Migration |
|---|---|---|---|---|
| <!-- e.g. TaskState.my_field --> | <!-- TaskModel.my_field --> | <!-- ✅ or MISSING --> | <!-- ✅ or MISSING --> | <!-- ✅ or N/A --> |

<!-- Also check: if a Pydantic model is stored as JSON in a dict column (e.g. in
     run.config), it will deserialize as a dict, not the model. Any code that reads
     it back must handle dict→model conversion. List such cases here: -->

**Dict-to-model conversion risks:**
-

## Identified Gaps

### Gap 1

- **Description:**
- **Impact:**
- **Resolution:** <!-- How to address this gap -->
- **Applied to step files:** <!-- YES with diff summary, or NO — must be YES before verification report can pass -->

### Gap 2

- **Description:**
- **Impact:**
- **Resolution:**
- **Applied to step files:** <!-- YES with diff summary, or NO -->

## Potential Blockers

### Blocker 1

- **Description:**
- **Likelihood:** High | Medium | Low
- **Mitigation:**

## Lessons from Simulation

<!-- What did we learn from mentally walking through the execution? -->

-
