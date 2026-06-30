from __future__ import annotations

import sys
from datetime import timedelta

import pandas as pd


def overlay_recent_official_institutional_flow(
    data: pd.DataFrame,
    lookback_days: int = 45,
    end_date: str | pd.Timestamp | None = None,
    log_prefix: str = "flow-overlay",
) -> pd.DataFrame:
    if data.empty or not {"date", "symbol"}.issubset(data.columns):
        data.attrs["official_institutional_rows_applied"] = 0
        return data

    dates = pd.to_datetime(data["date"], errors="coerce")
    latest_date = pd.Timestamp(end_date) if end_date is not None else dates.max()
    if pd.isna(latest_date):
        data.attrs["official_institutional_rows_applied"] = 0
        return data

    start_date = (pd.Timestamp(latest_date) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date_text = pd.Timestamp(latest_date).strftime("%Y-%m-%d")
    try:
        from data_loader import get_institutional_investors_multi_day

        official = get_institutional_investors_multi_day(start_date, end_date_text)
    except Exception as exc:
        print(f"[{log_prefix}] skipped: {exc}", file=sys.stderr)
        data.attrs["official_institutional_rows_applied"] = 0
        return data

    if official.empty:
        print(f"[{log_prefix}] no official institutional rows for {start_date}~{end_date_text}", file=sys.stderr)
        data.attrs["official_institutional_rows_applied"] = 0
        return data

    out = data.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = out["symbol"].astype(str).str.zfill(4)
    official = official.rename(columns={"stock_id": "symbol"})
    official["date"] = pd.to_datetime(official["date"])
    official["symbol"] = official["symbol"].astype(str).str.zfill(4)
    official = official.rename(
        columns={
            "foreign_net_buy": "_official_foreign_net",
            "trust_net_buy": "_official_trust_net",
            "total_net_buy": "_official_total_net",
        }
    )
    official_cols = ["date", "symbol", "_official_foreign_net", "_official_trust_net", "_official_total_net"]
    out = out.merge(official[official_cols], on=["date", "symbol"], how="left")
    has_official = out["_official_total_net"].notna()
    applied_rows = int(has_official.sum())
    if applied_rows == 0:
        out = out.drop(columns=["_official_foreign_net", "_official_trust_net", "_official_total_net"])
        out.attrs["official_institutional_rows_applied"] = 0
        return out

    out.loc[has_official, "foreign_net"] = pd.to_numeric(
        out.loc[has_official, "_official_foreign_net"], errors="coerce"
    ).fillna(0.0)
    out.loc[has_official, "trust_net"] = pd.to_numeric(
        out.loc[has_official, "_official_trust_net"], errors="coerce"
    ).fillna(0.0)
    out.loc[has_official, "total_net"] = pd.to_numeric(
        out.loc[has_official, "_official_total_net"], errors="coerce"
    ).fillna(0.0)
    out = out.sort_values(["symbol", "date"])
    out["foreign_net_5d_sum"] = (
        pd.to_numeric(out["foreign_net"], errors="coerce")
        .fillna(0.0)
        .groupby(out["symbol"])
        .rolling(5, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
    )
    out["trust_net_5d_sum"] = (
        pd.to_numeric(out["trust_net"], errors="coerce")
        .fillna(0.0)
        .groupby(out["symbol"])
        .rolling(5, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
    )
    print(
        f"[{log_prefix}] official institutional rows applied: {applied_rows:,}; "
        f"range={official['date'].min().date()}~{official['date'].max().date()}",
        file=sys.stderr,
    )
    result = (
        out.drop(columns=["_official_foreign_net", "_official_trust_net", "_official_total_net"])
        .sort_values(["date", "symbol"])
        .reset_index(drop=True)
    )
    result.attrs["official_institutional_rows_applied"] = applied_rows
    return result
