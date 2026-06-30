import subprocess
import json
import concurrent.futures
from pathlib import Path

def run_backtest(sell_pct):
    label = f"{int(sell_pct * 100)}pct"
    cmd = [
        "python", "scripts/run_rank_portfolio_backtest.py",
        "--trailing-stop-sell-pct", str(sell_pct),
        "--enable-replacement",
        "--output-dir", f"results/grid_trailing_{label}"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out_dir = Path(f"results/grid_trailing_{label}")
        json_files = list(out_dir.glob("*.json"))
        if not json_files:
            return sell_pct, None
        with open(json_files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
        return sell_pct, data['performance']
    except Exception as e:
        print(f"Error for {sell_pct}: {e}")
        return sell_pct, None

sell_pcts = [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]

print("Starting grid search for trailing stop sell %...")
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    futures = [executor.submit(run_backtest, pct) for pct in sell_pcts]
    for future in concurrent.futures.as_completed(futures):
        pct, perf = future.result()
        if perf:
            results.append({
                "sell_pct": pct,
                "cagr": perf["cagr"],
                "mdd": perf["max_drawdown"],
                "sharpe": perf["sharpe"],
                "win_rate": perf["win_rate"],
                "profit_factor": perf["profit_factor"],
                "trades": perf["trades"],
                "utilization": perf["mean_capital_utilization"],
            })
            print(f"Done: sell {pct*100:.0f}% -> CAGR: {perf['cagr']:.2%}, MDD: {perf['max_drawdown']:.2%}, Sharpe: {perf['sharpe']:.2f}")

results.sort(key=lambda x: x["sell_pct"])

print("\n=== FINAL RESULTS ===")
print(f"{'Sell %':>8} | {'CAGR':>8} | {'MDD':>8} | {'Sharpe':>7} | {'WinRate':>8} | {'PF':>6} | {'Trades':>7} | {'Util':>6}")
print("-" * 80)
for r in results:
    print(f"{r['sell_pct']*100:>6.0f}%  | {r['cagr']:>7.2%} | {r['mdd']:>7.2%} | {r['sharpe']:>6.2f}  | {r['win_rate']:>7.1%} | {r['profit_factor']:>5.2f} | {r['trades']:>6.0f}  | {r['utilization']:>5.1%}")
