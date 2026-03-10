const NODE_COPY = {
  AgentNode: {
    title: "Work Step",
    body: "Define the work, choose the agent class, and capture the key details in the form fields first.",
    fields: [
      {
        key: "goal",
        label: "Goal",
        placeholder: "What should this step accomplish?",
        helper: "Describe the concrete outcome you want from this step."
      },
      {
        key: "instructions",
        label: "Instructions",
        placeholder: "Add the directions or context for this step.",
        helper: "Use a few clear sentences instead of raw JSON when possible.",
        multiline: true
      },
      {
        key: "success_criteria",
        label: "Success Looks Like",
        placeholder: "How will you know this step worked?",
        helper: "Keep this short and operator-friendly."
      }
    ]
  },
  DebateNode: {
    title: "Review Step",
    body: "Use this step to challenge, refine, or quality-check work before it moves downstream.",
    fields: [
      {
        key: "review_focus",
        label: "Review Focus",
        placeholder: "What should this review step focus on?",
        helper: "Examples: tone, accuracy, risk, missing context."
      },
      {
        key: "challenge_prompt",
        label: "Challenge Prompt",
        placeholder: "What should this review challenge or improve?",
        helper: "Give the reviewer a simple instruction.",
        multiline: true
      },
      {
        key: "success_criteria",
        label: "Ready When",
        placeholder: "What must be true before this can move on?",
        helper: "Define the quality bar for the next step."
      }
    ]
  },
  ApprovalNode: {
    title: "Ask Me",
    body: "Pause the workflow here and spell out the decision in plain English.",
    fields: [
      {
        key: "approval_question",
        label: "Decision Question",
        placeholder: "What should the human approve?",
        helper: "This becomes the question the operator sees."
      },
      {
        key: "impact",
        label: "Impact",
        placeholder: "What happens if this is approved?",
        helper: "Explain the effect in one plain sentence."
      },
      {
        key: "risk",
        label: "Risk",
        placeholder: "What is the main risk?",
        helper: "Call out the main tradeoff or risk."
      }
    ]
  },
  ConditionNode: {
    title: "Decision",
    body: "Describe the rule that decides which path to take next.",
    fields: [
      {
        key: "decision_rule",
        label: "Decision Rule",
        placeholder: "What rule decides the branch?",
        helper: "Write the rule in plain language."
      },
      {
        key: "yes_path",
        label: "If Yes",
        placeholder: "What happens on the positive path?",
        helper: "Describe the outcome for the first branch."
      },
      {
        key: "no_path",
        label: "If No",
        placeholder: "What happens on the negative path?",
        helper: "Describe the outcome for the fallback branch."
      }
    ]
  },
  LoopNode: {
    title: "Retry/Repeat",
    body: "Use this step for retries, iteration, or refinement with a clear stopping rule.",
    fields: [
      {
        key: "retry_rule",
        label: "Retry Rule",
        placeholder: "When should this repeat?",
        helper: "State the condition that triggers another pass."
      },
      {
        key: "max_attempts",
        label: "Maximum Attempts",
        placeholder: "How many tries are allowed?",
        helper: "Use a plain number or short note."
      },
      {
        key: "stop_condition",
        label: "Stop When",
        placeholder: "When should the loop stop?",
        helper: "Describe the stop condition in simple language."
      }
    ]
  },
  OutputNode: {
    title: "Final Result",
    body: "Describe what the operator should receive at the end of the workflow.",
    fields: [
      {
        key: "result_format",
        label: "Result Format",
        placeholder: "What should the final result look like?",
        helper: "Examples: summary, email draft, approval packet."
      },
      {
        key: "audience",
        label: "Audience",
        placeholder: "Who is this result for?",
        helper: "Call out the human who will use the result."
      },
      {
        key: "delivery_note",
        label: "Delivery Note",
        placeholder: "Anything the operator should know?",
        helper: "Optional context for the final handoff.",
        multiline: true
      }
    ]
  }
};

