# Money Trade 第三階段專案優化完成表

驗收日期：2026-06-30  
本階段範圍：策略與交易真實性。先做最小可驗收版本，不導入新回測框架、不重寫前端、不新增大型依賴。

| ID | 優化項目 | 狀態 | 負責檔案 | 驗收指令 | 證據 |
| --- | --- | --- | --- | --- | --- |
| P3-1 | 防偷看測試補強 | PASS | `trading_code_ml/scripts/test_pandas_logic.py`, `trading_code_ml/src/feature_engine.py`, `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | `python trading_code_ml\scripts\test_pandas_logic.py` | assert 覆蓋 label 不偷看當日高點、target 欄位不進 feature list、rank 只在同日截面、訊號隔日才成交 |
| P3-2 | 真實交易限制 | PASS | `trading_code_ml/scripts/run_portfolio_strategy_wfa.py`, `trading_code_ml/scripts/run_rank_portfolio_backtest.py` | daily official run `20260629_20260630_124305_prod` | summary `execution_stats`：`blocked_limit_up_buys=46`、`blocked_limit_down_exits=43`、`gap_stop_exits=643`、`skipped_low_volume_buys=26`、`volume_capped_entries=66` |
| P3-3 | TCA 成本拆解 | PASS | `trading_code_ml/scripts/run_portfolio_strategy_wfa.py`, `trading_code_ml/scripts/run_rank_portfolio_backtest.py`, `scripts/db_importer.py` | 讀 `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_summary.json` | summary `tca.total_cost=8,157,717.05`；`replacement_switch_gross_pnl=3,524,190.75`、`replacement_switch_net_pnl=-1,138,554.68`；SQLite `trade_log` 有 `cost`、`participation_rate` |
| P3-4 | 前端/LINE/Python 共用 sizing | PASS | `trading_code_ml/src/risk_manager.py`, `frontend/scripts/generate_dashboard_data.py`, `scripts/send_line_holdings.py`, `trading_code_ml/scripts/test_pandas_logic.py` | `python trading_code_ml\scripts\test_pandas_logic.py`; `frontend\npm-local.cmd run build` | 共用 `calculate_position_size()`；前端 allocation 輸出 `theoreticalShares`、`volumeLimitedShares`、`cashLimitedShares`；LINE 沿用 dashboard allocation |
| P3-5 | GitHub Actions 最小 CI | PASS | `.github/workflows/ci.yml`, `requirements.txt` | GitHub push 後自動跑；本機同等命令已跑過 | CI 只跑 Python compile/self-check 與 frontend build，不碰 secrets 或 daily flow |

## 本次正式 run 證據

| 項目 | 值 |
| --- | --- |
| run id | `20260629_20260630_124305_prod` |
| manifest | `runs/2026-06-29/20260629_20260630_124305_prod/run_manifest.json` |
| official summary | `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/rank_portfolio_summary.json` |
| health report | `logs/data_health/data_health_20260630_125047.json` |
| health result | `checks=36 failed=0` |
| frontend build | PASS |

## 重要觀察

| 觀察 | 後續建議 |
| --- | --- |
| 加入 realistic execution 與 TCA 後，official CAGR 變成 28.09%，仍高於 0050 的 20.50% | 後續比較 phase-2 舊版與 phase-3 新版，確認成本模型合理 |
| `replacement_switch` 毛利為正但扣成本後為負 | 下一步應調高 replacement threshold、降低替換頻率，或把 replacement 納入 TCA gate |
| Forward simulation 目前 2026-06-05~2026-06-29 沒有交易 | 不是錯誤；代表 realistic gate 下該 forward 區間未觸發可成交買點 |

## 延後項目

| 項目 | 延後原因 |
| --- | --- |
| 完整漲跌停逐日撮合模型 | 目前只用日頻 OHLCV 做最低限度限制；逐筆/五檔資料成熟後再升級 |
| 完整 TCA 報表頁 | summary 已有成本拆解；前端圖表等策略決策需要時再加 |
| PSR/DSR/experiment registry | 先把交易真實性補上，再做升版統計治理 |
