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
    _migrate_active_coinex_experiments_to_mexc()


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
            "vip_level": "VARCHAR(16) NOT NULL DEFAULT 'API_SPOT'",
            "maker_fee_rate": "FLOAT NOT NULL DEFAULT 0.0",
            "taker_fee_rate": "FLOAT NOT NULL DEFAULT 0.0005",
            "fee_source": "VARCHAR(64) NOT NULL DEFAULT 'MEXC_API_CONFIG'",
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
            "entry_candle_timestamp": "DATETIME",
            "last_setup_event": "VARCHAR(64)",
            "last_setup_event_reason": "TEXT",
            "stop_management_mode": "VARCHAR(32) NOT NULL DEFAULT 'N/A'",
            "exit_trigger_price": "FLOAT",
            "exit_trigger_candle_timestamp": "DATETIME",
            "exit_trigger_candle_low": "FLOAT",
            "ai_mode": "VARCHAR(32)",
            "ai_regime": "VARCHAR(32)",
            "ai_pattern_cluster": "INTEGER",
            "ai_confidence": "FLOAT",
            "ai_upward_probability": "FLOAT",
            "ai_expected_net_return": "FLOAT",
            "ai_similar_patterns": "INTEGER NOT NULL DEFAULT 0",
            "ai_model_version": "VARCHAR(64)",
            "ai_risk_status": "VARCHAR(32)",
            "ai_risk_reason": "TEXT",
            "ai_last_prediction_at": "DATETIME",
            "selector_selected_strategy": "VARCHAR(64)",
            "selector_market_regime": "VARCHAR(32)",
            "selector_confidence": "FLOAT",
            "selector_expected_net_return": "FLOAT",
            "selector_candidate_scores": "TEXT",
            "selector_model_version": "VARCHAR(64)",
            "selector_active_strategy_name": "VARCHAR(128)",
            "selector_strategy_origin": "VARCHAR(32)",
            "selector_research_status": "VARCHAR(48)",
            "selector_research_summary": "TEXT",
            "selector_validation_score": "FLOAT",
            "selector_profit_factor": "FLOAT",
            "selector_max_drawdown_pct": "FLOAT",
            "selector_net_return": "FLOAT",
            "selector_trade_count": "INTEGER",
            "selector_next_research_at": "DATETIME",
            "selector_strategy_spec_json": "TEXT",
            "selector_source_urls_json": "TEXT",
            "selector_ai_provider": "VARCHAR(32)",
            "selector_ai_model": "VARCHAR(64)",
            "selector_ai_review_status": "VARCHAR(32)",
            "selector_ai_review_score": "FLOAT",
            "selector_ai_review_summary": "TEXT",
            "selector_last_error": "TEXT",
            "selector_last_reward": "FLOAT",
            "selector_last_completed_at": "DATETIME",
            "selector_position_strategy_code": "VARCHAR(64)",
            "selector_position_strategy_name": "VARCHAR(128)",
            "selector_position_strategy_origin": "VARCHAR(32)",
            "selector_position_strategy_spec_json": "TEXT",
            "selector_position_validation_score": "FLOAT",
            "selector_position_opened_at": "DATETIME",
        },
        "strategy_decision_snapshots": {
            "range_ratio_20": "FLOAT",
            "body_ratio": "FLOAT",
            "close_location": "FLOAT",
            "compression_ratio": "FLOAT",
            "trend_age_up": "FLOAT",
            "extension_ema20_atr": "FLOAT",
            "ignition_score": "FLOAT",
            "exhaustion_score": "FLOAT",
            "expected_value_r": "FLOAT",
            "fast_ema_period": "INTEGER",
            "slow_ema_period": "INTEGER",
            "regime_ema_period": "INTEGER",
            "fast_ema_value": "FLOAT",
            "slow_ema_value": "FLOAT",
            "regime_ema_value": "FLOAT",
            "stop_management_mode": "VARCHAR(32)",
            "active_stop_price": "FLOAT",
            "exit_trigger_price": "FLOAT",
            "is_recovered": "BOOLEAN NOT NULL DEFAULT 0",
            "recovery_note": "TEXT",
            "ai_mode": "VARCHAR(32)",
            "ai_proposed_action": "VARCHAR(16)",
            "ai_regime": "VARCHAR(32)",
            "ai_pattern_cluster": "INTEGER",
            "ai_confidence": "FLOAT",
            "ai_neighbor_count": "INTEGER",
            "ai_positive_neighbor_rate": "FLOAT",
            "ai_expected_gross_return": "FLOAT",
            "ai_expected_net_return": "FLOAT",
            "ai_worst_adverse_return": "FLOAT",
            "ai_model_version": "VARCHAR(64)",
            "ai_training_samples": "INTEGER",
            "ai_validation_accuracy": "FLOAT",
            "ai_validation_mae": "FLOAT",
            "ai_risk_status": "VARCHAR(32)",
            "ai_risk_reason": "TEXT",
            "ai_horizon_candles": "INTEGER",
            "ai_feature_summary": "TEXT",
            "ai_outcome_resolved": "BOOLEAN NOT NULL DEFAULT 0",
            "ai_outcome_candle_timestamp": "DATETIME",
            "ai_realized_gross_return": "FLOAT",
            "ai_realized_net_return": "FLOAT",
            "ai_realized_reward": "FLOAT",
            "ai_realized_adverse_return": "FLOAT",
            "ai_direction_correct": "BOOLEAN",
            "selector_selected_strategy": "VARCHAR(64)",
            "selector_market_regime": "VARCHAR(32)",
            "selector_confidence": "FLOAT",
            "selector_expected_net_return": "FLOAT",
            "selector_candidate_scores": "TEXT",
            "selector_model_version": "VARCHAR(64)",
            "selector_active_strategy_name": "VARCHAR(128)",
            "selector_strategy_origin": "VARCHAR(32)",
            "selector_research_status": "VARCHAR(48)",
            "selector_research_summary": "TEXT",
            "selector_validation_score": "FLOAT",
            "selector_profit_factor": "FLOAT",
            "selector_max_drawdown_pct": "FLOAT",
            "selector_net_return": "FLOAT",
            "selector_trade_count": "INTEGER",
            "selector_next_research_at": "DATETIME",
            "selector_strategy_spec_json": "TEXT",
            "selector_source_urls_json": "TEXT",
            "selector_ai_provider": "VARCHAR(32)",
            "selector_ai_model": "VARCHAR(64)",
            "selector_ai_review_status": "VARCHAR(32)",
            "selector_ai_review_score": "FLOAT",
            "selector_ai_review_summary": "TEXT",
        },
        "decision_snapshots": {
            "candle_high": "FLOAT NOT NULL DEFAULT 0",
            "candle_low": "FLOAT NOT NULL DEFAULT 0",
            "maker_fee_rate": "FLOAT NOT NULL DEFAULT 0.0",
            "taker_fee_rate": "FLOAT NOT NULL DEFAULT 0.0005",
            "spread_rate": "FLOAT NOT NULL DEFAULT 0.0002",
            "slippage_rate": "FLOAT NOT NULL DEFAULT 0.0005",
            "estimated_round_trip_cost_rate": "FLOAT NOT NULL DEFAULT 0.0022",
            "required_gross_return": "FLOAT NOT NULL DEFAULT 0.0027",
            "active_stop_loss_price": "FLOAT",
            "active_take_profit_price": "FLOAT",
            "active_trailing_stop_price": "FLOAT",
            "execution_reference_price": "FLOAT",
        },
        "strategy_simulated_trades": {
            "selected_strategy_code": "VARCHAR(64)",
            "entry_candle_timestamp": "DATETIME",
            "is_recovered": "BOOLEAN NOT NULL DEFAULT 0",
            "recovery_note": "TEXT",
        },
        "simulated_trades": {
            "order_role": "VARCHAR(16) NOT NULL DEFAULT 'TAKER'",
            "fee_rate": "FLOAT NOT NULL DEFAULT 0.0005",
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


def _migrate_active_coinex_experiments_to_mexc() -> None:
    """Move only unfinished v0.12 experiments to the v0.13 MEXC cost model.

    Completed experiments keep their original fee metadata and realized accounting.
    An unfinished paper experiment continues from its persisted portfolio, but every
    execution after the upgrade uses the configured MEXC API Spot assumptions.
    """

    with engine.begin() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='experiments'")
        ).scalar()
        if not exists:
            return

        connection.execute(
            text(
                """
                UPDATE experiments
                   SET vip_level = :vip_level,
                       maker_fee_rate = :maker_fee_rate,
                       taker_fee_rate = :taker_fee_rate,
                       fee_source = :fee_source,
                       min_market_amount = NULL
                 WHERE status IN ('PENDING', 'RUNNING', 'STOP_REQUESTED')
                   AND (
                        vip_level = 'VIP0'
                        OR fee_source LIKE 'CONFIG_VIP0%'
                        OR fee_source LIKE '%CET%'
                   )
                """
            ),
            {
                "vip_level": settings.vip_level,
                "maker_fee_rate": settings.effective_default_maker_fee_rate,
                "taker_fee_rate": settings.effective_default_taker_fee_rate,
                "fee_source": "MEXC_API_CONFIG"
                + ("_MX_DISCOUNT" if settings.mx_fee_discount_enabled else ""),
            },
        )


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
