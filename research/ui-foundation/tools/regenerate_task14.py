"""Apply the binding Task 14 audit and regenerate Phase 2 projections."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from validate import write_phase_two_projections


ROOT = Path(__file__).parents[1]
AUDIT = ROOT.parents[1] / ".superpowers/sdd/task-14-gap-carrier-audit.md"


def semantic_type(identifier: str) -> str:
    if identifier == "EVI-9":
        return "UsageTelemetry"
    return {
        "ENT": "EntityRecord",
        "STA": "StateRecord",
        "EVI": "EvidenceInventory",
        "ACT": "ActionContract",
        "PER": "PermissionContract",
    }[identifier.split("-", 1)[0]]


def role(capability_id: str, identifier: str) -> str:
    if capability_id in {"CAP-6", "CAP-47", "CAP-57", "CAP-71"} and identifier == "EVI-9":
        return "usage-telemetry"
    if capability_id in {"CAP-21", "CAP-44"} and identifier.startswith("ACT-"):
        return "reversibility-action"
    if capability_id == "CAP-42":
        if identifier.startswith("PER-"):
            return "authority-policy"
        if identifier.startswith("ACT-"):
            return "authority-action"
    return {
        "ENT": "entity-input",
        "STA": "state-input",
        "EVI": "evidence-inventory",
        "ACT": "action-contract",
        "PER": "permission-contract",
    }[identifier.split("-", 1)[0]]


def audit_prose(markdown: str) -> dict[str, tuple[str, str]]:
    findings: dict[str, tuple[str, str]] = {}
    for section in re.split(r"(?m)^### ", markdown):
        match = re.match(r"(CAP-\d+)\s+-.*?\n", section)
        limitation = re.search(r"- \*\*Individual limitation:\*\* (.+)", section)
        prohibited = re.search(r"- \*\*Prohibited interpretation:\*\* (.+)", section)
        if match and limitation and prohibited:
            findings[match.group(1)] = (limitation.group(1), prohibited.group(1))
    return findings


def main() -> None:
    markdown = AUDIT.read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)\n```", markdown, re.DOTALL)
    assert block is not None
    audit = yaml.safe_load(block.group(1))["records"]
    prose = audit_prose(markdown)
    registry_path = ROOT / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for item in registry["items"]:
        record = audit.get(item["id"])
        if record is None:
            continue
        item["capability_status"] = record["status"]
        item["implementation_status"] = record["implementation_status"]
        item["epistemic_status"] = record["epistemic_status"]
        item["evidence_ids"] = record["evidence"]
        item["conflict_ids"] = record.get("conflicts", [])
        item["question_ids"] = record.get("questions", [])
        item.pop("implementation_carrier_ids", None)
        item.pop("derivation_id", None)
        item.pop("output_contract", None)
        if item["id"] in prose:
            limitation, prohibited = prose[item["id"]]
            item["definition"] = (
                f"{item['title']} is a source demand with audited partial or absent Phase 1 evidence; "
                "it is not an implemented aggregate or projection."
            )
            item["limitations"] = [limitation]
            item["prohibited_interpretations"] = [prohibited]
        else:
            title = item["title"]
            item["definition"] = (
                f"{title} cannot be established across the audited Phase 1 carrier boundaries."
            )
            item["limitations"] = [
                f"{title} has only carrier-specific inputs and no unified demand contract."
            ]
            item["prohibited_interpretations"] = [
                f"Do not treat a partial carrier as complete {title.lower()}."
            ]
        carriers = record["carriers"]
        if item["implementation_status"] == "absent":
            item["implementation_carrier_ids"] = []
            item["absence_basis"] = (
                f"The audit found no implemented carrier for the {item['title'].lower()} demand."
            )
            item["absence_verified"] = True
            if carriers:
                item["absence_contract_ids"] = carriers
            item["disqualifying_input_ids"] = record.get("disqualifying_inputs", [])
        else:
            item.pop("absence_basis", None)
            item.pop("absence_contract_ids", None)
            item["implementation_carrier_bindings"] = [
                {
                    "id": carrier,
                    "role": role(item["id"], carrier),
                    "semantic_type": semantic_type(carrier),
                    "evidence_ids": record["evidence"],
                }
                for carrier in carriers
            ]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    write_phase_two_projections(ROOT)


if __name__ == "__main__":
    main()
