"""Database engine and session management."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from synthbody.config import get_settings
from synthbody.db.models import Base

_settings = get_settings()

_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine: Engine = create_engine(
    _settings.database_url,
    connect_args=_connect_args,
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):  # pragma: no cover - driver hook
    """Enable foreign keys and WAL on SQLite.

    SQLite does not enforce foreign keys unless asked, which would silently
    orphan simulations when an experiment is deleted.
    """
    if not _settings.database_url.startswith("sqlite"):
        return
    cur = dbapi_connection.cursor()
    try:
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
    finally:
        cur.close()


def init_db() -> None:
    """Create tables if they do not exist.

    Alembic owns schema migration for deployment; this exists so a fresh local
    checkout runs without a migration step.
    """
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and tests."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
