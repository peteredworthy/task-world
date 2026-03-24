"""SQLAlchemy ORM model for AgentConfig."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.config.enums import ModelProfile
from orchestrator.db import Base


class AgentConfigModel(Base):
    __tablename__ = "agent_configs"
    __table_args__ = (UniqueConstraint("name", name="uq_agent_configs_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    default_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_profile: Mapped[str] = mapped_column(String, nullable=False, default=ModelProfile.CODER)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
