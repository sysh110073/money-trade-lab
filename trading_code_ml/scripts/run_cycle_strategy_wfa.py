from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtester import Backtester
from src.config import load_settings
from src.regime import market_regime_by_date
from src.strategy_catalog import StrategySpec, add_strategy_ranks, build_strategy_catalog, strategy_signal


DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "processed" / "all_features.csv"


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    return str(value)


def _load_data(path: Path, max_symbols: int | None, max_rows: int | None) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df["symbol"] = df["symbol"].astype(str)
    df = df.sort_values(["date", "symbol"]).reset_index(drop=True)
    if max_symbols is not None and max_symbols > 0:
        symbols = sorted(df["symbol"].dropna().unique().tolist())[:max_symbols]
        df = df[df["symbol"].isin(symbols)].copy()
    if max_rows is not None and max_rows > 0 and len(df) > max_rows:
        df = df.tail(max_rows).copy()
    return df.reset_index(drop=True)


def _apply_risk_overrides(
    settings: dict[str, Any],
    max_risk_per_trade: float | None,
    max_position_pct: float | None,
    max_positions: int | None,
    drawdown_soft_limit: float | None,
) -> dict[str, Any]:
    settings["risk"] = dict(settings.get("risk", {}))
    if max_risk_per_trade is not None:
        settings["risk"]["max_risk_per_trade"] = float(max_risk_per_trade)
    if max_position_pct is not None:
        settings["risk"]["max_position_pct"] = float(max_position_pct)
    if max_positions is not None:
        settings["risk"]["max_positions"] = int(max_positions)
    if drawdown_soft_limit is not None:
        settings["risk"]["drawdown_soft_limit"] = float(drawdown_soft_limit)
    return settings


def _attach_forward_return(data: pd.DataFrame, forward_days: int) -> pd.DataFrame:
    frame = data.sort_values(["symbol", "date"]).copy()
    future_close = frame.groupby("symbol")["close"].shift(-forward_days)
    frame["eval_return"] = future_close / pd.to_numeric(frame["close"], errors="coerce") - 1
    return frame


def _attach_cycles(data: pd.DataFrame, settings: dict[str, Any]) -> pd.DataFrame:
    daily = market_regime_by_date(data, settings).sort_values("date").reset_index(drop=True)
    daily["prev_regime"] = daily["market_regime"].shift(1)
    daily["cycle_id"] = (daily["market_regime"] != daily["prev_regime"]).cumsum().astype(int)
    daily["cycle_day"] = daily.groupby("cycle_id").cumcount() + 1
    daily["weak_regime"] = daily["market_regime"].isin(["bear", "high_vol"]).astype(int)
    daily["recent_weak_5"] = daily["weak_regime"].rolling(5, min_periods=1).max()
    daily["recent_weak_10"] = daily["weak_regime"].rolling(10, min_periods=1).max()
    daily["recent_weak_20"] = daily["weak_regime"].rolling(20, min_periods=1).max()
    for column in [
        "market_breadth_ma20",
        "market_breadth_ma60",
        "market_positive_return_5",
        "market_volatility_20",
        "market_position_52w",
    ]:
        daily[f"{column}_chg5"] = daily[column].diff(5)
        daily[f"{column}_chg20"] = daily[column].diff(20)
    keep_cols = [
        "date",
        "market_regime",
        "regime_allowed",
        "market_symbol_count",
        "market_breadth_ma20",
        "market_breadth_ma60",
        "market_positive_return_5",
        "market_volatility_20",
        "market_position_52w",
        "cycle_id",
        "cycle_day",
        "weak_regime",
        "recent_weak_5",
        "recent_weak_10",
        "recent_weak_20",
        "market_breadth_ma20_chg5",
        "market_breadth_ma60_chg5",
        "market_positive_return_5_chg5",
        "market_volatility_20_chg5",
        "market_position_52w_chg5",
        "market_breadth_ma20_chg20",
        "market_breadth_ma60_chg20",
        "market_positive_return_5_chg20",
        "market_volatility_20_chg20",
        "market_position_52w_chg20",
    ]
    return data.merge(daily[keep_cols], on="date", how="left")


