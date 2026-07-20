from __future__ import annotations

import csv
import json
import math
import shutil
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    Candle,
    Experiment,
    StrategyAccount,
    StrategyDecisionSnapshot,
    StrategyEquitySnapshot,
    StrategyMarketSnapshot,
    StrategySimulatedTrade,
)


class ExportService:
    """Creates final JSON/CSV exports. The live React dashboard is the primary report."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, session: Session, experiment: Experiment) -> Path:
        output_dir = self.settings.resolved_reports_dir / experiment.id
        output_dir.mkdir(parents=True, exist_ok=True)

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

        strategy_summaries = [
            self._strategy_summary(account, trades, decisions, experiment.last_price)
            for account in accounts
        ]
        summary = {
            "application": "Crypto Paper Trader",
            "version": "0.6.0",
            "execution_mode": "PAPER_ONLY",
            "experiment": self._row_dict(experiment),
            "buy_and_hold_final_capital": experiment.buy_and_hold_final_capital,
            "strategies": strategy_summaries,
        }
        self._write_json(output_dir / "summary.json", summary)
        self._write_csv(
            output_dir / "strategy_accounts.csv",
            [account.to_public_dict(experiment.last_price) for account in accounts],
        )
        self._write_csv(output_dir / "strategy_decisions.csv", [row.to_dict() for row in decisions])
        self._write_csv(output_dir / "strategy_trades.csv", [row.to_dict() for row in trades])
        self._write_csv(output_dir / "strategy_equity.csv", [row.to_dict() for row in equities])
        self._write_csv(
            output_dir / "strategy_market_timeline.csv",
            [row.to_dict() for row in market_snapshots],
        )
        self._write_csv(output_dir / "candles.csv", [self._row_dict(row) for row in candles])

        archive_path = output_dir / "experiment_results.zip"
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(output_dir.iterdir()):
                if path == archive_path or not path.is_file():
                    continue
                archive.write(path, arcname=path.name)

        # Backward-compatible filename for existing frontend bookmarks.
        legacy_path = output_dir / "report_bundle.zip"
        shutil.copyfile(archive_path, legacy_path)
        experiment.report_directory = str(output_dir)
        session.commit()
        return archive_path

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
        gross_profit = sum(float(item.realized_pnl or 0) for item in wins)
        gross_loss = abs(sum(float(item.realized_pnl or 0) for item in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        final_capital = (
            account.final_capital
            if account.final_capital is not None
            else account.current_equity(last_price)
        )
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
                sum(float(item.realized_pnl or 0) for item in sells) / len(sells) if sells else None
            ),
            "final_capital": final_capital,
            "net_return": (
                final_capital / account.initial_capital - 1 if account.initial_capital > 0 else 0.0
            ),
        }

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=ExportService._json_default),
            encoding="utf-8",
        )

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        fieldnames: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: ExportService._csv_value(row.get(key)) for key in fieldnames})

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
