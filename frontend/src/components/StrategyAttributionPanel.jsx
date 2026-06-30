import { attributionData } from "../data/attributionData";

const pct = (value, digits = 1) =>
  value === null || value === undefined ? "-" : `${(value * 100).toFixed(digits)}%`;

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

const gateLabel = {
  signal_rank_gate: "Rank",
  signal_score_gate: "Score",
  signal_regime_gate: "Regime",
  signal_breadth_gate: "Breadth",
  signal_positive_return_gate: "5D Market",
  signal_volatility_gate: "Volatility",
  signal_overheat_gate: "Overheat",
  signal_market_gate: "Market Gate"
};

export default function StrategyAttributionPanel() {
  const data = attributionData;
  const tca = data.tca || {};
  const diagnostics = data.signalDiagnostics || {};
  const gates = data.latestGateRows?.length ? data.latestGateRows : data.gateRows || [];
  const weights = Object.entries(data.weights || {}).sort((a, b) => b[1] - a[1]);
  const exits = data.exitReasons || [];

  return (
    <section className="panel attribution-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Strategy Attribution</p>
          <h2>Signal gates, cost, and exits</h2>
        </div>
        <strong>{data.runContext?.strategyVersion || "production"}</strong>
      </div>

      <div className="metric-grid metric-grid--four">
        <article className="metric-card">
          <span>CAGR</span>
          <strong>{pct(data.performance?.cagr)}</strong>
          <small>0050 {pct(data.benchmark?.cagr)}</small>
        </article>
        <article className="metric-card">
          <span>Sharpe</span>
          <strong>{number(data.performance?.sharpe)}</strong>
          <small>benchmark {number(data.benchmark?.sharpe)}</small>
        </article>
        <article className="metric-card">
          <span>Trading Cost</span>
          <strong>{money(tca.total_cost)}</strong>
          <small>entry {money(tca.entry_cost)} / exit {money(tca.exit_cost)}</small>
        </article>
        <article className="metric-card">
          <span>Replacement Net</span>
          <strong>{money(tca.replacement_switch_net_pnl)}</strong>
          <small>{number(tca.replacement_cost_gate_rejections, 0)} cost-gate rejects</small>
        </article>
      </div>

      <div className="attribution-grid">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Gate</th>
                <th>Passed</th>
                <th>Rate</th>
              </tr>
            </thead>
            <tbody>
              {gates.map((gate) => (
                <tr key={gate.key}>
                  <td>{gateLabel[gate.key] || gate.key}</td>
                  <td>{number(gate.passed, 0)} / {number(gate.total, 0)}</td>
                  <td>{pct(gate.rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="attribution-side">
          <div>
            <h3>Factor Weights</h3>
            {weights.map(([key, value]) => (
              <p key={key}><span>{key}</span><strong>{pct(value, 0)}</strong></p>
            ))}
          </div>
          <div>
            <h3>Exit Reasons</h3>
            {exits.slice(0, 6).map((item) => (
              <p key={item.reason}><span>{item.reason || "unknown"}</span><strong>{number(item.count, 0)}</strong></p>
            ))}
          </div>
          <div>
            <h3>No Signal Diagnosis</h3>
            <p><span>Primary blocker</span><strong>{diagnostics.no_entry_primary_blocker || "-"}</strong></p>
            <p><span>Entry signals</span><strong>{number(diagnostics.entry_signals, 0)}</strong></p>
          </div>
        </div>
      </div>
    </section>
  );
}
