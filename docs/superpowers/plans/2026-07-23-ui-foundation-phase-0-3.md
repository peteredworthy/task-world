# Grounded UI/UX Foundation Phases 0-3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an implementation-grounded domain, action, state, evidence, and capability foundation and present its highest-impact unresolved decisions in a concise static HTML review.

**Architecture:** Parallel reality agents inspect bounded repository areas and write immutable reports without touching shared canonical files. Later synthesis agents produce disjoint typed contracts, a normalization task allocates stable IDs and resolves shared catalogs, and an independent verifier attempts to falsify the result before the HTML checkpoint is generated.

**Tech Stack:** Markdown, YAML, JSON Schema, Python 3.12 with Pydantic v2 and PyYAML, static HTML/CSS/JavaScript, Playwright.

## Global Constraints

- Follow the authority hierarchy and claim-specific evidence rules in `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`.
- Keep `docs/jtbd/jobs.md`, `journeys.md`, `decision-information.md`, `information-architecture.md`, and `evaluation-rubric.md` unchanged.
- Use `uv run` for every Python command.
- Use only `apply_patch` for manual file creation and edits.
- The user explicitly authorized reviewed task commits on the isolated `ui-foundation-phase-0-3` branch; do not merge or push without a separate request.
- Do not modify product backend or UI implementation code.
- Do not design screens, view contracts, scenarios, fixtures, or future command semantics.
- Parallel audit agents may write only their assigned report file.
- Canonical facts live in YAML; Markdown and HTML are projections.
- Every important claim must have evidence, capability, and epistemic status or an explicit unknown state.
- Current and target capabilities must remain separate.
- A temporal sequence must not be labeled causal without an explicit mechanism or qualifying evidence.

---

## File Structure

### Coordination And Catalog

- `research/ui-foundation/index.md`: package map and review entry points.
- `research/ui-foundation/status.md`: generated human-readable phase and coverage status.
- `research/ui-foundation/source-map.md`: generated evidence-source projection.
- `research/ui-foundation/decision-log.md`: generated human-decision projection.
- `research/ui-foundation/open-questions.md`: generated unresolved-question projection.
- `research/ui-foundation/catalog/scope.yaml`: closed source-demand and audit-scope manifest.
- `research/ui-foundation/catalog/ids.yaml`: canonical stable-ID registry.
- `research/ui-foundation/catalog/claims.yaml`: normalized cross-contract claim index.
- `research/ui-foundation/catalog/invariants.yaml`: invariant index.
- `research/ui-foundation/catalog/conflicts.yaml`: source and synthesis conflicts.
- `research/ui-foundation/catalog/questions.yaml`: open questions and blocking state.
- `research/ui-foundation/catalog/decisions.yaml`: confirmed human decisions.
- `research/ui-foundation/catalog/evidence.yaml`: audit snapshot and evidence registry.

### Typed Reality And Capability Contracts

- `research/ui-foundation/reality/domain-model.yaml`: entity identities and lifecycle boundaries.
- `research/ui-foundation/reality/relationships.yaml`: typed, directed, cardinal relationships.
- `research/ui-foundation/reality/state-model.yaml`: states and legal transitions.
- `research/ui-foundation/reality/permissions.yaml`: enforced authorization, domain eligibility, and proposed role policy kept separate.
- `research/ui-foundation/reality/actions/*.yaml`: one implemented action contract per file.
- `research/ui-foundation/reality/evidence/inventory.yaml`: evidence kinds, identity, attribution, and freshness.
- `research/ui-foundation/capabilities/registry.yaml`: field-level capability classifications.
- `research/ui-foundation/capabilities/derivations/*.yaml`: complete admitted derivation contracts.
- `research/ui-foundation/capabilities/gaps.md`: projection of capability gaps and proposed-action requirements.

### Tooling And Review

