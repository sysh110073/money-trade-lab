# 長期龍頭輪動策略儀表板

React + Vite 前端，用來呈現每日挑股訊號、資金使用率、策略核心因子與 0050 對照。

## 啟動

```bash
npm-local.cmd install
npm-local.cmd run dev
```

預設網址：

```text
http://127.0.0.1:5173
```

## 目前資料來源

畫面資料先接在 `src/data/dashboardData.js`，內容來自目前最新的策略回測與每日訊號輸出。後續可以把這層改成 API 讀取，讓前端每天自動抓最新檔案。

`/api/portfolio` 只存在於 Vite dev server，用來在本機開發時讀寫 `data/real_portfolio.json`。靜態 build 後沒有 POST 儲存能力；正式持倉 API 需要另接 Flask/FastAPI/Cloud Run。

## 本地 Node.js

目前使用專案內的可攜式 Node.js：

```text
../tools/node-v24.16.0-win-x64
```

使用 `npm-local.cmd` 會自動把這個 Node.js 放到 PATH 前面，避開 WindowsApps 裡目前無法執行的 `node.exe`。
