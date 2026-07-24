# Crypto Paper Trader API — v0.16.10

## v0.16.10 — adaptive strategy recovery

- Restores adaptive-history synchronization even when no new candle is due.
- Adds persisted history diagnostics to the adaptive strategy payload.
- Restores selector state from the latest decision snapshot when account fields are empty.
- Adds range-bound indicators required by local pattern research.
- Keeps adaptive research fully local, without OpenAI calls.
- Accepts 30-minute decision candles and requires the trend timeframe to be equal or greater.

## v0.16.9 — server-calculated sticky header summary

- Adds `GET /api/v1/experiments/running/header-summary`.
- Calculates the running market label, decision cadence, trend-confirmation cadence, next-analysis countdown and last-update label in the API.
- Calculates total, active-position, armed-entry and waiting strategy counts in the API.
- Keeps presentation-only numeric aggregation out of the frontend header.
- Returns `visible=false` when no experiment is running.

## v0.16.8 — canonical LBR card name

- Renames the public strategy display name to `Trend Resumption with LBR 3/10`.
- Keeps `LBR_310_ANTI_CONTEXT` as the stable internal strategy code.
- Clarifies that the UTC daily baseline is a Crypto Paper Trader context filter and not part of the original Anti setup.
- Keeps the clean release safeguards introduced in v0.16.7.


## v0.16.7 — safe release package and SQLite diagnostics

- Keeps all LBR 3/10 Anti strategy behavior from v0.16.6.
- Removes runtime SQLite database files from the release package.
- Prevents stale `-wal` and `-shm` files from being paired with a different database after extraction.
- Adds `python scripts/check_sqlite_health.py` for read-only integrity checks.
- Adds a release-hygiene test that fails if a runtime database is committed.

Important: never replace the local or Railway `data` directory when updating application code.

## v0.16.6 — LBR 3/10 Anti with 24-hour crypto baseline

- Adds Linda Bradford Raschke's 3/10 Anti as an independent long-only paper strategy.
- Uses SMA(3) - SMA(10) and a 16-period SMA signal line.
- Detects impulse, weak pullback, momentum hook and a later closed-candle breakout.
- Reuses ignition, exhaustion, extension, spread, risk and expectancy-oriented controls.
- Adapts opening/closing context to crypto with fixed UTC sessions: the completed previous 24-hour day and its final hour form the initial baseline; the current day's first hour is added after it closes.
- Treats the UTC baseline only as a context filter, never as an entry signal.

PAPER_ONLY FastAPI service for crypto strategy research with public MEXC Spot market data. The project contains no authenticated order, transfer, deposit or withdrawal implementation.

## v0.16.5 — market-context and expectancy strategy optimization

This release contains only the strategy improvements discussed from the Larry Williams concepts. It does **not** move runtime parameters to the database and does not add any new login or application-entry key requirement.

- Adds ignition, exhaustion, compression, trend-age and EMA-extension context features.
- Uses only current and previously closed candles when calculating context baselines.
- Blocks exhausted entries across hybrid, crossover, pullback, Stormer, breakout, EMA 9.1 and AI strategies.
- Requires configurable ignition quality for volatility breakouts.
- Extends the AI Pattern Trader feature set with market-context variables.
- Stores context measurements and expected value in R in decision snapshots.
- Changes adaptive strategy validation from win-rate emphasis to expectancy in R, stability, profit factor, drawdown and sample size.
- Keeps the existing environment-based configuration behavior unchanged for now.


## Adaptive Strategy Research Selector

The `ADAPTIVE_STRATEGY_SELECTOR` no longer chooses one of the fixed dashboard strategies. It now follows this process:

```text
Market regime detection
    -> strategy hypothesis research
    -> executable rule generation
    -> cost-adjusted backtest
    -> chronological walk-forward validation
    -> risk and stability gates
    -> generated strategy activation or WAIT
```

The current generated strategy is persisted with:

- detected regime;
- strategy name, code, origin and executable JSON specification;
- research summary and source URLs;
- validation score;
- net validated return;
- maximum drawdown;
- profit factor;
- validated trade count;
- next reassessment timestamp.

An open paper position remains attached to the generated strategy that opened it. The selector researches a replacement only after the portfolio is flat.

### Optional web research


Configure only in the API service:

```env
ADAPTIVE_RESEARCH_WEB_ENABLED=true
```


Main research settings:

```env
SELECTOR_MODEL_VERSION=ADAPTIVE-RESEARCH-SELECTOR-v1
ADAPTIVE_RESEARCH_INTERVAL_HOURS=12
ADAPTIVE_RESEARCH_RETRY_MINUTES=30
ADAPTIVE_RESEARCH_MIN_CANDLES=800
ADAPTIVE_RESEARCH_VALIDATION_ROWS=240
ADAPTIVE_RESEARCH_WALK_FORWARD_FOLDS=3
ADAPTIVE_RESEARCH_MAX_CANDIDATES=8
ADAPTIVE_RESEARCH_MIN_TRADES=20
ADAPTIVE_RESEARCH_MIN_PROFIT_FACTOR=1.20
ADAPTIVE_RESEARCH_MAX_DRAWDOWN_PCT=0.10
ADAPTIVE_RESEARCH_MIN_STABILITY=0.67
ADAPTIVE_RESEARCH_MIN_VALIDATION_SCORE=60
```

