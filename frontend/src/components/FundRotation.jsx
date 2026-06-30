import { useMemo, useState } from "react";
import { rotationData } from "../data/rotationData";

const STATUS = {
  all: { label: "全部", color: "#172033" },
  main: { label: "主力加速", color: "#2d6a4f" },
  rotation: { label: "輪動流入", color: "#22577a" },
  watch: { label: "觀望沉寂", color: "#7a8798" },
  outflow: { label: "資金退潮", color: "#b42318" }
};

const QUADRANTS = {
  steady: { label: "主流續強", tone: "positive", summary: "5日與20日同步流入，優先檢查策略分數與可買價格。" },
  turn: { label: "剛轉強", tone: "blue", summary: "短線法人翻多，但20日仍未確認，適合找早期輪動。" },
  warning: { label: "退潮警示", tone: "warning", summary: "中期還有資金，但短線轉賣超，避免追高。" },
  out: { label: "雙線流出", tone: "danger", summary: "短中期都偏流出，除非策略很強否則先降權重。" }
};

const QUADRANT_ORDER = ["steady", "turn", "warning", "out"];

const VIEW_OPTIONS = {
  matrix: "資金矩陣",
  quadrants: "四象限清單",
  ranking: "個股排名"
};

const RANK_OPTIONS = {
  buy5: "5日買超",
  sell5: "5日賣超",
  buy20: "20日買超",
  sell20: "20日賣超"
};

const fmt = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 });
const pct = (value, digits = 2) =>
  value === null || value === undefined ? "-" : `${(value * 100).toFixed(digits)}%`;
const score = (value) =>
  value === null || value === undefined ? "-" : (value * 100).toFixed(1);
