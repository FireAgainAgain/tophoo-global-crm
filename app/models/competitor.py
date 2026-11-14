"""Project-scoped competitor research records."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Competitor(Base):
    __tablename__ = "crm_competitors"
    __table_args__ = (UniqueConstraint("site_project_id", "name", name="uq_competitor_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(220))
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class CompetitorWebsite(Base):
    __tablename__ = "crm_competitor_websites"

    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("crm_competitors.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    url: Mapped[str] = mapped_column(String(1000))
    website_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class CompetitorKeyword(Base):
    __tablename__ = "crm_competitor_keywords"

    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("crm_competitors.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(300))
    language: Mapped[str | None] = mapped_column(String(30), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