- `research/ui-foundation/schemas/semantic-item.schema.json`: shared machine-readable semantic contract.
- `research/ui-foundation/schemas/review-feedback.schema.json`: review export contract.
- `research/ui-foundation/tools/validate.py`: deterministic package and report validator.
- `research/ui-foundation/tools/build_review.py`: canonical-data-to-static-HTML projection.
- `research/ui-foundation/tools/import_feedback.py`: validated feedback-to-candidate-decision importer.
- `research/ui-foundation/reviews/index.html`: static status and review index.
- `research/ui-foundation/reviews/phase-3-reality-capability-01.html`: first review batch.
- `ui/tests/e2e/ui-foundation-review.spec.ts`: direct-file interaction and accessibility checks.
- `tests/integration/test_ui_foundation_tools.py`: real-file tests for validation, projection, and feedback import.

### Agent Reports

- `research/ui-foundation/agent-reports/00-delegation-plan.md`
- `research/ui-foundation/agent-reports/01-domain-persistence.md`
- `research/ui-foundation/agent-reports/02-graph-runtime.md`
- `research/ui-foundation/agent-reports/03-workflow-state.md`
- `research/ui-foundation/agent-reports/04-api-actions-authority.md`
- `research/ui-foundation/agent-reports/05-evidence-telemetry.md`
- `research/ui-foundation/agent-reports/06-ui-projections.md`
- `research/ui-foundation/agent-reports/07-tests-documentation.md`
- `research/ui-foundation/agent-reports/08-domain-synthesis.md`
- `research/ui-foundation/agent-reports/09-action-state-synthesis.md`
- `research/ui-foundation/agent-reports/10-evidence-synthesis.md`
- `research/ui-foundation/agent-reports/11-semantic-verification.md`

---

### Task 1: Bootstrap Contracts And Validation

**Files:**
- Create: `research/ui-foundation/schemas/semantic-item.schema.json`
- Create: `research/ui-foundation/schemas/review-feedback.schema.json`
- Create: `research/ui-foundation/tools/validate.py`
- Create: `tests/integration/test_ui_foundation_tools.py`

**Interfaces:**
- Produces: `ValidationIssue(code: str, path: str, message: str)`.
- Produces: `validate_foundation(root: Path, phase: int) -> list[ValidationIssue]`.
- Produces: `validate_report(path: Path) -> list[ValidationIssue]`.
- Produces: CLI `uv run python research/ui-foundation/tools/validate.py [--root PATH] [--phase 0|1|2|3] [--report PATH]`.
- Consumes: no foundation artifacts; tests create real temporary files.

- [ ] **Step 1: Write failing real-file validator tests**

Add tests that create temporary YAML packages and verify these exact failures:

```python
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "research/ui-foundation/tools/validate.py"


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def append_yaml_item(path: Path, item: dict[str, object]) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {"items": []}
    value["items"].append(item)
    write_yaml(path, value)


def write_minimal_foundation(tmp_path: Path) -> Path:
    root = tmp_path / "research/ui-foundation"
    for relative in (
        "catalog/ids.yaml", "catalog/claims.yaml", "catalog/invariants.yaml",
        "catalog/conflicts.yaml", "catalog/questions.yaml", "catalog/decisions.yaml",
        "capabilities/registry.yaml", "reality/domain-model.yaml",
        "reality/relationships.yaml", "reality/state-model.yaml",
        "reality/permissions.yaml", "reality/evidence/inventory.yaml",
    ):
        write_yaml(root / relative, {"schema_version": "1", "items": []})
    write_yaml(root / "catalog/evidence.yaml", {
        "schema_version": "1", "snapshot": {"id": "snapshot-test", "files": []},
        "items": [],
    })
    return root


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root), "--phase", "2"],
        check=False, capture_output=True, text=True,
    )


def run_report_validator(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--report", str(path)],
        check=False, capture_output=True, text=True,
    )


def test_validator_rejects_duplicate_ids(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    append_yaml_item(root / "catalog/claims.yaml", {"id": "CAP-01"})
    append_yaml_item(root / "catalog/questions.yaml", {"id": "CAP-01"})
    result = run_validator(root)
    assert "ID_DUPLICATE" in result.stderr


def test_validator_rejects_incomplete_derived_claim(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    write_yaml(root / "capabilities/registry.yaml", {
        "items": [{"id": "CAP-01", "capability_status": "derived", "derivation_id": "DRV-01"}]
    })
    write_yaml(root / "capabilities/derivations/DRV-01.yaml", {
        "id": "DRV-01", "inputs": ["CAP-02"], "output_type": "string"
    })
    result = run_validator(root)
    assert "DERIVATION_UNKNOWN_BEHAVIOR_MISSING" in result.stderr


def test_validator_rejects_current_claim_without_implementation_evidence(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    write_yaml(root / "capabilities/registry.yaml", {
        "items": [{"id": "CAP-01", "capability_status": "current", "evidence_ids": ["EVD-01"]}]
    })
    write_yaml(root / "catalog/evidence.yaml", {
        "snapshot": {"files": []},
        "items": [{"id": "EVD-01", "source_kind": "product-documentation"}],
    })
    result = run_validator(root)
    assert "CURRENT_IMPLEMENTATION_EVIDENCE_MISSING" in result.stderr


def test_report_validator_requires_handoff_sections(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# Report\n\n## Purpose\nOnly one section.\n")
    result = run_report_validator(report)
    assert "REPORT_SECTION_MISSING" in result.stderr
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `uv run pytest tests/integration/test_ui_foundation_tools.py -v`

Expected: FAIL because `validate.py` and its CLI do not exist.

- [ ] **Step 3: Implement the validator and schemas**

Implement the validator with these concrete rules and no network access:

```python
@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


