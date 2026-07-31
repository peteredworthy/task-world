"""Tests for immutable graph projection collection primitives."""

from collections import UserDict
from collections.abc import Iterator, Mapping
from math import inf, nan
from types import MappingProxyType
import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from orchestrator.graph import (
    FrozenJsonValueError,
    FrozenMap,
    FrozenJsonValue,
    JsonValue,
    empty_frozen_map,
    freeze_json,
    map_delete,
    map_set,
    map_update,
    thaw_json,
)


class CustomMapping(Mapping[str, int]):
    def __getitem__(self, key: str) -> int:
        return {"one": 1}[key]

    def __iter__(self) -> Iterator[str]:
        return iter(("one",))

    def __len__(self) -> int:
        return 1


class FrozenMapSubclass(FrozenMap[str, int]):
    pass


def test_map_set_returns_a_new_map_without_changing_old_map() -> None:
    old = FrozenMap({"a": 1})

    new = map_set(old, "b", 2)

    assert dict(old) == {"a": 1}
    assert dict(new) == {"a": 1, "b": 2}


def test_map_delete_and_update_leave_the_old_map_unchanged() -> None:
    old = FrozenMap({"a": 1, "b": 2})

    deleted = map_delete(old, "a")
    updated = map_update(old, {"b": 3, "c": 4})

    assert dict(old) == {"a": 1, "b": 2}
    assert dict(deleted) == {"b": 2}
    assert dict(updated) == {"a": 1, "b": 3, "c": 4}


def test_empty_frozen_map_is_an_empty_mapping() -> None:
    assert dict(empty_frozen_map()) == {}


def test_frozen_map_exposes_only_immutable_mapping_operations() -> None:
    value = FrozenMap({"a": 1})

    assert value["a"] == 1
    assert len(value) == 1
    assert list(value) == ["a"]
    assert not hasattr(value, "set")
    assert not hasattr(value, "delete")
    assert not hasattr(value, "mutate")


def test_frozen_map_membership_reports_present_and_missing_keys() -> None:
    value = FrozenMap({"present": 1})

    assert "present" in value
    assert "missing" not in value


def test_frozen_map_has_mapping_equality_and_readable_repr() -> None:
    value = FrozenMap({"a": 1})

    assert value == FrozenMap({"a": 1})
    assert value == {"a": 1}
    assert value != {"a": 2}
    assert repr(value) == "FrozenMap({'a': 1})"


@pytest.mark.parametrize(
    "value",
    [
        UserDict({"one": 1}),
        MappingProxyType({"one": 1}),
        CustomMapping(),
    ],
)
def test_frozen_map_constructor_rejects_non_dict_external_mappings(
    value: Mapping[str, int],
) -> None:
    with pytest.raises(TypeError, match="exact dict or FrozenMap"):
        FrozenMap(value)


def test_frozen_map_constructor_accepts_exact_dict_and_existing_frozen_map() -> None:
    original = FrozenMap({"one": 1})

    assert FrozenMap({"one": 1}) == {"one": 1}
    assert FrozenMap(original) == {"one": 1}


def test_frozen_map_subclasses_are_rejected_at_public_boundaries() -> None:
    subclass = FrozenMapSubclass({"one": 1})

    with pytest.raises(TypeError, match="exact dict or FrozenMap"):
        FrozenMap(subclass)
    with pytest.raises(ValidationError, match="exact dict or FrozenMap"):
        TypeAdapter(FrozenMap[str, int]).validate_python(subclass)


def test_frozen_map_pydantic_validates_declared_key_and_value_types() -> None:
    adapter = TypeAdapter(FrozenMap[str, int])

    value = adapter.validate_python({"one": "1", "two": 2})

    assert value == {"one": 1, "two": 2}
    with pytest.raises(ValidationError):
        adapter.validate_python({1: "1"})


@pytest.mark.parametrize(
    "source",
    [
        {"one": "not-an-integer"},
        FrozenMap({"one": "not-an-integer"}),
        {1: 1},
        FrozenMap({1: 1}),
    ],
)
def test_frozen_map_pydantic_validates_dict_and_existing_map_children(
    source: object,
) -> None:
    adapter = TypeAdapter(FrozenMap[str, int])

    with pytest.raises(ValidationError):
        adapter.validate_python(source)


def test_frozen_map_pydantic_reconstructs_model_children() -> None:
    class Child(BaseModel):
        model_config = {"frozen": True, "revalidate_instances": "always"}
        names: tuple[str, ...]

    class UntrustedChild(Child):
        pass

    source_names = ["one"]
    source_child = UntrustedChild(names=source_names)
    value = TypeAdapter(FrozenMap[str, Child]).validate_python(FrozenMap({"child": source_child}))

    source_names.append("mutated")
    assert type(value["child"]) is Child
    assert value["child"] is not source_child
    assert value["child"].names == ("one",)


