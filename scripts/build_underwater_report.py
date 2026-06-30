from __future__ import annotations

from pathlib import Path

import pandas as pd

from report_html import text as h
from report_html import write


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "trading_code_ml" / "results" / "rank_portfolio_daily_buys_2013_2025"


def zh(value: str) -> str:
    return value.encode("ascii").decode("unicode_escape")


def pct(value: object) -> str:
    return "" if pd.isna(value) else f"{float(value):.2%}"


def money(value: object) -> str:
    return "" if pd.isna(value) else f"{float(value):,.0f}"


def stock_names() -> dict[str, str]:
    path = ROOT / "stock_universe" / "selected_stocks_500_liquid.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path, dtype={"stock_id": str})
    return dict(zip(frame["stock_id"].str.zfill(4), frame["stock_name"].fillna("")))


def trade_rows(frame: pd.DataFrame) -> str:
    return "".join(
        "<tr>"
        f"<td>{h(row.stock)}</td>"
        f"<td>{h(row.entry_date)}</td>"
        f"<td>{h(row.exit_date)}</td>"
        f"<td>{h(row.exit_reason)}</td>"
        f"<td>{int(row.holding_days)}</td>"
        f"<td>{pct(row.worst_close_return)}</td>"
        f"<td>{int(row.underwater_days)}</td>"
        f"<td>{int(row.max_underwater_streak)}</td>"
        f"<td>{'' if pd.isna(row.days_to_recover) else int(row.days_to_recover)}</td>"
        f"<td>{money(row.net_pnl)}</td>"
        f"<td>{pct(row.net_return)}</td>"
        "</tr>"
        for row in frame.itertuples()
    )


def main() -> None:
    analysis_path = REPORT_DIR / "underwater_trade_analysis_2013_2025.csv"
    data = pd.read_csv(analysis_path, dtype={"symbol": str})
    names = stock_names()
    data["symbol"] = data["symbol"].str.zfill(4)
    data["stock"] = data["symbol"].map(lambda symbol: f"{symbol} {names.get(symbol, '')}".strip())

    summary = [
        (zh(r"\u4ea4\u6613\u7b46\u6578"), f"{len(data):,}"),
        (zh(r"\u5178\u578b\u51f9\u55ae\u7b46\u6578"), f"{int(data['stuck_recovered_10pct_20d'].sum()):,}"),
        (zh(r"\u66fe\u8dcc\u7834\u6210\u672c20%\u4f46\u6700\u5f8c\u8cfa\u9322"), f"{int(data['deep_recovered_20pct'].sum()):,}"),
        (zh(r"\u9023\u7e8c\u5957\u726240\u5929\u4ee5\u4e0a"), f"{int(data['long_underwater_40d'].sum()):,}"),
        (zh(r"\u6700\u9577\u9023\u7e8c\u5957\u7262\u5929\u6578"), f"{int(data['max_underwater_streak'].max())}"),
        (zh(r"\u4e2d\u4f4d\u6578\u6700\u5dee\u6536\u76e4\u8dcc\u5e45"), pct(data["worst_close_return"].median())),
    ]

    threshold_rows: list[tuple[str, int, int, int]] = []
    for drawdown in (0.05, 0.10, 0.15, 0.20):
        for days in (10, 20, 30, 40):
            mask = (data["worst_close_return"] <= -drawdown) & (data["max_underwater_streak"] >= days)
            all_count = int(mask.sum())
            profit_count = int((mask & (data["net_pnl"] > 0)).sum())
            if all_count:
                threshold_rows.append((f"{drawdown:.0%}", days, all_count, profit_count))

    longest = data.sort_values(["max_underwater_streak", "worst_close_return"], ascending=[False, True]).head(25)
    profitable = (
        data[(data["net_pnl"] > 0) & (data["underwater_days"] > 0)]
        .sort_values(["max_underwater_streak", "worst_close_return"], ascending=[False, True])
        .head(25)
    )

    title = zh(r"2013-2025 \u5957\u7262\u8207\u51f9\u55ae\u5206\u6790")
    note = zh(
        r"\u9019\u88e1\u7528\u6bcf\u65e5\u6536\u76e4\u50f9\u4f30\u7b97\u8cb7\u5165\u5f8c\u662f\u5426\u4f4e\u65bc\u6210\u672c\uff1b"
        r"\u4e0d\u542b\u76e4\u4e2d\u4f4e\u9ede\uff0c\u6240\u4ee5\u662f\u504f\u4fdd\u5b88\u7684\u5957\u7262\u4f30\u8a08\u3002"
        r"\u5178\u578b\u51f9\u55ae\u5b9a\u7fa9\uff1a\u6700\u5f8c\u8cfa\u9322\u3001\u671f\u9593\u6700\u5dee\u6536\u76e4\u8dcc\u5e45\u8d85\u904e10%\u3001"
        r"\u4e14\u9023\u7e8c\u5957\u7262\u81f3\u5c1120\u500b\u4ea4\u6613\u65e5\u3002"
    )
    headers = [
        zh(r"\u80a1\u7968"),
        zh(r"\u8cb7\u5165\u65e5"),
        zh(r"\u51fa\u5834\u65e5"),
        zh(r"\u51fa\u5834\u539f\u56e0"),
        zh(r"\u6301\u6709\u5929\u6578"),
        zh(r"\u6700\u5dee\u6536\u76e4\u8dcc\u5e45"),
        zh(r"\u5957\u7262\u5929\u6578"),
        zh(r"\u6700\u9577\u9023\u7e8c\u5957\u7262"),
        zh(r"\u89e3\u5957\u5929\u6578"),
        zh(r"\u6de8\u640d\u76ca"),
        zh(r"\u6de8\u5831\u916c"),
    ]
    threshold_header = [
        zh(r"\u6700\u5dee\u6536\u76e4\u8dcc\u5e45"),
        zh(r"\u9023\u7e8c\u5957\u7262\u5929\u6578"),
        zh(r"\u5168\u90e8\u7b46\u6578"),
        zh(r"\u6700\u5f8c\u8cfa\u9322\u7b46\u6578"),
    ]
    back_label = zh(r"\u56de\u8cb7\u8ce3\u8cc7\u91d1\u6d41\u6c34")
    threshold_title = zh(r"\u9580\u6abb\u7d71\u8a08")
    longest_title = zh(r"\u6700\u9577\u5957\u7262\u7d00\u9304")
    profitable_title = zh(r"\u6700\u5f8c\u6709\u8cfa\u4f46\u66fe\u5957\u7262")
    link_label = zh(r"\u5957\u7262\u8207\u51f9\u55ae\u5206\u6790")

    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>{h(title)}</title>
