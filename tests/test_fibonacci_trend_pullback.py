from __future__ import annotations

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_strategy import FibonacciTrendPullbackStrategy
from crypto_paper_trader_api.strategy_codes import FIBONACCI_TREND_PULLBACK
from crypto_paper_trader_api.trading_profiles import get_trading_profile


def costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.0,
        taker_fee_rate=0.0005,
        spread_rate=0.0002,
        slippage_rate=0.0005,
        fee_source="TEST",
    )


def account() -> StrategyAccount:
    return StrategyAccount(
        experiment_id="experiment",
        strategy_code=FIBONACCI_TREND_PULLBACK,
        display_name="Fibonacci Trend Pullback",
        initial_capital=1000,
        cash_balance=1000,
        max_equity=1000,
        setup_status="N/A",
    )


def frame() -> pd.DataFrame:
    rows = 11
    data = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-07-20", periods=rows, freq="30min", tz="UTC"),
            "open": [99, 98, 97, 92, 96, 100, 103, 106, 108, 104, 101],
            "high": [100, 99, 98, 97, 100, 103, 106, 109, 110, 106, 105],
            "low": [98, 97, 96, 90, 95, 99, 102, 105, 107, 101, 100],
            "close": [99, 98, 97, 95, 99, 102, 105, 108, 109, 102, 104],
            "volume": [1000.0] * rows,
            "atr_14": [5.0] * rows,
            "ema_9": [96, 96, 96, 96, 97, 98, 99, 100, 101, 102, 103],
            "ema_21": [95, 95, 95, 95, 96, 97, 98, 99, 100, 101, 102],
            "ema_50": [93, 93, 93, 93, 94, 95, 96, 97, 98, 99, 100],
            "adx_14": [25.0] * rows,
            "relative_volume": [1.20] * rows,
            "rsi_14": [55.0] * rows,
            "ignition_score": [0.4] * rows,
            "exhaustion_score": [0.2] * rows,
            "compression_ratio": [0.9] * rows,
        }
    )
    return data


def test_fibonacci_pullback_buys_after_recovery_in_retracement_zone() -> None:
    settings = Settings(
        fibonacci_pivot_bars=2,
        fibonacci_min_impulse_atr=2.0,
        fibonacci_stop_buffer_atr=0.25,
        fibonacci_max_stop_distance_atr=3.0,
    )
    strategy = FibonacciTrendPullbackStrategy(settings)
    data = frame()
    trend_row = pd.Series(
        {"close": 110.0, "ema_21": 105.0, "ema_50": 100.0}
    )

    decision = strategy.decide(
        account=account(),
        history=data,
        current_index=len(data) - 1,
        trend_row=trend_row,
        costs=costs(),
        profile=get_trading_profile(None),
    )

    assert decision.final_signal == "BUY"
    assert decision.stop_loss_override is not None
    assert decision.take_profit_override is not None
    assert decision.stop_loss_override < float(data.iloc[-1]["close"])
    assert decision.reward_risk_ratio is not None
    assert decision.reward_risk_ratio >= settings.fibonacci_pullback_reward_risk_ratio
    assert "fibonacci_pullback_entry_approved" in decision.reason
