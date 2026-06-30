from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


PRICE_COLUMNS = ("open", "high", "low", "close")
RAW_PRICE_COLUMNS = tuple(f"raw_{column}" for column in PRICE_COLUMNS)
ADJUSTED_PRICE_COLUMNS = tuple(f"adjusted_{column}" for column in PRICE_COLUMNS)
CORPORATE_ACTION_COLUMNS = (
    "cash_dividend",
    "stock_dividend_ratio",
    "capital_reduction_ratio",
    "split_ratio",
    "corporate_action_type",
    "corporate_action_effective_date",
    "price_adjustment_factor",
)
PRICE_SERIES_CONTRACT_COLUMNS = RAW_PRICE_COLUMNS + ADJUSTED_PRICE_COLUMNS + CORPORATE_ACTION_COLUMNS


def ensure_price_series_contract(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in PRICE_COLUMNS:
        raw_column = f"raw_{column}"
        adjusted_column = f"adjusted_{column}"
        if raw_column not in out and column in out:
            out[raw_column] = out[column]
        if adjusted_column not in out and column in out:
            out[adjusted_column] = out[column]

    if "price_adjustment_factor" not in out:
        if "raw_close" in out and "adjusted_close" in out:
            raw_close = pd.to_numeric(out["raw_close"], errors="coerce").replace(0, np.nan)
            out["price_adjustment_factor"] = (pd.to_numeric(out["adjusted_close"], errors="coerce") / raw_close).fillna(1.0)
        else:
            out["price_adjustment_factor"] = 1.0

    defaults: dict[str, Any] = {
        "cash_dividend": 0.0,
        "stock_dividend_ratio": 0.0,
        "capital_reduction_ratio": 0.0,
        "split_ratio": 1.0,
        "corporate_action_type": "",
        "corporate_action_effective_date": "",
    }
    for column, default in defaults.items():
        if column not in out:
            out[column] = default
    return out


def normalize_corporate_actions(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    rename_map = {
        "stock_id": "symbol",
        "ticker": "symbol",
        "ex_date": "corporate_action_effective_date",
        "date": "corporate_action_effective_date",
        "cash": "cash_dividend",
        "cashDividend": "cash_dividend",
        "stockDividend": "stock_dividend_ratio",
        "type": "corporate_action_type",
    }
    out = out.rename(columns={source: target for source, target in rename_map.items() if source in out.columns})
    for column, default in {
        "symbol": "",
        "corporate_action_effective_date": "",
        "cash_dividend": 0.0,
        "stock_dividend_ratio": 0.0,
        "capital_reduction_ratio": 0.0,
        "split_ratio": 1.0,
        "corporate_action_type": "",
    }.items():
        if column not in out:
            out[column] = default
    out["symbol"] = out["symbol"].astype(str).str.zfill(4)
    out["corporate_action_effective_date"] = pd.to_datetime(out["corporate_action_effective_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out
