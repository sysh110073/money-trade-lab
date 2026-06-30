from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_daily_signals import (  # noqa: E402
    BEST_FILTERS,
    DEFAULT_RISK_FALLBACK,
    _merge_selected,
    _select_family_sleeves,
)
from run_cycle_strategy_wfa import (  # noqa: E402
    _apply_selected_strategies,
    _attach_cycles,
    _attach_forward_return,
    _load_data,
    _select_strategies,
)
from src.config import load_settings  # noqa: E402
from src.data_fetcher import DataFetcher  # noqa: E402
from src.risk_manager import calculate_position_size  # noqa: E402
from src.strategy_catalog import add_strategy_ranks, build_strategy_catalog  # noqa: E402


DEFAULT_DATA = ROOT.parent / "data" / "processed" / "all_features.csv"


@dataclass
class PortfolioPosition:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    stop_loss: float
    take_profit: float
    trailing_stop: float
    peak_price: float
    holding_days: int = 0
    signal_tier: str = ""
    strategy_score: float = 0.0
    selected_strategy_count: int = 0
    selected_strategy_ids: str = ""
    industry: str = "Unknown"


@dataclass
class PortfolioTrade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    shares: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    cost: float
    participation_rate: float
    exit_reason: str
    holding_days: int
    signal_tier: str
    strategy_score: float
    selected_strategy_count: int
    selected_strategy_ids: str


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    return str(value)


def _normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    settings = dict(settings)
    settings["risk"] = dict(settings.get("risk", {}))
    settings["trading"] = dict(settings.get("trading", {}))
    return settings


def _daily_cost(settings: dict[str, Any], value: float, is_entry: bool, participation_rate: float = 0.0) -> float:
    trading = settings["trading"]
    commission = value * float(trading["commission_rate"])
    slippage_rate = float(trading["slippage"]) + max(0.0, participation_rate) * float(trading.get("market_impact_slippage", 0.0))
    slippage = value * slippage_rate
    tax = value * float(trading["tax_rate"]) if not is_entry else 0.0
    return commission + slippage + tax


def _is_limit_up(prev_close: float, price: float) -> bool:
    return prev_close > 0 and price >= prev_close * 1.095


def _is_limit_down(prev_close: float, price: float) -> bool:
    return prev_close > 0 and price <= prev_close * 0.905


