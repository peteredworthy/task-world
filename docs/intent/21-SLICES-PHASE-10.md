# Implementation Slices: Phase 10 - Advanced Configuration & Clarification

**Goal:** Enable sophisticated workflow customization including clarification pauses, model escalation, MCP client integration, and per-task tool configuration.

**End state:** Users can configure model hierarchies with automatic escalation, pause workflows for human clarification via UI or CLI, connect to external MCP servers, and control which tools are available per step/task.

**Prerequisites:** Phases 1-5 complete, Phase 9 (human gates) helpful but not required.

---

## Context: What We're Solving

From Traycer community feedback and real-world planning workflows:

1. **Clarification mid-flow** — Agent hits ambiguity, needs human input, then continues (not fails)
2. **Model escalation** — Start cheap, auto-upgrade on failure, fresh context on escalation
3. **MCP client consumption** — Pull context from GitHub, Linear, etc. into tasks
4. **Tool scoping** — Different tasks need different tools; don't give everything to everyone
5. **Inheritance with override** — Define once at routine level, override at step/task

---

## Slice 10.1: Clarification State Machine

### Goal
Add a `PAUSED_FOR_CLARIFICATION` state that allows builder or verifier to request human input without failing.

### Prerequisites
- Slice 2.3 (task state machine) complete
- Slice 9.1 (human gates) complete

### Deliverables

```
src/orchestrator/workflow/
├── clarification.py    # Clarification request/response handling
├── states.py           # Extended state enum
tests/unit/test_clarification.py
tests/integration/test_clarification_flow.py
```

### Architecture Constraints

1. **Clarification is not failure** — Task remains in progress, just paused
2. **Context preservation** — Clarification Q&A becomes part of task context
3. **Multiple rounds allowed** — Agent can ask follow-ups
4. **Timeout configurable** — Eventually fails if no response
5. **Works for both builder and verifier** — Same mechanism, different prompts

### State Machine Extension

```
                              ┌─────────────┐
                              │   PENDING   │
                              └──────┬──────┘
                                     │ start
                                     ▼
                              ┌─────────────┐
                    ┌────────▶│  BUILDING   │◀────────┐
                    │         └──────┬──────┘         │
                    │                │                │
                    │    ┌───────────┴───────────┐    │
                    │    │                       │    │
                    │ submit              request_clarification
                    │    │                       │    │
                    │    ▼                       ▼    │
                    │  [gates]        ┌──────────────────┐
                    │    │            │ PAUSED_BUILDING  │
                    │    │            │ (clarification)  │
                    │    │            └────────┬─────────┘
                    │    │                     │ provide_clarification
                    │    │                     │
                    │    │    ┌────────────────┘
                    │    │    │
                    │    ▼    ▼
                    │  [gates pass?]
                    │    │
               fail │    │ pass
                    │    ▼
                    │  ┌─────────────┐
                    │  │  VERIFYING  │◀──────────────┐
                    │  └──────┬──────┘               │
                    │         │                      │
                    │    ┌────┴────┐                 │
                    │    │         │    request_clarification
                    │ submit    │                 │
                    │    │         ▼                 │
                    │    │  ┌──────────────────┐     │
                    │    │  │ PAUSED_VERIFYING │     │
                    │    │  │ (clarification)  │     │
                    │    │  └────────┬─────────┘     │
                    │    │           │ provide_clarification
                    │    │           └───────────────┘
                    │    │
                    │    ▼
                    │  [verify result]
                    │    │
                    ▼    ▼
              [revision] [complete]
```

### Data Models

```python
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class ClarificationType(Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    FREE_TEXT = "free_text"
    YES_NO = "yes_no"
    CODE_CHECK = "code_check"  # Agent should verify against codebase

class ClarificationRequest(BaseModel):
    """A request for clarification from builder or verifier."""
    id: str
    run_id: str
    step_id: str
    task_id: str
    attempt_id: str
    phase: str  # "building" or "verifying"
    
    question: str
    context: str  # Why this clarification is needed
    clarification_type: ClarificationType
    
    # For multiple choice
    options: list[str] | None = None
    suggested_default: str | None = None
    
    # For code_check - agent suggests checking codebase instead of asking human
    code_check_suggestion: str | None = None
    
    requested_at: datetime
    timeout_at: datetime | None = None

class ClarificationResponse(BaseModel):
    """Human response to a clarification request."""
    request_id: str
    response: str
    responded_by: str  # User identifier
    responded_at: datetime
    
    # If human redirected to code check
    redirected_to_code_check: bool = False
    code_check_query: str | None = None

class ClarificationLog(BaseModel):
    """Full log of clarification exchanges for a task."""
    task_id: str
    exchanges: list[tuple[ClarificationRequest, ClarificationResponse]]
    
    def to_context_block(self) -> str:
        """Format for injection into agent prompt."""
        if not self.exchanges:
            return ""
        
        lines = ["## Clarifications Received\n"]
        lines.append("The following clarifications were requested and answered:\n")
        
        for i, (req, resp) in enumerate(self.exchanges, 1):
            lines.append(f"### Clarification {i}")
            lines.append(f"**Question:** {req.question}")
            lines.append(f"**Context:** {req.context}")
            if req.options:
                lines.append(f"**Options presented:** {', '.join(req.options)}")
            lines.append(f"**Answer:** {resp.response}")
            if resp.redirected_to_code_check:
                lines.append(f"*(Verified against codebase: {resp.code_check_query})*")
            lines.append("")
        
        return "\n".join(lines)
```