function fieldValue(config, key) {
  const value = config ? config[key] : "";
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

window.NodeEditor = function NodeEditor({ node, onChange, agentOptions }) {
  const nodeId = node ? node.id : "";
  const configValue = node ? JSON.stringify(node.data?.config || {}, null, 2) : "{}";
  const [configDraft, setConfigDraft] = React.useState(configValue);
  const [configError, setConfigError] = React.useState("");
  const [showAdvanced, setShowAdvanced] = React.useState(false);

  React.useEffect(() => {
    setConfigDraft(configValue);
    setConfigError("");
    setShowAdvanced(false);
  }, [nodeId, configValue]);

  if (!node) {
    return React.createElement(
      "div",
      { className: "studio-editor-shell" },
      React.createElement(
        "div",
        { className: "studio-empty-sidebar" },
        React.createElement("div", { className: "studio-eyebrow" }, "Inspector"),
        React.createElement("h3", null, "Select a step to edit"),
        React.createElement(
          "p",
          null,
          "Pick a card on the canvas to rename it, choose the action, and fill in the structured fields before touching Advanced JSON."
        ),
        React.createElement(
          "div",
          { className: "studio-empty-sidebar-cards" },
          React.createElement(
            "div",
            { className: "studio-empty-sidebar-card" },
            React.createElement("strong", null, "Start with the form"),
            React.createElement("p", { className: "studio-helper" }, "Use the labeled fields first. They write into the same workflow payload underneath.")
          ),
          React.createElement(
            "div",
            { className: "studio-empty-sidebar-card" },
            React.createElement("strong", null, "Open Advanced only when needed"),
            React.createElement("p", { className: "studio-helper" }, "Use Advanced JSON for nested settings or unusual edge cases.")
          ),
          React.createElement(
            "div",
            { className: "studio-empty-sidebar-card" },
            React.createElement("strong", null, "Build left to right"),
            React.createElement("p", { className: "studio-helper" }, "Start with work, add decisions or approval, then end with a final result.")
          )
        )
      )
    );
  }

  const data = node.data || {};
  const copy = NODE_COPY[node.type] || NODE_COPY.AgentNode;
  const structuredFields = Array.isArray(copy.fields) ? copy.fields : [];
  const currentConfig = data.config && typeof data.config === "object" ? data.config : {};

  function update(patch) {
    onChange({ ...node, data: { ...data, ...patch } });
  }

  function updateStructuredField(key, value) {
    const nextConfig = { ...currentConfig };
    const cleaned = String(value || "").trim();
    if (!cleaned) {
      delete nextConfig[key];
    } else {
      nextConfig[key] = value;
    }
    update({ config: nextConfig });
    setConfigDraft(JSON.stringify(nextConfig, null, 2));
    setConfigError("");
  }

  function onConfigChange(event) {
    const nextDraft = event.target.value;
    setConfigDraft(nextDraft);
    try {
      update({ config: JSON.parse(nextDraft || "{}") });
      setConfigError("");
    } catch (_error) {
      setConfigError("Advanced JSON must stay valid before it can be saved.");
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
        React.createElement("span", null, copy.title),
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
        React.createElement("strong", null, "Step Basics"),
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
        React.createElement("strong", null, "Structured Details"),
        structuredFields.map((field) =>
          React.createElement(
            "div",
            { className: "studio-field", key: field.key },
            React.createElement("label", null, field.label),
            field.multiline
              ? React.createElement("textarea", {
                  rows: 4,
                  value: fieldValue(currentConfig, field.key),
                  placeholder: field.placeholder || "",
                  onChange: (event) => updateStructuredField(field.key, event.target.value)
                })
              : React.createElement("input", {
                  value: fieldValue(currentConfig, field.key),
                  placeholder: field.placeholder || "",
                  onChange: (event) => updateStructuredField(field.key, event.target.value)
                }),
            React.createElement("small", null, field.helper || "")
          )
        ),
        React.createElement(
          "small",
          { className: "studio-helper" },
          "These fields map into the same workflow config that Studio saves to the existing API."
        )
      ),
      React.createElement(
        "div",
        { className: "studio-fieldset" },
        React.createElement("strong", null, "Advanced"),
        React.createElement(
          "button",
          {
            type: "button",
            className: "studio-advanced-toggle",
            onClick: () => setShowAdvanced((current) => !current)
          },
          showAdvanced ? "Hide Advanced JSON" : "Show Advanced JSON"
        ),
        showAdvanced
          ? React.createElement(
              "div",
              { className: "studio-field" },
              React.createElement("label", null, "Advanced JSON"),
              React.createElement("textarea", {
                rows: 12,
                value: configDraft,
                onChange: onConfigChange
              }),
              React.createElement(
                "small",
                { className: configError ? "studio-error-text" : "studio-helper" },
                configError || "Use this only for nested settings or fields that are not covered above."
              )
            )
          : React.createElement(
              "small",
              { className: "studio-helper" },
              "Advanced JSON stays hidden by default so the main workflow stays readable."
            )
      )
    )
  );
};
