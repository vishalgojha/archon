(function () {
  const React = window.React;
  const ReactDOM = window.ReactDOM;
  const ReactFlow = window.ReactFlow;
  const dagre = window.dagreD3 && window.dagreD3.graphlib ? window.dagreD3.graphlib : null;

  const NODE_TYPES = ["AgentNode", "DebateNode", "ApprovalNode", "ConditionNode", "LoopNode", "OutputNode"];
  const NODE_LABELS = {
    AgentNode: "Work Step",
    DebateNode: "Review Step",
    ApprovalNode: "Ask Me",
    ConditionNode: "Decision",
    LoopNode: "Retry/Repeat",
    OutputNode: "Final Result"
  };
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
      label: NODE_LABELS.AgentNode,
      action: "agent_step",
      description: "Do one focused piece of work before the workflow moves on."
    },
    DebateNode: {
      label: NODE_LABELS.DebateNode,
      action: "debate_round",
      description: "Review, challenge, or tighten a draft before it moves downstream."
    },
    ApprovalNode: {
      label: NODE_LABELS.ApprovalNode,
      action: "approval_gate",
      description: "Pause the workflow and ask for a human decision."
    },
    ConditionNode: {
      label: NODE_LABELS.ConditionNode,
      action: "branch_condition",
      description: "Choose the next path based on one rule or decision."
    },
    LoopNode: {
      label: NODE_LABELS.LoopNode,
      action: "loop_step",
      description: "Repeat a step until a stop rule is met."
    },
    OutputNode: {
      label: NODE_LABELS.OutputNode,
      action: "output_result",
      description: "Capture the final answer or artifact for the operator."
    }
  };
  const TEMPLATE_OPTIONS = [
    {
      kind: "research_topic",
      label: "Research a topic",
      description: "Gather facts, review them, and return a clear answer."
    },
    {
      kind: "draft_reply",
      label: "Draft a reply",
      description: "Write a response, review it, and hold for approval."
    },
    {
      kind: "approval_workflow",
      label: "Approval workflow",
      description: "Prepare work, ask you for approval, then produce the approved result."
    },
    {
      kind: "lead_qualification",
      label: "Lead qualification",
      description: "Review an inbound lead, decide qualification, and recommend next steps."
    },
    {
      kind: "publish_content",
      label: "Publish content",
      description: "Draft, review, approve, and package content for publishing."
    }
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

  function getNodeSpec(type) {
    return NODE_LIBRARY[type] || NODE_LIBRARY.AgentNode;
  }

  function nodeLabel(type) {
    return NODE_LABELS[type] || NODE_LABELS.AgentNode;
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
    const normalizedKind = {
      research: "research_topic",
      approval: "approval_workflow",
      debate: "draft_reply"
    }[kind] || kind;

    if (normalizedKind === "draft_reply") {
      return createLinearTemplate("Draft a reply", [
        {
          type: "AgentNode",
          label: "Draft the reply",
          action: "draft_reply",
          description: "Write a clear response for the recipient.",
          agentClass: "ResearcherAgent",
          config: {
            goal: "Create a helpful draft reply.",
            instructions: "Use the available context and write a concise, ready-to-send response.",
            success_criteria: "The reply is clear, on-topic, and ready for review."
          }
        },
        {
          type: "DebateNode",
          label: "Review the draft",
          action: "review_reply",
          description: "Check tone, accuracy, and completeness before asking for approval.",
          config: {
            review_focus: "Tone, accuracy, and missing context",
            challenge_prompt: "Flag anything that could confuse the recipient.",
            success_criteria: "The reply is safe and clear."
          }
        },
        {
          type: "ApprovalNode",
          label: "Approve the reply",
          action: "request_approval",
          description: "Ask for a final human decision before sending.",
          config: {
            approval_question: "Should this reply be sent?",
            impact: "The drafted message will go out to the recipient.",
            risk: "Outbound messages cannot be quietly undone."
          }
        },
        {
          type: "OutputNode",
          label: "Ready to send",
          action: "deliver_reply",
          description: "Present the approved reply as the final result.",
          config: {
            result_format: "Final reply draft",
            audience: "Operator"
          }
        }
      ]);
    }

    if (normalizedKind === "approval_workflow") {
      return createLinearTemplate("Approval workflow", [
        {
          type: "AgentNode",
          label: "Prepare the work",
          action: "prepare_work",
          description: "Assemble the material that needs review.",
          agentClass: "ResearcherAgent",
          config: {
            goal: "Prepare the next action for approval.",
            instructions: "Summarize the proposed action and the expected outcome.",
            success_criteria: "A reviewer can make a quick decision."
          }
        },
        {
          type: "ApprovalNode",
          label: "Ask me to approve",
          action: "request_approval",
          description: "Pause here until a person approves the next action.",
          config: {
            approval_question: "Should ARCHON continue?",
            impact: "The workflow will continue to the next stage.",
            risk: "A human check is required before release."
          }
        },
        {
          type: "OutputNode",
          label: "Approved result",
          action: "publish_output",
          description: "Show the approved result or next action.",
          config: {
            result_format: "Approved summary",
            audience: "Operator"
          }
        }
      ]);
    }

    if (normalizedKind === "lead_qualification") {
      return createLinearTemplate("Lead qualification", [
        {
          type: "AgentNode",
          label: "Review the lead",
          action: "review_lead",
          description: "Pull out the most important signals from the lead.",
          agentClass: "ProspectorAgent",
          config: {
            goal: "Summarize the lead and highlight fit signals.",
            instructions: "Look for urgency, budget, location, and intent.",
            success_criteria: "The lead summary is ready for a qualification decision."
          }
        },
        {
          type: "ConditionNode",
          label: "Is it qualified?",
          action: "qualify_lead",
          description: "Branch based on fit and urgency.",
          config: {
            decision_rule: "If budget, timing, and fit are strong, treat as qualified.",
            yes_path: "Recommend immediate follow-up.",
            no_path: "Recommend nurture or disqualify."
          }
        },
        {
          type: "OutputNode",
          label: "Next action",
          action: "recommend_next_action",
          description: "Show the qualification result and recommended follow-up.",
          config: {
            result_format: "Lead qualification summary",
            audience: "Sales operator"
          }
        }
      ]);
    }

    if (normalizedKind === "publish_content") {
      return createLinearTemplate("Publish content", [
        {
          type: "AgentNode",
          label: "Draft the content",
          action: "draft_content",
          description: "Create a publishable first draft.",
          agentClass: "ResearcherAgent",
          config: {
            goal: "Draft a publishable content asset.",
            instructions: "Write a strong draft with a clear angle and hook.",
            success_criteria: "The draft is solid enough for review."
          }
        },
        {
          type: "DebateNode",
          label: "Review the draft",
          action: "review_content",
          description: "Polish clarity, quality, and factual confidence.",
          config: {
            review_focus: "Quality, accuracy, and polish",
            challenge_prompt: "Find weak claims or places that need tightening.",
            success_criteria: "The content is ready for approval."
          }
        },
        {
          type: "ApprovalNode",
          label: "Approve publishing",
          action: "request_publish_approval",
          description: "Ask for a final publishing decision.",
          config: {
            approval_question: "Should this content be published?",
            impact: "The content will be released outside ARCHON.",
            risk: "Published content may require manual correction later."
          }
        },
        {
          type: "OutputNode",
          label: "Publishing package",
          action: "publish_content",
          description: "Package the final approved content for publishing.",
          config: {
            result_format: "Publishing-ready content",
            audience: "Operator"
          }
        }
      ]);
    }

    return createLinearTemplate("Research a topic", [
      {
        type: "AgentNode",
        label: "Gather the facts",
        action: "gather_research",
        description: "Collect the source-backed details that matter.",
        agentClass: "ResearcherAgent",
        config: {
          goal: "Answer the question with reliable findings.",
          instructions: "Gather the most relevant facts, sources, and context.",
          success_criteria: "The research is ready for review."
        }
      },
      {
        type: "DebateNode",
        label: "Review the findings",
        action: "review_findings",
        description: "Check for weak claims, missing context, or unclear logic.",
        config: {
          review_focus: "Accuracy and gaps",
          challenge_prompt: "Challenge claims that are weak or unsupported.",
          success_criteria: "Only supported findings remain."
        }
      },
      {
        type: "OutputNode",
        label: "Share the answer",
        action: "deliver_result",
        description: "Return a clear final result for the operator.",
        config: {
          result_format: "Answer with supporting bullets",
          audience: "Operator"
        }
      }
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
        config: step?.config?.config && typeof step.config.config === "object" ? step.config.config : {},
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

  function normalizeWords(value) {
    return String(value || "")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function compactText(value, maxLength = 220) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    if (text.length <= maxLength) {
      return text;
    }
    return `${text.slice(0, maxLength)}...`;
  }

  function firstText(values) {
    for (let idx = 0; idx < values.length; idx += 1) {
      const value = values[idx];
      if (typeof value === "string" && value.trim()) {
        return value.trim();
      }
      if (value && typeof value === "object") {
        try {
          const preview = JSON.stringify(value);
          if (preview) {
            return compactText(preview);
          }
        } catch (_error) {
        }
      }
    }
    return "";
  }

  function inferVerbLabel(value) {
    const text = normalizeWords(value).toLowerCase();
    if (!text) {
      return "Working";
    }
    if (/approval|ask me|reviewer/.test(text)) {
      return "Waiting for approval";
    }
    if (/research|fact|source/.test(text)) {
      return "Researching";
    }
    if (/draft|reply|write|message/.test(text)) {
      return "Drafting";
    }
    if (/review|critique|debate|polish|quality/.test(text)) {
      return "Reviewing";
    }
    if (/qualif|lead|score/.test(text)) {
      return "Qualifying";
    }
    if (/publish|post|release/.test(text)) {
      return "Publishing";
    }
    if (/retry|repeat|loop/.test(text)) {
      return "Retrying";
    }
    if (/decision|condition|branch/.test(text)) {
      return "Deciding";
    }
    return "Working";
  }

  function approvalCopy(event) {
    const haystack = [
      event?.action,
      event?.action_type,
      event?.payload?.provider,
      event?.payload?.url,
      event?.agent,
      event?.step_id
    ]
      .map((value) => normalizeWords(value).toLowerCase())
      .join(" ");
    const preview = firstText([
      event?.payload?.message,
      event?.payload?.content,
      event?.payload?.url ? `Target: ${event.payload.url}` : "",
      event?.message
    ]);

    if (/(send|reply|message|email|webchat|sms|whatsapp)/.test(haystack)) {
      return {
        question: "Approve sending this reply?",
        reason: "The run paused because it needs a human check before sending a message.",
        preview
      };
    }
    if (/(publish|post|release|content)/.test(haystack)) {
      return {
        question: "Approve publishing this result?",
        reason: "The run reached a publish step and is waiting for sign-off.",
        preview
      };
    }
    return {
      question: "Approve the next step?",
      reason: "The run is paused until a person approves the next action.",
      preview
    };
  }

  function runStatusLabel(status) {
    if (status === "completed") {
      return "Completed";
    }
    if (status === "blocked") {
      return "Blocked";
    }
    if (status === "waiting") {
      return "Waiting";
    }
    if (status === "running") {
      return "Running";
    }
    return "Idle";
  }

  function summarizeRunEvents(runEvents) {
    const activity = [];
    const blockers = [];
    const decisionMap = new Map();
    let status = runEvents.length ? "running" : "idle";
    let result = "";

    runEvents.forEach((event) => {
      const type = String(event?.type || event?.state || "event").toLowerCase();
      if (type === "status") {
        const message = firstText([event?.message]) || "Waiting for run updates.";
        const statusTitle = /closed/i.test(message)
          ? "Stream closed"
          : /connected/i.test(message)
            ? "Connected"
            : "Connecting";
        activity.push({
          title: statusTitle,
          detail: message
        });
        return;
      }
      if (type === "workflow_started") {
        status = "running";
        activity.push({
          title: "Starting",
          detail: firstText([event?.workflow_name]) || "The workflow run has started."
        });
        return;
      }
      if (type === "step_started" || type === "agent_start") {
        status = "running";
        activity.push({
          title: inferVerbLabel(firstText([event?.action, event?.agent, event?.step_id])),
          detail:
            firstText([event?.message, event?.step_id && `Step ${event.step_id} is underway.`]) ||
            "ARCHON is working on the next step."
        });
        return;
      }
      if (type === "approval_required") {
        status = "waiting";
        const copy = approvalCopy(event);
        const decisionId = String(event?.request_id || event?.action_id || event?.step_id || decisionMap.size);
        decisionMap.set(decisionId, copy);
        activity.push({
          title: "Waiting for approval",
          detail: copy.question
        });
        return;
      }
      if (type === "approval_result" || type === "approval_resolved") {
        const decisionId = String(event?.request_id || event?.action_id || "");
        if (decisionId) {
          decisionMap.delete(decisionId);
        }
        activity.push({
          title: "Decision recorded",
          detail: "A pending decision was resolved."
        });
        status = decisionMap.size > 0 ? "waiting" : status;
        return;
      }
      if (type === "step_completed") {
        result = firstText([event?.output_text, event?.summary, result]);
        activity.push({
          title: "Completed",
          detail: firstText([event?.summary, event?.output_text]) || "A workflow step finished."
        });
        return;
      }
      if (type === "workflow_completed") {
        status = "completed";
        result = firstText([event?.final_answer, result]);
        activity.push({
          title: "Completed",
          detail: firstText([event?.final_answer]) || "The workflow finished successfully."
        });
        return;
      }
      if (type === "workflow_failed" || type === "error") {
        status = "blocked";
        const message = firstText([event?.message, event?.detail]) || "The run failed.";
        blockers.push(message);
        activity.push({
          title: "Blocked",
          detail: message
        });
      }
    });

    const decisions = Array.from(decisionMap.values());
    const uniqueBlockers = Array.from(new Set(blockers.filter(Boolean)));

    if (!result) {
      result =
        status === "completed"
          ? "The run completed without a final result summary."
          : status === "running" || status === "waiting"
            ? "The run is still in progress."
            : "No run output yet.";
    }

    let nextAction = "Choose a template or add a step, then press Run.";
    if (uniqueBlockers.length > 0) {
      nextAction = "Fix the blocker, then run the workflow again.";
    } else if (decisions.length > 0) {
      nextAction = "Review the pending decision so the workflow can continue.";
    } else if (status === "completed") {
      nextAction = "Review the result, then save the workflow or refine a step and run again.";
    } else if (status === "running" || status === "waiting") {
      nextAction = "Keep this panel open while the run finishes.";
    }

    return {
      status,
      statusLabel: runStatusLabel(status),
      result,
      blockers: uniqueBlockers,
      decisions,
      nextAction,
      activity: activity.slice(-5).reverse()
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
    const [templateMenuValue, setTemplateMenuValue] = React.useState("");
    const runSummary = React.useMemo(() => summarizeRunEvents(runEvents), [runEvents]);

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
      commitWorkflow(template, template.name, `Loaded the "${template.name}" template.`);
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
        showNotice("Run started. Studio will summarize the result below.", "info");
        const workflow = serialize(nodes, edges);
        workflow.name = workflowName.trim() || "Studio Workflow";
        const response = await studioApiFetch("/studio/run", {
          method: "POST",
          body: JSON.stringify({ workflow })
        });
        const payload = await response.json();
        const socketUrl = new URL(payload.websocket_path, window.location.origin);
        const token = getToken();
        if (token) {
          socketUrl.searchParams.set("token", token);
        }
        const socket = new WebSocket(socketUrl.toString().replace(/^http/, "ws"));
        socket.onopen = () => {
          setRunEvents((current) => [...current, { type: "status", message: "Connected to the run stream." }]);
          showNotice("Run connected.", "success");
        };
        socket.onmessage = (event) => {
          try {
            const frame = JSON.parse(event.data);
            setRunEvents((current) => [...current, frame]);
          } catch (_error) {
            setRunEvents((current) => [...current, { type: "error", message: "Received an unreadable run update." }]);
          }
        };
        socket.onerror = () => {
          setRunEvents((current) => [...current, { type: "error", message: "Run connection error." }]);
          showNotice("Run connection error.", "error");
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
          React.createElement("h1", null, "Build workflows in plain English"),
          React.createElement(
            "p",
            null,
            "Start from a use case, fill in the form fields, and Studio will serialize the same workflow payload for the existing API underneath."
          ),
          React.createElement(
            "div",
            { className: "studio-chip-row" },
            React.createElement("div", { className: "studio-chip" }, React.createElement("strong", null, nodes.length), "Nodes"),
            React.createElement("div", { className: "studio-chip" }, React.createElement("strong", null, edges.length), "Connections"),
            React.createElement("div", { className: "studio-chip" }, React.createElement("strong", null, runSummary.statusLabel), "Run status")
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
                "Use a use-case template first, then fine-tune the selected step in the inspector."
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
              React.createElement("option", { value: "" }, "Add Step"),
              NODE_TYPES.map((type) => React.createElement("option", { key: type, value: type }, nodeLabel(type)))
            ),
            React.createElement(
              "select",
              {
                value: templateMenuValue,
                onChange: (event) => {
                  const nextTemplate = event.target.value;
                  setTemplateMenuValue("");
                  if (!nextTemplate) {
                    return;
                  }
                  loadTemplate(nextTemplate);
                }
              },
              React.createElement("option", { value: "" }, "Use-case Template"),
              TEMPLATE_OPTIONS.map((template) =>
                React.createElement("option", { key: template.kind, value: template.kind }, template.label)
              )
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
            React.createElement("button", { type: "button", onClick: importJson }, "Import JSON")
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
                "Arrange the workflow left to right. Start with a use-case template, then edit the selected step on the right."
              )
            ),
            React.createElement(
              "div",
              { className: "studio-section-actions" },
              React.createElement("button", { type: "button", onClick: () => addNode("AgentNode") }, nodeLabel("AgentNode")),
              React.createElement("button", { type: "button", onClick: () => addNode("ApprovalNode") }, nodeLabel("ApprovalNode")),
              React.createElement("button", { type: "button", onClick: () => addNode("OutputNode") }, nodeLabel("OutputNode"))
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
              onLoadTemplate: loadTemplate,
              templateOptions: TEMPLATE_OPTIONS
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
              "See the run in operator language: the result, blockers, decisions, and the next action."
            )
          ),
          React.createElement(
            "div",
            { className: "studio-run-status-row" },
            React.createElement("div", { className: "studio-status-pill" }, runSummary.statusLabel)
          )
        ),
        React.createElement(
          "div",
          { className: "studio-run-summary-grid" },
          React.createElement(
            "article",
            { className: "studio-run-card" },
            React.createElement("h3", null, "Result"),
            React.createElement("p", { className: "studio-run-highlight" }, runSummary.result),
            runSummary.activity.length
              ? React.createElement(
                  "ul",
                  { className: "studio-clean-list" },
                  runSummary.activity.map((item, index) =>
                    React.createElement(
                      "li",
                      { key: `${item.title}-${index}` },
                      React.createElement("strong", null, item.title),
                      React.createElement("span", null, item.detail)
                    )
                  )
                )
              : React.createElement(
                  "div",
                  { className: "studio-summary-empty" },
                  "Press Run after adding a few steps."
                )
          ),
          React.createElement(
            "article",
            { className: "studio-run-card" },
            React.createElement("h3", null, "Blockers"),
            runSummary.blockers.length
              ? React.createElement(
                  "ul",
                  { className: "studio-clean-list" },
                  runSummary.blockers.map((item) =>
                    React.createElement(
                      "li",
                      { key: item },
                      React.createElement("span", null, item)
                    )
                  )
                )
              : React.createElement(
                  "div",
                  { className: "studio-summary-empty" },
                  "No blockers yet."
                )
          ),
          React.createElement(
            "article",
            { className: "studio-run-card" },
            React.createElement("h3", null, "Human decisions needed"),
            runSummary.decisions.length
              ? React.createElement(
                  "ul",
                  { className: "studio-clean-list" },
                  runSummary.decisions.map((item, index) =>
                    React.createElement(
                      "li",
                      { key: `${item.question}-${index}` },
                      React.createElement("strong", null, item.question),
                      React.createElement("span", null, item.reason),
                      item.preview
                        ? React.createElement("span", { className: "studio-helper" }, item.preview)
                        : null
                    )
                  )
                )
              : React.createElement(
                  "div",
                  { className: "studio-summary-empty" },
                  "No human decisions are waiting."
                )
          ),
          React.createElement(
            "article",
            { className: "studio-run-card" },
            React.createElement("h3", null, "Recommended next action"),
            React.createElement("p", { className: "studio-run-highlight" }, runSummary.nextAction)
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