### Clarification File Format

Clarifications persist to a file in the worktree for reference throughout planning:

```markdown
# Clarifications Log
<!-- Auto-generated by Orchestrator. Referenced throughout workflow. -->

## Clarification 1 (Step S-01, Building)
**Requested:** 2025-02-02T10:30:00Z
**Question:** Should the authentication module support OAuth2 or just username/password?
**Context:** The requirements mention "secure login" but don't specify the auth method.
**Options:** 
- OAuth2 only
- Username/password only  
- Both OAuth2 and username/password
**Answer:** Both OAuth2 and username/password
**Answered by:** peter@example.com

## Clarification 2 (Step S-03, Verifying)
**Requested:** 2025-02-02T11:45:00Z
**Question:** The rate limiting implementation uses a sliding window. Is 100 requests/minute acceptable?
**Context:** No rate limit was specified in requirements.
**Answer:** Yes, 100/minute is fine for MVP. Add a config option for production tuning.
**Answered by:** peter@example.com

## Clarification 3 (Step S-04, Building)
**Requested:** 2025-02-02T14:00:00Z
**Question:** Which database should be used for session storage?
**Context:** Architecture doc mentions PostgreSQL for main data but doesn't specify session store.
**Redirected to code check:** Yes
**Code check query:** "What database connections exist in the codebase?"
**Code check result:** Found Redis connection in src/cache.py, PostgreSQL in src/db.py
**Answer:** Use Redis for sessions (already configured)
```

### Schema Extension

```yaml
# Routine-level defaults
routine:
  clarification:
    enabled: true
    timeout: 30m
    max_per_task: 5
    log_file: "docs/{{feature}}/clarifications.md"
    
# Task-level override
task:
  clarification:
    enabled: true  # Can disable for fully automated tasks
    timeout: 1h    # Override timeout
    
    # Encourage structured questions
    prefer_multiple_choice: true
    require_context: true
    
    # Allow agent to self-answer via code check
    allow_code_check_redirect: true
```

### Implementation

```python
class ClarificationManager:
    """Manage clarification requests and responses."""
    
    def __init__(
        self,
        repository: ClarificationRepository,
        file_writer: ClarificationFileWriter,
        time_provider: Callable[[], datetime],
    ):
        self._repo = repository
        self._file_writer = file_writer
        self._now = time_provider
    
    async def request_clarification(
        self,
        run_id: str,
        step_id: str,
        task_id: str,
        attempt_id: str,
        phase: str,
        question: str,
        context: str,
        clarification_type: ClarificationType,
        options: list[str] | None = None,
        timeout: timedelta | None = None,
    ) -> ClarificationRequest:
        """
        Create a clarification request and pause the task.
        
        Returns the request; caller is responsible for transitioning task state.
        """
        request = ClarificationRequest(
            id=generate_id(),
            run_id=run_id,
            step_id=step_id,
            task_id=task_id,
            attempt_id=attempt_id,
            phase=phase,
            question=question,
            context=context,
            clarification_type=clarification_type,
            options=options,
            requested_at=self._now(),
            timeout_at=self._now() + timeout if timeout else None,
        )
        
        await self._repo.save_request(request)
        return request
    
    async def provide_clarification(
        self,
        request_id: str,
        response: str,
        responded_by: str,
        redirected_to_code_check: bool = False,
        code_check_query: str | None = None,
    ) -> ClarificationResponse:
        """
        Provide a response to a clarification request.
        
        Updates the log file and returns the response.
        Caller is responsible for resuming task execution.
        """
        request = await self._repo.get_request(request_id)
        if not request:
            raise ClarificationNotFoundError(request_id)
        
        response_obj = ClarificationResponse(
            request_id=request_id,
            response=response,
            responded_by=responded_by,
            responded_at=self._now(),
            redirected_to_code_check=redirected_to_code_check,
            code_check_query=code_check_query,
        )
        
        await self._repo.save_response(response_obj)
        
        # Update the clarifications log file
        await self._file_writer.append_exchange(
            run_id=request.run_id,
            request=request,
            response=response_obj,
        )
        
        return response_obj
    
    async def get_clarification_log(self, task_id: str) -> ClarificationLog:
        """Get all clarification exchanges for a task."""
        exchanges = await self._repo.get_exchanges_for_task(task_id)
        return ClarificationLog(task_id=task_id, exchanges=exchanges)
    
    async def check_timeout(self, request_id: str) -> bool:
        """Check if a clarification request has timed out."""
        request = await self._repo.get_request(request_id)
        if not request or not request.timeout_at:
            return False
        return self._now() > request.timeout_at
```

