"""Shared SQLAlchemy declarative base for the standalone CRM application."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all CRM database models."""
