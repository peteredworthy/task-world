"""Guard tests: hand-maintained field mirrors in ``graph_runtime/store.py``.

Five constants/functions in that module carry field lists or field-copy logic
that duplicate a canonical typed model instead of deriving from it:
``SUMMARY_PAYLOAD_FIELDS``, ``BOOLEAN_PAYLOAD_FIELDS``,
``DECISION_RECORD_VALUE_FIELDS``, ``_RECORD_PAYLOAD_BASE_FIELDS`` (together
with ``_LEGACY_RECORD_METADATA_FIELDS``), and ``_lease_from_grant``. None of
these had a parity guard before this file -- exactly the defect class that
shipped the scheduler-view snapshot drift bug: an unguarded mirror silently
diverges from canonical kernel policy.

Building these guards found two live bugs, fixed alongside this file:
``BOOLEAN_PAYLOAD_FIELDS`` carried four dead entries (``approved``,
``stale_only``, ``supported``, ``unsupported`` -- none corresponds to any
field in the current schema; ``approved`` was likely confused with the
``decision`` enum's ``"approved"` literal value) and was missing two live
boolean fields that DO need SQLite 0/1-to-bool coercion
(``deleted_snapshot_ref``, ``rate_missing``).

Each guard below is a reflective set-comparison against the canonical typed
model(s) that actually own the field, not a second hand-maintained list --
so there is nothing left to keep in sync by hand.
"""

from __future__ import annotations

import ast
import inspect
import typing

from pydantic import BaseModel, RootModel

import orchestrator.graph as graph_models
from orchestrator.graph import (
    AuthorityDecisionValue,
    AuthorityRequestValue,
    DecisionRecordValue,
    DecisionRequestValue,
    EVENT_PAYLOAD_MODELS,
    LeaseGrantedPayload,
    TypedRecordBase,
)
from orchestrator.graph_runtime import store


# ---------------------------------------------------------------------------
# BOOLEAN_PAYLOAD_FIELDS
# ---------------------------------------------------------------------------


def _bool_typed_field_names() -> set[str]:
    """Every field name typed as ``bool`` (or ``bool | None``) anywhere in
    the public ``orchestrator.graph`` surface.

    Reflective rather than a hand list: walks every Pydantic model exported
    from the package and inspects each field's annotation.
    """
    names: set[str] = set()
    import orchestrator.graph as graph_pkg

    for attr_name in dir(graph_pkg):
        obj = getattr(graph_pkg, attr_name)
        if not (inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel):
            continue
        for field_name, field_info in obj.model_fields.items():
            annotation = field_info.annotation
            if annotation is bool or "bool" in str(annotation).lower():
                names.add(field_name)
    return names


def _fields_extracted_via_json_extract_coercion() -> set[str]:
    """Field names read through ``_read_run_extracting_fields`` -- the only
    call path that runs values through ``_json_extract_payload_value``
    (SQLite 0/1 -> Python ``bool`` coercion). ``SUMMARY_PAYLOAD_FIELDS`` and
    ``DECISION_RECORD_VALUE_FIELDS`` are read through a *different* helper
    (``_json_extract_value``, no boolean coercion) and are out of scope here.
    """
    from orchestrator.graph import (
        GRAPH_PROJECTION_PAYLOAD_FIELDS,
        LIGHT_GRAPH_PAYLOAD_FIELDS,
        NODE_DETAIL_PAYLOAD_FIELDS,
        SUMMARY_REBUILD_PAYLOAD_FIELDS,
    )

    return (
        set(GRAPH_PROJECTION_PAYLOAD_FIELDS)
        | set(LIGHT_GRAPH_PAYLOAD_FIELDS)
        | set(SUMMARY_REBUILD_PAYLOAD_FIELDS)
        | set(NODE_DETAIL_PAYLOAD_FIELDS)
    )


def test_boolean_payload_fields_matches_bool_typed_fields_in_scope() -> None:
    """``BOOLEAN_PAYLOAD_FIELDS`` must be exactly the bool-typed fields that
    are actually read through the coercing extraction path -- no dead
    entries (a field name that matches nothing, or matches a same-named
    field of a different type elsewhere), no missing entries (a real bool
    field silently returned as a raw SQLite integer).
    """
    bool_fields = _bool_typed_field_names()
    in_scope = _fields_extracted_via_json_extract_coercion()
    expected = bool_fields & in_scope

    assert set(store.BOOLEAN_PAYLOAD_FIELDS) == expected, (
        "BOOLEAN_PAYLOAD_FIELDS has drifted from the bool-typed fields actually "
        f"read via the coercing extraction path.\nmissing: "
        f"{sorted(expected - set(store.BOOLEAN_PAYLOAD_FIELDS))}\nstale/dead: "
        f"{sorted(set(store.BOOLEAN_PAYLOAD_FIELDS) - expected)}"
    )


