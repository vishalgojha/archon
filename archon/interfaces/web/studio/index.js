(function () {
  const React = window.React;
  const ReactDOM = window.ReactDOM;
  const ReactFlow = window.ReactFlow;
  const dagre = window.dagreD3 && window.dagreD3.graphlib ? window.dagreD3.graphlib : null;

  const NODE_TYPES = ["AgentNode", "DebateNode", "ApprovalNode", "ConditionNode", "LoopNode", "OutputNode"];
  const AGENTS = [
    "ResearcherAgent",
    "CriticAgent",
    "FactCheckerAgent",
    "SynthesizerAgent",
    "ProspectorAgent",
    "OutreachAgent",
    "WebChatAgent"
  ];

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

  async function studioApiFetch(path, options = {}) {
    const headers = {
      ...(options.headers || {})
    };
    const token = getToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    if (!headers["Content-Type"] && options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(`${resolveApiBase()}${path}`, {
      ...options,
      headers
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const payload = await response.clone().json();
        detail = payload?.detail || detail;
      } catch (_error) {
        detail = (await response.clone().text()) || detail;
      }
      throw new Error(detail);
    }
    return response;
  }

  function applyLayout(nodes, edges) {
    if (!dagre) {
      return nodes.map((node, index) => ({ ...node, position: node.position || { x: 80 + (index * 80), y: 80 + (index * 40) } }));
    }
    const graph = new dagre.Graph();
    graph.setGraph({ rankdir: "LR", nodesep: 48, ranksep: 72 });
    graph.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((node) => graph.setNode(node.id, { width: 220, height: 88 }));
    edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
    window.dagreD3.dagre.layout(graph);
    return nodes.map((node) => {
      const position = graph.node(node.id);
      return { ...node, position: position ? { x: position.x - 110, y: position.y - 44 } : node.position };
    });
  }

  function serialize(nodes, edges) {
    const edgeMap = new Map();
    edges.forEach((edge) => {
      const list = edgeMap.get(edge.target) || [];
      list.push(edge.source);
      edgeMap.set(edge.target, list);
    });
    return {
      workflow_id: `workflow-${Math.random().toString(16).slice(2, 14)}`,
      name: "Studio Workflow",
      steps: nodes.map((node) => ({
        step_id: node.id,
        agent: node.type === "AgentNode" ? (node.data.agent_class || "ResearcherAgent") : node.type,
        action: node.data.action || node.type.toLowerCase(),
        config: { ...node.data, node_type: node.type },
        dependencies: edgeMap.get(node.id) || []
      })),
      metadata: { studio: { nodes: Object.fromEntries(nodes.map((node) => [node.id, node])), edges } },
      version: 1,
      created_at: Date.now() / 1000
    };
  }

  function TokenGate({ children }) {
    const [tokenInput, setTokenInput] = React.useState("");
    const [hasToken, setHasToken] = React.useState(Boolean(getToken()));

    if (hasToken) {
      return React.createElement(
        React.Fragment,
        null,
        React.createElement(
          "div",
          {
            style: {
              position: "fixed",
              right: 16,
              top: 16,
              zIndex: 20,
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 14px",
              borderRadius: 999,
              background: "rgba(255,250,242,0.92)",
              border: "1px solid var(--studio-border)",
              boxShadow: "0 10px 30px rgba(27,43,65,0.12)"
            }
          },
          React.createElement("span", { style: { fontSize: 12, color: "var(--studio-muted)" } }, "Authenticated"),
          React.createElement(
            "button",
            {
              type: "button",
              onClick: () => {
                setToken("");
                setHasToken(false);
              }
            },
            "Clear Token"
          )
        ),
        children
      );
    }

    return React.createElement(
      "div",
      {
        style: {
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: 24
        }
      },
      React.createElement(
        "div",
        {
          style: {
            width: "min(520px, 100%)",
            display: "grid",
            gap: 14,
            padding: 28,
            borderRadius: 24,
            background: "var(--studio-panel)",
            border: "1px solid var(--studio-border)",
            boxShadow: "0 24px 80px rgba(27,43,65,0.14)"
          }
        },
        React.createElement("div", { style: { fontSize: 12, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--studio-accent)" } }, "ARCHON Studio"),
        React.createElement("h1", { style: { margin: 0, fontSize: 28 } }, "Operator token required"),
        React.createElement(
          "p",
          { style: { margin: 0, color: "var(--studio-muted)", lineHeight: 1.6 } },
          "Paste the tenant JWT you already use for Console. Studio uses protected workflow endpoints, so it cannot save, load, or run without one."
        ),
        React.createElement("input", {
          type: "password",
          placeholder: "Paste JWT token",
          value: tokenInput,
          onChange: (event) => setTokenInput(event.target.value),
          style: {
            width: "100%",
            padding: "12px 14px",
            borderRadius: 14,
            border: "1px solid var(--studio-border)",
            background: "#ffffff",
            color: "var(--studio-ink)"
          }
        }),
        React.createElement(
          "button",
          {
            type: "button",
            disabled: !tokenInput.trim(),
            onClick: () => {
              setToken(tokenInput);
              setHasToken(Boolean(tokenInput.trim()));
            },
            style: {
              padding: "12px 16px",
              borderRadius: 14,
              border: "none",
              background: "var(--studio-accent)",
              color: "#fff7f0",
              cursor: tokenInput.trim() ? "pointer" : "not-allowed",
              opacity: tokenInput.trim() ? 1 : 0.5
            }
          },
          "Open Studio"
        )
      )
    );
  }

  function StudioApp() {
    const [nodes, setNodes] = React.useState([]);
    const [edges, setEdges] = React.useState([]);
    const [selectedNode, setSelectedNode] = React.useState(null);
    const [workflowName, setWorkflowName] = React.useState("Studio Workflow");
    const [runEvents, setRunEvents] = React.useState([]);
    const [notice, setNotice] = React.useState("");

    const onNodesChange = React.useCallback((changes) => setNodes((current) => ReactFlow.applyNodeChanges(changes, current)), []);
    const onEdgesChange = React.useCallback((changes) => setEdges((current) => ReactFlow.applyEdgeChanges(changes, current)), []);
    const onConnect = React.useCallback((connection) => setEdges((current) => ReactFlow.addEdge({ ...connection, label: "data" }, current)), []);

    function addNode(type) {
      const node = {
        id: `${type}-${Math.random().toString(16).slice(2, 10)}`,
        type,
        position: { x: 50, y: 50 },
        data: {
          label: type,
          action: type.toLowerCase(),
          agent_class: type === "AgentNode" ? "ResearcherAgent" : type
        }
      };
      setNodes((current) => applyLayout([...current, node], edges));
    }

    async function saveWorkflow() {
      try {
        setNotice("");
        const payload = serialize(nodes, edges);
        payload.name = workflowName;
        const response = await studioApiFetch("/studio/workflows", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        const saved = await response.json();
        setWorkflowName(saved.name || workflowName);
        setNotice("Workflow saved.");
      } catch (error) {
        setNotice(String(error?.message || "Save failed."));
      }
    }

    async function loadLatest() {
      try {
        setNotice("");
        const list = await studioApiFetch("/studio/workflows").then((response) => response.json());
        if (!Array.isArray(list) || list.length === 0) {
          setNotice("No saved workflows yet.");
          return;
        }
        const payload = await studioApiFetch(`/studio/workflows/${list[0].id}`).then((response) => response.json());
        const studio = payload.metadata?.studio || {};
        setWorkflowName(payload.name || "Studio Workflow");
        setNodes(Object.values(studio.nodes || {}));
        setEdges(studio.edges || []);
        setNotice("Loaded latest workflow.");
      } catch (error) {
        setNotice(String(error?.message || "Load failed."));
      }
    }

    async function runWorkflow() {
      try {
        setNotice("");
        setRunEvents([]);
        const workflow = serialize(nodes, edges);
        workflow.name = workflowName;
        const response = await studioApiFetch("/studio/run", {
          method: "POST",
          body: JSON.stringify({ workflow })
        });
        const payload = await response.json();
        const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${payload.websocket_path}`);
        socket.onmessage = (event) => {
          const frame = JSON.parse(event.data);
          setRunEvents((current) => [...current, frame]);
        };
      } catch (error) {
        setRunEvents([{ type: "error", message: String(error?.message || "Run failed.") }]);
      }
    }

    function updateNode(nextNode) {
      setSelectedNode(nextNode);
      setNodes((current) => current.map((node) => (node.id === nextNode.id ? nextNode : node)));
    }

    return React.createElement(
      "div",
      { style: { height: "100%", display: "grid", gridTemplateRows: "72px 1fr 180px" } },
      React.createElement(
        "div",
        {
          style: {
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "0 18px",
            borderBottom: "1px solid var(--studio-border)",
            background: "rgba(255,250,242,0.82)",
            backdropFilter: "blur(16px)"
          }
        },
        React.createElement("strong", null, "ARCHON Studio"),
        React.createElement("input", {
          value: workflowName,
          onChange: (event) => setWorkflowName(event.target.value),
          style: { minWidth: 220 }
        }),
        React.createElement(
          "select",
          { onChange: (event) => event.target.value && addNode(event.target.value) },
          React.createElement("option", { value: "" }, "Add Node"),
          NODE_TYPES.map((type) => React.createElement("option", { key: type, value: type }, type))
        ),
        React.createElement("button", { onClick: saveWorkflow }, "Save"),
        React.createElement("button", { onClick: loadLatest }, "Load"),
        React.createElement("button", { onClick: runWorkflow }, "Run"),
        React.createElement("button", { onClick: () => navigator.clipboard.writeText(JSON.stringify(serialize(nodes, edges), null, 2)) }, "Export JSON"),
        React.createElement("button", { onClick: async () => {
          const raw = window.prompt("Paste workflow JSON");
          if (!raw) return;
          const workflow = JSON.parse(raw);
          const studio = workflow.metadata?.studio || {};
          setWorkflowName(workflow.name || "Studio Workflow");
          setNodes(Object.values(studio.nodes || {}));
          setEdges(studio.edges || []);
        } }, "Import JSON")
      ),
      notice ? React.createElement(
        "div",
        {
          style: {
            marginLeft: "auto",
            color: "var(--studio-muted)",
            fontSize: 12
          }
        },
        notice
      ) : null,
      React.createElement(
        "div",
        { style: { display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 16, padding: 16 } },
        React.createElement(
          "div",
          { style: { minHeight: 0 } },
          React.createElement(window.WorkflowCanvas || (() => null), {
            nodes,
            edges,
            onNodesChange,
            onEdgesChange,
            onConnect,
            onNodeClick: setSelectedNode
          })
        ),
        React.createElement(
          "aside",
          {
            style: {
              background: "var(--studio-panel)",
              border: "1px solid var(--studio-border)",
              borderRadius: 20,
              overflow: "hidden"
            }
          },
          React.createElement(window.NodeEditor || (() => null), {
            node: selectedNode,
            onChange: updateNode,
            agentOptions: AGENTS
          })
        )
      ),
      React.createElement(
        "div",
        {
          style: {
            borderTop: "1px solid var(--studio-border)",
            background: "rgba(255,250,242,0.82)",
            padding: 12,
            overflow: "auto"
          }
        },
        React.createElement("strong", null, "Run Panel"),
        React.createElement(
          "pre",
          { style: { whiteSpace: "pre-wrap", fontSize: 12, margin: "8px 0 0" } },
          runEvents.map((event) => JSON.stringify(event)).join("\n")
        )
      )
    );
  }

  const root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(
    React.createElement(
      TokenGate,
      null,
      React.createElement(StudioApp)
    )
  );
})();