def validate_report(path: Path) -> list[ValidationIssue]:
    required = (
        "Purpose", "Scope inspected", "Key findings", "Important uncertainties",
        "Conflicts found", "Decisions required", "Artifact paths",
        "Evidence pointers", "Recommended next delegation",
    )
    text = path.read_text(encoding="utf-8")
    return [
        ValidationIssue("REPORT_SECTION_MISSING", str(path), heading)
        for heading in required
        if f"## {heading}" not in text
    ]


def validate_foundation(root: Path, phase: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_required_files(root, phase))
    issues.extend(validate_yaml_and_statuses(root))
    issues.extend(validate_unique_ids_and_references(root))
    issues.extend(validate_source_hashes(root))
    issues.extend(validate_current_evidence(root))
    issues.extend(validate_derivations(root))
    issues.extend(validate_actions_and_transitions(root))
    issues.extend(validate_epistemics(root))
    issues.extend(validate_review_references(root))
    return issues
```

Required files and completion rules increase by phase, so an explicit Phase 0
empty collection is valid while the same collection fails Phase 1 or Phase 2.
The semantic schema enumerates the exact implementation, test, documentation,
capability, and epistemic statuses from the design. The feedback schema requires
`schema_version`, `review_version`, `batch_id`, `source_snapshot`, `exported_at`,
and an array of response-history records containing `item_id`, `response`,
`note`, and `recorded_at`.

- [ ] **Step 4: Run tests and static checks**

Run: `uv run pytest tests/integration/test_ui_foundation_tools.py -v`

Expected: PASS for validator tests.

Run: `uv run ruff check research/ui-foundation/tools/validate.py tests/integration/test_ui_foundation_tools.py`

Expected: PASS with no diagnostics.

- [ ] **Step 5: Review checkpoint**

Confirm the validator reports all issues in one run, uses non-zero exit status on
failure, and does not infer missing values.

---

### Task 2: Establish Phase 0 Scope And Coordination

**Files:**
- Create: all coordination and catalog files listed in File Structure.
- Create: `research/ui-foundation/agent-reports/00-delegation-plan.md`
- Create: `research/ui-foundation/reviews/index.html`

**Interfaces:**
- Consumes: the five JTBD source documents and the approved design.
- Produces: closed `scope.yaml`, provisional source demands, audit ownership, source snapshot, and empty typed catalogs accepted by `validate.py`.
- Produces: source-demand IDs that later map to canonical `CAP-*` and `ACT-*` IDs during normalization.

- [ ] **Step 1: Create the closed scope manifest**

Represent every `Must know`, decision-inventory row, honesty rule, and
action-feedback requirement from the five source documents. Each demand records:

```yaml
- key: jobs.J1.health-class
  source: docs/jtbd/jobs.md
  source_anchor: J1
  demand_type: claim
  label: Health class
  audit_owner: evidence-telemetry
  downstream_jobs: [J1]
  blocking: true
