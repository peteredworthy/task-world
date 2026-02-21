# Dry Run Notes: codex-server

## Summary

Dry-run simulation was executed against all generated tasks in `docs/codex-server/steps/step-01.md` through `docs/codex-server/steps/step-06.md` (18 total tasks).

Result:
- Execution path is mostly complete and logically ordered.
- Several REQUIRED gaps remain that can cause non-runnable execution, unverifiable outcomes, or ambiguity at implementation time.
- Release should remain blocked until REQUIRED gaps in the table below are remediated.

## Global Assumptions Used In Simulation

- Step order is strictly sequential (01 -> 06) and each step's outputs are available before the next step starts.
- The repository remains runnable after each task chunk.
- "No mocking" applies to all new tests, including Codex-agent coverage.
- Codex server integration targets latest documented app-server contract only.
- REST and MCP callback channels must be verified with equivalent behavior.

## Task-by-Task Simulation

### Step 01, Task 1: Build a contract matrix from clarified decisions

- Simulation: Create `docs/codex-server/context/contract-matrix.md` with decision-source-impact-no-go sections and v1 exclusions.
- Assumptions: Clarification answers are complete and internally consistent.
- Expected outputs: Contract matrix used as canonical source by later steps.
- Blockers and mitigation: No hard blocker; add a mandatory template section for "verification evidence expected" to improve downstream test planning.

### Step 01, Task 2: Align plan and architecture docs to the contract matrix

- Simulation: Update `plan.md` and `architecture.md` to defer all policy decisions to matrix and add mismatch handling rules.
- Assumptions: No conflicting statements remain outside these files.
- Expected outputs: Single source-of-truth behavior for auth/tools/callback/release gating.
- Blockers and mitigation: EXPECTED gap: conflict detection is manual only. Mitigation: add explicit `rg` verification checklist lines in task body.

### Step 01, Task 3: Record implementation risks as blockers or explicit follow-ups

- Simulation: Create `open-risks.md` with trigger, impact, classification, mitigation, and step references.
- Assumptions: Risks can be classified before implementation details exist.
- Expected outputs: Risk-triggered stop/go guidance for Steps 02-06.
- Blockers and mitigation: No hard blocker; add owner and "exit criteria" columns so each risk can be closed objectively.

### Step 02, Task 1: Add enum and schema compatibility for new agent types

- Simulation: Add enum values and API schema support; run targeted type/lint/unit checks.
- Assumptions: Existing run persistence accepts new enum values without migration change.
- Expected outputs: `codex_server` and `codex_server_remote` serialize and round-trip.
- Blockers and mitigation: REQUIRED gap: task omits DB migration impact check for persisted enum strings. Mitigation: add explicit integration assertion for create/read/update of runs using both new types.

### Step 02, Task 2: Extend ToolDetector options and config fields for local + remote

- Simulation: Expand detector options and required field schemas, including unavailability hints.
- Assumptions: Detector schema format already supports new field classes without API change.
- Expected outputs: `/api/agents` can present actionable setup forms for both variants.
- Blockers and mitigation: EXPECTED gap: timeout defaults and retry bounds are not specified. Mitigation: add explicit numeric defaults/ranges in task contract.

### Step 02, Task 3: Verify API exposure for new detector options

- Simulation: Add integration tests for `/api/agents` and run serialization compatibility.
- Assumptions: Route shape remains stable.
- Expected outputs: Agent list includes both Codex variants with unchanged payload contract.
- Blockers and mitigation: REQUIRED gap: no negative-case assertion for unavailable local/remote setup states. Mitigation: add tests that assert install/connection hint strings and availability=false behavior.

### Step 03, Task 1: Scaffold Codex local agent and shared common module

- Simulation: Create compile-safe module skeletons and package exports.
- Assumptions: Existing import/export conventions in `src/orchestrator/agents/__init__.py` are sufficient.
- Expected outputs: New modules import cleanly and satisfy protocol signatures.
- Blockers and mitigation: No hard blocker; include explicit constructor/config dataclass contract in scaffold to reduce refactor churn in Task 2.

### Step 03, Task 2: Implement execute path with prompt and callback-tool bridging

- Simulation: Add phase-aware prompt assembly, callback tool allow-list, output normalization, and channel selection.
- Assumptions: Codex event stream can be normalized using existing action-log structure.
- Expected outputs: Builder/verifier runs complete via callback tools only.
- Blockers and mitigation: REQUIRED gap: success criteria do not demand assertion that non-allow-listed tools are rejected at runtime. Mitigation: add explicit failing test for disallowed tool invocation.

