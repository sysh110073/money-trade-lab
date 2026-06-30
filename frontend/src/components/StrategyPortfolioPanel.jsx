import { useMemo } from "react";
import { dashboardData } from "../data/dashboardData";

const number = (value, digits = 2) =>
  value === null || value === undefined
    ? "-"
    : new Intl.NumberFormat("zh-TW", { maximumFractionDigits: digits }).format(value);

const money = (value) =>
  new Intl.NumberFormat("zh-TW", {
    style: "currency",
    currency: "TWD",
    maximumFractionDigits: 0
  }).format(value || 0);

const pct = (value, digits = 1) =>
  value === null || value === undefined ? "-" : `${(value * 100).toFixed(digits)}%`;

const exitReasonLabel = {
  replacement_switch: "汰弱換強",
  trailing_stop: "移動停損出場",
  stop_loss: "停損出場",
  take_profit: "停利出場",
  time_exit: "到期出場",
};

export default function StrategyPortfolioPanel() {
  const positions = dashboardData.openPositions || [];
  const tradeLog = dashboardData.tradeLog || [];

  const stats = useMemo(() => {
    let totalCost = 0;
    let totalValue = 0;
    
    positions.forEach(p => {
      const costBasis = p.entryPrice * p.shares;
      totalCost += costBasis;
      totalValue += p.marketValue;
    });

    const totalPnl = totalValue - totalCost;
    const totalRoi = totalCost > 0 ? totalPnl / totalCost : 0;

    return { totalCost, totalValue, totalPnl, totalRoi };
  }, [positions]);

  return (
    <section className="panel real-portfolio-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Strategy Portfolio (Forward Simulation)</p>
          <h2>策略理論持股追蹤 (100萬模擬盤)</h2>
        </div>
        <div className="portfolio-actions">
          <span className="eyebrow">自 2026/06/05 起以 100 萬模擬操作</span>
        </div>
      </div>

      <div className="metric-grid metric-grid--four">
        <article className="metric-card">
          <span>理論總投入成本</span>
          <strong>{money(stats.totalCost)}</strong>
        </article>
        <article className="metric-card">
          <span>理論目前總市值</span>
          <strong>{money(stats.totalValue)}</strong>
        </article>
        <article className={`metric-card ${stats.totalPnl >= 0 ? "metric-card--positive" : "metric-card--danger"}`}>
          <span>理論未實現損益</span>
          <strong>{stats.totalPnl >= 0 ? "+" : ""}{money(stats.totalPnl)}</strong>
        </article>
        <article className={`metric-card ${stats.totalRoi >= 0 ? "metric-card--positive" : "metric-card--danger"}`}>
          <span>理論報酬率</span>
          <strong>{stats.totalRoi >= 0 ? "+" : ""}{pct(stats.totalRoi)}</strong>
        </article>
      </div>

      <div className="section-heading" style={{ marginTop: "2rem" }}>
        <div>
          <p className="eyebrow">Action Plan</p>
          <h2>明日操作指引</h2>
        </div>
      </div>
      <div className="panel" style={{ background: "rgba(255, 255, 255, 0.02)", border: "1px solid rgba(255, 255, 255, 0.1)", padding: "1.5rem", borderRadius: "12px", marginBottom: "2rem" }}>
        <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 300px" }}>
            <h3 style={{ fontSize: "1.1rem", color: "#34d399", marginBottom: "1rem" }}>🟢 買入計畫 (可建立部位)</h3>
            {dashboardData.allocations.oddLot.rows.filter(r => r.executionStatus === "可買入").length > 0 ? (
              <ul style={{ margin: 0, paddingLeft: "1.2rem", color: "var(--text-secondary)", lineHeight: 1.6 }}>
                {dashboardData.allocations.oddLot.rows.filter(r => r.executionStatus === "可買入").map(r => (
                  <li key={r.symbol}>買入 <strong>{r.symbol} {r.name}</strong>，建議買點: {r.buyPrice}</li>
                ))}
              </ul>
            ) : (
              <p style={{ margin: 0, color: "var(--text-secondary)" }}>目前沒有買入計畫 (可能因為條件未達或資金/檔數已滿)</p>
            )}
          </div>
          <div style={{ flex: "1 1 300px" }}>
            <h3 style={{ fontSize: "1.1rem", color: "#f87171", marginBottom: "1rem" }}>🔴 賣出防守 (跌破即賣 50%)</h3>
            <ul style={{ margin: 0, paddingLeft: "1.2rem", color: "var(--text-secondary)", lineHeight: 1.6 }}>
              {positions.map(p => {
                const trailingActive = p.trailingStop > p.stopLoss;
                const stopPrice = trailingActive ? p.trailingStop : p.stopLoss;
                return (
                  <li key={p.symbol}>
                    {p.symbol} {p.name}：若盤中跌破 <strong>{number(stopPrice)}</strong> 即賣出
                    {trailingActive ? " (移動停利 50%)" : " (初始停損 100%)"}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </div>

      {positions.length > 0 ? (
        <div className="table-wrap portfolio-table holding-table">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>理論買入紀錄</th>
                <th>目前市價 / 市值</th>
                <th>損益 / 報酬率</th>
                <th>停損停利點位</th>
                <th>持有天數</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, idx) => {
                const trailingActive = p.trailingStop > p.stopLoss;
                const effectiveStop = trailingActive ? p.trailingStop : p.stopLoss;
                const distanceToStop = effectiveStop > 0 ? (p.currentPrice - effectiveStop) / p.currentPrice : 0;
                const takeProfit = p.entryPrice * 2.0;
                return (
                  <tr key={`${p.symbol}-${idx}`}>
                    <td>
                      <strong>{p.symbol} {p.name}</strong>
                      <small>{p.industry}</small>
                    </td>
                    <td>
                      <span>{number(p.entryPrice)}</span>
                      <small>{p.shares} 股 ({p.entryDate})</small>
                    </td>
                    <td>
                      <span>{number(p.currentPrice)}</span>
                      <small>{money(p.marketValue)}</small>
                    </td>
                    <td>
                      <span className={p.unrealizedPnl >= 0 ? "profit" : "risk"}>{p.unrealizedPnl >= 0 ? "+" : ""}{money(p.unrealizedPnl)}</span>
                      <small className={p.unrealizedReturn >= 0 ? "profit" : "risk"}>{p.unrealizedReturn >= 0 ? "+" : ""}{pct(p.unrealizedReturn)}</small>
                    </td>
                    <td>
                      <span className={`trade-status ${trailingActive ? 'trade-status--buy' : 'trade-status--wait'}`} style={{ marginBottom: "4px", display: "inline-block" }}>
                        {trailingActive ? "🔒 移動停利已啟動" : "⏳ 未達 +30% (初始防守)"}
                      </span>
                      <br/>
                      {trailingActive ? (
                        <span className="profit" style={{ fontWeight: 600 }}>
                          移動停利: {number(p.trailingStop)} <small style={{ color: "inherit", opacity: 0.8 }}>(跌破即賣)</small>
                        </span>
                      ) : (
                        <span className="risk">
                          初始停損: {number(p.stopLoss)} <small style={{ color: "inherit", opacity: 0.8 }}>({pct(-distanceToStop)} 空間)</small>
                        </span>
                      )}
                      <br/>
                      <span className="profit" style={{ marginTop: "2px", display: "block", opacity: 0.85 }}>
                        最終停利: {number(takeProfit)} (+100%)
                      </span>
                      {p.peakPrice > p.entryPrice && (
                        <small style={{ display: "block", marginTop: "2px", opacity: 0.7 }}>
                          歷史最高: {number(p.peakPrice)}
                        </small>
                      )}
                    </td>
                    <td>
                      <span>{p.holdingDays} 天</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">
          <p>目前策略沒有持有任何股票，全數為現金部位。</p>
        </div>
      )}

      {tradeLog.length > 0 && (
        <>
          <div className="section-heading" style={{ marginTop: "2rem" }}>
            <div>
              <p className="eyebrow">Trade History</p>
              <h2>策略交易紀錄 (含汰弱換強)</h2>
            </div>
          </div>
          <div className="table-wrap portfolio-table holding-table">
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>買入 → 賣出</th>
                  <th>價格</th>
                  <th>損益</th>
                  <th>出場原因</th>
                </tr>
              </thead>
              <tbody>
                {tradeLog.map((t, idx) => (
                  <tr key={`trade-${idx}`}>
                    <td>
                      <strong>{t.symbol} {t.name}</strong>
                    </td>
                    <td>
                      <span>{t.entryDate} → {t.exitDate}</span>
                      <small>{t.holdingDays} 天, {t.shares} 股</small>
                    </td>
                    <td>
                      <span>{number(t.entryPrice)} → {number(t.exitPrice)}</span>
                    </td>
                    <td>
                      <span className={t.netPnl >= 0 ? "profit" : "risk"}>
                        {t.netPnl >= 0 ? "+" : ""}{money(t.netPnl)}
                      </span>
                    </td>
                    <td>
                      <span className={`trade-status ${t.exitReason === 'replacement_switch' ? 'trade-status--hot' : t.win ? 'trade-status--buy' : 'trade-status--wait'}`}>
                        {exitReasonLabel[t.exitReason] || t.exitReason}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
