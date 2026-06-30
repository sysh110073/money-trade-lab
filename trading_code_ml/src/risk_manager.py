from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class PositionState:
    symbol: str
    direction: int
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    stop_loss: float
    take_profit: float
    trailing_stop: float
    holding_days: int = 0
    peak_price: float = 0.0
    trough_price: float = 0.0


@dataclass
class PositionSizeResult:
    theoretical_shares: int
    volume_limited_shares: int
    cash_limited_shares: int
    shares: int
    notional: float
    blocked_reason: str = ""


def round_to_lot(shares: float, lot: int) -> int:
    if shares <= 0:
        return 0
    rounded = int(shares // lot) * lot
    return rounded if rounded >= lot else 0


def calculate_position_size(
    *,
    capital: float,
    price: float,
    atr_value: float,
    risk_pct: float,
    atr_multiplier: float,
    max_position_pct: float,
    min_trade_unit: int,
    cash: float | None = None,
    target_notional: float | None = None,
    max_notional: float = 0.0,
    volume: float = 0.0,
    max_volume_pct: float = 0.0,
    size_multiplier: float = 1.0,
) -> PositionSizeResult:
    if not np.isfinite(price) or price <= 0 or not np.isfinite(atr_value) or atr_value <= 0:
        return PositionSizeResult(0, 0, 0, 0, 0.0, "invalid_price_or_atr")

    lot = int(min_trade_unit)
    size_multiplier = max(float(size_multiplier), 0.0)
    risk_shares = (float(capital) * float(risk_pct)) / (float(atr_value) * float(atr_multiplier))
    position_shares = (float(capital) * float(max_position_pct)) / float(price)
    desired_notional = min(risk_shares * price, position_shares * price) * size_multiplier
    if target_notional is not None:
        desired_notional = min(desired_notional, float(target_notional))
    if max_notional > 0:
        desired_notional = min(desired_notional, float(max_notional))

    theoretical = round_to_lot(desired_notional / price, lot)
    volume_limited = theoretical
    blocked_reason = ""
    if max_volume_pct > 0:
        volume_limited = round_to_lot(float(volume) * float(max_volume_pct), lot)
        if volume_limited <= 0:
            blocked_reason = "low_volume"
    cash_limited = theoretical
    if cash is not None:
        cash_limited = round_to_lot(float(cash) / price, lot)

    shares = min(theoretical, volume_limited, cash_limited)
    if shares <= 0 and not blocked_reason:
        blocked_reason = "insufficient_cash_or_lot"
    return PositionSizeResult(
        theoretical_shares=theoretical,
        volume_limited_shares=volume_limited,
        cash_limited_shares=cash_limited,
        shares=shares,
        notional=shares * price,
        blocked_reason=blocked_reason,
    )


class RiskManager:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.risk_cfg = settings["risk"]
        self.trade_cfg = settings["trading"]

    def atr(self, df: pd.DataFrame, period: int | None = None) -> pd.Series:
        period = period or int(self.risk_cfg["atr_period"])
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    def round_lot(self, shares: float) -> int:
        return round_to_lot(shares, int(self.trade_cfg["min_trade_unit"]))

    def position_size(self, total_capital: float, atr_value: float, price: float, size_multiplier: float = 1.0) -> int:
        if np.isnan(atr_value) or atr_value <= 0 or price <= 0:
            return 0
        size_multiplier = max(float(size_multiplier), 0.0)
        result = calculate_position_size(
            capital=total_capital,
            price=price,
            atr_value=atr_value,
            risk_pct=float(self.risk_cfg["max_risk_per_trade"]),
            atr_multiplier=float(self.risk_cfg["atr_stop_multiplier"]),
            max_position_pct=float(self.risk_cfg["max_position_pct"]),
            min_trade_unit=int(self.trade_cfg["min_trade_unit"]),
            size_multiplier=size_multiplier,
        )
        return result.shares

    def initial_stops(self, entry_price: float, atr_value: float, direction: int = 1) -> tuple[float, float, float]:
        stop_distance = atr_value * float(self.risk_cfg["atr_stop_multiplier"])
        if direction >= 0:
            stop_loss = entry_price - stop_distance
            take_profit = entry_price * (1 + float(self.risk_cfg["take_profit_pct"]))
            trailing_stop = entry_price - stop_distance
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price * (1 - float(self.risk_cfg["take_profit_pct"]))
            trailing_stop = entry_price + stop_distance
        return stop_loss, take_profit, trailing_stop

    def update_trailing_stop(self, position: PositionState, current_high: float, current_low: float, atr_value: float) -> None:
        trigger = float(self.risk_cfg["trailing_stop_trigger"])
        trail_atr = float(self.risk_cfg["trailing_stop_atr"])
        if position.direction >= 0:
            position.peak_price = max(position.peak_price, current_high)
            if position.peak_price >= position.entry_price * (1 + trigger):
                position.trailing_stop = max(position.trailing_stop, position.peak_price - atr_value * trail_atr)
        else:
            position.trough_price = min(position.trough_price, current_low) if position.trough_price else current_low
            if position.trough_price <= position.entry_price * (1 - trigger):
                position.trailing_stop = min(position.trailing_stop, position.trough_price + atr_value * trail_atr)

    def should_exit(self, position: PositionState, bar: pd.Series) -> tuple[bool, str]:
        if position.direction >= 0:
            if bar["low"] <= position.stop_loss:
                return True, "stop_loss"
            if bar["high"] >= position.take_profit:
                return True, "take_profit"
            if bar["low"] <= position.trailing_stop:
                return True, "trailing_stop"
        else:
            if bar["high"] >= position.stop_loss:
                return True, "stop_loss"
            if bar["low"] <= position.take_profit:
                return True, "take_profit"
            if bar["high"] >= position.trailing_stop:
                return True, "trailing_stop"
        if position.holding_days >= int(self.trade_cfg["holding_period_max"]):
            return True, "time_exit"
        return False, ""
