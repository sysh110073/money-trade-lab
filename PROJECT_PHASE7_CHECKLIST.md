# Money Trade 第七階段優化檢查表

本階段落地長期藍圖的 Parquet 資料層第一步：保留 CSV 作為相容輸出，同時產生一份 official feature snapshot Parquet 與 manifest。暫不把所有讀取流程切到 Parquet。

| ID | 優化項目 | 狀態 | 負責檔案 | 驗收方式 | 證據 |
| --- | --- | --- | --- | --- | --- |
| P7-1 | Feature CSV to Parquet snapshot | PASS | `scripts/export_feature_snapshot.py` | `python scripts\export_feature_snapshot.py --csv ... --parquet data\processed\all_features_latest.parquet --manifest ...` | 產出 `data/processed/all_features_latest.parquet`，rows=`1,362,169`，latest_date=`2026-06-29` |
| P7-2 | Production Parquet 路徑設定 | PASS | `trading_code_ml/config/production.yaml` | `scripts\config_value.py trading_code_ml\config\production.yaml paths.feature_parquet` | `paths.feature_parquet=data/processed/all_features_latest.parquet` |
| P7-3 | Daily snapshot 接線 | PASS | `scripts/daily_update.ps1` | PowerShell scriptblock parse | daily manifest 新增 `feature_snapshot` step、`feature_parquet` artifact、`feature_snapshot_manifest` artifact |
| P7-4 | 最小自檢覆蓋 | PASS | `trading_code_ml/scripts/test_pandas_logic.py` | `python trading_code_ml\scripts\test_pandas_logic.py` | toy CSV 匯出 Parquet 並驗證 rows/latest date |

## 驗收結果

| 項目 | CSV | Parquet |
| --- | --- | --- |
| path | `C:\Users\huang\Desktop\trading_code\data\processed\all_features.csv` | `data\processed\all_features_latest.parquet` |
| rows | `1,362,169` | `1,362,169` |
| latest date | `2026-06-29` | `2026-06-29` |
| size | `1,455,505,149 bytes` | `580,641,885 bytes` |

## 本階段不做

| 延後項目 | 原因 |
| --- | --- |
| 全面改讀 Parquet | 先保留 CSV 相容性，避免一次改動所有研究腳本 |
| 分區資料湖 layout | 單檔 snapshot 已有立即 I/O 與檔案大小收益；分區等增量更新需求明確再做 |
