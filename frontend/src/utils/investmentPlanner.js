const SETTINGS = {
  maxPositions: 8,
  maxPositionPct: 0.2,
  maxRiskPerTrade: 0.02,
  atrStopMultiplier: 5,
  targetExposure: 1
};

export function planPurchases(stocks, amount, maxPositions = SETTINGS.maxPositions) {
  const budget = Number(amount) || 0;
  if (budget <= 0) return { rows: [], used: 0, cashLeft: budget };

  let cash = budget;
  let invested = 0;
  const rows = stocks
    .filter((s) => s.currentPrice > 0 && s.atr14 > 0 && s.strategyScore != null && !s.isDisposition)
    .sort((a, b) => b.strategyScore - a.strategyScore || (b.scoreDelta || 0) - (a.scoreDelta || 0))
    .slice(0, maxPositions)
    .map((s) => {
      const remainingTarget = Math.max(0, budget * SETTINGS.targetExposure - invested);
      const riskShares = (budget * SETTINGS.maxRiskPerTrade) / (s.atr14 * SETTINGS.atrStopMultiplier);
      const desiredNotional = Math.min(
        riskShares * s.currentPrice,
        budget * SETTINGS.maxPositionPct,
        remainingTarget,
        cash
      );
      const shares = Math.floor(desiredNotional / s.currentPrice);
      const notional = shares * s.currentPrice;
      if (shares > 0) {
        cash -= notional;
        invested += notional;
      }
      return { ...s, weight: budget > 0 ? notional / budget : 0, shares, notional };
    })
    .filter((s) => s.shares > 0);

  return { rows, used: invested, cashLeft: budget - invested };
}

if (typeof process !== "undefined" && import.meta.url === `file://${process.argv[1]}`) {
  const plan = planPurchases(
    [
      { symbol: "A", currentPrice: 100, strategyScore: 0.9, scoreDelta: 1 },
      { symbol: "B", currentPrice: 50, strategyScore: 0.6, scoreDelta: 0 },
      { symbol: "C", currentPrice: 2000, strategyScore: 1, scoreDelta: 0 }
    ].map((stock) => ({ ...stock, atr14: 10 })),
    1000,
    2
  );
  console.assert(plan.rows.length === 2, "keeps affordable top picks");
  console.assert(plan.used <= 1000, "never spends more than budget");
  console.assert(plan.rows[0].shares === 2, "uses risk-parity sizing");
}
