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
  const NODE_LIBRARY = {
    AgentNode: {
      label: "Agent Step",
      action: "agent_step",
      description: "Execute one named ARCHON agent with a focused config."
    },
    DebateNode: {
      label: "Debate Round",
      action: "debate_round",
      description: "Challenge or refine an answer before it moves downstream."
    },
    ApprovalNode: {
      label: "Approval Gate",
      action: "approval_gate",
      description: "Pause the workflow until a reviewer clears the next step."
    },
    ConditionNode: {
      label: "Condition Branch",
      action: "branch_condition",
      description: "Route work based on the result of one decision."
    },
    LoopNode: {
      label: "Loop Step",
      action: "loop_step",
      description: "Repeat a stage until a stop rule is met."
    },
    OutputNode: {
      label: "Output",
      action: "output_result",
      description: "Capture the final operator-facing result."
    }
  };

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

  function getNodeSpec(type) {
    return NODE_LIBRARY[type] || NODE_LIBRARY.AgentNode;
  }

  function createNode(type, overrides = {}) {
    const spec = getNodeSpec(type);
    return {
      id: overrides.id || `${type}-${Math.random().toString(16).slice(2, 10)}`,
      type,
      position: overrides.position || { x: 80, y: 140 },
      data: {
        label: overrides.label || spec.label,
        action: overrides.action || spec.action,
        description: overrides.description || spec.description,
        agent_class: type === "AgentNode" ? (overrides.agentClass || "ResearcherAgent") : type,
        config: overrides.config || {}
      }
    };
  }

  function applyLayout(nodes, edges) {
    if (!dagre) {
      return nodes.map((node, index) => ({
        ...node,
        position: node.position || { x: 90 + (index * 240), y: 120 + ((index % 2) * 48) }
      }));
    }
    const graph = new dagre.Graph();
    graph.setGraph({ rankdir: "LR", nodesep: 56, ranksep: 92, marginx: 20, marginy: 20 });
    graph.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((node) => graph.setNode(node.id, { width: 236, height: 112 }));
    edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
    window.dagreD3.dagre.layout(graph);
    return nodes.map((node) => {
      const position = graph.node(node.id);
      return {
        ...node,
        position: position ? { x: position.x - 118, y: position.y - 56 } : node.position
      };
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

  function createLinearTemplate(name, steps) {
    const nodes = steps.map((step, index) =>
      createNode(step.type, {
        ...step,
        position: { x: 100 + (index * 260), y: 140 + ((index % 2) * 36) }
      })
    );
    const edges = nodes.slice(1).map((node, index) => ({
      id: `${nodes[index].id}-${node.id}`,
      source: nodes[index].id,
      target: node.id,
      label: "data"
    }));
    return {
      name,
      nodes: applyLayout(nodes, edges),
      edges,
      preserveLayout: true
    };
  }

  function buildStarterTemplate(kind) {
    if (kind === "approval") {
      return createLinearTemplate("Approval Review Flow", [
        { type: "AgentNode", label: "Draft Response", action: "draft_response", agentClass: "ResearcherAgent" },
        { type: "ApprovalNode", label: "Operator Review", action: "request_approval" },
        { type: "OutputNode", label: "Approved Output", action: "publish_output" }
      ]);
    }
    if (kind === "debate") {
      return createLinearTemplate("Debate and Synthesize", [
        { type: "AgentNode", label: "Initial Thesis", action: "initial_thesis", agentClass: "ResearcherAgent" },
        { type: "DebateNode", label: "Critique Round", action: "challenge_answer" },
        { type: "OutputNode", label: "Synthesis", action: "deliver_synthesis" }
      ]);
    }
    return createLinearTemplate("Research Delivery Flow", [
      { type: "AgentNode", label: "Research", action: "gather_research", agentClass: "ResearcherAgent" },
      { type: "AgentNode", label: "Fact Check", action: "fact_check", agentClass: "FactCheckerAgent" },
      { type: "OutputNode", label: "Delivery", action: "deliver_result" }
    ]);
  }

  function inferNodeType(step) {
    const hinted = String(step?.config?.node_type || "").trim();
    if (NODE_TYPES.includes(hinted)) {
      return hinted;
    }
    const agent = String(step?.agent || "").trim();
    if (NODE_TYPES.includes(agent)) {
      return agent;
    }
    if (AGENTS.includes(agent)) {
      return "AgentNode";
    }
    return "OutputNode";
  }

  function deserializeWorkflow(workflow) {
    const studio = workflow?.metadata?.studio || {};
    const studioNodes = Object.values(studio.nodes || {});
    const studioEdges = Array.isArray(studio.edges) ? studio.edges : [];
    if (studioNodes.length > 0) {
      return { nodes: studioNodes, edges: studioEdges, preserveLayout: true };
    }

    const rawSteps = Array.isArray(workflow?.steps) ? workflow.steps : [];
    const nodes = rawSteps.map((step, index) =>
      createNode(inferNodeType(step), {
        id: step.step_id || `step-${index + 1}`,
        label: step?.config?.label || step?.agent || step?.action || `Step ${index + 1}`,
        action: step?.action || step?.config?.action || getNodeSpec(inferNodeType(step)).action,
        description: step?.config?.description || getNodeSpec(inferNodeType(step)).description,
        agentClass: AGENTS.includes(String(step?.agent || "").trim()) ? step.agent : "ResearcherAgent",
        config: step?.config || {},
        position: { x: 90 + (index * 250), y: 140 + ((index % 2) * 42) }
      })
    );
    const edges = [];
    rawSteps.forEach((step) => {
      const dependencies = Array.isArray(step?.dependencies) ? step.dependencies : [];
      dependencies.forEach((dependency) => {
        edges.push({
          id: `${dependency}-${step.step_id}`,
          source: dependency,
          target: step.step_id,
          label: "data"
        });
      });
    });
    return { nodes: applyLayout(nodes, edges), edges, preserveLayout: true };
  }

  function renderRunEvent(event, index) {
    const eventType = String(event?.type || event?.state || "event");
    const headline = String(event?.message || event?.detail || eventType).trim();
    const className = eventType.toLowerCase() === "error"
      ? "studio-run-event studio-run-event--error"
      : "studio-run-event";
    return React.createElement(
      "div",
      { className, key: `${eventType}-${index}` },
      React.createElement(
        "div",
        { className: "studio-run-event-header" },
        React.createElement("strong", null, eventType),
        React.createElement("span", { className: "studio-helper" }, headline)
      ),
      React.createElement("pre", null, JSON.stringify(event, null, 2))
    );
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
          { className: "studio-auth-pill" },
          React.createElement("span", { className: "studio-auth-dot" }),
          React.createElement("span", { className: "studio-helper" }, "Authenticated"),
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
      { className: "studio-token-gate" },
      React.createElement(
        "div",
        { className: "studio-token-card studio-panel" },
        React.createElement("div", { className: "studio-eyebrow" }, "ARCHON Studio"),
        React.createElement("h1", null, "Operator token required"),
        React.createElement(
          "p",
          null,
          "Paste the tenant JWT you already use for Console. Studio uses protected workflow endpoints, so save, load, and run are locked until a token is present."
        ),
        React.createElement("input", {
          type: "password",
          placeholder: "Paste JWT token",
          value: tokenInput,
          onChange: (event) => setTokenInput(event.target.value)
        }),
        React.createElement(
          "button",
          {
            type: "button",
            className: "studio-button-primary",
            disabled: !tokenInput.trim(),
            onClick: () => {
              setToken(tokenInput);
              setHasToken(Boolean(tokenInput.trim()));
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
    const [notice, setNotice] = React.useState(null);
    const [nodeMenuValue, setNodeMenuValue] = React.useState("");

    function showNotice(message, tone = "info") {
      setNotice({ message, tone });
    }

    function commitWorkflow({ nodes: nextNodes, edges: nextEdges, preserveLayout }, nextName, message, tone = "success") {
      const resolvedNodes = preserveLayout ? nextNodes : applyLayout(nextNodes, nextEdges);
      setNodes(resolvedNodes);
      setEdges(nextEdges);
      setSelectedNode(resolvedNodes[0] || null);
      setWorkflowName(nextName || "Studio Workflow");
      setRunEvents([]);
      showNotice(message, tone);
    }

    const onNodesChange = (changes) => {
      setNodes((current) => {
        const next = ReactFlow.applyNodeChanges(changes, current);
        if (selectedNode && !next.some((node) => node.id === selectedNode.id)) {
          setSelectedNode(null);
        }
        return next;
      });
    };

    const onEdgesChange = (changes) => {
      setEdges((current) => ReactFlow.applyEdgeChanges(changes, current));
    };

    const onConnect = (connection) => {
      setEdges((current) => ReactFlow.addEdge({ ...connection, label: "data" }, current));
      setNotice(null);
    };

    function addNode(type) {
      const node = createNode(type);
      setNodes((current) => {
        const next = applyLayout([...current, node], edges);
        const focused = next.find((candidate) => candidate.id === node.id) || node;
        setSelectedNode(focused);
        return next;
      });
      setNotice(null);
    }

    function loadTemplate(kind) {
      const template = buildStarterTemplate(kind);
      commitWorkflow(template, template.name, "Loaded starter workflow.");
    }

    async function saveWorkflow() {
      if (!nodes.length) {
        showNotice("Add at least one node before saving.", "error");
        return;
      }
      try {
        const payload = serialize(nodes, edges);
        payload.name = workflowName.trim() || "Studio Workflow";
        const response = await studioApiFetch("/studio/workflows", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        const saved = await response.json();
        setWorkflowName(saved.name || payload.name);
        showNotice("Workflow saved.", "success");
      } catch (error) {
        showNotice(String(error?.message || "Save failed."), "error");
      }
    }

    async function loadLatest() {
      try {
        const list = await studioApiFetch("/studio/workflows").then((response) => response.json());
        if (!Array.isArray(list) || list.length === 0) {
          showNotice("No saved workflows yet.", "info");
          return;
        }
        const workflowId = list[0].id || list[0].workflow_id;
        const payload = await studioApiFetch(`/studio/workflows/${workflowId}`).then((response) => response.json());
        commitWorkflow(deserializeWorkflow(payload), payload.name || "Studio Workflow", "Loaded latest workflow.");
      } catch (error) {
        showNotice(String(error?.message || "Load failed."), "error");
      }
    }

    async function exportJson() {
      const payload = JSON.stringify(serialize(nodes, edges), null, 2);
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(payload);
          showNotice("Workflow JSON copied to clipboard.", "success");
          return;
        }
      } catch (_error) {
      }
      window.prompt("Copy workflow JSON", payload);
      showNotice("Clipboard access was unavailable. Opened the JSON in a copy dialog.", "info");
    }

    function importJson() {
      try {
        const raw = window.prompt("Paste workflow JSON");
        if (!raw) {
          return;
        }
        const workflow = JSON.parse(raw);
        commitWorkflow(
          deserializeWorkflow(workflow),
          workflow.name || "Studio Workflow",
          "Imported workflow JSON."
        );
      } catch (error) {
        showNotice(String(error?.message || "Import failed."), "error");
      }
    }

    async function runWorkflow() {
      if (!nodes.length) {
        showNotice("Add at least one node before running.", "error");
        return;
      }
      try {
        setRunEvents([]);
        showNotice("Run requested. Waiting for websocket stream.", "info");
        const workflow = serialize(nodes, edges);
        workflow.name = workflowName.trim() || "Studio Workflow";
        const response = await studioApiFetch("/studio/run", {
          method: "POST",
          body: JSON.stringify({ workflow })
        });
        const payload = await response.json();
        const socketUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${payload.websocket_path}`;
        const socket = new WebSocket(socketUrl);
        socket.onopen = () => {
          setRunEvents((current) => [...current, { type: "status", message: "Connected to run stream." }]);
          showNotice("Run stream connected.", "success");
        };
        socket.onmessage = (event) => {
          const frame = JSON.parse(event.data);
          setRunEvents((current) => [...current, frame]);
        };
        socket.onerror = () => {
          setRunEvents((current) => [...current, { type: "error", message: "Run socket error." }]);
          showNotice("Run socket error.", "error");
        };
        socket.onclose = () => {
          setRunEvents((current) => [...current, { type: "status", message: "Run stream closed." }]);
        };
      } catch (error) {
        setRunEvents([{ type: "error", message: String(error?.message || "Run failed.") }]);
        showNotice(String(error?.message || "Run failed."), "error");
      }
    }

    function updateNode(nextNode) {
      setSelectedNode(nextNode);
      setNodes((current) => current.map((node) => (node.id === nextNode.id ? nextNode : node)));
    }

    return React.createElement(
      "div",
      { className: "studio-shell" },
      React.createElement(
        "header",
        { className: "studio-toolbar studio-panel" },
        React.createElement(
          "div",
          { className: "studio-brand" },
          React.createElement("div", { className: "studio-eyebrow" }, "Workflow Studio"),
          React.createElement("h1", null, "Build operator-safe orchestration flows"),
          React.createElement(
            "p",
            null,
            "Draft agent graphs, add approval gates, branch decisions, and run the workflow against your local ARCHON API without leaving the browser."
          ),
          React.createElement(
            "div",
            { className: "studio-chip-row" },
            React.createElement("div", { className: "studio-chip" }, React.createElement("strong", null, nodes.length), "Nodes"),
            React.createElement("div", { className: "studio-chip" }, React.createElement("strong", null, edges.length), "Connections"),
            React.createElement("div", { className: "studio-chip" }, React.createElement("strong", null, runEvents.length), "Run Events")
          )
        ),
        React.createElement(
          "div",
          { className: "studio-form-card" },
          React.createElement(
            "div",
            { className: "studio-field" },
            React.createElement("label", null, "Workflow Name"),
            React.createElement("input", {
              value: workflowName,
              onChange: (event) => setWorkflowName(event.target.value)
            }),
            React.createElement(
              "small",
              null,
              "The workflow name is saved with the definition and reused for exported JSON."
            )
          ),
          notice
            ? React.createElement(
                "div",
                { className: `studio-notice studio-notice--${notice.tone || "info"}` },
                notice.message
              )
            : React.createElement(
                "div",
                { className: "studio-notice studio-notice--info" },
                "Use starter templates for speed, then fine-tune node details in the inspector."
              )
        ),
        React.createElement(
          "div",
          { className: "studio-action-grid" },
          React.createElement(
            "div",
            { className: "studio-action-row" },
            React.createElement(
              "select",
              {
                value: nodeMenuValue,
                onChange: (event) => {
                  const nextType = event.target.value;
                  setNodeMenuValue("");
                  if (!nextType) {
                    return;
                  }
                  addNode(nextType);
                }
              },
              React.createElement("option", { value: "" }, "Add Node"),
              NODE_TYPES.map((type) => React.createElement("option", { key: type, value: type }, type))
            ),
            React.createElement("button", { type: "button", onClick: saveWorkflow }, "Save"),
            React.createElement("button", { type: "button", onClick: loadLatest }, "Load"),
            React.createElement(
              "button",
              { type: "button", className: "studio-button-primary", onClick: runWorkflow },
              "Run"
            )
          ),
          React.createElement(
            "div",
            { className: "studio-action-row" },
            React.createElement("button", { type: "button", onClick: exportJson }, "Export JSON"),
            React.createElement("button", { type: "button", onClick: importJson }, "Import JSON"),
            React.createElement("button", { type: "button", className: "studio-button-warm", onClick: () => loadTemplate("research") }, "Research"),
            React.createElement("button", { type: "button", className: "studio-button-warm", onClick: () => loadTemplate("approval") }, "Approval"),
            React.createElement("button", { type: "button", className: "studio-button-warm", onClick: () => loadTemplate("debate") }, "Debate")
          )
        )
      ),
      React.createElement(
        "main",
        { className: "studio-workspace" },
        React.createElement(
          "section",
          { className: "studio-panel studio-section" },
          React.createElement(
            "div",
            { className: "studio-section-header" },
            React.createElement(
              "div",
              null,
              React.createElement("div", { className: "studio-kicker" }, "Canvas"),
              React.createElement("h2", null, "Workflow Map"),
              React.createElement(
                "p",
                null,
                "Arrange the graph left to right. Start broad on the canvas, then edit the selected node on the right."
              )
            ),
            React.createElement(
              "div",
              { className: "studio-section-actions" },
              React.createElement("button", { type: "button", onClick: () => addNode("AgentNode") }, "Agent"),
              React.createElement("button", { type: "button", onClick: () => addNode("ApprovalNode") }, "Approval"),
              React.createElement("button", { type: "button", onClick: () => addNode("OutputNode") }, "Output")
            )
          ),
          React.createElement(
            "div",
            { className: "studio-canvas-card" },
            React.createElement(window.WorkflowCanvas || (() => null), {
              nodes,
              edges,
              onNodesChange,
              onEdgesChange,
              onConnect,
              onNodeClick: setSelectedNode,
              onAddNode: addNode,
              onLoadTemplate: loadTemplate
            })
          )
        ),
        React.createElement(
          "aside",
          { className: "studio-panel studio-sidebar" },
          React.createElement(window.NodeEditor || (() => null), {
            node: selectedNode,
            onChange: updateNode,
            agentOptions: AGENTS
          })
        )
      ),
      React.createElement(
        "section",
        { className: "studio-panel studio-run-panel" },
        React.createElement(
          "div",
          { className: "studio-section-header" },
          React.createElement(
            "div",
            null,
            React.createElement("div", { className: "studio-kicker" }, "Runtime"),
            React.createElement("h2", null, "Run Timeline"),
            React.createElement(
              "p",
              null,
              "Run traces appear here as websocket frames. Keep the panel open while you validate the behavior of the active workflow."
            )
          )
        ),
        runEvents.length
          ? React.createElement(
              "div",
              { className: "studio-run-list" },
              runEvents.map((event, index) => renderRunEvent(event, index))
            )
          : React.createElement(
              "div",
              { className: "studio-run-empty" },
              React.createElement(
                "div",
                null,
                React.createElement("strong", null, "No run output yet."),
                React.createElement(
                  "div",
                  { className: "studio-helper", style: { marginTop: 8 } },
                  "Press Run after adding a few nodes. Connection status, workflow events, and errors will stream here."
                )
              )
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