### Prompt Augmentation

When resuming after clarification:

```python
def build_post_clarification_prompt(
    original_task_context: str,
    clarification_log: ClarificationLog,
    latest_exchange: tuple[ClarificationRequest, ClarificationResponse],
) -> str:
    """Build prompt for resuming after clarification."""
    
    req, resp = latest_exchange
    
    return f"""
{original_task_context}

---

## CLARIFICATION RECEIVED

You previously requested clarification on the following:

**Your question:** {req.question}
**Context you provided:** {req.context}

**Answer received:** {resp.response}

Please proceed with the task, incorporating this clarification.

---

## ALL CLARIFICATIONS FOR THIS WORKFLOW

{clarification_log.to_context_block()}

---

Continue with the task. The clarification above should resolve your question.
"""
```

### API Endpoints

```python
@router.post("/api/runs/{run_id}/clarifications")
async def request_clarification(
    run_id: str,
    request: ClarificationRequestInput,
) -> ClarificationRequest:
    """Agent requests clarification (called via MCP tool)."""
    
@router.get("/api/runs/{run_id}/clarifications/pending")
async def get_pending_clarifications(
    run_id: str,
) -> list[ClarificationRequest]:
    """Get all pending clarification requests for a run."""

@router.post("/api/clarifications/{request_id}/respond")
async def respond_to_clarification(
    request_id: str,
    response: ClarificationResponseInput,
    current_user: str = Depends(get_current_user),
) -> ClarificationResponse:
    """Human provides clarification response."""

@router.post("/api/clarifications/{request_id}/redirect-to-code-check")
async def redirect_to_code_check(
    request_id: str,
    query: str,
    current_user: str = Depends(get_current_user),
) -> ClarificationResponse:
    """Human redirects clarification to agent code check."""
```

### CLI Interface

```bash
# List pending clarifications
orchestrator clarifications list --run <run-id>
orchestrator clarifications list --all-pending

# Interactive mode - work through clarifications one by one
orchestrator clarifications interactive --run <run-id>
# Prompts:
# [1/3] Step S-01 (Building) asks:
# Question: Should auth support OAuth2 or username/password?
# Options: [1] OAuth2 only [2] Username/password [3] Both
# Your answer (or 'skip', 'code-check <query>'): 3

# Respond to specific clarification
orchestrator clarifications respond <request-id> --answer "Both OAuth2 and username/password"

# Redirect to code check
orchestrator clarifications respond <request-id> --code-check "What auth methods exist in codebase?"

# Dump pending to file, edit, import back
orchestrator clarifications export --run <run-id> --output clarifications.yaml
# Edit the file...
orchestrator clarifications import clarifications.yaml

# Batch respond from file
orchestrator clarifications batch-respond responses.yaml
```

### File-Based Workflow

For users who prefer file-based interaction:

```yaml
# clarifications-pending.yaml (exported)
run_id: "run-123"
pending:
  - id: "clar-001"
    step: "S-01"
    phase: "building"
    question: "Should auth support OAuth2 or username/password?"
    options:
      - "OAuth2 only"
      - "Username/password only"
      - "Both"
    response: ""  # Fill this in
    
  - id: "clar-002"
    step: "S-03"
    phase: "verifying"
    question: "Is 100 requests/minute rate limit acceptable?"
    response: ""  # Fill this in
```

```yaml
# clarifications-responses.yaml (user fills in)
responses:
  - id: "clar-001"
    response: "Both"
  - id: "clar-002"
    response: "Yes, with config option for production"
    redirect_to_code_check: false
```

### Verification

#### Unit Tests
- Clarification request creation
- Response handling
- Timeout checking
- Log formatting
- Prompt augmentation

#### Integration Tests
- Full flow: request → pause → respond → resume
- Multiple clarifications in sequence
- Timeout triggers failure
- Code check redirect flow
- File-based workflow

#### E2E Tests
- CLI interactive mode
- File export/import cycle
- API flow

### Definition of Done
- [ ] ClarificationRequest/Response models
- [ ] State machine extended with PAUSED states
- [ ] ClarificationManager implemented
- [ ] Log file writing works
- [ ] Prompt augmentation includes all clarifications
- [ ] API endpoints work
- [ ] CLI commands work
- [ ] File-based workflow works

