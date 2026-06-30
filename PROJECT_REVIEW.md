# Money Trade 專案說明與優化檢查

更新日期：2026-06-30

## 1. 專案定位

這個專案是一套台股量化選股與投資輔助工作區，主要功能包含：

- 更新台股歷史行情、法人買賣超、營收與市場情緒資料。
- 產生技術指標、資金流、營收動能、盤勢 regime 等特徵。
- 用多因子排序與策略規則做回測、forward simulation、每日候選股與資金配置。
- 將回測與每日訊號轉成 React 儀表板的靜態資料。
- 透過 LINE 通知每日策略持倉、買賣建議、產業資金流與圖片卡片。
- 將特徵與回測結果同步到 SQLite，方便後續查詢或分析。

目前它更像「本機量化研究與每日產出系統」，不是單純前端網站，也不是完整後端服務。正式資料流程主要靠 PowerShell 與 Python 腳本串起來。

## 2. 主要目錄

| 路徑 | 用途 |
| --- | --- |
| `config.py` | 舊版或根目錄通用設定，包含 FinMind token fallback、技術指標參數、UI 色彩與字型路徑。 |
| `data_loader.py` | 台股資料抓取與清洗工具，涵蓋 TWSE、TPEx、FinMind、Yahoo、PTT/news 等來源。 |
| `utils.py` | 日期、數字格式、字型、jieba 字典、安全除法等小工具。 |
| `scripts/` | 每日更新、資料健康檢查、LINE 通知、SQLite 匯入、報表產生等營運腳本。 |
| `trading_code_ml/src/` | 量化核心模組：資料抓取、特徵工程、標籤、盤勢分類、風控、回測、策略規則庫。 |
| `trading_code_ml/scripts/` | 回測、walk-forward、grid search、每日訊號、最新特徵更新等研究/產出入口。 |
| `trading_code_ml/config/settings.yaml` | 主要策略設定，包含股票池、交易成本、風控、模型、策略、WFA 與輸出設定。 |
| `trading_code_ml/results/` | 回測、forward simulation、grid search、data update 等結果。 |
| `frontend/` | React + Vite 儀表板。資料多由 Python 產生到 `frontend/src/data/*.js`。 |
| `cloud_line/` | Flask Cloud Run 服務，負責接 LINE push、圖片通知與 webhook 訂閱。 |
| `data/` | SQLite、真實持倉 JSON、每日策略動作紀錄。 |
| `data_history/` | 本機歷史資料：price、institutional、revenue、margin 等 CSV。 |
| `stock_universe/` | 選股 universe，如 500 檔流動性股票清單。 |
| `logs/`, `log/` | 每日流程、資料健康檢查與程式執行 log。 |
| `results/` | LINE 圖片卡片等根目錄產出。 |
| `REPORT_ENCODING.md` | 本地 HTML 報表編碼政策。 |

## 3. 主要資料來源

### 3.1 Fubon Neo

`trading_code_ml/src/data_fetcher.py` 透過 `fubon_neo` SDK 抓日 K、盤中 quote、snapshot、除權息等資料。

需要 `.env` 內的登入資訊：

- `FUBON_LOGIN_MODE`
- `FUBON_USER_ID`
- `FUBON_PASSWORD` 或 `FUBON_API_KEY`
- `FUBON_CERT_PATH`
- `FUBON_CERT_PASSWORD`

日 K 下載會切成最多 360 天一段，遇到 429 rate limit 會 sleep 61 秒後重試。

### 3.2 TWSE / TPEx 官方資料

`data_loader.py` 會優先使用公開端點取得：

- 全市場當日成交資訊。
- TWSE T86 三大法人買賣超。
- TPEx 法人買賣超。
- TWSE 歷史日成交資料。

這些官方資料也會覆蓋最近 45 天的法人流向，避免只靠舊特徵檔。

### 3.3 FinMind / Yahoo / 網頁來源

`data_loader.py` 另外補：

- FinMind：基本面、融資融券、月營收等。
- Yahoo：部分個股基本資訊。
- PTT Stock、新聞標題：市場情緒或文字雲來源。

### 3.4 前端情緒資料

`frontend/scripts/generate_sentiment_data.py` 抓：

- PTT Stock。
- Google News RSS。
- Alpha Vantage News Sentiment。
- CNN Fear & Greed。
- Google Trends。
- 專案內的法人資金流資料。

最後寫成 `frontend/src/data/sentimentData.js`。

## 4. 每日正式流程

