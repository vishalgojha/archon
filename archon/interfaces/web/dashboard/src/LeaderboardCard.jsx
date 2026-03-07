(() => {
  function widthForScore(score) {
    const value = Number(score || 0);
    return `${Math.max(8, Math.min(100, value))}%`;
  }

  function formatCost(value) {
    return `$${Number(value || 0).toFixed(3)}`;
  }

  function LeaderboardCard({ rows, loading, scope }) {
    if (loading) {
      return <div className="empty-state">Loading {scope} benchmark...</div>;
    }

    if (!Array.isArray(rows) || rows.length === 0) {
      return <div className="empty-state">No benchmark data recorded yet.</div>;
    }

    return (
      <div className="leaderboard-list">
        {rows.map((row, index) => (
          <article className="leaderboard-item" key={`${String(row.tenant || "tenant")}-${String(row.agent || "agent")}-${index}`}>
            <div className="leaderboard-rank">#{index + 1}</div>
            <div className="leaderboard-main">
              <div className="leaderboard-line">
                <strong>{String(row.agent || "Unknown Agent")}</strong>
                <span className="leaderboard-tenant">{String(row.tenant || "tenant")}</span>
              </div>
              <div className="leaderboard-meta">
                <span>{String(row.mode || "unknown")}</span>
                <span>{Number(row.sample_size || 0)} runs</span>
                <span>{formatCost(row.avg_cost_usd)}</span>
              </div>
              <div className="leaderboard-score">
                <div className="leaderboard-track">
                  <div className="leaderboard-fill" style={{ width: widthForScore(row.score) }} />
                </div>
                <span>{Number(row.score || 0).toFixed(1)}</span>
              </div>
            </div>
          </article>
        ))}
      </div>
    );
  }

  window.LeaderboardCard = LeaderboardCard;
})();