@pytest.mark.parametrize("frozen", [False, True])
def test_frozen_map_validation_isolates_mutable_input(frozen: bool) -> None:
    source_names = ["one"]
    source: object = {"names": source_names}
    if frozen:
        source = FrozenMap({"names": source_names})
    value = TypeAdapter(FrozenMap[str, tuple[str, ...]]).validate_python(source)

    source_names.append("mutated")
    assert value == {"names": ("one",)}


@pytest.mark.parametrize(
    "value",
    [UserDict({"one": 1}), MappingProxyType({"one": 1}), CustomMapping()],
)
def test_frozen_map_pydantic_rejects_non_dict_external_mappings(value: object) -> None:
    adapter = TypeAdapter(FrozenMap[str, int])

    with pytest.raises(ValidationError):
        adapter.validate_python(value)


def test_frozen_map_pydantic_serializes_as_an_ordinary_dictionary() -> None:
    class Model(BaseModel):
        values: FrozenMap[str, int]

    model = Model(values={"one": 1})

    assert model.model_dump() == {"values": {"one": 1}}
    assert model.model_dump_json() == '{"values":{"one":1}}'

    revalidated = Model(values=FrozenMap({"one": 1}))
    assert revalidated.model_dump_json() == '{"values":{"one":1}}'


def test_frozen_json_rejects_cycles_and_non_string_keys() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)

    with pytest.raises(FrozenJsonValueError, match="cycle"):
        freeze_json(cyclic)
    with pytest.raises(FrozenJsonValueError, match="string keys"):
        freeze_json({1: "bad"})


def test_frozen_json_round_trips_normal_json() -> None:
    value = {"nested": [1, True, None, {"name": "x"}]}

    frozen = freeze_json(value)

    assert isinstance(frozen, FrozenMap)
    assert isinstance(frozen["nested"], tuple)
    assert thaw_json(frozen) == value


def test_thaw_json_rejects_frozen_map_subclasses() -> None:
    with pytest.raises(FrozenJsonValueError, match="expected a frozen JSON value"):
        thaw_json(FrozenMapSubclass({"one": 1}))


def test_thaw_json_rejects_non_string_map_keys() -> None:
    with pytest.raises(FrozenJsonValueError, match="string keys"):
        thaw_json(FrozenMap({1: "bad"}))


def test_thaw_json_rejects_unsupported_scalar_objects() -> None:
    with pytest.raises(FrozenJsonValueError, match="expected a frozen JSON value"):
        thaw_json(object())


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_thaw_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(FrozenJsonValueError, match="finite"):
        thaw_json(value)


@pytest.mark.parametrize("value", [None, False, True, 0, -2, 1.5, "text"])
def test_frozen_json_accepts_canonical_scalars(value: object) -> None:
    assert thaw_json(freeze_json(value)) == value


def test_frozen_json_preserves_booleans_without_integer_coercion() -> None:
    frozen = freeze_json(True)

    assert type(frozen) is bool


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_frozen_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(FrozenJsonValueError, match="finite"):
        freeze_json(value)


@pytest.mark.parametrize(
    "value",
    [b"bytes", {1, 2}, UserDict({"key": "value"}), object()],
)
def test_frozen_json_rejects_non_json_objects(value: object) -> None:
    with pytest.raises(FrozenJsonValueError, match="canonical JSON"):
        freeze_json(value)


def test_frozen_json_rejects_bool_as_an_integer_subclass() -> None:
    class IntegerSubclass(int):
        pass

    with pytest.raises(FrozenJsonValueError, match="canonical JSON"):
        freeze_json(IntegerSubclass(1))


def test_frozen_json_accepts_tuples_and_thaws_them_to_lists() -> None:
    assert thaw_json(freeze_json((1, {"two": 2}))) == [1, {"two": 2}]


def test_frozen_json_rejects_depth_greater_than_100() -> None:
    at_limit: object = None
    for _ in range(100):
        at_limit = [at_limit]
    too_deep: object = [at_limit]

    assert thaw_json(freeze_json(at_limit)) == at_limit
    with pytest.raises(FrozenJsonValueError, match="depth"):
        freeze_json(too_deep)


def test_frozen_json_allows_repeated_non_cyclic_containers() -> None:
    shared = [1, 2]

    assert thaw_json(freeze_json([shared, shared])) == [[1, 2], [1, 2]]


def test_public_json_aliases_describe_input_and_frozen_values() -> None:
    input_value: JsonValue = {"key": [1]}
    frozen_value: FrozenJsonValue = freeze_json(input_value)

    assert thaw_json(frozen_value) == input_value


def test_thaw_json_returns_fresh_mutable_results() -> None:
    frozen = freeze_json({"nested": [1]})

    first = thaw_json(frozen)
    second = thaw_json(frozen)
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    first_nested = first["nested"]
    assert isinstance(first_nested, list)
    first_nested.append(2)

    assert second == {"nested": [1]}
    assert thaw_json(frozen) == {"nested": [1]}
