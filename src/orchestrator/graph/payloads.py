"""Strict JSON payload primitives for the execution graph."""

from typing import cast

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


__all__ = ["JsonValue", "StrictPayload"]
