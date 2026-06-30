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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_cycle_strategy_wfa import (  # noqa: E402
    _apply_selected_strategies,
    _attach_cycles,
    _attach_forward_return,
    _load_data,
    _rank_metrics,
    _select_strategies,
)
from src.config import load_settings  # noqa: E402
from src.strategy_catalog import StrategySpec, add_strategy_ranks, build_strategy_catalog, strategy_signal  # noqa: E402


DEFAULT_DATA = ROOT.parent / "data" / "processed" / "all_features.csv"


BEST_FILTERS = {
    "min_strategy_score": 0.12,
    "min_market_breadth_ma20_chg5": -0.02,
    "min_market_positive_return_5_chg5": 0.0,
}


DEFAULT_RISK_FALLBACK = {
    "max_risk_per_trade": 0.0025,
    "max_position_pct": 0.03,
    "max_positions": 3,
    "atr_stop_multiplier": 5.0,
    "take_profit_pct": 1.0,
    "trailing_stop_trigger": 0.30,
    "trailing_stop_atr": 3.5,
}


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
    return settings


def _resolve_signal_date(data: pd.DataFrame, requested: str) -> pd.Timestamp:
    dates = sorted(pd.to_datetime(data["date"].dropna().unique()))
    if not dates:
        raise ValueError("No dates found in data.")
    if requested.lower() == "latest":
        return pd.Timestamp(dates[-1])
    target = pd.Timestamp(requested)
    eligible = [date for date in dates if pd.Timestamp(date) <= target]
    if not eligible:
        raise ValueError(f"No available data on or before {target.date()}.")
    return pd.Timestamp(eligible[-1])


def _training_slice(data: pd.DataFrame, signal_date: pd.Timestamp, forward_days: int, in_sample_days: int) -> pd.DataFrame:
    dates = sorted(pd.to_datetime(data.loc[data["date"] <= signal_date, "date"].dropna().unique()))
    signal_pos = dates.index(signal_date)
    train_end_pos = signal_pos - forward_days
    if train_end_pos <= 0:
        raise ValueError("Not enough history before signal date to build a leakage-safe training slice.")
    train_dates = dates[max(0, train_end_pos - in_sample_days + 1) : train_end_pos + 1]
    return data[data["date"].isin(train_dates)].copy()


def _strategy_descriptions(selected: pd.DataFrame, selected_ids: str) -> str:
    if not selected_ids:
        return ""
    desc_by_id = selected.drop_duplicates("strategy_id").set_index("strategy_id")["description"].to_dict()
    descriptions = []
    for strategy_id in str(selected_ids).split("|"):
        description = desc_by_id.get(strategy_id, "")
        if description:
            descriptions.append(f"{strategy_id}: {description}")
        else:
            descriptions.append(strategy_id)
    return " || ".join(descriptions)


def _strategy_families(selected: pd.DataFrame, selected_ids: str) -> str:
    if not selected_ids:
        return ""
    family_by_id = selected.drop_duplicates("strategy_id").set_index("strategy_id")["family"].to_dict()
    families = []
    for strategy_id in str(selected_ids).split("|"):
        family = family_by_id.get(strategy_id, "")
        if family and family not in families:
            families.append(family)
    return "|".join(families)


def _select_family_sleeves(
    train_df: pd.DataFrame,
    catalog: list[StrategySpec],
    min_signals: int,
    min_edge_score: float,
    min_positive_cycle_ratio: float,
    min_cycle_count: int,
    allowed_regimes: set[str] | None,
    top_per_family: int,
) -> pd.DataFrame:
    rows = []
    for spec in catalog:
        metrics = _rank_metrics(strategy_signal(train_df, spec), train_df, min_signals)
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
    ranked = ranked.sort_values(
        ["market_regime", "family", "robust_score", "edge_score"],
        ascending=[True, True, False, False],
    )
    ranked = ranked.groupby(["market_regime", "family"]).head(top_per_family).reset_index(drop=True)
    return ranked.sort_values(["market_regime", "robust_score", "edge_score"], ascending=[True, False, False]).reset_index(drop=True)


def _merge_selected(primary: pd.DataFrame, sleeves: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in [primary, sleeves] if not frame.empty]
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values(["market_regime", "robust_score", "edge_score"], ascending=[True, False, False])
    return merged.drop_duplicates(["market_regime", "strategy_id"]).reset_index(drop=True)


