import { Dispatch, SetStateAction, useEffect, useMemo, useState } from "react";
import { API_BASE, apiFetch, streamJsonLines } from "./lib/api";

const NAV_SECTIONS = [
  {
    title: "Build",
    items: [
      { id: "overview", label: "Overview" },
      { id: "builder", label: "Builder" },
      { id: "skills", label: "Capabilities" }
    ]
  },
  {
    title: "Operate",
    items: [
      { id: "providers", label: "Connections" },
      { id: "memory", label: "Knowledge" },
      { id: "approvals", label: "Confirmations" },
      { id: "chat", label: "Live Chat" },
      { id: "webchat", label: "Website Chat" },
      { id: "sessions", label: "Chat Sessions" },
      { id: "deploy", label: "Launches" },
      { id: "observability", label: "System Health" }
    ]
  },
  {
    title: "Admin",
    items: [
      { id: "evolution", label: "Change History" },
      { id: "config", label: "Settings" }
    ]
  }
] as const;

const NAV_ITEMS = NAV_SECTIONS.flatMap((section) => section.items);

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
  status: "live" | "missing_key";
  roles: string[];
  env_key: string | null;
  key_present: boolean | null;
  key_required: boolean;
  base_url: string | null;
};

type ProviderRoleResponse = {
  roles: Record<string, string>;
  providers: ProviderEntry[];
};

type ApprovalEntry = {
  request_id: string;
  action_id: string;
  action: string;
  risk_level?: string | null;
  created_at: number;
  context: Record<string, any>;
  timeout_remaining_s?: number;
};

