"""Guard test: static coverage check for graph event-store payload allowlists.

``src/orchestrator/graph_runtime/store.py`` hand-maintains ``json_extract``
field allowlists (``GRAPH_PROJECTION_PAYLOAD_FIELDS`` and friends) that let
compact graph reads (``read_run_projection`` et al.) pull only the payload
keys the projection fold actually needs, instead of validating the full
``EventEnvelope`` JSON body. If someone teaches ``reduce_event`` (in
``src/orchestrator/graph/projections.py``) to read a new payload key but
forgets to mirror it into the matching allowlist, the compact read silently
diverges from a full replay: the field is simply absent from the filtered
payload dict. This has happened twice in this codebase (a missing
``attempt_number``, then a missing ``decision``/``gate_id``/``approved``/
``appeal_type`` -- see commit 4f2cb0f58 and
``docs/dynamic-graph/dynamic-graph-implementation-review.html`` P0 #1).

This test closes the gap mechanically for ``GRAPH_PROJECTION_PAYLOAD_FIELDS``,
the allowlist backing ``read_run_projection`` -> ``project_task_states`` (the
``/{run_id}/graph`` endpoint's ``task_states`` field). It:

1. Parses ``projections.py`` with ``ast`` and builds a call graph of its
   module-level functions.
2. Computes every function transitively reachable from ``reduce_event`` --
   the single fold function shared by every consumer of
   ``read_run_projection``-backed events (today: ``project_task_states``; if
   a second consumer is added later it also runs through ``reduce_event``,
   so scoping to its call closure does not need to be revisited when that
   happens). Functions *outside* this closure operate on separately-filtered
   event lists (``read_run_light``, ``read_run_summary_rebuild``,
   ``read_run_node_detail``, full ``read_run``) or on already-materialized
   ``GraphProjection`` state, and are governed by their own allowlists
   (``LIGHT_GRAPH_PAYLOAD_FIELDS``, ``SUMMARY_REBUILD_PAYLOAD_FIELDS``,
   ``NODE_DETAIL_PAYLOAD_FIELDS``) -- not this test's concern.
3. Within that closure, over-approximates every string key read via
   ``.get("key")`` / ``["key"]`` on an expression named or attributed
   ``payload`` (covers ``event.payload.get(...)``, a local ``payload =
   event.payload`` alias, and helper functions taking a ``payload: dict``
   parameter), plus two secondary idioms actually used by this module:
   ``for key in ("a", "b"): ...payload.get(key)`` (a fixed tuple of literal
   keys probed dynamically -- inline, or named via a module-level constant
   tuple such as ``for key in _EDGE_METADATA_KEYS:``), and calls to small
   helpers whose own body does ``payload.get(key)`` for a caller-supplied
   ``key`` parameter (e.g. ``_payload_string_list(payload, "node_ids")``).
4. Asserts every extracted key is either in ``GRAPH_PROJECTION_PAYLOAD_FIELDS``
   or in the ``_EXCLUDED_KEYS`` map below, with a one-line reason.

Why over-approximate the whole ``reduce_event`` closure rather than slice
down to exactly the state fields ``_derive_task_states`` reads: several
writer functions mutate an already-fetched substate entry in place (e.g.
``_record_cleanup_requested``/``_record_gatekeeper_verdicts`` mutate the
typed file-state record stored by ``_record_file_state``). A
call-graph slice keyed on assignment targets misses those silently. Rather
than trust a second, harder-to-verify layer of static analysis for a
narrower scope, this test accepts a larger, honestly-justified exclusion
list built from manual tracing (see ``_EXCLUDED_KEYS``) instead.

One known blind spot from that same wholesale-copy pattern: ``verdict`` is
read downstream as ``record.get("verdict")`` off the *copied* dict inside
``_task_file_state_accepted``, never as ``event.payload.get("verdict")`` or
``payload["verdict"]`` -- so it is invisible to the AST patterns above no
matter how the closure is scoped. It is asserted separately below.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from orchestrator.graph import projections
from orchestrator.graph_runtime import store
from orchestrator.graph_runtime.store import GRAPH_PROJECTION_PAYLOAD_FIELDS

_PROJECTIONS_PATH = Path(inspect.getfile(projections))
_ROOT_FUNCTION = "reduce_event"

# Keys read by the reduce_event fold closure that do NOT need to be in
# GRAPH_PROJECTION_PAYLOAD_FIELDS, because they feed GraphProjection
# substates project_task_states / _derive_task_states never reads (e.g.
# scheduler, requirement/support, planner, cleanup, decision, and topology
# metadata substates). Each reason names the substate/consumer the key
# actually feeds. Traced by hand against _derive_task_states and its
# transitive callees in projections.py; see the module docstring above for
# why this is a manually-verified list rather than a second static slice.
_EXCLUDED_KEYS: dict[str, str] = {
    "accepted_record_selector": "edges: binding-selector metadata; recovery-lineage traversal "
    "only reads from_node_id/to_node_id",
    "active": "requirement_revisions/active_requirement_versions bookkeeping",
    "authority_required_reason": "requirement_revisions / decision_request_details bookkeeping",
    "behavior_change": "requirement revision classification helper, not task_states",
    "binding_policy": "_EDGE_METADATA_KEYS: topology-view-only edge metadata (_topology_edge); "
    "not read by _derive_task_states/_task_file_state_accepted/_downstream_node_ids",
    "change_classification": "requirement_revisions bookkeeping",
    "confidence": "support_evidence bookkeeping",
    "dependency_type": "edges metadata; downstream traversal only uses from_node_id/to_node_id",
    "description": "_EDGE_METADATA_KEYS: topology-view-only edge metadata (see binding_policy)",
    "edge_id": "edges dict key/metadata; not read by the recovery-lineage traversal helper",
    "evidence_id": "support_evidence bookkeeping",
    "explicit_authority_required": "requirement revision authority-resolution bookkeeping",
    "from_node_kind": "edges metadata; recovery-lineage traversal only reads "
    "from_node_id/to_node_id",
    "from_node_role": "edges metadata; recovery-lineage traversal only reads "
    "from_node_id/to_node_id",
    "freshness_policy": "_EDGE_METADATA_KEYS: topology-view-only edge metadata "
    "(see binding_policy)",
    "id": "requirement id fallback helper, used only for authority_revision_blockers/support views",
    "metadata": "_EDGE_METADATA_KEYS: topology-view-only edge metadata (see binding_policy)",
    "new_behavior": "requirement revision classification helper",
    "patch_id": "accepted_no_successor_patches_by_node / graph-patch-attempt bookkeeping",
    "previous_version_id": "requirement_revisions bookkeeping",
    "proposal_id": "open_proposal_blockers bookkeeping",
    "prompt_hydration_policy": "_EDGE_METADATA_KEYS: topology-view-only edge metadata "
    "(see binding_policy)",
    "purpose": "_EDGE_METADATA_KEYS: topology-view-only edge metadata (see binding_policy)",
    "required": 'edges metadata ("required" flag); traversal helper ignores it',
    "requirement": "requirement id/priority resolution helper, not task_states",
    "requirement_id": "requirement_revisions/authority_revision_blockers bookkeeping",
    "requirement_version_id": "requirement_revisions bookkeeping",
    "requires_authority": "requirement_revisions authority-resolution bookkeeping",
    "revision_id": "authority_revision_blockers bookkeeping",
    "revision_index": "requirement_revisions bookkeeping",
    "revision_type": "requirement revision classification helper",
    "selection": "_EDGE_METADATA_KEYS: topology-view-only edge metadata (see binding_policy)",
    "semantic_change": "requirement revision authority-resolution bookkeeping",
    "stale_reason": "support_evidence bookkeeping",
    "support_id": "support_evidence bookkeeping",
    "validation_strengthening": "requirement_revisions bookkeeping",
    "version_id": "requirement_revisions bookkeeping",
}


def test_graph_projection_payload_fields_are_owned_by_projection_module() -> None:
    """The compact projection allowlist must live with the reducer that reads it."""
    assert store.GRAPH_PROJECTION_PAYLOAD_FIELDS is projections.GRAPH_PROJECTION_PAYLOAD_FIELDS


def _is_payload_expr(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "payload") or (
        isinstance(node, ast.Name) and node.id == "payload"
    )


def _module_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(_PROJECTIONS_PATH.read_text())
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _module_string_constants() -> dict[str, list[str]]:
    """Module-level ``NAME = ("a", "b", ...)`` string-tuple/list/set constants.

    Needed so ``for key in _EDGE_METADATA_KEYS: ... payload[key]`` resolves the
    same way an inline literal tuple does.
    """
    tree = ast.parse(_PROJECTIONS_PATH.read_text())
    constants: dict[str, list[str]] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None or not isinstance(value, ast.Tuple | ast.List | ast.Set):
            continue
        literals = [
            elt.value
            for elt in value.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
        if not literals or len(literals) != len(value.elts):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = literals
    return constants


def _call_graph(funcs: dict[str, ast.FunctionDef]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for name, fn in funcs.items():
        callees = {
            node.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in funcs
        }
        graph[name] = callees
    return graph


def _reachable_from(root: str, call_graph: dict[str, set[str]]) -> set[str]:
    reached: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in reached:
            continue
        reached.add(current)
        stack.extend(call_graph.get(current, ()) - reached)
    return reached


def _direct_literal_keys(fn: ast.FunctionDef) -> set[str]:
    """``payload.get("k")`` / ``payload["k"]`` with a literal string key."""
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and _is_payload_expr(func.value)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
        if isinstance(node, ast.Subscript) and _is_payload_expr(node.value):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                keys.add(sl.value)
    return keys


def _loop_probed_keys(
    fn: ast.FunctionDef,
    module_constants: dict[str, list[str]],
) -> set[str]:
    """``for key in ("a", "b"): ... payload.get(key)`` -- a literal-tuple probe.

    The iterable may be an inline tuple/list/set literal or the name of a
    module-level string-tuple constant (e.g. ``_EDGE_METADATA_KEYS``),
    resolved via ``module_constants``.
    """
    keys: set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.For) and isinstance(node.target, ast.Name)):
            continue
        loop_var = node.target.id
        iterable = node.iter
        literals: list[str]
        if isinstance(iterable, ast.Tuple | ast.List | ast.Set):
            literals = [
                elt.value
                for elt in iterable.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
        elif isinstance(iterable, ast.Name) and iterable.id in module_constants:
            literals = module_constants[iterable.id]
        else:
            continue
        if not literals:
            continue
        body_module = ast.Module(body=node.body, type_ignores=[])
        used = False
        for sub in ast.walk(body_module):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "get"
                and _is_payload_expr(sub.func.value)
                and sub.args
                and isinstance(sub.args[0], ast.Name)
                and sub.args[0].id == loop_var
            ):
                used = True
            if isinstance(sub, ast.Subscript) and _is_payload_expr(sub.value):
                sl = sub.slice
                if isinstance(sl, ast.Name) and sl.id == loop_var:
                    used = True
        if used:
            keys.update(literals)
    return keys


def _dynamic_key_helper_params(
    scoped_names: set[str],
    funcs: dict[str, ast.FunctionDef],
) -> dict[str, int]:
    """Helpers of the form ``def f(payload, key): ... payload.get(key)``.

    Returns a mapping of helper function name -> positional index of its
    dynamic-key parameter.
    """
    dynamic: dict[str, int] = {}
    for name in scoped_names:
        fn = funcs[name]
        params = [a.arg for a in fn.args.args]
        if "payload" not in params:
            continue
        for node in ast.walk(fn):
            key_arg: ast.expr | None = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "payload"
                and node.args
            ):
                key_arg = node.args[0]
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "payload"
            ):
                key_arg = node.slice
            if isinstance(key_arg, ast.Name) and key_arg.id in params and key_arg.id != "payload":
                dynamic[name] = params.index(key_arg.id)
    return dynamic


def _helper_call_site_keys(
    scoped_names: set[str],
    funcs: dict[str, ast.FunctionDef],
    dynamic_key_funcs: dict[str, int],
) -> set[str]:
    keys: set[str] = set()
    for name in scoped_names:
        fn = funcs[name]
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            callee = node.func.id
            if callee not in dynamic_key_funcs:
                continue
            idx = dynamic_key_funcs[callee]
            if (
                idx < len(node.args)
                and isinstance(node.args[idx], ast.Constant)
                and isinstance(node.args[idx].value, str)
            ):
                keys.add(node.args[idx].value)
            callee_params = funcs[callee].args.args
            if idx < len(callee_params):
                param_name = callee_params[idx].arg
                for kw in node.keywords:
                    if (
                        kw.arg == param_name
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        keys.add(kw.value.value)
    return keys


def _extract_reduce_event_payload_keys() -> set[str]:
    funcs = _module_functions()
    assert _ROOT_FUNCTION in funcs, (
        f"{_ROOT_FUNCTION} not found as a module-level function in projections.py -- "
        "has it been renamed or moved? Update _ROOT_FUNCTION."
    )
    call_graph = _call_graph(funcs)
    scoped = _reachable_from(_ROOT_FUNCTION, call_graph)
    module_constants = _module_string_constants()

    keys: set[str] = set()
    for name in scoped:
        fn = funcs[name]
        keys |= _direct_literal_keys(fn)
        keys |= _loop_probed_keys(fn, module_constants)

    dynamic_key_funcs = _dynamic_key_helper_params(scoped, funcs)
    keys |= _helper_call_site_keys(scoped, funcs, dynamic_key_funcs)
    return keys


def test_reduce_event_closure_extraction_finds_a_plausible_number_of_functions_and_keys() -> None:
    """Sanity check that the AST walk isn't silently matching nothing.

    If projections.py is refactored so heavily that this drops to near zero,
    the coverage assertion below would trivially pass without guarding
    anything -- so pin a floor.
    """
    funcs = _module_functions()
    call_graph = _call_graph(funcs)
    scoped = _reachable_from(_ROOT_FUNCTION, call_graph)
    assert len(scoped) >= 20, (
        f"only {len(scoped)} functions reachable from {_ROOT_FUNCTION!r}; "
        "expected the reduce_event fold to have a substantial call closure -- "
        "did the AST extraction break?"
    )
    keys = _extract_reduce_event_payload_keys()
    assert len(keys) >= 40, (
        f"only {len(keys)} payload keys extracted from the reduce_event closure; "
        "expected many more -- did the AST extraction break?"
    )


def test_graph_projection_payload_fields_cover_the_reduce_event_fold() -> None:
    """Every payload key the reduce_event fold reads is allowlisted or excluded.

    See the module docstring for the extraction methodology and
    ``_EXCLUDED_KEYS`` for why each excluded key is safe to omit from
    ``GRAPH_PROJECTION_PAYLOAD_FIELDS``.
    """
    extracted = _extract_reduce_event_payload_keys()
    allowlisted = set(GRAPH_PROJECTION_PAYLOAD_FIELDS)
    excluded = set(_EXCLUDED_KEYS)

    uncovered = extracted - allowlisted - excluded
    assert not uncovered, (
        "reduce_event reads these payload keys but GRAPH_PROJECTION_PAYLOAD_FIELDS "
        "does not carry them and no exclusion justifies skipping them -- either add "
        "them to GRAPH_PROJECTION_PAYLOAD_FIELDS in store.py (if they affect "
        "task_states) or add a one-line-justified entry to _EXCLUDED_KEYS in this "
        f"test: {sorted(uncovered)}"
    )

    stale_exclusions = excluded - extracted
    assert not stale_exclusions, (
        "these _EXCLUDED_KEYS entries are no longer read by the reduce_event "
        f"closure at all -- remove them so the exclusion set stays honest: "
        f"{sorted(stale_exclusions)}"
    )


def test_verdict_field_is_allowlisted_despite_being_invisible_to_ast_extraction() -> None:
    """``_record_file_state`` copies ``event.payload`` wholesale into
    ``state["file_state_records"][record_id]`` via ``dict(record)`` rather
    than selecting named fields. ``_task_file_state_accepted`` later reads
    ``record.get("verdict")`` off that *copied* dict, not off ``payload``
    directly, so no AST pattern matching ``payload.get(...)`` can ever see
    this dependency. Pin it explicitly so the wholesale-copy blind spot
    doesn't silently regress.
    """
    assert "verdict" in GRAPH_PROJECTION_PAYLOAD_FIELDS
