import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AppState, AppStateStatus } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type ARCHONStatus = "connecting" | "connected" | "disconnected" | "error";
export type BackgroundSyncTrigger = "startup" | "app_active" | "reconnect" | "silent_push";

export type AgentState = {
  status: string;
  startedAt: number;
};

export type CostState = {
  spent: number;
  budget: number;
  history: Array<{ spent: number; budget: number; ts: number }>;
};

export type BackgroundSyncState = {
  watermark: number;
  cursor: string;
  lastSuccessfulSyncAt: number;
  lastAttemptAt: number;
  retryCount: number;
  nextRetryAt: number;
};

export type SilentPushInstruction = {
  kind: "background_sync";
  reason: string;
  tenantId: string;
  sessionId: string;
};

export type ARCHONMobileState = {
  status: ARCHONStatus;
  send: (payload: Record<string, unknown>) => void;
  connect: (sessionId: string, token: string) => void;
  disconnect: () => void;
  clearHistory: () => Promise<void>;
  runBackgroundSync: (trigger?: BackgroundSyncTrigger) => Promise<void>;
  syncState: BackgroundSyncState;
  lastEvent: Record<string, unknown> | null;
  history: Array<Record<string, unknown>>;
  pendingApprovals: Array<Record<string, unknown>>;
  agentStates: Record<string, AgentState>;
  costState: CostState;
};

export const SESSION_KEY = "archon.mobile.session_id";
export const TOKEN_KEY = "archon.mobile.token";
export const SYNC_STATE_KEY = "archon.mobile.sync_state";
export const OFFLINE_QUEUE_KEY = "archon.mobile.offline_queue";

const EMPTY_COST: CostState = { spent: 0, budget: 0, history: [] };
const EMPTY_SYNC_STATE: BackgroundSyncState = {
  watermark: 0,
  cursor: "",
  lastSuccessfulSyncAt: 0,
  lastAttemptAt: 0,
  retryCount: 0,
  nextRetryAt: 0,
};

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

