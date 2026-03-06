(() => {
  const { useCallback, useRef, useState } = React;

  function nowSeconds() {
    return Date.now() / 1000;
  }

  function normalizeEvent(raw) {
    if (!raw || typeof raw !== "object") {
      return { type: "unknown", payload: raw };
    }
    if (raw.type === "event" && raw.payload && typeof raw.payload === "object") {
      return raw.payload;
    }
    if (raw.type === "result" && raw.payload && typeof raw.payload === "object") {
      return { type: "task_result", ...raw.payload };
    }
    return raw;
  }

  function resolveApiBase() {
    const stored = String(localStorage.getItem("archon.api_base") || "").trim();
    if (stored) {
      return stored.replace(/\/$/, "");
    }
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      return window.location.origin.replace(/\/$/, "");
    }
    return "http://127.0.0.1:8000";
  }

  function wsBaseUrl() {
    const base = resolveApiBase();
    if (base.startsWith("wss://") || base.startsWith("ws://")) {
      return base;
    }
    if (base.startsWith("https://")) {
      return `wss://${base.slice("https://".length)}`;
    }
    if (base.startsWith("http://")) {
      return `ws://${base.slice("http://".length)}`;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${base.replace(/^(https?:\/\/|wss?:\/\/)/, "")}`;
  }

  function toApprovalEvent(event) {
    const id = String(event.request_id || event.action_id || "").trim();
    if (!id) {
      return null;
    }
    return {
      ...event,
      action_id: id,
      request_id: id,
      timeout_s: Number(event.timeout_s || 120),
      created_at: Number(event.created_at || nowSeconds()),
    };
  }

  function patchCostState(previous, event) {
    if (!event || typeof event !== "object") {
      return previous;
    }
    if (event.type === "cost_update") {
      const spent = Number(event.spent ?? event.total_spent ?? previous.spent ?? 0);
      const budget = Number(event.budget ?? event.limit ?? previous.budget ?? 0);
      const nextPoint = { spent, budget, ts: nowSeconds() };
      return {
        spent,
        budget,
        history: [...previous.history, nextPoint].slice(-20),
      };
    }
    if (event.type === "task_completed" && event.budget && typeof event.budget === "object") {
      const spent = Number(event.budget.spent_usd ?? previous.spent ?? 0);
      const budget = Number(event.budget.limit_usd ?? previous.budget ?? 0);
      const nextPoint = { spent, budget, ts: nowSeconds() };
      return {
        spent,
        budget,
        history: [...previous.history, nextPoint].slice(-20),
      };
    }
    return previous;
  }

  function patchAgentStates(previous, event) {
    if (!event || typeof event !== "object") {
      return previous;
    }
    const next = { ...previous };
    if (event.type === "agent_start") {
      const name = String(event.agent || event.agent_name || "").trim();
      if (name) {
        next[name] = { status: "thinking", startedAt: Number(event.started_at || nowSeconds()) };
      }
      return next;
    }
    if (event.type === "agent_end" || event.type === "growth_agent_completed") {
      const name = String(event.agent || event.agent_name || "").trim();
      if (name) {
        next[name] = {
          status: String(event.status || "done").toLowerCase(),
          startedAt: Number(event.started_at || next[name]?.startedAt || nowSeconds()),
        };
      }
      return next;
    }
    if (event.type === "error") {
      const name = String(event.agent || event.agent_name || "").trim();
      if (name) {
        next[name] = { status: "error", startedAt: Number(next[name]?.startedAt || nowSeconds()) };
      }
      return next;
    }
    return next;
  }

  function useARCHON() {
    const wsRef = useRef(null);
    const queueRef = useRef([]);
    const connectRef = useRef({ sessionId: "", token: "" });
    const [status, setStatus] = useState("disconnected");
    const [lastEvent, setLastEvent] = useState(null);
    const [history, setHistory] = useState([]);
    const [pendingApprovals, setPendingApprovals] = useState([]);
    const [agentStates, setAgentStates] = useState({});
    const [costState, setCostState] = useState({ spent: 0, budget: 0, history: [] });

    const disconnect = useCallback(() => {
      if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
        wsRef.current.close(1000, "Client disconnect");
      }
      wsRef.current = null;
      setStatus("disconnected");
    }, []);

    const flushQueue = useCallback(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        return;
      }
      while (queueRef.current.length > 0) {
        const item = queueRef.current.shift();
        wsRef.current.send(JSON.stringify(item));
      }
    }, []);

    const connect = useCallback(
      (sessionId, token) => {
        const sid = String(sessionId || "").trim();
        const auth = String(token || "").trim();
        if (!sid || !auth) {
          setStatus("error");
          return;
        }
        connectRef.current = { sessionId: sid, token: auth };
        disconnect();
        setStatus("connecting");
        const url = `${wsBaseUrl()}/webchat/ws/${encodeURIComponent(sid)}?token=${encodeURIComponent(auth)}`;
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          setStatus("connected");
          flushQueue();
        };
        ws.onclose = () => {
          setStatus("disconnected");
        };
        ws.onerror = () => {
          setStatus("error");
        };
        ws.onmessage = (message) => {
          let parsed = null;
          try {
            parsed = JSON.parse(message.data);
          } catch (_err) {
            return;
          }
          const event = normalizeEvent(parsed);
          setLastEvent(event);
          setHistory((prev) => [...prev, event].slice(-500));
          setAgentStates((prev) => patchAgentStates(prev, event));
          setCostState((prev) => patchCostState(prev, event));
          if (event.type === "approval_required") {
            const approvalEvent = toApprovalEvent(event);
            if (approvalEvent) {
              setPendingApprovals((prev) => {
                const existing = prev.find((item) => item.action_id === approvalEvent.action_id);
                if (existing) {
                  return prev.map((item) => (item.action_id === approvalEvent.action_id ? approvalEvent : item));
                }
                return [...prev, approvalEvent];
              });
            }
          }
          if (event.type === "approval_result" || event.type === "approval_resolved") {
            const resolvedId = String(event.request_id || event.action_id || "").trim();
            if (resolvedId) {
              setPendingApprovals((prev) => prev.filter((item) => item.action_id !== resolvedId));
            }
          }
        };
      },
      [disconnect, flushQueue],
    );

    const send = useCallback(
      (message) => {
        if (!message || typeof message !== "object") {
          return;
        }
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          queueRef.current.push(message);
          if (
            status === "disconnected" &&
            connectRef.current.sessionId &&
            connectRef.current.token
          ) {
            connect(connectRef.current.sessionId, connectRef.current.token);
          }
          return;
        }
        wsRef.current.send(JSON.stringify(message));
      },
      [connect, status],
    );

    return {
      status,
      connect,
      disconnect,
      send,
      lastEvent,
      history,
      pendingApprovals,
      agentStates,
      costState,
    };
  }

  window.useARCHON = useARCHON;
})();
