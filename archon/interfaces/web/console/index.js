(() => {
  const { useMemo, useState } = React;

  function getToken() {
    return (
      localStorage.getItem("archon.token") ||
      localStorage.getItem("token") ||
      localStorage.getItem("archon.console.token") ||
      ""
    ).trim();
  }

  function setToken(value) {
    const cleaned = String(value || "").trim();
    if (cleaned) {
      localStorage.setItem("archon.token", cleaned);
      localStorage.setItem("token", cleaned);
      localStorage.setItem("archon.console.token", cleaned);
    } else {
      localStorage.removeItem("archon.token");
      localStorage.removeItem("token");
      localStorage.removeItem("archon.console.token");
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

  async function consoleApiFetch(path, options = {}) {
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

  window.consoleApiFetch = consoleApiFetch;
  window.resolveConsoleApiBase = resolveApiBase;

  function TokenGate({ children }) {
    const [tokenInput, setTokenInput] = useState("");
    const [hasToken, setHasToken] = useState(Boolean(getToken()));

    if (hasToken) {
      return (
        <>
          <div className="token-strip">
            <span>Authenticated</span>
            <button
              type="button"
              onClick={() => {
                setToken("");
                setHasToken(false);
              }}
            >
              Clear Token
            </button>
          </div>
          {children}
        </>
      );
    }

    return (
      <div className="auth-gate">
        <h2>ARCHON Console Auth</h2>
        <p>Enter tenant JWT to access console endpoints.</p>
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
    );
  }

  const TABS = [
    { key: "agent", label: "Agent Editor" },
    { key: "byok", label: "BYOK Manager" },
    { key: "api", label: "API Explorer" },
    { key: "embed", label: "Embed Generator" },
  ];

  function ConsoleApp() {
    const [activeTab, setActiveTab] = useState("agent");

    const ActiveComponent = useMemo(() => {
      if (activeTab === "agent") {
        return window.AgentEditor;
      }
      if (activeTab === "byok") {
        return window.BYOKManager;
      }
      if (activeTab === "api") {
        return window.APIExplorer;
      }
      return window.EmbedGenerator;
    }, [activeTab]);

    return (
      <div className="console-root">
        <header className="console-header">
          <h1>ARCHON Console</h1>
          <div className="tab-row">
            {TABS.map((tab) => (
              <button
                type="button"
                key={tab.key}
                className={activeTab === tab.key ? "active" : ""}
                onClick={() => setActiveTab(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </header>

        <main className="console-main">{ActiveComponent ? <ActiveComponent /> : null}</main>
      </div>
    );
  }

  const root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(
    <React.StrictMode>
      <TokenGate>
        <ConsoleApp />
      </TokenGate>
    </React.StrictMode>,
  );
})();
