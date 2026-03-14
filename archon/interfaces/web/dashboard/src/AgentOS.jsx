(() => {
  const { useEffect, useMemo, useRef, useState } = React;

  const PALETTE = {
    bg: "#0b0c10",
    panel: "#11141b",
    panelSoft: "#171b26",
    panelBright: "#1c2230",
    border: "#2a3142",
    text: "#f8fafc",
    muted: "#97a3b6",
    faint: "#5d6677",
    accent: "#f97316",
    accentSoft: "#fb923c",
    teal: "#14b8a6",
    green: "#22c55e",
    blue: "#60a5fa",
    pink: "#f472b6",
    red: "#f87171",
  };

  const DEPARTMENTS = [
    {
      id: "cxo",
      title: "CXO Command",
      summary: "North-star outcomes, cross-functional OKRs, and board-ready signals.",
      outcomes: ["Investor update", "Strategic initiatives", "Risk posture", "Forecast narrative"],
      tone: "accent",
    },
    {
      id: "growth",
      title: "Growth & Revenue",
      summary: "Pipeline motion, conversion lifts, and retention plays that run on schedule.",
      outcomes: ["Weekly pipeline", "Outbound sequences", "Partner expansion", "Churn rescues"],
      tone: "blue",
    },
    {
      id: "ops",
      title: "Operations",
      summary: "Process automation, vendor control, and operational playbooks.",
      outcomes: ["Daily ops brief", "Spend governance", "SLA monitoring", "Incident routing"],
      tone: "teal",
    },
    {
      id: "product",
      title: "Product & CX",
      summary: "Voice-of-customer insights, roadmap synthesis, and escalations.",
      outcomes: ["Top bugs", "Feedback themes", "Roadmap risks", "Launch readiness"],
      tone: "pink",
    },
  ];

  const AGENT_PODS = [
    {
      id: "cxo-pod",
      name: "Executive Pod",
      lead: "Chief of Staff Agent",
      members: ["Finance Analyst", "Strategy Analyst", "Risk Sentinel", "Ops Liaison"],
    },
    {
      id: "growth-pod",
      name: "Revenue Pod",
      lead: "Growth Orchestrator",
      members: ["Prospector", "ICP Analyst", "Outreach Director", "Nurture Manager"],
    },
    {
      id: "ops-pod",
      name: "Ops Pod",
      lead: "Ops Governor",
      members: ["Process Automator", "Vendor Watch", "Compliance Sentinel", "Task Router"],
    },
    {
      id: "cx-pod",
      name: "Customer Pod",
      lead: "Customer Strategist",
      members: ["Support Synth", "Churn Defense", "Voice Logger", "Success Planner"],
    },
  ];

  const SWARM_AGENTS = [
    { id: "ProspectorAgent", role: "Prospector", icon: "search" },
    { id: "ICPAgent", role: "ICP Analyst", icon: "target" },
    { id: "OutreachAgent", role: "Outreach", icon: "mail" },
    { id: "NurtureAgent", role: "Nurture", icon: "repeat" },
    { id: "RevenueIntelAgent", role: "Revenue Intel", icon: "chart" },
    { id: "PartnerAgent", role: "Partner", icon: "handshake" },
    { id: "ChurnDefenseAgent", role: "Churn Defense", icon: "shield" },
  ];

  const MISSION_TEMPLATES = [
    {
      id: "template-quarterly",
      name: "Quarterly CXO Pack",
      summary: "Board-ready narrative, KPIs, risks, and next-quarter bets.",
      tags: ["C-Suite", "Strategy", "Board"],
    },
    {
      id: "template-growth",
      name: "Growth Sprint",
      summary: "ICP refresh, outbound sequences, nurture flows, and pipeline health.",
      tags: ["Growth", "Revenue", "Lifecycle"],
    },
    {
      id: "template-ops",
      name: "Ops Automation",
      summary: "Vendor checks, SLA routing, automation map, and escalation coverage.",
      tags: ["Operations", "Compliance"],
    },
    {
      id: "template-cx",
      name: "Customer Pulse",
      summary: "VOC synthesis, churn watchlist, and product insights for leadership.",
      tags: ["Customer", "Product"],
    },
  ];

  const SIGNAL_FALLBACK = [
    {
      id: "signal-1",
      time: "09:18",
      title: "Growth Pod drafted 3 outreach sequences",
      detail: "Pending approval for high-touch accounts.",
      tone: "blue",
    },
    {
      id: "signal-2",
      time: "09:15",
      title: "Ops Pod flagged spend variance",
      detail: "Vendor spend +12% vs. last week.",
      tone: "accent",
    },
    {
      id: "signal-3",
      time: "09:11",
      title: "CX Pod clustered 42 feedback items",
      detail: "Top themes: onboarding friction, SLA clarity.",
      tone: "teal",
    },
  ];

  function resolveApiBase() {
    try {
      const stored = String(localStorage.getItem("archon.api_base") || "").trim();
      if (typeof window !== "undefined" && window.__TAURI__) {
        return (stored || "http://127.0.0.1:8000").replace(/\/$/, "");
      }
      if (window.location.protocol === "http:" || window.location.protocol === "https:") {
        return window.location.origin.replace(/\/$/, "");
      }
      if (stored) {
        return stored.replace(/\/$/, "");
      }
    } catch (_error) {}
    return "http://127.0.0.1:8000";
  }

  function resolveWsBase(apiBase) {
    if (apiBase.startsWith("ws://") || apiBase.startsWith("wss://")) {
      return apiBase;
    }
    if (apiBase.startsWith("https://")) {
      return `wss://${apiBase.slice("https://".length)}`;
    }
    if (apiBase.startsWith("http://")) {
      return `ws://${apiBase.slice("http://".length)}`;
    }
    return apiBase;
  }

  function buildHeaders(token, json = false) {
    const headers = { accept: "application/json" };
    if (token) {
      headers.authorization = `Bearer ${token}`;
    }
    if (json) {
      headers["content-type"] = "application/json";
    }
    return headers;
  }

  function formatClock(value) {
    const date = value instanceof Date ? value : new Date(value || Date.now());
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function clipText(value, max = 120) {
    const text = String(value || "").trim();
    if (text.length <= max) {
      return text;
    }
    return `${text.slice(0, max - 1)}…`;
  }

  function formatCost(value) {
    const number = Number(value || 0);
    if (Number.isNaN(number)) {
      return "$0.00";
    }
    return `$${number.toFixed(2)}`;
  }

  function connectionTone(status, isInitializing, hasSession) {
    if (isInitializing) {
      return "boot";
    }
    if (status === "connected") {
      return "live";
    }
    if (status === "connecting") {
      return "pulse";
    }
    if (!hasSession) {
      return "idle";
    }
    return "alert";
  }

  function connectionLabel(status, isInitializing, hasSession) {
    if (isInitializing) {
      return "Booting";
    }
    if (status === "connected") {
      return "Live";
    }
    if (status === "connecting") {
      return "Linking";
    }
    if (!hasSession) {
      return "Offline";
    }
    return "Signal Lost";
  }

  function approvalAgentName(item) {
    const direct = String(item?.agent || item?.agent_name || item?.actor || "").trim();
    if (direct) {
      return direct;
    }
    return String(item?.metadata?.agent || item?.metadata?.agent_name || "").trim();
  }

  function approvalTitle(item) {
    const question = String(item?.approval_question || item?.question || "").trim();
    if (question) {
      return question;
    }
    const action = String(item?.action_type || item?.action || "").trim();
    if (action) {
      return `Approve ${action.replace(/_/g, " ")}`;
    }
    return "Approval required";
  }

  function approvalPreview(item) {
    const preview = String(item?.preview || item?.summary || item?.message || "").trim();
    if (preview) {
      return preview;
    }
    const context = item?.context;
    if (context && typeof context === "object") {
      return clipText(JSON.stringify(context), 140);
    }
    const payload = item?.payload || item?.data || {};
    if (payload && typeof payload === "object") {
      return clipText(JSON.stringify(payload), 140);
    }
    return "Review details before continuing this action.";
  }

  function historyEventMessage(event) {
    if (!event || typeof event !== "object") {
      return "Event received.";
    }
    const type = String(event.type || "").toLowerCase();
    if (type === "approval_required") {
      return approvalTitle(event);
    }
    if (type === "approval_result" || type === "approval_resolved") {
      return `Approval resolved: ${String(event.action_type || event.action || "action")}`;
    }
    if (type === "agent_start") {
      return `${String(event.agent || event.agent_name || "Agent")} started a task.`;
    }
    if (type === "agent_end" || type === "growth_agent_completed") {
      return `${String(event.agent || event.agent_name || "Agent")} completed a task.`;
    }
    if (type === "error") {
      return String(event.error || event.message || "Agent reported an error.");
    }
    if (type === "done" && event.message && typeof event.message === "object") {
      const content = String(event.message.content || "").trim();
      if (content) {
        return content;
      }
    }
    if (event.message) {
      return String(event.message);
    }
    if (event.summary) {
      return String(event.summary);
    }
    return clipText(JSON.stringify(event), 140);
  }

  function historyEventToSignal(event, index) {
    if (!event) {
      return null;
    }
    const agent = String(event.agent || event.agent_name || "System").trim() || "System";
    const type = String(event.type || "signal").toLowerCase();
    const time = formatClock(Number(event.created_at || event.timestamp || Date.now() - index * 60000) * 1000);
    const tone =
      type.includes("error")
        ? "red"
        : type.includes("approval")
          ? "accent"
          : type.includes("cost")
            ? "pink"
            : "blue";
    return {
      id: String(event.event_id || event.id || `${type}-${index}`),
      time,
      title: `${agent} · ${clipText(type.replace(/_/g, " "), 28)}`,
      detail: historyEventMessage(event),
      tone,
    };
  }

  function workflowBlocksFromPayload(payload) {
    if (!payload || !Array.isArray(payload.steps)) {
      return [];
    }
    return payload.steps.map((step) => ({
      id: String(step.step_id || step.id || ""),
      title: String(step.config?.label || step.action || "Step"),
      subtitle: String(step.config?.subtitle || step.agent || ""),
      icon: String(step.config?.icon || "spark"),
      agent: String(step.agent || "Agent"),
    }));
  }
  const SHELL_CSS = `
    :root {
      color-scheme: dark;
    }
    .archon-os {
      min-height: 100%;
      background: ${PALETTE.bg};
      color: ${PALETTE.text};
      font-family: "Space Grotesk", "Sora", "Segoe UI", sans-serif;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .archon-os * {
      box-sizing: border-box;
    }
    .archon-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 24px;
      border-bottom: 1px solid ${PALETTE.border};
      background: linear-gradient(90deg, rgba(15, 23, 42, 0.85), rgba(12, 15, 26, 0.94));
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .archon-brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 14px;
      letter-spacing: 0.32em;
      text-transform: uppercase;
      font-weight: 600;
    }
    .archon-brand-dot {
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: ${PALETTE.accent};
      box-shadow: 0 0 18px rgba(249, 115, 22, 0.5);
    }
    .archon-topbar-meta {
      display: flex;
      align-items: center;
      gap: 12px;
      color: ${PALETTE.muted};
      font-size: 12px;
    }
    .archon-connection-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid ${PALETTE.border};
      background: rgba(17, 20, 27, 0.8);
    }
    .archon-connection-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: ${PALETTE.faint};
    }
    .archon-connection-dot.live {
      background: ${PALETTE.green};
      box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.18);
    }
    .archon-connection-dot.pulse {
      background: ${PALETTE.accent};
      box-shadow: 0 0 0 6px rgba(249, 115, 22, 0.18);
      animation: archonPulse 1.4s infinite ease-in-out;
    }
    .archon-connection-dot.alert {
      background: ${PALETTE.red};
      box-shadow: 0 0 0 6px rgba(248, 113, 113, 0.14);
    }
    .archon-connection-dot.boot {
      background: ${PALETTE.blue};
      box-shadow: 0 0 0 6px rgba(96, 165, 250, 0.18);
    }
    .archon-topbar-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .archon-button {
      border: 1px solid ${PALETTE.border};
      background: rgba(17, 20, 27, 0.8);
      color: ${PALETTE.text};
      padding: 8px 14px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
    }
    .archon-button.primary {
      background: linear-gradient(120deg, ${PALETTE.accent}, ${PALETTE.accentSoft});
      border-color: rgba(249, 115, 22, 0.5);
      color: #1f0a00;
    }
    .archon-button.ghost {
      background: transparent;
    }
    .archon-button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .archon-shell {
      display: grid;
      grid-template-columns: 260px 1fr;
      min-height: 0;
    }
    .archon-rail {
      padding: 20px 16px;
      border-right: 1px solid ${PALETTE.border};
      background: linear-gradient(180deg, rgba(17, 20, 27, 0.98), rgba(10, 12, 16, 0.98));
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .archon-rail-section {
      display: grid;
      gap: 10px;
    }
    .archon-rail-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: ${PALETTE.faint};
    }
    .archon-rail button {
      border: 1px solid transparent;
      background: transparent;
      color: ${PALETTE.muted};
      padding: 10px 12px;
      border-radius: 14px;
      text-align: left;
      cursor: pointer;
      font-size: 14px;
    }
    .archon-rail button.active {
      border-color: rgba(249, 115, 22, 0.4);
      color: ${PALETTE.text};
      background: rgba(249, 115, 22, 0.08);
    }
    .archon-rail-meta {
      padding: 12px;
      border-radius: 16px;
      background: rgba(17, 20, 27, 0.6);
      border: 1px solid rgba(42, 49, 66, 0.6);
      font-size: 12px;
      color: ${PALETTE.muted};
      display: grid;
      gap: 8px;
    }
    .archon-rail-meta strong {
      color: ${PALETTE.text};
    }
    .archon-main {
      min-height: 0;
      padding: 24px;
      overflow: auto;
      display: grid;
      gap: 20px;
      background:
        radial-gradient(circle at 20% 20%, rgba(96, 165, 250, 0.12), transparent 35%),
        radial-gradient(circle at 80% 10%, rgba(249, 115, 22, 0.14), transparent 30%),
        radial-gradient(circle at 70% 80%, rgba(20, 184, 166, 0.12), transparent 35%),
        ${PALETTE.bg};
    }
    .archon-hero {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(300px, 0.9fr);
      gap: 18px;
      padding: 22px;
      border-radius: 24px;
      border: 1px solid rgba(42, 49, 66, 0.7);
      background: linear-gradient(135deg, rgba(23, 27, 38, 0.95), rgba(16, 20, 30, 0.9));
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }
    .archon-hero h1 {
      margin: 0;
      font-size: clamp(30px, 3vw, 40px);
      line-height: 1.05;
    }
    .archon-hero p {
      margin: 0;
      color: ${PALETTE.muted};
      font-size: 14px;
      line-height: 1.6;
      max-width: 62ch;
    }
    .archon-hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }
    .archon-metric-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .archon-metric {
      padding: 14px;
      border-radius: 16px;
      background: rgba(15, 18, 25, 0.7);
      border: 1px solid rgba(42, 49, 66, 0.4);
      display: grid;
      gap: 6px;
    }
    .archon-metric-value {
      font-size: 20px;
      font-weight: 600;
    }
    .archon-metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: ${PALETTE.faint};
    }
    .archon-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
    }
    .archon-card {
      padding: 18px;
      border-radius: 20px;
      background: ${PALETTE.panel};
      border: 1px solid rgba(42, 49, 66, 0.6);
      display: grid;
      gap: 12px;
    }
    .archon-card h3 {
      margin: 0;
      font-size: 16px;
    }
    .archon-card p {
      margin: 0;
      color: ${PALETTE.muted};
      font-size: 13px;
      line-height: 1.6;
    }
    .archon-tag-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .archon-tag {
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(96, 165, 250, 0.15);
      border: 1px solid rgba(96, 165, 250, 0.25);
      font-size: 11px;
      color: ${PALETTE.text};
    }
    .archon-list {
      display: grid;
      gap: 10px;
    }
    .archon-list-item {
      padding: 12px;
      border-radius: 14px;
      border: 1px solid rgba(42, 49, 66, 0.5);
      background: rgba(17, 20, 27, 0.7);
      display: grid;
      gap: 6px;
    }
    .archon-list-item strong {
      font-size: 13px;
    }
    .archon-subtle {
      font-size: 12px;
      color: ${PALETTE.faint};
    }
    .archon-command {
      display: grid;
      gap: 12px;
      padding: 18px;
      border-radius: 18px;
      background: rgba(17, 20, 27, 0.8);
      border: 1px solid rgba(42, 49, 66, 0.6);
    }
    .archon-command-note {
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(15, 118, 110, 0.12);
      border: 1px solid rgba(15, 118, 110, 0.4);
      font-size: 12px;
      color: #c9f4ef;
    }
    .archon-command-log {
      display: grid;
      gap: 8px;
      padding: 12px;
      border-radius: 14px;
      border: 1px solid rgba(42, 49, 66, 0.7);
      background: rgba(8, 12, 20, 0.65);
    }
    .archon-command-log-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: ${PALETTE.muted};
    }
    .archon-command-log-item {
      display: grid;
      grid-template-columns: 70px 1fr;
      gap: 10px;
      font-size: 13px;
      color: ${PALETTE.text};
    }
    .archon-command-log-item time {
      color: ${PALETTE.muted};
      font-size: 11px;
    }
    .archon-command textarea {
      resize: vertical;
      min-height: 120px;
      border-radius: 14px;
      padding: 12px;
      border: 1px solid rgba(42, 49, 66, 0.8);
      background: rgba(7, 9, 13, 0.9);
      color: ${PALETTE.text};
      font-family: "IBM Plex Mono", "Space Mono", monospace;
      font-size: 13px;
    }
    .archon-command-footer {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: space-between;
    }
    .archon-segment {
      display: inline-flex;
      gap: 4px;
      border-radius: 999px;
      border: 1px solid rgba(42, 49, 66, 0.8);
      background: rgba(7, 9, 13, 0.9);
      padding: 4px;
    }
    .archon-segment button {
      border: 0;
      background: transparent;
      color: ${PALETTE.muted};
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      cursor: pointer;
    }
    .archon-segment button.active {
      background: rgba(249, 115, 22, 0.2);
      color: ${PALETTE.text};
    }
    .archon-approvals {
      display: grid;
      gap: 12px;
    }
    .archon-approval-card {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(42, 49, 66, 0.7);
      background: rgba(17, 20, 27, 0.88);
      display: grid;
      gap: 10px;
    }
    .archon-approval-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .archon-approval-actions button {
      flex: 1;
    }
    .archon-approval-actions .deny {
      background: rgba(248, 113, 113, 0.15);
      border-color: rgba(248, 113, 113, 0.4);
      color: ${PALETTE.text};
    }
    .archon-signal-list {
      display: grid;
      gap: 10px;
    }
    .archon-signal {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 12px;
      align-items: start;
      padding: 12px;
      border-radius: 14px;
      background: rgba(17, 20, 27, 0.7);
      border: 1px solid rgba(42, 49, 66, 0.6);
    }
    .archon-signal time {
      font-size: 11px;
      color: ${PALETTE.faint};
    }
    .archon-signal-title {
      font-size: 13px;
      font-weight: 600;
    }
    .archon-signal-detail {
      font-size: 12px;
      color: ${PALETTE.muted};
    }
    .archon-workflow-shell {
      display: grid;
      grid-template-columns: minmax(240px, 320px) 1fr;
      gap: 16px;
    }
    .archon-workflow-list {
      display: grid;
      gap: 10px;
    }
    .archon-workflow-item {
      padding: 12px;
      border-radius: 14px;
      border: 1px solid rgba(42, 49, 66, 0.6);
      background: rgba(17, 20, 27, 0.7);
      cursor: pointer;
      display: grid;
      gap: 4px;
    }
    .archon-workflow-item.active {
      border-color: rgba(249, 115, 22, 0.5);
      background: rgba(249, 115, 22, 0.08);
      color: ${PALETTE.text};
    }
    .archon-workflow-item span {
      font-size: 12px;
      color: ${PALETTE.faint};
    }
    .archon-flow-step {
      padding: 12px;
      border-radius: 14px;
      border: 1px solid rgba(42, 49, 66, 0.6);
      background: rgba(7, 9, 13, 0.7);
      display: grid;
      gap: 4px;
    }
    .archon-flow-arrow {
      text-align: center;
      color: ${PALETTE.faint};
      font-size: 18px;
    }
    .archon-team-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
    }
    .archon-team-card {
      padding: 16px;
      border-radius: 18px;
      background: rgba(17, 20, 27, 0.86);
      border: 1px solid rgba(42, 49, 66, 0.6);
      display: grid;
      gap: 10px;
    }
    .archon-team-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      border-radius: 999px;
      padding: 4px 10px;
      border: 1px solid rgba(42, 49, 66, 0.6);
      color: ${PALETTE.muted};
    }
    .archon-agent-status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      border-radius: 999px;
      padding: 4px 10px;
      background: rgba(96, 165, 250, 0.1);
      border: 1px solid rgba(96, 165, 250, 0.25);
    }
    .archon-agent-status.idle {
      background: rgba(93, 102, 119, 0.15);
      border-color: rgba(93, 102, 119, 0.3);
    }
    .archon-agent-status.running {
      background: rgba(20, 184, 166, 0.15);
      border-color: rgba(20, 184, 166, 0.35);
    }
    .archon-agent-status.waiting_approval {
      background: rgba(249, 115, 22, 0.2);
      border-color: rgba(249, 115, 22, 0.4);
    }
    .archon-agent-status.failed {
      background: rgba(248, 113, 113, 0.2);
      border-color: rgba(248, 113, 113, 0.4);
    }
    .archon-modal {
      position: fixed;
      inset: 0;
      background: rgba(4, 6, 12, 0.7);
      display: grid;
      place-items: center;
      z-index: 20;
      padding: 20px;
    }
    .archon-modal-card {
      width: min(680px, 92vw);
      background: rgba(15, 18, 25, 0.98);
      border: 1px solid rgba(42, 49, 66, 0.7);
      border-radius: 20px;
      padding: 18px;
      display: grid;
      gap: 12px;
    }
    @keyframes archonPulse {
      0% { box-shadow: 0 0 0 0 rgba(249, 115, 22, 0.3); }
      100% { box-shadow: 0 0 0 10px rgba(249, 115, 22, 0); }
    }
    @media (max-width: 1100px) {
      .archon-shell {
        grid-template-columns: 1fr;
      }
      .archon-rail {
        flex-direction: row;
        flex-wrap: wrap;
        justify-content: space-between;
      }
      .archon-hero {
        grid-template-columns: 1fr;
      }
      .archon-workflow-shell {
        grid-template-columns: 1fr;
      }
    }
    @media (max-width: 720px) {
      .archon-topbar {
        flex-direction: column;
        align-items: flex-start;
      }
      .archon-topbar-actions {
        width: 100%;
        justify-content: flex-start;
        flex-wrap: wrap;
      }
      .archon-main {
        padding: 16px;
      }
      .archon-metric-grid {
        grid-template-columns: 1fr;
      }
    }
  `;

  function Icon({ name }) {
    const base = {
      width: 16,
      height: 16,
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.6",
      strokeLinecap: "round",
      strokeLinejoin: "round",
    };
    if (name === "target") {
      return (
        <svg {...base}>
          <circle cx="12" cy="12" r="8" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      );
    }
    if (name === "mail") {
      return (
        <svg {...base}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M4 7l8 6 8-6" />
        </svg>
      );
    }
    if (name === "repeat") {
      return (
        <svg {...base}>
          <path d="M17 2l3 3-3 3" />
          <path d="M4 11V9a4 4 0 0 1 4-4h12" />
          <path d="M7 22l-3-3 3-3" />
          <path d="M20 13v2a4 4 0 0 1-4 4H4" />
        </svg>
      );
    }
    if (name === "chart") {
      return (
        <svg {...base}>
          <path d="M4 19h16" />
          <path d="M7 16l3-5 3 2 4-6" />
          <circle cx="7" cy="16" r="1" />
          <circle cx="10" cy="11" r="1" />
          <circle cx="13" cy="13" r="1" />
          <circle cx="17" cy="7" r="1" />
        </svg>
      );
    }
    if (name === "handshake") {
      return (
        <svg {...base}>
          <path d="M4 12l4-4 3 2 3-2 6 6" />
          <path d="M4 12l4 4" />
          <path d="M20 14l-3 3a2 2 0 0 1-3 0l-2-2" />
          <path d="M10 14l2 2" />
        </svg>
      );
    }
    if (name === "shield") {
      return (
        <svg {...base}>
          <path d="M12 3l7 3v6c0 5-3.5 8.5-7 9-3.5-.5-7-4-7-9V6l7-3z" />
        </svg>
      );
    }
    return (
      <svg {...base}>
        <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" />
      </svg>
    );
  }
  function App() {
    const archon = window.useARCHONContext ? window.useARCHONContext() : {};
    const status = String(archon?.status || "disconnected");
    const isInitializing = Boolean(archon?.isInitializing);
    const sessionId = String(archon?.sessionId || "").trim();
    const token = String(archon?.token || "").trim();
    const history = Array.isArray(archon?.history) ? archon.history : [];
    const pendingApprovals = Array.isArray(archon?.pendingApprovals) ? archon.pendingApprovals : [];
    const agentStates = archon?.agentStates || {};
    const costState = archon?.costState || { spent: 0, budget: 0, history: [] };
    const send = typeof archon?.send === "function" ? archon.send : () => {};

    const tauriInvoke =
      typeof window !== "undefined" &&
      window.__TAURI__ &&
      typeof window.__TAURI__.invoke === "function"
        ? window.__TAURI__.invoke
        : null;

    const [activeView, setActiveView] = useState("home");
    const [prompt, setPrompt] = useState("");
    const [promptMode, setPromptMode] = useState("auto");
    const [commandNotice, setCommandNotice] = useState("");
    const [lastCommand, setLastCommand] = useState(null);
    const [approvalsHidden, setApprovalsHidden] = useState({});
    const [decisions, setDecisions] = useState({});

    const [desktopStatus, setDesktopStatus] = useState(tauriInvoke ? "STARTING" : "");
    const [desktopBusy, setDesktopBusy] = useState(false);
    const [desktopError, setDesktopError] = useState("");
    const [desktopNotice, setDesktopNotice] = useState("");

    const [bearerToken, setBearerToken] = useState("");
    const [showDevAuth, setShowDevAuth] = useState(false);
    const [bearerDraft, setBearerDraft] = useState("");
    const [devAuthError, setDevAuthError] = useState("");

    const [workflowEntries, setWorkflowEntries] = useState([]);
    const [workflowPayloads, setWorkflowPayloads] = useState({});
    const [activeWorkflowId, setActiveWorkflowId] = useState("");
    const [studioNotice, setStudioNotice] = useState("");
    const [studioBusy, setStudioBusy] = useState(false);
    const studioSocketRef = useRef(null);
    const [teamEntries, setTeamEntries] = useState([]);
    const [teamDraft, setTeamDraft] = useState({
      name: "",
      summary: "",
      lead: "",
      members: "",
      guardrails: "",
    });
    const [teamNotice, setTeamNotice] = useState("");
    const [briefingDraft, setBriefingDraft] = useState({
      title: "Weekly CXO Briefing",
      audience: "Executive Team",
      period: "Last 7 days",
      objectives: "Growth, cash, risk, and next actions",
    });
    const [briefingResult, setBriefingResult] = useState(null);
    const [briefingNotice, setBriefingNotice] = useState("");
    const [exportNotice, setExportNotice] = useState("");
    const [exportId, setExportId] = useState("");
    const [apiApprovals, setApiApprovals] = useState([]);
    const [apiApprovalError, setApiApprovalError] = useState("");
    const [composerDraft, setComposerDraft] = useState({
      name: "",
      steps: [
        {
          agent: "ProspectorAgent",
          action: "find_prospects",
          label: "Find Prospects",
          nodeType: "AgentNode",
          dependsOn: "",
          x: 80,
          y: 120,
        },
      ],
    });
    const dragRef = useRef({ index: -1, offsetX: 0, offsetY: 0 });
    const [canvasTransform, setCanvasTransform] = useState({ scale: 1, offsetX: 0, offsetY: 0 });
    const panRef = useRef({ active: false, startX: 0, startY: 0, originX: 0, originY: 0 });
    const [connectMode, setConnectMode] = useState(false);
    const [connectSourceId, setConnectSourceId] = useState("");
    const [selectedNodes, setSelectedNodes] = useState([]);
    const [nodeSearch, setNodeSearch] = useState("");
    const [edgeLabels, setEdgeLabels] = useState({});
    const [edgeLabelDraft, setEdgeLabelDraft] = useState("");
    const [edgeLabelTarget, setEdgeLabelTarget] = useState(null);

    const apiBase = useMemo(() => resolveApiBase(), []);
    const commandLog = useMemo(() => {
      const items = [];
      for (let idx = history.length - 1; idx >= 0 && items.length < 6; idx -= 1) {
        const event = history[idx];
        const type = String(event?.type || "").toLowerCase();
        if (["assistant_token", "pong", "session_restored", "cost_update"].includes(type)) {
          continue;
        }
        const signal = historyEventToSignal(event, idx);
        if (signal) {
          items.push(signal);
        }
      }
      return items;
    }, [history]);

    useEffect(() => {
      if (!tauriInvoke) {
        return;
      }
      let active = true;
      const poll = async () => {
        try {
          const ok = await tauriInvoke("server_health");
          if (!active) return;
          setDesktopStatus(ok ? "RUNNING" : "STOPPED");
          if (ok) {
            setDesktopError("");
          }
        } catch (_error) {
          if (!active) return;
          setDesktopStatus("STOPPED");
        }
      };
      poll();
      const timer = setInterval(poll, 2000);
      return () => {
        active = false;
        clearInterval(timer);
      };
    }, [tauriInvoke]);

    useEffect(() => {
      try {
        const stored = String(localStorage.getItem("archon.desktop.bearer") || "").trim();
        if (stored) {
          setBearerToken(stored);
        }
      } catch (_error) {}
    }, []);

    useEffect(() => {
      try {
        const normalized = String(bearerToken || "").trim();
        if (normalized) {
          localStorage.setItem("archon.desktop.bearer", normalized);
        } else {
          localStorage.removeItem("archon.desktop.bearer");
        }
      } catch (_error) {}
    }, [bearerToken]);

    useEffect(() => {
      if (!showDevAuth) {
        setBearerDraft("");
        setDevAuthError("");
      }
    }, [showDevAuth]);

    useEffect(() => {
      const onKeyDown = (event) => {
        if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) {
          return;
        }
        if (event.key === "Delete") {
          setComposerDraft((current) => {
            const next = current.steps.filter(
              (step, index) => !selectedNodes.includes(getStepId(step, index)),
            );
            return { ...current, steps: next };
          });
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") {
          const selected = composerDraft.steps.filter(
            (step, index) => selectedNodes.includes(getStepId(step, index)),
          );
          if (selected.length) {
            try {
              navigator.clipboard.writeText(JSON.stringify(selected));
            } catch (_error) {}
          }
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
          try {
            navigator.clipboard.readText().then((text) => {
              const parsed = JSON.parse(text);
              if (!Array.isArray(parsed)) {
                return;
              }
              setComposerDraft((current) => ({
                ...current,
                steps: [
                  ...current.steps,
                  ...parsed.map((step, idx) => ({
                    ...step,
                    step_id: `step-${current.steps.length + idx + 1}`,
                    x: Number(step.x || 80) + 40,
                    y: Number(step.y || 120) + 40,
                  })),
                ],
              }));
            });
          } catch (_error) {}
        }
        if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) {
          const delta = event.shiftKey ? 20 : 10;
          setComposerDraft((current) => {
            const next = current.steps.map((step, index) => {
              if (!selectedNodes.includes(getStepId(step, index))) {
                return step;
              }
              if (event.key === "ArrowUp") {
                return { ...step, y: Number(step.y || 0) - delta };
              }
              if (event.key === "ArrowDown") {
                return { ...step, y: Number(step.y || 0) + delta };
              }
              if (event.key === "ArrowLeft") {
                return { ...step, x: Number(step.x || 0) - delta };
              }
              if (event.key === "ArrowRight") {
                return { ...step, x: Number(step.x || 0) + delta };
              }
              return step;
            });
            return { ...current, steps: next };
          });
        }
      };
      window.addEventListener("keydown", onKeyDown);
      return () => window.removeEventListener("keydown", onKeyDown);
    }, [composerDraft.steps, selectedNodes]);

    useEffect(() => {
      return () => {
        if (studioSocketRef.current) {
          try {
            studioSocketRef.current.close();
          } catch (_error) {
            return;
          }
        }
      };
    }, []);

    useEffect(() => {
      if (!bearerToken) {
        setWorkflowEntries([]);
        setWorkflowPayloads({});
        setActiveWorkflowId("");
        setStudioNotice("Studio locked. Add a Bearer token to run protected workflows.");
        return;
      }

      let cancelled = false;
      fetch(`${apiBase}/studio/workflows`, { headers: buildHeaders(bearerToken) })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(`Workflow list request failed (${response.status})`);
          }
          return response.json();
        })
        .then((rows) => {
          if (cancelled) return;
          if (!Array.isArray(rows) || !rows.length) {
            setWorkflowEntries([]);
            setActiveWorkflowId("");
            setStudioNotice("No workflows found for this tenant.");
            return;
          }
          const nextEntries = rows.slice(0, 12).map((row) => ({
            id: String(row.id || row.workflow_id || ""),
            name: String(row.name || "Untitled workflow"),
            lastRunText: row.updated_at ? "recent" : "unknown",
            source: "api",
          }));
          setWorkflowEntries(nextEntries);
          setActiveWorkflowId((current) =>
            nextEntries.some((item) => item.id === current) ? current : nextEntries[0].id,
          );
          setStudioNotice("");
        })
        .catch((_error) => {
          if (!cancelled) {
            setWorkflowEntries([]);
            setWorkflowPayloads({});
            setActiveWorkflowId("");
            setStudioNotice("Studio API unavailable or token invalid.");
          }
        });

      return () => {
        cancelled = true;
      };
    }, [apiBase, bearerToken]);

    useEffect(() => {
      if (!bearerToken) {
        setTeamEntries([]);
        return;
      }
      let cancelled = false;
      fetch(`${apiBase}/studio/teams`, { headers: buildHeaders(bearerToken) })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(`Team list request failed (${response.status})`);
          }
          return response.json();
        })
        .then((rows) => {
          if (!cancelled) {
            setTeamEntries(Array.isArray(rows) ? rows : []);
          }
        })
        .catch((_error) => {
          if (!cancelled) {
            setTeamEntries([]);
          }
        });
      return () => {
        cancelled = true;
      };
    }, [apiBase, bearerToken]);

    useEffect(() => {
      if (!bearerToken) {
        setApiApprovals([]);
        return;
      }
      let active = true;
      const poll = async () => {
        try {
          const response = await fetch(`${apiBase}/v1/approvals`, {
            headers: buildHeaders(bearerToken),
          });
          if (!response.ok) {
            throw new Error("approvals_failed");
          }
          const payload = await response.json();
          if (active) {
            setApiApprovals(Array.isArray(payload?.approvals) ? payload.approvals : []);
            setApiApprovalError("");
          }
        } catch (_error) {
          if (active) {
            setApiApprovalError("Approval feed unavailable.");
          }
        }
      };
      poll();
      const timer = setInterval(poll, 4000);
      return () => {
        active = false;
        clearInterval(timer);
      };
    }, [apiBase, bearerToken]);

    useEffect(() => {
      const liveIds = new Set(
        pendingApprovals
          .map((item) => String(item?.request_id || item?.action_id || "").trim())
          .filter(Boolean),
      );
      setApprovalsHidden((current) => {
        const next = {};
        Object.keys(current).forEach((id) => {
          if (liveIds.has(id)) {
            next[id] = current[id];
          }
        });
        return next;
      });
      setDecisions((current) => {
        const next = {};
        Object.keys(current).forEach((id) => {
          if (liveIds.has(id)) {
            next[id] = current[id];
          }
        });
        return next;
      });
    }, [pendingApprovals]);

    const visibleApprovals = useMemo(() => {
      return pendingApprovals.filter((item) => {
        const id = String(item?.request_id || item?.action_id || "").trim();
        return id && !approvalsHidden[id];
      });
    }, [approvalsHidden, pendingApprovals]);

    const combinedApprovals = useMemo(() => {
      const collected = new Map();
      visibleApprovals.forEach((item) => {
        const id = String(item?.request_id || item?.action_id || "").trim();
        if (id) {
          collected.set(id, { ...item, source: "webchat" });
        }
      });
      apiApprovals.forEach((item) => {
        const id = String(item?.request_id || item?.action_id || "").trim();
        if (id && !collected.has(id)) {
          collected.set(id, { ...item, source: "api" });
        }
      });
      return Array.from(collected.values());
    }, [apiApprovals, visibleApprovals]);

    const signals = useMemo(() => {
      const items = [];
      for (let idx = history.length - 1; idx >= 0 && items.length < 10; idx -= 1) {
        const signal = historyEventToSignal(history[idx], idx);
        if (signal) {
          items.push(signal);
        }
      }
      if (!items.length) {
        return SIGNAL_FALLBACK;
      }
      return items;
    }, [history]);

    const agentRoster = useMemo(() => {
      const approvalsByAgent = {};
      pendingApprovals.forEach((item) => {
        const agent = approvalAgentName(item) || "";
        if (agent) {
          approvalsByAgent[agent] = item;
        }
      });

      return SWARM_AGENTS.map((agent) => {
        const raw = String(agentStates?.[agent.id]?.status || "").toLowerCase();
        let statusLabel = raw || "idle";
        if (approvalsByAgent[agent.id]) {
          statusLabel = "waiting_approval";
        }
        if (statusLabel === "error") {
          statusLabel = "failed";
        }
        if (!statusLabel) {
          statusLabel = "idle";
        }
        return {
          ...agent,
          status: statusLabel,
          last: approvalsByAgent[agent.id]
            ? approvalTitle(approvalsByAgent[agent.id])
            : "Standing by",
        };
      });
    }, [agentStates, pendingApprovals]);

    const activeWorkflowEntry = useMemo(() => {
      return workflowEntries.find((item) => item.id === activeWorkflowId) || workflowEntries[0] || null;
    }, [activeWorkflowId, workflowEntries]);

    useEffect(() => {
      if (!bearerToken || !activeWorkflowEntry || activeWorkflowEntry.source !== "api") {
        return;
      }
      if (workflowPayloads[activeWorkflowEntry.id]) {
        return;
      }
      let cancelled = false;
      fetch(`${apiBase}/studio/workflows/${encodeURIComponent(activeWorkflowEntry.id)}`, {
        headers: buildHeaders(bearerToken),
      })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(`Workflow load failed (${response.status})`);
          }
          return response.json();
        })
        .then((payload) => {
          if (!cancelled) {
            setWorkflowPayloads((current) => ({ ...current, [activeWorkflowEntry.id]: payload }));
          }
        })
        .catch((_error) => {
          if (!cancelled) {
            setStudioNotice(`Could not load "${activeWorkflowEntry.name}".`);
          }
        });

      return () => {
        cancelled = true;
      };
    }, [activeWorkflowEntry, apiBase, bearerToken, workflowPayloads]);

    const workflowBlocks = useMemo(() => {
      const payload =
        (activeWorkflowEntry && workflowPayloads[activeWorkflowEntry.id]) ||
        (activeWorkflowEntry && activeWorkflowEntry.payload);
      return workflowBlocksFromPayload(payload);
    }, [activeWorkflowEntry, workflowPayloads]);

    const handleDesktopStartStop = async () => {
      if (!tauriInvoke || desktopBusy) {
        return;
      }
      setDesktopBusy(true);
      try {
        if (desktopStatus === "RUNNING") {
          await tauriInvoke("stop_server");
          setDesktopStatus("STOPPED");
        } else {
          setDesktopStatus("STARTING");
          await tauriInvoke("start_server");
          setDesktopError("");
        }
      } catch (error) {
        setDesktopError(String(error?.message || error || "Backend action failed."));
        setDesktopStatus("STOPPED");
      } finally {
        setDesktopBusy(false);
      }
    };

    const handleLaunchArchonEz = async () => {
        if (!tauriInvoke || desktopBusy) {
          return;
        }
        setDesktopNotice("Launching Archon EZ...");
        try {
          await tauriInvoke("launch_archon_ez");
          setDesktopNotice("Archon EZ launched.");
        } catch (error) {
          setDesktopNotice(String(error?.message || "Launch failed."));
        }
      };

      const handleApprovalDecision = (item, decision) => {
      const requestId = String(item?.request_id || item?.action_id || "").trim();
      if (!requestId) {
        return;
      }
      setDecisions((current) => ({ ...current, [requestId]: decision }));
      window.setTimeout(() => {
        setApprovalsHidden((current) => ({ ...current, [requestId]: true }));
        send({ type: decision, request_id: requestId, action_id: requestId });
      }, 200);
    };

    const handleApiApprovalDecision = async (item, decision) => {
      if (!bearerToken) {
        setApiApprovalError("Bearer token required.");
        return;
      }
      const requestId = String(item?.request_id || item?.action_id || "").trim();
      if (!requestId) {
        return;
      }
      setDecisions((current) => ({ ...current, [requestId]: decision }));
      try {
        const response = await fetch(
          `${apiBase}/v1/approvals/${encodeURIComponent(requestId)}/${decision}`,
          {
            method: "POST",
            headers: buildHeaders(bearerToken, true),
            body: JSON.stringify({}),
          },
        );
        if (!response.ok) {
          throw new Error(`Approval ${decision} failed (${response.status})`);
        }
      } catch (error) {
        setApiApprovalError(String(error?.message || "Approval failed."));
      }
    };

    const connectStudioRunSocket = (websocketPath, workflowName) => {
      if (!bearerToken || !websocketPath) {
        return;
      }
      if (studioSocketRef.current) {
        try {
          studioSocketRef.current.close();
        } catch (_error) {
          return;
        }
      }
      const url = `${resolveWsBase(apiBase)}${websocketPath}?token=${encodeURIComponent(bearerToken)}`;
      const socket = new WebSocket(url);
      studioSocketRef.current = socket;
      socket.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data);
          const item = historyEventToSignal(frame, 0);
          if (item) {
            setStudioNotice(`${workflowName}: ${item.detail}`);
          }
        } catch (_error) {
          return;
        }
      };
      socket.onclose = () => {
        if (studioSocketRef.current === socket) {
          studioSocketRef.current = null;
        }
      };
    };

    const handleRunNow = async () => {
      if (!bearerToken) {
        setStudioNotice("Studio locked. Add a Bearer token.");
        setShowDevAuth(true);
        return;
      }
      if (!activeWorkflowEntry) {
        setStudioNotice("Select a workflow first.");
        return;
      }
      setStudioBusy(true);
      try {
        const payload = workflowPayloads[activeWorkflowEntry.id] || activeWorkflowEntry.payload;
        if (!payload) {
          throw new Error(`No workflow definition available for "${activeWorkflowEntry.name}".`);
        }
        const response = await fetch(`${apiBase}/studio/run`, {
          method: "POST",
          headers: buildHeaders(bearerToken, true),
          body: JSON.stringify({ workflow: payload }),
        });
        if (!response.ok) {
          const detail = await response.text();
          throw new Error(detail || `Run request failed (${response.status})`);
        }
        const run = await response.json();
        connectStudioRunSocket(run.websocket_path, activeWorkflowEntry.name);
        setStudioNotice(`Started "${activeWorkflowEntry.name}".`);
        setActiveView("home");
      } catch (error) {
        setStudioNotice(String(error?.message || "Run failed."));
      } finally {
        setStudioBusy(false);
      }
    };

    const handleComposerSave = async () => {
      if (!bearerToken) {
        setStudioNotice("Studio locked. Add a Bearer token.");
        setShowDevAuth(true);
        return;
      }
      const name = String(composerDraft.name || "").trim();
      if (!name) {
        setStudioNotice("Name the workflow before saving.");
        return;
      }
      const rawSteps = composerDraft.steps || [];
      const steps = rawSteps.map((step, index) => {
        const stepId = String(step.step_id || `step-${index + 1}`).trim() || `step-${index + 1}`;
        const deps = String(step.dependsOn || "")
          .split(",")
          .map((dep) => dep.trim())
          .filter(Boolean);
        return {
          step_id: stepId,
          agent: step.agent,
          action: step.action,
          config: {
            label: step.label || step.action || `Step ${index + 1}`,
            subtitle: step.subtitle || "",
            node_type: step.nodeType || "AgentNode",
            icon: step.icon || "spark",
          },
          dependencies: deps.length ? deps : index === 0 ? [] : [`step-${index}`],
        };
      });
      const nodes = rawSteps.map((step, index) => ({
        id: steps[index].step_id,
        position: { x: Number(step.x || 80), y: Number(step.y || 80) },
        data: { label: steps[index].config.label, nodeType: steps[index].config.node_type },
        type: "agent",
      }));
      const edges = steps.flatMap((step, index) =>
        (step.dependencies || []).map((dep, depIndex) => ({
          id: `edge-${index}-${depIndex}`,
          source: dep,
          target: step.step_id,
          label: edgeLabels[`${dep}->${step.step_id}`] || "",
        })),
      );
      setStudioNotice("Saving workflow...");
      try {
        const response = await fetch(`${apiBase}/studio/workflows/compose`, {
          method: "POST",
          headers: buildHeaders(bearerToken, true),
          body: JSON.stringify({
            name,
            steps,
            metadata: { source: "agent_os", studio: { nodes, edges }, edge_labels: edgeLabels },
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Save failed (${response.status})`);
        }
        if (payload?.status === "pending") {
          setStudioNotice("Approval required to save this workflow. Review approvals.");
        } else {
          setStudioNotice("Workflow saved.");
        }
      } catch (error) {
        setStudioNotice(String(error?.message || "Save failed."));
      }
    };

    const loadWorkflowIntoComposer = (payload) => {
      if (!payload || !Array.isArray(payload.steps)) {
        setStudioNotice("No workflow data to load.");
        return;
      }
      const studioMeta = payload.metadata && payload.metadata.studio ? payload.metadata.studio : {};
      const labels = payload.metadata && payload.metadata.edge_labels ? payload.metadata.edge_labels : {};
      const nodesById = studioMeta.nodes || {};
      const steps = payload.steps.map((step, index) => {
        const stepId = String(step.step_id || `step-${index + 1}`);
        const node = nodesById[stepId] || {};
        const position = node.position || {};
        return {
          step_id: stepId,
          agent: String(step.agent || ""),
          action: String(step.action || ""),
          label: String(step.config?.label || step.action || `Step ${index + 1}`),
          nodeType: String(step.config?.node_type || "AgentNode"),
          dependsOn: Array.isArray(step.dependencies) ? step.dependencies.join(", ") : "",
          x: Number(position.x || 80 + index * 200),
          y: Number(position.y || 120 + (index % 2) * 120),
        };
      });
      setComposerDraft({
        name: String(payload.name || ""),
        steps,
      });
      setEdgeLabels(labels || {});
      setStudioNotice("Loaded workflow into composer.");
    };

    const handleTeamSave = async () => {
      if (!bearerToken) {
        setTeamNotice("Add a Bearer token to save teams.");
        setShowDevAuth(true);
        return;
      }
      const name = String(teamDraft.name || "").trim();
      if (!name) {
        setTeamNotice("Team name is required.");
        return;
      }
      setTeamNotice("Saving team...");
      try {
        const response = await fetch(`${apiBase}/studio/teams`, {
          method: "POST",
          headers: buildHeaders(bearerToken, true),
          body: JSON.stringify({
            name,
            summary: String(teamDraft.summary || "").trim(),
            lead: String(teamDraft.lead || "").trim(),
            members: String(teamDraft.members || "")
              .split(",")
              .map((member) => member.trim())
              .filter(Boolean),
            guardrails: String(teamDraft.guardrails || "")
              .split(",")
              .map((rule) => rule.trim())
              .filter(Boolean),
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Save failed (${response.status})`);
        }
        if (payload?.status === "pending") {
          setTeamNotice("Approval required to save this team. Review approvals.");
        } else {
          setTeamNotice("Team saved.");
        }
        const listResponse = await fetch(`${apiBase}/studio/teams`, {
          headers: buildHeaders(bearerToken),
        });
        if (listResponse.ok) {
          const rows = await listResponse.json();
          setTeamEntries(Array.isArray(rows) ? rows : []);
        }
      } catch (error) {
        setTeamNotice(String(error?.message || "Save failed."));
      }
    };

    const handleBriefingDraft = async () => {
      if (!bearerToken) {
        setBriefingNotice("Add a Bearer token to generate briefings.");
        setShowDevAuth(true);
        return;
      }
      setBriefingNotice("Generating briefing...");
      try {
        const response = await fetch(`${apiBase}/studio/briefings/draft`, {
          method: "POST",
          headers: buildHeaders(bearerToken, true),
          body: JSON.stringify({
            title: String(briefingDraft.title || "").trim(),
            audience: String(briefingDraft.audience || "").trim(),
            period: String(briefingDraft.period || "").trim(),
            objectives: String(briefingDraft.objectives || "").trim(),
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Draft failed (${response.status})`);
        }
        setBriefingResult(payload);
        setBriefingNotice("Briefing ready.");
      } catch (error) {
        setBriefingNotice(String(error?.message || "Briefing generation failed."));
      }
    };

    const handleBriefingExport = async () => {
      if (!bearerToken || !briefingResult) {
        setExportNotice("Generate a briefing first.");
        return;
      }
      setExportNotice("Requesting approval for export...");
      try {
        const response = await fetch(`${apiBase}/studio/briefings/export`, {
          method: "POST",
          headers: buildHeaders(bearerToken, true),
          body: JSON.stringify({ briefing: briefingResult, format: "pdf" }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Export failed (${response.status})`);
        }
        if (payload?.status === "pending") {
          setExportId(payload.request_id || "");
          setExportNotice("Approval required. Once approved, click Download Export.");
        } else if (payload?.request_id) {
          setExportId(payload.request_id);
          setExportNotice("Export ready. Click Download Export.");
        }
      } catch (error) {
        setExportNotice(String(error?.message || "Export failed."));
      }
    };

    const handleBriefingDownload = async () => {
      if (!bearerToken || !exportId) {
        setExportNotice("No export is ready yet.");
        return;
      }
      try {
        const response = await fetch(`${apiBase}/studio/briefings/export/${encodeURIComponent(exportId)}`, {
          headers: buildHeaders(bearerToken),
        });
        if (!response.ok) {
          throw new Error(`Export not ready (${response.status})`);
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `archon-briefing-${exportId}.pdf`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        setExportNotice("Download started.");
      } catch (error) {
        setExportNotice(String(error?.message || "Download failed."));
      }
    };

    const clamp = (value, min, max) => Math.max(min, Math.min(value, max));

    const handleCanvasPointerDown = (event, index) => {
      const target = event.currentTarget;
      const rect = target.getBoundingClientRect();
      dragRef.current = {
        index,
        offsetX: event.clientX - rect.left,
        offsetY: event.clientY - rect.top,
      };
      event.stopPropagation();
      event.preventDefault();
    };

    const handleCanvasPointerMove = (event) => {
      if (dragRef.current.index < 0) {
        return;
      }
      const canvas = event.currentTarget.getBoundingClientRect();
      const rawX = (event.clientX - canvas.left - canvasTransform.offsetX) / canvasTransform.scale;
      const rawY = (event.clientY - canvas.top - canvasTransform.offsetY) / canvasTransform.scale;
      const x = rawX - dragRef.current.offsetX;
      const y = rawY - dragRef.current.offsetY;
      const snappedX = Math.round(x / 20) * 20;
      const snappedY = Math.round(y / 20) * 20;
      setComposerDraft((current) => {
        const next = [...current.steps];
        if (!next[dragRef.current.index]) {
          return current;
        }
        next[dragRef.current.index] = {
          ...next[dragRef.current.index],
          x: clamp(snappedX, 20, canvas.width / canvasTransform.scale - 180),
          y: clamp(snappedY, 20, canvas.height / canvasTransform.scale - 80),
        };
        return { ...current, steps: next };
      });
    };

    const handleCanvasPointerUp = () => {
      dragRef.current = { index: -1, offsetX: 0, offsetY: 0 };
      panRef.current.active = false;
    };

    const handleCanvasPanStart = (event) => {
      if (event.button !== 0 || event.shiftKey === false) {
        return;
      }
      panRef.current = {
        active: true,
        startX: event.clientX,
        startY: event.clientY,
        originX: canvasTransform.offsetX,
        originY: canvasTransform.offsetY,
      };
      event.preventDefault();
    };

    const handleCanvasPanMove = (event) => {
      if (!panRef.current.active) {
        return;
      }
      const dx = event.clientX - panRef.current.startX;
      const dy = event.clientY - panRef.current.startY;
      setCanvasTransform((current) => ({
        ...current,
        offsetX: panRef.current.originX + dx,
        offsetY: panRef.current.originY + dy,
      }));
    };

    const handleCanvasWheel = (event) => {
      event.preventDefault();
      const delta = event.deltaY > 0 ? -0.08 : 0.08;
      setCanvasTransform((current) => ({
        ...current,
        scale: clamp(current.scale + delta, 0.6, 1.6),
      }));
    };

    const handleAutoLayout = () => {
      setComposerDraft((current) => {
        const next = current.steps.map((step, index) => ({
          ...step,
          x: 80 + index * 220,
          y: 120 + (index % 2) * 120,
        }));
        return { ...current, steps: next };
      });
    };

    const getStepId = (step, index) => String(step.step_id || `step-${index + 1}`).trim();

    const handleConnectClick = (event, index) => {
      if (!connectMode) {
        return;
      }
      event.stopPropagation();
      const targetId = getStepId(composerDraft.steps[index], index);
      if (!connectSourceId) {
        setConnectSourceId(targetId);
        return;
      }
      if (connectSourceId === targetId) {
        setConnectSourceId("");
        return;
      }
      setComposerDraft((current) => {
        const next = [...current.steps];
        const target = next[index];
        const existing = String(target.dependsOn || "")
          .split(",")
          .map((dep) => dep.trim())
          .filter(Boolean);
        const updated = Array.from(new Set([...existing, connectSourceId]));
        next[index] = { ...target, dependsOn: updated.join(", ") };
        return { ...current, steps: next };
      });
      setConnectSourceId("");
    };

    const removeEdge = (targetIndex, sourceId) => {
      setComposerDraft((current) => {
        const next = [...current.steps];
        const target = next[targetIndex];
        if (!target) {
          return current;
        }
        const updated = String(target.dependsOn || "")
          .split(",")
          .map((dep) => dep.trim())
          .filter((dep) => dep && dep !== sourceId);
        next[targetIndex] = { ...target, dependsOn: updated.join(", ") };
        return { ...current, steps: next };
      });
    };

    const toggleSelection = (id, event) => {
      if (!event.shiftKey) {
        setSelectedNodes([id]);
        return;
      }
      setSelectedNodes((current) =>
        current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
      );
    };

    const alignSelected = (direction) => {
      setComposerDraft((current) => {
        const next = [...current.steps];
        const selected = next
          .map((step, index) => ({ step, index, id: getStepId(step, index) }))
          .filter((item) => selectedNodes.includes(item.id));
        if (selected.length < 2) {
          return current;
        }
        const xs = selected.map((item) => Number(item.step.x || 0));
        const ys = selected.map((item) => Number(item.step.y || 0));
        const targetX = direction === "left" ? Math.min(...xs) : Math.max(...xs);
        const targetY = direction === "top" ? Math.min(...ys) : Math.max(...ys);
        selected.forEach(({ index }) => {
          const step = next[index];
          next[index] = {
            ...step,
            x: direction === "left" || direction === "right" ? targetX : step.x,
            y: direction === "top" || direction === "bottom" ? targetY : step.y,
          };
        });
        return { ...current, steps: next };
      });
    };

    const distributeSelected = (axis) => {
      setComposerDraft((current) => {
        const next = [...current.steps];
        const selected = next
          .map((step, index) => ({ step, index, id: getStepId(step, index) }))
          .filter((item) => selectedNodes.includes(item.id))
          .sort((a, b) =>
            axis === "x" ? Number(a.step.x || 0) - Number(b.step.x || 0) : Number(a.step.y || 0) - Number(b.step.y || 0),
          );
        if (selected.length < 3) {
          return current;
        }
        const start = axis === "x" ? Number(selected[0].step.x || 0) : Number(selected[0].step.y || 0);
        const end =
          axis === "x"
            ? Number(selected[selected.length - 1].step.x || 0)
            : Number(selected[selected.length - 1].step.y || 0);
        const stepSize = (end - start) / (selected.length - 1);
        selected.forEach((item, idx) => {
          const step = next[item.index];
          next[item.index] = {
            ...step,
            x: axis === "x" ? start + stepSize * idx : step.x,
            y: axis === "y" ? start + stepSize * idx : step.y,
          };
        });
        return { ...current, steps: next };
      });
    };

    const submitPrompt = () => {
      const content = String(prompt || "").trim();
      if (!content) {
        return;
      }
      const mode = promptMode === "debate" ? "debate" : "growth";
      send({ type: "message", content, mode });
      setLastCommand({
        content,
        mode: promptMode,
        sentAt: Date.now(),
      });
      if (status !== "connected" && !isInitializing) {
        setCommandNotice("Connecting to ARCHON runtime...");
      } else {
        setCommandNotice(`Mission dispatched (${mode}).`);
      }
      setPrompt("");
    };

    const promptHint = useMemo(() => {
      return "Describe the outcome. Ex: \"Build a CFO briefing with cash runway risks and next steps\".";
    }, []);

    const activeWorkflowList = workflowEntries.length ? workflowEntries : MISSION_TEMPLATES;
    const renderHome = () => (
      <div className="archon-main">
        <section className="archon-hero">
          <div style={{ display: "grid", gap: 14 }}>
            <h1>Agentic OS for every department. Outcomes first, complexity hidden.</h1>
            <p>
              Define outcomes in plain language. ARCHON assembles the right agents, runs the workflow, and
              pauses only when a human decision is required.
            </p>
            <div className="archon-hero-actions">
              <button type="button" className="archon-button primary" onClick={() => setActiveView("workflows")}
              >Launch a Mission</button>
              <button type="button" className="archon-button" onClick={() => setActiveView("teams")}
              >Design a Team</button>
              <button type="button" className="archon-button ghost" onClick={() => setActiveView("approvals")}
              >Review Approvals</button>
            </div>
          </div>
          <div className="archon-metric-grid">
            <div className="archon-metric">
              <div className="archon-metric-value">{combinedApprovals.length}</div>
              <div className="archon-metric-label">Waiting Approvals</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{formatCost(costState.spent)}</div>
              <div className="archon-metric-label">Spend Today</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{agentRoster.filter((agent) => agent.status !== "idle").length}</div>
              <div className="archon-metric-label">Agents Active</div>
            </div>
          </div>
        </section>

        <section className="archon-command">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Command Deck</strong>
            <span className="archon-subtle">Tell ARCHON the outcome and constraints.</span>
          </div>
          <textarea
            placeholder={promptHint}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
          <div className="archon-command-footer">
            <div className="archon-segment">
              {["auto", "fast", "debate"].map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={promptMode === mode ? "active" : ""}
                  onClick={() => setPromptMode(mode)}
                >
                  {mode.toUpperCase()}
                </button>
              ))}
            </div>
            <button type="button" className="archon-button primary" onClick={submitPrompt}>Dispatch Mission</button>
          </div>
          {commandNotice ? <div className="archon-command-note">{commandNotice}</div> : null}
          <div className="archon-command-log">
            <div className="archon-command-log-title">Mission Feed</div>
            {lastCommand ? (
              <div className="archon-command-log-item">
                <time>{formatClock(lastCommand.sentAt)}</time>
                <div>
                  <strong>Command</strong>
                  <div className="archon-subtle">{lastCommand.content}</div>
                </div>
              </div>
            ) : null}
            {commandLog.length ? (
              commandLog.map((signal) => (
                <div key={signal.id} className="archon-command-log-item">
                  <time>{signal.time}</time>
                  <div>{signal.detail}</div>
                </div>
              ))
            ) : (
              <div className="archon-subtle">No mission updates yet.</div>
            )}
          </div>
        </section>

        <section className="archon-grid">
          {DEPARTMENTS.map((dept) => (
            <div key={dept.id} className="archon-card">
              <h3>{dept.title}</h3>
              <p>{dept.summary}</p>
              <div className="archon-tag-row">
                {dept.outcomes.map((outcome) => (
                  <span key={outcome} className="archon-tag">{outcome}</span>
                ))}
              </div>
            </div>
          ))}
        </section>

        <section className="archon-grid">
          <div className="archon-card">
            <h3>Live Agent Pod</h3>
            <p>Growth swarm status across lead, outreach, nurture, and retention roles.</p>
            <div className="archon-list">
              {agentRoster.map((agent) => (
                <div key={agent.id} className="archon-list-item">
                  <strong>{agent.role}</strong>
                  <div className={`archon-agent-status ${agent.status}`}>{agent.status.replace(/_/g, " ")}</div>
                  <span className="archon-subtle">{clipText(agent.last, 80)}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="archon-card">
            <h3>Signals & Alerts</h3>
            <p>Recent system signals and executive-level events.</p>
            <div className="archon-signal-list">
              {signals.map((signal) => (
                <div key={signal.id} className="archon-signal">
                  <time>{signal.time}</time>
                  <div>
                    <div className="archon-signal-title">{signal.title}</div>
                    <div className="archon-signal-detail">{signal.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    );

    const renderTeams = () => (
      <div className="archon-main">
        <section className="archon-hero">
          <div style={{ display: "grid", gap: 12 }}>
            <h1>Design multi-agent teams that behave like full departments.</h1>
            <p>
              Assign a lead agent, set guardrails, and let the pod run repeatable playbooks with approval
              gates.
            </p>
          </div>
          <div className="archon-metric-grid">
            <div className="archon-metric">
              <div className="archon-metric-value">7</div>
              <div className="archon-metric-label">Active Swarm Roles</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{AGENT_PODS.length}</div>
              <div className="archon-metric-label">Pods Ready</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{combinedApprovals.length}</div>
              <div className="archon-metric-label">Human Gates</div>
            </div>
          </div>
        </section>

        <section className="archon-grid">
          <div className="archon-card">
            <h3>Team Builder</h3>
            <p>Create a department pod with guardrails (approval required).</p>
            <div style={{ display: "grid", gap: 10 }}>
              <input
                type="text"
                placeholder="Team name"
                value={teamDraft.name}
                onChange={(event) => setTeamDraft((current) => ({ ...current, name: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <input
                type="text"
                placeholder="Summary"
                value={teamDraft.summary}
                onChange={(event) => setTeamDraft((current) => ({ ...current, summary: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <input
                type="text"
                placeholder="Lead agent"
                value={teamDraft.lead}
                onChange={(event) => setTeamDraft((current) => ({ ...current, lead: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <input
                type="text"
                placeholder="Members (comma separated)"
                value={teamDraft.members}
                onChange={(event) => setTeamDraft((current) => ({ ...current, members: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <input
                type="text"
                placeholder="Guardrails (comma separated)"
                value={teamDraft.guardrails}
                onChange={(event) => setTeamDraft((current) => ({ ...current, guardrails: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <button type="button" className="archon-button primary" onClick={handleTeamSave}>
                Save Team
              </button>
              {teamNotice ? <div className="archon-subtle">{teamNotice}</div> : null}
            </div>
          </div>
          <div className="archon-card">
            <h3>Saved Teams</h3>
            <p>Teams stored in Studio (approval-gated writes).</p>
            {teamEntries.length ? (
              <div className="archon-list">
                {teamEntries.map((team) => (
                  <div key={team.team_id} className="archon-list-item">
                    <strong>{team.name}</strong>
                    <div className="archon-subtle">{team.summary || "No summary"}</div>
                    <div className="archon-tag-row">
                      {(team.members || []).slice(0, 4).map((member) => (
                        <span key={member} className="archon-tag">{member}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="archon-subtle">No teams saved yet.</div>
            )}
          </div>
        </section>

        <section className="archon-team-grid">
          {AGENT_PODS.map((pod) => (
            <div key={pod.id} className="archon-team-card">
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>{pod.name}</strong>
                <span className="archon-team-pill">Lead: {pod.lead}</span>
              </div>
              <div className="archon-subtle">Members</div>
              <div className="archon-tag-row">
                {pod.members.map((member) => (
                  <span key={member} className="archon-tag">{member}</span>
                ))}
              </div>
              <button type="button" className="archon-button">Clone Pod</button>
            </div>
          ))}
        </section>
      </div>
    );

    const renderWorkflows = () => (
      <div className="archon-main">
        <section className="archon-hero">
          <div style={{ display: "grid", gap: 12 }}>
            <h1>Mission Studio. Build workflows from outcomes, not code.</h1>
            <p>
              Select a workflow, inspect the steps, and run it through the Studio API. Create new missions by
              describing outcomes in natural language.
            </p>
            <div className="archon-hero-actions">
              <button type="button" className="archon-button primary" onClick={handleRunNow} disabled={studioBusy}>
                {studioBusy ? "Running..." : "Run Selected"}
              </button>
              <button type="button" className="archon-button" onClick={() => setShowDevAuth(true)}>
                Dev Auth
              </button>
              <button
                type="button"
                className="archon-button"
                onClick={() => loadWorkflowIntoComposer(activeWorkflowEntry && (workflowPayloads[activeWorkflowEntry.id] || activeWorkflowEntry.payload))}
              >
                Load Into Composer
              </button>
            </div>
            {studioNotice ? <div className="archon-subtle">{studioNotice}</div> : null}
          </div>
          <div className="archon-command">
            <strong>Outcome Builder</strong>
            <p className="archon-subtle">Define a mission. ARCHON will synthesize the workflow steps.</p>
            <textarea
              placeholder="Example: Build a weekly CEO briefing covering growth, cash, risks, and next actions."
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
            />
            <div className="archon-command-footer">
              <button type="button" className="archon-button" onClick={submitPrompt}>Draft Workflow</button>
              <button type="button" className="archon-button primary" onClick={submitPrompt}>Generate Team + Workflow</button>
            </div>
            {commandNotice ? <div className="archon-command-note">{commandNotice}</div> : null}
            <div className="archon-command-log">
              <div className="archon-command-log-title">Mission Feed</div>
              {lastCommand ? (
                <div className="archon-command-log-item">
                  <time>{formatClock(lastCommand.sentAt)}</time>
                  <div>
                    <strong>Command</strong>
                    <div className="archon-subtle">{lastCommand.content}</div>
                  </div>
                </div>
              ) : null}
              {commandLog.length ? (
                commandLog.map((signal) => (
                  <div key={signal.id} className="archon-command-log-item">
                    <time>{signal.time}</time>
                    <div>{signal.detail}</div>
                  </div>
                ))
              ) : (
                <div className="archon-subtle">No mission updates yet.</div>
              )}
            </div>
          </div>
        </section>

        <section className="archon-workflow-shell">
          <div className="archon-card">
            <strong>Workflow Library</strong>
            <div className="archon-workflow-list">
              {activeWorkflowList.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`archon-workflow-item ${item.id === activeWorkflowId ? "active" : ""}`}
                  onClick={() => setActiveWorkflowId(item.id)}
                >
                  <div>{item.name}</div>
                  <span>{item.lastRunText || "not run"}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="archon-card">
            <strong>{activeWorkflowEntry ? activeWorkflowEntry.name : "Workflow Steps"}</strong>
            {workflowBlocks.length ? (
              <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
                {workflowBlocks.map((block, index) => (
                  <React.Fragment key={block.id || block.title + index}>
                    <div className="archon-flow-step">
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <Icon name={block.icon} />
                        <strong>{block.title}</strong>
                      </div>
                      <span className="archon-subtle">{block.subtitle}</span>
                    </div>
                    {index < workflowBlocks.length - 1 ? <div className="archon-flow-arrow">↓</div> : null}
                  </React.Fragment>
                ))}
              </div>
            ) : (
              <div className="archon-subtle" style={{ marginTop: 12 }}>
                Select a workflow to preview the steps.
              </div>
            )}
          </div>
        </section>
      </div>
    );
    const renderApprovals = () => (
      <div className="archon-main">
        <section className="archon-hero">
          <div style={{ display: "grid", gap: 12 }}>
            <h1>Human approval gates. Nothing external moves without you.</h1>
            <p>
              Review queued actions before they execute. ARCHON will never push external actions without your
              decision.
            </p>
          </div>
          <div className="archon-metric-grid">
            <div className="archon-metric">
              <div className="archon-metric-value">{visibleApprovals.length}</div>
              <div className="archon-metric-label">Waiting</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{formatCost(costState.spent)}</div>
              <div className="archon-metric-label">Spend Today</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{history.length}</div>
              <div className="archon-metric-label">Events Logged</div>
            </div>
          </div>
        </section>

        <section className="archon-approvals">
          {combinedApprovals.length ? (
            combinedApprovals.map((item) => {
              const requestId = String(item?.request_id || item?.action_id || "").trim();
              return (
                <div key={requestId} className="archon-approval-card">
                  <strong>{approvalTitle(item)}</strong>
                  <div className="archon-subtle">{approvalAgentName(item) || "System"}</div>
                  <p>{approvalPreview(item)}</p>
                  <div className="archon-approval-actions">
                    <button
                      type="button"
                      className="archon-button primary"
                      onClick={() =>
                        item.source === "api"
                          ? handleApiApprovalDecision(item, "approve")
                          : handleApprovalDecision(item, "approve")
                      }
                      disabled={decisions[requestId]}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="archon-button deny"
                      onClick={() =>
                        item.source === "api"
                          ? handleApiApprovalDecision(item, "deny")
                          : handleApprovalDecision(item, "deny")
                      }
                      disabled={decisions[requestId]}
                    >
                      Deny
                    </button>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="archon-card">
              <strong>No approvals waiting.</strong>
              <p>When an agent needs permission, it will appear here instantly.</p>
            </div>
          )}
          {apiApprovalError ? <div className="archon-subtle">{apiApprovalError}</div> : null}
        </section>
      </div>
    );

    const renderSignals = () => (
      <div className="archon-main">
        <section className="archon-hero">
          <div style={{ display: "grid", gap: 12 }}>
            <h1>Signal Room. Know what the agents are doing in real time.</h1>
            <p>Audit trails, cost tracking, and the live stream of actions across pods.</p>
          </div>
          <div className="archon-metric-grid">
            <div className="archon-metric">
              <div className="archon-metric-value">{formatCost(costState.spent)}</div>
              <div className="archon-metric-label">Spend Today</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{signals.length}</div>
              <div className="archon-metric-label">Signals</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{agentRoster.filter((agent) => agent.status !== "idle").length}</div>
              <div className="archon-metric-label">Agents Active</div>
            </div>
          </div>
        </section>

        <section className="archon-card">
          <strong>Latest Signals</strong>
          <div className="archon-signal-list" style={{ marginTop: 12 }}>
            {signals.map((signal) => (
              <div key={signal.id} className="archon-signal">
                <time>{signal.time}</time>
                <div>
                  <div className="archon-signal-title">{signal.title}</div>
                  <div className="archon-signal-detail">{signal.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="archon-card">
          <strong>Workflow Composer</strong>
          <p className="archon-subtle">Define steps and save as a reusable workflow (approval required).</p>
          <div style={{ display: "grid", gap: 10 }}>
            <input
              type="text"
              placeholder="Workflow name"
              value={composerDraft.name}
              onChange={(event) => setComposerDraft((current) => ({ ...current, name: event.target.value }))}
              style={{
                padding: "10px 12px",
                borderRadius: 12,
                border: `1px solid ${PALETTE.border}`,
                background: "rgba(7, 9, 13, 0.9)",
                color: PALETTE.text,
              }}
            />
            {(composerDraft.steps || []).map((step, index) => (
              <div
                key={`step-${index}`}
                style={{ display: "grid", gap: 6, gridTemplateColumns: "1.1fr 1fr 1fr 1fr 1fr 1.2fr" }}
              >
                <input
                  type="text"
                  placeholder={`step-${index + 1}`}
                  value={step.step_id || ""}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: `1px solid ${PALETTE.border}`,
                    background: "rgba(7, 9, 13, 0.9)",
                    color: PALETTE.text,
                  }}
                  onChange={(event) =>
                    setComposerDraft((current) => {
                      const next = [...current.steps];
                      next[index] = { ...next[index], step_id: event.target.value };
                      return { ...current, steps: next };
                    })
                  }
                />
                <select
                  value={step.nodeType || "AgentNode"}
                  onChange={(event) =>
                    setComposerDraft((current) => {
                      const next = [...current.steps];
                      next[index] = { ...next[index], nodeType: event.target.value };
                      return { ...current, steps: next };
                    })
                  }
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: `1px solid ${PALETTE.border}`,
                    background: "rgba(7, 9, 13, 0.9)",
                    color: PALETTE.text,
                  }}
                >
                  <option value="AgentNode">Agent</option>
                  <option value="ApprovalNode">Approval</option>
                  <option value="OutputNode">Output</option>
                  <option value="ConditionalNode">Conditional</option>
                </select>
                <input
                  type="text"
                  placeholder="Agent"
                  value={step.agent}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: `1px solid ${PALETTE.border}`,
                    background: "rgba(7, 9, 13, 0.9)",
                    color: PALETTE.text,
                  }}
                  onChange={(event) =>
                    setComposerDraft((current) => {
                      const next = [...current.steps];
                      next[index] = { ...next[index], agent: event.target.value };
                      return { ...current, steps: next };
                    })
                  }
                />
                <input
                  type="text"
                  placeholder="Action"
                  value={step.action}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: `1px solid ${PALETTE.border}`,
                    background: "rgba(7, 9, 13, 0.9)",
                    color: PALETTE.text,
                  }}
                  onChange={(event) =>
                    setComposerDraft((current) => {
                      const next = [...current.steps];
                      next[index] = { ...next[index], action: event.target.value };
                      return { ...current, steps: next };
                    })
                  }
                />
                <input
                  type="text"
                  placeholder="Label"
                  value={step.label || ""}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: `1px solid ${PALETTE.border}`,
                    background: "rgba(7, 9, 13, 0.9)",
                    color: PALETTE.text,
                  }}
                  onChange={(event) =>
                    setComposerDraft((current) => {
                      const next = [...current.steps];
                      next[index] = { ...next[index], label: event.target.value };
                      return { ...current, steps: next };
                    })
                  }
                />
                <input
                  type="text"
                  placeholder="Depends on (step ids)"
                  value={step.dependsOn || ""}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: `1px solid ${PALETTE.border}`,
                    background: "rgba(7, 9, 13, 0.9)",
                    color: PALETTE.text,
                  }}
                  onChange={(event) =>
                    setComposerDraft((current) => {
                      const next = [...current.steps];
                      next[index] = { ...next[index], dependsOn: event.target.value };
                      return { ...current, steps: next };
                    })
                  }
                />
              </div>
            ))}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                className="archon-button"
                onClick={() =>
                  setComposerDraft((current) => ({
                    ...current,
                    steps: [
                      ...current.steps,
                      {
                        step_id: `step-${current.steps.length + 1}`,
                        agent: "OutreachAgent",
                        action: "draft_outreach",
                        label: "",
                        nodeType: "AgentNode",
                        dependsOn: "",
                        x: 80 + current.steps.length * 200,
                        y: 120 + (current.steps.length % 2) * 120,
                      },
                    ],
                  }))
                }
              >
                Add Step
              </button>
              <button type="button" className="archon-button" onClick={handleAutoLayout}>
                Auto Layout
              </button>
              <button
                type="button"
                className="archon-button"
                onClick={() => setCanvasTransform({ scale: 1, offsetX: 0, offsetY: 0 })}
              >
                Reset View
              </button>
              <button
                type="button"
                className={`archon-button ${connectMode ? "primary" : ""}`}
                onClick={() => {
                  setConnectMode((current) => !current);
                  setConnectSourceId("");
                }}
              >
                {connectMode ? "Exit Connect" : "Connect Nodes"}
              </button>
              <button type="button" className="archon-button" onClick={() => alignSelected("left")}>
                Align Left
              </button>
              <button type="button" className="archon-button" onClick={() => alignSelected("top")}>
                Align Top
              </button>
              <button type="button" className="archon-button" onClick={() => distributeSelected("x")}>
                Distribute X
              </button>
              <button type="button" className="archon-button" onClick={() => distributeSelected("y")}>
                Distribute Y
              </button>
              <button type="button" className="archon-button primary" onClick={handleComposerSave}>
                Save Workflow
              </button>
            </div>
            {connectMode ? (
              <div className="archon-subtle">
                Click a source node, then click a target node to add a dependency.
              </div>
            ) : null}
            <input
              type="text"
              placeholder="Search nodes..."
              value={nodeSearch}
              onChange={(event) => setNodeSearch(event.target.value)}
              style={{
                padding: "10px 12px",
                borderRadius: 12,
                border: `1px solid ${PALETTE.border}`,
                background: "rgba(7, 9, 13, 0.9)",
                color: PALETTE.text,
              }}
            />
          </div>
          <div
            style={{
              position: "relative",
              height: 320,
              borderRadius: 16,
              border: `1px solid ${PALETTE.border}`,
              background: "rgba(7, 9, 13, 0.9)",
              overflow: "hidden",
            }}
            onPointerMove={handleCanvasPointerMove}
            onPointerUp={handleCanvasPointerUp}
            onPointerLeave={handleCanvasPointerUp}
            onPointerDown={handleCanvasPanStart}
            onPointerMoveCapture={handleCanvasPanMove}
            onWheel={handleCanvasWheel}
          >
            <div
              style={{
                position: "absolute",
                inset: 0,
                backgroundImage:
                  "linear-gradient(rgba(42,49,66,0.25) 1px, transparent 1px), linear-gradient(90deg, rgba(42,49,66,0.25) 1px, transparent 1px)",
                backgroundSize: `${20 * canvasTransform.scale}px ${20 * canvasTransform.scale}px`,
                transform: `translate(${canvasTransform.offsetX}px, ${canvasTransform.offsetY}px)`,
              }}
            />
            <svg
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                transform: `translate(${canvasTransform.offsetX}px, ${canvasTransform.offsetY}px) scale(${canvasTransform.scale})`,
                transformOrigin: "top left",
              }}
              aria-hidden="true"
            >
              {(composerDraft.steps || []).flatMap((step, index) => {
                const deps = String(step.dependsOn || "")
                  .split(",")
                  .map((dep) => dep.trim())
                  .filter(Boolean);
                const fallbackDep = index === 0 ? [] : [`step-${index}`];
                const edges = deps.length ? deps : fallbackDep;
                return edges.map((dep) => {
                  const source = composerDraft.steps.find(
                    (item, idx) => (item.step_id || `step-${idx + 1}`) === dep,
                  );
                  const sourceIndex = composerDraft.steps.findIndex(
                    (item, idx) => (item.step_id || `step-${idx + 1}`) === dep,
                  );
                  const resolvedSource = source || composerDraft.steps[sourceIndex] || composerDraft.steps[index - 1];
                  if (!resolvedSource) {
                    return null;
                  }
                  const x1 = (resolvedSource.x || 80) + 140;
                  const y1 = (resolvedSource.y || 80) + 24;
                  const x2 = (step.x || 80) + 0;
                  const y2 = (step.y || 80) + 24;
                  const edgeKey = `${dep}->${getStepId(step, index)}`;
                  const label = edgeLabels[edgeKey] || "";
                  return (
                    <g key={`edge-${index}-${dep}`}>
                      <line
                        x1={x1}
                        y1={y1}
                        x2={x2}
                        y2={y2}
                        stroke="rgba(249,115,22,0.6)"
                        strokeWidth="2"
                      />
                      {label ? (
                        <text
                          x={(x1 + x2) / 2}
                          y={(y1 + y2) / 2 - 10}
                          fill={PALETTE.text}
                          fontSize="12"
                          textAnchor="middle"
                        >
                          {label}
                        </text>
                      ) : null}
                      <circle
                        cx={(x1 + x2) / 2}
                        cy={(y1 + y2) / 2}
                        r="8"
                        fill="rgba(15, 23, 42, 0.9)"
                        stroke="rgba(249,115,22,0.8)"
                        strokeWidth="1.5"
                        style={{ cursor: "pointer" }}
                        onClick={(event) => {
                          event.stopPropagation();
                          setEdgeLabelTarget({ source: dep, target: getStepId(step, index) });
                          setEdgeLabelDraft(label);
                        }}
                      />
                      <circle
                        cx={(x1 + x2) / 2}
                        cy={(y1 + y2) / 2 + 18}
                        r="6"
                        fill="rgba(17, 24, 39, 0.9)"
                        stroke="rgba(248,113,113,0.8)"
                        strokeWidth="1.5"
                        style={{ cursor: "pointer" }}
                        onClick={(event) => {
                          event.stopPropagation();
                          removeEdge(index, dep);
                        }}
                      />
                    </g>
                  );
                });
              })}
            </svg>
            {(composerDraft.steps || []).map((step, index) => (
              (() => {
                const label = `${step.label || step.action || ""} ${step.agent || ""} ${step.step_id || ""}`.toLowerCase();
                const matches = !nodeSearch.trim() || label.includes(nodeSearch.trim().toLowerCase());
                const nodeId = getStepId(step, index);
                if (!matches) {
                  return null;
                }
                return (
              <div
                key={`node-${index}`}
                role="button"
                tabIndex={0}
                onPointerDown={(event) => handleCanvasPointerDown(event, index)}
                onClick={(event) => {
                  handleConnectClick(event, index);
                  toggleSelection(nodeId, event);
                }}
                style={{
                  position: "absolute",
                  left: (step.x || 80) * canvasTransform.scale + canvasTransform.offsetX,
                  top: (step.y || 80) * canvasTransform.scale + canvasTransform.offsetY,
                  width: 160,
                  transform: `scale(${canvasTransform.scale})`,
                  transformOrigin: "top left",
                  padding: "10px 12px",
                  borderRadius: 14,
                  border:
                    step.nodeType === "ApprovalNode"
                      ? "1px solid rgba(249,115,22,0.7)"
                      : step.nodeType === "OutputNode"
                        ? "1px solid rgba(20,184,166,0.7)"
                        : step.nodeType === "ConditionalNode"
                          ? "1px solid rgba(96,165,250,0.7)"
                          : `1px solid ${PALETTE.border}`,
                  background:
                    step.nodeType === "ApprovalNode"
                      ? "rgba(64, 28, 10, 0.9)"
                      : step.nodeType === "OutputNode"
                        ? "rgba(8, 39, 36, 0.9)"
                        : step.nodeType === "ConditionalNode"
                          ? "rgba(15, 24, 46, 0.9)"
                          : "rgba(23, 27, 38, 0.95)",
                  color: PALETTE.text,
                  cursor: connectMode ? "crosshair" : "grab",
                  userSelect: "none",
                  boxShadow:
                    connectSourceId && connectSourceId === nodeId
                      ? "0 0 0 2px rgba(249,115,22,0.8)"
                      : selectedNodes.includes(nodeId)
                        ? "0 0 0 2px rgba(96,165,250,0.8)"
                        : "none",
                }}
              >
                <div style={{ fontSize: 12, color: PALETTE.faint }}>
                  {step.step_id || `step-${index + 1}`}
                </div>
                <div style={{ fontWeight: 600 }}>{step.label || step.action || "Untitled"}</div>
                <div style={{ fontSize: 11, color: PALETTE.muted }}>
                  {step.nodeType || "AgentNode"} · {step.agent}
                </div>
              </div>
                );
              })()
            ))}
            <div
              style={{
                position: "absolute",
                right: 12,
                bottom: 12,
                width: 140,
                height: 100,
                borderRadius: 10,
                border: `1px solid ${PALETTE.border}`,
                background: "rgba(15, 18, 25, 0.9)",
                padding: 6,
                pointerEvents: "none",
              }}
            >
              <svg width="100%" height="100%" viewBox="0 0 600 400" aria-hidden="true">
                {(composerDraft.steps || []).map((step, idx) => {
                  const x = (step.x || 0) / 4;
                  const y = (step.y || 0) / 4;
                  return (
                    <rect
                      key={`mini-${idx}`}
                      x={x}
                      y={y}
                      width="32"
                      height="18"
                      rx="4"
                      fill="rgba(96,165,250,0.6)"
                    />
                  );
                })}
                <rect
                  x={Math.max(0, -canvasTransform.offsetX / 4)}
                  y={Math.max(0, -canvasTransform.offsetY / 4)}
                  width={140 / canvasTransform.scale}
                  height={100 / canvasTransform.scale}
                  fill="none"
                  stroke="rgba(249,115,22,0.9)"
                  strokeWidth="2"
                />
              </svg>
            </div>
            {edgeLabelTarget ? (
              <div
                style={{
                  position: "absolute",
                  left: 12,
                  bottom: 12,
                  width: 240,
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(12, 16, 24, 0.95)",
                  padding: 10,
                  display: "grid",
                  gap: 6,
                }}
              >
                <div className="archon-subtle">Edge label</div>
                <input
                  type="text"
                  value={edgeLabelDraft}
                  onChange={(event) => setEdgeLabelDraft(event.target.value)}
                  placeholder="Condition or label"
                  style={{
                    padding: "8px 10px",
                    borderRadius: 10,
                    border: `1px solid ${PALETTE.border}`,
                    background: "rgba(7, 9, 13, 0.9)",
                    color: PALETTE.text,
                  }}
                />
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="archon-button"
                    onClick={() => setEdgeLabelTarget(null)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="archon-button primary"
                    onClick={() => {
                      const key = `${edgeLabelTarget.source}->${edgeLabelTarget.target}`;
                      setEdgeLabels((current) => ({ ...current, [key]: edgeLabelDraft.trim() }));
                      setEdgeLabelTarget(null);
                      setEdgeLabelDraft("");
                    }}
                  >
                    Save Label
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    );

    const renderBriefings = () => (
      <div className="archon-main">
        <section className="archon-hero">
          <div style={{ display: "grid", gap: 12 }}>
            <h1>CXO Briefing Generator</h1>
            <p>Generate executive-ready briefs and export to PDF with approval gates.</p>
          </div>
          <div className="archon-metric-grid">
            <div className="archon-metric">
              <div className="archon-metric-value">{formatCost(costState.spent)}</div>
              <div className="archon-metric-label">Spend Today</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{briefingResult ? "Ready" : "Draft"}</div>
              <div className="archon-metric-label">Briefing State</div>
            </div>
            <div className="archon-metric">
              <div className="archon-metric-value">{exportId ? "Queued" : "Idle"}</div>
              <div className="archon-metric-label">Export Status</div>
            </div>
          </div>
        </section>

        <section className="archon-grid">
          <div className="archon-card">
            <h3>Briefing Inputs</h3>
            <div style={{ display: "grid", gap: 10 }}>
              <input
                type="text"
                placeholder="Title"
                value={briefingDraft.title}
                onChange={(event) => setBriefingDraft((current) => ({ ...current, title: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <input
                type="text"
                placeholder="Audience"
                value={briefingDraft.audience}
                onChange={(event) => setBriefingDraft((current) => ({ ...current, audience: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <input
                type="text"
                placeholder="Period"
                value={briefingDraft.period}
                onChange={(event) => setBriefingDraft((current) => ({ ...current, period: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <input
                type="text"
                placeholder="Objectives"
                value={briefingDraft.objectives}
                onChange={(event) => setBriefingDraft((current) => ({ ...current, objectives: event.target.value }))}
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button type="button" className="archon-button primary" onClick={handleBriefingDraft}>
                  Generate Briefing
                </button>
                <button type="button" className="archon-button" onClick={handleBriefingExport}>
                  Request PDF Export
                </button>
                <button type="button" className="archon-button" onClick={handleBriefingDownload}>
                  Download Export
                </button>
              </div>
              {briefingNotice ? <div className="archon-subtle">{briefingNotice}</div> : null}
              {exportNotice ? <div className="archon-subtle">{exportNotice}</div> : null}
            </div>
          </div>
          <div className="archon-card">
            <h3>Briefing Output</h3>
            {briefingResult ? (
              <pre style={{ whiteSpace: "pre-wrap", color: PALETTE.text, fontSize: 12 }}>
                {JSON.stringify(briefingResult, null, 2)}
              </pre>
            ) : (
              <p className="archon-subtle">Generate a briefing to preview output here.</p>
            )}
          </div>
        </section>
      </div>
    );

    const mainView =
      activeView === "workflows"
        ? renderWorkflows()
        : activeView === "teams"
          ? renderTeams()
          : activeView === "approvals"
            ? renderApprovals()
            : activeView === "signals"
              ? renderSignals()
              : activeView === "briefings"
                ? renderBriefings()
              : renderHome();

    return (
      <div className="archon-os">
        <style>{SHELL_CSS}</style>

        <header className="archon-topbar">
          <div className="archon-brand">
            <span className="archon-brand-dot" />
            ARCHON OS
          </div>
          <div className="archon-topbar-meta">
            <div className="archon-connection-pill">
              <span className={`archon-connection-dot ${connectionTone(status, isInitializing, Boolean(sessionId && token))}`} />
              <span>{connectionLabel(status, isInitializing, Boolean(sessionId && token))}</span>
            </div>
            {tauriInvoke ? (
              <div className="archon-connection-pill">
                <span>{desktopStatus || ""}</span>
                {desktopError ? <span className="archon-subtle">{desktopError}</span> : null}
                {desktopNotice ? <span className="archon-subtle">{desktopNotice}</span> : null}
              </div>
            ) : null}
          </div>
          <div className="archon-topbar-actions">
            {tauriInvoke ? (
              <>
                <button
                  type="button"
                  className="archon-button"
                  onClick={handleDesktopStartStop}
                  disabled={desktopBusy}
                >
                  {desktopStatus === "RUNNING" ? "Stop Core" : "Start Core"}
                </button>
                <button
                  type="button"
                  className="archon-button"
                  onClick={handleLaunchArchonEz}
                  disabled={desktopBusy}
                >
                  Launch Archon EZ
                </button>
              </>
            ) : null}
            <button type="button" className="archon-button" onClick={() => setShowDevAuth(true)}>
              Dev Auth
            </button>
          </div>
        </header>

        <div className="archon-shell">
          <aside className="archon-rail">
            <div className="archon-rail-section">
              <div className="archon-rail-title">Spaces</div>
              {[
                { id: "home", label: "Home" },
                { id: "workflows", label: "Workflows" },
                { id: "teams", label: "Teams" },
                { id: "signals", label: "Signals" },
                { id: "briefings", label: "Briefings" },
                { id: "approvals", label: "Approvals" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={activeView === tab.id ? "active" : ""}
                  onClick={() => setActiveView(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="archon-rail-meta">
              <strong>Active Session</strong>
              <div>Session: {sessionId ? clipText(sessionId, 14) : "anonymous"}</div>
              <div>Token: {token ? "active" : "none"}</div>
            </div>
          </aside>
          {mainView}
        </div>

        {showDevAuth ? (
          <div className="archon-modal" role="dialog" aria-modal="true" onClick={() => setShowDevAuth(false)}>
            <div className="archon-modal-card" onClick={(event) => event.stopPropagation()}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div className="archon-subtle">Dev Auth (local)</div>
                  <strong>Bearer Token</strong>
                </div>
                <button type="button" className="archon-button" onClick={() => setShowDevAuth(false)}>
                  Close
                </button>
              </div>
              <p className="archon-subtle">Used only for protected Studio workflows. Stored locally on this device.</p>
              <input
                type="password"
                placeholder="Paste Bearer token"
                value={bearerDraft}
                onChange={(event) => setBearerDraft(event.target.value)}
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  borderRadius: 12,
                  border: `1px solid ${PALETTE.border}`,
                  background: "rgba(7, 9, 13, 0.9)",
                  color: PALETTE.text,
                }}
              />
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {tauriInvoke ? (
                  <button
                    type="button"
                    className="archon-button"
                    onClick={async () => {
                      setDevAuthError("");
                      try {
                        const tokenValue = await tauriInvoke("create_token", {
                          tenant_id: "tenant_local",
                          tier: "free",
                          expires_in: 86400,
                        });
                        setBearerDraft(String(tokenValue || "").trim());
                      } catch (error) {
                        setDevAuthError(String(error?.message || error || "Failed to create token."));
                      }
                    }}
                  >
                    Generate token
                  </button>
                ) : null}
                <button
                  type="button"
                  className="archon-button"
                  onClick={async () => {
                    setDevAuthError("");
                    try {
                      const response = await fetch(`${apiBase}/v1/auth/session-token`, {
                        method: "POST",
                        headers: { "content-type": "application/json" },
                        body: JSON.stringify({}),
                      });
                      if (!response.ok) {
                        throw new Error(`Session token request failed (${response.status})`);
                      }
                      const payload = await response.json();
                      setBearerDraft(String(payload?.token || "").trim());
                    } catch (error) {
                      setDevAuthError(String(error?.message || error || "Failed to request session token."));
                    }
                  }}
                >
                  Auto-issue session token
                </button>
                <button
                  type="button"
                  className="archon-button primary"
                  onClick={() => {
                    setBearerToken(String(bearerDraft || "").trim());
                    setShowDevAuth(false);
                  }}
                  disabled={!String(bearerDraft || "").trim()}
                >
                  Use token
                </button>
                <button
                  type="button"
                  className="archon-button"
                  onClick={() => setBearerToken("")}
                  disabled={!bearerToken}
                >
                  Clear token
                </button>
              </div>
              {devAuthError ? <div className="archon-subtle">{devAuthError}</div> : null}
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  window.App = App;
})();