```

Include the named initial claims: health class, current constraint, blast radius,
final-gate effect, planner horizon, evidence convergence, retry information
delta, comparable cohort, prompt pressure, repeated work, budget pace, and causal
gap. Include implemented-action candidates and absent intervention demands as
separate demand types.

- [ ] **Step 2: Create the audit snapshot and initial evidence records**

Compute SHA-256 for every cited source file and record `path`, `sha256`,
`audited_at`, and optional repository revision metadata in
`catalog/evidence.yaml`. Use content hashes as the drift authority.

- [ ] **Step 3: Write coordination projections and delegation report**

`status.md` must state Phase 0 status, all seven audit owners, current blockers,
and the distinction between artifact completion and downstream readiness.
`reviews/index.html` must be a static status page labeled “Semantic foundation,
not a product mockup.”

- [ ] **Step 4: Validate Phase 0**

Run: `uv run python research/ui-foundation/tools/validate.py --phase 0`

Expected: PASS with empty Phase 1-3 collections explicitly marked incomplete,
not silently absent.

- [ ] **Step 5: Review checkpoint**

Confirm every source demand has exactly one audit owner and no downstream UI
artifact exists.

---

### Tasks 3-9: Run Seven Parallel Reality Audits

Run these tasks concurrently. Each agent may create only its assigned report and
must not edit canonical YAML or another report.

#### Task 3: Domain And Persistence Audit

**Files:**
- Create: `research/ui-foundation/agent-reports/01-domain-persistence.md`

**Scope:**
- `src/orchestrator/db/`
- `src/orchestrator/state/`
- `src/orchestrator/config/models.py`
- `src/orchestrator/config/enums.py`
- `src/orchestrator/api/schemas/`

**Required output:** Entity inventory; identity and lifecycle boundaries;
aliases; persistence tables; ownership and cardinality; run/step/task/attempt,
graph node/record/event/requirement distinctions; exact paths and symbols.

- [ ] Inspect schemas and ORM first, then implementation and tests.
- [ ] Record each finding as implemented, tested, documented-only, inferred, or unclear.
- [ ] Record contradictions without choosing a convenient interpretation.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/01-domain-persistence.md`
- [ ] Expected: PASS with all handoff sections present.

#### Task 4: Graph Kernel And Runtime Audit

**Files:**
- Create: `research/ui-foundation/agent-reports/02-graph-runtime.md`

**Scope:**
- `src/orchestrator/graph/`
- `src/orchestrator/graph_runtime/`
- graph-focused unit and integration tests

**Required output:** Node and record types; directed edge semantics; dynamic
expansion; scheduler readiness; leases; patch commands; validation and
invariants; ordering versus causality; stale-base and rejection behavior.

- [ ] Inspect executable models, command bindings, validator, scheduler, and event registry.
- [ ] Trace every graph action to emitted records and resulting projections.
- [ ] Record graph terms that resemble workflow terms but are not equivalent.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/02-graph-runtime.md`
- [ ] Expected: PASS.

#### Task 5: Workflow And State Audit

**Files:**
- Create: `research/ui-foundation/agent-reports/03-workflow-state.md`

**Scope:**
- `src/orchestrator/workflow/`
- `src/orchestrator/executor.py`
- `src/orchestrator/db/projections/`
- workflow and signal tests

**Required output:** Run/task/attempt states; legal transitions; lifecycle signal
authority; lock behavior; retries; cancellation and recovery; race handling;
durable transition evidence; legacy versus graph-mode differences.

- [ ] Trace transitions from accepted signal through event and projection.
- [ ] Distinguish request acceptance from resulting state.
- [ ] Mark states that exist only in one execution mode.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/03-workflow-state.md`
- [ ] Expected: PASS.

#### Task 6: API, Actions, And Authority Audit

**Files:**
- Create: `research/ui-foundation/agent-reports/04-api-actions-authority.md`

**Scope:**
- `src/orchestrator/api/`
- `src/orchestrator/cli/`
- public MCP tools
- API and CLI tests

**Required output:** Implemented commands and request schemas; actors; enforced
authentication/authorization; domain preconditions; validation; effects;
failure modes; race behavior; reversibility; audit evidence; absent demanded
interventions kept as gaps.

