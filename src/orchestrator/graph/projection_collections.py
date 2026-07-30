"""Persistent collection primitives for graph projections."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from math import isfinite
from typing import Any, cast, get_args

from immutables import Map
from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class FrozenMap[K, V](Mapping[K, V]):
    """A read-only mapping backed by a persistent hash-array mapped trie."""

    __slots__ = ("__map",)

    def __init__(self, values: dict[K, V] | FrozenMap[K, V] | None = None) -> None:
        self.__map: Map[K, V]
        if values is None:
            self.__map = cast(Map[K, V], Map())
        elif type(values) is dict:
            self.__map = Map(values)
        elif type(values) is FrozenMap:
            self.__map = cast(Map[K, V], object.__getattribute__(values, "_FrozenMap__map"))
        else:
            raise TypeError("FrozenMap input must be an exact dict or FrozenMap")

    def __getitem__(self, key: K) -> V:
        return self.__map[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self.__map)

    def __len__(self) -> int:
        return len(self.__map)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return NotImplemented
        other_mapping = cast(Mapping[object, object], other)
        return dict(self) == dict(other_mapping)

    def __repr__(self) -> str:
        return f"FrozenMap({dict(self)!r})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        """Validate generic key/value parameters and serialize as a plain dict."""
        arguments = get_args(source_type)
        key_schema = (
            handler.generate_schema(arguments[0]) if arguments else core_schema.any_schema()
        )
        value_schema = (
            handler.generate_schema(arguments[1])
            if len(arguments) > 1
            else core_schema.any_schema()
        )
        dictionary_schema = core_schema.dict_schema(
            keys_schema=key_schema,
            values_schema=value_schema,
        )
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.no_info_before_validator_function(
                _mapping_to_dict,
                dictionary_schema,
            ),
            serialization=core_schema.wrap_serializer_function_ser_schema(
                _serialize_frozen_map,
                schema=dictionary_schema,
            ),
        )


def _serialize_frozen_map(
    value: FrozenMap[Any, Any],
    handler: core_schema.SerializerFunctionWrapHandler,
) -> Any:
    return handler(dict(value))


def _mapping_to_dict(value: object) -> object:
    """Accept only external dictionaries and persistent-map revalidation."""
    if type(value) is FrozenMap:
        return dict(cast(Mapping[object, object], value))
    if type(value) is dict:
        return cast(dict[object, object], value)
    raise ValueError("FrozenMap input must be an exact dict or FrozenMap")


type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | tuple[JsonValue, ...] | dict[str, JsonValue]
type FrozenJsonValue = JsonScalar | tuple[FrozenJsonValue, ...] | FrozenMap[str, FrozenJsonValue]


class FrozenJsonValueError(ValueError):
    """Raised when a value is outside the supported immutable JSON domain."""


def empty_frozen_map() -> FrozenMap[Any, Any]:
    """Return an empty persistent mapping."""
    return FrozenMap()


def _frozen_map_from_backend[K, V](backend: Map[K, V]) -> FrozenMap[K, V]:
    mapping = cast(FrozenMap[K, V], object.__new__(FrozenMap))
    object.__setattr__(mapping, "_FrozenMap__map", backend)
    return mapping


def map_set[K, V](mapping: FrozenMap[K, V], key: K, value: V) -> FrozenMap[K, V]:
    """Return ``mapping`` with ``key`` set without changing the original."""
    backend = cast(Map[K, V], object.__getattribute__(mapping, "_FrozenMap__map"))
    return _frozen_map_from_backend(backend.set(key, value))


def map_delete[K, V](mapping: FrozenMap[K, V], key: K) -> FrozenMap[K, V]:
    """Return ``mapping`` without ``key`` without changing the original."""
    backend = cast(Map[K, V], object.__getattribute__(mapping, "_FrozenMap__map"))
    return _frozen_map_from_backend(backend.delete(key))


def map_update[K, V](
    mapping: FrozenMap[K, V],
    values: Mapping[K, V],
) -> FrozenMap[K, V]:
    """Return ``mapping`` updated with ``values`` without changing the original."""
    updated = cast(Map[K, V], object.__getattribute__(mapping, "_FrozenMap__map"))
    for key, value in values.items():
        updated = updated.set(key, value)
    return _frozen_map_from_backend(updated)


def freeze_json(value: object) -> FrozenJsonValue:
    """Recursively validate and freeze a canonical JSON value."""
    return _freeze_json(value, active_ids=set(), depth=0)


def _freeze_json(value: object, *, active_ids: set[int], depth: int) -> FrozenJsonValue:
    if depth > 100:
        raise FrozenJsonValueError("frozen JSON depth must not exceed 100")

    value_type = type(value)
    if value is None:
        return None
    if value_type is bool:
        return cast(bool, value)
    if value_type is int:
        return cast(int, value)
    if value_type is float:
        number = cast(float, value)
        if not isfinite(number):
            raise FrozenJsonValueError("frozen JSON numbers must be finite")
        return number
    if value_type is str:
        return cast(str, value)

    if value_type is list or value_type is tuple:
        sequence = cast(list[object] | tuple[object, ...], value)
        object_id = id(sequence)
        if object_id in active_ids:
            raise FrozenJsonValueError("frozen JSON cannot contain a cycle")
        active_ids.add(object_id)
        try:
            return tuple(
                _freeze_json(item, active_ids=active_ids, depth=depth + 1) for item in sequence
            )
        finally:
            active_ids.remove(object_id)

    if value_type is dict:
        dictionary = cast(dict[object, object], value)
        object_id = id(dictionary)
        if object_id in active_ids:
            raise FrozenJsonValueError("frozen JSON cannot contain a cycle")
        if any(type(key) is not str for key in dictionary):
            raise FrozenJsonValueError("frozen JSON objects must have string keys")
        active_ids.add(object_id)
        try:
            return FrozenMap(
                {
                    cast(str, key): _freeze_json(
                        item,
                        active_ids=active_ids,
                        depth=depth + 1,
                    )
                    for key, item in dictionary.items()
                }
            )
        finally:
            active_ids.remove(object_id)

    raise FrozenJsonValueError(
        f"expected a canonical JSON scalar, list, tuple, or dictionary; got {value_type.__name__}"
    )


def thaw_json(value: FrozenJsonValue) -> JsonValue:
    """Recursively convert an immutable JSON value to lists and dictionaries."""
    value_type = type(value)
    if value is None:
        return None
    if value_type is bool:
        return cast(bool, value)
    if value_type is int:
        return cast(int, value)
    if value_type is str:
        return cast(str, value)
    if value_type is float:
        number = cast(float, value)
        if not isfinite(number):
            raise FrozenJsonValueError("frozen JSON numbers must be finite")
        return number
    if value_type is tuple:
        sequence = cast(tuple[FrozenJsonValue, ...], value)
        return [thaw_json(item) for item in sequence]
    if isinstance(value, FrozenMap):
        if any(type(key) is not str for key in value):
            raise FrozenJsonValueError("frozen JSON objects must have string keys")
        return {key: thaw_json(item) for key, item in value.items()}
    raise FrozenJsonValueError(f"expected a frozen JSON value; got {value_type.__name__}")