function normalizeSyncState(raw: unknown): BackgroundSyncState {
  if (!raw || typeof raw !== "object") {
    return EMPTY_SYNC_STATE;
  }
  const blob = raw as Record<string, unknown>;
  return {
    watermark: Number(blob.watermark || 0),
    cursor: String(blob.cursor || ""),
    lastSuccessfulSyncAt: Number(blob.lastSuccessfulSyncAt || 0),
    lastAttemptAt: Number(blob.lastAttemptAt || 0),
    retryCount: Number(blob.retryCount || 0),
    nextRetryAt: Number(blob.nextRetryAt || 0),
  };
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
        nextAgents[agentName] = { ...nextAgents[agentName], status: "done" };
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

export function parseSilentPushPayload(raw: Record<string, unknown>): SilentPushInstruction | null {
  const data =
    raw.data && typeof raw.data === "object" ? (raw.data as Record<string, unknown>) : raw;
  const aps = raw.aps && typeof raw.aps === "object" ? (raw.aps as Record<string, unknown>) : {};
  const isSilent =
    String(data.silent || "").toLowerCase() === "true" ||
    String(data.kind || "").toLowerCase() === "background_sync" ||
    Number((aps["content-available"] as number) || 0) === 1 ||
    Number((aps.contentAvailable as number) || 0) === 1;
  if (!isSilent) {
    return null;
  }
  return {
    kind: "background_sync",
    reason: String(data.reason || data.action || "background_refresh"),
    tenantId: String(data.tenant_id || ""),
    sessionId: String(data.session_id || ""),
  };
}

export function scheduleBackgroundSync(
  current: BackgroundSyncState,
  trigger: BackgroundSyncTrigger,
  now: number = nowSeconds(),
): { shouldRun: boolean; nextState: BackgroundSyncState } {
  const dedupeWindow = trigger === "silent_push" ? 5 : 15;
  if (current.lastAttemptAt > 0 && now - current.lastAttemptAt < dedupeWindow) {
    return { shouldRun: false, nextState: current };
  }
  if (trigger !== "silent_push" && current.nextRetryAt > now) {
    return { shouldRun: false, nextState: current };
  }
  return {
    shouldRun: true,
    nextState: {
      ...current,
      lastAttemptAt: now,
    },
  };
}

export function routeSilentPushPayload(
  raw: Record<string, unknown>,
  current: BackgroundSyncState,
  now: number = nowSeconds(),
): { instruction: SilentPushInstruction | null; shouldRun: boolean; nextState: BackgroundSyncState } {
  const instruction = parseSilentPushPayload(raw);
  if (!instruction) {
    return { instruction: null, shouldRun: false, nextState: current };
  }
  const scheduled = scheduleBackgroundSync(current, "silent_push", now);
  return {
    instruction,
    shouldRun: scheduled.shouldRun,
    nextState: scheduled.nextState,
  };
}

export function recordBackgroundSyncSuccess(
  current: BackgroundSyncState,
  payload: Record<string, unknown>,
  now: number = nowSeconds(),
): BackgroundSyncState {
  const sync = payload.sync && typeof payload.sync === "object" ? (payload.sync as Record<string, unknown>) : {};
  const serverWatermark = Number(sync.watermark || current.watermark || 0);
  const nextCursor = String(sync.next_cursor || "");
  const recovered = sync.stale_watermark_recovered === true;
  return {
    watermark: recovered ? serverWatermark : Math.max(current.watermark, serverWatermark),
    cursor: nextCursor,
    lastSuccessfulSyncAt: now,
    lastAttemptAt: current.lastAttemptAt,
    retryCount: 0,
    nextRetryAt: 0,
  };
}

export function recordBackgroundSyncFailure(
  current: BackgroundSyncState,
  now: number = nowSeconds(),
): BackgroundSyncState {
  const retryCount = current.retryCount + 1;
  const backoff = Math.min(300, 5 * 2 ** Math.max(0, retryCount - 1));
  return {
    ...current,
    retryCount,
    nextRetryAt: now + backoff,
    lastAttemptAt: now,
  };
}

export async function loadSessionFromStorage(): Promise<{ token: string; sessionId: string }> {
  const [[, token], [, sessionId]] = await AsyncStorage.multiGet([TOKEN_KEY, SESSION_KEY]);
  return {
    token: String(token || "").trim(),
    sessionId: String(sessionId || "").trim(),
  };
}

export async function saveSessionToStorage(token: string, sessionId: string): Promise<void> {
  await AsyncStorage.multiSet([
    [TOKEN_KEY, token],
    [SESSION_KEY, sessionId],
  ]);
}

export async function loadSyncStateFromStorage(): Promise<BackgroundSyncState> {
  const raw = await AsyncStorage.getItem(SYNC_STATE_KEY);
  if (!raw) {
    return EMPTY_SYNC_STATE;
  }
  try {
    return normalizeSyncState(JSON.parse(raw));
  } catch (_err) {
    return EMPTY_SYNC_STATE;
  }
}

export async function saveSyncStateToStorage(state: BackgroundSyncState): Promise<void> {
  await AsyncStorage.setItem(SYNC_STATE_KEY, JSON.stringify(state));
}

export async function loadOfflineQueueFromStorage(): Promise<Array<Record<string, unknown>>> {
  const raw = await AsyncStorage.getItem(OFFLINE_QUEUE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") : [];
  } catch (_err) {
    return [];
  }
}

export async function saveOfflineQueueToStorage(queue: Array<Record<string, unknown>>): Promise<void> {
  if (queue.length === 0) {
    await AsyncStorage.removeItem(OFFLINE_QUEUE_KEY);
    return;
  }
  await AsyncStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
}

function httpBaseUrl(): string {
  const apiBase = (globalThis as any).ARCHON_API_BASE || "";
  if (typeof apiBase === "string" && apiBase.trim()) {
    return apiBase.replace(/\/$/, "");
  }
  return "http://127.0.0.1:8000";
}

function wsBaseUrl(): string {
  const apiBase = httpBaseUrl();
  if (apiBase.startsWith("http://")) {
    return apiBase.replace("http://", "ws://");
  }
  if (apiBase.startsWith("https://")) {
    return apiBase.replace("https://", "wss://");
  }
  return "ws://127.0.0.1:8000";
}

async function fetchBackgroundSync(
  sessionId: string,
  token: string,
  state: BackgroundSyncState,
): Promise<Record<string, unknown>> {
  const query = new URLSearchParams({
    token,
    since: String(state.watermark || 0),
    page_size: "50",
  });
  if (state.cursor) {
    query.set("cursor", state.cursor);
  }
  const response = await fetch(
    `${httpBaseUrl()}/webchat/mobile/sync/${encodeURIComponent(sessionId)}?${query.toString()}`,
  );
  if (!response.ok) {
    throw new Error(`Mobile sync failed (${response.status})`);
  }
  return (await response.json()) as Record<string, unknown>;
}

const ARCHONContext = createContext<ARCHONMobileState | null>(null);

export function ARCHONProvider({ children }: { children: React.ReactNode }) {
  const wsRef = useRef<WebSocket | null>(null);
  const queuedRef = useRef<Array<Record<string, unknown>>>([]);
  const credsRef = useRef<{ token: string; sessionId: string }>({ token: "", sessionId: "" });
  const syncRef = useRef<BackgroundSyncState>(EMPTY_SYNC_STATE);
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
  const [syncState, setSyncState] = useState<BackgroundSyncState>(EMPTY_SYNC_STATE);

  useEffect(() => {
    stateRef.current = { pendingApprovals, agentStates, costState };
  }, [pendingApprovals, agentStates, costState]);

  useEffect(() => {
    syncRef.current = syncState;
  }, [syncState]);

  const persistSyncState = useCallback((next: BackgroundSyncState) => {
    syncRef.current = next;
    setSyncState(next);
    void saveSyncStateToStorage(next);
  }, []);

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
    void saveOfflineQueueToStorage(queuedRef.current);
  }, []);

  const disconnect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      wsRef.current.close();
    }
    wsRef.current = null;
    setStatus("disconnected");
  }, []);

  const runBackgroundSync = useCallback(
    async (trigger: BackgroundSyncTrigger = "app_active") => {
      const { sessionId, token } = credsRef.current;
      if (!sessionId || !token) {
        return;
      }
      const scheduled = scheduleBackgroundSync(syncRef.current, trigger);
      persistSyncState(scheduled.nextState);
      if (!scheduled.shouldRun) {
        return;
      }
      try {
        const payload = await fetchBackgroundSync(sessionId, token, scheduled.nextState);
        const pending = Array.isArray(payload.pending_approvals)
          ? (payload.pending_approvals as Array<Record<string, unknown>>)
          : [];
        setPendingApprovals(pending);
        persistSyncState(recordBackgroundSyncSuccess(scheduled.nextState, payload));
      } catch (_err) {
        persistSyncState(recordBackgroundSyncFailure(scheduled.nextState));
      }
    },
    [persistSyncState],
  );

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
        void runBackgroundSync("reconnect");
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
    [disconnect, flushQueue, runBackgroundSync],
  );

  const send = useCallback(
    (payload: Record<string, unknown>) => {
      if (!payload || typeof payload !== "object") {
        return;
      }

      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        queuedRef.current.push(payload);
        void saveOfflineQueueToStorage(queuedRef.current);
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
      const [session, persistedQueue, persistedSyncState] = await Promise.all([
        loadSessionFromStorage(),
        loadOfflineQueueFromStorage(),
        loadSyncStateFromStorage(),
      ]);
      queuedRef.current = persistedQueue;
      persistSyncState(persistedSyncState);
      if (session.sessionId && session.token) {
        connect(session.sessionId, session.token);
        void runBackgroundSync("startup");
      }
    })();
  }, [connect, persistSyncState, runBackgroundSync]);

  useEffect(() => {
    const listener = (nextState: AppStateStatus) => {
      if (nextState === "active") {
        if (status === "disconnected" && credsRef.current.token && credsRef.current.sessionId) {
          connect(credsRef.current.sessionId, credsRef.current.token);
        }
        void runBackgroundSync("app_active");
      }
    };
    const subscription = AppState.addEventListener("change", listener);
    return () => subscription.remove();
  }, [connect, runBackgroundSync, status]);

  const value = useMemo<ARCHONMobileState>(
    () => ({
      status,
      connect,
      disconnect,
      send,
      clearHistory,
      runBackgroundSync,
      syncState,
      lastEvent,
      history,
      pendingApprovals,
      agentStates,
      costState,
    }),
    [
      status,
      connect,
      disconnect,
      send,
      clearHistory,
      runBackgroundSync,
      syncState,
      lastEvent,
      history,
      pendingApprovals,
      agentStates,
      costState,
    ],
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