- [ ] Treat REST, MCP, and CLI as interaction surfaces, not separate domain capabilities.
- [ ] Separate enforced authorization from assumed operator role.
- [ ] Do not complete a future steering command contract.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/04-api-actions-authority.md`
- [ ] Expected: PASS.

#### Task 7: Evidence And Telemetry Audit

**Files:**
- Create: `research/ui-foundation/agent-reports/05-evidence-telemetry.md`

**Scope:**
- workflow and graph events
- artifact storage
- prompt packet and runner trace paths
- usage and cost schemas, producers, and rollups
- relevant tests

**Required output:** Evidence types and identity; attribution; freshness;
consistency; prompt/transcript/file boundary coverage; pricing coverage;
cross-run aggregation support; unknown and stale conditions.

- [ ] Verify producer wiring, not only response schemas.
- [ ] Distinguish unpriced from zero cost.
- [ ] Identify whether repeated work, prompt pressure, and convergence inputs exist.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/05-evidence-telemetry.md`
- [ ] Expected: PASS.

#### Task 8: Current UI Projection Audit

**Files:**
- Create: `research/ui-foundation/agent-reports/06-ui-projections.md`

**Scope:**
- `ui/src/App.tsx`
- `ui/src/api/`
- `ui/src/hooks/`
- dashboard, detail, graph, decision, evidence, review, and telemetry components
- frontend tests

**Required output:** Current routes; consumed fields; available actions;
selection and URL behavior; stale/error/empty states; frontend-only inference;
current/future leakage; distributed evidence joins.

- [ ] Trace rendered values to API response types.
- [ ] Record UI labels that overstate backend semantics.
- [ ] Record action controls without complete result-state feedback.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/06-ui-projections.md`
- [ ] Expected: PASS.

#### Task 9: Tests And Documentation Adjudication Audit

**Files:**
- Create: `research/ui-foundation/agent-reports/07-tests-documentation.md`

**Scope:**
- `tests/unit/`
- `tests/integration/`
- `docs/ARCHITECTURE.md`
- `docs/intent/`
- `docs/jtbd/`
- existing `research/system/`

**Required output:** Tested behavior and invariant index; documented-only
capabilities; stale architecture claims; contradictions; historical claims that
require fresh source verification.

- [ ] Use tests as behavior evidence only when they exercise real objects.
- [ ] Flag old commit anchors and documentation drift.
- [ ] Preserve source-document intent while rejecting unsupported capability labels.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/07-tests-documentation.md`
- [ ] Expected: PASS.

---

### Tasks 10-12: Run Three Parallel Synthesis Passes

These tasks consume all seven reality reports. They write disjoint typed files
and their own synthesis report; canonical shared catalogs remain untouched until
Task 13.

#### Task 10: Domain And Relationship Synthesis

**Files:**
- Create: `research/ui-foundation/reality/domain-model.yaml`
- Create: `research/ui-foundation/reality/relationships.yaml`
- Create: `research/ui-foundation/agent-reports/08-domain-synthesis.md`

**Interfaces:**
- Produces provisional entity keys and relationship keys for Task 13.

- [ ] Normalize distinct entities without preserving slash-separated equivalences.
- [ ] Record identity, ownership, persistence, lifecycle, aliases, and mode boundaries.
- [ ] Record relationship direction, cardinality, temporal/dependency semantics, evidence, counter-evidence, and prohibited causal interpretation.
- [ ] Represent unresolved equivalence as uncertainty, not an alias.
- [ ] Run the report validator for `08-domain-synthesis.md` and parse both YAML files with `uv run python -c "import yaml; yaml.safe_load(open('research/ui-foundation/reality/domain-model.yaml')); yaml.safe_load(open('research/ui-foundation/reality/relationships.yaml'))"`.
- [ ] Expected: report PASS and both YAML files parse; canonical package validation waits for Task 13.

#### Task 11: Action, State, And Permission Synthesis

**Files:**
- Create: `research/ui-foundation/reality/state-model.yaml`
- Create: `research/ui-foundation/reality/permissions.yaml`
- Create: `research/ui-foundation/reality/actions/*.yaml`
- Create: `research/ui-foundation/agent-reports/09-action-state-synthesis.md`

