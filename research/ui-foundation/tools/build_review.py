from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


BATCH_SIZE = 12
CONFLICT_STATUSES = frozenset({"unresolved", "resolved"})
CAPABILITY_STATUSES = frozenset({"current", "derived", "proposed", "gap", "unknown"})
CAPABILITY_CONFIDENCES = frozenset({"high", "medium", "low"})


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    blocking: bool
    downstream_dependency_count: int
    authority_risk: int
    capability_impact: int


class ReviewPriority(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    downstream_dependency_count: int = Field(ge=0)
    authority_risk: int = Field(ge=0, le=3)
    capability_impact: int = Field(ge=0, le=3)
    basis: str = Field(min_length=1)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"REVIEW_SOURCE_INVALID:{path}")
    return cast(dict[str, Any], value)


def _review_item(value: object, priority: ReviewPriority) -> ReviewItem:
    if not isinstance(value, dict):
        raise ValueError("REVIEW_ITEM_INVALID")
    item = cast(dict[str, Any], value)
    return ReviewItem.model_validate(
        {
            "id": item.get("id"),
            "blocking": item.get("blocking", False),
            "downstream_dependency_count": priority.downstream_dependency_count,
            "authority_risk": priority.authority_risk,
            "capability_impact": priority.capability_impact,
        }
    )


def _review_priorities(root: Path) -> dict[str, ReviewPriority]:
    document = _load_yaml(root / "catalog/review-priorities.yaml")
    methodology = document.get("methodology")
    raw_items = document.get("items")
    if (
        not isinstance(methodology, (str, dict))
        or not methodology
        or not isinstance(raw_items, list)
    ):
        raise ValueError("REVIEW_PRIORITY_CATALOG_INVALID")
    priorities: dict[str, ReviewPriority] = {}
    for value in cast(list[Any], raw_items):
        try:
            priority = ReviewPriority.model_validate(value)
        except ValidationError as error:
            raise ValueError("REVIEW_PRIORITY_INVALID") from error
        if priority.id in priorities:
            raise ValueError(f"REVIEW_PRIORITY_DUPLICATE:{priority.id}")
        priorities[priority.id] = priority
    return priorities


def select_review_items(root: Path) -> list[list[ReviewItem]]:
    document = _load_yaml(root / "catalog/questions.yaml")
    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("REVIEW_ITEMS_INVALID")
    item_values = cast(list[Any], raw_items)
    unresolved: dict[str, dict[str, Any]] = {}
    for value in item_values:
        if not isinstance(value, dict):
            raise ValueError("REVIEW_ITEM_INVALID")
        question = cast(dict[str, Any], value)
        identifier = question.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("REVIEW_ITEM_INVALID")
        if question.get("status") == "resolved":
            continue
        if identifier in unresolved:
            raise ValueError(f"REVIEW_QUESTION_DUPLICATE:{identifier}")
        unresolved[identifier] = question
    priorities = _review_priorities(root)
    missing = sorted(set(unresolved) - set(priorities))
    if missing:
        raise ValueError(f"REVIEW_PRIORITY_MISSING:{missing[0]}")
    extra = sorted(set(priorities) - set(unresolved))
    if extra:
        raise ValueError(f"REVIEW_PRIORITY_EXTRA:{extra[0]}")
    items = sorted(
        (
            _review_item(question, priorities[identifier])
            for identifier, question in unresolved.items()
        ),
        key=lambda item: (
            not item.blocking,
            -item.downstream_dependency_count,
            -item.authority_risk,
            -item.capability_impact,
            item.id,
        ),
    )
    blockers = [item for item in items if item.blocking]
    selected = blockers or items[:BATCH_SIZE]
    return [selected[index : index + BATCH_SIZE] for index in range(0, len(selected), BATCH_SIZE)]


