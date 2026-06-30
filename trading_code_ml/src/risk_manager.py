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
        lot = int(self.trade_cfg["min_trade_unit"])
        if shares <= 0:
            return 0
        rounded = int(shares // lot) * lot
        return rounded if rounded >= lot else 0

    def position_size(self, total_capital: float, atr_value: float, price: float, size_multiplier: float = 1.0) -> int:
        if np.isnan(atr_value) or atr_value <= 0 or price <= 0:
            return 0
        size_multiplier = max(float(size_multiplier), 0.0)
        max_risk = total_capital * float(self.risk_cfg["max_risk_per_trade"])
        raw_shares = max_risk / (atr_value * float(self.risk_cfg["atr_stop_multiplier"]))
        max_affordable = total_capital * float(self.risk_cfg["max_position_pct"]) / price
        shares = min(raw_shares, max_affordable) * size_multiplier
        return self.round_lot(shares)

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
