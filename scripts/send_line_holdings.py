from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError
import requests

from generate_line_card import create_daily_card


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RANK_DIR = (
    PROJECT_ROOT
    / "trading_code_ml"
    / "results"
    / "rank_portfolio_optimized_risk_long_20pct_norebalance"
)
DEFAULT_DASHBOARD_DATA = PROJECT_ROOT / "frontend" / "src" / "data" / "dashboardData.js"
DEFAULT_ROTATION_DATA = PROJECT_ROOT / "frontend" / "src" / "data" / "rotationData.js"
DEFAULT_STOCK_SEARCH_DATA = PROJECT_ROOT / "frontend" / "src" / "data" / "stockSearchData.js"
DEFAULT_FORWARD_SIM_DIR = PROJECT_ROOT / "trading_code_ml" / "results" / "forward_simulation"
ACTION_LOG_DIR = PROJECT_ROOT / "data" / "strategy_actions"
DB_PATH = PROJECT_ROOT / "data" / "market_data.db"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("\"'")


def latest_positions_file(folder: Path) -> Path:
    files = sorted(
        folder.glob("rank_portfolio_positions_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"No position snapshot found in {folder}")
    return files[0]


def load_js_data(path: Path, variable_name: str) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    text = path.read_text(encoding="utf-8-sig")
    json_text = re.sub(
        rf"^\s*export\s+const\s+{re.escape(variable_name)}\s*=\s*",
        "",
        text,
        count=1,
    ).rstrip().rstrip(";")
    return json.loads(json_text)


def load_dashboard_selection(path: Path) -> pd.DataFrame:
    payload = load_js_data(path, "dashboardData")
    signal_date = str(payload.get("signalDate") or payload.get("dataDate") or "")[:10]
    rows = payload.get("allocations", {}).get("oddLot", {}).get("rows", [])
    if not isinstance(rows, list):
        raise ValueError(f"Invalid oddLot.rows in {path}")
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "name", "strategy_score", "as_of_date"])
    required = {"symbol", "name", "score"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path.name} missing fields: {', '.join(sorted(missing))}")
    return frame.rename(columns={"score": "strategy_score"}).assign(as_of_date=signal_date)


def load_action_plan(path: Path) -> dict:
    try:
        payload = load_js_data(path, "dashboardData")
        as_of = str(payload.get("signalDate") or payload.get("dataDate") or "")[:10]
        action_summary = payload.get("allocations", {}).get("oddLot", {}).get("actionSummary", {})
        buy_now = action_summary.get("buyNow", [])
        sell_now = action_summary.get("sellNow", [])
        risk_deferred = action_summary.get("riskDeferred", [])
        open_positions = payload.get("openPositions", [])
        return {
            "as_of": as_of,
            "buy_now": buy_now,
            "sell_now": sell_now,
            "risk_deferred": risk_deferred,
            "open_positions": open_positions
        }
    except Exception:
        return {}



def load_fund_radar(
    path: Path,
    sector_limit: int = 3,
    stock_limit: int = 3,
) -> dict[str, list[dict]]:
    payload = load_js_data(path, "rotationData")
    sectors = list(payload.get("sectors", []))
    stocks = list(payload.get("stocks", []))

    def sector_rows(inflow: bool) -> list[dict]:
        matching = [
            sector
            for sector in sectors
            if (float(sector.get("net5") or 0) > 0) is inflow
            and float(sector.get("net5") or 0) != 0
        ]
        matching.sort(
            key=lambda sector: float(sector.get("net5") or 0),
            reverse=inflow,
        )
        for sector in matching:
            members = [
                stock
                for stock in stocks
                if stock.get("industry") == sector.get("name")
                and (
                    float(stock.get("net5") or 0) > 0
                    if inflow
                    else float(stock.get("net5") or 0) < 0
                )
            ]
            members.sort(
                key=lambda stock: float(stock.get("net5") or 0),
                reverse=inflow,
            )
            sector["leaders"] = members[:stock_limit]
        return matching

    inflow = sector_rows(True)
    outflow = sector_rows(False)
    return {
        "inflow": inflow,
        "outflow": outflow,
        "inflow_details": inflow[:sector_limit],
        "outflow_details": outflow[:sector_limit],
    }


