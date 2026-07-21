# Crypto Paper Trader API — v0.13.3

PAPER_ONLY FastAPI service for comparing Spot crypto strategies with public MEXC market data. The project contains no authenticated order, transfer, deposit or withdrawal implementation.

## Release 0.13.3

### Administrative reset

A protected reset endpoint was added:

```http
POST /api/v1/admin/reset
X-Admin-Key: <ADMIN_API_KEY>
```

The operation:

- waits for the current worker cycle to finish;
- deletes all experiments and their dependent strategy, trade, decision, candle and snapshot records;
- preserves the separate AI market-history database;
- wakes the worker after the reset;
- rejects missing or invalid keys.

Configure a long random secret only in the API service:

```env
ADMIN_API_KEY=replace-with-a-long-random-secret
```

Never expose this value through a `VITE_*` variable.

## Release 0.13.1

This patch normalizes all AI history candle timestamps to UTC before persistence, comparison and gap analysis. It fixes the Windows/SQLite runtime error `TypeError: Cannot compare tz-naive and tz-aware timestamps` without requiring a database reset.

## Release 0.13.0

This release migrated the public market-data provider from CoinEx to MEXC and added an explainable adaptive strategy layer.

### Main capabilities

- MEXC Spot public price, order-book, exchange-information and candlestick integration.
- Balanced profile: `30min` decision candles with `1hour` trend confirmation.
- Conservative profile: `1hour` decisions with `4hour` confirmation.
- Fast profile: `15min` decisions with `1hour` confirmation.
- EMA Pullback strategy.
- Larry Volatility Breakout strategy.
- Adaptive Strategy Selector that can choose a candidate strategy or remain on `HOLD`.
- Post-exit selector reward and selected-strategy audit fields.
- Additive SQLite migrations compatible with existing persistent databases.

## Active strategy portfolios

Each strategy receives the same closed candles and owns an independent paper portfolio:

1. Adaptive Strategy Selector
2. Profile-Aware Hybrid + ML
3. EMA Crossover
4. EMA Pullback
5. Larry Williams 9.1 Classic
6. Larry Williams 9.1 Trend Follower
7. Larry Volatility Breakout
8. AI Pattern Trader

## Paper execution and costs

```text
Public market data -> strategy signal -> paper broker -> accounting
```

- Buys execute from the best ask; sells execute from the best bid.
- Configurable slippage is applied after bid/ask selection.
- The default MEXC API Spot assumption is `0.05%` taker per execution and `0%` maker.
- Public promotional rates are not applied automatically when `USE_PUBLIC_MARKET_FEE_RATES=false`.
- Spread, slippage and fees affect net accounting only; no exchange order is sent.

## Local execution

```powershell
poetry config virtualenvs.in-project true
poetry install
poetry run uvicorn crypto_paper_trader_api.app:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

API documentation:

```text
http://localhost:8000/docs
```

Run tests:

```powershell
poetry run pytest
```

## Configuration

Copy `.env.example` to `.env`. Important defaults:

```env
MEXC_BASE_URL=https://api.mexc.com
DEFAULT_EXECUTION_TIMEFRAME=30min
DEFAULT_TREND_TIMEFRAME=1hour
TAKER_FEE_RATE=0.0005
SLIPPAGE_RATE=0.0005
SELECTOR_MIN_CONFIDENCE=0.60
SELECTOR_MIN_EXPECTED_NET_RETURN=0.0030
ADMIN_API_KEY=replace-with-a-long-random-secret
```

## Persistence and Railway

Attach a persistent Railway Volume to the API service, preferably at `/data`. The application prioritizes `RAILWAY_VOLUME_MOUNT_PATH` when Railway provides it.

The main database stores experiments, portfolios, decisions, trades and selector audit data. The separate AI database stores the long-history AI Pattern Trader candles and sync state. The administrative reset clears only the main paper-trading data and intentionally preserves AI history.

Recommended production settings:

```env
APP_ENV=production
CORS_ORIGINS=https://your-frontend-domain
ADMIN_API_KEY=replace-with-a-long-random-secret
```

## Recovery policy

After a restart, every missing closed decision candle is replayed chronologically. Recovered actions remain simulated and are marked in the database. The worker never converts a missed historical signal into an authenticated or late live order.

## Safety boundary

The code uses only public MEXC market-data endpoints. It has no API-key fields and no authenticated trading, transfer or withdrawal client methods. All portfolios and executions are simulated.
