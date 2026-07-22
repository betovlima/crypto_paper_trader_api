from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .config import Settings
from .execution_costs import ExecutionCosts
from .models import (
    Experiment,
    StrategyAccount,
    StrategyEquitySnapshot,
    StrategySimulatedTrade,
)
from .strategy_codes import (
    ADAPTIVE_STRATEGY_SELECTOR,
    DYNAMIC_RISK_STRATEGY_CODES,
    EMA9_STRATEGY_CODES,
    SETUP_STATE_STRATEGY_CODES,
)
from .trading_profiles import TradingProfile


class MultiStrategyPaperBroker:
    """Execute simulated Spot trades for independent strategy accounts.

    Strategy rules decide *whether* and *where* to trade. This broker applies the
    real-world accounting effects afterwards: best ask/bid, slippage and exchange fees.
    None of these costs may veto a valid strategy signal or move a technical stop.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def update_dynamic_risk_levels(
        self,
        account: StrategyAccount,
        market_high: float,
        atr: float,
        costs: ExecutionCosts,
        profile: TradingProfile,
    ) -> None:
        del costs  # Costs are accounting-only and must not alter technical risk levels.
        if not account.has_open_position:
            return
        if account.strategy_code not in DYNAMIC_RISK_STRATEGY_CODES:
            return

        entry = float(account.entry_execution_price or account.average_entry_price or 0.0)
        if entry <= 0:
            return

        highest = max(account.highest_price_since_entry or market_high, market_high)
        account.highest_price_since_entry = highest
        initial_risk = float(account.initial_risk_per_unit or 0.0)
        if initial_risk <= 0 or atr <= 0:
            return

        favorable_move = highest - entry
        if favorable_move >= profile.trailing_activation_r * initial_risk:
            candidate = highest - profile.trailing_atr_multiplier * atr
            account.trailing_stop_price = max(account.trailing_stop_price or candidate, candidate)

        if favorable_move >= profile.break_even_activation_r * initial_risk:
            # Technical break-even: the strategy's executed entry price, without fee adjustment.
            account.stop_loss_price = max(account.stop_loss_price or entry, entry)
            account.break_even_activated = True

    def buy(
        self,
        session: Session,
        experiment: Experiment,
        account: StrategyAccount,
        mid_market_price: float,
        best_ask: float,
        atr: float,
        costs: ExecutionCosts,
        executed_at: datetime,
        reason: str,
        decision_id: int | None,
        entry_candle_timestamp: datetime | None = None,
        stop_override: float | None = None,
        take_profit_override: float | None = None,
        profile: TradingProfile | None = None,
        is_recovered: bool = False,
        recovery_note: str | None = None,
    ) -> StrategySimulatedTrade:
        if account.has_open_position:
            raise ValueError("Cannot buy while this strategy already has an open position.")
        if best_ask <= 0 or mid_market_price <= 0:
            raise ValueError("Invalid simulated market price.")

        execution_price = best_ask * (1 + costs.slippage_rate)
        active_profile = profile
        allocation = (
            active_profile.position_allocation
            if active_profile
            else self.settings.position_allocation
        )
        available_budget = account.cash_balance * allocation
        quantity = available_budget / (execution_price * (1 + costs.taker_fee_rate))
        if experiment.min_market_amount and quantity < experiment.min_market_amount:
            raise ValueError(
                f"Simulated quantity {quantity:.12f} is below the market minimum "
                f"{experiment.min_market_amount:.12f}."
            )

        gross_notional = quantity * execution_price
        fee = gross_notional * costs.taker_fee_rate
        total_cash_cost = gross_notional + fee
        spread_per_unit = max(best_ask - mid_market_price, 0.0)
        slippage_per_unit = max(execution_price - best_ask, 0.0)
        spread_cost = quantity * spread_per_unit
        slippage_cost = quantity * slippage_per_unit
        if quantity <= 0 or total_cash_cost > account.cash_balance + 1e-8:
            raise ValueError("Insufficient simulated cash for BUY.")

        if stop_override is not None:
            stop_loss_price = float(stop_override)
        else:
            stop_atr_multiplier = (
                active_profile.stop_atr_multiplier
                if active_profile
                else self.settings.stop_atr_multiplier
            )
            stop_min_pct = (
                active_profile.stop_loss_min_pct
                if active_profile
                else self.settings.stop_loss_min_pct
            )
            stop_max_pct = (
                active_profile.stop_loss_max_pct
                if active_profile
                else self.settings.stop_loss_max_pct
            )
            raw_stop_pct = stop_atr_multiplier * atr / max(mid_market_price, 1e-9)
            stop_pct = min(max(raw_stop_pct, stop_min_pct), stop_max_pct)
            stop_loss_price = execution_price * (1 - stop_pct)

        if stop_loss_price >= execution_price:
            raise ValueError("The initial stop must be below the executed entry price.")

        if take_profit_override is not None:
            take_profit_price = float(take_profit_override)
        elif account.strategy_code in DYNAMIC_RISK_STRATEGY_CODES:
            reward_risk_ratio = (
                active_profile.reward_risk_ratio
                if active_profile
                else self.settings.reward_risk_ratio
            )
            take_profit_atr_multiplier = (
                active_profile.take_profit_atr_multiplier
                if active_profile
                else self.settings.take_profit_atr_multiplier
            )
            technical_risk = max(execution_price - stop_loss_price, 0.0)
            atr_target = take_profit_atr_multiplier * atr
            take_profit_price = execution_price + max(
                technical_risk * reward_risk_ratio,
                atr_target,
            )
        else:
            # Traditional Larry Williams 9.1 exits below EMA 9 or at the setup stop.
            take_profit_price = None

        account.cash_balance -= total_cash_cost
        account.asset_quantity = quantity
        account.average_entry_price = execution_price
        account.entry_market_price = mid_market_price
        account.entry_execution_price = execution_price
        account.entry_fee_paid = fee
        account.entry_time = executed_at
        account.entry_candle_timestamp = entry_candle_timestamp or executed_at
        account.initial_risk_per_unit = max(execution_price - stop_loss_price, 0.0)
        account.break_even_activated = False
        account.highest_price_since_entry = mid_market_price
        account.stop_loss_price = stop_loss_price
        account.take_profit_price = take_profit_price
        account.trailing_stop_price = None
        account.total_fees += fee
        account.total_spread_cost += spread_cost
        account.total_slippage_cost += slippage_cost
        if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR:
            account.selector_position_strategy_code = account.selector_selected_strategy
            account.selector_position_strategy_name = (
                account.selector_active_strategy_name or account.selector_selected_strategy
            )
            account.selector_position_strategy_origin = account.selector_strategy_origin
            account.selector_position_strategy_spec_json = account.selector_strategy_spec_json
            account.selector_position_validation_score = account.selector_validation_score
            account.selector_position_opened_at = executed_at
        if account.strategy_code in SETUP_STATE_STRATEGY_CODES:
            account.setup_status = "IN_POSITION"
            account.exit_trigger_price = None
            account.exit_trigger_candle_timestamp = None
            account.exit_trigger_candle_low = None
            account.last_setup_event = "BREAKOUT_ENTRY"
            account.last_setup_event_reason = reason

        equity = account.cash_balance + quantity * mid_market_price
        trade = StrategySimulatedTrade(
            experiment_id=experiment.id,
            strategy_account_id=account.id,
            strategy_code=account.strategy_code,
            selected_strategy_code=(
                account.selector_selected_strategy
                if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR
                else None
            ),
            decision_id=decision_id,
            executed_at=executed_at,
            entry_candle_timestamp=entry_candle_timestamp or executed_at,
            side="BUY",
            order_role="TAKER",
            market_price=mid_market_price,
            execution_price=execution_price,
            quantity=quantity,
            gross_notional=gross_notional,
            fee_rate=costs.taker_fee_rate,
            fee=fee,
            spread_rate=costs.spread_rate,
            spread_cost=spread_cost,
            slippage_rate=costs.slippage_rate,
            slippage_cost=slippage_cost,
            total_transaction_cost=fee + spread_cost + slippage_cost,
            realized_pnl=None,
            gross_pnl_before_exit_costs=None,
            cash_after=account.cash_balance,
            asset_quantity_after=account.asset_quantity,
            equity_after=equity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_stop_price=None,
            reason=reason,
            is_recovered=is_recovered,
            recovery_note=recovery_note,
        )
        session.add(trade)
        session.flush()
        return trade

    def sell(
        self,
        session: Session,
        experiment: Experiment,
        account: StrategyAccount,
        mid_market_price: float,
        best_bid: float,
        costs: ExecutionCosts,
        executed_at: datetime,
        reason: str,
        decision_id: int | None,
        profile: TradingProfile | None = None,
        is_recovered: bool = False,
        recovery_note: str | None = None,
    ) -> StrategySimulatedTrade:
        if not account.has_open_position:
            raise ValueError("Cannot sell without an open simulated position.")
        if best_bid <= 0 or mid_market_price <= 0:
            raise ValueError("Invalid simulated market price.")

        quantity = account.asset_quantity
        execution_price = max(best_bid * (1 - costs.slippage_rate), 0.0)
        gross_notional = quantity * execution_price
        fee = gross_notional * costs.taker_fee_rate
        net_proceeds = gross_notional - fee
        spread_per_unit = max(mid_market_price - best_bid, 0.0)
        slippage_per_unit = max(best_bid - execution_price, 0.0)
        spread_cost = quantity * spread_per_unit
        slippage_cost = quantity * slippage_per_unit

        entry_market_price = float(
            account.entry_market_price
            or account.entry_execution_price
            or account.average_entry_price
            or 0.0
        )
        entry_execution_price = float(
            account.entry_execution_price or account.average_entry_price or 0.0
        )
        entry_notional = quantity * entry_execution_price
        entry_fee = float(account.entry_fee_paid or 0.0)
        # Gross P&L measures the setup's market move before all execution friction.
        gross_pnl_before_exit_costs = quantity * (mid_market_price - entry_market_price)
        # Net P&L uses actual bid/ask, slippage and both exchange fees.
        realized_pnl = net_proceeds - entry_notional - entry_fee

        stop_loss_price = account.stop_loss_price
        take_profit_price = account.take_profit_price
        trailing_stop_price = account.trailing_stop_price
        selected_strategy_code = (
            account.selector_position_strategy_code or account.selector_selected_strategy
            if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR
            else None
        )

        account.cash_balance += net_proceeds
        account.asset_quantity = 0.0
        account.realized_pnl += realized_pnl
        account.total_fees += fee
        account.total_spread_cost += spread_cost
        account.total_slippage_cost += slippage_cost
        if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR:
            account.selector_last_reward = (
                realized_pnl / account.initial_capital if account.initial_capital > 0 else 0.0
            )
            account.selector_last_completed_at = executed_at

        if realized_pnl < 0:
            account.consecutive_losses += 1
            max_losses = (
                profile.max_consecutive_losses
                if profile
                else self.settings.max_consecutive_losses
            )
            cooldown_minutes = (
                profile.cooldown_minutes if profile else self.settings.cooldown_minutes
            )
            if account.consecutive_losses >= max_losses:
                account.cooldown_until = executed_at + timedelta(minutes=cooldown_minutes)
        else:
            account.consecutive_losses = 0
            account.cooldown_until = None

        account.average_entry_price = None
        account.entry_market_price = None
        account.entry_execution_price = None
        account.entry_fee_paid = 0.0
        account.entry_time = None
        account.entry_candle_timestamp = None
        account.initial_risk_per_unit = None
        account.break_even_activated = False
        account.highest_price_since_entry = None
        account.stop_loss_price = None
        account.take_profit_price = None
        account.trailing_stop_price = None
        if account.strategy_code in SETUP_STATE_STRATEGY_CODES:
            account.setup_status = "IDLE"
            account.setup_candle_timestamp = None
            account.setup_candle_high = None
            account.setup_candle_low = None
            account.entry_trigger_price = None
            account.initial_setup_stop_price = None
            account.setup_target_price = None
            account.setup_cancel_reason = None
            account.exit_trigger_price = None
            account.exit_trigger_candle_timestamp = None
            account.exit_trigger_candle_low = None
            account.last_setup_event = "POSITION_CLOSED"
            account.last_setup_event_reason = reason

        trade = StrategySimulatedTrade(
            experiment_id=experiment.id,
            strategy_account_id=account.id,
            strategy_code=account.strategy_code,
            selected_strategy_code=selected_strategy_code,
            decision_id=decision_id,
            executed_at=executed_at,
            side="SELL",
            order_role="TAKER",
            market_price=mid_market_price,
            execution_price=execution_price,
            quantity=quantity,
            gross_notional=gross_notional,
            fee_rate=costs.taker_fee_rate,
            fee=fee,
            spread_rate=costs.spread_rate,
            spread_cost=spread_cost,
            slippage_rate=costs.slippage_rate,
            slippage_cost=slippage_cost,
            total_transaction_cost=fee + spread_cost + slippage_cost,
            realized_pnl=realized_pnl,
            gross_pnl_before_exit_costs=gross_pnl_before_exit_costs,
            cash_after=account.cash_balance,
            asset_quantity_after=0.0,
            equity_after=account.cash_balance,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_stop_price=trailing_stop_price,
            reason=reason,
            is_recovered=is_recovered,
            recovery_note=recovery_note,
        )
        session.add(trade)
        session.flush()
        if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR:
            account.selector_position_strategy_code = None
            account.selector_position_strategy_name = None
            account.selector_position_strategy_origin = None
            account.selector_position_strategy_spec_json = None
            account.selector_position_validation_score = None
            account.selector_position_opened_at = None
        return trade

    @staticmethod
    def record_equity(
        session: Session,
        experiment: Experiment,
        account: StrategyAccount,
        timestamp: datetime,
        mid_market_price: float,
        best_bid: float,
        costs: ExecutionCosts,
    ) -> StrategyEquitySnapshot:
        if account.has_open_position:
            liquidation_price = best_bid * (1 - costs.slippage_rate)
            position_value = account.asset_quantity * liquidation_price * (
                1 - costs.taker_fee_rate
            )
        else:
            position_value = 0.0
        total_equity = account.cash_balance + position_value
        account.max_equity = max(account.max_equity, total_equity)
        drawdown_pct = (
            total_equity / account.max_equity - 1 if account.max_equity > 0 else 0.0
        )
        account.max_drawdown_pct = min(account.max_drawdown_pct, drawdown_pct)

        snapshot = StrategyEquitySnapshot(
            experiment_id=experiment.id,
            strategy_account_id=account.id,
            strategy_code=account.strategy_code,
            timestamp=timestamp,
            market_price=mid_market_price,
            cash_balance=account.cash_balance,
            asset_quantity=account.asset_quantity,
            position_value=position_value,
            total_equity=total_equity,
            drawdown_pct=drawdown_pct,
            has_position=account.has_open_position,
        )
        session.add(snapshot)
        return snapshot