def load_strong_capital_signals(
    stock_path: Path,
    rotation_path: Path,
    minimum_score: float = 80.0,
    limit: int = 3,
) -> list[dict]:
    stock_data = load_js_data(stock_path, "stockSearchData")
    rotation_data = load_js_data(rotation_path, "rotationData")
    stocks = list(stock_data.get("stocks", []))
    sectors = {item.get("name"): item for item in rotation_data.get("sectors", [])}

    def positive_top_threshold(field: str, percentile: float = 0.2) -> float:
        values = sorted(
            (
                float(item.get(field) or 0)
                for item in stocks
                if float(item.get(field) or 0) > 0
            ),
            reverse=True,
        )
        if not values:
            return float("inf")
        index = max(0, math.ceil(len(values) * percentile) - 1)
        return values[index]

    latest_threshold = positive_top_threshold("totalNet")
    five_day_threshold = positive_top_threshold("totalNet5")
    matches = []
    for stock in stocks:
        sector = sectors.get(stock.get("industry"), {})
        total_net = float(stock.get("totalNet") or 0)
        total_net5 = float(stock.get("totalNet5") or 0)
        sector_net5 = float(sector.get("net5") or 0)
        all_capital_signals = (
            total_net > 0
            and total_net >= latest_threshold
            and total_net5 > 0
            and total_net5 >= five_day_threshold
            and sector_net5 > 0
            and sector.get("status") in {"main", "rotation"}
        )
        score = float(stock.get("strategyScore") or 0) * 100
        if all_capital_signals and score > minimum_score:
            matches.append(stock)
    return sorted(
        matches,
        key=lambda item: float(item.get("strategyScore") or 0),
        reverse=True,
    )[:limit]


def load_real_portfolio(stock_path: Path) -> list[dict]:
    portfolio_file = PROJECT_ROOT / "data" / "real_portfolio.json"
    if not portfolio_file.exists():
        return []
    try:
        portfolio = json.loads(portfolio_file.read_text(encoding="utf-8-sig"))
    except Exception:
        return []

    stock_data = load_js_data(stock_path, "stockSearchData")
    stocks = list(stock_data.get("stocks", []))
    stock_map = {str(s.get("symbol")): s for s in stocks}

    enriched = []
    for h in portfolio:
        symbol = str(h.get("symbol")).zfill(4)
        buy_price = float(h.get("buyPrice") or 0)
        shares = int(h.get("shares") or 0)
        highest_price = max(float(h.get("highestPriceSeen") or buy_price), buy_price)

        stock = stock_map.get(symbol, {})
        current_price = float(stock.get("currentPrice") or buy_price)
        name = str(stock.get("name") or "")

        cost_basis = buy_price * shares
        market_value = current_price * shares
        pnl = market_value - cost_basis
        roi = (pnl / cost_basis) if cost_basis > 0 else 0

        atr14 = float(stock.get("atr14") or (current_price * 0.05))
        is_trailing = current_price >= buy_price * 1.30
        stop_price = (highest_price - atr14 * 3.5) if is_trailing else (buy_price - atr14 * 5.0)

        enriched.append({
            "symbol": symbol,
            "name": name,
            "buy_price": buy_price,
            "current_price": current_price,
            "roi": roi,
            "is_trailing": is_trailing,
            "stop_price": stop_price,
            "market_value": market_value,
        })
    return sorted(enriched, key=lambda x: x["market_value"], reverse=True)


def load_stock_names() -> dict[str, str]:
    path = PROJECT_ROOT / "stock_universe" / "selected_stocks_500_liquid.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path, dtype={"stock_id": str})
    if not {"stock_id", "stock_name"}.issubset(frame.columns):
        return {}
    return {
        str(row.stock_id).zfill(4): str(row.stock_name)
        for row in frame[["stock_id", "stock_name"]].dropna().itertuples(index=False)
    }


