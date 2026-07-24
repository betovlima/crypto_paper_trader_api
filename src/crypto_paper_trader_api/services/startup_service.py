from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .. import database
from ..config import get_settings
from ..database import SessionLocal, repair_strategy_accounts_schema
from ..models import Experiment
from ..strategy_codes import (
    ACTIVE_STRATEGY_CODES,
    ADAPTIVE_STRATEGY_SELECTOR,
    AI_PATTERN_TRADER,
    CURRENT_HYBRID,
    EMA9_CLASSIC_STRATEGY_CODES,
    EMA9_STRATEGY_CODES,
    FIBONACCI_TREND_PULLBACK,
    LARRY_WILLIAMS_91_TREND_FOLLOWER,
    STORMER_FILHA_MAL_CRIADA,
    STRATEGY_DISPLAY_NAMES,
)
from ..worker import ensure_strategy_accounts


logger = logging.getLogger(__name__)


def _is_foreign_key_failure(exc: BaseException) -> bool:
    return "FOREIGN KEY constraint failed" in str(exc)


def _stop_management_mode(strategy_code: str) -> str:
    if strategy_code == LARRY_WILLIAMS_91_TREND_FOLLOWER:
        return "FIBONACCI_TREND_FOLLOWER"
    if strategy_code == FIBONACCI_TREND_PULLBACK:
        return "FIBONACCI_DYNAMIC"
    if strategy_code in EMA9_CLASSIC_STRATEGY_CODES:
        return "CLASSIC"
    if strategy_code == AI_PATTERN_TRADER:
        return "AI_DYNAMIC"
    if strategy_code == ADAPTIVE_STRATEGY_SELECTOR:
        return "SELECTOR_DYNAMIC"
    return "N/A"


def _setup_status(strategy_code: str) -> str:
    # Strategies that use the 9.1 setup state already receive their richer state during
    # the regular worker cycle. IDLE is safe for them and N/A for every direct strategy.
    if strategy_code in EMA9_STRATEGY_CODES or strategy_code == STORMER_FILHA_MAL_CRIADA:
        return "IDLE"
    return "N/A"


def _synchronize_strategy_accounts_once() -> None:
    with SessionLocal() as session:
        experiments = list(session.scalars(select(Experiment)))
        for experiment in experiments:
            ensure_strategy_accounts(session, experiment)
        if experiments:
            session.commit()


