# Money Trade Official Results

Updated: 2026-06-30

This file names the current production artifacts. Research folders under
`trading_code_ml/results/` are not production inputs unless listed here.

| Item | Value |
| --- | --- |
| Production config | `trading_code_ml/config/production.yaml` |
| Official run name | `official_rank_portfolio` |
| Official result dir | `trading_code_ml/results/rank_portfolio_optimized_risk_long_20pct_norebalance` |
| Forward run name | `forward_sim_20260605_1m` |
| Forward simulation dir | `trading_code_ml/results/forward_simulation` |
| Frontend data dir | `frontend/src/data` |
| SQLite DB | `data/market_data.db` |

`frontend/scripts/generate_dashboard_data.py`, `scripts/send_line_holdings.py`,
and `scripts/db_importer.py` should use the official and forward paths above
for production output.
