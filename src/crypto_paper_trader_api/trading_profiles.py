from __future__ import annotations

from dataclasses import asdict, dataclass


CONSERVATIVE_SWING = "CONSERVATIVE_SWING"
BALANCED_INTRADAY = "BALANCED_INTRADAY"
FAST_INTRADAY = "FAST_INTRADAY"


@dataclass(frozen=True)
class TradingProfile:
    code: str
    display_name: str
    style: str
    description: str
    decision_timeframe: str
    trend_timeframe: str
    default_duration_hours: float
    fast_ema_period: int
    slow_ema_period: int
    regime_ema_period: int
    buy_probability_threshold: float
    sell_probability_threshold: float
    min_technical_confirmations: int
    adx_min: float
    trend_adx_min: float
    relative_volume_min: float
    rsi_buy_min: float
    rsi_buy_max: float
    position_allocation: float
    stop_atr_multiplier: float
    stop_loss_min_pct: float
    stop_loss_max_pct: float
    reward_risk_ratio: float
    take_profit_atr_multiplier: float
    trailing_atr_multiplier: float
    trailing_activation_r: float
    break_even_activation_r: float
    max_holding_hours: float
    max_daily_loss_pct: float
    max_consecutive_losses: int
    cooldown_minutes: int

    def to_public_dict(self) -> dict[str, object]:
        return asdict(self)


TRADING_PROFILES: dict[str, TradingProfile] = {
    CONSERVATIVE_SWING: TradingProfile(
        code=CONSERVATIVE_SWING,
        display_name="Conservative Swing",
        style="Slower intraday trend following",
        description=(
            "Uses 1-hour decisions and a 4-hour trend filter. EMA 20/50/200, stronger "
            "technical confirmations, wider volatility-aware stops and a longer holding window "
            "reduce noise and trading frequency."
        ),
        decision_timeframe="1hour",
        trend_timeframe="4hour",
        default_duration_hours=168.0,
        fast_ema_period=20,
        slow_ema_period=50,
        regime_ema_period=200,
        buy_probability_threshold=0.60,
        sell_probability_threshold=0.40,
        min_technical_confirmations=5,
        adx_min=20.0,
        trend_adx_min=18.0,
        relative_volume_min=1.00,
        rsi_buy_min=50.0,
        rsi_buy_max=65.0,
        position_allocation=0.90,
        stop_atr_multiplier=2.5,
        stop_loss_min_pct=0.02,
        stop_loss_max_pct=0.05,
        reward_risk_ratio=2.0,
        take_profit_atr_multiplier=4.0,
        trailing_atr_multiplier=2.5,
        trailing_activation_r=1.25,
        break_even_activation_r=1.0,
        max_holding_hours=72.0,
        max_daily_loss_pct=0.02,
        max_consecutive_losses=2,
        cooldown_minutes=240,
    ),
    BALANCED_INTRADAY: TradingProfile(
        code=BALANCED_INTRADAY,
        display_name="Balanced Intraday",
        style="Thirty-minute intraday decisions",
        description=(
            "Uses 30-minute decisions and a 1-hour trend filter. EMA 9/21/50 reacts faster than "
            "the conservative profile while RSI, ADX, volume and technical risk controls confirm "
            "signals. Exchange costs are reported after execution and do not veto entries."
        ),
        decision_timeframe="30min",
        trend_timeframe="1hour",
        default_duration_hours=24.0,
        fast_ema_period=9,
        slow_ema_period=21,
        regime_ema_period=50,
        buy_probability_threshold=0.56,
        sell_probability_threshold=0.42,
        min_technical_confirmations=4,
        adx_min=18.0,
        trend_adx_min=16.0,
        relative_volume_min=0.90,
        rsi_buy_min=48.0,
        rsi_buy_max=68.0,
        position_allocation=0.95,
        stop_atr_multiplier=2.0,
        stop_loss_min_pct=0.01,
        stop_loss_max_pct=0.03,
        reward_risk_ratio=1.5,
        take_profit_atr_multiplier=3.0,
        trailing_atr_multiplier=2.0,
        trailing_activation_r=1.0,
        break_even_activation_r=1.0,
        max_holding_hours=12.0,
        max_daily_loss_pct=0.03,
        max_consecutive_losses=3,
        cooldown_minutes=60,
    ),
    FAST_INTRADAY: TradingProfile(
        code=FAST_INTRADAY,
        display_name="Fast Intraday",
        style="Rapid short-term movements",
        description=(
            "Uses 15-minute decisions and a 1-hour trend filter. EMA 5/13/34 reacts quickly, "
            "while stricter ADX, volume and probability rules help control short-term noise. "
            "Fees remain an accounting result only."
        ),
        decision_timeframe="15min",
        trend_timeframe="1hour",
        default_duration_hours=24.0,
        fast_ema_period=5,
        slow_ema_period=13,
        regime_ema_period=34,
        buy_probability_threshold=0.60,
        sell_probability_threshold=0.40,
        min_technical_confirmations=5,
        adx_min=20.0,
        trend_adx_min=18.0,
        relative_volume_min=1.00,
        rsi_buy_min=50.0,
        rsi_buy_max=66.0,
        position_allocation=0.90,
        stop_atr_multiplier=1.5,
        stop_loss_min_pct=0.006,
        stop_loss_max_pct=0.02,
        reward_risk_ratio=1.5,
        take_profit_atr_multiplier=2.5,
        trailing_atr_multiplier=1.5,
        trailing_activation_r=0.9,
        break_even_activation_r=0.9,
        max_holding_hours=4.0,
        max_daily_loss_pct=0.02,
        max_consecutive_losses=2,
        cooldown_minutes=45,
    ),
}

DEFAULT_TRADING_PROFILE = BALANCED_INTRADAY


def get_trading_profile(code: str | None) -> TradingProfile:
    normalized = (code or DEFAULT_TRADING_PROFILE).strip().upper()
    try:
        return TRADING_PROFILES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported trading profile: {code}") from exc


def list_trading_profiles() -> list[dict[str, object]]:
    return [profile.to_public_dict() for profile in TRADING_PROFILES.values()]
