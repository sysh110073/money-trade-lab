import { useState, useEffect, useMemo, useRef } from "react";
import { stockSearchData } from "../data/stockSearchData";

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

export default function RealPortfolioPanel() {
  const [holdings, setHoldings] = useState([]);
  const [formOpen, setFormOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [formData, setFormData] = useState({
    id: null,
    symbol: "",
    buyDate: new Date().toISOString().split("T")[0],
    buyPrice: "",
    shares: "1000"
  });

  const loadData = async () => {
    try {
      const res = await fetch('/api/portfolio');
      if (res.ok) {
        const data = await res.json();
        setHoldings(data);
      }
    } catch (err) {
      console.error("Failed to load real portfolio from API", err);
    } finally {
      setLoading(false);
    }
  };

  const saveData = async (newHoldings) => {
    try {
      await fetch('/api/portfolio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newHoldings)
      });
      setHoldings(newHoldings);
    } catch (err) {
      console.error("Failed to save real portfolio", err);
      alert("儲存失敗：" + err.message);
    }
  };

  useEffect(() => {
    loadData();
    window.addEventListener("portfolio:updated", loadData);
    return () => window.removeEventListener("portfolio:updated", loadData);
  }, []);

  useEffect(() => {
    if (!holdings.length || loading) return;
    let updated = false;
    const newHoldings = holdings.map((h) => {
      const stock = stockSearchData.stocks.find((s) => s.symbol === h.symbol);
      if (stock && stock.currentPrice > (h.highestPriceSeen || h.buyPrice)) {
        updated = true;
        return { ...h, highestPriceSeen: stock.currentPrice };
      }
      return h;
    });
    if (updated) {
      saveData(newHoldings);
    }
  }, [holdings, loading]);

  const enrichedHoldings = useMemo(() => {
    return holdings.map((h) => {
      const stock = stockSearchData.stocks.find((s) => s.symbol === h.symbol);
      const currentPrice = stock ? stock.currentPrice : h.buyPrice;
      const marketValue = currentPrice * h.shares;
      const costBasis = h.buyPrice * h.shares;
      const pnl = marketValue - costBasis;
      const roi = costBasis > 0 ? pnl / costBasis : 0;
      
      const atr14 = stock ? stock.atr14 : (currentPrice * 0.05);
      const highestPriceSeen = Math.max(h.highestPriceSeen || h.buyPrice, currentPrice);
      
      const isTrailing = currentPrice >= h.buyPrice * 1.30;
      const stopPrice = isTrailing 
        ? highestPriceSeen - atr14 * 3.5 
        : h.buyPrice - atr14 * 5.0;
        
      const distanceToStop = stopPrice > 0 ? (currentPrice - stopPrice) / stopPrice : 0;

      return {
        ...h,
        name: stock ? stock.name : "未知",
        currentPrice,
        marketValue,
        costBasis,
        pnl,
        roi,
        atr14,
        highestPriceSeen,
        isTrailing,
        stopPrice,
        distanceToStop
      };
    }).sort((a, b) => b.marketValue - a.marketValue);
  }, [holdings]);

  const stats = useMemo(() => {
    const totalCost = enrichedHoldings.reduce((sum, h) => sum + h.costBasis, 0);
    const totalValue = enrichedHoldings.reduce((sum, h) => sum + h.marketValue, 0);
    const totalPnl = totalValue - totalCost;
    const totalRoi = totalCost > 0 ? totalPnl / totalCost : 0;
    return { totalCost, totalValue, totalPnl, totalRoi };
  }, [enrichedHoldings]);

  const handleSave = async (e) => {
    e.preventDefault();
    const newHolding = {
      id: formData.id || Date.now().toString(),
      symbol: formData.symbol.trim(),
      buyDate: formData.buyDate,
      buyPrice: parseFloat(formData.buyPrice),
      shares: parseInt(formData.shares, 10),
      highestPriceSeen: parseFloat(formData.buyPrice)
    };

    let newHoldings;
    if (formData.id) {
      newHoldings = holdings.map(h => h.id === formData.id ? { ...h, ...newHolding, highestPriceSeen: Math.max(h.highestPriceSeen, newHolding.buyPrice) } : h);
    } else {
      newHoldings = [...holdings, newHolding];
    }
    
    await saveData(newHoldings);
    setFormOpen(false);
  };

  const handleEdit = (h) => {
    setFormData({
      id: h.id,
      symbol: h.symbol,
      buyDate: h.buyDate,
      buyPrice: h.buyPrice,
      shares: h.shares
    });
    setFormOpen(true);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("確定要刪除這筆持股紀錄嗎？")) return;
    const newHoldings = holdings.filter(h => h.id !== id);
    await saveData(newHoldings);
  };

  const handleCostChange = async (holding, value) => {
    const buyPrice = parseFloat(value);
    if (!Number.isFinite(buyPrice) || buyPrice <= 0 || buyPrice === holding.buyPrice) return;
    const newHoldings = holdings.map((h) =>
      h.id === holding.id
        ? { ...h, buyPrice, highestPriceSeen: Math.max(h.highestPriceSeen || 0, buyPrice) }
        : h
    );
    await saveData(newHoldings);
  };

  const openNewForm = () => {
    setFormData({
      id: null,
      symbol: "",
      buyDate: new Date().toISOString().split("T")[0],
      buyPrice: "",
      shares: "1000"
    });
    setFormOpen(true);
  };

  if (loading) {
    return <section className="panel chart-loading">真實持股面板載入中...</section>;
  }

  return (
    <section className="panel real-portfolio-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Real Portfolio</p>
          <h2>我的真實持股追蹤</h2>
        </div>
        <div className="portfolio-actions">
          <button className="btn btn-primary" onClick={openNewForm}>+ 新增持股</button>
        </div>
      </div>

      <div className="metric-grid metric-grid--four">
        <article className="metric-card">
          <span>總投入成本</span>
          <strong>{money(stats.totalCost)}</strong>
        </article>
        <article className="metric-card">
          <span>目前總市值</span>
          <strong>{money(stats.totalValue)}</strong>
        </article>
        <article className={`metric-card ${stats.totalPnl >= 0 ? "metric-card--positive" : "metric-card--danger"}`}>
          <span>未實現損益</span>
          <strong>{stats.totalPnl >= 0 ? "+" : ""}{money(stats.totalPnl)}</strong>
        </article>
        <article className={`metric-card ${stats.totalRoi >= 0 ? "metric-card--positive" : "metric-card--danger"}`}>
          <span>真實報酬率</span>
          <strong>{stats.totalRoi >= 0 ? "+" : ""}{pct(stats.totalRoi)}</strong>
        </article>
      </div>

      {formOpen && (
        <form className="portfolio-form" onSubmit={handleSave}>
          <div className="form-row">
            <label>股票代號: <input required type="text" value={formData.symbol} onChange={(e) => setFormData({...formData, symbol: e.target.value})} placeholder="例如: 2330" /></label>
            <label>買入日期: <input required type="date" value={formData.buyDate} onChange={(e) => setFormData({...formData, buyDate: e.target.value})} /></label>
            <label>實際成本: <input required type="number" step="0.01" min="0" value={formData.buyPrice} onChange={(e) => setFormData({...formData, buyPrice: e.target.value})} /></label>
            <label>買入股數: <input required type="number" step="1" min="1" value={formData.shares} onChange={(e) => setFormData({...formData, shares: e.target.value})} /></label>
          </div>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary">儲存持股</button>
            <button type="button" className="btn btn-secondary" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </form>
      )}

      {enrichedHoldings.length > 0 ? (
        <div className="table-wrap portfolio-table holding-table">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>買入紀錄</th>
                <th>目前市價 / 市值</th>
                <th>損益 / 報酬率</th>
                <th>停損停利點位</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {enrichedHoldings.map((h) => {
                const takeProfit = h.buyPrice * 2.0;
                return (
                <tr key={h.id}>
                  <td>
                    <strong>{h.symbol} {h.name}</strong>
                  </td>
                  <td>
                    <input
                      className="cost-input"
                      defaultValue={h.buyPrice}
                      min="0"
                      step="0.01"
                      type="number"
                      onBlur={(e) => handleCostChange(h, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") e.currentTarget.blur();
                      }}
                    />
                    <small>{h.shares} 股 ({h.buyDate})</small>
                  </td>
                  <td>
                    <span>{number(h.currentPrice)}</span>
                    <small>{money(h.marketValue)}</small>
                  </td>
                  <td>
                    <span className={h.pnl >= 0 ? "profit" : "risk"}>{h.pnl >= 0 ? "+" : ""}{money(h.pnl)}</span>
                    <small className={h.roi >= 0 ? "profit" : "risk"}>{h.roi >= 0 ? "+" : ""}{pct(h.roi)}</small>
                  </td>
                  <td>
                    <span className={`trade-status ${h.isTrailing ? 'trade-status--buy' : 'trade-status--wait'}`} style={{ marginBottom: "4px", display: "inline-block" }}>
                      {h.isTrailing ? "🔒 移動停利已啟動" : "⏳ 未達 +30% (初始防守)"}
                    </span>
                    <br/>
                    {h.isTrailing ? (
                      <span className="profit" style={{ fontWeight: 600 }}>
                        移動停利: {number(h.stopPrice)} <small style={{ color: "inherit", opacity: 0.8 }}>(跌破即賣)</small>
                      </span>
                    ) : (
                      <span className="risk">
                        初始停損: {number(h.stopPrice)} <small style={{ color: "inherit", opacity: 0.8 }}>({pct(-h.distanceToStop)} 空間)</small>
                      </span>
                    )}
                    <br/>
                    <span className="profit" style={{ marginTop: "2px", display: "block", opacity: 0.85 }}>
                      最終停利: {number(takeProfit)} (+100%)
                    </span>
                    {h.highestPriceSeen > h.buyPrice && (
                      <small style={{ display: "block", marginTop: "2px", opacity: 0.7 }}>
                        歷史最高: {number(h.highestPriceSeen)}
                      </small>
                    )}
                  </td>
                  <td>
                    <button className="btn-link" onClick={() => handleEdit(h)}>編輯</button>
                    <button className="btn-link text-danger" onClick={() => handleDelete(h.id)}>刪除</button>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">
          <p>目前還沒有任何真實持股紀錄。請點擊「新增持股」開始追蹤您的實際投資組合。</p>
        </div>
      )}
    </section>
  );
}
