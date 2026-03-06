import React, { useEffect, useMemo, useState } from "react";

function formatSeconds(seconds) {
  const clamped = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(clamped / 60);
  const secs = clamped % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export default function ApprovalQueue({ ws, approvals = [] }) {
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

  const sendDecision = (type, actionId) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return;
    }
    ws.send(JSON.stringify({ type, action_id: actionId }));
  };

  if (!rows.length) {
    return <div className="approval-empty">No pending approvals</div>;
  }

  return (
    <section className="approval-queue">
      {rows.map((item) => (
        <article key={item.action_id} className="approval-item">
          <h4>{item.action || item.action_type || "action"}</h4>
          <pre>{JSON.stringify(item.context || {}, null, 2)}</pre>
          <div className="approval-footer">
            <span>Time left: {formatSeconds(item.remaining)}</span>
            <div>
              <button type="button" onClick={() => sendDecision("approve", item.action_id)}>
                Approve
              </button>
              <button type="button" onClick={() => sendDecision("deny", item.action_id)}>
                Deny
              </button>
            </div>
          </div>
        </article>
      ))}
    </section>
  );
}