Supported generated strategy families:

- `TREND_PULLBACK`
- `DONCHIAN_BREAKOUT`
- `VOLATILITY_BREAKOUT`
- `MEAN_REVERSION`
- `MOMENTUM_CONTINUATION`

## Independent AI Opportunity Scanner

The scanner is independent from experiments and continues running after `Stop experiment`.

```http
GET /api/v1/ai-opportunities/status
GET /api/v1/ai-opportunities/latest?limit=10
```

It supports real progress states, long MEXC candle histories through pagination, adaptive training windows and error details.

Optional scanner sizing settings:

```env
AI_SCANNER_UNIVERSE_SIZE=10
AI_SCANNER_RESULT_LIMIT=10
```

`AI_SCANNER_RESULT_LIMIT` controls how many ranked markets are persisted after each scan.
The `/latest?limit=` parameter can only return records that were persisted by the scanner.

## Protected experiment stopping

```http
POST /api/v1/experiments/stop-running
Content-Type: application/json
X-Admin-Key: <ADMIN_API_KEY>

{
  "close_open_positions": true
}
```

The endpoint targets the latest `RUNNING` experiment, preserves all records and does not stop the AI Opportunity Scanner.

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

Tests:

```powershell
poetry run pytest
```

## Railway

Attach a persistent volume to the API service, preferably at `/data`. Railway supplies `RAILWAY_VOLUME_MOUNT_PATH` automatically.

Minimum production settings:

```env
APP_ENV=production
CORS_ORIGINS=https://your-frontend-domain
ADMIN_API_KEY=replace-with-a-long-random-secret
```

For real web-assisted research, also set:

```env
ADAPTIVE_RESEARCH_WEB_ENABLED=true
```


## Safety boundary

All executions are simulated. Public MEXC data is used for analysis, and the adaptive researcher cannot submit exchange orders.



## v0.16.4 — closed-candle entry confirmation and candle attribution

- Requires the Larry Williams 9.1 setup candle to close bullish above EMA 9 after a strict down-to-up turn.
- Requires a later bullish candle to close above the setup high; intrabar wick-only breakouts remain on HOLD.
- Moves both Larry 9.1 entries to the closed-candle execution path.
- Adds body-quality, close-confirmation and maximum-extension filters to the other rule-based strategies.
- Applies equivalent safeguards to generated adaptive strategy families.
- Persists the candle timestamp that produced every simulated entry.


- Uses strict Structured Outputs for web-researched strategy specifications.
- Keeps local backtests, walk-forward validation, transaction costs, drawdown and trade-count rules authoritative.
- Exposes the AI provider, model, review status, review score and review explanation to the frontend.



## v0.16.4 — stricter entry confirmation and entry-candle timestamp

- Stores the candle opening timestamp that produced each simulated entry.
- Requires a strict bullish EMA 9 reversal candle that closes above EMA 9 before Setup 9.1 is armed.
- Expires stale EMA 9 setups and requires a later bullish candle to close above the trigger without excessive extension.
- Adds candle-body, close confirmation and maximum-extension filters to EMA crossover, EMA pullback, volatility breakout, Stormer and hybrid entries.
- Applies the same entry-quality principles to generated adaptive strategies and their backtests.
- Keeps AI Pattern Trader probability, expected-return and deterministic risk gates unchanged.

## v0.16.3 — persist all ten ranked scanner markets

- Changes the scanner default result limit from 5 to 10.
- Changes the `/api/v1/ai-opportunities/latest` default query limit from 5 to 10.
- Keeps the result limit configurable through `AI_SCANNER_RESULT_LIMIT`.
- Adds regression tests confirming that ten ranked markets are persisted and returned.

## v0.16.2 — AI scanner snapshot persistence fix

- Keeps per-market scanner diagnostics in the status response.
- Filters transient diagnostic fields before creating `AIOpportunitySnapshot`.
- Prevents `TypeError` failures caused by fields such as `downloaded_execution_candles`.
- Adds a regression test for the snapshot payload contract.

## v0.16.0 — Stormer Filha Mal Criada

Adds a long-only EMA ribbon pullback strategy using EMAs 20, 25, 30, 35, 40, 45 and 50, an armed breakout trigger, a stop below the next untouched EMA and a 3R target.

## Adaptive selector and pattern confirmation

Starting in API v0.16.11, the adaptive selector and the local candle-pattern model operate as one market-specific decision flow:

- research is executed with the experiment market, execution timeframe and trend timeframe;
- candidate strategies are backtested on the MEXC history synchronized for that market;
- a BUY signal from the selected strategy requires approval from the local pattern model;
- SELL signals and protective exits are never blocked by pattern confirmation;
- pattern confidence, expected return, regime and risk diagnostics are copied to the adaptive decision snapshot;
- adaptive research runs hourly by default and retries after ten minutes when needed.

No OpenAI or paid generative-model request is used by this flow.
