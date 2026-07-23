from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ...runtime import worker
from ...schemas import AdaptiveHistoryRetryResponse, AdaptiveResearchRetryResponse
from ...security import require_admin_key

router = APIRouter(
    prefix="/api/v1/experiments/{experiment_id}/adaptive-selector",
    tags=["Adaptive Time-Series Pattern Strategy"],
)


@router.post(
    "/retry-history",
    response_model=AdaptiveHistoryRetryResponse,
    dependencies=[Depends(require_admin_key)],
)
async def retry_adaptive_selector_history(
    experiment_id: str,
) -> AdaptiveHistoryRetryResponse:
    try:
        result = await worker.retry_adaptive_selector_history(experiment_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AdaptiveHistoryRetryResponse(**result)


@router.post(
    "/retry-research",
    response_model=AdaptiveResearchRetryResponse,
    dependencies=[Depends(require_admin_key)],
)
async def retry_adaptive_selector_research(
    experiment_id: str,
) -> AdaptiveResearchRetryResponse:
    """Force the next adaptive research cycle using the local research engine."""
    try:
        result = await worker.retry_adaptive_selector_research(experiment_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AdaptiveResearchRetryResponse(**result)
