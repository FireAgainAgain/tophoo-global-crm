"""Operational health endpoints."""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import engine


router = APIRouter(prefix="/api/health", tags=["Health"])


@router.get("/database")
def database_health() -> dict[str, str]:
    """Verify that the configured database can be reached."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"database": "connected"}
