import { Dispatch, SetStateAction, useEffect, useMemo, useState } from "react";
import { apiFetch, streamJsonLines } from "./lib/api";

const NAV_ITEMS = [
  { id: "builder", label: "Agent Builder" },
  { id: "skills", label: "Skills" },
  { id: "providers", label: "Providers" },
  { id: "deploy", label: "Deploy" },
  { id: "chat", label: "Chat" },
  { id: "evolution", label: "Evolution Log" }
] as const;

type ViewId = (typeof NAV_ITEMS)[number]["id"];

type Skill = {
  name: string;
  state: string;
  provider_preference: string | null;
  cost_tier: string;
  version: number;
};

type ProviderEntry = {
  name: string;
  status: "live" | "off" | "missing_key";
  roles: string[];
  env_key: string | null;
  key_present: boolean | null;
  key_required: boolean;
  base_url: string | null;
};

type ProviderRoleResponse = {
  roles: Record<string, string>;
  providers: ProviderEntry[];
  live_provider_calls: boolean;
};

type WorkflowNode = {
  id: string;
  name: string;
  provider: string | null;
  cost_tier: string;
  state: string;
  config: Record<string, string>;
};

type Workflow = {
  id: string;
  name: string;
  nodes: WorkflowNode[];
  created_at: number;
};

type Deployment = {
  id: string;
  name: string;
  description: string;
  url: string;
  entry_skill: string;
  created_at: number;
};

type EvolutionEntry = {
  entry_id: string;
  timestamp: number;
  event_type: string;
  workflow_id: string;
  actor: string;
  payload: Record<string, any>;
};

type StreamLine = {
  type: "event" | "result" | "error";
  payload: any;
  timestamp?: number;
};

type Message = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  meta?: Record<string, any>;
};

const WORKFLOW_STORAGE_KEY = "archon_studio_workflows";

