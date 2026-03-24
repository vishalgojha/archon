(() => {
  const { useEffect, useMemo, useRef, useState } = React;
  const WORKFLOW_OPTIONS = [
    {
      id: "leads",
      label: "Leads",
      description: "Track inbound leads and status.",
      type: "list",
    },
    {
      id: "pipeline",
      label: "Pipeline",
      description: "Visualize stages and progress.",
      type: "kanban",
    },
    {
      id: "tasks",
      label: "Tasks",
      description: "Daily actions and follow-ups.",
      type: "list",
    },
    {
      id: "calendar",
      label: "Calendar",
      description: "Meetings and deadlines.",
      type: "timeline",
    },
    {
      id: "inventory",
      label: "Inventory",
      description: "Assets, listings, or catalog items.",
      type: "table",
    },
    {
      id: "reports",
      label: "Reports",
      description: "KPIs and weekly summaries.",
      type: "summary",
    },
    {
      id: "messages",
      label: "Messages",
      description: "Customer or team communication.",
      type: "list",
    },
    {
      id: "map",
      label: "Map",
      description: "Location-aware context.",
      type: "map",
    },
  ];

  function suggestWorkflowsFromText(text) {
    const lowered = String(text || "").toLowerCase();
    const matches = new Set();
    const rules = [
      { ids: ["leads", "pipeline"], keywords: ["lead", "prospect", "client", "customer"] },
      { ids: ["pipeline"], keywords: ["pipeline", "stage", "deal", "funnel"] },
      { ids: ["tasks"], keywords: ["task", "todo", "follow up", "follow-up", "action"] },
      { ids: ["calendar"], keywords: ["calendar", "schedule", "meeting", "appointment"] },
      { ids: ["inventory"], keywords: ["inventory", "listing", "catalog", "stock", "asset"] },
      { ids: ["reports"], keywords: ["report", "kpi", "analytics", "summary", "dashboard"] },
      { ids: ["messages"], keywords: ["message", "email", "whatsapp", "sms", "chat"] },
      { ids: ["map"], keywords: ["map", "location", "geo", "area", "region"] },
    ];
    rules.forEach((rule) => {
      if (rule.keywords.some((kw) => lowered.includes(kw))) {
        rule.ids.forEach((id) => matches.add(id));
      }
    });
    return matches;
  }

  function getToken() {
    return (
      localStorage.getItem("archon.token") ||
      localStorage.getItem("token") ||
      localStorage.getItem("archon.shell.token") ||
      ""
    ).trim();
  }

  function setToken(value) {
    const cleaned = String(value || "").trim();
    if (cleaned) {
      localStorage.setItem("archon.token", cleaned);
      localStorage.setItem("token", cleaned);
      localStorage.setItem("archon.shell.token", cleaned);
    } else {
      localStorage.removeItem("archon.token");
      localStorage.removeItem("token");
      localStorage.removeItem("archon.shell.token");
    }
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

  async function apiFetch(path, options = {}) {
    const token = getToken();
    const authEnabled = options.auth !== false;
    const headers = {
      ...(options.headers || {}),
    };
    if (!headers["Content-Type"] && options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    if (authEnabled && token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(`${resolveApiBase()}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let payload = null;
      try {
        payload = await response.clone().json();
      } catch (_error) {
        payload = { detail: await response.clone().text() };
      }
      const error = new Error(payload?.detail || `Request failed (${response.status})`);
      error.payload = payload;
      throw error;
    }

    return response;
  }

  function buildBridge({ pack, assetBase }) {
    const token = getToken();
    return {
      token,
      pack,
      assetBase,
      resolveApiBase,
      getToken,
      setToken,
      apiFetch,
      async callTask(goal, context = {}, mode = "debate") {
        const response = await apiFetch("/v1/tasks", {
          method: "POST",
          body: JSON.stringify({ goal, mode, context }),
        });
        return response.json();
      },
      async listApprovals() {
        const response = await apiFetch("/v1/approvals");
        return response.json();
      },
      assetUrl(path) {
        const cleaned = String(path || "").replace(/^\/+/, "");
        const base = String(assetBase || "").replace(/\/$/, "");
        return `${base}/${cleaned}?token=${encodeURIComponent(token)}`;
      },
    };
  }

  function ShellApp({ onClearToken }) {
    const [messages, setMessages] = useState([
      {
        id: "welcome",
        role: "assistant",
        content: "Tell me what you need. I will orchestrate and shape the UI.",
      },
    ]);
    const [input, setInput] = useState("");
    const [isSending, setIsSending] = useState(false);
    const [packStatus, setPackStatus] = useState("idle");
    const [packInfo, setPackInfo] = useState(null);
    const [builderVersion, setBuilderVersion] = useState("v1");
    const [builderTitle, setBuilderTitle] = useState("Custom Workspace");
    const [builderSummary, setBuilderSummary] = useState(
      "Self-evolving operator console tailored to your workflow.",
    );
    const [builderAccent, setBuilderAccent] = useState("#ff6b35");
    const [builderDrawers, setBuilderDrawers] = useState([
      { id: "overview", title: "Overview", type: "summary", description: "" },
    ]);
    const [builderStatus, setBuilderStatus] = useState("");
    const [wizardMode, setWizardMode] = useState(true);
    const [wizardStep, setWizardStep] = useState(0);
    const [wizardBusiness, setWizardBusiness] = useState("");
    const [wizardGoal, setWizardGoal] = useState("");
    const [wizardTitle, setWizardTitle] = useState("Custom Workspace");
    const [wizardAccent, setWizardAccent] = useState("#ff6b35");
    const [wizardWorkflows, setWizardWorkflows] = useState(() => new Set(["leads"]));
    const [wizardNarrative, setWizardNarrative] = useState("");
    const packHostRef = useRef(null);
    const packCleanupRef = useRef(null);
    const packScriptRef = useRef(null);
    const lastVersionRef = useRef(null);

    const statusLabel = useMemo(() => {
      if (packStatus === "loading") {
        return "Loading pack";
      }
      if (packStatus === "loaded") {
        return "Pack live";
      }
      if (packStatus === "error") {
        return "Pack error";
      }
      return "No pack yet";
    }, [packStatus]);

    async function sendMessage() {
      const prompt = input.trim();
      if (!prompt || isSending) {
        return;
      }
      setInput("");
      const userMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: prompt,
      };
      setMessages((prev) => [...prev, userMessage]);
      setIsSending(true);

      try {
        const response = await apiFetch("/v1/tasks", {
          method: "POST",
          body: JSON.stringify({ goal: prompt, mode: "debate", context: {} }),
        });
        const payload = await response.json();
        setMessages((prev) => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            content: payload?.final_answer || "No response.",
          },
        ]);
      } catch (error) {
        setMessages((prev) => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            content: `Error: ${error.message || "Unable to reach the runtime."}`,
          },
        ]);
      } finally {
        setIsSending(false);
      }
    }

    async function loadPack() {
      const token = getToken();
      if (!token) {
        return;
      }

      setPackStatus("loading");
      try {
        const response = await apiFetch("/v1/ui-packs/active");
        const payload = await response.json();
        if (payload.status !== "ok" || !payload.active) {
          setPackStatus("idle");
          setPackInfo(null);
          lastVersionRef.current = null;
          return;
        }
        const { active, asset_base: assetBase } = payload;
        if (lastVersionRef.current === active.version) {
          setPackStatus("loaded");
          setPackInfo(active);
          return;
        }
        setPackInfo(active);

        if (packCleanupRef.current) {
          try {
            packCleanupRef.current();
          } catch (_error) {}
          packCleanupRef.current = null;
        }
        if (packScriptRef.current) {
          packScriptRef.current.remove();
          packScriptRef.current = null;
        }

        const entry = String(active.entrypoint || "").replace(/^\/+/, "");
        const script = document.createElement("script");
        script.src = `${assetBase.replace(/\/$/, "")}/${entry}?token=${encodeURIComponent(token)}`;
        script.async = true;
        script.onload = () => {
          const bridge = buildBridge({ pack: active, assetBase });
          window.ARCHON_BRIDGE = bridge;
          window.ARCHON_ASSET_BASE = assetBase;
          window.ARCHON_ASSET_TOKEN = token;
          if (window.ARCHON_PACK && typeof window.ARCHON_PACK.mount === "function") {
            const cleanup = window.ARCHON_PACK.mount({
              root: packHostRef.current,
              bridge,
              pack: active,
            });
            if (typeof cleanup === "function") {
              packCleanupRef.current = cleanup;
            }
            lastVersionRef.current = active.version;
            setPackStatus("loaded");
          } else {
            setPackStatus("error");
          }
        };
        script.onerror = () => {
          lastVersionRef.current = null;
          setPackStatus("error");
        };
        document.head.appendChild(script);
        packScriptRef.current = script;
      } catch (_error) {
        lastVersionRef.current = null;
        setPackStatus("error");
      }
    }

    async function buildPack() {
      setBuilderStatus("Building pack...");
      try {
        const response = await apiFetch("/v1/ui-packs/build", {
          method: "POST",
          body: JSON.stringify({
            version: builderVersion.trim() || "v1",
            auto_approve: true,
            blueprint: {
              title: builderTitle,
              summary: builderSummary,
              theme: { accent: builderAccent },
              drawers: builderDrawers,
            },
          }),
        });
        await response.json();
        setBuilderStatus("Pack built. Registering...");
        await apiFetch("/v1/ui-packs/register", {
          method: "POST",
          body: JSON.stringify({ version: builderVersion.trim() || "v1", auto_approve: true }),
        });
        setBuilderStatus("Registered. Activating...");
        await apiFetch("/v1/ui-packs/activate", {
          method: "POST",
          body: JSON.stringify({ version: builderVersion.trim() || "v1", auto_approve: true }),
        });
        setBuilderStatus("Pack active.");
        await loadPack();
      } catch (error) {
        setBuilderStatus(`Error: ${error.message || "Unable to build pack."}`);
      }
    }

    function buildBlueprintFromWizard() {
      const selected = WORKFLOW_OPTIONS.filter((opt) => wizardWorkflows.has(opt.id));
      const drawers =
        selected.length > 0
          ? selected.map((opt) => ({
              id: opt.id,
              title: opt.label,
              type: opt.type,
              description: opt.description,
            }))
          : [
              {
                id: "overview",
                title: "Overview",
                type: "summary",
                description: "Describe your workflow and desired outcomes.",
              },
            ];

      const summaryParts = [];
      if (wizardBusiness.trim()) {
        summaryParts.push(`Business: ${wizardBusiness.trim()}.`);
      }
      if (wizardGoal.trim()) {
        summaryParts.push(`Primary goal: ${wizardGoal.trim()}.`);
      }
      if (wizardNarrative.trim()) {
        summaryParts.push(`Workflow notes: ${wizardNarrative.trim()}.`);
      }
      return {
        title: wizardTitle.trim() || "Custom Workspace",
        summary:
          summaryParts.join(" ") || "Self-evolving operator console tailored to your workflow.",
        theme: { accent: wizardAccent },
        drawers,
      };
    }

    useEffect(() => {
      loadPack();
      const interval = setInterval(loadPack, 15000);
      return () => clearInterval(interval);
    }, []);

    return (
      <div className="shell-root">
        <div className="shell-topbar">
          <div className="brand">
            ARCHON Shell <span className="brand-pill">Self-Evolving</span>
          </div>
          <div className="shell-status">
            <span className={`status-dot ${packStatus === "loaded" ? "ok" : ""}`} />
            {statusLabel}
            <button type="button" onClick={onClearToken}>
              Clear Token
            </button>
          </div>
        </div>
        <div className="shell-layout">
          <div className="panel">
            <div className="chat-header">
              <h2>Agentic Chat</h2>
              <span className="pack-status">{statusLabel}</span>
            </div>
            <div className="chat-feed">
              {messages.map((msg) => (
                <div key={msg.id} className={`chat-message ${msg.role}`}>
                  <div className="role">{msg.role}</div>
                  <div className="content">{msg.content}</div>
                </div>
              ))}
            </div>
            <div className="chat-input">
              <textarea
                placeholder="Describe the goal or requirement..."
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendMessage();
                  }
                }}
              />
              <button type="button" onClick={sendMessage} disabled={isSending || !input.trim()}>
                {isSending ? "Running..." : "Send"}
              </button>
            </div>
          </div>
          <div className="panel">
            <div className="drawer-header">
              <h2>Custom Drawers</h2>
              <span className="pack-status">
                {packInfo ? `v${packInfo.version}` : "Awaiting pack"}
              </span>
            </div>
            <div className="drawer-host" ref={packHostRef}>
              {!packInfo && (
                <div className="pack-status">
                  <p>No UI pack active yet. Use the builder below to generate one.</p>
                  <div className="builder-toggle">
                    <button
                      type="button"
                      className={wizardMode ? "active" : ""}
                      onClick={() => setWizardMode(true)}
                    >
                      Guided setup
                    </button>
                    <button
                      type="button"
                      className={!wizardMode ? "active" : ""}
                      onClick={() => setWizardMode(false)}
                    >
                      Manual builder
                    </button>
                  </div>
                  {wizardMode ? (
                    <div className="wizard">
                      <div className="wizard-steps">
                        {["Tell us about you", "Describe work", "Choose workflows", "Preview"].map(
                          (label, idx) => (
                            <div
                              key={label}
                              className={`wizard-step ${
                                wizardStep === idx ? "active" : ""
                              }`}
                            >
                              <span>{idx + 1}</span>
                              {label}
                            </div>
                          ),
                        )}
                      </div>
                      {wizardStep === 0 && (
                        <div className="wizard-panel">
                          <label>
                            What kind of business is this?
                            <input
                              type="text"
                              value={wizardBusiness}
                              onChange={(event) => setWizardBusiness(event.target.value)}
                              placeholder="Example: Real estate agency"
                            />
                          </label>
                          <label>
                            What outcome do you want first?
                            <input
                              type="text"
                              value={wizardGoal}
                              onChange={(event) => setWizardGoal(event.target.value)}
                              placeholder="Example: Close more qualified leads"
                            />
                          </label>
                        </div>
                      )}
                      {wizardStep === 1 && (
                        <div className="wizard-panel">
                          <label>
                            Describe your workflow in plain language
                            <textarea
                              rows="4"
                              value={wizardNarrative}
                              onChange={(event) => setWizardNarrative(event.target.value)}
                              placeholder="Example: We manage inbound leads, schedule calls, and keep track of listings."
                            />
                          </label>
                          <button
                            type="button"
                            className="builder-primary"
                            onClick={() => {
                              const suggestions = suggestWorkflowsFromText(wizardNarrative);
                              if (suggestions.size) {
                                setWizardWorkflows(suggestions);
                              }
                            }}
                          >
                            Suggest workflows
                          </button>
                        </div>
                      )}
                      {wizardStep === 2 && (
                        <div className="wizard-panel">
                          <p>Select the workflows you want in your workspace:</p>
                          <div className="wizard-options">
                            {WORKFLOW_OPTIONS.map((option) => (
                              <label key={option.id} className="wizard-option">
                                <input
                                  type="checkbox"
                                  checked={wizardWorkflows.has(option.id)}
                                  onChange={(event) => {
                                    const next = new Set(wizardWorkflows);
                                    if (event.target.checked) {
                                      next.add(option.id);
                                    } else {
                                      next.delete(option.id);
                                    }
                                    setWizardWorkflows(next);
                                  }}
                                />
                                <div>
                                  <strong>{option.label}</strong>
                                  <span>{option.description}</span>
                                </div>
                              </label>
                            ))}
                          </div>
                        </div>
                      )}
                      {wizardStep === 3 && (
                        <div className="wizard-panel">
                          <label>
                            Workspace name
                            <input
                              type="text"
                              value={wizardTitle}
                              onChange={(event) => setWizardTitle(event.target.value)}
                            />
                          </label>
                          <label>
                            Accent color
                            <input
                              type="color"
                              value={wizardAccent}
                              onChange={(event) => setWizardAccent(event.target.value)}
                            />
                          </label>
                          <label>
                            Version label
                            <input
                              type="text"
                              value={builderVersion}
                              onChange={(event) => setBuilderVersion(event.target.value)}
                              placeholder="v1"
                            />
                          </label>
                          <div className="wizard-preview">
                            <strong>Preview</strong>
                            <p>{buildBlueprintFromWizard().summary}</p>
                            <ul>
                              {buildBlueprintFromWizard().drawers.map((drawer) => (
                                <li key={drawer.id}>
                                  {drawer.title} · {drawer.type}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      )}
                      <div className="wizard-actions">
                        <button
                          type="button"
                          onClick={() => setWizardStep((step) => Math.max(step - 1, 0))}
                          disabled={wizardStep === 0}
                        >
                          Back
                        </button>
                        {wizardStep < 3 ? (
                          <button
                            type="button"
                            className="builder-primary"
                            onClick={() => setWizardStep((step) => Math.min(step + 1, 3))}
                          >
                            Continue
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="builder-primary"
                            onClick={async () => {
                              const blueprint = buildBlueprintFromWizard();
                              setBuilderTitle(blueprint.title);
                              setBuilderSummary(blueprint.summary);
                              setBuilderAccent(blueprint.theme.accent || builderAccent);
                              setBuilderDrawers(blueprint.drawers);
                              setWizardMode(false);
                              await buildPack();
                            }}
                          >
                            Build Workspace
                          </button>
                        )}
                      </div>
                    </div>
                  ) : null}
                  <div className="builder-grid">
                    <label>
                      Version
                      <input
                        type="text"
                        value={builderVersion}
                        onChange={(event) => setBuilderVersion(event.target.value)}
                      />
                    </label>
                    <label>
                      Workspace name
                      <input
                        type="text"
                        value={builderTitle}
                        onChange={(event) => setBuilderTitle(event.target.value)}
                      />
                    </label>
                    <label>
                      Summary
                      <input
                        type="text"
                        value={builderSummary}
                        onChange={(event) => setBuilderSummary(event.target.value)}
                      />
                    </label>
                    <label>
                      Accent color
                      <input
                        type="color"
                        value={builderAccent}
                        onChange={(event) => setBuilderAccent(event.target.value)}
                      />
                    </label>
                  </div>
                  <div className="builder-drawers">
                    {builderDrawers.map((drawer, index) => (
                      <div key={drawer.id || index} className="builder-drawer">
                        <input
                          type="text"
                          placeholder="Drawer title"
                          value={drawer.title}
                          onChange={(event) => {
                            const next = [...builderDrawers];
                            next[index] = { ...drawer, title: event.target.value };
                            setBuilderDrawers(next);
                          }}
                        />
                        <select
                          value={drawer.type}
                          onChange={(event) => {
                            const next = [...builderDrawers];
                            next[index] = { ...drawer, type: event.target.value };
                            setBuilderDrawers(next);
                          }}
                        >
                          <option value="summary">Summary</option>
                          <option value="list">List</option>
                          <option value="table">Table</option>
                          <option value="kanban">Kanban</option>
                          <option value="timeline">Timeline</option>
                          <option value="map">Map</option>
                          <option value="notes">Notes</option>
                        </select>
                        <input
                          type="text"
                          placeholder="Short description"
                          value={drawer.description || ""}
                          onChange={(event) => {
                            const next = [...builderDrawers];
                            next[index] = { ...drawer, description: event.target.value };
                            setBuilderDrawers(next);
                          }}
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const next = builderDrawers.filter((_, i) => i !== index);
                            setBuilderDrawers(next.length ? next : builderDrawers);
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        setBuilderDrawers((prev) => [
                          ...prev,
                          {
                            id: `drawer-${prev.length + 1}`,
                            title: `Drawer ${prev.length + 1}`,
                            type: "list",
                            description: "",
                          },
                        ])
                      }
                    >
                      Add drawer
                    </button>
                  </div>
                    <button type="button" className="builder-primary" onClick={buildPack}>
                      Build & Activate Pack
                    </button>
                  {builderStatus ? <p className="pack-status">{builderStatus}</p> : null}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  function ShellRoot() {
    const [tokenInput, setTokenInput] = useState("");
    const [hasToken, setHasToken] = useState(Boolean(getToken()));

    if (!hasToken) {
      return (
        <div className="auth-gate">
          <div className="auth-card">
            <h2>ARCHON Shell Auth</h2>
            <p>Paste a tenant JWT to unlock the shell and UI pack loader.</p>
            <input
              type="password"
              placeholder="Paste JWT token"
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
            />
            <button
              type="button"
              onClick={() => {
                setToken(tokenInput);
                setHasToken(Boolean(tokenInput.trim()));
              }}
              disabled={!tokenInput.trim()}
            >
              Continue
            </button>
          </div>
        </div>
      );
    }

    return (
      <ShellApp
        onClearToken={() => {
          setToken("");
          setHasToken(false);
        }}
      />
    );
  }

  const root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(
    <React.StrictMode>
      <ShellRoot />
    </React.StrictMode>,
  );
})();
