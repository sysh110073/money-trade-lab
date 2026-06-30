# Money Trade Deployment Notes

Latest validated production run:

- expected date: `2026-06-29`
- run id: `20260629_20260630_134927_prod`
- manifest: `runs/2026-06-29/20260629_20260630_134927_prod/run_manifest.json`
- health gate: `PASS`

## Formal Portfolio API

The dashboard uses `/api/portfolio` for real holdings. Vite still provides a dev-only implementation, but formal local/static deployments should run the standalone API:

```powershell
python scripts\portfolio_api.py --host 127.0.0.1 --port 8787 --data data\real_portfolio.json
```

Expose `/api/portfolio` to the browser through the same-origin reverse proxy. The API validates holdings and writes `data/real_portfolio.json` atomically.

Minimal smoke test:

```powershell
$body = '[{"symbol":"2330","buyDate":"2026-06-29","buyPrice":1000,"shares":1000}]'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8787/api/portfolio -Body $body -ContentType 'application/json'
Invoke-RestMethod http://127.0.0.1:8787/api/portfolio
```

## Strategy Attribution

`frontend/scripts/generate_dashboard_data.py` writes `frontend/src/data/attributionData.js`. The dashboard panel shows:

- signal gate pass counts
- factor weights
- TCA totals
- replacement-switch cost gate results
- exit reason counts

The health gate validates `attributionData.js` against the same run id and config hash as the other generated frontend data files.

## Docker

Daily Python image:

```powershell
docker build -f Dockerfile.daily -t money-trade-daily:latest .
```

Frontend static image:

```powershell
docker build -f frontend\Dockerfile -t money-trade-frontend:latest frontend
```

Run the frontend image:

```powershell
docker run --rm -p 8080:80 money-trade-frontend:latest
```