const net = (value) => {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(1)} 萬張`;
  return `${sign}${fmt.format(abs)} 張`;
};
const price = (value) => (value === null || value === undefined ? "-" : Number(value).toFixed(2));

function formatFlow(foreign, trust) {
  if (foreign == null && trust == null) return "";
  const fText = foreign != null ? `外 ${foreign > 0 ? '+' : ''}${Math.round(foreign)}` : '';
  const tText = trust != null ? `投 ${trust > 0 ? '+' : ''}${Math.round(trust)}` : '';
  if (fText && tText) return `(${fText} / ${tText})`;
  return `(${fText || tText})`;
}

function quadrantOf(item) {
  const net5 = item.net5 || 0;
  const net20 = item.net20 || 0;
  if (net5 >= 0 && net20 >= 0) return "steady";
  if (net5 >= 0 && net20 < 0) return "turn";
  if (net5 < 0 && net20 >= 0) return "warning";
  return "out";
}

function cellTone(value) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function scoreTone(value) {
  if ((value || 0) >= 0.85) return "positive";
  if ((value || 0) >= 0.7) return "blue";
  return "neutral";
}

function topBy(items, selector, limit = 3) {
  return [...items].sort((a, b) => selector(b) - selector(a)).slice(0, limit);
}

function rankSectors(items) {
  return [...items].sort((a, b) => {
    const quadrantDelta = QUADRANT_ORDER.indexOf(quadrantOf(a)) - QUADRANT_ORDER.indexOf(quadrantOf(b));
    if (quadrantDelta !== 0) return quadrantDelta;
    const strengthA = (a.net5 || 0) + (a.net20 || 0) * 0.35 + (a.acceleration || 0) * 0.5;
    const strengthB = (b.net5 || 0) + (b.net20 || 0) * 0.35 + (b.acceleration || 0) * 0.5;
    return strengthB - strengthA;
  });
}

function SectorBrief({ sector }) {
  if (!sector) return null;
  const quadrant = QUADRANTS[quadrantOf(sector)];
  return (
    <aside className={`sector-brief sector-brief--${quadrant.tone}`}>
      <div className="sector-brief__head">
        <span className={`rotation-badge rotation-badge--${sector.status}`}>
          {sector.statusLabel}
        </span>
        <h3>{sector.name}</h3>
        <strong>{quadrant.label} · {sector.strategyVerdict}</strong>
        <p>{quadrant.summary}</p>
      </div>
      <dl>
        <div>
          <dt>法人 5 日</dt>
          <dd className={sector.net5 >= 0 ? "positive-text" : "negative-text"}>{net(sector.net5)}</dd>
        </div>
        <div>
          <dt>法人 20 日</dt>
          <dd className={sector.net20 >= 0 ? "positive-text" : "negative-text"}>{net(sector.net20)}</dd>
        </div>
        <div>
          <dt>策略權重</dt>
          <dd>{pct(sector.portfolioPct || 0, 1)}</dd>
        </div>
        <div>
          <dt>平均策略分數</dt>
          <dd>{score(sector.avgStrategyScore)}</dd>
        </div>
        <div>
          <dt>資金加速度</dt>
          <dd className={sector.acceleration >= 0 ? "positive-text" : "negative-text"}>{net(sector.acceleration)}</dd>
        </div>
        <div>
          <dt>入選檔數</dt>
          <dd>{sector.candidateCount}</dd>
        </div>
      </dl>
    </aside>
  );
}

function InsightCard({ label, value, detail, tone = "neutral" }) {
  return (
    <article className={`rotation-insight rotation-insight--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function FlowList({ stocks }) {
  return (
    <div className="flow-stock-list">
      {stocks.length ? (
        stocks.map((stock) => (
          <article className="flow-stock" key={stock.symbol}>
            <div className="flow-stock__title">
              <div>
                <strong>{stock.symbol}</strong>
                <span>{stock.name || "-"}</span>
              </div>
              {stock.isCandidate ? <em>策略入選 {score(stock.strategyScore)}</em> : <small>觀察</small>}
            </div>
            <div className="flow-stock__metrics">
              <span className={(stock.foreignNet + stock.trustNet) >= 0 ? "positive-text" : "negative-text"}>
                昨日 {net((stock.foreignNet || 0) + (stock.trustNet || 0))} {formatFlow(stock.foreignNet, stock.trustNet)}
              </span>
              <span className={stock.net5 >= 0 ? "positive-text" : "negative-text"}>
                5日 {net(stock.net5)}
              </span>
              <span className={stock.net20 >= 0 ? "positive-text" : "negative-text"}>
                20日 {net(stock.net20)}
              </span>
              <span>量能 {Number(stock.volumeRatio20 || 0).toFixed(2)}x</span>
              <span>{pct(stock.return5)}</span>
            </div>
          </article>
        ))
      ) : (
        <p className="rotation-empty">這個產業目前沒有足夠的個股資金資料。</p>
      )}
    </div>
  );
}