def load_strategy_trade_actions(as_of: str, stock_path: Path = DEFAULT_STOCK_SEARCH_DATA) -> dict:
    names = load_stock_names()
    try:
        stock_data = load_js_data(stock_path, "stockSearchData")
        names.update({
            str(item.get("symbol", "")).zfill(4): str(item.get("name") or "")
            for item in stock_data.get("stocks", [])
            if item.get("symbol")
        })
    except Exception:
        pass

    trades_path = DEFAULT_FORWARD_SIM_DIR / "rank_portfolio_trades.csv"
    positions_path = DEFAULT_FORWARD_SIM_DIR / "rank_portfolio_positions.csv"
    sells = pd.DataFrame()
    buys = pd.DataFrame()
    if trades_path.exists():
        try:
            trades = pd.read_csv(trades_path, dtype={"symbol": str})
            sells = trades[trades.get("exit_date", "").astype(str).str[:10].eq(as_of)].copy()
        except EmptyDataError:
            pass
    if positions_path.exists():
        try:
            positions = pd.read_csv(positions_path, dtype={"symbol": str})
            buys = positions[positions.get("entry_date", "").astype(str).str[:10].eq(as_of)].copy()
        except EmptyDataError:
            pass

    sell_symbols = [str(row.symbol).zfill(4) for row in sells.itertuples(index=False)]
    buy_symbols = [str(row.symbol).zfill(4) for row in buys.itertuples(index=False)]
    buy_label = "、".join(f"{symbol} {names.get(symbol, '')}".strip() for symbol in buy_symbols)
    sell_label = "、".join(f"{symbol} {names.get(symbol, '')}".strip() for symbol in sell_symbols)

    sell_now = []
    for row in sells.itertuples(index=False):
        symbol = str(row.symbol).zfill(4)
        sell_now.append({
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "shares": int(float(getattr(row, "shares", 0) or 0)),
            "price": float(getattr(row, "exit_price", 0) or 0),
            "replacedBy": buy_label,
            "reason": str(getattr(row, "exit_reason", "")),
        })

    buy_now = []
    for row in buys.itertuples(index=False):
        symbol = str(row.symbol).zfill(4)
        buy_now.append({
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "shares": int(float(getattr(row, "shares", 0) or 0)),
            "price": float(getattr(row, "entry_price", 0) or 0),
            "replacedFrom": sell_label,
            "reason": "new_position",
        })

    return {"as_of": as_of, "sell_now": sell_now, "buy_now": buy_now}


def record_strategy_trade_actions(actions: dict) -> None:
    operations = [
        {"action": "sell", **item}
        for item in actions.get("sell_now", [])
    ] + [
        {"action": "buy", **item}
        for item in actions.get("buy_now", [])
    ]
    as_of = actions.get("as_of", "")
    if not as_of:
        return

    ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": as_of,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "operations": operations,
    }
    (ACTION_LOG_DIR / f"{as_of}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_action_log (
                action_date TEXT,
                action TEXT,
                symbol TEXT,
                name TEXT,
                shares INTEGER,
                price REAL,
                related_symbols TEXT,
                reason TEXT,
                generated_at TEXT,
                PRIMARY KEY (action_date, action, symbol)
            )
            """
        )
        conn.execute("DELETE FROM strategy_action_log WHERE action_date = ?", (as_of,))
        conn.executemany(
            """
            INSERT INTO strategy_action_log
            (action_date, action, symbol, name, shares, price, related_symbols, reason, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    as_of,
                    item["action"],
                    item.get("symbol", ""),
                    item.get("name", ""),
                    item.get("shares", 0),
                    item.get("price", 0.0),
                    item.get("replacedBy") or item.get("replacedFrom") or "",
                    item.get("reason", ""),
                    payload["generated_at"],
                )
                for item in operations
            ],
        )


def load_market_filter_reason(as_of: str) -> str:
    signals_path = DEFAULT_RANK_DIR / "rank_portfolio_signals.csv"
    summary_path = DEFAULT_RANK_DIR / "rank_portfolio_summary.json"
    if not signals_path.exists() or not summary_path.exists():
        return ""
    signals = pd.read_csv(
        signals_path,
        usecols=[
            "date",
            "entry_signal",
            "market_breadth_ma20",
            "market_positive_return_5",
            "market_volatility_20",
        ],
    )
    signals["date"] = signals["date"].astype(str).str[:10]
    latest = signals[signals["date"].eq(as_of)]
    if latest.empty or int(pd.to_numeric(latest["entry_signal"], errors="coerce").fillna(0).sum()) > 0:
        return ""

    settings = json.loads(summary_path.read_text(encoding="utf-8")).get("settings", {})
    checks = [
        ("大盤20日廣度", float(latest["market_breadth_ma20"].iloc[0]), settings.get("min_market_breadth_ma20"), ">="),
        ("5日正報酬比例", float(latest["market_positive_return_5"].iloc[0]), settings.get("min_market_positive_return_5"), ">="),
        ("20日波動", float(latest["market_volatility_20"].iloc[0]), settings.get("max_market_volatility_20"), "<="),
    ]
    failed = []
    for label, value, threshold, op in checks:
        if threshold is None:
            continue
        threshold = float(threshold)
        ok = value >= threshold if op == ">=" else value <= threshold
        if not ok:
            failed.append(f"{label} {value:.2%} 未達門檻 {threshold:.2%}" if op == ">=" else f"{label} {value:.2%} 高於門檻 {threshold:.2%}")
    if not failed:
        return "今日沒有新候補：策略分數或大盤濾網未通過。"
    return "今日沒有新候補：大盤濾網擋單，" + "；".join(failed) + "。"