---

## Slice 10.2: Model Configuration Inheritance

### Goal
Define model configuration at routine level with inheritance and override at step/task level.

### Prerequisites
- Slice 1.3 (routine loading) complete

### Deliverables

```
src/orchestrator/config/
├── model_config.py     # Model configuration with inheritance
tests/unit/test_model_inheritance.py
```

### Architecture Constraints

1. **Routine-level defaults** — Define once, apply everywhere
2. **Step-level override** — Override for a specific step
3. **Task-level override** — Override for a specific task (highest priority)
4. **Separate builder/verifier** — Different models for different roles
5. **No inheritance in routine file** — Config resolved at load time, not runtime

### Schema

```yaml
routine:
  id: "feature-implementation"
  
  # Routine-level defaults (applies to all steps/tasks)
  models:
    builder:
      model: "claude-sonnet-4-20250514"
      temperature: 0.7
      max_tokens: 8000
    verifier:
      model: "claude-sonnet-4-20250514"
      temperature: 0.2
      max_tokens: 4000
  
  steps:
    - id: "S-01"
      title: "Complex Design"
      
      # Step-level override (applies to all tasks in this step)
      models:
        builder:
          model: "claude-opus-4-20250514"  # Upgrade for complex step
      
      task:
        id: "T-01"
        title: "Architecture Design"
        
        # Task-level override (highest priority)
        models:
          builder:
            temperature: 0.9  # More creative for design
        
        # ... rest of task config

    - id: "S-02"
      title: "Implementation"
      # No override - uses routine defaults
      
      task:
        id: "T-01"
        title: "Write Code"
        # No override - uses routine defaults
```

### Resolution Logic

```python
from pydantic import BaseModel
from typing import Any

class ModelConfig(BaseModel):
    """Configuration for a single model."""
    model: str
    temperature: float = 0.7
    max_tokens: int = 8000
    # Add other model params as needed

class ModelsConfig(BaseModel):
    """Builder and verifier model configuration."""
    builder: ModelConfig
    verifier: ModelConfig

def resolve_models_config(
    routine_models: ModelsConfig | None,
    step_models: dict[str, Any] | None,
    task_models: dict[str, Any] | None,
) -> ModelsConfig:
    """
    Resolve model configuration with inheritance.
    
    Priority: task > step > routine > defaults
    
    Merges at the field level, not replacement.
    """
    # Start with defaults
    defaults = ModelsConfig(
        builder=ModelConfig(
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=8000,
        ),
        verifier=ModelConfig(
            model="claude-sonnet-4-20250514",
            temperature=0.2,
            max_tokens=4000,
        ),
    )
    
    # Layer routine config
    result = defaults
    if routine_models:
        result = _merge_models_config(result, routine_models)
    
    # Layer step config (partial override)
    if step_models:
        result = _merge_models_config_partial(result, step_models)
    
    # Layer task config (partial override)
    if task_models:
        result = _merge_models_config_partial(result, task_models)
    
    return result

def _merge_models_config(base: ModelsConfig, override: ModelsConfig) -> ModelsConfig:
    """Merge two complete ModelsConfig objects."""
    return ModelsConfig(
        builder=_merge_model_config(base.builder, override.builder),
        verifier=_merge_model_config(base.verifier, override.verifier),
    )

def _merge_models_config_partial(base: ModelsConfig, partial: dict) -> ModelsConfig:
    """Merge a partial override dict into ModelsConfig."""
    result = base.model_copy()
    
    if "builder" in partial:
        builder_dict = result.builder.model_dump()
        builder_dict.update(partial["builder"])
        result.builder = ModelConfig(**builder_dict)
    
    if "verifier" in partial:
        verifier_dict = result.verifier.model_dump()
        verifier_dict.update(partial["verifier"])
        result.verifier = ModelConfig(**verifier_dict)
    
    return result

def _merge_model_config(base: ModelConfig, override: ModelConfig) -> ModelConfig:
    """Merge two ModelConfig objects, override wins for set fields."""
    base_dict = base.model_dump()
    override_dict = override.model_dump(exclude_unset=True)
    base_dict.update(override_dict)
    return ModelConfig(**base_dict)
```

### Verification

#### Unit Tests
- Default resolution
- Routine-level override
- Step-level partial override
- Task-level partial override
- Full inheritance chain
- Builder/verifier independence

### Definition of Done
- [ ] ModelsConfig schema defined
- [ ] Resolution logic implemented
- [ ] Partial override merging works
- [ ] Integrated with routine loading

---

## Slice 10.3: Model Escalation on Failure

### Goal
Automatically escalate to more capable (expensive) models after N failures, with option for fresh context.

### Prerequisites
- Slice 10.2 (model inheritance) complete
- Slice 2.4 (workflow engine) complete

### Deliverables