<style>
body {{ font-family: Arial, 'Microsoft JhengHei', sans-serif; margin:24px; color:#1f2937; }}
a {{ color:#2563eb; text-decoration:none; }}
.note {{ color:#4b5563; margin:8px 0 18px; }}
.kpis {{ display:grid; grid-template-columns: repeat(3,minmax(180px,1fr)); gap:10px; margin:16px 0 22px; }}
.kpi {{ border:1px solid #d1d5db; border-radius:6px; padding:10px 12px; }}
.kpi b {{ display:block; font-size:20px; margin-top:4px; }}
table {{ border-collapse:collapse; width:100%; margin:12px 0 28px; font-size:12px; }}
th,td {{ border-bottom:1px solid #e5e7eb; padding:7px; white-space:nowrap; }}
th {{ position:sticky; top:0; background:#f9fafb; text-align:left; }}
tr:hover {{ background:#f9fafb; }}
</style>
</head>
<body>
<h1>{h(title)}</h1>
<div><a href="cashflow_report_2013_2025.html">{h(back_label)}</a></div>
<div class="note">{h(note)}</div>
<div class="kpis">{''.join(f'<div class="kpi">{h(key)}<b>{h(value)}</b></div>' for key, value in summary)}</div>
<h2>{h(threshold_title)}</h2>
<table><thead><tr>{''.join(f'<th>{h(label)}</th>' for label in threshold_header)}</tr></thead>
<tbody>{''.join(f'<tr><td>{drawdown}</td><td>{days}</td><td>{all_count}</td><td>{profit_count}</td></tr>' for drawdown, days, all_count, profit_count in threshold_rows)}</tbody></table>
<h2>{h(longest_title)}</h2>
<table><thead><tr>{''.join(f'<th>{h(label)}</th>' for label in headers)}</tr></thead><tbody>{trade_rows(longest)}</tbody></table>
<h2>{h(profitable_title)}</h2>
<table><thead><tr>{''.join(f'<th>{h(label)}</th>' for label in headers)}</tr></thead><tbody>{trade_rows(profitable)}</tbody></table>
</body>
</html>"""

    write(REPORT_DIR / "underwater_report_2013_2025.html", html)

    cashflow = REPORT_DIR / "cashflow_report_2013_2025.html"
    cashflow_text = cashflow.read_text(encoding="utf-8")
    link = f'<div class="note"><a href="underwater_report_2013_2025.html">{h(link_label)}</a></div>'
    import re

    if "underwater_report_2013_2025.html" in cashflow_text:
        cashflow_text = re.sub(
            r'<div class="note"><a href="underwater_report_2013_2025\.html">.*?</a></div>',
            link,
            cashflow_text,
            count=1,
        )
    else:
        cashflow_text = cashflow_text.replace("</h1>", "</h1>\n" + link, 1)
    write(cashflow, cashflow_text)

    print(REPORT_DIR / "underwater_report_2013_2025.html")


if __name__ == "__main__":
    main()