def format_net_shares(value: float) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 10000:
        return f"{sign}{absolute / 10000:.1f}萬張"
    return f"{sign}{absolute:,.0f}張"


def build_message(
    positions: pd.DataFrame,
    source: Path,
    expected_date: str = "",
    fund_radar: dict[str, list[dict]] | None = None,
    strong_capital_signals: list[dict] | None = None,
    real_portfolio: list[dict] | None = None,
    action_plan: dict | None = None,
) -> str:
    lines = []
    as_of = expected_date or "最新交易日"

    if action_plan and (action_plan.get("buy_now") or action_plan.get("sell_now") or action_plan.get("open_positions")):
        lines.extend([f"🔥 明日操作指引｜{as_of}", ""])
        
        sell_now = action_plan.get("sell_now", [])
        if sell_now:
            lines.append("【賣出計畫 (汰弱留強)】")
            for s in sell_now:
                suffix = f"，換入 {s.get('replacedBy')}" if s.get("replacedBy") else ""
                lines.append(f"• {s.get('symbol')} {s.get('name')} (賣出 {s.get('shares')}股{suffix})")
            lines.append("")

        buy_now = action_plan.get("buy_now", [])
        if buy_now:
            lines.append("【買入計畫】")
            for b in buy_now:
                lines.append(f"• {b.get('symbol')} {b.get('name')} (建議買入 {b.get('shares')}股)")
            lines.append("")

        risk_deferred = action_plan.get("risk_deferred", [])
        if risk_deferred:
            lines.append("【風控暫緩】")
            for r in risk_deferred[:5]:
                label = r.get("riskControlLabel") or r.get("status") or "風險偏高"
                lines.append(f"• {r.get('symbol')} {r.get('name')}｜{label}")
            lines.append("")
        
        open_pos = action_plan.get("open_positions", [])
        if open_pos:
            lines.append("【策略持股防守點】")
            for p in open_pos:
                stop_loss = float(p.get('stopLoss', 0))
                trailing_stop = float(p.get('trailingStop', 0))
                is_trailing = trailing_stop > stop_loss
                stop_type = "移動止盈" if is_trailing else "初始停損"
                stop_price = trailing_stop if is_trailing else stop_loss
                risk_label = str(p.get("riskControlLabel") or "")
                suffix = f"；{risk_label}" if risk_label else ""
                lines.append(f"• {p.get('symbol')} {p.get('name')}｜若盤中跌破 {stop_price:.1f} 即賣出 ({stop_type}){suffix}")
            lines.append("")

    if real_portfolio:
        lines.extend([f"📊 我的真實持股｜{as_of}", ""])
        for rank, p in enumerate(real_portfolio, start=1):
            roi_pct = p['roi'] * 100
            sign = "+" if roi_pct >= 0 else ""
            status = "移動止盈" if p['is_trailing'] else "初始停損"
            lines.append(f"{rank}. {p['symbol']} {p['name']}｜獲利 {sign}{roi_pct:.1f}%")
            lines.append(f"   市價 {p['current_price']:.1f} (成本 {p['buy_price']:.1f})｜{status}: {p['stop_price']:.1f}")
        lines.append("")

    if positions.empty:
        reason = (action_plan or {}).get("market_filter_reason", "")
        lines.append(f"📊 每日選股資訊｜{as_of}\n目前無候選名單。")
        if reason:
            lines.append(reason)
        return "\n".join(lines).rstrip()

    required = {
        "symbol",
        "as_of_date",
        "strategy_score",
    }
    missing = required.difference(positions.columns)
    if missing:
        raise ValueError(f"{source.name} missing columns: {', '.join(sorted(missing))}")

    positions = positions.copy()
    positions["symbol"] = positions["symbol"].astype(str).str.zfill(4)
    as_of = str(positions["as_of_date"].iloc[0])[:10]
    if expected_date and as_of != expected_date:
        raise ValueError(f"Position date is {as_of}, expected {expected_date}")

    names = load_stock_names()
    positions["strategy_score"] = pd.to_numeric(positions["strategy_score"], errors="coerce")
    positions = positions.sort_values(
        ["strategy_score", "symbol"],
        ascending=[False, True],
        na_position="last",
    )
    lines.extend([
        f"📊 每日選股資訊｜{as_of}",
        "",
        "【策略持股候補名單｜依策略分數由高到低排序】",
    ])

    for rank, row in enumerate(positions.itertuples(index=False), start=1):
        symbol = str(row.symbol).zfill(4)
        row_name = getattr(row, "name", "")
        name = "" if pd.isna(row_name) else str(row_name).strip()
        name = name or names.get(symbol, "")
        lines.append(f"{rank}. {symbol} {name}".rstrip())

    lines.extend(["", "【法人資金雷達｜近5日產業輪動】"])
    if fund_radar:
        inflow_names = "、".join(
            row.get("name", "") for row in fund_radar["inflow_details"]
        )
        outflow_names = "、".join(
            row.get("name", "") for row in fund_radar["outflow_details"]
        )
        lines.append(f"流入產業 Top 3：{inflow_names or '無'}")
        lines.append(f"流出產業 Top 3：{outflow_names or '無'}")

        lines.append("")
        lines.append("主要流入產業／買超最多個股")
        for sector in fund_radar["inflow_details"]:
            lines.append(
                f"• {sector.get('name')}｜{format_net_shares(float(sector.get('net5') or 0))}"
            )
            leaders = sector.get("leaders", [])
            lines.append(
                "  "
                + "、".join(
                    (
                        f"{str(stock.get('symbol', '')).zfill(4)} {stock.get('name', '')}"
                        f" {format_net_shares(float(stock.get('net5') or 0))}"
                    )
                    for stock in leaders
                )
            )

        lines.append("")
        lines.append("主要流出產業／賣超最多個股")
        for sector in fund_radar["outflow_details"]:
            lines.append(
                f"• {sector.get('name')}｜{format_net_shares(float(sector.get('net5') or 0))}"
            )
            leaders = sector.get("leaders", [])
            lines.append(
                "  "
                + "、".join(
                    (
                        f"{str(stock.get('symbol', '')).zfill(4)} {stock.get('name', '')}"
                        f" {format_net_shares(float(stock.get('net5') or 0))}"
                    )
                    for stock in leaders
                )
            )
    else:
        lines.append("目前無資料")

    lines.extend(["", "【資金共振強勢榜｜六項資金訊號全數符合、策略分數 > 80】"])
    for rank, row in enumerate(strong_capital_signals or [], start=1):
        symbol = str(row.get("symbol", "")).zfill(4)
        name = str(row.get("name") or names.get(symbol, "")).strip()
        score = float(row.get("strategyScore") or 0) * 100
        lines.append(f"{rank}. {symbol} {name}｜{score:.1f}分")
    if not strong_capital_signals:
        lines.append("目前無符合股票")

    message = "\n".join(lines).rstrip()
    if len(message) > 5000:
        raise ValueError(f"LINE text message exceeds 5000 characters: {len(message)}")
    return message


