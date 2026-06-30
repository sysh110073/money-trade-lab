from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from run_cycle_strategy_wfa import _attach_cycles, _load_data  # noqa: E402
from run_portfolio_strategy_wfa import (  # noqa: E402
    _benchmark_metrics,
    _performance,
    _run_portfolio,
)
from src.config import load_settings, setting_path  # noqa: E402
from src.institutional_overlay import overlay_recent_official_institutional_flow  # noqa: E402
from src.strategy_catalog import add_strategy_ranks  # noqa: E402


DEFAULT_DATA = PROJECT_ROOT / "data" / "processed" / "all_features.csv"


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    return str(value)


def _lag_monthly_revenue_features(data: pd.DataFrame) -> pd.DataFrame:
    cols = [col for col in ["revenue", "revenue_mom_21d"] if col in data.columns]
    if not cols:
        return data
    out = data.sort_values(["symbol", "date"]).copy()
    unavailable = pd.to_datetime(out["date"]).dt.day <= 10
    out.loc[unavailable, cols] = np.nan
    out[cols] = out.groupby("symbol", group_keys=False)[cols].ffill()
    return out


def _overheated_weak_market(data: pd.DataFrame) -> pd.Series:
    breadth = _series(data, "market_breadth_ma20", 1.0)
    positive5 = _series(data, "market_positive_return_5", 1.0)
    position52 = _series(data, "position_in_52w_range", 0.0)
    price_to_ma20 = _series(data, "price_to_ma_20", 0.0)
    volume20 = _series(data, "volume_ratio_20", 0.0)
    weak_market = (breadth < 0.50) | (positive5 < 0.50)
    overheated = (position52 > 0.95) & (price_to_ma20 > 0.15) & (volume20 > 2.0)
    return weak_market & overheated


def _rank(data: pd.DataFrame, column: str, high_good: bool = True, default: float = 0.5) -> pd.Series:
    if column not in data.columns:
        return pd.Series(default, index=data.index, dtype=float)
    values = pd.to_numeric(data[column], errors="coerce")
    ranks = values.groupby(data["date"]).rank(pct=True, ascending=high_good)
    if high_good:
        return ranks.fillna(default)
    return (1 - ranks).fillna(default)


