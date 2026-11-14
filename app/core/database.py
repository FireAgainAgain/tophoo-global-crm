"""SQLAlchemy database engine and session helpers."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_URL


engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600, hide_parameters=True)

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout = 10000")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Provide one database session for a request and close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