def _make_candidates(
    scored: pd.DataFrame,
    selected: pd.DataFrame,
    spec_by_id: dict[str, Any],
    signal_date: pd.Timestamp,
    signal_filters: dict[str, Any],
    include_watchlist: bool,
) -> pd.DataFrame:
    core = _apply_selected_strategies(scored, selected, spec_by_id, min_selected_votes=2, signal_filters=signal_filters)
    expansion_filters = dict(signal_filters)
    expansion_filters["allowed_signal_regimes"] = ["bull"]
    expansion = _apply_selected_strategies(
        scored,
        selected,
        spec_by_id,
        min_selected_votes=1,
        signal_filters=expansion_filters,
    )
    latest_core = core[core["date"].eq(signal_date)].copy()
    latest_expansion = expansion[expansion["date"].eq(signal_date)].copy()

    core_symbols = set(latest_core.loc[latest_core["entry_signal"].eq(1), "symbol"].astype(str))
    latest_core.loc[latest_core["entry_signal"].eq(1), "signal_tier"] = "core"
    latest_expansion.loc[
        latest_expansion["entry_signal"].eq(1) & ~latest_expansion["symbol"].astype(str).isin(core_symbols),
        "signal_tier",
    ] = "expansion"

    combined = pd.concat(
        [
            latest_core[latest_core.get("signal_tier", "").eq("core")],
            latest_expansion[latest_expansion.get("signal_tier", "").eq("expansion")],
        ],
        ignore_index=True,
    )
    if combined.empty:
        if not include_watchlist:
            return combined
        watch = latest_expansion.sort_values(
            ["strategy_score", "selected_strategy_count", "volume_ratio_20"],
            ascending=[False, False, False],
        ).head(30)
        watch = watch.copy()
        watch["signal_tier"] = "watch"
        combined = watch

    combined["strategy_descriptions"] = combined["selected_strategy_ids"].apply(lambda value: _strategy_descriptions(selected, value))
    combined["selected_families"] = combined["selected_strategy_ids"].apply(lambda value: _strategy_families(selected, value))
    combined["primary_family"] = combined["selected_families"].astype(str).str.split("|").str[0].fillna("")
    combined["tier_rank"] = combined["signal_tier"].map({"core": 0, "expansion": 1, "watch": 2}).fillna(9)
    combined = combined.sort_values(
        ["tier_rank", "strategy_score", "selected_strategy_count", "volume_ratio_20"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)
    return combined


def _round_shares(raw_shares: float, lot: int) -> int:
    if raw_shares <= 0:
        return 0
    return int(raw_shares // lot) * lot


def _allocate(
    candidates: pd.DataFrame,
    capital: float,
    target_exposure: float,
    max_positions: int,
    max_position_pct: float,
    min_trade_unit: int,
    max_per_family: int,
    risk: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    actionable = candidates[candidates.get("signal_tier", pd.Series(index=candidates.index, dtype=str)).isin(["core", "expansion"])].copy()
    rows = []
    cash_left = float(capital)
    target_notional = float(capital) * float(target_exposure)
    allocated = 0.0
    selected_count = 0
    family_counts: dict[str, int] = {}

    for row in actionable.itertuples(index=False):
        if selected_count >= max_positions or allocated >= target_notional:
            break
        family = str(getattr(row, "primary_family", "") or "unknown")
        if max_per_family > 0 and family_counts.get(family, 0) >= max_per_family:
            continue
        price = float(getattr(row, "close", np.nan))
        if not np.isfinite(price) or price <= 0:
            continue
        desired_notional = min(capital * max_position_pct, target_notional - allocated, cash_left)
        shares = _round_shares(desired_notional / price, min_trade_unit)
        notional = shares * price
        if shares <= 0 or notional <= 0:
            continue
        cash_left -= notional
        allocated += notional
        selected_count += 1
        family_counts[family] = family_counts.get(family, 0) + 1
        atr = float(getattr(row, "atr_14", np.nan))
        stop_loss = price - atr * float(risk.get("atr_stop_multiplier", DEFAULT_RISK_FALLBACK["atr_stop_multiplier"])) if np.isfinite(atr) else np.nan
        take_profit = price * (1 + float(risk.get("take_profit_pct", DEFAULT_RISK_FALLBACK["take_profit_pct"])))
        rows.append(
            {
                "rank": selected_count,
                "date": getattr(row, "date"),
                "symbol": str(getattr(row, "symbol")),
                "tier": getattr(row, "signal_tier", ""),
                "primary_family": family,
                "close": price,
                "shares": shares,
                "notional": notional,
                "portfolio_pct": notional / capital,
                "strategy_score": float(getattr(row, "strategy_score", 0.0)),
                "selected_strategy_count": int(getattr(row, "selected_strategy_count", 0)),
                "market_regime": getattr(row, "market_regime", ""),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "trailing_trigger_price": price * (1 + float(risk.get("trailing_stop_trigger", DEFAULT_RISK_FALLBACK["trailing_stop_trigger"]))),
                "selected_strategy_ids": getattr(row, "selected_strategy_ids", ""),
                "selected_families": getattr(row, "selected_families", ""),
                "strategy_descriptions": getattr(row, "strategy_descriptions", ""),
            }
        )

    allocation = pd.DataFrame(rows)
    summary = {
        "capital": float(capital),
        "target_exposure": float(target_exposure),
        "allocated_notional": float(allocated),
        "cash_left": float(cash_left),
        "capital_utilization": float(allocated / capital) if capital else 0.0,
        "positions": int(len(allocation)),
        "max_positions": int(max_positions),
        "max_position_pct": float(max_position_pct),
        "min_trade_unit": int(min_trade_unit),
        "max_per_family": int(max_per_family),
        "family_counts": family_counts,
        "actionable_candidates": int(len(actionable)),
    }
    return allocation, summary


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate daily multi-strategy stock-picking signals.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--date", default="latest")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--target-exposure", type=float, default=0.80)
    parser.add_argument("--portfolio-max-positions", type=int, default=8)
    parser.add_argument("--portfolio-max-position-pct", type=float, default=0.10)
    parser.add_argument("--max-per-family", type=int, default=0)
    parser.add_argument("--round-lot-unit", type=int, default=1000)
    parser.add_argument("--odd-lot-unit", type=int, default=1)
    parser.add_argument("--max-strategies", type=int, default=996)
    parser.add_argument("--forward-days", type=int, default=15)
    parser.add_argument("--in-sample-days", type=int, default=480)
    parser.add_argument("--min-signals", type=int, default=200)
    parser.add_argument("--top-per-regime", type=int, default=2)
    parser.add_argument("--sleeve-top-per-family", type=int, default=1)
    parser.add_argument("--min-edge-score", type=float, default=0.05)
    parser.add_argument("--min-positive-cycle-ratio", type=float, default=0.60)
    parser.add_argument("--min-cycle-count", type=int, default=3)
    parser.add_argument("--allowed-regimes", default="bull,recovery")
    parser.add_argument("--allowed-signal-regimes", default="")
    parser.add_argument("--include-watchlist", action="store_true")
    parser.add_argument("--min-strategy-score", type=float, default=None)
    parser.add_argument("--min-market-breadth-ma20-chg5", type=float, default=None)
    parser.add_argument("--min-market-positive-return-5-chg5", type=float, default=None)
    parser.add_argument("--max-market-volatility-20", type=float, default=None)
    parser.add_argument("--max-recent-weak-5", type=float, default=None)
    parser.add_argument("--max-recent-weak-10", type=float, default=None)
    parser.add_argument("--max-recent-weak-20", type=float, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "daily_signals")
    args = parser.parse_args()

    settings = _normalize_settings(load_settings(args.config))
    data = _load_data(args.data, None, None)
    signal_date = _resolve_signal_date(data, args.date)
    train = _training_slice(data, signal_date, args.forward_days, args.in_sample_days)
    train_scored = add_strategy_ranks(_attach_cycles(_attach_forward_return(train, args.forward_days), settings))
    signal_history = data[data["date"] <= signal_date].copy()
    scored = add_strategy_ranks(_attach_cycles(signal_history, settings))

    catalog = build_strategy_catalog(args.max_strategies or None)
    spec_by_id = {spec.strategy_id: spec for spec in catalog}
    allowed_regimes = {item.strip() for item in args.allowed_regimes.split(",") if item.strip()} or None
    signal_filters = _signal_filters_from_args(args)
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

    candidates = _make_candidates(scored, selected, spec_by_id, signal_date, signal_filters, args.include_watchlist)
    output_columns = [
        "date",
        "symbol",
        "signal_tier",
        "market_regime",
        "close",
        "volume",
        "volume_ratio_20",
        "atr_14",
        "strategy_score",
        "selected_strategy_count",
        "selected_strategy_ids",
        "selected_families",
        "primary_family",
        "strategy_descriptions",
        "market_breadth_ma20",
        "market_breadth_ma60",
        "market_positive_return_5",
        "market_position_52w",
        "market_breadth_ma20_chg5",
        "market_positive_return_5_chg5",
        "position_in_52w_range",
        "close_return_5",
        "close_return_10",
        "rolling_volatility_20",
    ]
    available_output_columns = [column for column in output_columns if column in candidates.columns]
    candidates_out = candidates[available_output_columns].copy()

    round_allocation, round_summary = _allocate(
        candidates,
        args.capital,
        args.target_exposure,
        args.portfolio_max_positions,
        args.portfolio_max_position_pct,
        args.round_lot_unit,
        args.max_per_family,
        settings.get("risk", {}),
    )
    odd_allocation, odd_summary = _allocate(
        candidates,
        args.capital,
        args.target_exposure,
        args.portfolio_max_positions,
        args.portfolio_max_position_pct,
        args.odd_lot_unit,
        args.max_per_family,
        settings.get("risk", {}),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    date_tag = signal_date.strftime("%Y%m%d")
    selected_path = args.output_dir / f"daily_selected_strategies_{date_tag}_{stamp}.csv"
    candidates_path = args.output_dir / f"daily_candidates_{date_tag}_{stamp}.csv"
    round_path = args.output_dir / f"daily_allocation_roundlot_{date_tag}_{stamp}.csv"
    odd_path = args.output_dir / f"daily_allocation_oddlot_{date_tag}_{stamp}.csv"
    summary_path = args.output_dir / f"daily_signal_summary_{date_tag}_{stamp}.json"

    selected.to_csv(selected_path, index=False, encoding="utf-8-sig")
    candidates_out.to_csv(candidates_path, index=False, encoding="utf-8-sig")
    round_allocation.to_csv(round_path, index=False, encoding="utf-8-sig")
    odd_allocation.to_csv(odd_path, index=False, encoding="utf-8-sig")
    payload = {
        "signal_date": signal_date,
        "data": str(args.data),
        "train_start": train["date"].min(),
        "train_end": train["date"].max(),
        "candidate_count": int(len(candidates_out)),
        "selected_strategy_count": int(len(selected)),
        "primary_selected_strategy_count": int(len(primary_selected)),
        "sleeve_selected_strategy_count": int(len(sleeve_selected)),
        "round_lot": round_summary,
        "odd_lot": odd_summary,
        "settings": {
            "strategy_selection": {
                "max_strategies": args.max_strategies,
                "forward_days": args.forward_days,
                "in_sample_days": args.in_sample_days,
                "min_signals": args.min_signals,
                "top_per_regime": args.top_per_regime,
                "sleeve_top_per_family": args.sleeve_top_per_family,
                "min_edge_score": args.min_edge_score,
                "min_positive_cycle_ratio": args.min_positive_cycle_ratio,
                "min_cycle_count": args.min_cycle_count,
                "allowed_regimes": sorted(allowed_regimes) if allowed_regimes else [],
            },
            "signal_filters": signal_filters,
            "risk": settings.get("risk", {}),
            "portfolio": {
                "capital": args.capital,
                "target_exposure": args.target_exposure,
                "portfolio_max_positions": args.portfolio_max_positions,
                "portfolio_max_position_pct": args.portfolio_max_position_pct,
                "max_per_family": args.max_per_family,
            },
        },
        "outputs": {
            "selected_strategies": str(selected_path),
            "candidates": str(candidates_path),
            "round_lot_allocation": str(round_path),
            "odd_lot_allocation": str(odd_path),
        },
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

    print(f"[daily] signal_date={signal_date.date()} candidates={len(candidates_out)} selected_strategies={len(selected)}")
    print(
        "[daily] round_lot utilization="
        f"{round_summary['capital_utilization']:.2%} positions={round_summary['positions']} "
        f"actionable={round_summary['actionable_candidates']}"
    )
    print(
        "[daily] odd_lot utilization="
        f"{odd_summary['capital_utilization']:.2%} positions={odd_summary['positions']} "
        f"actionable={odd_summary['actionable_candidates']}"
    )
    print(f"[saved] {summary_path}")
    print(f"[saved] {candidates_path}")
    print(f"[saved] {round_path}")
    print(f"[saved] {odd_path}")


if __name__ == "__main__":
    main()
