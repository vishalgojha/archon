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

  function clearStoredSession() {
    safeStorageSet("archon.session_id", "");
    safeStorageSet("archon.token", "");
  }

  async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 5000) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      return response;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function fetchAnonymousToken() {
    const response = await fetchJsonWithTimeout("/webchat/token", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
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
  }

  async function validateStoredSession(sessionId, token) {
    if (!sessionId || !token) {
      return false;
    }
    const url = `/webchat/session/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(token)}`;
    const response = await fetchJsonWithTimeout(url, { method: "GET" });
    if (response.ok) {
      return true;
    }
    if (response.status === 401 || response.status === 403 || response.status === 404) {
      return false;
    }
    throw new Error(`Session validation failed with HTTP ${response.status}`);
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

  function friendlyStatusLabel(status) {
    if (status === "connected") {
      return "Online";
    }
    if (status === "initializing" || status === "connecting") {
      return "Starting up";
    }
    if (status === "error") {
      return "Needs attention";
    }
    return "Offline";
  }

  function buildCivilianUpdates(history) {
    return history
      .slice(-6)
      .reverse()
      .map((event, idx) => {
        const type = String(event?.type || "update").toLowerCase();
        const agent = String(event?.agent || event?.agent_name || "").trim();
        if (type === "approval_required") {
          return {
            id: `update-${idx}`,
            title: "Approval needed",
            detail: String(event?.action || event?.action_type || "ARCHON is waiting for approval."),
          };
        }
        if (type === "approval_result" || type === "approval_resolved") {
          return {
            id: `update-${idx}`,
            title: "Approval updated",
            detail: String(event?.action || "A queued approval was updated."),
          };
        }
        if (type === "agent_start") {
          return {
            id: `update-${idx}`,
            title: `${agent || "An agent"} started work`,
            detail: "ARCHON is actively processing the current task.",
          };
        }
        if (type === "agent_end" || type === "growth_agent_completed") {
          return {
            id: `update-${idx}`,
            title: `${agent || "An agent"} finished a step`,
            detail: shortJson(event?.output || event?.result || event?.payload || event, 160),
          };
        }
        if (type === "done" || type === "task_result") {
          return {
            id: `update-${idx}`,
            title: "A result is ready",
            detail: shortJson(event?.message || event?.payload || event, 160),
          };
        }
        return {
          id: `update-${idx}`,
          title: type.replace(/_/g, " ") || "Update",
          detail: shortJson(event?.payload || event, 160),
        };
      });
  }

  function App() {
    const archon = window.useARCHONContext ? window.useARCHONContext() : {};
    const status = archon?.status || "disconnected";
    const token = String(archon?.token || "").trim();
    const sessionId = String(archon?.sessionId || "").trim();
    const lastCloseCode = Number(archon?.lastCloseCode || 0);
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

    const [mode, setMode] = useState(() => safeStorageGet("archon.dashboard.mode") || "civilian");
    const [swarmExpanded, setSwarmExpanded] = useState(false);
    const [selectedSwarmAgentId, setSelectedSwarmAgentId] = useState("orchestrator");
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
          const hasStoredSession = Boolean(next.token && next.sessionId);
          if (hasStoredSession) {
            const isValid = await validateStoredSession(next.sessionId, next.token);
            if (!isValid) {
              clearStoredSession();
              next = { sessionId: "", token: "" };
            }
          }
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
      if (isInitializing || (lastCloseCode !== 4001 && lastCloseCode !== 4003)) {
        return;
      }
      clearStoredSession();
      setSessionCredentials("", "");
      void startInitialization();
    }, [isInitializing, lastCloseCode, setSessionCredentials, startInitialization]);

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
    const selectedSwarmAgent = useMemo(() => {
      return swarmAgents.find((agent) => agent.id === selectedSwarmAgentId) || swarmAgents[0] || null;
    }, [selectedSwarmAgentId, swarmAgents]);
    const selectedSwarmNeighbors = useMemo(() => {
      const sourceId = selectedSwarmAgent?.id || "";
      if (!sourceId) {
        return { upstream: [], downstream: [] };
      }
      const upstream = [];
      const downstream = [];
      swarmEdges.forEach((edge) => {
        if (edge.target === sourceId) {
          upstream.push(edge.source);
        }
        if (edge.source === sourceId) {
          downstream.push(edge.target);
        }
      });
      return {
        upstream: [...new Set(upstream)],
        downstream: [...new Set(downstream)],
      };
    }, [selectedSwarmAgent, swarmEdges]);
    const swarmSummary = useMemo(() => {
      return swarmAgents.reduce(
        (summary, agent) => {
          const key = String(agent.status || "idle").toLowerCase();
          summary.total += 1;
          summary[key] = Number(summary[key] || 0) + 1;
          return summary;
        },
        { total: 0, idle: 0, thinking: 0, done: 0, error: 0 },
      );
    }, [swarmAgents]);

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
    const recentUpdates = useMemo(() => buildCivilianUpdates(history), [history]);
    const latestAnswer = useMemo(() => {
      for (let idx = history.length - 1; idx >= 0; idx -= 1) {
        const event = history[idx] || {};
        const candidate =
          event?.message?.content ||
          event?.payload?.final_answer ||
          event?.final_answer ||
          event?.content ||
          "";
        if (candidate) {
          return String(candidate);
        }
      }
      return "";
    }, [history]);
    const civilianActions = useMemo(() => {
      const actions = [];
      if (pendingApprovals.length > 0) {
        actions.push(`Review ${pendingApprovals.length} pending approval${pendingApprovals.length === 1 ? "" : "s"}.`);
      }
      if (displayStatus !== "connected") {
        actions.push("Reconnect the dashboard before relying on live activity.");
      }
      if (costState.budget > 0 && costState.spent / costState.budget >= 0.8) {
        actions.push("Budget usage is above 80%. Check limits before the next run.");
      }
      if (swarmSummary.thinking > 0) {
        actions.push(`${swarmSummary.thinking} agent${swarmSummary.thinking === 1 ? " is" : "s are"} currently working.`);
      }
      if (!actions.length) {
        actions.push("Everything is stable. You can let ARCHON continue and only step in for approvals.");
      }
      return actions.slice(0, 4);
    }, [costState.budget, costState.spent, displayStatus, pendingApprovals.length, swarmSummary.thinking]);
    const renderSwarmGraph = (expanded = false) => (
      <>
        <div className={`card-header ${expanded ? "card-header-modal" : ""}`}>
          <span>Swarm Graph</span>
          <div className="card-actions">
            <span className="card-meta">{swarmSummary.total} agents</span>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setSwarmExpanded((current) => !current)}
            >
              {expanded ? "Collapse" : "Expand"}
            </button>
          </div>
        </div>
        <div className={`card-body swarm-box ${expanded ? "swarm-box-expanded" : ""}`}>
          {window.SwarmGraph ? (
            <window.SwarmGraph
              agents={swarmAgents}
              edges={swarmEdges}
              selectedAgentId={selectedSwarmAgent?.id || ""}
              onNodeClick={(node) => setSelectedSwarmAgentId(String(node?.id || ""))}
            />
          ) : null}
        </div>
        <div className="swarm-inline-meta">
          <div className="swarm-summary">
            <span>thinking {swarmSummary.thinking}</span>
            <span>done {swarmSummary.done}</span>
            <span>idle {swarmSummary.idle}</span>
            <span>error {swarmSummary.error}</span>
          </div>
          {selectedSwarmAgent ? (
            <div className="swarm-selected-chip">
              selected: {selectedSwarmAgent.label || selectedSwarmAgent.id} ({selectedSwarmAgent.status || "idle"})
            </div>
          ) : null}
        </div>
      </>
    );
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
          <div className="brand">{showMissionControl ? "ARCHON Mission Control" : "ARCHON Overview"}</div>
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
            {showMissionControl
              ? `tenant: ${tenantId} | tier: ${tier} | session: ${sessionLabel}`
              : `session ${sessionLabel} | ${pendingApprovals.length > 0 ? "approval waiting" : "no blockers"}`}
          </div>
        </header>

        {readyToRender ? (
          <>
            <div
              className="main-grid"
              style={
                showMissionControl
                  ? undefined
                  : {
                      gridTemplateColumns: "1fr",
                      gap: 12,
                    }
              }
            >
              {showMissionControl ? (
                <aside className="left-panel panel">
                  <div className="card" style={{ minHeight: 0, flex: 1 }}>
                    {renderSwarmGraph(false)}
                  </div>
                  <div className="federation-pulse">
                    <span className={`pulse-dot ${federationActive ? "active" : ""}`} />
                    <span>Federation pulse: {federationActive ? "active" : "idle"}</span>
                  </div>
                </aside>
              ) : null}

              {showMissionControl ? (
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
              ) : (
                <main
                  className="panel"
                  style={{
                    padding: 18,
                    overflow: "auto",
                    display: "grid",
                    gap: 14,
                  }}
                >
                  <section
                    className="card"
                    style={{
                      background: "linear-gradient(135deg, rgba(15,118,110,0.18), rgba(37,48,65,0.34))",
                      borderRadius: 18,
                    }}
                  >
                    <div className="card-body" style={{ height: "auto", padding: 20 }}>
                      <div style={{ fontSize: 12, letterSpacing: "0.16em", textTransform: "uppercase", color: "#8bd3cb" }}>
                        Operations Overview
                      </div>
                      <h1 style={{ margin: "10px 0 8px", fontSize: "clamp(28px, 4vw, 40px)" }}>
                        {friendlyStatusLabel(displayStatus)} and {pendingApprovals.length > 0 ? "waiting on a decision" : "ready to continue"}.
                      </h1>
                      <p style={{ margin: 0, maxWidth: 760, color: "#c6d0dc", lineHeight: 1.7 }}>
                        {pendingApprovals.length > 0
                          ? `ARCHON has ${pendingApprovals.length} approval${pendingApprovals.length === 1 ? "" : "s"} queued. Review them here without opening the technical trace.`
                          : "No approvals are blocking work right now. Use Mission Control only when you need the deep technical trace."}
                      </p>
                    </div>
                  </section>

                  <section
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                      gap: 12,
                    }}
                  >
                    {[
                      { label: "System", value: friendlyStatusLabel(displayStatus) },
                      { label: "Pending approvals", value: String(pendingApprovals.length) },
                      { label: "Agents working", value: String(swarmSummary.thinking) },
                      {
                        label: "Budget used",
                        value: costState.budget > 0
                          ? `${Math.round((costState.spent / costState.budget) * 100)}%`
                          : `$${Number(costState.spent || 0).toFixed(2)}`,
                      },
                    ].map((card) => (
                      <div
                        key={card.label}
                        className="card"
                        style={{ padding: 16, minHeight: "unset" }}
                      >
                        <div style={{ fontSize: 12, color: "#8fa0b8", textTransform: "uppercase", letterSpacing: "0.12em" }}>
                          {card.label}
                        </div>
                        <div style={{ marginTop: 10, fontSize: 28, fontWeight: 700 }}>{card.value}</div>
                      </div>
                    ))}
                  </section>

                  <section
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
                      gap: 12,
                    }}
                  >
                    <section className="card">
                      <div className="card-header">What Needs Attention</div>
                      <div className="card-body" style={{ height: "auto", padding: 16 }}>
                        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 10, color: "#d7deea" }}>
                          {civilianActions.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    </section>

                    <section className="card">
                      <div className="card-header">Pending Approvals</div>
                      <div className="card-body" style={{ height: "auto", padding: 16, display: "grid", gap: 12 }}>
                        {pendingApprovals.length === 0 ? (
                          <div className="empty-state">Nothing is waiting for approval.</div>
                        ) : (
                          pendingApprovals.slice(0, 4).map((approval) => {
                            const requestId = String(approval.action_id || approval.request_id || "");
                            const action = String(approval.action || approval.action_type || "action");
                            return (
                              <div
                                key={requestId}
                                style={{
                                  display: "grid",
                                  gap: 8,
                                  padding: 14,
                                  borderRadius: 14,
                                  border: "1px solid var(--border)",
                                  background: "rgba(15, 23, 42, 0.36)",
                                }}
                              >
                                <div style={{ fontWeight: 600 }}>{action}</div>
                                <div style={{ fontSize: 13, color: "#9fb0c8" }}>
                                  Request ID: {requestId || "pending"}
                                </div>
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                  <button
                                    type="button"
                                    className="secondary-button"
                                    onClick={() => send({ type: "approve", request_id: requestId })}
                                  >
                                    Approve
                                  </button>
                                  <button
                                    type="button"
                                    className="secondary-button"
                                    onClick={() => send({ type: "deny", request_id: requestId })}
                                  >
                                    Deny
                                  </button>
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </section>
                  </section>

                  <section
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
                      gap: 12,
                    }}
                  >
                    <section className="card">
                      <div className="card-header">Recent Updates</div>
                      <div className="card-body" style={{ height: "auto", padding: 16, display: "grid", gap: 12 }}>
                        {recentUpdates.length === 0 ? (
                          <div className="empty-state">No recent updates yet.</div>
                        ) : (
                          recentUpdates.map((item) => (
                            <div key={item.id} style={{ display: "grid", gap: 4 }}>
                              <div style={{ fontWeight: 600 }}>{item.title}</div>
                              <div style={{ color: "#9fb0c8", fontSize: 14 }}>{item.detail}</div>
                            </div>
                          ))
                        )}
                      </div>
                    </section>

                    <section className="card">
                      <div className="card-header">Latest Answer</div>
                      <div className="card-body" style={{ height: "auto", padding: 16 }}>
                        {latestAnswer ? (
                          <div style={{ color: "#d7deea", lineHeight: 1.7 }}>
                            {latestAnswer.length > 420 ? `${latestAnswer.slice(0, 420)}...` : latestAnswer}
                          </div>
                        ) : (
                          <div className="empty-state">ARCHON has not completed a response yet.</div>
                        )}
                      </div>
                    </section>
                  </section>
                </main>
              )}

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

            {showMissionControl ? (
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
            ) : (
              <footer
                className="memory-wrap panel"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "0 18px",
                  color: "#9fb0c8",
                }}
              >
                <span>Session {sessionLabel}</span>
                <span>{pendingApprovals.length > 0 ? "Waiting for approval" : "No blockers"}</span>
                <span>{swarmSummary.thinking > 0 ? `${swarmSummary.thinking} agent(s) active` : "No active agents"}</span>
              </footer>
            )}
            {showMissionControl && swarmExpanded ? (
              <div className="graph-modal-backdrop" onClick={() => setSwarmExpanded(false)}>
                <section
                  className="graph-modal panel"
                  role="dialog"
                  aria-modal="true"
                  aria-label="Expanded swarm graph"
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className="graph-modal-main card">{renderSwarmGraph(true)}</div>
                  <aside className="graph-modal-sidebar panel">
                    <div className="card-header">
                      <span>Agent Details</span>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => setSwarmExpanded(false)}
                      >
                        Close
                      </button>
                    </div>
                    <div className="graph-modal-sidebar-body">
                      {selectedSwarmAgent ? (
                        <>
                          <div className="graph-agent-title">{selectedSwarmAgent.label || selectedSwarmAgent.id}</div>
                          <div className={`graph-agent-status status-${selectedSwarmAgent.status || "idle"}`}>
                            {selectedSwarmAgent.status || "idle"}
                          </div>
                          <div className="graph-detail-block">
                            <h4>Connections</h4>
                            <p>upstream: {selectedSwarmNeighbors.upstream.join(", ") || "none"}</p>
                            <p>downstream: {selectedSwarmNeighbors.downstream.join(", ") || "none"}</p>
                          </div>
                        </>
                      ) : (
                        <div className="empty-state">Select an agent node to inspect its position in the swarm.</div>
                      )}
                      <div className="graph-detail-block">
                        <h4>Swarm Summary</h4>
                        <p>Total agents: {swarmSummary.total}</p>
                        <p>Thinking: {swarmSummary.thinking}</p>
                        <p>Done: {swarmSummary.done}</p>
                        <p>Idle: {swarmSummary.idle}</p>
                        <p>Error: {swarmSummary.error}</p>
                      </div>
                    </div>
                  </aside>
                </section>
              </div>
            ) : null}
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