type StudioStatus = {
  status: string;
  version: string;
  git_sha: string;
  uptime_s: number;
  deployment_count: number;
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

type DrawerKind = "node" | "provider" | "deployment" | "session" | "approval";

type DrawerDescriptor = {
  id: string;
  title: string;
  kind: DrawerKind;
  payload: any;
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
  const [activeView, setActiveView] = useState<ViewId>("overview");
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
  const [studioStatus, setStudioStatus] = useState<StudioStatus | null>(null);

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
  const [webchatStatus, setWebchatStatus] = useState<"idle" | "loading" | "ready" | "error">(
    "idle"
  );
  const [approvals, setApprovals] = useState<ApprovalEntry[]>([]);
  const [approvalsError, setApprovalsError] = useState<string | null>(null);
  const [webchatToken, setWebchatToken] = useState<string>("");
  const [webchatSessionId, setWebchatSessionId] = useState<string>("");
  const [webchatMessages, setWebchatMessages] = useState<Message[]>([]);
  const [webchatSessions, setWebchatSessions] = useState<Array<{ id: string; token: string }>>(
    []
  );
  const [webchatError, setWebchatError] = useState<string | null>(null);
  const [drawers, setDrawers] = useState<DrawerDescriptor[]>([]);

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
    if (!selectedNode) return;
    openDrawer({
      id: `node:${selectedNode.id}`,
      title: `Node · ${selectedNode.name}`,
      kind: "node",
      payload: selectedNode
    });
  }, [selectedNode]);

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
    if (!["overview", "config", "observability"].includes(activeView)) return;
    loadStudioStatus();
  }, [activeView]);

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
    if (activeView !== "approvals") return;
    loadApprovals();
    const interval = setInterval(loadApprovals, 5000);
    return () => clearInterval(interval);
  }, [activeView]);

  useEffect(() => {
    if (activeView !== "webchat") return;
    const existing = document.getElementById("archon-webchat-script") as HTMLScriptElement | null;
    if ((window as any).archon) {
      setWebchatStatus("ready");
      return;
    }
    setWebchatStatus("loading");
    const script = existing ?? document.createElement("script");
    if (!existing) {
      script.id = "archon-webchat-script";
      script.async = true;
      script.src = `${API_BASE}/webchat/static/archon-chat.js`;
      script.dataset.host = API_BASE;
      script.dataset.theme = "dark";
      script.dataset.whiteLabel = "true";
      script.dataset.position = "right";
      document.body.appendChild(script);
    }

    const handleLoad = () => setWebchatStatus("ready");
    const handleError = () => setWebchatStatus("error");
    script.addEventListener("load", handleLoad);
    script.addEventListener("error", handleError);
    return () => {
      script.removeEventListener("load", handleLoad);
      script.removeEventListener("error", handleError);
    };
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

  const openDrawer = (drawer: DrawerDescriptor) => {
    setDrawers((prev) => {
      const index = prev.findIndex((item) => item.id === drawer.id);
      if (index >= 0) {
        const next = [...prev];
        next[index] = drawer;
        return next;
      }
      return [...prev, drawer];
    });
  };

  const closeDrawer = (drawerId: string) => {
    setDrawers((prev) => prev.filter((item) => item.id !== drawerId));
  };

  const renderDrawerContent = (drawer: DrawerDescriptor) => {
    if (drawer.kind === "node") {
      const node = drawer.payload as WorkflowNode;
      return (
        <div className="flex flex-col gap-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">Connection</span>
            <select
              className="rounded-lg border border-stroke bg-panel px-2 py-1 text-xs"
              value={node.provider || "auto"}
              onChange={(event) =>
                updateNode(node.id, {
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
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">Cost tier</span>
            <span>{node.cost_tier}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">State</span>
            <span>{node.state}</span>
          </div>
          <div className="rounded-lg border border-stroke p-2">
            <div className="text-[11px] uppercase tracking-[0.2em] text-inkMuted">Settings</div>
            {Object.entries(node.config).map(([key, value]) => (
              <div key={key} className="mt-2 flex items-center justify-between text-xs">
                <span className="text-inkMuted">{key}</span>
                <input
                  className="w-24 rounded-md border border-stroke bg-panel px-2 py-1 text-xs"
                  value={value}
                  onChange={(event) =>
                    updateNode(node.id, {
                      config: { ...node.config, [key]: event.target.value }
                    })
                  }
                />
              </div>
            ))}
          </div>
          <button className="ghost-button" onClick={() => handleRemoveNode(node.id)}>
            Remove Node
          </button>
        </div>
      );
    }
    if (drawer.kind === "provider") {
      const provider = drawer.payload as ProviderEntry;
      return (
        <div className="flex flex-col gap-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">Status</span>
            <span>{provider.status}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">Roles</span>
            <span>{provider.roles.join(", ") || "—"}</span>
          </div>
          {provider.base_url && (
            <div className="flex items-center justify-between">
              <span className="text-inkMuted">Base URL</span>
              <span>{provider.base_url}</span>
            </div>
          )}
          {provider.env_key && (
            <div className="flex items-center justify-between">
              <span className="text-inkMuted">Env key</span>
              <span>{provider.env_key}</span>
            </div>
          )}
        </div>
      );
    }
    if (drawer.kind === "deployment") {
      const deployment = drawer.payload as Deployment;
      return (
        <div className="flex flex-col gap-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">Entry capability</span>
            <span>{deployment.entry_skill}</span>
          </div>
          <div className="rounded-lg border border-stroke p-2 text-[11px] text-inkMuted">
            {deployment.description || "No description"}
          </div>
          <div className="text-[11px] text-inkMuted">{deployment.url}</div>
        </div>
      );
    }
    if (drawer.kind === "session") {
      const session = drawer.payload as { session_id: string; tenant_id?: string; tier?: string };
      return (
        <div className="flex flex-col gap-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">Chat Session</span>
            <span>{session.session_id}</span>
          </div>
          {session.tenant_id && (
            <div className="flex items-center justify-between">
              <span className="text-inkMuted">Tenant</span>
              <span>{session.tenant_id}</span>
            </div>
          )}
          {session.tier && (
            <div className="flex items-center justify-between">
              <span className="text-inkMuted">Tier</span>
              <span>{session.tier}</span>
            </div>
          )}
        </div>
      );
    }
    if (drawer.kind === "approval") {
      const approval = drawer.payload as ApprovalEntry;
      return (
        <div className="flex flex-col gap-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-inkMuted">Action</span>
            <span>{approval.action}</span>
          </div>
          <div className="text-[11px] text-inkMuted">
            {JSON.stringify(approval.context || {}, null, 0)}
          </div>
        </div>
      );
    }
    return <div className="text-xs text-inkMuted">No details.</div>;
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
            content: `Launch ready at ${line.payload?.url || ""}`,
            meta: line.payload
          });
          setToast("Launch created.");
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
                content: "Confirmation needed",
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
      setToast(approve ? "Confirmed." : "Declined.");
      if (activeView === "approvals") {
        loadApprovals();
      }
    } catch (err) {
      setToast(`Confirmation failed: ${(err as Error).message}`);
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

  const loadStudioStatus = async () => {
    try {
      const data = await apiFetch<StudioStatus>("/api/status");
      setStudioStatus(data);
    } catch (err) {
      setToast(`Status fetch failed: ${(err as Error).message}`);
    }
  };

  const loadApprovals = async () => {
    setApprovalsError(null);
    try {
      const data = await apiFetch<{ approvals: ApprovalEntry[] }>("/api/approvals");
      setApprovals(data.approvals || []);
    } catch (err) {
      setApprovalsError((err as Error).message);
      setApprovals([]);
    }
  };

  const createWebchatSession = async () => {
    setWebchatError(null);
    try {
      const data = await apiFetch<{
        token: string;
        session: { session_id: string };
        identity: { session_id: string };
      }>("/webchat/token", { method: "POST", body: JSON.stringify({}) });
      const sessionId = data.session?.session_id || data.identity?.session_id || "";
      if (!sessionId) {
        throw new Error("Missing chat session id from website chat token response.");
      }
      setWebchatToken(data.token);
      setWebchatSessionId(sessionId);
      setWebchatSessions((prev) =>
        prev.some((entry) => entry.id === sessionId)
          ? prev
          : [{ id: sessionId, token: data.token }, ...prev]
      );
      openDrawer({
        id: `session:${sessionId}`,
        title: `Session · ${sessionId}`,
        kind: "session",
        payload: { session_id: sessionId, token: data.token }
      });
    } catch (err) {
      setWebchatError((err as Error).message);
    }
  };

  const loadWebchatSession = async (sessionId: string, token: string) => {
    setWebchatError(null);
    if (!sessionId || !token) {
      setWebchatError("Chat session id and token are required.");
      return;
    }
    try {
      const response = await fetch(
        `${API_BASE}/webchat/session/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(
          token
        )}`
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const data = (await response.json()) as {
        session: { session_id: string; tenant_id: string; tier: string };
        messages: { id: string; role: string; content: string }[];
      };
      const messages = (data.messages || []).map((msg) => ({
        id: msg.id,
        role: msg.role === "assistant" ? "assistant" : msg.role === "user" ? "user" : "system",
        content: msg.content
      }));
      setWebchatMessages(messages);
      openDrawer({
        id: `session:${sessionId}`,
        title: `Session · ${sessionId}`,
        kind: "session",
        payload: { ...data.session, token }
      });
    } catch (err) {
      setWebchatError((err as Error).message);
    }
  };

  const clearWebchatSession = async (sessionId: string, token: string) => {
    setWebchatError(null);
    if (!sessionId || !token) {
      setWebchatError("Chat session id and token are required.");
      return;
    }
    try {
      const response = await fetch(
        `${API_BASE}/webchat/session/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(
          token
        )}`,
        { method: "DELETE" }
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setWebchatMessages([]);
      setToast("Session cleared.");
    } catch (err) {
      setWebchatError((err as Error).message);
    }
  };

  return (
    <div className="studio-shell min-h-screen">
      <div className="relative z-10 grid min-h-screen grid-rows-[1fr_auto]">
        <main className="grid flex-1 grid-cols-1 gap-3 px-3 pb-4 pt-4 lg:grid-cols-[220px_1fr_300px]">
          <aside className="panel flex h-fit flex-col gap-3 p-3 lg:h-full">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="status-dot" />
                  <p className="text-xs font-semibold uppercase tracking-[0.3em] text-inkMuted">
                    Archon Studio
                  </p>
                </div>
                <h1 className="text-xl font-semibold">Control Plane</h1>
              </div>
              <button className="ghost-button" onClick={handleAddWorkflow}>
                New
              </button>
            </div>
            <div className="mt-2 h-px w-full glow-line" />
            <nav className="flex flex-col gap-4">
              {NAV_SECTIONS.map((section) => (
                <div key={section.title} className="flex flex-col gap-2">
                  <p className="nav-label">{section.title}</p>
                  {section.items.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => setActiveView(item.id)}
                      className={`nav-button ${
                        activeView === item.id ? "nav-button-active" : "nav-button-idle"
                      }`}
                    >
                      {item.label}
                      <span className="text-xs">→</span>
                    </button>
                  ))}
                </div>
              ))}
            </nav>
            <div className="mt-auto">
              <p className="muted-text">
                Connection-agnostic agent control plane with live confirmations and launchable chat
                surfaces.
              </p>
            </div>
          </aside>

          <section className="panel min-h-[70vh] p-5">
            {activeView === "overview" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">Overview</h2>
                    <p className="muted-text">Live snapshot of the control plane.</p>
                  </div>
                  <button className="ghost-button" onClick={loadStudioStatus}>
                    Refresh
                  </button>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">Runtime</p>
                    <div className="mt-2 text-lg font-semibold">
                      {studioStatus?.status ?? "unknown"}
                    </div>
                    <div className="text-xs text-inkMuted">
                      {studioStatus?.version ?? "—"}
                    </div>
                  </div>
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">Launches</p>
                    <div className="mt-2 text-lg font-semibold">
                      {studioStatus?.deployment_count ?? deployments.length}
                    </div>
                    <div className="text-xs text-inkMuted">active endpoints</div>
                  </div>
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">Connections</p>
                    <div className="mt-2 text-lg font-semibold">
                      {providers?.providers.length ?? 0}
                    </div>
                    <div className="text-xs text-inkMuted">
                      {providers
                        ? providers.providers.some((entry) => entry.status === "missing_key")
                          ? "needs keys"
                          : "ready"
                        : "—"}
                    </div>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">Capabilities</p>
                    <div className="mt-2 text-lg font-semibold">{skills.length}</div>
                    <div className="text-xs text-inkMuted">registered capabilities</div>
                  </div>
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">Confirmations</p>
                    <div className="mt-2 text-lg font-semibold">{approvals.length}</div>
                    <div className="text-xs text-inkMuted">pending actions</div>
                  </div>
                </div>
              </div>
            )}

            {activeView === "builder" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">Agent Builder</h2>
                    <p className="muted-text">
                      Compose agent workflows as connected, connection-aware capabilities.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button className="ghost-button" onClick={() => setShowSkillPicker(true)}>
                      Add Capability
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
                            {wf.nodes.length} capabilities
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
                        <p className="muted-text">Canvas view of connected capabilities.</p>
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
                                  Connection: {node.provider || "auto"}
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
                          Drop capabilities here to build an execution chain.
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
                    <h2 className="text-2xl font-semibold">Capabilities Library</h2>
                    <p className="muted-text">
                      Audit, propose, and promote capabilities across domains.
                    </p>
                  </div>
                  <button className="accent-button" onClick={runSkillProposal}>
                    Propose Capability
                  </button>
                </div>
                <div className="panel-soft overflow-hidden">
                  <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 border-b border-stroke px-4 py-3 text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                    <span>Name</span>
                    <span>State</span>
                    <span>Connection</span>
                    <span>Tier</span>
                    <span>Version</span>
                    <span></span>
                  </div>
                  <div className="divide-y divide-stroke">
                    {skillsLoading && (
                      <div className="px-4 py-6 text-sm text-inkMuted">
                        Loading capabilities…
                      </div>
                    )}
                    {skillsError && (
                      <div className="px-4 py-6 text-sm text-danger">{skillsError}</div>
                    )}
                    {!skillsLoading && !skills.length && (
                      <div className="px-4 py-6 text-sm text-inkMuted">
                        No capabilities registered.
                      </div>
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
                              Confirm
                            </button>
                            <button
                              className="ghost-button"
                              onClick={() => approveAction(entry.meta.request_id, false)}
                            >
                              Decline
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
                    <h2 className="text-2xl font-semibold">Connections</h2>
                    <p className="muted-text">
                      Assign roles and manage connection availability.
                    </p>
                  </div>
                  <button className="ghost-button" onClick={loadProviders}>
                    Refresh
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
                      Connection Status
                    </p>
                    <div className="mt-4 flex flex-col gap-3">
                      {providers?.providers.map((entry) => (
                        <div
                          key={entry.name}
                          role="button"
                          tabIndex={0}
                          onClick={() =>
                            openDrawer({
                              id: `provider:${entry.name}`,
                              title: `Connection · ${entry.name}`,
                              kind: "provider",
                              payload: entry
                            })
                          }
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              openDrawer({
                                id: `provider:${entry.name}`,
                                title: `Connection · ${entry.name}`,
                                kind: "provider",
                                payload: entry
                              });
                            }
                          }}
                          className="flex cursor-pointer flex-col gap-2 rounded-xl border border-stroke p-3 transition hover:border-accent/40"
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

            {activeView === "memory" && (
              <div className="flex h-full flex-col gap-6">
                <div>
                  <h2 className="text-2xl font-semibold">Knowledge</h2>
                  <p className="muted-text">Search, retention, and tenant knowledge state.</p>
                </div>
                <div className="panel-soft p-4">
                  <div className="text-sm text-inkMuted">
                    Knowledge search UI is coming next. Use the API to query knowledge while we
                    wire the surface here.
                  </div>
                </div>
              </div>
            )}

            {activeView === "approvals" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">Confirmations</h2>
                    <p className="muted-text">Review and resolve guarded actions.</p>
                  </div>
                  <button className="ghost-button" onClick={loadApprovals}>
                    Refresh
                  </button>
                </div>
                <div className="panel-soft p-4">
                  {approvalsError && (
                    <div className="text-sm text-warn">Error: {approvalsError}</div>
                  )}
                  {approvals.length === 0 && (
                    <div className="text-sm text-inkMuted">No approvals pending.</div>
                  )}
                  <div className="mt-3 flex flex-col gap-3">
                    {approvals.map((approval) => (
                      <div
                        key={approval.request_id}
                        role="button"
                        tabIndex={0}
                        onClick={() =>
                            openDrawer({
                              id: `approval:${approval.request_id}`,
                              title: `Confirmation · ${approval.action}`,
                              kind: "approval",
                              payload: approval
                            })
                        }
                        className="flex flex-col gap-2 rounded-xl border border-stroke p-3 transition hover:border-accent/40"
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="text-sm font-semibold">{approval.action}</div>
                            <div className="text-xs text-inkMuted">{approval.request_id}</div>
                          </div>
                          <span className="chip">{approval.risk_level || "unknown"}</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="accent-button"
                            onClick={(event) => {
                              event.stopPropagation();
                              approveAction(approval.request_id, true);
                            }}
                          >
                            Confirm
                          </button>
                          <button
                            className="ghost-button"
                            onClick={(event) => {
                              event.stopPropagation();
                              approveAction(approval.request_id, false);
                            }}
                          >
                            Decline
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {activeView === "sessions" && (
              <div className="flex h-full flex-col gap-6">
                <div>
                  <h2 className="text-2xl font-semibold">Chat Sessions</h2>
                  <p className="muted-text">Create or inspect website chat sessions.</p>
                </div>
                <div className="panel-soft p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <button className="accent-button" onClick={createWebchatSession}>
                      Create Chat Session
                    </button>
                    <button
                      className="ghost-button"
                      onClick={() => loadWebchatSession(webchatSessionId, webchatToken)}
                    >
                      Load Chat Session
                    </button>
                    <button
                      className="ghost-button"
                      onClick={() => clearWebchatSession(webchatSessionId, webchatToken)}
                    >
                      Clear Messages
                    </button>
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="Chat session id"
                      value={webchatSessionId}
                      onChange={(event) => setWebchatSessionId(event.target.value)}
                    />
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="Chat session token"
                      value={webchatToken}
                      onChange={(event) => setWebchatToken(event.target.value)}
                    />
                  </div>
                  {webchatError && <div className="mt-3 text-sm text-warn">{webchatError}</div>}
                  <div className="mt-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-inkMuted">
                      Recent Chat Sessions
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {webchatSessions.length === 0 && (
                        <div className="text-sm text-inkMuted">No chat sessions yet.</div>
                      )}
                      {webchatSessions.map((entry) => (
                        <button
                          key={entry.id}
                          className="chip"
                          onClick={() => {
                            setWebchatSessionId(entry.id);
                            setWebchatToken(entry.token);
                            loadWebchatSession(entry.id, entry.token);
                          }}
                        >
                          {entry.id}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="mt-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-inkMuted">
                      Messages
                    </p>
                    <div className="mt-2 flex max-h-[300px] flex-col gap-2 overflow-y-auto">
                      {webchatMessages.length === 0 && (
                        <div className="text-sm text-inkMuted">No messages loaded.</div>
                      )}
                      {webchatMessages.map((message) => (
                        <div key={message.id} className="rounded-lg border border-stroke p-2">
                          <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">
                            {message.role}
                          </div>
                          <div className="text-sm">{message.content}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeView === "observability" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">System Health</h2>
                    <p className="muted-text">Costs, latency, and runtime health.</p>
                  </div>
                  <button className="ghost-button" onClick={loadStudioStatus}>
                    Refresh
                  </button>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">Uptime</p>
                    <div className="mt-2 text-lg font-semibold">
                      {studioStatus ? `${studioStatus.uptime_s.toFixed(0)}s` : "—"}
                    </div>
                  </div>
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">Version</p>
                    <div className="mt-2 text-lg font-semibold">{studioStatus?.version ?? "—"}</div>
                    <div className="text-xs text-inkMuted">{studioStatus?.git_sha ?? "—"}</div>
                  </div>
                  <div className="panel-soft p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-inkMuted">
                      Connection Health
                    </p>
                    <div className="mt-2 text-lg font-semibold">
                      {providers
                        ? providers.providers.some((entry) => entry.status === "missing_key")
                          ? "needs keys"
                          : "ready"
                        : "—"}
                    </div>
                  </div>
                </div>
                <div className="panel-soft p-4">
                  <div className="text-sm text-inkMuted">
                    Metrics dashboards can be linked here (Grafana, OTEL, traces).
                  </div>
                </div>
              </div>
            )}

            {activeView === "config" && (
              <div className="flex h-full flex-col gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold">Settings</h2>
                    <p className="muted-text">Runtime settings snapshot.</p>
                  </div>
                  <button className="ghost-button" onClick={loadStudioStatus}>
                    Refresh
                  </button>
                </div>
                <div className="panel-soft p-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-stroke p-3">
                      <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">
                        Version
                      </div>
                      <div className="text-sm font-semibold">{studioStatus?.version ?? "—"}</div>
                    </div>
                    <div className="rounded-xl border border-stroke p-3">
                      <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">Git SHA</div>
                      <div className="text-sm font-semibold">{studioStatus?.git_sha ?? "—"}</div>
                    </div>
                    <div className="rounded-xl border border-stroke p-3">
                      <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">
                        Connection Health
                      </div>
                      <div className="text-sm font-semibold">
                        {providers
                          ? providers.providers.some((entry) => entry.status === "missing_key")
                            ? "needs keys"
                            : "ready"
                          : "—"}
                      </div>
                    </div>
                    <div className="rounded-xl border border-stroke p-3">
                      <div className="text-xs uppercase tracking-[0.2em] text-inkMuted">
                        Launches
                      </div>
                      <div className="text-sm font-semibold">
                        {studioStatus?.deployment_count ?? deployments.length}
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 text-sm text-inkMuted">
                    Settings file edits happen in `config.archon.yaml` on the server. Reload the
                    API to apply changes.
                  </div>
                </div>
              </div>
            )}

            {activeView === "deploy" && (
              <div className="flex h-full flex-col gap-6">
                <div>
                  <h2 className="text-2xl font-semibold">Launches</h2>
                  <p className="muted-text">
                    Package and publish workflows into branded agent endpoints.
                  </p>
                </div>
                <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
                  <div className="panel-soft p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                      New Launch
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
                        <option value="">Select entry capability</option>
                        {skills.map((skill) => (
                          <option key={skill.name} value={skill.name}>
                            {skill.name}
                          </option>
                        ))}
                      </select>
                      <button className="accent-button" onClick={handleDeploySubmit}>
                        Create Launch
                      </button>
                    </div>
                    <div className="mt-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.25em] text-inkMuted">
                        Launch Stream
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
                                  Confirm
                                </button>
                                <button
                                  className="ghost-button"
                                  onClick={() => approveAction(entry.meta.request_id, false)}
                                >
                                  Decline
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
                      Active Launches
                    </p>
                    <div className="mt-4 flex flex-col gap-3">
                      {deployments.length === 0 && (
                        <div className="text-sm text-inkMuted">No launches yet.</div>
                      )}
                      {deployments.map((deployment) => (
                        <div
                          key={deployment.id}
                          role="button"
                          tabIndex={0}
                          onClick={() =>
                            openDrawer({
                              id: `deployment:${deployment.id}`,
                              title: `Launch · ${deployment.name}`,
                              kind: "deployment",
                              payload: deployment
                            })
                          }
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              openDrawer({
                                id: `deployment:${deployment.id}`,
                                title: `Launch · ${deployment.name}`,
                                kind: "deployment",
                                payload: deployment
                              });
                            }
                          }}
                          className="cursor-pointer rounded-xl border border-stroke p-3 transition hover:border-accent/40"
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
                  <h2 className="text-2xl font-semibold">Live Chat</h2>
                  <p className="muted-text">
                    Run tasks, inspect system events, and confirm actions.
                  </p>
                </div>
                <div className="panel-soft flex flex-1 flex-col gap-3 p-4">
                  <div className="flex-1 space-y-3 overflow-y-auto">
                    {chatMessages.length === 0 && (
                      <div className="text-sm text-inkMuted">Start a test task.</div>
                    )}
                    {chatMessages.map((message) => (
                      <div
                        key={message.id}
                        className={`chat-message rounded-2xl border p-3 text-sm ${
                          message.role === "user"
                            ? "chat-message-user"
                            : message.role === "assistant"
                            ? "chat-message-assistant"
                            : "chat-message-system"
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
                              Confirm
                            </button>
                            <button
                              className="ghost-button"
                              onClick={() => approveAction(message.meta.request_id, false)}
                            >
                              Decline
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

            {activeView === "webchat" && (
              <div className="flex h-full flex-col gap-6">
                <div>
                  <h2 className="text-2xl font-semibold">Website Chat</h2>
                  <p className="muted-text">
                    Embedded widget with session storage, confirmations, and streaming tokens.
                  </p>
                </div>
                <div className="panel-soft flex flex-col gap-4 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.2em] text-inkMuted">
                        Widget Status
                      </div>
                      <div className="text-sm font-semibold">
                        {webchatStatus === "ready"
                          ? "Ready"
                          : webchatStatus === "loading"
                          ? "Loading"
                          : webchatStatus === "error"
                          ? "Failed to load"
                          : "Idle"}
                      </div>
                    </div>
                    <span className="chip">{webchatStatus}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      className="accent-button"
                      onClick={() => (window as any).archon?.open?.()}
                      disabled={webchatStatus !== "ready"}
                    >
                      Open Website Chat Widget
                    </button>
                    <button
                      className="ghost-button"
                      onClick={() => (window as any).archon?.close?.()}
                    >
                      Close Widget
                    </button>
                  </div>
                  <div className="rounded-xl border border-stroke p-3 text-xs text-inkMuted">
                    API base: {API_BASE}
                  </div>
                  <div className="rounded-xl border border-stroke p-3 text-xs text-inkMuted">
                    This widget is served from `/webchat/static/archon-chat.js` and uses the
                    `/webchat` API for sessions.
                  </div>
                </div>
              </div>
            )}

            {activeView === "evolution" && (
              <div className="flex h-full flex-col gap-6">
                <div>
                  <h2 className="text-2xl font-semibold">Change History</h2>
                  <p className="muted-text">Audit trail across capabilities, workflows, and tasks.</p>
                </div>
                <div className="panel-soft p-4">
                  <div className="grid gap-3 md:grid-cols-4">
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="Filter capability"
                      value={evolutionFilter.skill}
                      onChange={(event) =>
                        setEvolutionFilter((prev) => ({ ...prev, skill: event.target.value }))
                      }
                    />
                    <input
                      className="rounded-lg border border-stroke bg-panel px-3 py-2 text-sm"
                      placeholder="Filter connection"
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
                    <span>Capability</span>
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

          <aside className="panel hidden h-fit flex-col gap-3 p-3 lg:flex">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-inkMuted">
                  Drawers
                </p>
                <h3 className="text-lg font-semibold">Details</h3>
              </div>
              {drawers.length > 0 && (
                <button className="ghost-button" onClick={() => setDrawers([])}>
                  Clear
                </button>
              )}
            </div>
            {drawers.length === 0 ? (
              <div className="text-sm text-inkMuted">
                Open items to inspect details. Drawers can stack.
              </div>
            ) : (
              <div className="flex max-h-[calc(100vh-220px)] flex-col gap-3 overflow-y-auto pr-1">
                {drawers.map((drawer) => (
                  <div key={drawer.id} className="panel-soft p-3">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold uppercase tracking-[0.2em] text-inkMuted">
                        {drawer.title}
                      </div>
                      <button className="ghost-button" onClick={() => closeDrawer(drawer.id)}>
                        Close
                      </button>
                    </div>
                    <div className="mt-2">{renderDrawerContent(drawer)}</div>
                  </div>
                ))}
              </div>
            )}
          </aside>
        </main>

        <footer className="studio-footer sticky bottom-0 flex w-full flex-wrap items-center justify-between gap-3 border-t border-stroke px-6 py-3 text-xs text-inkMuted backdrop-blur">
          <div className="flex flex-wrap items-center gap-4">
            <span>Connection: {statusBar.provider}</span>
            <span>Mode: {statusBar.mode}</span>
            <span>Tokens: {statusBar.tokens}</span>
            <span>Cost: {statusBar.cost}</span>
          </div>
          <div className="text-xs">
            Connection health:{" "}
            {providers
              ? providers.providers.some((entry) => entry.status === "missing_key")
                ? "needs keys"
                : "ready"
              : "—"}
          </div>
        </footer>
      </div>

      {showSkillPicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="panel w-full max-w-xl p-6">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">Capability Library</h3>
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
                    Connection: {skill.provider_preference || "auto"} · Tier: {skill.cost_tier}
                  </div>
                </button>
              ))}
              {!skills.length && (
                <div className="text-sm text-inkMuted">No capabilities available.</div>
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
