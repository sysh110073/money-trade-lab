# Money Trade 第二階段專案優化完成表

驗收日期：2026-06-30  
本階段範圍：流程治理 v2。先補正式 run 可追溯性、task 狀態、前端資料同源檢查、SQLite metadata、LINE 冪等。暫不導入 Parquet、Docker、TCA 或 DAG 平台。

| ID | 優化項目 | 狀態 | 負責檔案 | 驗收指令 | 證據 |
| --- | --- | --- | --- | --- | --- |
| P2-1 | Manifest 補齊正式 run metadata | PASS | `scripts/daily_update.ps1` | `Get-Content runs\2026-06-29\20260629_20260630_122152_prod\run_manifest.json` | manifest 含 `run_type`、`as_of_date`、`execution_date`、`git_commit`、`universe_version`、`feature_data_hash`、`price_source`、`institutional_source`、`strategy_version` |
| P2-2 | 每次 run 產生 task_status | PASS | `scripts/daily_update.ps1` | `Get-Content runs\2026-06-29\20260629_20260630_122152_prod\task_status.json` | `task_status.json` 記錄每個實際 task 的 `status`、`attempt`、`started_at`、`finished_at`、`exit_code`、stdout/stderr |
| P2-3 | 前端資料保存 runContext | PASS | `frontend/scripts/generate_dashboard_data.py` | 讀取 `frontend/src/data/dashboardData.js`、`rotationData.js`、`equityData.js`、`stockSearchData.js` | 四份資料皆含同一組 `runId=20260629_20260630_122152_prod` 與 production `configHash` |
| P2-4 | Health gate 驗證前端 runContext | PASS | `scripts/check_data_health.py`, `scripts/daily_update.ps1` | daily run 內建 health check | `logs/data_health/data_health_20260630_122402.json` 顯示 `checks=36 failed=0`，新增 8 個 run id/config hash 檢查 |
| P2-5 | SQLite 保存 run_uid/config_hash | PASS | `scripts/db_importer.py`, `scripts/daily_update.ps1` | `select run_name, run_uid, config_hash from backtest_runs where run_uid='20260629_20260630_122152_prod'` | official 與 forward run 都寫入同一 run uid 與 config hash |
| P2-6 | LINE 通知冪等 marker | PASS | `scripts/send_line_holdings.py`, `scripts/daily_update.ps1`, `trading_code_ml/scripts/test_pandas_logic.py` | `python trading_code_ml\scripts\test_pandas_logic.py`; daily line step 會傳 `--run-id` 與 `--notification-marker` | marker helper 自檢通過；成功發送後會寫 `runs/<date>/<run_id>/line_notification.json`，同 run 重跑會略過 |
| P2-7 | 最小驗證與 build | PASS | `trading_code_ml/scripts/test_pandas_logic.py`, frontend | `python -m py_compile ...`; `python trading_code_ml\scripts\test_pandas_logic.py`; `frontend\npm-local.cmd run build` | Python compile PASS；PowerShell parse PASS；self-check PASS；build PASS |

## 驗收命令

| 驗收項 | 結果 |
| --- | --- |
| `python -m py_compile scripts\check_data_health.py scripts\send_line_holdings.py scripts\db_importer.py trading_code_ml\scripts\test_pandas_logic.py frontend\scripts\generate_dashboard_data.py` | PASS |
| PowerShell parser check `scripts\daily_update.ps1` | PASS |
| `python trading_code_ml\scripts\test_pandas_logic.py` | PASS |
| `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -EndDate 2026-06-29 -SkipApiFetch -SkipBacktest -SkipSentiment -SkipBuild -SkipLineNotify -SkipFundamentalSync` | PASS，manifest `runs/2026-06-29/20260629_20260630_122152_prod/run_manifest.json` |
| `frontend\npm-local.cmd run build` | PASS |

## 延後項目

| 項目 | 延後原因 |
| --- | --- |
| Parquet / 增量特徵層 | 會牽動所有資料讀寫入口，本階段先把 run lineage 補齊 |
| Docker 化 | 目前本機流程已可重跑，等流程 metadata 穩定後再容器化 |
| 日頻 TCA / 除權息模型 | 需要策略與資料模型一起設計，不能用小 patch 假裝完成 |
| DAG 平台 | `task_status.json` 已提供最低可觀測性，Prefect/Airflow 等到多機或 UI 需求出現再評估 |
