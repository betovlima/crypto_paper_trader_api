# Crypto Paper Trader v0.8.0

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

- Backend root directory: `/crypto_paper_trader_api`
- Backend volume mount: `/data`
- Frontend root directory: `/frontend`
- Backend variable: `DATA_DIR=/data`
- Frontend variable: `VITE_API_URL=https://your-backend-domain`

The SQLite database is the only persistent experiment data source. CSV/JSON and ZIP content is built in memory only when a download is requested.
