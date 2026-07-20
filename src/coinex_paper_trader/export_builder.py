from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict
from datetime import date, datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Candle,
    Experiment,
    StrategyAccount,
    StrategyDecisionSnapshot,
    StrategyEquitySnapshot,
    StrategyMarketSnapshot,
    StrategySimulatedTrade,
)


class ExportBuilder:
    """Builds a downloadable ZIP entirely in memory from SQLite data."""

    def build_bundle(self, session: Session, experiment: Experiment) -> BytesIO:
        accounts = list(
            session.scalars(
                select(StrategyAccount)
                .where(StrategyAccount.experiment_id == experiment.id)
                .order_by(StrategyAccount.id)
            )
        )
        decisions = list(
            session.scalars(
                select(StrategyDecisionSnapshot)
                .where(StrategyDecisionSnapshot.experiment_id == experiment.id)
                .order_by(
                    StrategyDecisionSnapshot.strategy_code,
                    StrategyDecisionSnapshot.candle_timestamp,
                )
            )
        )
        trades = list(
            session.scalars(
                select(StrategySimulatedTrade)
                .where(StrategySimulatedTrade.experiment_id == experiment.id)
                .order_by(
                    StrategySimulatedTrade.strategy_code,
                    StrategySimulatedTrade.executed_at,
                )
            )
        )
        equities = list(
            session.scalars(
                select(StrategyEquitySnapshot)
                .where(StrategyEquitySnapshot.experiment_id == experiment.id)
                .order_by(
                    StrategyEquitySnapshot.strategy_code,
                    StrategyEquitySnapshot.timestamp,
                )
            )
        )
        market_snapshots = list(
            session.scalars(
                select(StrategyMarketSnapshot)
                .where(StrategyMarketSnapshot.experiment_id == experiment.id)
                .order_by(
                    StrategyMarketSnapshot.strategy_code,
                    StrategyMarketSnapshot.observed_at,
                )
            )
        )
        candles = list(
            session.scalars(
                select(Candle)
                .where(Candle.experiment_id == experiment.id)
                .order_by(Candle.timeframe, Candle.timestamp)
            )
        )

        summary = {
            "application": "Crypto Paper Trader",
            "version": "0.8.1",
            "execution_mode": "PAPER_ONLY",
            "storage_policy": {
                "persistent_source": "SQLite",
                "automatic_export_files": False,
                "download_bundle_generated_in_memory": True,
            },
            "cost_policy": {
                "fees_affect_signals": False,
                "fees_affect_technical_stops": False,
                "fees_are_applied_to_net_results": True,
            },
            "experiment": self._row_dict(experiment),
            "buy_and_hold_final_capital": experiment.buy_and_hold_final_capital,
            "strategies": [
                self._strategy_summary(account, trades, decisions, experiment.last_price)
                for account in accounts
            ],
        }

        files: dict[str, str] = {
            "summary.json": json.dumps(
                summary,
                indent=2,
                ensure_ascii=False,
                default=self._json_default,
            ),
            "strategy_accounts.csv": self._csv_text(
                [account.to_public_dict(experiment.last_price) for account in accounts]
            ),
            "strategy_decisions.csv": self._csv_text([row.to_dict() for row in decisions]),
            "strategy_trades.csv": self._csv_text([row.to_dict() for row in trades]),
            "strategy_equity.csv": self._csv_text([row.to_dict() for row in equities]),
            "strategy_market_timeline.csv": self._csv_text(
                [row.to_dict() for row in market_snapshots]
            ),
            "candles.csv": self._csv_text([self._row_dict(row) for row in candles]),
        }

        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for filename, content in files.items():
                archive.writestr(filename, content.encode("utf-8"))
        buffer.seek(0)
        return buffer

    def _strategy_summary(
        self,
        account: StrategyAccount,
        all_trades: list[StrategySimulatedTrade],
        all_decisions: list[StrategyDecisionSnapshot],
        last_price: float | None,
    ) -> dict[str, Any]:
        trades = [item for item in all_trades if item.strategy_account_id == account.id]
        decisions = [item for item in all_decisions if item.strategy_account_id == account.id]
        sells = [item for item in trades if item.side == "SELL" and item.realized_pnl is not None]
        wins = [item for item in sells if float(item.realized_pnl or 0) > 0]
        losses = [item for item in sells if float(item.realized_pnl or 0) < 0]
        net_profit = sum(float(item.realized_pnl or 0) for item in wins)
        net_loss = abs(sum(float(item.realized_pnl or 0) for item in losses))
        profit_factor = net_profit / net_loss if net_loss > 0 else None
        final_capital = (
            account.final_capital
            if account.final_capital is not None
            else account.current_equity(last_price)
        )
        closed_gross_pnl = sum(
            float(item.gross_pnl_before_exit_costs or 0.0) for item in sells
        )
        open_gross_pnl = 0.0
        if account.has_open_position and last_price is not None:
            entry = float(
                account.entry_market_price
                or account.entry_execution_price
                or account.average_entry_price
                or 0.0
            )
            open_gross_pnl = float(account.asset_quantity or 0.0) * (
                float(last_price) - entry
            )
        gross_pnl = closed_gross_pnl + open_gross_pnl
        gross_equity = account.initial_capital + gross_pnl
        net_pnl = final_capital - account.initial_capital
        return {
            **account.to_public_dict(last_price),
            "decision_count": len(decisions),
            "trade_execution_count": len(trades),
            "completed_trade_count": len(sells),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(sells) if sells else None,
            "profit_factor": profit_factor,
            "average_realized_pnl": (
                sum(float(item.realized_pnl or 0) for item in sells) / len(sells)
                if sells
                else None
            ),
            "gross_pnl": gross_pnl,
            "gross_equity": gross_equity,
            "gross_return": (
                gross_equity / account.initial_capital - 1
                if account.initial_capital > 0
                else 0.0
            ),
            "net_pnl": net_pnl,
            "estimated_cost_impact": gross_pnl - net_pnl,
            "recovered_trade_count": sum(1 for item in trades if item.is_recovered),
            "final_capital": final_capital,
            "net_return": (
                final_capital / account.initial_capital - 1
                if account.initial_capital > 0
                else 0.0
            ),
        }

    @staticmethod
    def _csv_text(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        fieldnames: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
        handle = StringIO(newline="")
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: ExportBuilder._csv_value(row.get(key)) for key in fieldnames}
            )
        return handle.getvalue()

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        if hasattr(row, "__table__"):
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}
        if hasattr(row, "to_dict"):
            return row.to_dict()
        if hasattr(row, "__dataclass_fields__"):
            return asdict(row)
        raise TypeError(f"Unsupported export row: {type(row)!r}")

    @staticmethod
    def _csv_value(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return ""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False)
        return value

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