def _build_score(data: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    close = pd.to_numeric(data["close"], errors="coerce")
    long_frame = data[["date", "symbol"]].copy()
    long_frame["close_return_60"] = close.groupby(data["symbol"]).pct_change(60)
    long_frame["close_return_120"] = close.groupby(data["symbol"]).pct_change(120)
    long_frame["close_return_252"] = close.groupby(data["symbol"]).pct_change(252)
    long_momentum = (
        0.25 * _rank(long_frame, "close_return_60")
        + 0.35 * _rank(long_frame, "close_return_120")
        + 0.40 * _rank(long_frame, "close_return_252")
    )
    momentum = (
        0.35 * _rank(data, "close_return_5")
        + 0.40 * _rank(data, "close_return_10")
        + 0.25 * _rank(data, "position_in_52w_range")
    )
    trend = (
        0.35 * _rank(data, "price_to_ma_20")
        + 0.30 * _rank(data, "close_sma_ratio_20")
        + 0.20 * _rank(data, "close_sma_ratio_60")
        + 0.15 * _rank(data, "adx_14")
    )
    flow = (
        0.35 * _rank(data, "volume_ratio_20")
        + 0.30 * _rank(data, "total_net")
        + 0.20 * _rank(data, "foreign_net_5d_sum")
        + 0.15 * _rank(data, "trust_net_5d_sum")
    )
    fundamental = _rank(data, "revenue_mom_21d")
    low_vol = _rank(data, "rolling_volatility_20", high_good=False)
    score = (
        weights["momentum"] * momentum
        + weights["long_momentum"] * long_momentum
        + weights["trend"] * trend
        + weights["flow"] * flow
        + weights["fundamental"] * fundamental
        + weights["low_vol"] * low_vol
    )
    denom = sum(abs(value) for value in weights.values()) or 1.0
    return score / denom


def _series(data: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column in data.columns:
        return pd.to_numeric(data[column], errors="coerce").fillna(default)
    return pd.Series(default, index=data.index, dtype=float)


def _build_sentiment_overlay(
    data: pd.DataFrame,
    high_threshold: float,
    neutral_threshold: float,
    weak_threshold: float,
    extreme_threshold: float,
) -> pd.DataFrame:
    frame = data.copy()
    breadth20 = _series(frame, "market_breadth_ma20", 0.5).clip(0.0, 1.0)
    positive5 = _series(frame, "market_positive_return_5", 0.5).clip(0.0, 1.0)
    position52 = _series(frame, "market_position_52w", 0.5).clip(0.0, 1.0)
    vol20 = _series(frame, "market_volatility_20", 0.03).clip(lower=0.0)
    vol_cap = max(float(frame["market_volatility_20"].quantile(0.90)) if "market_volatility_20" in frame.columns else 0.06, 0.03)
    volatility_score = (1.0 - (vol20 / vol_cap).clip(0.0, 1.0)).fillna(0.5)

    score = 100.0 * (
        0.35 * breadth20
        + 0.25 * positive5
        + 0.25 * position52
        + 0.15 * volatility_score
    )
    frame["sentiment_score"] = score.clip(0.0, 100.0)
    frame["sentiment_label"] = "normal"
    frame["sentiment_position_multiplier"] = 1.0
    frame["sentiment_max_positions_multiplier"] = 1.0
    frame["sentiment_target_exposure_multiplier"] = 1.0
    frame["sentiment_block_entries"] = False

    overheat = frame["sentiment_score"] >= high_threshold
    normal = frame["sentiment_score"].between(neutral_threshold, high_threshold, inclusive="left")
    weak = frame["sentiment_score"].between(weak_threshold, neutral_threshold, inclusive="left")
    defensive = frame["sentiment_score"].between(extreme_threshold, weak_threshold, inclusive="left")
    extreme = frame["sentiment_score"] < extreme_threshold

    frame.loc[overheat, "sentiment_label"] = "overheated"
    frame.loc[overheat, "sentiment_position_multiplier"] = 0.75
    frame.loc[overheat, "sentiment_max_positions_multiplier"] = 0.75
    frame.loc[overheat, "sentiment_target_exposure_multiplier"] = 0.85

    frame.loc[normal, "sentiment_label"] = "constructive"

    frame.loc[weak, "sentiment_label"] = "weak"
    frame.loc[weak, "sentiment_position_multiplier"] = 0.80
    frame.loc[weak, "sentiment_target_exposure_multiplier"] = 0.85

    frame.loc[defensive, "sentiment_label"] = "defensive"
    frame.loc[defensive, "sentiment_position_multiplier"] = 0.50
    frame.loc[defensive, "sentiment_max_positions_multiplier"] = 0.75
    frame.loc[defensive, "sentiment_target_exposure_multiplier"] = 0.60

    frame.loc[extreme, "sentiment_label"] = "extreme_fear"
    frame.loc[extreme, "sentiment_position_multiplier"] = 0.0
    frame.loc[extreme, "sentiment_max_positions_multiplier"] = 0.0
    frame.loc[extreme, "sentiment_target_exposure_multiplier"] = 0.0
    frame.loc[extreme, "sentiment_block_entries"] = True
    return frame


def _make_rank_signals(
    data: pd.DataFrame,
    top_n: int,
    min_score: float,
    allowed_signal_regimes: set[str],
    weights: dict[str, float],
    min_market_breadth_ma20: float | None,
    min_market_positive_return_5: float | None,
    max_market_volatility_20: float | None,
) -> pd.DataFrame:
    scored = add_strategy_ranks(data.copy())
    scored["strategy_score"] = _build_score(scored, weights)
    scored["rank_signal_score"] = scored.groupby("date")["strategy_score"].rank(ascending=False, method="first")
    market_ok = pd.Series(True, index=scored.index)
    if allowed_signal_regimes:
        market_ok &= scored["market_regime"].astype(str).isin(allowed_signal_regimes)
    if min_market_breadth_ma20 is not None:
        market_ok &= pd.to_numeric(scored["market_breadth_ma20"], errors="coerce") >= min_market_breadth_ma20
    if min_market_positive_return_5 is not None:
        market_ok &= pd.to_numeric(scored["market_positive_return_5"], errors="coerce") >= min_market_positive_return_5
    if max_market_volatility_20 is not None:
        market_ok &= pd.to_numeric(scored["market_volatility_20"], errors="coerce") <= max_market_volatility_20
    market_ok &= ~_overheated_weak_market(scored)
    entry = (scored["rank_signal_score"] <= top_n) & (scored["strategy_score"] >= min_score) & market_ok
    scored["signal"] = 0
    scored["entry_signal"] = 0
    scored.loc[entry, ["signal", "entry_signal"]] = 1
    scored["signal_tier"] = np.where(entry, "rank_core", "")
    scored["selected_strategy_count"] = np.where(entry, 1, 0)
    scored["selected_strategy_ids"] = np.where(entry, "rank_multi_factor", "")
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest a daily rank-based multi-factor stock-picking portfolio.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--target-exposure", type=float, default=1.0)
    parser.add_argument("--portfolio-max-positions", type=int, default=8)
    parser.add_argument("--portfolio-max-position-pct", type=float, default=0.20)
    parser.add_argument("--position-sizing", choices=["fixed", "risk_parity"], default="risk_parity")
    parser.add_argument("--max-risk-per-trade", type=float, default=0.02)
    parser.add_argument("--max-correlation", type=float, default=0.0)
    parser.add_argument("--correlation-lookback", type=int, default=60)
    parser.add_argument("--max-positions-per-industry", type=int, default=0)
    parser.add_argument("--rebalance-trigger", type=float, default=0.0)
    parser.add_argument("--enable-replacement", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--replacement-threshold", type=float, default=0.05)
    parser.add_argument("--trailing-stop-sell-pct", type=float, default=1.0, help="Fraction of shares to sell on trailing stop (0.5=50%%, 1.0=100%%)")
    parser.add_argument("--max-entry-volume-pct", type=float, default=0.01, help="Max shares to buy as a fraction of the previous trading day's volume.")
    parser.add_argument("--max-entry-notional", type=float, default=2_000_000)
    parser.add_argument("--score-sizing-spread", type=float, default=0.0, help="Tilt entry size by daily candidate rank; 0.30 means roughly -15%% to +15%%.")
    parser.add_argument("--market-impact-slippage", type=float, default=0.10, help="Extra slippage rate per 100%% volume participation.")
    parser.add_argument("--min-trade-unit", type=int, default=1000)
    parser.add_argument("--holding-period-max", type=int, default=180)
    parser.add_argument("--drawdown-block-threshold", type=float, default=0.0)
    parser.add_argument("--atr-stop-multiplier", type=float, default=5.0)
    parser.add_argument("--take-profit-pct", type=float, default=1.0)
    parser.add_argument("--trailing-stop-trigger", type=float, default=0.3)
    parser.add_argument("--trailing-stop-atr", type=float, default=3.5)
    parser.add_argument("--defense-market-breadth-ma20", type=float, default=None)
    parser.add_argument("--defense-trailing-stop-trigger", type=float, default=None)
    parser.add_argument("--defense-trailing-stop-atr", type=float, default=None)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--min-score", type=float, default=0.62)
    parser.add_argument("--allowed-signal-regimes", default="bull,neutral,recovery")
    parser.add_argument("--min-market-breadth-ma20", type=float, default=0.42)
    parser.add_argument("--min-market-positive-return-5", type=float, default=0.22)
    parser.add_argument("--max-market-volatility-20", type=float, default=0.055)
    parser.add_argument("--momentum-weight", type=float, default=0.08)
    parser.add_argument("--long-momentum-weight", type=float, default=0.55)
    parser.add_argument("--trend-weight", type=float, default=0.25)
    parser.add_argument("--flow-weight", type=float, default=0.04)
    parser.add_argument("--fundamental-weight", type=float, default=0.04)
    parser.add_argument("--low-vol-weight", type=float, default=0.08)
    parser.add_argument("--sentiment-overlay", action="store_true", help="Apply a historical market sentiment proxy to position sizing.")
    parser.add_argument("--sentiment-high-threshold", type=float, default=80.0)
    parser.add_argument("--sentiment-neutral-threshold", type=float, default=60.0)
    parser.add_argument("--sentiment-weak-threshold", type=float, default=45.0)
    parser.add_argument("--sentiment-extreme-threshold", type=float, default=30.0)
    parser.add_argument("--benchmark-symbol", default="0050")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "rank_portfolio")
    parser.add_argument("--simulation-start-date", type=str, default=None, help="If set, only simulate from this date onward (e.g. 2026-06-05). Creates a fresh forward simulation.")
    parser.add_argument("--simulation-end-date", type=str, default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    if args.data == DEFAULT_DATA:
        args.data = setting_path(settings, "paths.processed_features", DEFAULT_DATA)
    if args.output_dir == ROOT / "results" / "rank_portfolio":
        args.output_dir = setting_path(settings, "paths.official_rank_dir", args.output_dir)
    settings["trading"]["initial_capital"] = float(args.capital)
    settings["trading"]["min_trade_unit"] = int(args.min_trade_unit)
    settings["trading"]["holding_period_max"] = int(args.holding_period_max)
    settings["trading"]["market_impact_slippage"] = float(args.market_impact_slippage)
    for arg_name, key in [
        ("atr_stop_multiplier", "atr_stop_multiplier"),
        ("take_profit_pct", "take_profit_pct"),
        ("trailing_stop_trigger", "trailing_stop_trigger"),
        ("trailing_stop_atr", "trailing_stop_atr"),
        ("defense_market_breadth_ma20", "defense_market_breadth_ma20"),
        ("defense_trailing_stop_trigger", "defense_trailing_stop_trigger"),
        ("defense_trailing_stop_atr", "defense_trailing_stop_atr"),
    ]:
        value = getattr(args, arg_name)
        if value is not None:
            settings["risk"][key] = float(value)
    data = _load_data(args.data, None, None)
    data = _lag_monthly_revenue_features(data)
    data = overlay_recent_official_institutional_flow(data)
    scored = _attach_cycles(data, settings)
    allowed_signal_regimes = {item.strip() for item in args.allowed_signal_regimes.split(",") if item.strip()}
    weights = {
        "momentum": args.momentum_weight,
        "long_momentum": args.long_momentum_weight,
        "trend": args.trend_weight,
        "flow": args.flow_weight,
        "fundamental": args.fundamental_weight,
        "low_vol": args.low_vol_weight,
    }
    signals = _make_rank_signals(
        scored,
        args.top_n,
        args.min_score,
        allowed_signal_regimes,
        weights,
        args.min_market_breadth_ma20,
        args.min_market_positive_return_5,
        args.max_market_volatility_20,
    )
    if args.sentiment_overlay:
        signals = _build_sentiment_overlay(
            signals,
            args.sentiment_high_threshold,
            args.sentiment_neutral_threshold,
            args.sentiment_weak_threshold,
            args.sentiment_extreme_threshold,
        )
    # --- Forward simulation: filter signals to start date ---
    if args.simulation_start_date or args.simulation_end_date:
        signals["date"] = pd.to_datetime(signals["date"])
        if args.simulation_start_date:
            cutoff = pd.Timestamp(args.simulation_start_date)
            signals = signals[signals["date"] >= cutoff].copy()
        if args.simulation_end_date:
            end_cutoff = pd.Timestamp(args.simulation_end_date)
            signals = signals[signals["date"] <= end_cutoff].copy()
        print(
            f"[forward-sim] filtering signals {args.simulation_start_date or '-inf'}..{args.simulation_end_date or '+inf'}, "
            f"{len(signals):,} rows remain",
            file=sys.stderr,
        )

    result = _run_portfolio(
        signals,
        settings,
        args.capital,
        args.target_exposure,
        args.portfolio_max_positions,
        args.portfolio_max_position_pct,
        args.min_trade_unit,
        args.drawdown_block_threshold,
        args.position_sizing,
        args.max_risk_per_trade,
        args.max_correlation,
        args.correlation_lookback,
        args.max_positions_per_industry,
        args.rebalance_trigger,
        args.sentiment_overlay,
        args.enable_replacement,
        args.replacement_threshold,
        args.trailing_stop_sell_pct,
        args.max_entry_volume_pct,
        args.max_entry_notional,
        args.score_sizing_spread,
    )
    perf = _performance(result)
    benchmark_dates = sorted(pd.to_datetime(signals["date"].dropna().unique()))
    benchmark = _benchmark_metrics(data, settings, args.benchmark_symbol, benchmark_dates, args.output_dir / "benchmark_data")
    summary = {
        "performance": perf,
        "benchmark": benchmark,
        "beats_benchmark_cagr": bool(perf["cagr"] > benchmark["cagr"]) if benchmark.get("found") else None,
        "beats_benchmark_sharpe": bool(perf["sharpe"] > benchmark["sharpe"]) if benchmark.get("found") else None,
        "candidate_buy_signals": int(signals["entry_signal"].eq(1).sum()),
        "settings": {
            "capital": args.capital,
            "target_exposure": args.target_exposure,
            "portfolio_max_positions": args.portfolio_max_positions,
            "portfolio_max_position_pct": args.portfolio_max_position_pct,
            "position_sizing": args.position_sizing,
            "max_risk_per_trade": args.max_risk_per_trade,
            "max_correlation": args.max_correlation,
            "correlation_lookback": args.correlation_lookback,
            "max_positions_per_industry": args.max_positions_per_industry,
            "rebalance_trigger": args.rebalance_trigger,
            "max_entry_volume_pct": args.max_entry_volume_pct,
            "max_entry_notional": args.max_entry_notional,
            "score_sizing_spread": args.score_sizing_spread,
            "market_impact_slippage": args.market_impact_slippage,
            "min_trade_unit": args.min_trade_unit,
            "holding_period_max": args.holding_period_max,
            "drawdown_block_threshold": args.drawdown_block_threshold,
            "atr_stop_multiplier": settings["risk"].get("atr_stop_multiplier"),
            "take_profit_pct": settings["risk"].get("take_profit_pct"),
            "trailing_stop_trigger": settings["risk"].get("trailing_stop_trigger"),
            "trailing_stop_atr": settings["risk"].get("trailing_stop_atr"),
            "trailing_stop_sell_pct": args.trailing_stop_sell_pct,
            "defense_market_breadth_ma20": settings["risk"].get("defense_market_breadth_ma20"),
            "defense_trailing_stop_trigger": settings["risk"].get("defense_trailing_stop_trigger"),
            "defense_trailing_stop_atr": settings["risk"].get("defense_trailing_stop_atr"),
            "top_n": args.top_n,
            "min_score": args.min_score,
            "allowed_signal_regimes": sorted(allowed_signal_regimes),
            "min_market_breadth_ma20": args.min_market_breadth_ma20,
            "min_market_positive_return_5": args.min_market_positive_return_5,
            "max_market_volatility_20": args.max_market_volatility_20,
            "weights": weights,
            "sentiment_overlay": {
                "enabled": args.sentiment_overlay,
                "score_components": {
                    "market_breadth_ma20": 0.35,
                    "market_positive_return_5": 0.25,
                    "market_position_52w": 0.25,
                    "inverse_market_volatility_20": 0.15,
                },
                "thresholds": {
                    "high": args.sentiment_high_threshold,
                    "neutral": args.sentiment_neutral_threshold,
                    "weak": args.sentiment_weak_threshold,
                    "extreme": args.sentiment_extreme_threshold,
                },
            },
            "risk": settings.get("risk", {}),
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    summary_path = args.output_dir / "rank_portfolio_summary.json"
    equity_path = args.output_dir / "rank_portfolio_equity.csv"
    trades_path = args.output_dir / "rank_portfolio_trades.csv"
    buys_path = args.output_dir / "rank_portfolio_buys.csv"
    signals_path = args.output_dir / "rank_portfolio_signals.csv"
    positions_path = args.output_dir / "rank_portfolio_positions.csv"
    result["equity_curve"].to_csv(equity_path, index=False, encoding="utf-8-sig")
    result["trade_log"].to_csv(trades_path, index=False, encoding="utf-8-sig")
    result["buy_log"].to_csv(buys_path, index=False, encoding="utf-8-sig")
    result["open_positions"].to_csv(positions_path, index=False, encoding="utf-8-sig")
    
    if args.simulation_start_date:
        start_date_str = pd.to_datetime(args.simulation_start_date).strftime("%Y%m%d")
        capital_str = f"{int(args.capital / 1_000_000)}M" if args.capital % 1_000_000 == 0 else str(int(args.capital))
        custom_trades_path = args.output_dir / f"{start_date_str}_{capital_str}.csv"
        result["trade_log"].to_csv(custom_trades_path, index=False, encoding="utf-8-sig")
        print(f"[saved custom trades] {custom_trades_path}")
    signal_cols = [
        "date",
        "symbol",
        "market_regime",
        "entry_signal",
        "signal_tier",
        "strategy_score",
        "rank_signal_score",
        "close",
        "open",
        "atr_14",
        "market_breadth_ma20",
        "market_positive_return_5",
        "market_volatility_20",
        "market_position_52w",
        "sentiment_score",
        "sentiment_label",
        "sentiment_position_multiplier",
        "sentiment_max_positions_multiplier",
        "sentiment_target_exposure_multiplier",
        "sentiment_block_entries",
    ]
    signals.loc[:, [col for col in signal_cols if col in signals.columns]].to_csv(signals_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(f"[rank] cagr={perf['cagr']:.2%} sharpe={perf['sharpe']:.3f} max_dd={perf['max_drawdown']:.2%}")
    print(f"[rank] utilization={perf['mean_capital_utilization']:.2%} trades={perf['trades']:.0f}")
    print(f"[saved] {summary_path}")
    print(f"[saved] {positions_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