主要入口是：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1
```

`scripts/daily_update.ps1` 預設做這些事：

1. 執行 `trading_code_ml/scripts/update_latest_features.py`
   - 從外部 processed features 讀股票清單。
   - 逐檔補抓最新日 K。
   - 重算特徵與 label。
   - 覆蓋最近法人官方資料。
   - 輸出 `all_features.csv`、data update status 與 summary。

2. 執行官方 rank portfolio 回測
   - 腳本：`trading_code_ml/scripts/run_rank_portfolio_backtest.py`
   - 輸出到 `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance`
   - 參數包含 `--trailing-stop-sell-pct 0.5`

3. 執行 forward simulation
   - 同樣使用 `run_rank_portfolio_backtest.py`
   - 起始日預設為 `2026-06-05`
   - 資金預設 `1000000`
   - 最小交易單位設為 `1`
   - 輸出到 `trading_code_ml/results/forward_simulation`

4. 重生前端資料
   - `frontend/scripts/generate_dashboard_data.py`
   - `frontend/scripts/generate_sentiment_data.py`
   - 產出 `dashboardData.js`、`rotationData.js`、`equityData.js`、`stockSearchData.js`、`sentimentData.js`

5. 建置前端
   - `frontend/npm-local.cmd run build`
   - 產出 `frontend/dist`

6. 跑資料健康檢查
   - `scripts/check_data_health.py --expected-date <date> --warn-only`
   - 檢查 processed features、data update status、rank outputs、frontend data 是否同步。

7. LINE 通知
   - `scripts/send_line_holdings.py --expected-date <date>`
   - 可走本機 LINE token，也可走 `LINE_CLOUD_PUSH_URL` Cloud Run。

8. 同步 SQLite
   - `scripts/db_importer.py --import-features ...`
   - `scripts/db_importer.py --import-backtest ...`
   - 寫入 `data/market_data.db`

9. 同步外部 Fundamental Lens
   - 如果存在 `C:\Users\huang\Desktop\Fundamental Analysis\scripts\sync_watchlist_research.ps1` 才執行。

可用 skip 參數：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -SkipApiFetch
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -SkipBacktest
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -SkipSentiment
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -SkipBuild
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -SkipHealthCheck
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -SkipLineNotify
```

## 5. 量化核心模組

### 5.1 設定載入

檔案：`trading_code_ml/src/config.py`

功能：

- 內建 `DEFAULT_SETTINGS`。
- 從 `trading_code_ml/config/settings.yaml` 讀取 override。
- 用 `deep_merge()` 合併預設值與 YAML。
- 建立 `data/raw`、`data/processed`、`results`。

注意：根目錄也有 `config.py`，兩套設定目前並存，容易混淆。

### 5.2 資料抓取

檔案：`trading_code_ml/src/data_fetcher.py`

功能：

- 登入 Fubon SDK。
- 抓日 K、盤中資料、snapshot、corporate actions。
- 正規化欄位為 `date/open/high/low/close/volume/turnover/change`。
- 支援 `csv` source 或 `fubon_neo` source。
- 可儲存 raw CSV 與 marketdata CSV。

### 5.3 特徵工程

檔案：`trading_code_ml/src/feature_engine.py`

主要特徵：

- SMA、EMA、MACD、RSI、ATR、ADX。
- KD、Bollinger、Williams %R、OBV。
- 1/3/5/10 日報酬、range、gap、volume ratio。
- 52 週高低位置、rolling volatility。
- 法人流向：`foreign_net`、`trust_net`、`total_net`、5 日合計。
- 月營收與 21 日營收動能。
- 相對強弱：可和 benchmark 合併後計算。

注意：法人與營收 CSV 路徑目前硬寫到 `c:/Users/huang/Desktop/money_trade/data_history/...`。

### 5.4 標籤

檔案：`trading_code_ml/src/labeler.py`

邏輯：

- 用未來 `label_forward_days` 內最高價相對當日收盤的報酬當 `future_return`。
- 大於 `label_threshold_up` 標為 `1`。
- 小於 `label_threshold_down` 標為 `-1`。
- 其餘標為 `0`。
- 同時產生 `target_binary` 與 `target_3class`。

### 5.5 盤勢 regime

檔案：`trading_code_ml/src/regime.py`

用每日全市場統計分類：

- `market_breadth_ma20`
- `market_breadth_ma60`
- `market_positive_return_5`
- `market_volatility_20`
- `market_position_52w`
- `market_symbol_count`

分類結果包含：

- `bull`
- `recovery`
- `neutral`
- `bear`
- `high_vol`
- `unknown`

策略可用 `regime_allow_entries` 控制哪些 regime 允許進場。

### 5.6 策略規則庫

檔案：`trading_code_ml/src/strategy_catalog.py`

策略 family：

- trend
- momentum
- breakout
- mean_reversion
- volume_chip
- fundamental_revision
- low_volatility
- hybrid
- pth_turnover_momentum
- pth_turnover_reversal
- bollinger_rsi
- volatility_switch
- cross-family 組合

它會把規則組合成大量 `StrategySpec`，每個策略用多個 rule vote 判斷是否成立。

### 5.7 風控

檔案：`trading_code_ml/src/risk_manager.py`

功能：

- ATR 計算。
- 依 `max_risk_per_trade`、ATR stop distance、`max_position_pct` 計算部位。
- 依最小交易單位整股。
- 初始停損、停利、移動停損。
- 檢查 stop loss、take profit、trailing stop、time exit。

### 5.8 基礎回測器

檔案：`trading_code_ml/src/backtester.py`

功能：

- 逐日更新持倉與現金。
- 用前一日 signal 隔日進場，降低偷看問題。
- 交易成本包含手續費、滑價、賣出證交稅。
- 支援策略出場、drawdown guard、hard drawdown、de-risk cooldown。
- 輸出 equity curve、trade log、績效指標。

## 6. 主要回測與研究腳本

