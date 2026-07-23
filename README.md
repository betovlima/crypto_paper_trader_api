# Crypto Paper Trader API — v0.16.17


## v0.16.17 — sideways-market adaptive evaluation

- Adds a 0–100 range-bound score based on ADX, moving-average distance and slope, mean crossings, directional efficiency and Bollinger bandwidth.
- Adds Bollinger midpoint/bands/z-score, stochastic %K/%D, 24-candle support/resistance and normalized range position for the selected asset.
- Prioritizes a confirmed sideways regime before a weak trend classification while preserving strong-trend and high-volatility regimes.
- Adds four locally executable strategy families: Bollinger mean reversion, support-candle reversal, false-support-breakout reversal and stochastic range rotation.
- Requires every range strategy to pass a minimum range score and maximum ADX filter before entering.
- Exits range strategies at the Bollinger mean, range midpoint, stochastic target, bearish rejection near resistance or when the range regime is lost.
- Exposes the range state, score, support, resistance, range position, Bollinger z-score/bandwidth and stochastic values in adaptive diagnostics.

## v0.16.16 — selected-asset time-series pattern strategy

- Converts the adaptive selector into a selected-asset pattern-research engine while retaining the stable `ADAPTIVE_STRATEGY_SELECTOR` database code.
- Analyzes only the market chosen for the experiment; it never scans, ranks or changes markets.
- Enforces a one-hour minimum intraday decision candle and requires the trend timeframe to be equal to or greater than the decision timeframe.
- Uses a 10,000-candle history target and a configurable ceiling of 30,000 candles, with 800 clean candles as the first-analysis minimum.
- Compares the latest 24-candle movement with historical windows and estimates the next configured candle from the nearest patterns.
- Adds moving-average, momentum, volatility, volume and deterministic candlestick-pattern context including doji, hammer, shooting star, engulfing, inside/outside bar, morning star and evening star.
- Adds AI-generated and local hypotheses for EMA/candle pullbacks, support reversals, momentum, breakouts and mean reversion.
- Keeps local cost-aware backtests, chronological walk-forward validation and risk gates authoritative.
- Removes OpenAI web search from this strategy: OpenAI receives only a compact statistical summary of the selected asset.
- Keeps the independent AI Opportunity Scanner unchanged and isolated from experiment strategy research.

## v0.16.15 — current OpenAI retry and stale-error cleanup

- Adds `POST /api/v1/experiments/{experiment_id}/adaptive-selector/retry-research`, protected by `X-Admin-Key`.
- Reloads the effective OpenAI secret from the project `.env` or Railway variables without deleting or replacing SQLite data.
- Forces a complete adaptive research cycle without waiting for the next scheduled review or closed candle.
- Keeps the history-only retry endpoint for the distinct `WAITING_FOR_HISTORY` state.
- Replaces oversized authentication details with a concise, redacted diagnostic.
- Changes the selector model version so an existing deployment performs a fresh review after upgrade.

## v0.16.14 — independent adaptive-history recovery

- Runs the adaptive selector history backfill in its own background task instead of waiting for a new closed candle.
- Retries overdue history automatically and reruns selector research immediately after the clean-history requirement is reached.
- Adds bounded MEXC candle requests with an `endTime` fallback and expanding sparse-market lookback windows.
- Persists backfill pages, candles added, empty windows, last attempt, next retry and sanitized errors in SQLite.
- Adds `POST /api/v1/experiments/{experiment_id}/adaptive-selector/retry-history`, protected by `X-Admin-Key`.
- Keeps existing `.env` and `data` files compatible through additive database migration.


## v0.16.11 — history-safe adaptive validation

