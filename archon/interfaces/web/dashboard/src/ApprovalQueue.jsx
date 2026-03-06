(() => {
  const { useEffect, useMemo, useState } = React;

  function formatSeconds(seconds) {
    const clamped = Math.max(0, Math.floor(seconds));
    const mins = Math.floor(clamped / 60);
    const secs = clamped % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function ApprovalQueue({ approvals = [], send }) {
    const [now, setNow] = useState(Date.now() / 1000);

    useEffect(() => {
      const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
      return () => clearInterval(timer);
    }, []);

    const rows = useMemo(
      () =>
        approvals.map((item) => {
          const timeout = Number(item.timeout_s || 0);
          const created = Number(item.created_at || now);
          const remaining = timeout > 0 ? Math.max(0, timeout - (now - created)) : 0;
          return { ...item, remaining };
        }),
      [approvals, now],
    );

    const sendDecision = (type, item) => {
      if (!send || typeof send !== "function") {
        return;
      }
      const requestId = String(item.request_id || item.action_id || "").trim();
      if (!requestId) {
        return;
      }
      send({ type, request_id: requestId, action_id: requestId });
    };

    if (!rows.length) {
      return <div className="approval-empty">No pending approvals</div>;
    }

    return (
      <section className="approval-queue">
        {rows.map((item) => {
          const key = String(item.action_id || item.request_id || Math.random());
          return (
            <article key={key} className="approval-item">
              <h4>{item.action || item.action_type || "approval_required"}</h4>
              <pre>{JSON.stringify(item.context || item.payload || {}, null, 2)}</pre>
              <div className="approval-footer">
                <span>Time left: {formatSeconds(item.remaining)}</span>
                <div>
                  <button type="button" onClick={() => sendDecision("approve", item)}>
                    Approve
                  </button>
                  <button type="button" onClick={() => sendDecision("deny", item)}>
                    Deny
                  </button>
                </div>
              </div>
            </article>
          );
        })}
      </section>
    );
  }

  window.ApprovalQueue = ApprovalQueue;
})();
