# Example Configuration Files

Examples reflecting the simplified schema (no ref/use inheritance).

---

## 1. Global Configuration

```yaml
# ~/.orchestrator/config.yaml
server:
  host: "0.0.0.0"
  port: 8080

database:
  path: "~/.orchestrator/orchestrator.db"

routines:
  local_dir: "~/.orchestrator/routines"
  external_allowlist:
    - "git@github.com:myorg/shared-routines.git"

agents:
  default_type: "cli_subprocess"
  openhands_url: "http://localhost:3000"
  user_managed_timeout_minutes: 60  # Inactivity timeout for user-managed agents

dashboard:
  recent_hours: 24  # 1, 4, 24, 168

nudger:
  output_timeout: 60
  nudge_interval: 30
  max_nudges: 3

websocket:
  batching_enabled: true       # Enable event batching (default: true)
  batch_window_seconds: 0.1    # Collect events for 100ms before sending (default: 0.1)
```

---

## 2. Project Configuration

```yaml
# {project}/orchestrator.yaml
project:
  name: "my-project"

routines:
  dir: "routines"  # Must be git-tracked

worktree:
  enabled: true  # Default
  base_dir: ".worktrees"

completion:
  delete_worktree: false  # Default: keep worktree
```

---

## 3. Planning Routine (Simplified)

> Note: Both singular `task:` and plural `tasks:` are accepted. The plural form is canonical.

```yaml
# routines/planning.yaml
# NOTE: Must be committed to git before use

routine:
  id: "planning"
  name: "Feature Planning"
  description: "Plan a feature and generate implementation routine"
  
  inputs:
    - name: "feature_name"
      required: true
      description: "Name of the feature"
    - name: "target_branch"
      required: false
      default: "main"

  steps:
    - id: "S-01"
      title: "Requirements Gathering"
      step_context: "Gather requirements for the feature."
      
      task:
        id: "T-01"
        title: "Create Requirements Document"
        task_context: |
          Create a requirements document for {{feature_name}}.
          
          Include:
          - User stories (at least 3)
          - Acceptance criteria
          - Non-functional requirements
        
        # Model-specific overrides (optional)
        model_overrides:
          "claude-sonnet-4-20250514":
            task_context: |
              Create a requirements document for {{feature_name}}.
              
              Use structured thinking. Include:
              - User stories (at least 3, use "As a... I want... So that...")
              - Acceptance criteria (testable)
              - Non-functional requirements
          "gpt-4-turbo":
            task_context: |
              Create a requirements document for {{feature_name}}.
              
              Format with clear headers. Include:
              - User stories (minimum 3)
              - Acceptance criteria per story
              - NFRs section
        
        # Explicit requirements - no ref/use
        requirements:
          - id: "R1"
            desc: "Create docs/{{feature_name}}/requirements.md"
            must: true
            priority: critical
          - id: "R2"
            desc: "Include at least 3 user stories"
            must: true
            priority: critical
          - id: "R3"
            desc: "Define acceptance criteria"
            must: true
            priority: expected
          - id: "R4"
            desc: "Identify risks"
            must: false
            priority: nice
        
        auto_verify:
          items:
            - id: "file_exists"
              cmd: "test -f docs/{{feature_name}}/requirements.md"
              must: true
            - id: "has_stories"
              cmd: "grep -c 'As a' docs/{{feature_name}}/requirements.md | test $(cat) -ge 3"
              must: true
          tail_lines: 20
        
        verifier:
          rubric:
            - id: "quality"
              text: "Are requirements clear, specific, and testable?"
            - id: "coverage"
              text: "Do user stories cover the main use cases?"
          submission_template:
            grade_scale: [A, B, C, D, F]
            require_reason_if_below: A
            require_remediation_if_below: B
        
        retry:
          max_attempts: 3

    - id: "S-02"
      title: "Generate Implementation Routine"
      
      task:
        id: "T-01"
        title: "Create Implementation Routine"
        task_context: |
          Based on the requirements, create an implementation routine.
          
          Output: routines/implement-{{feature_name}}.yaml
        
        requirements:
          - id: "R1"
            desc: "Create implementation routine YAML"
            must: true
            priority: critical
          - id: "R2"
            desc: "Routine has clear step breakdown"
            must: true
            priority: expected
        
        auto_verify:
          items:
            - id: "routine_exists"
              cmd: "test -f routines/implement-{{feature_name}}.yaml"
              must: true
            - id: "routine_valid"
              cmd: "orchestrator routine validate routines/implement-{{feature_name}}.yaml"
              must: true
          tail_lines: 30
        
        verifier:
          rubric:
            - id: "structure"
              text: "Is the routine well-structured with appropriate task granularity?"
          submission_template:
            grade_scale: [A, B, C, D, F]
            require_reason_if_below: A
            require_remediation_if_below: B
        
        retry:
          max_attempts: 2
```

---

## 4. Bug Fix Routine (Simplified)

> Note: Both singular `task:` and plural `tasks:` are accepted. The plural form is canonical.

