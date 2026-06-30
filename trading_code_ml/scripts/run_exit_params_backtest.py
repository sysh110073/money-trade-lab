"""
回測停利停損參數組合：10組不同出場邏輯測試
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

def run_exit_scenario(data, settings, params, scenario_name, shared_signals):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 開始測試組合: {scenario_name}")
    print(f"參數: {params}")
    
    # 複製 settings 以避免污染
    import copy
    scenario_settings = copy.deepcopy(settings)
    
    # 套用出場參數
    scenario_settings["risk"]["atr_stop_multiplier"] = params["atr_stop_multiplier"]
    scenario_settings["risk"]["take_profit_pct"] = params["take_profit_pct"]
    scenario_settings["risk"]["trailing_stop_trigger"] = params["trailing_stop_trigger"]
    scenario_settings["risk"]["trailing_stop_atr"] = params["trailing_stop_atr"]
    scenario_settings["trading"]["holding_period_max"] = params["holding_period_max"]
    
    signals = shared_signals.copy()
    if params.get("score_drop_exit"):
        scenario_settings["trading"]["use_strategy_exit"] = True
        scenario_settings["strategy"] = scenario_settings.get("strategy", {})
        scenario_settings["strategy"]["use_strategy_exit"] = True
        
        drop_thresh = params["score_drop_exit"]
        signals["exit_signal"] = np.where(signals["strategy_score_change"] <= -drop_thresh, -1, 0)
        print(f"啟動策略分數下跌出場 (門檻: {drop_thresh*100:.0f}分)")
    
    result = _run_portfolio(
        signals=signals,
        settings=scenario_settings,
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
        "編號與情境": scenario_name,
        "初始停損(ATR)": f"{params['atr_stop_multiplier']}x",
        "固定停利": f"{params['take_profit_pct']*100:.0f}%",
        "移動停損啟動": f"{params['trailing_stop_trigger']*100:.0f}%",
        "移動停損距離": f"{params['trailing_stop_atr']}x",
        "最大持有(天)": params['holding_period_max'],
        "分數下跌出場": f"{params['score_drop_exit']*100:.0f}分" if params.get("score_drop_exit") else "無",
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
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "exit_params_backtest")
    args, _ = parser.parse_known_args()

    settings = _normalize_settings(load_settings(args.config))
    settings["trading"]["initial_capital"] = 1_000_000
    settings["trading"]["min_trade_unit"] = 1

    print("載入資料中... (這可能需要一點時間)")
    data = _load_data(args.data, None, None)
    data = overlay_recent_official_institutional_flow(data)
    scored = _attach_cycles(data, settings)

    # 為了加速測試，先產生共用的預設進場訊號 (原版長線動能為主 Rank Portfolio)
    print("產生共用進場訊號...")
    default_weights = {
        "momentum": 0.08, "long_momentum": 0.55, "trend": 0.25,
        "flow": 0.04, "fundamental": 0.04, "low_vol": 0.08
    }
    allowed_signal_regimes = {"bull", "high_vol", "neutral", "recovery"}
    
    shared_signals = _make_rank_signals(
        data=scored,
        top_n=12,
        min_score=0.62,
        allowed_signal_regimes=allowed_signal_regimes,
        weights=default_weights,
        min_market_breadth_ma20=0.42,
        min_market_positive_return_5=0.22,
        max_market_volatility_20=0.055,
    )
    
    # 計算分數增減
    shared_signals = shared_signals.sort_values(["symbol", "date"]).reset_index(drop=True)
    shared_signals["prev_strategy_score"] = shared_signals.groupby("symbol")["strategy_score"].shift(1)
    shared_signals["strategy_score_change"] = shared_signals["strategy_score"] - shared_signals["prev_strategy_score"]
    shared_signals = shared_signals.sort_values(["date", "symbol"]).reset_index(drop=True)

    scenarios = [
        {"name": "1. 現有基準 (寬停損、大停利)", 
         "params": {"atr_stop_multiplier": 5.0, "take_profit_pct": 1.0, "trailing_stop_trigger": 0.30, "trailing_stop_atr": 3.5, "holding_period_max": 180}},
        {"name": "2. 傳統趨勢跟蹤 (無固定停利，純看移動停損)", 
         "params": {"atr_stop_multiplier": 3.0, "take_profit_pct": 9.9, "trailing_stop_trigger": 0.10, "trailing_stop_atr": 2.5, "holding_period_max": 180}},
        {"name": "3. 緊縮停損與防守 (快速鎖定利潤)", 
         "params": {"atr_stop_multiplier": 2.0, "take_profit_pct": 0.20, "trailing_stop_trigger": 0.05, "trailing_stop_atr": 1.5, "holding_period_max": 60}},
        {"name": "4. 中庸之道 (適度波動空間)", 
         "params": {"atr_stop_multiplier": 2.5, "take_profit_pct": 0.30, "trailing_stop_trigger": 0.08, "trailing_stop_atr": 2.0, "holding_period_max": 60}},
        {"name": "5. 波段操作 (抓取 15% 即走)", 
         "params": {"atr_stop_multiplier": 2.0, "take_profit_pct": 0.15, "trailing_stop_trigger": 9.9, "trailing_stop_atr": 9.9, "holding_period_max": 30}},
        {"name": "6. 長線放風箏 (給予極大空間洗盤)", 
         "params": {"atr_stop_multiplier": 6.0, "take_profit_pct": 1.0, "trailing_stop_trigger": 0.20, "trailing_stop_atr": 4.0, "holding_period_max": 180}},
        {"name": "7. 嚴格時間停損 (短線不漲就走)", 
         "params": {"atr_stop_multiplier": 2.0, "take_profit_pct": 0.30, "trailing_stop_trigger": 0.05, "trailing_stop_atr": 1.5, "holding_period_max": 15}},
        {"name": "8. 早一步移動停損 (獲利3%就啟動)", 
         "params": {"atr_stop_multiplier": 2.5, "take_profit_pct": 0.50, "trailing_stop_trigger": 0.03, "trailing_stop_atr": 2.0, "holding_period_max": 90}},
        {"name": "9. 大波段與小回撤 (嚴格移動停損)", 
         "params": {"atr_stop_multiplier": 3.0, "take_profit_pct": 0.50, "trailing_stop_trigger": 0.10, "trailing_stop_atr": 1.5, "holding_period_max": 180}},
        {"name": "10. 寬初始、緊移動 (進場給空間，賺錢就盯緊)", 
         "params": {"atr_stop_multiplier": 4.0, "take_profit_pct": 0.80, "trailing_stop_trigger": 0.15, "trailing_stop_atr": 1.5, "holding_period_max": 180}},
        {"name": "11. 基準 + 分數下跌5分出場", 
         "params": {"atr_stop_multiplier": 5.0, "take_profit_pct": 1.0, "trailing_stop_trigger": 0.30, "trailing_stop_atr": 3.5, "holding_period_max": 180, "score_drop_exit": 0.05}},
        {"name": "12. 基準 + 分數下跌10分出場", 
         "params": {"atr_stop_multiplier": 5.0, "take_profit_pct": 1.0, "trailing_stop_trigger": 0.30, "trailing_stop_atr": 3.5, "holding_period_max": 180, "score_drop_exit": 0.10}},
        {"name": "13. 基準 + 分數下跌15分出場", 
         "params": {"atr_stop_multiplier": 5.0, "take_profit_pct": 1.0, "trailing_stop_trigger": 0.30, "trailing_stop_atr": 3.5, "holding_period_max": 180, "score_drop_exit": 0.15}},
    ]

    results_list = []
    for s in scenarios:
        res = run_exit_scenario(scored, settings, s["params"], s["name"], shared_signals)
        results_list.append(res)

    df_results = pd.DataFrame(results_list)
    df_results = df_results.sort_values("CAGR", ascending=False).reset_index(drop=True)
    
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = args.output_dir / f"exit_params_results_{stamp}.csv"
    df_results.to_csv(out_csv, index=False, encoding="utf-8-sig")
    
    print("\n" + "="*120)
    print("停損停利參數測試結果排序 (按年化報酬率 CAGR 排序):")
    print("="*120)
    format_str = "{:<32} | {:<8} | {:<8} | {:<10} | {:<8} | {:<7} | {:<10} | {:>8} | {:>7} | {:>8} | {:>7}"
    print(format_str.format("情境", "初始停損", "停利目標", "移動停損啟動", "移動距離", "最大天數", "分數下跌出場", "年化報酬", "勝率", "最大回撤", "獲利因子"))
    print("-" * 120)
    for _, row in df_results.iterrows():
        print(format_str.format(
            row['編號與情境'], row['初始停損(ATR)'], row['固定停利'], row['移動停損啟動'], row['移動停損距離'], str(row['最大持有(天)']), str(row.get('分數下跌出場', '無')),
            f"{row['CAGR']:.2%}", f"{row['勝率']:.2%}", f"{row['最大回撤']:.2%}", f"{row['獲利因子']:.2f}" if pd.notna(row['獲利因子']) else "N/A"
        ))
    print("="*120)
    print(f"[saved] {out_csv}")


if __name__ == "__main__":
    main()
