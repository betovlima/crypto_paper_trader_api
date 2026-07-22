from __future__ import annotations

from sqlalchemy import select

from ..ai_database import AISessionLocal
from ..ai_opportunity_models import AIOpportunityScannerState, AIOpportunitySnapshot
from ..ai_opportunity_scanner import AIOpportunityScanner

_ACTIVE_STATUSES = {
    "STARTING",
    "SELECTING_MARKETS",
    "FILTERING_MARKETS",
    "DOWNLOADING_CANDLES",
    "TRAINING_MODELS",
    "RANKING_OPPORTUNITIES",
}


def get_status(scanner: AIOpportunityScanner) -> dict[str, object]:
    progress = scanner.progress_snapshot()

    with AISessionLocal() as session:
        state = session.get(AIOpportunityScannerState, 1)
        if state is None:
            persisted = {
                "enabled": scanner.settings.ai_scanner_enabled,
                "running": scanner.is_running,
                "status": "STARTING" if scanner.settings.ai_scanner_enabled else "DISABLED",
                "universe_size": 0,
                "scanned_markets": 0,
                "opportunity_count": 0,
                "last_scan_started_at": None,
                "last_scan_completed_at": None,
                "next_scan_at": None,
                "last_error": None,
            }
        else:
            persisted = state.to_public_dict(scanner.is_running)

    status = str(progress.get("status") or persisted["status"])
    is_active = status in _ACTIVE_STATUSES
    total_markets = int(progress.get("total_markets") or 0)
    analyzed_markets = int(progress.get("analyzed_markets") or 0)
    classified = int(progress.get("classified_opportunities") or 0)
    eligible_markets = int(progress.get("eligible_markets") or classified)
    learning_markets = int(progress.get("learning_markets") or 0)

    return {
        **persisted,
        "enabled": scanner.settings.ai_scanner_enabled,
        "running": scanner.is_running,
        "status": status,
        "universe_size": (
            total_markets if is_active and total_markets else persisted["universe_size"]
        ),
        "scanned_markets": analyzed_markets if is_active else persisted["scanned_markets"],
        "opportunity_count": classified if is_active else persisted["opportunity_count"],
        "progress_percent": int(progress.get("progress_percent") or 0),
        "current_step": int(progress.get("current_step") or 0),
        "total_steps": int(progress.get("total_steps") or 5),
        "current_market": progress.get("current_market"),
        "current_market_index": int(progress.get("current_market_index") or 0),
        "total_markets": total_markets,
        "analyzed_markets": analyzed_markets,
        "failed_markets": int(progress.get("failed_markets") or 0),
        "classified_opportunities": classified,
        "eligible_markets": eligible_markets,
        "learning_markets": learning_markets,
        "training_window": progress.get("training_window"),
        "scan_started_at": progress.get("scan_started_at")
        or persisted["last_scan_started_at"],
        "last_activity_at": progress.get("last_activity_at"),
        "last_error": progress.get("last_error") or persisted["last_error"],
        "market_diagnostics": list(progress.get("market_diagnostics") or []),
    }


def list_latest(limit: int) -> list[dict[str, object]]:
    with AISessionLocal() as session:
        latest_scan_id = session.scalar(
            select(AIOpportunitySnapshot.scan_id)
            .order_by(AIOpportunitySnapshot.scanned_at.desc())
            .limit(1)
        )
        if latest_scan_id is None:
            return []
        rows = list(
            session.scalars(
                select(AIOpportunitySnapshot)
                .where(AIOpportunitySnapshot.scan_id == latest_scan_id)
                .order_by(AIOpportunitySnapshot.rank.asc())
                .limit(limit)
            )
        )
        return [row.to_public_dict() for row in rows]
