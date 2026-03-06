import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AppState, AppStateStatus } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type ARCHONStatus = "connecting" | "connected" | "disconnected" | "error";

export type AgentState = {
  status: string;
  startedAt: number;
};

export type CostState = {
  spent: number;
  budget: number;
  history: Array<{ spent: number; budget: number; ts: number }>;
};

export type ARCHONMobileState = {
  status: ARCHONStatus;
  send: (payload: Record<string, unknown>) => void;
  connect: (sessionId: string, token: string) => void;
  disconnect: () => void;
  clearHistory: () => Promise<void>;
  lastEvent: Record<string, unknown> | null;
  history: Array<Record<string, unknown>>;
  pendingApprovals: Array<Record<string, unknown>>;
  agentStates: Record<string, AgentState>;
  costState: CostState;
};

export const SESSION_KEY = "archon.mobile.session_id";
export const TOKEN_KEY = "archon.mobile.token";

const EMPTY_COST: CostState = { spent: 0, budget: 0, history: [] };

function nowSeconds(): number {
  return Date.now() / 1000;
}

function normalizeIncoming(raw: Record<string, unknown>): Record<string, unknown> {
  if (raw.type === "event" && typeof raw.payload === "object" && raw.payload) {
    return raw.payload as Record<string, unknown>;
  }
  if (raw.type === "result" && typeof raw.payload === "object" && raw.payload) {
    return { type: "task_result", ...(raw.payload as Record<string, unknown>) };
  }
  return raw;
}

export function reduceMobileEvent(
  current: {
    pendingApprovals: Array<Record<string, unknown>>;
    agentStates: Record<string, AgentState>;
    costState: CostState;
  },
  event: Record<string, unknown>,
): {
  pendingApprovals: Array<Record<string, unknown>>;
  agentStates: Record<string, AgentState>;
  costState: CostState;
} {
  const nextApprovals = [...current.pendingApprovals];
  const nextAgents = { ...current.agentStates };
  let nextCost = current.costState;

  const type = String(event.type || "").toLowerCase();

  if (type === "agent_start") {
    const name = String(event.agent || event.agent_name || "").trim();
    if (name) {
      nextAgents[name] = { status: "thinking", startedAt: Number(event.started_at || nowSeconds()) };
    }
  }

  if (type === "agent_end" || type === "growth_agent_completed") {
    const name = String(event.agent || event.agent_name || "").trim();
    if (name) {
      nextAgents[name] = {
        status: String(event.status || "done").toLowerCase(),
        startedAt: Number(event.started_at || nextAgents[name]?.startedAt || nowSeconds()),
      };
    }
  }

  if (type === "done") {
    Object.keys(nextAgents).forEach((agentName) => {
      if (nextAgents[agentName].status === "thinking") {
        nextAgents[agentName] = {
          ...nextAgents[agentName],
          status: "done",
        };
      }
    });
  }

  if (type === "cost_update") {
    const spent = Number(event.spent ?? event.total_spent ?? nextCost.spent ?? 0);
    const budget = Number(event.budget ?? event.limit ?? nextCost.budget ?? 0);
    const point = { spent, budget, ts: nowSeconds() };
    nextCost = {
      spent,
      budget,
      history: [...nextCost.history, point].slice(-20),
    };
  }

  if (type === "task_completed" && typeof event.budget === "object" && event.budget) {
    const budgetBlob = event.budget as Record<string, unknown>;
    const spent = Number(budgetBlob.spent_usd ?? nextCost.spent ?? 0);
    const budget = Number(budgetBlob.limit_usd ?? nextCost.budget ?? 0);
    const point = { spent, budget, ts: nowSeconds() };
    nextCost = {
      spent,
      budget,
      history: [...nextCost.history, point].slice(-20),
    };
  }

  if (type === "approval_required") {
    const requestId = String(event.request_id || event.action_id || "").trim();
    if (requestId) {
      const normalized = {
        ...event,
        request_id: requestId,
        action_id: requestId,
        timeout_s: Number(event.timeout_s || 120),
        created_at: Number(event.created_at || nowSeconds()),
      };
      const index = nextApprovals.findIndex((item) => item.action_id === requestId);
      if (index >= 0) {
        nextApprovals[index] = normalized;
      } else {
        nextApprovals.push(normalized);
      }
    }
  }

  if (type === "approval_result" || type === "approval_resolved") {
    const resolvedId = String(event.request_id || event.action_id || "").trim();
    if (resolvedId) {
      const filtered = nextApprovals.filter((item) => item.action_id !== resolvedId);
      nextApprovals.splice(0, nextApprovals.length, ...filtered);
    }
  }

  return {
    pendingApprovals: nextApprovals,
    agentStates: nextAgents,
    costState: nextCost,
  };
}

export async function loadSessionFromStorage(): Promise<{ token: string; sessionId: string }> {
  const [[, token], [, sessionId]] = await AsyncStorage.multiGet([TOKEN_KEY, SESSION_KEY]);
  return {
    token: (token || "").trim(),
    sessionId: (sessionId || "").trim(),
  };
}

export async function saveSessionToStorage(token: string, sessionId: string): Promise<void> {
  await AsyncStorage.multiSet([
    [TOKEN_KEY, token],
    [SESSION_KEY, sessionId],
  ]);
}

