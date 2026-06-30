from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

try:  # pragma: no cover
    import yaml
except Exception:  # pragma: no cover
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]


DEFAULT_SETTINGS: Dict[str, Any] = {
    "data": {
        "source": "fubon_neo",
        "stock_pool": [
            "2330",
            "2317",
            "2454",
            "2882",
            "1301",
            "2881",
            "2308",
            "2303",
            "3711",
            "2886",
        ],
        "start_date": "2013-05-08",
        "end_date": "2026-05-07",
        "query_interval_days": 360,
        "retry_max": 3,
        "retry_delay_sec": 2,
    },
    "trading": {
        "initial_capital": 1_000_000,
        "commission_rate": 0.001425,
        "tax_rate": 0.003,
        "slippage": 0.001,
        "min_trade_unit": 1000,
        "holding_period_min": 7,
        "holding_period_max": 15,
        "use_strategy_exit": False,
    },
    "risk": {
        "max_risk_per_trade": 0.005,
        "max_position_pct": 0.06,
        "max_positions": 3,
        "atr_period": 14,
        "atr_stop_multiplier": 1.5,
        "take_profit_pct": 0.08,
        "trailing_stop_trigger": 0.05,
        "trailing_stop_atr": 1.0,
        "daily_loss_limit": 0.05,
        "total_loss_limit": 0.15,
        "consecutive_loss_limit": 5,
        "drawdown_soft_limit": 0.10,
        "drawdown_hard_limit": 0.28,
        "drawdown_cooldown_days": 20,
        "drawdown_position_multiplier": 0.35,
        "drawdown_max_positions_multiplier": 0.5,
        "drawdown_block_new_entries": True,
        "drawdown_hard_liquidate": False,
    },
    "model": {
        "type": "xgboost",
        "label_threshold_up": 0.05,
        "label_threshold_down": -0.03,
        "label_forward_days": 15,
        "train_years": 10,
        "validation_years": 3,
        "test_size": 0.2,
        "random_state": 42,
        "parallel_jobs": 1,
        "disable_grid_search": False,
        "sequence_length": 20,
        "dl_epochs": 12,
        "dl_batch_size": 1024,
        "dl_learning_rate": 0.001,
        "dl_patience": 3,
    },
    "strategy": {
        "probability_threshold": 0.62,
        "max_daily_entries": 5,
        "allow_short": False,
        "long_adx_threshold": 23.0,
        "volume_multiplier": 1.10,
        "rsi_overbought": 72.0,
        "rsi_oversold": 30.0,
        "use_trend_filter": True,
        "use_adx_filter": True,
        "use_volume_filter": True,
        "use_bollinger_exit": True,
        "use_strategy_exit": False,
        "use_market_regime_filter": True,
        "min_regime_symbols": 100,
        "min_market_breadth_ma20": 0.45,
        "min_market_breadth_ma60": 0.40,
        "min_market_positive_return_5": 0.30,
        "max_market_volatility_20": 0.03,
        "regime_bull_breadth_ma20": 0.55,
        "regime_bull_breadth_ma60": 0.50,
        "regime_bull_positive_return_5": 0.45,
        "regime_bear_breadth_ma20": 0.35,
        "regime_bear_breadth_ma60": 0.35,
        "regime_high_volatility_20": 0.03,
        "regime_probability_thresholds": {
            "bull": 0.60,
            "recovery": 0.62,
            "neutral": 0.66,
            "bear": 0.74,
            "high_vol": 0.78,
        },
        "regime_allow_entries": {
            "bull": True,
            "recovery": True,
            "neutral": True,
            "bear": False,
            "high_vol": False,
        },
    },
    "wfa": {
        "in_sample_days": 480,
        "out_sample_days": 120,
        "step_days": 60,
        "min_windows": 5,
    },
    "compare": {
        "top_n_patterns": 10,
        "top_n_features": 10,
        "min_stock_coverage": 0.5,
        "min_stable_score": 0.0,
        "screen_threshold": 0.65,
        "pattern_weight": 0.6,
        "feature_weight": 0.4,
        "screen_top_n": 20,
    },
    "output": {
        "results_dir": "results",
        "excel_filename": "backtest_report",
    },
}


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: str | Path = "config/settings.yaml") -> Dict[str, Any]:
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        candidate = Path(__file__).resolve().parents[1] / path
        if candidate.exists():
            path = candidate

    settings = deepcopy(DEFAULT_SETTINGS)
    base_path = path.parent / "settings.yaml"
    if path.name != "settings.yaml":
        settings = deep_merge(settings, _load_yaml(base_path))
    return deep_merge(settings, _load_yaml(path))


def resolve_project_path(value: str | Path, base: Path = PROJECT_ROOT) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def setting_path(settings: Dict[str, Any], dotted_key: str, default: str | Path) -> Path:
    value: Any = settings
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return resolve_project_path(default)
        value = value[part]
    return resolve_project_path(value)


def ensure_directories(settings: Dict[str, Any]) -> None:
    for folder in [
        Path("data/raw"),
        Path("data/processed"),
        Path(settings["output"]["results_dir"]),
    ]:
        folder.mkdir(parents=True, exist_ok=True)
