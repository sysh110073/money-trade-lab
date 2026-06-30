from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_settings, setting_path  # noqa: E402
from src.corporate_actions import ensure_price_series_contract  # noqa: E402
from src.data_fetcher import DataFetcher  # noqa: E402
from src.feature_engine import FeatureEngine  # noqa: E402
from src.institutional_overlay import overlay_recent_official_institutional_flow  # noqa: E402
from src.labeler import Labeler  # noqa: E402


DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_PROCESSED = PROJECT_ROOT / "data" / "processed" / "all_features.csv"


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    return str(value)


def _load_symbols(processed_path: Path, symbol_limit: int | None, stock_pool: list[str] | None = None) -> list[str]:
    if processed_path.exists():
        symbols = pd.read_csv(processed_path, usecols=["symbol"])["symbol"].astype(str).dropna().unique().tolist()
        if stock_pool:
            allowed = {str(symbol).zfill(4) for symbol in stock_pool}
            symbols = [symbol for symbol in symbols if str(symbol).zfill(4) in allowed]
    elif stock_pool:
        symbols = [str(symbol).zfill(4) for symbol in stock_pool]
    else:
        raise FileNotFoundError(processed_path)
    symbols = sorted(symbols)
    if symbol_limit and symbol_limit > 0:
        symbols = symbols[:symbol_limit]
    return symbols