### Step 03, Task 3: Implement cancellation and explicit error mapping

- Simulation: Add idempotent cancel and map failures to orchestrator-specific errors.
- Assumptions: Cancel signal semantics from Codex runtime are deterministic.
- Expected outputs: Clean stop behavior with actionable and redacted errors.
- Blockers and mitigation: EXPECTED gap: cancellation timeout policy not defined. Mitigation: specify cancel wait ceiling and fallback kill behavior in task text.

### Step 04, Task 1: Create remote agent module and configuration adapter

- Simulation: Implement remote agent with validated config for base URL, token source, model/options, channel, timeout/retry.
- Assumptions: Token is available through configured source at runtime.
- Expected outputs: Remote agent constructible with strict validation errors for bad config.
- Blockers and mitigation: REQUIRED gap: token source precedence/env key naming is undefined. Mitigation: document exact precedence order and required env var names in contract matrix and task.

### Step 04, Task 2: Implement authenticated remote execution and callback parity

- Simulation: Inject bearer auth, run callbacks over REST/MCP parity path, preserve allow-list.
- Assumptions: Remote server supports equivalent tool callback semantics.
- Expected outputs: Remote execution parity with local path.
- Blockers and mitigation: REQUIRED gap: parity is stated but no parity test matrix is required. Mitigation: add a 2x2 verification matrix (builder/verifier x REST/MCP) with required passing tests.

### Step 04, Task 3: Add network resilience and transport error mapping

- Simulation: Add bounded retries/timeouts and map auth/network/schema errors to orchestrator errors.
- Assumptions: Retry-safe operations are idempotent.
- Expected outputs: Stable remote behavior with safe diagnostics.
- Blockers and mitigation: EXPECTED gap: retry backoff strategy is unspecified. Mitigation: define fixed or exponential policy with max attempts and total budget.

### Step 05, Task 1: Add executor dispatch for codex_server and codex_server_remote

- Simulation: Extend `_create_agent` routing and dispatch tests.
- Assumptions: Config payload passes through without transformation side effects.
- Expected outputs: Executor can instantiate both variants without breaking existing branches.
- Blockers and mitigation: No hard blocker; add assertion for unsupported type error message stability to protect API/UI behavior.

### Step 05, Task 2: Integrate spawn/cancel/resume/recover flow for both variants

- Simulation: Wire lifecycle for both types and verify lock handling across transitions.
- Assumptions: Existing recovery model supports new managed agents without schema changes.
- Expected outputs: No duplicate attempts; consistent lifecycle controls.
- Blockers and mitigation: REQUIRED gap: "recover" behavior lacks explicit stale-session conflict rule. Mitigation: define deterministic rule (resume existing session vs fail-fast) and add integration tests.

### Step 05, Task 3: Extend monitor health/dead-agent handling for Codex sessions

- Simulation: Add Codex-aware health checks and dead-agent handling tied to recovery/failure.
- Assumptions: Health signals are available and distinguish transient delays from dead sessions.
- Expected outputs: No ghost runs, no lock leaks.
- Blockers and mitigation: EXPECTED gap: heartbeat/timeout thresholds are not calibrated per variant. Mitigation: define per-variant defaults and test with deterministic timing fixtures.

### Step 06, Task 1: Complete Codex-focused automated coverage

- Simulation: Add coverage across detector/agents/executor/API and callback parity evidence.
- Assumptions: Prior steps have landed and are stable.
- Expected outputs: Sufficient regression protection for both variants.
- Blockers and mitigation: REQUIRED gap: command filters `-k codex` may miss API tests not labeled with "codex". Mitigation: specify exact test files or marker set for mandatory execution.

### Step 06, Task 2: Run quality gates and capture verification evidence

- Simulation: Run `ruff`, `pyright`, `pre-commit`, write release-readiness note.
- Assumptions: Local environment includes all hooks and toolchain.
- Expected outputs: Reproducible verification log and gate status.
- Blockers and mitigation: EXPECTED gap: no standard format for failure log references. Mitigation: require a fixed section template with command, exit code, timestamp, log path, follow-up owner.

### Step 06, Task 3: Update architecture docs and enforce dual-variant release gate