```
src/orchestrator/workflow/
├── escalation.py       # Escalation logic
tests/unit/test_escalation.py
```

### Architecture Constraints

1. **Two-tier escalation** — Normal models, then escalation models
2. **Configurable trigger** — Escalate after N failures at normal tier
3. **Fresh start option** — Discard prior attempts, fresh checkout
4. **Preserve clarifications** — Clarifications survive escalation
5. **Separate builder/verifier escalation** — Can escalate independently

### Schema

```yaml
routine:
  models:
    builder:
      model: "claude-haiku-4-20250514"  # Start cheap
      temperature: 0.7
    verifier:
      model: "claude-haiku-4-20250514"
      temperature: 0.2
    
    # Escalation configuration
    escalation:
      builder:
        model: "claude-sonnet-4-20250514"  # Upgrade on failure
        temperature: 0.5  # More focused
      verifier:
        model: "claude-opus-4-20250514"    # Best for verification
        temperature: 0.1
      
      # When to escalate
      trigger:
        builder_failures: 2   # After 2 builder failures, escalate builder
        verifier_failures: 2  # After 2 verifier rejections, escalate verifier
      
      # How to escalate
      strategy:
        fresh_checkout: true   # Git reset to clean state
        discard_attempts: true # Don't include failed attempt context
        preserve_clarifications: true  # Keep clarification log
      
      # Limits after escalation
      escalated_max_attempts: 2  # Total attempts at escalated tier
```

### State Tracking

```python
from pydantic import BaseModel
from enum import Enum

class ModelTier(Enum):
    NORMAL = "normal"
    ESCALATED = "escalated"

class EscalationState(BaseModel):
    """Track escalation state for a task."""
    task_id: str
    
    builder_tier: ModelTier = ModelTier.NORMAL
    builder_failures_at_normal: int = 0
    builder_failures_at_escalated: int = 0
    
    verifier_tier: ModelTier = ModelTier.NORMAL
    verifier_failures_at_normal: int = 0
    verifier_failures_at_escalated: int = 0
    
    escalation_triggered_at: datetime | None = None
    fresh_checkout_performed: bool = False

class EscalationManager:
    """Manage model escalation based on failures."""
    
    def __init__(
        self,
        config: EscalationConfig,
        git_manager: GitWorktreeManager,
    ):
        self._config = config
        self._git = git_manager
    
    def should_escalate_builder(self, state: EscalationState) -> bool:
        """Check if builder should escalate."""
        if state.builder_tier == ModelTier.ESCALATED:
            return False  # Already escalated
        return state.builder_failures_at_normal >= self._config.trigger.builder_failures
    
    def should_escalate_verifier(self, state: EscalationState) -> bool:
        """Check if verifier should escalate."""
        if state.verifier_tier == ModelTier.ESCALATED:
            return False
        return state.verifier_failures_at_normal >= self._config.trigger.verifier_failures
    
    def has_exceeded_escalated_limit(self, state: EscalationState) -> bool:
        """Check if we've exhausted escalated attempts."""
        builder_exhausted = (
            state.builder_tier == ModelTier.ESCALATED and
            state.builder_failures_at_escalated >= self._config.escalated_max_attempts
        )
        verifier_exhausted = (
            state.verifier_tier == ModelTier.ESCALATED and
            state.verifier_failures_at_escalated >= self._config.escalated_max_attempts
        )
        return builder_exhausted or verifier_exhausted
    
    async def perform_escalation(
        self,
        run: Run,
        state: EscalationState,
        escalate_builder: bool,
        escalate_verifier: bool,
    ) -> EscalationState:
        """
        Perform escalation, optionally with fresh checkout.
        
        Returns updated state.
        """
        new_state = state.model_copy()
        
        if escalate_builder:
            new_state.builder_tier = ModelTier.ESCALATED
        if escalate_verifier:
            new_state.verifier_tier = ModelTier.ESCALATED
        
        new_state.escalation_triggered_at = datetime.utcnow()
        
        # Fresh checkout if configured
        if self._config.strategy.fresh_checkout and not state.fresh_checkout_performed:
            await self._git.reset_worktree(run.worktree_path)
            new_state.fresh_checkout_performed = True
        
        return new_state
    
    def get_current_model_config(
        self,
        state: EscalationState,
        role: str,  # "builder" or "verifier"
        base_config: ModelsConfig,
        escalation_config: EscalationModelsConfig,
    ) -> ModelConfig:
        """Get the current model config based on escalation state."""
        tier = state.builder_tier if role == "builder" else state.verifier_tier
        
        if tier == ModelTier.NORMAL:
            return base_config.builder if role == "builder" else base_config.verifier
        else:
            return escalation_config.builder if role == "builder" else escalation_config.verifier
```

### Workflow Engine Integration

