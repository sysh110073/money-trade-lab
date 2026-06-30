整合「市場廣度防禦模式」並驗證回測績效計畫
這份計畫的目標是將「防禦模式」實作進您的交易系統中，並且透過 「修改前（對照組）」 與 「修改後（實驗組）」 的回測數據對比，來科學地驗證這個機制是否真的能提升您的整體交易績效（例如：減少最大回檔、提高勝率）。

User Review Required
IMPORTANT

請確認本次驗證計畫的參數設定：

一般模式移動停損：維持現有的 0.05 (5%) 觸發，ATR 倍數 1.0。
防禦模式啟動條件：市場廣度 (market_breadth_ma20) < 0.45。
防禦模式移動停損 (待測試)：改為 0.02 (2%) 觸發，ATR 倍數 0.5（更嚴格）。
測試用的腳本：預計使用您專案中的 run_rank_portfolio_backtest.py 來進行績效對比。若您想使用其他腳本請告訴我！
實作與驗證步驟 (Verification Plan)
階段一：建立基準線 (Baseline)
在不修改任何程式碼的情況下，直接執行一次回測：

bash

python trading_code_ml/scripts/run_rank_portfolio_backtest.py
並記錄下核心數據：總報酬率 (Total Return)、最大回檔 (Max Drawdown)、勝率 (Win Rate) 作為對照組。

階段二：實作防禦模式 (Implementation)
修改以下三個核心檔案：

1. [MODIFY] 
config.py
在 risk 設定中加入防禦模式專用的嚴格參數：

python

        "defense_trailing_stop_trigger": 0.02, # 提早啟動移動停損
        "defense_trailing_stop_atr": 0.5,      # 縮小容忍震盪空間
2. [MODIFY] 
risk_manager.py
改寫 update_trailing_stop 函式。若接收到 is_defense_mode=True 的訊號，就切換使用上方設定的嚴格停損參數。

3. [MODIFY] 
backtester.py
在每日迴圈 (daily loop) 的開頭，讀取當天的 market_breadth_ma20。若該數值低於 min_market_breadth_ma20，則將 is_defense_mode 設為 True，並在更新每個部位的移動停損時，把這個訊號傳給 RiskManager。

階段三：執行實驗與比較 (A/B Testing)
完成程式碼修改後，再次執行相同的回測腳本：

bash

python trading_code_ml/scripts/run_rank_portfolio_backtest.py
將兩次的回測報表（或是印出的 log 數據）進行比較。

預期效果：最大回檔 (MDD) 應該要下降，因為在大跌段我們提早停損了弱勢股。
評估標準：如果 MDD 下降的幅度超過了總報酬率減少的幅度（即風報比 Calmar Ratio 提升），則這項優化是成功的。