**Interfaces:**
- Produces provisional action, state, transition, and invariant keys for Task 13.

- [ ] Build mode-aware legal transitions and explicit rejection paths.
- [ ] Fully contract only implemented commands.
- [ ] Record source-demanded absent interventions as gap requirements.
- [ ] Separate authentication/authorization, domain eligibility, and proposed role policy.
- [ ] Include stale-state, race, idempotency, reversibility, and resulting evidence for implemented actions.
- [ ] Run the report validator for `09-action-state-synthesis.md` and parse every produced YAML file with PyYAML; canonical package validation waits for Task 13.

#### Task 12: Evidence Inventory Synthesis

**Files:**
- Create: `research/ui-foundation/reality/evidence/inventory.yaml`
- Create: `research/ui-foundation/agent-reports/10-evidence-synthesis.md`

**Interfaces:**
- Produces provisional evidence keys, source hashes, freshness rules, and coverage gaps for Task 13.

- [ ] Normalize event, record, prompt, transcript, artifact, file-state, decision, and cost evidence without declaring them equivalent.
- [ ] Record identity, producer, persistence, attribution, query surface, freshness, consistency, missing behavior, and prohibited interpretations.
- [ ] Recompute cited source hashes and flag drift from Phase 0.
- [ ] Run the report validator for `10-evidence-synthesis.md` and parse `inventory.yaml` with PyYAML; canonical package validation waits for Task 13.

---

### Task 13: Normalize Canonical Catalogs And IDs

**Files:**
- Modify: all `research/ui-foundation/catalog/*.yaml`
- Modify: typed files from Tasks 10-12 to replace provisional keys with stable IDs.
- Modify: `research/ui-foundation/source-map.md`
- Modify: `research/ui-foundation/open-questions.md`
- Modify: `research/ui-foundation/status.md`

**Interfaces:**
- Consumes: seven audit reports and three synthesis reports.
- Produces: stable `ENT-*`, `REL-*`, `CAP-*`, `ACT-*`, `INV-*`, `Q-*`, and `CON-*` references.