def _passes_optional_filters(data: pd.DataFrame, filters: dict[str, Any]) -> pd.Series:
    mask = pd.Series(True, index=data.index)
    numeric_bounds = {
        "min_strategy_score": ("strategy_score", ">="),
        "min_market_breadth_ma20": ("market_breadth_ma20", ">="),
        "min_market_breadth_ma60": ("market_breadth_ma60", ">="),
        "min_market_positive_return_5": ("market_positive_return_5", ">="),
        "min_market_position_52w": ("market_position_52w", ">="),
        "min_market_breadth_ma20_chg5": ("market_breadth_ma20_chg5", ">="),
        "min_market_breadth_ma60_chg5": ("market_breadth_ma60_chg5", ">="),
        "min_market_positive_return_5_chg5": ("market_positive_return_5_chg5", ">="),
        "min_market_breadth_ma20_chg20": ("market_breadth_ma20_chg20", ">="),
        "min_market_breadth_ma60_chg20": ("market_breadth_ma60_chg20", ">="),
        "min_cycle_day": ("cycle_day", ">="),
        "max_cycle_day": ("cycle_day", "<="),
        "max_market_volatility_20": ("market_volatility_20", "<="),
        "max_market_volatility_20_chg5": ("market_volatility_20_chg5", "<="),
        "max_market_volatility_20_chg20": ("market_volatility_20_chg20", "<="),
        "max_recent_weak_5": ("recent_weak_5", "<="),
        "max_recent_weak_10": ("recent_weak_10", "<="),
        "max_recent_weak_20": ("recent_weak_20", "<="),
    }
    for filter_name, (column, op) in numeric_bounds.items():
        value = filters.get(filter_name)
        if value is None or column not in data.columns:
            continue
        series = pd.to_numeric(data[column], errors="coerce")
        if op == ">=":
            mask &= series >= float(value)
        else:
            mask &= series <= float(value)
    allowed_signal_regimes = filters.get("allowed_signal_regimes")
    if allowed_signal_regimes:
        mask &= data["market_regime"].astype(str).isin(set(allowed_signal_regimes))
    return mask.fillna(False)


def _rank_metrics(signal: pd.Series, data: pd.DataFrame, min_signals: int) -> pd.DataFrame:
    frame = data.loc[signal.fillna(False), ["market_regime", "cycle_id", "eval_return"]].copy()
    frame["eval_return"] = pd.to_numeric(frame["eval_return"], errors="coerce")
    frame = frame.dropna(subset=["eval_return"])
    if frame.empty:
        return pd.DataFrame()
    out = (
        frame.groupby("market_regime")
        .agg(
            signals=("eval_return", "size"),
            mean_return=("eval_return", "mean"),
            hit_rate=("eval_return", lambda x: float((x > 0).mean())),
            p10_return=("eval_return", lambda x: float(x.quantile(0.10))),
        )
        .reset_index()
    )
    out = out[out["signals"] >= min_signals].copy()
    if out.empty:
        return out
    out["edge_score"] = out["mean_return"] * np.sqrt(out["signals"]) * (out["hit_rate"] - 0.5)
    cycle_stats = (
        frame.groupby(["market_regime", "cycle_id"])
        .agg(cycle_mean_return=("eval_return", "mean"), cycle_signals=("eval_return", "size"))
        .reset_index()
    )
    cycle_summary = (
        cycle_stats.groupby("market_regime")
        .agg(
            cycle_count=("cycle_id", "nunique"),
            positive_cycle_ratio=("cycle_mean_return", lambda x: float((x > 0).mean())),
            median_cycle_return=("cycle_mean_return", "median"),
        )
        .reset_index()
    )
    out = out.merge(cycle_summary, on="market_regime", how="left")
    stability_bonus = np.clip(out["positive_cycle_ratio"].fillna(0.0) - 0.5, 0.0, 0.5) * 2
    out["robust_score"] = out["edge_score"] * stability_bonus
    return out


def _select_strategies(
    train_df: pd.DataFrame,
    catalog: list[StrategySpec],
    min_signals: int,
    top_per_regime: int,
    min_edge_score: float,
    min_positive_cycle_ratio: float,
    min_cycle_count: int,
    allowed_regimes: set[str] | None,
) -> pd.DataFrame:
    rows = []
    for spec in catalog:
        signal = strategy_signal(train_df, spec)
        metrics = _rank_metrics(signal, train_df, min_signals)
        if metrics.empty:
            continue
        metrics["strategy_id"] = spec.strategy_id
        metrics["family"] = spec.family
        metrics["description"] = spec.description
        rows.append(metrics)
    if not rows:
        return pd.DataFrame()
    ranked = pd.concat(rows, ignore_index=True)
    if allowed_regimes:
        ranked = ranked[ranked["market_regime"].astype(str).isin(allowed_regimes)].copy()
    ranked = ranked[
        (ranked["edge_score"] >= min_edge_score)
        & (ranked["positive_cycle_ratio"].fillna(0.0) >= min_positive_cycle_ratio)
        & (ranked["cycle_count"].fillna(0).astype(int) >= min_cycle_count)
    ].copy()
    if ranked.empty:
        return ranked
    ranked = ranked.sort_values(["market_regime", "robust_score", "edge_score"], ascending=[True, False, False])
    return ranked.groupby("market_regime").head(top_per_regime).reset_index(drop=True)


