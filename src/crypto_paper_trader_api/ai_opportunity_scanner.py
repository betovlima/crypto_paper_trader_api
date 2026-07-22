from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable, TypeVar
from uuid import uuid4

from sqlalchemy import delete, select

from .ai_database import AISessionLocal
from .ai_opportunity_models import AIOpportunityScannerState, AIOpportunitySnapshot
from .ai_pattern_trader import AI_PATTERN_MODEL_VERSION, AIPatternTrader
from .config import Settings
from .execution_costs import ExecutionCosts
from .indicators import add_indicators, latest_complete_row
from .mexc_client import MEXCPublicClient
from .models import StrategyAccount
from .strategy_codes import AI_PATTERN_TRADER
from .trading_profiles import get_trading_profile

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_STABLE_BASES = {
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "DAI",
    "USDE",
    "USD1",
    "EUR",
}
_LEVERAGED_SUFFIXES = ("3L", "3S", "5L", "5S", "BULL", "BEAR", "UP", "DOWN")


@dataclass(frozen=True, slots=True)
class ScannerProgress:
    """Transient progress exposed while the scanner is working.

    The record is kept in memory because it changes frequently. Completed scan
    metadata remains stored in SQLite through ``AIOpportunityScannerState``.
    """

    status: str = "STARTING"
    progress_percent: int = 0
    current_step: int = 0
    total_steps: int = 5
    current_market: str | None = None
    current_market_index: int = 0
    total_markets: int = 0
    analyzed_markets: int = 0
    failed_markets: int = 0
    classified_opportunities: int = 0
    eligible_markets: int = 0
    learning_markets: int = 0
    training_window: int | None = None
    scan_started_at: datetime | None = None
    last_activity_at: datetime | None = None
    last_error: str | None = None
    market_diagnostics: tuple[dict[str, object], ...] = field(default_factory=tuple)


