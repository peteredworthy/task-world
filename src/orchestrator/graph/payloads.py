"""Strict JSON payload primitives for the execution graph."""

from typing import Any, cast

from pydantic import BaseModel, ConfigDict


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


class StrictPayload(BaseModel):
    """Immutable payload base that rejects coercion and unknown fields."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        populate_by_name=True,
    )

    def to_json(self) -> dict[str, JsonValue]:
        """Return the canonical JSON-compatible representation."""

        return cast(
            dict[str, JsonValue], self.model_dump(mode="json", by_alias=True, exclude_none=True)
        )

    def stored_json(self) -> dict[str, JsonValue]:
        """Return fields present at the storage boundary, without inferred defaults."""

        return cast(
            dict[str, JsonValue],
            self.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
                exclude_unset=True,
            ),
        )

    def __getitem__(self, key: str) -> Any:
        """Retained D-series read compatibility without reparsing the model."""

        return self.to_json()[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Retained D-series read compatibility without reparsing the model."""

        return self.to_json().get(key, default)

    def items(self):
        """Retained D-series mapping iteration over the concrete model."""

        return self.to_json().items()


class LegacyEventPayload(StrictPayload):
    """Typed carrier retained only for schema-generation-1 replay."""

    data: dict[str, JsonValue]

    def to_json(self) -> dict[str, JsonValue]:
        return self.data

    def stored_json(self) -> dict[str, JsonValue]:
        return self.data

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def items(self):
        return self.data.items()


__all__ = ["JsonValue", "LegacyEventPayload", "StrictPayload"]
