from __future__ import annotations

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_strategy import (
    EmaCrossoverStrategy,
    LarryVolatilityBreakoutStrategy,
    StormerFilhaMalCriadaStrategy,
)
from crypto_paper_trader_api.strategy_codes import (
    EMA_CROSSOVER,
    LARRY_VOLATILITY_BREAKOUT,
    STORMER_FILHA_MAL_CRIADA,
)
from crypto_paper_trader_api.trading_profiles import get_trading_profile


def account(code: str) -> StrategyAccount:
    return StrategyAccount(
        experiment_id="experiment",
        strategy_code=code,
        display_name=code,
        initial_capital=1000,
        cash_balance=1000,
        max_equity=1000,
        setup_status="IDLE",
    )


def costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        spread_rate=0.0,
        slippage_rate=0.0,
        fee_source="TEST",
    )


def crossover_row(
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    ema9: float,
    ema21: float,
    ema50: float,
) -> pd.Series:
    return pd.Series(
        {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "atr_14": 1.0,
            "ema_9": ema9,
            "ema_21": ema21,
            "ema_50": ema50,
            "adx_14": 25.0,
            "relative_volume": 1.2,
            "rsi_14": 55.0,
        }
    )


def test_ema_crossover_rejects_a_red_crossing_candle() -> None:
    settings = Settings()
    profile = get_trading_profile(None)
    strategy = EmaCrossoverStrategy(settings)

    current = crossover_row(
        open_price=103.0,
        high=103.5,
        low=101.5,
        close=102.0,
        ema9=101.0,
        ema21=100.0,
        ema50=98.0,
    )
    previous = crossover_row(
        open_price=100.0,
        high=100.5,
        low=99.0,
        close=100.0,
        ema9=99.0,
        ema21=100.0,
        ema50=98.0,
    )
    trend = crossover_row(
        open_price=108.0,
        high=111.0,
        low=107.0,
        close=110.0,
        ema9=105.0,
        ema21=104.0,
        ema50=100.0,
    )

    decision = strategy.decide(
        account(EMA_CROSSOVER), current, previous, trend, costs(), profile
    )

    assert decision.final_signal == "HOLD"
    assert "entry_body_atr" in decision.reason
    assert "crossover_entry_filters_not_all_satisfied" in decision.reason


def test_volatility_breakout_rejects_a_wick_without_buffered_close() -> None:
    settings = Settings()
    profile = get_trading_profile(None)
    strategy = LarryVolatilityBreakoutStrategy(settings)
    previous_window = pd.DataFrame(
        {
            "high": [100.0, 99.8, 99.9],
            "low": [98.0, 98.2, 98.1],
        }
    )
    current = pd.Series(
        {
            "open": 100.5,
            "high": 101.5,
            "low": 100.2,
            "close": 100.9,
            "atr_14": 1.0,
            "ema_9": 100.0,
            "ema_21": 99.5,
            "ema_50": 99.0,
            "adx_14": 25.0,
            "relative_volume": 1.2,
            "rsi_14": 55.0,
        }
    )
    trend = pd.Series(
        {
            "open": 103.0,
            "high": 105.0,
            "low": 102.0,
            "close": 104.0,
            "atr_14": 1.0,
            "ema_9": 103.0,
            "ema_21": 102.0,
            "ema_50": 100.0,
            "adx_14": 25.0,
            "relative_volume": 1.2,
            "rsi_14": 55.0,
        }
    )

    decision = strategy.decide(
        account(LARRY_VOLATILITY_BREAKOUT),
        current,
        previous_window,
        trend,
        costs(),
        profile,
    )

    assert decision.final_signal == "HOLD"
    assert "breakout=False" in decision.reason


def stormer_row(
    *,
    timestamp: str,
    open_price: float = 109.0,
    high: float = 111.0,
    low: float = 104.5,
    close: float = 110.0,
    ema_shift: float = 0.0,
) -> pd.Series:
    return pd.Series(
        {
            "timestamp": pd.Timestamp(timestamp),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "atr_14": 2.0,
            "ema_20": 108.0 + ema_shift,
            "ema_25": 107.0 + ema_shift,
            "ema_30": 106.0 + ema_shift,
            "ema_35": 105.0 + ema_shift,
            "ema_40": 104.0 + ema_shift,
            "ema_45": 103.0 + ema_shift,
            "ema_50": 102.0 + ema_shift,
        }
    )


def test_stormer_rejects_wick_only_breakout() -> None:
    settings = Settings()
    profile = get_trading_profile(None)
    strategy = StormerFilhaMalCriadaStrategy(settings)
    item = account(STORMER_FILHA_MAL_CRIADA)

    strategy.decide(
        item,
        stormer_row(timestamp="2026-07-22T09:30:00Z"),
        stormer_row(timestamp="2026-07-22T09:00:00Z", low=106.0, ema_shift=-0.5),
        stormer_row(timestamp="2026-07-22T09:00:00Z", low=106.0),
        costs(),
        profile,
    )
    trigger = float(item.entry_trigger_price)

    wick_only = stormer_row(
        timestamp="2026-07-22T10:00:00Z",
        open_price=trigger - 0.3,
        high=trigger + 0.5,
        low=108.5,
        close=trigger - 0.1,
    )
    decision = strategy.decide(
        item,
        wick_only,
        stormer_row(timestamp="2026-07-22T09:30:00Z", low=108.5, ema_shift=-0.5),
        stormer_row(timestamp="2026-07-22T10:00:00Z", low=106.0),
        costs(),
        profile,
    )

    assert decision.final_signal == "HOLD"
    assert item.has_open_position is False
    assert item.setup_status == "ARMED"