- Simulation: Update `AGENTS.md` and `docs/ARCHITECTURE.md` with new modules/routes and explicit dual-variant gate wording.
- Assumptions: Implemented file paths/names match planned names.
- Expected outputs: Documentation reflects implementation and release policy.
- Blockers and mitigation: REQUIRED gap: no explicit doc-to-code verification command. Mitigation: add required `rg` checks over `src/orchestrator/agents` plus docs to detect drift pre-merge.

## Gap Resolution Table

| Gap Description | Severity | Affected Step/Task | Functionality Area | Concrete Remediation |
|---|---|---|---|---|
| Missing persisted run round-trip verification for new agent enums | REQUIRED | Step 02 / Task 1 | API + persistence compatibility | Update `docs/codex-server/steps/step-02.md`: add required integration test for run create/read/update using both new agent types. |
| No explicit unavailable-state assertions for `/api/agents` Codex options | REQUIRED | Step 02 / Task 3 | Detector/API behavior | Update `docs/codex-server/steps/step-02.md`: require tests asserting `available=false` payload and actionable guidance text for missing local/remote prerequisites. |
| Allow-list enforcement lacks negative runtime proof | REQUIRED | Step 03 / Task 2 | Tool safety boundary | Update `docs/codex-server/steps/step-03.md`: add required test that disallowed tool calls are rejected and logged as policy violations. |
| Remote token source precedence undefined | REQUIRED | Step 04 / Task 1 | Auth configuration correctness | Update `docs/codex-server/context/contract-matrix.md` with explicit precedence order and required env var key(s); reference it in `docs/codex-server/steps/step-04.md`. |
| Callback parity lacks mandatory verification matrix | REQUIRED | Step 04 / Task 2 | Callback channel parity | Update `docs/codex-server/steps/step-04.md`: require builder+verifier coverage for both REST and MCP (4-case matrix) with explicit passing criteria. |
| Recover flow does not define stale-session conflict rule | REQUIRED | Step 05 / Task 2 | Lifecycle/recovery determinism | Update `docs/codex-server/steps/step-05.md`: add deterministic conflict rule and integration tests for stale-vs-active remote sessions. |
| Step-06 command filters may omit required tests | REQUIRED | Step 06 / Task 1 | Verification completeness | Update `docs/codex-server/steps/step-06.md`: replace broad `-k` commands with explicit required test modules/markers list. |
| Doc-to-code drift check is not enforceable | REQUIRED | Step 06 / Task 3 | Documentation integrity | Update `docs/codex-server/steps/step-06.md`: add mandatory `rg` verification linking documented modules/routes to concrete files. |
| Timeout/retry defaults not numerically defined | EXPECTED | Step 02 / Task 2 | Operational stability | Add default values and acceptable ranges in `docs/codex-server/step-02-plan.md` and mirror in step task text. |
| Cancellation timeout semantics unspecified | EXPECTED | Step 03 / Task 3 | Lifecycle ergonomics | Add cancel timeout + fallback behavior in `docs/codex-server/steps/step-03.md` and reference in unit tests. |
| Retry backoff policy undefined | EXPECTED | Step 04 / Task 3 | Remote resilience | Add fixed policy (e.g., exponential with cap) and max attempt budget in `docs/codex-server/steps/step-04.md`. |
| Health-check thresholds unspecified per variant | EXPECTED | Step 05 / Task 3 | Dead-agent detection quality | Define local/remote threshold defaults and test fixture timing contract in `docs/codex-server/steps/step-05.md`. |
| Conflict/mismatch detection relies on manual review | EXPECTED | Step 01 / Task 2 | Planning reliability | Add concrete grep-based validation checklist lines to `docs/codex-server/steps/step-01.md`. |
| Risk log lacks owner/exit criteria fields | EXPECTED | Step 01 / Task 3 | Risk closure governance | Extend `docs/codex-server/context/open-risks.md` template to include owner and explicit closure criteria. |
| Release-readiness note lacks standardized evidence schema | EXPECTED | Step 06 / Task 2 | Auditability | Add fixed table format requirement in `docs/codex-server/steps/step-06.md` (command, status, timestamp, log reference, action). |

## Recommendations

1. Apply all REQUIRED remediations to step task files before execution work starts.
2. Promote selected EXPECTED gaps (timeout/retry policy, cancellation policy, monitor thresholds) to REQUIRED if production rollout timing is tight.
3. Re-run Stage 6 dry-run after task text updates and before entering execution Stage 9.