```python
async def execute_task_with_escalation(
    task: Task,
    run: Run,
    models_config: ModelsConfig,
    escalation_config: EscalationConfig | None,
) -> TaskResult:
    """Execute task with automatic model escalation."""
    
    state = EscalationState(task_id=task.id)
    clarification_log = await get_clarification_log(task.id)
    
    while True:
        # Check for escalation
        if escalation_config:
            should_escalate_b = escalation_manager.should_escalate_builder(state)
            should_escalate_v = escalation_manager.should_escalate_verifier(state)
            
            if should_escalate_b or should_escalate_v:
                state = await escalation_manager.perform_escalation(
                    run, state, should_escalate_b, should_escalate_v
                )
                
                # If discarding attempts, clear non-clarification context
                if escalation_config.strategy.discard_attempts:
                    # Fresh start, but keep clarifications
                    pass
        
        # Check if exhausted
        if escalation_config and escalation_manager.has_exceeded_escalated_limit(state):
            return TaskResult(
                status="failed",
                reason="Exhausted attempts at all model tiers",
                escalation_state=state,
            )
        
        # Get current models
        builder_model = escalation_manager.get_current_model_config(
            state, "builder", models_config, escalation_config
        )
        verifier_model = escalation_manager.get_current_model_config(
            state, "verifier", models_config, escalation_config
        )
        
        # Execute builder
        build_result = await execute_builder(task, builder_model, clarification_log)
        
        if build_result.needs_clarification:
            # Handle clarification (Slice 10.1)
            pass
        
        if not build_result.success:
            if state.builder_tier == ModelTier.NORMAL:
                state.builder_failures_at_normal += 1
            else:
                state.builder_failures_at_escalated += 1
            continue
        
        # Execute verifier
        verify_result = await execute_verifier(task, verifier_model, build_result)
        
        if verify_result.needs_clarification:
            # Handle clarification
            pass
        
        if verify_result.passed:
            return TaskResult(status="completed", escalation_state=state)
        
        # Verifier rejected
        if state.verifier_tier == ModelTier.NORMAL:
            state.verifier_failures_at_normal += 1
        else:
            state.verifier_failures_at_escalated += 1
```

### Verification

#### Unit Tests
- Escalation trigger conditions
- State tracking
- Model selection based on tier
- Fresh checkout logic
- Clarification preservation

#### Integration Tests
- Full escalation flow
- Fresh checkout resets worktree
- Clarifications survive escalation
- Exhaustion triggers failure

### Definition of Done
- [ ] EscalationState model
- [ ] EscalationManager implemented
- [ ] Fresh checkout integration
- [ ] Clarification preservation
- [ ] Workflow engine integration

---

## Slice 10.4: MCP Client Integration

### Goal
Enable tasks to consume external MCP servers (GitHub, Linear, Notion, etc.) for context.

### Prerequisites
- Slice 5.6 (MCP server) complete

### Deliverables

```
src/orchestrator/mcp/
├── client.py           # MCP client implementation
├── registry.py         # MCP server registry
tests/unit/test_mcp_client.py
tests/integration/test_mcp_github.py
```

### Architecture Constraints

1. **Project-level MCP connections** — Define once per project
2. **Task-level tool access** — Control which MCP tools each task can use
3. **Context injection** — MCP results become part of task context
4. **Lazy connection** — Only connect when tool is actually used
5. **Timeout handling** — MCP calls have configurable timeouts

### Schema

```yaml
# Project-level config (orchestrator.yaml)
project:
  name: "my-project"
  
  mcp_servers:
    - id: "github"
      type: "stdio"
      command: "npx"
      args: ["@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
      timeout: 30s
      
    - id: "linear"
      type: "sse"
      url: "https://mcp.linear.app/sse"
      headers:
        Authorization: "Bearer ${LINEAR_API_KEY}"
      timeout: 30s
      
    - id: "context7"
      type: "stdio"
      command: "npx"
      args: ["-y", "@anthropic/context7"]
      timeout: 60s

# Routine-level tool access
routine:
  mcp_tools:
    # Default tools available to all tasks
    default:
      - "github.list_issues"
      - "github.get_issue"
      - "linear.get_ticket"
    
    # Explicitly denied (even if in default)
    denied: []

# Step-level override
steps:
  - id: "S-01"
    mcp_tools:
      # Additional tools for this step
      additional:
        - "github.create_branch"
      # Remove from defaults
      denied:
        - "linear.get_ticket"

# Task-level override
task:
  mcp_tools:
    # Only these tools (ignores inheritance)
    only:
      - "github.list_issues"
    # Or use additional/denied pattern
```

### Implementation

