from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable

import numpy as np
import pandas as pd

from .risk_manager import PositionState, RiskManager


@dataclass
class TradeRecord:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    direction: int
    shares: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    exit_reason: str
    holding_days: int


class Backtester:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.risk = RiskManager(settings)

    def _autocorr(self, values: list[float] | pd.Series, lag: int = 1) -> float:
        x = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy(dtype=float)
        if lag <= 0 or len(x) <= lag:
            return float("nan")
        x0 = x[:-lag]
        x1 = x[lag:]
        if np.std(x0) == 0 or np.std(x1) == 0:
            return float("nan")
        return float(np.corrcoef(x0, x1)[0, 1])

    def _durbin_watson(self, values: list[float] | pd.Series) -> float:
        x = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy(dtype=float)
        if len(x) < 2:
            return float("nan")
        resid = x - np.mean(x)
        denom = np.sum(resid**2)
        if denom == 0:
            return float("nan")
        return float(np.sum(np.diff(resid) ** 2) / denom)

    def _de_risk_config(self) -> dict[str, Any]:
        return dict(self.settings.get("validation", {}).get("de_risk", {}))

    def _daily_cost(self, value: float, is_entry: bool) -> float:
        commission = value * float(self.settings["trading"]["commission_rate"])
        slippage = value * float(self.settings["trading"]["slippage"])
        tax = value * float(self.settings["trading"]["tax_rate"]) if not is_entry else 0.0
        return commission + slippage + tax

    def run(self, data: pd.DataFrame) -> dict[str, Any]:
        if "symbol" not in data.columns:
            data = data.assign(symbol="UNKNOWN")
        data = data.sort_values(["date", "symbol"]).reset_index(drop=True)
        data["date"] = pd.to_datetime(data["date"])

        dates = sorted(data["date"].dropna().unique())
        grouped = {symbol: frame.set_index("date").sort_index() for symbol, frame in data.groupby("symbol")}

        cash = float(self.settings["trading"]["initial_capital"])
        start_capital = cash
        positions: dict[str, PositionState] = {}
        trades: list[TradeRecord] = []
        equity_curve: list[dict[str, Any]] = []
        daily_returns: list[float] = []
        consecutive_losses = 0
        peak_equity = cash
        positions_by_industry: dict[str, int] = {}
        de_risk_cfg = self._de_risk_config()
        de_risk_window = int(de_risk_cfg.get("window_days", 60))
        de_risk_dw_lower = float(de_risk_cfg.get("dw_lower", 1.3))
        de_risk_dw_upper = float(de_risk_cfg.get("dw_upper", 2.7))
        de_risk_acf1_abs = float(de_risk_cfg.get("acf1_abs_threshold", 0.3))
        de_risk_streak_required = int(de_risk_cfg.get("anomaly_streak_required", 3))
        de_risk_cooldown_days = int(de_risk_cfg.get("cooldown_days", 10))
        de_risk_position_multiplier = float(de_risk_cfg.get("position_multiplier", 0.5))
        de_risk_max_positions_multiplier = float(de_risk_cfg.get("max_positions_multiplier", 0.5))
        use_strategy_exit = bool(
            self.settings.get("strategy", {}).get(
                "use_strategy_exit",
                self.settings.get("trading", {}).get("use_strategy_exit", False),
            )
        )
        risk_cfg = self.settings.get("risk", {})
        dd_soft_limit = float(risk_cfg.get("drawdown_soft_limit", 0.0) or 0.0)
        dd_hard_limit = float(risk_cfg.get("drawdown_hard_limit", 0.0) or 0.0)
        dd_cooldown_days = int(risk_cfg.get("drawdown_cooldown_days", 0) or 0)
        dd_position_multiplier = float(risk_cfg.get("drawdown_position_multiplier", 1.0))
        dd_max_positions_multiplier = float(risk_cfg.get("drawdown_max_positions_multiplier", 1.0))
        dd_block_new_entries = bool(risk_cfg.get("drawdown_block_new_entries", True))
        dd_hard_liquidate = bool(risk_cfg.get("drawdown_hard_liquidate", False))
        de_risk_events = 0
        drawdown_guard_events = 0
        drawdown_hard_events = 0
        anomaly_streak = 0
        cooldown_remaining = 0
        drawdown_cooldown_remaining = 0

        prev_day_rows: list[tuple[str, pd.Series]] = []

        for current_date in dates:
            current_date = pd.Timestamp(current_date)
            day_rows = []
            for symbol, frame in grouped.items():
                if current_date not in frame.index:
                    continue
                row = frame.loc[current_date]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[-1]
                day_rows.append((symbol, row))

            base_max_positions = int(self.settings["risk"]["max_positions"])
            current_position_multiplier = 1.0
            current_max_positions = base_max_positions
            current_dw = float("nan")
            current_acf1 = float("nan")
            de_risk_active = cooldown_remaining > 0

            if len(daily_returns) >= de_risk_window:
                recent_returns = daily_returns[-de_risk_window:]
                current_dw = self._durbin_watson(recent_returns)
                current_acf1 = self._autocorr(recent_returns, lag=1)
                anomaly_now = (
                    (not np.isnan(current_dw) and (current_dw < de_risk_dw_lower or current_dw > de_risk_dw_upper))
                    or (not np.isnan(current_acf1) and abs(current_acf1) > de_risk_acf1_abs)
                )
                anomaly_streak = anomaly_streak + 1 if anomaly_now else 0
                if cooldown_remaining <= 0 and anomaly_streak >= de_risk_streak_required:
                    cooldown_remaining = de_risk_cooldown_days
                    de_risk_events += 1
                    de_risk_active = True
                    anomaly_streak = 0

            if cooldown_remaining > 0:
                current_position_multiplier = de_risk_position_multiplier
                current_max_positions = max(1, int(np.floor(base_max_positions * de_risk_max_positions_multiplier)))
            else:
                current_position_multiplier = 1.0
                current_max_positions = base_max_positions

            pre_equity = cash
            for symbol, pos in positions.items():
                today_row = dict(day_rows).get(symbol)
                if today_row is None:
                    continue
                price = float(today_row["close"])
                if pos.direction >= 0:
                    pre_equity += pos.shares * price
                else:
                    pre_equity += pos.shares * (2 * pos.entry_price - price)
            pre_drawdown = (peak_equity - pre_equity) / peak_equity if peak_equity else 0.0
            drawdown_guard_active = drawdown_cooldown_remaining > 0
            hard_drawdown_active = dd_hard_limit > 0 and pre_drawdown >= dd_hard_limit
            if dd_soft_limit > 0 and pre_drawdown >= dd_soft_limit and drawdown_cooldown_remaining <= 0:
                drawdown_cooldown_remaining = dd_cooldown_days
                drawdown_guard_events += 1
                drawdown_guard_active = True
            if hard_drawdown_active:
                drawdown_guard_active = True
                drawdown_hard_events += 1
                if dd_cooldown_days > 0:
                    drawdown_cooldown_remaining = max(drawdown_cooldown_remaining, dd_cooldown_days)
            if drawdown_guard_active:
                current_position_multiplier *= dd_position_multiplier
                current_max_positions = max(1, int(np.floor(current_max_positions * dd_max_positions_multiplier)))

            # Update existing positions first.
            realized_pnl = 0.0
            prev_day_signal_rows = {symbol: row for symbol, row in prev_day_rows}
            for symbol, pos in list(positions.items()):
                frame = grouped.get(symbol)
                if frame is None or current_date not in frame.index:
                    continue
                bar = frame.loc[current_date]
                if isinstance(bar, pd.DataFrame):
                    bar = bar.iloc[-1]
                pos.holding_days += 1
                atr_value = float(bar.get("atr_14", np.nan))
                if not np.isnan(atr_value):
                    self.risk.update_trailing_stop(pos, float(bar["high"]), float(bar["low"]), atr_value)
                should_exit, reason = self.risk.should_exit(pos, bar)
                signal_row = prev_day_signal_rows.get(symbol)
                if use_strategy_exit and not should_exit and signal_row is not None:
                    exit_signal = int(signal_row.get("exit_signal", 0))
                    if pos.direction >= 0 and exit_signal < 0:
                        should_exit, reason = True, "strategy_exit"
                    elif pos.direction < 0 and exit_signal > 0:
                        should_exit, reason = True, "strategy_exit"
                if dd_hard_liquidate and hard_drawdown_active and not should_exit:
                    should_exit, reason = True, "max_drawdown_exit"
                if should_exit:
                    exit_price = float(bar["close"])
                    if pos.direction >= 0:
                        exit_value = exit_price * pos.shares
                        gross = (exit_price - pos.entry_price) * pos.shares
                    else:
                        exit_value = exit_price * pos.shares
                        gross = (pos.entry_price - exit_price) * pos.shares
                    costs = self._daily_cost(exit_value, is_entry=False)
                    net = gross - costs
                    cash += exit_value - costs if pos.direction >= 0 else (pos.entry_price * pos.shares + net)
                    realized_pnl += net
                    trades.append(
                        TradeRecord(
                            symbol=symbol,
                            entry_date=pos.entry_date,
                            exit_date=current_date,
                            direction=pos.direction,
                            shares=pos.shares,
                            entry_price=pos.entry_price,
                            exit_price=exit_price,
                            gross_pnl=gross,
                            net_pnl=net,
                            exit_reason=reason,
                            holding_days=pos.holding_days,
                        )
                    )
                    if net < 0:
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0
                    exit_industry = str(bar.get("industry", "Unknown"))
                    if exit_industry in positions_by_industry:
                        positions_by_industry[exit_industry] = max(0, positions_by_industry[exit_industry] - 1)
                    del positions[symbol]

            # Open new positions using the previous trading day's signal.
            max_positions_per_industry = int(self.settings.get("validation", {}).get("max_positions_per_industry", 0) or 0)
            opening_candidates = [
                (symbol, row)
                for symbol, row in prev_day_rows
                if int(row.get("signal", 0)) == 1
            ]
            opening_candidates.sort(
                key=lambda item: (
                    -float(item[1].get("strategy_score", 0.0)),
                    -float(item[1].get("y_prob", 0.0)),
                    -float(item[1].get("template_score", 0.0)),
                    -float(item[1].get("pattern_score", 0.0)),
                    -float(item[1].get("feature_score", 0.0)),
                    str(item[0]),
                )
            )

            for symbol, row in opening_candidates:
                if dd_block_new_entries and drawdown_guard_active:
                    break
                if symbol in positions:
                    continue
                if len(positions) >= current_max_positions:
                    break
                consecutive_loss_limit = int(self.settings["risk"].get("consecutive_loss_limit", 0))
                if consecutive_loss_limit > 0 and consecutive_losses >= consecutive_loss_limit:
                    continue
                industry = str(row.get("industry", "Unknown"))
                if max_positions_per_industry > 0 and positions_by_industry.get(industry, 0) >= max_positions_per_industry:
                    continue
                signal = int(row.get("signal", 0))
                atr_value = float(row.get("atr_14", np.nan))
                today_row = dict(day_rows).get(symbol)
                if today_row is None:
                    continue
                entry_price = float(today_row["open"]) if "open" in today_row and pd.notna(today_row["open"]) else float(today_row["close"])
                shares = self.risk.position_size(cash, atr_value, entry_price, size_multiplier=current_position_multiplier)
                if shares <= 0:
                    continue
                notional = entry_price * shares
                if notional > cash:
                    continue
                stop_loss, take_profit, trailing_stop = self.risk.initial_stops(entry_price, atr_value, direction=signal)
                if signal < 0:
                    stop_loss, take_profit, trailing_stop = self.risk.initial_stops(entry_price, atr_value, direction=-1)
                cost = self._daily_cost(notional, is_entry=True)
                cash -= notional + cost
                positions[symbol] = PositionState(
                    symbol=symbol,
                    direction=signal,
                    entry_date=current_date,
                    entry_price=entry_price,
                    shares=shares,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    trailing_stop=trailing_stop,
                    peak_price=entry_price,
                    trough_price=entry_price,
                )
                positions_by_industry[industry] = positions_by_industry.get(industry, 0) + 1

            prev_day_rows = day_rows

            equity = cash
            for symbol, pos in positions.items():
                frame = grouped.get(symbol)
                if frame is None or current_date not in frame.index:
                    continue
                bar = frame.loc[current_date]
                if isinstance(bar, pd.DataFrame):
                    bar = bar.iloc[-1]
                price = float(bar["close"])
                if pos.direction >= 0:
                    equity += pos.shares * price
                else:
                    equity += pos.shares * (2 * pos.entry_price - price)
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity if peak_equity else 0.0
            if cooldown_remaining > 0:
                cooldown_remaining = max(0, cooldown_remaining - 1)
            if drawdown_cooldown_remaining > 0:
                drawdown_cooldown_remaining = max(0, drawdown_cooldown_remaining - 1)

            equity_curve.append(
                {
                    "date": current_date,
                    "equity": equity,
                    "cash": cash,
                    "open_positions": len(positions),
                    "drawdown": drawdown,
                    "realized_pnl": realized_pnl,
                    "risk_multiplier": current_position_multiplier,
                    "risk_de_risk_active": int(de_risk_active),
                    "risk_drawdown_guard_active": int(drawdown_guard_active),
                    "risk_pre_drawdown": pre_drawdown,
                    "risk_dw_60d": current_dw,
                    "risk_acf1_60d": current_acf1,
                    "risk_cooldown_remaining": cooldown_remaining,
                    "risk_drawdown_cooldown_remaining": drawdown_cooldown_remaining,
                }
            )
            if len(equity_curve) > 1:
                prev = equity_curve[-2]["equity"]
                daily_returns.append((equity - prev) / prev if prev else 0.0)

        equity_df = pd.DataFrame(equity_curve)
        trade_df = pd.DataFrame([asdict(t) for t in trades])
        if not trade_df.empty:
            trade_df["win"] = trade_df["net_pnl"] > 0
        return {
            "equity_curve": equity_df,
            "trade_log": trade_df,
            "final_equity": float(equity_df["equity"].iloc[-1]) if not equity_df.empty else start_capital,
            "daily_returns": pd.Series(daily_returns, name="daily_return"),
            "start_capital": start_capital,
            "de_risk_events": de_risk_events,
            "drawdown_guard_events": drawdown_guard_events,
            "drawdown_hard_events": drawdown_hard_events,
        }

    def performance_metrics(self, result: dict[str, Any]) -> dict[str, float]:
        equity = result["equity_curve"]
        trade_log = result["trade_log"]
        start_capital = float(result["start_capital"])
        final_equity = float(result["final_equity"])
        days = max(len(equity), 1)
        total_return = final_equity / start_capital - 1
        cagr = (final_equity / start_capital) ** (252 / days) - 1 if days > 1 else 0.0
        daily = result["daily_returns"]
        daily_std = float(daily.std()) if len(daily) > 1 else 0.0
        sharpe = float(np.sqrt(252) * daily.mean() / daily_std) if len(daily) > 1 and daily_std > 0 else np.nan
        max_drawdown = float(equity["drawdown"].max()) if not equity.empty else 0.0
        win_rate = float(trade_log["win"].mean()) if not trade_log.empty else 0.0
        profit_factor = float(trade_log.loc[trade_log["net_pnl"] > 0, "net_pnl"].sum() / abs(trade_log.loc[trade_log["net_pnl"] < 0, "net_pnl"].sum())) if not trade_log.empty and (trade_log["net_pnl"] < 0).any() else np.nan
        return {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "trades": float(len(trade_log)),
            "drawdown_guard_events": float(result.get("drawdown_guard_events", 0)),
            "drawdown_hard_events": float(result.get("drawdown_hard_events", 0)),
        }
