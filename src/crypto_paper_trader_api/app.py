from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routers import (
    ai_pattern,
    compatibility,
    experiments,
    strategy_comparison,
    strategy_data,
    system,
)
from .database import init_database
from .runtime import settings, worker
from .services.startup_service import synchronize_strategy_accounts

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_persistent_storage()
    init_database()
    synchronize_strategy_accounts()
    if settings.storage_warning:
        logging.getLogger(__name__).warning(settings.storage_warning)
    logging.getLogger(__name__).info(
        "SQLite database path: %s; Railway persistent volume attached: %s",
        settings.resolved_database_url,
        settings.persistent_storage_configured,
    )
    worker.start()
    worker.wake()
    yield
    await worker.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.11.1",
    description=(
        "PAPER_ONLY crypto strategy research using public CoinEx Spot data. "
        "All persistent state is stored in SQLite. HTTP routers and application services "
        "are separated by responsibility; no CSV, JSON, ZIP or report files are generated. "
        "AI Pattern Trader learns recurring OHLCV patterns and operates only an independent "
        "simulated portfolio. The application contains no authenticated order or withdrawal endpoints."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(experiments.router)
app.include_router(strategy_comparison.router)
app.include_router(strategy_data.router)
app.include_router(ai_pattern.router)
app.include_router(compatibility.router)
