from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings


def require_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """Require the administrative key configured through ADMIN_API_KEY.

    The comparison is performed in constant time. The key must be supplied only
    by direct API clients and must never be embedded in the public Vite build.
    """
    configured_key = get_settings().admin_api_key

    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrative operations are not configured.",
        )

    if not x_admin_key or not secrets.compare_digest(x_admin_key, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing administrative key.",
            headers={"WWW-Authenticate": "X-Admin-Key"},
        )
