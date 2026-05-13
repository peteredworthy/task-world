"""Immutable JSON helpers for delegation value objects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, cast


ImmutableJsonMapping = Mapping[str, Any]


def freeze_json_value(value: Any) -> Any:  # noqa: ANN401
    """Recursively freeze JSON-like values into immutable containers."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): freeze_json_value(item)
                for key, item in cast(Mapping[Any, Any], value).items()
            }
        )
    if isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
        return tuple(freeze_json_value(item) for item in cast(Sequence[Any], value))
    return value


def freeze_json_mapping(value: Mapping[str, Any] | None) -> ImmutableJsonMapping:
    """Return an immutable JSON mapping."""
    if value is None:
        return cast(ImmutableJsonMapping, MappingProxyType({}))
    frozen = freeze_json_value(value)
    if isinstance(frozen, Mapping):
        return cast(ImmutableJsonMapping, frozen)
    return cast(ImmutableJsonMapping, MappingProxyType({}))


def thaw_json_value(value: Any) -> Any:  # noqa: ANN401
    """Convert immutable JSON containers back to plain JSON containers."""
    if isinstance(value, Mapping):
        return {
            str(key): thaw_json_value(item) for key, item in cast(Mapping[Any, Any], value).items()
        }
    if isinstance(value, tuple):
        return [thaw_json_value(item) for item in cast(tuple[Any, ...], value)]
    return value


def thaw_json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Convert an immutable JSON mapping to a plain dict."""
    return cast(dict[str, Any], thaw_json_value(value))