```python
from pydantic import BaseModel
from typing import Any
import asyncio

class MCPServerConfig(BaseModel):
    """Configuration for an MCP server connection."""
    id: str
    type: str  # "stdio" or "sse"
    command: str | None = None  # For stdio
    args: list[str] = []
    url: str | None = None  # For sse
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    timeout: int = 30  # seconds

class MCPToolAccess(BaseModel):
    """Tool access configuration."""
    default: list[str] = []
    additional: list[str] = []
    denied: list[str] = []
    only: list[str] | None = None  # If set, overrides all inheritance

class MCPClient:
    """Client for connecting to MCP servers."""
    
    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._connection = None
        self._tools: dict[str, Any] = {}
    
    async def connect(self) -> None:
        """Establish connection to MCP server."""
        if self._config.type == "stdio":
            self._connection = await self._connect_stdio()
        elif self._config.type == "sse":
            self._connection = await self._connect_sse()
        
        # Discover available tools
        self._tools = await self._discover_tools()
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Call an MCP tool and return result."""
        if not self._connection:
            await self.connect()
        
        if tool_name not in self._tools:
            raise MCPToolNotFoundError(f"Tool {tool_name} not found on server {self._config.id}")
        
        return await asyncio.wait_for(
            self._execute_tool(tool_name, arguments),
            timeout=self._config.timeout,
        )
    
    async def disconnect(self) -> None:
        """Close connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

class MCPRegistry:
    """Registry of configured MCP servers."""
    
    def __init__(self):
        self._servers: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
    
    def register(self, config: MCPServerConfig) -> None:
        """Register an MCP server configuration."""
        self._servers[config.id] = config
    
    async def get_client(self, server_id: str) -> MCPClient:
        """Get or create client for a server."""
        if server_id not in self._clients:
            if server_id not in self._servers:
                raise MCPServerNotFoundError(server_id)
            self._clients[server_id] = MCPClient(self._servers[server_id])
        return self._clients[server_id]
    
    async def call_tool(
        self,
        qualified_name: str,  # "server_id.tool_name"
        arguments: dict[str, Any],
    ) -> Any:
        """Call a tool by qualified name."""
        server_id, tool_name = qualified_name.split(".", 1)
        client = await self.get_client(server_id)
        return await client.call_tool(tool_name, arguments)

def resolve_mcp_tool_access(
    routine_access: MCPToolAccess | None,
    step_access: MCPToolAccess | None,
    task_access: MCPToolAccess | None,
) -> set[str]:
    """Resolve which MCP tools are available for a task."""
    
    # If task specifies 'only', use that exclusively
    if task_access and task_access.only is not None:
        return set(task_access.only)
    
    # Start with routine defaults
    tools = set()
    if routine_access:
        tools.update(routine_access.default)
    
    # Add step additional, remove step denied
    if step_access:
        tools.update(step_access.additional)
        tools -= set(step_access.denied)
    
    # Add task additional, remove task denied
    if task_access:
        tools.update(task_access.additional)
        tools -= set(task_access.denied)
    
    return tools
```

### Context Injection

```yaml
# Task can request MCP context
task:
  context_from_mcp:
    - tool: "github.get_issue"
      args:
        owner: "myorg"
        repo: "myrepo"
        issue_number: "{{issue_id}}"
      as: "github_issue"
      
    - tool: "linear.get_ticket"
      args:
        id: "{{linear_ticket}}"
      as: "linear_context"
```

```python
async def build_task_context_with_mcp(
    task: Task,
    mcp_registry: MCPRegistry,
    variables: dict[str, Any],
) -> dict[str, str]:
    """Fetch MCP context for a task."""
    context = {}
    
    for source in task.context_from_mcp:
        # Resolve variables in args
        args = resolve_variables(source.args, variables)
        
        # Call MCP tool
        result = await mcp_registry.call_tool(source.tool, args)
        
        # Format for context
        context[source.as_name] = format_mcp_result(result)
    
    return context
```

### Verification

#### Unit Tests
- Tool access resolution
- Connection management
- Tool calling with timeout

#### Integration Tests
- Real GitHub MCP connection (with mock server)
- Context injection into task
- Tool access scoping

### Definition of Done
- [ ] MCPClient implementation
- [ ] MCPRegistry for server management
- [ ] Tool access resolution with inheritance
- [ ] Context injection from MCP
- [ ] Timeout handling

---

## Slice 10.5: Per-Task Tool Scoping

### Goal
Control which tools (both MCP and built-in) are available to each task.

### Prerequisites
- Slice 10.4 (MCP client) complete
- Slice 5.6 (MCP server - our tools) complete

### Deliverables

```
src/orchestrator/tools/
├── scoping.py          # Tool availability scoping
tests/unit/test_tool_scoping.py
```

### Architecture Constraints

1. **Inheritance model** — Routine → Step → Task
2. **Built-in tools** — update_checklist, submit, get_requirements, etc.
3. **MCP tools** — External server tools
4. **Filesystem tools** — Read/write/execute permissions
5. **Explicit is better** — If not listed, not available

