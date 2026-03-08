import React, { useMemo, useState } from "react";

import { useArchonStream } from "./archonStream";

const ROLE_COLORS = {
  proposer: "#2563eb",
  critic: "#dc2626",
  factchecker: "#059669",
  synthesizer: "#7c3aed",
};

function roleColor(role) {
  const normalized = String(role || "").toLowerCase().replace(/\s+/g, "");
  return ROLE_COLORS[normalized] || "#334155";
}

export default function DebatePanel({
  rounds,
  confidence,
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
  const effectiveRounds = Array.isArray(rounds) ? rounds : liveStream.rounds;
  const displayedConfidence =
    typeof confidence === "number" ? confidence : Number(liveStream.confidence || 0);
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [showHistory, setShowHistory] = useState(true);

  const displayedRounds = useMemo(
    () => (showHistory ? effectiveRounds : effectiveRounds.slice(-1)),
    [effectiveRounds, showHistory],
  );

  const toggleRound = (roundId) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(roundId)) {
        next.delete(roundId);
      } else {
        next.add(roundId);
      }
      return next;
    });
  };

  return (
    <section className="debate-panel">
      <header className="debate-header">
        <h2>Debate Stream</h2>
        <button type="button" onClick={() => setShowHistory((value) => !value)}>
          {showHistory ? "Collapse Full History" : "Show Full History"}
        </button>
      </header>
      <div className="confidence-meter">
        <span>Confidence</span>
        <div className="confidence-track">
          <div
            className="confidence-fill"
            style={{ width: `${Math.max(0, Math.min(100, displayedConfidence))}%` }}
          />
        </div>
        <strong>{Math.round(displayedConfidence)}%</strong>
      </div>
      <div className="debate-rounds">
        {!displayedRounds.length ? <div className="empty-state">No debate rounds yet</div> : null}
        {displayedRounds.map((round, idx) => {
          const roundId = round.round_id || `${idx}-${round.agent || "agent"}`;
          const expanded = expandedIds.has(roundId);
          const color = roleColor(round.role || round.agent);
          return (
            <article key={roundId} className="debate-round">
              <button
                type="button"
                className="round-header"
                onClick={() => toggleRound(roundId)}
                style={{ borderLeft: `4px solid ${color}` }}
              >
                <span className="agent-badge" style={{ backgroundColor: color }}>
                  {round.role || round.agent || "Agent"}
                </span>
                <span>{expanded ? "Hide" : "Show"} round</span>
              </button>
              {expanded ? <pre className="round-content">{round.content || round.output || ""}</pre> : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
