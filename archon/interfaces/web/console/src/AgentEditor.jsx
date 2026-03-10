(() => {
  const { useEffect, useMemo, useRef, useState } = React;

  let monacoPromise = null;

  function ensureMonaco() {
    if (window.monaco) {
      return Promise.resolve(window.monaco);
    }
    if (monacoPromise) {
      return monacoPromise;
    }
    monacoPromise = new Promise((resolve, reject) => {
      if (!window.require || typeof window.require.config !== "function") {
        reject(new Error("Monaco loader not available"));
        return;
      }
      window.require.config({
        paths: {
          vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs",
        },
      });
      window.require(["vs/editor/editor.main"], () => resolve(window.monaco), reject);
    });
    return monacoPromise;
  }

  function isCoreReadOnly(path) {
    const normalized = String(path || "").replace(/\\/g, "/").toLowerCase();
    return (
      normalized.startsWith("core/") ||
      normalized.endsWith("orchestrator.py") ||
      normalized.endsWith("debate_engine.py") ||
      normalized.endsWith("swarm_router.py")
    );
  }

  function TreeNode({ node, selectedPath, onSelect }) {
    const [expanded, setExpanded] = useState(true);
    if (node.type === "directory") {
      return (
        <div className="tree-node directory-node">
          <button type="button" className="tree-directory" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "▾" : "▸"} {node.name}
          </button>
          {expanded
            ? (node.children || []).map((child) => (
                <TreeNode key={child.path} node={child} selectedPath={selectedPath} onSelect={onSelect} />
              ))
            : null}
        </div>
      );
    }

    return (
      <button
        type="button"
        className={`tree-file ${selectedPath === node.path ? "active" : ""}`}
        onClick={() => onSelect(node.path)}
      >
        {node.name}
      </button>
    );
  }

  function AgentEditor() {
    const editorHostRef = useRef(null);
    const editorRef = useRef(null);

    const [tree, setTree] = useState([]);
    const [selectedPath, setSelectedPath] = useState("");
    const [content, setContent] = useState("");
    const [loadingTree, setLoadingTree] = useState(false);
    const [loadingFile, setLoadingFile] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState("");
    const [status, setStatus] = useState("");
    const [serverReadOnly, setServerReadOnly] = useState(false);

    const readOnly = useMemo(() => serverReadOnly || isCoreReadOnly(selectedPath), [serverReadOnly, selectedPath]);

    useEffect(() => {
      let cancelled = false;
      setLoadingTree(true);
      window
        .consoleApiFetch("/console/agents")
        .then(async (response) => {
          const payload = await response.json();
          if (cancelled) {
            return;
          }
          setTree(Array.isArray(payload.tree) ? payload.tree : []);
          setError("");
        })
        .catch((fetchError) => {
          if (!cancelled) {
            setError(String(fetchError.message || fetchError));
          }
        })
        .finally(() => {
          if (!cancelled) {
            setLoadingTree(false);
          }
        });
      return () => {
        cancelled = true;
      };
    }, []);

    useEffect(() => {
      let disposed = false;
      ensureMonaco()
        .then((monaco) => {
          if (disposed || !editorHostRef.current) {
            return;
          }
          if (!editorRef.current) {
            editorRef.current = monaco.editor.create(editorHostRef.current, {
              value: "",
              language: "python",
              theme: "vs-dark",
              automaticLayout: true,
              minimap: { enabled: false },
              fontSize: 13,
              readOnly,
            });
            editorRef.current.onDidChangeModelContent(() => {
              setContent(editorRef.current.getValue());
            });
          }
        })
        .catch((monacoError) => {
          setError(String(monacoError.message || monacoError));
        });

      return () => {
        disposed = true;
      };
    }, []);

    useEffect(() => {
      if (editorRef.current) {
        editorRef.current.updateOptions({ readOnly });
      }
    }, [readOnly]);

    const loadFile = async (path) => {
      setSelectedPath(path);
      setLoadingFile(true);
      setStatus("");
      try {
        const response = await window.consoleApiFetch(`/console/agents/${encodeURIComponent(path).replace(/%2F/g, "/")}`);
        const payload = await response.json();
        const nextContent = String(payload.content || "");
        setServerReadOnly(Boolean(payload.read_only));
        setContent(nextContent);
        if (editorRef.current) {
          editorRef.current.setValue(nextContent);
        }
      } catch (loadError) {
        setError(String(loadError.message || loadError));
      } finally {
        setLoadingFile(false);
      }
    };

    const onSave = async () => {
      if (!selectedPath || readOnly) {
        return;
      }
      setSaving(true);
      setError("");
      setStatus("");
      try {
        const response = await window.consoleApiFetch(
          `/console/agents/${encodeURIComponent(selectedPath).replace(/%2F/g, "/")}`,
          {
            method: "PUT",
            body: JSON.stringify({ content }),
          },
        );
        const payload = await response.json();
        setStatus(`Saved ${payload.path} (${payload.bytes} bytes)`);
      } catch (saveError) {
        const detail = saveError.payload?.detail;
        if (detail && typeof detail === "object") {
          setError(`Save failed: ${detail.message || JSON.stringify(detail)}`);
        } else {
          setError(`Save failed: ${saveError.message || saveError}`);
        }
      } finally {
        setSaving(false);
      }
    };

    return (
      <div className="agent-editor-root">
        <aside className="agent-tree-pane">
          <div className="pane-title">Agents</div>
          {loadingTree ? <div className="pane-empty">Loading tree...</div> : null}
          {!loadingTree && tree.length === 0 ? <div className="pane-empty">No agent files available.</div> : null}
          <div className="tree-wrap">
            {tree.map((node) => (
              <TreeNode key={node.path} node={node} selectedPath={selectedPath} onSelect={loadFile} />
            ))}
          </div>
        </aside>

        <section className="agent-editor-pane">
          <div className="editor-toolbar">
            <div>
              <strong>{selectedPath || "Select a file"}</strong>
              {loadingFile ? <span className="muted"> loading...</span> : null}
            </div>
            <div className="toolbar-actions">
              {readOnly ? <span className="badge badge-warn">Read only</span> : null}
              <button type="button" onClick={onSave} disabled={!selectedPath || saving || readOnly}>
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
          <div ref={editorHostRef} className="editor-host" />
          {error ? <div className="inline-error">{error}</div> : null}
          {status ? <div className="inline-success">{status}</div> : null}
        </section>
      </div>
    );
  }

  window.AgentEditor = AgentEditor;
})();
