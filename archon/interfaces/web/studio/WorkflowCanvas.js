const React = window.React;
const { ReactFlow, MiniMap, Controls, Background, Handle, Position } = window.ReactFlow;

const NODE_THEME = {
  AgentNode: {
    badge: "Agent",
    hint: "Execute one agent with explicit config.",
    tone: "#44c2a4",
    surface: "rgba(220, 247, 239, 0.92)"
  },
  DebateNode: {
    badge: "Debate",
    hint: "Run a structured challenge or synthesis pass.",
    tone: "#f0b85f",
    surface: "rgba(250, 236, 206, 0.96)"
  },
  ApprovalNode: {
    badge: "Approval",
    hint: "Insert a human review or gated release step.",
    tone: "#e58a6c",
    surface: "rgba(255, 233, 228, 0.94)"
  },
  ConditionNode: {
    badge: "Condition",
    hint: "Route execution based on one branching rule.",
    tone: "#659ae8",
    surface: "rgba(227, 239, 255, 0.94)"
  },
  LoopNode: {
    badge: "Loop",
    hint: "Repeat until a stop condition is met.",
    tone: "#8f80de",
    surface: "rgba(236, 232, 255, 0.94)"
  },
  OutputNode: {
    badge: "Output",
    hint: "Collect the final artifact or operator answer.",
    tone: "#5e7680",
    surface: "rgba(235, 241, 242, 0.96)"
  }
};

function getNodeTheme(type) {
  return NODE_THEME[type] || NODE_THEME.AgentNode;
}

function StudioNodeCard({ data, selected, type }) {
  const theme = getNodeTheme(type);
  const label = String(data?.label || theme.badge || type).trim();
  const subhead = type === "AgentNode"
    ? String(data?.agent_class || "ResearcherAgent").trim()
    : String(data?.action || theme.badge).trim();
  const description = String(data?.description || theme.hint || "").trim();

  return React.createElement(
    "div",
    {
      style: {
        minWidth: 218,
        maxWidth: 236,
        padding: "14px 16px",
        borderRadius: 18,
        border: selected ? `1px solid ${theme.tone}` : "1px solid rgba(19,36,43,0.12)",
        background: theme.surface,
        boxShadow: selected
          ? `0 18px 34px ${theme.tone}33`
          : "0 16px 28px rgba(19,36,43,0.12)"
      }
    },
    React.createElement(Handle, {
      type: "target",
      position: Position.Left,
      style: { width: 10, height: 10, background: theme.tone, border: "2px solid #ffffff" }
    }),
    React.createElement(
      "div",
      {
        style: {
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 10px",
          borderRadius: 999,
          background: "#ffffff",
          color: theme.tone,
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: "0.12em",
          textTransform: "uppercase"
        }
      },
      theme.badge
    ),
    React.createElement(
      "div",
      { style: { marginTop: 12, display: "grid", gap: 6 } },
      React.createElement(
        "strong",
        { style: { fontSize: 16, lineHeight: 1.2, color: "var(--studio-ink)" } },
        label
      ),
      React.createElement(
        "div",
        { style: { fontSize: 12, fontWeight: 700, color: theme.tone } },
        subhead
      ),
      React.createElement(
        "div",
        { style: { fontSize: 12, lineHeight: 1.55, color: "var(--studio-muted)" } },
        description
      )
    ),
    React.createElement(Handle, {
      type: "source",
      position: Position.Right,
      style: { width: 10, height: 10, background: theme.tone, border: "2px solid #ffffff" }
    })
  );
}

const studioNodeTypes = Object.fromEntries(
  Object.keys(NODE_THEME).map((type) => [
    type,
    function StudioTypedNode(props) {
      return React.createElement(StudioNodeCard, { ...props, type });
    }
  ])
);

window.WorkflowCanvas = function WorkflowCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onAddNode,
  onLoadTemplate
}) {
  const hasNodes = Array.isArray(nodes) && nodes.length > 0;

  return React.createElement(
    "div",
    { className: "studio-canvas-shell" },
    React.createElement(
      "div",
      { className: "studio-canvas-status" },
      React.createElement("span", null, `${nodes.length} node${nodes.length === 1 ? "" : "s"}`),
      React.createElement("span", null, `${edges.length} connection${edges.length === 1 ? "" : "s"}`),
      React.createElement("span", null, hasNodes ? "Drag, connect, then inspect on the right." : "Start with a template or a single node.")
    ),
    React.createElement(
      ReactFlow,
      {
        nodes,
        edges,
        nodeTypes: studioNodeTypes,
        onNodesChange,
        onEdgesChange,
        onConnect,
        onNodeClick: (_event, node) => onNodeClick(node),
        fitView: hasNodes,
        minZoom: 0.45,
        maxZoom: 1.4,
        defaultEdgeOptions: {
          animated: false,
          style: { stroke: "rgba(43, 143, 120, 0.68)", strokeWidth: 1.7 }
        },
        attributionPosition: "bottom-left",
        proOptions: { hideAttribution: true }
      },
      React.createElement(MiniMap, {
        position: "bottom-right",
        pannable: true,
        zoomable: true,
        nodeColor: (node) => getNodeTheme(node.type).tone,
        maskColor: "rgba(19,36,43,0.06)"
      }),
      React.createElement(Controls),
      React.createElement(Background, { gap: 24, size: 1, color: "rgba(19,36,43,0.12)" })
    ),
    !hasNodes
      ? React.createElement(
          "div",
          { className: "studio-empty-overlay" },
          React.createElement(
            "div",
            { className: "studio-empty-state" },
            React.createElement(
              "div",
              { style: { display: "grid", gap: 10 } },
              React.createElement("div", { className: "studio-eyebrow" }, "Guided Start"),
              React.createElement("h3", null, "Blueprint a workflow before wiring the details"),
              React.createElement(
                "p",
                null,
                "Start from a single operator node or load a ready-made path. Studio is designed for fast graph sketching: drop steps, connect outputs, and refine the selected node in the inspector."
              )
            ),
            React.createElement(
              "div",
              { className: "studio-empty-actions" },
              React.createElement(
                "button",
                {
                  type: "button",
                  className: "studio-button-primary",
                  onClick: () => onAddNode && onAddNode("AgentNode")
                },
                "Start with an Agent"
              ),
              React.createElement(
                "button",
                {
                  type: "button",
                  className: "studio-button-warm",
                  onClick: () => onLoadTemplate && onLoadTemplate("approval")
                },
                "Load Approval Flow"
              ),
              React.createElement(
                "button",
                {
                  type: "button",
                  onClick: () => onLoadTemplate && onLoadTemplate("research")
                },
                "Load Research Flow"
              )
            ),
            React.createElement(
              "div",
              { className: "studio-empty-grid" },
              React.createElement(
                "div",
                { className: "studio-empty-card" },
                React.createElement("strong", null, "1. Add structure"),
                React.createElement("p", null, "Choose a starter flow or add nodes one by one from the toolbar.")
              ),
              React.createElement(
                "div",
                { className: "studio-empty-card" },
                React.createElement("strong", null, "2. Wire decisions"),
                React.createElement("p", null, "Connect cards across the canvas to define dependencies and execution order.")
              ),
              React.createElement(
                "div",
                { className: "studio-empty-card" },
                React.createElement("strong", null, "3. Run and inspect"),
                React.createElement("p", null, "Use the bottom panel to watch websocket events and verify the workflow behavior.")
              )
            )
          )
        )
      : null
  );
};
