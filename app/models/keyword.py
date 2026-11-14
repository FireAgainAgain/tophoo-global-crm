"""Project-scoped keyword library, category tree and import history."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KeywordImport(Base):
    __tablename__ = "keyword_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    source_filename: Mapped[str] = mapped_column(String(500))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)


class KeywordCategory(Base):
    __tablename__ = "keyword_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_categories.id"), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Keyword(Base):
    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("site_project_id", "normalized_keyword", name="uq_keyword_project_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(500))
    normalized_keyword: Mapped[str] = mapped_column(String(191))
    chinese_translation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    volume_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    volume_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_imports.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class KeywordCategoryMap(Base):
    __tablename__ = "keyword_category_maps"
    __table_args__ = (UniqueConstraint("keyword_id", "category_id", name="uq_keyword_category_map"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("keyword_categories.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

