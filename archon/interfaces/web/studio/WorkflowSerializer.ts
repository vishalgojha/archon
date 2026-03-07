export type ValidationError = { code: string; message: string; nodeId?: string };

const KNOWN_AGENTS = new Set([
  "ResearcherAgent",
  "CriticAgent",
  "DevilsAdvocateAgent",
  "FactCheckerAgent",
  "SynthesizerAgent",
  "ProspectorAgent",
  "ICPAgent",
  "OutreachAgent",
  "NurtureAgent",
  "RevenueIntelAgent",
  "PartnerAgent",
  "ChurnDefenseAgent",
  "EmailAgent",
  "WebChatAgent",
  "DebateNode",
  "ApprovalNode",
  "ConditionNode",
  "LoopNode",
  "OutputNode"
]);

export function serialize(nodes, edges) {
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
      agent: node.type === "AgentNode" ? node.data.agent_class : node.type,
      action: node.data.action || node.type.toLowerCase(),
      config: { ...node.data, node_type: node.type },
      dependencies: edgeMap.get(node.id) || []
    })),
    metadata: {
      studio: {
        nodes: Object.fromEntries(nodes.map((node) => [node.id, node])),
        edges
      }
    },
    version: 1,
    created_at: Date.now() / 1000
  };
}

export function deserialize(workflow) {
  const studio = workflow.metadata?.studio || {};
  const nodes = workflow.steps.map((step) => ({
    id: step.step_id,
    type: step.config?.node_type || "AgentNode",
    position: studio.nodes?.[step.step_id]?.position || { x: 0, y: 0 },
    data: studio.nodes?.[step.step_id]?.data || step.config || {}
  }));
  const edges = studio.edges || workflow.steps.flatMap((step) =>
    (step.dependencies || []).map((dep) => ({
      id: `${dep}->${step.step_id}`,
      source: dep,
      target: step.step_id,
      label: step.config?.data_type || ""
    }))
  );
  return { nodes, edges };
}

export function validate(workflow) {
  const errors = [];
  const stepMap = new Map();
  const outgoing = new Map();
  const incoming = new Map();
  let hasReachableOutput = false;

  (workflow.steps || []).forEach((step) => {
    if (stepMap.has(step.step_id)) {
      errors.push({ code: "duplicate", message: `Duplicate step_id '${step.step_id}'.`, nodeId: step.step_id });
      return;
    }
    stepMap.set(step.step_id, step);
    if (!KNOWN_AGENTS.has(step.agent)) {
      errors.push({ code: "missing_agent_class", message: `Unknown agent_class '${step.agent}'.`, nodeId: step.step_id });
    }
    (step.dependencies || []).forEach((dep) => {
      const out = outgoing.get(dep) || new Set();
      out.add(step.step_id);
      outgoing.set(dep, out);
      const inc = incoming.get(step.step_id) || new Set();
      inc.add(dep);
      incoming.set(step.step_id, inc);
    });
  });

  (workflow.steps || []).forEach((step) => {
    if ((step.dependencies || []).some((dep) => !stepMap.has(dep))) {
      errors.push({ code: "missing_dependency", message: "Workflow has a missing dependency.", nodeId: step.step_id });
    }
    if (!incoming.has(step.step_id) && !outgoing.has(step.step_id)) {
      errors.push({ code: "orphan", message: "Node is orphaned.", nodeId: step.step_id });
    }
    if (step.config?.node_type === "OutputNode") {
      hasReachableOutput = true;
    }
  });

  const seen = new Map();
  function visit(id) {
    const state = seen.get(id) || 0;
    if (state === 1) {
      errors.push({ code: "cycle", message: "Cycle detected.", nodeId: id });
      return;
    }
    if (state === 2) return;
    seen.set(id, 1);
    (stepMap.get(id)?.dependencies || []).forEach((dep) => visit(dep));
    seen.set(id, 2);
  }
  [...stepMap.keys()].forEach((id) => visit(id));
  if (!hasReachableOutput) {
    errors.push({ code: "output_unreachable", message: "Output node reachable path is required." });
  }
  return errors;
}
