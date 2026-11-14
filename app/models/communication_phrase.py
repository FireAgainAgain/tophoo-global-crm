"""Project-scoped categories, scenarios and communication phrases."""
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class PhraseCategory(Base):
    __tablename__ = 'crm_phrase_categories'
    __table_args__ = (UniqueConstraint('site_project_id','name',name='uq_phrase_category_name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'),index=True)
    name: Mapped[str] = mapped_column(String(180))
    sort_order: Mapped[int] = mapped_column(Integer,default=0)

class PhraseScene(Base):
    __tablename__ = 'crm_phrase_scenes'
    __table_args__ = (UniqueConstraint('category_id','name',name='uq_phrase_scene_name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'),index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('crm_phrase_categories.id'),index=True)
    name: Mapped[str] = mapped_column(String(180))
    sort_order: Mapped[int] = mapped_column(Integer,default=0)

class CommunicationPhrase(Base):
    __tablename__ = 'crm_communication_phrases'
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'),index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('crm_phrase_categories.id'),index=True)
    scene_id: Mapped[int | None] = mapped_column(ForeignKey('crm_phrase_scenes.id'),index=True,nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer,default=0)
    content: Mapped[str] = mapped_column(Text)
    translation: Mapped[str] = mapped_column(Text,default="")
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.now,onupdate=datetime.now)
