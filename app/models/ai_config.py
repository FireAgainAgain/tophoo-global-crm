"""Project-scoped AI provider configuration."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AiConfiguration(Base):
    __tablename__ = "crm_ai_configurations"
    __table_args__ = (UniqueConstraint("site_project_id", name="uq_ai_configuration_project"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    provider: Mapped[str] = mapped_column(String(60), default="deepseek")
    protocol: Mapped[str] = mapped_column(String(40), default="openai-compatible")
    model: Mapped[str] = mapped_column(String(160), default="deepseek-chat")
    base_url: Mapped[str] = mapped_column(String(500), default="https://api.deepseek.com/v1")
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    auto_prospecting_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    temperature_tenths: Mapped[int] = mapped_column(Integer, default=1)
    last_test_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class LegacyAiModelConfiguration(Base):
    """A reusable model connection saved under one CRM project."""

    __tablename__ = "crm_ai_model_configurations"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(60), default="deepseek")
    protocol: Mapped[str] = mapped_column(String(40), default="openai-compatible")
    model: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(500))
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    temperature_tenths: Mapped[int] = mapped_column(Integer, default=1)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class LegacyAiFeatureBinding(Base):
    """Each project feature has one selected model; one model may serve many features."""

    __tablename__ = "crm_ai_feature_bindings"
    __table_args__ = (UniqueConstraint("site_project_id", "feature_key", name="uq_ai_feature_binding_project"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    feature_key: Mapped[str] = mapped_column(String(80))
    model_configuration_id: Mapped[int | None] = mapped_column(ForeignKey("crm_ai_model_configurations.id"), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# User-owned connections; legacy shared rows remain archived and inaccessible.
class AiModelConfiguration(Base):
    """A reusable model connection saved under one CRM project."""

    __tablename__ = "crm_user_ai_model_configurations"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(60), default="deepseek")
    protocol: Mapped[str] = mapped_column(String(40), default="openai-compatible")
    model: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(500))
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    temperature_tenths: Mapped[int] = mapped_column(Integer, default=1)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AiFeatureBinding(Base):
    """Each project feature has one selected model; one model may serve many features."""

    __tablename__ = "crm_user_ai_feature_bindings"
    __table_args__ = (UniqueConstraint("site_project_id", "owner_user_id", "feature_key", name="uq_user_ai_feature_binding"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    feature_key: Mapped[str] = mapped_column(String(80))
    model_configuration_id: Mapped[int | None] = mapped_column(ForeignKey("crm_user_ai_model_configurations.id"), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
