from __future__ import annotations

from fastapi import APIRouter, Query

from ...runtime import ai_scanner
from ...schemas import AIOpportunityItem, AIOpportunityScannerStatus
from ...services import ai_opportunity_service

router = APIRouter(prefix="/api/v1/ai-opportunities", tags=["AI Opportunity Scanner"])


@router.get("/status", response_model=AIOpportunityScannerStatus)
def scanner_status() -> AIOpportunityScannerStatus:
    return AIOpportunityScannerStatus.model_validate(
        ai_opportunity_service.get_status(ai_scanner)
    )


@router.get("/latest", response_model=list[AIOpportunityItem])
def latest_opportunities(
    limit: int = Query(default=10, ge=1, le=20),
) -> list[AIOpportunityItem]:
    return [
        AIOpportunityItem.model_validate(item)
        for item in ai_opportunity_service.list_latest(limit)
    ]