| 腳本 | 用途 |
| --- | --- |
| `trading_code_ml/scripts/update_latest_features.py` | 補抓最新資料並重建 `all_features.csv`。 |
| `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | 目前每日正式 rank portfolio 回測主入口。 |
| `trading_code_ml/scripts/generate_daily_signals.py` | 依 WFA 選出的策略產生每日候選股與資金配置。 |
| `trading_code_ml/scripts/run_portfolio_strategy_wfa.py` | portfolio-level walk-forward 回測。 |
| `trading_code_ml/scripts/run_cycle_strategy_wfa.py` | 依市場 cycle/regime 選策略。 |
| `trading_code_ml/scripts/run_score_momentum_backtest.py` | score momentum 類回測。 |
| `trading_code_ml/scripts/run_grid_score_backtest.py` | 分數與參數 grid search。 |
| `trading_code_ml/scripts/run_exit_params_backtest.py` | 出場參數測試。 |
| `trading_code_ml/scripts/run_weight_backtest.py` | 多因子權重測試。 |
| `trading_code_ml/scripts/grid_search_positions.py` | 最大持倉與單筆部位比例測試。 |
| `trading_code_ml/scripts/grid_search_trailing_sell.py` | trailing stop 賣出比例測試。 |

目前正式流程最依賴 `run_rank_portfolio_backtest.py`。它的預設多因子權重大致是：

- long momentum：0.55
- trend：0.25
- momentum：0.08
- low volatility：0.08
- flow：0.04
- fundamental：0.04

它還會疊加：

- 官方近期法人資料 overlay。
- 月營收特徵延遲處理，避免月初資料偷看。
- market regime 與 market breadth filter。
- 過熱弱勢市場排除。
- risk parity 或 fixed sizing。
- 相關性、產業持倉上限、替換、成交量參與率、market impact slippage。

## 7. 輸出資料

### 7.1 回測輸出

常見檔案：

- `rank_portfolio_summary.json`
- `rank_portfolio_equity.csv`
- `rank_portfolio_trades.csv`
- `rank_portfolio_positions.csv`
- `rank_portfolio_buys.csv`
- `rank_portfolio_signals.csv`
- `benchmark_data/benchmark_0050_*.csv`

正式輸出目錄：

- `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance`
- `trading_code_ml/results/forward_simulation`

### 7.2 前端資料

由 `frontend/scripts/generate_dashboard_data.py` 寫入：

- `frontend/src/data/dashboardData.js`
- `frontend/src/data/rotationData.js`
- `frontend/src/data/equityData.js`
- `frontend/src/data/stockSearchData.js`

由 `frontend/scripts/generate_sentiment_data.py` 寫入：

- `frontend/src/data/sentimentData.js`

### 7.3 SQLite

檔案：

- `data/market_data.db`

主要 table：

- `stock_daily_prices`
- `stock_daily_features`
- `institutional_flow`
- `backtest_runs`
- `trade_log`
- `equity_curve`
- `open_positions`
- `buy_log`
- `strategy_action_log`

## 8. 前端儀表板

路徑：`frontend/`

技術：

- React 19
- Vite 6
- Plotly basic dist
- `react-plotly.js`

常用指令：

```powershell
cd frontend
.\npm-local.cmd install
.\npm-local.cmd run dev
.\npm-local.cmd run build
.\npm-local.cmd run preview
```

預設 dev URL：

```text
http://127.0.0.1:5173
```

主要畫面：

- `App.jsx`：主頁與 lazy loading。
- `InvestmentPlannerPanel.jsx`：投資規劃。
- `StrategyPortfolioPanel.jsx`：策略 forward simulation 持倉與交易歷史。
- `RealPortfolioPanel.jsx`：真實持倉輸入與風控試算。
- `StockSearchPanel.jsx`：股票查詢、分數與資金流 filter。
- `FundRotation.jsx`：產業資金輪動。
- `EquityCurve.jsx`：策略與 benchmark 權益曲線。
- `SentimentPanel.jsx`：市場情緒。

前端的 `/api/portfolio` 只存在於 Vite dev server plugin：

- GET 讀 `data/real_portfolio.json`
- POST 寫 `data/real_portfolio.json`

如果只部署 `frontend/dist`，這個 API 不會存在，需要另外接後端或改成靜態/雲端儲存方案。

## 9. LINE 與 Cloud Run

### 9.1 本機 LINE 通知

入口：

```powershell
python scripts\send_line_holdings.py --dry-run
python scripts\send_line_holdings.py
```

資料來源：

- `frontend/src/data/dashboardData.js`
- `frontend/src/data/rotationData.js`
- `frontend/src/data/stockSearchData.js`
- `trading_code_ml/results/forward_simulation`
- `data/real_portfolio.json`

功能：

- 產生文字通知。
- 產生每日圖片卡片：`results/line_cards/daily_stock_card.png`
- 記錄策略買賣動作到 `data/strategy_actions/<date>.json` 與 SQLite。

需要 `.env`：

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_TARGET_ID`
- 或 `LINE_CLOUD_PUSH_URL` + `LINE_CLOUD_PUSH_KEY`

### 9.2 Cloud Run 服務

路徑：`cloud_line/`

入口：`cloud_line/app.py`

端點：

- `GET /`：health check。
- `POST /notify`：用 `X-Push-Key` 驗證後推文字。
- `POST /notify-image`：上傳圖片到 GCS，再推 LINE image message。
- `GET /cards/<card_id>.png`：讀取本機 `/tmp/line-cards` 圖片。
- `POST /callback`：LINE webhook，驗簽後把 userId 加入 Secret Manager。

