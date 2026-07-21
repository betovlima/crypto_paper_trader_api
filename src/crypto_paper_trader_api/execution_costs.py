from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketRules:
    market: str
    maker_fee_rate: float
    taker_fee_rate: float
    min_amount: float
    base_currency: str
    quote_currency: str
    base_precision: int
    quote_precision: int
    status: str
    source: str = "MEXC_PUBLIC_EXCHANGE_INFO"


@dataclass(frozen=True)
class DepthSnapshot:
    market: str
    best_bid: float
    best_ask: float
    mid_price: float
    spread_rate: float
    updated_at_ms: int


@dataclass(frozen=True)
class ExecutionCosts:
    """Costs used by one simulated decision/execution cycle."""

    maker_fee_rate: float
    taker_fee_rate: float
    spread_rate: float
    slippage_rate: float
    fee_source: str

    @property
    def half_spread_rate(self) -> float:
        return max(self.spread_rate, 0.0) / 2

    @property
    def estimated_round_trip_rate(self) -> float:
        return 2 * self.taker_fee_rate + self.spread_rate + 2 * self.slippage_rate

    @property
    def entry_market_impact_rate(self) -> float:
        return self.half_spread_rate + self.slippage_rate

    @property
    def exit_market_impact_rate(self) -> float:
        return self.half_spread_rate + self.slippage_rate
