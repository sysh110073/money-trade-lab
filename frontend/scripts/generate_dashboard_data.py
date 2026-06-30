from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]
TRADING_ROOT = ROOT / "trading_code_ml"
FRONT_DATA = ROOT / "frontend" / "src" / "data"
DAILY_DIR = ROOT / "trading_code_ml" / "results" / "daily_signals"
OFFICIAL_RANK_DIR = ROOT / "trading_code_ml" / "results" / "rank_portfolio_optimized_risk_long_20pct_norebalance"
FORWARD_SIM_DIR = ROOT / "trading_code_ml" / "results" / "forward_simulation"
BASELINE_RANK_DIR = ROOT / "trading_code_ml" / "results" / "rank_portfolio_baseline_fixed_patch"
BENCHMARK_CACHE_DIR = ROOT / "trading_code_ml" / "results" / "rank_portfolio" / "benchmark_data"
PROCESSED_DATA = ROOT / "data" / "processed" / "all_features.csv"

for item in [ROOT, TRADING_ROOT]:
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from src.config import load_settings, setting_path  # noqa: E402
from src.institutional_overlay import overlay_recent_official_institutional_flow  # noqa: E402
from src.risk_manager import calculate_position_size  # noqa: E402


def configure_paths(args: argparse.Namespace) -> None:
    global FRONT_DATA, OFFICIAL_RANK_DIR, FORWARD_SIM_DIR, PROCESSED_DATA

    settings = load_settings(args.config)
    FRONT_DATA = args.front_data or setting_path(settings, "paths.frontend_data_dir", FRONT_DATA)
    OFFICIAL_RANK_DIR = args.official_rank_dir or setting_path(settings, "paths.official_rank_dir", OFFICIAL_RANK_DIR)
    FORWARD_SIM_DIR = args.forward_sim_dir or setting_path(settings, "paths.forward_sim_dir", FORWARD_SIM_DIR)
    PROCESSED_DATA = args.processed or setting_path(settings, "paths.processed_features", PROCESSED_DATA)