function wsBaseUrl(): string {
  const apiBase = (globalThis as any).ARCHON_API_BASE || "";
  if (typeof apiBase === "string" && apiBase.startsWith("http://")) {
    return apiBase.replace("http://", "ws://").replace(/\/$/, "");
  }
  if (typeof apiBase === "string" && apiBase.startsWith("https://")) {
    return apiBase.replace("https://", "wss://").replace(/\/$/, "");
  }
  return "ws://127.0.0.1:8000";
}

const ARCHONContext = createContext<ARCHONMobileState | null>(null);

export function ARCHONProvider({ children }: { children: React.ReactNode }) {
  const wsRef = useRef<WebSocket | null>(null);
  const queuedRef = useRef<Array<Record<string, unknown>>>([]);
  const credsRef = useRef<{ token: string; sessionId: string }>({ token: "", sessionId: "" });
  const stateRef = useRef<{
    pendingApprovals: Array<Record<string, unknown>>;
    agentStates: Record<string, AgentState>;
    costState: CostState;
  }>({
    pendingApprovals: [],
    agentStates: {},
    costState: EMPTY_COST,
  });

  const [status, setStatus] = useState<ARCHONStatus>("disconnected");
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);
  const [lastEvent, setLastEvent] = useState<Record<string, unknown> | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<Array<Record<string, unknown>>>([]);
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>({});
  const [costState, setCostState] = useState<CostState>(EMPTY_COST);

  useEffect(() => {
    stateRef.current = {
      pendingApprovals,
      agentStates,
      costState,
    };
  }, [pendingApprovals, agentStates, costState]);

  const flushQueue = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }
    while (queuedRef.current.length > 0) {
      const payload = queuedRef.current.shift();
      if (payload) {
        wsRef.current.send(JSON.stringify(payload));
      }
    }
  }, []);

  const disconnect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      wsRef.current.close();
    }
    wsRef.current = null;
    setStatus("disconnected");
  }, []);

  const connect = useCallback(
    (sessionId: string, token: string) => {
      const sid = String(sessionId || "").trim();
      const auth = String(token || "").trim();
      if (!sid || !auth) {
        setStatus("error");
        return;
      }

      credsRef.current = { sessionId: sid, token: auth };
      void saveSessionToStorage(auth, sid);

      disconnect();
      setStatus("connecting");

      const ws = new WebSocket(`${wsBaseUrl()}/webchat/ws/${encodeURIComponent(sid)}?token=${encodeURIComponent(auth)}`);
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

      ws.onmessage = (frame) => {
        let parsed: Record<string, unknown> = {};
        try {
          parsed = JSON.parse(frame.data) as Record<string, unknown>;
        } catch (_err) {
          return;
        }

        const event = normalizeIncoming(parsed);
        setLastEvent(event);
        setHistory((prev) => [...prev, event].slice(-800));

        const reduced = reduceMobileEvent(stateRef.current, event);
        stateRef.current = reduced;

        setPendingApprovals(reduced.pendingApprovals);
        setAgentStates(reduced.agentStates);
        setCostState(reduced.costState);
      };
    },
    [disconnect, flushQueue],
  );

  const send = useCallback(
    (payload: Record<string, unknown>) => {
      if (!payload || typeof payload !== "object") {
        return;
      }

      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        queuedRef.current.push(payload);
        if (status === "disconnected" && credsRef.current.sessionId && credsRef.current.token) {
          connect(credsRef.current.sessionId, credsRef.current.token);
        }
        return;
      }

      wsRef.current.send(JSON.stringify(payload));
    },
    [connect, status],
  );

  const clearHistory = useCallback(async () => {
    setHistory([]);
    setLastEvent(null);
    setPendingApprovals([]);
    setAgentStates({});
    setCostState(EMPTY_COST);
    await AsyncStorage.removeItem("archon.mobile.history");
  }, []);

  useEffect(() => {
    void (async () => {
      const session = await loadSessionFromStorage();
      if (session.sessionId && session.token) {
        connect(session.sessionId, session.token);
      }
    })();
  }, [connect]);

  useEffect(() => {
    const listener = (nextState: AppStateStatus) => {
      if (nextState === "active" && status === "disconnected" && credsRef.current.token && credsRef.current.sessionId) {
        connect(credsRef.current.sessionId, credsRef.current.token);
      }
    };
    const subscription = AppState.addEventListener("change", listener);
    return () => subscription.remove();
  }, [connect, status]);

  const value = useMemo<ARCHONMobileState>(
    () => ({
      status,
      connect,
      disconnect,
      send,
      clearHistory,
      lastEvent,
      history,
      pendingApprovals,
      agentStates,
      costState,
    }),
    [status, connect, disconnect, send, clearHistory, lastEvent, history, pendingApprovals, agentStates, costState],
  );

  return React.createElement(ARCHONContext.Provider, { value }, children);
}

export function useARCHONMobileContext(): ARCHONMobileState {
  const value = useContext(ARCHONContext);
  if (!value) {
    throw new Error("useARCHONMobileContext must be used within ARCHONProvider");
  }
  return value;
}

export function useARCHONMobile(): ARCHONMobileState {
  return useARCHONMobileContext();
}
