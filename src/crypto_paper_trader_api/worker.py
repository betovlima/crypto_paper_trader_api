from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .ai_pattern_trader import AIPatternTrader
from .ai_history_service import AIHistoryService
from .mexc_client import MEXCPublicClient, TIMEFRAME_SECONDS
from .config import Settings, get_settings
from .database import SessionLocal
from .execution_costs import ExecutionCosts
from .indicators import add_indicators, latest_complete_row
from .ml_model import ModelPrediction, XGBoostDirectionModel
from .models import (
    Candle,
    Experiment,
    StrategyAccount,
    StrategyDecisionSnapshot,
    StrategyEquitySnapshot,
    StrategyMarketSnapshot,
)
from .multi_broker import MultiStrategyPaperBroker
from .multi_strategy import (
    AdaptiveStrategySelector,
    Ema9Setup91Strategy,
    EmaCrossoverCostAwareStrategy,
    EmaPullbackStrategy,
    HybridComparisonStrategy,
    LarryVolatilityBreakoutStrategy,
    Lbr310AntiContextStrategy,
    StormerFilhaMalCriadaStrategy,
    StrategyDecision,
)
from .strategy_codes import (
    ACTIVE_STRATEGY_CODES,
    ADAPTIVE_STRATEGY_SELECTOR,
    AI_PATTERN_TRADER,
    CURRENT_HYBRID,
    DIRECT_ENTRY_STRATEGY_CODES,
    DYNAMIC_RISK_STRATEGY_CODES,
    EMA_CROSSOVER_COST_AWARE,
    EMA_PULLBACK,
    EMA9_CLASSIC_STRATEGY_CODES,
    EMA9_STRATEGY_CODES,
    LARRY_VOLATILITY_BREAKOUT,
    LBR_310_ANTI_CONTEXT,
    LARRY_WILLIAMS_91_TREND_FOLLOWER,
    STORMER_FILHA_MAL_CRIADA,
    STRATEGY_DISPLAY_NAMES,
)
from .trading_profiles import (
    DEFAULT_TRADING_PROFILE,
    TradingProfile,
    get_trading_profile,
)

logger = logging.getLogger(__name__)


