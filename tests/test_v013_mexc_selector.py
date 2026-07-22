from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest

from crypto_paper_trader_api.adaptive_strategy_research import StrategySpecification
from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.mexc_client import MEXCPublicClient
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_strategy import (
    AdaptiveStrategySelector,
    EmaPullbackStrategy,
    LarryVolatilityBreakoutStrategy,
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
    current = row(low=100.7, close=103.5, high=104.0)
    previous = row(close=103.0)
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


def test_adaptive_selector_executes_generated_strategy() -> None:
    settings = Settings(_env_file=None, adaptive_research_web_enabled=False)
    selector_account = account("ADAPTIVE_STRATEGY_SELECTOR")
    spec = StrategySpecification(
        code="GEN_TREND_PULLBACK_TEST",
        name="Adaptive EMA ATR Pullback",
        family="TREND_PULLBACK",
        origin="SYSTEM_GENERATED",
        rationale="test hypothesis",
        allowed_regimes=("STRONG_UPTREND", "WEAK_UPTREND", "TRANSITION"),
        fast_ema=9,
        slow_ema=20,
        regime_ema=200,
        rsi_min=40,
        rsi_max=70,
        adx_min=18,
        relative_volume_min=1.0,
        pullback_atr=0.5,
    )
    selector_account.selector_strategy_spec_json = spec.to_json()
    selector_account.selector_selected_strategy = spec.code
    selector_account.selector_active_strategy_name = spec.name
    selector_account.selector_strategy_origin = spec.origin
    selector_account.selector_research_status = "ACTIVE"
    selector_account.selector_market_regime = "STRONG_UPTREND"
    selector_account.selector_next_research_at = datetime.now(timezone.utc) + timedelta(hours=1)
    selector_account.selector_validation_score = 75.0

    previous = row(close=101.5, low=100.5)
    current = row(close=103.0, low=101.0)
    frame = pd.DataFrame([previous.to_dict(), current.to_dict()])
    frame["timestamp"] = pd.to_datetime(
        ["2026-07-21T10:00:00Z", "2026-07-21T10:30:00Z"]
    )
    frame["return_3"] = [0.0, 0.01]
    frame["atr_pct"] = frame["atr_14"] / frame["close"]

    decision = AdaptiveStrategySelector(settings).decide(
        selector_account,
        current,
        row(close=105.0, ema_50=99.0),
        costs(),
        frame,
        1,
        "BTCUSDT",
        "30min",
        "1hour",
        datetime.now(timezone.utc),
    )
    assert decision.final_signal == "BUY"
    assert decision.selector_selected_strategy == spec.code
    assert decision.selector_active_strategy_name == spec.name


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
