(() => {
  const { useEffect, useMemo, useState } = React;

  function pathKey(method, path) {
    return `${method.toUpperCase()} ${path}`;
  }

  function APIExplorer() {
    const [routes, setRoutes] = useState([]);
    const [selectedKey, setSelectedKey] = useState("");
    const [params, setParams] = useState({});
    const [bodyText, setBodyText] = useState("{}");
    const [responsePayload, setResponsePayload] = useState(null);
    const [executing, setExecuting] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
      let cancelled = false;
      window
        .consoleApiFetch("/openapi.json")
        .then((response) => response.json())
        .then((openapi) => {
          if (cancelled) {
            return;
          }
          const discovered = [];
          const paths = openapi.paths || {};
          Object.entries(paths).forEach(([path, value]) => {
            Object.entries(value || {}).forEach(([method, config]) => {
              discovered.push({
                method: method.toUpperCase(),
                path,
                summary: config.summary || "",
                parameters: Array.isArray(config.parameters) ? config.parameters : [],
                requestBody: config.requestBody || null,
              });
            });
          });
          discovered.sort((a, b) => pathKey(a.method, a.path).localeCompare(pathKey(b.method, b.path)));
          setRoutes(discovered);
          if (discovered.length > 0) {
            setSelectedKey(pathKey(discovered[0].method, discovered[0].path));
          }
        })
        .catch((loadError) => {
          if (!cancelled) {
            setError(String(loadError.message || loadError));
          }
        });

      return () => {
        cancelled = true;
      };
    }, []);

    const selectedRoute = useMemo(
      () => routes.find((route) => pathKey(route.method, route.path) === selectedKey) || null,
      [routes, selectedKey],
    );

    const onExecute = async () => {
      if (!selectedRoute) {
        return;
      }
      setExecuting(true);
      setError("");
      setResponsePayload(null);

      try {
        const query = new URLSearchParams();
        let resolvedPath = selectedRoute.path;

        selectedRoute.parameters.forEach((param) => {
          const value = String(params[param.name] || "").trim();
          if (!value) {
            return;
          }
          if (param.in === "path") {
            resolvedPath = resolvedPath.replace(`{${param.name}}`, encodeURIComponent(value));
          } else if (param.in === "query") {
            query.append(param.name, value);
          }
        });

        const finalPath = query.toString() ? `${resolvedPath}?${query.toString()}` : resolvedPath;
        const requestInit = { method: selectedRoute.method };

        if (selectedRoute.requestBody && !["GET", "DELETE"].includes(selectedRoute.method)) {
          let parsedBody = {};
          try {
            parsedBody = bodyText.trim() ? JSON.parse(bodyText) : {};
          } catch (parseError) {
            throw new Error(`Invalid JSON body: ${parseError.message}`);
          }
          requestInit.body = JSON.stringify(parsedBody);
        }

        const response = await window.consoleApiFetch(finalPath, requestInit);
        const text = await response.text();
        let parsed;
        try {
          parsed = text ? JSON.parse(text) : null;
        } catch (_parseError) {
          parsed = text;
        }
        setResponsePayload({ status: response.status, body: parsed });
      } catch (execError) {
        setError(String(execError.message || execError));
      } finally {
        setExecuting(false);
      }
    };

    return (
      <div className="console-pane api-pane">
        <h2>API Explorer</h2>

        <div className="api-layout">
          <aside className="api-route-list">
            {routes.map((route) => {
              const key = pathKey(route.method, route.path);
              return (
                <button
                  key={key}
                  type="button"
                  className={`api-route-item ${selectedKey === key ? "active" : ""}`}
                  onClick={() => setSelectedKey(key)}
                >
                  <span className="route-method">{route.method}</span>
                  <span className="route-path">{route.path}</span>
                </button>
              );
            })}
          </aside>

          <section className="api-details">
            {selectedRoute ? (
              <>
                <div className="api-selected-head">
                  <strong>{selectedRoute.method}</strong> <code>{selectedRoute.path}</code>
                </div>
                <p className="muted">{selectedRoute.summary || "No summary"}</p>

                <div className="param-form">
                  {(selectedRoute.parameters || []).map((param) => (
                    <label key={`${param.in}-${param.name}`}>
                      {param.name} ({param.in})
                      <input
                        value={params[param.name] || ""}
                        onChange={(event) =>
                          setParams((prev) => ({
                            ...prev,
                            [param.name]: event.target.value,
                          }))
                        }
                      />
                    </label>
                  ))}
                </div>

                {selectedRoute.requestBody ? (
                  <label className="body-editor-label">
                    Request Body (JSON)
                    <textarea value={bodyText} onChange={(event) => setBodyText(event.target.value)} rows={10} />
                  </label>
                ) : null}

                <button type="button" onClick={onExecute} disabled={executing}>
                  {executing ? "Executing..." : "Execute"}
                </button>

                {responsePayload ? (
                  <div className="api-response">
                    <div>Status: {responsePayload.status}</div>
                    <pre>{JSON.stringify(responsePayload.body, null, 2)}</pre>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="pane-empty">Select an endpoint to inspect.</div>
            )}
          </section>
        </div>

        {error ? <div className="inline-error">{error}</div> : null}
      </div>
    );
  }

  window.APIExplorer = APIExplorer;
})();
