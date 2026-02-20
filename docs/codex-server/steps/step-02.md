# Step 02: Types and Detector Support

Add Codex local/remote agent types and expose selectable detector metadata through API surfaces without breaking existing agent options.

## Intent Verification
**Original Intent**: `docs/codex-server/intent.md` requires first-class `codex_server` and `codex_server_remote` selection with actionable configuration guidance.

**Functionality to Produce**:
- New agent enum values available across API/state serialization
- Detector emits both Codex options with required config field metadata
- API agents listing includes availability + install/config hints

**Final Verification Criteria**:
- Existing agent types still serialize and appear unchanged
- Codex options are visible and actionable in `/api/agents`

---

## Task 1: Add enum and schema compatibility for new agent types

**Description**: Extend the type surface first so downstream detector/executor changes compile cleanly.

**Implementation Plan (Do These Steps)**
- [ ] Update `src/orchestrator/config/enums.py` to add `CODEX_SERVER` and `CODEX_SERVER_REMOTE`.
- [ ] Update `src/orchestrator/api/schemas/runs.py` mappings/serialization helpers for both values.
- [ ] Add integration coverage in `tests/integration/test_api_runs.py` (or equivalent) asserting create/read/update run round-trip for both `codex_server` and `codex_server_remote`.
- [ ] Run targeted type checks on changed files before detector edits.

```bash
uv run pyright src/orchestrator/config/enums.py src/orchestrator/api/schemas/runs.py
```

**References**
- `docs/codex-server/step-01-plan.md`
- `docs/codex-server/step-02-plan.md`
- `docs/codex-server/context/contract-matrix.md`

**Constraints**
- [ ] Atomicity budget: change <=2 files and <=150 LOC.
- [ ] Do not modify executor or detector in this task.

**Functionality (Expected Outcomes)**
- [ ] Schemas accept both new types without breaking old values.
- [ ] No API enum serialization regressions.
- [ ] Persisted run records round-trip correctly for both new enum values.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k "agent and schema" -v` passes for impacted tests.
- [ ] `uv run pytest tests/integration/test_api_runs.py -k "codex_server or codex_server_remote" -v` passes for persisted run round-trip assertions.
- [ ] `uv run ruff check src/orchestrator/config/enums.py src/orchestrator/api/schemas/runs.py` passes.

---

## Task 2: Extend ToolDetector options and config fields for local + remote

**Description**: Add discoverable detector metadata that guides setup for both variants.

**Implementation Plan (Do These Steps)**
- [ ] Update `src/orchestrator/agents/detector.py` to publish options for local and remote Codex variants.
- [ ] Define required config fields per variant:
  - local: endpoint/model/callback transport/timeouts
  - remote: base_url/model/callback transport/token source/timeouts
- [ ] Add availability messaging tied to "latest documented Codex app server only" policy.

```bash
uv run pytest tests/unit -k detector -v
```

**References**
- `docs/codex-server/step-02-plan.md`
- `docs/codex-server/context/contract-matrix.md`
- `docs/codex-server/context/open-risks.md`

**Constraints**
- [ ] Atomicity budget: change <=3 files and <=250 LOC.
- [ ] Keep existing agent detection output structure stable.

**Functionality (Expected Outcomes)**
- [ ] Detector returns Codex local/remote options with clear required fields.
- [ ] Unavailable states include actionable install/connection hints.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k "detector and codex" -v` passes.
- [ ] `uv run ruff check src/orchestrator/agents/detector.py` passes.

---

## Task 3: Verify API exposure for new detector options

**Description**: Ensure API consumers can retrieve Codex options through existing routes.

**Implementation Plan (Do These Steps)**
- [ ] Validate `src/orchestrator/api/routers/agents.py` requires no route-shape change and supports expanded detector output.
- [ ] Add/update integration coverage for `GET /api/agents` response containing both Codex variants.
- [ ] Add negative-case assertions for unavailable local/remote setups: `available=false` plus actionable install/connection hint text.
- [ ] Confirm run serialization with selected Codex type still round-trips.

```bash
uv run pytest tests/integration -k "api_agents or runs" -v
```

**References**
- `docs/codex-server/step-02-plan.md`
- `docs/codex-server/plan.md`

**Constraints**
- [ ] Atomicity budget: change <=4 files and <=300 LOC.
- [ ] No UI changes in this step.

**Functionality (Expected Outcomes)**
- [ ] `/api/agents` includes `codex_server` and `codex_server_remote` entries.
- [ ] Existing consumers continue to parse unchanged fields.
- [ ] Unavailable Codex options are explicit and actionable instead of ambiguous.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/integration -k api_agents -v` passes.
- [ ] `uv run pytest tests/integration/test_api_agents.py -k "codex and (unavailable or available)" -v` passes.
- [ ] `uv run pyright` passes for changed modules.
