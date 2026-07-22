from datetime import datetime, timedelta, timezone

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.indicators import add_indicators
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_strategy import Lbr310AntiContextStrategy
from crypto_paper_trader_api.trading_profiles import get_trading_profile


def _account() -> StrategyAccount:
    return StrategyAccount(
        experiment_id="test",
        strategy_code="LBR_310_ANTI_CONTEXT",
        display_name="LBR 3/10 Anti",
        initial_capital=1000,
        cash_balance=1000,
        max_equity=1000,
    )


def _frame() -> pd.DataFrame:
    start = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for index in range(260):
        # Stable previous day, bullish impulse, weak pullback, then hook candle.
        if 220 <= index < 226:
            delta = 0.75
        elif 226 <= index < 229:
            delta = -0.18
        elif index == 229:
            delta = 0.55
        else:
            delta = 0.08
        open_price = price
        close = price + delta
        rows.append({
            "timestamp": start + timedelta(minutes=30 * index),
            "open": open_price,
            "high": max(open_price, close) + 0.12,
            "low": min(open_price, close) - 0.12,
            "close": close,
            "volume": 1000 + (400 if 220 <= index < 226 else 0),
        })
        price = close
    return add_indicators(pd.DataFrame(rows)).dropna().reset_index(drop=True)


def test_lbr_indicator_uses_simple_3_10_and_16_period_lines() -> None:
    frame = _frame()
    row = frame.iloc[-1]
    assert "lbr_310_fast" in frame.columns
    assert "lbr_310_slow" in frame.columns
    assert float(row["lbr_310_fast"]) == float(row["sma_3"] - row["sma_10"])


def test_utc_baseline_uses_completed_previous_day_and_last_hour() -> None:
    frame = _frame()
    strategy = Lbr310AntiContextStrategy(Settings())
    timestamp = pd.Timestamp(frame.iloc[-1]["timestamp"]).to_pydatetime()
    baseline = strategy._utc_baseline(frame, timestamp)
    assert baseline["available"] is True
    assert baseline["previous_return"] is not None
    assert baseline["closing_hour_return"] is not None


def test_setup_requires_later_closed_candle_for_entry() -> None:
    settings = Settings(
        lbr_anti_require_utc_baseline_alignment=False,
        lbr_anti_require_signal_cross=False,
        lbr_anti_min_impulse_atr=0.2,
        lbr_anti_max_pullback_strength=1.2,
        lbr_anti_max_pullback_range_ratio=2.0,
        entry_min_body_atr=0.01,
        exhaustion_max_entry_score=1.0,
        entry_max_extension_atr=10.0,
    )
    strategy = Lbr310AntiContextStrategy(settings)
    frame = _frame()
    account = _account()
    costs = ExecutionCosts(
        maker_fee_rate=0.0,
        taker_fee_rate=0.0005,
        spread_rate=0.0002,
        slippage_rate=0.0005,
        fee_source="TEST",
    )
    profile = get_trading_profile("BALANCED_INTRADAY")

    # Search chronologically for the first armed setup.
    armed_at = None
    for index in range(30, len(frame)):
        decision = strategy.decide(account, frame, index, frame.iloc[index], costs, profile)
        if decision.setup_status == "ARMED":
            armed_at = index
            break
    assert armed_at is not None
    assert decision.final_signal == "HOLD"
    assert account.entry_trigger_price is not None

    trigger = float(account.entry_trigger_price)
    next_row = frame.iloc[armed_at].copy()
    next_row["timestamp"] = pd.Timestamp(next_row["timestamp"]) + pd.Timedelta(minutes=30)
    next_row["open"] = trigger
    next_row["low"] = trigger - 0.05
    next_row["high"] = trigger + 0.30
    next_row["close"] = trigger + 0.25
    next_row["lbr_310_slow"] = float(frame.iloc[armed_at]["lbr_310_slow"]) + 0.05
    next_row["lbr_310_fast"] = float(next_row["lbr_310_slow"]) + 0.20
    next_row["lbr_310_fast_slope"] = 0.10
    next_row["lbr_310_slow_slope"] = 0.05
    next_row["extension_ema20_atr"] = 0.25
    next_row["exhaustion_score"] = 0.10
    next_row["ignition_score"] = 0.70
    next_row["body_ratio"] = 0.70
    extended = pd.concat([frame.iloc[: armed_at + 1], pd.DataFrame([next_row])], ignore_index=True)
    buy = strategy.decide(account, extended, len(extended) - 1, next_row, costs, profile)
    assert buy.final_signal == "BUY"
    assert buy.stop_loss_override is not None
    assert buy.take_profit_override is not None
