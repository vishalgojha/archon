import { useEffect, useMemo, useState } from "react";

import {
  EMPTY_STREAM_STATE,
  readStoredSession,
  reduceStreamState,
  resolveApiBase,
  resolveWsBase,
  writeStoredSession,
} from "./streamModel";

const stores = new Map();
const bootstrapRequests = new Map();

function fetchJsonWithTimeout(url, options = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => {
    window.clearTimeout(timeout);
  });
}

function bootstrapAnonymousSession(apiBase) {
  const key = String(apiBase || "").trim() || "default";
  if (bootstrapRequests.has(key)) {
    return bootstrapRequests.get(key);
  }
  const request = fetchJsonWithTimeout(`${apiBase}/webchat/token`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      const sessionId = String(
        payload.session?.session_id || payload.identity?.session_id || "",
      ).trim();
      const token = String(payload.token || "").trim();
      if (!sessionId || !token) {
        throw new Error("Token response missing session_id or token.");
      }
      writeStoredSession(sessionId, token);
      return { sessionId, token };
    })
    .finally(() => {
      bootstrapRequests.delete(key);
    });
  bootstrapRequests.set(key, request);
  return request;
}

function buildSocketUrl(config) {
  const wsBase = resolveWsBase({ apiBase: config.apiBase, wsBase: config.wsBase });
  if (config.transport === "task") {
    return `${wsBase}/v1/tasks/ws?token=${encodeURIComponent(config.token)}`;
  }
  return `${wsBase}/webchat/ws/${encodeURIComponent(config.sessionId)}?token=${encodeURIComponent(
    config.token,
  )}`;
}

