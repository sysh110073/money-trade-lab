# LINE Cloud Run 推播服務

這個服務只負責接收本機策略產生的文字訊息，再透過 LINE Messaging API 發送。策略與大型歷史資料仍留在本機，因此 Cloud Run 通常可落在免費額度內。

## `.env` 必填

```env
GCP_PROJECT_ID=select-stock-list
LINE_CHANNEL_ACCESS_TOKEN=你的LINE Channel Access Token
LINE_TARGET_ID=第一個UserId,第二個UserId
```

部署腳本會自動建立：

```env
LINE_CLOUD_PUSH_KEY=隨機產生的呼叫密鑰
LINE_CLOUD_PUSH_URL=部署完成後的CloudRun網址
```

LINE token、目標 ID 和呼叫密鑰會寫入 Google Secret Manager，不會包進容器映像。

## 部署

1. 安裝 Google Cloud CLI。
2. 執行 `gcloud auth login`。
3. 確認 Google Cloud 專案已啟用 Billing。
4. 執行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy_line_cloud_run.ps1
```

部署完成後，原本的每日排程會自動改走 Cloud Run，不必重新註冊排程。
