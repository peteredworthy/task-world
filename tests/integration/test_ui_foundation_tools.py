import importlib.util
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "research/ui-foundation/tools/validate.py"
SNAPSHOT_RECORDER = REPO_ROOT / "research/ui-foundation/tools/record_snapshot_lineage.py"
SNAPSHOT_RESOLVER = REPO_ROOT / "research/ui-foundation/tools/snapshot_resolver.py"


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def append_yaml_item(path: Path, item: dict[str, object]) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {"items": []}
    value["items"].append(item)
    write_yaml(path, value)


def write_minimal_foundation(tmp_path: Path) -> Path:
    root = tmp_path / "research/ui-foundation"
    source = tmp_path / "source.txt"
    source.write_text("snapshot source\n", encoding="utf-8")
    for relative in (
        "catalog/ids.yaml",
        "catalog/claims.yaml",
        "catalog/invariants.yaml",
        "catalog/conflicts.yaml",
        "catalog/questions.yaml",
        "catalog/decisions.yaml",
        "capabilities/registry.yaml",
        "reality/domain-model.yaml",
        "reality/relationships.yaml",
        "reality/state-model.yaml",
        "reality/permissions.yaml",
        "reality/evidence/inventory.yaml",
    ):
        write_yaml(root / relative, {"schema_version": "1", "items": []})
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "active_snapshot_id": "snapshot-test",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "source.txt",
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "audited_at": "2026-07-24T00:00:00Z",
                    }
                ],
            },
            "items": [],
        },
    )
    snapshot = {
        "id": "snapshot-test",
        "files": [
            {
                "path": "source.txt",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "audited_at": "2026-07-24T00:00:00Z",
            }
        ],
    }
    snapshot_digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (root / "catalog/phase-1-snapshot.sha256").write_text(f"{snapshot_digest}\n", encoding="utf-8")
    entry = {
        "snapshot_id": "snapshot-test",
        "parent_snapshot_id": None,
        "snapshot_digest": snapshot_digest,
        "predecessor_lineage_digest": None,
        "status": "active",
    }
    entry["lineage_entry_digest"] = hashlib.sha256(
        json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    write_yaml(root / "catalog/snapshot-lineage.yaml", {"schema_version": "1", "entries": [entry]})
    return root


def run_validator(root: Path, phase: int = 2) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root), "--phase", str(phase)],
        check=False,
        capture_output=True,
        text=True,
    )


def issue_codes(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line.split(":", 1)[0] for line in result.stderr.splitlines()]


def validate_status_reviews(root: Path) -> set[str]:
    validator = load_validator()
    package = validator.load_foundation(root)
    scope = package.documents["catalog/status-scope.yaml"]["items"]
    records = {}
    for item in scope:
        document = package.documents[item["path"]]
        record = (
            document
            if document.get("id") == item["id"]
            else next(value for value in document["items"] if value["id"] == item["id"])
        )
        records[item["id"]] = (item["path"], record)
    active = validator._active_snapshot(package.documents["catalog/evidence.yaml"])
    return {
        issue.code
        for issue in validator._validate_status_evidence_reviews(package, records, active["id"])
    }


def status_review_catalog(root: Path) -> dict[str, object]:
    return yaml.safe_load(
        (root / "catalog/status-evidence-reviews.yaml").read_text(encoding="utf-8")
    )


def write_status_review_catalog(root: Path, value: dict[str, object]) -> None:
    write_yaml(root / "catalog/status-evidence-reviews.yaml", value)


def phase_two_closure(root: Path) -> dict[str, object]:
    catalog = status_review_catalog(root)
    scope = yaml.safe_load((root / "catalog/status-scope.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((root / "catalog/status-test-nodes.yaml").read_text(encoding="utf-8"))
    records = []
    for item in scope["items"]:
        document = yaml.safe_load((root / item["path"]).read_text(encoding="utf-8"))
        records.append(
            document
            if document.get("id") == item["id"]
            else next(value for value in document["items"] if value["id"] == item["id"])
        )
    families = ("REL", "STA", "ACT", "EVI", "INV")
    return {
        "schema_version": "1",
        "status": "passed",
        "reviewer": {
            "reviewer_id": "reviewer-independent",
            "model": "openai/gpt-5.6-sol",
            "role": "independent-semantic-closure-reviewer",
        },
        "independence": {
            "status": "independent",
            "basis": "No authorship of the reviewed status or review artifacts.",
        },
        "active_snapshot_id": catalog["metadata"]["active_snapshot_id"],
        "artifact_digests": {
            relative: f"sha256:{hashlib.sha256((root / relative).read_bytes()).hexdigest()}"
            for relative in (
                "catalog/status-scope.yaml",
                "catalog/status-evidence-reviews.yaml",
                "catalog/status-test-nodes.yaml",
            )
        },
        "counts": {
            "status_records": len(records),
            "status_records_by_family": {
                family: sum(record["id"].startswith(f"{family}-") for record in records)
                for family in families
            },
            "ser_rows": len(catalog["reviews"]),
            "ser_admission_counts": {
                status: sum(row["admission"] == status for row in catalog["reviews"])
                for status in ("admitted", "bounded", "rejected")
            },
            "sdr_rows": len(catalog["dimension_reviews"]),
            "exact_test_locators": sum(len(record.get("test_locators", [])) for record in records),
            "bounded_test_locators": sum(
                len(record.get("bounded_test_locators", [])) for record in records
            ),
            "test_manifest_bases": len(manifest["entries"]),
            "test_manifest_nodes": sum(
                len(entry["concrete_node_ids"]) for entry in manifest["entries"]
            ),
            "test_status_by_family": {
                family: {
                    status: sum(
                        record["id"].startswith(f"{family}-") and record["test_status"] == status
                        for record in records
                    )
                    for status in ("exercised", "unexercised")
                }
                for family in families
            },
        },
        "predecessor_report_sha256": None,
        "findings": [
            {"finding_id": f"SV-{number:03d}", "status": "resolved", "rationale": "Rechecked."}
            for number in range(1, 9)
        ],
        "blocking_items": [],
        "commands": [
            {
                "argv": [
                    "uv",
                    "run",
                    "python",
                    "research/ui-foundation/tools/validate.py",
                    "--phase",
                    "2",
                ],
                "active_snapshot_id": catalog["metadata"]["active_snapshot_id"],
                "exit_code": 0,
            },
            {
                "argv": ["uv", "run", "pytest", "tests/integration/test_ui_foundation_tools.py"],
                "active_snapshot_id": catalog["metadata"]["active_snapshot_id"],
                "exit_code": 0,
            },
            {
                "argv": ["uv", "run", "pytest"],
                "active_snapshot_id": catalog["metadata"]["active_snapshot_id"],
                "exit_code": 0,
            },
        ],
    }


def mark_task15_complete(root: Path) -> None:
    status_path = root / "status.md"
    status_path.write_text(
        status_path.read_text(encoding="utf-8").replace(
            "Task15 remains IN PROGRESS pending independent review.",
            "Task15 is COMPLETE after independent review.",
        ),
        encoding="utf-8",
    )


def documentation_summary(
    catalog: dict[str, object], record_id: str = "REL-1"
) -> dict[str, object]:
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    return next(
        value
        for value in summaries
        if value["record_id"] == record_id and value["dimension"] == "documentation"
    )


def implementation_summary(catalog: dict[str, object], record_id: str) -> dict[str, object]:
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    return next(
        value
        for value in summaries
        if value["record_id"] == record_id and value["dimension"] == "implementation"
    )


def locator_review(catalog: dict[str, object], review_id: str) -> dict[str, object]:
    reviews = catalog["reviews"]
    assert isinstance(reviews, list)
    return next(value for value in reviews if value["review_id"] == review_id)


def capability_summary(catalog: dict[str, object], record_id: str = "REL-1") -> dict[str, object]:
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    return next(
        value
        for value in summaries
        if value["record_id"] == record_id and value["dimension"] == "capability"
    )


def epistemic_summary(catalog: dict[str, object], record_id: str = "REL-1") -> dict[str, object]:
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    return next(
        value
        for value in summaries
        if value["record_id"] == record_id and value["dimension"] == "epistemic"
    )


def canonical_status_record(root: Path, record_id: str) -> tuple[Path, dict[str, object]]:
    scope = yaml.safe_load((root / "catalog/status-scope.yaml").read_text(encoding="utf-8"))
    relative = next(item["path"] for item in scope["items"] if item["id"] == record_id)
    path = root / relative
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    record = (
        document
        if document.get("id") == record_id
        else next(item for item in document["items"] if item["id"] == record_id)
    )
    return path, record


def set_canonical_epistemic_status(root: Path, record_id: str, status: str) -> None:
    path, record = canonical_status_record(root, record_id)
    record["epistemic_status"] = status
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if document.get("id") == record_id:
        document = record
    else:
        next(item for item in document["items"] if item["id"] == record_id)["epistemic_status"] = (
            status
        )
    write_yaml(path, document)


def load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ui_foundation_validate", VALIDATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_snapshot_recorder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ui_foundation_snapshot_recorder", SNAPSHOT_RECORDER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_snapshot_resolver() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ui_foundation_snapshot_resolver", SNAPSHOT_RESOLVER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def copy_foundation_with_source(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    root = repository / "research/ui-foundation"
    root.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    (repository / "src").symlink_to(REPO_ROOT / "src", target_is_directory=True)
    (repository / "tests").symlink_to(REPO_ROOT / "tests", target_is_directory=True)
    return root


SELF_SNAPSHOT_PATHS = (
    "research/ui-foundation/catalog/evidence.yaml",
    "research/ui-foundation/catalog/snapshot-lineage.yaml",
)


def add_legacy_self_snapshot_records(root: Path) -> None:
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    repository = root.parents[1]
    for relative in SELF_SNAPSHOT_PATHS:
        path = repository / relative
        evidence["snapshot"]["files"].append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "audited_at": "2026-07-24T00:00:00Z",
            }
        )
    write_yaml(evidence_path, evidence)


def status_scope_items(root: Path) -> list[dict[str, str]]:
    fixed_paths = {
        "REL": "reality/relationships.yaml",
        "STA": "reality/state-model.yaml",
        "EVI": "reality/evidence/inventory.yaml",
        "INV": "catalog/invariants.yaml",
    }
    family_ids = {
        "REL": range(1, 36),
        "STA": (*range(1, 28), *range(29, 74)),
        "EVI": range(1, 10),
        "INV": range(2, 8),
    }
    items = [
        {"id": f"{family}-{number}", "path": path}
        for family, numbers in family_ids.items()
        for number in numbers
        for path in (fixed_paths[family],)
    ]
    for path in sorted((root / "reality/actions").glob("act-*.yaml")):
        action = yaml.safe_load(path.read_text(encoding="utf-8"))
        items.append({"id": action["id"], "path": path.relative_to(root).as_posix()})
    return items


def write_status_scope(root: Path, items: list[dict[str, str]] | None = None) -> Path:
    path = root / "catalog/status-scope.yaml"
    write_yaml(
        path,
        {"schema_version": "1", "items": items if items is not None else status_scope_items(root)},
    )
    return path


def write_valid_phase_zero(tmp_path: Path) -> Path:
    root = write_minimal_foundation(tmp_path)
    for relative in (
        "index.md",
        "status.md",
        "source-map.md",
        "decision-log.md",
        "open-questions.md",
        "capabilities/gaps.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("complete\n", encoding="utf-8")
    write_yaml(root / "catalog/scope.yaml", {"schema_version": "1", "items": []})
    review = root / "reviews/index.html"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text("Semantic foundation, not a product mockup.", encoding="utf-8")
    schemas = root / "schemas"
    schemas.mkdir(parents=True)
    for name in ("semantic-item.schema.json", "review-feedback.schema.json"):
        shutil.copyfile(REPO_ROOT / "research/ui-foundation/schemas" / name, schemas / name)
    return root


def semantic_item(identifier: str, **overrides: object) -> dict[str, object]:
    return {
        "id": identifier,
        "title": identifier,
        "definition": "Definition",
        "implementation_status": "unknown",
        "test_status": "unknown",
        "documentation_status": "unknown",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": [],
        "conflict_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    } | overrides


def status_basis(**overrides: object) -> dict[str, object]:
    return {
        "implementation": "Direct implementation locator: src/example.py::carrier.",
        "test": "Direct test locator: tests/test_example.py::test_carrier.",
        "documentation": "Canonical record definition and limitations.",
        "capability": "Carrier existence does not establish a product capability.",
        "epistemic": "Observed in the immutable Phase 1 snapshot.",
    } | overrides


def present_action(command_id: str, transition: dict[str, object]) -> dict[str, object]:
    return {
        "id": "ACT-01",
        "implementation_status": "present",
        "capability_status": "current",
        "executable": True,
        "command_id": command_id,
        "actor": "operator",
        "permission_requirements": ["run.write"],
        "preconditions": ["run active"],
        "expected_source_version": "v1",
        "required_input": {"reason": "text"},
        "validation": ["reason nonempty"],
        "durable_effect": "records command",
        "resulting_state_id": "STA-02",
        "failure_modes": ["stale"],
        "stale_state_behavior": "reject",
        "idempotency": "command id",
        "retry_behavior": "safe with same id",
        "reversibility": "irreversible",
        "audit_evidence_ids": ["EVD-01"],
        "transition": transition,
    }


def run_report_validator(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--report", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_validator_rejects_duplicate_ids(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    append_yaml_item(root / "catalog/claims.yaml", semantic_item("CAP-01"))
    append_yaml_item(root / "capabilities/registry.yaml", semantic_item("CAP-01"))
    result = run_validator(root)
    assert result.returncode == 1
    assert "ID_DUPLICATE" in result.stderr


def test_phase_one_ignores_exact_capability_claims_projection_for_duplicate_ids(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    item = semantic_item("CAP-01")
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "phase_status": "complete",
            "completion_phase": 2,
            "items": [item],
        },
    )
    validator = load_validator()
    package = validator.load_foundation(root)
    write_yaml(
        root / "catalog/claims.yaml",
        validator._phase_two_claims_projection(package, [item]),
    )

    result = run_validator(root, phase=1)

    assert "ID_DUPLICATE" not in issue_codes(result)


def test_status_adjudication_requires_dimension_specific_basis_and_direct_implementation(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/relationships.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "REL-1",
                    implementation_status="present",
                    documentation_status="documented",
                    epistemic_status="observed",
                    status_basis={"implementation": "carrier exists"},
                )
            ],
        },
    )

    result = run_validator(root)

    assert "STATUS_BASIS_MISSING" in issue_codes(result)


def test_present_status_requires_resolving_implementation_locator(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/relationships.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "REL-1",
                    implementation_status="present",
                    documentation_status="documented",
                    epistemic_status="observed",
                    status_basis=status_basis(),
                )
            ],
        },
    )

    result = run_validator(root)

    assert "IMPLEMENTATION_LOCATOR_UNRESOLVED" in issue_codes(result)


def test_status_adjudication_rejects_exercised_without_resolvable_test_locator(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "STA-01",
                    implementation_status="absent",
                    test_status="exercised",
                    documentation_status="documented",
                    epistemic_status="observed",
                    status_basis=status_basis(),
                )
            ],
        },
    )

    result = run_validator(root)

    assert "EXERCISED_DIRECT_TEST_EVIDENCE_MISSING" in issue_codes(result)


def test_status_locator_requires_exact_ast_test_symbol_and_current_snapshot_hash(
    tmp_path: Path,
) -> None:
    validator = load_validator()
    test_path = tmp_path / "tests/test_locator.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', [1])\n"
        "def test_parametrized(value):\n"
        "    assert value == 1\n\n"
        "def simple_routine():\n"
        "    return None\n\n"
        "class TestLocator:\n"
        "    def test_method(self):\n"
        "        assert True\n",
        encoding="utf-8",
    )
    relative = "tests/test_locator.py"
    snapshot_paths = {"snapshot": {relative}}
    snapshot_hashes = {relative: hashlib.sha256(test_path.read_bytes()).hexdigest()}

    assert validator._basis_test_locator_is_snapshot_resolvable(
        f"Exact test: {relative}::test_parametrized.", snapshot_paths, tmp_path, snapshot_hashes
    )
    assert validator._basis_test_locator_is_snapshot_resolvable(
        f"Exact method: {relative}::TestLocator::test_method.",
        snapshot_paths,
        tmp_path,
        snapshot_hashes,
    )
    assert not validator._basis_test_locator_is_snapshot_resolvable(
        f"Fixture: {relative}::simple_routine.",
        snapshot_paths,
        tmp_path,
        snapshot_hashes,
    )
    assert not validator._basis_test_locator_is_snapshot_resolvable(
        f"Arbitrary suffix: {relative}::test_parametrized::carrier_boundary.",
        snapshot_paths,
        tmp_path,
        snapshot_hashes,
    )
    assert not validator._basis_test_locator_is_snapshot_resolvable(
        f"Invented suffix: {relative}::record-specific carrier boundary.",
        snapshot_paths,
        tmp_path,
        snapshot_hashes,
    )
    assert not validator._basis_test_locator_is_snapshot_resolvable(
        f"Missing method: {relative}::TestLocator::test_missing.",
        snapshot_paths,
        tmp_path,
        snapshot_hashes,
    )
    assert not validator._basis_test_locator_is_snapshot_resolvable(
        f"Missing class: {relative}::Missing::test_method.",
        snapshot_paths,
        tmp_path,
        snapshot_hashes,
    )


def test_status_locator_rejects_stale_active_snapshot_hash(tmp_path: Path) -> None:
    validator = load_validator()
    test_path = tmp_path / "tests/test_locator.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_locator():\n    assert True\n", encoding="utf-8")

    assert not validator._basis_test_locator_is_snapshot_resolvable(
        "Exact test: tests/test_locator.py::test_locator.",
        {"snapshot": {"tests/test_locator.py"}},
        tmp_path,
        {"tests/test_locator.py": "stale"},
    )


