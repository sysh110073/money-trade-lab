from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADING_ROOT = PROJECT_ROOT / "trading_code_ml"
if str(TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRADING_ROOT))

from src.research_metrics import deflated_sharpe_ratio, probabilistic_sharpe_ratio  # noqa: E402


REGISTRY_COLUMNS = [
    "experiment_id",
    "registered_at",
    "run_id",
    "config_hash",
    "summary_path",
    "equity_path",
    "period_start",
    "period_end",
    "observations",
    "trial_count",
    "cagr",
    "sharpe",
    "benchmark_sharpe",
    "max_drawdown",
    "trades",
    "psr",
    "dsr",
    "replacement_switch_net_pnl",
    "replacement_cost_gate_rejections",
    "notes",
]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if pd.notna(number) else default


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def build_registry_row(
    summary_path: Path,
    equity_path: Path,
    experiment_id: str,
    run_id: str = "",
    config_hash: str = "",
    trial_count: int = 1,
    notes: str = "",
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    equity = pd.read_csv(equity_path, parse_dates=["date"])
    returns = pd.to_numeric(equity["equity"], errors="coerce").pct_change().dropna()
    observations = int(len(returns))
    skew = _finite(returns.skew(), 0.0) if observations else 0.0
    kurtosis = _finite(returns.kurtosis(), 0.0) + 3.0 if observations else 3.0
    performance = summary.get("performance", {})
    benchmark = summary.get("benchmark", {})
    tca = summary.get("tca", {})
    sharpe = _finite(performance.get("sharpe"))
    benchmark_sharpe = _finite(benchmark.get("sharpe"))
    return {
        "experiment_id": experiment_id,
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "config_hash": config_hash,
        "summary_path": display_path(summary_path),
        "equity_path": display_path(equity_path),
        "period_start": str(equity["date"].min().date()) if not equity.empty else "",
        "period_end": str(equity["date"].max().date()) if not equity.empty else "",
        "observations": observations,
        "trial_count": int(trial_count),
        "cagr": _finite(performance.get("cagr")),
        "sharpe": sharpe,
        "benchmark_sharpe": benchmark_sharpe,
        "max_drawdown": _finite(performance.get("max_drawdown")),
        "trades": int(_finite(performance.get("trades"))),
        "psr": probabilistic_sharpe_ratio(sharpe, benchmark_sharpe, observations, skew, kurtosis),
        "dsr": deflated_sharpe_ratio(sharpe, observations, trial_count, skew, kurtosis),
        "replacement_switch_net_pnl": _finite(tca.get("replacement_switch_net_pnl")),
        "replacement_cost_gate_rejections": int(_finite(tca.get("replacement_cost_gate_rejections"))),
        "notes": notes,
    }


def upsert_registry_row(registry_path: Path, row: dict[str, Any]) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists():
        registry = pd.read_csv(registry_path)
    else:
        registry = pd.DataFrame(columns=REGISTRY_COLUMNS)
    registry = registry[registry.get("experiment_id", pd.Series(dtype=str)).astype(str) != str(row["experiment_id"])]
    registry = pd.DataFrame([row]) if registry.empty else pd.concat([registry, pd.DataFrame([row])], ignore_index=True)
    registry = registry.reindex(columns=REGISTRY_COLUMNS).sort_values(["registered_at", "experiment_id"])
    registry.to_csv(registry_path, index=False, encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a backtest/shadow run in the research experiment registry.")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--equity", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=PROJECT_ROOT / "research" / "experiment_registry.csv")
    parser.add_argument("--experiment-id", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--config-hash", default="")
    parser.add_argument("--trial-count", type=int, default=1)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    experiment_id = args.experiment_id or args.run_id or args.summary.parent.name
    row = build_registry_row(args.summary, args.equity, experiment_id, args.run_id, args.config_hash, args.trial_count, args.notes)
    upsert_registry_row(args.registry, row)
    print(json.dumps({"status": "ok", "registry": str(args.registry), "experiment_id": experiment_id, "psr": row["psr"], "dsr": row["dsr"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
