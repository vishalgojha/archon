export const EMPTY_COST_STATE = {
  spent: 0,
  budget: 0,
  history: [],
};

export const EMPTY_STREAM_STATE = {
  status: "disconnected",
  sessionId: "",
  token: "",
  transport: "webchat",
  apiBase: "",
  lastCloseCode: 0,
  lastEvent: null,
  history: [],
  rounds: [],
  confidence: null,
  messages: [],
  activeMessage: null,
  sessionRestored: false,
  pendingApprovals: [],
  agentStates: {},
  costState: EMPTY_COST_STATE,
  memoryRefreshVersion: 0,
  messageSequence: 0,
};

const SESSION_ID_KEY = "archon.dashboard.session_id";
const TOKEN_KEY = "archon.dashboard.token";

export function safeStorageGet(key) {
  try {
    return localStorage.getItem(key) || "";
  } catch (_error) {
    return "";
  }
}

export function safeStorageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (_error) {
    return;
  }
}

export function readStoredSession() {
  return {
    sessionId: String(safeStorageGet(SESSION_ID_KEY) || "").trim(),
    token: String(safeStorageGet(TOKEN_KEY) || "").trim(),
  };
}

export function writeStoredSession(sessionId, token) {
  safeStorageSet(SESSION_ID_KEY, String(sessionId || "").trim());
  safeStorageSet(TOKEN_KEY, String(token || "").trim());
}

export function resolveApiBase(apiBase = "") {
  const provided = String(apiBase || "").trim();
  if (provided) {
    return provided.replace(/\/$/, "");
  }
  if (typeof window !== "undefined" && /^https?:$/.test(window.location.protocol)) {
    return window.location.origin.replace(/\/$/, "");
  }
  return "http://127.0.0.1:8000";
}

export function resolveWsBase({ apiBase = "", wsBase = "" } = {}) {
  const provided = String(wsBase || "").trim();
  if (provided) {
    return provided.replace(/\/$/, "");
  }
  const base = resolveApiBase(apiBase);
  if (base.startsWith("wss://") || base.startsWith("ws://")) {
    return base;
  }
  if (base.startsWith("https://")) {
    return `wss://${base.slice("https://".length)}`;
  }
  if (base.startsWith("http://")) {
    return `ws://${base.slice("http://".length)}`;
  }
  return `ws://${base.replace(/^(https?:\/\/|wss?:\/\/)/, "")}`;
}

export function normalizeIncoming(raw) {
  if (!raw || typeof raw !== "object") {
    return { type: "unknown", payload: raw };
  }
  if (raw.type === "event" && raw.payload && typeof raw.payload === "object") {
    return normalizeIncoming(raw.payload);
  }
  if (raw.type === "result" && raw.payload && typeof raw.payload === "object") {
    return normalizeIncoming({ type: "task_result", ...raw.payload });
  }
  if (raw.type === "assistant_token") {
    return { ...raw, type: "token", content: String(raw.token || "") };
  }
  if (raw.type === "debate_round_completed") {
    return {
      ...raw,
      type: "debate_round",
      round_id: String(raw.round_id || `${raw.round || 0}-${raw.agent || "agent"}`),
      content: String(raw.output || raw.output_preview || ""),
    };
  }
  return raw;
}

export function deriveSwarmAgents(agentStates = {}, history = [], baselineAgents = []) {
  const result = {
    orchestrator: {
      id: "orchestrator",
      label: "orchestrator",
      status: "thinking",
    },
  };

  baselineAgents.forEach((agent) => {
    const id = String(agent?.id || "").trim();
    if (!id) {
      return;
    }
    result[id] = {
      id,
      label: String(agent.label || id),
      status: String(agent.status || "idle"),
    };
  });

  Object.keys(agentStates || {}).forEach((name) => {
    result[name] = {
      id: name,
      label: name,
      status: String(agentStates[name]?.status || result[name]?.status || "idle"),
    };
  });

  if (Object.keys(result).length <= 1) {
    history.forEach((event) => {
      const name = String(event.agent || event.agent_name || "").trim();
      if (!name) {
        return;
      }
      result[name] = {
        id: name,
        label: name,
        status: String(event.status || "idle"),
      };
    });
  }

  return Object.values(result);
}

