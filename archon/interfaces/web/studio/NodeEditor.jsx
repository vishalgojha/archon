window.NodeEditor = function NodeEditor({ node, onChange, agentOptions }) {
  if (!node) {
    return React.createElement("div", { style: { padding: 20, color: "var(--studio-muted)" } }, "Select a node to edit.");
  }
  const data = node.data || {};
  function update(patch) {
    onChange({ ...node, data: { ...data, ...patch } });
  }
  return React.createElement(
    "div",
    { style: { padding: 20, display: "grid", gap: 12 } },
    React.createElement("h3", null, node.type),
    React.createElement("label", null, "Action"),
    React.createElement("input", {
      value: data.action || "",
      onChange: (event) => update({ action: event.target.value })
    }),
    node.type === "AgentNode" && React.createElement(React.Fragment, null,
      React.createElement("label", null, "Agent Class"),
      React.createElement(
        "select",
        {
          value: data.agent_class || "",
          onChange: (event) => update({ agent_class: event.target.value })
        },
        agentOptions.map((option) => React.createElement("option", { key: option, value: option }, option))
      )
    ),
    React.createElement("label", null, "Config JSON"),
    React.createElement("textarea", {
      rows: 10,
      value: JSON.stringify(data.config || {}, null, 2),
      onChange: (event) => {
        try { update({ config: JSON.parse(event.target.value || "{}") }); } catch (_) {}
      }
    })
  );
};
