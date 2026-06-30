from __future__ import annotations

import argparse
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "real_portfolio.json"


def _response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def load_portfolio(path: Path = DEFAULT_DATA) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("portfolio file must contain a JSON array")
    return [validate_holding(item) for item in data]


def validate_holding(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("holding must be an object")
    symbol = str(item.get("symbol", "")).strip().zfill(4)
    buy_date = str(item.get("buyDate", "")).strip()
    buy_price = float(item.get("buyPrice", 0))
    shares = int(item.get("shares", 0))
    if not symbol or buy_price <= 0 or shares <= 0 or not buy_date:
        raise ValueError("holding requires symbol, buyDate, positive buyPrice and positive shares")
    return {
        **item,
        "id": str(item.get("id") or f"{symbol}-{buy_date}"),
        "symbol": symbol,
        "buyDate": buy_date,
        "buyPrice": buy_price,
        "shares": shares,
        "highestPriceSeen": float(item.get("highestPriceSeen") or buy_price),
    }


def save_portfolio(holdings: Any, path: Path = DEFAULT_DATA) -> list[dict[str, Any]]:
    if not isinstance(holdings, list):
        raise ValueError("portfolio payload must be a JSON array")
    validated = [validate_holding(item) for item in holdings]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(validated, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp_name, path)
    return validated


def make_handler(data_path: Path) -> type[BaseHTTPRequestHandler]:
    class PortfolioHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            _response(self, 204, {})

        def do_GET(self) -> None:
            if self.path != "/api/portfolio":
                _response(self, 404, {"error": "not found"})
                return
            try:
                _response(self, 200, load_portfolio(data_path))
            except Exception as exc:
                _response(self, 500, {"error": str(exc)})

        def do_POST(self) -> None:
            if self.path != "/api/portfolio":
                _response(self, 404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "[]")
                _response(self, 200, {"success": True, "holdings": save_portfolio(payload, data_path)})
            except Exception as exc:
                _response(self, 400, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return PortfolioHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the formal real portfolio JSON API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.data))
    print(f"[portfolio-api] http://{args.host}:{args.port}/api/portfolio data={args.data}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