export function deriveSwarmEdges(agents = [], explicitEdges = []) {
  const validIds = new Set(
    agents.map((agent) => String(agent?.id || "").trim()).filter(Boolean),
  );
  if (Array.isArray(explicitEdges) && explicitEdges.length > 0) {
    return explicitEdges
      .map((edge) => ({
        source: String(edge.source || ""),
        target: String(edge.target || ""),
      }))
      .filter((edge) => validIds.has(edge.source) && validIds.has(edge.target));
  }
  return agents
    .filter((agent) => agent.id !== "orchestrator")
    .map((agent) => ({ source: "orchestrator", target: agent.id }));
}

function nextMessageId(state, prefix) {
  return `${prefix}-${state.messageSequence + 1}`;
}

function finalizeAssistantMessage(state, content, contentType = "default") {
  const resolved = String(content || state.activeMessage?.content || "").trim();
  if (!resolved) {
    return state;
  }
  const finalized = state.activeMessage || {
    id: nextMessageId(state, "assistant"),
    role: "assistant",
    contentType,
    content: resolved,
  };
  const message = {
    ...finalized,
    contentType: contentType || finalized.contentType || "default",
    content: resolved,
  };
  return {
    ...state,
    messages: [...state.messages, message],
    activeMessage: null,
    messageSequence: state.messageSequence + 1,
    memoryRefreshVersion: state.memoryRefreshVersion + 1,
  };
}

function reduceApprovalQueue(current, event) {
  const type = String(event.type || "").toLowerCase();
  if (type === "approval_required") {
    const requestId = String(event.request_id || event.action_id || "").trim();
    if (!requestId) {
      return current;
    }
    const normalized = {
      ...event,
      request_id: requestId,
      action_id: requestId,
      timeout_s: Number(event.timeout_s || event.timeout_remaining_s || 120),
      created_at: Number(event.created_at || Date.now() / 1000),
    };
    const index = current.findIndex((item) => item.action_id === requestId);
    if (index >= 0) {
      return current.map((item, itemIndex) => (itemIndex === index ? normalized : item));
    }
    return [...current, normalized];
  }
  if (type === "approval_result" || type === "approval_resolved") {
    const requestId = String(event.request_id || event.action_id || "").trim();
    if (!requestId) {
      return current;
    }
    return current.filter((item) => item.action_id !== requestId);
  }
  return current;
}

function reduceAgentStates(current, event) {
  const next = { ...current };
  const type = String(event.type || "").toLowerCase();
  if (type === "agent_start") {
    const name = String(event.agent || event.agent_name || "").trim();
    if (name) {
      next[name] = {
        status: "thinking",
        startedAt: Number(event.started_at || Date.now() / 1000),
      };
    }
    return next;
  }
  if (type === "agent_end" || type === "growth_agent_completed") {
    const name = String(event.agent || event.agent_name || "").trim();
    if (name) {
      next[name] = {
        status: String(event.status || "done").toLowerCase(),
        startedAt: Number(event.started_at || next[name]?.startedAt || Date.now() / 1000),
      };
    }
    return next;
  }
  if (type === "done" || type === "task_result") {
    Object.keys(next).forEach((name) => {
      if (next[name]?.status === "thinking") {
        next[name] = { ...next[name], status: "done" };
      }
    });
  }
  return next;
}

