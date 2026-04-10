# Step File Structure Reference

Quick reference for reading and analyzing `STEP-XX.md` files.

---

## File Layout

```
# Step [N]: [Title]

[Context paragraph]

## Intent Verification
**Original Intent**: [Reference to intent.md requirement]
**Functionality to Produce**: [Bulleted list of observable outcomes]
**Final Verification Criteria**: [Bulleted list of how to evaluate the step]

---

## Task [N]: [Title]
**Description**: [Purpose]

**Implementation Plan (Do These Steps)**
- [ ] [Action, edit file, create file, run command]

**Dependencies (Optional)**
**References (Optional)**
**Constraints (Optional)**
**Side Effects (Optional)**

**Functionality (Expected Outcomes)**
- [ ] [What must be present when task is done]

**Final Verification (Proof of Completion)**
- [ ] [How to verify the task is complete]
```

Tasks are separated by `---` on its own line.

## Key Fields for Analysis

- **Implementation Plan**: the specific changes the builder will make
- **Functionality (Expected Outcomes)**: the observable contract — what "done" means
- **Final Verification**: the checks that prove completion; these can be presence-only or behavioral
- **Constraints**: explicit boundaries on what may not change
- **Dependencies**: preconditions that must exist before the task starts
