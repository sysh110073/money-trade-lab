# Money Trade 第四階段優化檢查表

本階段聚焦第三階段 TCA 暴露的問題：`replacement_switch` 在扣除交易成本後曾經轉為淨虧。這次不新增大型框架，只把替換交易納入成本門檻，並讓正式流程、summary、前端資料產生器共用同一設定。

| ID | 優化項目 | 狀態 | 負責檔案 | 驗收方式 | 證據 |
| --- | --- | --- | --- | --- | --- |
| P4-1 | Replacement TCA gate | PASS | `trading_code_ml/scripts/run_portfolio_strategy_wfa.py` | `python trading_code_ml\scripts\test_pandas_logic.py`；正式 daily run | 替換交易需通過 `replacement_threshold + estimated_cost/equity*replacement_cost_score_scale`；official summary 顯示 `replacement_cost_gate_rejections=543` |
| P4-2 | 正式設定一致化 | PASS | `trading_code_ml/config/production.yaml`, `scripts/daily_update.ps1`, `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | `rg replacement_cost_score_scale trading_code_ml\scripts scripts trading_code_ml\config` | `production.yaml` 設定 `replacement_cost_score_scale: 10.0`，daily script 傳入 `--replacement-cost-score-scale` |
| P4-3 | Summary/TCA 可追蹤 | PASS | `trading_code_ml/scripts/run_rank_portfolio_backtest.py`, `trading_code_ml/scripts/run_portfolio_strategy_wfa.py` | 讀取 `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_summary.json` | summary settings 含 `replacement_threshold=0.05`、`replacement_cost_score_scale=10.0`；TCA 含 `replacement_cost_gate_rejections=543` |
| P4-4 | 前端建議同步 replacement gate | PASS | `frontend/scripts/generate_dashboard_data.py`, `frontend/src/data/*.js` | `.\npm-local.cmd run build` from `frontend` | dashboard allocation 使用同一成本懲罰；Vite build PASS |
| P4-5 | 最小自檢覆蓋 | PASS | `trading_code_ml/scripts/test_pandas_logic.py` | `python trading_code_ml\scripts\test_pandas_logic.py` | 新增弱替換被成本門檻擋下的 assert；測試 PASS |

## 驗收 Run

| 項目 | 結果 |
| --- | --- |
| run id | `20260629_20260630_130156_prod` |
| manifest | `runs/2026-06-29/20260629_20260630_130156_prod/run_manifest.json` |
| health report | `logs/data_health/data_health_20260630_130938.json` |
| health result | `checks=36 failed=0` |
| official CAGR | `31.52%` |
| benchmark CAGR | `20.50%` |
| replacement switch trades | `1524` |
| replacement switch net PnL | `1,655,482.12` |
| replacement cost gate rejections | `543` |

## 本階段不做

| 延後項目 | 原因 |
| --- | --- |
| 自動尋優 replacement gate 參數 | 目前先用單一 production 設定，避免把正式流程變成實驗平台 |
| 完整實盤成交模型 | 已有 limit/gap/volume/cost gate；更細成交模型需外部成交資料 |
| 新後端服務 | 本階段只修策略流程與前端資料產生，不擴大架構 |
