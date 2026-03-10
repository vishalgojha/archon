(() => {
  const { useEffect, useMemo, useState } = React;

  function formatSeconds(seconds) {
    const clamped = Math.max(0, Math.floor(seconds));
    const mins = Math.floor(clamped / 60);
    const secs = clamped % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function normalizeWords(value) {
    return String(value || "")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function titleCase(value) {
    const text = normalizeWords(value);
    if (!text) {
      return "";
    }
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function compactText(value, maxLength = 180) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    if (text.length <= maxLength) {
      return text;
    }
    return `${text.slice(0, maxLength)}...`;
  }

  function stringifyPreview(value) {
    if (value == null) {
      return "";
    }
    if (typeof value === "string") {
      return compactText(value);
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    try {
      return compactText(JSON.stringify(value));
    } catch (_error) {
      return "";
    }
  }

  function pickPreview(item) {
    const context = item && typeof item.context === "object" ? item.context : {};
    const payload = item && typeof item.payload === "object" ? item.payload : {};
    const candidates = [
      context.reply,
      context.message,
      context.content,
      context.output_text,
      context.output,
      payload.reply,
      payload.message,
      payload.content,
      payload.output_text,
      payload.output,
      context.url ? `Target: ${context.url}` : "",
      payload.url ? `Target: ${payload.url}` : "",
    ];
    for (let idx = 0; idx < candidates.length; idx += 1) {
      const preview = stringifyPreview(candidates[idx]);
      if (preview) {
        return preview;
      }
    }
    return "";
  }

  function approvalHaystack(item) {
    const context = item && typeof item.context === "object" ? item.context : {};
    const payload = item && typeof item.payload === "object" ? item.payload : {};
    return [
      item?.action,
      item?.action_type,
      context?.action,
      context?.channel,
      context?.provider,
      context?.url,
      context?.agent,
      context?.step_id,
      payload?.action,
      payload?.channel,
      payload?.provider,
      payload?.url,
    ]
      .map((value) => normalizeWords(value).toLowerCase())
      .join(" ");
  }

  function buildApprovalDecisionCard(item) {
    const haystack = approvalHaystack(item);
    const preview = pickPreview(item);
    const provider = titleCase(item?.context?.provider || item?.payload?.provider || "");
    const actionLabel = titleCase(item?.action || item?.action_type || "this step");

    if (/(send|reply|message|email|webchat|sms|whatsapp|outreach)/.test(haystack)) {
      return {
        question: "Approve sending this reply?",
        impact: "This will send the drafted message outside ARCHON.",
        risk: "Medium risk: outbound messages cannot be quietly undone.",
        reason: "ARCHON drafted a response and paused for a human check before it sends it.",
        preview,
      };
    }

    if (/(publish|post|release|content|deliver|final result)/.test(haystack)) {
      return {
        question: "Approve publishing this result?",
        impact: "This will publish or share the result outside the current workflow.",
        risk: "Medium risk: released content may need manual correction later.",
        reason: "ARCHON believes the result is ready for release and wants human sign-off first.",
        preview,
      };
    }

    if (/(external api|external api call|openclaw|provider|gateway|http|url)/.test(haystack)) {
      return {
        question: `Approve this external ${provider ? `${provider} ` : ""}call?`,
        impact: "This will let ARCHON use an external service to continue the workflow.",
        risk: "Low to medium risk: the step reaches outside the local workflow boundary.",
        reason: "ARCHON needs one external call to complete the next step and paused for approval first.",
        preview,
      };
    }

    return {
      question: `Approve ${actionLabel ? actionLabel.toLowerCase() : "this step"}?`,
      impact: "This will let the workflow continue to the next step.",
      risk: "Low risk: this is a gated workflow decision.",
      reason: "ARCHON reached a step that requires a human decision before it can continue.",
      preview,
    };
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
      return <div className="approval-empty">No decisions are waiting.</div>;
    }

    return (
      <section className="approval-queue">
        {rows.map((item) => {
          const key = String(item.action_id || item.request_id || Math.random());
          const card = buildApprovalDecisionCard(item);
          return (
            <article key={key} className="approval-item">
              <h4 className="approval-question">{card.question}</h4>
              {card.preview ? <p className="approval-preview">{card.preview}</p> : null}
              <div className="approval-detail-grid">
                <div className="approval-detail">
                  <span className="approval-label">Impact</span>
                  <p>{card.impact}</p>
                </div>
                <div className="approval-detail">
                  <span className="approval-label">Risk</span>
                  <p>{card.risk}</p>
                </div>
                <div className="approval-detail">
                  <span className="approval-label">Reason</span>
                  <p>{card.reason}</p>
                </div>
              </div>
              <div className="approval-footer">
                <span>Decision expires in {formatSeconds(item.remaining)}</span>
                <div className="approval-footer-actions">
                  <button type="button" onClick={() => sendDecision("approve", item)}>
                    Approve
                  </button>
                  <button type="button" onClick={() => sendDecision("deny", item)}>
                    Not now
                  </button>
                </div>
              </div>
            </article>
          );
        })}
      </section>
    );
  }

  window.buildApprovalDecisionCard = buildApprovalDecisionCard;
  window.ApprovalQueue = ApprovalQueue;
})();
