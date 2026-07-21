from __future__ import annotations

from fastapi import APIRouter, Depends

from ...runtime import worker
from ...schemas import AdminResetResponse
from ...security import require_admin_key
from ...services import admin_service

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Administration"],
    dependencies=[Depends(require_admin_key)],
)


@router.post("/reset", response_model=AdminResetResponse)
async def reset_application_data() -> AdminResetResponse:
    deleted_experiments = await admin_service.reset_paper_trading_data(worker)
    return AdminResetResponse(
        deleted_experiments=deleted_experiments,
        ai_history_preserved=True,
    )