```yaml
# routines/bug-fix.yaml

routine:
  id: "bug-fix"
  name: "Bug Fix"
  description: "Investigate and fix a bug"
  
  inputs:
    - name: "issue_id"
      required: true
    - name: "description"
      required: true
    - name: "reproduction_steps"
      required: false

  steps:
    - id: "S-01"
      title: "Investigation"
      
      task:
        id: "T-01"
        title: "Root Cause Analysis"
        task_context: |
          Investigate: {{issue_id}}
          Description: {{description}}
          {% if reproduction_steps %}
          Reproduction: {{reproduction_steps}}
          {% endif %}
          
          Document root cause and affected code paths.
        
        requirements:
          - id: "R1"
            desc: "Identify root cause"
            must: true
            priority: critical
          - id: "R2"
            desc: "Document affected code"
            must: true
            priority: expected
        
        auto_verify:
          items:
            - id: "notes"
              cmd: "test -f investigation-{{issue_id}}.md"
              must: false
          tail_lines: 20
        
        verifier:
          rubric:
            - id: "accuracy"
              text: "Is root cause correctly identified with evidence?"
          submission_template:
            grade_scale: [A, B, C, D, F]
            require_reason_if_below: B
            require_remediation_if_below: C
        
        retry:
          max_attempts: 2

    - id: "S-02"
      title: "Fix Implementation"
      
      task:
        id: "T-01"
        title: "Implement Fix"
        task_context: |
          Implement fix for {{issue_id}}.
          
          Ensure:
          - Fix addresses root cause
          - Add regression test
          - No side effects
        
        requirements:
          - id: "R1"
            desc: "Fix addresses root cause"
            must: true
            priority: critical
          - id: "R2"
            desc: "Add regression test"
            must: true
            priority: critical
          - id: "R3"
            desc: "Update docs if needed"
            must: false
            priority: nice
        
        auto_verify:
          items:
            - id: "types"
              cmd: "uv run pyright"
              must: true
            - id: "lint"
              cmd: "uv run ruff check ."
              must: true
            - id: "tests"
              cmd: "uv run pytest -q"
              must: true
            - id: "regression"
              cmd: "uv run pytest -k '{{issue_id}}' -v"
              must: true
          tail_lines: 30
        
        verifier:
          rubric:
            - id: "fix_quality"
              text: "Does fix address root cause without side effects?"
            - id: "test_quality"
              text: "Will regression test prevent recurrence?"
          submission_template:
            grade_scale: [A, B, C, D, F]
            require_reason_if_below: A
            require_remediation_if_below: B
        
        retry:
          max_attempts: 3
```

---

## 5. Creating a Run (API)

### With Referenced Routine

```json
POST /api/runs
{
  "project_id": "proj-123",
  "routine_id": "planning",
  "routine_source": "local",
  "config": {
    "feature_name": "user-auth",
    "target_branch": "main"
  },
  "worktree_enabled": true,
  "delete_worktree_on_completion": false
}
```

### Get Available Agents

```json
GET /api/runs/run-456/agents

Response:
{
  "agents": [
    {
      "type": "openhands_local",
      "name": "OpenHands (Local)",
      "available": true
    },
    {
      "type": "cli_subprocess",
      "name": "Claude CLI",
      "available": true,
      "cli_command": "claude"
    },
    {
      "type": "user_managed",
      "name": "User Managed",
      "available": true
    }
  ]
}
```

### Start with Selected Agent

```json
POST /api/runs/run-456/start
{
  "agent_type": "openhands_local"
}
```

---

## 6. Embedded Routine (One-Shot)

```json
POST /api/runs
{
  "project_id": "proj-123",
  "routine_embedded": {
    "id": "implement-auth",
    "name": "Implement Auth",
    "steps": [
      {
        "id": "S-01",
        "title": "Create Module",
        "task": {
          "id": "T-01",
          "title": "Module Structure",
          "task_context": "Create src/auth/ module structure",
          "requirements": [
            {
              "id": "R1",
              "desc": "Create src/auth/__init__.py",
              "must": true,
              "priority": "critical"
            }
          ],
          "auto_verify": {
            "items": [
              {
                "id": "check",
                "cmd": "test -d src/auth",
                "must": true
              }
            ],
            "tail_lines": 20
          },
          "verifier": {
            "rubric": [
              {"id": "q", "text": "Is structure correct?"}
            ],
            "submission_template": {
              "grade_scale": ["A","B","C","D","F"],
              "require_reason_if_below": "A",
              "require_remediation_if_below": "B"
            }
          },
          "retry": {"max_attempts": 3}
        }
      }
    ]
  },
  "config": {},
  "agent_type": "cli_subprocess"
}
```

---

## 7. CLI Examples

```bash
# List routines
orchestrator routine list

# Validate before commit
orchestrator routine validate routines/planning.yaml

# Create run
orchestrator run create planning \
  --project ./my-project \
  --config '{"feature_name": "auth"}'

# Check available agents
orchestrator run agents run-123

# Start with specific agent
orchestrator run start run-123 --agent openhands

# Check status
orchestrator run status run-123

# List active runs
orchestrator run list --status active

# List recent (last 4 hours)
orchestrator run list --recent 4
```

---

## Key Points

1. **No ref/use** - All config is explicit, no inheritance
2. **Must commit** - Routines must be in git and committed
3. **User selects agent** - No auto-selection
4. **Model overrides** - Optional per-model task_context
5. **Completion actions** - Configure what happens when done