class TraderWorker:
    """Runs one market experiment with multiple independent paper strategies."""

    ACTIVE_STATUSES = ("RUNNING", "STOP_REQUESTED")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = MEXCPublicClient(settings)
        self.hybrid_strategy = HybridComparisonStrategy(settings)
        self.ema_crossover_strategy = EmaCrossoverCostAwareStrategy(settings)
        self.ema_pullback_strategy = EmaPullbackStrategy(settings)
        self.larry_volatility_strategy = LarryVolatilityBreakoutStrategy(settings)
        self.stormer_filha_mal_criada_strategy = StormerFilhaMalCriadaStrategy(settings)
        self.lbr_310_anti_strategy = Lbr310AntiContextStrategy(settings)
        self.adaptive_selector = AdaptiveStrategySelector(settings)
        self.ema9_classic_strategy = Ema9Setup91Strategy(
            settings=settings, cost_aware=False, mode=Ema9Setup91Strategy.CLASSIC
        )
        self.ema9_trend_strategy = Ema9Setup91Strategy(
            settings=settings, cost_aware=False, mode=Ema9Setup91Strategy.TREND_FOLLOWER
        )
        self.ai_pattern_strategy = AIPatternTrader(settings)
        self.ai_history_service = AIHistoryService(settings, self.client)
        # Backward-compatible attribute used by older tests/integrations.
        self.ema9_strategy = self.ema9_classic_strategy
        self.broker = MultiStrategyPaperBroker(settings)
        self._task: asyncio.Task[None] | None = None
        self._wake_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._processing_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return bool(self._task and not self._task.done())

    def start(self) -> None:
        if self.is_running:
            return
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="crypto-paper-trader-worker")

    async def retry_adaptive_selector_research(self, experiment_id: str) -> dict[str, str]:
        """Schedule an immediate local adaptive-research cycle for one experiment."""
        with SessionLocal() as session:
            experiment = session.get(Experiment, experiment_id)
            if experiment is None:
                raise LookupError(f"Experiment {experiment_id} was not found.")

            account = session.scalar(
                select(StrategyAccount).where(
                    StrategyAccount.experiment_id == experiment_id,
                    StrategyAccount.strategy_code == ADAPTIVE_STRATEGY_SELECTOR,
                )
            )
            if account is None:
                raise LookupError(
                    f"Adaptive Strategy Selector account was not found for experiment {experiment_id}."
                )

            account.selector_next_research_at = datetime.now(timezone.utc)
            account.selector_research_status = "RETRY_REQUESTED"
            account.selector_research_summary = (
                "A new local adaptive research cycle was requested manually."
            )
            account.selector_last_error = None
            session.commit()

        self.wake()
        return {
            "experiment_id": experiment_id,
            "status": "RETRY_REQUESTED",
            "message": "Local adaptive research was scheduled for immediate execution.",
            "research_provider": "LOCAL",
        }

    async def stop(self) -> None:
        self._shutdown_event.set()
        self._wake_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=15)
            except asyncio.TimeoutError:
                self._task.cancel()
            except asyncio.CancelledError:
                pass
        await self.client.close()

    def wake(self) -> None:
        self._wake_event.set()

    @asynccontextmanager
    async def exclusive_processing(self) -> AsyncIterator[None]:
        """Serialize administrative mutations with the live worker cycle."""

        async with self._processing_lock:
            yield

    async def stop_latest_running_experiment(
        self,
        close_open_positions: bool,
    ) -> dict[str, object]:
        """Finalize the most recently started RUNNING experiment without touching AI scanner."""

        async with self._processing_lock:
            with SessionLocal() as session:
                experiment = session.scalar(
                    select(Experiment)
                    .where(Experiment.status == "RUNNING")
                    .order_by(Experiment.started_at.desc(), Experiment.id.desc())
                    .limit(1)
                )
                if experiment is None:
                    raise LookupError("No running experiment was found.")

                previous_status = experiment.status
                stopped_at = datetime.now(timezone.utc)
                accounts = self._strategy_accounts(session, experiment.id)
                open_before = sum(1 for account in accounts if account.has_open_position)
                await self._finalize(
                    session=session,
                    experiment=experiment,
                    finished_at=stopped_at,
                    final_status="STOPPED",
                    close_open_positions=close_open_positions,
                )
                remaining = sum(1 for account in accounts if account.has_open_position)
                return {
                    "experiment_id": experiment.id,
                    "previous_status": previous_status,
                    "status": "STOPPED",
                    "stopped_at": stopped_at,
                    "closed_positions": open_before - remaining,
                    "remaining_open_positions": remaining,
                    "data_preserved": True,
                }

    async def _run_loop(self) -> None:
        logger.info(
            "PAPER_ONLY multi-strategy worker started; market interval=%ss",
            self.settings.poll_interval_seconds,
        )
        while not self._shutdown_event.is_set():
            try:
                await self._process_active_experiment()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected worker-loop error")

            try:
                self._wake_event.clear()
                await asyncio.wait_for(
                    self._wake_event.wait(), timeout=self.settings.poll_interval_seconds
                )
            except asyncio.TimeoutError:
                pass
        logger.info("PAPER_ONLY multi-strategy worker stopped")

    async def _process_active_experiment(self) -> None:
        async with self._processing_lock:
            with SessionLocal() as session:
                experiment = session.scalar(
                    select(Experiment)
                    .where(Experiment.status.in_(self.ACTIVE_STATUSES))
                    .order_by(Experiment.started_at)
                    .limit(1)
                )
                if experiment is None:
                    return

                ensure_strategy_accounts(session, experiment)
                session.flush()
                now = datetime.now(timezone.utc)
                if experiment.status == "STOP_REQUESTED":
                    await self._finalize(session, experiment, now, "STOPPED")
                    return
                if now >= self._as_utc(experiment.scheduled_end_at):
                    await self._finalize(session, experiment, now, "FINISHED")
                    return

                try:
                    await self._refresh_waiting_selector_history(
                        session=session, experiment=experiment, now=now
                    )
                    await self._run_live_cycle(session, experiment, now)
                except Exception as exc:
                    logger.exception("Experiment %s live cycle failed", experiment.id)
                    experiment.last_cycle_at = now
                    experiment.error_message = f"Temporary cycle error: {type(exc).__name__}: {exc}"
                    session.commit()

    async def _refresh_waiting_selector_history(
        self,
        *,
        session: Session | None = None,
        experiment: Experiment | None = None,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        """Continue adaptive history backfill even when no new candle is due."""
        owns_session = session is None
        active_session = session or SessionLocal()
        try:
            current_now = now or datetime.now(timezone.utc)
            active_experiment = experiment
            if active_experiment is None:
                active_experiment = active_session.scalar(
                    select(Experiment)
                    .where(Experiment.status.in_(self.ACTIVE_STATUSES))
                    .order_by(Experiment.started_at)
                    .limit(1)
                )
            if active_experiment is None:
                return None
            selector_account = active_session.scalar(
                select(StrategyAccount).where(
                    StrategyAccount.experiment_id == active_experiment.id,
                    StrategyAccount.strategy_code == ADAPTIVE_STRATEGY_SELECTOR,
                )
            )
            if selector_account is None:
                return None
            due_at = self._as_utc(selector_account.selector_next_research_at)
            if due_at is None:
                last_completed = self._as_utc(selector_account.selector_last_completed_at)
                selector_account.selector_next_research_at = (
                    (last_completed or current_now)
                    + timedelta(hours=self.settings.adaptive_research_interval_hours)
                )
                due_at = self._as_utc(selector_account.selector_next_research_at)
                if not selector_account.selector_research_status:
                    selector_account.selector_research_status = "SCHEDULED"
                active_session.flush()

            waiting = (selector_account.selector_research_status or "").upper() in {
                "WAITING_FOR_HISTORY", "INSUFFICIENT_HISTORY", "RETRY_REQUESTED",
                "RESEARCH_ERROR", "BUILDING_HISTORY",
            }
            if not waiting or (due_at is not None and current_now < due_at):
                return None
            result = await self._refresh_selector_account_from_history(
                session=active_session,
                experiment=active_experiment,
                selector_account=selector_account,
                now=current_now,
            )
            active_session.commit()
            return result
        finally:
            if owns_session:
                active_session.close()

    async def _refresh_selector_account_from_history(
        self,
        *,
        session: Session,
        experiment: Experiment,
        selector_account: StrategyAccount,
        now: datetime,
    ) -> dict[str, object]:
        latest = await self.client.get_candles(
            experiment.market, experiment.execution_timeframe, limit=1000, closed_only=True
        )
        history = await self.ai_history_service.synchronize(
            experiment.market, experiment.execution_timeframe, latest
        )
        diagnostics = self.ai_history_service.diagnostics(
            experiment.market, experiment.execution_timeframe
        )
        stored = len(history)
        required = self.settings.adaptive_research_min_candles
        ready = stored >= required
        selector_account.selector_candidate_scores = json.dumps(
            {
                "history": {
                    "raw_candles": stored,
                    "clean_candles": stored,
                    "stored_candles": int(diagnostics.get("stored_candles") or stored),
                    "required_clean_candles": required,
                    "backfill_status": diagnostics.get("status"),
                    "backfill_last_attempt_at": self._json_datetime(
                        diagnostics.get("last_attempt_at")
                    ),
                },
                "history_sync": self._json_safe_mapping(diagnostics),
            },
            separators=(",", ":"),
        )
        if ready:
            selector_account.selector_research_status = "RETRY_REQUESTED"
            selector_account.selector_research_summary = (
                "Adaptive history is ready. Local quantitative research will run on the next analysis cycle."
            )
            selector_account.selector_next_research_at = now
            selector_account.selector_last_error = None
        else:
            selector_account.selector_research_status = "WAITING_FOR_HISTORY"
            selector_account.selector_research_summary = (
                f"Adaptive history is still building: {stored}/{required} candles available."
            )
            selector_account.selector_next_research_at = now + timedelta(
                minutes=self.settings.adaptive_research_retry_minutes
            )
            selector_account.selector_last_error = diagnostics.get("last_error")
        return {
            "experiment_id": experiment.id,
            "selector_status": selector_account.selector_research_status,
            "history": diagnostics,
        }

    def _with_history_sync_diagnostics(
        self, decision: StrategyDecision, market: str, timeframe: str
    ) -> StrategyDecision:
        diagnostics = self.ai_history_service.diagnostics(market, timeframe)
        try:
            payload = json.loads(decision.selector_candidate_scores or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        history = payload.setdefault("history", {})
        history["stored_candles"] = int(diagnostics.get("stored_candles") or 0)
        history["backfill_status"] = diagnostics.get("status")
        history["backfill_last_attempt_at"] = self._json_datetime(
            diagnostics.get("last_attempt_at")
        )
        payload["history_sync"] = self._json_safe_mapping(diagnostics)
        return replace(
            decision,
            selector_candidate_scores=json.dumps(payload, separators=(",", ":")),
        )

    @staticmethod
    def _json_datetime(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return TraderWorker._as_utc(value).isoformat()
        return str(value)

    @classmethod
    def _json_safe_mapping(cls, values: dict[str, object]) -> dict[str, object]:
        return {
            key: cls._json_datetime(value) if isinstance(value, datetime) else value
            for key, value in values.items()
        }

    async def _run_live_cycle(
        self, session: Session, experiment: Experiment, now: datetime
    ) -> None:
        profile = get_trading_profile(experiment.trading_profile)
        market_price, costs = await asyncio.gather(
            self.client.get_latest_price(experiment.market),
            self._resolve_execution_costs(experiment),
        )
        market_price = float(market_price)
        best_bid = float(experiment.best_bid or market_price * (1 - costs.half_spread_rate))
        best_ask = float(experiment.best_ask or market_price * (1 + costs.half_spread_rate))
        experiment.last_price = market_price
        experiment.first_market_price = experiment.first_market_price or market_price
        experiment.last_market_update_at = now
        experiment.last_cycle_at = now

        accounts = self._strategy_accounts(session, experiment.id)
        events: dict[str, tuple[str, str]] = {
            account.strategy_code: ("PRICE_UPDATE", "Market and portfolio data updated.")
            for account in accounts
        }
        live_action_accounts: set[int] = set()

        for account in accounts:
            if account.has_open_position and account.last_atr_14:
                self.broker.update_dynamic_risk_levels(
                    account=account,
                    market_high=market_price,
                    atr=float(account.last_atr_14),
                    costs=costs,
                    profile=profile,
                )
                exit_reason = self._live_exit_reason(
                    account=account,
                    market_price=market_price,
                    best_bid=best_bid,
                    costs=costs,
                    profile=profile,
                    now=now,
                )
                if exit_reason:
                    self.broker.sell(
                        session=session,
                        experiment=experiment,
                        account=account,
                        mid_market_price=market_price,
                        best_bid=best_bid,
                        costs=costs,
                        executed_at=now,
                        reason=exit_reason,
                        decision_id=None,
                        profile=profile,
                    )
                    live_action_accounts.add(account.id)
                    events[account.strategy_code] = (
                        exit_reason,
                        self._event_message(exit_reason),
                    )
                    account.last_event = exit_reason
                    account.last_status_message = self._event_message(exit_reason)

            # EMA 9 entries are confirmed only after a candle closes above the trigger.
            # Live monitoring remains responsible for protective exits, not new entries.

        analysis_due = self._analysis_is_due(experiment=experiment, now=now)
        if analysis_due:
            processed, analysis_events = await self._run_candle_analysis(
                session=session,
                experiment=experiment,
                now=now,
                costs=costs,
                live_action_accounts=live_action_accounts,
            )
            if processed:
                for code, event in analysis_events.items():
                    if (
                        self._strategy_account_by_code(accounts, code).id
                        not in live_action_accounts
                    ):
                        events[code] = event

        for account in accounts:
            equity = self.broker.record_equity(
                session=session,
                experiment=experiment,
                account=account,
                timestamp=now,
                mid_market_price=market_price,
                best_bid=best_bid,
                costs=costs,
            )
            event_type, status_message = events[account.strategy_code]
            account.last_event = event_type
            account.last_status_message = status_message
            self._record_market_snapshot(
                session=session,
                experiment=experiment,
                account=account,
                observed_at=now,
                market_price=market_price,
                best_bid=best_bid,
                best_ask=best_ask,
                costs=costs,
                equity=equity,
                event_type=event_type,
                status_message=status_message,
            )

        experiment.buy_and_hold_current_capital = self._buy_and_hold_final_capital(
            experiment.initial_capital,
            experiment.first_market_price or market_price,
            market_price,
            costs,
        )
        experiment.last_market_event = "MULTI_STRATEGY_UPDATE"
        experiment.error_message = None
        self._mirror_hybrid_account(experiment, accounts)
        session.commit()

        if datetime.now(timezone.utc) >= self._as_utc(experiment.scheduled_end_at):
            await self._finalize(session, experiment, datetime.now(timezone.utc), "FINISHED")

    async def _run_candle_analysis(
        self,
        session: Session,
        experiment: Experiment,
        now: datetime,
        costs: ExecutionCosts,
        live_action_accounts: set[int],
    ) -> tuple[bool, dict[str, tuple[str, str]]]:
        execution_candles, trend_candles = await asyncio.gather(
            self.client.get_candles(
                experiment.market, experiment.execution_timeframe, limit=1000, closed_only=True
            ),
            self.client.get_candles(
                experiment.market, experiment.trend_timeframe, limit=500, closed_only=True
            ),
        )
        self._persist_candles(
            session,
            experiment.id,
            experiment.market,
            experiment.execution_timeframe,
            execution_candles,
        )
        self._persist_candles(
            session,
            experiment.id,
            experiment.market,
            experiment.trend_timeframe,
            trend_candles,
        )

        ai_execution_candles = await self.ai_history_service.synchronize(
            experiment.market, experiment.execution_timeframe, execution_candles
        )
        execution_indicators = add_indicators(
            execution_candles,
            context_lookback=self.settings.market_context_lookback,
            compression_window=self.settings.market_context_compression_window,
        )
        ai_execution_indicators = add_indicators(
            ai_execution_candles,
            context_lookback=self.settings.market_context_lookback,
            compression_window=self.settings.market_context_compression_window,
        )
        trend_indicators = add_indicators(
            trend_candles,
            context_lookback=self.settings.market_context_lookback,
            compression_window=self.settings.market_context_compression_window,
        )
        latest_complete_row(execution_indicators)
        latest_complete_row(trend_indicators)

        required_columns = [
            "ema_9",
            "ema_20",
            "ema_50",
            "ema_200",
            "rsi_14",
            "atr_14",
            "adx_14",
            "relative_volume",
            "volatility_20",
        ]
        valid_indices = execution_indicators.dropna(subset=required_columns).index.tolist()
        if not valid_indices:
            raise ValueError("Not enough complete candles for strategy analysis.")

        initial_dashboard_snapshot = False
        if experiment.last_processed_candle_at is None:
            post_start_indices = [
                index
                for index in valid_indices
                if index >= 2
                and (
                    self._to_datetime(execution_indicators.iloc[index]["timestamp"])
                    + timedelta(seconds=TIMEFRAME_SECONDS[experiment.execution_timeframe])
                )
                > self._as_utc(experiment.started_at)
            ]
            if post_start_indices:
                pending_indices = post_start_indices
            else:
                # Populate the technical/model dashboard immediately from the latest
                # already-closed candle. Every account is action-blocked below, so this
                # baseline snapshot cannot create a historical paper trade.
                pending_indices = [valid_indices[-1]]
                initial_dashboard_snapshot = True
        else:
            pending_indices = [
                index
                for index in valid_indices
                if index >= 2
                and self._is_pending_candle(
                    candle_timestamp=self._to_datetime(
                        execution_indicators.iloc[index]["timestamp"]
                    ),
                    experiment=experiment,
                )
            ]

        if not pending_indices:
            experiment.next_analysis_at = self._next_boundary(now, experiment.execution_timeframe)
            return False, {}

        recovery_mode = len(pending_indices) > 1
        if recovery_mode:
            experiment.recovery_status = "RUNNING"
            experiment.recovery_started_at = now
            experiment.recovery_message = (
                f"Replaying {len(pending_indices)} closed candles missed after the last "
                "processed candle."
            )

        events: dict[str, tuple[str, str]] = {}
        recovered_trades_before = experiment.recovered_trade_count
        baseline_action_block = (
            {account.id for account in self._strategy_accounts(session, experiment.id)}
            if initial_dashboard_snapshot
            else set()
        )
        for current_index in pending_indices:
            # When more than one closed candle is pending, the worker was offline or delayed.
            # Every pending candle belongs to the historical replay, including the latest one.
            is_recovered = recovery_mode
            candle_events, recovered_trade_count = await self._process_candle_index(
                session=session,
                experiment=experiment,
                execution_indicators=execution_indicators,
                ai_execution_indicators=ai_execution_indicators,
                trend_indicators=trend_indicators,
                current_index=current_index,
                costs=costs,
                live_action_accounts=(
                    baseline_action_block
                    if initial_dashboard_snapshot
                    else (live_action_accounts if not is_recovered else set())
                ),
                is_recovered=is_recovered,
            )
            events = candle_events
            if is_recovered:
                experiment.recovered_candle_count += 1
                experiment.recovered_trade_count += recovered_trade_count

        if initial_dashboard_snapshot:
            experiment.recovery_status = "IDLE"
            experiment.recovery_message = (
                "Initial dashboard state generated from the latest closed candle; "
                "no historical trade was executed."
            )
        elif recovery_mode:
            experiment.recovery_status = "COMPLETED"
            experiment.recovery_completed_at = datetime.now(timezone.utc)
            new_trades = experiment.recovered_trade_count - recovered_trades_before
            experiment.recovery_message = (
                f"Recovered {len(pending_indices)} historical candles and "
                f"{new_trades} paper trade executions. No late market order was created."
            )
        else:
            experiment.recovery_status = "IDLE"

        experiment.next_analysis_at = self._next_boundary(now, experiment.execution_timeframe)
        return True, events

    async def _process_candle_index(
        self,
        session: Session,
        experiment: Experiment,
        execution_indicators: pd.DataFrame,
        ai_execution_indicators: pd.DataFrame,
        trend_indicators: pd.DataFrame,
        current_index: int,
        costs: ExecutionCosts,
        live_action_accounts: set[int],
        is_recovered: bool,
    ) -> tuple[dict[str, tuple[str, str]], int]:
        execution_row = execution_indicators.iloc[current_index]
        previous_row = execution_indicators.iloc[current_index - 1]
        previous_previous_row = execution_indicators.iloc[current_index - 2]
        candle_timestamp = self._to_datetime(execution_row["timestamp"])
        candle_end = candle_timestamp + timedelta(
            seconds=TIMEFRAME_SECONDS[experiment.execution_timeframe]
        )

        trend_seconds = TIMEFRAME_SECONDS[experiment.trend_timeframe]
        trend_candidates = trend_indicators[
            trend_indicators["timestamp"].apply(
                lambda value: self._to_datetime(value) + timedelta(seconds=trend_seconds)
                <= candle_end
            )
        ].dropna(subset=["ema_20", "ema_50", "ema_200", "rsi_14", "adx_14"])
        if trend_candidates.empty:
            raise ValueError("No chronologically valid trend candle is available.")
        trend_row = trend_candidates.iloc[-1]

        close_price = float(execution_row["close"])
        historical_bid = close_price * (1 - costs.half_spread_rate)
        historical_ask = close_price * (1 + costs.half_spread_rate)
        atr = float(execution_row["atr_14"])
        profile = get_trading_profile(experiment.trading_profile)

        model = XGBoostDirectionModel(
            required_gross_return=0.0,
            buy_threshold=profile.buy_probability_threshold,
            sell_threshold=profile.sell_probability_threshold,
        )
        model_frame = execution_indicators.iloc[: current_index + 1].copy()
        ai_model_frame = ai_execution_indicators[
            ai_execution_indicators["timestamp"] <= pd.Timestamp(candle_timestamp)
        ].copy()
        if ai_model_frame.empty:
            ai_model_frame = model_frame
        prediction = await asyncio.to_thread(model.fit_predict, model_frame)

        events: dict[str, tuple[str, str]] = {}
        recovered_trade_count = 0
        recovered_action_accounts: set[int] = set()
        accounts = self._strategy_accounts(session, experiment.id)
        accounts_by_code = {account.strategy_code: account for account in accounts}
        self._resolve_ai_pattern_outcomes(
            session=session,
            experiment=experiment,
            execution_indicators=execution_indicators,
            current_index=current_index,
        )

        if is_recovered:
            for account in accounts:
                if account.has_open_position:
                    exit_price, exit_reason = self._historical_exit(
                        account=account,
                        candle=execution_row,
                    )
                    if exit_reason and exit_price is not None:
                        self.broker.sell(
                            session=session,
                            experiment=experiment,
                            account=account,
                            mid_market_price=exit_price,
                            best_bid=exit_price,
                            costs=costs,
                            executed_at=candle_end,
                            reason=exit_reason,
                            decision_id=None,
                            profile=profile,
                            is_recovered=True,
                            recovery_note="Historical OHLC replay after worker downtime.",
                        )
                        recovered_trade_count += 1
                        recovered_action_accounts.add(account.id)
                        events[account.strategy_code] = (
                            "RECOVERED_EXIT",
                            "A missed historical exit was reconstructed from closed candles.",
                        )


        # Evaluate all specialist candidates first. The selector receives the same
        # chronologically valid closed candle and cannot see future data.
        decisions: dict[str, StrategyDecision] = {}
        for account in accounts:
            if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR:
                continue
            account.last_atr_14 = atr
            if account.strategy_code in DYNAMIC_RISK_STRATEGY_CODES and account.has_open_position:
                self.broker.update_dynamic_risk_levels(
                    account=account,
                    market_high=float(execution_row["high"]),
                    atr=atr,
                    costs=costs,
                    profile=profile,
                )
            if account.strategy_code == CURRENT_HYBRID:
                decision = self.hybrid_strategy.decide(
                    account=account,
                    execution_row=execution_row,
                    trend_row=trend_row,
                    prediction=prediction,
                    costs=costs,
                    profile=profile,
                    now=candle_end,
                )
            elif account.strategy_code == EMA_CROSSOVER_COST_AWARE:
                decision = self.ema_crossover_strategy.decide(
                    account=account,
                    current_row=execution_row,
                    previous_row=previous_row,
                    trend_row=trend_row,
                    costs=costs,
                    profile=profile,
                )
            elif account.strategy_code == EMA_PULLBACK:
                decision = self.ema_pullback_strategy.decide(
                    account=account,
                    current_row=execution_row,
                    previous_row=previous_row,
                    trend_row=trend_row,
                    costs=costs,
                    profile=profile,
                )
            elif account.strategy_code == LARRY_VOLATILITY_BREAKOUT:
                lookback_start = max(0, current_index - self.settings.larry_breakout_lookback)
                previous_window = execution_indicators.iloc[lookback_start:current_index]
                decision = self.larry_volatility_strategy.decide(
                    account=account,
                    current_row=execution_row,
                    previous_window=previous_window,
                    trend_row=trend_row,
                    costs=costs,
                    profile=profile,
                )
            elif account.strategy_code == STORMER_FILHA_MAL_CRIADA:
                decision = self.stormer_filha_mal_criada_strategy.decide(
                    account=account,
                    current_row=execution_row,
                    previous_row=previous_row,
                    trend_row=trend_row,
                    costs=costs,
                    profile=profile,
                )
            elif account.strategy_code == LBR_310_ANTI_CONTEXT:
                decision = self.lbr_310_anti_strategy.decide(
                    account=account,
                    history=execution_indicators,
                    current_index=current_index,
                    trend_row=trend_row,
                    costs=costs,
                    profile=profile,
                )
            elif account.strategy_code == AI_PATTERN_TRADER:
                decision = await asyncio.to_thread(
                    self.ai_pattern_strategy.decide,
                    account,
                    ai_model_frame,
                    trend_row,
                    costs,
                    candle_end,
                    profile,
                )
            else:
                ema9_strategy = (
                    self.ema9_trend_strategy
                    if account.strategy_code == LARRY_WILLIAMS_91_TREND_FOLLOWER
                    else self.ema9_classic_strategy
                )
                decision = ema9_strategy.analyze_candle(
                    account=account,
                    current_row=execution_row,
                    previous_row=previous_row,
                    previous_previous_row=previous_previous_row,
                    costs=costs,
                    profile=profile,
                    now=candle_timestamp,
                )
            decisions[account.strategy_code] = decision

        selector_account = accounts_by_code.get(ADAPTIVE_STRATEGY_SELECTOR)
        if selector_account is not None:
            selector_account.last_atr_14 = atr
            if selector_account.has_open_position:
                self.broker.update_dynamic_risk_levels(
                    account=selector_account,
                    market_high=float(execution_row["high"]),
                    atr=atr,
                    costs=costs,
                    profile=profile,
                )
            selector_decision = await asyncio.to_thread(
                self.adaptive_selector.decide,
                selector_account,
                execution_row,
                trend_row,
                costs,
                ai_model_frame,
                len(ai_model_frame) - 1,
                experiment.market,
                experiment.execution_timeframe,
                experiment.trend_timeframe,
                candle_end,
                decisions.get(AI_PATTERN_TRADER),
            )
            selector_decision = self._with_history_sync_diagnostics(
                selector_decision, experiment.market, experiment.execution_timeframe
            )
            selector_account.selector_selected_strategy = (
                selector_decision.selector_selected_strategy
                or selector_account.selector_selected_strategy
            )
            selector_account.selector_market_regime = selector_decision.selector_market_regime
            selector_account.selector_confidence = selector_decision.selector_confidence
            selector_account.selector_expected_net_return = (
                selector_decision.selector_expected_net_return
            )
            selector_account.selector_candidate_scores = selector_decision.selector_candidate_scores
            selector_account.selector_model_version = selector_decision.selector_model_version
            selector_account.selector_active_strategy_name = (
                selector_decision.selector_active_strategy_name
                or selector_account.selector_active_strategy_name
            )
            selector_account.selector_strategy_origin = (
                selector_decision.selector_strategy_origin
                or selector_account.selector_strategy_origin
            )
            selector_account.selector_research_status = (
                selector_decision.selector_research_status
                or selector_account.selector_research_status
            )
            selector_account.selector_research_summary = (
                selector_decision.selector_research_summary
                or selector_account.selector_research_summary
            )
            selector_account.selector_validation_score = (
                selector_decision.selector_validation_score
                if selector_decision.selector_validation_score is not None
                else selector_account.selector_validation_score
            )
            selector_account.selector_profit_factor = (
                selector_decision.selector_profit_factor
                if selector_decision.selector_profit_factor is not None
                else selector_account.selector_profit_factor
            )
            selector_account.selector_max_drawdown_pct = (
                selector_decision.selector_max_drawdown_pct
                if selector_decision.selector_max_drawdown_pct is not None
                else selector_account.selector_max_drawdown_pct
            )
            selector_account.selector_net_return = (
                selector_decision.selector_net_return
                if selector_decision.selector_net_return is not None
                else selector_account.selector_net_return
            )
            selector_account.selector_trade_count = (
                selector_decision.selector_trade_count
                if selector_decision.selector_trade_count is not None
                else selector_account.selector_trade_count
            )
            selector_account.selector_next_research_at = (
                selector_decision.selector_next_research_at
                or selector_account.selector_next_research_at
            )
            selector_account.selector_strategy_spec_json = (
                selector_decision.selector_strategy_spec_json
                or selector_account.selector_strategy_spec_json
            )
            selector_account.selector_source_urls_json = (
                selector_decision.selector_source_urls_json
                or selector_account.selector_source_urls_json
            )
            selector_account.selector_ai_provider = (
                selector_decision.selector_ai_provider
                or selector_account.selector_ai_provider
            )
            selector_account.selector_ai_model = (
                selector_decision.selector_ai_model
                or selector_account.selector_ai_model
            )
            selector_account.selector_ai_review_status = (
                selector_decision.selector_ai_review_status
                or selector_account.selector_ai_review_status
            )
            selector_account.selector_ai_review_score = (
                selector_decision.selector_ai_review_score
                if selector_decision.selector_ai_review_score is not None
                else selector_account.selector_ai_review_score
            )
            selector_account.selector_ai_review_summary = (
                selector_decision.selector_ai_review_summary
                or selector_account.selector_ai_review_summary
            )
            decisions[ADAPTIVE_STRATEGY_SELECTOR] = selector_decision

        for account in accounts:
            decision = decisions[account.strategy_code]
            position_before = "LONG" if account.has_open_position else "FLAT"
            snapshot = self._build_decision_snapshot(
                experiment=experiment,
                account=account,
                candle_timestamp=candle_timestamp,
                execution_row=execution_row,
                trend_row=trend_row,
                prediction=prediction,
                costs=costs,
                required_gross_return=costs.estimated_round_trip_rate,
                position_before=position_before,
                decision=decision,
            )
            snapshot.is_recovered = is_recovered
            snapshot.recovery_note = (
                "Closed candle replayed after worker downtime." if is_recovered else None
            )
            session.add(snapshot)
            session.flush()

            event_type = f"ANALYSIS_{decision.final_signal}"
            status_message = f"Closed-candle analysis completed: {decision.final_signal}."
            action_accounts = live_action_accounts | recovered_action_accounts
            if account.id not in action_accounts:
                if (
                    account.strategy_code in DIRECT_ENTRY_STRATEGY_CODES
                    and decision.final_signal == "BUY"
                    and not account.has_open_position
                ):
                    try:
                        self.broker.buy(
                            session=session,
                            experiment=experiment,
                            account=account,
                            mid_market_price=close_price,
                            best_ask=historical_ask,
                            atr=atr,
                            costs=costs,
                            executed_at=candle_end,
                            reason=decision.reason,
                            decision_id=snapshot.id,
                            entry_candle_timestamp=candle_timestamp,
                            stop_override=decision.stop_loss_override,
                            take_profit_override=decision.take_profit_override,
                            profile=profile,
                            is_recovered=is_recovered,
                            recovery_note=(
                                "Signal reconstructed from a missed closed candle."
                                if is_recovered
                                else None
                            ),
                        )
                        snapshot.action_executed = True
                        recovered_trade_count += int(is_recovered)
                        if is_recovered:
                            event_type = "RECOVERED_ENTRY"
                            status_message = (
                                "A missed closed-candle purchase was reconstructed as a paper trade."
                            )
                        else:
                            status_message = "The strategy authorized a simulated purchase."
                    except ValueError as exc:
                        snapshot.decision_reason = f"{snapshot.decision_reason}; buy_skipped={exc}"
                        event_type = "ANALYSIS_HOLD"
                        status_message = f"Simulated purchase skipped: {exc}"
                elif decision.final_signal == "SELL" and account.has_open_position:
                    self.broker.sell(
                        session=session,
                        experiment=experiment,
                        account=account,
                        mid_market_price=close_price,
                        best_bid=historical_bid,
                        costs=costs,
                        executed_at=candle_end,
                        reason=decision.reason,
                        decision_id=snapshot.id,
                        profile=profile,
                        is_recovered=is_recovered,
                        recovery_note=(
                            "Exit reconstructed from a missed closed candle."
                            if is_recovered
                            else None
                        ),
                    )
                    snapshot.action_executed = True
                    recovered_trade_count += int(is_recovered)
                    if is_recovered:
                        event_type = "RECOVERED_EXIT"
                        status_message = (
                            "A missed closed-candle sale was reconstructed as a paper trade."
                        )
                    else:
                        status_message = "The strategy authorized a simulated sale."

            if account.id in recovered_action_accounts and account.strategy_code in events:
                event_type, status_message = events[account.strategy_code]
            events[account.strategy_code] = (event_type, status_message)
            account.last_event = event_type
            account.last_status_message = status_message

        experiment.last_processed_candle_at = candle_timestamp
        return events, recovered_trade_count

    def _resolve_ai_pattern_outcomes(
        self,
        session: Session,
        experiment: Experiment,
        execution_indicators: pd.DataFrame,
        current_index: int,
    ) -> None:
        """Resolve delayed AI rewards without using future data at prediction time."""

        unresolved = list(
            session.scalars(
                select(StrategyDecisionSnapshot)
                .where(
                    StrategyDecisionSnapshot.experiment_id == experiment.id,
                    StrategyDecisionSnapshot.strategy_code == AI_PATTERN_TRADER,
                    StrategyDecisionSnapshot.ai_outcome_resolved.is_(False),
                    StrategyDecisionSnapshot.ai_horizon_candles.is_not(None),
                )
                .order_by(StrategyDecisionSnapshot.candle_timestamp)
            )
        )
        if not unresolved:
            return

        timestamp_to_index = {
            self._to_datetime(row["timestamp"]): index
            for index, row in execution_indicators.iloc[: current_index + 1].iterrows()
        }
        for snapshot in unresolved:
            base_timestamp = self._as_utc(snapshot.candle_timestamp)
            base_index = timestamp_to_index.get(base_timestamp)
            if base_index is None:
                continue
            horizon = int(snapshot.ai_horizon_candles or self.settings.ai_pattern_horizon_candles)
            target_index = base_index + horizon
            if target_index > current_index:
                continue

            reference_price = float(snapshot.market_price)
            if reference_price <= 0:
                continue
            target_row = execution_indicators.iloc[target_index]
            path = execution_indicators.iloc[base_index + 1 : target_index + 1]
            realized_gross_return = float(target_row["close"]) / reference_price - 1
            realized_adverse_return = (
                float(path["low"].min()) / reference_price - 1 if not path.empty else 0.0
            )
            realized_net_return = (
                realized_gross_return - float(snapshot.estimated_round_trip_cost_rate or 0.0)
            )
            reward = realized_net_return - (
                max(-realized_adverse_return, 0.0)
                * self.settings.ai_pattern_reward_drawdown_penalty
            )
            proposed = str(snapshot.ai_proposed_action or "HOLD").upper()
            if proposed == "BUY":
                direction_correct = realized_net_return > 0
            elif proposed == "SELL":
                direction_correct = realized_gross_return < 0
            else:
                direction_correct = abs(realized_net_return) < max(
                    self.settings.ai_pattern_min_expected_net_return,
                    float(snapshot.estimated_round_trip_cost_rate or 0.0),
                )

            snapshot.ai_outcome_resolved = True
            snapshot.ai_outcome_candle_timestamp = self._to_datetime(target_row["timestamp"])
            snapshot.ai_realized_gross_return = realized_gross_return
            snapshot.ai_realized_net_return = realized_net_return
            snapshot.ai_realized_reward = reward
            snapshot.ai_realized_adverse_return = realized_adverse_return
            snapshot.ai_direction_correct = direction_correct

    @staticmethod
    def _historical_exit(
        account: StrategyAccount,
        candle: pd.Series,
    ) -> tuple[float | None, str | None]:
        low = float(candle["low"])
        high = float(candle["high"])
        if (
            account.strategy_code in EMA9_CLASSIC_STRATEGY_CODES
            and account.exit_trigger_price is not None
            and low <= account.exit_trigger_price
        ):
            return float(account.exit_trigger_price), "RECOVERED_EMA9_CLASSIC_EXIT"
        protective_levels = [
            value
            for value in (account.stop_loss_price, account.trailing_stop_price)
            if value is not None
        ]
        protective_stop = max(protective_levels) if protective_levels else None
        # Conservative OHLC replay: when both stop and target are touched, assume stop first.
        if protective_stop is not None and low <= protective_stop:
            reason = (
                "RECOVERED_TRAILING_STOP"
                if account.trailing_stop_price and protective_stop == account.trailing_stop_price
                else "RECOVERED_STOP_LOSS"
            )
            return float(protective_stop), reason
        if account.take_profit_price is not None and high >= account.take_profit_price:
            return float(account.take_profit_price), "RECOVERED_TAKE_PROFIT"
        return None, None

    def _build_decision_snapshot(
        self,
        experiment: Experiment,
        account: StrategyAccount,
        candle_timestamp: datetime,
        execution_row: pd.Series,
        trend_row: pd.Series,
        prediction: ModelPrediction,
        costs: ExecutionCosts,
        required_gross_return: float,
        position_before: str,
        decision,
    ) -> StrategyDecisionSnapshot:
        profile = get_trading_profile(experiment.trading_profile)
        return StrategyDecisionSnapshot(
            experiment_id=experiment.id,
            strategy_account_id=account.id,
            strategy_code=account.strategy_code,
            candle_timestamp=candle_timestamp,
            market_price=float(execution_row["close"]),
            candle_high=float(execution_row["high"]),
            candle_low=float(execution_row["low"]),
            fast_ema_period=profile.fast_ema_period,
            slow_ema_period=profile.slow_ema_period,
            regime_ema_period=profile.regime_ema_period,
            fast_ema_value=float(execution_row[f"ema_{profile.fast_ema_period}"]),
            slow_ema_value=float(execution_row[f"ema_{profile.slow_ema_period}"]),
            regime_ema_value=float(execution_row[f"ema_{profile.regime_ema_period}"]),
            ema_9=float(execution_row["ema_9"]),
            ema_9_previous=account.ema_9_previous,
            ema_9_slope=account.ema_9_slope,
            ema_20=float(execution_row["ema_20"]),
            ema_50=float(execution_row["ema_50"]),
            ema_200=float(execution_row["ema_200"]),
            rsi_14=float(execution_row["rsi_14"]),
            atr_14=float(execution_row["atr_14"]),
            adx_14=float(execution_row["adx_14"]),
            average_volume_20=float(execution_row["average_volume_20"]),
            relative_volume=float(execution_row["relative_volume"]),
            volatility_20=float(execution_row["volatility_20"]),
            return_1=float(execution_row["return_1"]),
            return_3=float(execution_row["return_3"]),
            return_6=float(execution_row["return_6"]),
            range_ratio_20=float(execution_row.get("range_ratio_20", 0.0)),
            body_ratio=float(execution_row.get("body_ratio", 0.0)),
            close_location=float(execution_row.get("close_location", 0.0)),
            compression_ratio=float(execution_row.get("compression_ratio", 1.0)),
            trend_age_up=float(execution_row.get("trend_age_up", 0.0)),
            extension_ema20_atr=float(execution_row.get("extension_ema20_atr", 0.0)),
            ignition_score=float(execution_row.get("ignition_score", 0.0)),
            exhaustion_score=float(execution_row.get("exhaustion_score", 0.0)),
            expected_value_r=(
                (
                    float(prediction.upward_probability)
                    * float(decision.reward_risk_ratio or 0.0)
                    - (1.0 - float(prediction.upward_probability))
                )
                if account.strategy_code == CURRENT_HYBRID
                else (
                    float(decision.ai_upward_probability)
                    * float(decision.reward_risk_ratio or 0.0)
                    - (1.0 - float(decision.ai_upward_probability))
                )
                if account.strategy_code == AI_PATTERN_TRADER
                and decision.ai_upward_probability is not None
                else None
            ),
            trend_close=float(trend_row["close"]),
            trend_ema_20=float(trend_row["ema_20"]),
            trend_ema_50=float(trend_row["ema_50"]),
            trend_ema_200=float(trend_row["ema_200"]),
            trend_rsi_14=float(trend_row["rsi_14"]),
            trend_adx_14=float(trend_row["adx_14"]),
            upward_probability=(
                prediction.upward_probability
                if account.strategy_code == CURRENT_HYBRID
                else decision.ai_upward_probability
                if account.strategy_code == AI_PATTERN_TRADER
                else None
            ),
            downward_probability=(
                prediction.downward_probability
                if account.strategy_code == CURRENT_HYBRID
                else (1 - decision.ai_upward_probability)
                if account.strategy_code == AI_PATTERN_TRADER
                and decision.ai_upward_probability is not None
                else None
            ),
            expected_return=(
                prediction.expected_return
                if account.strategy_code == CURRENT_HYBRID
                else decision.ai_expected_net_return
                if account.strategy_code == AI_PATTERN_TRADER
                else None
            ),
            model_accuracy=(
                prediction.accuracy
                if account.strategy_code == CURRENT_HYBRID
                else decision.ai_validation_accuracy
                if account.strategy_code == AI_PATTERN_TRADER
                else None
            ),
            model_precision=(
                prediction.precision if account.strategy_code == CURRENT_HYBRID else None
            ),
            model_recall=(prediction.recall if account.strategy_code == CURRENT_HYBRID else None),
            model_roc_auc=(prediction.roc_auc if account.strategy_code == CURRENT_HYBRID else None),
            training_rows=(
                prediction.training_rows
                if account.strategy_code == CURRENT_HYBRID
                else int(decision.ai_training_samples or 0)
                if account.strategy_code == AI_PATTERN_TRADER
                else 0
            ),
            model_top_features=(
                prediction.top_features_json
                if account.strategy_code == CURRENT_HYBRID
                else decision.ai_feature_summary or "{}"
                if account.strategy_code == AI_PATTERN_TRADER
                else "[]"
            ),
            maker_fee_rate=costs.maker_fee_rate,
            taker_fee_rate=costs.taker_fee_rate,
            spread_rate=costs.spread_rate,
            slippage_rate=costs.slippage_rate,
            estimated_round_trip_cost_rate=costs.estimated_round_trip_rate,
            required_gross_return=required_gross_return,
            setup_status=decision.setup_status,
            setup_candle_high=account.setup_candle_high,
            setup_candle_low=account.setup_candle_low,
            entry_trigger_price=account.entry_trigger_price,
            initial_stop_price=account.initial_setup_stop_price,
            potential_target_price=decision.potential_target_price,
            potential_gross_return=decision.potential_gross_return,
            reward_risk_ratio=decision.reward_risk_ratio,
            stop_management_mode=account.stop_management_mode,
            active_stop_price=max(
                [
                    value
                    for value in (account.stop_loss_price, account.trailing_stop_price)
                    if value is not None
                ],
                default=None,
            ),
            exit_trigger_price=account.exit_trigger_price,
            ai_mode=decision.ai_mode,
            ai_proposed_action=decision.ai_proposed_action,
            ai_regime=decision.ai_regime,
            ai_pattern_cluster=decision.ai_pattern_cluster,
            ai_confidence=decision.ai_confidence,
            ai_neighbor_count=decision.ai_neighbor_count,
            ai_positive_neighbor_rate=decision.ai_positive_neighbor_rate,
            ai_expected_gross_return=decision.ai_expected_gross_return,
            ai_expected_net_return=decision.ai_expected_net_return,
            ai_worst_adverse_return=decision.ai_worst_adverse_return,
            ai_model_version=decision.ai_model_version,
            ai_training_samples=decision.ai_training_samples,
            ai_validation_accuracy=decision.ai_validation_accuracy,
            ai_validation_mae=decision.ai_validation_mae,
            ai_risk_status=decision.ai_risk_status,
            ai_risk_reason=decision.ai_risk_reason,
            ai_horizon_candles=decision.ai_horizon_candles,
            ai_feature_summary=decision.ai_feature_summary,
            selector_selected_strategy=decision.selector_selected_strategy,
            selector_market_regime=decision.selector_market_regime,
            selector_confidence=decision.selector_confidence,
            selector_expected_net_return=decision.selector_expected_net_return,
            selector_candidate_scores=decision.selector_candidate_scores,
            selector_model_version=decision.selector_model_version,
            selector_active_strategy_name=decision.selector_active_strategy_name,
            selector_strategy_origin=decision.selector_strategy_origin,
            selector_research_status=decision.selector_research_status,
            selector_research_summary=decision.selector_research_summary,
            selector_validation_score=decision.selector_validation_score,
            selector_profit_factor=decision.selector_profit_factor,
            selector_max_drawdown_pct=decision.selector_max_drawdown_pct,
            selector_net_return=decision.selector_net_return,
            selector_trade_count=decision.selector_trade_count,
            selector_next_research_at=decision.selector_next_research_at,
            selector_strategy_spec_json=decision.selector_strategy_spec_json,
            selector_source_urls_json=decision.selector_source_urls_json,
            selector_ai_provider=decision.selector_ai_provider,
            selector_ai_model=decision.selector_ai_model,
            selector_ai_review_status=decision.selector_ai_review_status,
            selector_ai_review_score=decision.selector_ai_review_score,
            selector_ai_review_summary=decision.selector_ai_review_summary,
            technical_signal=decision.technical_signal,
            model_signal=decision.model_signal,
            final_signal=decision.final_signal,
            technical_confirmations=decision.technical_confirmations,
            decision_reason=decision.reason,
            position_before=position_before,
            action_executed=False,
            execution_reference_price=decision.execution_reference_price,
        )

    def _live_exit_reason(
        self,
        account: StrategyAccount,
        market_price: float,
        best_bid: float,
        costs: ExecutionCosts,
        now: datetime,
        profile: TradingProfile | None = None,
    ) -> str | None:
        active_profile = profile
        max_holding_hours = (
            active_profile.max_holding_hours
            if active_profile
            else self.settings.max_holding_hours
        )
        max_daily_loss_pct = (
            active_profile.max_daily_loss_pct
            if active_profile
            else self.settings.max_daily_loss_pct
        )
        if (
            account.strategy_code in EMA9_CLASSIC_STRATEGY_CODES
            and account.exit_trigger_price is not None
            and best_bid <= account.exit_trigger_price
        ):
            return "LIVE_EMA9_CLASSIC_EXIT"
        protective_levels = [
            value
            for value in (account.stop_loss_price, account.trailing_stop_price)
            if value is not None
        ]
        protective_stop = max(protective_levels) if protective_levels else None
        if protective_stop is not None and best_bid <= protective_stop:
            if account.trailing_stop_price and protective_stop == account.trailing_stop_price:
                return "LIVE_TRAILING_STOP"
            return "LIVE_STOP_LOSS"
        if account.take_profit_price is not None and best_bid >= account.take_profit_price:
            return "LIVE_TAKE_PROFIT"
        if account.entry_time:
            holding_hours = (
                self._as_utc(now) - self._as_utc(account.entry_time)
            ).total_seconds() / 3600
            if holding_hours >= max_holding_hours:
                return "LIVE_TIME_STOP"
        if self._liquidation_equity(account, best_bid, costs) <= (
            account.initial_capital * (1 - max_daily_loss_pct)
        ):
            return "LIVE_DAILY_LOSS_LIMIT"
        return None

    def _entry_block_reason(
        self,
        account: StrategyAccount,
        best_bid: float,
        costs: ExecutionCosts,
        now: datetime,
        profile: TradingProfile | None = None,
    ) -> str | None:
        max_daily_loss_pct = (
            profile.max_daily_loss_pct if profile else self.settings.max_daily_loss_pct
        )
        if account.cooldown_until and self._as_utc(account.cooldown_until) > self._as_utc(now):
            return f"The strategy is in cooldown until {account.cooldown_until}."
        if self._liquidation_equity(account, best_bid, costs) <= account.initial_capital * (
            1 - max_daily_loss_pct
        ):
            return "New entries are blocked by the maximum-loss rule."
        return None

    @staticmethod
    def _reject_armed_setup(account: StrategyAccount, reason: str) -> None:
        account.setup_status = "REJECTED"
        account.setup_cancel_reason = reason
        account.rejected_signals = int(account.rejected_signals or 0) + 1

    async def _resolve_execution_costs(self, experiment: Experiment) -> ExecutionCosts:
        if self.settings.use_public_market_fee_rates and experiment.min_market_amount is None:
            try:
                rules = await self.client.get_market_rules(experiment.market)
                discount_factor = (
                    1 - self.settings.mx_fee_discount_pct
                    if self.settings.mx_fee_discount_enabled
                    else 1.0
                )
                experiment.maker_fee_rate = rules.maker_fee_rate * discount_factor
                experiment.taker_fee_rate = rules.taker_fee_rate * discount_factor
                experiment.fee_source = rules.source + (
                    "_MX_DISCOUNT" if self.settings.mx_fee_discount_enabled else "_API_SPOT"
                )
                experiment.min_market_amount = rules.min_amount
                experiment.base_currency = rules.base_currency
                experiment.quote_currency = rules.quote_currency
            except Exception:
                logger.exception("Could not refresh public MEXC market rules; using API Spot config")

        spread_rate = self.settings.fallback_spread_rate
        try:
            depth = await self.client.get_depth_snapshot(experiment.market)
            spread_rate = max(depth.spread_rate, 0.0)
            experiment.best_bid = depth.best_bid
            experiment.best_ask = depth.best_ask
        except Exception:
            logger.exception("Could not read market depth; using fallback spread")

        experiment.last_spread_rate = spread_rate
        count = experiment.spread_observations + 1
        experiment.average_spread_rate = (
            experiment.average_spread_rate * experiment.spread_observations + spread_rate
        ) / count
        experiment.spread_observations = count
        return ExecutionCosts(
            maker_fee_rate=experiment.maker_fee_rate,
            taker_fee_rate=experiment.taker_fee_rate,
            spread_rate=spread_rate,
            slippage_rate=self.settings.slippage_rate,
            fee_source=experiment.fee_source,
        )

    def _record_market_snapshot(
        self,
        session: Session,
        experiment: Experiment,
        account: StrategyAccount,
        observed_at: datetime,
        market_price: float,
        best_bid: float,
        best_ask: float,
        costs: ExecutionCosts,
        equity: StrategyEquitySnapshot,
        event_type: str,
        status_message: str,
    ) -> None:
        unrealized_pnl = self._unrealized_pnl(account, best_bid, costs)
        protective_levels = [
            value
            for value in (account.stop_loss_price, account.trailing_stop_price)
            if value is not None
        ]
        protective_stop = max(protective_levels) if protective_levels else None
        distance_to_stop = (
            (best_bid - protective_stop) / best_bid
            if protective_stop is not None and best_bid > 0
            else None
        )
        distance_to_target = (
            (account.take_profit_price - best_bid) / best_bid
            if account.take_profit_price is not None and best_bid > 0
            else None
        )
        session.add(
            StrategyMarketSnapshot(
                experiment_id=experiment.id,
                strategy_account_id=account.id,
                strategy_code=account.strategy_code,
                observed_at=observed_at,
                market_price=market_price,
                best_bid=best_bid,
                best_ask=best_ask,
                spread_rate=costs.spread_rate,
                cash_balance=account.cash_balance,
                asset_quantity=account.asset_quantity,
                position_value=equity.position_value,
                total_equity=equity.total_equity,
                unrealized_pnl=unrealized_pnl,
                drawdown_pct=equity.drawdown_pct,
                has_position=account.has_open_position,
                stop_loss_price=account.stop_loss_price,
                take_profit_price=account.take_profit_price,
                trailing_stop_price=account.trailing_stop_price,
                distance_to_stop_pct=distance_to_stop,
                distance_to_take_profit_pct=distance_to_target,
                event_type=event_type,
                status_message=status_message,
                last_analysis_at=experiment.last_processed_candle_at,
                next_analysis_at=experiment.next_analysis_at,
            )
        )

    async def _finalize(
        self,
        session: Session,
        experiment: Experiment,
        finished_at: datetime,
        final_status: str,
        close_open_positions: bool = True,
    ) -> None:
        costs = await self._resolve_execution_costs(experiment)
        profile = get_trading_profile(experiment.trading_profile)
        try:
            market_price = float(await self.client.get_latest_price(experiment.market))
        except Exception:
            logger.exception("Could not obtain final ticker; using the last stored price")
            market_price = float(experiment.last_price or experiment.first_market_price or 0.0)

        if market_price <= 0:
            experiment.status = "FAILED"
            experiment.finished_at = finished_at
            experiment.error_message = "No market price was available to finalize the experiment."
            session.commit()
            return

        best_bid = float(experiment.best_bid or market_price * (1 - costs.half_spread_rate))
        best_ask = float(experiment.best_ask or market_price * (1 + costs.half_spread_rate))
        accounts = self._strategy_accounts(session, experiment.id)
        for account in accounts:
            if close_open_positions and account.has_open_position:
                self.broker.sell(
                    session=session,
                    experiment=experiment,
                    account=account,
                    mid_market_price=market_price,
                    best_bid=best_bid,
                    costs=costs,
                    executed_at=finished_at,
                    reason="FORCED_CLOSE_AT_EXPERIMENT_END",
                    decision_id=None,
                    profile=profile,
                )
            equity = self.broker.record_equity(
                session=session,
                experiment=experiment,
                account=account,
                timestamp=finished_at,
                mid_market_price=market_price,
                best_bid=best_bid,
                costs=costs,
            )
            account.final_capital = equity.total_equity
            account.status = final_status
            account.last_event = final_status
            account.last_status_message = (
                "The experiment was stopped and its data was preserved."
                if final_status == "STOPPED"
                else "The experiment was finalized."
            )
            self._record_market_snapshot(
                session=session,
                experiment=experiment,
                account=account,
                observed_at=finished_at,
                market_price=market_price,
                best_bid=best_bid,
                best_ask=best_ask,
                costs=costs,
                equity=equity,
                event_type=final_status,
                status_message=(
                    "The experiment was stopped and consolidated without deleting data."
                    if final_status == "STOPPED"
                    else "The experiment was finalized and consolidated."
                ),
            )

        experiment.last_price = market_price
        experiment.last_market_update_at = finished_at
        experiment.buy_and_hold_current_capital = self._buy_and_hold_final_capital(
            experiment.initial_capital,
            experiment.first_market_price or market_price,
            market_price,
            costs,
        )
        experiment.buy_and_hold_final_capital = self._buy_and_hold_final_capital(
            experiment.initial_capital,
            experiment.first_market_price or market_price,
            market_price,
            costs,
        )
        experiment.status = final_status
        experiment.finished_at = finished_at
        experiment.last_cycle_at = finished_at
        experiment.last_market_event = final_status
        self._mirror_hybrid_account(experiment, accounts)
        session.commit()


    @staticmethod
    def _unrealized_pnl(account: StrategyAccount, best_bid: float, costs: ExecutionCosts) -> float:
        if not account.has_open_position or account.average_entry_price is None:
            return 0.0
        execution_price = best_bid * (1 - costs.slippage_rate)
        net_proceeds = account.asset_quantity * execution_price * (1 - costs.taker_fee_rate)
        cost_basis = account.asset_quantity * account.average_entry_price
        return net_proceeds - cost_basis

    @staticmethod
    def _liquidation_equity(
        account: StrategyAccount, best_bid: float, costs: ExecutionCosts
    ) -> float:
        if not account.has_open_position:
            return account.cash_balance
        execution_price = best_bid * (1 - costs.slippage_rate)
        position_value = account.asset_quantity * execution_price * (1 - costs.taker_fee_rate)
        return account.cash_balance + position_value

    @staticmethod
    def _event_message(event_type: str) -> str:
        return {
            "LIVE_STOP_LOSS": "The protective stop was reached during 15-second monitoring.",
            "LIVE_TRAILING_STOP": "The trailing stop was reached during 15-second monitoring.",
            "LIVE_TAKE_PROFIT": "The take-profit level was reached during monitoring.",
            "LIVE_TIME_STOP": "The maximum holding time was reached.",
            "LIVE_DAILY_LOSS_LIMIT": "The strategy reached the maximum-loss limit.",
            "LIVE_EMA9_CLASSIC_EXIT": "The classical Setup 9.1 exit trigger was broken.",
        }.get(event_type, event_type)

    @staticmethod
    def _buy_and_hold_final_capital(
        initial_capital: float,
        initial_price: float,
        final_price: float,
        costs: ExecutionCosts,
    ) -> float:
        initial_ask = initial_price * (1 + costs.half_spread_rate)
        buy_execution_price = initial_ask * (1 + costs.slippage_rate)
        quantity = initial_capital / (buy_execution_price * (1 + costs.taker_fee_rate))
        final_bid = final_price * (1 - costs.half_spread_rate)
        sell_execution_price = final_bid * (1 - costs.slippage_rate)
        return quantity * sell_execution_price * (1 - costs.taker_fee_rate)

    @staticmethod
    def _persist_candles(
        session: Session,
        experiment_id: str,
        market: str,
        timeframe: str,
        frame: pd.DataFrame,
    ) -> None:
        rows = [
            {
                "experiment_id": experiment_id,
                "market": market,
                "timeframe": timeframe,
                "timestamp": TraderWorker._to_datetime(row.timestamp),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "value": float(row.value),
                "is_closed": True,
            }
            for row in frame.itertuples(index=False)
        ]
        if not rows:
            return
        statement = sqlite_insert(Candle).values(rows)
        statement = statement.on_conflict_do_nothing(
            index_elements=["experiment_id", "market", "timeframe", "timestamp"]
        )
        session.execute(statement)

    @staticmethod
    def _strategy_accounts(session: Session, experiment_id: str) -> list[StrategyAccount]:
        return list(
            session.scalars(
                select(StrategyAccount)
                .where(
                    StrategyAccount.experiment_id == experiment_id,
                    StrategyAccount.strategy_code.in_(ACTIVE_STRATEGY_CODES),
                )
                .order_by(StrategyAccount.id)
            )
        )

    @staticmethod
    def _strategy_account_by_code(
        accounts: list[StrategyAccount], strategy_code: str
    ) -> StrategyAccount:
        for account in accounts:
            if account.strategy_code == strategy_code:
                return account
        raise KeyError(strategy_code)

    @staticmethod
    def _mirror_hybrid_account(experiment: Experiment, accounts: list[StrategyAccount]) -> None:
        hybrid = next((item for item in accounts if item.strategy_code == CURRENT_HYBRID), None)
        if hybrid is None:
            return
        experiment.cash_balance = hybrid.cash_balance
        experiment.asset_quantity = hybrid.asset_quantity
        experiment.average_entry_price = hybrid.average_entry_price
        experiment.entry_market_price = hybrid.entry_market_price
        experiment.entry_execution_price = hybrid.entry_execution_price
        experiment.entry_fee_paid = hybrid.entry_fee_paid
        experiment.entry_time = hybrid.entry_time
        experiment.initial_risk_per_unit = hybrid.initial_risk_per_unit
        experiment.break_even_activated = hybrid.break_even_activated
        experiment.last_atr_14 = hybrid.last_atr_14
        experiment.highest_price_since_entry = hybrid.highest_price_since_entry
        experiment.stop_loss_price = hybrid.stop_loss_price
        experiment.take_profit_price = hybrid.take_profit_price
        experiment.trailing_stop_price = hybrid.trailing_stop_price
        experiment.total_fees = hybrid.total_fees
        experiment.total_spread_cost = hybrid.total_spread_cost
        experiment.total_slippage_cost = hybrid.total_slippage_cost
        experiment.realized_pnl = hybrid.realized_pnl
        experiment.max_equity = hybrid.max_equity
        experiment.max_drawdown_pct = hybrid.max_drawdown_pct
        experiment.consecutive_losses = hybrid.consecutive_losses
        experiment.cooldown_until = hybrid.cooldown_until
        experiment.final_capital = hybrid.final_capital

    def _analysis_is_due(self, experiment: Experiment, now: datetime) -> bool:
        """Return whether strategy analysis must run in the current worker cycle.

        A persisted experiment without any processed candle always needs its initial
        dashboard snapshot immediately. This takes precedence over a future
        ``next_analysis_at`` value that may have been stored by an older deployment.
        """

        if experiment.last_processed_candle_at is None:
            return True
        if experiment.next_analysis_at is None:
            return True
        return self._as_utc(now) >= self._as_utc(experiment.next_analysis_at)

    def _is_pending_candle(
        self,
        candle_timestamp: datetime,
        experiment: Experiment,
    ) -> bool:
        """Return whether a closed candle still needs strategy analysis.

        Persisted ``last_processed_candle_at`` stores the candle opening timestamp, so
        subsequent recovery must compare opening timestamps. For a brand-new experiment,
        however, the first eligible candle can start before the experiment and close after
        it. Comparing only its opening timestamp would delay the first dashboard decision by
        one additional full timeframe.
        """

        candle_start = self._as_utc(candle_timestamp)
        if experiment.last_processed_candle_at is not None:
            return candle_start > self._as_utc(experiment.last_processed_candle_at)

        candle_end = candle_start + timedelta(
            seconds=TIMEFRAME_SECONDS[experiment.execution_timeframe]
        )
        return candle_end > self._as_utc(experiment.started_at)

    @staticmethod
    def _current_candle_start(now: datetime, timeframe: str) -> datetime:
        seconds = TIMEFRAME_SECONDS[timeframe]
        epoch = int(TraderWorker._as_utc(now).timestamp())
        candle_epoch = (epoch // seconds) * seconds
        return datetime.fromtimestamp(candle_epoch, tz=timezone.utc)

    @staticmethod
    def _next_boundary(now: datetime, timeframe: str) -> datetime:
        seconds = TIMEFRAME_SECONDS[timeframe]
        epoch = int(TraderWorker._as_utc(now).timestamp())
        next_epoch = ((epoch // seconds) + 1) * seconds
        return datetime.fromtimestamp(next_epoch, tz=timezone.utc)

    @staticmethod
    def _to_datetime(value) -> datetime:
        if isinstance(value, pd.Timestamp):
            result = value.to_pydatetime()
        elif isinstance(value, datetime):
            result = value
        else:
            result = pd.Timestamp(value).to_pydatetime()
        if result.tzinfo is None:
            return result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def ensure_strategy_accounts(
    session: Session,
    experiment: Experiment,
    strategy_codes: tuple[str, ...] = ACTIVE_STRATEGY_CODES,
) -> list[StrategyAccount]:
    existing = {
        row.strategy_code: row
        for row in session.scalars(
            select(StrategyAccount).where(StrategyAccount.experiment_id == experiment.id)
        )
    }
    for code in strategy_codes:
        if code in existing:
            existing[code].display_name = STRATEGY_DISPLAY_NAMES[code]
            existing[code].stop_management_mode = (
                "TREND_FOLLOWER"
                if code == LARRY_WILLIAMS_91_TREND_FOLLOWER
                else "CLASSIC"
                if code in EMA9_CLASSIC_STRATEGY_CODES
                else "AI_DYNAMIC"
                if code == AI_PATTERN_TRADER
                else "SELECTOR_DYNAMIC"
                if code == ADAPTIVE_STRATEGY_SELECTOR
                else "N/A"
            )
            if code == AI_PATTERN_TRADER:
                existing[code].ai_mode = get_settings().ai_pattern_mode
                existing[code].ai_model_version = "AI-PATTERN-v1"
            continue
        copy_legacy_hybrid = code == CURRENT_HYBRID
        account = StrategyAccount(
            experiment_id=experiment.id,
            strategy_code=code,
            display_name=STRATEGY_DISPLAY_NAMES[code],
            status="ACTIVE",
            initial_capital=experiment.initial_capital,
            cash_balance=(
                experiment.cash_balance if copy_legacy_hybrid else experiment.initial_capital
            ),
            asset_quantity=(experiment.asset_quantity if copy_legacy_hybrid else 0.0),
            average_entry_price=(experiment.average_entry_price if copy_legacy_hybrid else None),
            entry_market_price=(experiment.entry_market_price if copy_legacy_hybrid else None),
            entry_execution_price=(
                experiment.entry_execution_price if copy_legacy_hybrid else None
            ),
            entry_fee_paid=(experiment.entry_fee_paid if copy_legacy_hybrid else 0.0),
            entry_time=(experiment.entry_time if copy_legacy_hybrid else None),
            initial_risk_per_unit=(
                experiment.initial_risk_per_unit if copy_legacy_hybrid else None
            ),
            highest_price_since_entry=(
                experiment.highest_price_since_entry if copy_legacy_hybrid else None
            ),
            stop_loss_price=(experiment.stop_loss_price if copy_legacy_hybrid else None),
            take_profit_price=(experiment.take_profit_price if copy_legacy_hybrid else None),
            trailing_stop_price=(experiment.trailing_stop_price if copy_legacy_hybrid else None),
            break_even_activated=(experiment.break_even_activated if copy_legacy_hybrid else False),
            last_atr_14=(experiment.last_atr_14 if copy_legacy_hybrid else None),
            total_fees=(experiment.total_fees if copy_legacy_hybrid else 0.0),
            total_spread_cost=(experiment.total_spread_cost if copy_legacy_hybrid else 0.0),
            total_slippage_cost=(experiment.total_slippage_cost if copy_legacy_hybrid else 0.0),
            realized_pnl=(experiment.realized_pnl if copy_legacy_hybrid else 0.0),
            final_capital=(experiment.final_capital if copy_legacy_hybrid else None),
            max_equity=(
                experiment.max_equity if copy_legacy_hybrid else experiment.initial_capital
            ),
            max_drawdown_pct=(experiment.max_drawdown_pct if copy_legacy_hybrid else 0.0),
            consecutive_losses=(experiment.consecutive_losses if copy_legacy_hybrid else 0),
            cooldown_until=(experiment.cooldown_until if copy_legacy_hybrid else None),
            setup_status="IDLE" if code in EMA9_STRATEGY_CODES or code == STORMER_FILHA_MAL_CRIADA else "N/A",
            stop_management_mode=(
                "TREND_FOLLOWER"
                if code == LARRY_WILLIAMS_91_TREND_FOLLOWER
                else "CLASSIC"
                if code in EMA9_CLASSIC_STRATEGY_CODES
                else "AI_DYNAMIC"
                if code == AI_PATTERN_TRADER
                else "SELECTOR_DYNAMIC"
                if code == ADAPTIVE_STRATEGY_SELECTOR
                else "N/A"
            ),
            ai_mode=(get_settings().ai_pattern_mode if code == AI_PATTERN_TRADER else None),
            ai_model_version=("AI-PATTERN-v1" if code == AI_PATTERN_TRADER else None),
            ai_risk_status=("LEARNING" if code == AI_PATTERN_TRADER else None),
            ai_risk_reason=(
                "Waiting for the first autonomous pattern analysis."
                if code == AI_PATTERN_TRADER
                else None
            ),
            selector_model_version=(
                get_settings().selector_model_version
                if code == ADAPTIVE_STRATEGY_SELECTOR
                else None
            ),
            selector_market_regime=(
                "UNDEFINED" if code == ADAPTIVE_STRATEGY_SELECTOR else None
            ),
        )
        session.add(account)
        existing[code] = account
    session.flush()
    return [existing[code] for code in strategy_codes]


def create_experiment_record(
    market: str,
    execution_timeframe: str,
    trend_timeframe: str,
    duration_hours: float,
    initial_capital: float,
    settings: Settings | None = None,
    trading_profile: str = DEFAULT_TRADING_PROFILE,
) -> Experiment:
    cfg = settings or get_settings()
    started_at = datetime.now(timezone.utc)
    return Experiment(
        id=str(uuid4()),
        market=market,
        trading_profile=trading_profile,
        execution_timeframe=execution_timeframe,
        trend_timeframe=trend_timeframe,
        duration_hours=duration_hours,
        status="RUNNING",
        started_at=started_at,
        scheduled_end_at=started_at + timedelta(hours=duration_hours),
        next_analysis_at=started_at,
        initial_capital=initial_capital,
        cash_balance=initial_capital,
        asset_quantity=0.0,
        entry_fee_paid=0.0,
        break_even_activated=False,
        vip_level=cfg.vip_level,
        maker_fee_rate=cfg.effective_default_maker_fee_rate,
        taker_fee_rate=cfg.effective_default_taker_fee_rate,
        fee_source="MEXC_API_CONFIG" + ("_MX_DISCOUNT" if cfg.mx_fee_discount_enabled else ""),
        last_spread_rate=cfg.fallback_spread_rate,
        average_spread_rate=0.0,
        spread_observations=0,
        total_fees=0.0,
        total_spread_cost=0.0,
        total_slippage_cost=0.0,
        realized_pnl=0.0,
        max_equity=initial_capital,
        max_drawdown_pct=0.0,
        consecutive_losses=0,
        model_name=(
            "Adaptive selector + XGBoost + EMA crossover/pullback + Larry Williams intraday"
        ),
        model_version="5.0",
        recovery_status="IDLE",
        recovered_candle_count=0,
        recovered_trade_count=0,
    )
