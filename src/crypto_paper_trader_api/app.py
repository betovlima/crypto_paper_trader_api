from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routers import (
    adaptive_selector,
    ai_opportunities,
    ai_pattern,
    compatibility,
    experiments,
    strategy_comparison,
    strategy_data,
    system,
)
from .database import init_database
from .ai_database import init_ai_database
from .runtime import ai_scanner, settings, worker
from .services.startup_service import synchronize_strategy_accounts

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_persistent_storage()
    init_database()
    init_ai_database()
    synchronize_strategy_accounts()
    if settings.storage_warning:
        logging.getLogger(__name__).warning(settings.storage_warning)
    logging.getLogger(__name__).info(
        "SQLite databases: main=%s ai=%s; Railway persistent volume attached: %s",
        settings.resolved_database_url,
        settings.resolved_ai_database_url,
        settings.persistent_storage_configured,
    )
    worker.start()
    worker.wake()
    ai_scanner.start()
    ai_scanner.wake()
    yield
    await worker.stop()
    await ai_scanner.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.16.10",
    description=(
        "PAPER_ONLY crypto strategy research using public MEXC Spot data. "
        "All persistent state is stored in SQLite. HTTP routers and application services "
        "are separated by responsibility; no CSV, JSON, ZIP or report files are generated. "
        "An independent AI Opportunity Scanner ranks liquid markets and remains active when "
        "paper experiments are stopped. The application contains no authenticated order or withdrawal endpoints."
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
app.include_router(adaptive_selector.router)
app.include_router(experiments.router)
app.include_router(ai_opportunities.router)
app.include_router(strategy_comparison.router)
app.include_router(strategy_data.router)
app.include_router(ai_pattern.router)
app.include_router(compatibility.router)
