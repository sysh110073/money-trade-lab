from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100)
    rsi = rsi.where(~((avg_gain == 0) & (avg_loss > 0)), 0)
    rsi = rsi.fillna(50)
    return rsi


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = _atr(df, period)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def _stochastic_kd(df: pd.DataFrame, k_period: int = 9, d_period: int = 3) -> tuple[pd.Series, pd.Series]:
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = ((df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)) * 100
    d = k.rolling(d_period).mean()
    return k, d


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"].fillna(0)).cumsum()


def _lag_monthly_revenue_features(data: pd.DataFrame) -> pd.DataFrame:
    cols = [col for col in ["revenue", "revenue_mom_21d"] if col in data.columns]
    if not cols:
        return data
    unavailable = data["date"].dt.day <= 10
    data.loc[unavailable, cols] = np.nan
    data[cols] = data[cols].ffill()
    return data


@dataclass
class FeatureEngine:
    settings: dict[str, Any]

    def _data_history_dir(self) -> Path:
        """Resolve the data_history base directory.

        Priority:
        1. settings["paths"]["data_history_dir"] (supports relative or absolute).
        2. PROJECT_ROOT / "data_history" as fallback.
        """
        PROJECT_ROOT = Path(__file__).resolve().parents[2]
        raw = (
            self.settings.get("paths", {})
            .get("data_history_dir", "")
        )
        if raw:
            candidate = Path(raw)
            return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
        return PROJECT_ROOT / "data_history"

    def transform(self, df: pd.DataFrame, symbol: str | None = None, benchmark: pd.DataFrame | None = None) -> pd.DataFrame:
        data = df.copy()
        data = data.sort_values("date").reset_index(drop=True)
        data["symbol"] = symbol or data.get("symbol", pd.Series([None] * len(data)))
        data["date"] = pd.to_datetime(data["date"])

        if symbol:
            _data_hist = self._data_history_dir()
            inst_path = _data_hist / "institutional" / f"{symbol}.csv"
            if os.path.exists(inst_path):
                try:
                    inst_df = pd.read_csv(inst_path)
                    inst_df["date"] = pd.to_datetime(inst_df["date"])
                    inst_df = inst_df[["date", "foreign_net", "trust_net", "total_net"]]
                    data = pd.merge(data, inst_df, on="date", how="left")
                    data["foreign_net"] = data["foreign_net"].fillna(0)
                    data["trust_net"] = data["trust_net"].fillna(0)
                    data["total_net"] = data["total_net"].fillna(0)
                    data["foreign_net_5d_sum"] = data["foreign_net"].rolling(5, min_periods=1).sum()
                    data["trust_net_5d_sum"] = data["trust_net"].rolling(5, min_periods=1).sum()
                except Exception as e:
                    print(f"Error loading institutional data for {symbol}: {e}")

            rev_path = _data_hist / "revenue" / f"{symbol}.csv"
            if os.path.exists(rev_path):
                try:
                    rev_df = pd.read_csv(rev_path)
                    rev_df["date"] = pd.to_datetime(rev_df["date"])
                    rev_df = rev_df[["date", "revenue"]]
                    data = pd.merge(data, rev_df, on="date", how="left")
                    data["revenue"] = data["revenue"].ffill()
                    data["revenue_mom_21d"] = data["revenue"] / data["revenue"].shift(21) - 1
                    data = _lag_monthly_revenue_features(data)
                except Exception as e:
                    print(f"Error loading revenue data for {symbol}: {e}")

        for window in [5, 10, 20, 60]:
            data[f"sma_{window}"] = data["close"].rolling(window, min_periods=1).mean()
            data[f"close_sma_ratio_{window}"] = (data["close"] - data[f"sma_{window}"]) / data[f"sma_{window}"]
            data[f"volume_sma_{window}"] = data["volume"].rolling(window, min_periods=1).mean()
            data[f"volume_ratio_{window}"] = data["volume"] / data[f"volume_sma_{window}"]

        for span in [12, 26]:
            data[f"ema_{span}"] = data["close"].ewm(span=span, adjust=False).mean()

        macd, macd_signal, macd_hist = _macd(data["close"])
        data["macd"] = macd
        data["macd_signal"] = macd_signal
        data["macd_hist"] = macd_hist

        data["rsi_14"] = _rsi(data["close"], 14)
        data["atr_14"] = _atr(data, 14)
        data["adx_14"] = _adx(data, 14)
        k, d = _stochastic_kd(data)
        data["stoch_k"] = k
        data["stoch_d"] = d
        data["bollinger_mid_20"] = data["close"].rolling(20, min_periods=1).mean()
        data["bollinger_std_20"] = data["close"].rolling(20, min_periods=1).std(ddof=0).fillna(0)
        data["bollinger_upper_20"] = data["bollinger_mid_20"] + 2 * data["bollinger_std_20"]
        data["bollinger_lower_20"] = data["bollinger_mid_20"] - 2 * data["bollinger_std_20"]
        data["bollinger_percent_b"] = (data["close"] - data["bollinger_lower_20"]) / (
            data["bollinger_upper_20"] - data["bollinger_lower_20"]
        )
        data["williams_r_14"] = (
            (data["high"].rolling(14, min_periods=1).max() - data["close"]) /
            (data["high"].rolling(14, min_periods=1).max() - data["low"].rolling(14, min_periods=1).min()).replace(0, np.nan)
        ) * -100
        data["obv"] = _obv(data)
        data["volume_roc_10"] = data["volume"].pct_change(10)
        data["close_return_1"] = data["close"].pct_change(1)
        for n in [3, 5, 10]:
            data[f"close_return_{n}"] = data["close"].pct_change(n)
            data[f"high_low_range_{n}"] = (data["high"].rolling(n, min_periods=1).max() - data["low"].rolling(n, min_periods=1).min()) / data["close"]
        data["high_52w"] = data["close"].rolling(252, min_periods=1).max()
        data["low_52w"] = data["close"].rolling(252, min_periods=1).min()
        data["position_in_52w_range"] = (data["close"] - data["low_52w"]) / (data["high_52w"] - data["low_52w"]).replace(0, np.nan)
        data["range_ratio_20"] = (
            (data["close"] - data["low"].rolling(20, min_periods=1).min()) /
            (data["high"].rolling(20, min_periods=1).max() - data["low"].rolling(20, min_periods=1).min()).replace(0, np.nan)
        )
        data["price_to_ma_20"] = (data["close"] - data["sma_20"]) / data["sma_20"]
        data["rolling_volatility_10"] = data["close_return_1"].rolling(10, min_periods=1).std(ddof=0)
        data["rolling_volatility_20"] = data["close_return_1"].rolling(20, min_periods=1).std(ddof=0)
        data["daily_range_pct"] = (data["high"] - data["low"]) / data["close"]
        data["gap_pct"] = data["open"] / data["close"].shift(1) - 1

        if benchmark is not None and not benchmark.empty:
            benchmark = benchmark.sort_values("date").copy()
            benchmark["benchmark_return_1"] = benchmark["close"].pct_change(1)
            merged = data.merge(benchmark[["date", "benchmark_return_1"]], on="date", how="left")
            merged["relative_strength_20"] = merged["close"].pct_change(20) - merged["benchmark_return_1"].rolling(20).sum()
            data = merged

        data = data.replace([np.inf, -np.inf], np.nan)
        return data

    def feature_columns(self, df: pd.DataFrame) -> list[str]:
        exclude = {
            "date",
            "symbol",
            "label",
            "future_return",
            "target_binary",
            "target_3class",
            "signal",
            "entry_signal",
            "exit_signal",
            "signal_reason",
            "win",
            "regime_allowed",
            "market_regime",
            "market_symbol_count",
            "market_breadth_ma20",
            "market_breadth_ma60",
            "market_positive_return_5",
            "market_volatility_20",
            "market_position_52w",
        }
        cols = [c for c in df.columns if c not in exclude]
        numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        return numeric_cols
