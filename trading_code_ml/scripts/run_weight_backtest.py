"""
回測選股權重：調高基本面與籌碼面比重
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
for p in [str(ROOT), str(SCRIPT_DIR), str(PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from run_cycle_strategy_wfa import _attach_cycles, _load_data  # noqa: E402
from run_portfolio_strategy_wfa import _normalize_settings, _performance, _run_portfolio  # noqa: E402
from run_rank_portfolio_backtest import _make_rank_signals  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.institutional_overlay import overlay_recent_official_institutional_flow  # noqa: E402

DEFAULT_DATA = PROJECT_ROOT / "data" / "processed" / "all_features.csv"

def run_weight_scenario(data, settings, weights, scenario_name):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 開始測試組合: {scenario_name}")
    print(f"權重: {weights}")
    
    allowed_signal_regimes = {"bull", "high_vol", "neutral", "recovery"}
    
    signals = _make_rank_signals(
        data=data,
        top_n=12,
        min_score=0.62,
        allowed_signal_regimes=allowed_signal_regimes,
        weights=weights,
        min_market_breadth_ma20=0.42,
        min_market_positive_return_5=0.22,
        max_market_volatility_20=0.055,
    )
    
    result = _run_portfolio(
        signals=signals,
        settings=settings,
        capital=1_000_000,
        target_exposure=1.0,
        max_positions=8,
        max_position_pct=0.20,
        min_trade_unit=1,
        drawdown_block_threshold=0.0,
        position_sizing="risk_parity",
        max_risk_per_trade=0.02,
        max_correlation=0.0,
        correlation_lookback=60,
        max_positions_per_industry=0,
        rebalance_trigger=0.0,
        sentiment_overlay=False,
    )
    
    perf = _performance(result)
    
    print(f"結果 -> CAGR: {perf['cagr']:.2%}, 勝率: {perf['win_rate']:.2%}, 最大回撤: {perf['max_drawdown']:.2%}")
    return {
        "情境": scenario_name,
        "籌碼面權重": f"{weights['flow']:.0%}",
        "基本面權重": f"{weights['fundamental']:.0%}",
        "長天期動能權重": f"{weights['long_momentum']:.0%}",
        "CAGR": perf["cagr"],
        "勝率": perf["win_rate"],
        "最大回撤": perf["max_drawdown"],
        "獲利因子": perf.get("profit_factor", np.nan),
        "交易次數": perf["trades"]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "weight_test_backtest")
    args, _ = parser.parse_known_args()

    settings = _normalize_settings(load_settings(args.config))
    settings["trading"]["initial_capital"] = 1_000_000
    settings["trading"]["min_trade_unit"] = 1
    settings["trading"]["holding_period_max"] = 180

    print("載入資料中... (這可能需要一點時間)")
    data = _load_data(args.data, None, None)
    data = overlay_recent_official_institutional_flow(data)
    scored = _attach_cycles(data, settings)

    scenarios = [
        {
            "name": "原版預設 (動能為主)",
            "weights": {
                "momentum": 0.08, "long_momentum": 0.55, "trend": 0.25,
                "flow": 0.04, "fundamental": 0.04, "low_vol": 0.08
            }
        },
        {
            "name": "稍微提高基本與籌碼 (各 15%)",
            "weights": {
                "momentum": 0.05, "long_momentum": 0.40, "trend": 0.20,
                "flow": 0.15, "fundamental": 0.15, "low_vol": 0.05
            }
        },
        {
            "name": "均衡配置 (四大指標各 20~25%)",
            "weights": {
                "momentum": 0.05, "long_momentum": 0.20, "trend": 0.20,
                "flow": 0.25, "fundamental": 0.25, "low_vol": 0.05
            }
        },
        {
            "name": "基本與籌碼為主 (各 35%)",
            "weights": {
                "momentum": 0.05, "long_momentum": 0.10, "trend": 0.10,
                "flow": 0.35, "fundamental": 0.35, "low_vol": 0.05
            }
        }
    ]

    results_list = []
    for s in scenarios:
        res = run_weight_scenario(scored, settings, s["weights"], s["name"])
        results_list.append(res)

    df_results = pd.DataFrame(results_list)
    df_results = df_results.sort_values("CAGR", ascending=False).reset_index(drop=True)
    
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = args.output_dir / f"weight_test_results_{stamp}.csv"
    df_results.to_csv(out_csv, index=False, encoding="utf-8-sig")
    
    print("\n" + "="*90)
    print("權重測試結果排序 (按年化報酬率 CAGR 排序):")
    print("="*90)
    format_str = "{:<25} | {:<5} | {:<5} | {:<5} | {:>8} | {:>7} | {:>9} | {:>8} | {:>8}"
    print(format_str.format("情境", "籌碼%", "基本%", "動能%", "年化報酬", "勝率", "最大回撤", "獲利因子", "交易次數"))
    print("-" * 90)
    for _, row in df_results.iterrows():
        print(format_str.format(
            row['情境'], row['籌碼面權重'], row['基本面權重'], row['長天期動能權重'], 
            f"{row['CAGR']:.2%}", f"{row['勝率']:.2%}", f"{row['最大回撤']:.2%}", 
            f"{row['獲利因子']:.2f}" if pd.notna(row['獲利因子']) else "N/A", f"{row['交易次數']:.0f}"
        ))
    print("="*90)
    print(f"[saved] {out_csv}")


if __name__ == "__main__":
    main()
