const React = window.React;
const { ReactFlow, MiniMap, Controls, Background, Handle, Position } = window.ReactFlow;

const NODE_THEME = {
  AgentNode: {
    badge: "Work Step",
    hint: "Do one focused piece of work.",
    tone: "#44c2a4",
    surface: "rgba(220, 247, 239, 0.92)"
  },
  DebateNode: {
    badge: "Review Step",
    hint: "Review or challenge work before it moves on.",
    tone: "#f0b85f",
    surface: "rgba(250, 236, 206, 0.96)"
  },
  ApprovalNode: {
    badge: "Ask Me",
    hint: "Pause and wait for a human decision.",
    tone: "#e58a6c",
    surface: "rgba(255, 233, 228, 0.94)"
  },
  ConditionNode: {
    badge: "Decision",
    hint: "Pick a path based on one rule.",
    tone: "#659ae8",
    surface: "rgba(227, 239, 255, 0.94)"
  },
  LoopNode: {
    badge: "Retry/Repeat",
    hint: "Repeat until the stop rule is met.",
    tone: "#8f80de",
    surface: "rgba(236, 232, 255, 0.94)"
  },
  OutputNode: {
    badge: "Final Result",
    hint: "Collect the answer or artifact for the operator.",
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
  onLoadTemplate,
  templateOptions
}) {
  const hasNodes = Array.isArray(nodes) && nodes.length > 0;
  const templates = Array.isArray(templateOptions) ? templateOptions : [];

  return React.createElement(
    "div",
    { className: "studio-canvas-shell" },
    React.createElement(
      "div",
      { className: "studio-canvas-status" },
      React.createElement("span", null, `${nodes.length} node${nodes.length === 1 ? "" : "s"}`),
      React.createElement("span", null, `${edges.length} connection${edges.length === 1 ? "" : "s"}`),
      React.createElement("span", null, hasNodes ? "Drag, connect, then edit on the right." : "Start with a use-case template or a single step.")
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
                "Choose the use case that best matches the job. Studio will load a starting workflow you can tune in the inspector."
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
                  onClick: () => onLoadTemplate && onLoadTemplate("research_topic")
                },
                "Research a topic"
              ),
              React.createElement(
                "button",
                {
                  type: "button",
                  className: "studio-button-warm",
                  onClick: () => onAddNode && onAddNode("AgentNode")
                },
                "Start with a Work Step"
              )
            ),
            React.createElement(
              "div",
              { className: "studio-template-grid" },
              templates.map((template) =>
                React.createElement(
                  "div",
                  { className: "studio-template-card", key: template.kind },
                  React.createElement("strong", null, template.label),
                  React.createElement("p", null, template.description),
                  React.createElement(
                    "button",
                    {
                      type: "button",
                      onClick: () => onLoadTemplate && onLoadTemplate(template.kind)
                    },
                    "Load template"
                  )
                )
              )
            )
          )
        )
      : null
  );
};
