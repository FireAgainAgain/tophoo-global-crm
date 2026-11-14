"""Bookmarks and flat categories scoped to both user and project."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class UserLinkCategory(Base):
    __tablename__ = 'user_link_categories'
    __table_args__ = (UniqueConstraint('owner_user_id','site_project_id','name',name='uq_user_link_category_project'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    site_project_id: Mapped[int | None] = mapped_column(ForeignKey('site_projects.id'),nullable=True,index=True)
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer,default=0)

class UserLink(Base):
    __tablename__ = 'user_links'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    site_project_id: Mapped[int | None] = mapped_column(ForeignKey('site_projects.id'),nullable=True,index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey('user_link_categories.id',ondelete='SET NULL'),nullable=True,index=True)
    name: Mapped[str] = mapped_column(String(150))
    url: Mapped[str] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(String(1000),nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer,default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.now)

class UserLinkMigration(Base):
    __tablename__ = 'user_link_migrations'
    __table_args__ = (UniqueConstraint('owner_user_id','legacy_link_id',name='uq_user_link_migration'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    legacy_link_id: Mapped[int] = mapped_column(Integer)