def _round_shares(raw_shares: float, lot: int) -> int:
    if raw_shares <= 0:
        return 0
    return int(raw_shares // lot) * lot


def _initial_stops(settings: dict[str, Any], entry_price: float, atr_value: float) -> tuple[float, float, float]:
    risk = settings.get("risk", {})
    stop_distance = atr_value * float(risk.get("atr_stop_multiplier", DEFAULT_RISK_FALLBACK["atr_stop_multiplier"]))
    stop_loss = entry_price - stop_distance
    take_profit = entry_price * (1 + float(risk.get("take_profit_pct", DEFAULT_RISK_FALLBACK["take_profit_pct"])))
    trailing_stop = entry_price - stop_distance
    return stop_loss, take_profit, trailing_stop


def _update_trailing(settings: dict[str, Any], position: PortfolioPosition, bar: pd.Series, defense_mode: bool = False) -> None:
    atr_value = float(bar.get("atr_14", np.nan))
    if not np.isfinite(atr_value) or atr_value <= 0:
        return
    high = float(bar["high"])
    position.peak_price = max(position.peak_price, high)
    risk = settings.get("risk", {})
    trigger_key = "defense_trailing_stop_trigger" if defense_mode else "trailing_stop_trigger"
    atr_key = "defense_trailing_stop_atr" if defense_mode else "trailing_stop_atr"
    trigger = float(risk.get(trigger_key, risk.get("trailing_stop_trigger", DEFAULT_RISK_FALLBACK["trailing_stop_trigger"])))
    if position.peak_price >= position.entry_price * (1 + trigger):
        position.trailing_stop = max(
            position.trailing_stop,
            position.peak_price - atr_value * float(risk.get(atr_key, risk.get("trailing_stop_atr", DEFAULT_RISK_FALLBACK["trailing_stop_atr"]))),
        )


def _exit_check(position: PortfolioPosition, bar: pd.Series, holding_period_max: int, settings: dict[str, Any] = None) -> tuple[bool, str]:
    if float(bar["low"]) <= position.stop_loss:
        return True, "stop_loss"
    if float(bar["high"]) >= position.take_profit:
        return True, "take_profit"
    if float(bar["low"]) <= position.trailing_stop:
        return True, "trailing_stop"
    if position.holding_days >= holding_period_max:
        return True, "time_exit"
    
    use_strategy_exit = False
    if settings:
        use_strategy_exit = bool(
            settings.get("strategy", {}).get(
                "use_strategy_exit",
                settings.get("trading", {}).get("use_strategy_exit", False),
            )
        )
    if use_strategy_exit:
        exit_signal = int(bar.get("exit_signal", 0))
        if exit_signal < 0:
            return True, "strategy_exit"
            
    return False, ""


def _exit_price(position: PortfolioPosition, bar: pd.Series, reason: str) -> tuple[float, bool]:
    open_price = float(bar.get("open", bar["close"]))
    if reason == "stop_loss":
        return (open_price, True) if open_price < position.stop_loss else (float(position.stop_loss), False)
    if reason == "take_profit":
        return float(position.take_profit), False
    if reason == "trailing_stop":
        return (open_price, True) if open_price < position.trailing_stop else (float(position.trailing_stop), False)
    return float(bar["close"]), False


def _make_oos_signals(
    scored: pd.DataFrame,
    selected: pd.DataFrame,
    spec_by_id: dict[str, Any],
    min_core_votes: int,
    include_expansion: bool,
    signal_filters: dict[str, Any],
) -> pd.DataFrame:
    core = _apply_selected_strategies(scored, selected, spec_by_id, min_core_votes, signal_filters)
    core["signal_tier"] = np.where(core["entry_signal"].eq(1), "core", "")
    if not include_expansion:
        return core

    expansion_filters = dict(signal_filters)
    expansion_filters["allowed_signal_regimes"] = ["bull"]
    expansion = _apply_selected_strategies(scored, selected, spec_by_id, 1, expansion_filters)
    expansion_only = expansion["entry_signal"].eq(1) & ~core["entry_signal"].eq(1)
    replace_cols = ["signal", "entry_signal", "selected_strategy_count", "selected_strategy_ids", "strategy_score"]
    core.loc[expansion_only, replace_cols] = expansion.loc[expansion_only, replace_cols]
    core.loc[expansion_only, "signal_tier"] = "expansion"
    return core


def _signal_filters_from_args(args: argparse.Namespace) -> dict[str, Any]:
    filters = dict(BEST_FILTERS)
    for arg_name, key in [
        ("min_strategy_score", "min_strategy_score"),
        ("min_market_breadth_ma20_chg5", "min_market_breadth_ma20_chg5"),
        ("min_market_positive_return_5_chg5", "min_market_positive_return_5_chg5"),
        ("max_market_volatility_20", "max_market_volatility_20"),
        ("max_recent_weak_5", "max_recent_weak_5"),
        ("max_recent_weak_10", "max_recent_weak_10"),
        ("max_recent_weak_20", "max_recent_weak_20"),
    ]:
        value = getattr(args, arg_name)
        if value is not None:
            filters[key] = value
    allowed_signal_regimes = [item.strip() for item in args.allowed_signal_regimes.split(",") if item.strip()]
    if allowed_signal_regimes:
        filters["allowed_signal_regimes"] = allowed_signal_regimes
    return filters


def _rank_candidates(rows: list[tuple[str, pd.Series]]) -> list[tuple[str, pd.Series]]:
    return sorted(
        rows,
        key=lambda item: (
            0 if str(item[1].get("signal_tier", "")) == "core" else 1,
            -float(item[1].get("strategy_score", 0.0)),
            -float(item[1].get("selected_strategy_count", 0.0)),
            -float(item[1].get("volume_ratio_20", 0.0)),
            str(item[0]),
        ),
    )


def _mark_to_market(
    positions: dict[str, PortfolioPosition],
    bars_by_symbol: dict[str, pd.Series],
    cash: float,
    price_column: str,
) -> tuple[float, float]:
    equity = cash
    invested = 0.0
    for symbol, position in positions.items():
        bar = bars_by_symbol.get(symbol)
        if bar is None:
            price = position.entry_price
        else:
            price = float(bar[price_column]) if price_column in bar and pd.notna(bar[price_column]) else float(bar["close"])
        notional = position.shares * price
        invested += notional
        equity += notional
    return equity, invested


def _recent_return_corr(
    symbol: str,
    other_symbol: str,
    grouped: dict[str, pd.DataFrame],
    current_date: pd.Timestamp,
    lookback: int,
) -> float | None:
    left = grouped.get(symbol)
    right = grouped.get(other_symbol)
    if left is None or right is None:
        return None
    left_close = pd.to_numeric(left.loc[left.index < current_date, "close"], errors="coerce").tail(lookback + 1)
    right_close = pd.to_numeric(right.loc[right.index < current_date, "close"], errors="coerce").tail(lookback + 1)
    joined = pd.concat(
        [left_close.pct_change().rename("left"), right_close.pct_change().rename("right")],
        axis=1,
    ).dropna()
    if len(joined) < max(12, lookback // 3):
        return None
    corr = joined["left"].corr(joined["right"])
    return None if pd.isna(corr) else float(corr)


def _passes_correlation_filter(
    symbol: str,
    positions: dict[str, PortfolioPosition],
    grouped: dict[str, pd.DataFrame],
    current_date: pd.Timestamp,
    max_correlation: float,
    lookback: int,
) -> bool:
    if max_correlation <= 0 or not positions:
        return True
    for held_symbol in positions:
        corr = _recent_return_corr(symbol, held_symbol, grouped, current_date, lookback)
        if corr is not None and corr >= max_correlation:
            return False
    return True


def _position_counts_by_industry(positions: dict[str, PortfolioPosition]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for position in positions.values():
        counts[position.industry] = counts.get(position.industry, 0) + 1
    return counts


def _row_float(row: pd.Series, column: str, default: float) -> float:
    if column not in row:
        return default
    try:
        value = float(row.get(column, default))
    except (TypeError, ValueError):
        return default
    return default if not np.isfinite(value) else value


def _rank_weight(index: int, total: int, spread: float) -> float:
    if spread <= 0 or total <= 1:
        return 1.0
    rank_pct = 1.0 - index / (total - 1)
    return 1.0 + spread * (rank_pct - 0.5)


def _run_portfolio(
    signals: pd.DataFrame,
    settings: dict[str, Any],
    capital: float,
    target_exposure: float,
    max_positions: int,
    max_position_pct: float,
    min_trade_unit: int,
    drawdown_block_threshold: float = 0.0,
    position_sizing: str = "fixed",
    max_risk_per_trade: float | None = None,
    max_correlation: float = 0.0,
    correlation_lookback: int = 60,
    max_positions_per_industry: int = 0,
    rebalance_trigger: float = 0.0,
    sentiment_overlay: bool = False,
    enable_replacement: bool = True,
    replacement_threshold: float = 0.05,
    trailing_stop_sell_pct: float = 1.0,
    max_entry_volume_pct: float = 0.0,
    max_entry_notional: float = 0.0,
    score_sizing_spread: float = 0.0,
) -> dict[str, Any]:
    data = signals.sort_values(["date", "symbol"]).reset_index(drop=True).copy()
    data["date"] = pd.to_datetime(data["date"])
    if "prev_close" not in data.columns and "close" in data.columns:
        data["prev_close"] = data.groupby("symbol")["close"].shift(1)
    grouped = {symbol: frame.set_index("date").sort_index() for symbol, frame in data.groupby("symbol")}
    dates = sorted(data["date"].dropna().unique())
    holding_period_max = int(settings["trading"].get("holding_period_max", 15))

    cash = float(capital)
    start_capital = float(capital)
    positions: dict[str, PortfolioPosition] = {}
    trades: list[PortfolioTrade] = []
    buy_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    execution_stats = {
        "blocked_limit_up_buys": 0,
        "blocked_limit_down_exits": 0,
        "gap_stop_exits": 0,
        "skipped_low_volume_buys": 0,
        "volume_capped_entries": 0,
    }
    prev_day_rows: list[tuple[str, pd.Series]] = []
    peak_equity = start_capital

    for current_date in dates:
        current_date = pd.Timestamp(current_date)
        bars_by_symbol: dict[str, pd.Series] = {}
        for symbol, frame in grouped.items():
            if current_date not in frame.index:
                continue
            row = frame.loc[current_date]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            bars_by_symbol[symbol] = row
        defense_threshold = settings.get("risk", {}).get("defense_market_breadth_ma20")
        defense_mode = False
        if defense_threshold is not None and bars_by_symbol:
            market_row = next(iter(bars_by_symbol.values()))
            breadth20 = _row_float(market_row, "market_breadth_ma20", np.nan)
            defense_mode = np.isfinite(breadth20) and breadth20 < float(defense_threshold)

        for symbol, position in list(positions.items()):
            bar = bars_by_symbol.get(symbol)
            if bar is None:
                continue
            position.holding_days += 1
            _update_trailing(settings, position, bar, defense_mode)
            should_exit, reason = _exit_check(position, bar, holding_period_max, settings)
            if not should_exit:
                continue
            prev_close = _row_float(bar, "prev_close", _row_float(bar, "close", 0.0))
            open_price = _row_float(bar, "open", _row_float(bar, "close", 0.0))
            if reason in {"stop_loss", "trailing_stop"} and _is_limit_down(prev_close, open_price):
                execution_stats["blocked_limit_down_exits"] += 1
                continue
            exit_price, gap_adjusted = _exit_price(position, bar, reason)
            if gap_adjusted:
                execution_stats["gap_stop_exits"] += 1

            # Partial sell for trailing_stop
            if reason == "trailing_stop" and 0 < trailing_stop_sell_pct < 1.0:
                sell_shares = max(1, int(position.shares * trailing_stop_sell_pct))
                keep_shares = position.shares - sell_shares
            else:
                sell_shares = position.shares
                keep_shares = 0

            exit_value = exit_price * sell_shares
            gross = (exit_price - position.entry_price) * sell_shares
            exit_volume = _row_float(bar, "volume", 0.0)
            participation_rate = sell_shares / exit_volume if exit_volume > 0 else 0.0
            costs = _daily_cost(settings, exit_value, is_entry=False, participation_rate=participation_rate)
            net = gross - costs
            cash += exit_value - costs
            trades.append(
                PortfolioTrade(
                    symbol=symbol,
                    entry_date=position.entry_date,
                    exit_date=current_date,
                    shares=sell_shares,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    gross_pnl=gross,
                    net_pnl=net,
                    cost=costs,
                    participation_rate=participation_rate,
                    exit_reason=reason,
                    holding_days=position.holding_days,
                    signal_tier=position.signal_tier,
                    strategy_score=position.strategy_score,
                    selected_strategy_count=position.selected_strategy_count,
                    selected_strategy_ids=position.selected_strategy_ids,
                )
            )
            if keep_shares > 0:
                position.shares = keep_shares
                position.peak_price = exit_price
            else:
                del positions[symbol]

        open_equity, open_invested = _mark_to_market(positions, bars_by_symbol, cash, "open")

        if rebalance_trigger > 0 and max_position_pct > 0 and open_equity > 0:
            for symbol, position in list(positions.items()):
                bar = bars_by_symbol.get(symbol)
                if bar is None:
                    continue
                open_price = float(bar["open"]) if "open" in bar and pd.notna(bar["open"]) else float(bar["close"])
                if not np.isfinite(open_price) or open_price <= 0:
                    continue
                current_weight = position.shares * open_price / open_equity
                if current_weight <= max_position_pct + rebalance_trigger:
                    continue
                target_shares = _round_shares((open_equity * max_position_pct) / open_price, min_trade_unit)
                sell_shares = position.shares - target_shares
                if sell_shares < min_trade_unit:
                    continue
                sell_value = sell_shares * open_price
                sell_volume = _row_float(bar, "volume", 0.0)
                participation_rate = sell_shares / sell_volume if sell_volume > 0 else 0.0
                costs = _daily_cost(settings, sell_value, is_entry=False, participation_rate=participation_rate)
                gross = (open_price - position.entry_price) * sell_shares
                net = gross - costs
                cash += sell_value - costs
                position.shares -= sell_shares
                trades.append(
                    PortfolioTrade(
                        symbol=symbol,
                        entry_date=position.entry_date,
                        exit_date=current_date,
                        shares=sell_shares,
                        entry_price=position.entry_price,
                        exit_price=open_price,
                        gross_pnl=gross,
                        net_pnl=net,
                        cost=costs,
                        participation_rate=participation_rate,
                        exit_reason="rebalance_trim",
                        holding_days=position.holding_days,
                        signal_tier=position.signal_tier,
                        strategy_score=position.strategy_score,
                        selected_strategy_count=position.selected_strategy_count,
                        selected_strategy_ids=position.selected_strategy_ids,
                    )
                )
                if position.shares <= 0:
                    del positions[symbol]
            open_equity, open_invested = _mark_to_market(positions, bars_by_symbol, cash, "open")

        open_drawdown = (peak_equity - open_equity) / peak_equity if peak_equity else 0.0
        daily_target_exposure = target_exposure
        daily_max_positions = max_positions
        daily_max_position_pct = max_position_pct
        daily_position_multiplier = 1.0
        daily_max_risk_per_trade = max_risk_per_trade
        daily_sentiment_score = np.nan
        daily_sentiment_label = ""
        if sentiment_overlay and prev_day_rows:
            sentiment_row = prev_day_rows[0][1]
            daily_sentiment_score = _row_float(sentiment_row, "sentiment_score", np.nan)
            daily_sentiment_label = str(sentiment_row.get("sentiment_label", ""))
            daily_position_multiplier = max(_row_float(sentiment_row, "sentiment_position_multiplier", 1.0), 0.0)
            max_positions_multiplier = max(_row_float(sentiment_row, "sentiment_max_positions_multiplier", 1.0), 0.0)
            target_exposure_multiplier = max(_row_float(sentiment_row, "sentiment_target_exposure_multiplier", 1.0), 0.0)
            block_entries = bool(sentiment_row.get("sentiment_block_entries", False))
            daily_target_exposure *= target_exposure_multiplier
            daily_max_position_pct *= daily_position_multiplier
            if daily_max_risk_per_trade is not None:
                daily_max_risk_per_trade *= daily_position_multiplier
            daily_max_positions = int(max_positions * max_positions_multiplier)
            daily_max_positions = max(0 if block_entries else 1, daily_max_positions)

        remaining_target = max(0.0, open_equity * daily_target_exposure - open_invested)
        opening_candidates = [
            (symbol, row)
            for symbol, row in prev_day_rows
            if int(row.get("entry_signal", 0)) == 1 and symbol not in positions
        ]
        prev_rows_by_symbol = dict(prev_day_rows)

        if drawdown_block_threshold > 0 and open_drawdown >= drawdown_block_threshold:
            opening_candidates = []

        ranked_opening_candidates = _rank_candidates(opening_candidates)
        for candidate_index, (symbol, row) in enumerate(ranked_opening_candidates):
            replacement_from = ""
            bar = bars_by_symbol.get(symbol)
            if bar is None:
                continue
            entry_price = float(bar["open"]) if "open" in bar and pd.notna(bar["open"]) else float(bar["close"])
            atr_value = float(row.get("atr_14", np.nan))
            if not np.isfinite(entry_price) or entry_price <= 0 or not np.isfinite(atr_value) or atr_value <= 0:
                continue
            prev_close = _row_float(row, "close", 0.0)
            if _is_limit_up(prev_close, entry_price):
                execution_stats["blocked_limit_up_buys"] += 1
                continue

            can_buy_freely = len(positions) < daily_max_positions and remaining_target > 0 and cash > 0
            replacement_trade: PortfolioTrade | None = None
            working_positions = positions
            working_cash = cash
            working_open_equity = open_equity
            working_remaining_target = remaining_target

            if not can_buy_freely and enable_replacement and positions:
                worst_sym = None
                worst_score = float('inf')
                for psym, ppos in positions.items():
                    pbar = prev_rows_by_symbol.get(psym)
                    pscore = float(pbar["strategy_score"]) if pbar is not None and "strategy_score" in pbar and pd.notna(pbar["strategy_score"]) else float(ppos.strategy_score)
                    if pscore < worst_score:
                        worst_score = pscore
                        worst_sym = psym
                
                cand_score = float(row.get("strategy_score", 0.0))
                if cand_score > worst_score + replacement_threshold:
                    worst_pos = positions[worst_sym]
                    worst_bar = bars_by_symbol.get(worst_sym)
                    exit_price = float(worst_bar["open"]) if worst_bar is not None and "open" in worst_bar and pd.notna(worst_bar["open"]) else float(worst_bar["close"]) if worst_bar is not None else float(worst_pos.entry_price)
                    worst_prev_close = _row_float(worst_bar, "prev_close", float(worst_pos.entry_price)) if worst_bar is not None else float(worst_pos.entry_price)
                    if _is_limit_down(worst_prev_close, exit_price):
                        execution_stats["blocked_limit_down_exits"] += 1
                        continue

                    exit_value = exit_price * worst_pos.shares
                    gross = (exit_price - worst_pos.entry_price) * worst_pos.shares
                    exit_volume = _row_float(worst_bar, "volume", 0.0) if worst_bar is not None else 0.0
                    participation_rate = worst_pos.shares / exit_volume if exit_volume > 0 else 0.0
                    costs = _daily_cost(settings, exit_value, is_entry=False, participation_rate=participation_rate)
                    net = gross - costs
                    replacement_trade = PortfolioTrade(
                        symbol=worst_sym,
                        entry_date=worst_pos.entry_date,
                        exit_date=current_date,
                        shares=worst_pos.shares,
                        entry_price=worst_pos.entry_price,
                        exit_price=exit_price,
                        gross_pnl=gross,
                        net_pnl=net,
                        cost=costs,
                        participation_rate=participation_rate,
                        exit_reason="replacement_switch",
                        holding_days=worst_pos.holding_days,
                        signal_tier=worst_pos.signal_tier,
                        strategy_score=worst_pos.strategy_score,
                        selected_strategy_count=worst_pos.selected_strategy_count,
                        selected_strategy_ids=worst_pos.selected_strategy_ids,
                    )
                    replacement_from = worst_sym
                    working_positions = dict(positions)
                    del working_positions[worst_sym]
                    working_cash = cash + exit_value - costs
                    working_open_equity, working_open_invested = _mark_to_market(working_positions, bars_by_symbol, working_cash, "open")
                    working_remaining_target = max(0.0, working_open_equity * daily_target_exposure - working_open_invested)

            if len(working_positions) >= daily_max_positions or working_remaining_target <= 0 or working_cash <= 0:
                if replacement_trade is not None:
                    continue
                break

            industry = str(row.get("industry", bar.get("industry", "Unknown")) or "Unknown")
            if max_positions_per_industry > 0:
                industry_counts = _position_counts_by_industry(working_positions)
                if industry_counts.get(industry, 0) >= max_positions_per_industry:
                    continue
            if not _passes_correlation_filter(symbol, working_positions, grouped, current_date, max_correlation, correlation_lookback):
                continue
            sizing_multiplier = _rank_weight(candidate_index, len(ranked_opening_candidates), score_sizing_spread)
            risk_pct_for_size = (
                float(daily_max_risk_per_trade if daily_max_risk_per_trade is not None else settings["risk"].get("max_risk_per_trade", 0.01))
                if position_sizing == "risk_parity"
                else 1_000_000.0
            )
            sizing = calculate_position_size(
                capital=working_open_equity,
                price=entry_price,
                atr_value=atr_value,
                risk_pct=risk_pct_for_size,
                atr_multiplier=float(settings["risk"].get("atr_stop_multiplier", DEFAULT_RISK_FALLBACK["atr_stop_multiplier"])),
                max_position_pct=daily_max_position_pct,
                min_trade_unit=min_trade_unit,
                cash=working_cash,
                target_notional=working_remaining_target,
                max_notional=max_entry_notional,
                volume=_row_float(row, "volume", 0.0),
                max_volume_pct=max_entry_volume_pct,
                size_multiplier=sizing_multiplier if position_sizing == "risk_parity" else 1.0,
            )
            shares = sizing.shares
            if sizing.blocked_reason == "low_volume":
                execution_stats["skipped_low_volume_buys"] += 1
            if sizing.volume_limited_shares < sizing.theoretical_shares:
                execution_stats["volume_capped_entries"] += 1
            if shares <= 0:
                continue
            notional = shares * entry_price
            entry_volume = _row_float(row, "volume", 0.0)
            participation_rate = shares / entry_volume if entry_volume > 0 else 0.0
            cost = _daily_cost(settings, notional, is_entry=True, participation_rate=participation_rate)
            while shares > 0 and notional + cost > working_cash:
                shares -= min_trade_unit
                notional = shares * entry_price
                participation_rate = shares / entry_volume if entry_volume > 0 else 0.0
                cost = _daily_cost(settings, notional, is_entry=True, participation_rate=participation_rate)
            if shares <= 0:
                continue
            stop_loss, take_profit, trailing_stop = _initial_stops(settings, entry_price, atr_value)
            if replacement_trade is not None:
                trades.append(replacement_trade)
                positions = working_positions
                cash = working_cash
                open_equity = working_open_equity
                remaining_target = working_remaining_target
            cash -= notional + cost
            buy_rows.append(
                {
                    "date": current_date,
                    "symbol": symbol,
                    "shares": shares,
                    "entry_price": entry_price,
                    "notional": notional,
                    "cost": cost,
                    "participation_rate": participation_rate,
                    "theoretical_shares": sizing.theoretical_shares,
                    "volume_limited_shares": sizing.volume_limited_shares,
                    "cash_limited_shares": sizing.cash_limited_shares,
                    "blocked_reason": sizing.blocked_reason,
                    "cash_after": cash,
                    "strategy_score": float(row.get("strategy_score", 0.0)),
                    "rank_signal_score": float(row.get("rank_signal_score", np.nan)),
                    "candidate_rank": candidate_index + 1,
                    "candidate_count": len(ranked_opening_candidates),
                    "sizing_multiplier": sizing_multiplier,
                    "buy_reason": "replacement_buy" if replacement_from else "new_position",
                    "replacement_from": replacement_from,
                    "market_regime": str(row.get("market_regime", "")),
                    "signal_tier": str(row.get("signal_tier", "")),
                }
            )
            positions[symbol] = PortfolioPosition(
                symbol=symbol,
                entry_date=current_date,
                entry_price=entry_price,
                shares=shares,
                stop_loss=stop_loss,
                take_profit=take_profit,
                trailing_stop=trailing_stop,
                peak_price=entry_price,
                signal_tier=str(row.get("signal_tier", "")),
                strategy_score=float(row.get("strategy_score", 0.0)),
                selected_strategy_count=int(row.get("selected_strategy_count", 0)),
                selected_strategy_ids=str(row.get("selected_strategy_ids", "")),
                industry=industry,
            )
            remaining_target = max(0.0, remaining_target - notional)

        equity, invested = _mark_to_market(positions, bars_by_symbol, cash, "close")
        peak_equity = max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity if peak_equity else 0.0
        equity_rows.append(
            {
                "date": current_date,
                "equity": equity,
                "cash": cash,
                "invested_notional": invested,
                "capital_utilization": invested / equity if equity else 0.0,
                "open_positions": len(positions),
                "drawdown": drawdown,
                "sentiment_score": daily_sentiment_score,
                "sentiment_label": daily_sentiment_label,
                "sentiment_position_multiplier": daily_position_multiplier,
                "sentiment_max_positions": daily_max_positions,
                "defense_mode": defense_mode,
            }
        )

        prev_day_rows = list(bars_by_symbol.items())

    equity = pd.DataFrame(equity_rows)
    trade_log = pd.DataFrame([asdict(trade) for trade in trades])
    buy_log = pd.DataFrame(buy_rows)
    if not trade_log.empty:
        trade_log["win"] = trade_log["net_pnl"] > 0
    tca_summary = {
        "entry_cost": float(buy_log["cost"].sum()) if not buy_log.empty and "cost" in buy_log else 0.0,
        "exit_cost": float(trade_log["cost"].sum()) if not trade_log.empty and "cost" in trade_log else 0.0,
        "total_cost": float((buy_log["cost"].sum() if not buy_log.empty and "cost" in buy_log else 0.0) + (trade_log["cost"].sum() if not trade_log.empty and "cost" in trade_log else 0.0)),
        "replacement_switch_trades": int(trade_log["exit_reason"].eq("replacement_switch").sum()) if not trade_log.empty and "exit_reason" in trade_log else 0,
        "replacement_switch_gross_pnl": float(trade_log.loc[trade_log["exit_reason"].eq("replacement_switch"), "gross_pnl"].sum()) if not trade_log.empty and "exit_reason" in trade_log else 0.0,
        "replacement_switch_net_pnl": float(trade_log.loc[trade_log["exit_reason"].eq("replacement_switch"), "net_pnl"].sum()) if not trade_log.empty and "exit_reason" in trade_log else 0.0,
        "replacement_switch_exit_cost": float(trade_log.loc[trade_log["exit_reason"].eq("replacement_switch"), "cost"].sum()) if not trade_log.empty and "exit_reason" in trade_log and "cost" in trade_log else 0.0,
        "replacement_buy_cost": float(buy_log.loc[buy_log["buy_reason"].eq("replacement_buy"), "cost"].sum()) if not buy_log.empty and "buy_reason" in buy_log and "cost" in buy_log else 0.0,
    }
    final_equity = float(equity["equity"].iloc[-1]) if not equity.empty else start_capital
    final_date = pd.Timestamp(equity["date"].iloc[-1]) if not equity.empty else pd.NaT
    open_position_rows: list[dict[str, Any]] = []
    for symbol, position in sorted(positions.items()):
        latest_bar = bars_by_symbol.get(symbol)
        current_price = (
            float(latest_bar["close"])
            if latest_bar is not None and pd.notna(latest_bar.get("close"))
            else float(position.entry_price)
        )
        market_value = float(position.shares) * current_price
        unrealized_pnl = float(position.shares) * (current_price - float(position.entry_price))
        open_position_rows.append(
            {
                **asdict(position),
                "as_of_date": final_date,
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_return": (
                    current_price / float(position.entry_price) - 1.0
                    if position.entry_price
                    else 0.0
                ),
                "portfolio_weight": market_value / final_equity if final_equity else 0.0,
            }
        )
    open_position_columns = [
        *PortfolioPosition.__dataclass_fields__.keys(),
        "as_of_date",
        "current_price",
        "market_value",
        "unrealized_pnl",
        "unrealized_return",
        "portfolio_weight",
    ]
    return {
        "equity_curve": equity,
        "trade_log": trade_log,
        "buy_log": buy_log,
        "open_positions": pd.DataFrame(open_position_rows, columns=open_position_columns),
        "start_capital": start_capital,
        "final_equity": final_equity,
        "execution_stats": execution_stats,
        "tca_summary": tca_summary,
    }


def _performance(result: dict[str, Any]) -> dict[str, float]:
    equity = result["equity_curve"]
    trades = result["trade_log"]
    start_capital = float(result["start_capital"])
    final_equity = float(result["final_equity"])
    if equity.empty:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "sharpe": np.nan,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": np.nan,
            "trades": 0.0,
            "mean_capital_utilization": 0.0,
        }
    days = max(len(equity), 1)
    daily = equity["equity"].pct_change().dropna()
    total_return = final_equity / start_capital - 1
    cagr = (final_equity / start_capital) ** (252 / days) - 1 if days > 1 else 0.0
    daily_std = float(daily.std()) if len(daily) > 1 else 0.0
    sharpe = float(np.sqrt(252) * daily.mean() / daily_std) if daily_std > 0 else np.nan
    win_rate = float(trades["win"].mean()) if not trades.empty else 0.0
    loss_sum = abs(float(trades.loc[trades["net_pnl"] < 0, "net_pnl"].sum())) if not trades.empty else 0.0
    profit_sum = float(trades.loc[trades["net_pnl"] > 0, "net_pnl"].sum()) if not trades.empty else 0.0
    profit_factor = profit_sum / loss_sum if loss_sum > 0 else np.nan
    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": sharpe,
        "max_drawdown": float(equity["drawdown"].max()),
        "win_rate": win_rate,
        "profit_factor": float(profit_factor) if np.isfinite(profit_factor) else np.nan,
        "trades": float(len(trades)),
        "mean_capital_utilization": float(equity["capital_utilization"].mean()),
    }


