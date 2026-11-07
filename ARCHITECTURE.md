# Python API architecture

This repository contains only the Python/FastAPI paper-trading backend. The React/Vite application is maintained separately in [crypto_paper_trader_front](https://github.com/betovlima/crypto_paper_trader_front), and the independent quantitative backtest API is maintained in [crypto_paper_trader_ml_api](https://github.com/betovlima/crypto_paper_trader_ml_api).

## Application entry and runtime

- `src/crypto_paper_trader_api/app.py`: creates the FastAPI application, registers HTTP routers and manages startup/shutdown.
- `src/crypto_paper_trader_api/runtime.py`: shared settings, scanner and worker.
- `src/crypto_paper_trader_api/worker.py`: periodic simulated trading execution.
- `railway.toml`: installs Python dependencies and starts Uvicorn, without any frontend build.

## Backend responsibilities

- `api/routers/`: REST routes, grouped by responsibility.
- `services/`: application services and orchestration.
- `multi_strategy/`: independent strategy implementations, selector and shared decision utilities.
- `adaptive_intelligence/` and `adaptive_strategy_research.py`: pattern confirmation and local strategy research.
- `risk_management/fibonacci/`: reusable Fibonacci levels, swing detection and stop policy.
- `mexc_client.py`, `coinex_client.py`, `multi_broker.py`: market-data and broker abstractions.
- `paper_broker.py`: paper-only order execution; no authenticated real-order, transfer or withdrawal endpoints.
- `indicators.py`, `ml_model.py`, `ai_opportunity_scanner.py`, `ai_pattern_trader.py`: quantitative signals and opportunity analysis.
- `database.py`, `ai_database.py`, `models.py`: SQLite storage and persistence models.
- `config.py`, `security.py`, `schemas.py`: application settings, access control and API contracts.

## Repository layout

```text
src/
└── crypto_paper_trader_api/
    ├── api/routers/
    ├── services/
    ├── multi_strategy/
    ├── adaptive_intelligence/
    ├── risk_management/fibonacci/
    ├── app.py
    ├── worker.py
    └── ...
scripts/   # Python maintenance utilities
tests/     # Python regression tests
```

## Local run and verification

```bash
poetry install
poetry run pytest
poetry run uvicorn crypto_paper_trader_api.app:app --app-dir src --host 127.0.0.1 --port 8000 --reload
```

The deployed entry point is `crypto_paper_trader_api.app:app`. The repository intentionally excludes React, Vite, Node/NPM configuration, frontend source files and frontend public assets. A repository-boundary test prevents these files from being added again.
