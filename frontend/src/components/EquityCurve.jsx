import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import { equityData } from "../data/equityData";

const Plot = createPlotlyComponent(Plotly);

export default function EquityCurve() {
  const dates = equityData.points.map((point) => point.date);
  const strategy = equityData.points.map((point) => point.strategy);
  const benchmark = equityData.points.map((point) => point.benchmark);
  const drawdown = equityData.points.map((point) => -(point.drawdown || 0));

  return (
    <section className="panel equity-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Equity Curve</p>
          <h2>策略 vs 0050 十年資產曲線</h2>
        </div>
        <div className="rotation-meta">
          <span>{equityData.periodStart}</span>
          <strong>{equityData.periodEnd}</strong>
        </div>
      </div>
      <Plot
        data={[
          {
            x: dates,
            y: strategy,
            type: "scatter",
            mode: "lines",
            name: "策略",
            line: { color: "#2d6a4f", width: 3 },
            hovertemplate: "%{x}<br>策略：%{y:,.0f}<extra></extra>"
          },
          {
            x: dates,
            y: benchmark,
            type: "scatter",
            mode: "lines",
            name: "0050",
            line: { color: "#22577a", width: 2 },
            hovertemplate: "%{x}<br>0050：%{y:,.0f}<extra></extra>"
          },
          {
            x: dates,
            y: drawdown,
            type: "scatter",
            mode: "lines",
            name: "策略回撤",
            yaxis: "y2",
            line: { color: "#b42318", width: 1.5, dash: "dot" },
            hovertemplate: "%{x}<br>回撤：%{y:.2%}<extra></extra>"
          }
        ]}
        layout={{
          autosize: true,
          margin: { l: 72, r: 52, t: 10, b: 48 },
          paper_bgcolor: "#ffffff",
          plot_bgcolor: "#fbfcfe",
          hovermode: "x unified",
          legend: { orientation: "h", x: 0, y: 1.12 },
          xaxis: { gridcolor: "#e8edf3" },
          yaxis: { title: "資產淨值", gridcolor: "#e8edf3" },
          yaxis2: {
            title: "回撤",
            overlaying: "y",
            side: "right",
            tickformat: ".0%",
            range: [-0.6, 0.02],
            showgrid: false
          }
        }}
        config={{ responsive: true, displaylogo: false, scrollZoom: true }}
        useResizeHandler
        style={{ width: "100%", height: "430px" }}
      />
    </section>
  );
}
