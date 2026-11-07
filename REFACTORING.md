# Refactoring notes

## v0.16.17 — parent-row SQLite compatibility path

The final startup recovery no longer disables SQLite foreign keys. Missing strategy accounts are created with `INSERT ... SELECT` from the `experiments` table, so the parent identifier remains in SQLite's native storage representation and is validated by the database in the same statement. Existing accounts and dependent history records are not rebuilt by this final path.

## v0.16.13

Fibonacci logic is isolated under `risk_management/fibonacci/` so swing detection, level calculation and stop policies remain reusable and testable. The new `FibonacciTrendPullbackStrategy` lives in its own strategy module. Existing strategies remain separate; only the trend-following Larry Williams 9.1 variant imports the shared Fibonacci stop policy.

# API refactoring summary

## Implemented

- Split the former `multi_strategy.py` monolith into the `multi_strategy/` package.
- Created one module for each strategy family while preserving the old public import path.
- Kept shared decision DTOs and entry/risk helpers in `multi_strategy/common.py`.
- Removed all paid external language-model research calls.
- The adaptive selector now generates candidates from the local template library and selects them using local cost-adjusted walk-forward validation and risk gates.
- Removed paid-provider configuration variables, retry endpoint, diagnostic script and provider-specific tests.
- Removed stale export tests that referenced modules absent from the received project.
- Removed the packaged `.env` file and Python cache directories from the delivery.

## Main structure

```text
src/crypto_paper_trader_api/
├── api/routers/
├── services/
├── multi_strategy/
│   ├── common.py
│   ├── hybrid.py
│   ├── ema_crossover.py
│   ├── ema_pullback.py
│   ├── ema9_setup.py
│   ├── larry_breakout.py
│   ├── lbr_310.py
│   ├── stormer.py
│   └── adaptive_selector.py
├── adaptive_strategy_research.py
├── worker.py
└── ...
```

## Verification

- Python compilation: passed.
- Focused regression suite covering routes, strategies, indicators and local adaptive research: 23 passed.
- Full remaining suite: 85 passed, 7 failed.
- The seven failures already concern features that are inconsistent with the received source version: missing historical-refresh methods, missing timeframe validation, missing range-bound indicator output, and selector snapshot fallback. They are not caused by the removal of the paid research provider or by the strategy package split.
## v0.16.14 — legacy foreign-key recovery

- `init_database()` now validates the parent foreign key of `strategy_accounts`.
- Legacy schemas are rebuilt from SQLAlchemy metadata while preserving valid row IDs and data.
- Startup synchronization retries once after a SQLite foreign-key failure.
- Runtime database files remain outside the release package and must be preserved during upgrades.



## v0.16.15 — verified SQLite fallback

The startup synchronization now recreates pooled connections after schema repair. If a legacy SQLite file still rejects a valid strategy-account insert, the API performs a transaction with enforcement temporarily disabled, verifies every experiment parent, runs `PRAGMA foreign_key_check`, and commits only when no violation exists.

## v0.16.16 — verified fallback parent lookup fix

The SQLite compatibility synchronization no longer repeats a parent lookup for ORM objects already loaded from `experiments`. Some legacy files returned a false negative for that redundant lookup immediately after schema replacement. Safety remains enforced by comparing a database-wide `PRAGMA foreign_key_check` before and after the transaction. The commit is rejected only when the synchronization introduces a new violation or leaves an invalid `strategy_accounts` row.