- [ ] Allocate IDs once in `catalog/ids.yaml`; preserve rejected and superseded entries.
- [ ] Merge duplicate evidence only when identity and semantics match.
- [ ] Register every disagreement as a `CON-*` item with both claims and decisive evidence path.
- [ ] Register unresolved reality as `Q-*` with blocking state and settlement method.
- [ ] Generate Markdown projections from canonical records without adding facts.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --phase 1`
- [ ] Expected: PASS for Phase 1 contracts; Phase 2 capability demands may remain classified `unknown` pending Task 14.

---

### Task 14: Classify Capabilities And Define Derivations

**Files:**
- Create: `research/ui-foundation/capabilities/registry.yaml`
- Create: `research/ui-foundation/capabilities/derivations/*.yaml`
- Create: `research/ui-foundation/capabilities/gaps.md`
- Modify: `research/ui-foundation/catalog/claims.yaml`
- Modify: `research/ui-foundation/status.md`

**Interfaces:**
- Consumes: canonical Phase 1 reality and every claim/action demand in `scope.yaml`.
- Produces: exactly one `current`, `derived`, `proposed`, `gap`, or `unknown` classification per in-scope demand.

- [ ] Classify source-document labels from fresh evidence rather than copying them.
- [ ] For each `current` claim, cite reachable implementation evidence.
- [ ] For each `derived` claim, create a `DRV-*` file containing inputs, deterministic algorithm, output type, unknown conditions, freshness behavior, evidence, limitations, and prohibited interpretations.
- [ ] Keep a claim `gap` or `unknown` when an algorithm or unknown behavior cannot be defined.
- [ ] Keep typed steering and planner-assisted replanning out of the current manifest.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --phase 2`
- [ ] Expected: PASS with every in-scope demand classified and every derivation complete.

---

### Task 15: Independently Falsify The Semantic Model

**Files:**
- Verifier creates only: `research/ui-foundation/agent-reports/11-semantic-verification.md`
- Orchestrator adjudication may modify: `catalog/conflicts.yaml`, `catalog/questions.yaml`, and affected canonical contracts.

**Interfaces:**
- Consumes: complete Phase 1-2 artifacts but does not reuse a synthesis agent.
- Produces: verifier finding IDs, severity, evidence, affected IDs, and blocking state.

- [ ] Search independently for invented fields, false equivalences, unsupported causality, impossible transitions, actions without commands, current/future leakage, missing unknown states, invariant violations, evidence gaps, and degradation-scenario overfitting.
- [ ] Reopen decisive source for every Critical or High finding.
- [ ] The verifier reports findings without editing canonical files.
- [ ] At the orchestration checkpoint, accept findings by correcting canonical contracts; reject only with qualifying evidence; otherwise register a blocking conflict or question.
- [ ] Run the report validator, then `uv run python research/ui-foundation/tools/validate.py --phase 2` after adjudication.
- [ ] Expected: PASS, with unresolved verifier findings represented canonically and marked blocking or non-blocking.

---

### Task 16: Implement Review Projection And Feedback Import

**Files:**
- Create: `research/ui-foundation/tools/build_review.py`
- Create: `research/ui-foundation/tools/import_feedback.py`
- Extend: `tests/integration/test_ui_foundation_tools.py`

**Interfaces:**
- Produces: `ReviewItem(id: str, blocking: bool, downstream_dependency_count: int, authority_risk: int, capability_impact: int)`.
- Produces: `CandidateDecision(item_id: str, response: str, note: str, source_snapshot: str)`.
- Produces: `select_review_items(root: Path) -> list[list[ReviewItem]]`.
- Produces: `build_review(root: Path) -> list[Path]`.
- Produces: `import_feedback(root: Path, export_path: Path) -> list[CandidateDecision]`.

- [ ] **Step 1: Write failing integration tests**

Cover deterministic blocker-first ordering, batches of at most 12, rejection of a
stale source snapshot, response-history preservation, and the guarantee that
feedback import cannot change observed evidence or capability status.

```python
def load_tool(name: str) -> ModuleType:
    path = REPO_ROOT / f"research/ui-foundation/tools/{name}.py"
    spec = importlib.util.spec_from_file_location(f"ui_foundation_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_review_foundation(tmp_path: Path, blockers: int, non_blockers: int) -> Path:
    root = write_minimal_foundation(tmp_path)
    items = [
        {
            "id": f"Q-{index:02d}", "blocking": index <= blockers,
            "downstream_dependency_count": blockers + non_blockers - index,
            "authority_risk": 3, "capability_impact": 3,
        }
        for index in range(1, blockers + non_blockers + 1)
    ]
    write_yaml(root / "catalog/questions.yaml", {"schema_version": "1", "items": items})
    return root


def write_feedback_export(tmp_path: Path, source_snapshot: str) -> Path:
    path = tmp_path / "feedback.json"
    path.write_text(json.dumps({
        "schema_version": "1", "review_version": "phase-3-01",
        "batch_id": "01", "source_snapshot": source_snapshot,
        "exported_at": "2026-07-23T00:00:00Z", "history": [],
    }), encoding="utf-8")
    return path


def run_feedback_import(root: Path, export: Path) -> subprocess.CompletedProcess[str]:
    tool = REPO_ROOT / "research/ui-foundation/tools/import_feedback.py"
    return subprocess.run(
        [sys.executable, str(tool), "--root", str(root), str(export)],
        check=False, capture_output=True, text=True,
    )


def test_review_batches_all_blockers_before_non_blockers(tmp_path: Path) -> None:
    root = write_review_foundation(tmp_path, blockers=13, non_blockers=2)
    select_review_items = load_tool("build_review").select_review_items
    batches = select_review_items(root)
    assert [len(batch) for batch in batches] == [12, 1]
    assert all(item.blocking for batch in batches for item in batch)


def test_feedback_import_rejects_stale_snapshot(tmp_path: Path) -> None:
    root = write_review_foundation(tmp_path, blockers=1, non_blockers=0)
    export = write_feedback_export(tmp_path, source_snapshot="old")
    result = run_feedback_import(root, export)
    assert result.returncode != 0
    assert "FEEDBACK_SNAPSHOT_STALE" in result.stderr
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `uv run pytest tests/integration/test_ui_foundation_tools.py -v`

Expected: FAIL because review and import modules do not exist.

- [ ] **Step 3: Implement deterministic projection and import**

Sort by `(not blocking, -downstream_dependency_count, -authority_risk,
-capability_impact, stable_id)`. Build only blocking batches when blockers exist;
otherwise include the highest-impact non-blocking items. Validate feedback against
the JSON schema and exact source snapshot. Emit candidate decisions without
mutating canonical evidence.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/integration/test_ui_foundation_tools.py -v`

Expected: PASS.

---

### Task 17: Build And Test The Phase 3 HTML Checkpoint

**Files:**
- Generate: `research/ui-foundation/reviews/index.html`
- Generate: `research/ui-foundation/reviews/phase-3-reality-capability-01.html`
- Create: `ui/tests/e2e/ui-foundation-review.spec.ts`

**Interfaces:**
- Consumes: canonical semantic IDs, evidence, conflicts, questions, and capability classifications.
- Produces: offline review batches with versioned local feedback and export.

- [ ] Generate no more than 12 primary items per page with ID/title, importance, proposed interpretation, support, uncertainty, acceptance consequence, options, and feedback controls.
- [ ] Add filters for unresolved, accepted, rejected, revise, and uncertain.
- [ ] Put evidence paths and technical details in `<details>` disclosures.
- [ ] Persist response history under a schema-versioned `localStorage` key.
- [ ] Add JSON and concise-text export buttons and copyable item IDs.
- [ ] Add keyboard-visible focus, semantic controls, narrow responsive layout, and readable initialization failure.
- [ ] Add Playwright tests for `file://` loading, no network requests, filters, disclosure, all feedback states, persistence after reload, exports, keyboard use, 390px viewport, and initialization failure.
- [ ] Run: `npm --prefix ui run test:e2e -- tests/e2e/ui-foundation-review.spec.ts`
- [ ] Expected: PASS.

---

### Task 18: Run Final Gates And Publish The Human Checkpoint

**Files:**
- Modify: `research/ui-foundation/status.md`
- Modify: `research/ui-foundation/index.md`
- Modify: `research/ui-foundation/reviews/index.html`
- Modify: `research/ui-foundation/catalog/evidence.yaml` with final checked hashes.

**Interfaces:**
- Consumes: all Phase 0-3 artifacts and verification output.
- Produces: `complete-ready` or `complete-blocked` outcome and the review entry path.

- [ ] Recompute source hashes and re-audit every drifted evidence pointer.
- [ ] Run: `uv run python research/ui-foundation/tools/validate.py --phase 3`
- [ ] Expected: PASS.
- [ ] Run: `uv run pytest tests/integration/test_ui_foundation_tools.py -v`
- [ ] Expected: PASS.
- [ ] Run: `npm --prefix ui run test:e2e -- tests/e2e/ui-foundation-review.spec.ts`
- [ ] Expected: PASS.
- [ ] Record `complete-ready` only when no blocking conflict, unknown, verifier finding, or human decision remains; otherwise record `complete-blocked`.
- [ ] Present `research/ui-foundation/reviews/phase-3-reality-capability-01.html` to the human with the number of review batches, blocking items, capability classifications, and unresolved evidence gaps.
- [ ] Stop before jobs/journeys reconciliation, scenarios, view contracts, architecture concepts, or prototypes.

---

## Execution Waves

1. Task 1 establishes validation contracts.
2. Task 2 establishes Phase 0 scope and ownership.
3. Tasks 3-9 run concurrently as read-heavy, single-report audits.
4. Tasks 10-12 run concurrently after all audit reports exist.
5. Tasks 13-15 normalize, classify, and independently falsify in sequence.
6. Tasks 16-18 implement review mechanics, verify, and stop at the human gate.

## Completion Evidence

The executor must return:

- exact paths to all artifacts;
- counts of entities, relationships, states, actions, capabilities, derivations,
  conflicts, questions, and review items;
- all three verification command outputs;
- the final `complete-ready` or `complete-blocked` state;
- the first HTML review path;
- a concise list of decisions required from the human.
