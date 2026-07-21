from __future__ import annotations

import httpx
import pandas as pd
import pytest

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.mexc_client import MEXCPublicClient
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_strategy import (
    AdaptiveStrategySelector,
    EmaPullbackStrategy,
    LarryVolatilityBreakoutStrategy,
    StrategyDecision,
)
from crypto_paper_trader_api.strategy_codes import EMA_PULLBACK
from crypto_paper_trader_api.trading_profiles import BALANCED_INTRADAY, get_trading_profile


def account(code: str = EMA_PULLBACK) -> StrategyAccount:
    return StrategyAccount(
        experiment_id="test",
        strategy_code=code,
        display_name=code,
        initial_capital=1000,
        cash_balance=1000,
        asset_quantity=0,
        max_equity=1000,
    )


def row(**overrides) -> pd.Series:
    values = {
        "open": 100.0,
        "high": 104.0,
        "low": 100.5,
        "close": 103.0,
        "ema_5": 102.5,
        "ema_9": 102.0,
        "ema_13": 101.5,
        "ema_20": 101.0,
        "ema_21": 100.8,
        "ema_34": 99.0,
        "ema_50": 98.0,
        "ema_200": 90.0,
        "atr_14": 2.0,
        "adx_14": 25.0,
        "relative_volume": 1.5,
        "rsi_14": 58.0,
        "volatility_20": 0.01,
    }
    values.update(overrides)
    return pd.Series(values)


def costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.0,
        taker_fee_rate=0.0005,
        spread_rate=0.0002,
        slippage_rate=0.0005,
        fee_source="MEXC_API_CONFIG",
    )


def test_ema_pullback_and_larry_breakout_can_emit_intraday_buy() -> None:
    settings = Settings(_env_file=None)
    profile = get_trading_profile(BALANCED_INTRADAY)
    current = row(low=100.7)
    previous = row(close=101.5)
    trend = row(close=105.0, ema_9=103.0, ema_21=101.0, ema_50=99.0)

    pullback = EmaPullbackStrategy(settings).decide(
        account(), current, previous, trend, costs(), profile
    )
    assert pullback.final_signal == "BUY"
    assert pullback.reward_risk_ratio is not None

    previous_window = pd.DataFrame(
        [
            {"high": 101.0, "low": 99.0},
            {"high": 102.0, "low": 98.0},
        ]
    )
    breakout = LarryVolatilityBreakoutStrategy(settings).decide(
        account("LARRY_VOLATILITY_BREAKOUT"),
        row(open=100.0, high=104.0, close=103.0),
        previous_window,
        trend,
        costs(),
        profile,
    )
    assert breakout.final_signal == "BUY"
    assert breakout.execution_reference_price == pytest.approx(102.0)


def test_adaptive_selector_ranks_positive_net_candidate() -> None:
    settings = Settings(_env_file=None)
    selector_account = account("ADAPTIVE_STRATEGY_SELECTOR")
    candidate = StrategyDecision(
        technical_signal="BUY",
        model_signal="NOT_USED",
        final_signal="BUY",
        technical_confirmations=6,
        reason="qualified pullback",
        execution_reference_price=103.0,
        potential_target_price=105.0,
        potential_gross_return=0.02,
        reward_risk_ratio=2.0,
        stop_loss_override=102.0,
        take_profit_override=105.0,
    )
    decision = AdaptiveStrategySelector(settings).decide(
        selector_account,
        row(),
        row(close=105.0, ema_50=99.0),
        costs(),
        {EMA_PULLBACK: candidate},
    )
    assert decision.final_signal == "BUY"
    assert decision.selector_selected_strategy == EMA_PULLBACK
    assert decision.selector_expected_net_return is not None
    assert decision.selector_expected_net_return > settings.selector_min_expected_net_return


@pytest.mark.asyncio
async def test_mexc_public_client_parses_price_book_and_klines() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ticker/price"):
            return httpx.Response(200, json={"symbol": "PENDLEUSDT", "price": "1.6500"})
        if request.url.path.endswith("/ticker/bookTicker"):
            return httpx.Response(
                200,
                json={"symbol": "PENDLEUSDT", "bidPrice": "1.6490", "askPrice": "1.6510"},
            )
        if request.url.path.endswith("/klines"):
            return httpx.Response(
                200,
                json=[
                    [1_700_000_000_000, "1.60", "1.70", "1.55", "1.65", "100", 1_700_001_799_999, "165"],
                ],
            )
        raise AssertionError(request.url)

    settings = Settings(_env_file=None)
    client = MEXCPublicClient(settings)
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://api.mexc.com",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await client.get_latest_price("PENDLEUSDT") == pytest.approx(1.65)
        depth = await client.get_depth_snapshot("PENDLEUSDT")
        assert depth.best_bid == pytest.approx(1.649)
        assert depth.best_ask == pytest.approx(1.651)
        candles = await client.get_candles("PENDLEUSDT", "30min", limit=1)
        assert list(candles.columns) == [
            "market", "timestamp", "open", "high", "low", "close", "volume", "value"
        ]
        assert float(candles.iloc[0]["close"]) == pytest.approx(1.65)
    finally:
        await client.close()