def send_line_message(message: str, token: str, targets: list[str]) -> None:
    for target in dict.fromkeys(targets):
        response = requests.post(
            LINE_PUSH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "to": target,
                "messages": [{"type": "text", "text": message}],
            },
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"LINE API {response.status_code}: {response.text}")


def send_cloud_message(message: str, url: str, push_key: str) -> None:
    response = requests.post(
        url.rstrip("/") + "/notify",
        headers={
            "Content-Type": "application/json",
            "X-Push-Key": push_key,
        },
        json={"message": message},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Cloud push {response.status_code}: {response.text}")


def send_cloud_image(image_path: Path, url: str, push_key: str) -> None:
    with image_path.open("rb") as image_file:
        response = requests.post(
            url.rstrip("/") + "/notify-image",
            headers={"X-Push-Key": push_key},
            files={"image": (image_path.name, image_file, "image/png")},
            timeout=60,
        )
    if not response.ok:
        raise RuntimeError(f"Cloud image push {response.status_code}: {response.text}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Send latest strategy holdings to LINE.")
    parser.add_argument("--rank-dir", type=Path, default=DEFAULT_RANK_DIR)
    parser.add_argument("--dashboard-data", type=Path, default=DEFAULT_DASHBOARD_DATA)
    parser.add_argument("--rotation-data", type=Path, default=DEFAULT_ROTATION_DATA)
    parser.add_argument("--stock-search-data", type=Path, default=DEFAULT_STOCK_SEARCH_DATA)
    parser.add_argument(
        "--source",
        choices=["dashboard", "backtest-positions"],
        default="dashboard",
        help="dashboard sends the current strategy list shown in the UI.",
    )
    parser.add_argument("--expected-date", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--text-only", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    if args.source == "dashboard":
        source = args.dashboard_data
        positions = load_dashboard_selection(source)
        fund_radar = load_fund_radar(args.rotation_data)
        strong_capital_signals = load_strong_capital_signals(
            args.stock_search_data,
            args.rotation_data,
        )
        real_portfolio = load_real_portfolio(args.stock_search_data)
        action_plan = load_action_plan(source)
        as_of = args.expected_date or str(load_js_data(source, "dashboardData").get("signalDate") or "")[:10]
        action_plan["as_of"] = as_of
        action_plan["market_filter_reason"] = load_market_filter_reason(as_of)
        strategy_actions = load_strategy_trade_actions(as_of, args.stock_search_data)
        record_strategy_trade_actions(strategy_actions)
        action_plan["sell_now"] = strategy_actions["sell_now"] + action_plan.get("sell_now", [])
        action_plan["buy_now"] = strategy_actions["buy_now"] + action_plan.get("buy_now", [])
        held_symbols = {item.get("symbol") for item in action_plan.get("open_positions", [])}
        sold_symbols = {
            item.get("symbol")
            for item in strategy_actions["sell_now"]
            if item.get("symbol") not in held_symbols
        }
        action_plan["open_positions"] = [
            item for item in action_plan.get("open_positions", [])
            if item.get("symbol") not in sold_symbols
        ]
    else:
        source = latest_positions_file(args.rank_dir)
        positions = pd.read_csv(source, dtype={"symbol": str})
        fund_radar = []
        strong_capital_signals = []
        real_portfolio = []
        action_plan = {}
    message = build_message(
        positions,
        source,
        args.expected_date,
        fund_radar,
        strong_capital_signals,
        real_portfolio,
        action_plan,
    )
    card_path = PROJECT_ROOT / "results" / "line_cards" / "daily_stock_card.png"
    if args.source == "dashboard":
        create_daily_card(
            positions,
            fund_radar,
            strong_capital_signals,
            card_path,
            action_plan=action_plan,
            real_portfolio=real_portfolio
        )

    if args.dry_run:
        print(message)
        print(f"\n[source] {source}")
        if args.source == "dashboard":
            print(f"[card] {card_path}")
        return

    cloud_url = os.getenv("LINE_CLOUD_PUSH_URL", "").strip()
    cloud_key = os.getenv("LINE_CLOUD_PUSH_KEY", "").strip()
    if cloud_url:
        if not cloud_key:
            raise RuntimeError("LINE_CLOUD_PUSH_URL is set but LINE_CLOUD_PUSH_KEY is missing.")
        if args.text_only or args.source != "dashboard":
            send_cloud_message(message, cloud_url, cloud_key)
        else:
            send_cloud_image(card_path, cloud_url, cloud_key)
        print(f"[line-cloud] sent daily card via {cloud_url}")
        return

    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    targets = [
        target.strip()
        for target in os.getenv("LINE_TARGET_ID", "").split(",")
        if target.strip()
    ]
    if not token or not targets:
        print(
            "[line] skipped: add LINE_CHANNEL_ACCESS_TOKEN and LINE_TARGET_ID "
            "to .env, then run again."
        )
        return
    send_line_message(message, token, targets)
    print(f"[line] sent {len(positions)} holdings for {message.splitlines()[0].split('｜')[-1]}")


if __name__ == "__main__":
    main()