function createStore(config) {
  let state = {
    ...EMPTY_STREAM_STATE,
    sessionId: config.sessionId,
    token: config.token,
    transport: config.transport,
    apiBase: config.apiBase,
  };
  let socket = null;
  let refCount = 0;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  const queue = [];
  const subscribers = new Set();

  function publish(nextState) {
    state = nextState;
    subscribers.forEach((subscriber) => subscriber(state));
  }

  function update(partial) {
    publish({ ...state, ...partial });
  }

  function clearReconnectTimer() {
    if (reconnectTimer) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function flushQueue() {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    while (queue.length > 0) {
      socket.send(JSON.stringify(queue.shift()));
    }
  }

  function handleIncoming(raw) {
    publish(reduceStreamState(state, raw));
  }

  function connect() {
    if (!config.token || (config.transport === "webchat" && !config.sessionId)) {
      return;
    }
    if (
      socket &&
      (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    clearReconnectTimer();
    update({ status: "connecting", lastCloseCode: 0 });
    socket = new WebSocket(buildSocketUrl(config));

    socket.onopen = () => {
      reconnectAttempt = 0;
      update({ status: "connected", lastCloseCode: 0 });
      flushQueue();
    };

    socket.onmessage = (message) => {
      try {
        handleIncoming(JSON.parse(message.data));
      } catch (_error) {
        return;
      }
    };

    socket.onerror = () => {
      update({ status: "error" });
    };

    socket.onclose = (event) => {
      socket = null;
      update({ status: "disconnected", lastCloseCode: Number(event?.code || 0) });
      if (!refCount) {
        return;
      }
      if (event?.code === 4001 || event?.code === 4003) {
        return;
      }
      const delayMs = Math.min(30000, 1000 * (2 ** reconnectAttempt));
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delayMs);
    };
  }

  function disconnect() {
    clearReconnectTimer();
    if (
      socket &&
      (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)
    ) {
      socket.close(1000, "Component disconnect");
    }
    socket = null;
    update({ status: "disconnected" });
  }

  function send(payload) {
    if (!payload || typeof payload !== "object") {
      return;
    }
    if (payload.type === "message" && String(payload.content || "").trim()) {
      handleIncoming({ type: "local_user_message", content: String(payload.content || "") });
    }
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      queue.push(payload);
      connect();
      return;
    }
    socket.send(JSON.stringify(payload));
  }

  return {
    getSnapshot() {
      return state;
    },
    subscribe(listener) {
      subscribers.add(listener);
      return () => {
        subscribers.delete(listener);
      };
    },
    retain() {
      refCount += 1;
      connect();
    },
    release() {
      refCount = Math.max(0, refCount - 1);
      if (!refCount) {
        disconnect();
      }
    },
    send,
    approve(requestId, notes = "") {
      const normalized = String(requestId || "").trim();
      if (!normalized) {
        return;
      }
      send({ type: "approve", request_id: normalized, action_id: normalized, notes });
    },
    deny(requestId, notes = "") {
      const normalized = String(requestId || "").trim();
      if (!normalized) {
        return;
      }
      send({ type: "deny", request_id: normalized, action_id: normalized, notes });
    },
  };
}

function getStore(config) {
  const key = [
    config.transport,
    config.apiBase,
    config.wsBase,
    config.sessionId,
    config.token,
  ].join("|");
  if (!stores.has(key)) {
    stores.set(key, createStore(config));
  }
  return stores.get(key);
}

export function useArchonStream(options = {}) {
  const {
    apiBase: requestedApiBase = "",
    wsBase = "",
    sessionId: requestedSessionId = "",
    token: requestedToken = "",
    transport = "webchat",
    autoConnect = true,
    bootstrap = true,
  } = options;

  const apiBase = useMemo(() => resolveApiBase(requestedApiBase), [requestedApiBase]);
  const [credentials, setCredentials] = useState(() => {
    const sessionId = String(requestedSessionId || "").trim();
    const token = String(requestedToken || "").trim();
    if (sessionId && token) {
      return { sessionId, token };
    }
    return transport === "webchat" ? readStoredSession() : { sessionId, token };
  });

  useEffect(() => {
    const sessionId = String(requestedSessionId || "").trim();
    const token = String(requestedToken || "").trim();
    if (sessionId && token) {
      writeStoredSession(sessionId, token);
      setCredentials({ sessionId, token });
      return;
    }
    if (transport === "webchat") {
      const stored = readStoredSession();
      if (stored.sessionId && stored.token) {
        setCredentials(stored);
      }
    }
  }, [requestedSessionId, requestedToken, transport]);

  useEffect(() => {
    if (transport !== "webchat" || bootstrap === false) {
      return undefined;
    }
    if (credentials.sessionId && credentials.token) {
      return undefined;
    }
    let cancelled = false;
    bootstrapAnonymousSession(apiBase)
      .then((nextCredentials) => {
        if (!cancelled) {
          setCredentials(nextCredentials);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCredentials((current) => current);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase, bootstrap, credentials.sessionId, credentials.token, transport]);

  const store = useMemo(() => {
    if (!credentials.token || (transport === "webchat" && !credentials.sessionId)) {
      return null;
    }
    return getStore({
      apiBase,
      wsBase,
      sessionId: credentials.sessionId,
      token: credentials.token,
      transport,
    });
  }, [apiBase, credentials.sessionId, credentials.token, transport, wsBase]);

  const [snapshot, setSnapshot] = useState(() => ({
    ...EMPTY_STREAM_STATE,
    sessionId: credentials.sessionId,
    token: credentials.token,
    transport,
    apiBase,
  }));

  useEffect(() => {
    if (!store) {
      setSnapshot({
        ...EMPTY_STREAM_STATE,
        sessionId: credentials.sessionId,
        token: credentials.token,
        transport,
        apiBase,
      });
      return undefined;
    }
    setSnapshot(store.getSnapshot());
    return store.subscribe(setSnapshot);
  }, [apiBase, credentials.sessionId, credentials.token, store, transport]);

  useEffect(() => {
    if (!store || autoConnect === false) {
      return undefined;
    }
    store.retain();
    return () => {
      store.release();
    };
  }, [autoConnect, store]);

  return useMemo(
    () => ({
      ...snapshot,
      send: store ? store.send : () => {},
      approve: store ? store.approve : () => {},
      deny: store ? store.deny : () => {},
    }),
    [snapshot, store],
  );
}