### Schema

```yaml
routine:
  # Built-in orchestrator tools
  tools:
    default:
      - "update_checklist"
      - "submit"
      - "get_requirements"
      - "request_clarification"
    denied: []
  
  # Filesystem access
  filesystem:
    read:
      - "src/**"
      - "docs/**"
      - "tests/**"
    write:
      - "src/**"
      - "tests/**"
    execute:
      - "uv"
      - "npm"
      - "git"
    denied_write:
      - "src/config/secrets.py"

steps:
  - id: "S-01"
    title: "Planning"
    
    # Planning step: read-only, no submit
    tools:
      denied:
        - "submit"  # Can't submit during planning
    
    filesystem:
      write: []  # Read-only for planning
      
  - id: "S-02"
    title: "Implementation"
    
    # Implementation: full access
    tools:
      additional:
        - "run_tests"
    
    filesystem:
      write:
        - "src/**"
        - "tests/**"
```

### Implementation

```python
class ToolScope(BaseModel):
    """Resolved tool scope for a task."""
    orchestrator_tools: set[str]
    mcp_tools: set[str]
    filesystem_read: list[str]  # Glob patterns
    filesystem_write: list[str]
    filesystem_execute: list[str]
    filesystem_denied_write: list[str]

def resolve_tool_scope(
    routine_config: RoutineToolConfig,
    step_config: StepToolConfig | None,
    task_config: TaskToolConfig | None,
) -> ToolScope:
    """Resolve complete tool scope for a task."""
    
    # Orchestrator tools
    orch_tools = set(routine_config.tools.default)
    if step_config and step_config.tools:
        orch_tools.update(step_config.tools.additional)
        orch_tools -= set(step_config.tools.denied)
    if task_config and task_config.tools:
        orch_tools.update(task_config.tools.additional)
        orch_tools -= set(task_config.tools.denied)
    
    # MCP tools (from Slice 10.4)
    mcp_tools = resolve_mcp_tool_access(
        routine_config.mcp_tools,
        step_config.mcp_tools if step_config else None,
        task_config.mcp_tools if task_config else None,
    )
    
    # Filesystem (similar pattern)
    fs_read = _resolve_filesystem_patterns(
        routine_config.filesystem.read,
        step_config.filesystem.read if step_config else None,
        task_config.filesystem.read if task_config else None,
    )
    # ... similar for write, execute
    
    return ToolScope(
        orchestrator_tools=orch_tools,
        mcp_tools=mcp_tools,
        filesystem_read=fs_read,
        filesystem_write=fs_write,
        filesystem_execute=fs_execute,
        filesystem_denied_write=fs_denied,
    )

class ToolEnforcer:
    """Enforce tool scope during execution."""
    
    def __init__(self, scope: ToolScope):
        self._scope = scope
    
    def can_use_tool(self, tool_name: str) -> bool:
        """Check if a tool can be used."""
        if tool_name in self._scope.orchestrator_tools:
            return True
        if tool_name in self._scope.mcp_tools:
            return True
        return False
    
    def can_read(self, path: str) -> bool:
        """Check if path can be read."""
        return any(fnmatch(path, pattern) for pattern in self._scope.filesystem_read)
    
    def can_write(self, path: str) -> bool:
        """Check if path can be written."""
        if any(fnmatch(path, pattern) for pattern in self._scope.filesystem_denied_write):
            return False
        return any(fnmatch(path, pattern) for pattern in self._scope.filesystem_write)
    
    def can_execute(self, command: str) -> bool:
        """Check if command can be executed."""
        executable = command.split()[0]
        return executable in self._scope.filesystem_execute
```

### Verification

#### Unit Tests
- Tool resolution with inheritance
- Filesystem pattern matching
- Denied patterns override allowed

#### Integration Tests
- Agent blocked from using denied tool
- Filesystem enforcement works

### Definition of Done
- [ ] ToolScope model
- [ ] Resolution with inheritance
- [ ] ToolEnforcer implementation
- [ ] Integration with agent execution

---

## Phase 10 Milestone Verification

```bash
# All tests pass
uv run pytest tests/ -v

# Test clarification flow
uv run orchestrator run create test-routine --project ./test
uv run orchestrator run start <run-id> --agent mock
# Agent requests clarification...
uv run orchestrator clarifications list --run <run-id>
uv run orchestrator clarifications interactive --run <run-id>

# Test model escalation
# Configure cheap model, let it fail, observe escalation
uv run orchestrator run status <run-id>  # Should show escalation state

# Test MCP integration
uv run orchestrator mcp list-servers --project ./test
uv run orchestrator mcp test-connection github
```

If clarification flow, model escalation, and MCP integration all work, Phase 10 is complete.
