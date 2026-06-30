# Money Trade 第六階段優化檢查表

本階段落地長期藍圖中的兩個治理項目：公司行動/雙價格序列欄位契約，以及研究實驗註冊表。先用最小可驗收版本，不新增服務、不引入 MLflow 或新資料庫。

| ID | 優化項目 | 狀態 | 負責檔案 | 驗收方式 | 證據 |
| --- | --- | --- | --- | --- | --- |
| P6-1 | 公司行動與 raw/adjusted 價格欄位契約 | PASS | `trading_code_ml/src/corporate_actions.py`, `trading_code_ml/scripts/update_latest_features.py`, `trading_code_ml/scripts/run_cycle_strategy_wfa.py` | `python trading_code_ml\scripts\test_pandas_logic.py`; processed rebuild | processed features 已包含 `raw_*`、`adjusted_*`、`cash_dividend`、`stock_dividend_ratio`、`price_adjustment_factor` 等契約欄位 |
| P6-2 | Health check 驗證價格序列契約 | PASS | `scripts/check_data_health.py` | `python scripts\check_data_health.py --expected-date 2026-06-29 ...` | `logs/data_health/data_health_20260630_133651.json` 顯示 `processed_features.price_series_contract=pass`，`failed=0`、`warning=0` |
| P6-3 | 實驗註冊表 | PASS | `scripts/register_experiment.py`, `research/experiment_registry.csv` | `python scripts\register_experiment.py --summary ... --equity ...` | registry 產生 `rank_portfolio_production_v1`，含 run id、config hash、CAGR、Sharpe、PSR、DSR、replacement TCA |
| P6-4 | PSR/DSR 最小治理指標 | PASS | `trading_code_ml/src/research_metrics.py`, `trading_code_ml/scripts/test_pandas_logic.py` | `python trading_code_ml\scripts\test_pandas_logic.py` | PSR/DSR 以 stdlib `statistics.NormalDist` 計算並有 bounds assert |
| P6-5 | Daily registry 接線 | PASS | `scripts/daily_update.ps1` | PowerShell scriptblock parse | daily manifest 新增 `experiment_registry` step 與 artifact；正式 run 會 upsert `research/experiment_registry.csv` |

## 驗收結果

| 項目 | 結果 |
| --- | --- |
| processed rows | `1,362,169` |
| processed latest date | `2026-06-29` |
| health report | `logs/data_health/data_health_20260630_133651.json` |
| health status | `pass` |
| registry | `research/experiment_registry.csv` |
| PSR | `0.9999999947511495` |
| DSR | `1.0` |

## 本階段不做

| 延後項目 | 原因 |
| --- | --- |
| 實際公司行動調價重算 | Fubon daily 已使用 adjusted 查詢；本階段先建立欄位契約與健康檢查 |
| MLflow/DB experiment tracker | CSV registry 已能驗收升版治理；等多人查詢或 UI 需求出現再升級 |
