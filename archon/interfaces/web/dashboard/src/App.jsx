(() => {
  const { useEffect, useMemo, useRef, useState } = React;

  function safeStorageGet(key) {
    try {
      return localStorage.getItem(key) || "";
    } catch (_error) {
      return "";
    }
  }

  function safeStorageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (_error) {
      return;
    }
  }

  function resolveApiBase() {
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      return window.location.origin.replace(/\/$/, "");
    }
    const stored = safeStorageGet("archon.api_base");
    if (stored) {
      return stored.replace(/\/$/, "");
    }
    return "http://127.0.0.1:8000";
  }

  function readStoredSession() {
    return {
      sessionId: String(safeStorageGet("archon.session_id") || "").trim(),
      token: String(safeStorageGet("archon.token") || "").trim(),
    };
  }

  function writeStoredSession(sessionId, token) {
    safeStorageSet("archon.session_id", sessionId);
    safeStorageSet("archon.token", token);
  }

  async function fetchAnonymousToken() {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("/webchat/token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({}),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      const token = String(payload.token || "").trim();
      const sessionId = String(payload.session?.session_id || payload.identity?.session_id || "").trim();
      if (!token || !sessionId) {
        throw new Error("Token response missing token/session_id");
      }
      return { sessionId, token };
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function decodeJwtClaims(token) {
    try {
      const payload = String(token || "").split(".")[1];
      if (!payload) {
        return {};
      }
      const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
      const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4 || 4)) % 4), "=");
      return JSON.parse(window.atob(padded));
    } catch (_error) {
      return {};
    }
  }

  function eventTimestampSeconds(event) {
    if (!event || typeof event !== "object") {
      return 0;
    }
    const numeric = Number(event.ts || event.timestamp || event.created_at || 0);
    if (Number.isFinite(numeric) && numeric > 0) {
      return numeric;
    }
    const text = String(event.created_at || event.timestamp || "").trim();
    if (!text) {
      return 0;
    }
    const parsed = Date.parse(text);
    if (Number.isNaN(parsed)) {
      return 0;
    }
    return parsed / 1000;
  }

  function shortJson(value, maxLength = 220) {
    let text = "";
    try {
      if (typeof value === "string") {
        text = value;
      } else {
        text = JSON.stringify(value || {}, null, 0);
      }
    } catch (_error) {
      text = String(value || "");
    }
    if (text.length <= maxLength) {
      return text;
    }
    return `${text.slice(0, maxLength)}...`;
  }

  function shortSessionLabel(sessionId) {
    const normalized = String(sessionId || "").trim();
    if (!normalized) {
      return "none";
    }
    if (normalized.length <= 8) {
      return normalized;
    }
    return `${normalized.slice(0, 8)}...`;
  }

  function buildDebateRounds(history) {
    const rounds = [];
    history.forEach((event, idx) => {
      const type = String(event?.type || "").toLowerCase();
      if (!["debate_round", "agent_end", "growth_agent_completed", "task_result"].includes(type)) {
        return;
      }
      const role = String(event.role || event.agent || event.agent_name || "Agent");
      const content =
        typeof event.content === "string"
          ? event.content
          : shortJson(event.output || event.result || event.payload || event.answer || event, 1800);
      rounds.push({
        round_id: String(event.round_id || `${idx}-${role}`),
        role,
        content,
      });
    });
    return rounds.slice(-80);
  }

  function workflowFromHistory(history) {
    for (let idx = history.length - 1; idx >= 0; idx -= 1) {
      const event = history[idx] || {};
      if (Array.isArray(event.workflow) && event.workflow.length > 0) {
        return event.workflow;
      }
      if (Array.isArray(event.steps) && event.steps.length > 0) {
        return event.steps;
      }
      if (event.payload && Array.isArray(event.payload.workflow) && event.payload.workflow.length > 0) {
        return event.payload.workflow;
      }
    }
    return [];
  }

  function deriveSwarmAgents(agentRegistry, agentStates, history) {
    const result = {};
    const baseline = agentRegistry && typeof agentRegistry === "object" ? agentRegistry : {};

    result.orchestrator = {
      id: "orchestrator",
      label: "orchestrator",
      status: "thinking",
    };

    Object.keys(baseline).forEach((name) => {
      result[name] = {
        id: name,
        label: name,
        status: String(baseline[name]?.status || "idle"),
      };
    });

    Object.keys(agentStates || {}).forEach((name) => {
      result[name] = {
        id: name,
        label: name,
        status: String(agentStates[name]?.status || result[name]?.status || "idle"),
      };
    });

    if (Object.keys(result).length === 0) {
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

  function deriveSwarmEdges(baselineEdges, agents) {
    const validIds = new Set((agents || []).map((agent) => String(agent?.id || "").trim()).filter(Boolean));
    if (Array.isArray(baselineEdges) && baselineEdges.length > 0) {
      return baselineEdges
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

  function ThoughtLog({ history }) {
    const rows = history.slice(-40).reverse();
    return (
      <section className="thought-log card">
        <div className="card-header">Thought Log</div>
        <ul className="thought-log-list">
          {rows.map((event, idx) => (
            <li key={`${String(event.type || "event")}-${idx}`}>
              <span className="thought-type">{String(event.type || "event")}</span>
              <div>{shortJson(event.output || event.result || event.payload || event, 260)}</div>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  function App() {
    const archon = window.useARCHONContext ? window.useARCHONContext() : {};
    const status = archon?.status || "disconnected";
    const token = String(archon?.token || "").trim();
    const sessionId = String(archon?.sessionId || "").trim();
    const isInitializing = Boolean(archon?.isInitializing);
    const setIsInitializing = archon?.setIsInitializing || (() => {});
    const setSessionCredentials = archon?.setSessionCredentials || (() => ({ sessionId: "", token: "" }));
    const connect = archon?.connect || (() => {});
    const disconnect = archon?.disconnect || (() => {});
    const send = archon?.send || (() => {});
    const history = Array.isArray(archon?.history) ? archon.history : [];
    const pendingApprovals = Array.isArray(archon?.pendingApprovals) ? archon.pendingApprovals : [];
    const agentStates = archon?.agentStates || {};
    const costState = archon?.costState || { spent: 0, budget: 0, history: [] };

    const [mode, setMode] = useState(() => safeStorageGet("archon.dashboard.mode") || "mission_control");
    const [agentsStatus, setAgentsStatus] = useState({ agents: {}, edges: [] });
    const [leaderboard, setLeaderboard] = useState({ loading: false, rows: [], scope: "tenant" });
    const [initError, setInitError] = useState("");
    const initRequestRef = useRef(0);
    const apiBase = useMemo(() => resolveApiBase(), []);

    useEffect(() => {
      safeStorageSet("archon.dashboard.mode", mode);
    }, [mode]);

    const startInitialization = React.useCallback(() => {
      const requestId = initRequestRef.current + 1;
      initRequestRef.current = requestId;
      setInitError("");
      setIsInitializing(true);
      return (async () => {
        try {
          let next = readStoredSession();
          if (!next.token || !next.sessionId) {
            next = await fetchAnonymousToken();
            writeStoredSession(next.sessionId, next.token);
          }
          if (initRequestRef.current !== requestId) {
            return;
          }
          setSessionCredentials(next.sessionId, next.token);
        } catch (error) {
          if (initRequestRef.current !== requestId) {
            return;
          }
          setSessionCredentials("", "");
          const message =
            error?.name === "AbortError"
              ? "Session bootstrap timed out after 5 seconds."
              : String(error?.message || "Unknown initialization error.");
          console.error("[ARCHON] Token fetch failed:", error);
          setInitError(message);
        } finally {
          if (initRequestRef.current === requestId) {
            setIsInitializing(false);
          }
        }
      })();
    }, [setIsInitializing, setSessionCredentials]);

    useEffect(() => {
      void startInitialization();
      return () => {
        initRequestRef.current += 1;
      };
    }, [startInitialization]);

    useEffect(() => {
      if (isInitializing || !sessionId || !token) {
        return undefined;
      }
      connect(sessionId, token);
      return () => {
        disconnect();
      };
    }, [connect, disconnect, isInitializing, sessionId, token]);

    useEffect(() => {
      let cancelled = false;
      fetch(`${apiBase}/agents/status`)
        .then((response) => response.json())
        .then((payload) => {
          if (cancelled) {
            return;
          }
          setAgentsStatus({
            agents: payload?.agents || {},
            edges: payload?.edges || [],
          });
        })
        .catch(() => {
          if (!cancelled) {
            setAgentsStatus({ agents: {}, edges: [] });
          }
        });
      return () => {
        cancelled = true;
      };
    }, [apiBase]);

    const claims = useMemo(() => decodeJwtClaims(token), [token]);
    const tenantId = String(claims.sub || claims.tenant_id || claims.tid || "anonymous");
    const tier = String(claims.tier || "free");

    useEffect(() => {
      const scope = tier === "enterprise" ? "global" : "tenant";
      if (!token) {
        setLeaderboard({ loading: false, rows: [], scope });
        return;
      }

      let cancelled = false;
      const params = new URLSearchParams({ days: "30", limit: "6", scope });
      if (scope !== "global") {
        params.set("tenant_id", tenantId);
      }
      setLeaderboard((previous) => ({ ...previous, loading: true, scope }));
      fetch(`${apiBase}/analytics/leaderboard?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`leaderboard:${response.status}`);
          }
          return response.json();
        })
        .then((payload) => {
          if (cancelled) {
            return;
          }
          setLeaderboard({
            loading: false,
            rows: Array.isArray(payload) ? payload : [],
            scope,
          });
        })
        .catch(() => {
          if (!cancelled) {
            setLeaderboard({ loading: false, rows: [], scope });
          }
        });
      return () => {
        cancelled = true;
      };
    }, [apiBase, token, tenantId, tier]);

    const workflow = useMemo(() => workflowFromHistory(history), [history]);
    const rounds = useMemo(() => buildDebateRounds(history), [history]);
    const confidence = useMemo(() => {
      for (let idx = history.length - 1; idx >= 0; idx -= 1) {
        const value = Number(history[idx]?.confidence);
        if (Number.isFinite(value)) {
          return Math.max(0, Math.min(100, value));
        }
      }
      return null;
    }, [history]);

    const swarmAgents = useMemo(
      () => deriveSwarmAgents(agentsStatus.agents, agentStates, history),
      [agentsStatus.agents, agentStates, history],
    );
    const swarmEdges = useMemo(() => deriveSwarmEdges(agentsStatus.edges, swarmAgents), [agentsStatus.edges, swarmAgents]);

    const federationActive = useMemo(() => {
      const now = Date.now() / 1000;
      for (let idx = history.length - 1; idx >= 0; idx -= 1) {
        const event = history[idx] || {};
        const type = String(event.type || "").toLowerCase();
        if (!type.includes("federation") && type !== "growth_agent_completed") {
          continue;
        }
        const ts = eventTimestampSeconds(event);
        if (!ts) {
          return true;
        }
        return now - ts < 30;
      }
      return false;
    }, [history]);

    const showMissionControl = mode === "mission_control";
    const hasSession = Boolean(sessionId && token);
    const readyToRender = !isInitializing && !initError && hasSession;
    const displayStatus =
      isInitializing || status === "connecting"
        ? "initializing"
        : status === "connected"
          ? "connected"
          : "disconnected";
    const statusDotStyle =
      displayStatus === "initializing"
        ? {
            background: "#8d99ae",
            boxShadow: "0 0 0 4px rgba(141, 153, 174, 0.25)",
          }
        : undefined;
    const sessionLabel = shortSessionLabel(sessionId);
    const initializingPanel = (
      <div
        style={{
          minHeight: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "24px",
        }}
      >
        <div
          style={{
            display: "grid",
            justifyItems: "center",
            gap: "12px",
            color: "#cbd5e1",
            textAlign: "center",
          }}
        >
          <svg width="44" height="44" viewBox="0 0 44 44" role="img" aria-label="Initializing session">
            <circle cx="22" cy="22" r="17" fill="none" stroke="rgba(100, 116, 139, 0.35)" strokeWidth="4" />
            <path d="M22 5a17 17 0 0 1 17 17" fill="none" stroke="#0d9488" strokeWidth="4" strokeLinecap="round">
              <animateTransform
                attributeName="transform"
                type="rotate"
                from="0 22 22"
                to="360 22 22"
                dur="0.9s"
                repeatCount="indefinite"
              />
            </path>
          </svg>
          <div style={{ fontSize: "15px", fontWeight: 600 }}>Initializing session...</div>
        </div>
      </div>
    );
    const initErrorPanel = (
      <div
        style={{
          minHeight: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "24px",
        }}
      >
        <div
          style={{
            display: "grid",
            justifyItems: "center",
            gap: "8px",
            textAlign: "center",
          }}
        >
          <div style={{ color: "#ef4444", fontWeight: 700 }}>Could not connect to ARCHON API</div>
          <div style={{ color: "#94a3b8", fontSize: "12px", maxWidth: "320px" }}>{initError}</div>
          <button
            type="button"
            onClick={() => {
              void startInitialization();
            }}
            style={{
              marginTop: "8px",
              border: "1px solid rgba(148, 163, 184, 0.35)",
              borderRadius: "999px",
              padding: "8px 14px",
              background: "#0f172a",
              color: "#e2e8f0",
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );

    return (
      <div className={`dashboard-root ${showMissionControl ? "mission-control" : "civilian"}`}>
        <header className="top-bar">
          <div className="brand">ARCHON Mission Control</div>
          <div className="mode-switch">
            <button
              type="button"
              className={showMissionControl ? "" : "active"}
              onClick={() => setMode("civilian")}
            >
              Civilian
            </button>
            <button
              type="button"
              className={showMissionControl ? "active" : ""}
              onClick={() => setMode("mission_control")}
            >
              Mission Control
            </button>
          </div>
          <div className="connection">
            <span className={`status-dot ${displayStatus === "initializing" ? "" : displayStatus}`} style={statusDotStyle} />
            <span>{displayStatus}</span>
          </div>
          <div className="tenant-info">
            tenant: {tenantId} | tier: {tier} | session: {sessionLabel}
          </div>
        </header>

        {readyToRender ? (
          <>
            <div className="main-grid">
              {showMissionControl ? (
                <aside className="left-panel panel">
                  <div className="card" style={{ minHeight: 0, flex: 1 }}>
                    <div className="card-header">Swarm Graph</div>
                    <div className="card-body swarm-box">
                      {window.SwarmGraph ? <window.SwarmGraph agents={swarmAgents} edges={swarmEdges} /> : null}
                    </div>
                  </div>
                  <div className="federation-pulse">
                    <span className={`pulse-dot ${federationActive ? "active" : ""}`} />
                    <span>Federation pulse: {federationActive ? "active" : "idle"}</span>
                  </div>
                </aside>
              ) : null}

              <main className="center-panel">
                <section className="card">
                  <div className="card-header">Active Task DAG</div>
                  <div className="card-body">
                    {window.TaskDAG ? (
                      <window.TaskDAG workflow={workflow} history={history} />
                    ) : (
                      <div className="empty-state">Task DAG component unavailable.</div>
                    )}
                  </div>
                </section>

                <section className="card">
                  <div className="card-body" style={{ height: "100%" }}>
                    {window.DebatePanel && confidence !== null ? (
                      <window.DebatePanel rounds={rounds} confidence={confidence} />
                    ) : (
                      <div className="empty-state">Awaiting task activity...</div>
                    )}
                  </div>
                </section>
              </main>

              {showMissionControl ? (
                <aside className="right-panel panel">
                  <section className="card">
                    <div className="card-header">Cost Meter</div>
                    <div className="card-body">
                      {window.CostMeter ? (
                        <window.CostMeter spent={costState.spent} budget={costState.budget} history={costState.history} />
                      ) : (
                        <div className="empty-state">Cost meter component unavailable.</div>
                      )}
                    </div>
                  </section>

                  <section className="card" style={{ minHeight: 200 }}>
                    <div className="card-header">Performance Leaderboard</div>
                    <div className="card-body">
                      {window.LeaderboardCard ? (
                        <window.LeaderboardCard rows={leaderboard.rows} loading={leaderboard.loading} scope={leaderboard.scope} />
                      ) : (
                        <div className="empty-state">Leaderboard component unavailable.</div>
                      )}
                    </div>
                  </section>

                  <section className="card" style={{ minHeight: 180 }}>
                    <div className="card-header">Approval Queue</div>
                    <div className="card-body">
                      {window.ApprovalQueue ? (
                        <window.ApprovalQueue approvals={pendingApprovals} send={send} />
                      ) : (
                        <div className="empty-state">Approval queue component unavailable.</div>
                      )}
                    </div>
                  </section>

                  <ThoughtLog history={history} />
                </aside>
              ) : null}
            </div>

            <footer className="memory-wrap panel">
              <div className="card-header">Memory Timeline</div>
              <div className="card-body">
                {window.MemoryTimeline ? (
                  <window.MemoryTimeline sessionId={sessionId} apiBase={apiBase} />
                ) : (
                  <div className="empty-state">Memory timeline component unavailable.</div>
                )}
              </div>
            </footer>
          </>
        ) : (
          <div className="main-grid" style={{ display: "block", minHeight: 0 }}>
            <section className="panel" style={{ height: "100%" }}>
              {initError ? initErrorPanel : initializingPanel}
            </section>
          </div>
        )}
      </div>
    );
  }

  window.App = App;
})();