# ---------------------------------------------------------------------------
# DECISION_RECORD_VALUE_FIELDS
# ---------------------------------------------------------------------------


def test_decision_record_value_fields_matches_the_four_typed_value_models() -> None:
    """``DECISION_RECORD_VALUE_FIELDS`` extracts the nested ``value`` object
    for records whose ``record_type``/``port`` is one of ``decision_record``,
    ``authority_decision``, ``decision_request``, or
    ``authority_request_record`` (see the ``record_type in {...}`` /
    ``port in {...}`` check in ``_read_run_extracting_fields``). Each of
    those four record kinds' ``value`` field is one canonical typed model
    (``DecisionRecordValue``, ``AuthorityDecisionValue``,
    ``DecisionRequestValue``, ``AuthorityRequestValue``) -- the allowlist
    must be exactly their field-name union.
    """
    expected = (
        set(DecisionRecordValue.model_fields)
        | set(AuthorityDecisionValue.model_fields)
        | set(DecisionRequestValue.model_fields)
        | set(AuthorityRequestValue.model_fields)
    )
    assert set(store.DECISION_RECORD_VALUE_FIELDS) == expected


# ---------------------------------------------------------------------------
# _RECORD_PAYLOAD_BASE_FIELDS / _LEGACY_RECORD_METADATA_FIELDS
# ---------------------------------------------------------------------------


def _typed_record_base_subclasses() -> list[type[BaseModel]]:
    return [
        obj
        for obj in vars(graph_models).values()
        if inspect.isclass(obj) and issubclass(obj, TypedRecordBase) and obj is not TypedRecordBase
    ]


def test_record_payload_base_fields_match_typed_record_base_envelope() -> None:
    """``_typed_record_payload`` strips envelope/base fields from a durable
    record's flat payload to isolate the domain ``value`` object, using
    ``_RECORD_PAYLOAD_BASE_FIELDS`` (the ``TypedRecordBase`` fields) plus
    ``_LEGACY_RECORD_METADATA_FIELDS`` (fields every concrete record
    subclass adds beyond the base: ``port``/``record_kind``/``schema``).

    Reflectively discovers every ``TypedRecordBase`` subclass rather than
    hardcoding the list, so a newly added record type is covered
    automatically instead of silently leaking its identity fields into the
    domain value on the day it's added.
    """
    subclasses = _typed_record_base_subclasses()
    assert len(subclasses) >= 15, (
        f"only {len(subclasses)} TypedRecordBase subclasses found -- "
        "did the reflective discovery break?"
    )

    base_fields = set(TypedRecordBase.model_fields)
    common_beyond_base: set[str] | None = None
    for cls in subclasses:
        own = set(cls.model_fields) - base_fields
        common_beyond_base = own if common_beyond_base is None else common_beyond_base & own

    assert common_beyond_base is not None
    alias_names: set[str] = set()
    for field_name in common_beyond_base:
        field_info = next(
            cls.model_fields[field_name] for cls in subclasses if field_name in cls.model_fields
        )
        alias_names.add(field_info.alias or field_name)

    expected = base_fields | alias_names
    actual = set(store._RECORD_PAYLOAD_BASE_FIELDS) | set(store._LEGACY_RECORD_METADATA_FIELDS)
    assert actual == expected, (
        "_RECORD_PAYLOAD_BASE_FIELDS | _LEGACY_RECORD_METADATA_FIELDS no longer "
        f"matches the TypedRecordBase envelope.\nmissing: {sorted(expected - actual)}"
        f"\nstale: {sorted(actual - expected)}"
    )


# ---------------------------------------------------------------------------
# _lease_from_grant
# ---------------------------------------------------------------------------


