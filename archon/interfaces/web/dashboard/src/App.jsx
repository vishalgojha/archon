(() => {
  const { useEffect, useMemo, useRef, useState } = React;

  const COLORS = {
    background: "#0a0a0a",
    surface: "#111111",
    border: "#1a1a1a",
    borderActive: "#333333",
    textPrimary: "#ffffff",
    textSecondary: "#888888",
    textMuted: "#444444",
    amber: "#f59e0b",
    blue: "#3b82f6",
    green: "#16a34a",
    red: "#ef4444",
  };

  const AGENT_LAYOUT = [
    { id: "ProspectorAgent", icon: "search", x: 13, y: 18 },
    { id: "ICPAgent", icon: "target", x: 39, y: 18 },
    { id: "OutreachAgent", icon: "mail", x: 16, y: 52 },
    { id: "NurtureAgent", icon: "repeat", x: 44, y: 52 },
    { id: "RevenueIntelAgent", icon: "chart", x: 66, y: 24 },
    { id: "PartnerAgent", icon: "handshake", x: 71, y: 62 },
    { id: "ChurnDefenseAgent", icon: "shield", x: 86, y: 42 },
  ];

  const AGENT_LINKS = [
    { from: "ProspectorAgent", to: "ICPAgent" },
    { from: "OutreachAgent", to: "NurtureAgent" },
  ];

  const FEED_FALLBACK = [
    {
      id: "feed-1",
      timestamp: "09:14:32",
      agent: "OutreachAgent",
      message: "Draft ready for Rahul Sharma - awaiting approval",
      tone: "amber",
    },
    {
      id: "feed-2",
      timestamp: "09:14:28",
      agent: "ICPAgent",
      message: "Refined ICP: B2B SaaS, 50-200 employees, Mumbai",
      tone: "blue",
    },
    {
      id: "feed-3",
      timestamp: "09:14:21",
      agent: "ProspectorAgent",
      message: "Found 12 new leads matching revised ICP",
      tone: "blue",
    },
    {
      id: "feed-4",
      timestamp: "09:14:15",
      agent: "RevenueIntelAgent",
      message: "Churn risk detected: 2 accounts >60 days silent",
      tone: "blue",
    },
    {
      id: "feed-5",
      timestamp: "09:14:09",
      agent: "ChurnDefenseAgent",
      message: "Failed to load account history - retrying",
      tone: "red",
    },
    {
      id: "feed-6",
      timestamp: "09:13:58",
      agent: "NurtureAgent",
      message: "Scheduled follow-up for 3 warm leads",
      tone: "green",
    },
    {
      id: "feed-7",
      timestamp: "09:13:44",
      agent: "PartnerAgent",
      message: "Identified 4 potential reseller candidates",
      tone: "green",
    },
    {
      id: "feed-8",
      timestamp: "09:13:31",
      agent: "Orchestrator",
      message: "Growth swarm initialised - debate mode active",
      tone: "green",
    },
  ];

  function createWorkflowPayload(workflowId, name, steps) {
    return {
      workflow_id: workflowId,
      name,
      steps: steps.map((step, index) => ({
        step_id: step.step_id || `${workflowId}-step-${index + 1}`,
        agent: step.agent,
        action: step.action,
        config: {
          label: step.title,
          subtitle: step.subtitle,
          node_type: step.node_type || "AgentNode",
          icon: step.icon,
        },
        dependencies: index === 0 ? [] : [steps[index - 1].step_id || `${workflowId}-step-${index}`],
      })),
      metadata: { source: "dashboard" },
      version: 1,
      created_at: Date.now() / 1000,
    };
  }

  const PRESET_WORKFLOWS = [
    {
      id: "preset-weekly-outreach",
      name: "Weekly Outreach Run",
      lastRunText: "today",
      payload: createWorkflowPayload("preset-weekly-outreach", "Weekly Outreach Run", [
        {
          step_id: "find-prospects",
          title: "Find Prospects",
          subtitle: "Target: B2B SaaS Mumbai",
          agent: "ProspectorAgent",
          action: "find_prospects",
          node_type: "AgentNode",
          icon: "search",
        },
        {
          step_id: "refine-icp",
          title: "Refine ICP",
          subtitle: "Based on last 30 days",
          agent: "ICPAgent",
          action: "refine_icp",
          node_type: "AgentNode",
          icon: "target",
        },
        {
          step_id: "draft-outreach",
          title: "Draft Outreach",
          subtitle: "Template: intro_v2",
          agent: "OutreachAgent",
          action: "draft_outreach",
          node_type: "AgentNode",
          icon: "mail",
        },
        {
          step_id: "send-with-approval",
          title: "Send with Approval",
          subtitle: "Daily limit: 20 emails",
          agent: "ApprovalNode",
          action: "send_with_approval",
          node_type: "ApprovalNode",
          icon: "check",
        },
      ]),
    },
    {
      id: "preset-churn-defense",
      name: "Churn Defense Sweep",
      lastRunText: "2 days ago",
      payload: createWorkflowPayload("preset-churn-defense", "Churn Defense Sweep", [
        {
          step_id: "scan-risk",
          title: "Scan Churn Risk",
          subtitle: "Accounts silent > 60 days",
          agent: "RevenueIntelAgent",
          action: "scan_churn_risk",
          node_type: "AgentNode",
          icon: "chart",
        },
        {
          step_id: "load-history",
          title: "Load Account History",
          subtitle: "Recent product and billing signals",
          agent: "ChurnDefenseAgent",
          action: "load_history",
          node_type: "AgentNode",
          icon: "shield",
        },
        {
          step_id: "draft-save-plan",
          title: "Draft Save Plan",
          subtitle: "Channel mix: email + call task",
          agent: "NurtureAgent",
          action: "draft_save_plan",
          node_type: "AgentNode",
          icon: "repeat",
        },
        {
          step_id: "approve-save-plan",
          title: "Approve Outreach",
          subtitle: "Supervisor sign-off required",
          agent: "ApprovalNode",
          action: "approve_save_plan",
          node_type: "ApprovalNode",
          icon: "check",
        },
      ]),
    },
    {
      id: "preset-monday-planning",
      name: "Monday Planning",
      lastRunText: "5 days ago",
      payload: createWorkflowPayload("preset-monday-planning", "Monday Planning", [
        {
          step_id: "review-last-week",
          title: "Review Last Week",
          subtitle: "Top wins and misses",
          agent: "RevenueIntelAgent",
          action: "review_last_week",
          node_type: "AgentNode",
          icon: "chart",
        },
        {
          step_id: "update-icp",
          title: "Update ICP",
          subtitle: "Signals from fresh conversions",
          agent: "ICPAgent",
          action: "update_icp",
          node_type: "AgentNode",
          icon: "target",
        },
        {
          step_id: "plan-outreach",
          title: "Plan Outreach",
          subtitle: "Channels: email, partner, nurture",
          agent: "PartnerAgent",
          action: "plan_channels",
          node_type: "AgentNode",
          icon: "handshake",
        },
        {
          step_id: "final-plan",
          title: "Final Result",
          subtitle: "Operator handoff packet",
          agent: "OutputNode",
          action: "final_plan",
          node_type: "OutputNode",
          icon: "spark",
        },
      ]),
    },
  ];

  const CAPABILITY_GROUPS = [
    {
      id: "pipeline",
      title: "Find the next accounts worth attention",
      summary:
        "Prospect new leads, tighten the ICP, and rank the deals most likely to move now.",
      system:
        "ProspectorAgent, ICPAgent, and RevenueIntelAgent keep lead discovery and prioritization aligned.",
    },
    {
      id: "outreach",
      title: "Draft and queue outreach without losing control",
      summary:
        "Prepare outreach, nurture follow-ups, and hold sensitive sends until a human approves them.",
      system:
        "OutreachAgent and NurtureAgent draft the work. Approval-gated actions pause for operator sign-off.",
    },
    {
      id: "retention",
      title: "Catch churn and partner opportunities early",
      summary:
        "Spot silent accounts, recovery plays, and reseller opportunities before they slip out of view.",
      system:
        "RevenueIntelAgent, ChurnDefenseAgent, and PartnerAgent watch pipeline risk and channel expansion together.",
    },
    {
      id: "workflow",
      title: "Run repeatable workflows instead of babysitting prompts",
      summary:
        "Save recurring plays, launch them from Studio, and watch execution only when you need to intervene.",
      system:
        "Studio stores workflow definitions. Mission Control shows approvals, cost, and the live execution feed on demand.",
    },
  ];

  const SHELL_CSS = `
    .archon-shell {
      height: 100%;
      background: ${COLORS.background};
      color: ${COLORS.textPrimary};
      font-family: system-ui, -apple-system, sans-serif;
      display: flex;
      flex-direction: column;
    }
    .archon-shell * {
      box-sizing: border-box;
    }
    .archon-nav {
      height: 56px;
      border-bottom: 1px solid ${COLORS.border};
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      padding: 0 20px;
      background: rgba(10, 10, 10, 0.98);
      flex-shrink: 0;
    }
    .archon-nav-tabs {
      display: flex;
      gap: 20px;
      height: 100%;
      align-items: flex-end;
    }
    .archon-nav-tab {
      appearance: none;
      border: 0;
      background: transparent;
      color: ${COLORS.textMuted};
      cursor: pointer;
      height: 100%;
      padding: 0 2px;
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-weight: 600;
      border-bottom: 2px solid transparent;
    }
    .archon-nav-tab--active {
      color: ${COLORS.textPrimary};
      border-bottom-color: ${COLORS.textPrimary};
    }
    .archon-nav-meta {
      display: flex;
      align-items: center;
      gap: 10px;
      color: ${COLORS.textSecondary};
      font-size: 12px;
    }
    .archon-live-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #323232;
      flex-shrink: 0;
    }
    .archon-live-dot--live {
      background: ${COLORS.green};
      box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.4);
      animation: archonLivePulse 1.5s infinite ease-out;
    }
    .archon-live-dot--connecting {
      background: ${COLORS.amber};
      box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.32);
      animation: archonLivePulse 1.5s infinite ease-out;
    }
    .archon-live-dot--error {
      background: ${COLORS.red};
      box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.12);
    }
    .archon-live-dot--idle {
      background: #323232;
      box-shadow: none;
    }
    .archon-dashboard {
      min-height: 0;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 16px;
      padding: 18px;
      overflow: auto;
    }
    .archon-briefing {
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(300px, 0.9fr);
      gap: 16px;
      padding: 24px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 22px;
      background:
        radial-gradient(circle at top left, rgba(59, 130, 246, 0.16), transparent 34%),
        radial-gradient(circle at bottom right, rgba(245, 158, 11, 0.12), transparent 36%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.01)),
        ${COLORS.surface};
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
    }
    .archon-briefing-copy {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .archon-briefing-copy h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 42px);
      line-height: 0.98;
      letter-spacing: -0.04em;
      color: ${COLORS.textPrimary};
      max-width: 14ch;
    }
    .archon-briefing-copy p {
      margin: 0;
      max-width: 62ch;
      color: ${COLORS.textSecondary};
      font-size: 14px;
      line-height: 1.65;
    }
    .archon-inline-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      padding-top: 4px;
    }
    .archon-briefing-metrics {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      align-self: stretch;
    }
    .archon-briefing-stat {
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      gap: 8px;
      padding: 16px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .archon-briefing-stat-value {
      font-size: 28px;
      line-height: 1;
      color: ${COLORS.textPrimary};
      font-variant-numeric: tabular-nums;
    }
    .archon-briefing-stat-label {
      color: ${COLORS.textMuted};
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .archon-focus-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .archon-focus-card {
      display: flex;
      flex-direction: column;
      gap: 16px;
      padding: 20px;
      border-radius: 20px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(17, 17, 17, 0.92);
    }
    .archon-focus-title {
      color: ${COLORS.textPrimary};
      font-size: 20px;
      line-height: 1.1;
      font-weight: 600;
    }
    .archon-focus-copy {
      color: ${COLORS.textSecondary};
      font-size: 13px;
      line-height: 1.6;
    }
    .archon-action-list {
      display: grid;
      gap: 12px;
    }
    .archon-action-card {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.025);
      border: 1px solid rgba(255, 255, 255, 0.04);
    }
    .archon-action-copy {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }
    .archon-action-title {
      color: ${COLORS.textPrimary};
      font-size: 15px;
      font-weight: 600;
      line-height: 1.35;
    }
    .archon-action-body {
      color: ${COLORS.textSecondary};
      font-size: 12px;
      line-height: 1.55;
    }
    .archon-capability-list {
      display: grid;
      gap: 10px;
    }
    .archon-capability-card {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.025);
      border: 1px solid rgba(255, 255, 255, 0.04);
    }
    .archon-capability-title {
      color: ${COLORS.textPrimary};
      font-size: 15px;
      font-weight: 600;
      line-height: 1.35;
    }
    .archon-capability-copy {
      color: ${COLORS.textSecondary};
      font-size: 12px;
      line-height: 1.55;
    }
    .archon-capability-meta {
      color: ${COLORS.textMuted};
      font-size: 11px;
      line-height: 1.55;
    }
    .archon-capability-details {
      display: grid;
      gap: 10px;
      padding-top: 2px;
    }
    .archon-capability-detail {
      padding-top: 10px;
      border-top: 1px solid rgba(255, 255, 255, 0.05);
    }
    .archon-capability-detail strong {
      display: block;
      color: ${COLORS.textPrimary};
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    .archon-capability-detail p {
      margin: 0;
      color: ${COLORS.textSecondary};
      font-size: 12px;
      line-height: 1.6;
    }
    .archon-priority-panel {
      display: flex;
      flex-direction: column;
      gap: 14px;
      padding: 20px;
      border-radius: 20px;
      border: 1px solid rgba(245, 158, 11, 0.18);
      background: rgba(245, 158, 11, 0.05);
    }
    .archon-priority-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
    }
    .archon-reveal-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 20px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      background: rgba(255, 255, 255, 0.02);
    }
    .archon-reveal-title {
      color: ${COLORS.textPrimary};
      font-size: 18px;
      font-weight: 600;
      line-height: 1.15;
      margin-top: 4px;
    }
    .archon-reveal-copy {
      color: ${COLORS.textSecondary};
      font-size: 13px;
      line-height: 1.55;
      margin-top: 8px;
      max-width: 62ch;
    }
    .archon-system-placeholder {
      display: grid;
      gap: 8px;
      padding: 20px;
      border-radius: 18px;
      border: 1px dashed rgba(255, 255, 255, 0.08);
      color: ${COLORS.textSecondary};
      font-size: 13px;
      line-height: 1.6;
      background: rgba(255, 255, 255, 0.015);
    }
    .archon-system-shell {
      min-height: 0;
      display: grid;
      grid-template-rows: minmax(520px, 1fr) minmax(180px, 26vh);
      border-radius: 20px;
      overflow: hidden;
      border: 1px solid ${COLORS.border};
      background: #0d0d0d;
    }
    .archon-dashboard-main {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 65fr) minmax(340px, 35fr);
      background: ${COLORS.background};
    }
    .archon-canvas-panel {
      min-height: 0;
      padding: 18px;
      border-right: 1px solid ${COLORS.border};
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .archon-panel-label {
      color: ${COLORS.textMuted};
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      flex-shrink: 0;
    }
    .archon-canvas {
      position: relative;
      min-height: 0;
      flex: 1;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 18px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0)),
        radial-gradient(circle at top left, rgba(59, 130, 246, 0.12), transparent 32%),
        radial-gradient(circle at bottom right, rgba(245, 158, 11, 0.12), transparent 30%),
        radial-gradient(circle at center, rgba(255, 255, 255, 0.03), transparent 48%),
        ${COLORS.background};
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.03),
        inset 0 -80px 120px rgba(0, 0, 0, 0.35);
      overflow: hidden;
    }
    .archon-canvas::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px),
        linear-gradient(rgba(255, 255, 255, 0.018) 1px, transparent 1px);
      background-size: 72px 72px;
      opacity: 0.24;
      pointer-events: none;
    }
    .archon-canvas::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 22% 18%, rgba(59, 130, 246, 0.08), transparent 18%),
        radial-gradient(circle at 72% 70%, rgba(245, 158, 11, 0.07), transparent 22%);
      pointer-events: none;
    }
    .archon-canvas svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }
    .archon-link {
      fill: none;
      stroke: rgba(148, 163, 184, 0.34);
      stroke-width: 1.35;
      stroke-dasharray: 8 7;
      opacity: 1;
    }
    .archon-link--active {
      stroke: rgba(245, 158, 11, 0.56);
      stroke-width: 1.55;
      animation: archonDash 6s linear infinite;
      filter: drop-shadow(0 0 8px rgba(245, 158, 11, 0.18));
    }
    .archon-agent-node {
      position: absolute;
      width: 160px;
      min-height: 80px;
      border-radius: 16px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.035), rgba(255, 255, 255, 0.012)),
        ${COLORS.surface};
      border: 1px solid rgba(255, 255, 255, 0.06);
      padding: 14px 14px 12px;
      cursor: pointer;
      transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease, opacity 160ms ease;
      text-align: left;
      color: ${COLORS.textPrimary};
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }
    .archon-agent-node:hover {
      transform: translateY(-2px);
      border-color: ${COLORS.borderActive};
    }
    .archon-agent-node--idle {
      border-color: ${COLORS.border};
    }
    .archon-agent-node--thinking {
      border-color: ${COLORS.amber};
      animation: archonGlowAmber 1.8s ease-in-out infinite;
    }
    .archon-agent-node--running {
      border-color: ${COLORS.blue};
      box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.2), 0 0 22px rgba(59, 130, 246, 0.16);
    }
    .archon-agent-node--waiting_approval {
      border: 2px solid ${COLORS.amber};
      background: rgba(245, 158, 11, 0.09);
    }
    .archon-agent-node--failed {
      border-color: ${COLORS.red};
      background: rgba(239, 68, 68, 0.08);
    }
    .archon-agent-topline {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .archon-agent-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      opacity: 0.68;
      flex-shrink: 0;
    }
    .archon-agent-node:hover .archon-agent-icon {
      opacity: 0.88;
    }
    .archon-agent-title {
      font-size: 14px;
      font-weight: 600;
      color: ${COLORS.textPrimary};
      line-height: 1.2;
    }
    .archon-status-pill {
      display: inline-flex;
      align-items: center;
      margin-top: 10px;
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      border: 1px solid ${COLORS.border};
      color: ${COLORS.textMuted};
      background: rgba(255, 255, 255, 0.02);
    }
    .archon-status-pill--thinking {
      color: ${COLORS.amber};
      border-color: rgba(245, 158, 11, 0.4);
    }
    .archon-status-pill--running {
      color: ${COLORS.blue};
      border-color: rgba(59, 130, 246, 0.45);
    }
    .archon-status-pill--waiting_approval {
      color: ${COLORS.amber};
      border-color: rgba(245, 158, 11, 0.45);
    }
    .archon-status-pill--failed {
      color: ${COLORS.red};
      border-color: rgba(239, 68, 68, 0.45);
    }
    .archon-status-badge {
      position: absolute;
      right: 10px;
      top: 10px;
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 9px;
      line-height: 1;
      letter-spacing: 0.12em;
      font-weight: 700;
      text-transform: uppercase;
    }
    .archon-status-badge--warning {
      background: rgba(245, 158, 11, 0.14);
      color: ${COLORS.amber};
      border: 1px solid rgba(245, 158, 11, 0.35);
    }
    .archon-status-badge--danger {
      background: rgba(239, 68, 68, 0.14);
      color: ${COLORS.red};
      border: 1px solid rgba(239, 68, 68, 0.35);
    }
    .archon-tooltip {
      position: absolute;
      width: 220px;
      border-radius: 12px;
      background: rgba(17, 17, 17, 0.96);
      border: 1px solid ${COLORS.borderActive};
      padding: 12px;
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.45);
      z-index: 4;
    }
    .archon-tooltip-label {
      color: ${COLORS.textMuted};
      font-size: 10px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    .archon-tooltip-text {
      color: ${COLORS.textSecondary};
      font-size: 12px;
      line-height: 1.45;
    }
    .archon-sidebar {
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      background: ${COLORS.background};
    }
    .archon-stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      border-bottom: 1px solid ${COLORS.border};
      min-height: 110px;
    }
    .archon-stat {
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 8px;
    }
    .archon-stat + .archon-stat {
      border-left: 1px solid ${COLORS.border};
    }
    .archon-stat-value {
      font-size: 28px;
      line-height: 1;
      color: ${COLORS.textPrimary};
      font-variant-numeric: tabular-nums;
    }
    .archon-stat-label {
      color: #555555;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .archon-approvals {
      min-height: 0;
      overflow: auto;
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .archon-approvals-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      color: #555555;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      flex-shrink: 0;
    }
    .archon-count-badge {
      min-width: 22px;
      height: 22px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: rgba(245, 158, 11, 0.14);
      color: ${COLORS.amber};
      border: 1px solid rgba(245, 158, 11, 0.3);
      font-size: 11px;
      font-weight: 700;
    }
    .archon-approval-card {
      background: ${COLORS.surface};
      border-left: 3px solid ${COLORS.amber};
      border-radius: 14px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      transition: transform 160ms ease, opacity 180ms ease, box-shadow 160ms ease;
    }
    .archon-approval-card:hover {
      transform: translateY(-1px);
      box-shadow: 0 18px 28px rgba(0, 0, 0, 0.22);
    }
    .archon-approval-card--exiting {
      opacity: 0;
      transform: translateY(-8px);
      pointer-events: none;
    }
    .archon-approval-agent {
      color: ${COLORS.textSecondary};
      font-size: 11px;
    }
    .archon-approval-title {
      color: ${COLORS.textPrimary};
      font-size: 14px;
      font-weight: 600;
      line-height: 1.35;
    }
    .archon-approval-preview {
      color: #666666;
      font-size: 12px;
      line-height: 1.5;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      min-height: 36px;
    }
    .archon-approval-actions {
      display: flex;
      gap: 10px;
      margin-top: 2px;
    }
    .archon-button {
      appearance: none;
      border-radius: 10px;
      height: 32px;
      padding: 0 14px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      cursor: pointer;
      transition: background 160ms ease, border-color 160ms ease, color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
      border: 1px solid ${COLORS.border};
      background: ${COLORS.border};
      color: ${COLORS.textSecondary};
    }
    .archon-button:hover {
      transform: translateY(-1px);
    }
    .archon-button--approve {
      background: ${COLORS.green};
      border-color: ${COLORS.green};
      color: ${COLORS.textPrimary};
    }
    .archon-button--approve:hover {
      box-shadow: 0 0 0 1px rgba(22, 163, 74, 0.24), 0 0 18px rgba(22, 163, 74, 0.24);
    }
    .archon-button--deny {
      background: ${COLORS.border};
      border-color: ${COLORS.borderActive};
      color: #666666;
    }
    .archon-empty {
      color: ${COLORS.textMuted};
      font-size: 13px;
      line-height: 1.5;
      padding: 12px 4px;
    }
    .archon-clear-card {
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 16px;
      padding: 16px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0)),
        rgba(255, 255, 255, 0.01);
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .archon-clear-kicker {
      color: ${COLORS.green};
      font-size: 10px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      font-weight: 700;
    }
    .archon-clear-title {
      color: ${COLORS.textPrimary};
      font-size: 16px;
      font-weight: 600;
      line-height: 1.2;
    }
    .archon-clear-copy {
      color: ${COLORS.textSecondary};
      font-size: 13px;
      line-height: 1.55;
    }
    .archon-clear-meta {
      display: grid;
      gap: 8px;
      padding-top: 6px;
      border-top: 1px solid rgba(255, 255, 255, 0.04);
    }
    .archon-clear-meta span {
      color: #666666;
      font-size: 12px;
      line-height: 1.45;
    }
    .archon-feed {
      min-height: 0;
      background: #0d0d0d;
      border-top: 1px solid ${COLORS.border};
      display: flex;
      flex-direction: column;
    }
    .archon-feed-header {
      padding: 10px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid ${COLORS.border};
      flex-shrink: 0;
    }
    .archon-feed-title {
      color: #555555;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .archon-feed-live {
      display: flex;
      align-items: center;
      gap: 8px;
      color: ${COLORS.green};
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .archon-feed-list {
      min-height: 0;
      overflow-y: auto;
      padding: 8px 18px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .archon-feed-item {
      display: grid;
      grid-template-columns: 82px 140px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      font-size: 12px;
    }
    .archon-feed-time {
      color: #333333;
      font-size: 11px;
      font-family: ui-monospace, monospace;
      white-space: nowrap;
    }
    .archon-feed-agent {
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
    }
    .archon-feed-agent--amber {
      color: ${COLORS.amber};
    }
    .archon-feed-agent--blue {
      color: ${COLORS.blue};
    }
    .archon-feed-agent--green {
      color: ${COLORS.green};
    }
    .archon-feed-agent--red {
      color: ${COLORS.red};
    }
    .archon-feed-message {
      color: ${COLORS.textSecondary};
      line-height: 1.45;
    }
    .archon-studio {
      min-height: 0;
      flex: 1;
      display: grid;
      grid-template-columns: 240px minmax(0, 1fr);
    }
    .archon-studio-sidebar {
      border-right: 1px solid ${COLORS.border};
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      background: rgba(10, 10, 10, 0.92);
    }
    .archon-workflow-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .archon-workflow-item {
      appearance: none;
      width: 100%;
      text-align: left;
      border: 1px solid transparent;
      border-left: 3px solid transparent;
      background: transparent;
      border-radius: 12px;
      color: ${COLORS.textPrimary};
      padding: 12px 12px 12px 14px;
      cursor: pointer;
      transition: background 160ms ease, border-color 160ms ease, transform 160ms ease;
    }
    .archon-workflow-item:hover {
      background: rgba(255, 255, 255, 0.02);
      border-color: ${COLORS.border};
      transform: translateY(-1px);
    }
    .archon-workflow-item--active {
      background: ${COLORS.surface};
      border-color: ${COLORS.border};
      border-left-color: ${COLORS.amber};
    }
    .archon-workflow-name {
      color: ${COLORS.textPrimary};
      font-size: 13px;
      font-weight: 500;
      line-height: 1.35;
    }
    .archon-workflow-meta {
      color: #555555;
      font-size: 11px;
      margin-top: 6px;
    }
    .archon-studio-main {
      min-height: 0;
      padding: 22px 24px 26px;
      display: flex;
      flex-direction: column;
      gap: 22px;
    }
    .archon-studio-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      flex-wrap: wrap;
    }
    .archon-studio-title {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .archon-studio-title h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 600;
      color: ${COLORS.textPrimary};
    }
    .archon-studio-title p {
      margin: 0;
      color: ${COLORS.textSecondary};
      font-size: 12px;
      line-height: 1.5;
    }
    .archon-studio-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .archon-button--muted {
      background: ${COLORS.border};
      border-color: ${COLORS.borderActive};
      color: #666666;
    }
    .archon-button--run {
      background: ${COLORS.amber};
      border-color: ${COLORS.amber};
      color: #000000;
    }
    .archon-button--run:hover {
      box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.26), 0 0 18px rgba(245, 158, 11, 0.26);
    }
    .archon-studio-status {
      color: ${COLORS.textSecondary};
      font-size: 12px;
      line-height: 1.45;
      min-height: 18px;
    }
    .archon-flow {
      min-height: 0;
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 14px;
      overflow: auto;
      padding: 10px 0;
    }
    .archon-flow-card {
      width: min(100%, 360px);
      background: ${COLORS.surface};
      border: 1px solid #222222;
      border-radius: 12px;
      padding: 16px 18px;
      transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
    }
    .archon-flow-card:hover {
      border-color: ${COLORS.borderActive};
      transform: translateY(-2px);
      box-shadow: 0 18px 32px rgba(0, 0, 0, 0.2);
    }
    .archon-flow-topline {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .archon-flow-title {
      color: ${COLORS.textPrimary};
      font-size: 14px;
      font-weight: 600;
      line-height: 1.3;
    }
    .archon-flow-subtitle {
      margin-top: 8px;
      color: #555555;
      font-size: 12px;
      line-height: 1.45;
    }
    .archon-flow-arrow {
      color: ${COLORS.textMuted};
      font-size: 20px;
      line-height: 1;
      user-select: none;
    }
    @keyframes archonDash {
      from { stroke-dashoffset: 0; }
      to { stroke-dashoffset: -32; }
    }
    @keyframes archonGlowAmber {
      0%, 100% { box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.12), 0 0 0 rgba(245, 158, 11, 0); }
      50% { box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.24), 0 0 20px rgba(245, 158, 11, 0.18); }
    }
    @keyframes archonLivePulse {
      0% { box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.4); }
      100% { box-shadow: 0 0 0 8px rgba(22, 163, 74, 0); }
    }
    @media (max-width: 1180px) {
      .archon-briefing,
      .archon-focus-grid {
        grid-template-columns: 1fr;
      }
      .archon-reveal-bar {
        align-items: flex-start;
        flex-direction: column;
      }
      .archon-dashboard-main {
        grid-template-columns: 1fr;
      }
      .archon-canvas-panel {
        border-right: 0;
        border-bottom: 1px solid ${COLORS.border};
      }
      .archon-studio {
        grid-template-columns: 1fr;
      }
      .archon-studio-sidebar {
        border-right: 0;
        border-bottom: 1px solid ${COLORS.border};
      }
    }
    @media (max-width: 760px) {
      .archon-dashboard {
        padding: 14px;
      }
      .archon-briefing {
        padding: 18px;
      }
      .archon-briefing-copy h1 {
        max-width: none;
      }
      .archon-briefing-metrics,
      .archon-priority-grid {
        grid-template-columns: 1fr;
      }
      .archon-action-card,
      .archon-reveal-bar {
        align-items: flex-start;
        flex-direction: column;
      }
      .archon-system-shell {
        grid-template-rows: minmax(420px, 1fr) minmax(180px, 30vh);
      }
      .archon-feed-item {
        grid-template-columns: 72px 120px minmax(0, 1fr);
        gap: 8px;
      }
      .archon-stats {
        grid-template-columns: 1fr;
      }
      .archon-stat + .archon-stat {
        border-left: 0;
        border-top: 1px solid ${COLORS.border};
      }
      .archon-nav {
        padding: 0 14px;
      }
      .archon-canvas-panel,
      .archon-sidebar,
      .archon-studio-main,
      .archon-studio-sidebar {
        padding-left: 14px;
        padding-right: 14px;
      }
    }
  `;

  function resolveApiBase() {
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      return window.location.origin.replace(/\/$/, "");
    }
    try {
      const stored = String(localStorage.getItem("archon.api_base") || "").trim();
      if (stored) {
        return stored.replace(/\/$/, "");
      }
    } catch (_error) {
      return "http://127.0.0.1:8000";
    }
    return "http://127.0.0.1:8000";
  }

  function resolveWsBase(apiBase) {
    if (String(apiBase).startsWith("https://")) {
      return `wss://${String(apiBase).slice("https://".length)}`;
    }
    if (String(apiBase).startsWith("http://")) {
      return `ws://${String(apiBase).slice("http://".length)}`;
    }
    return apiBase;
  }

  function buildHeaders(token, includeJson = false) {
    const headers = {};
    if (includeJson) {
      headers["Content-Type"] = "application/json";
    }
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  function normalizeWords(value) {
    return String(value || "")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function titleCase(value) {
    const text = normalizeWords(value);
    if (!text) {
      return "";
    }
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function clipText(value, maxLength) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    if (text.length <= maxLength) {
      return text;
    }
    return `${text.slice(0, maxLength)}...`;
  }

  function shortJson(value, maxLength = 160) {
    try {
      return clipText(typeof value === "string" ? value : JSON.stringify(value || {}), maxLength);
    } catch (_error) {
      return clipText(String(value || ""), maxLength);
    }
  }

  function firstText(values) {
    for (let idx = 0; idx < values.length; idx += 1) {
      const value = values[idx];
      if (typeof value === "string" && value.trim()) {
        return value.trim();
      }
      if (value && typeof value === "object") {
        const preview = shortJson(value, 180);
        if (preview) {
          return preview;
        }
      }
    }
    return "";
  }

  function eventTimestampSeconds(event) {
    if (!event || typeof event !== "object") {
      return 0;
    }
    const numeric = Number(event.ts || event.timestamp || event.created_at || 0);
    if (Number.isFinite(numeric) && numeric > 0) {
      return numeric > 10_000_000_000 ? numeric / 1000 : numeric;
    }
    const text = String(event.created_at || event.timestamp || "").trim();
    if (!text) {
      return 0;
    }
    const parsed = Date.parse(text);
    return Number.isNaN(parsed) ? 0 : parsed / 1000;
  }

  function formatClock(value) {
    if (typeof value === "string" && /^\d{2}:\d{2}:\d{2}$/.test(value.trim())) {
      return value.trim();
    }
    const numeric = typeof value === "number" ? value : Date.parse(String(value || ""));
    if (!numeric || Number.isNaN(numeric)) {
      const now = new Date();
      return now.toLocaleTimeString("en-GB", { hour12: false });
    }
    return new Date(numeric * (numeric < 10_000_000_000 ? 1000 : 1)).toLocaleTimeString("en-GB", {
      hour12: false,
    });
  }

  function formatRelativeDay(seconds) {
    const numeric = typeof seconds === "number" ? seconds : Number(seconds || 0);
    const resolved =
      Number.isFinite(numeric) && numeric > 0
        ? numeric > 10_000_000_000
          ? numeric / 1000
          : numeric
        : Date.parse(String(seconds || "")) / 1000;
    if (!Number.isFinite(resolved) || resolved <= 0) {
      return "today";
    }
    const diffDays = Math.floor((Date.now() / 1000 - resolved) / 86400);
    if (diffDays <= 0) {
      return "today";
    }
    if (diffDays === 1) {
      return "1 day ago";
    }
    return `${diffDays} days ago`;
  }

  function formatCost(value) {
    const numeric = Number(value || 0);
    return `$ ${numeric.toFixed(2)}`;
  }

  function approvalPreview(item) {
    const context = item && typeof item.context === "object" ? item.context : {};
    const payload = item && typeof item.payload === "object" ? item.payload : {};
    return clipText(
      firstText([
        context.preview,
        context.message,
        context.content,
        context.output_text,
        payload.preview,
        payload.message,
        payload.content,
        payload.output_text,
        payload.url ? `Target: ${payload.url}` : "",
        context.url ? `Target: ${context.url}` : "",
      ]) || "This action is waiting for a human decision.",
      140,
    );
  }

  function findAgentNameFromText(value) {
    const haystack = String(value || "");
    for (let idx = 0; idx < AGENT_LAYOUT.length; idx += 1) {
      if (haystack.includes(AGENT_LAYOUT[idx].id)) {
        return AGENT_LAYOUT[idx].id;
      }
    }
    return "";
  }

  function approvalAgentName(item) {
    const context = item && typeof item.context === "object" ? item.context : {};
    const payload = item && typeof item.payload === "object" ? item.payload : {};
    const direct = [
      item?.agent,
      item?.agent_name,
      context.agent,
      context.agent_name,
      payload.agent,
      payload.agent_name,
    ]
      .map((value) => String(value || "").trim())
      .find(Boolean);
    if (direct) {
      return direct;
    }
    return (
      findAgentNameFromText(item?.action) ||
      findAgentNameFromText(item?.action_type) ||
      findAgentNameFromText(JSON.stringify(context || {})) ||
      findAgentNameFromText(JSON.stringify(payload || {})) ||
      "Orchestrator"
    );
  }

  function approvalTitle(item) {
    const preview = approvalPreview(item);
    const action = normalizeWords(item?.action || item?.action_type || "");
    if (/email|mail|reply|outreach|message/i.test(action) || /email|reply|follow up/i.test(preview)) {
      const recipient = firstText([
        item?.context?.recipient_name,
        item?.payload?.recipient_name,
        item?.context?.lead_name,
        item?.payload?.lead_name,
      ]);
      return recipient ? `Send email to ${recipient}` : "Send outbound message";
    }
    if (/publish|post|content|release/i.test(action)) {
      return "Publish prepared content";
    }
    if (/approval/i.test(action)) {
      return "Approve next workflow step";
    }
    return titleCase(action || "Review pending action");
  }

  function prettyStatus(status) {
    if (status === "waiting_approval") {
      return "Waiting";
    }
    return titleCase(status || "idle");
  }

  function connectionTone(status, isInitializing, hasSession) {
    if (isInitializing) {
      return "connecting";
    }
    const normalized = String(status || "").toLowerCase();
    if (normalized === "connected") {
      return "live";
    }
    if (normalized === "connecting") {
      return "connecting";
    }
    if (normalized === "error") {
      return "error";
    }
    if (normalized === "disconnected" && hasSession) {
      return "connecting";
    }
    return "idle";
  }

  function connectionLabel(status, isInitializing, hasSession) {
    if (isInitializing) {
      return "Starting session";
    }
    const normalized = String(status || "").toLowerCase();
    if (normalized === "connected") {
      return "Live session";
    }
    if (normalized === "connecting") {
      return "Connecting";
    }
    if (normalized === "error") {
      return "Connection error";
    }
    if (normalized === "disconnected" && hasSession) {
      return "Reconnecting";
    }
    return "Session unavailable";
  }

  function feedTone(agent, message) {
    const source = `${agent} ${message}`.toLowerCase();
    if (/failed|error|retry/.test(source)) {
      return "red";
    }
    if (/outreach|approval|email|reply/.test(source)) {
      return "amber";
    }
    if (/prospector|icp|revenue|research/.test(source)) {
      return "blue";
    }
    return "green";
  }

  function historyEventMessage(event) {
    const type = String(event?.type || "").toLowerCase();
    if (type === "approval_required") {
      return `${approvalTitle(event)} - awaiting approval`;
    }
    if (type === "agent_start" || type === "step_started") {
      return firstText([
        event?.message,
        event?.summary,
        event?.action ? `${titleCase(event.action)} started` : "",
      ]) || "Started work";
    }
    if (type === "agent_end" || type === "growth_agent_completed" || type === "step_completed") {
      return firstText([event?.summary, event?.output_text, event?.message, event?.result]) || "Completed step";
    }
    if (type === "task_result" || type === "workflow_completed") {
      return firstText([event?.final_answer, event?.message, event?.payload]) || "Completed run";
    }
    if (type === "error" || type === "workflow_failed") {
      return firstText([event?.message, event?.detail, event?.payload]) || "Run failed";
    }
    return firstText([event?.message, event?.detail, event?.payload, event?.result]) || shortJson(event, 140);
  }

  function historyEventToFeedItem(event, index) {
    const agent = String(event?.agent || event?.agent_name || event?.role || "Orchestrator").trim() || "Orchestrator";
    return {
      id: `history-${index}-${String(event?.type || "event")}`,
      timestamp: formatClock(eventTimestampSeconds(event)),
      agent,
      message: historyEventMessage(event),
      tone: feedTone(agent, historyEventMessage(event)),
    };
  }

  function studioFrameToFeedItem(frame, workflowName) {
    const type = String(frame?.type || "").toLowerCase();
    if (!type) {
      return null;
    }
    if (type === "workflow_started") {
      return {
        id: `studio-${Date.now()}-started`,
        timestamp: formatClock(Date.now()),
        agent: "Orchestrator",
        message: `${workflowName} started`,
        tone: "green",
      };
    }
    if (type === "step_started") {
      return {
        id: `studio-${Date.now()}-${frame.step_id || "step-started"}`,
        timestamp: formatClock(Date.now()),
        agent: String(frame.agent || "Orchestrator"),
        message: `${titleCase(frame.action || frame.step_id || "step")} started`,
        tone: feedTone(String(frame.agent || "Orchestrator"), String(frame.action || "")),
      };
    }
    if (type === "step_completed") {
      return {
        id: `studio-${Date.now()}-${frame.step_id || "step-completed"}`,
        timestamp: formatClock(Date.now()),
        agent: String(frame.agent || "Orchestrator"),
        message: firstText([frame.summary, frame.output_text]) || "Step completed",
        tone: feedTone(String(frame.agent || "Orchestrator"), firstText([frame.summary, frame.output_text])),
      };
    }
    if (type === "workflow_completed") {
      return {
        id: `studio-${Date.now()}-completed`,
        timestamp: formatClock(Date.now()),
        agent: "Orchestrator",
        message: firstText([frame.final_answer]) || `${workflowName} completed`,
        tone: "green",
      };
    }
    if (type === "workflow_failed" || type === "error") {
      return {
        id: `studio-${Date.now()}-failed`,
        timestamp: formatClock(Date.now()),
        agent: "Orchestrator",
        message: firstText([frame.message, frame.detail]) || `${workflowName} failed`,
        tone: "red",
      };
    }
    return null;
  }

  function workflowBlocksFromPayload(payload) {
    const steps = Array.isArray(payload?.steps) ? payload.steps : [];
    return steps.map((step, index) => {
      const config = step && typeof step.config === "object" ? step.config : {};
      return {
        id: step?.step_id || `block-${index + 1}`,
        title: firstText([config.label, titleCase(step?.action), titleCase(step?.agent)]) || `Step ${index + 1}`,
        subtitle:
          firstText([
            config.subtitle,
            config.description,
            config.goal,
            config.result_format,
            config.approval_question,
            config.instructions,
          ]) || "No additional details",
        icon: String(config.icon || inferIconForStep(step)),
      };
    });
  }

  function inferIconForStep(step) {
    const haystack = `${step?.agent || ""} ${step?.action || ""} ${(step?.config && JSON.stringify(step.config)) || ""}`.toLowerCase();
    if (/prospect|research|find/.test(haystack)) {
      return "search";
    }
    if (/icp|target|refine/.test(haystack)) {
      return "target";
    }
    if (/mail|email|reply|outreach|draft/.test(haystack)) {
      return "mail";
    }
    if (/approval|approve/.test(haystack)) {
      return "check";
    }
    if (/revenue|plan|chart/.test(haystack)) {
      return "chart";
    }
    if (/partner/.test(haystack)) {
      return "handshake";
    }
    if (/shield|churn/.test(haystack)) {
      return "shield";
    }
    return "spark";
  }

  function Icon({ name, color, size = 14 }) {
    const props = {
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: color,
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round",
    };

    if (name === "search") {
      return (
        <svg {...props}>
          <circle cx="11" cy="11" r="6" />
          <path d="M20 20l-4.2-4.2" />
        </svg>
      );
    }
    if (name === "target") {
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="7" />
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
        </svg>
      );
    }
    if (name === "mail") {
      return (
        <svg {...props}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M4 7l8 6 8-6" />
        </svg>
      );
    }
    if (name === "repeat") {
      return (
        <svg {...props}>
          <path d="M17 2l3 3-3 3" />
          <path d="M4 11V9a4 4 0 0 1 4-4h12" />
          <path d="M7 22l-3-3 3-3" />
          <path d="M20 13v2a4 4 0 0 1-4 4H4" />
        </svg>
      );
    }
    if (name === "chart") {
      return (
        <svg {...props}>
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
        <svg {...props}>
          <path d="M4 12l4-4 3 2 3-2 6 6" />
          <path d="M4 12l4 4" />
          <path d="M20 14l-3 3a2 2 0 0 1-3 0l-2-2" />
          <path d="M10 14l2 2" />
        </svg>
      );
    }
    if (name === "shield") {
      return (
        <svg {...props}>
          <path d="M12 3l7 3v6c0 5-3.5 8.5-7 9-3.5-.5-7-4-7-9V6l7-3z" />
        </svg>
      );
    }
    if (name === "check") {
      return (
        <svg {...props}>
          <path d="M4 12l5 5 11-11" />
        </svg>
      );
    }
    return (
      <svg {...props}>
        <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" />
      </svg>
    );
  }

  function App() {
    const archon = window.useARCHONContext ? window.useARCHONContext() : {};
    const token = String(archon?.token || "").trim();
    const sessionId = String(archon?.sessionId || "").trim();
    const status = String(archon?.status || "disconnected");
    const isInitializing = Boolean(archon?.isInitializing);
    const history = Array.isArray(archon?.history) ? archon.history : [];
    const pendingApprovals = Array.isArray(archon?.pendingApprovals) ? archon.pendingApprovals : [];
    const agentStates = archon?.agentStates || {};
    const costState = archon?.costState || { spent: 0, budget: 0, history: [] };
    const send = typeof archon?.send === "function" ? archon.send : () => {};

    const [activeTab, setActiveTab] = useState("dashboard");
    const [openTooltipAgent, setOpenTooltipAgent] = useState("");
    const [showCapabilityDetails, setShowCapabilityDetails] = useState(false);
    const [showSystemView, setShowSystemView] = useState(false);
    const [hiddenApprovals, setHiddenApprovals] = useState({});
    const [fadingApprovals, setFadingApprovals] = useState({});
    const [approvedCount, setApprovedCount] = useState(0);
    const [localFeedItems, setLocalFeedItems] = useState([]);
    const [workflowEntries, setWorkflowEntries] = useState(
      PRESET_WORKFLOWS.map((item) => ({
        id: item.id,
        name: item.name,
        lastRunText: item.lastRunText,
        source: "preset",
      })),
    );
    const [workflowPayloads, setWorkflowPayloads] = useState(() =>
      Object.fromEntries(PRESET_WORKFLOWS.map((item) => [item.id, item.payload])),
    );
    const [activeWorkflowId, setActiveWorkflowId] = useState(PRESET_WORKFLOWS[0].id);
    const [studioNotice, setStudioNotice] = useState("");
    const [studioBusy, setStudioBusy] = useState(false);
    const apiBase = useMemo(() => resolveApiBase(), []);
    const studioSocketRef = useRef(null);

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
      setOpenTooltipAgent("");
    }, [activeTab]);

    useEffect(() => {
      const liveIds = new Set(
        pendingApprovals
          .map((item) => String(item?.request_id || item?.action_id || "").trim())
          .filter(Boolean),
      );
      setHiddenApprovals((current) => {
        const next = {};
        Object.keys(current).forEach((id) => {
          if (liveIds.has(id)) {
            next[id] = current[id];
          }
        });
        return next;
      });
      setFadingApprovals((current) => {
        const next = {};
        Object.keys(current).forEach((id) => {
          if (liveIds.has(id)) {
            next[id] = current[id];
          }
        });
        return next;
      });
    }, [pendingApprovals]);

    useEffect(() => {
      if (!token) {
        return undefined;
      }
      let cancelled = false;

      fetch(`${apiBase}/studio/workflows`, {
        headers: buildHeaders(token),
      })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(`Workflow list request failed (${response.status})`);
          }
          return response.json();
        })
        .then((rows) => {
          if (cancelled || !Array.isArray(rows) || !rows.length) {
            return;
          }
          const nextEntries = rows.slice(0, 3).map((row) => ({
            id: String(row.id || row.workflow_id || ""),
            name: String(row.name || "Untitled workflow"),
            lastRunText: formatRelativeDay(row.updated_at),
            source: "api",
          }));
          if (!nextEntries.length) {
            return;
          }
          setWorkflowEntries(nextEntries);
          setActiveWorkflowId((current) =>
            nextEntries.some((item) => item.id === current) ? current : nextEntries[0].id,
          );
        })
        .catch((_error) => {
          if (!cancelled) {
            setStudioNotice("Studio API unavailable - showing built-in workflows.");
          }
        });

      return () => {
        cancelled = true;
      };
    }, [apiBase, token]);

    const activeWorkflowEntry = useMemo(() => {
      return workflowEntries.find((item) => item.id === activeWorkflowId) || workflowEntries[0] || null;
    }, [activeWorkflowId, workflowEntries]);

    useEffect(() => {
      if (!token || !activeWorkflowEntry || activeWorkflowEntry.source !== "api") {
        return undefined;
      }
      if (workflowPayloads[activeWorkflowEntry.id]) {
        return undefined;
      }

      let cancelled = false;
      fetch(`${apiBase}/studio/workflows/${encodeURIComponent(activeWorkflowEntry.id)}`, {
        headers: buildHeaders(token),
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
    }, [activeWorkflowEntry, apiBase, token, workflowPayloads]);

    const agentNodes = useMemo(() => {
      const latestEvents = {};
      for (let idx = history.length - 1; idx >= 0; idx -= 1) {
        const event = history[idx] || {};
        const agentName = String(event.agent || event.agent_name || "").trim();
        if (agentName && !latestEvents[agentName]) {
          latestEvents[agentName] = event;
        }
      }

      return AGENT_LAYOUT.map((agent) => {
        const approval = pendingApprovals.find((item) => approvalAgentName(item) === agent.id);
        const latestEvent = latestEvents[agent.id];
        const rawStatus = String(agentStates?.[agent.id]?.status || "").toLowerCase();
        let statusLabel = "idle";

        if (approval) {
          statusLabel = "waiting_approval";
        } else if (rawStatus === "error" || ["error", "workflow_failed"].includes(String(latestEvent?.type || "").toLowerCase())) {
          statusLabel = "failed";
        } else if (String(latestEvent?.type || "").toLowerCase() === "agent_start") {
          const age = Date.now() / 1000 - eventTimestampSeconds(latestEvent);
          statusLabel = age < 20 ? "running" : "thinking";
        } else if (rawStatus === "thinking") {
          statusLabel = "thinking";
        }

        const lastAction =
          approval
            ? `${approvalTitle(approval)} - awaiting approval`
            : latestEvent
              ? historyEventMessage(latestEvent)
              : "No recent activity.";

        return {
          ...agent,
          status: statusLabel,
          lastAction,
        };
      });
    }, [agentStates, history, pendingApprovals]);

    const visibleApprovals = useMemo(() => {
      return pendingApprovals
        .filter((item) => {
          const id = String(item?.request_id || item?.action_id || "").trim();
          return id && !hiddenApprovals[id];
        })
        .slice();
    }, [hiddenApprovals, pendingApprovals]);

    const renderedApprovals = useMemo(() => visibleApprovals.slice(0, 2), [visibleApprovals]);

    const completedCount = useMemo(() => {
      const completedEvents = history.filter((event) =>
        ["agent_end", "growth_agent_completed", "step_completed", "task_result", "workflow_completed"].includes(
          String(event?.type || "").toLowerCase(),
        ),
      ).length;
      return completedEvents + approvedCount;
    }, [approvedCount, history]);

    const feedItems = useMemo(() => {
      const liveItems = [];
      for (let idx = history.length - 1; idx >= 0 && liveItems.length < 16; idx -= 1) {
        const item = historyEventToFeedItem(history[idx], idx);
        if (item.message) {
          liveItems.push(item);
        }
      }
      const combined = [...localFeedItems, ...liveItems];
      if (!combined.length) {
        return FEED_FALLBACK;
      }
      return combined.slice(0, 8);
    }, [history, localFeedItems]);

    const approvalClearState = useMemo(() => {
      const activeAgents = agentNodes.filter((item) =>
        ["thinking", "running", "waiting_approval"].includes(String(item?.status || "")),
      );
      const latestItem = feedItems[0] || null;
      const latestSummary = latestItem
        ? `${latestItem.agent}: ${clipText(latestItem.message, 88)}`
        : "No recent activity yet.";

      if (activeAgents.length > 0) {
        return {
          title: `${activeAgents.length} active ${activeAgents.length === 1 ? "agent" : "agents"} still moving`,
          copy:
            "No human decisions are blocking the swarm right now. The next approval request will appear here as soon as a step needs your sign-off.",
          meta: [
            `Latest activity: ${latestSummary}`,
            `Canvas activity: ${activeAgents.map((item) => item.id).join(", ")}`,
          ],
        };
      }

      return {
        title: "Queue is clear",
        copy:
          "No approvals are waiting. The system is idle or already moving through fully autonomous steps until the next human handoff is required.",
        meta: [
          `Latest activity: ${latestSummary}`,
          "Canvas activity: All visible agents are idle, complete, or waiting on new work.",
        ],
      };
    }, [agentNodes, feedItems]);

    const activeWorkflowPayload = activeWorkflowEntry ? workflowPayloads[activeWorkflowEntry.id] : null;
    const workflowBlocks = useMemo(
      () => workflowBlocksFromPayload(activeWorkflowPayload || (activeWorkflowEntry && activeWorkflowEntry.payload)),
      [activeWorkflowEntry, activeWorkflowPayload],
    );
    const latestFeedItem = feedItems[0] || null;

    const dashboardBrief = useMemo(() => {
      if (visibleApprovals.length) {
        return {
          kicker: "Needs your decision",
          title: `${visibleApprovals.length} approval${visibleApprovals.length === 1 ? "" : "s"} are waiting.`,
          copy:
            "ARCHON has already done the research and drafted the next step. Review the queued actions first, then reveal the live system only if you need to inspect the agent state behind them.",
        };
      }
      if (!token) {
        return {
          kicker: "Session ready",
          title: "Connect a tenant token before you run protected workflows.",
          copy:
            "Mission Control can explain the system and show its current state right away, but saved workflow runs and protected API actions stay locked until a tenant JWT is present.",
        };
      }
      if (activeWorkflowEntry) {
        return {
          kicker: "Ready to execute",
          title: `${activeWorkflowEntry.name} is the next useful move.`,
          copy:
            "No approvals are blocking the system right now. Start the saved workflow, or keep the machinery hidden and use this screen as an operator briefing until you need deeper supervision.",
        };
      }
      return {
        kicker: "Operator briefing",
        title: "ARCHON is live and waiting for the next decision.",
        copy:
          "Use this view to understand what the system can do in plain language. Agent graphs, cost, and event flow stay collapsed until you ask to see them.",
      };
    }, [activeWorkflowEntry, token, visibleApprovals.length]);

    function addLocalFeedItem(item) {
      setLocalFeedItems((current) => [item, ...current].slice(0, 16));
    }

    function openStudioSurface(note = "") {
      if (note) {
        setStudioNotice(note);
      }
      setActiveTab("studio");
    }

    function handleApprovalDecision(item, decision) {
      const requestId = String(item?.request_id || item?.action_id || "").trim();
      if (!requestId) {
        return;
      }
      setFadingApprovals((current) => ({ ...current, [requestId]: decision }));
      window.setTimeout(() => {
        if (decision === "approve") {
          setApprovedCount((current) => current + 1);
        }
        setHiddenApprovals((current) => ({ ...current, [requestId]: true }));
        send({
          type: decision,
          request_id: requestId,
          action_id: requestId,
        });
      }, 220);
    }

    async function ensureWorkflowPayload(entry) {
      if (!entry) {
        return null;
      }
      if (workflowPayloads[entry.id]) {
        return workflowPayloads[entry.id];
      }
      if (entry.source !== "api" || !token) {
        return null;
      }
      const response = await fetch(`${apiBase}/studio/workflows/${encodeURIComponent(entry.id)}`, {
        headers: buildHeaders(token),
      });
      if (!response.ok) {
        throw new Error(`Could not load "${entry.name}" (${response.status})`);
      }
      const payload = await response.json();
      setWorkflowPayloads((current) => ({ ...current, [entry.id]: payload }));
      return payload;
    }

    function connectStudioRunSocket(websocketPath, workflowName) {
      if (!token || !websocketPath) {
        return;
      }
      if (studioSocketRef.current) {
        try {
          studioSocketRef.current.close();
        } catch (_error) {
          return;
        }
      }
      const url = `${resolveWsBase(apiBase)}${websocketPath}?token=${encodeURIComponent(token)}`;
      const socket = new WebSocket(url);
      studioSocketRef.current = socket;
      socket.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data);
          const item = studioFrameToFeedItem(frame, workflowName);
          if (item) {
            addLocalFeedItem(item);
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
    }

    async function handleRunNow() {
      if (!token) {
        setStudioNotice("A valid tenant session is required before Studio can run a workflow.");
        return;
      }
      if (!activeWorkflowEntry) {
        setStudioNotice("Select a workflow before running it.");
        return;
      }

      setStudioBusy(true);
      try {
        const payload = await ensureWorkflowPayload(activeWorkflowEntry);
        if (!payload) {
          throw new Error(`No workflow definition available for "${activeWorkflowEntry.name}".`);
        }
        const response = await fetch(`${apiBase}/studio/run`, {
          method: "POST",
          headers: buildHeaders(token, true),
          body: JSON.stringify({ workflow: payload }),
        });
        if (!response.ok) {
          const detail = await response.text();
          throw new Error(detail || `Run request failed (${response.status})`);
        }
        const run = await response.json();
        addLocalFeedItem({
          id: `studio-start-${Date.now()}`,
          timestamp: formatClock(Date.now()),
          agent: "Orchestrator",
          message: `${activeWorkflowEntry.name} started`,
          tone: "green",
        });
        connectStudioRunSocket(run.websocket_path, activeWorkflowEntry.name);
        setWorkflowEntries((current) =>
          current.map((item) =>
            item.id === activeWorkflowEntry.id ? { ...item, lastRunText: "today" } : item,
          ),
        );
        setStudioNotice(`Started "${activeWorkflowEntry.name}".`);
        setActiveTab("dashboard");
      } catch (error) {
        setStudioNotice(String(error?.message || "Run failed."));
      } finally {
        setStudioBusy(false);
      }
    }

    function nodePosition(agentId) {
      const node = agentNodes.find((item) => item.id === agentId);
      return node || AGENT_LAYOUT.find((item) => item.id === agentId);
    }

    function renderDashboard() {
      const primaryAction = visibleApprovals.length
        ? {
            label: "Review approvals",
            body: "Queued decisions are the only hard blockers right now.",
            tone: "approve",
            onClick: () => {
              setShowSystemView(true);
              setOpenTooltipAgent("");
            },
            disabled: false,
          }
        : !token
          ? {
              label: "Open Studio",
              body: "Attach a tenant token before you run protected workflows.",
              tone: "muted",
              onClick: () =>
                openStudioSurface(
                  "Studio is available now, but protected runs stay locked until a tenant JWT is present.",
                ),
              disabled: false,
            }
          : activeWorkflowEntry
            ? {
                label: studioBusy ? "Running..." : "Run now",
                body: `${activeWorkflowEntry.name} is ready to launch from this screen.`,
                tone: "run",
                onClick: handleRunNow,
                disabled: studioBusy,
              }
            : {
                label: "Open Studio",
                body: "Load or edit a saved workflow before you run the next play.",
                tone: "muted",
                onClick: () => openStudioSurface("Load a saved workflow or choose one of the built-in runs."),
                disabled: false,
              };

      const primaryButtonClass =
        primaryAction.tone === "run"
          ? "archon-button archon-button--run"
          : primaryAction.tone === "approve"
            ? "archon-button archon-button--approve"
            : "archon-button archon-button--muted";

      const focusCopy = visibleApprovals.length
        ? "Review the queued sign-offs first. Everything else can stay collapsed until you need the full audit trail."
        : !token
          ? "Mission Control can explain the system now, but protected runs wait for tenant auth. You only need Studio when you are ready to run or edit workflows."
          : activeWorkflowEntry
            ? `${activeWorkflowEntry.name} is loaded and ready. You can launch it immediately, then reveal the deeper system view only if you want agent-by-agent context.`
            : "Nothing is blocked. Use this screen as an operator briefing until the next workflow or approval requires intervention.";

      return (
        <section className="archon-dashboard">
          <div className="archon-briefing">
            <div className="archon-briefing-copy">
              <div className="archon-panel-label">{dashboardBrief.kicker}</div>
              <h1>{dashboardBrief.title}</h1>
              <p>{dashboardBrief.copy}</p>
              <div className="archon-inline-actions">
                <button
                  type="button"
                  className={primaryButtonClass}
                  onClick={primaryAction.onClick}
                  disabled={primaryAction.disabled}
                >
                  {primaryAction.label}
                </button>
                <button
                  type="button"
                  className="archon-button archon-button--muted"
                  onClick={() => setShowSystemView((current) => !current)}
                >
                  {showSystemView ? "Hide live system" : "Reveal live system"}
                </button>
                <button
                  type="button"
                  className="archon-button archon-button--muted"
                  onClick={() => setShowCapabilityDetails((current) => !current)}
                >
                  {showCapabilityDetails ? "Hide system details" : "Explain the system"}
                </button>
              </div>
            </div>

            <div className="archon-briefing-metrics">
              {[
                { value: formatCost(costState.spent), label: "Cost Today" },
                { value: String(completedCount), label: "Completed" },
                { value: String(visibleApprovals.length), label: "Pending" },
              ].map((stat) => (
                <div className="archon-briefing-stat" key={stat.label}>
                  <div className="archon-briefing-stat-value">{stat.value}</div>
                  <div className="archon-briefing-stat-label">{stat.label}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="archon-focus-grid">
            <section className="archon-focus-card">
              <div className="archon-panel-label">Operator Focus</div>
              <div className="archon-focus-title">What needs your attention</div>
              <div className="archon-focus-copy">{focusCopy}</div>

              <div className="archon-action-list">
                <div className="archon-action-card">
                  <div className="archon-action-copy">
                    <div className="archon-action-title">{primaryAction.label}</div>
                    <div className="archon-action-body">{primaryAction.body}</div>
                  </div>
                  <button
                    type="button"
                    className={primaryButtonClass}
                    onClick={primaryAction.onClick}
                    disabled={primaryAction.disabled}
                  >
                    {primaryAction.label}
                  </button>
                </div>

                <div className="archon-action-card">
                  <div className="archon-action-copy">
                    <div className="archon-action-title">Open Studio when you need workflow control</div>
                    <div className="archon-action-body">
                      Load a saved workflow, inspect the step chain, and run it without turning this home screen into a control panel.
                    </div>
                  </div>
                  <button
                    type="button"
                    className="archon-button archon-button--muted"
                    onClick={() =>
                      openStudioSurface(
                        token
                          ? "Studio is ready. Load a workflow or run the active one."
                          : "Studio is visible, but protected runs still need a tenant JWT.",
                      )
                    }
                  >
                    Open Studio
                  </button>
                </div>

                <div className="archon-action-card">
                  <div className="archon-action-copy">
                    <div className="archon-action-title">
                      {showSystemView ? "Hide the machinery again" : "Reveal the live system only on demand"}
                    </div>
                    <div className="archon-action-body">
                      {latestFeedItem
                        ? `${latestFeedItem.agent}: ${clipText(latestFeedItem.message, 92)}`
                        : "Open the underlying canvas, approvals queue, and raw feed only when you want deeper supervision."}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="archon-button archon-button--muted"
                    onClick={() => setShowSystemView((current) => !current)}
                  >
                    {showSystemView ? "Hide System" : "Reveal System"}
                  </button>
                </div>
              </div>
            </section>

            <section className="archon-focus-card">
              <div className="archon-panel-label">System Scope</div>
              <div className="archon-focus-title">What ARCHON can do</div>
              <div className="archon-focus-copy">
                This screen stays outcome-first. These are the operator jobs ARCHON can take over before you ever open the agent graph.
              </div>

              <div className="archon-capability-list">
                {CAPABILITY_GROUPS.map((capability) => (
                  <div className="archon-capability-card" key={capability.id}>
                    <div className="archon-capability-title">{capability.title}</div>
                    <div className="archon-capability-copy">{capability.summary}</div>
                    <div className="archon-capability-meta">
                      {showCapabilityDetails ? capability.system : "System details stay collapsed until you ask for them."}
                    </div>
                  </div>
                ))}
              </div>

              <div className="archon-inline-actions">
                <button
                  type="button"
                  className="archon-button archon-button--muted"
                  onClick={() => setShowCapabilityDetails((current) => !current)}
                >
                  {showCapabilityDetails ? "Hide internals" : "Reveal internals"}
                </button>
              </div>

              {showCapabilityDetails ? (
                <div className="archon-capability-details">
                  <div className="archon-capability-detail">
                    <strong>How work is routed</strong>
                    <p>
                      Mission Control surfaces approvals and recent activity while Studio holds the reusable workflows.
                      Underneath, specialist agents pass work across prospecting, outreach, revenue intelligence,
                      partnerships, and churn defense.
                    </p>
                  </div>
                  <div className="archon-capability-detail">
                    <strong>Where control stays human</strong>
                    <p>
                      Sensitive sends and approval-gated steps pause until you approve or deny them. Protected Studio
                      runs also require a tenant token before the dashboard calls the workflow API.
                    </p>
                  </div>
                  <div className="archon-capability-detail">
                    <strong>What the hidden layer contains</strong>
                    <p>
                      The collapsed system view exposes the Agent Canvas, approval queue, spend, completion counts, and
                      the live event feed. It exists for supervision, not as the primary interface.
                    </p>
                  </div>
                </div>
              ) : null}
            </section>
          </div>

          {renderedApprovals.length ? (
            <section className="archon-priority-panel">
              <div className="archon-panel-label">Approvals</div>
              <div className="archon-focus-title">Queued decisions waiting right now</div>
              <div className="archon-focus-copy">
                ARCHON has already drafted the next step. Review the sign-off cards here without opening the full system view unless you need wider context.
              </div>
              <div className="archon-priority-grid">
                {renderedApprovals.map((item) => {
                  const requestId = String(item?.request_id || item?.action_id || "").trim();
                  return (
                    <div
                      key={requestId}
                      className={`archon-approval-card ${fadingApprovals[requestId] ? "archon-approval-card--exiting" : ""}`}
                    >
                      <div className="archon-approval-agent">{approvalAgentName(item)}</div>
                      <div className="archon-approval-title">{approvalTitle(item)}</div>
                      <div className="archon-approval-preview">{approvalPreview(item)}</div>
                      <div className="archon-approval-actions">
                        <button
                          type="button"
                          className="archon-button archon-button--approve"
                          onClick={() => handleApprovalDecision(item, "approve")}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className="archon-button archon-button--deny"
                          onClick={() => handleApprovalDecision(item, "deny")}
                        >
                          Deny
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          <div className="archon-reveal-bar">
            <div>
              <div className="archon-panel-label">System View</div>
              <div className="archon-reveal-title">
                {showSystemView ? "Live machinery is visible." : "Live machinery stays collapsed by default."}
              </div>
              <div className="archon-reveal-copy">
                {showSystemView
                  ? "You are looking at the live supervision layer: agent topology, approvals, spend, and the event stream."
                  : "Keep the system hidden while you operate from the briefing surface. Reveal it only when you need audit depth, approval context, or agent-by-agent status."}
              </div>
            </div>
            <button
              type="button"
              className="archon-button archon-button--muted"
              onClick={() => setShowSystemView((current) => !current)}
            >
              {showSystemView ? "Hide live system" : "Reveal live system"}
            </button>
          </div>

          {showSystemView ? (
            <div className="archon-system-shell">
              <div className="archon-dashboard-main">
                <div className="archon-canvas-panel">
                  <div className="archon-panel-label">Agent Canvas</div>
                  <div className="archon-canvas">
                    <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                      {AGENT_LINKS.map((link) => {
                        const source = nodePosition(link.from);
                        const target = nodePosition(link.to);
                        const active =
                          ["thinking", "running", "waiting_approval"].includes(String(source?.status || "")) ||
                          ["thinking", "running", "waiting_approval"].includes(String(target?.status || ""));
                        if (!source || !target) {
                          return null;
                        }
                        return (
                          <line
                            key={`${link.from}-${link.to}`}
                            className={`archon-link ${active ? "archon-link--active" : ""}`}
                            x1={source.x}
                            y1={source.y}
                            x2={target.x}
                            y2={target.y}
                          />
                        );
                      })}
                    </svg>

                    {agentNodes.map((agent) => {
                      const isOpen = openTooltipAgent === agent.id;
                      return (
                        <React.Fragment key={agent.id}>
                          <button
                            type="button"
                            className={`archon-agent-node archon-agent-node--${agent.status}`}
                            style={{
                              left: `calc(${agent.x}% - 80px)`,
                              top: `calc(${agent.y}% - 40px)`,
                            }}
                            onClick={() => setOpenTooltipAgent((current) => (current === agent.id ? "" : agent.id))}
                          >
                            {agent.status === "waiting_approval" ? (
                              <span className="archon-status-badge archon-status-badge--warning">Needs Approval</span>
                            ) : null}
                            {agent.status === "failed" ? (
                              <span className="archon-status-badge archon-status-badge--danger">Failed</span>
                            ) : null}
                            <div className="archon-agent-topline">
                              <span className="archon-agent-icon" aria-hidden="true">
                                <Icon name={agent.icon} color={COLORS.textSecondary} size={12} />
                              </span>
                              <div className="archon-agent-title">{agent.id}</div>
                            </div>
                            <div className={`archon-status-pill archon-status-pill--${agent.status}`}>
                              {prettyStatus(agent.status)}
                            </div>
                          </button>
                          {isOpen ? (
                            <div
                              className="archon-tooltip"
                              style={{
                                left: `calc(${agent.x}% - 10px)`,
                                top: `calc(${agent.y}% + 48px)`,
                              }}
                            >
                              <div className="archon-tooltip-label">Last action</div>
                              <div className="archon-tooltip-text">{agent.lastAction}</div>
                            </div>
                          ) : null}
                        </React.Fragment>
                      );
                    })}
                  </div>
                </div>

                <aside className="archon-sidebar">
                  <div className="archon-stats">
                    {[
                      { value: formatCost(costState.spent), label: "Cost Today" },
                      { value: String(completedCount), label: "Completed" },
                      { value: String(visibleApprovals.length), label: "Pending" },
                    ].map((stat) => (
                      <div className="archon-stat" key={stat.label}>
                        <div className="archon-stat-value">{stat.value}</div>
                        <div className="archon-stat-label">{stat.label}</div>
                      </div>
                    ))}
                  </div>

                  <div className="archon-approvals">
                    <div className="archon-approvals-header">
                      <span>Approvals</span>
                      <span className="archon-count-badge">{visibleApprovals.length}</span>
                    </div>

                    {renderedApprovals.length ? (
                      renderedApprovals.map((item) => {
                        const requestId = String(item?.request_id || item?.action_id || "").trim();
                        return (
                          <div
                            key={requestId}
                            className={`archon-approval-card ${fadingApprovals[requestId] ? "archon-approval-card--exiting" : ""}`}
                          >
                            <div className="archon-approval-agent">{approvalAgentName(item)}</div>
                            <div className="archon-approval-title">{approvalTitle(item)}</div>
                            <div className="archon-approval-preview">{approvalPreview(item)}</div>
                            <div className="archon-approval-actions">
                              <button
                                type="button"
                                className="archon-button archon-button--approve"
                                onClick={() => handleApprovalDecision(item, "approve")}
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                className="archon-button archon-button--deny"
                                onClick={() => handleApprovalDecision(item, "deny")}
                              >
                                Deny
                              </button>
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="archon-clear-card">
                        <div className="archon-clear-kicker">System Clear</div>
                        <div className="archon-clear-title">{approvalClearState.title}</div>
                        <div className="archon-clear-copy">{approvalClearState.copy}</div>
                        <div className="archon-clear-meta">
                          {approvalClearState.meta.map((item) => (
                            <span key={item}>{item}</span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </aside>
              </div>

              <div className="archon-feed">
                <div className="archon-feed-header">
                  <div className="archon-feed-title">Live Feed</div>
                  <div className="archon-feed-live">
                    <span className="archon-live-dot archon-live-dot--live" />
                    <span>Live</span>
                  </div>
                </div>
                <div className="archon-feed-list">
                  {feedItems.map((item) => (
                    <div className="archon-feed-item" key={item.id}>
                      <div className="archon-feed-time">{item.timestamp}</div>
                      <div className={`archon-feed-agent archon-feed-agent--${item.tone || "green"}`}>
                        {item.agent}
                      </div>
                      <div className="archon-feed-message">{item.message}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="archon-system-placeholder">
              <div className="archon-panel-label">Live System Hidden</div>
              <div className="archon-reveal-title">
                {latestFeedItem ? `Most recent signal: ${latestFeedItem.agent}` : approvalClearState.title}
              </div>
              <div className="archon-reveal-copy">
                {latestFeedItem ? latestFeedItem.message : approvalClearState.copy}
              </div>
              {approvalClearState.meta.map((item) => (
                <div key={item}>{item}</div>
              ))}
            </div>
          )}
        </section>
      );
    }

    function renderStudio() {
      return (
        <section className="archon-studio">
          <aside className="archon-studio-sidebar">
            <div className="archon-panel-label">Workflows</div>
            <div className="archon-workflow-list">
              {workflowEntries.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`archon-workflow-item ${item.id === activeWorkflowId ? "archon-workflow-item--active" : ""}`}
                  onClick={() => setActiveWorkflowId(item.id)}
                >
                  <div className="archon-workflow-name">{item.name}</div>
                  <div className="archon-workflow-meta">last run: {item.lastRunText}</div>
                </button>
              ))}
            </div>
            <div className="archon-studio-status">{studioNotice}</div>
          </aside>

          <div className="archon-studio-main">
            <div className="archon-studio-topbar">
              <div className="archon-studio-title">
                <div className="archon-panel-label">Studio</div>
                <h1>{activeWorkflowEntry ? activeWorkflowEntry.name : "No workflow selected"}</h1>
                <p>Load a saved workflow, inspect its steps, and run it through the existing Studio API.</p>
              </div>
              <div className="archon-studio-actions">
                <button
                  type="button"
                  className="archon-button archon-button--muted"
                  onClick={() => setStudioNotice("Dry run is still a local-only control in this dashboard view.")}
                >
                  Dry Run
                </button>
                <button
                  type="button"
                  className="archon-button archon-button--muted"
                  onClick={() => setStudioNotice("Schedule is not wired into this dashboard shell yet.")}
                >
                  Schedule
                </button>
                <button
                  type="button"
                  className="archon-button archon-button--run"
                  onClick={handleRunNow}
                  disabled={studioBusy}
                >
                  {studioBusy ? "Running..." : "Run Now"}
                </button>
              </div>
            </div>

            <div className="archon-flow">
              {workflowBlocks.length ? (
                workflowBlocks.map((block, index) => (
                  <React.Fragment key={block.id}>
                    <div className="archon-flow-card">
                      <div className="archon-flow-topline">
                        <Icon name={block.icon} color={COLORS.textPrimary} size={16} />
                        <div className="archon-flow-title">{block.title}</div>
                      </div>
                      <div className="archon-flow-subtitle">{block.subtitle}</div>
                    </div>
                    {index < workflowBlocks.length - 1 ? <div className="archon-flow-arrow">↓</div> : null}
                  </React.Fragment>
                ))
              ) : (
                <div className="archon-empty">This workflow has no visible steps yet.</div>
              )}
            </div>
          </div>
        </section>
      );
    }

    return (
      <div className="archon-shell">
        <style>{SHELL_CSS}</style>

        <header className="archon-nav">
          <div className="archon-nav-tabs">
            <button
              type="button"
              className={`archon-nav-tab ${activeTab === "dashboard" ? "archon-nav-tab--active" : ""}`}
              onClick={() => setActiveTab("dashboard")}
            >
              Dashboard
            </button>
            <button
              type="button"
              className={`archon-nav-tab ${activeTab === "studio" ? "archon-nav-tab--active" : ""}`}
              onClick={() => setActiveTab("studio")}
            >
              Studio
            </button>
          </div>
          <div className="archon-nav-meta">
            <span
              className={`archon-live-dot archon-live-dot--${connectionTone(status, isInitializing, Boolean(sessionId && token))}`}
            />
            <span>{connectionLabel(status, isInitializing, Boolean(sessionId && token))}</span>
          </div>
        </header>

        {activeTab === "dashboard" ? renderDashboard() : renderStudio()}
      </div>
    );
  }

  window.App = App;
})();
