(() => {
  const { useEffect, useMemo, useState } = React;

  function shortText(text) {
    const raw = String(text || "");
    if (raw.length <= 80) {
      return raw;
    }
    return `${raw.slice(0, 80)}...`;
  }

  function MemoryTimeline({ sessionId, apiBase = "", limit = 50 }) {
    const [entries, setEntries] = useState([]);
    const [expandedId, setExpandedId] = useState(null);

    useEffect(() => {
      if (!sessionId) {
        setEntries([]);
        setExpandedId(null);
        return undefined;
      }
      let cancelled = false;
      const urlBase = apiBase || window.location.origin;
      const url = `${urlBase.replace(/\/$/, "")}/memory/timeline?session_id=${encodeURIComponent(
        sessionId,
      )}&limit=${encodeURIComponent(limit)}`;
      fetch(url)
        .then((response) => response.json())
        .then((payload) => {
          if (cancelled) {
            return;
          }
          const data = Array.isArray(payload) ? payload : payload.entries || [];
          setEntries(Array.isArray(data) ? data : []);
        })
        .catch(() => {
          if (!cancelled) {
            setEntries([]);
          }
        });
      return () => {
        cancelled = true;
      };
    }, [sessionId, apiBase, limit]);

    const selected = useMemo(() => entries.find((entry) => entry.memory_id === expandedId), [entries, expandedId]);

    return (
      <section className="memory-timeline">
        {!sessionId || entries.length === 0 ? (
          <div className="empty-state">No memory entries yet</div>
        ) : (
          <div className="timeline-scroll">
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
                    <span key={link.chain_id || `${entry.memory_id}-${link.effect}`}>-&gt; {link.effect}</span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        )}
        {selected ? (
          <article className="memory-expanded">
            <h4>Memory Detail</h4>
            <p>{selected.content}</p>
            <h5>Causal Chain</h5>
            <ul>
              {(selected.causal_chain || []).map((row) => (
                <li key={row.chain_id || `${row.cause}-${row.effect}`}>
                  {row.cause} -&gt; {row.effect} ({Math.round((row.confidence || 0) * 100)}%)
                </li>
              ))}
            </ul>
          </article>
        ) : null}
      </section>
    );
  }

  window.MemoryTimeline = MemoryTimeline;
})();