部署腳本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy_line_cloud_run.ps1
```

## 10. 健康檢查

入口：

```powershell
python scripts\check_data_health.py --expected-date 2026-06-30
```

檢查項目：

- processed features 是否存在、最新日期是否符合 expected date。
- 最新日是否有足夠 rows。
- 法人欄位是否不是全空。
- data update status 是否所有股票都更新到 expected date。
- rank summary、signals、equity 是否到 expected date。
- frontend data 是否同步到 expected date。
- sentiment 是否今天產生。

輸出：

- `logs/data_health/data_health_<timestamp>.json`
- `logs/data_health/data_health_<timestamp>.csv`

每日流程目前使用 `--warn-only`，所以健康檢查失敗不會中斷後續流程。

## 11. 已知風險與優化清單

### P0：先處理，會影響安全或穩定性

1. 移除程式碼內的 token 與敏感資訊
   - 根目錄 `config.py` 內有 FinMind token fallback。
   - `.env` 存在於專案根目錄，若之後放進 git，必須確保忽略。
   - 建議：所有 token 只讀環境變數或 Secret Manager；新增 `.env.example` 放欄位名，不放真值。

2. 統一路徑設定
   - 多處硬寫絕對路徑，例如：
     - `C:\Users\huang\Desktop\trading_code\data\processed\all_features.csv`
     - `C:\Users\huang\Desktop\trading_code\data\raw`
     - `c:/Users/huang/Desktop/money_trade/data_history/...`
     - `C:\Windows\Fonts\...`
     - Cloud Run GCS bucket 名稱。
   - 建議：先集中到 `settings.yaml` 或 `.env`，程式只從設定讀。

3. 修正中文編碼與亂碼來源
   - README、註解、前端文案、LINE 文案在目前讀取結果中大量呈現亂碼。
   - `REPORT_ENCODING.md` 已經定義 HTML 報表政策，但一般 `.py/.jsx/.md` 仍需處理。
   - 建議：先確認原始檔實際編碼，再做一次性轉換；不要手動逐段猜字。

4. 建立最小版本控制與忽略規則
   - 目前此資料夾不是 git repository。
   - 專案包含 `node_modules`、`dist`、大量 results、logs、db、圖片與工具 binary。
   - 建議：建立 git 後只追蹤原始碼、設定模板、文件；忽略資料、產物、log、secret。

### P1：高報酬的維護性改善

1. 單一設定來源
   - 現在有根目錄 `config.py`、`trading_code_ml/src/config.py`、`settings.yaml`、多個腳本內常數、`BEST_RISK`。
   - 風控參數在不同地方重複，容易「回測 A 用一套、每日訊號 B 用另一套」。
   - 建議：先把每日正式流程用到的設定集中，其他研究腳本再逐步跟上。

2. 合併重複的法人資料 overlay
   - 類似邏輯出現在：
     - `update_latest_features.py`
     - `run_rank_portfolio_backtest.py`
     - `frontend/scripts/generate_dashboard_data.py`
   - 建議：抽成一個小函式放在共用模組，避免未來修一處漏兩處。

3. 消除 bootstrap 依賴
   - `update_latest_features.py` 會從既有 processed features 讀 symbols。
   - 如果 processed file 不存在，無法從 `settings.yaml` 股票池直接重建。
   - 建議：讀不到 processed 時 fallback 到 `settings["data"]["stock_pool"]`。

4. 讓前端真實持倉 API 有正式方案
   - `/api/portfolio` 只在 dev server 有效。
   - build 後的靜態網站不具備 POST 儲存能力。
   - 建議：若要正式使用，接 SQLite/Flask/FastAPI 或 Cloud Run；若只本機用，就在文件標明「dev-only」。

5. 減少巨大結果目錄干擾
   - `trading_code_ml/results` 有大量實驗結果，對研究有價值，但會讓搜尋、備份與版本控制變慢。
   - 建議：保留 official、forward_simulation、data_update；舊 grid search 歸檔到外部資料夾。

### P2：策略可靠度與研究品質

1. 補最小測試
   - 現有 `test_pandas_logic.py` 很薄。
   - 建議先補 3 類小測試：
     - `Labeler.add_labels()` 是否沒有 off-by-one。
     - `RiskManager.position_size()` 與 `should_exit()`。
     - `check_data_health.py` 解析 JS export 與日期檢查。

2. 加強回測防偷看檢查
   - 專案已有 `backtest_pitfalls_guide.md`，方向正確。
   - 建議把其中幾條變成可跑檢查，例如：
     - 進場只使用前一交易日 signal。
     - 月營收月初不可用。
     - rank 只在同日截面內算。

3. 統一資金單位命名
   - `run_rank_portfolio_backtest.py` 內 forward simulation 的自訂輸出檔名，`capital == 1000000` 時會產生 `100M` 字樣，與 1,000,000 資金語意不一致。
   - 建議修成 `1M` 或直接用完整金額。

4. 明確區分研究結果與正式結果
   - 目前 results 內有 baseline、oos、defense、grid、test_replace 等多種版本。
   - 建議新增 `OFFICIAL_RESULTS.md` 或設定 `official_run_name`，標明目前儀表板採用哪個結果。

5. 將資料健康檢查分級
   - 每日流程使用 `--warn-only`，不會阻止 LINE 通知。
   - 建議把「資料日期不符、法人資料全空、前端資料未更新」列為 hard fail；非核心情緒資料可 warn。

### P3：效能與部署

1. 改善全量 CSV 重算成本
   - 每日更新目前會把多檔 raw 轉特徵後 concat 成完整 processed CSV。
   - 500 檔、2013 至今資料量會逐年變大。
   - 建議：短期先保留 CSV；中期可改 Parquet 或 SQLite 增量寫入。

2. 資料庫加查詢索引與查詢 API
   - SQLite 已有 primary key。
   - 如果前端或分析要常查日期區間、symbol、run_name，可以補 index 或建立讀取 API。

3. Cloud Run 參數環境化
   - `cloud_line/app.py` 內 GCS bucket 名稱硬寫。
   - 建議改用 `LINE_CARD_BUCKET`。

4. 前端 bundle 與資料大小
   - 現在資料以 JS module 方式打包，資料大時 bundle 會變肥。
   - 建議資料變大後改成 JSON 檔 lazy fetch，不急著現在改。

## 12. 建議優化順序

最短路徑：

1. 先做安全與可攜性：移除 hard-coded token、集中絕對路徑、補 `.env.example`。
2. 處理編碼：確認並修復 README、UI/LINE 文案、註解亂碼。
3. 統一正式流程設定：把 `BEST_RISK`、daily_update 參數、official result dir 寫進設定。
4. 抽出重複 overlay：法人資料 overlay 先合併成共用函式。
5. 補 3 個最小測試：label、risk、health check。
6. 清理產物目錄與建立 git ignore。

暫時可以不用做：

- 不急著換完整後端框架。
- 不急著把所有 CSV 改資料庫。
- 不急著重寫策略引擎。
- 不急著大改前端架構。

## 13. 常用指令

安裝 Python 套件：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r trading_code_ml\requirements.txt
python -m pip install -r cloud_line\requirements.txt
```

