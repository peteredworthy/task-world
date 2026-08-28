"""Durable, single-use reliable-plan qualification authority."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.orm.models import ReliablePlanQualificationModel


class ReliablePlanQualificationReferenceError(ValueError):
    """An opaque qualification reference is unknown, consumed, or misbound."""


class ReliablePlanQualificationRepository:
    """Persist and atomically bind server-issued qualification facts to one run."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(self, reference: str, facts: dict[str, Any]) -> None:
        self._session.add(ReliablePlanQualificationModel(reference=reference, facts=facts))
        await self._session.flush()

    async def consume(self, reference: str, run_id: str) -> dict[str, Any]:
        result = await self._session.execute(
            update(ReliablePlanQualificationModel)
            .where(ReliablePlanQualificationModel.reference == reference)
            .where(ReliablePlanQualificationModel.consumed_by_run_id.is_(None))
            .values(consumed_by_run_id=run_id)
            .returning(ReliablePlanQualificationModel.reference)
        )
        if result.scalar_one_or_none() is None:
            existing = await self._session.scalar(
                select(ReliablePlanQualificationModel).where(
                    ReliablePlanQualificationModel.reference == reference
                )
            )
            if existing is None:
                raise ReliablePlanQualificationReferenceError(
                    "unknown reliable-plan qualification reference"
                )
            raise ReliablePlanQualificationReferenceError(
                "reliable-plan qualification reference has already been consumed"
            )
        facts = await self._session.scalar(
            select(ReliablePlanQualificationModel.facts).where(
                ReliablePlanQualificationModel.reference == reference
            )
        )
        assert isinstance(facts, dict)
        return facts

    async def require_bound(self, reference: str, run_id: str) -> dict[str, Any]:
        facts = await self._session.scalar(
            select(ReliablePlanQualificationModel.facts)
            .where(ReliablePlanQualificationModel.reference == reference)
            .where(ReliablePlanQualificationModel.consumed_by_run_id == run_id)
        )
        if not isinstance(facts, dict):
            raise ReliablePlanQualificationReferenceError(
                "reliable-plan qualification reference is not bound to this run"
            )
        return facts
