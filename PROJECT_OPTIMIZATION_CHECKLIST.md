# Money Trade 第一階段專案優化完成表

驗收日期：2026-06-30  
正式資料日期：2026-06-29  
正式 PASS manifest：`runs/2026-06-29/20260629_20260630_114002_prod/run_manifest.json`  
負案例 manifest：`runs/2099-01-02/20990102_20260630_113637_prod/run_manifest.json`

| ID | 優化項目 | 狀態 | 負責檔案 | 驗收指令 | 證據 |
| --- | --- | --- | --- | --- | --- |
| P0-1 | 移除 hard-coded token | PASS | `config.py`, `.env.example` | `rg -n 'eyJ\|FINMIND_TOKEN\s*=\s*[''\"][^''\"]+\|money-trade-line-bot' config.py .env.example cloud_line\app.py` | 無真實 token；`.env.example` 只有 `FINMIND_TOKEN=` 欄位名 |
| P0-2 | 建立忽略規則 | PASS | `.gitignore` | `git status --short -- .env logs runs results trading_code_ml\results data\market_data.db frontend\node_modules frontend\dist tools` | 指令無輸出；大型產物與 secrets 路徑未列入 status |
| P0-3 | 初始化版本控制 | PASS | `.git/`, `.gitignore` | `git init`; `git status --short -- .env logs runs trading_code_ml\results data\market_data.db` | `.git` 已存在；未自動 commit；ignore 生效 |
| P0-4 | 統一路徑設定 | PASS | `trading_code_ml/config/production.yaml`, `trading_code_ml/src/config.py`, `scripts/daily_update.ps1`, `frontend/scripts/generate_dashboard_data.py`, `trading_code_ml/scripts/update_latest_features.py`, `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | `rg -n 'C:\\Users\\huang\\Desktop\\trading_code\|C:/Users/huang/Desktop/trading_code' scripts trading_code_ml\scripts trading_code_ml\src frontend\scripts` | source 無舊外部路徑硬編碼；相容外部 raw/processed 路徑只集中在 `production.yaml` |
| P0-5 | Cloud Run bucket 環境化 | PASS | `cloud_line/app.py`, `.env.example` | `rg -n 'money-trade-line-bot\|LINE_CARD_BUCKET' cloud_line\app.py .env.example` | hard-coded bucket 已移除；缺 `LINE_CARD_BUCKET` 時 `/notify-image` 回 500 |
| P0-6 | 編碼檢查 | PASS | `.py`, `.jsx`, `.md` | UTF-8 掃描 `.py/.jsx/.md`，排除 `.git`、`logs`、`runs`、`frontend/dist`、`frontend/node_modules`、`trading_code_ml/results` | `UTF-8 scan PASS`；未盲目轉碼亂碼註解 |
| P1-1 | 單一正式策略設定 | PASS | `trading_code_ml/config/production.yaml`, `trading_code_ml/src/config.py`, `trading_code_ml/scripts/run_rank_portfolio_backtest.py`, `trading_code_ml/scripts/generate_daily_signals.py`, `trading_code_ml/scripts/run_portfolio_strategy_wfa.py` | `rg -n 'BEST_RISK\|_apply_best_risk' scripts trading_code_ml\scripts trading_code_ml\src`; summary/settings 對照 production | 無 `BEST_RISK` 覆蓋；`rank_portfolio_summary.json` settings match production；manifest config hash match current `production.yaml` |
| P1-2 | Daily hard gate | PASS | `scripts/daily_update.ps1`, `scripts/check_data_health.py` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -EndDate 2099-01-02 -SkipApiFetch -SkipBacktest -SkipSentiment -SkipBuild -SkipFundamentalSync` | script exit 1；`runs/2099-01-02/20990102_20260630_113637_prod/run_manifest.json` 顯示 `health_gate=FAIL`、SQLite 與 LINE 仍是 `PENDING` |
| P1-3 | Run manifest | PASS | `scripts/daily_update.ps1` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -EndDate 2026-06-29 -SkipApiFetch -SkipSentiment -SkipBuild -SkipLineNotify -SkipFundamentalSync` | `runs/2026-06-29/20260629_20260630_114002_prod/run_manifest.json` 顯示 `status=pass`、`official_rank=PASS`、`forward_sim=PASS`、`frontend_data=PASS`、SQLite imports PASS |
| P1-4 | 法人 overlay 去重 | PASS | `trading_code_ml/src/institutional_overlay.py`, `trading_code_ml/scripts/update_latest_features.py`, `trading_code_ml/scripts/run_rank_portfolio_backtest.py`, `frontend/scripts/generate_dashboard_data.py` | `rg -n '_overlay_recent_official_institutional_flow' scripts trading_code_ml\scripts trading_code_ml\src frontend\scripts` | 無舊 duplicated 私有函式；正式入口共用 `overlay_recent_official_institutional_flow` |
| P1-5 | Bootstrap fallback | PASS | `trading_code_ml/scripts/update_latest_features.py` | 呼叫 `_load_symbols(Path('Z:/missing/all_features.csv'), 5, settings['data']['stock_pool'])` | 輸出 `0050,0052,0056,1101,1102`；缺 processed 檔時可用 `stock_pool` 啟動 |
| P1-6 | Forward capital 命名 | PASS | `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | full daily run with forward sim | 新產物 `trading_code_ml/results/forward_simulation/20260605_1M.csv` 已產生；source 無 `100M`。舊 `20260605_100M.csv` 依本階段「不搬動舊 results」保留 |
| P1-7 | 前端 portfolio API 標示 | PASS | `frontend/README.md` | `rg -n '/api/portfolio\|dev-only\|Vite' frontend\README.md` | README 標明 `/api/portfolio` 是 Vite dev-only；static build 不宣稱支援 POST 儲存 |
| P1-8 | 正式結果指標 | PASS | `OFFICIAL_RESULTS.md`, `trading_code_ml/config/production.yaml` | `Get-Content OFFICIAL_RESULTS.md` | 文件指定唯一 official run、forward run、dashboard data、SQLite DB 來源；未搬動舊大型 results |
| P2-1 | 最小測試 | PASS | `trading_code_ml/scripts/test_pandas_logic.py`, `scripts/check_data_health.py` | `python trading_code_ml\scripts\test_pandas_logic.py`; `python -m py_compile scripts\check_data_health.py scripts\send_line_holdings.py scripts\config_value.py trading_code_ml\scripts\update_latest_features.py trading_code_ml\scripts\run_rank_portfolio_backtest.py trading_code_ml\scripts\generate_daily_signals.py trading_code_ml\scripts\run_portfolio_strategy_wfa.py frontend\scripts\generate_dashboard_data.py trading_code_ml\src\config.py trading_code_ml\src\institutional_overlay.py cloud_line\app.py` | `test_pandas_logic: PASS`; py_compile 通過 |
| DOC-1 | 優化完成表 | PASS | `PROJECT_OPTIMIZATION_CHECKLIST.md` | 檢視本表 | 每一項都有狀態、負責檔案、驗收指令、證據 |

## 最終驗收命令

| 驗收項 | 結果 |
| --- | --- |
| `python trading_code_ml\scripts\test_pandas_logic.py` | PASS |
| Python `py_compile` 指定檔案 | PASS |
| `python scripts\check_data_health.py --expected-date 2026-06-29 ... --skip-sentiment-generated-today` | PASS，`checks=28 failed=0`，report `logs/data_health/data_health_20260630_115044.json` |
| `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -EndDate 2026-06-29 -SkipApiFetch -SkipSentiment -SkipBuild -SkipLineNotify -SkipFundamentalSync` | PASS，manifest `runs/2026-06-29/20260629_20260630_114002_prod/run_manifest.json` |
| `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -EndDate 2099-01-02 -SkipApiFetch -SkipBacktest -SkipSentiment -SkipBuild -SkipFundamentalSync` | FAIL as expected；hard gate 阻擋 SQLite 與 LINE |
| `frontend\npm-local.cmd run build` | PASS |
| source `rg` 驗證 secrets、bucket、`BEST_RISK`、duplicated overlay、錯誤 `100M` | PASS，無輸出 |
