import itertools
import subprocess
import json
import concurrent.futures
from pathlib import Path

def run_backtest(max_pos, max_pct):
    cmd = [
        "python", "scripts/run_rank_portfolio_backtest.py",
        "--portfolio-max-positions", str(max_pos),
        "--portfolio-max-position-pct", str(max_pct),
        "--enable-replacement",
        "--replacement-threshold", "0.05",
        "--output-dir", f"results/grid_pos_{max_pos}_pct_{max_pct}"
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Find the summary json
        out_dir = Path(f"results/grid_pos_{max_pos}_pct_{max_pct}")
        json_files = list(out_dir.glob("*.json"))
        if not json_files:
            return max_pos, max_pct, None
            
        with open(json_files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        return max_pos, max_pct, data['performance']
    except Exception as e:
        print(f"Error for {max_pos} {max_pct}: {e}")
        return max_pos, max_pct, None

combinations = [
    (4, 0.25),
    (5, 0.20),
    (5, 0.30),
    (8, 0.15),
    (8, 0.20),
    (10, 0.10),
    (10, 0.15),
    (15, 0.08)
]

print("Starting grid search for positions...")
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(run_backtest, pos, pct) for pos, pct in combinations]
    for future in concurrent.futures.as_completed(futures):
        pos, pct, perf = future.result()
        if perf:
            results.append({
                "pos": pos,
                "pct": pct,
                "cagr": perf["cagr"],
                "mdd": perf["max_drawdown"],
                "sharpe": perf["sharpe"],
                "utilization": perf["mean_capital_utilization"],
                "trades": perf["trades"]
            })
            print(f"Done: {pos} stocks, {pct*100}% max -> CAGR: {perf['cagr']:.2%}, MDD: {perf['max_drawdown']:.2%}")

results.sort(key=lambda x: x["cagr"], reverse=True)

print("\n=== FINAL RESULTS ===")
for r in results:
    print(f"Max {r['pos']} stocks, {r['pct']*100}% per stock | CAGR: {r['cagr']:.2%} | MDD: {r['mdd']:.2%} | Sharpe: {r['sharpe']:.2f} | Trades: {r['trades']} | Util: {r['utilization']:.1%}")
