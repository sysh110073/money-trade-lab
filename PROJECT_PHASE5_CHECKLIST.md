# Money Trade 第五階段優化檢查表

本階段只處理 forward simulation `candidate_buy_signals=0` 的可觀測性。檢查結果顯示不是流程錯誤，而是 2026-06-05 至 2026-06-29 期間全部落在 `high_vol` regime，production 設定只允許 `bull, neutral, recovery` 進場。

| ID | 優化項目 | 狀態 | 負責檔案 | 驗收方式 | 證據 |
| --- | --- | --- | --- | --- | --- |
| P5-1 | Forward 無訊號原因診斷 | PASS | `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | 重跑 forward simulation 並讀 `rank_portfolio_summary.json` | summary 新增 `signal_diagnostics`；`no_entry_primary_blocker=signal_regime_gate` |
| P5-2 | Signals CSV 保留 gate 欄位 | PASS | `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | 讀 `trading_code_ml/results/forward_simulation/rank_portfolio_signals.csv` | 輸出 `signal_rank_gate`、`signal_score_gate`、`signal_regime_gate`、`signal_market_gate` 等欄位 |
| P5-3 | 最小自檢覆蓋 | PASS | `trading_code_ml/scripts/test_pandas_logic.py` | `python trading_code_ml\scripts\test_pandas_logic.py` | assert 驗證 high-vol 無進場時主阻擋原因為 `signal_regime_gate` |

## 驗收 Run

| 項目 | 結果 |
| --- | --- |
| forward period | `2026-06-05` to `2026-06-29` |
| rows | `7918` |
| dates | `16` |
| entry signals | `0` |
| max strategy score | `0.9603730924` |
| market regime counts | `high_vol=7918` |
| signal rank gate rows | `192` |
| signal score gate rows | `2291` |
| signal regime gate rows | `0` |
| no entry primary blocker | `signal_regime_gate` |

## 本階段不做

| 延後項目 | 原因 |
| --- | --- |
| 放寬 high-vol 進場 | 這會改變 production 風控，不應只因 forward 沒交易就調低門檻 |
| 建立完整策略歸因儀表板 | 目前 summary 診斷已能回答無訊號原因；儀表板等到歸因需求更明確再做 |
