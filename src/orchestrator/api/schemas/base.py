"""Shared API schema base model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer

from orchestrator.time_utils import format_utc_datetime


def _serialize_datetimes(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_utc_datetime(value)
    if isinstance(value, dict):
        return {k: _serialize_datetimes(v) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [_serialize_datetimes(v) for v in cast(list[Any], value)]
    if isinstance(value, tuple):
        return tuple(_serialize_datetimes(v) for v in cast(tuple[Any, ...], value))
    return value


class ApiModel(BaseModel):
    """Base model for API schemas with consistent datetime JSON encoding."""

    @model_serializer(mode="wrap", when_used="json")
    def _serialize_json(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return _serialize_datetimes(handler(self))
