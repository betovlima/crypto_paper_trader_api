from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Crypto Paper Trader"
    app_env: str = "development"
    log_level: str = "INFO"

    data_dir: Path = Path("./data")
    reports_dir: Path | None = None
    database_url: str | None = None

    coinex_base_url: str = "https://api.coinex.com/v2"
    http_timeout_seconds: float = 20.0
    poll_interval_seconds: int = Field(default=15, ge=10, le=900)

    default_market: str = "BTCUSDT"
    default_execution_timeframe: str = "1hour"
    default_trend_timeframe: str = "4hour"
    default_duration_hours: float = Field(default=24.0, gt=0, le=168)
    default_initial_capital: float = Field(default=1000.0, gt=0)

    # CoinEx Spot VIP 0 baseline. PAPER_ONLY uses taker rates because it simulates
    # immediate marketable executions. Public market metadata can refresh these rates.
    vip_level: str = "VIP0"
    maker_fee_rate: float = Field(default=0.002, ge=0, lt=0.1)
    taker_fee_rate: float = Field(default=0.002, ge=0, lt=0.1)
    use_public_market_fee_rates: bool = True
    cet_fee_discount_enabled: bool = False
    cet_fee_discount_pct: float = Field(default=0.20, ge=0, lt=1)

    # Execution friction beyond exchange fees.
    fallback_spread_rate: float = Field(default=0.0002, ge=0, lt=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, lt=0.1)
    position_allocation: float = Field(default=0.95, gt=0, le=1)

    buy_probability_threshold: float = Field(default=0.55, ge=0.5, le=1)
    sell_probability_threshold: float = Field(default=0.42, ge=0, le=0.5)
    min_technical_confirmations: int = Field(default=4, ge=1, le=8)

    # Hybrid stop: ATR distance constrained by percentage limits.
    stop_atr_multiplier: float = Field(default=2.0, gt=0)
    stop_loss_min_pct: float = Field(default=0.01, gt=0, lt=1)
    stop_loss_max_pct: float = Field(default=0.03, gt=0, lt=1)
    reward_risk_ratio: float = Field(default=1.5, gt=0)
    take_profit_atr_multiplier: float = Field(default=3.0, gt=0)
    trailing_atr_multiplier: float = Field(default=2.0, gt=0)
    trailing_activation_r: float = Field(default=1.0, ge=0)
    break_even_activation_r: float = Field(default=1.0, ge=0)
    max_holding_hours: float = Field(default=12.0, gt=0, le=168)

    max_daily_loss_pct: float = Field(default=0.03, gt=0, le=1)
    max_consecutive_losses: int = Field(default=3, ge=1, le=20)
    cooldown_minutes: int = Field(default=60, ge=0, le=1440)

    cors_origins: str = "http://localhost:5173"
    admin_api_key: str | None = None

    # EMA9 Setup 9.1 comparison settings.
    ema9_period: int = Field(default=9, ge=2, le=100)
    ema9_entry_tick_rate: float = Field(default=0.0, ge=0, lt=0.01)

    # Autonomous AI Pattern Trader. This remains PAPER_ONLY and learns directly
    # from chronological OHLCV windows instead of selecting a handcrafted setup.
    ai_pattern_mode: str = "PAPER_AUTONOMOUS"
    ai_pattern_horizon_candles: int = Field(default=5, ge=2, le=24)
    ai_pattern_min_training_rows: int = Field(default=240, ge=120, le=2000)
    ai_pattern_training_max_rows: int = Field(default=900, ge=240, le=5000)
    ai_pattern_neighbors: int = Field(default=32, ge=8, le=200)
    ai_pattern_clusters: int = Field(default=8, ge=2, le=32)
    ai_pattern_tree_count: int = Field(default=96, ge=32, le=300)
    ai_pattern_tree_max_depth: int = Field(default=7, ge=3, le=20)
    ai_pattern_min_samples_leaf: int = Field(default=6, ge=2, le=50)
    ai_pattern_random_state: int = 91
    ai_pattern_buy_probability_threshold: float = Field(default=0.61, ge=0.5, le=0.95)
    ai_pattern_sell_probability_threshold: float = Field(default=0.43, ge=0.05, le=0.5)
    ai_pattern_min_expected_net_return: float = Field(default=0.0015, ge=0, le=0.1)
    ai_pattern_min_confidence: float = Field(default=0.52, ge=0, le=1)
    ai_pattern_high_vol_min_confidence: float = Field(default=0.68, ge=0, le=1)
    ai_pattern_max_spread_rate: float = Field(default=0.006, ge=0, le=0.05)
    ai_pattern_stop_atr_multiplier: float = Field(default=1.8, gt=0, le=10)
    ai_pattern_target_atr_multiplier: float = Field(default=2.8, gt=0, le=20)
    ai_pattern_reward_risk_ratio: float = Field(default=1.8, gt=0, le=10)
    ai_pattern_adverse_buffer: float = Field(default=0.75, gt=0, le=2)
    ai_pattern_reward_drawdown_penalty: float = Field(default=0.30, ge=0, le=2)
    ai_pattern_confident_rows: int = Field(default=600, ge=100, le=5000)

    @field_validator("default_market")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned or not cleaned.isalnum():
            raise ValueError("Market must contain only letters and numbers.")
        return cleaned

    @field_validator("ai_pattern_mode")
    @classmethod
    def normalize_ai_pattern_mode(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"OBSERVATION", "PAPER_AUTONOMOUS"}:
            raise ValueError("ai_pattern_mode must be OBSERVATION or PAPER_AUTONOMOUS")
        return normalized

    @field_validator("vip_level")
    @classmethod
    def normalize_vip_level(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("stop_loss_max_pct")
    @classmethod
    def validate_stop_loss_max_pct(cls, value: float, info):
        minimum = info.data.get("stop_loss_min_pct")
        if minimum is not None and value < minimum:
            raise ValueError("stop_loss_max_pct must be >= stop_loss_min_pct")
        return value

    @property
    def railway_volume_mount_path(self) -> Path | None:
        """Return the Railway volume mount path injected at runtime, when present."""
        raw_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
        return Path(raw_path).expanduser() if raw_path else None

    @property
    def resolved_data_dir(self) -> Path:
        """Resolve the runtime data directory, preferring an attached Railway volume.

        Railway automatically exposes ``RAILWAY_VOLUME_MOUNT_PATH`` when a volume is
        attached. Preferring that value prevents an accidental fallback to the ephemeral
        application filesystem after a deployment.
        """
        railway_mount = self.railway_volume_mount_path
        if railway_mount is not None:
            path = railway_mount
        elif self.app_env.strip().lower() == "production" and self.data_dir == Path("./data"):
            path = Path("/data")
        else:
            path = self.data_dir

        path = path.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def persistent_storage_configured(self) -> bool:
        """Whether Railway reports an attached persistent volume."""
        return self.railway_volume_mount_path is not None

    @property
    def storage_warning(self) -> str | None:
        if os.getenv("RAILWAY_ENVIRONMENT") and not self.persistent_storage_configured:
            return (
                "No Railway volume is attached. SQLite data will be lost on every deploy. "
                "Attach a volume to the API service, preferably at /data."
            )
        return None

    @property
    def resolved_reports_dir(self) -> Path:
        path = (self.reports_dir or (self.resolved_data_dir / "reports")).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate_persistent_storage(self) -> None:
        """Fail fast on Railway when no persistent volume is attached.

        Starting with an ephemeral SQLite database would make an experiment appear to
        disappear after every deployment. It is safer to refuse startup than to run
        silently without durable state.
        """
        if os.getenv("RAILWAY_ENVIRONMENT") and not self.persistent_storage_configured:
            raise RuntimeError(
                "A Railway persistent volume is required for the API service. "
                "Attach a volume at /data before starting the application."
            )

    @property
    def resolved_database_url(self) -> str:
        railway_mount = self.railway_volume_mount_path
        if railway_mount is not None:
            database_path = self.resolved_data_dir / "crypto_paper_trader_api.db"
            return f"sqlite:///{database_path.as_posix()}"

        if self.database_url:
            return self.database_url

        database_path = self.resolved_data_dir / "crypto_paper_trader_api.db"
        return f"sqlite:///{database_path.as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        """Return normalized browser origins accepted by CORS.

        Browser Origin headers never contain a trailing slash. Railway variables are
        often pasted from the public URL with a trailing slash, so normalize both
        comma-separated and JSON-like values before configuring CORSMiddleware.
        """
        raw_value = self.cors_origins.strip()
        if raw_value.startswith("[") and raw_value.endswith("]"):
            raw_value = raw_value[1:-1]

        origins: list[str] = []
        for item in raw_value.split(","):
            origin = item.strip().strip('"').strip("'").rstrip("/")
            if origin and origin not in origins:
                origins.append(origin)
        return origins

    @property
    def effective_default_taker_fee_rate(self) -> float:
        if self.cet_fee_discount_enabled:
            return self.taker_fee_rate * (1 - self.cet_fee_discount_pct)
        return self.taker_fee_rate

    @property
    def effective_default_maker_fee_rate(self) -> float:
        if self.cet_fee_discount_enabled:
            return self.maker_fee_rate * (1 - self.cet_fee_discount_pct)
        return self.maker_fee_rate

    def estimated_round_trip_cost_rate(
        self,
        spread_rate: float | None = None,
        taker_fee_rate: float | None = None,
    ) -> float:
        """Approximate two-sided fee + full spread + two-sided slippage."""
        fee = self.effective_default_taker_fee_rate if taker_fee_rate is None else taker_fee_rate
        spread = self.fallback_spread_rate if spread_rate is None else max(spread_rate, 0.0)
        return 2 * fee + spread + 2 * self.slippage_rate

    @property
    def round_trip_cost_rate(self) -> float:
        """Backward-compatible default used before a live spread snapshot exists."""
        return self.estimated_round_trip_cost_rate()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
