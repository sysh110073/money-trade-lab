from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
SCRIPT_ROOT = PROJECT_ROOT / "scripts"
ML_SCRIPT_ROOT = ROOT / "scripts"
for item in [ROOT, PROJECT_ROOT, SCRIPT_ROOT, ML_SCRIPT_ROOT]:
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from scripts.check_data_health import _read_js_export  # noqa: E402
from scripts.export_feature_snapshot import export_snapshot  # noqa: E402
from scripts.portfolio_api import load_portfolio, save_portfolio  # noqa: E402
from scripts.send_line_holdings import already_notified, write_notification_marker  # noqa: E402
from run_portfolio_strategy_wfa import _replacement_cost_penalty, _run_portfolio  # noqa: E402
from run_rank_portfolio_backtest import _rank, _signal_diagnostics  # noqa: E402
from src.corporate_actions import ensure_price_series_contract, normalize_corporate_actions  # noqa: E402
from src.feature_engine import FeatureEngine  # noqa: E402
from src.labeler import Labeler  # noqa: E402
from src.research_metrics import deflated_sharpe_ratio, probabilistic_sharpe_ratio  # noqa: E402
from src.risk_manager import PositionState, RiskManager, calculate_position_size  # noqa: E402


def check_labeler_no_current_day_leak() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=4),
            "close": [100, 100, 100, 100],
            "high": [200, 101, 102, 90],
        }
    )
    labeler = Labeler({"model": {"label_forward_days": 2, "label_threshold_up": 0.05, "label_threshold_down": -0.02}})
    labeled = labeler.add_labels(frame)
    assert abs(labeled.loc[0, "future_return"] - 0.02) < 1e-12
    assert labeled.loc[0, "label"] == 0


def check_risk_manager_position_and_exit() -> None:
    settings = {
        "risk": {
            "max_risk_per_trade": 0.02,
            "max_position_pct": 0.20,
            "atr_period": 14,
            "atr_stop_multiplier": 5.0,
            "take_profit_pct": 1.0,
            "trailing_stop_trigger": 0.30,
            "trailing_stop_atr": 3.5,
        },
        "trading": {"min_trade_unit": 1000, "holding_period_max": 180},
    }
    manager = RiskManager(settings)
    assert manager.position_size(total_capital=1_000_000, atr_value=2, price=50) == 2000
    position = PositionState(
        symbol="2330",
        direction=1,
        entry_date=pd.Timestamp("2026-01-01"),
        entry_price=100,
        shares=1000,
        stop_loss=90,
        take_profit=200,
        trailing_stop=95,
    )
    should_exit, reason = manager.should_exit(position, pd.Series({"low": 89, "high": 110}))
    assert should_exit and reason == "stop_loss"


def check_shared_position_sizing_limits() -> None:
    sizing = calculate_position_size(
        capital=1_000_000,
        price=50,
        atr_value=2,
        risk_pct=0.02,
        atr_multiplier=5.0,
        max_position_pct=0.20,
        min_trade_unit=1000,
        cash=1_000_000,
        volume=1500,
        max_volume_pct=1.0,
    )
    assert sizing.theoretical_shares == 2000
    assert sizing.volume_limited_shares == 1000
    assert sizing.shares == 1000


def check_feature_columns_exclude_targets() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01"],
            "symbol": ["2330"],
            "close": [100.0],
            "future_return": [0.2],
            "label": [1],
            "target_binary": [1],
            "target_3class": [1],
        }
    )
    cols = FeatureEngine({}).feature_columns(frame)
    assert "close" in cols
    assert not {"future_return", "label", "target_binary", "target_3class"} & set(cols)


def check_price_series_contract_defaults() -> None:
    frame = pd.DataFrame({"date": ["2026-01-01"], "symbol": ["2330"], "open": [99], "high": [101], "low": [98], "close": [100]})
    contracted = ensure_price_series_contract(frame)
    assert contracted.loc[0, "raw_close"] == 100
    assert contracted.loc[0, "adjusted_close"] == 100
    assert contracted.loc[0, "price_adjustment_factor"] == 1.0
    assert contracted.loc[0, "split_ratio"] == 1.0

    actions = normalize_corporate_actions(pd.DataFrame({"stock_id": ["2330"], "ex_date": ["2026-01-02"], "cashDividend": [2.5]}))
    assert actions.loc[0, "symbol"] == "2330"
    assert actions.loc[0, "corporate_action_effective_date"] == "2026-01-02"
    assert actions.loc[0, "cash_dividend"] == 2.5


def check_research_metrics_bounds() -> None:
    psr = probabilistic_sharpe_ratio(sharpe=1.0, benchmark_sharpe=0.5, observations=252)
    dsr = deflated_sharpe_ratio(sharpe=1.0, observations=252, trial_count=20)
    assert 0.0 <= psr <= 1.0
    assert 0.0 <= dsr <= 1.0
    assert dsr <= probabilistic_sharpe_ratio(sharpe=1.0, benchmark_sharpe=0.0, observations=252)


