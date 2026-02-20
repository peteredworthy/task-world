# Step 06: Tests, Documentation, and Release Hardening

Close the rollout gate with complete test coverage and documentation updates. Release remains blocked until both Codex variants are production-ready.

## Intent Verification
**Original Intent**: `docs/codex-server/intent.md` requires robust verification and documentation updates, with release blocked if either Codex variant is not ready.

**Functionality to Produce**:
- Codex-specific unit/integration coverage across detector, agents, executor, and API
- Evidence for builder/verifier callback flow parity on local and remote
- Updated architecture/module docs reflecting final implementation

**Final Verification Criteria**:
- Static checks and relevant suites pass on changed code
- Documentation accurately mirrors implementation and release gate policy

---

## Task 1: Complete Codex-focused automated coverage

**Description**: Add missing tests to close gaps across all Codex-specific behavior.

**Implementation Plan (Do These Steps)**
- [ ] Add or extend unit tests for detector metadata, local/remote agent behavior, error mapping, and executor dispatch.
- [ ] Add or extend integration tests for `/api/agents` exposure and builder/verifier callback flows for both variants.
- [ ] Ensure tests validate allow-listed tools only and both callback channels.
- [ ] Maintain an explicit required test-target list (file paths) instead of broad `-k` filters so no required coverage is skipped.

```bash
uv run pytest tests/unit/test_tool_detector.py tests/unit/test_agent_types.py tests/unit/test_agent_monitor.py tests/unit/test_codex_server_agent.py tests/unit/test_codex_server_remote_agent.py -v
uv run pytest tests/integration/test_api_agents.py tests/integration/test_api_runs.py tests/integration/test_agent_executor.py tests/integration/test_api_runs_recover.py tests/integration/test_codex_server_callbacks.py -v
```

**References**
- `docs/codex-server/step-06-plan.md`
- `docs/codex-server/context/contract-matrix.md`
- `docs/codex-server/context/open-risks.md`

**Constraints**
- [ ] Atomicity budget: change <=5 files and <=500 LOC per task chunk.
- [ ] No mocking; use real dependencies and DI patterns.

**Functionality (Expected Outcomes)**
- [ ] Coverage exists for all new Codex code paths.
- [ ] Both variants have equivalent callback-flow evidence.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Explicit unit test target list runs with no skipped required Codex coverage.
- [ ] Explicit integration test target list runs with no skipped required Codex coverage.

---

## Task 2: Run quality gates and capture verification evidence

**Description**: Run full quality checks for changed areas and record outputs in a release-readiness note.

**Implementation Plan (Do These Steps)**
- [ ] Run static checks and targeted suites for modified files.
- [ ] Run `uv run pre-commit run --all-files`.
- [ ] Create `docs/codex-server/context/release-readiness.md` including command results, date, and any failures/blockers.

```bash
uv run ruff check .
uv run pyright
uv run pre-commit run --all-files
```

**References**
- `docs/plan-runner/idea_to_plan_stripped.md`
- `docs/codex-server/step-06-plan.md`

**Constraints**
- [ ] Atomicity budget: change <=2 files and <=220 LOC.
- [ ] If any check fails, mark release gate blocked and link failure logs.

**Functionality (Expected Outcomes)**
- [ ] A reproducible verification record exists for reviewer validation.
- [ ] Failures are explicitly tied to follow-up actions.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `docs/codex-server/context/release-readiness.md` includes command list and pass/fail status.
- [ ] All required commands pass or have explicit blocker classification.

---

## Task 3: Update architecture docs and enforce dual-variant release gate

**Description**: Ensure project documentation reflects all new modules, routes, and release requirements.

**Implementation Plan (Do These Steps)**
- [ ] Update `AGENTS.md` key modules table with `codex_server.py`, `codex_server_remote.py`, and `codex_server_common.py`.
- [ ] Update `docs/ARCHITECTURE.md` directory map and API route notes for agent option changes.
- [ ] Confirm release gate wording explicitly blocks shipping until both variants are production-ready.

```bash
rg -n "codex_server|codex_server_remote|codex_server_common" AGENTS.md docs/ARCHITECTURE.md
rg -n "api/agents|ToolDetector|AgentType" AGENTS.md docs/ARCHITECTURE.md src/orchestrator/api/routers/agents.py src/orchestrator/agents/detector.py src/orchestrator/config/enums.py
```

**References**
- `docs/codex-server/step-06-plan.md`
- `AGENTS.md`
- `docs/ARCHITECTURE.md`

**Constraints**
- [ ] Atomicity budget: change <=3 files and <=260 LOC.
- [ ] Documentation must match implemented file paths exactly.

**Functionality (Expected Outcomes)**
- [ ] Module and route docs are synchronized with implementation.
- [ ] Release checklist language is explicit and enforceable.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Manual review confirms no docs drift for new Codex modules/config.
- [ ] Release gate statement appears in both codex planning docs and project architecture docs.
