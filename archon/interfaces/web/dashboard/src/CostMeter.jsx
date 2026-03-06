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

  function CostMeter({ spent = 0, budget = 1, history = [] }) {
    const Recharts = window.Recharts || {};
    const percent = Math.max(0, Math.min(100, (spent / Math.max(0.000001, budget)) * 100));
    const color = bandColor(percent);
    const radius = 52;
    const stroke = 10;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (percent / 100) * circumference;
    const sparklineData = useMemo(
      () => history.slice(-20).map((item, idx) => ({ idx, spent: Number(item.spent || 0) })),
      [history],
    );

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
            {percent.toFixed(0)}%
          </text>
        </svg>
        <p>
          spent ${Number(spent || 0).toFixed(2)} of ${Number(budget || 0).toFixed(2)} budget
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
