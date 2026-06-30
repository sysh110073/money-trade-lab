from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADING_ROOT = PROJECT_ROOT / "trading_code_ml"
if str(TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRADING_ROOT))

from src.corporate_actions import PRICE_SERIES_CONTRACT_COLUMNS  # noqa: E402

DEFAULT_PROCESSED = PROJECT_ROOT / "data" / "processed" / "all_features.csv"
DEFAULT_RANK_DIR = PROJECT_ROOT / "trading_code_ml" / "results" / "rank_portfolio_optimized_risk_long_20pct_norebalance"
DEFAULT_DATA_UPDATE_DIR = PROJECT_ROOT / "trading_code_ml" / "results" / "data_update"
DEFAULT_FRONT_DATA = PROJECT_ROOT / "frontend" / "src" / "data"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "logs" / "data_health"


def _today_taipei() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")


def _latest_file(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _date_only(value: Any) -> str | None:
    if value is None:
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def _read_js_export(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export\s+const\s+\w+\s*=\s*(\{.*\})\s*;?\s*$", text, flags=re.S)
    if not match:
        raise ValueError(f"Cannot parse JS export: {path}")
    return json.loads(match.group(1))


def _add_check(
    checks: list[dict[str, Any]],
    name: str,
    source: str,
    actual: Any,
    expected: Any,
    detail: str = "",
    severity: str = "error",
) -> None:
    actual_text = "" if actual is None else str(actual)
    expected_text = "" if expected is None else str(expected)
    ok = actual_text == expected_text if expected is not None else bool(actual)
    checks.append(
        {
            "name": name,
            "status": "pass" if ok else ("warn" if severity == "warning" else "fail"),
            "actual": actual_text,
            "expected": expected_text,
            "severity": severity,
            "detail": detail,
            "source": source,
        }
    )


def _add_exists_check(checks: list[dict[str, Any]], name: str, path: Path) -> bool:
    exists = path.exists()
    _add_check(checks, name, str(path), "exists" if exists else "missing", "exists")
    return exists


def _check_processed_features(checks: list[dict[str, Any]], path: Path, expected_date: str) -> None:
    if not _add_exists_check(checks, "processed_features.exists", path):
        return

    required = ["date", "symbol", "close", "foreign_net", "trust_net", "total_net"]
    try:
        columns = set(pd.read_csv(path, nrows=0).columns)
        frame = pd.read_csv(path, usecols=required)
    except Exception as exc:
        _add_check(checks, "processed_features.readable", str(path), f"error: {exc}", "readable")
        return

    dates = pd.to_datetime(frame["date"], errors="coerce")
    latest_date = _date_only(dates.max())
    _add_check(checks, "processed_features.latest_date", str(path), latest_date, expected_date)

    latest = frame.loc[dates == dates.max()].copy()
    _add_check(
        checks,
        "processed_features.latest_row_count",
        str(path),
        len(latest) >= 100,
        True,
        detail=f"latest_rows={len(latest)}",
    )

    total_net = pd.to_numeric(latest["total_net"], errors="coerce").fillna(0.0)
    _add_check(
        checks,
        "processed_features.institutional_not_blank",
        str(path),
        int((total_net != 0).sum()) > 0,
        True,
        detail=f"latest_total_net_sum={float(total_net.sum()):.3f}; nonzero_rows={int((total_net != 0).sum())}",
    )
    missing_price_contract = [column for column in PRICE_SERIES_CONTRACT_COLUMNS if column not in columns]
    _add_check(
        checks,
        "processed_features.price_series_contract",
        str(path),
        not missing_price_contract,
        True,
        detail=f"missing={','.join(missing_price_contract[:10])}",
        severity="warning",
    )


def _check_data_update_status(checks: list[dict[str, Any]], folder: Path, expected_date: str) -> None:
    path = _latest_file(folder, "data_update_status_*.csv")
    if path is None:
        _add_check(checks, "data_update_status.exists", str(folder), "missing", "exists")
        return

    _add_check(checks, "data_update_status.exists", str(path), "exists", "exists")
    frame = pd.read_csv(path)
    after = pd.to_datetime(frame.get("after_last_date"), errors="coerce")
    latest = _date_only(after.max())
    oldest = _date_only(after.min())
    _add_check(
        checks,
        "data_update_status.all_symbols_latest",
        str(path),
        oldest,
        expected_date,
        detail=f"latest={latest}; symbols={len(frame)}",
    )
    bad_statuses = {"api_error", "no_raw_data"}
    bad_count = int(frame["status"].isin(bad_statuses).sum()) if "status" in frame.columns else 0
    _add_check(checks, "data_update_status.no_failed_symbols", str(path), bad_count, 0)


def _check_rank_outputs(checks: list[dict[str, Any]], folder: Path, expected_date: str) -> None:
    summary = folder / "rank_portfolio_summary.json"
    signals = folder / "rank_portfolio_signals.csv"
    equity = folder / "rank_portfolio_equity.csv"
    summary = summary if summary.exists() else _latest_file(folder, "rank_portfolio_summary_*.json")
    signals = signals if signals.exists() else _latest_file(folder, "rank_portfolio_signals_*.csv")
    equity = equity if equity.exists() else _latest_file(folder, "rank_portfolio_equity_*.csv")

    for label, path in [
        ("rank_summary.exists", summary),
        ("rank_signals.exists", signals),
        ("rank_equity.exists", equity),
    ]:
        _add_check(checks, label, str(path or folder), "exists" if path else "missing", "exists")

    if summary:
        data = json.loads(summary.read_text(encoding="utf-8"))
        benchmark_end = _date_only(data.get("benchmark", {}).get("end"))
        _add_check(checks, "rank_summary.benchmark_end", str(summary), benchmark_end, expected_date)

    if signals:
        frame = pd.read_csv(signals, usecols=["date"])
        _add_check(checks, "rank_signals.latest_date", str(signals), _date_only(frame["date"].max()), expected_date)

    if equity:
        frame = pd.read_csv(equity, usecols=["date"])
        _add_check(checks, "rank_equity.latest_date", str(equity), _date_only(frame["date"].max()), expected_date)


def _check_frontend_data(
    checks: list[dict[str, Any]],
    folder: Path,
    expected_date: str,
    skip_sentiment_generated_today: bool = False,
    run_id: str = "",
    config_hash: str = "",
) -> None:
    files = {
        "dashboard": folder / "dashboardData.js",
        "rotation": folder / "rotationData.js",
        "stock_search": folder / "stockSearchData.js",
        "equity": folder / "equityData.js",
        "attribution": folder / "attributionData.js",
        "sentiment": folder / "sentimentData.js",
    }
    payloads: dict[str, dict[str, Any]] = {}
    for key, path in files.items():
        if not _add_exists_check(checks, f"frontend_{key}.exists", path):
            continue
        try:
            payloads[key] = _read_js_export(path)
        except Exception as exc:
            _add_check(checks, f"frontend_{key}.parseable", str(path), f"error: {exc}", "parseable")

    if run_id or config_hash:
        for key in ["dashboard", "rotation", "stock_search", "equity", "attribution"]:
            payload = payloads.get(key)
            if not payload:
                continue
            context = payload.get("runContext", {})
            if run_id:
                _add_check(checks, f"frontend_{key}.run_id", str(files[key]), context.get("runId"), run_id)
            if config_hash:
                _add_check(checks, f"frontend_{key}.config_hash", str(files[key]), context.get("configHash"), config_hash)

    dashboard = payloads.get("dashboard")
    if dashboard:
        _add_check(checks, "frontend_dashboard.data_date", str(files["dashboard"]), dashboard.get("dataDate"), expected_date)
        _add_check(checks, "frontend_dashboard.signal_date", str(files["dashboard"]), dashboard.get("signalDate"), expected_date)
        _add_check(
            checks,
            "frontend_dashboard.strategy_period_end",
            str(files["dashboard"]),
            dashboard.get("aggressive", {}).get("periodEnd"),
            expected_date,
        )

    rotation = payloads.get("rotation")
    if rotation:
        summary = rotation.get("summary", {})
        _add_check(checks, "frontend_rotation.source_date", str(files["rotation"]), summary.get("sourceDate"), expected_date)
        _add_check(
            checks,
            "frontend_rotation.uses_official_institutional_flow",
            str(files["rotation"]),
            summary.get("institutionalSource"),
            "TWSE/TPEx official institutional flow",
        )
        _add_check(
            checks,
            "frontend_rotation.institutional_total_not_blank",
            str(files["rotation"]),
            abs(float(summary.get("totalNet5") or 0.0)) > 0,
            True,
            detail=f"totalNet5={summary.get('totalNet5')}; totalNet20={summary.get('totalNet20')}",
        )

    stock_search = payloads.get("stock_search")
    if stock_search:
        summary = stock_search.get("summary", {})
        _add_check(checks, "frontend_stock_search.source_date", str(files["stock_search"]), summary.get("sourceDate"), expected_date)
        _add_check(
            checks,
            "frontend_stock_search.disposition_as_of",
            str(files["stock_search"]),
            summary.get("dispositionAsOf"),
            _today_taipei(),
        )
        _add_check(
            checks,
            "frontend_stock_search.stock_count",
            str(files["stock_search"]),
            int(summary.get("stockCount") or 0) >= 100,
            True,
            detail=f"stockCount={summary.get('stockCount')}; candidateCount={summary.get('candidateCount')}",
        )

    equity = payloads.get("equity")
    if equity:
        _add_check(checks, "frontend_equity.period_end", str(files["equity"]), equity.get("periodEnd"), expected_date)

    sentiment = payloads.get("sentiment")
    if sentiment and not skip_sentiment_generated_today:
        generated = _date_only(sentiment.get("summary", {}).get("generatedAt"))
        _add_check(checks, "frontend_sentiment.generated_today", str(files["sentiment"]), generated, _today_taipei())


def _write_reports(checks: list[dict[str, Any]], output_dir: Path, expected_date: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"data_health_{stamp}.json"
    csv_path = output_dir / f"data_health_{stamp}.csv"
    failed = [item for item in checks if item["status"] == "fail"]
    warned = [item for item in checks if item["status"] == "warn"]
    payload = {
        "generated_at": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "expected_date": expected_date,
        "status": "fail" if failed else ("warn" if warned else "pass"),
        "failed_count": len(failed),
        "warning_count": len(warned),
        "check_count": len(checks),
        "checks": checks,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "status", "actual", "expected", "severity", "detail", "source"])
        writer.writeheader()
        writer.writerows(checks)
    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether daily trading data outputs are synchronized.")
    parser.add_argument("--expected-date", default=_today_taipei())
    parser.add_argument("--processed", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--rank-dir", type=Path, default=DEFAULT_RANK_DIR)
    parser.add_argument("--data-update-dir", type=Path, default=DEFAULT_DATA_UPDATE_DIR)
    parser.add_argument("--front-data", type=Path, default=DEFAULT_FRONT_DATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--config-hash", default="")
    parser.add_argument(
        "--skip-sentiment-generated-today",
        action="store_true",
        help="Skip only the sentiment generated-at freshness check, for daily runs that explicitly skip sentiment refresh.",
    )
    parser.add_argument("--warn-only", action="store_true", help="Write the report but exit 0 even when checks fail.")
    args = parser.parse_args()

    expected_date = _date_only(args.expected_date)
    if expected_date is None:
        raise ValueError(f"Invalid --expected-date: {args.expected_date}")

    checks: list[dict[str, Any]] = []
    _check_processed_features(checks, args.processed, expected_date)
    _check_data_update_status(checks, args.data_update_dir, expected_date)
    _check_rank_outputs(checks, args.rank_dir, expected_date)
    _check_frontend_data(
        checks,
        args.front_data,
        expected_date,
        args.skip_sentiment_generated_today,
        args.run_id,
        args.config_hash,
    )

    json_path, csv_path = _write_reports(checks, args.output_dir, expected_date)
    failed = [item for item in checks if item["status"] == "fail"]
    print(f"[data-health] expected_date={expected_date} checks={len(checks)} failed={len(failed)}")
    print(f"[data-health] report={json_path}")
    print(f"[data-health] report_csv={csv_path}")
    for item in failed[:20]:
        print(
            f"[data-health][FAIL] {item['name']} actual={item['actual']} "
            f"expected={item['expected']} source={item['source']}"
        )
    if failed and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
