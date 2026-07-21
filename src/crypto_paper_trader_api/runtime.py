from __future__ import annotations

from .config import get_settings
from .worker import TraderWorker

settings = get_settings()
worker = TraderWorker(settings)
