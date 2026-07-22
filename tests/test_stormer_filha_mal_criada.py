from datetime import datetime, timezone

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_strategy import StormerFilhaMalCriadaStrategy
from crypto_paper_trader_api.trading_profiles import get_trading_profile


def row(
    close=110.0,
    high=111.0,
    low=104.5,
    open_price=109.0,
    timestamp="2026-07-21T12:00:00Z",
    ema_shift=0.0,
):
    values = {
        "timestamp": pd.Timestamp(timestamp), "open": open_price, "high": high, "low": low, "close": close,
        "atr_14": 2.0, "ema_20": 108.0 + ema_shift, "ema_25": 107.0 + ema_shift, "ema_30": 106.0 + ema_shift,
        "ema_35": 105.0 + ema_shift, "ema_40": 104.0 + ema_shift, "ema_45": 103.0 + ema_shift, "ema_50": 102.0 + ema_shift,
    }
    return pd.Series(values)


def account():
    return StrategyAccount(experiment_id="x", strategy_code="STORMER_FILHA_MAL_CRIADA", display_name="Stormer Filha Mal Criada", initial_capital=1000, cash_balance=1000, max_equity=1000)


def costs():
    return ExecutionCosts(maker_fee_rate=0.0, taker_fee_rate=0.0, spread_rate=0.0, slippage_rate=0.0, fee_source="TEST")


def test_arms_after_pullback_into_aligned_ribbon():
    strategy = StormerFilhaMalCriadaStrategy(Settings())
    acc = account()
    decision = strategy.decide(acc, row(), row(timestamp="2026-07-21T11:30:00Z", low=106.0, ema_shift=-0.5), row(close=110, low=106), costs(), get_trading_profile(None))
    assert decision.final_signal == "HOLD"
    assert decision.setup_status == "ARMED"
    assert acc.entry_trigger_price is not None
    assert acc.initial_setup_stop_price is not None
    assert acc.setup_target_price > acc.entry_trigger_price


def test_triggers_buy_when_later_candle_breaks_armed_high():
    strategy = StormerFilhaMalCriadaStrategy(Settings())
    acc = account()
    strategy.decide(acc, row(), row(timestamp="2026-07-21T11:30:00Z", low=106.0, ema_shift=-0.5), row(close=110, low=106), costs(), get_trading_profile(None))
    trigger = acc.entry_trigger_price
    later = row(
        open_price=trigger - 0.2,
        close=trigger + 0.2,
        high=trigger + 0.5,
        low=108.5,
        timestamp="2026-07-21T12:30:00Z",
    )
    decision = strategy.decide(acc, later, row(timestamp="2026-07-21T12:00:00Z", low=108.0, ema_shift=-0.5), row(close=110, low=106), costs(), get_trading_profile(None))
    assert decision.final_signal == "BUY"
    assert decision.reward_risk_ratio == 3.0