- Loads a raw execution history with a 300-candle indicator warm-up margin above the minimum clean-candle requirement.
- Continues MEXC pagination when the currently forming candle is removed from an otherwise full batch.
- Checks usable history before strategy generation or OpenAI research and retries after five minutes when the buffer is incomplete.
- Returns unavailable validation metrics as unavailable instead of representing missing data as a 100% drawdown.
- Stops inventing a bullish fallback candidate during confirmed bearish regimes in the long-only Spot simulator.
- Records an explicit wait-for-recovery state instead of presenting a rejected strategy comparison.
- Preserves a concise, redacted OpenAI error for dashboard diagnosis while local validation remains authoritative.

## v0.16.10 — adaptive selector champion/challenger research

- Expands TRANSITION research from five hypotheses to fifteen controlled candidates.
- Separates mandatory validation failures from soft quality warnings.
- Requires positive expectancy, positive net return, bounded drawdown, a statistically usable trade sample and at least two positive folds out of three.
- Keeps profit factor, ideal sample size, stability and target validation score as ranking penalties instead of automatic rejection gates.
- Persists the best rejected candidate, exact failure reasons and aggregate rejection counts in the existing selector diagnostics JSON.
- Preserves a validated champion when challengers fail and suspends it rather than deleting it when the current regime is incompatible.
- Replaces a champion only when a challenger exceeds it by the configured improvement margin.
- Reassesses TRANSITION more frequently while remaining paper-only and cost-aware.

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


## Adaptive Time-Series Pattern Strategy

`ADAPTIVE_STRATEGY_SELECTOR` is retained as the internal persisted code for SQLite compatibility. Its public behavior is now a pattern-research strategy for the **single asset selected by the user**.

```text
Selected experiment asset
    -> long selected-asset history
    -> current closed-candle pattern and regime
    -> nearest historical movement windows
    -> local and optional AI strategy hypotheses
    -> executable rules
    -> cost-adjusted chronological backtest
    -> walk-forward and risk gates
    -> BUY, HOLD or SELL for the next configured candle
```

The strategy never scans, ranks or changes markets. Market discovery remains the responsibility of the independent AI Opportunity Scanner. Every fixed strategy and the adaptive strategy operate on the same experiment asset and the same configured decision/trend timeframes.

For intraday experiments, the minimum decision timeframe is `1hour`. The trend timeframe must be equal to or greater than the decision timeframe. The standard profiles use `1hour`/`4hour` or `4hour`/`1day`.

The pattern engine combines:

- EMA alignment, slope, distance and pullback context;
- RSI, ADX, rate of change and momentum continuation;
- ATR, volatility compression/expansion and breakout context;
- relative volume and volume-confirmed movement;
- support/resistance, Donchian and mean-reversion contexts;
- doji, hammer, shooting star, bullish/bearish engulfing, inside/outside bars, morning star and evening star.

Candlestick patterns are context features, not standalone trade signals. A generated rule is activated only after local costs, sample size, expectancy, net return, drawdown, walk-forward stability and risk gates approve it.

The history controls are intentionally separate:

```env
SELECTOR_MODEL_VERSION=ADAPTIVE-PATTERN-RESEARCH-v8-RANGE-BOUND
ADAPTIVE_RESEARCH_MIN_CANDLES=800
ADAPTIVE_RESEARCH_TARGET_CANDLES=10000
ADAPTIVE_RESEARCH_MAX_HISTORY_CANDLES=30000
ADAPTIVE_PATTERN_WINDOW_CANDLES=24
ADAPTIVE_PATTERN_HORIZON_CANDLES=1
ADAPTIVE_PATTERN_NEIGHBORS=64
ADAPTIVE_RESEARCH_VALIDATION_ROWS=240
ADAPTIVE_RESEARCH_WALK_FORWARD_FOLDS=3
ADAPTIVE_RESEARCH_MAX_CANDIDATES=15
ADAPTIVE_RESEARCH_MIN_TRADES=20
ADAPTIVE_RESEARCH_MIN_PROFIT_FACTOR=1.20
ADAPTIVE_RESEARCH_MAX_DRAWDOWN_PCT=0.10
ADAPTIVE_RESEARCH_MIN_STABILITY=0.67
ADAPTIVE_RESEARCH_MIN_VALIDATION_SCORE=60
```

