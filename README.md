# Release 0.9.9 — Larry Williams Classic vs Trend Follower

This release runs two independent Setup 9.1 paper portfolios:

- **Larry Williams 9.1 Classic**: strict down-to-up EMA 9 reversal on a candle that crosses EMA 9; buy above that candle high; initial stop at that candle low; a later bearish EMA 9 reversal arms an exit below the bearish reversal candle low.
- **Larry Williams 9.1 Trend Follower**: same entry and initial stop; after entry, the stop follows the low of each newly closed candle and never moves down; the position also exits on a bearish EMA 9 reversal.

Existing `EMA9_SETUP_91_COST_AWARE` accounts are retained and are now labeled as the classic version. Existing experiments automatically receive the new trend-follower account without losing their prior state. SQLite migrations are additive.

# Crypto Paper Trader v0.9.2

Crypto Paper Trader is a PAPER_ONLY research application for comparing crypto trading techniques with public CoinEx Spot market data. It contains no authenticated order, transfer or withdrawal implementation.

## Core research policy

The application separates strategy logic from execution accounting:

```text
Technical setup -> BUY / HOLD / SELL signal
Paper broker    -> bid/ask execution and simulated slippage
Accounting      -> CoinEx fees, gross P&L and net P&L
```

Exchange fees, spread and slippage never authorize or veto a technical signal and never move a technical stop. They are recorded after each simulated execution so the dashboard can compare the strategy's gross result with the realistic net result.

## Trading profiles

Each experiment selects one profile. The profile defines decision candles, trend timeframe, EMA structure, technical confirmations, stop policy, holding period and portfolio risk limits.

### Conservative Swing

- Decision candle: `4hour`
- Trend timeframe: `1day`
- EMA structure: `20 / 50 / 200`
- Default duration: 168 hours
- Purpose: slower trend following, fewer signals and wider technical stops.

### Balanced Intraday

- Decision candle: `1hour`
- Trend timeframe: `4hour`
- EMA structure: `9 / 21 / 50`
- Default duration: 24 hours
- Purpose: one-hour intraday decisions with broader four-hour confirmation.

### Fast Intraday

- Decision candle: `15min`
- Trend timeframe: `1hour`
- EMA structure: `5 / 13 / 34`
- Default duration: 24 hours
- Purpose: faster reactions with stricter technical confirmation against short-term noise.

## Techniques compared

Every technique receives the same closed candles and market snapshots, but owns an independent simulated portfolio.

### Profile-Aware Hybrid

Combines the selected profile's fast, slow and regime EMAs with RSI, ADX, relative volume and an XGBoost next-candle direction estimate. Technical and model rules create the signal. Costs are informational and affect only net accounting.

### EMA Crossover

Looks for a fresh crossover of the fast EMA above the slow EMA. The regime EMA, higher-timeframe direction, ADX, relative volume and RSI confirm the technical entry. A bearish crossover or close below the slow EMA can close the position.

### Larry Williams 9.1

Detects a down-to-up turn in EMA 9 on closed candles. The reversal candle becomes the setup candle. The setup is armed until price breaks the setup candle high or EMA 9 turns down. The initial stop remains below the setup candle low. A closed candle below EMA 9 can close an open position.

### Buy and Hold

A passive benchmark that buys at the experiment start and displays its current liquidation value after equivalent execution costs.

## Downtime recovery

When the worker restarts, it reads `last_processed_candle_at`, downloads every missing closed candle and replays them chronologically. Recovered entries and exits are always paper trades and are explicitly marked in the database, dashboard and on-demand in-memory exports. The application never converts a missed historical signal into a late purchase at the current market price.

Hourly OHLC data cannot reveal the exact order of all intrabar events. During recovery, the simulator uses a conservative rule: if both a protective stop and target were touched in the same candle, the stop is assumed to have occurred first.

## Live dashboard

The React interface refreshes approximately every 15 seconds and shows:

