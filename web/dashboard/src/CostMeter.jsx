import React, { useMemo } from "react";
import { LineChart, Line, ResponsiveContainer } from "recharts";

import { useArchonStream } from "./archonStream";

function bandColor(percent) {
  if (percent > 80) {
    return "#dc2626";
  }
  if (percent >= 60) {
    return "#ca8a04";
  }
  return "#16a34a";
}

export default function CostMeter({
  spent,
  budget,
  history,
  stream,
  sessionId = "",
  token = "",
  apiBase = "",
  wsBase = "",
  transport = "webchat",
}) {
  const liveStream =
    stream ||
    useArchonStream({
      sessionId,
      token,
      apiBase,
      wsBase,
      transport,
    });
  const numericSpent =
    typeof spent === "number" ? spent : Number(liveStream.costState.spent || 0);
  const numericBudget =
    typeof budget === "number" ? budget : Number(liveStream.costState.budget || 0);
  const effectiveHistory = Array.isArray(history) ? history : liveStream.costState.history;
  const percent = Math.max(
    0,
    Math.min(100, (numericSpent / Math.max(0.000001, numericBudget || 1)) * 100),
  );
  const color = bandColor(percent);
  const radius = 52;
  const stroke = 10;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percent / 100) * circumference;
  const sparklineData = useMemo(
    () =>
      effectiveHistory
        .slice(-20)
        .map((item, idx) => ({ idx, spent: Number(item.spent || 0) })),
    [effectiveHistory],
  );

  return (
    <section className="cost-meter">
      <svg width="160" height="160" viewBox="0 0 160 160" role="img" aria-label="Budget gauge">
        <circle cx="80" cy="80" r={radius} stroke="#e2e8f0" strokeWidth={stroke} fill="none" />
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
        spent ${numericSpent.toFixed(2)} of ${numericBudget.toFixed(2)} budget
      </p>
      <div style={{ width: "220px", height: "60px" }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={sparklineData}>
            <Line type="monotone" dataKey="spent" stroke={color} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
