import { lazy, Suspense, useState } from "react";
import SentimentPanel from "./components/SentimentPanel";
import { dashboardData } from "./data/dashboardData";

const EquityCurve = lazy(() => import("./components/EquityCurve"));
const FundRotation = lazy(() => import("./components/FundRotation"));
const StockSearchPanel = lazy(() => import("./components/StockSearchPanel"));
const RealPortfolioPanel = lazy(() => import("./components/RealPortfolioPanel"));
const StrategyPortfolioPanel = lazy(() => import("./components/StrategyPortfolioPanel"));
const StrategyAttributionPanel = lazy(() => import("./components/StrategyAttributionPanel"));
const InvestmentPlannerPanel = lazy(() => import("./components/InvestmentPlannerPanel"));

const pct = (value, digits = 1) =>
  value === null || value === undefined ? "-" : `${(value * 100).toFixed(digits)}%`;
const money = (value) =>
  new Intl.NumberFormat("zh-TW", {
    style: "currency",
    currency: "TWD",
    maximumFractionDigits: 0
  }).format(value || 0);
const number = (value, digits = 2) =>
  new Intl.NumberFormat("zh-TW", { maximumFractionDigits: digits }).format(value || 0);

function Stars({ value }) {
  return <span className="stars">{"★".repeat(value)}{"☆".repeat(5 - value)}</span>;
}

function MetricCard({ label, value, subValue, tone = "neutral" }) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {subValue ? <small>{subValue}</small> : null}
    </article>
  );
}

function formatFlow(foreign, trust) {
  if (foreign == null && trust == null) return "";
  const fText = foreign != null ? `外 ${foreign > 0 ? '+' : ''}${Math.round(foreign)}` : '';
  const tText = trust != null ? `投 ${trust > 0 ? '+' : ''}${Math.round(trust)}` : '';
  if (fText && tText) return `(${fText} / ${tText})`;
  return `(${fText || tText})`;
}

function DecisionPanel({ data, allocation }) {
  const decision = data.decision;
  const summary = allocation.actionSummary || {};
  const buyNow = summary.buyNow || [];
  const waitPullback = summary.waitPullback || [];
  const avoidChasing = summary.avoidChasing || [];
  const primaryWeights = [...(data.weights || [])].sort((a, b) => b.value - a.value).slice(0, 3);
  return (
    <section className="command-center">
      <div className="command-main">
        <p className="eyebrow">Today Decision</p>
        <h1>今日策略狀態：{decision.state}</h1>
        <Stars value={decision.scoreStars} />
        <p>{decision.stance}，目前以 {allocation.label} 作為每日訊號預設配置。</p>
        <div className="strategy-context">
          <div className="strategy-context__group">
            <span>交易門檻</span>
            <div>
              {data.filters.map((filter) => {
                const ok = ["達標", "偏多", "可控"].includes(filter.status);
                return (
                  <b className={ok ? "ok" : "warn"} key={filter.label}>
                    {filter.label} {filter.status}
                  </b>
                );
              })}
            </div>
          </div>
          <div className="strategy-context__group">
            <span>主要權重</span>
            <div>
              {primaryWeights.map((item) => (
                <b key={item.key}>{item.label} {pct(item.value, 0)}</b>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function CapitalPanel({ allocation }) {
  const concentration = allocation.concentration;
  return (
    <aside className="panel capital-panel capital-panel--flat">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Capital</p>
          <h2>每日資金配置</h2>
        </div>
        <strong>{allocation.label}</strong>
      </div>
      <div className="capital-number">
        <span>資金使用率</span>
        <strong>{pct(allocation.utilization)}</strong>
      </div>
      <dl className="capital-stats">
        <div>
          <dt>投入</dt>
          <dd>{money(allocation.allocatedNotional)}</dd>
        </div>
        <div>
          <dt>現金</dt>
          <dd>{money(allocation.cashLeft)}</dd>
        </div>
        <div>
          <dt>最大單一持股</dt>
          <dd>{pct(concentration.maxPositionPct)}</dd>
        </div>
        <div>
          <dt>產業集中度</dt>
          <dd>{concentration.topSector} {pct(concentration.topSectorPct)}</dd>
        </div>
        <div>
          <dt>HHI</dt>
          <dd>{concentration.hhi.toFixed(3)}</dd>
        </div>
      </dl>
    </aside>
  );
}


export default function App() {
  const [orderMode, setOrderMode] = useState("oddLot");
  const [riskMode, setRiskMode] = useState("aggressive");
  const data = dashboardData;
  const strategy = data[riskMode];
  const allocation = data.allocations[orderMode];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Quant Fund Dashboard</p>
          <h1>{data.strategyName}</h1>
        </div>
        <div className="topbar__meta">
          <span className="status-pill status-pill--blue">資料日 {data.dataDate}</span>
          <span className="status-pill status-pill--amber">{data.marketLabel}</span>
          <span className="status-pill status-pill--green">收盤訊號</span>
          <span className="status-pill status-pill--red">風險 {data.decision.riskLevel}</span>
        </div>
      </header>

      <DecisionPanel data={data} allocation={allocation} />

      <Suspense fallback={<section className="panel chart-loading">日期金額試算載入中...</section>}>
        <InvestmentPlannerPanel />
      </Suspense>

      <Suspense fallback={<section className="panel chart-loading">策略理論持股面板載入中...</section>}>
        <StrategyPortfolioPanel />
      </Suspense>

      <Suspense fallback={<section className="panel chart-loading">Strategy attribution loading...</section>}>
        <StrategyAttributionPanel />
      </Suspense>

      <Suspense fallback={<section className="panel chart-loading">真實持股面板載入中...</section>}>
        <RealPortfolioPanel />
      </Suspense>

      <Suspense fallback={<section className="panel chart-loading">個股策略查詢載入中...</section>}>
        <StockSearchPanel />
      </Suspense>

      <CapitalPanel allocation={allocation} />
    </main>
  );
}