def _fetch_benchmark_from_api(
    settings: dict[str, Any],
    benchmark_symbol: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    output_dir: Path,
) -> tuple[pd.DataFrame, Path | None, str | None]:
    api_settings = dict(settings)
    api_settings["data"] = dict(settings.get("data", {}))
    api_settings["data"]["source"] = "fubon_neo"
    api_settings["data"]["start_date"] = start_date.strftime("%Y-%m-%d")
    api_settings["data"]["end_date"] = end_date.strftime("%Y-%m-%d")
    try:
        fetcher = DataFetcher(api_settings, raw_dir=ROOT / "data" / "raw")
        bench = fetcher.fetch_daily_candles(
            str(benchmark_symbol),
            api_settings["data"]["start_date"],
            api_settings["data"]["end_date"],
        )
        if bench.empty:
            return pd.DataFrame(), None, "api_returned_empty"
        bench = bench.copy()
        bench["symbol"] = str(benchmark_symbol)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"benchmark_{benchmark_symbol}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"
        bench.to_csv(path, index=False, encoding="utf-8-sig")
        return bench, path, None
    except Exception as exc:  # pragma: no cover - SDK/network/credential dependent
        return pd.DataFrame(), None, f"api_fetch_failed: {exc}"


def _benchmark_metrics(
    data: pd.DataFrame,
    settings: dict[str, Any],
    benchmark_symbol: str,
    dates: list[pd.Timestamp],
    output_dir: Path,
) -> dict[str, Any]:
    if not dates:
        return {"benchmark_symbol": benchmark_symbol, "found": False, "status": "no_strategy_dates"}
    start_date = pd.Timestamp(min(dates))
    end_date = pd.Timestamp(max(dates))
    bench = data[data["symbol"].astype(str).eq(str(benchmark_symbol))].sort_values("date").copy()
    if bench.empty:
        bench, api_path, error = _fetch_benchmark_from_api(settings, benchmark_symbol, start_date, end_date, output_dir)
        source = "api"
        if bench.empty:
            return {
                "benchmark_symbol": benchmark_symbol,
                "found": False,
                "status": "missing_api_data",
                "start": start_date,
                "end": end_date,
                "error": error,
            }
    else:
        api_path = None
        source = "local"
    date_set = set(pd.to_datetime(dates))
    bench["date"] = pd.to_datetime(bench["date"])
    bench = bench[bench["date"].isin(date_set)].copy()
    if len(bench) < 2:
        return {
            "benchmark_symbol": benchmark_symbol,
            "found": False,
            "status": "insufficient_overlap_after_api_or_local_load",
            "source": source,
            "start": start_date,
            "end": end_date,
        }
    equity = bench["close"] / float(bench["close"].iloc[0])
    daily = equity.pct_change().dropna()
    drawdown = equity / equity.cummax() - 1
    days = len(bench)
    cagr = float(equity.iloc[-1] ** (252 / days) - 1)
    daily_std = float(daily.std()) if len(daily) > 1 else 0.0
    sharpe = float(np.sqrt(252) * daily.mean() / daily_std) if daily_std > 0 else np.nan
    return {
        "benchmark_symbol": benchmark_symbol,
        "found": True,
        "source": source,
        "api_path": str(api_path) if api_path else None,
        "start": bench["date"].iloc[0],
        "end": bench["date"].iloc[-1],
        "total_return": float(equity.iloc[-1] - 1),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": float(abs(drawdown.min())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio-level WFA for daily multi-strategy stock-picking signals.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--target-exposure", type=float, default=0.80)
    parser.add_argument("--portfolio-max-positions", type=int, default=8)
    parser.add_argument("--portfolio-max-position-pct", type=float, default=0.10)
    parser.add_argument("--min-trade-unit", type=int, default=1)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--max-strategies", type=int, default=996)
    parser.add_argument("--forward-days", type=int, default=15)
    parser.add_argument("--min-signals", type=int, default=200)
    parser.add_argument("--top-per-regime", type=int, default=2)
    parser.add_argument("--sleeve-top-per-family", type=int, default=1)
    parser.add_argument("--min-edge-score", type=float, default=0.05)
    parser.add_argument("--min-positive-cycle-ratio", type=float, default=0.60)
    parser.add_argument("--min-cycle-count", type=int, default=3)
    parser.add_argument("--min-core-votes", type=int, default=2)
    parser.add_argument("--include-expansion", action="store_true")
    parser.add_argument("--allowed-regimes", default="bull,recovery")
    parser.add_argument("--allowed-signal-regimes", default="")
    parser.add_argument("--min-strategy-score", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma20-chg5", type=float, default=None)
    parser.add_argument("--min-market-positive-return-5-chg5", type=float, default=None)
    parser.add_argument("--max-market-volatility-20", type=float, default=None)
    parser.add_argument("--max-recent-weak-5", type=float, default=None)
    parser.add_argument("--max-recent-weak-10", type=float, default=None)
    parser.add_argument("--max-recent-weak-20", type=float, default=None)
    parser.add_argument("--in-sample-days", type=int, default=None)
    parser.add_argument("--out-sample-days", type=int, default=None)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--benchmark-symbol", default="0050")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "portfolio_wfa")
    args = parser.parse_args()

    settings = _normalize_settings(load_settings(args.config))
    settings["trading"]["initial_capital"] = float(args.capital)
    settings["trading"]["min_trade_unit"] = int(args.min_trade_unit)
    wfa_cfg = settings["wfa"]
    is_days = int(args.in_sample_days or wfa_cfg["in_sample_days"])
    oos_days = int(args.out_sample_days or wfa_cfg["out_sample_days"])
    step_days = int(args.step_days or oos_days)

    data = _load_data(args.data, args.max_symbols or None, args.max_rows or None)
    catalog = build_strategy_catalog(args.max_strategies or None)
    spec_by_id = {spec.strategy_id: spec for spec in catalog}
    unique_dates = sorted(pd.to_datetime(data["date"].dropna().unique()))
    allowed_regimes = {item.strip() for item in args.allowed_regimes.split(",") if item.strip()} or None
    signal_filters = _signal_filters_from_args(args)

    signal_frames = []
    selected_rows = []
    window_rows = []
    start = 0
    window = 0
    used_oos_dates: set[pd.Timestamp] = set()

    while start + is_days + oos_days <= len(unique_dates):
        is_dates = unique_dates[start : start + is_days]
        oos_dates = unique_dates[start + is_days : start + is_days + oos_days]
        oos_dates = [pd.Timestamp(date) for date in oos_dates if pd.Timestamp(date) not in used_oos_dates]
        if not oos_dates:
            start += step_days
            continue
        train_df = _attach_forward_return(data[data["date"].isin(is_dates)].copy(), args.forward_days)
        oos_df = data[data["date"].isin(oos_dates)].copy()
        print(
            f"[portfolio-wfa] window={window} "
            f"is={pd.Timestamp(is_dates[0]).date()}..{pd.Timestamp(is_dates[-1]).date()} "
            f"oos={pd.Timestamp(oos_dates[0]).date()}..{pd.Timestamp(oos_dates[-1]).date()}",
            flush=True,
        )
        started = time.perf_counter()
        train_scored = add_strategy_ranks(_attach_cycles(train_df, settings))
        oos_scored = add_strategy_ranks(_attach_cycles(oos_df, settings))
        primary_selected = _select_strategies(
            train_scored,
            catalog,
            args.min_signals,
            args.top_per_regime,
            args.min_edge_score,
            args.min_positive_cycle_ratio,
            args.min_cycle_count,
            allowed_regimes,
        )
        sleeve_selected = _select_family_sleeves(
            train_scored,
            catalog,
            args.min_signals,
            args.min_edge_score,
            args.min_positive_cycle_ratio,
            args.min_cycle_count,
            allowed_regimes,
            args.sleeve_top_per_family,
        )
        selected = _merge_selected(primary_selected, sleeve_selected)
        selected = selected.copy()
        if not selected.empty:
            selected["window"] = window
            selected_rows.append(selected)
        signals = _make_oos_signals(
            oos_scored,
            selected,
            spec_by_id,
            args.min_core_votes,
            args.include_expansion,
            signal_filters,
        )
        signals["window"] = window
        signal_frames.append(signals)
        used_oos_dates.update(pd.Timestamp(date) for date in oos_dates)
        elapsed = time.perf_counter() - started
        signal_count = int(signals["entry_signal"].eq(1).sum())
        window_rows.append(
            {
                "window": window,
                "is_start": pd.Timestamp(is_dates[0]),
                "is_end": pd.Timestamp(is_dates[-1]),
                "oos_start": pd.Timestamp(oos_dates[0]),
                "oos_end": pd.Timestamp(oos_dates[-1]),
                "train_seconds": round(elapsed, 2),
                "selected_strategies": int(len(selected)),
                "buy_signals": signal_count,
            }
        )
        print(
            f"[portfolio-wfa] window={window} selected={len(selected)} buy_signals={signal_count} "
            f"seconds={elapsed:.1f}",
            flush=True,
        )
        window += 1
        start += step_days

    signals_all = pd.concat(signal_frames, ignore_index=True) if signal_frames else pd.DataFrame()
    selected_all = pd.concat(selected_rows, ignore_index=True) if selected_rows else pd.DataFrame()
    windows = pd.DataFrame(window_rows)
    result = _run_portfolio(
        signals_all,
        settings,
        args.capital,
        args.target_exposure,
        args.portfolio_max_positions,
        args.portfolio_max_position_pct,
        args.min_trade_unit,
    )
    perf = _performance(result)
    benchmark_dates = sorted(pd.to_datetime(signals_all["date"].dropna().unique())) if not signals_all.empty else []
    benchmark = _benchmark_metrics(data, settings, args.benchmark_symbol, benchmark_dates, args.output_dir / "benchmark_data")
    beats_benchmark_cagr = (
        bool(perf["cagr"] > float(benchmark["cagr"]))
        if benchmark.get("found") and benchmark.get("cagr") is not None
        else None
    )
    beats_benchmark_sharpe = (
        bool(perf["sharpe"] > float(benchmark["sharpe"]))
        if benchmark.get("found") and benchmark.get("sharpe") is not None and pd.notna(perf["sharpe"])
        else None
    )
    summary = {
        "performance": perf,
        "benchmark": benchmark,
        "beats_benchmark_cagr": beats_benchmark_cagr,
        "beats_benchmark_sharpe": beats_benchmark_sharpe,
        "windows": int(len(windows)),
        "candidate_buy_signals": int(signals_all["entry_signal"].eq(1).sum()) if not signals_all.empty else 0,
        "selected_strategy_rows": int(len(selected_all)),
        "settings": {
            "capital": args.capital,
            "target_exposure": args.target_exposure,
            "portfolio_max_positions": args.portfolio_max_positions,
            "portfolio_max_position_pct": args.portfolio_max_position_pct,
            "min_trade_unit": args.min_trade_unit,
            "in_sample_days": is_days,
            "out_sample_days": oos_days,
            "step_days": step_days,
            "max_strategies": args.max_strategies,
            "forward_days": args.forward_days,
            "top_per_regime": args.top_per_regime,
            "sleeve_top_per_family": args.sleeve_top_per_family,
            "min_core_votes": args.min_core_votes,
            "include_expansion": args.include_expansion,
            "allowed_regimes": sorted(allowed_regimes) if allowed_regimes else [],
            "signal_filters": signal_filters,
            "risk": settings.get("risk", {}),
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    windows_path = args.output_dir / f"portfolio_wfa_windows_{stamp}.csv"
    selected_path = args.output_dir / f"portfolio_wfa_selected_{stamp}.csv"
    signals_path = args.output_dir / f"portfolio_wfa_signals_{stamp}.csv"
    equity_path = args.output_dir / f"portfolio_wfa_equity_{stamp}.csv"
    trades_path = args.output_dir / f"portfolio_wfa_trades_{stamp}.csv"
    summary_path = args.output_dir / f"portfolio_wfa_summary_{stamp}.json"

    windows.to_csv(windows_path, index=False, encoding="utf-8-sig")
    selected_all.to_csv(selected_path, index=False, encoding="utf-8-sig")
    signal_cols = [
        "date",
        "symbol",
        "window",
        "market_regime",
        "entry_signal",
        "signal_tier",
        "strategy_score",
        "selected_strategy_count",
        "selected_strategy_ids",
        "close",
        "open",
        "atr_14",
        "volume_ratio_20",
    ]
    available_signal_cols = [col for col in signal_cols if col in signals_all.columns]
    signals_all.loc[:, available_signal_cols].to_csv(signals_path, index=False, encoding="utf-8-sig")
    result["equity_curve"].to_csv(equity_path, index=False, encoding="utf-8-sig")
    result["trade_log"].to_csv(trades_path, index=False, encoding="utf-8-sig")
    
    if simulation_start_date:
        start_date_str = pd.to_datetime(simulation_start_date).strftime("%Y%m%d")
        capital_m = int(capital / 1_000_000)
        custom_trades_path = out_dir / f"{start_date_str}_{capital_m}M.csv"
        result["trade_log"].to_csv(custom_trades_path, index=False, encoding="utf-8-sig")
        print(f"[saved] {custom_trades_path}")
        
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

    print(f"[portfolio-wfa] cagr={perf['cagr']:.2%} sharpe={perf['sharpe']:.3f} max_dd={perf['max_drawdown']:.2%}")
    print(f"[portfolio-wfa] utilization={perf['mean_capital_utilization']:.2%} trades={perf['trades']:.0f}")
    print(f"[saved] {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