function reduceCostState(current, event) {
  const type = String(event.type || "").toLowerCase();
  if (type === "cost_update") {
    const spent = Number(event.spent ?? event.total_spent ?? current.spent ?? 0);
    const budget = Number(event.budget ?? event.limit ?? current.budget ?? 0);
    return {
      spent,
      budget,
      history: [...current.history, { spent, budget, ts: Date.now() / 1000 }].slice(-20),
    };
  }
  if (
    (type === "task_completed" || type === "task_result") &&
    event.budget &&
    typeof event.budget === "object"
  ) {
    const spent = Number(event.budget.spent_usd ?? current.spent ?? 0);
    const budget = Number(event.budget.limit_usd ?? current.budget ?? 0);
    return {
      spent,
      budget,
      history: [...current.history, { spent, budget, ts: Date.now() / 1000 }].slice(-20),
    };
  }
  return current;
}

export function reduceStreamState(previousState, rawIncoming) {
  const event = normalizeIncoming(rawIncoming);
  const nextState = {
    ...previousState,
    lastEvent: event,
    history: [...previousState.history, event].slice(-500),
    pendingApprovals: reduceApprovalQueue(previousState.pendingApprovals, event),
    agentStates: reduceAgentStates(previousState.agentStates, event),
    costState: reduceCostState(previousState.costState, event),
  };

  const confidence = Number(event.confidence);
  if (Number.isFinite(confidence)) {
    nextState.confidence = Math.max(0, Math.min(100, confidence));
  }

  const type = String(event.type || "").toLowerCase();
  if (type === "local_user_message") {
    return {
      ...nextState,
      messages: [
        ...previousState.messages,
        {
          id: nextMessageId(previousState, "user"),
          role: "user",
          contentType: "default",
          content: String(event.content || ""),
        },
      ],
      messageSequence: previousState.messageSequence + 1,
    };
  }

  if (type === "session_restored") {
    const restoredMessages = Array.isArray(event.messages)
      ? event.messages.map((message, index) => ({
          id: `restored-${index + 1}`,
          role: String(message.role || "assistant"),
          contentType: String(message.content_type || "default"),
          content: String(message.content || ""),
        }))
      : [];
    return {
      ...nextState,
      sessionId: String(event.session?.session_id || previousState.sessionId || ""),
      messages: restoredMessages,
      activeMessage: null,
      sessionRestored: true,
      memoryRefreshVersion: previousState.memoryRefreshVersion + 1,
      messageSequence: restoredMessages.length,
    };
  }

  if (type === "debate_round") {
    return {
      ...nextState,
      rounds: [
        ...previousState.rounds,
        {
          round_id: String(event.round_id || `${event.round || 0}-${event.agent || "agent"}`),
          role: String(event.role || event.agent || "Agent"),
          content: String(event.content || event.output || event.output_preview || ""),
          confidence: Number(event.confidence || 0),
        },
      ].slice(-80),
    };
  }

  if (type === "token") {
    const chunk = String(event.content || event.token || "").trim();
    if (!chunk) {
      return nextState;
    }
    const activeMessage = previousState.activeMessage || {
      id: nextMessageId(previousState, "assistant"),
      role: "assistant",
      contentType: "default",
      content: "",
    };
    return {
      ...nextState,
      activeMessage: {
        ...activeMessage,
        content: activeMessage.content
          ? `${activeMessage.content} ${chunk}`.trim()
          : chunk,
      },
    };
  }

  if (type === "done") {
    return finalizeAssistantMessage(
      nextState,
      String(event.message?.content || ""),
      String(event.message?.content_type || "default"),
    );
  }

  if (type === "task_result") {
    const withMessage = finalizeAssistantMessage(
      nextState,
      String(event.final_answer || event.message?.content || ""),
      String(event.content_type || "default"),
    );
    return {
      ...withMessage,
      confidence: Number.isFinite(Number(event.confidence))
        ? Math.max(0, Math.min(100, Number(event.confidence)))
        : withMessage.confidence,
    };
  }

  if (type === "approval_result" || type === "approval_resolved") {
    return {
      ...nextState,
      memoryRefreshVersion: previousState.memoryRefreshVersion + 1,
    };
  }

  return nextState;
}