def _catalog_records(root: Path, relative: str, code: str) -> dict[str, dict[str, Any]]:
    raw_items = _load_yaml(root / relative).get("items")
    if not isinstance(raw_items, list):
        raise ValueError(f"REVIEW_{code}_INVALID")
    records: dict[str, dict[str, Any]] = {}
    for raw_item in cast(list[Any], raw_items):
        if not isinstance(raw_item, dict):
            raise ValueError(f"REVIEW_{code}_INVALID")
        item = cast(dict[str, Any], raw_item)
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"REVIEW_{code}_INVALID")
        if identifier in records:
            raise ValueError(f"REVIEW_{code}_DUPLICATE:{identifier}")
        records[identifier] = item
    return records


def _string_list(value: object, code: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(code)
    values = cast(list[Any], value)
    if not all(isinstance(item, str) and item for item in values):
        raise ValueError(code)
    return [cast(str, item) for item in values]


def _evidence_detail(evidence: dict[str, Any], identifier: str) -> str:
    label = evidence.get("source_label")
    path = evidence.get("path")
    symbol = evidence.get("symbol")
    if not all(isinstance(value, str) and value for value in (label, path, symbol)):
        raise ValueError(f"REVIEW_EVIDENCE_INVALID:{identifier}")
    return f"{identifier} — {label} — {path} — {symbol}"


def _validate_review_catalog_vocabulary(
    conflicts: dict[str, dict[str, Any]], capabilities: dict[str, dict[str, Any]]
) -> None:
    for identifier, conflict in conflicts.items():
        if conflict.get("status") not in CONFLICT_STATUSES:
            raise ValueError(f"REVIEW_CONFLICT_STATUS_INVALID:{identifier}")
    for identifier, capability in capabilities.items():
        if capability.get("capability_status") not in CAPABILITY_STATUSES:
            raise ValueError(f"REVIEW_CAPABILITY_STATUS_INVALID:{identifier}")
        if capability.get("confidence") not in CAPABILITY_CONFIDENCES:
            raise ValueError(f"REVIEW_CAPABILITY_CONFIDENCE_INVALID:{identifier}")


def _review_data(root: Path, batch: list[ReviewItem], snapshot: str, number: int) -> dict[str, Any]:
    questions = _catalog_records(root, "catalog/questions.yaml", "ITEM")
    priorities = _review_priorities(root)
    conflicts = _catalog_records(root, "catalog/conflicts.yaml", "CONFLICT")
    capabilities = _catalog_records(root, "capabilities/registry.yaml", "CAPABILITY")
    evidence = _catalog_records(root, "catalog/evidence.yaml", "EVIDENCE")
    _validate_review_catalog_vocabulary(conflicts, capabilities)
    items: list[dict[str, Any]] = []
    for item in batch:
        question = questions.get(item.id)
        if question is None:
            raise ValueError(f"REVIEW_ITEM_MISSING:{item.id}")
        priority = priorities[item.id]
        affected = _string_list(
            question.get("affected_ids"), f"REVIEW_AFFECTED_IDS_INVALID:{item.id}"
        )
        related_conflicts = [
            conflict
            for conflict in conflicts.values()
            if conflict.get("status") == "unresolved"
            and set(affected).intersection(
                _string_list(
                    conflict.get("affected_ids"),
                    f"REVIEW_CONFLICT_AFFECTED_IDS_INVALID:{conflict['id']}",
                )
            )
        ]
        evidence_details: list[str] = []
        conflict_titles: list[str] = []
        competing_claims: list[str] = []
        for conflict in related_conflicts:
            conflict_id = cast(str, conflict["id"])
            title = conflict.get("title")
            if not isinstance(title, str) or not title:
                raise ValueError(f"REVIEW_CONFLICT_INVALID:{conflict_id}")
            conflict_titles.append(title)
            raw_claims = conflict.get("claims")
            if not isinstance(raw_claims, list):
                raise ValueError(f"REVIEW_CONFLICT_CLAIMS_INVALID:{conflict_id}")
            for raw_claim in cast(list[Any], raw_claims):
                if not isinstance(raw_claim, dict):
                    raise ValueError(f"REVIEW_CONFLICT_CLAIMS_INVALID:{conflict_id}")
                proposition = cast(dict[str, Any], raw_claim).get("proposition")
                if not isinstance(proposition, str) or not proposition:
                    raise ValueError(f"REVIEW_CONFLICT_CLAIMS_INVALID:{conflict_id}")
                competing_claims.append(proposition)
            for evidence_id in _string_list(
                conflict.get("decisive_evidence_ids"),
                f"REVIEW_CONFLICT_EVIDENCE_INVALID:{conflict_id}",
            ):
                evidence_record = evidence.get(evidence_id)
                if evidence_record is None:
                    raise ValueError(f"REVIEW_EVIDENCE_MISSING:{evidence_id}")
                evidence_details.append(_evidence_detail(evidence_record, evidence_id))
        capability_details: list[str] = []
        capability_statuses: list[str] = []
        capability_confidences: list[str] = []
        for capability_id in (
            identifier for identifier in affected if identifier.startswith("CAP-")
        ):
            capability = capabilities.get(capability_id)
            if capability is None:
                raise ValueError(f"REVIEW_CAPABILITY_MISSING:{capability_id}")
            title = capability.get("title")
            status = capability.get("capability_status")
            definition = capability.get("definition")
            confidence = capability.get("confidence")
            if (
                not isinstance(title, str)
                or not title
                or not isinstance(status, str)
                or not status
                or not isinstance(definition, str)
                or not definition
                or not isinstance(confidence, str)
                or not confidence
            ):
                raise ValueError(f"REVIEW_CAPABILITY_INVALID:{capability_id}")
            capability_details.append(f"{capability_id} {title} — {status}: {definition}")
            capability_statuses.append(status)
            capability_confidences.append(confidence)
        items.append(
            {
                "id": item.id,
                "title": question.get("title", item.id),
                "blocking": item.blocking,
                "importance": priority.basis,
                "interpretation": question.get(
                    "settlement_method", "No settlement method recorded."
                ),
                "support": "; ".join(evidence_details) if evidence_details else priority.basis,
                "uncertainty": (
                    f"{' ; '.join(conflict_titles)} — competing claims: {' ; '.join(competing_claims)}"
                    if competing_claims
                    else "No unresolved canonical conflict intersects this question's affected IDs."
                ),
                "consequence": f"Affects: {', '.join(affected)}.",
                "evidence_paths": evidence_details,
                "technical_details": (
                    f"Ranked with dependency count {item.downstream_dependency_count}, "
                    f"authority risk {item.authority_risk}, and capability impact {item.capability_impact}. "
                    f"Canonical capability impact: {'; '.join(capability_details) if capability_details else 'none'}."
                ),
                "capability_status": ", ".join(sorted(set(capability_statuses)))
                if capability_statuses
                else "not applicable",
                "confidence": ", ".join(sorted(set(capability_confidences)))
                if capability_confidences
                else "not applicable",
                "capability_impact": "; ".join(capability_details)
                if capability_details
                else "No affected canonical capability IDs.",
            }
        )
    return {
        "schema_version": "1",
        "review_version": "phase-3-01",
        "batch_id": f"{number:02d}",
        "source_snapshot": snapshot,
        "items": items,
    }


def _render_batch(data: dict[str, Any]) -> str:
    encoded = escape(json.dumps(data), quote=False)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reality &amp; capability review</title><style>
:root {{ color-scheme: light; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color:#192126; background:#f1eee6; }}
* {{ box-sizing:border-box; }} body {{ margin:0; padding:clamp(1rem,4vw,3rem); overflow-wrap:anywhere; }} main {{ max-width:72rem; margin:auto; }}
.masthead {{ border-left:.75rem solid #d15828; padding:1rem 1.25rem; background:#18252b; color:#f8f3e7; }} h1 {{ margin:.15rem 0; font-family:Georgia,serif; font-size:clamp(2rem,8vw,4.25rem); }} .eyebrow {{ text-transform:uppercase; letter-spacing:.12em; font-size:.76rem; }}
.notice {{ border:1px solid #b9aa86; padding:1rem; background:#fffaf0; margin:1rem 0; }} .toolbar {{ display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin:1rem 0; }} button {{ font:inherit; border:1px solid #49616a; background:#fbf6ea; color:#18252b; padding:.55rem .7rem; cursor:pointer; }} button[aria-pressed="true"] {{ background:#d15828; color:white; border-color:#d15828; }} button:focus-visible, textarea:focus-visible, summary:focus-visible {{ outline:3px solid #086c7c; outline-offset:3px; }}
.ledger {{ display:grid; gap:1rem; }} article {{ border:1px solid #49616a; border-top:5px solid #d15828; padding:1rem; background:#fffdf7; }} article[data-response] {{ border-top-color:#086c7c; }} .item-head {{ display:flex; justify-content:space-between; gap:.75rem; align-items:baseline; }} h2 {{ margin:0; font-family:Georgia,serif; }} .tag {{ background:#dce6df; padding:.15rem .4rem; font-size:.78rem; }} dl {{ display:grid; grid-template-columns:minmax(8rem, .32fr) 1fr; gap:.6rem 1rem; }} dt {{ font-weight:700; color:#48545a; }} dd {{ margin:0; }} .response-row {{ display:flex; flex-wrap:wrap; gap:.45rem; margin-top:1rem; }} textarea {{ width:100%; min-height:4rem; font:inherit; padding:.5rem; margin-top:.7rem; }} details {{ margin-top:1rem; border-top:1px dashed #889; padding-top:.7rem; }} .status {{ min-height:1.4em; color:#075b67; }} [hidden] {{ display:none !important; }}
@media (max-width: 390px) {{ body {{ padding:.75rem; }} .masthead {{ margin:0 -.1rem; }} dl {{ grid-template-columns:1fr; gap:.25rem; }} dd {{ margin-bottom:.75rem; }} .toolbar button {{ flex:1 1 42%; }} .response-row button {{ flex:1 1 42%; }} }}
</style></head><body><main><header class="masthead"><p class="eyebrow">Semantic foundation / Phase 3 / batch {escape(str(data["batch_id"]))}</p><h1>Reality &amp; capability review</h1><p>Decide the boundaries the implementation cannot decide for us.</p></header>
<p class="notice"><strong>Review checkpoint, not a product screen.</strong> Responses are local, exportable review evidence; they do not alter observed facts or capability classifications.</p>
<section class="toolbar" aria-label="Review controls"><span class="eyebrow">Show</span><button type="button" data-filter="all" aria-pressed="true">all responses</button><button type="button" data-filter="unresolved">unresolved</button><button type="button" data-filter="accept">accepted</button><button type="button" data-filter="reject">rejected</button><button type="button" data-filter="revise">revise</button><button type="button" data-filter="uncertain">uncertain</button><button type="button" data-export="json">Export JSON</button><button type="button" data-export="text">Export concise text</button></section>
<p class="status" aria-live="polite" data-status></p><section class="ledger" aria-label="Review items" data-ledger></section></main>
<script type="application/json" data-review-data>{encoded}</script><script>
(() => {{
 const keyPrefix='grounded-ui-foundation.review-feedback.v'; let data, state, ledger, status;
 const esc=(value)=>String(value).replace(/[&<>"]/g, c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
 const fail=(message)=>{{document.querySelector('main').innerHTML='<section role="alert" class="notice"><h1>Review initialization failed</h1><p>Generated review data is invalid. '+esc(message)+'</p><p>Regenerate this checkpoint from canonical catalogs before reviewing it.</p></section>';}};
 const load=(key)=>{{const raw=localStorage.getItem(key); if(!raw) return {{history:[], latest:{{}}, notes:{{}}}}; const saved=JSON.parse(raw); if(!Array.isArray(saved.history)) throw Error('Stored feedback history is malformed.'); return saved;}};
 const save=()=>localStorage.setItem(state.key, JSON.stringify(state));
 const responseLabel=(response)=>response === 'accept' ? 'accepted' : response || 'unresolved';
 const render=()=>{{const filter=document.querySelector('[data-filter][aria-pressed="true"]').dataset.filter; ledger.innerHTML=data.items.map(item=>{{const response=state.latest[item.id] || ''; const visible=filter==='all'||(filter==='unresolved'?!response:response===filter); return `<article data-review-item="${{esc(item.id)}}" data-response="${{esc(response)}}"${{visible?'':' hidden'}}><div class="item-head"><h2>${{esc(item.id)}} · ${{esc(item.title)}}</h2><button type="button" aria-label="Copy ${{esc(item.id)}}" data-copy="${{esc(item.id)}}">copy ID</button></div><p><span class="tag">${{item.blocking?'blocking':'non-blocking'}}</span> <span class="tag">capability: ${{esc(item.capability_status)}}</span> <span class="tag">confidence: ${{esc(item.confidence)}}</span></p><dl><dt>Why this matters</dt><dd>${{esc(item.importance)}}</dd><dt>Proposed interpretation</dt><dd>${{esc(item.interpretation)}}</dd><dt>What supports it</dt><dd>${{esc(item.support)}}</dd><dt>What remains uncertain</dt><dd>${{esc(item.uncertainty)}}</dd><dt>Consequence of accepting</dt><dd>${{esc(item.consequence)}}</dd><dt>Options</dt><dd>Accept the proposed settlement, reject it, request a revision, or retain explicit uncertainty.</dd></dl><div class="response-row" aria-label="Feedback for ${{esc(item.id)}}">${{['accept','reject','revise','uncertain'].map(choice=>`<button type="button" data-response-choice="${{choice}}" data-item="${{esc(item.id)}}" aria-pressed="${{String(response===choice)}}">${{choice}}</button>`).join('')}}</div><label>Note for ${{esc(item.id)}}<textarea aria-label="Note for ${{esc(item.id)}}" data-note="${{esc(item.id)}}">${{esc(state.notes[item.id]||'')}}</textarea></label><details><summary>Evidence paths and technical details</summary><p><strong>Paths:</strong> ${{item.evidence_paths.map(esc).join(', ')}}</p><p>${{esc(item.technical_details)}}</p></details></article>`;}}).join('');}};
 const record=(id,response)=>{{const note=state.notes[id]||''; const event={{item_id:id,response,note,recorded_at:new Date().toISOString()}}; state.history.push(event); state.latest[id]=response; save(); delete status.dataset.copyMethod; status.textContent=`${{id}} marked ${{responseLabel(response)}} locally.`; render(); queueMicrotask(()=>ledger.querySelector(`[data-item="${{id}}"][data-response-choice="${{response}}"]`)?.focus());}};
 const fallbackCopy=(value)=>{{const control=document.createElement('textarea'); control.value=value; control.setAttribute('aria-hidden','true'); control.style.cssText='position:fixed;opacity:0'; document.body.append(control); control.select(); const copied=document.execCommand('copy'); control.remove(); return copied;}};
 const copyId=async(id)=>{{try{{if(!navigator.clipboard?.writeText)throw Error('Clipboard API unavailable.'); await navigator.clipboard.writeText(id); status.dataset.copyMethod='clipboard'; status.dataset.copyValue=id; status.textContent=`${{id}} copied to clipboard.`;}}catch(_error){{if(fallbackCopy(id)){{status.dataset.copyMethod='fallback'; status.dataset.copyValue=id; status.textContent=`${{id}} copied using fallback.`;}}else{{delete status.dataset.copyMethod; delete status.dataset.copyValue; status.textContent=`${{id}} could not be copied. Select the ID and copy it manually.`;}}}}}};
 const exportFeedback=(kind)=>{{const payload={{schema_version:data.schema_version,review_version:data.review_version,batch_id:data.batch_id,source_snapshot:data.source_snapshot,exported_at:new Date().toISOString(),response_history:state.history}}; const text=kind==='json'?JSON.stringify(payload,null,2):state.history.map(event=>`${{event.item_id}} | ${{event.response}} | ${{event.note}}`).join('\\n'); const blob=new Blob([text],{{type:kind==='json'?'application/json':'text/plain'}}); const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=`phase-3-${{data.batch_id}}-feedback.${{kind==='json'?'json':'txt'}}`; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),0);}};
 window.foundationReview={{initialize}};
 function initialize() {{ try {{ data=JSON.parse(document.querySelector('[data-review-data]').textContent); if(!data || data.schema_version!=='1'||!Array.isArray(data.items)||!data.batch_id) throw Error('Required schema fields are missing.'); const key=`${{keyPrefix}}${{data.schema_version}}.${{data.review_version}}.${{data.batch_id}}`; state={{key, ...load(key)}}; ledger=document.querySelector('[data-ledger]'); status=document.querySelector('[data-status]'); render(); document.addEventListener('click', event=>{{const target=event.target.closest('button'); if(!target)return; if(target.dataset.responseChoice) record(target.dataset.item,target.dataset.responseChoice); if(target.dataset.filter){{document.querySelectorAll('[data-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button===target)));render();}} if(target.dataset.copy) copyId(target.dataset.copy); if(target.dataset.export) exportFeedback(target.dataset.export);}}); document.addEventListener('input', event=>{{const target=event.target; if(target.matches('[data-note]')){{state.notes[target.dataset.note]=target.value;save();}}}}); }} catch(error) {{ fail(error instanceof Error ? error.message : 'Unknown initialization error.'); }} }} initialize();
}})();</script></body></html>\n"""


def _render_index(snapshot: str, paths: list[Path]) -> str:
    links = "".join(
        f'<li><a href="{escape(path.name)}">{escape(path.stem.replace("-", " "))}</a></li>'
        for path in paths
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>UI Foundation Review Status</title></head><body><main><h1>Grounded UI/UX Foundation</h1><p><strong>Semantic foundation, not a product mockup.</strong></p><p>Phase 3 is <strong>complete-blocked</strong>: blocking reality and capability decisions remain for human review.</p><p>Source snapshot: <code>{escape(snapshot)}</code>. This index and its checkpoints do not prove future capabilities.</p><h2>Review batches</h2><ul>{links}</ul></main></body></html>\n"""


def build_review(root: Path) -> list[Path]:
    evidence = _load_yaml(root / "catalog/evidence.yaml")
    snapshot = evidence.get("active_snapshot_id")
    if not isinstance(snapshot, str) or not snapshot:
        raise ValueError("ACTIVE_SNAPSHOT_INVALID")
    rendered: list[tuple[str, str]] = []
    for number, batch in enumerate(select_review_items(root), start=1):
        name = f"phase-3-reality-capability-{number:02d}.html"
        rendered.append((name, _render_batch(_review_data(root, batch, snapshot, number))))
    output = root / "reviews"
    output.mkdir(parents=True, exist_ok=True)
    desired = {name for name, _content in rendered}
    for obsolete in [
        *output.glob("batch-[0-9][0-9].html"),
        *output.glob("phase-3-reality-capability-[0-9][0-9].html"),
    ]:
        if obsolete.name not in desired:
            obsolete.unlink()
    paths: list[Path] = []
    for name, content in rendered:
        path = output / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    (output / "index.html").write_text(_render_index(snapshot, paths), encoding="utf-8")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("research/ui-foundation"))
    args = parser.parse_args()
    for path in build_review(args.root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