function loadWorkflows(): Workflow[] {
  try {
    const raw = localStorage.getItem(WORKFLOW_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Workflow[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveWorkflows(workflows: Workflow[]) {
  localStorage.setItem(WORKFLOW_STORAGE_KEY, JSON.stringify(workflows));
}

function formatTimestamp(value?: number) {
  if (!value) return "--:--";
  const dt = new Date(value * 1000);
  return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function createNodeFromSkill(skill: Skill): WorkflowNode {
  return {
    id: `node-${crypto.randomUUID().slice(0, 8)}`,
    name: skill.name,
    provider: skill.provider_preference,
    cost_tier: skill.cost_tier,
    state: skill.state,
    config: {
      mode: "debate",
      budget: "auto",
      retries: "2"
    }
  };
}

export default function App() {
  const [activeView, setActiveView] = useState<ViewId>("builder");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [skillsLoading, setSkillsLoading] = useState(false);

  const [providers, setProviders] = useState<ProviderRoleResponse | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);

  const [workflows, setWorkflows] = useState<Workflow[]>(() => loadWorkflows());
  const [activeWorkflowId, setActiveWorkflowId] = useState<string | null>(
    workflows[0]?.id ?? null
  );
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showSkillPicker, setShowSkillPicker] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const [skillsLog, setSkillsLog] = useState<Message[]>([]);
  const [deployLog, setDeployLog] = useState<Message[]>([]);

  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [deploymentForm, setDeploymentForm] = useState({
    name: "",
    description: "",
    accent: "#6ee7ff",
    logoUrl: "",
    entrySkill: ""
  });

  const [chatMessages, setChatMessages] = useState<Message[]>([]);
  const [chatInput, setChatInput] = useState("");

  const [statusBar, setStatusBar] = useState({
    provider: "auto",
    mode: "debate",
    tokens: "n/a",
    cost: "$0.00"
  });

  const [evolutionLog, setEvolutionLog] = useState<EvolutionEntry[]>([]);
  const [evolutionFilter, setEvolutionFilter] = useState({
    skill: "",
    provider: "",
    task: "",
    date: ""
  });

  const activeWorkflow = useMemo(
    () => workflows.find((wf) => wf.id === activeWorkflowId) ?? null,
    [workflows, activeWorkflowId]
  );

  useEffect(() => {
    saveWorkflows(workflows);
  }, [workflows]);

  useEffect(() => {
    if (!toast) return;
    const timeout = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    let cancel = false;
    const loadSkills = async () => {
      setSkillsLoading(true);
      setSkillsError(null);
      try {
        const data = await apiFetch<{ skills: Skill[] }>("/api/skills");
        if (!cancel) setSkills(data.skills || []);
      } catch (err) {
        if (!cancel) setSkillsError((err as Error).message);
      } finally {
        if (!cancel) setSkillsLoading(false);
      }
    };
    loadSkills();
    const interval = setInterval(loadSkills, 5000);
    return () => {
      cancel = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancel = false;
    const loadProviders = async () => {
      try {
        const data = await apiFetch<ProviderRoleResponse>("/api/providers");
        if (!cancel) setProviders(data);
      } catch (err) {
        if (!cancel) setProvidersError((err as Error).message);
      }
    };
    loadProviders();
    const interval = setInterval(loadProviders, 5000);
    return () => {
      cancel = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (activeView !== "deploy") return;
    const loadDeployments = async () => {
      try {
        const data = await apiFetch<{ deployments: Deployment[] }>("/api/deployments");
        setDeployments(data.deployments || []);
      } catch (err) {
        setDeployments([]);
      }
    };
    loadDeployments();
  }, [activeView]);

  useEffect(() => {
    if (activeView !== "evolution") return;
    const loadEvolution = async () => {
      const query = new URLSearchParams();
      if (evolutionFilter.skill) query.set("skill", evolutionFilter.skill);
      if (evolutionFilter.provider) query.set("provider", evolutionFilter.provider);
      if (evolutionFilter.task) query.set("task", evolutionFilter.task);
      if (evolutionFilter.date) query.set("date", evolutionFilter.date);
      try {
        const data = await apiFetch<{ entries: EvolutionEntry[] }>(
          `/api/evolution/log?${query.toString()}`
        );
        setEvolutionLog(data.entries || []);
      } catch {
        setEvolutionLog([]);
      }
    };
    loadEvolution();
  }, [activeView, evolutionFilter]);

  const availableProviders = useMemo(() => {
    return providers?.providers.map((item) => item.name) ?? [];
  }, [providers]);

  const handleAddWorkflow = () => {
    const name = `Workflow ${workflows.length + 1}`;
    const fresh: Workflow = {
      id: crypto.randomUUID(),
      name,
      nodes: [],
      created_at: Date.now()
    };
    setWorkflows((prev) => [fresh, ...prev]);
    setActiveWorkflowId(fresh.id);
    setSelectedNodeId(null);
    setToast("New workflow created.");
  };

  const handleSaveWorkflow = () => {
    if (!activeWorkflow) return;
    const name = prompt("Name this agent workflow", activeWorkflow.name);
    if (!name) return;
    setWorkflows((prev) =>
      prev.map((wf) => (wf.id === activeWorkflow.id ? { ...wf, name } : wf))
    );
    setToast("Workflow saved to local library.");
  };

  const handleAddSkillNode = (skill: Skill) => {
    if (!activeWorkflow) return;
    const node = createNodeFromSkill(skill);
    setWorkflows((prev) =>
      prev.map((wf) =>
        wf.id === activeWorkflow.id ? { ...wf, nodes: [...wf.nodes, node] } : wf
      )
    );
    setSelectedNodeId(node.id);
    setShowSkillPicker(false);
  };

  const handleRemoveNode = (nodeId: string) => {
    if (!activeWorkflow) return;
    setWorkflows((prev) =>
      prev.map((wf) =>
        wf.id === activeWorkflow.id
          ? { ...wf, nodes: wf.nodes.filter((node) => node.id !== nodeId) }
          : wf
      )
    );
    setSelectedNodeId(null);
  };

  const updateNode = (nodeId: string, update: Partial<WorkflowNode>) => {
    if (!activeWorkflow) return;
    setWorkflows((prev) =>
      prev.map((wf) =>
        wf.id === activeWorkflow.id
          ? {
              ...wf,
              nodes: wf.nodes.map((node) =>
                node.id === nodeId ? { ...node, ...update } : node
              )
            }
          : wf
      )
    );
  };

  const selectedNode = activeWorkflow?.nodes.find((node) => node.id === selectedNodeId) ?? null;

  const appendLog = (setter: Dispatch<SetStateAction<Message[]>>, line: Message) => {
    setter((prev) => [...prev, line]);
  };

  const runSkillProposal = async () => {
    setSkillsLog([]);
    try {
      await streamJsonLines("/api/skills/propose?stream=1", {}, (line: StreamLine) => {
        if (line.type === "event") {
          appendLog(setSkillsLog, {
            id: crypto.randomUUID(),
            role: "system",
            content: `${formatTimestamp(line.timestamp)} · ${line.payload.type}`,
            meta: line.payload
          });
        }
        if (line.type === "result") {
          appendLog(setSkillsLog, {
            id: crypto.randomUUID(),
            role: "assistant",
            content: `Proposal ${line.payload?.status || "complete"}.`,
            meta: line.payload
          });
        }
        if (line.type === "error") {
          appendLog(setSkillsLog, {
            id: crypto.randomUUID(),
            role: "system",
            content: `Error: ${line.payload?.message || "Unknown error"}`
          });
        }
      });
    } catch (err) {
      appendLog(setSkillsLog, {
        id: crypto.randomUUID(),
        role: "system",
        content: `Error: ${(err as Error).message}`
      });
    }
  };

  const runSkillPromotion = async (name: string) => {
    setSkillsLog([]);
    try {
      await streamJsonLines(`/api/skills/apply/${encodeURIComponent(name)}?stream=1`, {}, (line) => {
        if (line.type === "event") {
          appendLog(setSkillsLog, {
            id: crypto.randomUUID(),
            role: "system",
            content: `${formatTimestamp(line.timestamp)} · ${line.payload.type}`,
            meta: line.payload
          });
        }
        if (line.type === "result") {
          appendLog(setSkillsLog, {
            id: crypto.randomUUID(),
            role: "assistant",
            content: `Promotion ${line.payload?.status || "complete"}.`,
            meta: line.payload
          });
        }
        if (line.type === "error") {
          appendLog(setSkillsLog, {
            id: crypto.randomUUID(),
            role: "system",
            content: `Error: ${line.payload?.message || "Unknown error"}`
          });
        }
      });
    } catch (err) {
      appendLog(setSkillsLog, {
        id: crypto.randomUUID(),
        role: "system",
        content: `Error: ${(err as Error).message}`
      });
    }
  };

  const handleDeploySubmit = async () => {
    if (!deploymentForm.name || !deploymentForm.entrySkill) {
      setToast("Name and entry skill are required.");
      return;
    }
    const workflow = workflows.find((wf) => wf.id === activeWorkflowId) ?? workflows[0];
    if (!workflow) {
      setToast("Create a workflow first.");
      return;
    }

    setDeployLog([]);
    try {
      await streamJsonLines("/api/deployments?stream=1", {
        name: deploymentForm.name,
        description: deploymentForm.description,
        branding: {
          name: deploymentForm.name,
          accent_color: deploymentForm.accent,
          logo_url: deploymentForm.logoUrl
        },
        entry_skill: deploymentForm.entrySkill,
        workflow
      }, (line: StreamLine) => {
        if (line.type === "event") {
          appendLog(setDeployLog, {
            id: crypto.randomUUID(),
            role: "system",
            content: `${formatTimestamp(line.timestamp)} · ${line.payload.type}`,
            meta: line.payload
          });
        }
        if (line.type === "result") {
          appendLog(setDeployLog, {
            id: crypto.randomUUID(),
            role: "assistant",
            content: `Deployment ready at ${line.payload?.url || ""}`,
            meta: line.payload
          });
          setToast("Deployment created.");
        }
        if (line.type === "error") {
          appendLog(setDeployLog, {
            id: crypto.randomUUID(),
            role: "system",
            content: `Error: ${line.payload?.message || "Unknown error"}`
          });
        }
      });
      const data = await apiFetch<{ deployments: Deployment[] }>("/api/deployments");
      setDeployments(data.deployments || []);
    } catch (err) {
      appendLog(setDeployLog, {
        id: crypto.randomUUID(),
        role: "system",
        content: `Error: ${(err as Error).message}`
      });
    }
  };

  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const goal = chatInput.trim();
    setChatInput("");
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: goal
    };
    setChatMessages((prev) => [...prev, userMessage]);

    try {
      await streamJsonLines("/api/tasks?stream=1", { goal, mode: "debate" }, (line: StreamLine) => {
        if (line.type === "event") {
          if (line.payload?.type === "approval_required") {
            setChatMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: "system",
                content: "Approval required",
                meta: line.payload
              }
            ]);
            return;
          }
          if (line.payload?.type === "provider_routing") {
            const providersUsed = (line.payload?.providers_used || []).join(", ") || "auto";
            setStatusBar((prev) => ({ ...prev, provider: providersUsed }));
          }
          setChatMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "system",
              content: `${formatTimestamp(line.timestamp)} · ${line.payload.type}`,
              meta: line.payload
            }
          ]);
        }
        if (line.type === "result") {
          setChatMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: line.payload?.final_answer || "Completed.",
              meta: line.payload
            }
          ]);
          if (line.payload?.budget) {
            const cost = Number(line.payload.budget.total_cost_usd || line.payload.budget.spent_usd || 0);
            setStatusBar((prev) => ({
              ...prev,
              cost: `$${cost.toFixed(4)}`
            }));
          }
        }
        if (line.type === "error") {
          setChatMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "system",
              content: `Error: ${line.payload?.message || "Unknown error"}`
            }
          ]);
        }
      });
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "system",
          content: `Error: ${(err as Error).message}`
        }
      ]);
    }
  };

  const approveAction = async (actionId: string, approve: boolean) => {
    try {
      if (approve) {
        await apiFetch(`/api/approvals/${encodeURIComponent(actionId)}/approve`, {
          method: "POST",
          body: JSON.stringify({ approver: "studio" })
        });
      } else {
        await apiFetch(`/api/approvals/${encodeURIComponent(actionId)}/deny`, {
          method: "POST",
          body: JSON.stringify({ approver: "studio", notes: "Denied from Studio" })
        });
      }
      setToast(approve ? "Approved." : "Denied.");
    } catch (err) {
      setToast(`Approval failed: ${(err as Error).message}`);
    }
  };

  const toggleLiveProviders = async () => {
    if (!providers) return;
    const next = !providers.live_provider_calls;
    try {
      const data = await apiFetch<ProviderRoleResponse>(`/api/providers/live`, {
        method: "PATCH",
        body: JSON.stringify({ live_provider_calls: next })
      });
      setProviders(data);
      setToast(next ? "Live providers enabled." : "Live providers disabled.");
    } catch (err) {
      setToast(`Toggle failed: ${(err as Error).message}`);
    }
  };

  const updateRoleProvider = async (role: string, provider: string) => {
    try {
      const data = await apiFetch<ProviderRoleResponse>(`/api/providers/${role}`, {
        method: "PATCH",
        body: JSON.stringify({ provider })
      });
      setProviders(data);
      setToast(`Role ${role} set to ${provider}.`);
    } catch (err) {
      setToast(`Update failed: ${(err as Error).message}`);
    }
  };

  return (
    <div className="min-h-screen">
      <div className="relative z-10 grid min-h-screen grid-rows-[1fr_auto]">
        <main className="grid flex-1 grid-cols-1 gap-4 px-4 pb-6 pt-6 lg:grid-cols-[240px_1fr_320px]">
          <aside className="panel flex h-fit flex-col gap-3 p-4 lg:h-full">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-inkMuted">
                  Archon Studio
                </p>
                <h1 className="text-xl font-semibold">Control Plane</h1>
              </div>
              <button className="ghost-button" onClick={handleAddWorkflow}>
                New
              </button>
            </div>
            <div className="mt-2 h-px w-full glow-line" />
            <nav className="flex flex-col gap-2">
              {NAV_ITEMS.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setActiveView(item.id)}
                  className={`flex items-center justify-between rounded-xl border px-4 py-3 text-left text-sm font-semibold transition ${
                    activeView === item.id
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-stroke text-inkMuted hover:border-accent/40 hover:text-ink"
                  }`}
                >
                  {item.label}
                  <span className="text-xs">→</span>
                </button>
              ))}
            </nav>
            <div className="mt-auto">
              <p className="muted-text">
                Provider-agnostic agent control plane with live approvals and deployable chat
                surfaces.
              </p>
            </div>
          </aside>

          <section className="panel min-h-[70vh] p-6">
            {activeView === "builder" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">Agent Builder</h2>
                    <p className="muted-text">
                      Compose agent workflows as connected, provider-aware skills.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button className="ghost-button" onClick={() => setShowSkillPicker(true)}>
                      Add Skill
                    </button>
                    <button className="ghost-button" onClick={handleSaveWorkflow}>
                      Save Workflow
                    </button>
                  </div>
                </div>
                <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
                  <div className="panel-soft p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.3em] text-inkMuted">
                      Workflow Library
                    </p>
                    <div className="mt-3 flex flex-col gap-2">
                      {workflows.map((wf) => (
                        <button
                          key={wf.id}
                          onClick={() => setActiveWorkflowId(wf.id)}
                          className={`rounded-xl border px-3 py-2 text-left text-sm font-semibold ${
                            activeWorkflowId === wf.id
                              ? "border-accent bg-accent/10 text-accent"
                              : "border-stroke text-inkMuted hover:border-accent/40 hover:text-ink"
                          }`}
                        >
                          {wf.name}
                          <div className="text-xs font-normal text-inkMuted">
                            {wf.nodes.length} skills
                          </div>
                        </button>
                      ))}
                      {!workflows.length && (
                        <div className="rounded-xl border border-dashed border-stroke p-4 text-sm text-inkMuted">
                          No workflows yet. Click New to start.
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="panel-soft flex flex-1 flex-col gap-4 p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-lg font-semibold">
                          {activeWorkflow?.name || "Untitled"}
                        </h3>
                        <p className="muted-text">Canvas view of connected skills.</p>
                      </div>
                      <span className="chip">{activeWorkflow?.nodes.length || 0} nodes</span>
                    </div>
                    <div className="flex flex-1 flex-col gap-3 overflow-x-auto">
                      {activeWorkflow?.nodes.length ? (
                        <div className="flex items-center gap-3">
                          {activeWorkflow.nodes.map((node, index) => (
                            <div key={node.id} className="flex items-center gap-3">
                              <button
                                onClick={() => setSelectedNodeId(node.id)}
                                className={`min-w-[180px] rounded-2xl border p-4 text-left transition ${
                                  selectedNodeId === node.id
                                    ? "border-accent bg-accent/10"
                                    : "border-stroke bg-panel/80 hover:border-accent/50"
                                }`}
                              >
                                <div className="flex items-center justify-between">
                                  <h4 className="text-sm font-semibold">{node.name}</h4>
                                  <span className="text-xs text-inkMuted">{node.state}</span>
                                </div>
                                <p className="text-xs text-inkMuted">Tier: {node.cost_tier}</p>
                                <p className="text-xs text-inkMuted">
                                  Provider: {node.provider || "auto"}
                                </p>
                              </button>
                              {index < activeWorkflow.nodes.length - 1 && (
                                <div className="h-px w-12 glow-line" />
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-stroke p-12 text-center text-sm text-inkMuted">
                          Drop skills here to build an execution chain.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeView === "skills" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">Skills Registry</h2>
                    <p className="muted-text">Audit, propose, and promote skills across domains.</p>
                  </div>
                  <button className="accent-button" onClick={runSkillProposal}>
                    Propose Skill
                  </button>
                </div>
                <div className="panel-soft overflow-hidden">
                  <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 border-b border-stroke px-4 py-3 text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                    <span>Name</span>
                    <span>State</span>
                    <span>Provider</span>
                    <span>Tier</span>
                    <span>Version</span>
                    <span></span>
                  </div>
                  <div className="divide-y divide-stroke">
                    {skillsLoading && (
                      <div className="px-4 py-6 text-sm text-inkMuted">Loading skills…</div>
                    )}
                    {skillsError && (
                      <div className="px-4 py-6 text-sm text-danger">{skillsError}</div>
                    )}
                    {!skillsLoading && !skills.length && (
                      <div className="px-4 py-6 text-sm text-inkMuted">No skills registered.</div>
                    )}
                    {skills.map((skill) => (
                      <div
                        key={skill.name}
                        className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] items-center gap-3 px-4 py-3 text-sm"
                      >
                        <span>{skill.name}</span>
                        <span className="text-xs font-semibold text-inkMuted">{skill.state}</span>
                        <span className="text-xs text-inkMuted">
                          {skill.provider_preference || "auto"}
                        </span>
                        <span className="text-xs text-inkMuted">{skill.cost_tier}</span>
                        <span className="text-xs text-inkMuted">v{skill.version}</span>
                        <span>
                          {skill.state === "STAGING" ? (
                            <button
                              className="ghost-button"
                              onClick={() => runSkillPromotion(skill.name)}
                            >
                              Promote
                            </button>
                          ) : (
                            <span className="text-xs text-inkMuted">—</span>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="panel-soft p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                    Proposal Stream
                  </p>
                  <div className="mt-3 flex flex-col gap-2">
                    {skillsLog.length === 0 && (
                      <div className="text-sm text-inkMuted">No events yet.</div>
                    )}
                    {skillsLog.map((entry) => (
                      <div key={entry.id} className="rounded-xl border border-stroke p-3">
                        <div className="text-xs text-inkMuted">{entry.role}</div>
                        <div className="text-sm">{entry.content}</div>
                        {entry.meta?.type === "approval_required" && (
                          <div className="mt-2 flex gap-2">
                            <button
                              className="accent-button"
                              onClick={() => approveAction(entry.meta.request_id, true)}
                            >
                              Approve
                            </button>
                            <button
                              className="ghost-button"
                              onClick={() => approveAction(entry.meta.request_id, false)}
                            >
                              Deny
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {activeView === "providers" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">Providers</h2>
                    <p className="muted-text">Assign roles and manage provider availability.</p>
                  </div>
                  <button className="accent-button" onClick={toggleLiveProviders}>
                    {providers?.live_provider_calls ? "Disable Live" : "Enable Live"}
                  </button>
                </div>
                {providersError && <div className="text-sm text-danger">{providersError}</div>}
                <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
                  <div className="panel-soft p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                      Role Assignments
                    </p>
                    <div className="mt-4 flex flex-col gap-3">
                      {providers &&
                        Object.entries(providers.roles).map(([role, provider]) => (
                          <div
                            key={role}
                            className="flex items-center justify-between rounded-xl border border-stroke p-3"
                          >
                            <div>
                              <div className="text-sm font-semibold capitalize">{role}</div>
                              <div className="text-xs text-inkMuted">{provider}</div>
                            </div>
                            <select
                              className="rounded-lg border border-stroke bg-panel px-2 py-1 text-sm"
                              value={provider}
                              onChange={(event) => updateRoleProvider(role, event.target.value)}
                            >
                              {availableProviders.map((option) => (
                                <option key={option} value={option}>
                                  {option}
                                </option>
                              ))}
                            </select>
                          </div>
                        ))}
                    </div>
                  </div>
                  <div className="panel-soft p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                      Provider Status
                    </p>
                    <div className="mt-4 flex flex-col gap-3">
                      {providers?.providers.map((entry) => (
                        <div
                          key={entry.name}
                          className="flex flex-col gap-2 rounded-xl border border-stroke p-3"
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className="text-sm font-semibold">{entry.name}</div>
                              <div className="text-xs text-inkMuted">
                                Roles: {entry.roles.join(", ") || "unassigned"}
                              </div>
                            </div>
                            <span
                              className={`chip ${
                                entry.status === "live"
                                  ? "border-good text-good"
                                  : entry.status === "missing_key"
                                  ? "border-warn text-warn"
                                  : "border-stroke text-inkMuted"
                              }`}
                            >
                              {entry.status}
                            </span>
                          </div>
                          <div className="text-xs text-inkMuted">
                            {entry.env_key ? `Key: ${entry.env_key}` : "Key: n/a"}
                          </div>
                          <div className="text-xs text-inkMuted">
                            {entry.key_required
                              ? entry.key_present
                                ? "Key present"
                                : "Key missing"
                              : "Key optional"}
                          </div>
                          {entry.base_url && (
                            <div className="text-xs text-inkMuted">Base: {entry.base_url}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeView === "deploy" && (
              <div className="flex h-full flex-col gap-6">
                <div>
                  <h2 className="text-2xl font-semibold">Deploy</h2>
                  <p className="muted-text">
                    Package and publish workflows into branded agent endpoints.
                  </p>
                </div>
                <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
                  <div className="panel-soft p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                      New Deployment
                    </p>
                    <div className="mt-4 flex flex-col gap-3">
                      <input
                        className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                        placeholder="Name"
                        value={deploymentForm.name}
                        onChange={(event) =>
                          setDeploymentForm((prev) => ({ ...prev, name: event.target.value }))
                        }
                      />
                      <input
                        className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                        placeholder="Description"
                        value={deploymentForm.description}
                        onChange={(event) =>
                          setDeploymentForm((prev) => ({
                            ...prev,
                            description: event.target.value
                          }))
                        }
                      />
                      <input
                        className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                        placeholder="Logo URL"
                        value={deploymentForm.logoUrl}
                        onChange={(event) =>
                          setDeploymentForm((prev) => ({ ...prev, logoUrl: event.target.value }))
                        }
                      />
                      <input
                        className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                        placeholder="Accent color"
                        value={deploymentForm.accent}
                        onChange={(event) =>
                          setDeploymentForm((prev) => ({ ...prev, accent: event.target.value }))
                        }
                      />
                      <select
                        className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                        value={deploymentForm.entrySkill}
                        onChange={(event) =>
                          setDeploymentForm((prev) => ({ ...prev, entrySkill: event.target.value }))
                        }
                      >
                        <option value="">Select entry skill</option>
                        {skills.map((skill) => (
                          <option key={skill.name} value={skill.name}>
                            {skill.name}
                          </option>
                        ))}
                      </select>
                      <button className="accent-button" onClick={handleDeploySubmit}>
                        Create Deployment
                      </button>
                    </div>
                    <div className="mt-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                        Deployment Stream
                      </p>
                      <div className="mt-2 flex flex-col gap-2">
                        {deployLog.length === 0 && (
                          <div className="text-sm text-inkMuted">No events yet.</div>
                        )}
                        {deployLog.map((entry) => (
                          <div key={entry.id} className="rounded-xl border border-stroke p-3">
                            <div className="text-xs text-inkMuted">{entry.role}</div>
                            <div className="text-sm">{entry.content}</div>
                            {entry.meta?.type === "approval_required" && (
                              <div className="mt-2 flex gap-2">
                                <button
                                  className="accent-button"
                                  onClick={() => approveAction(entry.meta.request_id, true)}
                                >
                                  Approve
                                </button>
                                <button
                                  className="ghost-button"
                                  onClick={() => approveAction(entry.meta.request_id, false)}
                                >
                                  Deny
                                </button>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="panel-soft p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                      Active Deployments
                    </p>
                    <div className="mt-4 flex flex-col gap-3">
                      {deployments.length === 0 && (
                        <div className="text-sm text-inkMuted">No deployments yet.</div>
                      )}
                      {deployments.map((deployment) => (
                        <div
                          key={deployment.id}
                          className="rounded-xl border border-stroke p-3"
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className="text-sm font-semibold">{deployment.name}</div>
                              <div className="text-xs text-inkMuted">
                                {deployment.description || "No description"}
                              </div>
                            </div>
                            <span className="chip">live</span>
                          </div>
                          <div className="mt-2 text-xs text-inkMuted">{deployment.url}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeView === "chat" && (
              <div className="flex h-full flex-col gap-4">
                <div>
                  <h2 className="text-2xl font-semibold">Chat</h2>
                  <p className="muted-text">Run tasks, inspect system events, and approve actions.</p>
                </div>
                <div className="panel-soft flex flex-1 flex-col gap-3 p-4">
                  <div className="flex-1 space-y-3 overflow-y-auto">
                    {chatMessages.length === 0 && (
                      <div className="text-sm text-inkMuted">Start a test task.</div>
                    )}
                    {chatMessages.map((message) => (
                      <div
                        key={message.id}
                        className={`rounded-2xl border p-3 text-sm ${
                          message.role === "user"
                            ? "border-accent bg-accent/10"
                            : message.role === "assistant"
                            ? "border-stroke bg-panel"
                            : "border-stroke bg-panelSoft"
                        }`}
                      >
                        <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">
                          {message.role}
                        </div>
                        <div className="mt-1 whitespace-pre-wrap text-ink">{message.content}</div>
                        {message.meta?.type === "approval_required" && (
                          <div className="mt-3 flex gap-2">
                            <button
                              className="accent-button"
                              onClick={() => approveAction(message.meta.request_id, true)}
                            >
                              Approve
                            </button>
                            <button
                              className="ghost-button"
                              onClick={() => approveAction(message.meta.request_id, false)}
                            >
                              Deny
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="flex flex-col gap-2">
                    <textarea
                      className="min-h-[100px] rounded-xl border border-stroke bg-panel p-3 text-sm"
                      placeholder="Describe the goal you want the agent to accomplish."
                      value={chatInput}
                      onChange={(event) => setChatInput(event.target.value)}
                    />
                    <button className="accent-button" onClick={sendChat}>
                      Send Task
                    </button>
                  </div>
                </div>
              </div>
            )}

            {activeView === "evolution" && (
              <div className="flex h-full flex-col gap-6">
                <div>
                  <h2 className="text-2xl font-semibold">Evolution Log</h2>
                  <p className="muted-text">Audit trail across skills, workflows, and tasks.</p>
                </div>
                <div className="panel-soft p-4">
                  <div className="grid gap-3 md:grid-cols-4">
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="Filter skill"
                      value={evolutionFilter.skill}
                      onChange={(event) =>
                        setEvolutionFilter((prev) => ({ ...prev, skill: event.target.value }))
                      }
                    />
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="Filter provider"
                      value={evolutionFilter.provider}
                      onChange={(event) =>
                        setEvolutionFilter((prev) => ({ ...prev, provider: event.target.value }))
                      }
                    />
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="Filter task"
                      value={evolutionFilter.task}
                      onChange={(event) =>
                        setEvolutionFilter((prev) => ({ ...prev, task: event.target.value }))
                      }
                    />
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="YYYY-MM-DD"
                      value={evolutionFilter.date}
                      onChange={(event) =>
                        setEvolutionFilter((prev) => ({ ...prev, date: event.target.value }))
                      }
                    />
                  </div>
                </div>
                <div className="panel-soft overflow-hidden">
                  <div className="grid grid-cols-[1fr_1fr_1fr_1fr_2fr] gap-3 border-b border-stroke px-4 py-3 text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                    <span>Event</span>
                    <span>Skill</span>
                    <span>Outcome</span>
                    <span>Confidence</span>
                    <span>Details</span>
                  </div>
                  <div className="divide-y divide-stroke">
                    {evolutionLog.map((entry) => (
                      <div
                        key={entry.entry_id}
                        className="grid grid-cols-[1fr_1fr_1fr_1fr_2fr] items-center gap-3 px-4 py-3 text-sm"
                      >
                        <div>
                          <div className="font-semibold">{entry.event_type}</div>
                          <div className="text-xs text-inkMuted">
                            {formatTimestamp(entry.timestamp)}
                          </div>
                        </div>
                        <div className="text-xs text-inkMuted">
                          {entry.payload?.skill?.name || entry.payload?.skill || "—"}
                        </div>
                        <div className="text-xs text-inkMuted">
                          {entry.payload?.status || entry.payload?.outcome || "—"}
                        </div>
                        <div className="text-xs text-inkMuted">
                          {entry.payload?.confidence ?? "—"}
                        </div>
                        <div className="text-xs text-inkMuted">{entry.workflow_id}</div>
                      </div>
                    ))}
                    {evolutionLog.length === 0 && (
                      <div className="px-4 py-6 text-sm text-inkMuted">No events found.</div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>

          <aside className="panel hidden h-fit flex-col gap-4 p-4 lg:flex">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-inkMuted">
                Properties
              </p>
              <h3 className="text-lg font-semibold">Selection</h3>
            </div>
            {activeView === "builder" ? (
              selectedNode ? (
                <div className="flex flex-col gap-3">
                  <div className="rounded-xl border border-stroke p-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">Skill</div>
                    <div className="text-sm font-semibold">{selectedNode.name}</div>
                  </div>
                  <div className="rounded-xl border border-stroke p-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">
                      Provider Override
                    </div>
                    <select
                      className="mt-2 w-full rounded-lg border border-stroke bg-panel px-2 py-1 text-sm"
                      value={selectedNode.provider || "auto"}
                      onChange={(event) =>
                        updateNode(selectedNode.id, {
                          provider: event.target.value === "auto" ? null : event.target.value
                        })
                      }
                    >
                      <option value="auto">auto</option>
                      {availableProviders.map((provider) => (
                        <option key={provider} value={provider}>
                          {provider}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="rounded-xl border border-stroke p-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">Config</div>
                    {Object.entries(selectedNode.config).map(([key, value]) => (
                      <div key={key} className="mt-2 flex items-center justify-between text-xs">
                        <span className="text-inkMuted">{key}</span>
                        <input
                          className="w-24 rounded-md border border-stroke bg-panel px-2 py-1 text-xs"
                          value={value}
                          onChange={(event) =>
                            updateNode(selectedNode.id, {
                              config: { ...selectedNode.config, [key]: event.target.value }
                            })
                          }
                        />
                      </div>
                    ))}
                  </div>
                  <button className="ghost-button" onClick={() => handleRemoveNode(selectedNode.id)}>
                    Remove Node
                  </button>
                </div>
              ) : (
                <div className="text-sm text-inkMuted">Select a node to edit its settings.</div>
              )
            ) : (
              <div className="text-sm text-inkMuted">
                Choose a section to inspect its configuration and metadata.
              </div>
            )}
          </aside>
        </main>

        <footer className="sticky bottom-0 flex w-full flex-wrap items-center justify-between gap-3 border-t border-stroke bg-panel/80 px-6 py-3 text-xs text-inkMuted backdrop-blur">
          <div className="flex flex-wrap items-center gap-4">
            <span>Provider: {statusBar.provider}</span>
            <span>Mode: {statusBar.mode}</span>
            <span>Tokens: {statusBar.tokens}</span>
            <span>Cost: {statusBar.cost}</span>
          </div>
          <div className="text-xs">
            Live providers: {providers?.live_provider_calls ? "on" : "off"}
          </div>
        </footer>
      </div>

      {showSkillPicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="panel w-full max-w-xl p-6">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">Skill Registry</h3>
              <button className="ghost-button" onClick={() => setShowSkillPicker(false)}>
                Close
              </button>
            </div>
            <div className="mt-4 grid max-h-[360px] gap-3 overflow-y-auto">
              {skills.map((skill) => (
                <button
                  key={skill.name}
                  onClick={() => handleAddSkillNode(skill)}
                  className="rounded-xl border border-stroke p-3 text-left transition hover:border-accent"
                >
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold">{skill.name}</div>
                    <span className="text-xs text-inkMuted">{skill.state}</span>
                  </div>
                  <div className="text-xs text-inkMuted">
                    Provider: {skill.provider_preference || "auto"} · Tier: {skill.cost_tier}
                  </div>
                </button>
              ))}
              {!skills.length && (
                <div className="text-sm text-inkMuted">No skills available.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-full border border-stroke bg-panel px-4 py-2 text-sm text-ink">
          {toast}
        </div>
      )}
    </div>
  );
}