def test_status_evidence_reviews_enforce_partitions_statuses_and_metadata(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    reviews = catalog["reviews"]
    summaries = catalog["dimension_reviews"]
    assert isinstance(reviews, list) and isinstance(summaries, list)

    catalog["metadata"]["scope_manifest_digest"] = f"sha256:{'0' * 64}"
    summaries.pop()
    first_test = next(review for review in reviews if review["dimension"] == "test")
    first_test["verdict"] = "does-not-prove"
    first_test["admission"] = "admitted"
    first_implementation = next(
        review for review in reviews if review["dimension"] == "implementation"
    )
    first_implementation["locator"] = "reality/relationships.yaml::items"
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_REVIEW_METADATA_MISMATCH" in codes
    assert "STATUS_EVIDENCE_DIMENSION_SUMMARY_MISSING" in codes
    assert "STATUS_EVIDENCE_TEST_ADMISSION_INVALID" in codes
    assert "STATUS_EVIDENCE_LOCATOR_PARTITION_INVALID" in codes


def test_status_evidence_review_v2_declares_exact_contributors_and_collection_semantics() -> None:
    catalog = status_review_catalog(REPO_ROOT / "research/ui-foundation")
    metadata = catalog["metadata"]

    assert metadata["schema_version"] == "2"
    assert metadata["canonical_test_status_meaning"] == "qualifying-collected-test-coverage"
    assert metadata["implies_test_execution"] is False
    assert metadata["collection_manifest_path"] == "catalog/status-test-nodes.yaml"
    assert "reviewer_model" not in metadata
    assert "reviewer_role" not in metadata
    declared_ids = {reviewer["reviewer_id"] for reviewer in metadata["reviewers"]}
    referenced_ids = {
        row["reviewer_id"] for key in ("reviews", "dimension_reviews") for row in catalog[key]
    }
    assert referenced_ids == declared_ids
    assert metadata["final_reviewer_id"] in declared_ids
    assert all(
        "reviewer" not in row for key in ("reviews", "dimension_reviews") for row in catalog[key]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda catalog: catalog["reviews"][0].__setitem__("reviewer_id", "undeclared"),
            "STATUS_EVIDENCE_REVIEW_CONTRIBUTORS_INVALID",
        ),
        (
            lambda catalog: catalog["metadata"]["reviewers"].append(
                {"reviewer_id": "unused", "model": "unused/model", "role": "unused"}
            ),
            "STATUS_EVIDENCE_REVIEW_CONTRIBUTORS_INVALID",
        ),
        (
            lambda catalog: catalog["metadata"].__setitem__("final_reviewer_id", "undeclared"),
            "STATUS_EVIDENCE_REVIEW_FINAL_REVIEWER_INVALID",
        ),
        (
            lambda catalog: catalog["metadata"].__setitem__("implies_test_execution", True),
            "STATUS_EVIDENCE_REVIEW_CATALOG_INVALID",
        ),
    ],
)
def test_status_evidence_review_v2_rejects_false_provenance(
    tmp_path: Path, mutation: object, expected_code: str
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    assert callable(mutation)
    mutation(catalog)
    write_status_review_catalog(root, catalog)

    assert expected_code in validate_status_reviews(root)


def test_phase_two_allows_no_semantic_closure_while_task15_is_in_progress(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    validator = load_validator()

    codes = {
        issue.code
        for issue in validator._validate_phase_two_semantic_closures(
            validator.load_foundation(root)
        )
    }

    assert "PHASE_TWO_SEMANTIC_CLOSURE_REQUIRED" not in codes


def test_passed_phase_two_semantic_closure_rejects_stale_or_false_evidence(
    tmp_path: Path,
) -> None:
    cases = [
        (
            lambda closure: closure["artifact_digests"].__setitem__(
                "catalog/status-scope.yaml", f"sha256:{'0' * 64}"
            ),
            "PHASE_TWO_SEMANTIC_CLOSURE_DIGEST_MISMATCH",
        ),
        (
            lambda closure: closure["counts"].__setitem__("ser_rows", 0),
            "PHASE_TWO_SEMANTIC_CLOSURE_COUNT_MISMATCH",
        ),
        (
            lambda closure: closure.__setitem__("active_snapshot_id", "stale-snapshot"),
            "PHASE_TWO_SEMANTIC_CLOSURE_SNAPSHOT_MISMATCH",
        ),
        (
            lambda closure: closure["findings"].pop(),
            "PHASE_TWO_SEMANTIC_CLOSURE_FINDINGS_INVALID",
        ),
        (
            lambda closure: closure["findings"][0].__setitem__("status", "still-blocking"),
            "PHASE_TWO_SEMANTIC_CLOSURE_FINDINGS_INVALID",
        ),
        (
            lambda closure: closure["blocking_items"].append("SV-001 remains open"),
            "PHASE_TWO_SEMANTIC_CLOSURE_BLOCKED",
        ),
        (
            lambda closure: closure["commands"][2]["argv"].append("--collect-only"),
            "PHASE_TWO_SEMANTIC_CLOSURE_EXECUTION_INVALID",
        ),
        (
            lambda closure: closure["commands"][0].__setitem__("exit_code", 1),
            "PHASE_TWO_SEMANTIC_CLOSURE_EXECUTION_INVALID",
        ),
    ]
    root = copy_foundation_with_source(tmp_path)
    mark_task15_complete(root)
    base_closure = phase_two_closure(root)
    closure_path = "verifications/phase-2-semantic-closure-001.yaml"
    write_yaml(root / closure_path, base_closure)
    validator = load_validator()
    package = validator.load_foundation(root)

    for mutation, expected_code in cases:
        closure = deepcopy(base_closure)
        mutation(closure)
        package.documents[closure_path] = closure
        codes = {issue.code for issue in validator._validate_phase_two_semantic_closures(package)}

        assert expected_code in codes


def test_phase_two_semantic_closure_rejects_predecessor_hash_mismatch(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    mark_task15_complete(root)
    latest = phase_two_closure(root)
    previous = deepcopy(latest)
    previous["status"] = "failed"
    write_yaml(root / "verifications/phase-2-semantic-closure-001.yaml", previous)
    latest["predecessor_report_sha256"] = f"sha256:{'0' * 64}"
    write_yaml(root / "verifications/phase-2-semantic-closure-002.yaml", latest)
    validator = load_validator()

    codes = {
        issue.code
        for issue in validator._validate_phase_two_semantic_closures(
            validator.load_foundation(root)
        )
    }

    assert "PHASE_TWO_SEMANTIC_CLOSURE_PREDECESSOR_MISMATCH" in codes


def test_phase_two_allows_task15_completion_without_semantic_closure(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    mark_task15_complete(root)
    validator = load_validator()

    codes = {
        issue.code
        for issue in validator._validate_phase_two_semantic_closures(
            validator.load_foundation(root)
        )
    }

    assert "PHASE_TWO_SEMANTIC_CLOSURE_REQUIRED" not in codes


def test_phase_two_rejects_completed_index_with_incomplete_shell_claim(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    index_path = root / "index.md"
    index_path.write_text(
        index_path.read_text(encoding="utf-8") + "\nPhase 2 is an incomplete shell.\n",
        encoding="utf-8",
    )
    validator = load_validator()

    issues = validator._validate_phase_two_index_statement(validator.load_foundation(root))

    assert {issue.code for issue in issues} == {"PHASE_TWO_INDEX_STATUS_CONTRADICTION"}


def test_status_evidence_reviews_reject_active_rejected_and_wrong_partitions(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    reviews = catalog["reviews"]
    assert isinstance(reviews, list)
    test_review = next(review for review in reviews if review["dimension"] == "test")
    record_id, locator = test_review["record_id"], test_review["locator"]
    test_review["admission"] = "rejected"
    test_review["verdict"] = "does-not-prove"
    summary = next(
        value
        for value in catalog["dimension_reviews"]
        if value["record_id"] == record_id and value["dimension"] == "test"
    )
    summary["admitted_locators"].remove(test_review["review_id"])
    summary["rejected_locators"].append(test_review["review_id"])
    scope = yaml.safe_load((root / "catalog/status-scope.yaml").read_text(encoding="utf-8"))
    path = next(item["path"] for item in scope["items"] if item["id"] == record_id)
    document_path = root / path
    document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    record = (
        document
        if document.get("id") == record_id
        else next(item for item in document["items"] if item["id"] == record_id)
    )
    record["test_locators"] = [locator]
    record["test_status"] = "exercised"
    write_yaml(document_path, document)
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_REJECTED_LOCATOR_ACTIVE" in codes
    assert "STATUS_EVIDENCE_CANONICAL_TEST_PARTITION_MISMATCH" in codes


def test_status_evidence_reviews_reject_partial_test_left_exact_and_wrong_summary_status(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    reviews = catalog["reviews"]
    summaries = catalog["dimension_reviews"]
    assert isinstance(reviews, list) and isinstance(summaries, list)
    partial = next(
        review
        for review in reviews
        if review["dimension"] == "test" and review["verdict"] == "partially-proves"
    )
    summary = next(
        value
        for value in summaries
        if value["record_id"] == partial["record_id"] and value["dimension"] == "test"
    )
    summary["admitted_locators"] = [partial["review_id"]]
    summary["bounded_locators"] = []
    summary["combined_verdict"] = "proves"
    summary["compatible_status"] = "exercised"
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_SUMMARY_STATUS_INVALID" in codes
    assert "STATUS_EVIDENCE_CANONICAL_TEST_PARTITION_MISMATCH" in codes


def test_implementation_composition_accepts_simple_admitted_proof(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" not in validate_status_reviews(root)


def test_implementation_composition_accepts_complementary_partial_proofs(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = implementation_summary(catalog, "EVI-1")
    assert summary["combined_verdict"] == "proves"
    assert all(
        locator_review(catalog, review_id)["verdict"] == "partially-proves"
        for review_id in summary["admitted_locators"]
    )

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" not in validate_status_reviews(root)


def test_implementation_composition_accepts_truthful_partial(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = implementation_summary(catalog, "EVI-4")
    assert summary["compatible_status"] == "partial"
    assert summary["uncovered_boundary"]

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" not in validate_status_reviews(root)


def test_implementation_composition_accepts_rejected_noncanonical_candidate(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    reviews = catalog["reviews"]
    assert isinstance(reviews, list)
    reviews.append(
        {
            "review_id": "SER-9999",
            "record_id": "ACT-1",
            "dimension": "implementation",
            "locator_kind": "python-symbol",
            "locator": "src/orchestrator/api/routers/runners.py::unrelated_candidate",
            "record_proposition": "An exploratory adjacent symbol does not implement ACT-1.",
            "observed_source_or_test_fact": "The candidate is adjacent but does not replace profile-default rows.",
            "boundary": "This rejected candidate is not a canonical ACT-1 implementation locator.",
            "verdict": "does-not-prove",
            "status_compatibility": "partial",
            "review_rationale": "The exploratory symbol is retained as negative evidence only.",
            "reviewer_id": "sol-independent",
            "reviewed_at": "2026-07-25T00:00:00Z",
            "admission": "rejected",
        }
    )
    implementation_summary(catalog, "ACT-1")["rejected_locators"].append("SER-9999")
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" not in validate_status_reviews(root)


@pytest.mark.parametrize(
    ("admission", "verdict", "partition"),
    [
        ("bounded", "partially-proves", "bounded_locators"),
        ("rejected", "does-not-prove", "rejected_locators"),
    ],
)
def test_implementation_composition_rejects_nonadmitted_canonical_locator(
    tmp_path: Path, admission: str, verdict: str, partition: str
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = implementation_summary(catalog, "ACT-1")
    review_id = summary["admitted_locators"].pop()
    summary[partition].append(review_id)
    row = locator_review(catalog, review_id)
    row["admission"] = admission
    row["verdict"] = verdict
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" in validate_status_reviews(root)


def test_implementation_composition_rejects_present_partial_rows_without_clause_map(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = implementation_summary(catalog, "EVI-1")
    summary["required_clause_ids"] = []
    summary["clauses"] = {}
    for review_id in summary["admitted_locators"]:
        locator_review(catalog, review_id)["covered_clause_ids"] = []
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" in validate_status_reviews(root)


def test_implementation_composition_rejects_unknown_clause_id(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = implementation_summary(catalog, "EVI-1")
    locator_review(catalog, summary["admitted_locators"][0])["covered_clause_ids"].append(
        "unknown-clause"
    )
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" in validate_status_reviews(root)


def test_implementation_composition_rejects_uncovered_required_clause(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = implementation_summary(catalog, "EVI-1")
    locator_review(catalog, summary["admitted_locators"][-1])["covered_clause_ids"] = []
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" in validate_status_reviews(root)


def test_implementation_composition_rejects_partial_claiming_full_coverage(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = implementation_summary(catalog, "EVI-4")
    required = summary["required_clause_ids"]
    locator_review(catalog, summary["admitted_locators"][0])["covered_clause_ids"] = list(required)
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_IMPLEMENTATION_COMPOSITION_INVALID" in validate_status_reviews(root)


def test_status_evidence_reviews_rejects_each_dimension_status_mutation(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    replacements = {
        "implementation": "absent",
        "test": "unexercised",
        "documentation": "unknown",
        "capability": "gap",
        "epistemic": "unknown",
    }
    for dimension, replacement in replacements.items():
        summary = next(
            item
            for item in summaries
            if item["record_id"] == "REL-1" and item["dimension"] == dimension
        )
        summary["compatible_status"] = replacement
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DIMENSION_CANONICAL_MISMATCH" in codes


def test_capability_unknown_requires_unresolved_boundary(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    capability_summary(catalog)["unresolved_boundary"] = ""
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_unknown_rejects_global_cap_substitution(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = capability_summary(catalog)
    summary["authority_ids"] = ["CAP-1"]
    summary["capability_authority_bindings"] = [
        {"authority_id": "CAP-1", "relation": "gap-contract"}
    ]
    summary["gap_contract_ids"] = ["CAP-1"]
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_gap_rejects_unrelated_gap_cap(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = capability_summary(catalog, "ACT-15")
    summary["gap_contract_ids"] = ["CAP-85"]
    summary["capability_authority_bindings"] = [
        {"authority_id": "CAP-85", "relation": "gap-contract"}
    ]
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_gap_requires_reciprocal_action(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    capability = next(item for item in registry["items"] if item["id"] == "CAP-92")
    capability["gap_action_ids"] = []
    write_yaml(registry_path, registry)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_gap_requires_gap_contract_relation(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    capability_summary(catalog, "ACT-15")["capability_authority_bindings"][0]["relation"] = (
        "implementation-carrier"
    )
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_gap_requires_exact_action_proposition(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    capability_summary(catalog, "ACT-15")["record_proposition"] = (
        "ACT-15 user-capability proposition: An unrelated future action."
    )
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_current_requires_typed_authority(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = capability_summary(catalog, "ACT-15")
    summary["compatible_status"] = "current"
    summary["combined_verdict"] = "proves"
    summary["authority_ids"] = ["CAP-92"]
    summary["gap_contract_ids"] = []
    summary["capability_authority_bindings"] = []
    action_path = root / "reality/actions/act-15-steer-context-gap.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["capability_status"] = "current"
    write_yaml(action_path, action)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    capability = next(item for item in registry["items"] if item["id"] == "CAP-92")
    capability["capability_status"] = "current"
    capability["implementation_carrier_bindings"] = [{"id": "ACT-15"}]
    write_yaml(registry_path, registry)
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_derived_requires_typed_cap_and_derivation_authority(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = capability_summary(catalog, "ACT-15")
    summary["compatible_status"] = "derived"
    summary["combined_verdict"] = "proves"
    summary["authority_ids"] = ["CAP-92"]
    summary["derivation_contract_ids"] = ["DRV-1"]
    summary["gap_contract_ids"] = []
    summary["capability_authority_bindings"] = []
    action_path = root / "reality/actions/act-15-steer-context-gap.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["capability_status"] = "derived"
    write_yaml(action_path, action)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    capability = next(item for item in registry["items"] if item["id"] == "CAP-92")
    capability["capability_status"] = "derived"
    capability["derivation_contract_ids"] = ["DRV-1"]
    capability["implementation_carrier_bindings"] = [{"id": "ACT-15"}]
    write_yaml(registry_path, registry)
    write_yaml(root / "capabilities/derivations/drv-1.yaml", {"id": "DRV-1"})
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_capability_proposed_requires_typed_source_demand_authority(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = capability_summary(catalog, "ACT-15")
    summary["compatible_status"] = "proposed"
    summary["combined_verdict"] = "proposed"
    summary["authority_ids"] = ["CAP-92"]
    summary["gap_contract_ids"] = []
    summary["capability_authority_bindings"] = []
    action_path = root / "reality/actions/act-15-steer-context-gap.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["capability_status"] = "proposed"
    write_yaml(action_path, action)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    capability = next(item for item in registry["items"] if item["id"] == "CAP-92")
    capability["capability_status"] = "proposed"
    write_yaml(registry_path, registry)
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in validate_status_reviews(root)


def test_status_evidence_reviews_rejects_false_conflict_promotion_and_epistemic_evidence_removal(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    documentation = next(
        item
        for item in summaries
        if item["record_id"] == "REL-1" and item["dimension"] == "documentation"
    )
    documentation["compatible_status"] = "conflicting"
    documentation["combined_verdict"] = "contradicts"
    epistemic = next(
        item
        for item in summaries
        if item["record_id"] == "REL-1" and item["dimension"] == "epistemic"
    )
    epistemic["evidence_ids"] = []
    epistemic["observation_evidence_ids"] = []
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_STATUS_INVALID" in codes
    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in codes


def test_status_evidence_reviews_rejects_overlapping_partial_clause_coverage(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    reviews = catalog["reviews"]
    summaries = catalog["dimension_reviews"]
    assert isinstance(reviews, list) and isinstance(summaries, list)
    summary = next(
        value
        for value in summaries
        if value["dimension"] == "test"
        and value["compatible_status"] == "exercised"
        and len(value["admitted_locators"]) >= 2
    )
    first, second = (
        next(value for value in reviews if value["review_id"] == review_id)
        for review_id in summary["admitted_locators"][:2]
    )
    assert isinstance(first["covered_clause_ids"], list)
    second["covered_clause_ids"] = list(first["covered_clause_ids"])
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_CLAUSE_COVERAGE_INVALID" in codes


def test_status_evidence_reviews_rejects_missing_required_test_clause(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(
        value
        for value in summaries
        if value["dimension"] == "test" and value["compatible_status"] == "exercised"
    )
    assert isinstance(summary["required_clause_ids"], list)
    summary["required_clause_ids"] = summary["required_clause_ids"] + ["missing-required-clause"]
    summary["clauses"]["missing-required-clause"] = "A required clause without admitted evidence."
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_CLAUSE_COVERAGE_INVALID" in codes


def test_status_evidence_reviews_rejects_bounded_test_clause_counted_as_exercised(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    reviews = catalog["reviews"]
    summaries = catalog["dimension_reviews"]
    assert isinstance(reviews, list) and isinstance(summaries, list)
    summary = next(
        value
        for value in summaries
        if value["dimension"] == "test"
        and value["compatible_status"] == "unexercised"
        and value["bounded_locators"]
    )
    bounded = next(
        value for value in reviews if value["review_id"] == summary["bounded_locators"][0]
    )
    summary["admitted_locators"].append(bounded["review_id"])
    summary["bounded_locators"].remove(bounded["review_id"])
    bounded["admission"] = "admitted"
    bounded["verdict"] = "proves"
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_CLAUSE_COVERAGE_INVALID" in codes


def test_status_evidence_reviews_rejects_open_question_as_documentation_contradiction(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(value for value in summaries if value["dimension"] == "documentation")
    summary["compatible_status"] = "conflicting"
    summary["combined_verdict"] = "contradicts"
    summary["contradiction_clauses"] = {"Q-5": "A question is not contradictory authority."}
    summary["conflict_ids"] = []
    summary["question_ids"] = ["Q-5"]
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_CONTRADICTION_INVALID" in codes


def test_status_evidence_reviews_require_typed_documentation_authority(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    documentation_summary(catalog).pop("documentation_authority")
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_AUTHORITY_REQUIRED" in codes


def test_status_evidence_reviews_reject_wrong_documentation_declaration_path(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    authority = documentation_summary(catalog)["documentation_authority"]
    authority["canonical_declaration"]["path"] = "reality/state-model.yaml"
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_DECLARATION_INVALID" in codes


def test_status_evidence_reviews_reject_wrong_documentation_declaration_id(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    authority = documentation_summary(catalog)["documentation_authority"]
    authority["canonical_declaration"]["id"] = "REL-2"
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_DECLARATION_INVALID" in codes


def test_status_evidence_reviews_reject_wrong_documentation_declaration_hash(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    authority = documentation_summary(catalog)["documentation_authority"]
    authority["canonical_declaration"]["current_sha256"] = f"sha256:{'0' * 64}"
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_DECLARATION_HASH_MISMATCH" in codes


def test_status_evidence_reviews_reject_globally_valid_unrelated_documentation_evidence(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = documentation_summary(catalog)
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    unrelated = next(item for item in evidence["items"] if item["id"] == "EVD-50")
    summary["evidence_ids"] = ["EVD-50"]
    summary["documentation_evidence_ids"] = ["EVD-50"]
    summary["documentation_authority"]["evidence_bindings"] = [
        {
            "evidence_id": "EVD-50",
            "expected_source_kind": unrelated["source_kind"],
            "expected_provenance_role": unrelated["provenance_role"],
            "path": unrelated["path"],
            "symbol_or_heading": unrelated["symbol"],
            "proposition_role": "audit-synthesis-record-trace",
        }
    ]
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_BINDING_INVALID" in codes


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("expected_source_kind", "source-code"),
        ("expected_provenance_role", "direct"),
        ("path", "research/ui-foundation/agent-reports/03-workflow-state.md#key-findings"),
        ("symbol_or_heading", "unrelated-heading"),
    ),
)
def test_status_evidence_reviews_reject_inexact_documentation_evidence_bindings(
    tmp_path: Path, field: str, replacement: str
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    binding = documentation_summary(catalog)["documentation_authority"]["evidence_bindings"][0]
    binding[field] = replacement
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_BINDING_INVALID" in codes, field


def test_status_evidence_reviews_reject_literal_current_with_stale_declaration_hash(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    relationships_path = root / "reality/relationships.yaml"
    relationships = yaml.safe_load(relationships_path.read_text(encoding="utf-8"))
    record = next(item for item in relationships["items"] if item["id"] == "REL-1")
    record["definition"] = "Changed after the documentation review."
    write_yaml(relationships_path, relationships)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_DECLARATION_HASH_MISMATCH" in codes


def test_status_evidence_reviews_reject_declaration_path_absent_from_active_snapshot_chain(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    for snapshot in [evidence["snapshot"], *evidence["snapshots"]]:
        snapshot["files"] = [
            item
            for item in snapshot["files"]
            if item["path"] != "research/ui-foundation/reality/relationships.yaml"
        ]
    write_yaml(evidence_path, evidence)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_DECLARATION_PATH_NOT_ACTIVE" in codes


def test_status_evidence_reviews_reject_declaration_path_only_in_unrelated_historical_snapshot(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    for snapshot in [evidence["snapshot"], *evidence["snapshots"]]:
        snapshot["files"] = [
            item
            for item in snapshot["files"]
            if item["path"] != "research/ui-foundation/reality/relationships.yaml"
        ]
    evidence["snapshots"].append(
        {
            "id": "unrelated-historical-snapshot",
            "parent_snapshot_id": None,
            "files": [
                {
                    "path": "research/ui-foundation/reality/relationships.yaml",
                    "sha256": "0" * 64,
                    "audited_at": "2026-07-25T00:00:00Z",
                }
            ],
        }
    )
    write_yaml(evidence_path, evidence)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_DECLARATION_PATH_NOT_ACTIVE" in codes


def test_status_evidence_reviews_reject_stale_full_file_hash_for_current_declaration(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    relationships_path = root / "reality/relationships.yaml"
    relationships = yaml.safe_load(relationships_path.read_text(encoding="utf-8"))
    relationships["schema_version"] = "changed-after-review"
    write_yaml(relationships_path, relationships)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_DECLARATION_FILE_HASH_MISMATCH" in codes


def test_status_evidence_reviews_reject_fake_documentation_contradiction_claim(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = documentation_summary(catalog, "REL-4")
    summary["compatible_status"] = "conflicting"
    summary["combined_verdict"] = "contradicts"
    summary["contradiction_clauses"] = {
        "CON-1#claim-0": "A fabricated claim that is not canonical.",
        "CON-1#claim-1": "Another fabricated competing claim.",
    }
    relationships_path = root / "reality/relationships.yaml"
    relationships = yaml.safe_load(relationships_path.read_text(encoding="utf-8"))
    record = next(item for item in relationships["items"] if item["id"] == "REL-4")
    record["documentation_status"] = "conflicting"
    write_yaml(relationships_path, relationships)
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_CONTRADICTION_INVALID" in codes


def test_status_evidence_reviews_rejects_documented_without_current_evidence(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(
        value
        for value in summaries
        if value["dimension"] == "documentation" and value["compatible_status"] == "documented"
    )
    summary["freshness_state"] = "stale"
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_STATUS_INVALID" in codes


def test_status_evidence_reviews_rejects_stale_without_freshness_boundary_and_age(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(value for value in summaries if value["dimension"] == "documentation")
    summary["compatible_status"] = "stale"
    summary["freshness_boundary"] = ""
    summary["evidence_age"] = ""
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_STATUS_INVALID" in codes


def test_status_evidence_reviews_rejects_undocumented_without_missing_boundary(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(value for value in summaries if value["dimension"] == "documentation")
    summary["compatible_status"] = "undocumented"
    summary["documentation_evidence_ids"] = []
    summary["missing_documentation_boundary"] = ""
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_DOCUMENTATION_STATUS_INVALID" in codes


def test_status_evidence_reviews_rejects_capability_unknown_without_boundary(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(
        value
        for value in summaries
        if value["dimension"] == "capability" and value["compatible_status"] == "unknown"
    )
    summary["unresolved_boundary"] = ""
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in codes


def test_status_evidence_reviews_rejects_capability_gap_without_resolving_authority(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(
        value
        for value in summaries
        if value["dimension"] == "capability" and value["compatible_status"] == "gap"
    )
    summary["gap_contract_ids"] = []
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID" in codes


def test_status_evidence_reviews_rejects_observed_without_observation_evidence(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(value for value in summaries if value["dimension"] == "epistemic")
    summary["observation_evidence_ids"] = []
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in codes


def test_epistemic_binding_must_belong_to_summary_and_canonical_record(tmp_path: Path) -> None:
    for case in ("summary", "record"):
        root = copy_foundation_with_source(tmp_path / case)
        catalog = status_review_catalog(root)
        summary = epistemic_summary(catalog)
        evidence_id = summary["epistemic_authority_bindings"][0]["evidence_id"]
        if case == "summary":
            summary["evidence_ids"].remove(evidence_id)
        else:
            record_path, record = canonical_status_record(root, summary["record_id"])
            record["evidence_ids"].remove(evidence_id)
            document = yaml.safe_load(record_path.read_text(encoding="utf-8"))
            if document.get("id") == summary["record_id"]:
                document = record
            else:
                next(item for item in document["items"] if item["id"] == summary["record_id"])[
                    "evidence_ids"
                ].remove(evidence_id)
            write_yaml(record_path, document)
            assert (
                evidence_id
                not in canonical_status_record(root, summary["record_id"])[1]["evidence_ids"]
            )
        write_status_review_catalog(root, catalog)

        assert "STATUS_EVIDENCE_EPISTEMIC_BINDING_INVALID" in validate_status_reviews(root)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("expected_source_kind", "implementation"),
        ("expected_provenance_role", "direct"),
        ("path", "src/orchestrator/config/enums.py"),
        ("symbol_or_heading", "unrelated_symbol"),
    ),
)
def test_epistemic_binding_rejects_inexact_evidence_metadata(
    tmp_path: Path, field: str, replacement: str
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    epistemic_summary(catalog)["epistemic_authority_bindings"][0][field] = replacement
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_BINDING_INVALID" in validate_status_reviews(root), field


def test_epistemic_observation_rejects_globally_valid_unrelated_evidence(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    unrelated = next(item for item in evidence["items"] if item["id"] == "EVD-50")
    summary["evidence_ids"] = [unrelated["id"]]
    summary["observation_evidence_ids"] = [unrelated["id"]]
    summary["epistemic_authority_bindings"] = [
        {
            "evidence_id": unrelated["id"],
            "expected_source_kind": unrelated["source_kind"],
            "expected_provenance_role": unrelated["provenance_role"],
            "path": unrelated["path"],
            "symbol_or_heading": unrelated["symbol"],
            "proposition_role": "observation of REL-1",
        }
    ]
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_BINDING_INVALID" in validate_status_reviews(root)


def test_epistemic_observed_requires_typed_observation_binding(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    epistemic_summary(catalog)["epistemic_authority_bindings"] = []
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in validate_status_reviews(root)


def test_epistemic_direct_evidence_rejects_falsely_copied_missing_symbol(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence_by_id = {item["id"]: item for item in evidence["items"]}
    summary = next(
        item
        for item in catalog["dimension_reviews"]
        if item["dimension"] == "epistemic"
        and any(
            evidence_by_id[binding["evidence_id"]].get("provenance_role") == "direct"
            for binding in item["epistemic_authority_bindings"]
        )
    )
    binding = next(
        binding
        for binding in summary["epistemic_authority_bindings"]
        if evidence_by_id[binding["evidence_id"]].get("provenance_role") == "direct"
    )
    binding["symbol_or_heading"] = "symbol_that_does_not_exist"
    evidence_by_id[binding["evidence_id"]]["symbol"] = "symbol_that_does_not_exist"
    write_yaml(evidence_path, evidence)
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_BINDING_INVALID" in validate_status_reviews(root)


def test_epistemic_synthesis_evidence_requires_resolvable_heading(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    binding = summary["epistemic_authority_bindings"][0]
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    record = next(item for item in evidence["items"] if item["id"] == binding["evidence_id"])
    report_path = record["path"].partition("#")[0]
    record["path"] = f"{report_path}#heading-that-does-not-exist"
    binding["path"] = record["path"]
    write_yaml(evidence_path, evidence)
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_BINDING_INVALID" in validate_status_reviews(root)


def test_epistemic_derived_requires_active_reciprocal_derivation(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    summary["compatible_status"] = "deterministically-derived"
    summary["derivation_contract_ids"] = ["DRV-999"]
    set_canonical_epistemic_status(root, summary["record_id"], "deterministically-derived")
    write_yaml(root / "capabilities/derivations/drv-999.yaml", {"id": "DRV-999"})
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in validate_status_reviews(root)


def test_epistemic_proposed_rejects_untyped_global_evidence_authority(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    summary["compatible_status"] = "proposed"
    summary["combined_verdict"] = "proposed"
    summary["proposal_authority_ids"] = list(summary["evidence_ids"])
    set_canonical_epistemic_status(root, summary["record_id"], "proposed")
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in validate_status_reviews(root)


def test_epistemic_inferred_rejects_untyped_rule_with_global_evidence(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    summary["compatible_status"] = "inferred"
    summary["combined_verdict"] = "partially-proves"
    summary["inference_rule"] = "A free-form string is not a typed inference rule."
    summary["inference_evidence_ids"] = list(summary["evidence_ids"])
    set_canonical_epistemic_status(root, summary["record_id"], "inferred")
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in validate_status_reviews(root)


def test_epistemic_operator_assertion_requires_operator_identity(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    binding = summary["epistemic_authority_bindings"][0]
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    record = next(item for item in evidence["items"] if item["id"] == binding["evidence_id"])
    record["source_kind"] = "operator-assertion"
    binding["expected_source_kind"] = "operator-assertion"
    binding["proposition_role"] = "operator assertion"
    summary["compatible_status"] = "operator-asserted"
    summary["assertion_evidence_ids"] = list(summary["evidence_ids"])
    set_canonical_epistemic_status(root, summary["record_id"], "operator-asserted")
    write_yaml(evidence_path, evidence)
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in validate_status_reviews(root)


def test_epistemic_unknown_rejects_proving_observation_binding(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    summary["compatible_status"] = "unknown"
    summary["combined_verdict"] = "unknown"
    summary["unresolved_boundary"] = "REL-1 remains explicitly unresolved."
    set_canonical_epistemic_status(root, summary["record_id"], "unknown")
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in validate_status_reviews(root)


def test_epistemic_narrative_must_identify_the_record(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summary = epistemic_summary(catalog)
    summary["record_proposition"] = "A sufficiently long but generic proposition."
    summary["observed_fact"] = "A sufficiently long but generic observed fact."
    summary["boundary"] = "A sufficiently long but generic evidence boundary."
    summary["rationale"] = "A sufficiently long but generic review rationale."
    write_status_review_catalog(root, catalog)

    assert "STATUS_EVIDENCE_EPISTEMIC_NARRATIVE_GENERIC" in validate_status_reviews(root)


@pytest.mark.parametrize(
    ("status", "verdict"),
    (
        ("deterministically-derived", "proves"),
        ("inferred", "partially-proves"),
        ("operator-asserted", "proves"),
    ),
)
def test_status_evidence_reviews_rejects_derived_inferred_and_operator_statuses_without_proof(
    tmp_path: Path, status: str, verdict: str
) -> None:
    root = copy_foundation_with_source(tmp_path)
    catalog = status_review_catalog(root)
    summaries = catalog["dimension_reviews"]
    assert isinstance(summaries, list)
    summary = next(value for value in summaries if value["dimension"] == "epistemic")
    summary["compatible_status"] = status
    summary["combined_verdict"] = verdict
    summary["derivation_contract_ids"] = []
    summary["inference_rule"] = ""
    summary["inference_evidence_ids"] = []
    summary["assertion_evidence_ids"] = []
    write_status_review_catalog(root, catalog)

    codes = validate_status_reviews(root)

    assert "STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID" in codes


def test_absent_unknown_action_does_not_require_unallocated_gap_demand(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    action = yaml.safe_load(
        (root / "reality/actions/act-58-agent-test-fix-job-gap.yaml").read_text(encoding="utf-8")
    )
    assert action["capability_status"] == "unknown"
    assert action["source_demand_ids"] == []

    result = run_validator(root)

    assert "ABSENT_INTERVENTION_INVALID" not in issue_codes(result)
    assert "ABSENT_INTERVENTION_REQUIREMENT_MISSING" not in issue_codes(result)


def test_status_scope_rejects_missing_record(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    items = status_scope_items(root)
    write_status_scope(root, items[1:])

    result = run_validator(root)

    assert "STATUS_SCOPE_MISSING" in issue_codes(result)


def test_status_scope_rejects_extra_record(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    write_status_scope(root)
    relationships_path = root / "reality/relationships.yaml"
    relationships = yaml.safe_load(relationships_path.read_text(encoding="utf-8"))
    extra = dict(relationships["items"][0])
    extra["id"] = "REL-999"
    relationships["items"].append(extra)
    write_yaml(relationships_path, relationships)

    result = run_validator(root)

    assert "STATUS_SCOPE_EXTRA" in issue_codes(result)


def test_status_scope_rejects_duplicate_record(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    items = status_scope_items(root)
    items.append(items[0])
    write_status_scope(root, items)

    result = run_validator(root)

    assert "STATUS_SCOPE_DUPLICATE" in issue_codes(result)


def test_external_mutation_inventory_covers_independent_transport_commands() -> None:
    """Every independently callable omitted mutation has one stable ACT/CMD root."""
    root = REPO_ROOT / "research/ui-foundation"
    ids = yaml.safe_load((root / "catalog/ids.yaml").read_text(encoding="utf-8"))
    authority = yaml.safe_load(
        (root / "catalog/action-authority-surfaces.yaml").read_text(encoding="utf-8")
    )
    actions = {
        value["id"]: value
        for path in (root / "reality/actions").glob("act-*.yaml")
        if (value := yaml.safe_load(path.read_text(encoding="utf-8")))
    }
    ledger = {value["canonical_id"]: value for value in ids["items"] if value["namespace"] == "CMD"}
    expected_routes = {
        "task-start": "src/orchestrator/api/routers/tasks.py::start_task",
        "task-submit": "src/orchestrator/api/routers/tasks.py::submit_task",
        "task-complete-verification": "src/orchestrator/api/routers/tasks.py::complete_verification_endpoint",
        "task-checklist": "src/orchestrator/api/routers/tasks.py::update_checklist_item",
        "task-grade": "src/orchestrator/api/routers/tasks.py::set_grade",
        "clarification-create": "src/orchestrator/api/routers/clarifications.py::create_clarification",
        "requirement-escalation": "src/orchestrator/api/routers/tasks.py::escalate_requirement",
        "review-file-revert": "src/orchestrator/api/routers/review.py::revert_file_endpoint",
        "public-mcp-task-checklist": "src/orchestrator/api/mcp/tools.py::ToolHandler._update_checklist",
        "public-mcp-task-submit": "src/orchestrator/api/mcp/tools.py::ToolHandler._submit",
        "public-mcp-task-grade": "src/orchestrator/api/mcp/tools.py::ToolHandler._set_grade",
        "public-mcp-clarification-create": "src/orchestrator/api/mcp/tools.py::ToolHandler._request_clarification",
        "public-mcp-requirement-escalation": "src/orchestrator/api/mcp/tools.py::ToolHandler._escalate_requirement",
        "local-cli-db-restore-backup": "src/orchestrator/cli/db.py::restore_backup_cmd",
        "local-cli-db-rebuild-projections": "src/orchestrator/cli/db.py::rebuild_projections_cmd",
    }
    inventory = {item["route_family"]: item for item in authority["route_inventory"]}
    assert {
        family: item["implementation_locator"] for family, item in inventory.items()
    } == expected_routes
    authority_by_action = {item["action_id"]: item for item in authority["items"]}
    assert all(
        item["action_id"] in actions
        and actions[item["action_id"]]["command_id"] == item["command_id"]
        and item["command_id"] in ledger
        and authority_by_action[item["action_id"]]["command_id"] == item["command_id"]
        and authority_by_action[item["action_id"]]["surface_kind"]
        == "independent-external-mutation"
        and authority_by_action[item["action_id"]]["q5_required"] is True
        for item in inventory.values()
    )


def test_status_scope_rejects_wrong_declaration_path(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    items = status_scope_items(root)
    items[0]["path"] = "reality/state-model.yaml"
    write_status_scope(root, items)

    result = run_validator(root)

    assert "STATUS_SCOPE_WRONG_PATH" in issue_codes(result)


def test_status_scope_rejects_reactivated_sta_28(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    items = status_scope_items(root)
    items.append({"id": "STA-28", "path": "reality/state-model.yaml"})
    write_status_scope(root, items)

    result = run_validator(root)

    assert "STATUS_SCOPE_REACTIVATED" in issue_codes(result)


def test_implementation_locator_grammar_resolves_python_and_yaml_ids(tmp_path: Path) -> None:
    validator = load_validator()
    python_path = tmp_path / "src/example.py"
    python_path.parent.mkdir(parents=True)
    python_path.write_text(
        "from enum import Enum\n\n"
        "def carrier():\n    return None\n\n"
        "ALIAS = carrier\n\n"
        "class Holder:\n    member: str\n\n"
        "class Kind(Enum):\n    ACTIVE = 'active'\n",
        encoding="utf-8",
    )
    yaml_path = tmp_path / "config/example.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text("items:\n- id: ITEM-1\n  kind: active\n", encoding="utf-8")
    hashes = {
        "src/example.py": hashlib.sha256(python_path.read_bytes()).hexdigest(),
        "config/example.yaml": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }

    for locator in (
        "src/example.py::carrier",
        "src/example.py::ALIAS",
        "src/example.py::Holder.member",
        "src/example.py::Kind.ACTIVE",
        "config/example.yaml::ITEM-1",
    ):
        assert validator._implementation_locator_is_snapshot_resolvable(locator, tmp_path, hashes)
    for locator in (
        "Exact source: src/example.py::carrier.",
        "src/example.py::missing",
        "config/example.yaml::kind",
    ):
        assert not validator._implementation_locator_is_snapshot_resolvable(
            locator, tmp_path, hashes
        )


def test_implementation_locators_do_not_allow_one_good_to_rescue_bad(tmp_path: Path) -> None:
    validator = load_validator()
    source = tmp_path / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("def carrier():\n    return None\n", encoding="utf-8")
    hashes = {"src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()}

    assert not validator._implementation_locators_are_snapshot_resolvable(
        ["src/example.py::carrier", "src/example.py::missing"], tmp_path, hashes
    )


def test_yaml_implementation_locator_id_must_exist_in_named_file(tmp_path: Path) -> None:
    validator = load_validator()
    first = tmp_path / "config/first.yaml"
    second = tmp_path / "config/second.yaml"
    first.parent.mkdir(parents=True)
    first.write_text("id: ITEM-1\n", encoding="utf-8")
    second.write_text("id: ITEM-2\n", encoding="utf-8")
    hashes = {
        "config/first.yaml": hashlib.sha256(first.read_bytes()).hexdigest(),
        "config/second.yaml": hashlib.sha256(second.read_bytes()).hexdigest(),
    }

    assert not validator._implementation_locator_is_snapshot_resolvable(
        "config/second.yaml::ITEM-1", tmp_path, hashes
    )


def test_status_scope_rejects_missing_and_generic_status_basis(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    write_status_scope(root)
    action_path = root / "reality/actions/act-1-runner-model-profile-defaults-save.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    del action["status_basis"]["test"]
    action["status_basis"]["implementation"] = "  Carrier   exists.  "
    write_yaml(action_path, action)

    result = run_validator(root)

    assert "STATUS_BASIS_MISSING" in issue_codes(result)
    assert "STATUS_BASIS_GENERIC" in issue_codes(result)


def test_absent_action_rejects_locator_and_executable_flag(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    write_status_scope(root)
    action_path = root / "reality/actions/act-1-runner-model-profile-defaults-save.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["implementation_status"] = "absent"
    write_yaml(action_path, action)

    result = run_validator(root)

    assert "ABSENT_IMPLEMENTATION_LOCATORS_NONEMPTY" in issue_codes(result)
    assert "ABSENT_ACTION_EXECUTABLE" in issue_codes(result)


def test_unexercised_action_rejects_test_locator(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    write_status_scope(root)
    action_path = root / "reality/actions/act-1-runner-model-profile-defaults-save.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["test_status"] = "unexercised"
    write_yaml(action_path, action)

    result = run_validator(root)

    assert "NONEXERCISED_TEST_LOCATORS_NONEMPTY" in issue_codes(result)


def test_conflicting_action_requires_reciprocal_unresolved_issue(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    write_status_scope(root)
    action_path = root / "reality/actions/act-1-runner-model-profile-defaults-save.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["documentation_status"] = "conflicting"
    action["conflict_ids"] = []
    action["question_ids"] = []
    write_yaml(action_path, action)

    result = run_validator(root)

    assert "CONFLICTING_STATUS_RECIPROCAL_ISSUE_MISSING" in issue_codes(result)


def test_committed_status_adjudication_matches_exact_evidence_outputs() -> None:
    root = REPO_ROOT / "research/ui-foundation"
    records: dict[str, dict[str, object]] = {}
    for relative in (
        "reality/domain-model.yaml",
        "reality/relationships.yaml",
        "reality/state-model.yaml",
        "reality/evidence/inventory.yaml",
        "catalog/invariants.yaml",
    ):
        document = yaml.safe_load((root / relative).read_text(encoding="utf-8"))
        records.update({item["id"]: item for item in document["items"]})
    for path in sorted((root / "reality/actions").glob("act-*.yaml")):
        item = yaml.safe_load(path.read_text(encoding="utf-8"))
        records[item["id"]] = item

    expected_test_statuses = {
        "REL": {"exercised": 13, "unexercised": 22},
        "STA": {"exercised": 57, "unexercised": 17},
        "ACT": {"exercised": 56, "unexercised": 30},
        "EVI": {"exercised": 2, "unexercised": 7},
        "INV": {"exercised": 6},
    }
    family_ids = {
        "REL": {f"REL-{number}" for number in range(1, 36)},
        "STA": {f"STA-{number}" for number in range(1, 76)} - {"STA-28"},
        "ACT": {f"ACT-{number}" for number in range(1, 87)},
        "EVI": {f"EVI-{number}" for number in range(1, 10)},
        "INV": {f"INV-{number}" for number in range(2, 8)},
    }
    for family, identifiers in family_ids.items():
        distribution: dict[str, int] = {}
        for identifier in identifiers:
            status = str(records[identifier]["test_status"])
            distribution[status] = distribution.get(status, 0) + 1
        assert distribution == expected_test_statuses[family]

    representatives = {
        "REL-2": "tests/integration/test_database.py::test_crud_with_steps_and_tasks",
        "STA-17": "tests/unit/test_graph_commands.py::test_lifecycle_legal_transitions",
        "ACT-10": "tests/integration/test_graph_decisions_api.py::test_record_approval_decision_is_durable_and_releases_waiting_successor",
        "ACT-11": "tests/integration/test_graph_fr08_acceptance.py::test_fr08_authority_denial_and_rejection_readbacks",
        "ACT-13": "tests/integration/test_graph_api.py::test_operator_graph_patch_endpoint_accepts_human_patch",
        "ACT-44": "tests/integration/test_graph_fr08_acceptance.py::test_fr08_authority_denial_and_rejection_readbacks",
        "EVI-8": "tests/integration/test_graph_decisions_api.py::test_record_approval_decision_is_durable_and_releases_waiting_successor",
        "INV-2": "tests/integration/test_graph_dynamic_e2e.py::test_dynamic_run_does_not_complete_while_final_invariant_check_fails",
    }
    for identifier, locator in representatives.items():
        assert locator in (
            records[identifier]["test_locators"] + records[identifier]["bounded_test_locators"]
        )

    exact_locators = {
        locator
        for identifiers in family_ids.values()
        for identifier in identifiers
        for field in ("test_locators", "bounded_test_locators")
        for locator in records[identifier].get(field, [])
    }
    assert len(exact_locators) == 119


def test_exercised_status_rejects_empty_exact_test_locators(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    state_path = root / "reality/state-model.yaml"
    state_model = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    next(item for item in state_model["items"] if item["id"] == "STA-17")["test_locators"] = []
    write_yaml(state_path, state_model)

    result = run_validator(root)

    assert "EXERCISED_TEST_LOCATORS_EMPTY" in issue_codes(result)


def test_all_family_unexercised_rejects_resolvable_exact_test_basis(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    relationships_path = root / "reality/relationships.yaml"
    relationships = yaml.safe_load(relationships_path.read_text(encoding="utf-8"))
    for item in relationships["items"]:
        item["test_status"] = "unexercised"
    write_yaml(relationships_path, relationships)

    result = run_validator(root)

    assert "STATUS_FAMILY_MECHANICAL_UNEXERCISED" in issue_codes(result)


def test_all_actions_unexercised_rejects_resolvable_exact_test_locators(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    for path in (root / "reality/actions").glob("act-*.yaml"):
        action = yaml.safe_load(path.read_text(encoding="utf-8"))
        action["test_status"] = "unexercised"
        write_yaml(path, action)

    result = run_validator(root)

    assert "STATUS_FAMILY_MECHANICAL_UNEXERCISED" in issue_codes(result)


def test_entity_namespace_rejects_non_entity_and_requires_retired_allocation_history(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/ids.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "namespace": "ENT",
                    "canonical_id": "ENT-01",
                    "provisional_key": "taxonomy",
                    "title": "Taxonomy",
                    "status": "active",
                }
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "ENT-01",
                    identity="none",
                    ownership="none",
                    persistence="none",
                    lifecycle="none",
                    status_basis=status_basis(),
                )
            ],
        },
    )

    result = run_validator(root)

    assert "ENTITY_LIFECYCLE_FIELDS_INVALID" in issue_codes(result)
    assert "ENTITY_ALLOCATION_RETIREMENT_MISSING" in issue_codes(result)


def test_validator_rejects_incomplete_derived_claim(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CAP-01",
                    "capability_status": "derived",
                    "derivation_id": "DRV-01",
                }
            ],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {"id": "DRV-01", "inputs": ["CAP-02"], "output_type": "string"},
    )
    result = run_validator(root)
    assert result.returncode == 1
    assert "DERIVATION_UNKNOWN_BEHAVIOR_MISSING" in result.stderr


def test_validator_rejects_current_claim_without_implementation_evidence(
    tmp_path: Path,
) -> None:
    root = write_minimal_foundation(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-01",
                    implementation_status="present",
                    test_status="exercised",
                    documentation_status="documented",
                    capability_status="current",
                    evidence_ids=["EVD-01"],
                )
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "product-documentation"}],
        },
    )
    result = run_validator(root)
    assert result.returncode == 1
    assert "CURRENT_IMPLEMENTATION_EVIDENCE_MISSING" in result.stderr


def test_report_validator_requires_handoff_sections(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# Report\n\n## Purpose\nOnly one section.\n", encoding="utf-8")
    result = run_report_validator(report)
    assert result.returncode == 1
    assert "REPORT_SECTION_MISSING" in result.stderr


def test_valid_phase_zero_package_succeeds(tmp_path: Path) -> None:
    result = run_validator(write_valid_phase_zero(tmp_path), phase=0)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_graph_node_state_contract_rejects_pending_alias_and_missing_node_states(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    state_path = root / "reality/state-model.yaml"
    state_model = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    for item in state_model["items"]:
        if item["id"] == "STA-71":
            item["id"] = "STA-28"
            item["title"] = "Graph node pending"
    state_model["items"] = [
        item for item in state_model["items"] if item["id"] not in {"STA-72", "STA-73"}
    ]
    state_path.write_text(yaml.safe_dump(state_model, sort_keys=False), encoding="utf-8")

    validator = load_validator()
    issues = validator.validate_graph_node_state_contract(root)

    assert {"GRAPH_NODE_STATE_ALIAS", "GRAPH_NODE_STATE_COVERAGE_MISMATCH"} <= {
        issue.code for issue in issues
    }


def test_graph_node_state_contract_rejects_inactive_links_without_ledger_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    ids_path = root / "catalog/ids.yaml"
    ids = yaml.safe_load(ids_path.read_text(encoding="utf-8"))
    allocation = next(item for item in ids["items"] if item["canonical_id"] == "STA-28")
    allocation["status"] = "rejected"
    allocation.pop("history", None)
    ids_path.write_text(yaml.safe_dump(ids, sort_keys=False), encoding="utf-8")
    action_path = root / "reality/actions/act-41-graph-approved-approval-node-outcome.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["transition"] = {"from_state_id": "STA-28", "to_state_id": "STA-33"}
    action_path.write_text(yaml.safe_dump(action, sort_keys=False), encoding="utf-8")

    validator = load_validator()
    issues = validator.validate_graph_node_state_contract(root)

    codes = {issue.code for issue in issues}
    assert "RETIRED_SEMANTIC_ID_HISTORY_MISSING" in codes
    assert "INACTIVE_STATE_REFERENCE" in codes


def test_phase_one_snapshot_is_checked_against_its_checked_in_immutable_baseline(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["snapshot"]["files"][0]["sha256"] = "0" * 64
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")

    result = run_validator(root)

    assert "PHASE_ONE_SNAPSHOT_IMMUTABLE_MISMATCH" in issue_codes(result)


def test_snapshot_lineage_registry_is_required_for_every_evidence_snapshot(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    (root / "catalog/snapshot-lineage.yaml").unlink()

    result = run_validator(root)

    assert "SNAPSHOT_LINEAGE_MISSING" in issue_codes(result)


def snapshot_lineage(root: Path) -> dict[str, object]:
    return yaml.safe_load((root / "catalog/snapshot-lineage.yaml").read_text(encoding="utf-8"))


def test_snapshot_lineage_rejects_mutated_registered_active_snapshot(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["snapshots"][-1]["files"][0]["sha256"] = "0" * 64
    write_yaml(evidence_path, evidence)

    assert "SNAPSHOT_LINEAGE_SNAPSHOT_MISMATCH" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_removed_historical_snapshot(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"] = lineage["entries"][1:]
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_SET_MISMATCH" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_duplicate_id(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"].append(dict(lineage["entries"][-1]))
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_ID_DUPLICATE" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_unknown_parent(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"][-1]["parent_snapshot_id"] = "snapshot-unknown"
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_PARENT_UNKNOWN" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_invented_parent_for_canonical_root(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    phase_zero = next(
        entry
        for entry in lineage["entries"]
        if entry["snapshot_id"] == "snapshot-2026-07-23-phase-0"
    )
    phase_zero["parent_snapshot_id"] = "snapshot-2026-07-24-phase-1"
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_REPARENTED" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_null_parent_for_canonical_child(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    child = next(
        entry
        for entry in lineage["entries"]
        if entry["snapshot_id"] == "snapshot-2026-07-24-task-15-adjudication"
    )
    child["parent_snapshot_id"] = None
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_REPARENTED" in issue_codes(run_validator(root))


def test_effective_snapshot_does_not_inherit_detached_historical_root() -> None:
    validator = load_validator()
    evidence = {
        "snapshot": {
            "id": "snapshot-2026-07-24-phase-1",
            "files": [{"path": "phase1.py", "sha256": "1" * 64, "audited_at": "now"}],
        },
        "snapshots": [
            {
                "id": "snapshot-2026-07-23-phase-0",
                "parent_snapshot_id": None,
                "files": [{"path": "phase0.py", "sha256": "0" * 64, "audited_at": "now"}],
            },
            {
                "id": "active",
                "parent_snapshot_id": "snapshot-2026-07-24-phase-1",
                "files": [{"path": "active.py", "sha256": "a" * 64, "audited_at": "now"}],
            },
        ],
        "active_snapshot_id": "active",
    }

    active = validator._active_snapshot(evidence)

    assert active is not None
    assert {item["path"] for item in active["files"]} == {"phase1.py", "active.py"}


def test_only_research_snapshot_recorder_path_exists() -> None:
    assert SNAPSHOT_RECORDER.is_file()
    assert not (REPO_ROOT / "tools/record_snapshot_lineage.py").exists()


def test_snapshot_lineage_rejects_cycle(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"][0]["parent_snapshot_id"] = lineage["entries"][-1]["snapshot_id"]
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_CYCLE" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_active_non_leaf(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    for entry in lineage["entries"]:
        entry["status"] = (
            "active" if entry["snapshot_id"] == "snapshot-2026-07-24-phase-1" else "historical"
        )
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_ACTIVE_NONLEAF" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_reparented_snapshot(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"][-1]["parent_snapshot_id"] = "snapshot-2026-07-23-phase-0"
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_REPARENTED" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_reordered_entries(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"][1], lineage["entries"][2] = lineage["entries"][2], lineage["entries"][1]
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_PREDECESSOR_INVALID" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_bad_predecessor_digest(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"][-1]["predecessor_lineage_digest"] = "0" * 64
    write_yaml(lineage_path, lineage)

    assert "SNAPSHOT_LINEAGE_PREDECESSOR_INVALID" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_duplicate_file_paths_with_same_hash(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["snapshots"][-1]["files"].append(dict(evidence["snapshots"][-1]["files"][0]))
    write_yaml(evidence_path, evidence)

    assert "SNAPSHOT_FILE_PATH_DUPLICATE" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_duplicate_file_paths_with_different_hash(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    duplicate = dict(evidence["snapshots"][-1]["files"][0])
    duplicate["sha256"] = "0" * 64
    evidence["snapshots"][-1]["files"].append(duplicate)
    write_yaml(evidence_path, evidence)

    assert "SNAPSHOT_FILE_PATH_CONFLICT" in issue_codes(run_validator(root))


def test_snapshot_lineage_rejects_missing_active_target(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["active_snapshot_id"] = "snapshot-unknown"
    write_yaml(evidence_path, evidence)

    assert "SNAPSHOT_LINEAGE_ACTIVE_TARGET_MISSING" in issue_codes(run_validator(root))


def test_effective_snapshot_overlays_delta_and_tombstone_only_from_parent_chain(
    tmp_path: Path,
) -> None:
    validator = load_validator()
    evidence = {
        "snapshot": {
            "id": "root",
            "files": [{"path": "one.py", "sha256": "1" * 64, "audited_at": "now"}],
        },
        "snapshots": [
            {
                "id": "unrelated",
                "files": [{"path": "other.py", "sha256": "2" * 64, "audited_at": "now"}],
            },
            {
                "id": "child",
                "parent_snapshot_id": "root",
                "files": [
                    {"path": "one.py", "sha256": "3" * 64, "audited_at": "now"},
                    {"path": "two.py", "sha256": "4" * 64, "audited_at": "now"},
                ],
            },
            {
                "id": "leaf",
                "parent_snapshot_id": "child",
                "files": [{"path": "two.py", "tombstone": True}],
            },
        ],
        "active_snapshot_id": "leaf",
    }

    active = validator._active_snapshot(evidence)

    assert active is not None
    assert {item["path"]: item["sha256"] for item in active["files"]} == {"one.py": "3" * 64}


def test_snapshot_resolver_accepts_exact_legacy_alias_and_resolves_effective_snapshot() -> None:
    resolver = load_snapshot_resolver()
    root = {
        "id": "root",
        "files": [{"path": "one.py", "sha256": "1" * 64, "audited_at": "now"}],
    }
    evidence = {
        "snapshot": root,
        "snapshots": [
            dict(root),
            {
                "id": "leaf",
                "parent_snapshot_id": "root",
                "files": [{"path": "two.py", "sha256": "2" * 64, "audited_at": "now"}],
            },
        ],
        "active_snapshot_id": "leaf",
    }

    snapshots = resolver.snapshots_from_evidence(evidence)
    active = resolver.resolve_effective_snapshot(evidence)

    assert [snapshot["id"] for snapshot in snapshots] == ["root", "leaf"]
    assert {item["path"] for item in active["files"]} == {"one.py", "two.py"}


def test_snapshot_resolver_rejects_conflicting_legacy_alias_duplicate() -> None:
    resolver = load_snapshot_resolver()
    evidence = {
        "snapshot": {"id": "root", "files": []},
        "snapshots": [{"id": "root", "files": [{"path": "one.py"}]}],
    }

    with pytest.raises(ValueError, match="SNAPSHOT_ID_DUPLICATE"):
        resolver.snapshots_from_evidence(evidence)


def test_snapshot_resolver_rejects_duplicate_registered_snapshot_id() -> None:
    resolver = load_snapshot_resolver()
    registered = {"id": "root", "files": []}
    evidence = {"snapshot": dict(registered), "snapshots": [registered, dict(registered)]}

    with pytest.raises(ValueError, match="SNAPSHOT_ID_DUPLICATE"):
        resolver.snapshots_from_evidence(evidence)


@pytest.mark.parametrize(
    ("registered", "error"),
    [
        (
            [{"id": "detached", "parent_snapshot_id": "missing", "files": []}],
            "SNAPSHOT_PARENT_UNKNOWN",
        ),
        (
            [
                {"id": "detached-a", "parent_snapshot_id": "detached-b", "files": []},
                {"id": "detached-b", "parent_snapshot_id": "detached-a", "files": []},
            ],
            "SNAPSHOT_PARENT_CYCLE",
        ),
        (
            [{"id": "detached", "files": [{"path": "missing"}]}],
            "SNAPSHOT_FILE_INVALID",
        ),
        (
            [
                {
                    "id": "detached",
                    "parent_snapshot_id": "root",
                    "files": [{"path": "missing", "tombstone": True}],
                }
            ],
            "INVALID_TOMBSTONE:missing",
        ),
    ],
)
def test_snapshot_resolver_validates_detached_registered_branches(
    registered: list[dict[str, object]], error: str
) -> None:
    resolver = load_snapshot_resolver()
    evidence = {
        "snapshot": {"id": "root", "files": []},
        "snapshots": registered,
        "active_snapshot_id": "root",
    }

    with pytest.raises(ValueError, match=error):
        resolver.resolve_effective_snapshot(evidence)


def test_snapshot_resolver_validates_reserved_self_tombstones() -> None:
    resolver = load_snapshot_resolver()
    evidence = {
        "snapshot": {
            "id": "root",
            "files": [
                {
                    "path": "research/ui-foundation/catalog/evidence.yaml",
                    "tombstone": True,
                }
            ],
        }
    }

    with pytest.raises(
        ValueError,
        match="INVALID_TOMBSTONE:research/ui-foundation/catalog/evidence.yaml",
    ):
        resolver.resolve_effective_snapshot(evidence)


def test_effective_snapshot_rejects_unknown_parent_and_cycle(tmp_path: Path) -> None:
    validator = load_validator()
    unknown = {
        "snapshot": {"id": "root", "files": []},
        "snapshots": [{"id": "leaf", "parent_snapshot_id": "missing", "files": []}],
        "active_snapshot_id": "leaf",
    }
    cycle = {
        "snapshot": {"id": "root", "parent_snapshot_id": "leaf", "files": []},
        "snapshots": [{"id": "leaf", "parent_snapshot_id": "root", "files": []}],
        "active_snapshot_id": "leaf",
    }

    assert validator._active_snapshot(unknown) is None
    assert validator._active_snapshot(cycle) is None


@pytest.mark.parametrize("operation", ("path", "remove"))
@pytest.mark.parametrize("self_path", SELF_SNAPSHOT_PATHS)
def test_snapshot_recorder_rejects_self_reference_before_mutation(
    tmp_path: Path, self_path: str, operation: str
) -> None:
    root = write_minimal_foundation(tmp_path)
    before_evidence = (root / "catalog/evidence.yaml").read_bytes()
    before_lineage = (root / "catalog/snapshot-lineage.yaml").read_bytes()
    recorder = load_snapshot_recorder()

    with pytest.raises(ValueError, match="SNAPSHOT_SELF_REFERENCE"):
        recorder.record(
            root,
            "child",
            "2026-07-24T01:00:00Z",
            [self_path] if operation == "path" else [],
            [self_path] if operation == "remove" else [],
        )

    assert (root / "catalog/evidence.yaml").read_bytes() == before_evidence
    assert (root / "catalog/snapshot-lineage.yaml").read_bytes() == before_lineage


def test_validator_ignores_only_legacy_self_records_and_keeps_ordinary_files_strict(
    tmp_path: Path,
) -> None:
    root = write_minimal_foundation(tmp_path)
    add_legacy_self_snapshot_records(root)
    validator = load_validator()
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))

    active = validator._active_snapshot(evidence)

    assert active is not None
    assert {item["path"] for item in active["files"]} == {"source.txt"}

    (tmp_path / "source.txt").write_text("ordinary drift\n", encoding="utf-8")
    package = validator.load_foundation(root)
    issues = validator.validate_source_hashes(package, phase=2)
    stale_paths = {issue.path for issue in issues if issue.code == "SOURCE_HASH_STALE"}

    assert stale_paths == {str(tmp_path / "source.txt")}


def test_snapshot_recorder_appends_child_without_legacy_self_records(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    add_legacy_self_snapshot_records(root)
    source = tmp_path / "source.txt"
    source.write_text("changed\n", encoding="utf-8")
    recorder = load_snapshot_recorder()

    recorder.record(root, "child", "2026-07-24T01:00:00Z", ["source.txt"], [])

    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    active = load_validator()._active_snapshot(evidence)
    assert active is not None
    assert {item["path"] for item in active["files"]} == {"source.txt"}
    assert [item["path"] for item in evidence["snapshots"][-1]["files"]] == ["source.txt"]


def test_snapshot_recorder_appends_one_deterministic_delta_and_refuses_noop(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("changed\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SNAPSHOT_RECORDER),
            "--root",
            str(root),
            "--snapshot-id",
            "child",
            "--audited-at",
            "2026-07-24T01:00:00Z",
            "--path",
            "source.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    lineage = snapshot_lineage(root)
    assert evidence["active_snapshot_id"] == "child"
    assert evidence["snapshots"][-1]["parent_snapshot_id"] == "snapshot-test"
    assert [item["path"] for item in evidence["snapshots"][-1]["files"]] == ["source.txt"]
    assert lineage["entries"][-1]["snapshot_id"] == "child"
    assert lineage["entries"][-1]["parent_snapshot_id"] == "snapshot-test"
    assert lineage["entries"][-1]["status"] == "active"
    repeat = subprocess.run(
        [
            sys.executable,
            str(SNAPSHOT_RECORDER),
            "--root",
            str(root),
            "--snapshot-id",
            "again",
            "--audited-at",
            "2026-07-24T01:00:00Z",
            "--path",
            "source.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert repeat.returncode == 1
    assert "NO_OP_DELTA" in repeat.stderr


def test_snapshot_recorder_hashes_generated_status_manifests_from_final_bytes(
    tmp_path: Path,
) -> None:
    root = write_minimal_foundation(tmp_path)
    dependent_paths = {
        "research/ui-foundation/catalog/status-test-nodes.yaml": {
            "schema_version": "1",
            "active_snapshot_id": "snapshot-test",
            "entries": [{"active_snapshot_id": "snapshot-test"}],
        },
        "research/ui-foundation/catalog/status-evidence-reviews.yaml": {
            "metadata": {"active_snapshot_id": "snapshot-test"},
            "reviews": [],
        },
    }
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    for relative, value in dependent_paths.items():
        path = tmp_path / relative
        write_yaml(path, value)
        evidence["snapshot"]["files"].append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "audited_at": "2026-07-24T00:00:00Z",
            }
        )
    snapshot_digest = hashlib.sha256(
        json.dumps(evidence["snapshot"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
    (root / "catalog/phase-1-snapshot.sha256").write_text(f"{snapshot_digest}\n", encoding="utf-8")
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"][0]["snapshot_digest"] = snapshot_digest
    lineage["entries"][0]["lineage_entry_digest"] = hashlib.sha256(
        json.dumps(
            {
                key: value
                for key, value in lineage["entries"][0].items()
                if key != "lineage_entry_digest"
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    write_yaml(lineage_path, lineage)

    (tmp_path / "source.txt").write_text("changed\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SNAPSHOT_RECORDER),
            "--root",
            str(root),
            "--snapshot-id",
            "child",
            "--audited-at",
            "2026-07-24T01:00:00Z",
            "--path",
            "source.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    active = load_validator()._active_snapshot(evidence)
    assert active is not None
    effective_hashes = {item["path"]: item["sha256"] for item in active["files"]}
    for relative in dependent_paths:
        assert (
            effective_hashes[relative]
            == hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
        )
    child_files = evidence["snapshots"][-1]["files"]
    assert {item["path"] for item in child_files} == {
        "source.txt",
        *dependent_paths,
    }
    assert len(evidence["snapshots"]) == 1
    assert len(snapshot_lineage(root)["entries"]) == 2


def test_snapshot_recorder_transforms_declared_existing_manifest_drift(
    tmp_path: Path,
) -> None:
    root = write_minimal_foundation(tmp_path)
    status_path = root / "catalog/status-test-nodes.yaml"
    relative = "research/ui-foundation/catalog/status-test-nodes.yaml"
    write_yaml(
        status_path,
        {
            "schema_version": "1",
            "active_snapshot_id": "snapshot-test",
            "reviewer_note": "original generated bytes",
            "entries": [{"active_snapshot_id": "snapshot-test"}],
        },
    )
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["snapshot"]["files"].append(
        {
            "path": relative,
            "sha256": hashlib.sha256(status_path.read_bytes()).hexdigest(),
            "audited_at": "2026-07-24T00:00:00Z",
        }
    )
    write_yaml(
        status_path,
        {
            "schema_version": "1",
            "active_snapshot_id": "snapshot-test",
            "reviewer_note": "authorized non-ID change",
            "entries": [{"active_snapshot_id": "snapshot-test"}],
        },
    )
    snapshot_digest = hashlib.sha256(
        json.dumps(evidence["snapshot"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    lineage = snapshot_lineage(root)
    lineage["entries"][0]["snapshot_digest"] = snapshot_digest
    lineage["entries"][0]["lineage_entry_digest"] = hashlib.sha256(
        json.dumps(
            {
                key: value
                for key, value in lineage["entries"][0].items()
                if key != "lineage_entry_digest"
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    write_yaml(lineage_path, lineage)

    result = subprocess.run(
        [
            sys.executable,
            str(SNAPSHOT_RECORDER),
            "--root",
            str(root),
            "--snapshot-id",
            "child",
            "--audited-at",
            "2026-07-24T01:00:00Z",
            "--path",
            relative,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    child_status = yaml.safe_load(status_path.read_text(encoding="utf-8"))
    assert child_status["active_snapshot_id"] == "child"
    assert child_status["entries"] == [{"active_snapshot_id": "child"}]
    assert child_status["reviewer_note"] == "authorized non-ID change"
    active = load_validator()._active_snapshot(
        yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    )
    assert active is not None
    status_record = next(item for item in active["files"] if item["path"] == relative)
    assert status_record["sha256"] == hashlib.sha256(status_path.read_bytes()).hexdigest()


def test_snapshot_recorder_rejects_tampered_generated_manifest_without_writing(
    tmp_path: Path,
) -> None:
    root = write_minimal_foundation(tmp_path)
    status_path = root / "catalog/status-test-nodes.yaml"
    write_yaml(
        status_path,
        {"schema_version": "1", "active_snapshot_id": "not-the-active-id", "entries": []},
    )
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["snapshot"]["files"].append(
        {
            "path": "research/ui-foundation/catalog/status-test-nodes.yaml",
            "sha256": hashlib.sha256(b"original generated bytes").hexdigest(),
            "audited_at": "2026-07-24T00:00:00Z",
        }
    )
    write_yaml(evidence_path, evidence)
    before = {
        path: path.read_bytes()
        for path in (
            evidence_path,
            root / "catalog/snapshot-lineage.yaml",
            status_path,
        )
    }

    with pytest.raises(ValueError, match="UNREQUESTED_DRIFT"):
        load_snapshot_recorder().record(root, "child", "2026-07-24T01:00:00Z", [], [])

    assert {path: path.read_bytes() for path in before} == before


def test_snapshot_recorder_recovers_injected_publication_failure_before_retry(
    tmp_path: Path,
) -> None:
    root = write_minimal_foundation(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("changed\n", encoding="utf-8")
    recorder = load_snapshot_recorder()
    before = {
        path: path.read_bytes()
        for path in (root / "catalog/evidence.yaml", root / "catalog/snapshot-lineage.yaml")
    }

    class FailingPublisher(recorder.FilesystemPublisher):
        def __init__(self, marker: Path) -> None:
            super().__init__(marker)
            self.calls = 0

        def _replace(self, path: Path, content: bytes) -> None:
            self.calls += 1
            if self.calls == 2:
                raise OSError("injected boundary failure")
            super()._replace(path, content)

    publisher = FailingPublisher(root / "catalog/.snapshot-lineage.transaction.json")
    with pytest.raises(OSError, match="injected boundary failure"):
        recorder.record(root, "child", "2026-07-24T01:00:00Z", ["source.txt"], [], publisher)

    assert {path: path.read_bytes() for path in before} == before
    recorder.record(root, "child", "2026-07-24T01:00:00Z", ["source.txt"], [])
    assert len(snapshot_lineage(root)["entries"]) == 2


def test_q5_backlinks_cover_every_externally_callable_unauthorized_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    action_path = root / "reality/actions/act-13-graph-patch.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["question_ids"] = []
    action_path.write_text(yaml.safe_dump(action, sort_keys=False), encoding="utf-8")

    result = run_validator(root)

    assert "Q5_AUTHORIZATION_COVERAGE_MISSING" in issue_codes(result)


def test_action_authority_map_has_exact_action_command_and_q5_parity(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)

    result = run_validator(root)

    relevant = {
        code
        for code in issue_codes(result)
        if code.startswith("ACTION_AUTHORITY_") or code.startswith("Q5_AUTHORIZATION_")
    }
    assert relevant == set()


def test_action_authority_map_rejects_missing_action_row(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    path = root / "catalog/action-authority-surfaces.yaml"
    catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    catalog["items"].pop()
    write_yaml(path, catalog)

    result = run_validator(root)

    assert "ACTION_AUTHORITY_ACTION_PARITY" in issue_codes(result)


def test_reviewed_mutation_route_inventory_requires_action_and_command_coverage(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    authority_path = root / "catalog/action-authority-surfaces.yaml"
    authority = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
    inventory_item = authority["route_inventory"][0]
    action_id = inventory_item["action_id"]
    action_path = next(
        path
        for path in (root / "reality/actions").glob("act-*.yaml")
        if yaml.safe_load(path.read_text(encoding="utf-8"))["id"] == action_id
    )
    action_path.unlink()

    result = run_validator(root)

    assert "ACTION_AUTHORITY_ROUTE_INVENTORY_ACTION_MISSING" in issue_codes(result)


def test_reviewed_mutation_route_inventory_rejects_missing_command(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    authority = yaml.safe_load(
        (root / "catalog/action-authority-surfaces.yaml").read_text(encoding="utf-8")
    )
    command_id = authority["route_inventory"][0]["command_id"]
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["items"] = [item for item in evidence["items"] if item.get("id") != command_id]
    write_yaml(evidence_path, evidence)

    result = run_validator(root)

    assert "ACTION_AUTHORITY_ROUTE_INVENTORY_COMMAND_MISSING" in issue_codes(result)


def test_q5_action_ids_are_exactly_the_map_required_rows(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    authority = yaml.safe_load(
        (root / "catalog/action-authority-surfaces.yaml").read_text(encoding="utf-8")
    )
    required_id = next(item["action_id"] for item in authority["items"] if item["q5_required"])
    questions_path = root / "catalog/questions.yaml"
    questions = yaml.safe_load(questions_path.read_text(encoding="utf-8"))
    q5 = next(item for item in questions["items"] if item["id"] == "Q-5")
    q5["affected_ids"].remove(required_id)
    write_yaml(questions_path, questions)

    result = run_validator(root)

    assert "Q5_AUTHORIZATION_COVERAGE_MISSING" in issue_codes(result)


def test_derived_authority_row_requires_same_command_independent_owner(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    path = root / "catalog/action-authority-surfaces.yaml"
    authority = yaml.safe_load(path.read_text(encoding="utf-8"))
    derived = next(
        item
        for item in authority["items"]
        if item["surface_kind"] == "derived-same-command-consequence"
    )
    derived["authority_owner_action_id"] = derived["action_id"]
    write_yaml(path, authority)

    result = run_validator(root)

    assert "ACTION_AUTHORITY_DERIVED_OWNER_INVALID" in issue_codes(result)


def test_action_authority_locators_resolve_exact_symbols_including_cli_start(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    path = root / "catalog/action-authority-surfaces.yaml"
    catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    cli_start = next(item for item in catalog["items"] if item["action_id"] == "ACT-8")
    cli_start["implementation_locators"] = [
        "CLI runs start -> src/orchestrator/cli/runs.py::missing_start_run"
    ]
    write_yaml(path, catalog)

    result = run_validator(root)

    assert "ACTION_AUTHORITY_IMPLEMENTATION_LOCATOR_UNRESOLVED" in issue_codes(result)


def test_retired_node_transitions_are_command_specific_and_do_not_invent_broad_edges() -> None:
    state = yaml.safe_load(
        (REPO_ROOT / "research/ui-foundation/reality/state-model.yaml").read_text(encoding="utf-8")
    )
    retirement_transitions = [
        transition for transition in state["transitions"] if transition["to_state_id"] == "STA-73"
    ]

    patch_sources = {
        transition["from_state_id"]
        for transition in retirement_transitions
        if transition["mechanism"] == "accepted retire_node patch"
    }
    reconciliation_sources = {
        transition["from_state_id"]
        for transition in retirement_transitions
        if transition["mechanism"] == "reconciliation retirement after passed terminal evidence"
    }

    assert patch_sources == {"STA-71", "STA-72", "STA-29", "STA-32"}
    assert reconciliation_sources == {"STA-71", "STA-72", "STA-32"}
    assert all(
        transition.get("command_id") == "CMD-12"
        for transition in retirement_transitions
        if transition["mechanism"] == "accepted retire_node patch"
    )
    assert {"STA-30", "STA-31"}.isdisjoint(patch_sources | reconciliation_sources)


def test_validator_rejects_ready_reconciliation_retirement_but_accepts_patch_retirement(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    state_path = root / "reality/state-model.yaml"
    state_model = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_model["transitions"].append(
        {
            "from_state_id": "STA-29",
            "to_state_id": "STA-73",
            "mechanism": "reconciliation retirement after passed terminal evidence",
            "evidence_ids": ["EVD-24"],
        }
    )
    state_path.write_text(yaml.safe_dump(state_model, sort_keys=False), encoding="utf-8")

    validator = load_validator()
    issues = validator.validate_graph_retirement_transition_contract(root)

    assert "STATE_RETIREMENT_SOURCE_INELIGIBLE" in {issue.code for issue in issues}


def test_validator_rejects_malformed_items_and_semantic_fields(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(root / "catalog/claims.yaml", {"schema_version": "1", "items": "bad"})
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [{"id": "CAP-01"}]}
    )
    result = run_validator(root, phase=0)
    assert result.returncode == 1
    assert set(issue_codes(result)) == {"CANONICAL_DOCUMENT_INVALID", "SEMANTIC_ITEM_INVALID"}


def test_validator_rejects_invalid_status_and_schema_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CAP-01",
                    "title": "Capability",
                    "definition": "Definition",
                    "implementation_status": "invented",
                    "test_status": "exercised",
                    "documentation_status": "documented",
                    "capability_status": "current",
                    "confidence": 1,
                    "confidence_basis": "Evidence",
                    "evidence_ids": [],
                    "conflict_ids": [],
                    "question_ids": [],
                    "limitations": [],
                    "prohibited_interpretations": [],
                }
            ],
        },
    )
    schema = json.loads(
        (REPO_ROOT / "research/ui-foundation/schemas/semantic-item.schema.json").read_text()
    )
    schema["properties"]["implementation_status"]["enum"] = ["invented"]
    schemas = root / "schemas"
    (schemas / "semantic-item.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    result = run_validator(root, phase=0)
    assert {"SEMANTIC_ITEM_INVALID", "SCHEMA_CONTRACT_INVALID"} <= set(issue_codes(result))


def test_current_capability_requires_reachable_and_exercised_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    item = {
        "id": "CAP-01",
        "title": "Capability",
        "definition": "Definition",
        "implementation_status": "present",
        "test_status": "exercised",
        "documentation_status": "documented",
        "capability_status": "current",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": ["EVD-01", "EVD-02"],
        "conflict_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "implementation", "reachable": False},
                {"id": "EVD-02", "source_kind": "test", "test_status": "contradicted"},
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {"CURRENT_IMPLEMENTATION_EVIDENCE_MISSING", "CURRENT_EXERCISED_EVIDENCE_MISSING"} <= set(
        issue_codes(result)
    )


def test_validator_rejects_authority_conflicts_and_current_future_leakage(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    base = {
        "title": "Capability",
        "definition": "Definition",
        "test_status": "unknown",
        "documentation_status": "documented",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                base
                | {
                    "id": "CAP-01",
                    "implementation_status": "absent",
                    "capability_status": "current",
                    "conflict_ids": ["CON-01"],
                },
                base
                | {
                    "id": "CAP-02",
                    "implementation_status": "present",
                    "capability_status": "proposed",
                    "conflict_ids": [],
                },
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {"CURRENT_CONFLICTING", "CURRENT_FUTURE_LEAKAGE", "FUTURE_CURRENT_LEAKAGE"} <= set(
        issue_codes(result)
    )


def test_current_action_cannot_substitute_proposed_role_for_enforced_authority(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "CMD-01",
            "enforced_authorization": "absent",
            "proposed_role_policy": "operator",
            "transition": {"from_state_ids": ["STA-01"], "to_state_ids": ["STA-02"]},
        },
    )
    result = run_validator(root, phase=0)
    assert "AUTHORITY_CONFLICT" in issue_codes(result)


def test_feedback_schema_contract_requires_export_and_history_fields(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    schema = json.loads(
        (REPO_ROOT / "research/ui-foundation/schemas/review-feedback.schema.json").read_text()
    )
    schema["required"].remove("source_snapshot")
    schema["properties"]["response_history"]["items"]["required"].remove("note")
    schema["properties"]["response_history"]["items"]["properties"]["response"]["enum"] = ["maybe"]
    schemas = root / "schemas"
    (schemas / "review-feedback.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("SCHEMA_CONTRACT_INVALID") == 3


def test_validator_rejects_unsafe_and_unreadable_evidence_paths_and_accumulates(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    directory = root.parents[1] / "source-directory"
    directory.mkdir()
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {"path": "../../secret", "sha256": "0" * 64},
                    {"path": str(tmp_path / "absolute"), "sha256": "0" * 64},
                    {"path": "source-directory", "sha256": "0" * 64},
                ],
            },
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("SOURCE_PATH_UNSAFE") == 2
    assert "SOURCE_READ_ERROR" in issue_codes(result)


def test_implemented_action_requires_resolved_command_and_legal_transition(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/state-model.yaml",
        {"schema_version": "1", "items": [{"id": "STA-01"}], "transitions": []},
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "CMD-99",
            "transition": {"from_state_ids": [], "to_state_ids": ["STA-02"]},
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "ACTION_COMMAND_UNRESOLVED",
        "ACTION_TRANSITION_EMPTY",
        "STATE_UNKNOWN",
        "ACTION_TRANSITION_UNREACHABLE",
    } <= set(issue_codes(result))


def test_implemented_action_accepts_resolved_command_and_singular_legal_transition(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    state = {
        "id": "STA-01",
        "title": "Ready",
        "definition": "Ready state",
        "implementation_status": "present",
        "test_status": "exercised",
        "documentation_status": "documented",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": [],
        "conflict_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [state, state | {"id": "STA-02", "title": "Done"}],
            "transitions": [{"from_state_id": "STA-01", "to_state_id": "STA-02"}],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                },
                {"id": "EVD-01", "source_kind": "implementation", "reachable": True},
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"}),
    )
    result = run_validator(root, phase=0)
    assert not {
        "ACTION_COMMAND_UNRESOLVED",
        "ACTION_TRANSITION_EMPTY",
        "STATE_UNKNOWN",
        "ACTION_TRANSITION_UNREACHABLE",
    } & set(issue_codes(result))


def test_implemented_action_accepts_typed_transition_variants(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    state = {
        "id": "STA-01",
        "title": "Ready",
        "definition": "Ready state",
        "implementation_status": "present",
        "test_status": "exercised",
        "documentation_status": "documented",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": [],
        "conflict_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [state, state | {"id": "STA-02", "title": "Done"}],
            "transitions": [
                {"from_state_id": "STA-01", "to_state_id": "STA-02"},
                {"from_state_id": "STA-02", "to_state_id": "STA-02"},
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                },
                {"id": "EVD-01", "source_kind": "implementation", "reachable": True},
            ],
        },
    )
    action = present_action("CMD-01", {})
    action.pop("transition")
    action.pop("resulting_state_id")
    action["transition_variants"] = [
        {
            "carrier": "task",
            "from_state_id": "STA-01",
            "to_state_id": "STA-02",
            "eligibility_precondition": "task status is exactly pending",
            "effect_kind": "state-change",
            "evidence_ids": ["EVD-01"],
        },
        {
            "carrier": "result",
            "from_state_id": "STA-02",
            "to_state_id": "STA-02",
            "eligibility_precondition": "task status is exactly completed",
            "effect_kind": "self-loop-field-mutation",
            "evidence_ids": ["EVD-01"],
        },
    ]
    write_yaml(root / "reality/actions/ACT-01.yaml", action)

    result = run_validator(root, phase=0)

    assert not {
        "ACTION_CONTRACT_INVALID",
        "ACTION_TRANSITION_MISSING",
        "ACTION_TRANSITION_UNREACHABLE",
        "ACTION_RESULT_STATE_MISMATCH",
    } & set(issue_codes(result))


def test_action_rejects_resulting_state_alongside_transition_variants(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    action = present_action("CMD-01", {})
    action.pop("transition")
    action["transition_variants"] = [
        {
            "carrier": "task",
            "from_state_id": "STA-01",
            "to_state_id": "STA-02",
            "eligibility_precondition": "task status is exactly pending",
            "effect_kind": "state-change",
            "evidence_ids": ["EVD-01"],
        }
    ]
    write_yaml(root / "reality/actions/ACT-01.yaml", action)

    result = run_validator(root, phase=0)

    assert "ACTION_CONTRACT_INVALID" in issue_codes(result)


def test_action_rejects_singular_transition_without_resulting_state(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    action = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"})
    action.pop("resulting_state_id")
    write_yaml(root / "reality/actions/ACT-01.yaml", action)

    result = run_validator(root, phase=0)

    assert "ACTION_CONTRACT_INVALID" in issue_codes(result)


def test_action_rejects_normalized_duplicate_transition_variants(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    action = present_action("CMD-01", {})
    action.pop("transition")
    variant = {
        "carrier": "task",
        "from_state_id": "STA-01",
        "to_state_id": "STA-02",
        "eligibility_precondition": "task status is exactly pending",
        "effect_kind": "state-change",
        "evidence_ids": ["EVD-01"],
    }
    action["transition_variants"] = [
        variant,
        variant
        | {
            "eligibility_precondition": "  TASK status is exactly PENDING ",
        },
    ]
    write_yaml(root / "reality/actions/ACT-01.yaml", action)

    result = run_validator(root, phase=0)

    assert "ACTION_CONTRACT_INVALID" in issue_codes(result)


def test_action_rejects_normalized_duplicate_locator_lists(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    action = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"})
    action["implementation_locators"] = [
        "src/example.py::carrier",
        " SRC/example.py::carrier ",
    ]
    action["test_locators"] = [
        "tests/test_example.py::test_carrier",
        " tests/test_example.py::TEST_carrier ",
    ]
    action["bounded_test_locators"] = ["bounded", " BOUNDED "]
    write_yaml(root / "reality/actions/ACT-01.yaml", action)

    result = run_validator(root, phase=0)

    assert "ACTION_CONTRACT_INVALID" in issue_codes(result)


def test_task15_action_variants_encode_exact_eligibility_and_paused_no_op() -> None:
    action_root = REPO_ROOT / "research/ui-foundation/reality/actions"

    def variants(action_id: int, slug: str) -> list[dict[str, object]]:
        action = yaml.safe_load((action_root / f"act-{action_id}-{slug}.yaml").read_text())
        assert "transition" not in action
        assert "resulting_state_id" not in action
        return action["transition_variants"]

    for action_id, slug in (
        (75, "checklist-update-rest"),
        (80, "checklist-update-mcp"),
    ):
        values = variants(action_id, slug)
        assert {
            (value["carrier"], value["from_state_id"], value["to_state_id"], value["effect_kind"])
            for value in values
        } == {
            ("task", state, state, "self-loop-field-mutation")
            for state in ("STA-8", "STA-9", "STA-11", "STA-12", "STA-13")
        }
        assert not {"STA-10", "STA-14", "STA-15"} & {value["from_state_id"] for value in values}

    for action_id, slug in ((76, "grade-update-rest"), (82, "grade-update-mcp")):
        values = variants(action_id, slug)
        assert {
            (value["carrier"], value["from_state_id"], value["to_state_id"], value["effect_kind"])
            for value in values
            if value["carrier"] == "task"
        } == {
            ("task", state, state, "self-loop-field-mutation")
            for state in ("STA-10", "STA-14", "STA-15")
        }
        assert not {"STA-8", "STA-9", "STA-11", "STA-12", "STA-13"} & {
            value["from_state_id"] for value in values
        }
    act82 = variants(82, "grade-update-mcp")
    assert {
        (value["carrier"], value["from_state_id"], value["to_state_id"], value["effect_kind"])
        for value in act82
        if value["carrier"] == "run"
    } == {("run", "STA-4", "STA-4", "accepted-no-op")}

    submit = variants(81, "task-submit-mcp")
    assert {
        (value["carrier"], value["from_state_id"], value["to_state_id"], value["effect_kind"])
        for value in submit
    } == {
        ("task", "STA-9", "STA-10", "state-change"),
        ("run", "STA-4", "STA-4", "accepted-no-op"),
    }
    assert {value["eligibility_precondition"] for value in submit if value["carrier"] == "run"} == {
        "run status is exactly PAUSED and pause_reason is exactly "
        "requirement_escalated; task is not mutated",
        "run status is exactly PAUSED and pause_reason is exactly "
        "awaiting_clarification; task is not mutated",
    }


def test_task15_variant_authority_rejects_missing_paused_noop_clause(tmp_path: Path) -> None:
    root = copy_foundation_with_source(tmp_path)
    authority_path = root / "catalog/action-variant-authority.yaml"
    authority = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
    row = next(item for item in authority["reviewed_rows"] if item["action_id"] == "ACT-82")
    row["required_variants"] = [
        clause
        for clause in row["required_variants"]
        if clause["clause_id"] != "act-82-paused-requirement-escalated-noop"
    ]
    write_yaml(authority_path, authority)

    result = run_validator(root)

    assert "ACTION_VARIANT_AUTHORITY_PARITY" in issue_codes(result)


def test_task15_escalation_evidence_separates_transports_from_engine() -> None:
    evidence = yaml.safe_load(
        (REPO_ROOT / "research/ui-foundation/catalog/evidence.yaml").read_text()
    )["items"]
    by_id = {item["id"]: item for item in evidence}
    assert (by_id["EVD-116"]["path"], by_id["EVD-116"]["symbol"]) == (
        "src/orchestrator/workflow/engine/engine.py",
        "WorkflowEngine.escalate_requirement",
    )
    expected = {
        "EVD-129": (
            "src/orchestrator/api/routers/tasks.py",
            "escalate_requirement",
        ),
        "EVD-130": (
            "tests/integration/test_api_escalation.py",
            "test_escalate_pauses_run_and_marks_requirement",
        ),
        "EVD-131": (
            "src/orchestrator/api/mcp/server.py",
            "OrchestratorMCPServer._register_tools.orchestrator_escalate_requirement",
        ),
        "EVD-132": (
            "src/orchestrator/api/mcp/tools.py",
            "ToolHandler._escalate_requirement",
        ),
        "EVD-133": (
            "tests/integration/test_mcp_server.py",
            "test_escalate_requirement_through_mcp_server",
        ),
    }
    assert {
        evidence_id: (by_id[evidence_id]["path"], by_id[evidence_id]["symbol"])
        for evidence_id in expected
    } == expected

    actions = {
        action_id: yaml.safe_load(path.read_text())
        for action_id, path in (
            (
                78,
                REPO_ROOT
                / "research/ui-foundation/reality/actions/act-78-requirement-escalate-rest.yaml",
            ),
            (
                84,
                REPO_ROOT
                / "research/ui-foundation/reality/actions/act-84-requirement-escalate-mcp.yaml",
            ),
        )
    }
    assert actions[78]["audit_evidence_ids"] == ["EVD-129", "EVD-130", "EVD-116"]
    assert actions[84]["audit_evidence_ids"] == [
        "EVD-131",
        "EVD-132",
        "EVD-133",
        "EVD-116",
    ]


def test_absent_intervention_requires_complete_requirement_record(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "absent",
            "capability_status": "gap",
            "executable": False,
        },
    )
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("ABSENT_INTERVENTION_REQUIREMENT_MISSING") == 5


def test_phase_three_requires_review_items_with_canonical_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    batch = root / "reviews/phase-3-reality-capability-01.html"
    batch.write_text(
        '<article data-item-id="CAP-99" data-evidence-ids="EVD-99"></article>', encoding="utf-8"
    )
    result = run_validator(root, phase=3)
    assert {"REVIEW_REFERENCE_UNRESOLVED", "REVIEW_EVIDENCE_UNRESOLVED"} <= set(issue_codes(result))


def test_phase_three_rejects_review_batch_without_items(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    batch = root / "reviews/phase-3-reality-capability-01.html"
    batch.write_text("<html></html>", encoding="utf-8")
    result = run_validator(root, phase=3)
    assert "REVIEW_ITEMS_MISSING" in issue_codes(result)


def test_report_headings_must_match_exactly(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("## Purposeful\n", encoding="utf-8")
    result = run_report_validator(report)
    assert issue_codes(result).count("REPORT_SECTION_MISSING") == 9


def test_validate_foundation_rejects_invalid_direct_phase(tmp_path: Path) -> None:
    module = load_validator()
    issues = module.validate_foundation(write_valid_phase_zero(tmp_path), 4)
    assert [issue.code for issue in issues] == ["PHASE_INVALID"]


def test_every_phase_requires_both_schema_files(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    (root / "schemas/semantic-item.schema.json").unlink()
    (root / "schemas/review-feedback.schema.json").unlink()
    for phase in range(4):
        result = run_validator(root, phase=phase)
        assert issue_codes(result).count("REQUIRED_SCHEMA_MISSING") == 2


def test_semantic_schema_requires_the_complete_semantic_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    path = root / "schemas/semantic-item.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["required"].remove("confidence_basis")
    path.write_text(json.dumps(schema), encoding="utf-8")
    result = run_validator(root, phase=0)
    assert "SCHEMA_CONTRACT_INVALID" in issue_codes(result)


def test_malformed_typed_action_derivation_transition_and_snapshot_are_rejected(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {"id": "ACT-01", "implementation_status": "sometimes", "actor": ["operator"]},
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {"id": "DRV-01", "status": "maybe", "inputs": "CAP-01"},
    )
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [],
            "transitions": [{"from_state_id": ["STA-01"], "to_state_id": "STA-02"}],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": [{"path": 7, "sha256": False}]},
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "ACTION_CONTRACT_INVALID",
        "DERIVATION_CONTRACT_INVALID",
        "STATE_TRANSITION_INVALID",
        "SOURCE_SNAPSHOT_INVALID",
    } <= set(issue_codes(result))


def test_current_capability_rejects_nonreachable_kinds_contradiction_and_unresolved_conflict(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    current = semantic_item(
        "CAP-01",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        capability_status="current",
        evidence_ids=["EVD-01", "EVD-02", "EVD-03"],
        conflict_ids=["CON-01"],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [current]})
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "executable-schema", "reachable": True},
                {"id": "EVD-02", "source_kind": "test", "test_status": "exercised"},
                {"id": "EVD-03", "source_kind": "documentation", "test_status": "contradicted"},
            ],
        },
    )
    write_yaml(
        root / "catalog/conflicts.yaml",
        {"schema_version": "1", "items": [{"id": "CON-01", "status": "unresolved"}]},
    )
    result = run_validator(root, phase=0)
    assert {
        "CURRENT_IMPLEMENTATION_EVIDENCE_MISSING",
        "CURRENT_EVIDENCE_CONTRADICTED",
        "CURRENT_CONFLICT_UNRESOLVED",
    } <= set(issue_codes(result))


def test_derived_capability_inputs_must_resolve_to_current_capabilities(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    proposed = semantic_item("CAP-01", capability_status="proposed")
    derived = semantic_item("CAP-02", capability_status="derived", derivation_id="DRV-01")
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [proposed, derived]},
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {
            "id": "DRV-01",
            "status": "admitted",
            "inputs": ["CAP-01"],
            "algorithm": "identity",
            "output_type": "string",
            "unknown_behavior": "unknown",
            "failure_behavior": "unknown",
            "freshness": "snapshot",
            "recomputation_behavior": "recompute when inputs change",
            "implementation_evidence_ids": ["EVD-01"],
            "limitations": ["none"],
            "prohibited_interpretations": ["causal"],
        },
    )
    result = run_validator(root, phase=0)
    assert "DERIVATION_INPUT_NOT_CURRENT" in issue_codes(result)


def test_present_action_requires_typed_command_namespace_actor_permissions_and_fields(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                }
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "EVD-01",
            "transition": {"from_state_id": "STA-01", "to_state_id": "STA-02"},
        },
    )
    result = run_validator(root, phase=0)
    assert "ACTION_COMMAND_WRONG_NAMESPACE" in issue_codes(result)
    assert "ACTION_CONTRACT_INVALID" in issue_codes(result)


def test_command_must_be_implemented_and_reachable(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "absent",
                    "reachable": False,
                }
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "CMD-01",
            "transition": {"from_state_id": "STA-01", "to_state_id": "STA-02"},
        },
    )
    result = run_validator(root, phase=0)
    assert "ACTION_COMMAND_UNAVAILABLE" in issue_codes(result)


def test_present_action_resolves_result_state_and_audit_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    states = [
        semantic_item("STA-01"),
        semantic_item("STA-02"),
    ]
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": states,
            "transitions": [{"from_state_id": "STA-01", "to_state_id": "STA-02"}],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                }
            ],
        },
    )
    action = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"})
    action["resulting_state_id"] = "STA-99"
    action["audit_evidence_ids"] = ["EVD-99"]
    write_yaml(root / "reality/actions/ACT-01.yaml", action)
    result = run_validator(root, phase=0)
    assert {
        "STATE_UNKNOWN",
        "ACTION_AUDIT_EVIDENCE_UNRESOLVED",
    } <= set(issue_codes(result))


def test_source_snapshot_rejects_symlink_escape(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    repository_root = root.parents[1]
    (repository_root / "escape.txt").symlink_to(outside)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "escape.txt",
                        "sha256": "2bb80d537b1da3e38bd30361aa855686bde0ba0d5a73ccba1cac4843f89a253b",
                        "audited_at": "2026-07-23T00:00:00Z",
                    }
                ],
            },
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert "SOURCE_PATH_UNSAFE" in issue_codes(result)


def test_each_review_item_requires_its_own_nonempty_evidence_set(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/claims.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("CAP-01"), semantic_item("CAP-02")],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "documentation"}],
        },
    )
    batch = root / "reviews/phase-3-reality-capability-01.html"
    batch.write_text(
        '<article data-item-id="CAP-01" data-evidence-ids=""></article>'
        '<article data-item-id="CAP-02" data-evidence-ids="EVD-01"></article>',
        encoding="utf-8",
    )
    result = run_validator(root, phase=3)
    assert "REVIEW_EVIDENCE_MISSING" in issue_codes(result)


def test_unresolved_or_weak_causality_cannot_retain_causal_label(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    relationship = semantic_item(
        "REL-01",
        relationship_type="causal",
        epistemic_status="inferred",
        evidence_ids=["EVD-01"],
    )
    write_yaml(
        root / "reality/relationships.yaml",
        {"schema_version": "1", "items": [relationship]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "implementation",
                    "evidence_type": "temporal-observation",
                }
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "CAUSAL_EPISTEMIC_INSUFFICIENT",
        "CAUSAL_MECHANISM_EVIDENCE_MISSING",
        "CAUSAL_LABEL_UNRESOLVED",
    } <= set(issue_codes(result))


def test_non_mapping_action_and_derivation_roots_are_never_skipped(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    for index, value in enumerate(([], "scalar", None), start=1):
        write_yaml(root / f"reality/actions/ACT-0{index}.yaml", value)
        write_yaml(root / f"capabilities/derivations/DRV-0{index}.yaml", value)
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("ACTION_CONTRACT_INVALID") == 3
    assert issue_codes(result).count("DERIVATION_CONTRACT_INVALID") == 3


def test_derived_capability_requires_admitted_derivation_and_qualifying_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("CAP-01", capability_status="derived", derivation_id="DRV-01"),
                semantic_item("CAP-02", capability_status="derived", derivation_id="DRV-02"),
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "documentation",
                    "reachable": True,
                }
            ],
        },
    )
    contract = {
        "status": "admitted",
        "inputs": ["CAP-03"],
        "algorithm": "identity",
        "output_type": "string",
        "unknown_behavior": "unknown",
        "failure_behavior": "unknown",
        "freshness": "snapshot",
        "recomputation_behavior": "when inputs change",
        "implementation_evidence_ids": ["EVD-01"],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {"id": "DRV-01"} | contract,
    )
    write_yaml(
        root / "capabilities/derivations/DRV-02.yaml",
        {"id": "DRV-02"} | contract | {"status": "rejected"},
    )
    result = run_validator(root, phase=0)
    assert {
        "DERIVATION_NOT_ADMITTED",
        "DERIVATION_IMPLEMENTATION_EVIDENCE_INVALID",
    } <= set(issue_codes(result))


def test_action_status_compatibility_and_absent_requirement_purity(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    present = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"}) | {
        "capability_status": "proposed",
        "executable": True,
    }
    absent = {
        "id": "ACT-02",
        "implementation_status": "absent",
        "capability_status": "gap",
        "executable": False,
        "required_outcome": "Intervene",
        "source_demand_ids": ["scope.action"],
        "implementation_constraints": ["none"],
        "required_evidence": ["command design"],
        "unresolved_command_decisions": ["authority"],
        "command_id": "CMD-01",
        "transition": {"from_state_id": "STA-01", "to_state_id": "STA-02"},
        "durable_effect": "mutates state",
        "retry_behavior": "retry",
        "idempotency": "keyed",
        "reversibility": "irreversible",
        "audit_evidence_ids": ["EVD-01"],
    }
    write_yaml(root / "reality/actions/ACT-01.yaml", present)
    write_yaml(root / "reality/actions/ACT-02.yaml", absent)
    result = run_validator(root, phase=0)
    assert "ACTION_STATUS_INCOMPATIBLE" in issue_codes(result)
    assert "ABSENT_INTERVENTION_COMPLETED_SEMANTICS" in issue_codes(result)


def test_action_resulting_state_must_match_legal_transition_target(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("STA-01"), semantic_item("STA-02")],
            "transitions": [{"from_state_id": "STA-01", "to_state_id": "STA-02"}],
        },
    )
    action = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"})
    action["resulting_state_id"] = "STA-01"
    write_yaml(root / "reality/actions/ACT-01.yaml", action)
    result = run_validator(root, phase=0)
    assert "ACTION_RESULT_STATE_MISMATCH" in issue_codes(result)


def test_question_references_use_only_typed_question_namespace(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/questions.yaml",
        {"schema_version": "1", "items": [{"id": "Q-01"}]},
    )
    write_yaml(
        root / "catalog/decisions.yaml",
        {"schema_version": "1", "items": [{"id": "DEC-01"}]},
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("CAP-01", question_ids=["Q-01", "Q-99", "DEC-01"])],
        },
    )
    result = run_validator(root, phase=0)
    assert "QUESTION_REFERENCE_WRONG_NAMESPACE" in issue_codes(result)
    assert "QUESTION_REFERENCE_UNRESOLVED" in issue_codes(result)


def test_current_action_status_requires_present_and_executable_in_both_directions(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    absent_current = {
        "id": "ACT-01",
        "implementation_status": "absent",
        "capability_status": "current",
        "executable": False,
        "required_outcome": "Intervene",
        "source_demand_ids": ["scope.action"],
        "implementation_constraints": ["none"],
        "required_evidence": ["command design"],
        "unresolved_command_decisions": ["authority"],
    }
    present_nonexecutable = present_action(
        "CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"}
    ) | {"executable": False}
    write_yaml(root / "reality/actions/ACT-01.yaml", absent_current)
    write_yaml(root / "reality/actions/ACT-02.yaml", present_nonexecutable | {"id": "ACT-02"})
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("ACTION_STATUS_INCOMPATIBLE") == 2


def test_derived_classification_rejects_all_conflicting_semantic_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    current_input = semantic_item(
        "CAP-01",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        capability_status="current",
        evidence_ids=["EVD-01", "EVD-02"],
    )
    derived = semantic_item(
        "CAP-02",
        capability_status="derived",
        derivation_id="DRV-01",
        test_status="contradicted",
        documentation_status="conflicting",
        conflict_ids=["CON-01"],
        evidence_ids=["EVD-03"],
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [current_input, derived]},
    )
    write_yaml(
        root / "catalog/conflicts.yaml",
        {"schema_version": "1", "items": [{"id": "CON-01", "status": "unresolved"}]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "implementation", "reachable": True},
                {"id": "EVD-02", "source_kind": "test", "test_status": "exercised"},
                {
                    "id": "EVD-03",
                    "source_kind": "documentation",
                    "test_status": "contradicted",
                },
            ],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {
            "id": "DRV-01",
            "status": "admitted",
            "inputs": ["CAP-01"],
            "algorithm": "identity",
            "output_type": "string",
            "unknown_behavior": "unknown",
            "failure_behavior": "unknown",
            "freshness": "snapshot",
            "recomputation_behavior": "when inputs change",
            "implementation_evidence_ids": ["EVD-01"],
            "limitations": ["none"],
            "prohibited_interpretations": ["causal"],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "DERIVED_CONFLICT_UNRESOLVED",
        "DERIVED_EVIDENCE_CONTRADICTED",
        "DERIVED_CONFLICTING",
    } <= set(issue_codes(result))


def test_derivation_rejects_unrelated_current_contract_and_evidence_chain(tmp_path: Path) -> None:
    """A command validator cannot stand in for prompt size evidence or input."""
    root = write_valid_phase_zero(tmp_path)
    current = semantic_item(
        "CAP-69",
        capability_status="current",
        implementation_status="present",
        output_contract={
            "semantic_type": "CommandValidation",
            "fields": ["valid"],
            "role": "validator",
        },
        evidence_ids=["EVD-105"],
    )
    derived = semantic_item(
        "CAP-30",
        capability_status="derived",
        derivation_id="DRV-30",
        evidence_ids=["EVD-105"],
    )
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [current, derived]}
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-105", "source_kind": "implementation", "reachable": True}],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-30.yaml",
        {
            "id": "DRV-30",
            "status": "admitted",
            "capability_ids": ["CAP-30"],
            "inputs": ["CAP-69"],
            "typed_inputs": {
                "CAP-69": {
                    "semantic_type": "PromptSize",
                    "consumed_fields": ["tokens"],
                    "role": "prompt",
                }
            },
            "algorithm": "deterministically select, tie break, and round",
            "output_type": "PromptSize",
            "unknown_behavior": "unknown",
            "failure_behavior": "fail",
            "freshness": "snapshot",
            "recomputation_behavior": "recompute",
            "implementation_evidence_ids": ["EVD-105"],
            "evidence_ids": ["EVD-105"],
            "limitations": ["bounded"],
            "prohibited_interpretations": ["complete"],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "DERIVATION_TYPED_INPUT_CONTRACT_MISMATCH",
        "DERIVATION_IMPLEMENTATION_EVIDENCE_CHAIN_INVALID",
    } <= set(issue_codes(result))


def test_partial_gap_rejects_duplicate_normalized_limitations_and_prohibitions(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    duplicate = "Carrier evidence is incomplete."
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    limitations=[duplicate, " carrier evidence is incomplete. "],
                    prohibited_interpretations=[duplicate, "CARRIER EVIDENCE IS INCOMPLETE."],
                    implementation_carrier_bindings=[],
                )
            ],
        },
    )
    result = run_validator(root)
    assert {
        "CAPABILITY_LIMITATIONS_DUPLICATE",
        "CAPABILITY_PROHIBITED_INTERPRETATIONS_DUPLICATE",
    } <= set(issue_codes(result))


def test_partial_gap_rejects_non_action_reversibility_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "EVI-1",
                            "role": "reversibility-action",
                            "semantic_type": "ActionContract",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/evidence/inventory.yaml",
        {"schema_version": "1", "items": [semantic_item("EVI-1", evidence_ids=["EVD-01"])]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_non_permission_authority_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-42",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "EVI-1",
                            "role": "authority-policy",
                            "semantic_type": "PermissionContract",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/evidence/inventory.yaml",
        {"schema_version": "1", "items": [semantic_item("EVI-1", evidence_ids=["EVD-01"])]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_non_usage_telemetry_cost_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-6",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "EVI-1",
                            "role": "usage-telemetry",
                            "semantic_type": "UsageTelemetry",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/evidence/inventory.yaml",
        {"schema_version": "1", "items": [semantic_item("EVI-1", evidence_ids=["EVD-01"])]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_binding_semantic_type_mismatch(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ACT-01",
                            "role": "reversibility-action",
                            "semantic_type": "UsageTelemetry",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml", {"id": "ACT-01", "audit_evidence_ids": ["EVD-01"]}
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_typed_carrier_with_unrelated_binding_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-02"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-1",
                            "role": "entity-input",
                            "semantic_type": "EntityRecord",
                            "evidence_ids": ["EVD-02"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {"schema_version": "1", "items": [semantic_item("ENT-1", evidence_ids=["EVD-01"])]},
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_EVIDENCE_UNSUPPORTED" in issue_codes(result)


def test_partial_unknown_requires_typed_carrier_bindings(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-70",
                    capability_status="unknown",
                    implementation_status="partial",
                    implementation_carrier_bindings=[],
                )
            ],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_UNRESOLVED" in issue_codes(result)


def test_partial_unknown_rejects_absent_carrier(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-70",
                    capability_status="unknown",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-1",
                            "role": "entity-input",
                            "semantic_type": "EntityRecord",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("ENT-1", implementation_status="absent", evidence_ids=["EVD-01"])
            ],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_NON_EXECUTABLE" in issue_codes(result)


def test_partial_gap_rejects_unknown_non_action_carrier(tmp_path: Path) -> None:
    del tmp_path
    validator = load_validator()

    assert (
        validator._carrier_is_executable({"id": "ENT-1", "implementation_status": "unknown"})
        is False
    )


def test_partial_gap_rejects_non_action_carrier_without_implementation_status(
    tmp_path: Path,
) -> None:
    del tmp_path
    validator = load_validator()

    assert validator._carrier_is_executable({"id": "ENT-1"}) is False


def test_partial_gap_rejects_legacy_cost_as_graph_usage_rollup(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("ENT-21", implementation_status="partial", evidence_ids=["EVD-01"])
            ],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-47",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-21",
                            "role": "graph-usage-rollup",
                            "semantic_type": "UsageTelemetry",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )

    result = run_validator(root)

    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_attempt_entity_as_structured_tool_trace(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("ENT-5", implementation_status="partial", evidence_ids=["EVD-01"])
            ],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-50",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-5",
                            "role": "structured-tool-trace",
                            "semantic_type": "EvidenceInventory",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )

    result = run_validator(root)

    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_capability_evidence_copied_into_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-99"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-1",
                            "role": "entity-input",
                            "semantic_type": "EntityRecord",
                            "evidence_ids": ["EVD-99"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {"schema_version": "1", "items": [semantic_item("ENT-1", evidence_ids=[])]},
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_EVIDENCE_UNSUPPORTED" in issue_codes(result)


def test_partial_gap_rejects_absence_contract_as_implementation_carrier(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    absent_action = semantic_item(
        "ACT-15",
        implementation_status="absent",
        executable=False,
        audit_evidence_ids=["EVD-01"],
    )
    write_yaml(root / "reality/actions/act-15.yaml", absent_action)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    absence_contract_ids=["ACT-15"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ACT-15",
                            "role": "action-contract",
                            "semantic_type": "ActionContract",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    result = run_validator(root)
    assert {
        "GAP_PARTIAL_CARRIER_NON_EXECUTABLE",
        "GAP_PARTIAL_ABSENCE_CARRIER_OVERLAP",
    } <= set(issue_codes(result))


def test_absent_gap_rejects_executable_absence_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/act-1.yaml",
        semantic_item(
            "ACT-1",
            implementation_status="present",
            executable=True,
            audit_evidence_ids=["EVD-01"],
        ),
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-43",
                    capability_status="gap",
                    implementation_status="absent",
                    absence_basis="No implementation exists.",
                    absence_contract_ids=["ACT-1"],
                    implementation_carrier_ids=[],
                )
            ],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_ABSENCE_CARRIER_INVALID" in issue_codes(result)


def test_current_and_derived_capabilities_require_output_contracts(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("CAP-1", capability_status="current"),
                semantic_item("CAP-2", capability_status="derived"),
            ],
        },
    )
    result = run_validator(root)
    assert issue_codes(result).count("CAPABILITY_OUTPUT_CONTRACT_INVALID") == 2


def _admitted_derivation_fixture(
    root: Path, *, output_contract: dict[str, object], bindings: list[dict[str, object]]
) -> None:
    current = semantic_item(
        "CAP-01",
        capability_status="current",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        output_contract={"semantic_type": "Input", "fields": ["value"]},
        evidence_ids=["EVD-01", "EVD-02"],
    )
    derived = semantic_item(
        "CAP-02",
        capability_status="derived",
        derivation_id="DRV-01",
        output_contract=output_contract,
        evidence_ids=["EVD-03"],
    )
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [current, derived]}
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "implementation", "reachable": True},
                {
                    "id": "EVD-02",
                    "source_kind": "test",
                    "reachable": True,
                    "test_status": "exercised",
                },
                {"id": "EVD-03", "source_kind": "implementation", "reachable": True},
            ],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {
            "id": "DRV-01",
            "status": "admitted",
            "capability_ids": ["CAP-02"],
            "inputs": ["CAP-01"],
            "typed_inputs": {
                "CAP-01": {"semantic_type": "Input", "consumed_fields": ["value"], "role": "input"}
            },
            "algorithm": "deterministically select, tie break, and round",
            "output_type": "Output",
            "produced_fields": ["result"],
            "unknown_behavior": "unknown",
            "failure_behavior": "fail",
            "freshness": "snapshot",
            "recomputation_behavior": "recompute",
            "implementation_evidence_ids": ["EVD-03"],
            "evidence_bindings": bindings,
            "limitations": ["bounded"],
            "prohibited_interpretations": ["complete"],
        },
    )


def test_derivation_rejects_unrelated_implementation_locator(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "Output", "fields": ["result"]},
        bindings=[
            {
                "id": "EVD-03",
                "role": "pure-projection-implementation",
                "path": "other.py",
                "symbol": "other",
                "semantic_type": "Output",
            }
        ],
    )
    result = run_validator(root)
    assert "DERIVATION_EVIDENCE_BINDING_LOCATOR_INVALID" in issue_codes(result)


def test_derivation_rejects_incompatible_output_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "Different", "fields": ["other"]},
        bindings=[
            {
                "id": "EVD-03",
                "role": "pure-projection-implementation",
                "path": "implementation.py",
                "symbol": "project",
                "semantic_type": "Output",
            }
        ],
    )
    result = run_validator(root)
    assert "DERIVATION_OUTPUT_CONTRACT_MISMATCH" in issue_codes(result)


def test_derivation_rejects_output_evidence_without_derivation_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root, output_contract={"semantic_type": "Output", "fields": ["result"]}, bindings=[]
    )
    result = run_validator(root)
    assert "DERIVATION_EVIDENCE_BINDING_MISSING" in issue_codes(result)


def test_derivation_rejects_real_patch_validator_as_prompt_size_implementation(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "PromptSize", "fields": ["bytes"]},
        bindings=[
            {
                "id": "EVD-105",
                "role": "pure-projection-implementation",
                "path": "src/orchestrator/graph/patch_validator.py",
                "symbol": "validate_patch",
                "semantic_type": "PromptSize",
            }
        ],
    )
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    evidence["items"][2].update(
        {
            "id": "EVD-105",
            "path": "src/orchestrator/graph/patch_validator.py",
            "symbol": "validate_patch",
            "supported_semantic_types": ["GraphPatchValidationResult"],
        }
    )
    write_yaml(root / "catalog/evidence.yaml", evidence)
    derivation = yaml.safe_load(
        (root / "capabilities/derivations/DRV-01.yaml").read_text(encoding="utf-8")
    )
    derivation["implementation_evidence_ids"] = ["EVD-105"]
    derivation["output_type"] = "PromptSize"
    derivation["produced_fields"] = ["bytes"]
    write_yaml(root / "capabilities/derivations/DRV-01.yaml", derivation)
    registry = yaml.safe_load((root / "capabilities/registry.yaml").read_text(encoding="utf-8"))
    registry["items"][1]["evidence_ids"] = ["EVD-105"]
    write_yaml(root / "capabilities/registry.yaml", registry)
    result = run_validator(root)
    assert "DERIVATION_IMPLEMENTATION_SEMANTIC_UNSUPPORTED" in issue_codes(result)


def test_derivation_rejects_evidence_copied_to_output_without_canonical_semantic_support(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "Output", "fields": ["result"]},
        bindings=[
            {
                "id": "EVD-03",
                "role": "pure-projection-implementation",
                "path": "implementation.py",
                "symbol": "project",
                "semantic_type": "Output",
            }
        ],
    )
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    evidence["items"][2].update(
        {
            "path": "implementation.py",
            "symbol": "project",
            "supported_semantic_types": ["DifferentOutput"],
        }
    )
    write_yaml(root / "catalog/evidence.yaml", evidence)
    result = run_validator(root)
    assert "DERIVATION_IMPLEMENTATION_SEMANTIC_UNSUPPORTED" in issue_codes(result)


def test_unresolved_conflict_requires_distinct_claims_evidence_and_affected_ids(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-01",
                    "status": "unresolved",
                    "claims": [{"proposition": "same"}, {"proposition": "same"}],
                    "claim_evidence": [{"claim_index": 0, "evidence_ids": ["EVD-01"]}],
                    "affected_ids": [],
                    "settlement_method": "decide",
                }
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "CONFLICT_CLAIMS_NOT_DISTINCT",
        "CONFLICT_EVIDENCE_INSUFFICIENT",
        "CONFLICT_AFFECTED_IDS_MISSING",
    } <= set(issue_codes(result))


def test_conflicting_semantic_item_requires_conflict_or_question_reference(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("ENT-01", documentation_status="conflicting")],
        },
    )
    result = run_validator(root, phase=0)
    assert "CONFLICTING_SEMANTIC_REFERENCE_MISSING" in issue_codes(result)


def test_scope_demand_requires_substantive_finding_not_delegation_assignment(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "key": "demand.one",
                    "source": "docs/jtbd/jobs.md",
                    "source_anchor": "J1",
                    "demand_type": "claim",
                    "label": "Demand",
                    "audit_owner": "graph-runtime",
                    "downstream_jobs": ["J1"],
                    "blocking": True,
                    "phase_1_finding": {"evidence_ids": ["EVD-01"], "status": "found"},
                }
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "path": "agent-reports/00-delegation-plan.md#Key findings",
                }
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert "SCOPE_FINDING_NOT_SUBSTANTIVE" in issue_codes(result)


def test_validator_rejects_unlinked_conflicts_questions_snapshots_and_weak_direct_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-01",
                    "status": "unresolved",
                    "claims": [{"proposition": "one"}, {"proposition": "two"}],
                    "claim_evidence": [
                        {"claim_index": 0, "evidence_ids": ["EVD-01"]},
                        {"claim_index": 1, "evidence_ids": ["EVD-02"]},
                    ],
                    "affected_ids": ["ENT-01"],
                    "settlement_method": "settle",
                }
            ],
        },
    )
    write_yaml(
        root / "catalog/questions.yaml",
        {
            "schema_version": "1",
            "items": [
                {"id": "Q-01", "status": "open", "blocking": True, "affected_ids": ["ENT-01"]}
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {"schema_version": "1", "items": [semantic_item("ENT-01", capability_status="current")]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "snapshots": [{"id": "snapshot-test", "files": []}],
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "implementation",
                    "snapshot_id": "missing",
                    "snapshot_path": "no.py",
                },
                {
                    "id": "EVD-02",
                    "source_kind": "test",
                    "test_status": "exercised",
                    "path": "tests/x.py",
                    "symbol": "test_x",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "no.py",
                },
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                    "test_evidence_ids": ["EVD-01"],
                },
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "CONFLICT_BACKLINK_MISSING",
        "QUESTION_BACKLINK_MISSING",
        "UNRESOLVED_ADMISSION_BLOCKED",
        "EVIDENCE_SNAPSHOT_UNRESOLVED",
        "EVIDENCE_SNAPSHOT_PATH_UNRESOLVED",
        "COMMAND_TEST_EVIDENCE_INVALID",
    } <= set(issue_codes(result))


def test_unresolved_conflict_blocks_affected_current_action(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-01",
                    "status": "unresolved",
                    "claims": [{"proposition": "a"}, {"proposition": "b"}],
                    "claim_evidence": [{"evidence_ids": []}, {"evidence_ids": []}],
                    "affected_ids": ["ACT-01"],
                    "settlement_method": "settle",
                }
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "capability_status": "current",
            "conflict_ids": ["CON-01"],
        },
    )
    result = run_validator(root, phase=0)
    assert "UNRESOLVED_ACTION_ADMISSION_BLOCKED" in issue_codes(result)


def test_current_capability_linked_to_open_blocking_question_is_barred_without_affected_id(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/questions.yaml",
        {
            "schema_version": "1",
            "items": [{"id": "Q-01", "status": "open", "blocking": True, "affected_ids": []}],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-01",
                    implementation_status="present",
                    test_status="exercised",
                    documentation_status="documented",
                    capability_status="current",
                    question_ids=["Q-01"],
                )
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "CURRENT_QUESTION_UNRESOLVED" in issue_codes(result)


def test_snapshot_coverage_rejects_hash_valid_but_incomplete_patterns(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    repository = root.parents[1]
    (repository / "src").mkdir()
    (repository / "src/required.py").write_text("x = 1\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "phase1",
                "include_patterns": ["src/**/*.py"],
                "expected_count": 1,
                "covered_count": 1,
                "files": [],
            },
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert "SOURCE_SNAPSHOT_COVERAGE_MISSING" in issue_codes(result)


def test_validator_rejects_duplicate_id_allocation_ledger_entries(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/ids.yaml",
        {
            "schema_version": "1",
            "items": [{"canonical_id": "EVD-113"}, {"canonical_id": "EVD-113"}],
        },
    )
    result = run_validator(root, phase=0)
    assert "ID_ALLOCATION_DUPLICATE" in issue_codes(result)


def test_validator_rejects_direct_evidence_missing_each_required_locator(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": "direct.py", "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "direct",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "direct.py",
                    "symbol": "subject",
                },
                {
                    "id": "EVD-02",
                    "source_kind": "implementation",
                    "path": "direct.py",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "direct.py",
                },
                {
                    "id": "EVD-03",
                    "source_kind": "implementation",
                    "path": "direct.py",
                    "symbol": "subject",
                    "snapshot_path": "direct.py",
                },
                {
                    "id": "EVD-04",
                    "source_kind": "implementation",
                    "path": "direct.py",
                    "symbol": "subject",
                    "snapshot_id": "snapshot-test",
                },
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert issue_codes(result).count("DIRECT_EVIDENCE_FIELD_MISSING") == 4
    assert "path" in result.stderr
    assert "symbol" in result.stderr
    assert "snapshot_id" in result.stderr
    assert "snapshot_path" in result.stderr


def test_validator_rejects_direct_evidence_path_mismatch_and_undeclared_snapshot_path(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": "declared.py", "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "test",
                    "path": "actual.py",
                    "symbol": "test_subject",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "undeclared.py",
                },
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "DIRECT_EVIDENCE_PATH_MISMATCH" in issue_codes(result)
    assert "EVIDENCE_SNAPSHOT_PATH_UNRESOLVED" in issue_codes(result)


def test_phase_one_snapshot_requires_coverage_counts_and_files(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    required_source = root.parents[1] / "src/orchestrator"
    required_source.mkdir(parents=True)
    (required_source / "required.py").write_text("x = 1\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "phase1",
                "include_patterns": [
                    "src/orchestrator/**/*.py",
                    "tests/**/*.py",
                    "ui/src/**/*.ts",
                    "ui/src/**/*.tsx",
                    "docs/jtbd/jobs.md",
                    "docs/jtbd/journeys.md",
                    "docs/jtbd/decision-information.md",
                    "docs/jtbd/information-architecture.md",
                    "docs/jtbd/evaluation-rubric.md",
                    "docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md",
                    "research/ui-foundation/agent-reports/*.md",
                    "research/ui-foundation/tools/validate.py",
                    "tests/integration/test_ui_foundation_tools.py",
                ],
                "expected_count": 0,
                "covered_count": 0,
                "files": [],
            },
            "items": [],
        },
    )

    result = run_validator(root, phase=1)

    assert "SOURCE_SNAPSHOT_COUNT_MISMATCH" in issue_codes(result)
    assert "SOURCE_SNAPSHOT_COVERAGE_MISSING" in issue_codes(result)


def test_phase_one_snapshot_requires_every_coverage_pattern(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "phase1",
                "include_patterns": [],
                "expected_count": 0,
                "covered_count": 0,
                "files": [],
            },
            "items": [],
        },
    )

    result = run_validator(root, phase=1)

    assert "SOURCE_SNAPSHOT_PATTERN_MISSING" in issue_codes(result)


def test_phase_one_rejects_invalid_q7_coverage_attestation(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/questions.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "Q-7",
                    "status": "resolved",
                    "blocking": False,
                    "decisive_evidence_ids": ["EVD-113"],
                },
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-113", "source_kind": "audit-report"}],
        },
    )

    result = run_validator(root, phase=1)

    assert "Q7_COVERAGE_ATTESTATION_INVALID" in issue_codes(result)


def test_validator_rejects_exercised_semantic_without_direct_test_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "ENT-01",
                    test_status="exercised",
                    evidence_ids=["EVD-01"],
                )
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "test_status": "exercised",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "EXERCISED_DIRECT_TEST_EVIDENCE_MISSING" in issue_codes(result)


def test_validator_rejects_current_semantic_without_direct_reachable_implementation(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "ENT-01",
                    capability_status="current",
                    evidence_ids=["EVD-01"],
                )
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report", "reachable": True}],
        },
    )

    result = run_validator(root, phase=0)

    assert "CURRENT_DIRECT_IMPLEMENTATION_EVIDENCE_MISSING" in issue_codes(result)


def test_phase_one_rejects_missing_or_malformed_snapshot_coverage_fields(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    for field in ("include_patterns", "files", "expected_count", "covered_count"):
        snapshot: dict[str, object] = {
            "id": "phase1",
            "include_patterns": [],
            "files": [],
            "expected_count": 0,
            "covered_count": 0,
        }
        snapshot.pop(field)
        write_yaml(
            root / "catalog/evidence.yaml",
            {"schema_version": "1", "snapshot": snapshot, "items": []},
        )

        result = run_validator(root, phase=1)

        assert "SOURCE_SNAPSHOT_COVERAGE_INVALID" in issue_codes(result), field


def test_validator_rejects_zero_padded_allocation_suffix_collision(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/ids.yaml",
        {
            "schema_version": "1",
            "items": [{"canonical_id": "EVD-01"}, {"canonical_id": "EVD-1"}],
        },
    )

    result = run_validator(root, phase=0)

    assert "ID_ALLOCATION_SUFFIX_DUPLICATE" in issue_codes(result)


def test_validator_rejects_synthesis_evidence_with_missing_markdown_anchor(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report = root.parents[1] / "research/ui-foundation/agent-reports/03-workflow-state.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Workflow state\n\n## Key findings\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    }
                ],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "source_label": "03-workflow-state.md#Key findings",
                    "path": "research/ui-foundation/agent-reports/03-workflow-state.md#missing",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_REPORT_ANCHOR_UNRESOLVED" in issue_codes(result)


def test_validator_rejects_synthesis_evidence_in_wrong_source_label_report(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    repository = root.parents[1]
    for name in ("03-workflow-state.md", "04-api-actions-authority.md"):
        report = repository / "research/ui-foundation/agent-reports" / name
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Report\n\n## Key findings\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    },
                    {
                        "path": "research/ui-foundation/agent-reports/04-api-actions-authority.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    },
                ],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "source_label": "03-workflow-state.md#Key findings",
                    "path": "research/ui-foundation/agent-reports/04-api-actions-authority.md#key-findings",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/04-api-actions-authority.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_REPORT_SOURCE_LABEL_MISMATCH" in issue_codes(result)


def test_validator_accepts_synthesis_evidence_with_specific_report_anchor(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report = root.parents[1] / "research/ui-foundation/agent-reports/03-workflow-state.md"
    report.parent.mkdir(parents=True)
    report.write_text(
        "# Workflow state\n\n## State carriers and legal transitions\n", encoding="utf-8"
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    }
                ],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "source_label": "03-workflow-state.md#state-carriers-and-legal-transitions",
                    "path": "research/ui-foundation/agent-reports/03-workflow-state.md#state-carriers-and-legal-transitions",
                    "symbol": "WF-run-status",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_REPORT_ANCHOR_UNRESOLVED" not in issue_codes(result)
    assert "SYNTHESIS_REPORT_SOURCE_LABEL_MISMATCH" not in issue_codes(result)


def test_validator_rejects_synthesis_evidence_missing_each_required_field(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report_path = "research/ui-foundation/agent-reports/03-workflow-state.md"
    report = root.parents[1] / report_path
    report.parent.mkdir(parents=True)
    report.write_text("# Workflow\n\n## Key findings\n", encoding="utf-8")
    items = []
    for index, field in enumerate(
        ("path", "symbol", "source_label", "snapshot_id", "snapshot_path")
    ):
        item: dict[str, object] = {
            "id": f"EVD-{index + 1:02}",
            "source_kind": "audit-report",
            "provenance_role": "synthesis",
            "path": f"{report_path}#key-findings",
            "symbol": "finding",
            "source_label": "03-workflow-state.md#key-findings",
            "snapshot_id": "snapshot-test",
            "snapshot_path": report_path,
        }
        item.pop(field)
        items.append(item)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": report_path, "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": items,
        },
    )

    result = run_validator(root, phase=0)

    assert issue_codes(result).count("SYNTHESIS_EVIDENCE_FIELD_MISSING") == 5
    for field in ("path", "symbol", "source_label", "snapshot_id", "snapshot_path"):
        assert field in result.stderr


def test_validator_rejects_synthesis_evidence_path_snapshot_mismatch(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report_path = "research/ui-foundation/agent-reports/03-workflow-state.md"
    report = root.parents[1] / report_path
    report.parent.mkdir(parents=True)
    report.write_text("# Workflow\n\n## Key findings\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": report_path, "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "path": f"{report_path}#key-findings",
                    "symbol": "finding",
                    "source_label": "03-workflow-state.md#key-findings",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/other.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_EVIDENCE_SNAPSHOT_PATH_MISMATCH" in issue_codes(result)


def test_phase_two_requires_exactly_one_registry_status_per_scope_demand(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "key": "claim.one",
                    "source": "docs/jtbd/jobs.md",
                    "source_anchor": "J1",
                    "demand_type": "claim",
                    "label": "One",
                    "audit_owner": "workflow-state",
                    "downstream_jobs": ["J1"],
                    "blocking": True,
                },
                {
                    "key": "action.two",
                    "source": "docs/jtbd/decision-information.md",
                    "source_anchor": "Action",
                    "demand_type": "implemented-action-candidate",
                    "label": "Two",
                    "audit_owner": "api-actions-authority",
                    "downstream_jobs": ["J1"],
                    "blocking": True,
                },
            ],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("CAP-01", scope_demand_key="claim.one", capability_status="gap")
            ],
        },
    )

    result = run_validator(root, phase=2)

    assert "CAPABILITY_DEMAND_COVERAGE_MISSING" in issue_codes(result)


def test_phase_two_rejects_duplicate_scope_status_and_forbidden_current_manifest(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    demand = {
        "key": "decisions.steer-context",
        "source": "docs/jtbd/decision-information.md",
        "source_anchor": "Action",
        "demand_type": "absent-intervention",
        "label": "Steer with new context",
        "audit_owner": "api-actions-authority",
        "downstream_jobs": ["J6"],
        "blocking": True,
    }
    write_yaml(root / "catalog/scope.yaml", {"schema_version": "1", "items": [demand]})
    current = semantic_item(
        "CAP-01",
        scope_demand_key="decisions.steer-context",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        capability_status="current",
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [current, current | {"id": "CAP-02"}]},
    )

    result = run_validator(root, phase=2)

    assert "CAPABILITY_DEMAND_STATUS_DUPLICATE" in issue_codes(result)
    assert "FORBIDDEN_CURRENT_MANIFEST" in issue_codes(result)


def test_committed_phase_two_registry_preserves_adjudicated_capability_boundaries() -> None:
    result = run_validator(REPO_ROOT / "research/ui-foundation", phase=2)

    assert result.returncode == 0, result.stderr
    claims = yaml.safe_load(
        (REPO_ROOT / "research/ui-foundation/catalog/claims.yaml").read_text(encoding="utf-8")
    )
    assert claims["classification_counts"] == {
        "current": 1,
        "derived": 0,
        "proposed": 25,
        "gap": 49,
        "unknown": 57,
    }
    assert claims["derivation_count"] == 0


def test_current_variant_contract_rejects_missing_evidence_for_one_asserted_branch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69["current_command_identities"] = ["graph.patch-validator"]
    cap69["evidence_ids"].remove("EVD-106")
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_VARIANT_EVIDENCE_MISSING" in issue_codes(result)


def test_current_variant_contract_rejects_broad_definition_with_narrow_output_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "current_command_identities": ["graph.record-decision"],
            "output_contract": {
                "semantic_type": "RecordGraphDecisionResponse",
                "fields": ["run_id", "events", "decision_view"],
                "role": "graph-decision-result",
                "command_identity": "graph.record-decision",
            },
            "asserted_output_variant_types": [
                "RecordGraphDecisionResponse",
                "PatchValidationResult",
            ],
        }
    )
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_validator_result_rejects_decision_and_attempt_variants(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69["current_command_identities"] = ["graph.patch-validator"]
    cap69["evidence_ids"] += ["EVD-111", "EVD-112"]
    cap69["asserted_output_variant_types"] += [
        "RecordGraphDecisionResponse",
        "GraphPatchAttemptsResponse",
    ]
    cap69["output_contract"]["variants"] += [
        {
            "semantic_type": "RecordGraphDecisionResponse",
            "fields": ["run_id", "graph_position", "events", "decision_view"],
            "role": "graph-decision-response",
            "command_identity": "graph.record-decision",
        },
        {
            "semantic_type": "GraphPatchAttemptsResponse",
            "fields": ["run_id", "graph_position", "attempts"],
            "role": "graph-patch-attempt-readback",
            "command_identity": "graph.patch-attempt-readback",
        },
    ]
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_VARIANT_DEMAND_MISMATCH" in issue_codes(result)


def test_current_rejects_unrelated_command_evidence_for_a_variant(tmp_path: Path) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69["current_command_identities"] = ["graph.record-decision"]
    cap69["output_contract"]["variants"][0]["command_identity"] = "graph.record-decision"
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_VARIANT_COMMAND_EVIDENCE_MISSING" in issue_codes(result)


def test_current_rejects_copied_output_contract_for_a_distinct_demand(tmp_path: Path) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "output_contract": cap69["output_contract"],
            "asserted_output_variant_types": cap69["asserted_output_variant_types"],
        }
    )
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_CONTRACT_COPIED_CROSS_DEMAND" in issue_codes(result)


def test_current_approve_gate_patch_requires_human_patch_approval_and_defer_commands(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "output_contract": {
                "semantic_type": "RecordGraphDecisionResponse",
                "fields": ["run_id", "graph_position", "events", "decision_view"],
                "role": "graph-decision-response",
                "command_identity": "graph.record-decision",
            },
            "asserted_output_variant_types": ["RecordGraphDecisionResponse"],
        }
    )
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_REQUIRED_COMMAND_EVIDENCE_MISSING" in issue_codes(result)


def test_current_variant_contract_requires_asserted_variants_for_narrow_cap69(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69.pop("asserted_output_variant_types")
    cap69["output_contract"]["variants"] = cap69["output_contract"]["variants"][:1]
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_requires_asserted_variants_for_narrow_cap86(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "current_command_identities": ["graph.record-decision"],
            "output_contract": {
                "semantic_type": "RecordGraphDecisionResponse",
                "fields": ["run_id", "graph_position", "events", "decision_view"],
                "role": "graph-decision-response",
                "command_identity": "graph.record-decision",
            },
        }
    )
    cap86.pop("asserted_output_variant_types", None)
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_rejects_duplicate_contract_variant_type(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    variants = cap69["output_contract"]["variants"]
    variants.append(dict(variants[0]))
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_rejects_duplicate_asserted_variant_type(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    asserted = cap69["asserted_output_variant_types"]
    asserted.append(asserted[0])
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_rejects_duplicate_variant_field(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    fields = cap69["output_contract"]["variants"][0]["fields"]
    fields.append(fields[0])
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_CONTRACT_INVALID" in issue_codes(result)


def test_phase_two_validates_superseded_derivation_ledger_bindings(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    append_yaml_item(
        root / "catalog/ids.yaml",
        {
            "namespace": "DRV",
            "canonical_id": "DRV-1",
            "provisional_key": "historical-output",
            "title": "Historical output",
            "status": "superseded",
            "output_capability_ids": ["CAP-404"],
        },
    )
    result = run_validator(root)
    assert "DERIVATION_LEDGER_SUPERSEDED_INVALID" in issue_codes(result)


def phase_two_demand(key: str, label: str = "Demand-specific label") -> dict[str, object]:
    return {
        "key": key,
        "source": "docs/jtbd/jobs.md",
        "source_anchor": "J1",
        "demand_type": "claim",
        "label": label,
        "audit_owner": "workflow-state",
        "downstream_jobs": ["J1"],
        "blocking": True,
    }


def classified_capability(identifier: str, key: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "title": "Demand-specific capability",
        "definition": f"Demand-specific definition for {key}.",
        "implementation_status": "absent",
        "test_status": "unexercised",
        "documentation_status": "documented",
        "capability_status": "gap",
        "confidence_basis": f"Direct adjudication for {key}.",
        "limitations": [f"{key} remains unavailable."],
        "prohibited_interpretations": [f"Do not present {key} as available."],
        "scope_demand_key": key,
        "classification_basis": "No reachable implementation evidence establishes this demand.",
    }
    return semantic_item(identifier, **(values | overrides))


def write_cap_allocation(root: Path, identifier: str, key: str) -> None:
    append_yaml_item(
        root / "catalog/ids.yaml",
        {
            "namespace": "CAP",
            "provisional_key": key,
            "title": "Demand-specific capability",
            "status": "active",
            "canonical_id": identifier,
        },
    )


def test_phase_two_rejects_duplicate_scope_keys_before_coverage_set_conversion(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")] * 2},
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [classified_capability("CAP-1", "claim.one")]},
    )
    write_cap_allocation(root, "CAP-1", "claim.one")

    result = run_validator(root)

    assert "SCOPE_DEMAND_KEY_DUPLICATE" in issue_codes(result)


def test_phase_two_rejects_extra_registry_records_and_unbound_or_placeholder_allocations(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                classified_capability("CAP-1", "claim.one"),
                classified_capability("CAP-2", "claim.extra"),
            ],
        },
    )
    write_cap_allocation(root, "CAP-1", "scope-demand-001")
    write_cap_allocation(root, "CAP-2", "claim.extra")

    result = run_validator(root)

    assert {
        "CAPABILITY_DEMAND_EXTRA",
        "CAPABILITY_ALLOCATION_BINDING_INVALID",
        "CAPABILITY_ALLOCATION_PLACEHOLDER",
    } <= set(issue_codes(result))


def test_phase_two_rejects_generic_or_incomplete_capability_adjudication(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability("CAP-1", "claim.one")
    item.update(
        {
            "title": "CAP-1",
            "definition": "Definition",
            "limitations": [],
            "prohibited_interpretations": [],
        }
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")

    result = run_validator(root)

    assert "CAPABILITY_ADJUDICATION_GENERIC" in issue_codes(result)
    assert "CAPABILITY_ORTHOGONAL_STATUS_MISSING" in issue_codes(result)


def test_phase_two_rejects_known_generic_unknown_fallback_template(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1",
        "claim.one",
        capability_status="unknown",
        implementation_status="partial",
        definition=("Demand cannot be established across the audited Phase 1 carrier boundaries."),
        implementation_carrier_bindings=[],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    result = run_validator(root)
    assert "CAPABILITY_UNKNOWN_FALLBACK_GENERIC" in issue_codes(result)


def test_phase_two_rejects_generic_gap_template_and_duplicate_gap_definitions(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {
            "schema_version": "1",
            "items": [phase_two_demand("claim.one"), phase_two_demand("claim.two")],
        },
    )
    generic = "Demand is a source demand with audited partial or absent Phase 1 evidence; it is not an implemented aggregate or projection."
    first = classified_capability("CAP-1", "claim.one", definition=generic)
    second = classified_capability("CAP-2", "claim.two", definition=generic)
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [first, second]}
    )
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_cap_allocation(root, "CAP-2", "claim.two")

    result = run_validator(root)

    assert {
        "CAPABILITY_GAP_FALLBACK_GENERIC",
        "CAPABILITY_GAP_DEFINITION_DUPLICATE",
    } <= set(issue_codes(result))


def test_committed_phase_two_gap_definitions_are_individualized_and_unique() -> None:
    registry = yaml.safe_load(
        (REPO_ROOT / "research/ui-foundation/capabilities/registry.yaml").read_text(
            encoding="utf-8"
        )
    )
    gap_definitions = [
        " ".join(item["definition"].split())
        for item in registry["items"]
        if item["capability_status"] == "gap"
    ]

    assert len(gap_definitions) == 49
    assert len(gap_definitions) == len(set(gap_definitions))
    assert all(
        "source demand with audited partial or absent" not in definition
        for definition in gap_definitions
    )


def test_phase_two_current_requires_direct_reachable_implementation_and_direct_exercised_test(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1",
        "claim.one",
        implementation_status="partial",
        test_status="unknown",
        capability_status="current",
        evidence_ids=["EVD-1", "EVD-2"],
        question_ids=["Q-1"],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-1", "source_kind": "persisted-record", "reachable": True},
                {
                    "id": "EVD-2",
                    "source_kind": "audit-report",
                    "reachable": True,
                    "test_status": "exercised",
                },
            ],
        },
    )
    write_yaml(
        root / "catalog/questions.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "Q-1",
                    "blocking": True,
                    "status": "open",
                    "affected_ids": ["CAP-1"],
                }
            ],
        },
    )

    result = run_validator(root)

    assert {
        "CURRENT_DIRECT_IMPLEMENTATION_EVIDENCE_MISSING",
        "CURRENT_DIRECT_TEST_EVIDENCE_MISSING",
        "CURRENT_STATUS_INCONSISTENT",
        "CURRENT_QUESTION_UNRESOLVED",
    } <= set(issue_codes(result))


def test_phase_two_rejects_incomplete_or_non_bidirectional_derivation_contract(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1", "claim.one", capability_status="derived", derivation_id="DRV-1"
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "capabilities/derivations/DRV-1.yaml",
        {
            "id": "DRV-1",
            "status": "admitted",
            "capability_ids": ["CAP-2"],
            "inputs": ["CAP-9"],
            "algorithm": "Combine values.",
            "output_type": "Result",
            "unknown_behavior": "Unknown on missing input.",
            "failure_behavior": "Reject malformed input.",
            "freshness": "At source position.",
            "recomputation_behavior": "On source change.",
            "implementation_evidence_ids": ["EVD-1"],
            "limitations": ["Limited."],
            "prohibited_interpretations": ["Not causal."],
        },
    )

    result = run_validator(root)

    assert {
        "DERIVATION_TYPED_INPUTS_MISSING",
        "DERIVATION_CAPABILITY_BACKLINK_MISSING",
        "DERIVATION_CAPABILITY_LINK_UNRESOLVED",
        "DERIVATION_ALGORITHM_INCOMPLETE",
    } <= set(issue_codes(result))


def test_phase_two_rejects_false_absence_and_unlinked_claimed_uncertainty(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1",
        "claim.one",
        classification_basis="Partial reachable implementation exists, but a blocking conflict remains.",
        evidence_ids=["EVD-1"],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-1", "source_kind": "implementation", "reachable": True}],
        },
    )

    result = run_validator(root)

    assert "CAPABILITY_FALSE_ABSENCE" in issue_codes(result)
    assert "CAPABILITY_BASIS_LINK_MISSING" in issue_codes(result)


def test_phase_two_rejects_stale_completion_metadata_and_generated_projections(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability("CAP-1", "claim.one")
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "phase_status": "complete", "completion_phase": 2, "items": [item]},
    )
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "catalog/claims.yaml",
        {
            "schema_version": "1",
            "phase_status": "complete",
            "completion_phase": 2,
            "scope_demand_count": 99,
            "classification_counts": {"gap": 99},
            "items": [],
        },
    )
    (root / "capabilities/gaps.md").write_text("stale\n", encoding="utf-8")
    (root / "status.md").write_text("stale\n", encoding="utf-8")

    result = run_validator(root)

    assert {
        "PHASE_TWO_METADATA_MISMATCH",
        "PHASE_TWO_CLAIMS_PROJECTION_STALE",
        "PHASE_TWO_GAPS_PROJECTION_STALE",
        "PHASE_TWO_STATUS_PROJECTION_STALE",
    } <= set(issue_codes(result))


def test_task15_status_projection_derives_canonical_inputs_and_rejects_stale_status(
    tmp_path: Path,
) -> None:
    root = copy_foundation_with_source(tmp_path)
    validator = load_validator()
    baseline = validator._phase_two_status_projection(validator.load_foundation(root))
    assert "210 records (35 REL, 74 STA, 86 ACT, 9 EVI, 6 INV)" in baseline

    scope_path = root / "catalog/status-scope.yaml"
    scope = yaml.safe_load(scope_path.read_text(encoding="utf-8"))
    scope["items"] = [item for item in scope["items"] if item["id"] != "REL-1"]
    write_yaml(scope_path, scope)

    action_path = root / "reality/actions/act-1-runner-model-profile-defaults-save.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["test_status"] = "unexercised"
    action["test_locators"] = []
    write_yaml(action_path, action)

    manifest_path = root / "catalog/status-test-nodes.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"].append(
        {
            "base_locator": "tests/new_status.py::test_new_status",
            "concrete_node_ids": ["tests/new_status.py::test_new_status"],
        }
    )
    write_yaml(manifest_path, manifest)

    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["active_snapshot_id"] = "snapshot-mutated"
    write_yaml(evidence_path, evidence)

    questions_path = root / "catalog/questions.yaml"
    questions = yaml.safe_load(questions_path.read_text(encoding="utf-8"))
    q5 = next(item for item in questions["items"] if item["id"] == "Q-5")
    q5["affected_ids"].append("ACT-999")
    write_yaml(questions_path, questions)

    projection = validator._phase_two_status_projection(validator.load_foundation(root))
    assert "projection covers 209 records (34 REL, 74 STA, 86 ACT, 9 EVI, 6 INV)" in projection
    assert "137 exact and 50 bounded test locators" in projection
    assert "120-base/120-concrete-node collected manifest under `snapshot-mutated`" in projection
    assert (
        "Test distributions are REL 13/21, STA 57/17, ACT 55/31, EVI 2/7, and INV 6/0" in projection
    )
    assert "63 actions retain Q-5" in projection

    (root / "status.md").write_text(baseline, encoding="utf-8")
    result = run_validator(root)

    assert "PHASE_TWO_STATUS_PROJECTION_STALE" in issue_codes(result)
