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

  function StudioApp() {
    const [nodes, setNodes] = React.useState([]);
    const [edges, setEdges] = React.useState([]);
    const [selectedNode, setSelectedNode] = React.useState(null);
    const [workflowName, setWorkflowName] = React.useState("Studio Workflow");
    const [runEvents, setRunEvents] = React.useState([]);

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
      const payload = serialize(nodes, edges);
      payload.name = workflowName;
      const response = await fetch("/studio/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error("Save failed");
      const saved = await response.json();
      setWorkflowName(saved.name || workflowName);
    }

    async function loadLatest() {
      const list = await fetch("/studio/workflows").then((response) => response.json());
      if (!Array.isArray(list) || list.length === 0) return;
      const payload = await fetch(`/studio/workflows/${list[0].id}`).then((response) => response.json());
      const studio = payload.metadata?.studio || {};
      setWorkflowName(payload.name || "Studio Workflow");
      setNodes(Object.values(studio.nodes || {}));
      setEdges(studio.edges || []);
    }

    async function runWorkflow() {
      const workflow = serialize(nodes, edges);
      workflow.name = workflowName;
      const response = await fetch("/studio/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow })
      });
      const payload = await response.json();
      if (!response.ok) {
        setRunEvents(payload.detail || []);
        return;
      }
      const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${payload.websocket_path}`);
      socket.onmessage = (event) => {
        const frame = JSON.parse(event.data);
        setRunEvents((current) => [...current, frame]);
      };
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
      React.createElement(
        "div",
        { style: { display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 16, padding: 16 } },
        React.createElement(
          "div",
          { style: { minHeight: 0 } },
          React.createElement(
            ReactFlow.ReactFlow,
            {
              nodes,
              edges,
              onNodesChange,
              onEdgesChange,
              onConnect,
              onNodeClick: (_event, node) => setSelectedNode(node),
              fitView: true
            },
            React.createElement(ReactFlow.MiniMap, { position: "bottom-right" }),
            React.createElement(ReactFlow.Controls),
            React.createElement(ReactFlow.Background, { gap: 20, size: 1 })
          )
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
  root.render(React.createElement(StudioApp));
})();
