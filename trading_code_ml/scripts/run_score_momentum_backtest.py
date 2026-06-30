"""
回測策略：策略分數日增10分且策略分數大於80分時買入
--------------------------------------------------
基於 run_rank_portfolio_backtest.py 的 _build_score，計算每日策略分數，
當某檔股票的策略分數 > 0.80（百分位 80 分）且較前一日上升 >= 0.10（10分）時，
產生買入訊號。
"""
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
for p in [str(ROOT), str(SCRIPT_DIR), str(PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from run_cycle_strategy_wfa import _attach_cycles, _load_data  # noqa: E402
from run_portfolio_strategy_wfa import (  # noqa: E402
    _benchmark_metrics,
    _normalize_settings,
    _performance,
    _run_portfolio,
)
from run_rank_portfolio_backtest import (  # noqa: E402
    _build_score,
)
from src.config import load_settings  # noqa: E402
from src.institutional_overlay import overlay_recent_official_institutional_flow  # noqa: E402
from src.strategy_catalog import add_strategy_ranks  # noqa: E402


DEFAULT_DATA = PROJECT_ROOT / "data" / "processed" / "all_features.csv"


def _make_score_momentum_signals(
    data: pd.DataFrame,
    weights: dict[str, float],
    score_threshold: float,
    score_daily_increase: float,
    allowed_signal_regimes: set[str] | None,
    min_market_breadth_ma20: float | None,
    min_market_positive_return_5: float | None,
    max_market_volatility_20: float | None,
    top_n: int,
) -> pd.DataFrame:
    """
    產生訊號：策略分數 > score_threshold 且日增 >= score_daily_increase
    """
    scored = add_strategy_ranks(data.copy())
    scored["strategy_score"] = _build_score(scored, weights)

    # 計算每日策略分數變動量（每支股票各自算）
    scored = scored.sort_values(["symbol", "date"]).reset_index(drop=True)
    scored["prev_strategy_score"] = scored.groupby("symbol")["strategy_score"].shift(1)
    scored["strategy_score_change"] = scored["strategy_score"] - scored["prev_strategy_score"]

    # 排名（用於同日多訊號時排序，仍保留）
    scored["rank_signal_score"] = scored.groupby("date")["strategy_score"].rank(
        ascending=False, method="first"
    )

    # 市場過濾條件
    market_ok = pd.Series(True, index=scored.index)
    if allowed_signal_regimes:
        market_ok &= scored["market_regime"].astype(str).isin(allowed_signal_regimes)
    if min_market_breadth_ma20 is not None:
        market_ok &= pd.to_numeric(scored["market_breadth_ma20"], errors="coerce") >= min_market_breadth_ma20
    if min_market_positive_return_5 is not None:
        market_ok &= pd.to_numeric(scored["market_positive_return_5"], errors="coerce") >= min_market_positive_return_5
    if max_market_volatility_20 is not None:
        market_ok &= pd.to_numeric(scored["market_volatility_20"], errors="coerce") <= max_market_volatility_20

    # 核心買入條件：分數 > 80 且日增 >= 10 分
    score_condition = (scored["strategy_score"] >= score_threshold)
    momentum_condition = (scored["strategy_score_change"] >= score_daily_increase)
    entry = score_condition & momentum_condition & market_ok

    # 選取每日前 top_n 個信號（按分數排名）
    if top_n > 0:
        entry &= scored["rank_signal_score"] <= top_n

    scored["signal"] = 0
    scored["entry_signal"] = 0
    scored.loc[entry, ["signal", "entry_signal"]] = 1
    scored["signal_tier"] = np.where(entry, "score_momentum", "")
    scored["selected_strategy_count"] = np.where(entry, 1, 0)
    scored["selected_strategy_ids"] = np.where(entry, "score_momentum_80_10", "")

    return scored.sort_values(["date", "symbol"]).reset_index(drop=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="回測：策略分數日增10分且>80分時買入"
    )
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
    parser.add_argument("--min-trade-unit", type=int, default=1)
    parser.add_argument("--holding-period-max", type=int, default=180)
    parser.add_argument("--drawdown-block-threshold", type=float, default=0.0)
    parser.add_argument("--atr-stop-multiplier", type=float, default=5.0)
    parser.add_argument("--take-profit-pct", type=float, default=1.0)
    parser.add_argument("--trailing-stop-trigger", type=float, default=0.3)
    parser.add_argument("--trailing-stop-atr", type=float, default=3.5)
    # 策略分數門檻（百分位，0-1 表示法）
    parser.add_argument("--score-threshold", type=float, default=0.80,
                        help="策略分數門檻，預設 0.80 = 80分")
    # 策略分數日增門檻
    parser.add_argument("--score-daily-increase", type=float, default=0.10,
                        help="策略分數日增門檻，預設 0.10 = 10分")
    parser.add_argument("--top-n", type=int, default=20,
                        help="每日最多取前N名訊號")
    parser.add_argument("--allowed-signal-regimes", default="bull,high_vol,neutral,recovery")
    parser.add_argument("--min-market-breadth-ma20", type=float, default=0.42)
    parser.add_argument("--min-market-positive-return-5", type=float, default=0.22)
    parser.add_argument("--max-market-volatility-20", type=float, default=0.055)
    parser.add_argument("--momentum-weight", type=float, default=0.08)
    parser.add_argument("--long-momentum-weight", type=float, default=0.55)
    parser.add_argument("--trend-weight", type=float, default=0.25)
    parser.add_argument("--flow-weight", type=float, default=0.04)
    parser.add_argument("--fundamental-weight", type=float, default=0.04)
    parser.add_argument("--low-vol-weight", type=float, default=0.08)
    parser.add_argument("--benchmark-symbol", default="0050")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "score_momentum_backtest")
    args = parser.parse_args()

    settings = _normalize_settings(load_settings(args.config))
    settings["trading"]["initial_capital"] = float(args.capital)
    settings["trading"]["min_trade_unit"] = int(args.min_trade_unit)
    settings["trading"]["holding_period_max"] = int(args.holding_period_max)
    for arg_name, key in [
        ("atr_stop_multiplier", "atr_stop_multiplier"),
        ("take_profit_pct", "take_profit_pct"),
        ("trailing_stop_trigger", "trailing_stop_trigger"),
        ("trailing_stop_atr", "trailing_stop_atr"),
    ]:
        value = getattr(args, arg_name)
        if value is not None:
            settings["risk"][key] = float(value)

    print("[score_momentum] 載入資料...")
    data = _load_data(args.data, None, None)
    data = overlay_recent_official_institutional_flow(data)
    scored = _attach_cycles(data, settings)

    allowed_signal_regimes = {
        item.strip() for item in args.allowed_signal_regimes.split(",") if item.strip()
    }
    weights = {
        "momentum": args.momentum_weight,
        "long_momentum": args.long_momentum_weight,
        "trend": args.trend_weight,
        "flow": args.flow_weight,
        "fundamental": args.fundamental_weight,
        "low_vol": args.low_vol_weight,
    }

    print(f"[score_momentum] 產生訊號: score>{args.score_threshold} & daily_increase>={args.score_daily_increase}")
    signals = _make_score_momentum_signals(
        scored,
        weights,
        args.score_threshold,
        args.score_daily_increase,
        allowed_signal_regimes,
        args.min_market_breadth_ma20,
        args.min_market_positive_return_5,
        args.max_market_volatility_20,
        args.top_n,
    )

    total_signals = int(signals["entry_signal"].eq(1).sum())
    signal_dates = int(signals.loc[signals["entry_signal"].eq(1), "date"].nunique())
    print(f"[score_momentum] 總訊號數: {total_signals}，涵蓋 {signal_dates} 個交易日")

    if total_signals == 0:
        print("[score_momentum] 沒有產生任何買入訊號！嘗試放寬條件...")
        # 統計分數分布
        has_score = signals["strategy_score"].notna()
        has_change = signals["strategy_score_change"].notna()
        print(f"  分數範圍: {signals.loc[has_score, 'strategy_score'].min():.4f} ~ {signals.loc[has_score, 'strategy_score'].max():.4f}")
        print(f"  日增範圍: {signals.loc[has_change, 'strategy_score_change'].min():.4f} ~ {signals.loc[has_change, 'strategy_score_change'].max():.4f}")
        q80 = signals.loc[has_score, "strategy_score"].quantile(0.80)
        q90 = signals.loc[has_score, "strategy_score"].quantile(0.90)
        q95 = signals.loc[has_score, "strategy_score"].quantile(0.95)
        print(f"  分數分位: 80%={q80:.4f}, 90%={q90:.4f}, 95%={q95:.4f}")
        above_80 = (signals["strategy_score"] >= args.score_threshold).sum()
        above_80_and_change = (
            (signals["strategy_score"] >= args.score_threshold)
            & (signals["strategy_score_change"] >= args.score_daily_increase)
        ).sum()
        print(f"  分數>{args.score_threshold}: {above_80} 筆")
        print(f"  分數>{args.score_threshold} 且日增>={args.score_daily_increase}: {above_80_and_change} 筆")
        # 看不同閾值的訊號數量
        for sc in [0.70, 0.75, 0.80, 0.85]:
            for di in [0.05, 0.08, 0.10, 0.15]:
                n = ((signals["strategy_score"] >= sc) & (signals["strategy_score_change"] >= di)).sum()
                if n > 0:
                    print(f"  score>={sc:.2f} & change>={di:.2f}: {n} 筆")

    print("[score_momentum] 執行回測...")
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
        False,  # no sentiment overlay
    )
    perf = _performance(result)

    # 基準指標
    benchmark_dates = sorted(pd.to_datetime(signals["date"].dropna().unique()))
    benchmark = _benchmark_metrics(
        data, settings, args.benchmark_symbol, benchmark_dates,
        args.output_dir / "benchmark_data"
    )

    # 比較結果
    baseline_cagr = 0.243  # 現有策略 24.3%
    summary = {
        "strategy_name": "策略分數日增10分且>80分買入",
        "entry_conditions": {
            "score_threshold": args.score_threshold,
            "score_daily_increase": args.score_daily_increase,
            "description": f"策略分數 >= {args.score_threshold*100:.0f} 且 日增 >= {args.score_daily_increase*100:.0f} 分",
        },
        "performance": perf,
        "benchmark": benchmark,
        "comparison_with_baseline": {
            "baseline_cagr": baseline_cagr,
            "new_cagr": perf["cagr"],
            "cagr_difference": perf["cagr"] - baseline_cagr,
            "cagr_improvement_pct": (perf["cagr"] - baseline_cagr) / baseline_cagr * 100 if baseline_cagr != 0 else None,
            "verdict": "改善" if perf["cagr"] > baseline_cagr else "退步",
        },
        "signal_stats": {
            "total_buy_signals": total_signals,
            "signal_days": signal_dates,
        },
        "settings": {
            "capital": args.capital,
            "target_exposure": args.target_exposure,
            "portfolio_max_positions": args.portfolio_max_positions,
            "portfolio_max_position_pct": args.portfolio_max_position_pct,
            "position_sizing": args.position_sizing,
            "weights": weights,
        },
    }

    # 儲存結果
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    summary_path = args.output_dir / f"score_momentum_summary_{stamp}.json"
    equity_path = args.output_dir / f"score_momentum_equity_{stamp}.csv"
    trades_path = args.output_dir / f"score_momentum_trades_{stamp}.csv"

    result["equity_curve"].to_csv(equity_path, index=False, encoding="utf-8-sig")
    result["trade_log"].to_csv(trades_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8"
    )

    # 印出結果
    print("\n" + "=" * 70)
    print("回測結果：策略分數日增10分且>80分買入策略")
    print("=" * 70)
    print(f"  年化報酬率 (CAGR):     {perf['cagr']:.2%}")
    print(f"  總報酬率:              {perf['total_return']:.2%}")
    print(f"  夏普比率:              {perf['sharpe']:.3f}")
    print(f"  最大回撤:              {perf['max_drawdown']:.2%}")
    print(f"  勝率:                  {perf['win_rate']:.2%}")
    print(f"  獲利因子:              {perf['profit_factor']:.3f}" if np.isfinite(perf.get('profit_factor', np.nan)) else f"  獲利因子:              N/A")
    print(f"  總交易次數:            {perf['trades']:.0f}")
    print(f"  平均資金使用率:        {perf['mean_capital_utilization']:.2%}")
    print(f"  總買入訊號數:          {total_signals}")
    print("-" * 70)
    print("與現有策略比較")
    print("-" * 70)
    print(f"  現有策略 CAGR:         {baseline_cagr:.2%}")
    print(f"  新策略 CAGR:           {perf['cagr']:.2%}")
    diff = perf['cagr'] - baseline_cagr
    print(f"  差異:                  {diff:+.2%}")
    if baseline_cagr != 0:
        print(f"  變動幅度:              {diff/baseline_cagr*100:+.1f}%")
    if perf['cagr'] > baseline_cagr:
        print("  [O] 新策略 優於 現有策略")
    elif perf['cagr'] < baseline_cagr:
        print("  [X] 新策略 劣於 現有策略")
    else:
        print("  [-] 兩策略表現相同")
    if benchmark.get("found"):
        print("-" * 70)
        print(f"  Benchmark ({args.benchmark_symbol}) CAGR: {benchmark['cagr']:.2%}")
        print(f"  Benchmark Sharpe:      {benchmark['sharpe']:.3f}")
    print("=" * 70)
    print(f"[saved] {summary_path}")
    print(f"[saved] {equity_path}")
    print(f"[saved] {trades_path}")


if __name__ == "__main__":
    main()
