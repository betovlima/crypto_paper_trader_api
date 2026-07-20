from __future__ import annotations

import sqlite3
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.resolved_database_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_database() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_additive_columns()


def _migrate_additive_columns() -> None:
    """Small additive SQLite migration for users upgrading the v0.1 database."""

    additions: dict[str, dict[str, str]] = {
        "experiments": {
            "trading_profile": "VARCHAR(32) NOT NULL DEFAULT 'BALANCED_INTRADAY'",
            "last_market_update_at": "DATETIME",
            "next_analysis_at": "DATETIME",
            "best_bid": "FLOAT",
            "best_ask": "FLOAT",
            "last_atr_14": "FLOAT",
            "last_market_event": "VARCHAR(64)",
            "entry_time": "DATETIME",
            "initial_risk_per_unit": "FLOAT",
            "break_even_activated": "BOOLEAN NOT NULL DEFAULT 0",
            "vip_level": "VARCHAR(16) NOT NULL DEFAULT 'VIP0'",
            "maker_fee_rate": "FLOAT NOT NULL DEFAULT 0.002",
            "taker_fee_rate": "FLOAT NOT NULL DEFAULT 0.002",
            "fee_source": "VARCHAR(64) NOT NULL DEFAULT 'CONFIG_VIP0'",
            "min_market_amount": "FLOAT",
            "base_currency": "VARCHAR(16)",
            "quote_currency": "VARCHAR(16)",
            "last_spread_rate": "FLOAT NOT NULL DEFAULT 0.0002",
            "average_spread_rate": "FLOAT NOT NULL DEFAULT 0",
            "spread_observations": "INTEGER NOT NULL DEFAULT 0",
            "total_spread_cost": "FLOAT NOT NULL DEFAULT 0",
            "total_slippage_cost": "FLOAT NOT NULL DEFAULT 0",
            "buy_and_hold_current_capital": "FLOAT",
            "entry_market_price": "FLOAT",
            "entry_execution_price": "FLOAT",
            "entry_fee_paid": "FLOAT NOT NULL DEFAULT 0",
            "recovery_status": "VARCHAR(24) NOT NULL DEFAULT 'IDLE'",
            "recovery_started_at": "DATETIME",
            "recovery_completed_at": "DATETIME",
            "recovered_candle_count": "INTEGER NOT NULL DEFAULT 0",
            "recovered_trade_count": "INTEGER NOT NULL DEFAULT 0",
            "recovery_message": "TEXT",
        },
        "strategy_accounts": {
            "entry_market_price": "FLOAT",
            "entry_execution_price": "FLOAT",
            "entry_fee_paid": "FLOAT NOT NULL DEFAULT 0",
            "last_setup_event": "VARCHAR(64)",
            "last_setup_event_reason": "TEXT",
        },
        "strategy_decision_snapshots": {
            "fast_ema_period": "INTEGER",
            "slow_ema_period": "INTEGER",
            "regime_ema_period": "INTEGER",
            "fast_ema_value": "FLOAT",
            "slow_ema_value": "FLOAT",
            "regime_ema_value": "FLOAT",
            "is_recovered": "BOOLEAN NOT NULL DEFAULT 0",
            "recovery_note": "TEXT",
        },
        "decision_snapshots": {
            "candle_high": "FLOAT NOT NULL DEFAULT 0",
            "candle_low": "FLOAT NOT NULL DEFAULT 0",
            "maker_fee_rate": "FLOAT NOT NULL DEFAULT 0.002",
            "taker_fee_rate": "FLOAT NOT NULL DEFAULT 0.002",
            "spread_rate": "FLOAT NOT NULL DEFAULT 0.0002",
            "slippage_rate": "FLOAT NOT NULL DEFAULT 0.0005",
            "estimated_round_trip_cost_rate": "FLOAT NOT NULL DEFAULT 0.0052",
            "required_gross_return": "FLOAT NOT NULL DEFAULT 0.0057",
            "active_stop_loss_price": "FLOAT",
            "active_take_profit_price": "FLOAT",
            "active_trailing_stop_price": "FLOAT",
            "execution_reference_price": "FLOAT",
        },
        "strategy_simulated_trades": {
            "is_recovered": "BOOLEAN NOT NULL DEFAULT 0",
            "recovery_note": "TEXT",
        },
        "simulated_trades": {
            "order_role": "VARCHAR(16) NOT NULL DEFAULT 'TAKER'",
            "fee_rate": "FLOAT NOT NULL DEFAULT 0.002",
            "spread_rate": "FLOAT NOT NULL DEFAULT 0.0002",
            "spread_cost": "FLOAT NOT NULL DEFAULT 0",
            "slippage_rate": "FLOAT NOT NULL DEFAULT 0.0005",
            "total_transaction_cost": "FLOAT NOT NULL DEFAULT 0",
            "gross_pnl_before_exit_costs": "FLOAT",
            "stop_loss_price": "FLOAT",
            "take_profit_price": "FLOAT",
            "trailing_stop_price": "FLOAT",
        },
    }

    with engine.begin() as connection:
        for table, columns in additions.items():
            exists = connection.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": table},
            ).scalar()
            if not exists:
                continue
            current = {
                row[1]
                for row in connection.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()
            }
            for column, ddl in columns.items():
                if column not in current:
                    connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}')


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
