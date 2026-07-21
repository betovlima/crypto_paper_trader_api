from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .config import Settings
from .execution_costs import ExecutionCosts
from .models import EquitySnapshot, Experiment, SimulatedTrade


class PaperBroker:
    """Executes simulated Spot trades only. No exchange order methods exist here."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def update_dynamic_risk_levels(
        self,
        experiment: Experiment,
        candle_high: float,
        atr: float,
        costs: ExecutionCosts,
    ) -> None:
        if not experiment.has_open_position or experiment.average_entry_price is None:
            return

        highest = max(experiment.highest_price_since_entry or candle_high, candle_high)
        experiment.highest_price_since_entry = highest
        initial_risk = float(experiment.initial_risk_per_unit or 0.0)
        if initial_risk <= 0:
            return

        entry = float(experiment.average_entry_price)
        favorable_move = highest - entry

        if favorable_move >= self.settings.trailing_activation_r * initial_risk:
            candidate = highest - self.settings.trailing_atr_multiplier * atr
            experiment.trailing_stop_price = max(
                experiment.trailing_stop_price or candidate,
                candidate,
            )

        if favorable_move >= self.settings.break_even_activation_r * initial_risk:
            impact = costs.exit_market_impact_rate
            denominator = max((1 - impact) * (1 - costs.taker_fee_rate), 1e-9)
            break_even_market_price = entry / denominator
            experiment.stop_loss_price = max(
                experiment.stop_loss_price or break_even_market_price,
                break_even_market_price,
            )
            experiment.break_even_activated = True

    def buy(
        self,
        session: Session,
        experiment: Experiment,
        market_price: float,
        atr: float,
        costs: ExecutionCosts,
        executed_at: datetime,
        reason: str,
        decision_id: int | None,
    ) -> SimulatedTrade:
        if experiment.has_open_position:
            raise ValueError("Cannot buy while a simulated position is already open.")

        spread_component = market_price * costs.half_spread_rate
        slippage_component = market_price * costs.slippage_rate
        execution_price = market_price + spread_component + slippage_component
        available_budget = experiment.cash_balance * self.settings.position_allocation
        quantity = available_budget / (execution_price * (1 + costs.taker_fee_rate))
        if experiment.min_market_amount and quantity < experiment.min_market_amount:
            raise ValueError(
                f"Simulated quantity {quantity:.12f} is below MEXC minimum "
                f"{experiment.min_market_amount:.12f}."
            )

        gross_notional = quantity * execution_price
        fee = gross_notional * costs.taker_fee_rate
        total_cost = gross_notional + fee
        spread_cost = quantity * spread_component
        slippage_cost = quantity * slippage_component
        if quantity <= 0 or total_cost > experiment.cash_balance + 1e-8:
            raise ValueError("Insufficient simulated cash for BUY.")

        average_entry_price = total_cost / quantity
        raw_stop_pct = self.settings.stop_atr_multiplier * atr / max(market_price, 1e-9)
        stop_pct = min(
            max(raw_stop_pct, self.settings.stop_loss_min_pct),
            self.settings.stop_loss_max_pct,
        )
        stop_loss_price = average_entry_price * (1 - stop_pct)
        atr_target_pct = self.settings.take_profit_atr_multiplier * atr / max(market_price, 1e-9)
        take_profit_pct = max(stop_pct * self.settings.reward_risk_ratio, atr_target_pct)
        take_profit_price = average_entry_price * (1 + take_profit_pct)

        experiment.cash_balance -= total_cost
        experiment.asset_quantity = quantity
        experiment.average_entry_price = average_entry_price
        experiment.entry_time = executed_at
        experiment.initial_risk_per_unit = average_entry_price - stop_loss_price
        experiment.break_even_activated = False
        experiment.highest_price_since_entry = market_price
        experiment.stop_loss_price = stop_loss_price
        experiment.take_profit_price = take_profit_price
        experiment.trailing_stop_price = None
        experiment.total_fees += fee
        experiment.total_spread_cost += spread_cost
        experiment.total_slippage_cost += slippage_cost

        equity = experiment.cash_balance + quantity * market_price
        trade = SimulatedTrade(
            experiment_id=experiment.id,
            decision_id=decision_id,
            executed_at=executed_at,
            side="BUY",
            order_role="TAKER",
            market_price=market_price,
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
            cash_after=experiment.cash_balance,
            asset_quantity_after=experiment.asset_quantity,
            equity_after=equity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_stop_price=None,
            reason=reason,
        )
        session.add(trade)
        session.flush()
        return trade

    def sell(
        self,
        session: Session,
        experiment: Experiment,
        market_price: float,
        costs: ExecutionCosts,
        executed_at: datetime,
        reason: str,
        decision_id: int | None,
    ) -> SimulatedTrade:
        if not experiment.has_open_position:
            raise ValueError("Cannot sell without a simulated open position.")

        quantity = experiment.asset_quantity
        spread_component = market_price * costs.half_spread_rate
        slippage_component = market_price * costs.slippage_rate
        execution_price = max(market_price - spread_component - slippage_component, 0.0)
        gross_notional = quantity * execution_price
        fee = gross_notional * costs.taker_fee_rate
        net_proceeds = gross_notional - fee
        spread_cost = quantity * spread_component
        slippage_cost = quantity * slippage_component
        cost_basis = quantity * float(experiment.average_entry_price or 0.0)
        gross_pnl_before_exit_costs = quantity * market_price - cost_basis
        realized_pnl = net_proceeds - cost_basis

        stop_loss_price = experiment.stop_loss_price
        take_profit_price = experiment.take_profit_price
        trailing_stop_price = experiment.trailing_stop_price

        experiment.cash_balance += net_proceeds
        experiment.asset_quantity = 0.0
        experiment.realized_pnl += realized_pnl
        experiment.total_fees += fee
        experiment.total_spread_cost += spread_cost
        experiment.total_slippage_cost += slippage_cost

        if realized_pnl < 0:
            experiment.consecutive_losses += 1
            if experiment.consecutive_losses >= self.settings.max_consecutive_losses:
                experiment.cooldown_until = executed_at + timedelta(
                    minutes=self.settings.cooldown_minutes
                )
        else:
            experiment.consecutive_losses = 0
            experiment.cooldown_until = None

        experiment.average_entry_price = None
        experiment.entry_time = None
        experiment.initial_risk_per_unit = None
        experiment.break_even_activated = False
        experiment.highest_price_since_entry = None
        experiment.stop_loss_price = None
        experiment.take_profit_price = None
        experiment.trailing_stop_price = None

        trade = SimulatedTrade(
            experiment_id=experiment.id,
            decision_id=decision_id,
            executed_at=executed_at,
            side="SELL",
            order_role="TAKER",
            market_price=market_price,
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
            cash_after=experiment.cash_balance,
            asset_quantity_after=0.0,
            equity_after=experiment.cash_balance,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_stop_price=trailing_stop_price,
            reason=reason,
        )
        session.add(trade)
        session.flush()
        return trade

    @staticmethod
    def record_equity(
        session: Session,
        experiment: Experiment,
        timestamp: datetime,
        market_price: float,
        costs: ExecutionCosts,
    ) -> EquitySnapshot:
        if experiment.has_open_position:
            liquidation_price = market_price * (1 - costs.exit_market_impact_rate)
            position_value = (
                experiment.asset_quantity * liquidation_price * (1 - costs.taker_fee_rate)
            )
        else:
            position_value = 0.0
        total_equity = experiment.cash_balance + position_value
        experiment.max_equity = max(experiment.max_equity, total_equity)
        drawdown_pct = (
            (total_equity / experiment.max_equity) - 1 if experiment.max_equity > 0 else 0.0
        )
        experiment.max_drawdown_pct = min(experiment.max_drawdown_pct, drawdown_pct)
        experiment.last_price = market_price

        snapshot = EquitySnapshot(
            experiment_id=experiment.id,
            timestamp=timestamp,
            market_price=market_price,
            cash_balance=experiment.cash_balance,
            asset_quantity=experiment.asset_quantity,
            position_value=position_value,
            total_equity=total_equity,
            drawdown_pct=drawdown_pct,
            has_position=experiment.has_open_position,
        )
        session.add(snapshot)
        return snapshot
