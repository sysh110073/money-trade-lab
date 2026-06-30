# Money Trade Frontend

React + Vite dashboard for the official daily strategy output.

## Local Development

```powershell
npm-local.cmd install
npm-local.cmd run dev
```

Default URL:

```text
http://127.0.0.1:5173
```

## Generated Data

The dashboard reads generated files from `src/data/`:

- `dashboardData.js`
- `equityData.js`
- `rotationData.js`
- `stockSearchData.js`
- `attributionData.js`

Regenerate them through the daily workflow or directly:

```powershell
python frontend\scripts\generate_dashboard_data.py
```

## Portfolio API

Vite still has a dev-only `/api/portfolio` implementation for local testing. Static production builds do not provide POST storage by themselves.

For formal local or deployed use, run the standalone API from the repository root:

```powershell
python scripts\portfolio_api.py --host 127.0.0.1 --port 8787 --data data\real_portfolio.json
```

Production hosting should route `/api/portfolio` to that service, or to an equivalent backend.

## Build

```powershell
npm-local.cmd run build
```

Docker static image:

```powershell
docker build -f frontend\Dockerfile -t money-trade-frontend:latest frontend
docker run --rm -p 8080:80 money-trade-frontend:latest
```

## Bundled Node

This project uses the local Node runtime through `npm-local.cmd`, currently under:

```text
../tools/node-v24.16.0-win-x64
```
