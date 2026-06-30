from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
SCRIPT_ROOT = PROJECT_ROOT / "scripts"
for item in [ROOT, PROJECT_ROOT, SCRIPT_ROOT]:
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from scripts.check_data_health import _read_js_export  # noqa: E402
from scripts.send_line_holdings import already_notified, write_notification_marker  # noqa: E402
from src.labeler import Labeler  # noqa: E402
from src.risk_manager import PositionState, RiskManager  # noqa: E402


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
    check_js_export_parse()
    check_line_notification_marker()
    print("test_pandas_logic: PASS")


if __name__ == "__main__":
    main()
