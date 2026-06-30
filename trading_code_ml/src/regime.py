from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(default, index=frame.index, dtype=float)


def classify_market_regime(metrics: pd.DataFrame, settings: dict[str, Any]) -> pd.Series:
    cfg = dict(settings.get("strategy", {}))
    breadth20 = pd.to_numeric(metrics.get("market_breadth_ma20", 0.0), errors="coerce").fillna(0.0)
    breadth60 = pd.to_numeric(metrics.get("market_breadth_ma60", 0.0), errors="coerce").fillna(0.0)
    positive5 = pd.to_numeric(metrics.get("market_positive_return_5", 0.0), errors="coerce").fillna(0.0)
    vol20 = pd.to_numeric(metrics.get("market_volatility_20", 0.0), errors="coerce").fillna(np.inf)

    bull_b20 = float(cfg.get("regime_bull_breadth_ma20", 0.55))
    bull_b60 = float(cfg.get("regime_bull_breadth_ma60", 0.50))
    bull_p5 = float(cfg.get("regime_bull_positive_return_5", 0.45))
    bear_b20 = float(cfg.get("regime_bear_breadth_ma20", 0.35))
    bear_b60 = float(cfg.get("regime_bear_breadth_ma60", 0.35))
    high_vol = float(cfg.get("regime_high_volatility_20", cfg.get("max_market_volatility_20", 0.03)))

    labels = pd.Series("neutral", index=metrics.index, dtype=object)
    labels.loc[(breadth20 >= bull_b20) & (breadth60 >= bull_b60) & (positive5 >= bull_p5) & (vol20 <= high_vol)] = "bull"
    labels.loc[(breadth20 >= bull_b20) & (breadth60 < bull_b60) & (positive5 >= bull_p5) & (vol20 <= high_vol)] = "recovery"
    labels.loc[(breadth20 < bear_b20) | (breadth60 < bear_b60)] = "bear"
    labels.loc[vol20 > high_vol] = "high_vol"
    return labels


def market_regime_by_date(data: pd.DataFrame, settings: dict[str, Any]) -> pd.DataFrame:
    dates = pd.DataFrame({"date": pd.to_datetime(data["date"].dropna().unique())})
    if dates.empty:
        return pd.DataFrame(columns=["date", "regime_allowed", "market_regime"])

    frame = data.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for column in [
        "close",
        "sma_20",
        "sma_60",
        "close_return_5",
        "rolling_volatility_20",
        "position_in_52w_range",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    grouped = frame.groupby("date", sort=False)
    regime = grouped.size().rename("market_symbol_count").to_frame()
    if {"close", "sma_20"}.issubset(frame.columns):
        regime["market_breadth_ma20"] = grouped.apply(lambda x: (x["close"] > x["sma_20"]).mean())
    else:
        regime["market_breadth_ma20"] = 1.0
    if {"close", "sma_60"}.issubset(frame.columns):
        regime["market_breadth_ma60"] = grouped.apply(lambda x: (x["close"] > x["sma_60"]).mean())
    else:
        regime["market_breadth_ma60"] = 1.0
    if "close_return_5" in frame.columns:
        regime["market_positive_return_5"] = grouped.apply(lambda x: (x["close_return_5"] > 0).mean())
    else:
        regime["market_positive_return_5"] = 1.0
    if "rolling_volatility_20" in frame.columns:
        regime["market_volatility_20"] = grouped["rolling_volatility_20"].median()
    else:
        regime["market_volatility_20"] = 0.0
    if "position_in_52w_range" in frame.columns:
        regime["market_position_52w"] = grouped["position_in_52w_range"].median()
    else:
        regime["market_position_52w"] = 1.0

    regime = regime.reset_index()
    cfg = dict(settings.get("strategy", {}))
    allowed = (
        (regime["market_symbol_count"] >= int(cfg.get("min_regime_symbols", 100)))
        & (regime["market_breadth_ma20"] >= float(cfg.get("min_market_breadth_ma20", 0.45)))
        & (regime["market_breadth_ma60"] >= float(cfg.get("min_market_breadth_ma60", 0.40)))
        & (regime["market_positive_return_5"] >= float(cfg.get("min_market_positive_return_5", 0.30)))
        & (regime["market_volatility_20"].fillna(0.0) <= float(cfg.get("max_market_volatility_20", 0.03)))
    )
    regime["regime_allowed"] = allowed
    regime["market_regime"] = classify_market_regime(regime, settings)
    return dates.merge(regime, on="date", how="left").fillna(
        {
            "market_symbol_count": 0,
            "market_breadth_ma20": 0.0,
            "market_breadth_ma60": 0.0,
            "market_positive_return_5": 0.0,
            "market_volatility_20": np.inf,
            "market_position_52w": 0.0,
            "regime_allowed": False,
            "market_regime": "unknown",
        }
    )


def attach_market_regime(data: pd.DataFrame, settings: dict[str, Any]) -> pd.DataFrame:
    regime = market_regime_by_date(data, settings)
    frame = data.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.merge(regime, on="date", how="left")
