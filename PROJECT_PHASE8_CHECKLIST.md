# Money Trade Phase 8 Checklist

Scope: finish the long-term blueprint items that make the project easier to run outside the local dev setup: a formal portfolio API, strategy attribution output, and Docker deployment checks.

Official validation date: `2026-06-29`  
Official run: `runs/2026-06-29/20260629_20260630_134927_prod/run_manifest.json`  
Health gate: `PASS`

| ID | Item | Status | Owner files | Validation command | Evidence |
| --- | --- | --- | --- | --- | --- |
| P8-1 | Formal portfolio API | PASS | `scripts/portfolio_api.py`, `trading_code_ml/scripts/test_pandas_logic.py`, `DEPLOYMENT.md` | `python scripts\portfolio_api.py --host 127.0.0.1 --port 8788 --data <temp.json>` plus GET/POST smoke test | GET returned an empty portfolio, POST saved one holding, GET returned symbol `2330` and shares `1000` |
| P8-2 | Portfolio API storage test | PASS | `trading_code_ml/scripts/test_pandas_logic.py` | `python trading_code_ml\scripts\test_pandas_logic.py` | `test_pandas_logic: PASS` |
| P8-3 | Strategy attribution data export | PASS | `frontend/scripts/generate_dashboard_data.py`, `frontend/src/data/attributionData.js`, `scripts/check_data_health.py` | `powershell -ExecutionPolicy Bypass -File scripts\daily_update.ps1 -EndDate 2026-06-29 -SkipApiFetch -SkipSentiment -SkipBuild -SkipLineNotify -SkipFundamentalSync` | `attributionData.js` includes run id `20260629_20260630_134927_prod`, config hash, gates, TCA, factor weights, and exit reasons |
| P8-4 | Strategy attribution dashboard panel | PASS | `frontend/src/components/StrategyAttributionPanel.jsx`, `frontend/src/App.jsx`, `frontend/src/styles.css` | `frontend\npm-local.cmd run build` | Vite build created `StrategyAttributionPanel-*.js` chunk |
| P8-5 | Attribution health gate | PASS | `scripts/check_data_health.py` | daily run health gate and direct health rerun | `logs\data_health\data_health_20260630_141454.json`, `checks=40`, `failed=0` |
| P8-6 | Docker daily image | PASS | `Dockerfile.daily`, `.dockerignore`, `requirements.txt` | `docker build -f Dockerfile.daily -t money-trade-daily:phase8 .` | Image build completed successfully |
| P8-7 | Docker frontend image | PASS | `frontend/Dockerfile`, `frontend/.dockerignore` | `docker build -f frontend\Dockerfile -t money-trade-frontend:phase8 frontend` | Image build completed successfully and ran Vite production build inside Docker |
| P8-8 | Deployment documentation | PASS | `DEPLOYMENT.md`, `frontend/README.md`, `PROJECT_PHASE8_CHECKLIST.md` | File review | Documents now cover API, frontend, Docker, and latest official run evidence |
| P8-9 | Portable source paths | PASS | `scripts/daily_update.ps1`, `scripts/deploy_line_cloud_run.ps1`, `scripts/register_daily_update_task.ps1`, `scripts/generate_line_card.py`, `scripts/register_experiment.py`, `frontend/scripts/generate_dashboard_data.py` | `rg -n 'C:\\Users\\huang\\Desktop\\money_trade' scripts frontend\src\data research` | Project-root defaults are script-relative; frontend attribution and registry paths are repo-relative |

## Added Capabilities

| Area | Result |
| --- | --- |
| API | `/api/portfolio` can now run outside Vite through a small stdlib HTTP server. |
| Dashboard | The frontend now shows attribution for gates, costs, replacement switches, factor weights, and exit reasons. |
| Data contract | `attributionData.js` is generated from the same official run context as the other dashboard data files and is checked by the health gate. |
| Deployment | Python daily jobs and frontend static hosting have Dockerfiles and ignore rules. |

## Strategy Impact

No new alpha rule was added in Phase 8. The official strategy remains the production rank portfolio from the same `production.yaml` settings. This phase makes the existing strategy easier to inspect and deploy; it does not change entry scoring, sizing, or exit rules.
