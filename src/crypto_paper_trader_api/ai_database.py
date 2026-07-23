from __future__ import annotations

import sqlite3
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event, text
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
    _migrate_ai_history_state_columns()


def _migrate_ai_history_state_columns() -> None:
    additions = {
        "pages_attempted": "INTEGER NOT NULL DEFAULT 0",
        "pages_succeeded": "INTEGER NOT NULL DEFAULT 0",
        "candles_added_last_attempt": "INTEGER NOT NULL DEFAULT 0",
        "empty_windows_last_attempt": "INTEGER NOT NULL DEFAULT 0",
        "last_attempt_at": "DATETIME",
        "next_retry_at": "DATETIME",
    }
    with ai_engine.begin() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_history_sync_state'")
        ).scalar()
        if not exists:
            return
        current = {
            row[1]
            for row in connection.exec_driver_sql(
                'PRAGMA table_info("ai_history_sync_state")'
            ).fetchall()
        }
        for column, ddl in additions.items():
            if column not in current:
                connection.exec_driver_sql(
                    f'ALTER TABLE "ai_history_sync_state" ADD COLUMN "{column}" {ddl}'
                )


def get_ai_session() -> Generator[Session, None, None]:
    session = AISessionLocal()
    try:
        yield session
    finally:
        session.close()