def _normalize_raw(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    frame = df.copy()
    rename_map = {
        "datetime": "date",
        "trade_date": "date",
        "timestamp": "date",
        "vol": "volume",
    }
    frame = frame.rename(columns=rename_map)
    for column in ["date", "open", "high", "low", "close", "volume", "turnover", "change"]:
        if column not in frame.columns:
            frame[column] = np.nan
    frame = frame[["date", "open", "high", "low", "close", "volume", "turnover", "change"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    numeric_cols = [column for column in frame.columns if column != "date"]
    frame[numeric_cols] = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
    frame["symbol"] = str(symbol)
    frame = frame.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
    return frame.reset_index(drop=True)


def _load_raw(path: Path, symbol: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover", "change", "symbol"])
    return _normalize_raw(pd.read_csv(path), symbol)


def _save_raw(path: Path, df: pd.DataFrame) -> None:
    out = df.drop(columns=["symbol"], errors="ignore").copy()
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")


def _next_fetch_start(raw: pd.DataFrame, fallback_start: pd.Timestamp) -> pd.Timestamp:
    if raw.empty:
        return fallback_start
    return pd.Timestamp(raw["date"].max()) + pd.Timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch latest daily candles by API and rebuild all_features.csv.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--processed", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--start-date", default=None, help="Fallback start date when a raw CSV is missing.")
    parser.add_argument("--symbol-limit", type=int, default=0)
    parser.add_argument("--sleep-sec", type=float, default=0.05)
    parser.add_argument("--rebuild-only", action="store_true", help="Skip API fetch and only rebuild features from raw CSVs.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "data_update")
    args = parser.parse_args()

    settings = load_settings(args.config)
    if args.raw_dir == DEFAULT_RAW_DIR:
        args.raw_dir = setting_path(settings, "paths.raw_dir", DEFAULT_RAW_DIR)
    if args.processed == DEFAULT_PROCESSED:
        args.processed = setting_path(settings, "paths.processed_features", DEFAULT_PROCESSED)
    if args.output == DEFAULT_PROCESSED:
        args.output = setting_path(settings, "paths.processed_features", DEFAULT_PROCESSED)
    if args.output_dir == ROOT / "results" / "data_update":
        args.output_dir = setting_path(settings, "paths.data_update_dir", args.output_dir)
    settings["data"] = dict(settings.get("data", {}))
    settings["data"]["source"] = "fubon_neo"
    settings["data"]["end_date"] = args.end_date
    fallback_start = pd.Timestamp(args.start_date or settings["data"].get("start_date", "2013-01-01"))
    end_date = pd.Timestamp(args.end_date)

    symbols = _load_symbols(args.processed, args.symbol_limit or None, settings["data"].get("stock_pool"))
    fetcher = DataFetcher(settings, raw_dir=args.raw_dir)
    feature_engine = FeatureEngine(settings)
    labeler = Labeler(settings)

    frames: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    started_at = datetime.now()

    for index, symbol in enumerate(symbols, start=1):
        raw_path = args.raw_dir / f"{symbol}_daily.csv"
        raw = _load_raw(raw_path, symbol)
        before_last = pd.Timestamp(raw["date"].max()) if not raw.empty else pd.NaT
        fetch_start = _next_fetch_start(raw, fallback_start)
        fetched_rows = 0
        status = "already_latest"

        if not args.rebuild_only and fetch_start <= end_date:
            try:
                fetched = fetcher.fetch_daily_candles(
                    symbol,
                    fetch_start.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d"),
                )
                fetched = _normalize_raw(fetched, symbol)
                fetched_rows = int(len(fetched))
                if fetched_rows:
                    raw = pd.concat([raw, fetched], ignore_index=True)
                    raw = raw.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
                    _save_raw(raw_path, raw)
                    status = "updated"
                else:
                    status = "api_no_new_rows"
                if args.sleep_sec > 0:
                    time.sleep(args.sleep_sec)
            except Exception as exc:
                status = "api_error"
                errors.append({"symbol": symbol, "fetch_start": fetch_start, "end_date": end_date, "error": str(exc)})

        if raw.empty:
            rows.append(
                {
                    "symbol": symbol,
                    "status": "no_raw_data",
                    "before_last_date": before_last,
                    "after_last_date": pd.NaT,
                    "raw_rows": 0,
                    "fetched_rows": fetched_rows,
                }
            )
            continue

        feature_df = feature_engine.transform(raw.drop(columns=["symbol"], errors="ignore"), symbol=symbol)
        labeled = labeler.add_labels(feature_df)
        frames.append(labeled)
        after_last = pd.Timestamp(raw["date"].max())
        rows.append(
            {
                "symbol": symbol,
                "status": status,
                "before_last_date": before_last,
                "after_last_date": after_last,
                "raw_rows": int(len(raw)),
                "fetched_rows": fetched_rows,
            }
        )
        if index % 25 == 0 or index == len(symbols):
            print(
                f"[data-update] {index}/{len(symbols)} symbol={symbol} status={status} "
                f"last={after_last.date()} fetched={fetched_rows}",
                flush=True,
            )

    if not frames:
        raise RuntimeError("No feature frames were produced; all API/raw data failed.")

    processed = pd.concat(frames, ignore_index=True)
    processed["symbol"] = processed["symbol"].astype(str)
    processed = processed.sort_values(["date", "symbol"]).reset_index(drop=True)
    processed = ensure_price_series_contract(processed)
    processed = overlay_recent_official_institutional_flow(processed, log_prefix="data-update-flow-overlay")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        backup = args.output.with_name(f"{args.output.stem}_backup_{started_at:%Y%m%d_%H%M%S}{args.output.suffix}")
        args.output.replace(backup)
    else:
        backup = None
    processed.to_csv(args.output, index=False, encoding="utf-8-sig")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    status_path = args.output_dir / f"data_update_status_{stamp}.csv"
    summary_path = args.output_dir / f"data_update_summary_{stamp}.json"
    status_df = pd.DataFrame(rows)
    status_df.to_csv(status_path, index=False, encoding="utf-8-sig")
    summary = {
        "started_at": started_at,
        "ended_at": datetime.now(),
        "symbols": len(symbols),
        "rows": int(len(processed)),
        "latest_date": processed["date"].max(),
        "earliest_date": processed["date"].min(),
        "output": str(args.output),
        "backup": str(backup) if backup else None,
        "status_path": str(status_path),
        "errors": errors,
        "status_counts": status_df["status"].value_counts().to_dict() if not status_df.empty else {},
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(f"[data-update] latest_date={pd.Timestamp(summary['latest_date']).date()} rows={summary['rows']}")
    print(f"[saved] {args.output}")
    print(f"[saved] {summary_path}")


if __name__ == "__main__":
    main()