def check_no_lookahead_in_revenue() -> None:
    """月營收不能在每月前 10 天使用當月資料（_lag_monthly_revenue_features 防偷看檢查）。

    backtest_pitfalls_guide.md 規定：月初 10 日前不得使用當月最新營收，
    否則等同偷看尚未公布的資料。本測試確認 _lag_monthly_revenue_features() 會：
    1. 把月初 1~10 日的 revenue 清為 NaN（阻止當月未公布資料洩漏）。
    2. 以 ffill 向前填充前一個月的合法 revenue（不是空值）。
    3. 若前面完全沒有合法 revenue，則月初仍保持 NaN。
    """
    from src.feature_engine import _lag_monthly_revenue_features  # noqa: E402

    # 情境 A：月初有前月資料可以 ffill
    # 假設 1 月 11 日公布了 1000 的月營收，2 月 3 日尚未公布 2 月 revenue
    dates_a = pd.to_datetime(
        [
            "2026-01-05",  # 月初第 5 天（無前月資料）→ 應為 NaN
            "2026-01-11",  # 月初第 11 天 → revenue=1000 合法可用
            "2026-02-03",  # 2 月月初（10 日前）→ 被清 NaN 後 ffill 到上月的 1000
        ]
    )
    frame_a = pd.DataFrame(
        {
            "date": dates_a,
            "revenue": [1000.0, 1000.0, 1200.0],  # 2 月月初原本有 1200 但不應使用
        }
    )
    result_a = _lag_monthly_revenue_features(frame_a.copy())

    # 1 月 5 日：完全沒有前月合法值 → 應為 NaN
    assert pd.isna(result_a.loc[0, "revenue"]), (
        "2026-01-05 revenue should be NaN — no prior valid value to ffill from"
    )
    # 1 月 11 日：已過 10 日，合法 → 應保留 1000
    assert result_a.loc[1, "revenue"] == 1000.0, "2026-01-11 revenue should be 1000"
    # 2 月 3 日：雖然原本是 1200（當月），但月初前 10 天不可用
    # ffill 後應拿前面合法的 1000（上個月），而非 1200
    assert result_a.loc[2, "revenue"] == 1000.0, (
        "2026-02-03 revenue should be 1000 (ffill from Jan) not the leaked 1200"
    )

    # 情境 B：確認月初 11 日後可以使用當月新值（不會被清掉）
    dates_b = pd.to_datetime(["2026-03-11", "2026-03-15"])
    frame_b = pd.DataFrame({"date": dates_b, "revenue": [1500.0, 1500.0]})
    result_b = _lag_monthly_revenue_features(frame_b.copy())
    assert not pd.isna(result_b.loc[0, "revenue"]), "2026-03-11 revenue should be available (day > 10)"
    assert not pd.isna(result_b.loc[1, "revenue"]), "2026-03-15 revenue should be available (day > 10)"


def check_feature_snapshot_export() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        csv_path = root / "features.csv"
        parquet_path = root / "features.parquet"
        manifest_path = root / "manifest.json"
        pd.DataFrame({"date": ["2026-01-01", "2026-01-02"], "symbol": ["2330", "2330"], "close": [100, 101]}).to_csv(csv_path, index=False)
        manifest = export_snapshot(csv_path, parquet_path, manifest_path)
        assert parquet_path.exists()
        assert manifest_path.exists()
        assert manifest["rows"] == 2
        assert manifest["latest_date"] == "2026-01-02"


def check_portfolio_api_storage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "portfolio.json"
        saved = save_portfolio([{"symbol": "2330", "buyDate": "2026-01-02", "buyPrice": "100", "shares": "1000"}], path)
        assert saved[0]["symbol"] == "2330"
        assert saved[0]["highestPriceSeen"] == 100.0
        assert load_portfolio(path)[0]["shares"] == 1000


def check_rank_is_same_day_cross_section() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02"],
            "symbol": ["A", "B", "A", "B"],
            "score": [1.0, 2.0, 100.0, 50.0],
        }
    )
    ranks = _rank(frame, "score")
    assert ranks.tolist() == [0.5, 1.0, 1.0, 0.5]


def check_signal_diagnostics_explains_no_entries() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-06-05", "2026-06-05"],
            "market_regime": ["high_vol", "high_vol"],
            "entry_signal": [0, 0],
            "strategy_score": [0.9, 0.8],
            "signal_rank_gate": [True, True],
            "signal_score_gate": [True, True],
            "signal_regime_gate": [False, False],
            "signal_breadth_gate": [True, True],
            "signal_positive_return_gate": [True, True],
            "signal_volatility_gate": [True, True],
            "signal_overheat_gate": [True, True],
            "signal_market_gate": [False, False],
        }
    )
    diagnostics = _signal_diagnostics(frame)
    assert diagnostics["entry_signals"] == 0
    assert diagnostics["market_regime_counts"] == {"high_vol": 2}
    assert diagnostics["no_entry_primary_blocker"] == "signal_regime_gate"


