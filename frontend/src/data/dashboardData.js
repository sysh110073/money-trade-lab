export const dashboardData = {
  "updatedAt": "2026-06-08",
  "dataDate": "2026-06-29",
  "signalDate": "2026-06-29",
  "rotation_date": "2026-06-29",
  "strategyName": "長期龍頭輪動策略",
  "posture": "正式版 Risk Parity Best",
  "benchmark": "0050",
  "accountCapital": 1000000.0,
  "regime": "high_vol",
  "marketLabel": "high_vol",
  "decision": {
    "state": "觀望",
    "scoreStars": 2,
    "stance": "市場條件不足或風險偏高，保留現金等待下一次訊號",
    "suggestedPositions": 0,
    "suggestedUtilization": 0.0,
    "marketEnvironment": "high_vol",
    "riskLevel": "中高",
    "riskNotes": [
      "市場處於 bear/high_vol，不開追高新倉",
      "市場廣度或 5 日上漲家數偏弱，過熱股暫緩"
    ],
    "riskDeferredCount": 0
  },
  "aggressive": {
    "name": "正式版 Risk Parity Best",
    "totalReturn": 31.826400657377597,
    "cagr": 0.31520527448630986,
    "sharpe": 1.2522790119930036,
    "maxDrawdown": 0.34327524122918907,
    "winRate": 0.5878274268104776,
    "profitFactor": 1.6192547037371872,
    "calmar": 0.918228979630552,
    "utilization": 0.650052946120177,
    "trades": 2596.0,
    "periodStart": "2013-05-08",
    "periodEnd": "2026-06-29"
  },
  "conservative": {
    "name": "原始固定權重 Baseline",
    "totalReturn": 23.68756660976075,
    "cagr": 0.28764133171321915,
    "sharpe": 1.007441322158398,
    "maxDrawdown": 0.45853781606869787,
    "winRate": 0.5652173913043478,
    "profitFactor": 2.249844217526649,
    "calmar": 0.6273012206045071,
    "utilization": 0.8706942345408603,
    "trades": 368.0,
    "periodStart": "2013-05-08",
    "periodEnd": "2026-06-05"
  },
  "benchmarkMetrics": {
    "name": "0050",
    "totalReturn": 9.72381930184805,
    "cagr": 0.20500311425236561,
    "sharpe": 1.0956633104508666,
    "maxDrawdown": 0.33957138545125276
  },
  "weights": [
    {
      "key": "long_momentum",
      "label": "長期動能",
      "value": 0.55,
      "detail": "60 / 120 / 252 日報酬排名，尋找長線相對強勢股"
    },
    {
      "key": "trend",
      "label": "趨勢結構",
      "value": 0.25,
      "detail": "MA20 / MA60 / ADX，確認價格仍在多頭趨勢內"
    },
    {
      "key": "momentum",
      "label": "短線動能",
      "value": 0.08,
      "detail": "5 / 10 日報酬與 52 週位置，用來捕捉短線加速"
    },
    {
      "key": "flow",
      "label": "法人資金",
      "value": 0.04,
      "detail": "外資、投信與成交量排名，觀察資金是否跟進"
    },
    {
      "key": "fundamental",
      "label": "營收動能",
      "value": 0.04,
      "detail": "營收月增率排名，避免只買到純技術反彈"
    },
    {
      "key": "low_vol",
      "label": "波動控制",
      "value": 0.08,
      "detail": "偏好相對低波動標的，搭配 ATR 部位控管降低回撤"
    }
  ],
  "filters": [
    {
      "label": "市場健康度",
      "status": "未達標",
      "value": 0.3656565656565657,
      "threshold": 0.42,
      "copy": "高於門檻 42% 才允許進攻"
    },
    {
      "label": "市場情緒",
      "status": "偏弱",
      "value": 0.1757575757575757,
      "threshold": 0.22,
      "copy": "高於門檻 22% 才允許進攻"
    },
    {
      "label": "市場波動",
      "status": "可接受",
      "value": 0.0369190576727069,
      "threshold": 0.055,
      "copy": "需低於 5.5%"
    }
  ],
  "openPositions": [],
  "allocations": {
    "oddLot": {
      "label": "零股風險平價",
      "utilization": 0.0,
      "cashLeft": 1000000.0,
      "positions": 0,
      "allocatedNotional": 0.0,
      "concentration": {
        "maxPositionPct": 0,
        "topSector": "-",
        "topSectorPct": 0,
        "hhi": 0,
        "sectorWeights": {}
      },
      "statusCounts": {
        "可買入": 0,
        "替換買入": 0,
        "等待回調": 0,
        "過熱不追": 0,
        "候選觀察": 0
      },
      "actionSummary": {
        "buyNow": [],
        "waitPullback": [],
        "avoidChasing": [],
        "riskDeferred": [],
        "watch": [],
        "sellNow": []
      },
      "holdingRows": [],
      "rows": []
    },
    "roundLot": {
      "label": "整股風險平價",
      "utilization": 0.0,
      "cashLeft": 1000000.0,
      "positions": 0,
      "allocatedNotional": 0.0,
      "concentration": {
        "maxPositionPct": 0,
        "topSector": "-",
        "topSectorPct": 0,
        "hhi": 0,
        "sectorWeights": {}
      },
      "statusCounts": {
        "可買入": 0,
        "替換買入": 0,
        "等待回調": 0,
        "過熱不追": 0,
        "候選觀察": 0
      },
      "actionSummary": {
        "buyNow": [],
        "waitPullback": [],
        "avoidChasing": [],
        "riskDeferred": [],
        "watch": [],
        "sellNow": []
      },
      "holdingRows": [],
      "rows": []
    }
  },
  "runContext": {
    "runId": "20260629_20260630_134927_prod",
    "strategyVersion": "official_rank_portfolio",
    "asOfDate": "2026-06-29",
    "configHash": "sha256:3465b1265fb586109894068d3bdb4460b57d8f593126d806f65e24e36bd31ac4"
  }
};
