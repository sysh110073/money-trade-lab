import { useMemo, useState } from "react";
import { rotationData } from "../data/rotationData";
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

const score = (value) => (value === null || value === undefined ? "-" : (value * 100).toFixed(1));

const net = (value) => {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(1)} 萬張`;
  return `${sign}${number(abs, 0)} 張`;
};

function toneClass(stock) {
  if (stock.executionTone) return stock.executionTone;
  if (stock.isCandidate) return "buy";
  return "watch";
}

function yahooQuoteUrl(symbol) {
  return `https://tw.stock.yahoo.com/quote/${symbol}.TW`;
}

function dispositionTone(stock) {
  return stock.disposition?.tone || "neutral";
}

const SCORE_FILTERS = [
  { label: "全部", value: 0 },
  { label: ">60", value: 60 },
  { label: ">70", value: 70 },
  { label: ">80", value: 80 },
  { label: ">90", value: 90 }
];

const sectorByName = new Map((rotationData.sectors || []).map((sector) => [sector.name, sector]));

function positiveTopThreshold(field, percentile = 0.2) {
  const positives = (stockSearchData.stocks || [])
    .map((item) => item[field] || 0)
    .filter((value) => value > 0)
    .sort((a, b) => b - a);
  if (!positives.length) return Number.POSITIVE_INFINITY;
  return positives[Math.max(0, Math.ceil(positives.length * percentile) - 1)];
}

const LATEST_FLOW_TOP_THRESHOLD = positiveTopThreshold("totalNet");
const FIVE_DAY_FLOW_TOP_THRESHOLD = positiveTopThreshold("totalNet5");

const CAPITAL_FILTERS = [
  {
    key: "latestBuy",
    label: "昨日法人買超",
    description: "最新交易日 totalNet > 0",
    group: "capital",
    test: (stock) => (stock.totalNet || 0) > 0
  },
  {
    key: "latestSurge",
    label: "昨日大量買超",
    description: "最新交易日買超前 20%",
    group: "capital",
    test: (stock) => (stock.totalNet || 0) >= LATEST_FLOW_TOP_THRESHOLD
  },
  {
    key: "fiveDayBuy",
    label: "5日法人買超",
    description: "近 5 日 totalNet5 > 0",
    group: "capital",
    test: (stock) => (stock.totalNet5 || 0) > 0
  },
  {
    key: "fiveDaySurge",
    label: "5日大量買超",
    description: "近 5 日買超前 20%",
    group: "capital",
    test: (stock) => (stock.totalNet5 || 0) >= FIVE_DAY_FLOW_TOP_THRESHOLD
  },
  {
    key: "sectorInflow",
    label: "產業5日流入",
    description: "所屬產業近 5 日法人淨流入",
    group: "capital",
    test: (stock) => (sectorByName.get(stock.industry)?.net5 || 0) > 0
  },
  {
    key: "sectorHot",
    label: "強勢資金產業",
    description: "產業狀態為主升或輪動流入",
    group: "capital",
    test: (stock) => {
      const sector = sectorByName.get(stock.industry);
      return Boolean(sector && sector.net5 > 0 && ["main", "rotation"].includes(sector.status));
    }
  },
  {
    key: "scoreDelta10",
    label: "分數日增 ≥10",
    description: "策略分數相較昨日增加 10 分(含)以上",
    group: "score",
    test: (stock) => (stock.scoreDelta || 0) >= 10
  },
  {
    key: "scoreDelta20",
    label: "分數日增 ≥20",
    description: "策略分數相較昨日增加 20 分(含)以上",
    group: "score",
    test: (stock) => (stock.scoreDelta || 0) >= 20
  },
  {
    key: "scoreDelta30",
    label: "分數日增 ≥30",
    description: "策略分數相較昨日增加 30 分(含)以上",
    group: "score",
    test: (stock) => (stock.scoreDelta || 0) >= 30
  }
];