def _tiny_settings() -> dict:
    return {
        "trading": {
            "holding_period_max": 10,
            "commission_rate": 0.0,
            "tax_rate": 0.0,
            "slippage": 0.0,
            "min_trade_unit": 1,
        },
        "risk": {
            "max_risk_per_trade": 0.02,
            "max_position_pct": 0.2,
            "atr_stop_multiplier": 5.0,
            "take_profit_pct": 1.0,
            "trailing_stop_trigger": 0.3,
            "trailing_stop_atr": 3.5,
        },
    }


def check_signal_execution_lag_and_limit_up_block() -> None:
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "symbol": ["2330", "2330"],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
            "volume": [100000, 100000],
            "entry_signal": [1, 0],
            "atr_14": [2.0, 2.0],
            "strategy_score": [1.0, 1.0],
            "rank_signal_score": [1.0, 1.0],
        }
    )
    result = _run_portfolio(base, _tiny_settings(), 1_000_000, 1.0, 1, 0.2, 1, max_risk_per_trade=0.02)
    assert str(result["buy_log"].iloc[0]["date"])[:10] == "2026-01-02"
    assert result["tca_summary"]["entry_cost"] == 0.0

    limit_up = base.copy()
    limit_up.loc[1, "open"] = 110.0
    blocked = _run_portfolio(limit_up, _tiny_settings(), 1_000_000, 1.0, 1, 0.2, 1, max_risk_per_trade=0.02)
    assert blocked["buy_log"].empty
    assert blocked["execution_stats"]["blocked_limit_up_buys"] == 1


def check_gap_stop_uses_open_price() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "symbol": ["2330", "2330", "2330"],
            "open": [100.0, 100.0, 92.0],
            "high": [101.0, 101.0, 93.0],
            "low": [99.0, 99.0, 90.0],
            "close": [100.0, 100.0, 92.0],
            "volume": [100000, 100000, 100000],
            "entry_signal": [1, 0, 0],
            "atr_14": [1.0, 1.0, 1.0],
            "strategy_score": [1.0, 1.0, 1.0],
            "rank_signal_score": [1.0, 1.0, 1.0],
        }
    )
    result = _run_portfolio(frame, _tiny_settings(), 1_000_000, 1.0, 1, 0.2, 1, max_risk_per_trade=0.02)
    trade = result["trade_log"].iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_price"] == 92.0
    assert result["execution_stats"]["gap_stop_exits"] == 1


def check_replacement_cost_gate_rejects_weak_switch() -> None:
    assert abs(_replacement_cost_penalty(3000, 1000, 1_000_000, 10.0) - 0.04) < 1e-12

    settings = _tiny_settings()
    settings["trading"].update({"commission_rate": 0.01, "tax_rate": 0.01, "slippage": 0.01})
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-03",
                ]
            ),
            "symbol": ["2330", "2317", "2330", "2317", "2330", "2317"],
            "open": [100.0] * 6,
            "high": [101.0] * 6,
            "low": [99.0] * 6,
            "close": [100.0] * 6,
            "volume": [100000] * 6,
            "entry_signal": [1, 0, 0, 1, 0, 0],
            "atr_14": [2.0] * 6,
            "strategy_score": [0.50, 0.40, 0.50, 0.57, 0.50, 0.57],
            "rank_signal_score": [1.0] * 6,
        }
    )
    result = _run_portfolio(
        frame,
        settings,
        100_000,
        1.0,
        1,
        0.5,
        1,
        max_risk_per_trade=0.02,
        replacement_threshold=0.05,
        replacement_cost_score_scale=10.0,
    )
    assert result["trade_log"].empty
    assert result["execution_stats"]["replacement_cost_gate_rejections"] == 1
    assert result["open_positions"].iloc[0]["symbol"] == "2330"


def check_js_export_parse() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.js"
        path.write_text(
            'export const dashboardData = {"dataDate":"2026-06-29","runContext":{"runId":"r1","configHash":"h1"}};\n',
            encoding="utf-8",
        )
        payload = _read_js_export(path)
        assert payload["dataDate"] == "2026-06-29"
        assert payload["runContext"]["runId"] == "r1"


def check_line_notification_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "line_notification.json"
        assert not already_notified(marker, "run-1")
        write_notification_marker(marker, "run-1", "2026-06-29", Path("dashboardData.js"))
        assert already_notified(marker, "run-1")
        assert not already_notified(marker, "run-2")


def main() -> None:
    check_labeler_no_current_day_leak()
    check_risk_manager_position_and_exit()
    check_shared_position_sizing_limits()
    check_feature_columns_exclude_targets()
    check_price_series_contract_defaults()
    check_research_metrics_bounds()
    check_no_lookahead_in_revenue()
    check_feature_snapshot_export()
    check_portfolio_api_storage()
    check_rank_is_same_day_cross_section()
    check_signal_diagnostics_explains_no_entries()
    check_signal_execution_lag_and_limit_up_block()
    check_gap_stop_uses_open_price()
    check_replacement_cost_gate_rejects_weak_switch()
    check_js_export_parse()
    check_line_notification_marker()
    print("test_pandas_logic: PASS")


if __name__ == "__main__":
    main()