The optional OpenAI stage receives a compact statistical summary only. It does not receive or select other markets and it does not replace local validation.

```env
ADAPTIVE_RESEARCH_WEB_ENABLED=true
OPENAI_API_KEY=replace-with-your-server-side-key
ADAPTIVE_RESEARCH_OPENAI_MODEL=gpt-5
ADAPTIVE_RESEARCH_OPENAI_TIMEOUT_SECONDS=90
ADAPTIVE_RESEARCH_OPENAI_ATTEMPTS=2
```

Without `OPENAI_API_KEY`, local selected-asset pattern matching and the internal hypothesis library continue operating.

Supported generated strategy families:

- `TREND_PULLBACK`
- `DONCHIAN_BREAKOUT`
- `VOLATILITY_BREAKOUT`
- `MEAN_REVERSION`
- `MOMENTUM_CONTINUATION`
- `EMA_CANDLE_PULLBACK`
- `CANDLE_REVERSAL`

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

Copy `.env.example` to `.env` in the API project root. The backend now resolves this
file from the location of `config.py`, so the OpenAI key is loaded correctly even when
Uvicorn is started from another working directory. During local development the project
`.env` takes precedence over an old `OPENAI_API_KEY` stored in the operating-system
environment. On Railway, service variables keep precedence.

```powershell
Copy-Item .env.example .env
poetry config virtualenvs.in-project true
poetry install
poetry run uvicorn crypto_paper_trader_api.app:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

Safe configuration diagnostic:

```powershell
poetry run python scripts/check_openai_configuration.py
poetry run python scripts/check_openai_configuration.py --check-api
```

The diagnostic never prints the secret. It reports whether the effective key came from
the project `.env`, a process variable or a Railway variable. The optional API check also
shows the redacted OpenAI error code, including `invalid_api_key` and `ip_not_authorized`.

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
OPENAI_API_KEY=replace-with-your-server-side-key
ADAPTIVE_RESEARCH_OPENAI_MODEL=gpt-5
```

Never put `ADMIN_API_KEY` or `OPENAI_API_KEY` in the frontend or in any `VITE_*` variable.

## Safety boundary

All executions are simulated. Public MEXC data is used for analysis, and the adaptive researcher cannot submit exchange orders.




## v0.16.12 — deterministic local `.env` loading and OpenAI authentication diagnostics

- Resolves the local `.env` from the API project root instead of the current shell directory.
- Gives the project `.env` precedence over stale operating-system variables during local development.
- Preserves Railway variable precedence in production.
- Normalizes accidental quotes, whitespace and a copied `Bearer ` prefix in secret values.
- Replaces the generic HTTP 401 text with a redacted OpenAI error code and key source.
- Distinguishes an invalid key from an OpenAI IP allowlist rejection.
- Adds a safe local diagnostic script that can validate authentication without generating a response.

## v0.16.4 — closed-candle entry confirmation and candle attribution

- Requires the Larry Williams 9.1 setup candle to close bullish above EMA 9 after a strict down-to-up turn.
- Requires a later bullish candle to close above the setup high; intrabar wick-only breakouts remain on HOLD.
- Moves both Larry 9.1 entries to the closed-candle execution path.
- Adds body-quality, close-confirmation and maximum-extension filters to the other rule-based strategies.
- Applies equivalent safeguards to generated adaptive strategy families.
- Persists the candle timestamp that produced every simulated entry.

## 0.15.1 - Hybrid OpenAI research and local quantitative validation

- Uses strict Structured Outputs for web-researched strategy specifications.
- Adds an optional OpenAI suitability review only after local candidates pass all deterministic gates.
- Keeps local backtests, walk-forward validation, transaction costs, drawdown and trade-count rules authoritative.
- Exposes the AI provider, model, review status, review score and review explanation to the frontend.
- Sends `store=false` in OpenAI Responses API requests.



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