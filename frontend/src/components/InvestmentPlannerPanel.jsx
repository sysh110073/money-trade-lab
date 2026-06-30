import { useMemo, useState } from "react";
import { dashboardData } from "../data/dashboardData";
import { stockSearchData } from "../data/stockSearchData";
import { planPurchases } from "../utils/investmentPlanner";

const today = () => new Date().toISOString().split("T")[0];
const money = (value) =>
  new Intl.NumberFormat("zh-TW", {
    style: "currency",
    currency: "TWD",
    maximumFractionDigits: 0
  }).format(value || 0);
const pct = (value, digits = 1) =>
  value === null || value === undefined ? "-" : `${(value * 100).toFixed(digits)}%`;

export default function InvestmentPlannerPanel() {
  const [buyDate, setBuyDate] = useState(today());
  const [amount, setAmount] = useState("100000");
  const [saving, setSaving] = useState(false);
  const plan = useMemo(() => planPurchases(stockSearchData.stocks, amount), [amount]);
  const canEnter =
    (dashboardData.decision?.suggestedPositions || 0) > 0 &&
    (dashboardData.decision?.suggestedUtilization || 0) > 0;

  const addToTracking = async () => {
    if (!canEnter || !plan.rows.length) return;
    setSaving(true);
    try {
      const res = await fetch("/api/portfolio");
      const holdings = res.ok ? await res.json() : [];
      const next = [
        ...holdings,
        ...plan.rows.map((s) => ({
          id: `${Date.now()}-${s.symbol}`,
          symbol: s.symbol,
          buyDate,
          buyPrice: s.currentPrice,
          shares: s.shares,
          highestPriceSeen: s.currentPrice
        }))
      ];
      await fetch("/api/portfolio", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next)
      });
      window.dispatchEvent(new Event("portfolio:updated"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="panel investment-planner-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Buy Planner</p>
          <h2>日期金額試算</h2>
        </div>
        <button className="btn btn-primary" onClick={addToTracking} disabled={saving || !canEnter || !plan.rows.length}>
          {saving ? "加入中..." : "加入追蹤"}
        </button>
      </div>

      {!canEnter && (
        <div className="planner-warning">
          <strong>目前不適合進場</strong>
          <span>大盤濾網未通過，以下只作為觀察清單，不會建議買進或加入追蹤。</span>
        </div>
      )}

      <div className="planner-controls">
        <label>
          <span>買進日期</span>
          <input type="date" value={buyDate} onChange={(e) => setBuyDate(e.target.value)} />
        </label>
        <label>
          <span>可用金額</span>
          <input min="0" step="1000" type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <div>
          <span>{canEnter ? "預估投入" : "建議投入"}</span>
          <strong>{canEnter ? money(plan.used) : money(0)}</strong>
          <small>{canEnter ? `現金剩餘 ${money(plan.cashLeft)}` : "等待濾網轉強"}</small>
        </div>
      </div>

      {plan.rows.length ? (
        <div className="table-wrap planner-table">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>{canEnter ? "配置" : "觀察權重"}</th>
                <th>{canEnter ? "買進股數" : "暫不買進"}</th>
                <th>{canEnter ? "投入金額" : "觀察金額"}</th>
                <th>分數</th>
              </tr>
            </thead>
            <tbody>
              {plan.rows.map((s) => (
                <tr key={s.symbol}>
                  <td>
                    <strong>{s.symbol} {s.name}</strong>
                    <small>{s.industry}</small>
                  </td>
                  <td>
                    <span>{pct(s.weight)}</span>
                  </td>
                  <td>{canEnter ? s.shares : 0}</td>
                  <td>{canEnter ? money(s.notional) : "-"}</td>
                  <td>{pct(s.strategyScore, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">金額不足以買入目前分數最高且價格有效的標的。</div>
      )}
    </section>
  );
}