- independent strategy status and equity;
- gross return, net return and cost impact;
- best bid, best ask and spread;
- technical stops and targets;
- Larry Williams setup state, trigger and last setup event;
- recovered candles and recovered paper trades;
- trade-level fee, spread, slippage, gross P&L and net P&L;
- simple help hints for non-technical users.

Indicators and new strategy decisions are recalculated only after a decision candle closes. Market price, portfolio equity and protective levels continue to update between candle closes.

## Transaction accounting

The default fallback for a CoinEx VIP 0 Spot account is a 0.20% taker fee per execution. The system can read public market-specific fee metadata. Simulated purchases use the best ask and simulated sales use the best bid; spread is therefore not deducted a second time. Configurable slippage is applied after bid/ask selection.

## Local execution with Poetry

### Backend

```powershell
cd crypto_paper_trader_api
poetry config virtualenvs.in-project true
poetry install
poetry run uvicorn crypto_paper_trader_api.app:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

Run tests:

```powershell
poetry run pytest
```

API documentation:

```text
http://localhost:8000/docs
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## Railway

- Attach one persistent volume to the **API service**, preferably mounted at `/data`.
- Railway injects `RAILWAY_VOLUME_MOUNT_PATH`; the API now uses that path automatically.
- Set `APP_ENV=production`.
- `DATA_DIR=/data` remains supported, but is no longer required when the volume is attached.
- Frontend variable: `VITE_API_URL=https://your-backend-domain`.

Do not set a relative `DATABASE_URL` in Railway. Either remove `DATABASE_URL` and let the
application use the mounted volume, or use the absolute SQLite URL
`sqlite:////data/crypto_paper_trader_api.db`.

The `/health` endpoint reports the resolved database path, whether the database file exists,
and whether Railway exposed an attached volume. The SQLite database is the only persistent
experiment data source. CSV/JSON and ZIP content is built in memory only when a download is
requested.

## Manual stop/consolidation security

The public dashboard does not expose the manual **Stop and consolidate** action.
The API endpoint remains available only to direct administrative clients:

```text
POST /api/v1/experiments/{experiment_id}/stop
```

Configure the secret on the Railway **API service**:

```env
ADMIN_API_KEY=replace-with-a-long-random-secret
```

Send the same value in the request header:

```bash
curl -X POST \
  "https://cryptopapertraderapi-production.up.railway.app/api/v1/experiments/EXPERIMENT_ID/stop" \
  -H "X-Admin-Key: YOUR_ADMIN_API_KEY"
```

Do not create `VITE_ADMIN_API_KEY` and do not place the key in frontend source code.
When `ADMIN_API_KEY` is absent, the endpoint fails closed with HTTP 503. A missing or
incorrect request key returns HTTP 401.
## v0.9.3 persistence and initial-dashboard correction

- The API automatically prefers `RAILWAY_VOLUME_MOUNT_PATH` for SQLite and reports a clear
  warning when Railway is running without a persistent volume.
- A new experiment immediately receives a technical/model baseline from the latest already
  closed candle. This baseline is action-blocked and cannot create a historical paper trade.
- Existing `RUNNING` experiments continue after deploys when the SQLite file is stored on the
  attached volume.

## Strategy comparison read endpoints

The comparison dashboard uses two read-only endpoints with separate responsibilities:

- `GET /api/v1/experiments/{experiment_id}/strategy-comparison` returns only the latest persisted decision for each active strategy.
- `GET /api/v1/experiments/{experiment_id}/strategy-comparison/history?limit=4` returns recent persisted decisions grouped by strategy.

Neither endpoint calculates indicators, trains the model, executes trades, or modifies experiment state. Those responsibilities remain in the worker.

## Railway deployment persistence

Production deployments must attach a Railway Volume to the API service at `/data`.
The application refuses to start on Railway when no persistent volume is detected,
preventing experiments from silently running on ephemeral storage. When the API
restarts, experiments persisted with status `RUNNING` or `STOP_REQUESTED` are picked
up automatically by the worker and continue until their original scheduled end time.