def latest_file(folder: Path, pattern: str) -> Path:
    files = sorted(folder.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No files match {pattern} in {folder}")
    return files[0]


def write_js(path: Path, name: str, payload: dict) -> None:
    path.write_text(
        f"export const {name} = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def portable_path(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    try:
        path = Path(value)
    except (OSError, ValueError):
        return value
    if not path.is_absolute():
        return value
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def public_benchmark(benchmark: dict) -> dict:
    output = dict(benchmark or {})
    for key in ("api_path", "path", "cache_path"):
        if key in output:
            output[key] = portable_path(output[key])
    return output


def build_attribution_data(summary: dict, signals_path: Path, trades_path: Path) -> dict:
    signals = pd.read_csv(signals_path) if signals_path.exists() else pd.DataFrame()
    trades = pd.read_csv(trades_path) if trades_path.exists() else pd.DataFrame()
    gate_keys = [
        "signal_rank_gate",
        "signal_score_gate",
        "signal_regime_gate",
        "signal_breadth_gate",
        "signal_positive_return_gate",
        "signal_volatility_gate",
        "signal_overheat_gate",
        "signal_market_gate",
    ]
    gate_rows = []
    for key in gate_keys:
        if key in signals:
            passed = int(signals[key].fillna(False).sum())
            gate_rows.append({"key": key, "passed": passed, "total": int(len(signals)), "rate": passed / len(signals) if len(signals) else 0.0})
    exit_reasons = []
    if not trades.empty and "exit_reason" in trades:
        for reason, count in trades["exit_reason"].fillna("").value_counts().items():
            exit_reasons.append({"reason": str(reason), "count": int(count)})
    latest_gates = []
    if not signals.empty and "date" in signals:
        latest = signals[signals["date"].astype(str).eq(str(signals["date"].max()))]
        for key in gate_keys:
            if key in latest:
                passed = int(latest[key].fillna(False).sum())
                latest_gates.append({"key": key, "passed": passed, "total": int(len(latest)), "rate": passed / len(latest) if len(latest) else 0.0})
    return {
        "performance": summary.get("performance", {}),
        "benchmark": public_benchmark(summary.get("benchmark", {})),
        "weights": summary.get("settings", {}).get("weights", {}),
        "signalDiagnostics": summary.get("signal_diagnostics", {}),
        "gateRows": gate_rows,
        "latestGateRows": latest_gates,
        "executionStats": summary.get("execution_stats", {}),
        "tca": summary.get("tca", {}),
        "exitReasons": exit_reasons,
    }


def pct_rank_reason(value: float) -> str:
    return f"相對強度排名前 {max(1, round((1 - value) * 100))}%"


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_pct(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator - 1


def replacement_cost_penalty(exit_value: float, entry_value: float, capital: float, settings: dict) -> float:
    scale = float(settings.get("replacement_cost_score_scale", 10.0))
    if scale <= 0 or capital <= 0:
        return 0.0
    commission = float(settings.get("commission_rate", 0.001425))
    tax = float(settings.get("tax_rate", 0.003))
    slippage = float(settings.get("slippage", 0.001))
    exit_cost = max(0.0, exit_value) * (commission + tax + slippage)
    entry_cost = max(0.0, entry_value) * (commission + slippage)
    return (exit_cost + entry_cost) / capital * scale


def stop_risk_flags(row: pd.Series) -> list[str]:
    flags = []
    weak_market = safe_float(row.get("market_breadth_ma20"), 1.0) < 0.50 or safe_float(row.get("market_positive_return_5"), 1.0) < 0.50
    overheated = (
        safe_float(row.get("position_in_52w_range")) > 0.95
        and safe_float(row.get("price_to_ma_20")) > 0.15
        and safe_float(row.get("volume_ratio_20")) > 2.0
    )
    if weak_market and overheated:
        flags.append("weak_market_overheated")
    if str(row.get("market_regime", "")).lower() in {"bear", "high_vol"}:
        flags.append("defensive_regime")
    return flags


def risk_control_label(flags: list[str]) -> str:
    if "weak_market_overheated" in flags:
        return "弱市追高風險，暫緩新倉"
    if "defensive_regime" in flags:
        return "高波動/空方環境，僅觀察"
    return ""


def execution_plan(row: pd.Series, close: float, atr: float, settings: dict) -> dict:
    prev_close = safe_float(row.get("prev_close"))
    ma5 = safe_float(row.get("ma5"))
    ma10 = safe_float(row.get("ma10"))
    ma20 = safe_float(row.get("ma20"))
    limit_up_today = prev_close > 0 and close >= prev_close * 1.095
    extended_from_ma5 = ma5 > 0 and close >= ma5 * 1.035
    above_ma20 = ma20 <= 0 or close >= ma20
    flags = stop_risk_flags(row)
    risk_label = risk_control_label(flags)

    if risk_label:
        status = "風控暫緩"
        tone = "watch"
        action = risk_label
        buy_price = None
        pullback_price = ma20 if ma20 > 0 else close
    elif limit_up_today:
        status = "過熱不追"
        tone = "hot"
        action = "明天先觀察，漲停或大跳空不追"
        buy_price = None
        pullback_price = ma5 or ma10 or close
    elif extended_from_ma5:
        status = "等待回調"
        tone = "wait"
        action = "回到 5MA 附近再買，5 天內沒碰到就放棄"
        pullback_price = ma5
        buy_price = ma5
    elif above_ma20:
        status = "可買入"
        tone = "buy"
        action = "隔日未接近漲停，開盤或小回檔可分批買"
        pullback_price = ma5 if ma5 > 0 else close
        buy_price = close
    else:
        status = "候選觀察"
        tone = "watch"
        action = "趨勢仍在整理，等重新站回 20MA"
        pullback_price = ma20 if ma20 > 0 else close
        buy_price = None

    take_profit_pct = float(settings.get("take_profit_pct", 1.0))
    trailing_trigger_pct = float(settings.get("trailing_stop_trigger", 0.3))
    stop = close - atr * float(settings.get("atr_stop_multiplier", 5.0))
    take_profit = close * (1.0 + take_profit_pct)
    invalid_price = ma20 if ma20 > 0 else stop
    return {
        "executionStatus": status,
        "executionTone": tone,
        "actionLabel": action,
        "buyPrice": buy_price,
        "pullbackPrice": pullback_price,
        "ma5": ma5 or None,
        "ma10": ma10 or None,
        "ma20": ma20 or None,
        "prevClose": prev_close or None,
        "limitUpToday": bool(limit_up_today),
        "stop": stop,
        "takeProfit": take_profit,
        "stopPct": safe_pct(stop, close),
        "takeProfitPct": take_profit_pct,
        "trailingTriggerPct": trailing_trigger_pct,
        "invalidPrice": invalid_price,
        "riskFlags": flags,
        "riskControlLabel": risk_label,
    }


def build_explainability(row: pd.Series) -> tuple[list[str], list[dict]]:
    def val(key: str) -> float:
        return safe_float(row.get(key, 0.0))

    factors = [
        {
            "factor": "Relative Strength",
            "value": (val("rank_close_return_10") + val("rank_position_in_52w_range") + val("rank_price_to_ma_20")) / 3,
            "detail": "10日動能、52週位置與均線乖離綜合排名",
        },
        {
            "factor": "Trend Structure",
            "value": (val("rank_adx_14") + val("rank_price_to_ma_20")) / 2,
            "detail": "ADX 與 MA20 趨勢結構",
        },
        {
            "factor": "Institutional Flow",
            "value": (val("rank_foreign_net_5d_sum") + val("rank_trust_net_5d_sum")) / 2,
            "detail": "外資與投信近5日買超排名",
        },
        {
            "factor": "Volume Expansion",
            "value": (val("rank_volume_ratio_5") + val("rank_volume_ratio_20")) / 2,
            "detail": "5日與20日量能放大排名",
        },
        {
            "factor": "Volatility Control",
            "value": max(0.0, 1 - val("rank_rolling_volatility_20")),
            "detail": "20日波動相對分數，越高代表越穩定",
        },
    ]
    factors = sorted(factors, key=lambda item: item["value"], reverse=True)

    reasons = []
    for item in factors[:4]:
        if item["factor"] == "Relative Strength":
            reasons.append(pct_rank_reason(item["value"]))
        elif item["factor"] == "Trend Structure":
            reasons.append(f"趨勢結構分數 {item['value'] * 100:.0f}")
        elif item["factor"] == "Institutional Flow":
            reasons.append(f"法人資金分數 {item['value'] * 100:.0f}")
        elif item["factor"] == "Volume Expansion":
            reasons.append(f"量能分數 {item['value'] * 100:.0f}")
        else:
            reasons.append(f"波動控制分數 {item['value'] * 100:.0f}")

    total = sum(max(0.0, item["value"]) for item in factors) or 1
    explainability = [
        {
            "factor": item["factor"],
            "contribution": round(max(0.0, item["value"]) / total, 4),
            "detail": item["detail"],
        }
        for item in factors
    ]
    return reasons, explainability


def concentration(rows: list[dict]) -> dict:
    total = sum(row["pct"] for row in rows) or 1
    by_sector: dict[str, float] = {}
    for row in rows:
        sector = row.get("industry") or "未知產業"
        by_sector[sector] = by_sector.get(sector, 0) + row["pct"]
    top_sector, top_sector_pct = max(by_sector.items(), key=lambda item: item[1]) if by_sector else ("-", 0)
    return {
        "maxPositionPct": max((row["pct"] for row in rows), default=0),
        "topSector": top_sector,
        "topSectorPct": top_sector_pct,
        "hhi": sum((row["pct"] / total) ** 2 for row in rows),
        "sectorWeights": by_sector,
    }


def build_action_summary(rows: list[dict], sell_rows: list[dict] = None) -> dict:
    sell_rows = sell_rows or []
    groups = {
        "buyNow": [row for row in rows if row.get("executionStatus") in ("可買入", "替換買入")],
        "waitPullback": [row for row in rows if row.get("executionStatus") == "等待回調"],
        "avoidChasing": [row for row in rows if row.get("executionStatus") == "過熱不追"],
        "riskDeferred": [row for row in rows if row.get("executionStatus") == "風控暫緩"],
        "watch": [row for row in rows if row.get("executionStatus") == "候選觀察"],
    }
    summary = {
        key: [
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "price": row["currentPrice"],
                "buyPrice": row.get("buyPrice"),
                "pullbackPrice": row.get("pullbackPrice"),
                "status": row["executionStatus"],
                "foreignNet": row.get("foreignNet"),
                "trustNet": row.get("trustNet"),
                "shares": row.get("shares"),
                "riskFlags": row.get("riskFlags", []),
                "riskControlLabel": row.get("riskControlLabel", ""),
            }
            for row in value
        ]
        for key, value in groups.items()
    }
    summary["sellNow"] = [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "price": row.get("currentPrice"),
            "status": "替換賣出",
            "shares": row.get("shares", 0),
            "replacedBy": row.get("replacedBy"),
        }
        for row in sell_rows
    ]
    return summary


def build_holding_rows(rows: list[dict]) -> list[dict]:
    action_by_status = {
        "可買入": "可建立部位",
        "等待回調": "等待買點",
        "過熱不追": "保留候選，不追價",
        "候選觀察": "觀察不動作",
    }
    return [
        {
            "rank": row["rank"],
            "symbol": row["symbol"],
            "name": row["name"],
            "industry": row["industry"],
            "status": row["executionStatus"],
            "action": action_by_status.get(row["executionStatus"], "觀察"),
            "referencePrice": row["currentPrice"],
            "shares": row["shares"],
            "notional": row["notional"],
            "pct": row["pct"],
            "stop": row["stop"],
            "takeProfit": row["takeProfit"],
            "takeProfitPct": row.get("takeProfitPct"),
            "trailingTriggerPct": row.get("trailingTriggerPct"),
            "invalidPrice": row["invalidPrice"],
            "foreignNet": row.get("foreignNet"),
            "trustNet": row.get("trustNet"),
        }
        for row in rows
    ]


def benchmark_metrics(benchmark: dict, capital: float, dates: list[pd.Timestamp]) -> dict:
    if benchmark.get("found"):
        return {
            "name": "0050",
            "totalReturn": benchmark["total_return"],
            "cagr": benchmark["cagr"],
            "sharpe": benchmark["sharpe"],
            "maxDrawdown": benchmark["max_drawdown"],
        }

    cache_files = sorted(BENCHMARK_CACHE_DIR.glob("benchmark_0050_*.csv"))
    if not cache_files:
        return {"name": "0050", "totalReturn": None, "cagr": None, "sharpe": None, "maxDrawdown": None}

    frame = pd.read_csv(cache_files[-1], parse_dates=["date"])
    frame = frame[frame["date"].isin(dates)].sort_values("date")
    if len(frame) < 2:
        return {"name": "0050", "totalReturn": None, "cagr": None, "sharpe": None, "maxDrawdown": None}

    equity = frame["close"] / float(frame["close"].iloc[0])
    daily = equity.pct_change().dropna()
    drawdown = equity / equity.cummax() - 1
    daily_std = float(daily.std()) if len(daily) > 1 else 0.0
    sharpe = float((252**0.5) * daily.mean() / daily_std) if daily_std > 0 else None
    cagr = float(equity.iloc[-1] ** (252 / len(frame)) - 1)
    return {
        "name": "0050",
        "totalReturn": float(equity.iloc[-1] - 1),
        "cagr": cagr,
        "sharpe": sharpe,
        "maxDrawdown": float(abs(drawdown.min())),
    }


def load_stock_info() -> pd.DataFrame:
    stock_info = pd.read_csv(ROOT / "stock_universe" / "selected_stocks_500_liquid.csv", dtype={"stock_id": str})
    stock_info["stock_id"] = stock_info["stock_id"].str.zfill(4)
    stock_info = stock_info[["stock_id", "stock_name", "industry_category"]].drop_duplicates("stock_id")
    return stock_info.rename(columns={"stock_id": "symbol", "stock_name": "name", "industry_category": "industry"})


def overlay_recent_official_flow(frame: pd.DataFrame, latest_date: str, lookback_days: int = 45) -> pd.DataFrame:
    return overlay_recent_official_institutional_flow(
        frame,
        lookback_days=lookback_days,
        end_date=latest_date,
        log_prefix="dashboard-flow-overlay",
    )


def add_latest_ranks(frame: pd.DataFrame) -> pd.DataFrame:
    ranked = frame.copy()
    rank_specs = [
        ("close_return_10", True),
        ("position_in_52w_range", True),
        ("price_to_ma_20", True),
        ("adx_14", True),
        ("foreign_net_5d_sum", True),
        ("trust_net_5d_sum", True),
        ("volume_ratio_5", True),
        ("volume_ratio_20", True),
        ("rolling_volatility_20", True),
    ]
    for column, high_good in rank_specs:
        values = pd.to_numeric(ranked.get(column), errors="coerce")
        pct = values.rank(pct=True, ascending=high_good)
        ranked[f"rank_{column}"] = pct.fillna(0.5)
    return ranked


def load_candidates(stock_info: pd.DataFrame) -> pd.DataFrame:
    signals_path = OFFICIAL_RANK_DIR / "rank_portfolio_signals.csv"
    dates = pd.read_csv(signals_path, usecols=["date"])["date"]
    latest_date = str(dates.max())[:10]

    signals = pd.read_csv(
        signals_path,
        dtype={"symbol": str},
        usecols=[
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
        ],
    )
    signals["date"] = signals["date"].astype(str).str[:10]

    # Get previous day's strategy score for score-delta filters
    all_dates = sorted(signals["date"].unique())
    prev_date = all_dates[-2] if len(all_dates) >= 2 else None
    if prev_date:
        prev_scores = signals[signals["date"].eq(prev_date)][["symbol", "strategy_score"]].copy()
        prev_scores["symbol"] = prev_scores["symbol"].str.zfill(4)
        prev_scores = prev_scores.rename(columns={"strategy_score": "prev_strategy_score"})
    else:
        prev_scores = pd.DataFrame(columns=["symbol", "prev_strategy_score"])

    signals = signals[signals["date"].eq(latest_date)].copy()
    signals["symbol"] = signals["symbol"].str.zfill(4)
    signals = signals.merge(prev_scores, on="symbol", how="left")

    feature_cols = [
        "date",
        "symbol",
        "high",
        "low",
        "close",
        "volume",
        "foreign_net",
        "trust_net",
        "total_net",
        "foreign_net_5d_sum",
        "trust_net_5d_sum",
        "revenue_mom_21d",
        "volume_ratio_5",
        "volume_ratio_20",
        "adx_14",
        "position_in_52w_range",
        "close_return_5",
        "close_return_10",
        "price_to_ma_20",
        "rolling_volatility_20",
    ]
    features = pd.read_csv(PROCESSED_DATA, dtype={"symbol": str}, usecols=lambda col: col in feature_cols)
    features["date"] = features["date"].astype(str).str[:10]
    features["symbol"] = features["symbol"].str.zfill(4)
    features = features.sort_values(["symbol", "date"])
    close_series = pd.to_numeric(features["close"], errors="coerce")
    by_symbol = features["symbol"]
    features["prev_close"] = close_series.groupby(by_symbol).shift(1)
    features["ma5"] = close_series.groupby(by_symbol).transform(lambda item: item.rolling(5, min_periods=5).mean())
    features["ma10"] = close_series.groupby(by_symbol).transform(lambda item: item.rolling(10, min_periods=10).mean())
    features["ma20"] = close_series.groupby(by_symbol).transform(lambda item: item.rolling(20, min_periods=20).mean())
    features = overlay_recent_official_flow(features, latest_date)
    features["date"] = features["date"].astype(str).str[:10]
    features = features[features["date"].eq(latest_date)].copy()

    candidates = signals.merge(features, on=["date", "symbol"], how="left", suffixes=("", "_feature"))
    candidates = candidates.merge(stock_info, on="symbol", how="left")
    candidates = add_latest_ranks(candidates)
    for col in candidates.columns:
        if col not in {"date", "symbol", "name", "industry", "market_regime", "signal_tier"}:
            candidates[col] = pd.to_numeric(candidates[col], errors="coerce")
    return candidates.sort_values(["date", "rank_signal_score", "strategy_score"], ascending=[True, True, False])


def load_open_positions(stock_info: pd.DataFrame) -> list[dict]:
    """Load positions from the forward simulation (fresh 1M capital from 2026-06-05)."""
    try:
        positions_path = FORWARD_SIM_DIR / "rank_portfolio_positions.csv"
        positions = pd.read_csv(positions_path, dtype={"symbol": str})
        if positions.empty:
            return []
            
        positions["symbol"] = positions["symbol"].str.zfill(4)
        positions = positions.merge(stock_info, on="symbol", how="left")
        
        rows = []
        for _, row in positions.iterrows():
            rows.append({
                "symbol": str(row["symbol"]),
                "name": str(row.get("name", "")),
                "industry": str(row.get("industry", "未知產業")),
                "entryDate": str(row.get("entry_date", ""))[:10],
                "entryPrice": safe_float(row.get("entry_price")),
                "currentPrice": safe_float(row.get("current_price")),
                "shares": int(safe_float(row.get("shares", 0))),
                "cost": safe_float(row.get("entry_price")) * int(safe_float(row.get("shares", 0))),
                "marketValue": safe_float(row.get("market_value")),
                "unrealizedPnl": safe_float(row.get("unrealized_pnl")),
                "unrealizedReturn": safe_float(row.get("unrealized_return")),
                "holdingDays": int(safe_float(row.get("holding_days", 0))),
                "stopLoss": safe_float(row.get("stop_loss")),
                "trailingStop": safe_float(row.get("trailing_stop")),
                "peakPrice": safe_float(row.get("peak_price")),
                "portfolioWeight": safe_float(row.get("portfolio_weight")),
                "strategyScore": safe_float(row.get("strategy_score")),
            })

        # Sort by unrealizedReturn descending
        rows.sort(key=lambda x: x["unrealizedReturn"], reverse=True)
        return rows
    except Exception as e:
        print(f"[open-positions] Error loading positions: {e}", file=sys.stderr)
        return []


def annotate_open_position_risk(open_positions: list[dict], candidates: pd.DataFrame, signal_date: str) -> list[dict]:
    latest = candidates[candidates["date"].astype(str).str[:10].eq(signal_date)].copy()
    by_symbol = {str(row.symbol).zfill(4): row for row in latest.itertuples(index=False)}
    for position in open_positions:
        symbol = str(position.get("symbol", "")).zfill(4)
        row = by_symbol.get(symbol)
        if row is None:
            position["riskAction"] = ""
            position["riskControlLabel"] = ""
            continue
        regime = str(getattr(row, "market_regime", ""))
        current = safe_float(getattr(row, "close", position.get("currentPrice", 0)))
        entry = safe_float(position.get("entryPrice"))
        stop = max(safe_float(position.get("stopLoss")), safe_float(position.get("trailingStop")))
        if regime in {"bear", "high_vol"} and current < entry:
            position["riskAction"] = "regime_risk_exit"
            position["riskControlLabel"] = "市場轉弱且跌破成本，優先風控出場"
        elif stop > 0 and current <= stop * 1.03:
            position["riskAction"] = "near_stop"
            position["riskControlLabel"] = "接近停損/移動停利，縮小觀察時間"
        else:
            position["riskAction"] = ""
            position["riskControlLabel"] = ""
    return open_positions


def load_trade_log(stock_info: pd.DataFrame) -> list[dict]:
    """Load completed trades from the forward simulation, especially replacement_switch ones."""
    try:
        trades_path = FORWARD_SIM_DIR / "rank_portfolio_trades.csv"
        trades = pd.read_csv(trades_path, dtype={"symbol": str})
        if trades.empty:
            return []
        trades["symbol"] = trades["symbol"].str.zfill(4)
        trades = trades.merge(stock_info, on="symbol", how="left")
        rows = []
        for _, row in trades.iterrows():
            rows.append({
                "symbol": str(row["symbol"]),
                "name": str(row.get("name", "")),
                "entryDate": str(row.get("entry_date", ""))[:10],
                "exitDate": str(row.get("exit_date", ""))[:10],
                "entryPrice": safe_float(row.get("entry_price")),
                "exitPrice": safe_float(row.get("exit_price")),
                "shares": int(safe_float(row.get("shares", 0))),
                "netPnl": safe_float(row.get("net_pnl")),
                "exitReason": str(row.get("exit_reason", "")),
                "holdingDays": int(safe_float(row.get("holding_days", 0))),
                "win": bool(row.get("win", False)),
            })
        rows.sort(key=lambda x: x["exitDate"], reverse=True)
        return rows
    except Exception as e:
        print(f"[trade-log] Error loading trades: {e}", file=sys.stderr)
        return []


def risk_parity_allocation(candidates: pd.DataFrame, settings: dict, lot: int, open_positions: list[dict]) -> dict:
    capital = float(settings["capital"])
    max_positions = int(settings["portfolio_max_positions"])
    max_position_pct = float(settings["portfolio_max_position_pct"])
    risk_pct = float(settings["max_risk_per_trade"])
    atr_multiplier = float(settings["atr_stop_multiplier"])
    target_exposure = float(settings["target_exposure"])

    current_positions_count = len(open_positions)
    invested_cash = sum(float(p.get("marketValue", p.get("cost", 0))) for p in open_positions)
    cash = max(0.0, capital - invested_cash)

    selected = candidates[candidates["entry_signal"].eq(1)].copy()
    selected = selected.sort_values(["rank_signal_score", "strategy_score"], ascending=[True, False])
    selected = selected.head(max(max_positions * 3, max_positions))

    replacement_threshold = float(settings.get("replacement_threshold", 0.05))
    open_positions_sorted = sorted(open_positions, key=lambda p: float(p.get("strategyScore", 0)))
    replaced_symbols = set()
    sell_rows = []

    invested = 0.0
    rows: list[dict] = []
    used_symbols: set[str] = {p["symbol"] for p in open_positions}
    for _, item in selected.iterrows():
        symbol = str(item["symbol"]).zfill(4)
        if symbol in used_symbols:
            continue
            
        close = safe_float(item.get("close"))
        atr = safe_float(item.get("atr_14"))
        if close <= 0 or atr <= 0:
            continue

        reasons, _ = build_explainability(item)
        plan = execution_plan(item, close, atr, settings)
        
        # Check capacity & replacement
        is_replacement = False
        replaced_symbol = None
        worst_pos = None
        
        current_active_positions = current_positions_count + len(rows) - len(replaced_symbols)
        if current_active_positions >= max_positions or cash <= 0:
            cand_score = safe_float(item.get("strategy_score"))
            worst_pos = next((p for p in open_positions_sorted if p["symbol"] not in replaced_symbols), None)
            
            if worst_pos:
                worst_score = float(worst_pos.get("strategyScore", 0))
                freed_cash = float(worst_pos.get("marketValue", 0))
                entry_budget = min(max(0.0, cash + freed_cash), max(0.0, capital * max_position_pct))
                max_entry_notional = float(settings.get("max_entry_notional", 0.0))
                if max_entry_notional > 0:
                    entry_budget = min(entry_budget, max_entry_notional)
                required_edge = replacement_threshold + replacement_cost_penalty(freed_cash, entry_budget, capital, settings)
                if cand_score > worst_score + required_edge:
                    is_replacement = True
                    replaced_symbol = worst_pos["symbol"]
                    replaced_symbols.add(replaced_symbol)
                    
                    cash += freed_cash
                    invested_cash -= freed_cash

        if (current_active_positions >= max_positions or cash <= 0) and not is_replacement:
            plan["executionStatus"] = "候選觀察"
            plan["actionLabel"] = "資金/檔數已滿，等汰弱留強"
            plan["executionTone"] = "watch"
            shares = 0
            notional = 0.0
        elif plan.get("executionStatus") == "風控暫緩":
            shares = 0
            notional = 0.0
        else:
            remaining_target = max(0.0, capital * target_exposure - invested_cash - invested)
            sizing = calculate_position_size(
                capital=capital,
                price=close,
                atr_value=atr,
                risk_pct=risk_pct,
                atr_multiplier=atr_multiplier,
                max_position_pct=max_position_pct,
                min_trade_unit=lot,
                cash=cash,
                target_notional=remaining_target,
                max_notional=float(settings.get("max_entry_notional", 0.0)),
                volume=safe_float(item.get("volume")),
                max_volume_pct=float(settings.get("max_entry_volume_pct", 0.0)),
            )
            shares = sizing.shares
            if shares <= 0:
                continue

            if shares <= 0 and is_replacement:
                # Rollback if we actually can't buy
                replaced_symbols.remove(replaced_symbol)
                freed_cash = float(worst_pos.get("marketValue", 0))
                cash -= freed_cash
                invested_cash += freed_cash
                is_replacement = False
                plan["executionStatus"] = "候選觀察"
                plan["actionLabel"] = "資金/檔數已滿，等汰弱留強"
                plan["executionTone"] = "watch"
                shares = 0
                notional = 0.0

            if shares > 0:
                notional = sizing.notional
                cash -= notional
                invested += notional
                
                if is_replacement:
                    plan["executionStatus"] = "替換買入"
                    plan["actionLabel"] = f"汰換 {replaced_symbol}"
                    plan["executionTone"] = "positive"
                    sell_rows.append({
                        "symbol": worst_pos["symbol"],
                        "name": worst_pos["name"],
                        "currentPrice": worst_pos["currentPrice"],
                        "shares": worst_pos["shares"],
                        "replacedBy": symbol
                    })

        status_prefix = {
            "可買入": "今日可執行",
            "替換買入": "今日替換",
            "等待回調": "等回調",
            "過熱不追": "不追高",
            "風控暫緩": "風控暫緩",
            "候選觀察": "觀察",
        }.get(plan["executionStatus"], "觀察")

        rows.append(
            {
                "rank": len(rows) + 1,
                "date": str(item["date"])[:10],
                "symbol": symbol,
                "name": None if pd.isna(item.get("name")) else str(item["name"]),
                "industry": None if pd.isna(item.get("industry")) else str(item["industry"]),
                "close": close,
                "currentPrice": close,
                "shares": shares,
                "theoreticalShares": sizing.theoretical_shares,
                "volumeLimitedShares": sizing.volume_limited_shares,
                "cashLimitedShares": sizing.cash_limited_shares,
                "sizingBlockedReason": sizing.blocked_reason,
                "notional": notional,
                "pct": notional / capital,
                "score": safe_float(item.get("strategy_score")),
                "regime": str(item.get("market_regime", "")),
                "stop": plan["stop"],
                "takeProfit": plan["takeProfit"],
                "stopPct": plan["stopPct"],
                "takeProfitPct": plan["takeProfitPct"],
                "trailingTriggerPct": plan.get("trailingTriggerPct"),
                "buyPrice": plan["buyPrice"],
                "pullbackPrice": plan["pullbackPrice"],
                "invalidPrice": plan["invalidPrice"],
                "ma5": plan["ma5"],
                "ma10": plan["ma10"],
                "ma20": plan["ma20"],
                "prevClose": plan["prevClose"],
                "executionStatus": plan["executionStatus"],
                "executionTone": plan["executionTone"],
                "actionLabel": plan["actionLabel"],
                "limitUpToday": plan["limitUpToday"],
                "riskFlags": plan.get("riskFlags", []),
                "riskControlLabel": plan.get("riskControlLabel", ""),
                "expectedReturn": None,
                "upsideToTakeProfit": plan["takeProfitPct"],
                "foreign5": None if pd.isna(item.get("foreign_net_5d_sum")) else float(item["foreign_net_5d_sum"]),
                "trust5": None if pd.isna(item.get("trust_net_5d_sum")) else float(item["trust_net_5d_sum"]),
                "foreignNet": None if pd.isna(item.get("foreign_net")) else float(item["foreign_net"]),
                "trustNet": None if pd.isna(item.get("trust_net")) else float(item["trust_net"]),
                "reasons": [status_prefix, *reasons],
            }
        )

    return {
        "capital_utilization": (invested_cash + invested) / capital,
        "cash_left": cash,
        "positions": current_positions_count + len([r for r in rows if r.get("shares", 0) > 0]),
        "allocated_notional": invested_cash + invested,
        "status_counts": {
            status: sum(1 for row in rows if row.get("executionStatus") == status)
            for status in ["可買入", "替換買入", "等待回調", "過熱不追", "候選觀察"]
        },
        "action_summary": build_action_summary(rows, sell_rows),
        "holding_rows": build_holding_rows(rows),
        "rows": rows,
    }


def _roc_date(value: object) -> str | None:
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return None
    year = int(digits[:3]) + 1911
    month = int(digits[3:5])
    day = int(digits[5:7])
    try:
        datetime(year, month, day)
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def _parse_disposition_period(value: object) -> tuple[str | None, str | None]:
    text = str(value or "")
    parts = [part for part in re.split(r"[~～至]+", text) if part.strip()]
    if len(parts) >= 2:
        return _roc_date(parts[0]), _roc_date(parts[1])
    return None, None


def _disposition_status(start: str | None, end: str | None, as_of_date: str) -> dict:
    if not start or not end:
        return {"status": "unknown", "label": "處置日期未明", "tone": "watch", "daysToStart": None, "daysToEnd": None}
    as_of = pd.Timestamp(as_of_date)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    days_to_start = int((start_ts - as_of).days)
    days_to_end = int((end_ts - as_of).days)
    if as_of == start_ts:
        return {"status": "entering", "label": "今日起處置", "tone": "danger", "daysToStart": 0, "daysToEnd": days_to_end}
    if as_of == end_ts:
        return {"status": "ending", "label": "今日結束處置", "tone": "warning", "daysToStart": days_to_start, "daysToEnd": 0}
    if start_ts < as_of < end_ts:
        return {"status": "active", "label": "處置中", "tone": "danger", "daysToStart": days_to_start, "daysToEnd": days_to_end}
    if as_of < start_ts:
        return {
            "status": "upcoming",
            "label": "即將處置" if days_to_start <= 3 else f"{days_to_start}日後處置",
            "tone": "warning",
            "daysToStart": days_to_start,
            "daysToEnd": days_to_end,
        }
    return {"status": "ended", "label": "已結束處置", "tone": "neutral", "daysToStart": days_to_start, "daysToEnd": days_to_end}


def fetch_disposition_data(as_of_date: str) -> dict[str, dict]:
    urls = [
        ("twse", "https://openapi.twse.com.tw/v1/announcement/punish"),
        ("tpex", "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"),
    ]
    session = requests.Session()
    session.trust_env = False
    by_symbol: dict[str, dict] = {}
    for market, url in urls:
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            rows = response.json()
        except Exception as exc:
            print(f"[disposition] skipped {market}: {exc}", file=sys.stderr)
            continue
        for row in rows if isinstance(rows, list) else []:
            symbol = str(row.get("Code") or row.get("SecuritiesCompanyCode") or "").strip()
            if not re.fullmatch(r"\d{4}", symbol):
                continue
            start, end = _parse_disposition_period(row.get("DispositionPeriod"))
            status = _disposition_status(start, end, as_of_date)
            item = {
                "market": market,
                "symbol": symbol,
                "name": row.get("Name") or row.get("CompanyName"),
                "announcementDate": _roc_date(row.get("Date")),
                "startDate": start,
                "endDate": end,
                "status": status["status"],
                "label": status["label"],
                "tone": status["tone"],
                "daysToStart": status["daysToStart"],
                "daysToEnd": status["daysToEnd"],
                "reason": row.get("ReasonsOfDisposition") or row.get("DispositionReasons"),
                "measure": row.get("DispositionMeasures"),
                "condition": row.get("DisposalCondition"),
                "detail": row.get("Detail") or row.get("DisposalCondition"),
            }
            current = by_symbol.get(symbol)
            priority = {"entering": 5, "active": 4, "upcoming": 3, "ending": 2, "ended": 1, "unknown": 0}
            if current is None or priority.get(item["status"], 0) > priority.get(current.get("status"), 0):
                by_symbol[symbol] = item
    return by_symbol


def build_stock_search_data(
    signal_date: str,
    candidates: pd.DataFrame,
    open_positions: list[dict],
    settings: dict,
    disposition_by_symbol: dict[str, dict] | None = None,
    disposition_as_of: str | None = None,
) -> dict:
    holding_by_symbol = {str(row["symbol"]).zfill(4): row for row in open_positions}
    disposition_by_symbol = disposition_by_symbol or {}
    search_rows = []
    ranked = candidates[candidates["date"].astype(str).str[:10].eq(signal_date)].copy()
    ranked = ranked.sort_values(["rank_signal_score", "strategy_score"], ascending=[True, False])

    for rank, (_, item) in enumerate(ranked.iterrows(), start=1):
        symbol = str(item["symbol"]).zfill(4)
        close = safe_float(item.get("close"))
        atr = safe_float(item.get("atr_14"))
        plan = execution_plan(item, close, atr, settings) if close > 0 and atr > 0 else {}
        reasons, explainability = build_explainability(item)
        holding_row = holding_by_symbol.get(symbol)
        disposition = disposition_by_symbol.get(symbol)
        foreign5 = safe_float(item.get("foreign_net_5d_sum"))
        trust5 = safe_float(item.get("trust_net_5d_sum"))
        total5 = foreign5 + trust5
        search_rows.append(
            {
                "rank": rank,
                "date": str(item.get("date", ""))[:10],
                "symbol": symbol,
                "name": None if pd.isna(item.get("name")) else str(item.get("name")),
                "industry": None if pd.isna(item.get("industry")) else str(item.get("industry")),
                "isCandidate": bool(safe_float(item.get("entry_signal")) == 1),
                "isHolding": holding_row is not None,
                "signalTier": None if pd.isna(item.get("signal_tier")) else str(item.get("signal_tier")),
                "strategyScore": safe_float(item.get("strategy_score")),
                "prevStrategyScore": safe_float(item.get("prev_strategy_score")),
                "scoreDelta": round((safe_float(item.get("strategy_score")) - safe_float(item.get("prev_strategy_score"))) * 100, 1) if not pd.isna(item.get("prev_strategy_score")) else None,
                "rankSignalScore": safe_float(item.get("rank_signal_score")),
                "marketRegime": None if pd.isna(item.get("market_regime")) else str(item.get("market_regime")),
                "currentPrice": close,
                "open": safe_float(item.get("open")),
                "prevClose": safe_float(item.get("prev_close")),
                "ma5": safe_float(item.get("ma5")),
                "ma10": safe_float(item.get("ma10")),
                "ma20": safe_float(item.get("ma20")),
                "atr14": atr,
                "return5": safe_float(item.get("close_return_5")),
                "return10": safe_float(item.get("close_return_10")),
                "priceToMa20": safe_float(item.get("price_to_ma_20")),
                "position52w": safe_float(item.get("position_in_52w_range")),
                "adx14": safe_float(item.get("adx_14")),
                "volumeRatio5": safe_float(item.get("volume_ratio_5")),
                "volumeRatio20": safe_float(item.get("volume_ratio_20")),
                "revenueMom21d": safe_float(item.get("revenue_mom_21d")),
                "foreign5": foreign5,
                "trust5": trust5,
                "totalNet5": total5,
                "foreignNet": safe_float(item.get("foreign_net")),
                "trustNet": safe_float(item.get("trust_net")),
                "totalNet": safe_float(item.get("total_net")),
                "executionStatus": plan.get("executionStatus"),
                "executionTone": plan.get("executionTone"),
                "actionLabel": plan.get("actionLabel"),
                "buyPrice": plan.get("buyPrice"),
                "pullbackPrice": plan.get("pullbackPrice"),
                "stop": plan.get("stop"),
                "takeProfit": plan.get("takeProfit"),
                "stopPct": plan.get("stopPct"),
                "takeProfitPct": plan.get("takeProfitPct"),
                "invalidPrice": plan.get("invalidPrice"),
                "limitUpToday": bool(plan.get("limitUpToday")),
                "riskFlags": plan.get("riskFlags", []),
                "riskControlLabel": plan.get("riskControlLabel", ""),
                "portfolioPct": float(holding_row.get("portfolioWeight", 0.0)) if holding_row else 0.0,
                "shares": int(holding_row.get("shares", 0)) if holding_row else 0,
                "notional": float(holding_row.get("marketValue", 0.0)) if holding_row else 0.0,
                "disposition": disposition,
                "isDisposition": bool(disposition and disposition.get("status") in {"entering", "active", "upcoming", "ending"}),
                "isDispositionEntering": bool(disposition and disposition.get("status") == "entering"),
                "isDispositionEnding": bool(disposition and disposition.get("status") == "ending"),
                "reasons": reasons,
                "explainability": explainability,
            }
        )

    return {
        "summary": {
            "sourceDate": signal_date,
            "stockCount": len(search_rows),
            "candidateCount": int(sum(1 for row in search_rows if row["isCandidate"])),
            "holdingCount": int(sum(1 for row in search_rows if row["isHolding"])),
            "dispositionAsOf": disposition_as_of,
            "dispositionCount": int(sum(1 for row in search_rows if row["isDisposition"])),
            "dispositionEnteringCount": int(sum(1 for row in search_rows if row["isDispositionEntering"])),
            "dispositionEndingCount": int(sum(1 for row in search_rows if row["isDispositionEnding"])),
        },
        "stocks": search_rows,
    }


def make_strategy_payload(name: str, summary: dict, fallback_benchmark: dict | None = None) -> dict:
    perf = summary["performance"]
    bench = summary.get("benchmark", {})
    start_value = bench.get("start") or (fallback_benchmark or {}).get("start") or ""
    end_value = bench.get("end") or (fallback_benchmark or {}).get("end") or ""
    start = str(start_value)[:10]
    end = str(end_value)[:10]
    return {
        "name": name,
        "totalReturn": perf["total_return"],
        "cagr": perf["cagr"],
        "sharpe": perf["sharpe"],
        "maxDrawdown": perf["max_drawdown"],
        "winRate": perf["win_rate"],
        "profitFactor": perf["profit_factor"],
        "calmar": perf["cagr"] / perf["max_drawdown"] if perf["max_drawdown"] else None,
        "utilization": perf["mean_capital_utilization"],
        "trades": perf["trades"],
        "periodStart": start,
        "periodEnd": end,
    }


def classify_rotation_status(net5: float, net20: float, return5: float, acceleration: float) -> tuple[str, str, str]:
    if net5 > 0 and return5 > 0.01 and acceleration > 0:
        return "main", "主力加速", "主攻產業"
    if net5 > 0 and net20 > 0:
        return "rotation", "輪動流入", "策略觀察"
    if net5 < 0 and net20 < 0:
        return "outflow", "資金退潮", "降低曝險"
    if net5 < 0:
        return "outflow", "資金退潮", "觀察轉弱"
    return "watch", "觀望沉寂", "觀察"


def build_rotation_data(
    source_date: str,
    candidates: pd.DataFrame,
    allocation_rows: list[dict],
    stock_info: pd.DataFrame,
    candidate_date: str | None = None,
) -> dict:
    feature_cols = [
        "date",
        "symbol",
        "close",
        "volume",
        "turnover",
        "foreign_net",
        "trust_net",
        "total_net",
        "close_return_5",
        "close_return_10",
        "volume_ratio_20",
        "rolling_volatility_20",
    ]
    flow = pd.read_csv(PROCESSED_DATA, dtype={"symbol": str}, usecols=lambda col: col in feature_cols)
    flow["date"] = pd.to_datetime(flow["date"])
    requested_date = pd.Timestamp(source_date)
    latest_feature_date = pd.Timestamp(flow["date"].dropna().max())
    if latest_feature_date > requested_date:
        requested_date = latest_feature_date
    flow = flow[flow["date"].le(requested_date)].copy()
    if flow.empty:
        raise RuntimeError(f"No feature rows found before {source_date}")

    available_dates = sorted(flow["date"].dropna().unique())
    actual_date = pd.Timestamp(available_dates[-1])
    dates5 = available_dates[-5:]
    dates20 = available_dates[-20:]
    window5_start = pd.Timestamp(dates5[0])
    window20_start = pd.Timestamp(dates20[0])
    institutional_source = "all_features.csv"

    for column in ["foreign_net", "trust_net", "total_net", "turnover", "volume", "close"]:
        if column in flow.columns:
            flow[column] = pd.to_numeric(flow[column], errors="coerce").fillna(0.0)
    flow = overlay_recent_official_institutional_flow(
        flow,
        lookback_days=20,
        end_date=actual_date,
        log_prefix="dashboard-flow-overlay",
    )
    if int(flow.attrs.get("official_institutional_rows_applied", 0)) > 0:
        institutional_source = "TWSE/TPEx official institutional flow"

    latest = flow[flow["date"].eq(actual_date)].copy()
    latest["symbol"] = latest["symbol"].astype(str).str.zfill(4)
    latest = latest.merge(stock_info, on="symbol", how="left")
    latest["industry"] = latest["industry"].fillna("未知產業")

    flow["symbol"] = flow["symbol"].astype(str).str.zfill(4)
    flow["total_net"] = pd.to_numeric(flow["total_net"], errors="coerce").fillna(
        pd.to_numeric(flow["foreign_net"], errors="coerce").fillna(0.0)
        + pd.to_numeric(flow["trust_net"], errors="coerce").fillna(0.0)
    )
    net5 = flow[flow["date"].isin(dates5)].groupby("symbol")["total_net"].sum().rename("net5")
    net20 = flow[flow["date"].isin(dates20)].groupby("symbol")["total_net"].sum().rename("net20")
    foreign5 = flow[flow["date"].isin(dates5)].groupby("symbol")["foreign_net"].sum().rename("foreign5")
    trust5 = flow[flow["date"].isin(dates5)].groupby("symbol")["trust_net"].sum().rename("trust5")
    latest = latest.merge(net5, on="symbol", how="left")
    latest = latest.merge(net20, on="symbol", how="left")
    latest = latest.merge(foreign5, on="symbol", how="left")
    latest = latest.merge(trust5, on="symbol", how="left")
    for column in [
        "close",
        "net5",
        "net20",
        "foreign5",
        "trust5",
        "close_return_5",
        "close_return_10",
        "turnover",
        "volume_ratio_20",
        "rolling_volatility_20",
    ]:
        latest[column] = pd.to_numeric(latest.get(column), errors="coerce").fillna(0.0)

    candidate_date = candidate_date or source_date
    candidate_latest = candidates[candidates["date"].astype(str).str[:10].eq(candidate_date)].copy()
    candidate_latest["symbol"] = candidate_latest["symbol"].astype(str).str.zfill(4)
    selected = candidate_latest[candidate_latest["entry_signal"].eq(1)].copy()
    candidate_symbols = set(selected["symbol"])
    score_by_symbol = selected.set_index("symbol")["strategy_score"].to_dict()
    portfolio_pct_by_symbol = {row["symbol"]: float(row.get("pct", 0.0)) for row in allocation_rows}
    portfolio_pct_by_sector: dict[str, float] = {}
    for row in allocation_rows:
        sector = row.get("industry") or "未知產業"
        portfolio_pct_by_sector[sector] = portfolio_pct_by_sector.get(sector, 0.0) + float(row.get("pct", 0.0))

    if "industry" in selected.columns:
        selected_by_sector = selected.copy()
        selected_by_sector["industry"] = selected_by_sector["industry"].fillna("未知產業")
    else:
        selected_by_sector = selected.merge(stock_info, on="symbol", how="left")
        selected_by_sector["industry"] = selected_by_sector["industry"].fillna("未知產業")
    candidate_count = selected_by_sector.groupby("industry")["symbol"].nunique().to_dict()
    avg_score = selected_by_sector.groupby("industry")["strategy_score"].mean().to_dict()

    sector_rows = []
    grouped = latest.groupby("industry", dropna=False)
    for sector, frame in grouped:
        net5_value = float(frame["net5"].sum())
        net20_value = float(frame["net20"].sum())
        return5 = float(frame["close_return_5"].mean())
        acceleration = net5_value - (net20_value / 4.0)
        status, label, verdict = classify_rotation_status(net5_value, net20_value, return5, acceleration)
        pct_value = float(portfolio_pct_by_sector.get(sector, 0.0))
        if pct_value > 0 and verdict in {"策略觀察", "觀察"}:
            verdict = "策略持有"
        sector_rows.append(
            {
                "name": sector,
                "status": status,
                "statusLabel": label,
                "net5": net5_value,
                "net20": net20_value,
                "foreign5": float(frame["foreign5"].sum()),
                "trust5": float(frame["trust5"].sum()),
                "return5": return5,
                "return10": float(frame["close_return_10"].mean()),
                "turnover": float(frame["turnover"].sum()),
                "avgVolumeRatio20": float(frame["volume_ratio_20"].mean()),
                "avgVolatility20": float(frame["rolling_volatility_20"].mean()),
                "stockCount": int(frame["symbol"].nunique()),
                "candidateCount": int(candidate_count.get(sector, 0)),
                "avgStrategyScore": float(avg_score.get(sector, 0.0)) if sector in avg_score else 0.0,
                "acceleration": acceleration,
                "portfolioPct": pct_value,
                "strategyVerdict": verdict,
            }
        )
    sector_rows = sorted(
        sector_rows,
        key=lambda item: (item["portfolioPct"] > 0, item["candidateCount"], abs(item["net5"])),
        reverse=True,
    )
    for idx, row in enumerate(sector_rows, start=1):
        row["rank"] = idx

    stock_rows = []
    # Ensure we have up to 10 stocks per industry, plus any candidate symbols
    top_per_industry = latest.groupby("industry", group_keys=False).apply(
        lambda df: df.sort_values("net5", key=lambda s: s.abs(), ascending=False).head(10)
    )
    top_symbols = set(top_per_industry["symbol"])
    top_symbols |= candidate_symbols
    for _, row in latest[latest["symbol"].isin(top_symbols)].iterrows():
        symbol = str(row["symbol"]).zfill(4)
        stock_rows.append(
            {
                "symbol": symbol,
                "name": None if pd.isna(row.get("name")) else str(row.get("name")),
                "industry": str(row.get("industry", "未知產業")),
                "net5": float(row["net5"]),
                "net20": float(row["net20"]),
                "foreign5": float(row["foreign5"]),
                "trust5": float(row["trust5"]),
                "foreignNet": float(row["foreign_net"]),
                "trustNet": float(row["trust_net"]),
                "return5": float(row["close_return_5"]),
                "return10": float(row["close_return_10"]),
                "turnover": float(row["turnover"]),
                "volumeRatio20": float(row["volume_ratio_20"]),
                "isCandidate": symbol in candidate_symbols,
                "strategyScore": float(score_by_symbol.get(symbol, 0.0)),
                "portfolioPct": float(portfolio_pct_by_symbol.get(symbol, 0.0)),
            }
        )
    stock_rows = sorted(stock_rows, key=lambda item: (item["isCandidate"], abs(item["net5"])), reverse=True)

    def stock_rank_rows(frame: pd.DataFrame, column: str, direction: str, limit: int = 30) -> list[dict]:
        if direction == "buy":
            ranked = frame[frame[column] > 0].sort_values(column, ascending=False).head(limit)
        else:
            ranked = frame[frame[column] < 0].sort_values(column, ascending=True).head(limit)
        rows = []
        for rank, (_, row) in enumerate(ranked.iterrows(), start=1):
            symbol = str(row["symbol"]).zfill(4)
            rows.append(
                {
                    "rank": rank,
                    "symbol": symbol,
                    "name": None if pd.isna(row.get("name")) else str(row.get("name")),
                    "industry": str(row.get("industry", "未分類產業")),
                    "close": float(row["close"]),
                    "net5": float(row["net5"]),
                    "net20": float(row["net20"]),
                    "periodNet": float(row[column]),
                    "foreign5": float(row["foreign5"]),
                    "trust5": float(row["trust5"]),
                    "foreignNet": float(row["foreign_net"]),
                    "trustNet": float(row["trust_net"]),
                    "return5": float(row["close_return_5"]),
                    "return10": float(row["close_return_10"]),
                    "turnover": float(row["turnover"]),
                    "volumeRatio20": float(row["volume_ratio_20"]),
                    "isCandidate": symbol in candidate_symbols,
                    "strategyScore": float(score_by_symbol.get(symbol, 0.0)),
                    "portfolioPct": float(portfolio_pct_by_symbol.get(symbol, 0.0)),
                }
            )
        return rows

    stock_rankings = {
        "buy5": stock_rank_rows(latest, "net5", "buy"),
        "sell5": stock_rank_rows(latest, "net5", "sell"),
        "buy20": stock_rank_rows(latest, "net20", "buy"),
        "sell20": stock_rank_rows(latest, "net20", "sell"),
    }

    return {
        "summary": {
            "sourceDate": actual_date.strftime("%Y-%m-%d"),
            "requestedSourceDate": source_date,
            "candidateDate": candidate_date,
            "window5Start": window5_start.strftime("%Y-%m-%d"),
            "window20Start": window20_start.strftime("%Y-%m-%d"),
            "stockCount": int(latest["symbol"].nunique()),
            "sectorCount": int(len(sector_rows)),
            "missingIndustryCount": int((latest["industry"].eq("未知產業")).sum()),
            "totalNet5": float(latest["net5"].sum()),
            "totalNet20": float(latest["net20"].sum()),
            "candidateSectorCount": int(sum(1 for row in sector_rows if row["candidateCount"] > 0)),
            "stockRankingCount": int(sum(len(rows) for rows in stock_rankings.values())),
            "sources": [
                str(PROCESSED_DATA),
                str(ROOT / "stock_universe" / "selected_stocks_500_liquid.csv"),
                str(OFFICIAL_RANK_DIR / "rank_portfolio_signals.csv"),
            ],
            "institutionalSource": institutional_source,
        },
        "sectors": sector_rows,
        "stocks": stock_rows,
        "stockRankings": stock_rankings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "trading_code_ml" / "config" / "production.yaml")
    parser.add_argument("--processed", type=Path, default=None)
    parser.add_argument("--official-rank-dir", type=Path, default=None)
    parser.add_argument("--forward-sim-dir", type=Path, default=None)
    parser.add_argument("--front-data", type=Path, default=None)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--config-hash", default="")
    parser.add_argument("--strategy-version", default="")
    args = parser.parse_args()
    configure_paths(args)

    official_summary_path = OFFICIAL_RANK_DIR / "rank_portfolio_summary.json"
    official_equity_path = OFFICIAL_RANK_DIR / "rank_portfolio_equity.csv"
    official_signals_path = OFFICIAL_RANK_DIR / "rank_portfolio_signals.csv"
    official_trades_path = OFFICIAL_RANK_DIR / "rank_portfolio_trades.csv"
    baseline_summary_path = BASELINE_RANK_DIR / "rank_portfolio_summary.json"
    summary = json.loads(official_summary_path.read_text(encoding="utf-8"))
    baseline_summary = json.loads(baseline_summary_path.read_text(encoding="utf-8"))

    settings = summary["settings"]
    dashboard_settings = {
        "capital": 1000000.0,
        "portfolio_max_positions": settings.get("portfolio_max_positions", 8),
        "portfolio_max_position_pct": settings.get("portfolio_max_position_pct", 0.20),
        "max_risk_per_trade": settings.get("max_risk_per_trade", 0.02),
        "atr_stop_multiplier": settings.get("atr_stop_multiplier", 5.0),
        "target_exposure": settings.get("target_exposure", 1.0),
        "take_profit_pct": settings.get("risk", {}).get("take_profit_pct", 1.0) if "risk" in settings else settings.get("take_profit_pct", 1.0),
        "trailing_stop_trigger": settings.get("risk", {}).get("trailing_stop_trigger", 0.3) if "risk" in settings else settings.get("trailing_stop_trigger", 0.3),
        "max_entry_volume_pct": settings.get("max_entry_volume_pct", 0.0),
        "max_entry_notional": settings.get("max_entry_notional", 0.0),
        "replacement_threshold": settings.get("replacement_threshold", 0.05),
        "replacement_cost_score_scale": settings.get("replacement_cost_score_scale", 10.0),
        "commission_rate": settings.get("commission_rate", 0.001425),
        "tax_rate": settings.get("tax_rate", 0.003),
        "slippage": settings.get("slippage", 0.001),
    }

    stock_info = load_stock_info()
    candidates = load_candidates(stock_info)
    signal_date = str(candidates["date"].max())[:10]
    market = candidates[candidates["date"].astype(str).str[:10].eq(signal_date)].iloc[0]

    dashboard = {}
    dashboard["openPositions"] = annotate_open_position_risk(load_open_positions(stock_info), candidates, signal_date)
    dashboard["tradeLog"] = load_trade_log(stock_info)

    odd = risk_parity_allocation(candidates[candidates["date"].astype(str).str[:10].eq(signal_date)], dashboard_settings, 1, open_positions=dashboard["openPositions"])
    round_lot = risk_parity_allocation(candidates[candidates["date"].astype(str).str[:10].eq(signal_date)], dashboard_settings, 1000, open_positions=dashboard["openPositions"])

    market_breadth = safe_float(market["market_breadth_ma20"])
    market_positive = safe_float(market["market_positive_return_5"])
    market_vol = safe_float(market["market_volatility_20"])
    regime = str(market["market_regime"])
    market_label = "高波動偏多" if regime == "high_vol" and market_breadth >= 0.6 else regime
    risk_deferred_count = int(odd["status_counts"].get("風控暫緩", 0))
    state = "防守型進攻" if odd["positions"] >= int(settings["portfolio_max_positions"]) and market_breadth >= settings["min_market_breadth_ma20"] and regime not in {"bear", "high_vol"} else "觀望"
    risk_level = "中" if summary["performance"]["max_drawdown"] <= 0.32 else "中高"
    buyable_count = int(odd["status_counts"].get("可買入", 0))
    waiting_count = int(odd["status_counts"].get("等待回調", 0))
    risk_notes = []
    if regime in {"bear", "high_vol"}:
        risk_notes.append("市場處於 bear/high_vol，不開追高新倉")
    if market_breadth < 0.50 or market_positive < 0.50:
        risk_notes.append("市場廣度或 5 日上漲家數偏弱，過熱股暫緩")

    equity = pd.read_csv(official_equity_path, parse_dates=["date"])
    dates = sorted(pd.to_datetime(equity["date"].dropna().unique()))
    benchmark = benchmark_metrics(summary.get("benchmark", {}), float(settings["capital"]), dates)

    dashboard = {
        "updatedAt": "2026-06-08",
        "dataDate": signal_date,
        "signalDate": signal_date,
        "rotation_date": signal_date,
        "strategyName": "長期龍頭輪動策略",
        "posture": "正式版 Risk Parity Best",
        "benchmark": "0050",
        "accountCapital": float(settings["capital"]),
        "regime": regime,
        "marketLabel": market_label,
        "decision": {
            "state": state,
            "scoreStars": 4 if state == "防守型進攻" else 2,
            "stance": f"收盤後產生隔日候選，現在 {buyable_count} 檔可買、{waiting_count} 檔等待回調、{risk_deferred_count} 檔風控暫緩" if state == "防守型進攻" else "市場條件不足或風險偏高，保留現金等待下一次訊號",
            "suggestedPositions": int(odd["positions"]),
            "suggestedUtilization": float(odd["capital_utilization"]),
            "marketEnvironment": market_label,
            "riskLevel": risk_level,
            "riskNotes": risk_notes,
            "riskDeferredCount": risk_deferred_count,
        },
        "aggressive": make_strategy_payload("正式版 Risk Parity Best", summary),
        "conservative": make_strategy_payload("原始固定權重 Baseline", baseline_summary),
        "benchmarkMetrics": benchmark,
        "weights": [
            {"key": "long_momentum", "label": "長期動能", "value": float(settings["weights"]["long_momentum"]), "detail": "60 / 120 / 252 日報酬排名，尋找長線相對強勢股"},
            {"key": "trend", "label": "趨勢結構", "value": float(settings["weights"]["trend"]), "detail": "MA20 / MA60 / ADX，確認價格仍在多頭趨勢內"},
            {"key": "momentum", "label": "短線動能", "value": float(settings["weights"]["momentum"]), "detail": "5 / 10 日報酬與 52 週位置，用來捕捉短線加速"},
            {"key": "flow", "label": "法人資金", "value": float(settings["weights"]["flow"]), "detail": "外資、投信與成交量排名，觀察資金是否跟進"},
            {"key": "fundamental", "label": "營收動能", "value": float(settings["weights"]["fundamental"]), "detail": "營收月增率排名，避免只買到純技術反彈"},
            {"key": "low_vol", "label": "波動控制", "value": float(settings["weights"]["low_vol"]), "detail": "偏好相對低波動標的，搭配 ATR 部位控管降低回撤"},
        ],
        "filters": [
            {"label": "市場健康度", "status": "達標" if market_breadth >= settings["min_market_breadth_ma20"] else "未達標", "value": market_breadth, "threshold": settings["min_market_breadth_ma20"], "copy": f"高於門檻 {settings['min_market_breadth_ma20'] * 100:.0f}% 才允許進攻"},
            {"label": "市場情緒", "status": "偏多" if market_positive >= settings["min_market_positive_return_5"] else "偏弱", "value": market_positive, "threshold": settings["min_market_positive_return_5"], "copy": f"高於門檻 {settings['min_market_positive_return_5'] * 100:.0f}% 才允許進攻"},
            {"label": "市場波動", "status": "可接受" if market_vol <= settings["max_market_volatility_20"] else "過熱", "value": market_vol, "threshold": settings["max_market_volatility_20"], "copy": f"需低於 {settings['max_market_volatility_20'] * 100:.1f}%"},
        ],
        "openPositions": load_open_positions(stock_info),
        "allocations": {
            "oddLot": {
                "label": "零股風險平價",
                "utilization": float(odd["capital_utilization"]),
                "cashLeft": float(odd["cash_left"]),
                "positions": int(odd["positions"]),
                "allocatedNotional": float(odd["allocated_notional"]),
                "concentration": concentration(odd["rows"]),
                "statusCounts": odd["status_counts"],
                "actionSummary": odd["action_summary"],
                "holdingRows": odd["holding_rows"],
                "rows": odd["rows"],
            },
            "roundLot": {
                "label": "整股風險平價",
                "utilization": float(round_lot["capital_utilization"]),
                "cashLeft": float(round_lot["cash_left"]),
                "positions": int(round_lot["positions"]),
                "allocatedNotional": float(round_lot["allocated_notional"]),
                "concentration": concentration(round_lot["rows"]),
                "statusCounts": round_lot["status_counts"],
                "actionSummary": round_lot["action_summary"],
                "holdingRows": round_lot["holding_rows"],
                "rows": round_lot["rows"],
            },
        },
    }
    feature_dates = pd.read_csv(PROCESSED_DATA, usecols=["date"])
    latest_feature_date = pd.Timestamp(pd.to_datetime(feature_dates["date"], errors="coerce").max()).strftime("%Y-%m-%d")
    rotation_source_date = max(pd.Timestamp(signal_date), pd.Timestamp(latest_feature_date)).strftime("%Y-%m-%d")
    rotation = build_rotation_data(rotation_source_date, candidates, odd["rows"], stock_info, candidate_date=signal_date)
    disposition_as_of = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    disposition_by_symbol = fetch_disposition_data(disposition_as_of)
    stock_search = build_stock_search_data(
        signal_date,
        candidates,
        dashboard["openPositions"],
        settings=dashboard_settings,
        disposition_by_symbol=disposition_by_symbol,
        disposition_as_of=disposition_as_of,
    )
    attribution = build_attribution_data(summary, official_signals_path, official_trades_path)

    benchmark_frame = None
    cache_files = sorted(BENCHMARK_CACHE_DIR.glob("benchmark_0050_*.csv"))
    if cache_files:
        benchmark_frame = pd.read_csv(cache_files[-1], parse_dates=["date"])[["date", "close"]]
        benchmark_frame["benchmarkEquity"] = benchmark_frame["close"] / float(benchmark_frame["close"].iloc[0]) * float(settings["capital"])

    curve = equity[["date", "equity", "drawdown", "capital_utilization", "open_positions"]].copy()
    if benchmark_frame is not None:
        curve = curve.merge(benchmark_frame[["date", "benchmarkEquity"]], on="date", how="left")
        curve["benchmarkEquity"] = curve["benchmarkEquity"].ffill()
    else:
        curve["benchmarkEquity"] = None
    curve = curve.iloc[::5].copy()
    points = [
        {
            "date": row["date"].strftime("%Y-%m-%d"),
            "strategy": float(row["equity"]),
            "benchmark": None if pd.isna(row["benchmarkEquity"]) else float(row["benchmarkEquity"]),
            "drawdown": None if pd.isna(row["drawdown"]) else float(row["drawdown"]),
            "utilization": None if pd.isna(row["capital_utilization"]) else float(row["capital_utilization"]),
            "positions": int(row["open_positions"]) if not pd.isna(row["open_positions"]) else 0,
        }
        for _, row in curve.iterrows()
    ]
    equity_data = {
        "periodStart": equity["date"].min().strftime("%Y-%m-%d"),
        "periodEnd": equity["date"].max().strftime("%Y-%m-%d"),
        "points": points,
    }
    run_context = {
        "runId": args.run_id,
        "strategyVersion": args.strategy_version,
        "asOfDate": signal_date,
        "configHash": args.config_hash,
    }
    for payload in [dashboard, rotation, equity_data, stock_search, attribution]:
        payload["runContext"] = run_context

    write_js(FRONT_DATA / "dashboardData.js", "dashboardData", dashboard)
    write_js(FRONT_DATA / "rotationData.js", "rotationData", rotation)
    write_js(FRONT_DATA / "equityData.js", "equityData", equity_data)
    write_js(FRONT_DATA / "stockSearchData.js", "stockSearchData", stock_search)
    write_js(FRONT_DATA / "attributionData.js", "attributionData", attribution)

    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": args.run_id,
                "official_summary": str(official_summary_path),
                "signal_date": signal_date,
                "rotation_date": rotation["summary"]["sourceDate"],
                "search_stocks": stock_search["summary"]["stockCount"],
                "disposition_stocks": stock_search["summary"]["dispositionCount"],
                "odd_lot_utilization": odd["capital_utilization"],
                "positions": odd["positions"],
                "equity_points": len(points),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
