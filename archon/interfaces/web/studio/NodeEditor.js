const NODE_COPY = {
  AgentNode: {
    title: "Agent step",
    body: "Choose the agent class, set the action name, and attach any JSON config required for execution."
  },
  DebateNode: {
    title: "Debate step",
    body: "Use this node to insert a challenge, critique, or synthesis pass before moving downstream."
  },
  ApprovalNode: {
    title: "Approval gate",
    body: "This step pauses the workflow until a human reviewer or policy gate approves the next action."
  },
  ConditionNode: {
    title: "Condition branch",
    body: "Define the branching action and store the rule details in the JSON config."
  },
  LoopNode: {
    title: "Loop step",
    body: "Use loops for retry, iteration, or refinement patterns with a clearly defined stop condition."
  },
  OutputNode: {
    title: "Output step",
    body: "Capture the final artifact, summary, or operator-facing result from the workflow."
  }
};

window.NodeEditor = function NodeEditor({ node, onChange, agentOptions }) {
  const nodeId = node ? node.id : "";
  const configValue = node ? JSON.stringify(node.data?.config || {}, null, 2) : "{}";
  const [configDraft, setConfigDraft] = React.useState(configValue);
  const [configError, setConfigError] = React.useState("");

  React.useEffect(() => {
    setConfigDraft(configValue);
    setConfigError("");
  }, [nodeId, configValue]);

  if (!node) {
    return React.createElement(
      "div",
      { className: "studio-editor-shell" },
      React.createElement(
        "div",
        { className: "studio-empty-sidebar" },
        React.createElement("div", { className: "studio-eyebrow" }, "Inspector"),
        React.createElement("h3", null, "Select a node to edit"),
        React.createElement(
          "p",
          null,
          "Pick any card on the canvas to rename it, assign an action, choose the agent class, and shape the JSON config that will be saved with the workflow."
        ),
        React.createElement(
          "div",
          { className: "studio-empty-sidebar-cards" },
          React.createElement(
            "div",
            { className: "studio-empty-sidebar-card" },
            React.createElement("strong", null, "Click a node"),
            React.createElement("p", { className: "studio-helper" }, "The inspector updates instantly when you select a card from the canvas.")
          ),
          React.createElement(
            "div",
            { className: "studio-empty-sidebar-card" },
            React.createElement("strong", null, "Tune the config"),
            React.createElement("p", { className: "studio-helper" }, "Keep JSON valid while editing. The config is stored exactly as shown here.")
          ),
          React.createElement(
            "div",
            { className: "studio-empty-sidebar-card" },
            React.createElement("strong", null, "Build from left to right"),
            React.createElement("p", { className: "studio-helper" }, "Add an operator node first, then gates, conditions, loops, and a final output.")
          )
        )
      )
    );
  }

  const data = node.data || {};
  const copy = NODE_COPY[node.type] || NODE_COPY.AgentNode;

  function update(patch) {
    onChange({ ...node, data: { ...data, ...patch } });
  }

  function onConfigChange(event) {
    const nextDraft = event.target.value;
    setConfigDraft(nextDraft);
    try {
      update({ config: JSON.parse(nextDraft || "{}") });
      setConfigError("");
    } catch (_error) {
      setConfigError("Config must be valid JSON before it can be saved.");
    }
  }

  return React.createElement(
    "div",
    { className: "studio-editor-shell" },
    React.createElement(
      "div",
      { className: "studio-editor-header" },
      React.createElement("div", { className: "studio-eyebrow" }, "Inspector"),
      React.createElement("h3", null, data.label || copy.title),
      React.createElement("p", null, copy.body),
      React.createElement(
        "div",
        { className: "studio-inline-meta" },
        React.createElement("span", null, node.type),
        React.createElement("span", null, `ID: ${node.id}`),
        node.type === "AgentNode"
          ? React.createElement("span", null, data.agent_class || "ResearcherAgent")
          : null
      )
    ),
    React.createElement(
      "div",
      { className: "studio-editor-body" },
      React.createElement(
        "div",
        { className: "studio-fieldset" },
        React.createElement("strong", null, "Node Basics"),
        React.createElement(
          "div",
          { className: "studio-field" },
          React.createElement("label", null, "Label"),
          React.createElement("input", {
            value: data.label || "",
            onChange: (event) => update({ label: event.target.value })
          })
        ),
        React.createElement(
          "div",
          { className: "studio-field" },
          React.createElement("label", null, "Action"),
          React.createElement("input", {
            value: data.action || "",
            onChange: (event) => update({ action: event.target.value })
          }),
          React.createElement("small", null, "Use a short action name that matches the step intent.")
        ),
        React.createElement(
          "div",
          { className: "studio-field" },
          React.createElement("label", null, "Description"),
          React.createElement("input", {
            value: data.description || "",
            placeholder: copy.body,
            onChange: (event) => update({ description: event.target.value })
          })
        ),
        node.type === "AgentNode"
          ? React.createElement(
              "div",
              { className: "studio-field" },
              React.createElement("label", null, "Agent Class"),
              React.createElement(
                "select",
                {
                  value: data.agent_class || "",
                  onChange: (event) => update({ agent_class: event.target.value })
                },
                agentOptions.map((option) =>
                  React.createElement("option", { key: option, value: option }, option)
                )
              )
            )
          : null
      ),
      React.createElement(
        "div",
        { className: "studio-fieldset" },
        React.createElement("strong", null, "Config JSON"),
        React.createElement(
          "div",
          { className: "studio-field" },
          React.createElement("label", null, "Structured Config"),
          React.createElement("textarea", {
            rows: 12,
            value: configDraft,
            onChange: onConfigChange
          }),
          React.createElement(
            "small",
            { className: configError ? "studio-error-text" : "studio-helper" },
            configError || "Tip: keep the JSON focused on step-specific runtime settings."
          )
        )
      )
    )
  );
};
