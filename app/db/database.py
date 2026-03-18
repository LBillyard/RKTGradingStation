"""Database engine, session management, and base model."""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Generator

from sqlalchemy import String, DateTime, create_engine, func, event, text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
    Session,
)

# Reusable type annotations for all models
uuid_pk = Annotated[
    str,
    mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4())),
]
created_at_col = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
]
updated_at_col = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    ),
]


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


# Module-level engine and session factory
_engine = None
_SessionLocal = None


def init_db(db_url: str, echo: bool = False) -> None:
    """Initialize the database engine and create all tables."""
    global _engine, _SessionLocal
    _engine = create_engine(db_url, echo=echo)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    # Enable WAL mode for SQLite for better concurrent read performance
    if "sqlite" in db_url:
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # Import all models to ensure they're registered with Base
    from app.models import scan, card, ocr, grading, authenticity, security, hardware, admin, reference, operator, slab, station  # noqa: F401

    Base.metadata.create_all(bind=_engine)

    # Lightweight migrations for new columns on existing tables
    if "sqlite" in db_url:
        with _engine.connect() as conn:
            _add_column_if_missing(conn, "grade_decisions", "ai_review_json", "TEXT")
            _add_column_if_missing(conn, "grade_decisions", "grading_confidence", "REAL")
            conn.commit()


def _add_column_if_missing(conn, table: str, column: str, col_type: str) -> None:
    """Add a column to a SQLite table if it doesn't exist yet."""
    try:
        result = conn.execute(text(f"PRAGMA table_info({table})"))
        columns = [row[1] for row in result]
        if column not in columns:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
    except Exception:
        pass  # Table might not exist yet


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    """Get a database session directly (non-generator)."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal()
