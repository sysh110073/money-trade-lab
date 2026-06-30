export const attributionData = {
  "performance": {
    "total_return": 31.826400657377597,
    "cagr": 0.31520527448630986,
    "sharpe": 1.2522790119930036,
    "max_drawdown": 0.34327524122918907,
    "win_rate": 0.5878274268104776,
    "profit_factor": 1.6192547037371872,
    "trades": 2596.0,
    "mean_capital_utilization": 0.650052946120177
  },
  "benchmark": {
    "benchmark_symbol": "0050",
    "found": true,
    "source": "api",
    "api_path": "trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance/benchmark_data/benchmark_0050_20130508_20260629.csv",
    "start": "2013-05-08T00:00:00",
    "end": "2026-06-29T00:00:00",
    "total_return": 9.72381930184805,
    "cagr": 0.20500311425236561,
    "sharpe": 1.0956633104508666,
    "max_drawdown": 0.33957138545125276
  },
  "weights": {
    "momentum": 0.08,
    "long_momentum": 0.55,
    "trend": 0.25,
    "flow": 0.04,
    "fundamental": 0.04,
    "low_vol": 0.08
  },
  "signalDiagnostics": {
    "rows": 1362169,
    "dates": 3211,
    "entry_signals": 22268,
    "max_strategy_score": 0.9882671589117297,
    "market_regime_counts": {
      "bear": 361227,
      "bull": 449791,
      "high_vol": 77587,
      "neutral": 417273,
      "recovery": 56291
    },
    "signal_rank_gate_rows": 38532,
    "signal_score_gate_rows": 359985,
    "signal_regime_gate_rows": 923355,
    "signal_breadth_gate_rows": 918037,
    "signal_positive_return_gate_rows": 1196867,
    "signal_volatility_gate_rows": 1361810,
    "signal_overheat_gate_rows": 1358513,
    "signal_market_gate_rows": 822732,
    "no_entry_primary_blocker": null
  },
  "gateRows": [
    {
      "key": "signal_rank_gate",
      "passed": 38532,
      "total": 1362169,
      "rate": 0.028287238954931435
    },
    {
      "key": "signal_score_gate",
      "passed": 359985,
      "total": 1362169,
      "rate": 0.26427337577055415
    },
    {
      "key": "signal_regime_gate",
      "passed": 923355,
      "total": 1362169,
      "rate": 0.6778564186969458
    },
    {
      "key": "signal_breadth_gate",
      "passed": 918037,
      "total": 1362169,
      "rate": 0.6739523509931588
    },
    {
      "key": "signal_positive_return_gate",
      "passed": 1196867,
      "total": 1362169,
      "rate": 0.8786479504378678
    },
    {
      "key": "signal_volatility_gate",
      "passed": 1361810,
      "total": 1362169,
      "rate": 0.9997364497356789
    },
    {
      "key": "signal_overheat_gate",
      "passed": 1358513,
      "total": 1362169,
      "rate": 0.9973160452190587
    },
    {
      "key": "signal_market_gate",
      "passed": 822732,
      "total": 1362169,
      "rate": 0.6039867299872482
    }
  ],
  "latestGateRows": [
    {
      "key": "signal_rank_gate",
      "passed": 12,
      "total": 495,
      "rate": 0.024242424242424242
    },
    {
      "key": "signal_score_gate",
      "passed": 132,
      "total": 495,
      "rate": 0.26666666666666666
    },
    {
      "key": "signal_regime_gate",
      "passed": 0,
      "total": 495,
      "rate": 0.0
    },
    {
      "key": "signal_breadth_gate",
      "passed": 0,
      "total": 495,
      "rate": 0.0
    },
    {
      "key": "signal_positive_return_gate",
      "passed": 0,
      "total": 495,
      "rate": 0.0
    },
    {
      "key": "signal_volatility_gate",
      "passed": 495,
      "total": 495,
      "rate": 1.0
    },
    {
      "key": "signal_overheat_gate",
      "passed": 495,
      "total": 495,
      "rate": 1.0
    },
    {
      "key": "signal_market_gate",
      "passed": 0,
      "total": 495,
      "rate": 0.0
    }
  ],
  "executionStats": {
    "blocked_limit_up_buys": 53,
    "blocked_limit_down_exits": 46,
    "gap_stop_exits": 625,
    "skipped_low_volume_buys": 23,
    "volume_capped_entries": 79,
    "replacement_cost_gate_rejections": 543
  },
  "tca": {
    "entry_cost": 3109335.838017569,
    "exit_cost": 7219996.178586981,
    "total_cost": 10329332.01660455,
    "replacement_switch_trades": 1524,
    "replacement_switch_gross_pnl": 7551918.640000001,
    "replacement_switch_net_pnl": 1655482.1180360771,
    "replacement_switch_exit_cost": 5896436.521963922,
    "replacement_buy_cost": 2873011.7834446235,
    "replacement_cost_gate_rejections": 543
  },
  "exitReasons": [
    {
      "reason": "replacement_switch",
      "count": 1524
    },
    {
      "reason": "trailing_stop",
      "count": 941
    },
    {
      "reason": "stop_loss",
      "count": 89
    },
    {
      "reason": "take_profit",
      "count": 42
    }
  ],
  "runContext": {
    "runId": "20260629_20260630_134927_prod",
    "strategyVersion": "official_rank_portfolio",
    "asOfDate": "2026-06-29",
    "configHash": "sha256:3465b1265fb586109894068d3bdb4460b57d8f593126d806f65e24e36bd31ac4"
  }
};
