(() => {
  const { useMemo } = React;

  function bandColor(percent) {
    if (percent > 80) {
      return "#dc2626";
    }
    if (percent >= 60) {
      return "#ca8a04";
    }
    return "#16a34a";
  }

  function CostMeter({ spent = 0, budget = 0, history = [] }) {
    const Recharts = window.Recharts || {};
    const numericSpent = Number(spent || 0);
    const numericBudget = Number(budget || 0);
    const hasData = history.length > 0 || numericSpent > 0 || numericBudget > 0;
    const percent = hasData
      ? Math.max(0, Math.min(100, (numericSpent / Math.max(0.000001, numericBudget)) * 100))
      : null;
    const safePercent = percent ?? 0;
    const color = bandColor(percent ?? 0);
    const radius = 52;
    const stroke = 10;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (safePercent / 100) * circumference;
    const sparklineData = useMemo(
      () => history.slice(-20).map((item, idx) => ({ idx, spent: Number(item.spent || 0) })),
      [history],
    );

    if (!hasData) {
      return (
        <section className="cost-meter">
          <div className="empty-state">No cost data yet</div>
        </section>
      );
    }

    return (
      <section className="cost-meter">
        <svg width="160" height="160" viewBox="0 0 160 160" role="img" aria-label="Budget gauge">
          <circle cx="80" cy="80" r={radius} stroke="#233042" strokeWidth={stroke} fill="none" />
          <circle
            cx="80"
            cy="80"
            r={radius}
            stroke={color}
            strokeWidth={stroke}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            transform="rotate(-90 80 80)"
          />
          <text x="80" y="86" textAnchor="middle" fontSize="20" fill={color}>
            {safePercent.toFixed(0)}%
          </text>
        </svg>
        <p>
          spent ${numericSpent.toFixed(2)} of ${numericBudget.toFixed(2)} budget
        </p>
        {Recharts.LineChart && Recharts.Line && Recharts.ResponsiveContainer ? (
          <div style={{ width: "220px", height: "60px" }}>
            <Recharts.ResponsiveContainer width="100%" height="100%">
              <Recharts.LineChart data={sparklineData}>
                <Recharts.Line type="monotone" dataKey="spent" stroke={color} strokeWidth={2} dot={false} />
              </Recharts.LineChart>
            </Recharts.ResponsiveContainer>
          </div>
        ) : (
          <p style={{ fontSize: "11px" }}>Sparkline unavailable (Recharts not loaded)</p>
        )}
      </section>
    );
  }

  window.CostMeter = CostMeter;
})();
