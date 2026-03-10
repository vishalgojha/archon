(() => {
  const { useEffect, useMemo, useState } = React;

  const FALLBACK_PROVIDERS = [
    "anthropic",
    "openai",
    "gemini",
    "mistral",
    "groq",
    "together",
    "fireworks",
    "openrouter",
    "ollama",
  ];

  function BYOKManager() {
    const [providers, setProviders] = useState([]);
    const [keys, setKeys] = useState({});
    const [budget, setBudget] = useState({
      daily_limit_usd: "",
      monthly_limit_usd: "",
      per_request_limit_usd: "",
    });
    const [statusByProvider, setStatusByProvider] = useState({});
    const [error, setError] = useState("");
    const [status, setStatus] = useState("");

    const providerRows = useMemo(() => {
      if (providers.length > 0) {
        return providers;
      }
      return FALLBACK_PROVIDERS.map((name) => ({ name, status: "unknown", has_key: false, detail: "" }));
    }, [providers]);

    const loadProviders = async () => {
      setError("");
      try {
        const response = await window.consoleApiFetch("/console/providers/validate");
        const payload = await response.json();
        setProviders(Array.isArray(payload.providers) ? payload.providers : []);
      } catch (loadError) {
        setError(String(loadError.message || loadError));
      }
    };

    useEffect(() => {
      loadProviders();
    }, []);

    const saveProvider = async (name) => {
      setStatus("");
      setError("");
      const value = String(keys[name] || "").trim();
      try {
        await window.consoleApiFetch("/console/config", {
          method: "POST",
          body: JSON.stringify({
            providers: {
              [name]: {
                api_key: value || null,
              },
            },
            budget: {},
          }),
        });
        setStatus(`Saved key config for ${name}.`);
        if (!value) {
          setKeys((prev) => ({ ...prev, [name]: "" }));
        }
        await loadProviders();
      } catch (saveError) {
        setError(String(saveError.message || saveError));
      }
    };

    const deleteProvider = async (name) => {
      setStatus("");
      setError("");
      try {
        await window.consoleApiFetch("/console/config", {
          method: "POST",
          body: JSON.stringify({
            providers: {
              [name]: {
                api_key: null,
              },
            },
            budget: {},
          }),
        });
        setKeys((prev) => ({ ...prev, [name]: "" }));
        setStatus(`Removed key config for ${name}.`);
        await loadProviders();
      } catch (deleteError) {
        setError(String(deleteError.message || deleteError));
      }
    };

    const testProvider = async (name) => {
      setStatus("");
      setError("");
      try {
        const response = await window.consoleApiFetch(`/console/providers/test/${encodeURIComponent(name)}`, {
          method: "POST",
        });
        const payload = await response.json();
        setStatusByProvider((prev) => ({ ...prev, [name]: payload }));
        setStatus(`Test complete for ${name}: ${payload.status}`);
      } catch (testError) {
        setError(String(testError.message || testError));
      }
    };

    const saveBudget = async () => {
      setStatus("");
      setError("");
      const parsedBudget = {};
      if (budget.daily_limit_usd !== "") {
        parsedBudget.daily_limit_usd = Number(budget.daily_limit_usd);
      }
      if (budget.monthly_limit_usd !== "") {
        parsedBudget.monthly_limit_usd = Number(budget.monthly_limit_usd);
      }
      if (budget.per_request_limit_usd !== "") {
        parsedBudget.per_request_limit_usd = Number(budget.per_request_limit_usd);
      }

      try {
        await window.consoleApiFetch("/console/config", {
          method: "POST",
          body: JSON.stringify({ providers: {}, budget: parsedBudget }),
        });
        setStatus("Budget configuration saved.");
      } catch (budgetError) {
        setError(String(budgetError.message || budgetError));
      }
    };

    return (
      <div className="console-pane byok-pane">
        <h2>BYOK Manager</h2>

        <div className="provider-list">
          {providerRows.map((provider) => {
            const name = provider.name;
            const testResult = statusByProvider[name];
            const badgeClass = provider.status === "healthy" ? "badge-ok" : provider.status === "missing_key" ? "badge-warn" : "badge-idle";
            return (
              <div className="provider-card" key={name}>
                <div className="provider-header">
                  <strong>{name}</strong>
                  <span className={`badge ${badgeClass}`}>{provider.status || "unknown"}</span>
                </div>

                <div className="provider-row">
                  <input
                    type="password"
                    placeholder="Enter API key"
                    value={keys[name] || ""}
                    onChange={(event) => setKeys((prev) => ({ ...prev, [name]: event.target.value }))}
                  />
                  <button type="button" onClick={() => saveProvider(name)}>
                    Save
                  </button>
                  <button type="button" onClick={() => deleteProvider(name)}>
                    Delete
                  </button>
                  <button type="button" onClick={() => testProvider(name)}>
                    Test
                  </button>
                </div>

                <div className="provider-meta">
                  <span>{provider.detail || ""}</span>
                  {testResult ? <span>Latest test: {testResult.status}</span> : null}
                </div>
              </div>
            );
          })}
        </div>

        <div className="budget-panel">
          <h3>Budget Limits</h3>
          <div className="provider-row">
            <input
              type="number"
              min="0"
              step="0.01"
              placeholder="Daily USD"
              value={budget.daily_limit_usd}
              onChange={(event) => setBudget((prev) => ({ ...prev, daily_limit_usd: event.target.value }))}
            />
            <input
              type="number"
              min="0"
              step="0.01"
              placeholder="Monthly USD"
              value={budget.monthly_limit_usd}
              onChange={(event) => setBudget((prev) => ({ ...prev, monthly_limit_usd: event.target.value }))}
            />
            <input
              type="number"
              min="0"
              step="0.01"
              placeholder="Per Request USD"
              value={budget.per_request_limit_usd}
              onChange={(event) => setBudget((prev) => ({ ...prev, per_request_limit_usd: event.target.value }))}
            />
            <button type="button" onClick={saveBudget}>
              Save Budget
            </button>
          </div>
        </div>

        {error ? <div className="inline-error">{error}</div> : null}
        {status ? <div className="inline-success">{status}</div> : null}
      </div>
    );
  }

  window.BYOKManager = BYOKManager;
})();
