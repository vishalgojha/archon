(() => {
  const { useCallback, useRef, useState } = React;
  const EMPTY_SESSION = { sessionId: "", token: "" };

  function nowSeconds() {
    return Date.now() / 1000;
  }

  function safeStorageGet(key) {
    try {
      return localStorage.getItem(key) || "";
    } catch (_error) {
      return "";
    }
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
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      return window.location.origin.replace(/\/$/, "");
    }
    const stored = String(safeStorageGet("archon.api_base") || "").trim();
    if (stored) {
      return stored.replace(/\/$/, "");
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
    const connectRef = useRef({ ...EMPTY_SESSION });
    const reconnectTimerRef = useRef(null);
    const reconnectAttemptRef = useRef(0);
    const reconnectEnabledRef = useRef(false);
    const [status, setStatus] = useState("disconnected");
    const [lastCloseCode, setLastCloseCode] = useState(0);
    const [isInitializing, setIsInitializing] = useState(true);
    const [session, setSession] = useState({ ...EMPTY_SESSION });
    const [lastEvent, setLastEvent] = useState(null);
    const [history, setHistory] = useState([]);
    const [pendingApprovals, setPendingApprovals] = useState([]);
    const [agentStates, setAgentStates] = useState({});
    const [costState, setCostState] = useState({ spent: 0, budget: 0, history: [] });

    const clearReconnectTimer = useCallback(() => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }, []);

    const setSessionCredentials = useCallback((sessionId, token) => {
      const next = {
        sessionId: String(sessionId || "").trim(),
        token: String(token || "").trim(),
      };
      connectRef.current = next;
      setSession(next);
      return next;
    }, []);

    const disconnect = useCallback(() => {
      reconnectEnabledRef.current = false;
      reconnectAttemptRef.current = 0;
      clearReconnectTimer();
      const activeSocket = wsRef.current;
      wsRef.current = null;
      if (activeSocket && (activeSocket.readyState === WebSocket.OPEN || activeSocket.readyState === WebSocket.CONNECTING)) {
        activeSocket.close(1000, "Client disconnect");
      }
      setLastCloseCode(1000);
      setStatus("disconnected");
    }, [clearReconnectTimer]);

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
        const next = setSessionCredentials(sessionId, token);
        if (!next.sessionId || !next.token) {
          setStatus("disconnected");
          return;
        }

        reconnectEnabledRef.current = true;
        clearReconnectTimer();
        setLastCloseCode(0);

        const previousSocket = wsRef.current;
        wsRef.current = null;
        if (previousSocket && (previousSocket.readyState === WebSocket.OPEN || previousSocket.readyState === WebSocket.CONNECTING)) {
          try {
            previousSocket.close(1000, "Reconnect");
          } catch (_error) {
            // Ignore close races from stale sockets.
          }
        }

        setStatus("connecting");
        const url = `${wsBaseUrl()}/webchat/ws/${encodeURIComponent(next.sessionId)}?token=${encodeURIComponent(next.token)}`;
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          if (wsRef.current !== ws) {
            return;
          }
          reconnectAttemptRef.current = 0;
          setLastCloseCode(0);
          setStatus("connected");
          flushQueue();
        };
        ws.onclose = (event) => {
          if (wsRef.current !== ws) {
            return;
          }
          wsRef.current = null;
          const closeCode = Number(event?.code || 0);
          setLastCloseCode(closeCode);
          setStatus("disconnected");
          if (closeCode === 4001 || closeCode === 4003) {
            reconnectEnabledRef.current = false;
            connectRef.current = { ...EMPTY_SESSION };
            setSession({ ...EMPTY_SESSION });
            return;
          }
          if (!reconnectEnabledRef.current || !connectRef.current.sessionId || !connectRef.current.token) {
            return;
          }
          const delayMs = Math.min(30000, 1000 * (2 ** reconnectAttemptRef.current));
          reconnectAttemptRef.current += 1;
          reconnectTimerRef.current = setTimeout(() => {
            reconnectTimerRef.current = null;
            const creds = connectRef.current;
            if (reconnectEnabledRef.current && creds.sessionId && creds.token) {
              connect(creds.sessionId, creds.token);
            }
          }, delayMs);
        };
        ws.onerror = () => {
          if (wsRef.current !== ws) {
            return;
          }
          setStatus("disconnected");
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
      [clearReconnectTimer, flushQueue, setSessionCredentials],
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
      sessionId: session.sessionId,
      token: session.token,
      isInitializing,
      setIsInitializing,
      setSessionCredentials,
      connect,
      disconnect,
      send,
      lastEvent,
      lastCloseCode,
      history,
      pendingApprovals,
      agentStates,
      costState,
    };
  }

  window.useARCHON = useARCHON;
})();
