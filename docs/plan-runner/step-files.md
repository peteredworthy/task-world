# Guide to Creating `STEP-XX.md` Files

This document defines the structure and best practices for creating `STEP-XX.md` files used to guide AI implementation tasks. Adhering to this format ensures clarity, verifiability, and successful execution by the implementing AI.

---

## 1. File Structure Principles

### 1.1. Purpose

Each `STEP-XX.md` file represents a single, cohesive stage of a larger plan. It must:

- Be self-contained.
- Be broken down into atomic tasks.

### 1.2. Overall Layout

A STEP file has two main components:

- **Preamble Header**: Context and intent.
- **Task List**: A series of tasks separated by a marker.

```
# Step [step #]: [Descriptive Title]

[Context paragraph explaining the goal]

## Intent Verification
**Original Intent**: [Reference to specific intent.md requirement]
**Functionality to Produce**: [A bulleted list of the functionality that must be present once the step is complete]
**Final Verification Criteria**: [A bulleted list of how the step must be evaluated]

---

## Task 1: [Descriptive Title]
...
```

### 1.3. Preamble Header

- Begins with a **level 1 markdown heading** containing the step number and descriptive title.
- Followed by one or two paragraphs of explanatory text providing context.

### 1.4. Task Separator

- Each task is separated from the previous one by a line containing exactly three hyphens (`---`).
- The separator must be surrounded by blank lines for readability.

---

## 2. Task Format Requirements

Each task must follow a consistent structure to provide the AI with clear, unambiguous instructions.

- **Title**: A level 2 markdown heading describing the objective.

- **Description (Optional)**: A brief explanation of the goal.

- **Implementation Plan (Do These Steps)**: A checklist of the breakdown of changes that should be made, including edits, file creation, and commands to run.

  - Include fenced code blocks where appropriate with explicit code to be inserted or modified.
  - Use comments like `# existingcode` to indicate context without including the full file.
  - Include fenced shell command blocks that are suitable for direct execution.
  - May include inline verification checkpoints (e.g., run tests, lint checks) expressed as **actions** to perform before continuing.

- **Dependencies (Optional)**: Preconditions that must exist before starting (e.g., library must be installed).

- **References (Optional)**: Links to external documentation, related specs, or supporting material.

- **Constraints (Optional)**: Explicit boundaries for what may or may not change. Example:

  ```
  Only ClassY and ClassZ should have their functionality changed.
  No other class should be altered, except imports/references.
  ```

- **Side Effects (Optional)**: Known impacts, such as temporary breakage in another module.

- **Functionality (Expected Outcomes)**:

  This section defines the end-state that must exist once the task is complete.

  -

- **Final Verification (Proof of Completion)**:

  ⚠️ DO NOT perform these until all Implementation Plan items are complete. These must be repeated even if similar checks were performed earlier.

  -

````
# Task [Task #]: [Descriptive Title]
**Description**: 
[Description of the purpose of the task]

**Implementation Plan (Do These Steps)**
[Rationale / contextual notes explaining why the plan is structured this way]
- [ ] [Action, edit file, create file, run command]
```
[Optional code block(s) giving clear guidance on implementation]
```
- [ ] [Further breakdown action]

**Dependencies (Optional)**
- [ ] [Dependency that must exist]

**References (Optional)**
- [Link to relevant documentation]

**Constraints (Optional)**
- [ ] [Explicit boundary on what may or may not be changed]

**Side Effects (Optional)**
- [ ] [Known impacts]

**Functionality (Expected Outcomes)**
- [ ] [Functionality that must be present at the end of this task]
- [ ] [Functionality]

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] [Action that must be carried out to verify that the task is complete and successful]
- [ ] [Additional verification step]
````

---

## 3. Best Practices

- **Atomicity**: Each task should be the smallest possible unit of work that leaves the codebase valid and testable. Do not bundle unrelated changes.
- **Provide Full Context**: Include necessary background for libraries, APIs, or tools. For example:
  > This task uses LangChain's Pydantic output parser. It requires X, Y, and Z. See the [official documentation](https://example.com).
- **Be Explicit**:
  - Code in `implementation` must be copy-paste ready.
  - Commands in `command` must be directly executable.
  - Acceptance criteria must be objective, verifiable, and unambiguous.

