import React, { useEffect, useMemo, useState } from "react";

function shortText(text) {
  const raw = String(text || "");
  if (raw.length <= 80) {
    return raw;
  }
  return `${raw.slice(0, 80)}...`;
}

export default function MemoryTimeline({ sessionId, apiBase = "" }) {
  const [entries, setEntries] = useState([]);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const urlBase = apiBase || window.location.origin;
    const url = `${urlBase.replace(/\/$/, "")}/memory/timeline?session_id=${encodeURIComponent(
      sessionId,
    )}&limit=50`;
    fetch(url)
      .then((response) => response.json())
      .then((payload) => {
        if (cancelled) {
          return;
        }
        const data = Array.isArray(payload) ? payload : payload.entries || [];
        setEntries(data);
      })
      .catch(() => {
        if (!cancelled) {
          setEntries([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, apiBase]);

  const selected = useMemo(() => entries.find((entry) => entry.memory_id === expandedId), [entries, expandedId]);

  return (
    <section className="memory-timeline">
      <div className="timeline-scroll" style={{ display: "flex", overflowX: "auto", gap: "12px" }}>
        {entries.map((entry) => (
          <button
            type="button"
            key={entry.memory_id}
            className={`timeline-entry ${expandedId === entry.memory_id ? "active" : ""}`}
            onClick={() => setExpandedId(entry.memory_id)}
          >
            <time>{new Date((entry.timestamp || 0) * 1000).toLocaleTimeString()}</time>
            <span className="role-badge">{entry.role || "unknown"}</span>
            <p>{shortText(entry.content)}</p>
            <div className="causal-arrows">
              {(entry.causal_links || []).map((link) => (
                <span key={link.chain_id || `${entry.memory_id}-${link.effect}`}>→ {link.effect}</span>
              ))}
            </div>
          </button>
        ))}
      </div>
      {selected ? (
        <article className="memory-expanded">
          <h4>Memory Detail</h4>
          <p>{selected.content}</p>
          <h5>Causal Chain</h5>
          <ul>
            {(selected.causal_chain || []).map((row) => (
              <li key={row.chain_id || `${row.cause}-${row.effect}`}>
                {row.cause} → {row.effect} ({Math.round((row.confidence || 0) * 100)}%)
              </li>
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  );
}

