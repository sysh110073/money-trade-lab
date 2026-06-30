"""
回測策略網格搜尋：不同基礎分數與日增條件
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
from run_score_momentum_backtest import _make_score_momentum_signals  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.institutional_overlay import overlay_recent_official_institutional_flow  # noqa: E402


DEFAULT_DATA = PROJECT_ROOT / "data" / "processed" / "all_features.csv"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "grid_search_backtest")
    args, unknown = parser.parse_known_args()

    settings = _normalize_settings(load_settings(args.config))
    settings["trading"]["initial_capital"] = 1_000_000
    settings["trading"]["min_trade_unit"] = 1
    settings["trading"]["holding_period_max"] = 180

    print("載入資料中... (這可能需要一點時間)")
    data = _load_data(args.data, None, None)
    data = overlay_recent_official_institutional_flow(data)
    scored = _attach_cycles(data, settings)

    weights = {
        "momentum": 0.08,
        "long_momentum": 0.55,
        "trend": 0.25,
        "flow": 0.04,
        "fundamental": 0.04,
        "low_vol": 0.08,
    }
    allowed_signal_regimes = {"bull", "high_vol", "neutral", "recovery"}

    thresholds = [0.90, 0.85]
    increases = [0.05]
    
    results_list = []

    for threshold in thresholds:
        for increase in increases:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 開始測試組合: 分數 >= {threshold*100:.0f}, 日增 >= {increase*100:.0f}")
            
            signals = _make_score_momentum_signals(
                data=scored,
                weights=weights,
                score_threshold=threshold,
                score_daily_increase=increase,
                allowed_signal_regimes=allowed_signal_regimes,
                min_market_breadth_ma20=0.42,
                min_market_positive_return_5=0.22,
                max_market_volatility_20=0.055,
                top_n=20,
            )
            
            total_signals = int(signals["entry_signal"].eq(1).sum())
            if total_signals == 0:
                print(f"無買入訊號，跳過")
                continue
                
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
            
            results_list.append({
                "分數門檻": f"{threshold*100:.0f}分",
                "日增門檻": f"{increase*100:.0f}分",
                "CAGR": perf["cagr"],
                "勝率": perf["win_rate"],
                "最大回撤": perf["max_drawdown"],
                "獲利因子": perf.get("profit_factor", np.nan),
                "交易次數": perf["trades"],
                "總報酬率": perf["total_return"]
            })
            print(f"結果 -> CAGR: {perf['cagr']:.2%}, 勝率: {perf['win_rate']:.2%}, 交易次數: {perf['trades']}")

    if not results_list:
        print("沒有組合產生任何結果。")
        return

    # 將結果轉換成 DataFrame 並依據 CAGR 排序
    df_results = pd.DataFrame(results_list)
    df_results = df_results.sort_values("CAGR", ascending=False).reset_index(drop=True)
    
    # 儲存結果
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = args.output_dir / f"grid_search_results_{stamp}.csv"
    df_results.to_csv(out_csv, index=False, encoding="utf-8-sig")
    
    # 格式化輸出
    print("\n" + "="*80)
    print("網格搜尋結果排序 (按年化報酬率 CAGR 排序):")
    print("="*80)
    # Print formatted table
    format_str = "{:<6} | {:<6} | {:>8} | {:>7} | {:>9} | {:>8} | {:>8}"
    print(format_str.format("基本分", "日增分", "年化報酬", "勝率", "最大回撤", "獲利因子", "交易次數"))
    print("-" * 80)
    for _, row in df_results.iterrows():
        cagr_str = f"{row['CAGR']:.2%}"
        win_str = f"{row['勝率']:.2%}"
        dd_str = f"{row['最大回撤']:.2%}"
        pf_val = row['獲利因子']
        pf_str = f"{pf_val:.2f}" if pd.notna(pf_val) else "N/A"
        trades_str = f"{row['交易次數']:.0f}"
        print(format_str.format(
            row['分數門檻'], row['日增門檻'], 
            cagr_str, win_str, dd_str, pf_str, trades_str
        ))
    print("="*80)
    print(f"[saved] {out_csv}")


if __name__ == "__main__":
    main()