function Metric({ label, value, sub, tone = "neutral" }) {
  return (
    <article className={`stock-search-metric stock-search-metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {sub ? <small>{sub}</small> : null}
    </article>
  );
}

function Detail({ label, value, tone }) {
  return (
    <div className={tone ? `stock-search-detail ${tone}` : "stock-search-detail"}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export default function StockSearchPanel() {
  const defaultStock =
    stockSearchData.stocks.find((item) => item.isHolding) ||
    stockSearchData.stocks.find((item) => item.isCandidate) ||
    stockSearchData.stocks[0];
  const [query, setQuery] = useState("");
  const [scoreFilter, setScoreFilter] = useState(0);
  const [flowLogic, setFlowLogic] = useState("or");
  const [activeFlowFilters, setActiveFlowFilters] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState(defaultStock?.symbol);

  const normalizedQuery = query.trim().toLowerCase();
  const matches = useMemo(() => {
    const source = stockSearchData.stocks || [];
    const passesScore = (item) => (item.strategyScore || 0) * 100 >= scoreFilter;
    const activeCapitalFilters = CAPITAL_FILTERS.filter((filter) => activeFlowFilters.includes(filter.key));
    const passesCapital = (item) => {
      if (!activeCapitalFilters.length) return true;
      const results = activeCapitalFilters.map((filter) => filter.test(item));
      return flowLogic === "and" ? results.every(Boolean) : results.some(Boolean);
    };
    if (!normalizedQuery) {
      const hasActiveFilters = scoreFilter > 0 || activeFlowFilters.length > 0;
      const base = hasActiveFilters ? source : source.filter((item) => item.isHolding || item.isCandidate);
      const filtered = base.filter((item) => passesScore(item) && passesCapital(item));
      return hasActiveFilters ? filtered : filtered.slice(0, 12);
    }
    return source
      .filter((item) => {
        const text = `${item.symbol} ${item.name || ""} ${item.industry || ""}`.toLowerCase();
        return text.includes(normalizedQuery) && passesScore(item) && passesCapital(item);
      });
  }, [activeFlowFilters, flowLogic, normalizedQuery, scoreFilter]);

  const hasActiveFilters = Boolean(normalizedQuery || scoreFilter > 0 || activeFlowFilters.length);

  const selected =
    matches.find((item) => item.symbol === selectedSymbol) ||
    matches[0] ||
    (hasActiveFilters ? null : defaultStock);

  const toggleFlowFilter = (key) => {
    setActiveFlowFilters((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key]
    );
  };

  const resetAll = () => {
    setQuery("");
    setScoreFilter(0);
    setActiveFlowFilters([]);
    setFlowLogic("or");
  };

  return (
    <section className="panel stock-search-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Stock Lookup</p>
          <h2>個股策略查詢</h2>
        </div>
        <strong>{stockSearchData.summary.sourceDate} / {stockSearchData.summary.stockCount} 檔</strong>
      </div>

      <div className="stock-search-layout">
        <aside className="stock-search-sidebar">
          <label className="stock-search-input">
            <span>輸入股票代號或名稱</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="例如 2330 / 台積電"
            />
          </label>
          <div className="stock-filter-panel">
            <div className="stock-filter-group">
              <div className="stock-filter-label">
                <span>策略分數</span>
                <small>品質門檻</small>
              </div>
              <div className="stock-score-filter" aria-label="策略分數篩選">
                {SCORE_FILTERS.map((item) => (
                  <button
                    className={scoreFilter === item.value ? "active" : ""}
                    key={item.value}
                    onClick={() => setScoreFilter(item.value)}
                    type="button"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="stock-filter-group">
              <div className="stock-filter-heading">
                <div className="stock-filter-label">
                  <span>篩選條件</span>
                  <small>資金訊號 / 分數變化</small>
                </div>
                <div className="stock-logic-toggle" aria-label="條件邏輯">
                  <button
                    className={flowLogic === "or" ? "active" : ""}
                    onClick={() => setFlowLogic("or")}
                    type="button"
                  >
                    任一符合
                  </button>
                  <button
                    className={flowLogic === "and" ? "active" : ""}
                    onClick={() => setFlowLogic("and")}
                    type="button"
                  >
                    全部符合
                  </button>
                </div>
              </div>
              <div className="stock-flow-filter stock-flow-filter--checkbox">
                {CAPITAL_FILTERS.map((item) => (
                  <label
                    className={`stock-checkbox ${activeFlowFilters.includes(item.key) ? "checked" : ""}`}
                    key={item.key}
                    title={item.description}
                  >
                    <input
                      checked={activeFlowFilters.includes(item.key)}
                      onChange={() => toggleFlowFilter(item.key)}
                      type="checkbox"
                    />
                    <span>{item.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <div className="stock-search-toolbar">
            <div className="stock-search-count">
              <span>{hasActiveFilters ? `找到 ${matches.length} 筆` : "目前持股與今日候選"}</span>
              <small>
                分數 {scoreFilter ? `>${scoreFilter}` : "全部"} / 條件{" "}
                {activeFlowFilters.length ? `${flowLogic === "and" ? "全部符合" : "任一符合"} ${activeFlowFilters.length} 項` : "不限"}
              </small>
              <small>策略候選 {stockSearchData.summary.candidateCount} 檔，持股 {stockSearchData.summary.holdingCount} 檔</small>
            </div>
            {hasActiveFilters ? (
              <button className="stock-reset-btn" onClick={resetAll} type="button">
                清除所有條件
              </button>
            ) : null}
          </div>
          <div className="stock-search-results">
            {matches.length ? (
              matches.map((stock) => (
                <button
                  className={stock.symbol === selected?.symbol ? "active" : ""}
                  key={stock.symbol}
                  onClick={() => setSelectedSymbol(stock.symbol)}
                  type="button"
                >
                  <span>
                    <strong>{stock.symbol}</strong>
                    {stock.name || "-"}
                  </span>
                  <small>
                    #{stock.rank} / {score(stock.strategyScore)}
                    {stock.scoreDelta != null ? ` (${stock.scoreDelta > 0 ? "+" : ""}${stock.scoreDelta.toFixed(0)})` : ""}
                    {stock.isHolding ? " / 持股" : stock.isCandidate ? " / 候選" : ""}
                    {stock.isDisposition ? " / 處置" : ""}
                  </small>
                </button>
              ))
            ) : (
              <p className="stock-search-empty">沒有找到符合的股票，請換代號或名稱。</p>
            )}
          </div>
        </aside>

        {selected ? (
          <article className="stock-search-card">
            <div className="stock-search-title">
              <div>
                <div className="stock-status-line">
                  <span className={`trade-status trade-status--${toneClass(selected)}`}>
                    {selected.executionStatus || (selected.isCandidate ? "今日候選" : "未入選")}
                  </span>
                  {selected.disposition ? (
                    <span className={`disposition-badge disposition-badge--${dispositionTone(selected)}`}>
                      {selected.disposition.label}
                    </span>
                  ) : null}
                </div>
                <h3>{selected.symbol} {selected.name || "-"}</h3>
                <p>{selected.industry || "-"} / {selected.signalTier || "no_signal"}</p>
                <a
                  className="stock-search-link"
                  href={yahooQuoteUrl(selected.symbol)}
                  rel="noreferrer"
                  target="_blank"
                >
                  Yahoo 個股資訊
                </a>
              </div>
              <div>
                <strong>{score(selected.strategyScore)}</strong>
                <small>策略分數</small>
              </div>
            </div>

            <div className="stock-search-metrics">
              <Metric label="策略排名" value={`#${selected.rank}`} sub="數字越小越前面" tone="positive" />
              <Metric
                label="策略分數"
                value={score(selected.strategyScore)}
                sub={selected.scoreDelta != null ? `昨日 ${score(selected.prevStrategyScore)} (${selected.scoreDelta > 0 ? "+" : ""}${selected.scoreDelta.toFixed(1)})` : "無昨日資料"}
                tone={selected.scoreDelta != null && selected.scoreDelta >= 20 ? "positive" : "neutral"}
              />
              <Metric label="現價" value={number(selected.currentPrice)} sub={`前收 ${number(selected.prevClose)}`} />
              <Metric
                label="法人昨日"
                value={net(selected.totalNet)}
                sub={`外資 ${net(selected.foreignNet)} / 投信 ${net(selected.trustNet)}`}
                tone={selected.totalNet >= 0 ? "positive" : "danger"}
              />
              <Metric
                label="法人 5 日"
                value={net(selected.totalNet5)}
                sub={`外資 ${net(selected.foreign5)} / 投信 ${net(selected.trust5)}`}
                tone={selected.totalNet5 >= 0 ? "positive" : "danger"}
              />
              <Metric
                label="部位"
                value={selected.isHolding ? pct(selected.portfolioPct) : selected.isCandidate ? "候選" : "未入選"}
                sub={selected.isHolding ? `${number(selected.shares, 0)} 股 / ${money(selected.notional)}` : "依訊號狀態決定"}
                tone={selected.isHolding ? "positive" : "neutral"}
              />
            </div>

            {selected.disposition ? (
              <div className={`disposition-card disposition-card--${dispositionTone(selected)}`}>
                <div>
                  <strong>{selected.disposition.label}</strong>
                  <span>
                    {selected.disposition.startDate || "-"} ~ {selected.disposition.endDate || "-"}
                  </span>
                </div>
                <p>{selected.disposition.reason || selected.disposition.condition || "官方處置資訊已公告。"}</p>
                {selected.disposition.measure ? <small>{selected.disposition.measure}</small> : null}
              </div>
            ) : null}

            <dl className="stock-search-details">
              <Detail label="買進參考" value={number(selected.buyPrice || selected.pullbackPrice)} />
              <Detail label="回調價" value={number(selected.pullbackPrice)} />
              <Detail label="停損" value={`${number(selected.stop)} (${pct(selected.stopPct)})`} tone="negative-text" />
              <Detail label="停利" value={`${number(selected.takeProfit)} (${pct(selected.takeProfitPct)})`} tone="positive-text" />
              <Detail label="MA5 / MA20" value={`${number(selected.ma5)} / ${number(selected.ma20)}`} />
              <Detail label="5日 / 10日報酬" value={`${pct(selected.return5)} / ${pct(selected.return10)}`} />
              <Detail label="量能 5日 / 20日" value={`${number(selected.volumeRatio5)}x / ${number(selected.volumeRatio20)}x`} />
              <Detail label="ADX / 52週位置" value={`${number(selected.adx14)} / ${pct(selected.position52w)}`} />
            </dl>

            <div className="stock-search-reasons">
              <div>
                <strong>策略判讀</strong>
                <p>{selected.actionLabel || "目前未進入今日買進清單，仍可追蹤分數與法人資金變化。"}</p>
              </div>
              <ul>
                {(selected.reasons || []).slice(0, 4).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>

            <div className="stock-search-factors">
              {(selected.explainability || []).slice(0, 5).map((item) => (
                <div key={item.factor}>
                  <span>{item.factor}</span>
                  <b>{pct(item.contribution, 0)}</b>
                  <i style={{ width: pct(item.contribution, 2) }} />
                </div>
              ))}
            </div>
          </article>
        ) : null}
      </div>
    </section>
  );
}