class AIOpportunityScanner:
    """Continuously rank liquid MEXC Spot markets independently of experiments."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        scanner_settings = settings.model_copy(
            update={
                "ai_pattern_min_training_rows": settings.ai_scanner_min_training_rows,
                "ai_pattern_training_max_rows": settings.ai_scanner_training_window,
                "ai_pattern_confident_rows": settings.ai_scanner_training_window,
                "ai_pattern_validation_rows": settings.ai_scanner_validation_rows,
                "ai_pattern_candidate_windows": settings.ai_scanner_candidate_windows,
                "ai_pattern_recent_regime_rows": settings.ai_scanner_recent_regime_rows,
                "ai_pattern_tree_count": min(settings.ai_pattern_tree_count, 64),
                "ai_pattern_mode": "OBSERVATION",
            }
        )
        self.client = MEXCPublicClient(settings)
        self.model = AIPatternTrader(scanner_settings)
        self._task: asyncio.Task[None] | None = None
        self._wake_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._scan_lock = asyncio.Lock()
        self._progress_lock = Lock()
        self._progress = ScannerProgress(
            status="STARTING" if settings.ai_scanner_enabled else "DISABLED",
            last_activity_at=datetime.now(timezone.utc),
        )

    @property
    def is_running(self) -> bool:
        return bool(self._task and not self._task.done())

    def progress_snapshot(self) -> dict[str, object]:
        """Return a consistent copy for the status endpoint."""
        with self._progress_lock:
            return asdict(self._progress)

    def _set_progress(self, **changes: object) -> None:
        now = datetime.now(timezone.utc)
        with self._progress_lock:
            previous_status = self._progress.status
            self._progress = replace(
                self._progress,
                **changes,
                last_activity_at=now,
            )
            current = self._progress

        if current.status != previous_status:
            logger.info(
                "AI scanner status=%s progress=%s%% market=%s (%s/%s)",
                current.status,
                current.progress_percent,
                current.current_market or "-",
                current.current_market_index,
                current.total_markets,
            )

    def _touch_progress(self) -> None:
        """Refresh activity while CPU-bound model training is still running."""
        self._set_progress()

    def start(self) -> None:
        if not self.settings.ai_scanner_enabled or self.is_running:
            return
        self._shutdown_event.clear()
        self._set_progress(
            status="STARTING",
            progress_percent=0,
            current_step=0,
            last_error=None,
        )
        self._task = asyncio.create_task(
            self._run_loop(),
            name="ai-opportunity-scanner",
        )

    async def stop(self) -> None:
        self._shutdown_event.set()
        self._wake_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=20)
            except asyncio.TimeoutError:
                self._task.cancel()
            except asyncio.CancelledError:
                pass
        self._set_progress(status="STOPPED", current_market=None)
        await self.client.close()

    def wake(self) -> None:
        self._wake_event.set()

    async def _run_loop(self) -> None:
        logger.info(
            "AI Opportunity Scanner started; interval=%ss universe=%s",
            self.settings.ai_scanner_interval_seconds,
            self.settings.ai_scanner_universe_size,
        )
        while not self._shutdown_event.is_set():
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("AI opportunity scan failed")
                self._save_error(exc)

            try:
                self._wake_event.clear()
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self.settings.ai_scanner_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
        logger.info("AI Opportunity Scanner stopped")

    async def scan_once(self) -> None:
        async with self._scan_lock:
            started_at = datetime.now(timezone.utc)
            self._set_progress(
                status="SELECTING_MARKETS",
                progress_percent=3,
                current_step=1,
                current_market=None,
                current_market_index=0,
                total_markets=0,
                analyzed_markets=0,
                failed_markets=0,
                classified_opportunities=0,
                eligible_markets=0,
                learning_markets=0,
                training_window=None,
                scan_started_at=started_at,
                last_error=None,
                market_diagnostics=(),
            )
            self._save_state(
                status="SCANNING",
                universe_size=0,
                scanned_markets=0,
                opportunity_count=0,
                started_at=started_at,
                completed_at=None,
                error=None,
            )

            tickers = await self.client.get_24h_tickers()
            self._set_progress(
                status="FILTERING_MARKETS",
                progress_percent=10,
                current_step=2,
            )
            universe = self._select_universe(tickers)
            if not universe:
                raise RuntimeError("No eligible MEXC markets were found for the AI scanner.")

            total_markets = len(universe)
            self._set_progress(total_markets=total_markets, progress_percent=15)
            ranked_candidates: list[dict[str, object]] = []
            learning_candidates: list[dict[str, object]] = []
            failure_messages: list[str] = []
            market_diagnostics: list[dict[str, object]] = []
            failed_markets = 0

            for index, item in enumerate(universe, start=1):
                market = str(item["symbol"])
                quote_volume = float(item["quote_volume"])
                try:
                    candidate = await self._evaluate_market(
                        market=market,
                        quote_volume=quote_volume,
                        scanned_at=started_at,
                        market_index=index,
                        total_markets=total_markets,
                        successful_markets=len(ranked_candidates),
                        failed_markets=failed_markets,
                    )
                    market_diagnostics.append(self._candidate_diagnostic(candidate))
                    if self._is_ranked_opportunity(candidate):
                        ranked_candidates.append(candidate)
                    else:
                        learning_candidates.append(candidate)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    failed_markets += 1
                    failure_message = (
                        f"{market}: {type(exc).__name__}: {exc}"
                    )
                    failure_messages.append(failure_message)
                    self._set_progress(last_error=failure_message)
                    logger.warning("AI scanner skipped %s: %s", market, exc)
                finally:
                    self._set_progress(
                        analyzed_markets=index,
                        failed_markets=failed_markets,
                        classified_opportunities=min(
                            len(ranked_candidates), self.settings.ai_scanner_result_limit
                        ),
                        eligible_markets=len(ranked_candidates),
                        learning_markets=len(learning_candidates),
                        market_diagnostics=tuple(market_diagnostics),
                    )

            evaluated_markets = len(ranked_candidates) + len(learning_candidates)
            if evaluated_markets == 0:
                details = "; ".join(failure_messages[:3])
                detail_suffix = f" First failures: {details}" if details else ""
                raise RuntimeError(
                    "The AI scanner could not evaluate any of the "
                    f"{total_markets} selected markets."
                    f"{detail_suffix}"
                )

            self._set_progress(
                status="RANKING_OPPORTUNITIES",
                progress_percent=94,
                current_step=5,
                current_market=None,
                current_market_index=total_markets,
                analyzed_markets=total_markets,
                failed_markets=failed_markets,
                eligible_markets=len(ranked_candidates),
                learning_markets=len(learning_candidates),
            )
            ranked_candidates.sort(key=lambda row: float(row["score"]), reverse=True)
            selected = ranked_candidates[: self.settings.ai_scanner_result_limit]
            scan_id = str(uuid4())

            await asyncio.to_thread(self._persist_scan, scan_id, selected)

            completed_at = datetime.now(timezone.utc)
            self._save_state(
                status="READY",
                universe_size=len(universe),
                scanned_markets=evaluated_markets,
                opportunity_count=len(selected),
                started_at=started_at,
                completed_at=completed_at,
                error=None,
            )
            self._set_progress(
                status="READY",
                progress_percent=100,
                current_step=5,
                current_market=None,
                current_market_index=total_markets,
                total_markets=total_markets,
                analyzed_markets=total_markets,
                failed_markets=failed_markets,
                classified_opportunities=len(selected),
                eligible_markets=len(ranked_candidates),
                learning_markets=len(learning_candidates),
                training_window=None,
                scan_started_at=started_at,
                last_error=None,
                market_diagnostics=tuple(market_diagnostics),
            )

    async def _evaluate_market(
        self,
        market: str,
        quote_volume: float,
        scanned_at: datetime,
        market_index: int,
        total_markets: int,
        successful_markets: int,
        failed_markets: int,
    ) -> dict[str, object]:
        start_progress = self._market_progress(market_index - 1, total_markets, 0.0)
        self._set_progress(
            status="DOWNLOADING_CANDLES",
            progress_percent=start_progress,
            current_step=3,
            current_market=market,
            current_market_index=market_index,
            total_markets=total_markets,
            analyzed_markets=market_index - 1,
            failed_markets=failed_markets,
            classified_opportunities=min(
                successful_markets, self.settings.ai_scanner_result_limit
            ),
            training_window=None,
        )

        execution_frame, trend_frame, depth = await asyncio.gather(
            self.client.get_candles(
                market,
                self.settings.ai_scanner_execution_timeframe,
                limit=self.settings.ai_scanner_candle_limit,
                closed_only=True,
            ),
            self.client.get_candles(
                market,
                self.settings.ai_scanner_trend_timeframe,
                limit=self.settings.ai_scanner_candle_limit,
                closed_only=True,
            ),
            self.client.get_depth_snapshot(market),
        )

        training_progress = self._market_progress(market_index - 1, total_markets, 0.35)
        self._set_progress(
            status="TRAINING_MODELS",
            progress_percent=training_progress,
            current_step=4,
            current_market=market,
            current_market_index=market_index,
            training_window=self.settings.ai_scanner_training_window,
        )

        candidate = await self._run_in_thread_with_heartbeat(
            lambda: self._build_candidate(
                market=market,
                quote_volume=quote_volume,
                scanned_at=scanned_at,
                execution_frame=execution_frame,
                trend_frame=trend_frame,
                depth=depth,
            )
        )
        completed_progress = self._market_progress(market_index, total_markets, 0.0)
        self._set_progress(
            progress_percent=completed_progress,
            training_window=int(candidate["training_samples"]),
        )
        return candidate

    async def _run_in_thread_with_heartbeat(
        self,
        function: Callable[[], _T],
        heartbeat_seconds: float = 5.0,
    ) -> _T:
        task = asyncio.create_task(asyncio.to_thread(function))
        while True:
            done, _ = await asyncio.wait({task}, timeout=heartbeat_seconds)
            if task in done:
                return task.result()
            self._touch_progress()

    @staticmethod
    def _market_progress(completed_markets: int, total_markets: int, fraction: float) -> int:
        if total_markets <= 0:
            return 15
        progress = 15 + 75 * ((completed_markets + fraction) / total_markets)
        return max(15, min(90, int(round(progress))))

    def _build_candidate(
        self,
        *,
        market: str,
        quote_volume: float,
        scanned_at: datetime,
        execution_frame,
        trend_frame,
        depth,
    ) -> dict[str, object]:
        execution_frame = add_indicators(
            execution_frame,
            context_lookback=self.settings.market_context_lookback,
            compression_window=self.settings.market_context_compression_window,
        )
        trend_frame = add_indicators(
            trend_frame,
            context_lookback=self.settings.market_context_lookback,
            compression_window=self.settings.market_context_compression_window,
        )
        trend_row = latest_complete_row(trend_frame)
        profile = get_trading_profile("BALANCED_INTRADAY")
        costs = ExecutionCosts(
            maker_fee_rate=self.settings.effective_default_maker_fee_rate,
            taker_fee_rate=self.settings.effective_default_taker_fee_rate,
            spread_rate=depth.spread_rate,
            slippage_rate=self.settings.slippage_rate,
            fee_source="AI_SCANNER_MEXC_PUBLIC",
        )
        account = StrategyAccount(
            experiment_id="AI_OPPORTUNITY_SCANNER",
            strategy_code=AI_PATTERN_TRADER,
            display_name="AI Opportunity Scanner",
            initial_capital=1000.0,
            cash_balance=1000.0,
            max_equity=1000.0,
        )
        decision = self.model.decide(
            account=account,
            frame=execution_frame,
            trend_row=trend_row,
            costs=costs,
            now=scanned_at,
            profile=profile,
        )
        current_price = float(execution_frame.iloc[-1]["close"])
        confidence = float(decision.ai_confidence or 0.0)
        upward_probability = float(decision.ai_upward_probability or 0.0)
        expected_net_return = float(decision.ai_expected_net_return or 0.0)
        expected_component = max(0.0, min(expected_net_return / 0.03, 1.0))
        score = round(
            100
            * (
                0.45 * confidence
                + 0.35 * upward_probability
                + 0.20 * expected_component
            ),
            2,
        )
        action = self._opportunity_action(decision, score)
        atr = float(execution_frame.iloc[-1].get("atr_14") or 0.0)
        zone_width = max(atr * 0.35, current_price * 0.001)
        entry_zone_low = max(current_price - zone_width, 0.0)
        entry_zone_high = current_price + zone_width
        trigger_price = (
            float(decision.execution_reference_price)
            if decision.execution_reference_price is not None
            else current_price + zone_width
        )
        reason = (
            f"AI score={score:.2f}; regime={decision.ai_regime or 'UNKNOWN'}; "
            f"confidence={confidence:.4f}; probability_up={upward_probability:.4f}; "
            f"expected_net_return={expected_net_return:.6f}; action={action}."
        )
        return {
            "market": market,
            "score": score,
            "action": action,
            "market_price": current_price,
            "entry_zone_low": entry_zone_low,
            "entry_zone_high": entry_zone_high,
            "trigger_price": trigger_price,
            "stop_loss_price": decision.stop_loss_override,
            "target_price": decision.take_profit_override,
            "regime": decision.ai_regime,
            "confidence": decision.ai_confidence,
            "upward_probability": decision.ai_upward_probability,
            "expected_net_return": decision.ai_expected_net_return,
            "quote_volume_24h": quote_volume,
            "spread_rate": depth.spread_rate,
            "downloaded_execution_candles": int(len(execution_frame)),
            "downloaded_trend_candles": int(len(trend_frame)),
            "training_samples": int(decision.ai_training_samples or 0),
            "required_training_samples": int(self.settings.ai_scanner_min_training_rows),
            "missing_training_samples": max(int(self.settings.ai_scanner_min_training_rows) - int(decision.ai_training_samples or 0), 0),
            "selected_training_window": int(decision.ai_training_samples or 0),
            "validation_accuracy": decision.ai_validation_accuracy,
            "validation_mae": decision.ai_validation_mae,
            "risk_status": decision.ai_risk_status,
            "risk_reason": decision.ai_risk_reason,
            "model_version": decision.ai_model_version or AI_PATTERN_MODEL_VERSION,
            "reason": reason,
            "scanned_at": scanned_at,
        }

    @staticmethod
    def _candidate_diagnostic(candidate: dict[str, object]) -> dict[str, object]:
        return {
            "market": candidate.get("market"),
            "status": candidate.get("risk_status") or candidate.get("action") or "UNKNOWN",
            "action": candidate.get("action"),
            "downloaded_execution_candles": candidate.get("downloaded_execution_candles", 0),
            "downloaded_trend_candles": candidate.get("downloaded_trend_candles", 0),
            "training_samples": candidate.get("training_samples", 0),
            "required_training_samples": candidate.get("required_training_samples", 0),
            "missing_training_samples": candidate.get("missing_training_samples", 0),
            "selected_training_window": candidate.get("selected_training_window"),
            "validation_accuracy": candidate.get("validation_accuracy"),
            "validation_mae": candidate.get("validation_mae"),
            "regime": candidate.get("regime"),
            "confidence": candidate.get("confidence"),
            "upward_probability": candidate.get("upward_probability"),
            "expected_net_return": candidate.get("expected_net_return"),
            "score": candidate.get("score"),
            "risk_reason": candidate.get("risk_reason"),
            "model_version": candidate.get("model_version"),
        }

    @staticmethod
    def _is_ranked_opportunity(candidate: dict[str, object]) -> bool:
        action = str(candidate.get("action") or "")
        score = float(candidate.get("score") or 0.0)
        confidence = float(candidate.get("confidence") or 0.0)
        upward_probability = float(candidate.get("upward_probability") or 0.0)
        expected_net_return = candidate.get("expected_net_return")

        if action == "LEARNING":
            return False
        if score <= 0.0:
            return False
        if expected_net_return is None:
            return False
        if confidence <= 0.0:
            return False
        if upward_probability <= 0.0:
            return False
        return True

    @staticmethod
    def _snapshot_payload(candidate: dict[str, object]) -> dict[str, object]:
        """Return only fields that are real columns of the persisted snapshot model.

        Scanner candidates also contain transient diagnostics used by the status endpoint.
        Those values must remain in memory and must never be forwarded to the SQLAlchemy
        constructor unless matching database columns are added through a migration.
        """
        reserved_fields = {"id", "scan_id", "rank"}
        snapshot_fields = {
            column.name
            for column in AIOpportunitySnapshot.__table__.columns
            if column.name not in reserved_fields
        }
        return {
            key: value
            for key, value in candidate.items()
            if key in snapshot_fields
        }

    def _persist_scan(self, scan_id: str, selected: list[dict[str, object]]) -> None:
        with AISessionLocal() as session:
            session.execute(delete(AIOpportunitySnapshot))
            for rank, candidate in enumerate(selected, start=1):
                session.add(
                    AIOpportunitySnapshot(
                        scan_id=scan_id,
                        rank=rank,
                        **self._snapshot_payload(candidate),
                    )
                )
            stale_scan_ids = list(
                session.scalars(
                    select(AIOpportunitySnapshot.scan_id)
                    .group_by(AIOpportunitySnapshot.scan_id)
                    .order_by(AIOpportunitySnapshot.scanned_at.desc())
                    .offset(100)
                )
            )
            if stale_scan_ids:
                session.execute(
                    delete(AIOpportunitySnapshot).where(
                        AIOpportunitySnapshot.scan_id.in_(stale_scan_ids)
                    )
                )
            session.commit()

    def _select_universe(self, tickers: list[dict[str, object]]) -> list[dict[str, object]]:
        quote_asset = self.settings.ai_scanner_quote_asset.upper()
        rows: list[dict[str, object]] = []
        for ticker in tickers:
            symbol = str(ticker.get("symbol") or "").upper()
            if not symbol.endswith(quote_asset) or len(symbol) <= len(quote_asset):
                continue
            base = symbol[: -len(quote_asset)]
            if base in _STABLE_BASES or base.endswith(_LEVERAGED_SUFFIXES):
                continue
            try:
                quote_volume = float(ticker.get("quoteVolume") or ticker.get("quote_volume") or 0)
                last_price = float(ticker.get("lastPrice") or ticker.get("last_price") or 0)
            except (TypeError, ValueError):
                continue
            if quote_volume <= 0 or last_price <= 0:
                continue
            rows.append({"symbol": symbol, "quote_volume": quote_volume})
        rows.sort(key=lambda row: float(row["quote_volume"]), reverse=True)
        return rows[: self.settings.ai_scanner_universe_size]

    @staticmethod
    def _opportunity_action(decision, score: float) -> str:
        if decision.ai_risk_status == "LEARNING":
            return "LEARNING"
        if decision.ai_proposed_action == "BUY" and decision.ai_risk_status in {
            "APPROVED",
            "OBSERVATION",
        }:
            return "ENTRY_READY"
        if score >= 65:
            return "WAIT_FOR_ENTRY"
        if score >= 50:
            return "WATCH"
        return "HOLD"

    def _save_state(
        self,
        *,
        status: str,
        universe_size: int,
        scanned_markets: int,
        opportunity_count: int,
        started_at: datetime | None,
        completed_at: datetime | None,
        error: str | None,
    ) -> None:
        next_scan_at = (
            completed_at + timedelta(seconds=self.settings.ai_scanner_interval_seconds)
            if completed_at is not None
            else None
        )
        with AISessionLocal() as session:
            state = session.get(AIOpportunityScannerState, 1)
            if state is None:
                state = AIOpportunityScannerState(id=1)
                session.add(state)
            state.enabled = self.settings.ai_scanner_enabled
            state.status = status
            state.universe_size = universe_size
            state.scanned_markets = scanned_markets
            state.opportunity_count = opportunity_count
            state.last_scan_started_at = started_at
            state.last_scan_completed_at = completed_at
            state.next_scan_at = next_scan_at
            state.last_error = error
            session.commit()

    def _save_error(self, exc: Exception) -> None:
        now = datetime.now(timezone.utc)
        message = f"{type(exc).__name__}: {exc}"
        snapshot = self.progress_snapshot()
        self._set_progress(
            status="ERROR",
            progress_percent=int(snapshot.get("progress_percent") or 0),
            current_market=None,
            last_error=message,
        )
        self._save_state(
            status="ERROR",
            universe_size=int(snapshot.get("total_markets") or 0),
            scanned_markets=int(snapshot.get("analyzed_markets") or 0),
            opportunity_count=int(snapshot.get("classified_opportunities") or 0),
            started_at=snapshot.get("scan_started_at"),
            completed_at=now,
            error=message,
        )