def _apply_selected_strategies(
    oos_df: pd.DataFrame,
    selected: pd.DataFrame,
    spec_by_id: dict[str, StrategySpec],
    min_selected_votes: int = 1,
    signal_filters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    data = oos_df.copy()
    data["signal"] = 0
    data["entry_signal"] = 0
    data["exit_signal"] = 0
    data["signal_reason"] = ""
    data["strategy_score"] = 0.0
    data["selected_strategy_count"] = 0
    data["selected_strategy_ids"] = ""
    if selected.empty:
        return data

    selected_ids = set(selected["strategy_id"].astype(str))
    signal_cache: dict[str, pd.Series] = {}
    for strategy_id in selected_ids:
        spec = spec_by_id.get(strategy_id)
        if spec is None:
            continue
        signal_cache[strategy_id] = strategy_signal(data, spec).fillna(False).astype(bool)

    for regime, group in selected.groupby("market_regime"):
        regime_mask = data["market_regime"].astype(str).eq(str(regime))
        for rank, (_, row) in enumerate(group.iterrows(), start=1):
            strategy_id = str(row["strategy_id"])
            sig = signal_cache.get(strategy_id)
            if sig is None:
                continue
            hit = regime_mask & sig
            score = float(row.get("edge_score", 0.0)) / max(rank, 1)
            data.loc[hit, "selected_strategy_count"] += 1
            data.loc[hit, "strategy_score"] += score
            prior = data.loc[hit, "selected_strategy_ids"].astype(str)
            data.loc[hit, "selected_strategy_ids"] = np.where(prior.eq(""), strategy_id, prior + "|" + strategy_id)

    entry = data["selected_strategy_count"] >= max(1, int(min_selected_votes))
    if signal_filters:
        entry &= _passes_optional_filters(data, signal_filters)
    data.loc[entry, "signal"] = 1
    data.loc[entry, "entry_signal"] = 1
    data.loc[entry, "signal_reason"] = "cycle_strategy"
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward test cycle-specific strategy selection.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--max-strategies", type=int, default=996)
    parser.add_argument("--forward-days", type=int, default=15)
    parser.add_argument("--min-signals", type=int, default=200)
    parser.add_argument("--top-per-regime", type=int, default=3)
    parser.add_argument("--min-edge-score", type=float, default=0.0)
    parser.add_argument("--min-positive-cycle-ratio", type=float, default=0.52)
    parser.add_argument("--min-cycle-count", type=int, default=3)
    parser.add_argument("--min-selected-votes", type=int, default=1)
    parser.add_argument("--allowed-regimes", default="")
    parser.add_argument("--max-risk-per-trade", type=float, default=None)
    parser.add_argument("--max-position-pct", type=float, default=None)
    parser.add_argument("--max-positions", type=int, default=None)
    parser.add_argument("--drawdown-soft-limit", type=float, default=None)
    parser.add_argument("--atr-stop-multiplier", type=float, default=None)
    parser.add_argument("--take-profit-pct", type=float, default=None)
    parser.add_argument("--trailing-stop-trigger", type=float, default=None)
    parser.add_argument("--trailing-stop-atr", type=float, default=None)
    parser.add_argument("--min-strategy-score", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma20", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma60", type=float, default=None)
    parser.add_argument("--min-market-positive-return-5", type=float, default=None)
    parser.add_argument("--min-market-position-52w", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma20-chg5", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma60-chg5", type=float, default=None)
    parser.add_argument("--min-market-positive-return-5-chg5", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma20-chg20", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma60-chg20", type=float, default=None)
    parser.add_argument("--max-market-volatility-20", type=float, default=None)
    parser.add_argument("--max-market-volatility-20-chg5", type=float, default=None)
    parser.add_argument("--max-market-volatility-20-chg20", type=float, default=None)
    parser.add_argument("--max-recent-weak-5", type=float, default=None)
    parser.add_argument("--max-recent-weak-10", type=float, default=None)
    parser.add_argument("--max-recent-weak-20", type=float, default=None)
    parser.add_argument("--min-cycle-day", type=int, default=None)
    parser.add_argument("--max-cycle-day", type=int, default=None)
    parser.add_argument("--allowed-signal-regimes", default="")
    parser.add_argument("--in-sample-days", type=int, default=None)
    parser.add_argument("--out-sample-days", type=int, default=None)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()

    settings = _apply_risk_overrides(
        load_settings(args.config),
        args.max_risk_per_trade,
        args.max_position_pct,
        args.max_positions,
        args.drawdown_soft_limit,
    )
    for arg_name, key in [
        ("atr_stop_multiplier", "atr_stop_multiplier"),
        ("take_profit_pct", "take_profit_pct"),
        ("trailing_stop_trigger", "trailing_stop_trigger"),
        ("trailing_stop_atr", "trailing_stop_atr"),
    ]:
        value = getattr(args, arg_name)
        if value is not None:
            settings["risk"][key] = float(value)
    wfa_cfg = settings["wfa"]
    is_days = int(args.in_sample_days or wfa_cfg["in_sample_days"])
    oos_days = int(args.out_sample_days or wfa_cfg["out_sample_days"])
    step_days = int(args.step_days or wfa_cfg["step_days"])
    data = _load_data(args.data, args.max_symbols or None, args.max_rows or None)
    catalog = build_strategy_catalog(args.max_strategies or None)
    spec_by_id = {spec.strategy_id: spec for spec in catalog}
    unique_dates = sorted(pd.to_datetime(data["date"].dropna().unique()))
    backtester = Backtester(settings)
    allowed_regimes = {item.strip() for item in args.allowed_regimes.split(",") if item.strip()} or None
    signal_filters = {
        "min_strategy_score": args.min_strategy_score,
        "min_market_breadth_ma20": args.min_market_breadth_ma20,
        "min_market_breadth_ma60": args.min_market_breadth_ma60,
        "min_market_positive_return_5": args.min_market_positive_return_5,
        "min_market_position_52w": args.min_market_position_52w,
        "min_market_breadth_ma20_chg5": args.min_market_breadth_ma20_chg5,
        "min_market_breadth_ma60_chg5": args.min_market_breadth_ma60_chg5,
        "min_market_positive_return_5_chg5": args.min_market_positive_return_5_chg5,
        "min_market_breadth_ma20_chg20": args.min_market_breadth_ma20_chg20,
        "min_market_breadth_ma60_chg20": args.min_market_breadth_ma60_chg20,
        "max_market_volatility_20": args.max_market_volatility_20,
        "max_market_volatility_20_chg5": args.max_market_volatility_20_chg5,
        "max_market_volatility_20_chg20": args.max_market_volatility_20_chg20,
        "max_recent_weak_5": args.max_recent_weak_5,
        "max_recent_weak_10": args.max_recent_weak_10,
        "max_recent_weak_20": args.max_recent_weak_20,
        "min_cycle_day": args.min_cycle_day,
        "max_cycle_day": args.max_cycle_day,
        "allowed_signal_regimes": [item.strip() for item in args.allowed_signal_regimes.split(",") if item.strip()],
    }
    signal_filters = {key: value for key, value in signal_filters.items() if value not in (None, [])}

    rows = []
    selected_rows = []
    pred_rows = []
    start = 0
    window = 0
    while start + is_days + oos_days <= len(unique_dates):
        is_dates = unique_dates[start : start + is_days]
        oos_dates = unique_dates[start + is_days : start + is_days + oos_days]
        train_df = _attach_forward_return(data[data["date"].isin(is_dates)].copy(), args.forward_days)
        oos_df = data[data["date"].isin(oos_dates)].copy()
        if train_df.empty or oos_df.empty:
            start += step_days
            continue

        print(
            f"[cycle-wfa] window={window} "
            f"is={pd.Timestamp(is_dates[0]).date()}..{pd.Timestamp(is_dates[-1]).date()} "
            f"oos={pd.Timestamp(oos_dates[0]).date()}..{pd.Timestamp(oos_dates[-1]).date()}",
            flush=True,
        )
        started = time.perf_counter()
        train_scored = add_strategy_ranks(_attach_cycles(train_df, settings))
        oos_scored = add_strategy_ranks(_attach_cycles(oos_df, settings))
        selected = _select_strategies(
            train_scored,
            catalog,
            args.min_signals,
            args.top_per_regime,
            args.min_edge_score,
            args.min_positive_cycle_ratio,
            args.min_cycle_count,
            allowed_regimes,
        )
        elapsed = time.perf_counter() - started
        if not selected.empty:
            selected["window"] = window
            selected_rows.append(selected)
        signals = _apply_selected_strategies(
            oos_scored,
            selected,
            spec_by_id,
            args.min_selected_votes,
            signal_filters,
        )
        bt = backtester.run(signals)
        perf = backtester.performance_metrics(bt)
        row = {
            "window": window,
            "is_start": pd.Timestamp(is_dates[0]),
            "is_end": pd.Timestamp(is_dates[-1]),
            "oos_start": pd.Timestamp(oos_dates[0]),
            "oos_end": pd.Timestamp(oos_dates[-1]),
            "train_seconds": round(elapsed, 2),
            "selected_strategies": int(len(selected)),
            "buy_signals": int(signals["entry_signal"].eq(1).sum()),
            **{f"perf_{key}": value for key, value in perf.items()},
        }
        rows.append(row)
        pred_rows.append(
            signals[
                [
                    "date",
                    "symbol",
                    "market_regime",
                    "signal",
                    "entry_signal",
                    "strategy_score",
                    "selected_strategy_count",
                    "selected_strategy_ids",
                ]
            ].assign(window=window)
        )
        print(
            f"[cycle-wfa] window={window} return={perf.get('total_return'):.4f} "
            f"sharpe={perf.get('sharpe') if pd.notna(perf.get('sharpe')) else None} "
            f"max_dd={perf.get('max_drawdown'):.4f} trades={perf.get('trades')} "
            f"selected={len(selected)}",
            flush=True,
        )
        window += 1
        start += step_days

    results = pd.DataFrame(rows)
    selected_all = pd.concat(selected_rows, ignore_index=True) if selected_rows else pd.DataFrame()
    predictions = pd.concat(pred_rows, ignore_index=True) if pred_rows else pd.DataFrame()
    summary = {
        "windows": int(len(results)),
        "positive_return_windows": int((results["perf_total_return"] > 0).sum()) if not results.empty else 0,
        "positive_return_ratio": float((results["perf_total_return"] > 0).mean()) if not results.empty else None,
        "mean_return": float(results["perf_total_return"].mean()) if not results.empty else None,
        "median_return": float(results["perf_total_return"].median()) if not results.empty else None,
        "mean_sharpe": float(results["perf_sharpe"].mean()) if "perf_sharpe" in results else None,
        "median_sharpe": float(results["perf_sharpe"].median()) if "perf_sharpe" in results else None,
        "mean_max_drawdown": float(results["perf_max_drawdown"].mean()) if not results.empty else None,
        "max_window_drawdown": float(results["perf_max_drawdown"].max()) if not results.empty else None,
        "total_trades": float(results["perf_trades"].sum()) if not results.empty else 0.0,
        "settings": {
            "in_sample_days": is_days,
            "out_sample_days": oos_days,
            "step_days": step_days,
            "max_strategies": args.max_strategies,
            "forward_days": args.forward_days,
            "min_signals": args.min_signals,
            "top_per_regime": args.top_per_regime,
            "min_edge_score": args.min_edge_score,
            "min_positive_cycle_ratio": args.min_positive_cycle_ratio,
            "min_cycle_count": args.min_cycle_count,
            "min_selected_votes": args.min_selected_votes,
            "allowed_regimes": sorted(allowed_regimes) if allowed_regimes else [],
            "signal_filters": signal_filters,
            "risk": settings.get("risk", {}),
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    result_path = args.output_dir / f"cycle_strategy_wfa_results_{stamp}.csv"
    selected_path = args.output_dir / f"cycle_strategy_wfa_selected_{stamp}.csv"
    pred_path = args.output_dir / f"cycle_strategy_wfa_predictions_{stamp}.csv"
    summary_path = args.output_dir / f"cycle_strategy_wfa_summary_{stamp}.json"
    results.to_csv(result_path, index=False, encoding="utf-8-sig")
    selected_all.to_csv(selected_path, index=False, encoding="utf-8-sig")
    predictions.to_csv(pred_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(f"[saved] {result_path}")
    print(f"[saved] {selected_path}")
    print(f"[saved] {pred_path}")
    print(f"[saved] {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