每日更新：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1
```

只重建特徵：

```powershell
python trading_code_ml\scripts\update_latest_features.py --end-date 2026-06-30
```

只跑官方 rank portfolio：

```powershell
python trading_code_ml\scripts\run_rank_portfolio_backtest.py --output-dir trading_code_ml\results\rank_portfolio_optimized_risk_long_20pct_norebalance --trailing-stop-sell-pct 0.5
```

只重生前端資料：

```powershell
python frontend\scripts\generate_dashboard_data.py
python frontend\scripts\generate_sentiment_data.py
```

啟動前端：

```powershell
cd frontend
.\npm-local.cmd run dev
```

前端 build：

```powershell
cd frontend
.\npm-local.cmd run build
```

資料健康檢查：

```powershell
python scripts\check_data_health.py --expected-date 2026-06-30
```

LINE dry run：

```powershell
python scripts\send_line_holdings.py --dry-run
```

SQLite 初始化或匯入：

```powershell
python scripts\db_importer.py --init-db
python scripts\db_importer.py --import-features C:\Users\huang\Desktop\trading_code\data\processed\all_features.csv
```

## 14. 目前核心策略最終結果

本節記錄目前專案採用的核心策略最終結果。資料來源是：

- `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_summary.json`
- `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_equity.csv`
- `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_positions.csv`
- `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_trades.csv`
- `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_buys.csv`
- `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_signals.csv`

### 14.1 核心策略摘要

| 項目 | 目前結果 |
| --- | --- |
| 策略名稱/目錄 | `rank_portfolio_optimized_risk_long_20pct_norebalance` |
| 回測期間 | 2013-05-08 ~ 2026-06-29 |
| 訊號最新日期 | 2026-06-29 |
| 初始資金 | 1,000,000 |
| 期末權益 | 38,399,070 |
| 現金 | 34,831,220 |
| 目前開放部位數 | 3 |
| 平均資金使用率 | 66.80% |
| 歷史買進紀錄 | 1,830 筆 |
| 歷史完成交易 | 2,032 筆 |
| 候選買進訊號數 | 22,268 |

### 14.2 績效與 0050 比較

| 指標 | 核心策略 | 0050 Benchmark |
| --- | ---: | ---: |
| 總報酬率 | 3,739.91% | 972.38% |
| CAGR | 33.15% | 20.50% |
| Sharpe | 1.288 | 1.096 |
| 最大回撤 | 33.12% | 33.96% |
| 勝率 | 45.13% | - |
| 獲利因子 | 1.710 | - |
| 交易次數 | 2,032 | - |

### 14.3 目前採用參數

| 設定 | 數值 |
| --- | --- |
| 部位 sizing | `risk_parity` |
| 最大持股數 | 8 |
| 單股部位上限 | 20.00% |
| 單筆最大風險 | 2.00% |
| 每日候選 Top N | 12 |
| 最低策略分數 | 0.62 |
| 允許進場 regime | bull, neutral, recovery |
| MA20 市場廣度下限 | 42.00% |
| 5 日正報酬占比下限 | 22.00% |
| 20 日市場波動上限 | 5.50% |
| 初始停損 | 5.0 ATR |
| 固定停利 | 100.00% |
| 移動停損啟動 | 30.00% |
| 移動停損距離 | 3.5 ATR |
| 移動停損賣出比例 | 50.00% |
| 最大持有天數 | 180 |
| 單日成交量參與上限 | 1.00% |
| 市場衝擊滑價 | 0.10 |
| 最小交易單位 | 1000 |
| 因子權重 | long_momentum 0.55, trend 0.25, momentum 0.08, low_vol 0.08, flow 0.04, fundamental 0.04 |

### 14.4 目前開放部位

截至 2026-06-29，核心策略仍持有 3 檔：

| 股票 | 進場日 | 進場價 | 現價 | 股數 | 市值 | 未實現損益 | 報酬率 | 停損 | 移動停損 | 權重 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2426 鼎元 | 2026-05-08 | 70.12 | 77.20 | 28,000 | 2,161,600 | 198,240 | 10.10% | 44.40 | 73.88 | 5.63% |
| 6426 統新 | 2026-05-11 | 262.00 | 190.00 | 6,000 | 1,140,000 | -432,000 | -27.48% | 154.42 | 154.42 | 2.97% |
| 6658 聯策 | 2026-05-11 | 166.00 | 213.00 | 1,250 | 266,250 | 58,750 | 28.31% | 124.33 | 171.40 | 0.69% |

### 14.5 出場原因統計

| 出場原因 | 筆數 | 占比 | 淨損益 | 勝率 |
| --- | ---: | ---: | ---: | ---: |
| replacement_switch | 1,692 | 83.3% | 8,307,253 | 39.5% |
| stop_loss | 89 | 4.4% | -14,553,302 | 0.0% |
| take_profit | 46 | 2.3% | 30,561,229 | 100.0% |
| trailing_stop | 205 | 10.1% | 16,494,486 | 99.0% |

重點判讀：

- 大部分交易是 `replacement_switch`，代表策略主要靠候選排名替換持股。
- 真正貢獻最大的是 `take_profit` 與 `trailing_stop`，兩者合計淨損益約 47,055,715。
- `stop_loss` 筆數不多，但單筆殺傷力大，這是後續風控優化的主戰場。

### 14.6 最近 10 筆已完成交易

| 股票 | 進場日 | 出場日 | 股數 | 進場 | 出場 | 淨損益 | 原因 | 勝負 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 6830 汎銓 | 2026-04-10 | 2026-05-11 | 750 | 659.00 | 762.00 | 74,136 | replacement_switch | True |
| 3167 大量 | 2026-04-10 | 2026-05-11 | 1,500 | 580.00 | 656.00 | 108,590 | replacement_switch | True |
| 6141 柏承 | 2026-04-21 | 2026-05-11 | 55,000 | 36.35 | 33.10 | -195,783 | replacement_switch | False |
| 6861 睿生光電 | 2026-04-23 | 2026-05-15 | 6,000 | 235.50 | 471.00 | 1,393,391 | take_profit | True |
| 6658 聯策 | 2026-05-11 | 2026-05-20 | 2,500 | 166.00 | 177.97 | 27,472 | trailing_stop | True |
| 3026 禾伸堂 | 2026-05-08 | 2026-05-28 | 6,000 | 313.50 | 627.00 | 1,859,691 | take_profit | True |
| 6658 聯策 | 2026-05-11 | 2026-06-05 | 1,250 | 166.00 | 198.02 | 38,670 | trailing_stop | True |
| 1711 永光 | 2026-04-23 | 2026-06-08 | 31,000 | 63.70 | 44.58 | -600,581 | stop_loss | False |
| 4764 雙鍵 | 2026-05-08 | 2026-06-11 | 5,000 | 350.50 | 243.16 | -543,631 | stop_loss | False |
| 8271 宇瞻 | 2026-05-11 | 2026-06-11 | 7,000 | 264.00 | 192.19 | -510,189 | stop_loss | False |

### 14.7 目前結論

目前正式採用版本選擇的是較保守、可交易性較高的 `1000` 股單位版本，而不是歷史回測裡最漂亮的 `unit=1` 版本。這會犧牲 CAGR，但比較接近實際下單限制，也避免小股數版本把績效吹得太滿。

## 15. 過去參數與情境回測彙整

本節只彙整已存在於 `trading_code_ml/results` 的結果，不重新跑回測。重複的 `summary.json` 與 timestamp 副本不重複列。

### 15.1 持股數與單股上限測試

這批多數使用 `min_trade_unit=1`，所以更像策略能力上限測試，不等同真實整股交易。

| 測試 | 期間 | CAGR | 總報酬 | MDD | Sharpe | 勝率 | PF | 交易 | 主要參數 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `grid_pos_4_pct_0.25` | 2013-05-08~2026-06-23 | 42.90% | 9,294.79% | 18.03% | 2.14 | 46.09% | 2.20 | 1,152 | pos=4, max=25%, unit=1 |
| `grid_pos_5_pct_0.2` | 2013-05-08~2026-06-23 | 55.67% | 27,823.03% | 22.78% | 2.30 | 47.00% | 2.25 | 1,419 | pos=5, max=20%, unit=1 |
| `grid_pos_5_pct_0.3` | 2013-05-08~2026-06-23 | 56.09% | 28,812.29% | 22.78% | 2.31 | 46.97% | 2.22 | 1,418 | pos=5, max=30%, unit=1 |
| `grid_pos_8_pct_0.15` | 2013-05-08~2026-06-23 | 91.61% | 392,603.47% | 30.39% | 2.49 | 46.81% | 2.14 | 2,213 | pos=8, max=15%, unit=1 |
| `grid_pos_8_pct_0.2` | 2013-05-08~2026-06-23 | 92.55% | 417,925.12% | 30.39% | 2.51 | 46.78% | 2.14 | 2,204 | pos=8, max=20%, unit=1 |
| `grid_pos_10_pct_0.1` | 2013-05-08~2026-06-23 | 99.87% | 672,062.80% | 31.95% | 2.43 | 46.15% | 2.06 | 2,782 | pos=10, max=10%, unit=1 |
| `grid_pos_10_pct_0.15` | 2013-05-08~2026-06-23 | 104.71% | 911,007.94% | 32.13% | 2.48 | 46.21% | 2.06 | 2,759 | pos=10, max=15%, unit=1 |
| `grid_pos_15_pct_0.08` | 2013-05-08~2026-06-23 | 92.60% | 419,257.77% | 34.74% | 2.26 | 45.67% | 2.17 | 3,530 | pos=15, max=8%, unit=1 |

判讀：`pos=10/max=15%` 的 CAGR 最高，但 `pos=8/max=20%` 已經接近，且交易數較少。正式版本改用整股後，結果回到更保守的 33.15% CAGR。

### 15.2 移動停損賣出比例測試

| 測試 | 期間 | CAGR | 總報酬 | MDD | Sharpe | 勝率 | PF | 交易 | 主要參數 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `grid_trailing_50pct` | 2013-05-08~2026-06-23 | 96.33% | 535,228.81% | 30.01% | 2.59 | 50.11% | 2.22 | 2,285 | trailing sell=50%, unit=1 |
| `grid_trailing_60pct` | 2013-05-08~2026-06-23 | 95.07% | 492,975.96% | 29.96% | 2.58 | 50.11% | 2.20 | 2,285 | trailing sell=60%, unit=1 |
| `grid_trailing_70pct` | 2013-05-08~2026-06-23 | 93.89% | 456,530.50% | 29.91% | 2.58 | 50.11% | 2.19 | 2,285 | trailing sell=70%, unit=1 |
| `grid_trailing_80pct` | 2013-05-08~2026-06-23 | 92.72% | 422,633.59% | 29.86% | 2.57 | 50.11% | 2.17 | 2,285 | trailing sell=80%, unit=1 |
| `grid_trailing_90pct` | 2013-05-08~2026-06-23 | 91.59% | 392,027.74% | 29.81% | 2.57 | 50.11% | 2.15 | 2,285 | trailing sell=90%, unit=1 |
| `grid_trailing_100pct` | 2013-05-08~2026-06-23 | 92.55% | 417,925.12% | 30.39% | 2.51 | 46.78% | 2.14 | 2,204 | trailing sell=100%, unit=1 |

判讀：50% 部分出場是這批測試裡最好的折衷，所以正式版本採用 `trailing_stop_sell_pct=0.5`。

### 15.3 OOS、no-peek、retail 與風控版本

| 測試 | 期間 | CAGR | 總報酬 | MDD | Sharpe | 勝率 | PF | 交易 | 備註 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `rank_portfolio_oos_2024_2026_retail` | 2024-01-02~2026-06-26 | 76.29% | 284.82% | 23.14% | 2.42 | 48.35% | 2.17 | 395 | OOS retail 情境 |
| `rank_portfolio_oos_2024_2026_trigger_exit` | 2024-01-02~2026-06-26 | 74.74% | 276.86% | 22.01% | 2.39 | 48.73% | 2.15 | 394 | OOS trigger exit |
| `rank_portfolio_oos_2024_2026_nopeek_regime` | 2024-01-02~2026-06-26 | 68.42% | 245.27% | 21.96% | 2.30 | 52.40% | 2.43 | 334 | OOS no-peek regime |
| `rank_portfolio_oos_2024_2026_score_sizing_30pct` | 2024-01-02~2026-06-26 | 56.02% | 187.87% | 19.86% | 2.04 | 49.82% | 2.26 | 279 | 分數調整部位 |
| `rank_portfolio_oos_2024_2026_final_risk_control_v2` | 2024-01-02~2026-06-26 | 51.19% | 167.15% | 19.71% | 1.88 | 47.02% | 2.07 | 285 | OOS 風控 v2 |
| `rank_portfolio_oos_2024_2026_final_risk_control` | 2024-01-02~2026-06-26 | 43.21% | 134.82% | 19.33% | 1.90 | 34.15% | 2.07 | 328 | OOS 風控 |
| `rank_portfolio_full_nopeek_regime` | 2013-05-08~2026-06-26 | 46.01% | 12,313.08% | 25.57% | 2.16 | 46.55% | 2.62 | 2,118 | 全期間 no-peek regime |
| `rank_portfolio_full_final_risk_control` | 2013-05-08~2026-06-26 | 42.45% | 8,967.47% | 19.42% | 1.98 | 37.07% | 2.20 | 2,441 | 全期間強風控 |
| `rank_portfolio_retail_realistic` | 2013-05-08~2026-06-26 | 47.12% | 13,576.98% | 25.33% | 2.21 | 46.79% | 2.57 | 2,229 | retail realistic |
| `rank_portfolio_score_sizing_30pct` | 2013-05-08~2026-06-26 | 47.23% | 13,703.08% | 21.33% | 2.17 | 50.23% | 2.78 | 2,222 | 分數調整部位 |

判讀：OOS 的 retail / trigger exit 表現最好；最終正式版沒有直接選最高 OOS CAGR，而是採用整股、50% trailing sell、較容易每日執行的版本。

### 15.4 Defense / 風控參數版本

| 測試 | 期間 | CAGR | 總報酬 | MDD | Sharpe | 勝率 | PF | 交易 | 備註 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `rank_portfolio_defense_045_020_30` | 2013-05-08~2026-06-26 | 83.14% | 222,483.26% | 31.37% | 2.38 | 46.08% | 1.98 | 2,281 | defense 測試 |
| `rank_portfolio_defense_045_010_25` | 2013-05-08~2026-06-26 | 69.00% | 79,838.27% | 32.48% | 2.10 | 44.92% | 1.98 | 2,442 | defense 測試 |
| `rank_portfolio_defense_plancheck` | 2013-05-08~2026-06-26 | 50.42% | 18,033.75% | 31.64% | 1.70 | 48.07% | 1.74 | 3,368 | plan check |
| `rank_portfolio_volume_5pct` | 2013-05-08~2026-06-26 | 82.36% | 210,598.10% | 29.38% | 2.45 | 46.71% | 2.23 | 2,218 | max entry volume 5% 類測試 |

判讀：防守參數可以拉高全期間回測，但仍多為 `unit=1` 類型，不能直接當正式結果。

### 15.5 Timing ablation 與替換機制

| 測試 | 期間 | CAGR | 總報酬 | MDD | Sharpe | 勝率 | PF | 交易 | 備註 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `timing_ablation_baseline` | 2013-05-08~2026-06-29 | 32.31% | 3,441.30% | 33.60% | 1.26 | 39.42% | 1.69 | 1,910 | baseline |
| `timing_ablation_relaxed` | 2013-05-08~2026-06-29 | 21.87% | 1,143.10% | 42.47% | 0.89 | 36.38% | 1.39 | 2,801 | relaxed 較差 |
| `timing_ablation_oos_baseline` | 2024-01-02~2026-06-26 | 36.27% | 108.69% | 20.77% | 1.45 | 40.76% | 1.75 | 238 | OOS baseline |
| `timing_ablation_oos_relaxed` | 2024-01-02~2026-06-26 | 33.32% | 98.10% | 31.30% | 1.26 | 37.13% | 1.47 | 342 | OOS relaxed |
| `test_replace` | 2013-05-08~2026-06-23 | 92.55% | 417,925.12% | 30.39% | 2.51 | 46.78% | 2.14 | 2,204 | 啟用 replacement |
| `test_no_replace` | 2013-05-08~2026-06-23 | 24.31% | 1,494.64% | 30.58% | 1.18 | 57.34% | 2.18 | 368 | 不替換 |

判讀：替換機制是績效差異最大的來源之一；不用 replacement 時 CAGR 明顯下降。

### 15.6 其他期間與 forward simulation

| 測試 | 期間 | CAGR | 總報酬 | MDD | Sharpe | 勝率 | PF | 交易 | 備註 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `forward_simulation` | 2026-06-05~2026-06-29 | 124.16% | 5.26% | 6.39% | 2.39 | 54.55% | 2.58 | 11 | 短期 annualized，僅供追蹤 |
| `rank_portfolio_2026_test` | 2026-01-02~2026-06-24 | 202.05% | 63.44% | 10.95% | 3.24 | 54.90% | 2.32 | 102 | 2026 短期測試 |
| `rank_portfolio_2026_test` | 2026-06-08~2026-06-24 | 568.45% | 9.47% | 3.41% | 6.54 | 33.33% | 0.78 | 9 | 極短期 annualized 不可過度解讀 |
| `rank_portfolio_2022_nopeek_regime` | 2022-01-03~2022-12-30 | 2.45% | 2.39% | 16.11% | 0.22 | 38.57% | 1.13 | 140 | 2022 單年壓力期 |
| `score_momentum_backtest` | 2013-05-08~2026-06-23 | 14.20% | 441.69% | 30.53% | 0.87 | 56.93% | 2.02 | 267 | score momentum 版本 |
| `rank_portfolio_baseline_fixed_patch` | 2013-05-08~2026-06-05 | 28.76% | 2,368.76% | 45.85% | 1.01 | 56.52% | 2.25 | 368 | fixed sizing baseline |
| `rank_portfolio_daily_buys_2013_2025` | 2013-05-08~2025-12-31 | 31.20% | 2,712.06% | 33.12% | 1.23 | 44.70% | 1.53 | 1,973 | 截至 2025 的每日買進版本 |

### 15.7 CSV 參數測試摘要

| 檔案 | 最佳/代表結果 | 判讀 |
| --- | --- | --- |
| `exit_params_results_20260624_122445.csv` | 現有基準：CAGR 24.31%、勝率 57.34%、MDD 30.58%、PF 2.18、交易 368。次佳是「基準 + 分數下跌 15 分出場」：CAGR 22.78%。 | 寬停損、大停利、30% 啟動 trailing 的基準仍最好；分數下跌出場沒有改善。 |
| `exit_params_results_20260624_114158.csv` | 現有基準與多個分數下跌出場情境同為 CAGR 24.31%；嚴格移動停損約 20.97%。 | 這批結果支持保留原基準出場。 |
| `grid_search_results_20260624_104444.csv` | 85 分 / 日增 5 分：CAGR 0.12%、MDD 63.41%、PF 1.06。 | 單純分數門檻 grid 幾乎沒有實用價值。 |
| `grid_search_results_20260624_101453.csv` | 最佳仍為負 CAGR：75 分 / 日增 10 分，CAGR -2.08%。 | 早期分數門檻版本應視為淘汰。 |
| `weight_test_results_20260624_110148.csv` | 原版預設「動能為主」最佳：CAGR 23.51%、勝率 58.51%、MDD 54.07%、PF 1.23。均衡配置 14.63%，基本與籌碼為主 11.22%。 | 長天期動能權重是這組策略的主引擎；提高籌碼/基本面權重反而降低績效。 |

### 15.8 回測彙整結論

- 最漂亮的全期間數字多來自 `min_trade_unit=1`，可視為策略研究上限，不宜直接當實盤預期。
- `replacement_switch` 是核心 alpha 的重要來源，移除後 CAGR 明顯下降。
- `trailing_stop_sell_pct=50%` 在 trailing grid 中表現最好，因此被放進目前正式版本。
- OOS 2024-2026 的 retail / trigger exit 版本表現強，但仍需注意樣本期短。
- 目前正式版本的定位是「可每日執行、整股交易、較保守」；不是歷史最佳 CAGR 版本。

## 16. 一句話總結

這個專案已經具備完整的「資料更新 -> 特徵 -> 回測/訊號 -> 前端 -> LINE -> SQLite」鏈路；下一步最值得優化的不是重寫策略，而是先把 secrets、路徑、編碼、正式設定與少量測試整理乾淨，讓每天產出的結果更穩、更好追。
