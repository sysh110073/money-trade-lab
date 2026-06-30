from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategyRule:
    name: str
    description: str
    fn: Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    family: str
    description: str
    rules: tuple[StrategyRule, ...]
    min_rules: int = 2


def _num(data: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column in data.columns:
        return pd.to_numeric(data[column], errors="coerce")
    return pd.Series(default, index=data.index, dtype=float)


def _rank(data: pd.DataFrame, column: str, default: float = 0.5) -> pd.Series:
    rank_col = f"rank_{column}"
    if rank_col in data.columns:
        return pd.to_numeric(data[rank_col], errors="coerce").fillna(default)
    values = _num(data, column)
    return values.groupby(data["date"]).rank(pct=True).fillna(default)


def _rule(name: str, description: str, fn: Callable[[pd.DataFrame], pd.Series]) -> StrategyRule:
    return StrategyRule(name=name, description=description, fn=fn)


def add_strategy_ranks(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.copy()
    rank_cols = [
        "close_return_1",
        "close_return_3",
        "close_return_5",
        "close_return_10",
        "volume_ratio_5",
        "volume_ratio_20",
        "total_net",
        "foreign_net_5d_sum",
        "trust_net_5d_sum",
        "revenue_mom_21d",
        "rolling_volatility_20",
        "position_in_52w_range",
        "price_to_ma_20",
        "bollinger_percent_b",
        "bollinger_std_20",
        "adx_14",
        "daily_range_pct",
        "turnover",
    ]
    for column in rank_cols:
        if column in frame.columns:
            frame[f"rank_{column}"] = _num(frame, column).groupby(frame["date"]).rank(pct=True)
    return frame


def build_strategy_catalog(max_strategies: int | None = None) -> list[StrategySpec]:
    base_rules: dict[str, list[StrategyRule]] = {
        "trend": [
            _rule("ema_bull", "EMA12 above EMA26", lambda d: _num(d, "ema_12") > _num(d, "ema_26")),
            _rule("ma20_bull", "Close above 20-day average", lambda d: _num(d, "close_sma_ratio_20") > 0),
            _rule("ma60_bull", "Close above 60-day average", lambda d: _num(d, "close_sma_ratio_60") > 0),
            _rule("macd_bull", "MACD histogram positive", lambda d: _num(d, "macd_hist") > 0),
            _rule("adx_top", "Strong ADX cross-section", lambda d: _rank(d, "adx_14") >= 0.60),
            _rule("high_pos", "Upper half of 52-week range", lambda d: _num(d, "position_in_52w_range") >= 0.55),
        ],
        "momentum": [
            _rule("mom3_top", "Top 3-day momentum", lambda d: _rank(d, "close_return_3") >= 0.70),
            _rule("mom5_top", "Top 5-day momentum", lambda d: _rank(d, "close_return_5") >= 0.70),
            _rule("mom10_top", "Top 10-day momentum", lambda d: _rank(d, "close_return_10") >= 0.70),
            _rule("mom5_positive", "5-day return positive", lambda d: _num(d, "close_return_5") > 0),
            _rule("range_expansion", "10-day range expanding", lambda d: _rank(d, "high_low_range_10") >= 0.60),
            _rule("vol_confirm", "Volume confirmation", lambda d: _rank(d, "volume_ratio_20") >= 0.60),
        ],
        "breakout": [
            _rule("near_52w_high", "Near 52-week high", lambda d: _num(d, "close") >= _num(d, "high_52w") * 0.97),
            _rule("range20_high", "High 20-day range position", lambda d: _num(d, "range_ratio_20") >= 0.80),
            _rule("bollinger_break", "Above Bollinger upper band", lambda d: _num(d, "close") > _num(d, "bollinger_upper_20")),
            _rule("volume_surge5", "5-day volume surge", lambda d: _rank(d, "volume_ratio_5") >= 0.75),
            _rule("gap_strength", "Positive gap", lambda d: _num(d, "gap_pct") > 0),
            _rule("adx_confirm", "ADX confirms breakout", lambda d: _num(d, "adx_14") >= 23),
        ],
        "mean_reversion": [
            _rule("rsi_low", "RSI below 35", lambda d: _num(d, "rsi_14") <= 35),
            _rule("bollinger_low", "Near lower Bollinger band", lambda d: _num(d, "bollinger_percent_b") <= 0.20),
            _rule("ma20_discount", "Below 20-day average", lambda d: _num(d, "close_sma_ratio_20") <= -0.03),
            _rule("mom5_weak", "Bottom 5-day momentum", lambda d: _rank(d, "close_return_5") <= 0.30),
            _rule("low_pos52", "Lower half of 52-week range", lambda d: _num(d, "position_in_52w_range") <= 0.45),
            _rule("capitulation_volume", "High volume on weakness", lambda d: _rank(d, "volume_ratio_20") >= 0.60),
        ],
        "volume_chip": [
            _rule("foreign_buy", "Foreign investors net buying", lambda d: _num(d, "foreign_net_5d_sum", 0) > 0),
            _rule("trust_buy", "Trust investors net buying", lambda d: _num(d, "trust_net_5d_sum", 0) > 0),
            _rule("total_net_buy", "Total institutional net buying", lambda d: _num(d, "total_net", 0) > 0),
            _rule("total_net_top", "Top institutional flow", lambda d: _rank(d, "total_net") >= 0.70),
            _rule("volume_top", "Top volume expansion", lambda d: _rank(d, "volume_ratio_20") >= 0.70),
            _rule("price_confirm", "Price confirms flow", lambda d: _num(d, "close_return_3") > 0),
        ],
        "fundamental_revision": [
            _rule("revenue_growth", "Revenue momentum positive", lambda d: _num(d, "revenue_mom_21d") > 0),
            _rule("revenue_top", "Top revenue momentum", lambda d: _rank(d, "revenue_mom_21d") >= 0.70),
            _rule("trend_confirm", "Trend confirms revision", lambda d: _num(d, "close_sma_ratio_20") > 0),
            _rule("flow_confirm", "Institutional flow confirms", lambda d: _num(d, "total_net", 0) > 0),
            _rule("volume_confirm", "Volume confirms revision", lambda d: _rank(d, "volume_ratio_20") >= 0.55),
            _rule("not_overextended", "Not extremely overextended", lambda d: _rank(d, "position_in_52w_range") <= 0.85),
        ],
        "low_volatility": [
            _rule("low_vol", "Low 20-day volatility", lambda d: _rank(d, "rolling_volatility_20") <= 0.35),
            _rule("trend_ok", "Trend not broken", lambda d: _num(d, "close_sma_ratio_20") > -0.01),
            _rule("range_tight", "Daily range contained", lambda d: _rank(d, "daily_range_pct") <= 0.45),
            _rule("ma60_ok", "Above 60-day average", lambda d: _num(d, "close_sma_ratio_60") > 0),
            _rule("volume_normal", "Volume not overheated", lambda d: _rank(d, "volume_ratio_20") <= 0.70),
            _rule("momentum_positive", "Momentum positive", lambda d: _num(d, "close_return_10") > 0),
        ],
        "hybrid": [
            _rule("trend_bull", "Trend aligned", lambda d: (_num(d, "ema_12") > _num(d, "ema_26")) & (_num(d, "close_sma_ratio_20") > 0)),
            _rule("pullback", "Short pullback in trend", lambda d: (_num(d, "close_return_3") < 0) & (_num(d, "close_sma_ratio_20") > 0)),
            _rule("flow_buy", "Flow support", lambda d: _num(d, "total_net", 0) > 0),
            _rule("volume_ok", "Volume support", lambda d: _rank(d, "volume_ratio_20") >= 0.50),
            _rule("not_high_vol", "Avoid highest vol names", lambda d: _rank(d, "rolling_volatility_20") <= 0.80),
            _rule("rs_ok", "Relative strength okay", lambda d: _rank(d, "close_return_10") >= 0.45),
        ],
        "pth_turnover_momentum": [
            _rule("pth_high", "High price-to-52-week range", lambda d: _rank(d, "position_in_52w_range") >= 0.70),
            _rule("turnover_top", "Top turnover", lambda d: _rank(d, "turnover") >= 0.70),
            _rule("volume_top", "Top volume ratio", lambda d: _rank(d, "volume_ratio_20") >= 0.70),
            _rule("mom5_top", "Top 5-day momentum", lambda d: _rank(d, "close_return_5") >= 0.70),
            _rule("mom10_top", "Top 10-day momentum", lambda d: _rank(d, "close_return_10") >= 0.70),
            _rule("trend_confirm", "Trend confirmation", lambda d: _num(d, "close_sma_ratio_20") > 0),
        ],
        "pth_turnover_reversal": [
            _rule("pth_low", "Low price-to-52-week range", lambda d: _rank(d, "position_in_52w_range") <= 0.30),
            _rule("turnover_low", "Low turnover", lambda d: _rank(d, "turnover") <= 0.40),
            _rule("volume_low", "Low volume ratio", lambda d: _rank(d, "volume_ratio_20") <= 0.45),
            _rule("mom5_weak", "Weak 5-day momentum", lambda d: _rank(d, "close_return_5") <= 0.30),
            _rule("rsi_low", "RSI below 40", lambda d: _num(d, "rsi_14") <= 40),
            _rule("not_crashing", "Not extreme volatility", lambda d: _rank(d, "rolling_volatility_20") <= 0.85),
        ],
        "bollinger_rsi": [
            _rule("bb_low", "Bollinger lower-zone", lambda d: _num(d, "bollinger_percent_b") <= 0.15),
            _rule("bb_high", "Bollinger upper-zone", lambda d: _num(d, "bollinger_percent_b") >= 0.85),
            _rule("rsi_oversold", "RSI oversold", lambda d: _num(d, "rsi_14") <= 35),
            _rule("rsi_recovering", "RSI recovering", lambda d: (_num(d, "rsi_14") > 35) & (_num(d, "rsi_14") < 55)),
            _rule("squeeze", "Bollinger squeeze", lambda d: _rank(d, "bollinger_std_20") <= 0.35),
            _rule("volume_confirm", "Volume confirmation", lambda d: _rank(d, "volume_ratio_20") >= 0.55),
        ],
        "volatility_switch": [
            _rule("high_vol", "High stock volatility", lambda d: _rank(d, "rolling_volatility_20") >= 0.70),
            _rule("low_vol", "Low stock volatility", lambda d: _rank(d, "rolling_volatility_20") <= 0.35),
            _rule("momentum_top", "Top momentum", lambda d: _rank(d, "close_return_10") >= 0.70),
            _rule("reversal_bottom", "Bottom short momentum", lambda d: _rank(d, "close_return_5") <= 0.30),
            _rule("range_wide", "Wide daily range", lambda d: _rank(d, "daily_range_pct") >= 0.70),
            _rule("trend_ok", "Trend okay", lambda d: _num(d, "close_sma_ratio_20") > 0),
        ],
    }

    specs: list[StrategySpec] = []
    for family, rules in base_rules.items():
        for size in (2, 3, 4, 5):
            for combo in combinations(rules, size):
                names = "_".join(rule.name for rule in combo)
                specs.append(
                    StrategySpec(
                        strategy_id=f"{family}_{names}",
                        family=family,
                        description=" + ".join(rule.description for rule in combo),
                        rules=tuple(combo),
                        min_rules=size,
                    )
                )
    cross_pairs = [
        ("trend", "volume_chip"),
        ("trend", "fundamental_revision"),
        ("momentum", "volume_chip"),
        ("breakout", "volume_chip"),
        ("mean_reversion", "volume_chip"),
        ("low_volatility", "fundamental_revision"),
        ("pth_turnover_momentum", "volume_chip"),
        ("bollinger_rsi", "volume_chip"),
        ("volatility_switch", "fundamental_revision"),
    ]
    for left, right in cross_pairs:
        for left_rule in base_rules[left]:
            for right_rule in base_rules[right]:
                specs.append(
                    StrategySpec(
                        strategy_id=f"cross_{left}_{right}_{left_rule.name}_{right_rule.name}",
                        family=f"cross_{left}_{right}",
                        description=f"{left_rule.description} + {right_rule.description}",
                        rules=(left_rule, right_rule),
                        min_rules=2,
                    )
                )
    if max_strategies is not None and max_strategies > 0:
        return specs[:max_strategies]
    return specs


def strategy_signal(data: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    if not spec.rules:
        return pd.Series(False, index=data.index)
    votes = []
    for rule in spec.rules:
        try:
            votes.append(rule.fn(data).fillna(False).astype(bool))
        except Exception:
            votes.append(pd.Series(False, index=data.index))
    score = pd.concat(votes, axis=1).sum(axis=1)
    return score >= spec.min_rules
