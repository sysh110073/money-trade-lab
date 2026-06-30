import { sentimentData } from "../data/sentimentData";

const pct = (value, digits = 1) => `${(value * 100).toFixed(digits)}%`;
const signedScore = (value) => {
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}`;
};
const sentimentScore = (value) => (value == null ? "未納入" : `${value.toFixed(0)}/100`);

function SentimentBadge({ label }) {
  const tone = label === "positive" ? "positive" : label === "negative" ? "negative" : "neutral";
  const text = label === "positive" ? "偏多" : label === "negative" ? "偏空" : "中性";
  return <span className={`sentiment-badge sentiment-badge--${tone}`}>{text}</span>;
}

function SourceCard({ source }) {
  const statusOk = source.status === "ok";
  return (
    <article className="sentiment-source">
      <div>
        <strong>{source.name}</strong>
        <span className={statusOk ? "positive-text" : "negative-text"}>{source.status}</span>
      </div>
      <b>{signedScore(source.score)}</b>
      <small>
        {source.count} 則，偏多 {source.positiveCount} / 偏空 {source.negativeCount}
      </small>
    </article>
  );
}

function ComponentRow({ component }) {
  const score = component.score ?? 0;
  const unavailable = component.score == null;
  return (
    <article className={unavailable ? "sentiment-component sentiment-component--off" : "sentiment-component"}>
      <div>
        <strong>{component.name}</strong>
        <span>{component.weight}%</span>
      </div>
      <div className="sentiment-component__bar" aria-hidden="true">
        <i style={{ width: `${score}%` }} />
      </div>
      <small>
        {sentimentScore(component.score)} · {component.state} · {component.status}
      </small>
    </article>
  );
}

function SourceSummaries() {
  return (
    <div className="source-summary-grid">
      {sentimentData.sourceSummaries.map((source) => (
        <article className="source-summary-item" key={source.name}>
          <div>
            <span>{source.category}</span>
            <strong>{source.name}</strong>
          </div>
          <b>{source.value}</b>
          <em>{source.state}</em>
          <p>{source.summary}</p>
        </article>
      ))}
    </div>
  );
}

export default function SentimentPanel() {
  const summary = sentimentData.summary;
  const market = sentimentData.marketSentiment;
  const topItems = sentimentData.items.slice(0, 10);
  const marker = market.score == null ? 50 : market.score;

  return (
    <section className="panel sentiment-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Market Sentiment Score</p>
          <h2>新聞、社群與資金情緒</h2>
        </div>
        <div className="rotation-meta">
          <span>{summary.model}</span>
          <strong>{summary.itemCount} 則訊號</strong>
        </div>
      </div>

      <div className="sentiment-layout sentiment-layout--score">
        <div className="sentiment-summary sentiment-summary--market">
          <span>市場情緒分數</span>
          <strong>{sentimentScore(market.score)}</strong>
          <div className="sentiment-scorebar" aria-hidden="true">
            <i style={{ left: `${marker}%` }} />
          </div>
          <dl>
            <div>
              <dt>狀態</dt>
              <dd>{market.state}</dd>
            </div>
            <div>
              <dt>建議</dt>
              <dd>{market.advice}</dd>
            </div>
            <div>
              <dt>風險</dt>
              <dd>{market.risk}</dd>
            </div>
          </dl>
          <small>可用權重 {market.activeWeight}%；缺資料來源不會用替代資料補分。</small>
        </div>

        <div className="sentiment-components">
          {market.components.map((component) => (
            <ComponentRow component={component} key={component.key} />
          ))}
        </div>
      </div>

      <div className="sentiment-layout">
        <div className="sentiment-summary">
          <span>新聞與社群文字情緒</span>
          <strong>{summary.state}</strong>
          <div className="sentiment-scorebar" aria-hidden="true">
            <i style={{ left: `${Math.max(0, Math.min(100, (summary.score + 1) * 50))}%` }} />
          </div>
          <small>
            文字分數 {signedScore(summary.score)}，信心 {pct(summary.confidence)}
          </small>
          <dl>
            <div>
              <dt>偏多</dt>
              <dd>{summary.positiveCount}</dd>
            </div>
            <div>
              <dt>中性</dt>
              <dd>{summary.neutralCount}</dd>
            </div>
            <div>
              <dt>偏空</dt>
              <dd>{summary.negativeCount}</dd>
            </div>
          </dl>
        </div>

        <div className="sentiment-sources">
          {sentimentData.sources.map((source) => (
            <SourceCard source={source} key={source.name} />
          ))}
        </div>
      </div>

      <div className="sentiment-grid">
        <div className="sentiment-list">
          {topItems.map((item) => (
            <a className="sentiment-item" href={item.url || "#"} key={`${item.source}-${item.title}`} target="_blank" rel="noreferrer">
              <div>
                <strong>{item.title}</strong>
                <span>
                  {item.source} · {item.method}
                </span>
              </div>
              <SentimentBadge label={item.label} />
            </a>
          ))}
        </div>
        <div>
          <SourceSummaries />
        </div>
      </div>
    </section>
  );
}