def _payload_key_literals(fn: object) -> set[str]:
    """``payload.get("k")`` / ``payload["k"]`` / ``for k in (...)`` literal
    keys read off a parameter named ``payload`` inside ``fn``.
    """
    tree = ast.parse(inspect.getsource(fn))
    fn_node = tree.body[0]
    assert isinstance(fn_node, ast.FunctionDef)

    def is_payload(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id == "payload"

    keys: set[str] = set()
    for node in ast.walk(fn_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and is_payload(node.func.value)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        if isinstance(node, ast.Subscript) and is_payload(node.value):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                keys.add(sl.value)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            iterable = node.iter
            if isinstance(iterable, ast.Tuple | ast.List | ast.Set):
                literal_keys = {
                    elt.value
                    for elt in iterable.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
                loop_var = node.target.id
                body_module = ast.Module(body=node.body, type_ignores=[])
                used = any(
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and is_payload(sub.func.value)
                    and sub.args
                    and isinstance(sub.args[0], ast.Name)
                    and sub.args[0].id == loop_var
                    for sub in ast.walk(body_module)
                )
                if used:
                    keys |= literal_keys
    return keys


def test_lease_from_grant_copies_every_lease_granted_payload_field() -> None:
    """``_lease_from_grant`` hand-copies fields off a ``lease_granted``
    event payload into the compact lease view. Every field on
    ``LeaseGrantedPayload`` must have a corresponding read in the function
    body -- otherwise a new lease attribute silently never reaches the
    ``GraphNodeDetailSummary.leases`` view.
    """
    read_keys = _payload_key_literals(store._lease_from_grant)
    expected = set(LeaseGrantedPayload.model_fields)
    assert read_keys == expected, (
        f"_lease_from_grant no longer reads exactly LeaseGrantedPayload's fields.\n"
        f"missing: {sorted(expected - read_keys)}\nstale: {sorted(read_keys - expected)}"
    )


# ---------------------------------------------------------------------------
# SUMMARY_PAYLOAD_FIELDS
# ---------------------------------------------------------------------------

_SUMMARY_EXTRA_FIELDS = {
    "blockers",
    "graph_verifier_grades",
    "patch_ops",
    "patch_rejection_reasons",
    "tokens_by_node",
    "tokens_by_node_kind",
}

# Event types whose compact event-timeline summary is genuinely empty today
# (summarize_graph_event's payload filter matches none of their fields).
# Traced by hand against SUMMARY_PAYLOAD_FIELDS + _SUMMARY_EXTRA_FIELDS on
# 2026-07-20; this test's job is to catch a new event type landing with zero
# summary coverage, not to relitigate these gaps. Remove an entry here (and
# add real coverage) rather than
# growing this list for a genuinely new gap.
_SUMMARY_KNOWN_EMPTY_EVENT_TYPES = {
    "input_bound",
    "support_evidence_recorded",
}


def _effective_payload_fields(model: type[BaseModel]) -> set[str]:
    """Field names actually present on the wire for an event payload model.

    Unwraps ``RootModel``-wrapped payloads (``file_state_accepted``,
    ``output_record_accepted``) to the flattened field names of their root
    type(s) -- ``model_fields`` on the ``RootModel`` itself only exposes a
    single synthetic ``root`` field, which would otherwise read as having no
    real fields at all.
    """
    if inspect.isclass(model) and issubclass(model, RootModel):
        annotation = model.model_fields["root"].annotation
        args = typing.get_args(annotation) or (annotation,)
        fields: set[str] = set()
        for arg in args:
            if inspect.isclass(arg) and issubclass(arg, BaseModel):
                fields |= set(arg.model_fields)
        return fields
    return set(model.model_fields)


def test_summary_payload_fields_covers_every_event_type_or_is_a_documented_gap() -> None:
    """Every canonical event type must intersect
    ``SUMMARY_PAYLOAD_FIELDS | _SUMMARY_EXTRA_FIELDS`` -- i.e. produce a
    non-empty compact event-timeline summary -- unless it's named in
    ``_SUMMARY_KNOWN_EMPTY_EVENT_TYPES`` with a reason on record above. This
    doesn't guarantee the *right* fields are chosen (that's a display/UX
    judgment), only that a newly introduced event type can't silently land
    with a permanently blank summary the way these three did.
    """
    covered = set(store.SUMMARY_PAYLOAD_FIELDS) | _SUMMARY_EXTRA_FIELDS

    newly_empty: list[str] = []
    for event_type, model in EVENT_PAYLOAD_MODELS.items():
        if event_type in _SUMMARY_KNOWN_EMPTY_EVENT_TYPES:
            continue
        fields = _effective_payload_fields(model)
        edge_covered = event_type == "edge_created" and bool(
            fields & set(store.SUMMARY_EDGE_FIELDS)
        )
        if not (fields & covered) and not edge_covered:
            newly_empty.append(event_type)

    assert not newly_empty, (
        "these event types produce an empty summarize_graph_event() payload and "
        "are not in the documented _SUMMARY_KNOWN_EMPTY_EVENT_TYPES exclusion "
        f"list -- add real SUMMARY_PAYLOAD_FIELDS coverage or document why not: "
        f"{sorted(newly_empty)}"
    )

    stale_exclusions = [
        event_type
        for event_type in _SUMMARY_KNOWN_EMPTY_EVENT_TYPES
        if event_type in EVENT_PAYLOAD_MODELS
        and (_effective_payload_fields(EVENT_PAYLOAD_MODELS[event_type]) & covered)
    ]
    assert not stale_exclusions, (
        "these event types now have real summary coverage -- remove them from "
        f"_SUMMARY_KNOWN_EMPTY_EVENT_TYPES so the exclusion list stays honest: "
        f"{sorted(stale_exclusions)}"
    )