function FlowMatrix({ sectors, selectedName, onSelect }) {
  return (
    <div className="flow-matrix">
      <div className="flow-matrix__head">
        <div>
          <p className="eyebrow">Flow Heat Matrix</p>
          <h3>資金熱力矩陣</h3>
        </div>
        <small>點選產業後，右側會同步更新個股資金清單。</small>
      </div>
      <div className="flow-matrix__table">
        <table>
          <thead>
            <tr>
              <th>產業</th>
              <th>象限</th>
              <th>5日法人</th>
              <th>20日法人</th>
              <th>加速度</th>
              <th>策略分數</th>
              <th>候選</th>
              <th>權重</th>
            </tr>
          </thead>
          <tbody>
            {sectors.map((sector) => {
              const quadrantKey = quadrantOf(sector);
              const quadrant = QUADRANTS[quadrantKey];
              return (
                <tr
                  className={sector.name === selectedName ? "selected" : ""}
                  key={sector.name}
                  onClick={() => onSelect(sector.name)}
                >
                  <td>
                    <strong>{sector.name}</strong>
                    <small>{sector.statusLabel}</small>
                  </td>
                  <td>
                    <span className={`quadrant-pill quadrant-pill--${quadrant.tone}`}>{quadrant.label}</span>
                  </td>
                  <td className={`heat-cell heat-cell--${cellTone(sector.net5)}`}>{net(sector.net5)}</td>
                  <td className={`heat-cell heat-cell--${cellTone(sector.net20)}`}>{net(sector.net20)}</td>
                  <td className={`heat-cell heat-cell--${cellTone(sector.acceleration)}`}>{net(sector.acceleration)}</td>
                  <td className={`heat-cell heat-cell--${scoreTone(sector.avgStrategyScore)}`}>{score(sector.avgStrategyScore)}</td>
                  <td>{sector.candidateCount}</td>
                  <td>{pct(sector.portfolioPct || 0, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function QuadrantBoard({ groups, selectedName, onSelect }) {
  return (
    <div className="quadrant-board">
      {QUADRANT_ORDER.map((key) => (
        <article className={`quadrant-column quadrant-column--${QUADRANTS[key].tone}`} key={key}>
          <div className="quadrant-column__head">
            <strong>{QUADRANTS[key].label}</strong>
            <span>{groups[key].length} 產業</span>
          </div>
          <p>{QUADRANTS[key].summary}</p>
          <div className="quadrant-sector-list">
            {rankSectors(groups[key]).map((sector) => (
              <button
                className={sector.name === selectedName ? "active" : ""}
                key={sector.name}
                onClick={() => onSelect(sector.name)}
                type="button"
              >
                <span>{sector.name}</span>
                <small>
                  5日 {net(sector.net5)} / 20日 {net(sector.net20)}
                </small>
              </button>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

function StockRankingTable({ rows, mode }) {
  return (
    <div className="stock-ranking">
      <div className="stock-ranking__head">
        <div>
          <p className="eyebrow">Stock Flow Ranking</p>
          <h3>個股買賣超排名</h3>
        </div>
        <strong>{RANK_OPTIONS[mode]}</strong>
      </div>
      <div className="stock-ranking__table">
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>股票</th>
              <th>產業</th>
              <th>收盤價</th>
              <th>昨日法人</th>
              <th>區間淨額</th>
              <th>5日法人</th>
              <th>20日法人</th>
              <th>策略分數</th>
              <th>狀態</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((stock) => (
              <tr key={`${mode}-${stock.symbol}`}>
                <td>{stock.rank}</td>
                <td>
                  <strong>{stock.symbol}</strong>
                  <span>{stock.name || "-"}</span>
                </td>
                <td>{stock.industry || "-"}</td>
                <td>{price(stock.close)}</td>
                <td className={(stock.foreignNet + stock.trustNet) >= 0 ? "positive-text" : "negative-text"}>
                  {net((stock.foreignNet || 0) + (stock.trustNet || 0))} {formatFlow(stock.foreignNet, stock.trustNet)}
                </td>
                <td className={stock.periodNet >= 0 ? "positive-text" : "negative-text"}>{net(stock.periodNet)}</td>
                <td className={stock.net5 >= 0 ? "positive-text" : "negative-text"}>{net(stock.net5)}</td>
                <td className={stock.net20 >= 0 ? "positive-text" : "negative-text"}>{net(stock.net20)}</td>
                <td>{stock.strategyScore ? score(stock.strategyScore) : "-"}</td>
                <td>
                  {stock.isCandidate ? (
                    <em>策略入選</em>
                  ) : stock.portfolioPct > 0 ? (
                    <em>持股中</em>
                  ) : (
                    <small>觀察</small>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function FundRotation() {
  const firstSector = rotationData.sectors.find((item) => item.portfolioPct > 0)?.name || rotationData.sectors[0]?.name;
  const [viewMode, setViewMode] = useState("matrix");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedSector, setSelectedSector] = useState(firstSector);
  const [rankMode, setRankMode] = useState("buy5");

  const sectors = useMemo(() => {
    const base =
      statusFilter === "all"
        ? rotationData.sectors
        : rotationData.sectors.filter((item) => item.status === statusFilter);
    return rankSectors(base.length ? base : rotationData.sectors);
  }, [statusFilter]);

  const selected = rotationData.sectors.find((item) => item.name === selectedSector) || sectors[0];

  const stocks = useMemo(() => {
    return rotationData.stocks
      .filter((stock) => stock.industry === selected?.name)
      .sort((a, b) => {
        if (a.isCandidate !== b.isCandidate) return a.isCandidate ? -1 : 1;
        if ((a.strategyScore || 0) !== (b.strategyScore || 0)) return (b.strategyScore || 0) - (a.strategyScore || 0);
        return Math.abs(b.net5 || 0) - Math.abs(a.net5 || 0);
      })
      .slice(0, 8);
  }, [selected]);

  const rankingRows = rotationData.stockRankings?.[rankMode] || [];
  const quadrantGroups = useMemo(() => {
    return rotationData.sectors.reduce(
      (acc, sector) => {
        acc[quadrantOf(sector)].push(sector);
        return acc;
      },
      { steady: [], turn: [], warning: [], out: [] }
    );
  }, []);

  const strongest = topBy(rotationData.sectors, (item) => (item.net5 || 0) + (item.net20 || 0), 1)[0];
  const earlyTurns = topBy(quadrantGroups.turn, (item) => item.net5 || 0, 1)[0];
  const warnings = topBy(quadrantGroups.warning, (item) => Math.abs(item.net5 || 0), 1)[0];

  return (
    <section className="panel rotation-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Institutional Rotation</p>
          <h2>法人資金雷達</h2>
        </div>
        <div className="rotation-meta">
          <span>{rotationData.summary.sourceDate}</span>
          <strong>{rotationData.summary.sectorCount} 個產業</strong>
        </div>
      </div>

      <div className="rotation-insights">
        <InsightCard
          label="主流續強"
          value={`${quadrantGroups.steady.length} 產業`}
          detail={strongest ? `最強：${strongest.name} ${net(strongest.net5)}` : "目前沒有同步流入產業"}
          tone="positive"
        />
        <InsightCard
          label="剛轉強"
          value={`${quadrantGroups.turn.length} 產業`}
          detail={earlyTurns ? `短線轉強：${earlyTurns.name}` : "尚無明顯早期輪動"}
          tone="blue"
        />
        <InsightCard
          label="退潮警示"
          value={`${quadrantGroups.warning.length} 產業`}
          detail={warnings ? `短線轉弱：${warnings.name}` : "沒有短線退潮警示"}
          tone="warning"
        />
        <InsightCard
          label="策略重疊"
          value={`${rotationData.summary.candidateSectorCount} 產業`}
          detail="點選產業後看該產業個股與策略分數"
        />
      </div>

      <div className="rotation-toolbar">
        <label className="rotation-control rotation-control--primary">
          <span>查看方式</span>
          <select value={viewMode} onChange={(event) => setViewMode(event.target.value)}>
            {Object.entries(VIEW_OPTIONS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {viewMode !== "ranking" ? (
          <label className="rotation-control">
            <span>產業狀態</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              {Object.entries(STATUS).map(([key, item]) => (
                <option key={key} value={key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {viewMode === "ranking" ? (
          <label className="rotation-control">
            <span>排名類型</span>
            <select value={rankMode} onChange={(event) => setRankMode(event.target.value)}>
              {Object.entries(RANK_OPTIONS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label className="rotation-control">
            <span>定位產業</span>
            <select value={selected?.name || ""} onChange={(event) => setSelectedSector(event.target.value)}>
              {rotationData.sectors.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {viewMode === "ranking" ? (
        <StockRankingTable rows={rankingRows} mode={rankMode} />
      ) : (
        <div className="rotation-layout">
          {viewMode === "matrix" ? (
            <FlowMatrix sectors={sectors} selectedName={selected?.name} onSelect={setSelectedSector} />
          ) : (
            <QuadrantBoard groups={quadrantGroups} selectedName={selected?.name} onSelect={setSelectedSector} />
          )}
          <div className="rotation-side">
            <SectorBrief sector={selected} />
            <div className="rotation-source">
              <span>5日區間 {rotationData.summary.window5Start} - {rotationData.summary.sourceDate}</span>
              <span>20日區間 {rotationData.summary.window20Start} - {rotationData.summary.sourceDate}</span>
              <span>資料源 {rotationData.summary.institutionalSource}</span>
            </div>
            <FlowList stocks={stocks} />
          </div>
        </div>
      )}
    </section>
  );
}