def _insert_missing_accounts_from_parent_rows() -> None:
    """Create missing accounts with ``INSERT ... SELECT`` from ``experiments``.

    A small number of legacy SQLite files return an experiment identifier through the
    Python DB-API in a representation that is not accepted when the same value is bound
    back into the child table. The parent row exists and can be read by the ORM, yet an
    ORM INSERT still fails its foreign key. Copying ``experiments.id`` inside SQLite keeps
    its exact storage representation and lets SQLite validate the parent/child relation
    without a Python round trip.

    Foreign-key enforcement remains ON for the whole operation. No bypass is used and no
    orphan account can be committed. Existing account identifiers and history are left
    untouched because only missing ``(experiment_id, strategy_code)`` pairs are inserted.
    """

    settings = get_settings()
    insert_sql = text(
        """
        INSERT INTO strategy_accounts (
            experiment_id,
            strategy_code,
            display_name,
            status,
            initial_capital,
            cash_balance,
            asset_quantity,
            average_entry_price,
            entry_market_price,
            entry_execution_price,
            entry_fee_paid,
            entry_time,
            initial_risk_per_unit,
            highest_price_since_entry,
            stop_loss_price,
            take_profit_price,
            trailing_stop_price,
            break_even_activated,
            last_atr_14,
            total_fees,
            total_spread_cost,
            total_slippage_cost,
            realized_pnl,
            final_capital,
            max_equity,
            max_drawdown_pct,
            consecutive_losses,
            cooldown_until,
            rejected_signals,
            ema_9_direction,
            setup_status,
            stop_management_mode,
            ai_similar_patterns,
            ai_mode,
            ai_model_version,
            ai_risk_status,
            ai_risk_reason,
            selector_model_version,
            selector_market_regime,
            selector_research_status,
            selector_research_summary,
            selector_next_research_at
        )
        SELECT
            experiment.id,
            :strategy_code,
            :display_name,
            'ACTIVE',
            experiment.initial_capital,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.cash_balance
                 ELSE experiment.initial_capital END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.asset_quantity
                 ELSE 0.0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.average_entry_price
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.entry_market_price
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.entry_execution_price
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.entry_fee_paid
                 ELSE 0.0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.entry_time
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.initial_risk_per_unit
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.highest_price_since_entry
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.stop_loss_price
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.take_profit_price
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.trailing_stop_price
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.break_even_activated
                 ELSE 0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.last_atr_14
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.total_fees
                 ELSE 0.0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.total_spread_cost
                 ELSE 0.0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.total_slippage_cost
                 ELSE 0.0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.realized_pnl
                 ELSE 0.0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.final_capital
                 ELSE NULL END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.max_equity
                 ELSE experiment.initial_capital END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.max_drawdown_pct
                 ELSE 0.0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.consecutive_losses
                 ELSE 0 END,
            CASE WHEN :copy_legacy_hybrid = 1
                 THEN experiment.cooldown_until
                 ELSE NULL END,
            0,
            'UNKNOWN',
            :setup_status,
            :stop_management_mode,
            0,
            :ai_mode,
            :ai_model_version,
            :ai_risk_status,
            :ai_risk_reason,
            :selector_model_version,
            :selector_market_regime,
            :selector_research_status,
            :selector_research_summary,
            CASE WHEN :is_selector = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
        FROM experiments AS experiment
        WHERE NOT EXISTS (
            SELECT 1
            FROM strategy_accounts AS account
            WHERE account.experiment_id = experiment.id
              AND account.strategy_code = :strategy_code
        )
        """
    )

    update_sql = text(
        """
        UPDATE strategy_accounts
           SET display_name = :display_name,
               stop_management_mode = :stop_management_mode,
               setup_status = CASE
                   WHEN setup_status IS NULL OR setup_status = '' THEN :setup_status
                   ELSE setup_status
               END,
               ai_mode = CASE
                   WHEN :is_ai_pattern = 1 THEN :ai_mode
                   ELSE ai_mode
               END,
               ai_model_version = CASE
                   WHEN :is_ai_pattern = 1 THEN :ai_model_version
                   ELSE ai_model_version
               END,
               selector_model_version = CASE
                   WHEN :is_selector = 1 THEN :selector_model_version
                   ELSE selector_model_version
               END,
               selector_market_regime = CASE
                   WHEN :is_selector = 1 AND selector_market_regime IS NULL
                   THEN :selector_market_regime
                   ELSE selector_market_regime
               END,
               selector_research_status = CASE
                   WHEN :is_selector = 1
                        AND (selector_research_status IS NULL OR selector_research_status = '')
                   THEN :selector_research_status
                   ELSE selector_research_status
               END,
               selector_research_summary = CASE
                   WHEN :is_selector = 1
                        AND (selector_research_summary IS NULL OR selector_research_summary = '')
                   THEN :selector_research_summary
                   ELSE selector_research_summary
               END,
               selector_next_research_at = CASE
                   WHEN :is_selector = 1 AND selector_next_research_at IS NULL
                   THEN CURRENT_TIMESTAMP
                   ELSE selector_next_research_at
               END
         WHERE strategy_code = :strategy_code
        """
    )

    with database.engine.begin() as connection:
        fk_state = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        if int(fk_state) != 1:
            raise RuntimeError(
                "Refusing parent-row synchronization because SQLite foreign keys are disabled."
            )

        experiment_count = int(
            connection.exec_driver_sql("SELECT COUNT(*) FROM experiments").scalar_one()
        )
        if experiment_count == 0:
            logger.info("No experiments were found; strategy-account synchronization was skipped.")
            return

        for strategy_code in ACTIVE_STRATEGY_CODES:
            is_ai_pattern = strategy_code == AI_PATTERN_TRADER
            is_selector = strategy_code == ADAPTIVE_STRATEGY_SELECTOR
            params = {
                "strategy_code": strategy_code,
                "display_name": STRATEGY_DISPLAY_NAMES[strategy_code],
                "copy_legacy_hybrid": int(strategy_code == CURRENT_HYBRID),
                "setup_status": _setup_status(strategy_code),
                "stop_management_mode": _stop_management_mode(strategy_code),
                "ai_mode": settings.ai_pattern_mode if is_ai_pattern else None,
                "ai_model_version": "AI-PATTERN-v1" if is_ai_pattern else None,
                "ai_risk_status": "LEARNING" if is_ai_pattern else None,
                "ai_risk_reason": (
                    "Waiting for the first autonomous pattern analysis."
                    if is_ai_pattern
                    else None
                ),
                "selector_model_version": (
                    settings.selector_model_version if is_selector else None
                ),
                "selector_market_regime": "UNDEFINED" if is_selector else None,
                "selector_research_status": "SCHEDULED" if is_selector else None,
                "selector_research_summary": (
                    "Initial local adaptive research was scheduled."
                    if is_selector
                    else None
                ),
                "is_ai_pattern": int(is_ai_pattern),
                "is_selector": int(is_selector),
            }
            connection.execute(insert_sql, params)
            connection.execute(update_sql, params)

        violations = connection.exec_driver_sql(
            'PRAGMA foreign_key_check("strategy_accounts")'
        ).fetchall()
        if violations:
            raise RuntimeError(
                "Parent-row strategy-account synchronization did not restore integrity: "
                f"{violations[:10]}"
            )

    database.engine.dispose()
    logger.warning(
        "Strategy accounts were synchronized by copying experiment identifiers inside "
        "SQLite; foreign-key enforcement remained enabled and no violations were found."
    )


# Backward-compatible private alias retained for integrations/tests created during v0.16.15.
def _synchronize_strategy_accounts_with_verified_fk_bypass() -> None:
    _insert_missing_accounts_from_parent_rows()


def synchronize_strategy_accounts() -> None:
    """Create newly introduced strategy accounts for existing experiments at startup.

    Normal ORM synchronization is attempted first. Legacy child-table metadata is then
    rebuilt and retried on fresh pooled connections. If an old SQLite storage-affinity
    quirk still rejects the Python-bound parent identifier, the final path performs an
    integrity-enforced ``INSERT ... SELECT`` directly from ``experiments``.
    """

    try:
        _synchronize_strategy_accounts_once()
        return
    except IntegrityError as first_error:
        if not _is_foreign_key_failure(first_error):
            raise

    logger.warning(
        "Strategy-account synchronization found a foreign-key failure; rebuilding "
        "strategy_accounts and retrying with a fresh connection."
    )
    repair_strategy_accounts_schema(force=True)
    database.engine.dispose()

    try:
        _synchronize_strategy_accounts_once()
        return
    except IntegrityError as second_error:
        if not _is_foreign_key_failure(second_error):
            raise

    logger.warning(
        "The normal retry still failed after schema repair. Synchronizing missing "
        "accounts directly from parent experiment rows with foreign keys enabled."
    )
    _insert_missing_accounts_from_parent_rows()
