# 每日策略持股推播到 LINE

本專案使用 LINE Messaging API。每日更新完成且資料健檢成功後，會將最新策略持股推播到指定使用者或群組。

## 1. 建立 LINE Messaging API channel

在 LINE Developers Console 建立 Provider 與 Messaging API channel，並將該官方帳號加為好友。

## 2. 將憑證加入專案根目錄 `.env`

```env
LINE_CHANNEL_ACCESS_TOKEN=你的ChannelAccessToken
LINE_TARGET_ID=第一個UserId,第二個UserId
```

個人推播可在 channel 的 **Basic settings → Your user ID** 找到 User ID。User ID 是 33 字元並以 `U` 開頭，不是電話號碼或 LINE ID。若要推播到群組，將官方帳號加入群組，並從 webhook event 取得以 `C` 開頭的 `groupId`。

多位收件人使用半形逗號分隔，不要加入引號。

## 3. 測試

先執行完整回測，產生最新持股快照：

```powershell
python trading_code_ml\scripts\run_rank_portfolio_backtest.py --output-dir trading_code_ml\results\rank_portfolio_optimized_risk_long_20pct_norebalance
```

預覽訊息但不發送：

```powershell
python scripts\send_line_holdings.py --dry-run
```

實際發送：

```powershell
python scripts\send_line_holdings.py
```

原本的 `MoneyTrade Daily Update` 排程不必重建；它呼叫的 `daily_update.ps1` 已包含 LINE 推播。若臨時不想發送，可加上 `-SkipLineNotify`。
