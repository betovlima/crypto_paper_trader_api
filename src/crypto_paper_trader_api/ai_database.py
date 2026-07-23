from __future__ import annotations

import sqlite3
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class AIBase(DeclarativeBase):
    """Declarative base exclusively for AI Pattern Trader persistence."""


settings = get_settings()
ai_engine = create_engine(
    settings.resolved_ai_database_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)
AISessionLocal = sessionmaker(bind=ai_engine, autoflush=False, expire_on_commit=False)


@event.listens_for(ai_engine, "connect")
def set_ai_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


def init_ai_database() -> None:
    from . import ai_models  # noqa: F401
    from . import ai_opportunity_models  # noqa: F401

    AIBase.metadata.create_all(bind=ai_engine)


def get_ai_session() -> Generator[Session, None, None]:
    session = AISessionLocal()
    try:
        yield session
    finally:
        session.close()
