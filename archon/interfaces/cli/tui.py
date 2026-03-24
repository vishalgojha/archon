"""Enhanced Textual-based terminal UI for ARCHON orchestration sessions."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Header,
    Input,
    Label,
    Markdown,
    RichLog,
    Rule,
    Static,
    Tab,
    Tabs,
)

from archon.chat import ChatRuntime, ChatSession, build_chat_runtime
from archon.config import ArchonConfig
from archon.core.orchestrator import Orchestrator
from archon.core.types import TaskMode
from archon.logging_utils import append_log, log_path
from archon.skills.skill_registry import SkillRegistry
from archon.versioning import resolve_version


@dataclass(slots=True)
class TaskHistory:
    task_id: str
    goal: str
    mode: str
    confidence: int
    spent_usd: float
    budget_usd: float
    completed_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ActiveTask:
    task_id: str
    goal: str
    mode: str
    status: str = "running"
    agent: str = "-"
    confidence: int | None = None
    spent_usd: float = 0.0
    budget_usd: float = 0.0
    progress: float = 0.0
    expected_agents: int = 0
    completed_agents: int = 0
    updated_at: float = field(default_factory=time.time)
    started_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ProviderStatus:
    name: str
    available: bool
    model: str
    last_used: float | None = None


@dataclass(slots=True)
class TuiState:
    mode: str
    context: dict[str, Any]
    active_tasks: dict[str, ActiveTask] = field(default_factory=dict)
    history: list[TaskHistory] = field(default_factory=list)
    pending_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    audit_log: list[str] = field(default_factory=list)
    providers: dict[str, ProviderStatus] = field(default_factory=dict)
    total_spent_usd: float = 0.0
    total_budget_usd: float = 0.0
    log_hook: Any | None = None
    activity: str = ""
    spinner_index: int = 0

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.audit_log.append(line)
        if callable(self.log_hook):
            self.log_hook(line)

    def apply_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "")).strip().lower()

        if event_type == "task_started":
            task_id = str(event.get("task_id", "task")).strip()
            self.active_tasks[task_id] = ActiveTask(
                task_id=task_id,
                goal=str(event.get("goal", "unknown")),
                mode=str(event.get("mode", self.mode)),
                status="running",
                progress=0.0,
            )
            self.activity = "Starting swarm..."
            self.log(f"⚡ Task started {task_id} ({self.active_tasks[task_id].mode})")
            return

        if event_type in {"agent_start", "agent_end", "agent_spawned", "swarm_manifest"}:
            task_id = str(event.get("task_id", "")).strip()
            task = self.active_tasks.get(task_id)
            if task is not None:
                if event_type == "swarm_manifest":
                    task.expected_agents = int(event.get("count", 0) or 0)
                if event_type in {"agent_start", "agent_end", "agent_spawned"}:
                    task.agent = str(event.get("agent", "unknown"))
                if "confidence" in event:
                    task.confidence = int(event.get("confidence", 0) or 0)
                task.updated_at = time.time()
                if event_type == "agent_end":
                    task.completed_agents += 1
                    if task.expected_agents > 0:
                        task.progress = min(task.completed_agents / task.expected_agents, 0.9)
                elif event_type == "agent_start":
                    stage = _swarm_stage_label(task.agent, event.get("skill"))
                    self.activity = stage
                    self.log(f"🧠 {stage}")
            return

        if event_type == "cost_update":
            task_id = str(event.get("task_id", "")).strip()
            task = self.active_tasks.get(task_id)
            if task is not None:
                task.spent_usd = float(event.get("spent", 0.0) or 0.0)
                task.budget_usd = float(event.get("budget", 0.0) or 0.0)
                task.updated_at = time.time()
            self.total_spent_usd = sum(t.spent_usd for t in self.active_tasks.values())
            self.total_budget_usd = sum(t.budget_usd for t in self.active_tasks.values())
            return

        if event_type == "task_completed":
            task_id = str(event.get("task_id", "")).strip()
            budget = event.get("budget", {}) or {}
            spent = float(budget.get("spent_usd", 0.0) or 0.0)
            limit = float(budget.get("limit_usd", 0.0) or 0.0)
            confidence = int(event.get("confidence", 0) or 0)
            task = self.active_tasks.pop(task_id, None)
            if task is not None:
                if spent == 0.0 and task.spent_usd:
                    spent = task.spent_usd
                if limit == 0.0 and task.budget_usd:
                    limit = task.budget_usd
                task.progress = 1.0
            goal = task.goal if task else str(event.get("goal", "unknown"))
            mode = task.mode if task else str(event.get("mode", self.mode))
            self.history.append(
                TaskHistory(
                    task_id=task_id,
                    goal=goal,
                    mode=mode,
                    confidence=confidence,
                    spent_usd=spent,
                    budget_usd=limit,
                )
            )
            self.log(f"✅ Task completed {task_id} ({confidence}% confidence)")
            self.activity = ""
            return

        if event_type == "approval_required":
            request_id = str(event.get("request_id", "")).strip()
            self.pending_approvals[request_id] = dict(event)
            self.log(
                f"⚠️ Confirmation needed: {event.get('action_type', 'action')} ({event.get('risk_level', 'unknown')})"
            )
            return

        if event_type == "approval_resolved":
            request_id = str(event.get("request_id", "")).strip()
            approved = bool(event.get("approved", False))
            self.pending_approvals.pop(request_id, None)
            self.log(f"{'✓' if approved else '✗'} Confirmation resolved {request_id}")
            return


class ApprovalScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "deny", "Decline"),
        Binding("enter", "approve", "Confirm"),
    ]

    def __init__(self, *, request_id: str, action: str, risk: str, context: dict[str, Any]):
        super().__init__()
        self._request_id = request_id
        self._action = action
        self._risk = risk
        self._context = context

    def compose(self) -> ComposeResult:
        risk_color = (
            "#ff6b6b"
            if self._risk == "high"
            else "#ffd93d"
            if self._risk == "medium"
            else "#6bcb77"
        )
        summary = (
            f"[bold]Confirmation Required[/bold]\n\n"
            f"[bold]Action:[/bold] {self._action}\n"
            f"[bold]Risk Level:[/bold] [{risk_color}]{self._risk}[/]\n"
            f"[bold]Request ID:[/bold] {self._request_id}\n\n"
            f"[dim]{str(self._context)[:500]}[/]"
        )
        yield Container(
            Markdown(summary, id="approval-summary"),
            Rule(),
            Horizontal(
                Button("✓ Confirm", id="approve", variant="success"),
                Button("✗ Decline", id="deny", variant="error"),
                id="approval-buttons",
            ),
            id="approval-modal",
        )

    def action_deny(self) -> None:
        self.dismiss(False)

    def action_approve(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")


class ProviderStatusPanel(Static):
    """Displays provider availability status."""

    def __init__(self, providers: dict[str, ProviderStatus], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.providers = providers

    def render(self) -> str:
        lines = ["[bold]Providers[/bold]"]
        for name, status in self.providers.items():
            icon = "🟢" if status.available else "🔴"
            model = status.model[:20] + "..." if len(status.model) > 20 else status.model
            lines.append(f"{icon} {name}: {model}")
        return "\n".join(lines)


class TaskProgressPanel(Static):
    """Displays active task progress."""

    def __init__(self, tasks: dict[str, ActiveTask], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tasks = tasks

    def render(self) -> str:
        if not self.tasks:
            return "[dim]No active tasks[/]"

        lines = ["[bold]Active Tasks[/bold]"]
        for task in self.tasks.values():
            progress_bar = self._render_progress(task.progress)
            status_icon = "🔄" if task.status == "running" else "⏸️"
            lines.append(f"{status_icon} {task.task_id[:8]}...")
            lines.append(f"  {progress_bar} {int(task.progress * 100)}%")
            lines.append(f"  Agent: {task.agent} | Confidence: {task.confidence or '-'}%")
        return "\n".join(lines)

    def _render_progress(self, progress: float) -> str:
        width = 20
        filled = int(progress * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"


class ArchonTuiApp(App[None]):
    CSS = """
    Screen {
        background: #0b0b0b;
        color: #e8e8e8;
    }

    Header {
        background: #1a1a2e;
        color: #f5b86c;
    }

    Footer {
        background: #1a1a2e;
        color: #8a8a8a;
    }

    #root {
        height: 1fr;
        min-height: 0;
        padding: 1 2;
    }

    #main-container {
        height: 1fr;
        min-height: 0;
    }

    #tabs-container {
        height: 3;
        dock: top;
        background: #1a1a2e;
    }

    Tabs {
        background: #1a1a2e;
    }

    Tabs > Tab {
        background: #2a2a3e;
        color: #e8e8e8;
    }

    Tabs > Tab:hover {
        background: #3a3a4e;
    }

    Tabs > Tab.-active {
        background: #f5b86c;
        color: #0b0b0b;
    }

    #content-area {
        height: 1fr;
        min-height: 0;
    }

    #overview-panel {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }

    #tasks-panel {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }

    #history-panel {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }

    #skills-panel {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }


    #chat-panel {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }

    DataTable {
        background: #0f0f0f;
        border: solid #2a2a2a;
    }

    DataTable > .datatable--header {
        background: #1a1a2e;
        color: #f5b86c;
    }

    DataTable > .datatable--cursor {
        background: #2a2a3e;
    }

    Markdown {
        color: #e8e8e8;
        background: #0f0f0f;
        border: solid #2a2a2a;
    }

    Markdown H1 {
        color: #f5b86c;
        border-bottom: solid #2a2a2a;
    }

    Markdown H2 {
        color: #f5b86c;
    }

    Markdown Code {
        color: #a6d8ff;
        background: #1a1a2e;
    }

    RichLog {
        border: solid #2a2a2a;
        background: #0f0f0f;
        color: #e8e8e8;
        overflow-y: auto;
    }

    #input-bar {
        height: 5;
        min-height: 5;
        padding: 0 2;
        background: #1a1a2e;
        border-top: solid #2a2a2a;
    }

    #input-container {
        height: 3;
        min-height: 3;
        align: left middle;
    }

    #goal-label {
        width: 6;
        color: #f5b86c;
        text-style: bold;
        padding-right: 1;
    }

    #goal-input {
        width: 1fr;
        height: 3;
        border: solid #2a2a2a;
        background: #0f0f0f;
        color: #e8e8e8;
        padding: 0 1;
    }

    #goal-input:focus {
        border: solid #f5b86c;
    }

    #submit-btn {
        width: 12;
        height: 3;
        margin-left: 1;
        background: #f5b86c;
        color: #0b0b0b;
        text-style: bold;
    }

    #status-bar {
        height: 1;
        color: #8a8a8a;
        padding: 0 1;
    }

    #budget-display {
        height: 1;
        color: #6bcb77;
        padding: 0 1;
    }

    #provider-panel {
        width: 30;
        height: 1fr;
        padding: 1;
        background: #0f0f0f;
        border: solid #2a2a2a;
        margin: 1;
    }

    #active-tasks-panel {
        width: 1fr;
        height: 10;
        padding: 1;
        background: #0f0f0f;
        border: solid #2a2a2a;
        margin: 1;
    }

    #approval-modal {
        width: 80;
        height: auto;
        padding: 1 2;
        border: round #f5b86c;
        background: #1a1a2e;
    }

    #approval-summary {
        padding: 1 0;
        color: #e8e8e8;
    }

    Button {
        border: solid #2a2a2a;
        background: #0f0f0f;
        color: #e8e8e8;
        text-style: bold;
    }

    Button:hover {
        background: #2a2a3e;
    }

    Button#approve {
        background: #4a4a5e;
        color: #6bcb77;
        border: solid #6bcb77;
    }

    Button#approve:hover {
        background: #6bcb77;
        color: #0b0b0b;
    }

    Button#deny {
        background: #4a4a5e;
        color: #ff6b6b;
        border: solid #ff6b6b;
    }

    Button#deny:hover {
        background: #ff6b6b;
        color: #0b0b0f;
    }

    #approval-buttons {
        margin-top: 1;
        height: 3;
        align: center middle;
    }

    .success {
        background: #6bcb77;
        color: #0b0b0b;
    }

    .error {
        background: #ff6b6b;
        color: #0b0b0b;
    }

    Label {
        color: #8a8a8a;
    }

    Rule {
        color: #2a2a2a;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+1", "show_chat", "Chat"),
        Binding("ctrl+2", "show_overview", "Overview"),
        Binding("ctrl+3", "show_tasks", "Tasks"),
        Binding("ctrl+4", "show_skills", "Skills"),
        Binding("ctrl+5", "show_history", "History"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("ctrl+l", "clear_log", "Clear"),
        Binding("ctrl+n", "new_task", "New"),
        Binding("f1", "help", "Help"),
    ]

    current_tab = reactive(0)
    _spinner_frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(
        self,
        *,
        config: ArchonConfig,
        initial_mode: str,
        initial_context: dict[str, Any],
        config_path: str,
    ) -> None:
        super().__init__()
        self._config = config
        self._config_path = config_path
        self._skill_registry = SkillRegistry()
        self._log_file = log_path("archon-tui.log")
        self._state = TuiState(
            mode=initial_mode,
            context=dict(initial_context),
        )
        self._state.log_hook = lambda line: append_log("archon-tui.log", line)
        self._log_cursor = 0
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._swarm_db_path = os.getenv("ARCHON_SWARM_DB", "archon_swarm.sqlite3")
        self._chat_runtime: ChatRuntime | None = None
        self._chat_session: ChatSession | None = None
        self._initialize_providers()

    def _initialize_providers(self) -> None:
        """Initialize provider status from config."""
        byok = self._config.byok
        for provider in ["anthropic", "openai", "gemini", "mistral", "groq", "ollama"]:
            self._state.providers[provider] = ProviderStatus(
                name=provider,
                available=provider in getattr(byok, "providers", [provider]),
                model=getattr(byok, f"{provider}_model", "default"),
            )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="root"):
            yield Tabs(
                Tab("💬 Chat", id="tab-chat"),
                Tab("📊 Overview", id="tab-overview"),
                Tab("🔄 Tasks", id="tab-tasks"),
                Tab("🧠 Skills", id="tab-skills"),
                Tab("📜 History", id="tab-history"),
                id="tabs-container",
            )

            with Container(id="content-area"):
                with ScrollableContainer(id="chat-panel"):
                    yield RichLog(id="evolution-log", wrap=True, highlight=True, markup=True)

                with ScrollableContainer(id="overview-panel"):
                    yield Markdown(id="overview-markdown")

                with ScrollableContainer(id="tasks-panel"):
                    yield DataTable(id="tasks-table")

                with ScrollableContainer(id="skills-panel"):
                    yield DataTable(id="skills-table")

                with ScrollableContainer(id="history-panel"):
                    yield Label("Task History", id="history-label")
                    yield DataTable(id="history-table")
                    yield Rule()
                    yield Label("Evolution Insights", id="evolution-label")
                    yield DataTable(id="evolution-table")

            with Container(id="input-bar"):
                yield Static(id="budget-display")
                with Horizontal(id="input-container"):
                    yield Input(placeholder="Message Archon and press Enter...", id="goal-input")
                    yield Button("Send", id="submit-btn", variant="primary")

            yield Static(id="status-bar")

    def on_mount(self) -> None:
        if self._state.mode == "chat":
            self._state.log("🚀 ARCHON online - Ready for interactive chat")
        else:
            self._state.log("🚀 ARCHON online - Ready for orchestration")
        self._state.log(f"Log file: {self._log_file}")
        self._flush_audit_log()
        self.action_show_chat()
        self._refresh_overview()
        self._refresh_budget_display()
        self._refresh_status_bar()
        self._setup_data_tables()
        self._refresh_skills_table()
        self.query_one("#goal-input", Input).focus()
        self.set_interval(2.0, self._safe_refresh)
        self.set_interval(0.2, self._tick_spinner)

    def _setup_data_tables(self) -> None:
        tasks_table = self.query_one("#tasks-table", DataTable)
        tasks_table.add_columns(
            "Task ID", "Goal", "Mode", "Status", "Agent", "Progress", "Confidence", "Spent"
        )

        history_table = self.query_one("#history-table", DataTable)
        history_table.add_columns("Task ID", "Goal", "Mode", "Confidence", "Spent", "Completed")

        skills_table = self.query_one("#skills-table", DataTable)
        skills_table.add_columns("Name", "State", "Provider", "Tier", "Version")

        evolution_table = self.query_one("#evolution-table", DataTable)
        evolution_table.add_columns("Skill", "Success Rate", "Avg Confidence", "Last Used")

    def _flush_audit_log(self) -> None:
        log = self.query_one("#evolution-log", RichLog)
        while self._log_cursor < len(self._state.audit_log):
            log.write(self._state.audit_log[self._log_cursor])
            self._log_cursor += 1
        log.scroll_end(animate=False)

    def _build_overview_markdown(self) -> str:
        config_exists = Path(self._config_path).exists()
        version = resolve_version()
        mode_label = "interactive chat" if self._state.mode == "chat" else self._state.mode

        lines = [
            "# 🤖 ARCHON Control Panel",
            "",
            f"**Status**: {'🟢 Online' if config_exists else '🔴 Config Missing'}",
            f"**Version**: {version}",
            f"**Mode**: {mode_label}",
            "",
            "## 📈 Quick Stats",
            "",
            f"- Active Work: {self._active_work_count()}",
            f"- Completed: {len(self._state.history)}",
            f"- Total Spent: ${self._state.total_spent_usd:.4f}",
            f"- Pending Approvals: {len(self._state.pending_approvals)}",
            "",
            "## 🔌 Provider Status",
            "",
        ]

        for name, status in self._state.providers.items():
            icon = "🟢" if status.available else "🔴"
            lines.append(f"- {icon} **{name}**: {status.model}")

        lines.extend(
            [
                "",
                "## ⚙️ Context",
                "",
            ]
        )

        if self._state.context:
            for key, value in self._state.context.items():
                lines.append(f"- **{key}**: {value}")
        else:
            lines.append("_No context configured_")

        return "\n".join(lines)

    def _refresh_overview(self) -> None:
        overview = self.query_one("#overview-markdown", Markdown)
        overview.update(self._build_overview_markdown())

    def _refresh_tasks_table(self) -> None:
        table = self.query_one("#tasks-table", DataTable)
        table.clear()

        for task in self._state.active_tasks.values():
            progress_str = f"{int(task.progress * 100)}%"
            table.add_row(
                task.task_id[:12],
                task.goal[:30] + "..." if len(task.goal) > 30 else task.goal,
                task.mode,
                task.status,
                task.agent,
                progress_str,
                f"{task.confidence}%" if task.confidence else "-",
                f"${task.spent_usd:.4f}",
            )

    def _refresh_history_table(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear()

        for task in reversed(self._state.history[-20:]):
            completed = time.strftime("%H:%M:%S", time.localtime(task.completed_at))
            table.add_row(
                task.task_id[:12],
                task.goal[:30] + "..." if len(task.goal) > 30 else task.goal,
                task.mode,
                f"{task.confidence}%",
                f"${task.spent_usd:.4f}",
                completed,
            )
        self._refresh_evolution_table()

    def _refresh_evolution_table(self) -> None:
        table = self.query_one("#evolution-table", DataTable)
        table.clear()
        if not os.path.exists(self._swarm_db_path):
            return
        try:
            with sqlite3.connect(self._swarm_db_path) as conn:
                rows = conn.execute(
                    "SELECT skill_name, success_count, failure_count, avg_confidence, last_used FROM skill_performance"
                ).fetchall()
        except Exception:
            return
        for name, success_count, failure_count, avg_confidence, last_used in rows[:20]:
            total = int(success_count) + int(failure_count)
            rate = "-" if total == 0 else f"{(success_count / total) * 100:.0f}%"
            last_used_text = (
                time.strftime("%H:%M:%S", time.localtime(float(last_used))) if last_used else "-"
            )
            table.add_row(
                str(name),
                rate,
                f"{float(avg_confidence):.2f}",
                last_used_text,
            )

    def _refresh_skills_table(self) -> None:
        table = self.query_one("#skills-table", DataTable)
        table.clear()
        self._skill_registry.reload()
        skills = self._skill_registry.list_skills()
        for skill in skills:
            table.add_row(
                skill.name,
                skill.state,
                skill.provider_preference or "-",
                skill.cost_tier,
                str(skill.version),
            )

    def _refresh_budget_display(self) -> None:
        spent = self._state.total_spent_usd
        limit = self._state.total_budget_usd

        if limit > 0:
            remaining = max(limit - spent, 0.0)
            percentage = (spent / limit) * 100
            text = f"💰 Budget: ${spent:.2f} / ${limit:.2f} ({percentage:.1f}%) - ${remaining:.2f} remaining"
        else:
            text = f"💰 Budget: ${spent:.2f} used"

        self.query_one("#budget-display", Static).update(text)

    def _active_work_count(self) -> int:
        return (
            len(self._state.active_tasks)
            if self._state.mode != "chat"
            else len(self._pending_tasks)
        )

    def _refresh_status_bar(self) -> None:
        active = self._active_work_count()
        spinner = ""
        if active:
            spinner = f"⏳ {self._spinner_frames[self._state.spinner_index]} "
        if self._state.activity:
            activity = self._state.activity
        elif active:
            activity = "Working..."
        else:
            activity = "Ready for chat" if self._state.mode == "chat" else "Idle"
        work_label = "Turns" if self._state.mode == "chat" else "Tasks"
        mode_label = "interactive chat" if self._state.mode == "chat" else self._state.mode
        status = (
            f"{spinner}{activity} | 📡 Connected | 🎯 Mode: {mode_label} | "
            f"📝 {work_label}: {active} active, {len(self._state.history)} completed"
        )
        self.query_one("#status-bar", Static).update(status)

    def _perform_auto_refresh(self) -> None:
        self._refresh_overview()
        self._refresh_tasks_table()
        self._refresh_history_table()
        self._refresh_budget_display()
        self._refresh_status_bar()

    def _tick_spinner(self) -> None:
        if not self._active_work_count():
            if self._state.spinner_index != 0:
                self._state.spinner_index = 0
                self._refresh_status_bar()
            return
        self._state.spinner_index = (self._state.spinner_index + 1) % len(self._spinner_frames)
        self._refresh_status_bar()

    def _safe_refresh(self) -> None:
        refresh = getattr(self.__class__, "_perform_auto_refresh", None)
        if callable(refresh):
            refresh(self)

    def action_show_chat(self) -> None:
        self.current_tab = 0
        self._switch_tab("chat-panel")

    def action_show_overview(self) -> None:
        self.current_tab = 1
        self._switch_tab("overview-panel")

    def action_show_tasks(self) -> None:
        self.current_tab = 2
        self._switch_tab("tasks-panel")

    def action_show_skills(self) -> None:
        self.current_tab = 3
        self._switch_tab("skills-panel")
        self._refresh_skills_table()

    def action_show_history(self) -> None:
        self.current_tab = 4
        self._switch_tab("history-panel")

    def _switch_tab(self, panel_id: str) -> None:
        for panel in [
            "chat-panel",
            "overview-panel",
            "tasks-panel",
            "skills-panel",
            "history-panel",
        ]:
            widget = self.query_one(f"#{panel}", ScrollableContainer)
            widget.display = panel == panel_id

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id
        if tab_id == "tab-chat":
            self.action_show_chat()
        elif tab_id == "tab-overview":
            self.action_show_overview()
        elif tab_id == "tab-tasks":
            self.action_show_tasks()
        elif tab_id == "tab-skills":
            self.action_show_skills()
        elif tab_id == "tab-history":
            self.action_show_history()

    def action_refresh(self) -> None:
        self._safe_refresh()
        self._state.log("🔄 Manual refresh triggered")

    def action_clear_log(self) -> None:
        log = self.query_one("#evolution-log", RichLog)
        log.clear()
        self._state.audit_log.clear()
        self._log_cursor = 0
        self._state.log("🗑️ Log cleared")
        self._refresh_overview()

    def action_new_task(self) -> None:
        self.query_one("#goal-input", Input).focus()

    def action_help(self) -> None:
        help_text = """
# 📖 Keyboard Shortcuts

- `Ctrl+1`: Chat panel
- `Ctrl+2`: Overview panel
- `Ctrl+3`: Tasks panel  
- `Ctrl+4`: Skills panel
- `Ctrl+5`: History panel
- `Ctrl+R`: Refresh all
- `Ctrl+L`: Clear log
- `Ctrl+N`: New task
- `Ctrl+Q`: Quit
- `F1`: This help
- `Enter`: Submit goal
- `Esc`: Cancel input
        """
        self.notify(help_text, title="Help", timeout=10)

    async def _handle_event(self, orchestrator: Orchestrator, event: dict[str, Any]) -> None:
        self._state.apply_event(event)
        # Schedule UI updates on the app loop to avoid any thread/context issues.
        self.call_later(self._flush_audit_log)
        self.call_later(self._safe_refresh)

        if str(event.get("type", "")).strip().lower() == "approval_required":
            self.call_later(self._present_approval, orchestrator, event)

    def _present_approval(self, orchestrator: Orchestrator, event: dict[str, Any]) -> None:
        request_id = str(event.get("request_id", "")).strip()
        action = str(event.get("action_type", "action"))
        risk = str(event.get("risk_level", "unknown"))
        context = dict(event.get("context", {}) or {})

        def _resolve(approved: bool) -> None:
            if approved:
                orchestrator.approval_gate.approve(
                    request_id, approver="tui-user", notes="approved_in_textual"
                )
                self._state.log(f"✓ Confirmed {request_id}")
            else:
                orchestrator.approval_gate.deny(
                    request_id, reason="denied_in_textual", approver="tui-user"
                )
                self._state.log(f"✗ Declined {request_id}")
            self._flush_audit_log()
            self._safe_refresh()

        self.push_screen(
            ApprovalScreen(
                request_id=request_id,
                action=action,
                risk=risk,
                context=context,
            ),
            _resolve,
        )

    def _chat_system_prompt(self) -> str:
        return (
            "You are ARCHON, an interactive chat agent. Talk with the user naturally, "
            "use tools only when they move the task forward, and prefer concise, "
            "practical answers. You can inspect the filesystem, run commands inside "
            "the allowed roots, and use Baileys tools for WhatsApp actions when useful."
        )

    async def _ensure_chat_session(self) -> ChatSession:
        if self._chat_runtime is None:
            self._chat_runtime = build_chat_runtime(
                config=self._config,
                context=dict(self._state.context),
                system_prompt=self._chat_system_prompt(),
            )
        if self._chat_session is None:
            self._chat_session = self._chat_runtime.new_session(
                context=dict(self._state.context),
                system_prompt=self._chat_system_prompt(),
                session_id="tui",
            )
        return self._chat_session

    async def _handle_chat_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "")).strip().lower()
        if event_type == "turn_started":
            self._state.activity = "Agent planning reply"
        elif event_type == "tool_call":
            name = str(event.get("name", "tool"))
            raw_args = event.get("arguments", {})
            args_preview = json.dumps(raw_args, ensure_ascii=False)
            if len(args_preview) > 180:
                args_preview = args_preview[:177] + "..."
            self._state.activity = f"Using {name}"
            self._state.log(f"🛠️ {name}: {args_preview}")
        elif event_type == "tool_result":
            name = str(event.get("name", "tool"))
            ok = bool(event.get("ok", False))
            output = str(event.get("output", "")).replace("\n", " ").strip()
            if len(output) > 180:
                output = output[:177] + "..."
            self._state.log(f"{'✅' if ok else '❌'} {name}: {output}")
        elif event_type == "turn_completed":
            self._state.activity = ""
        self._flush_audit_log()
        self._safe_refresh()

    async def _run_chat_goal(self, goal: str) -> None:
        try:
            session = await self._ensure_chat_session()
            self._state.activity = "Agent planning reply"
            self._safe_refresh()
            result = await session.send(message=goal, event_sink=self._handle_chat_event)
        except Exception as exc:
            detail = str(exc) or repr(exc)
            self._state.log(f"❌ Chat failed: {detail}")
            self._state.log("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            self.notify(f"Chat failed: {detail}", title="Error", timeout=5, severity="error")
            self._flush_audit_log()
            return

        budget_limit = float(self._config.byok.budget_per_task_usd or 0.0)
        self._state.total_spent_usd += result.cost_usd
        self._state.total_budget_usd = max(self._state.total_budget_usd, budget_limit)
        self._state.history.append(
            TaskHistory(
                task_id=result.turn_id,
                goal=goal,
                mode="chat",
                confidence=100 if result.reply else 0,
                spent_usd=result.cost_usd,
                budget_usd=budget_limit,
            )
        )
        self._state.log(f"🤖 Archon: {result.reply or '[no reply]'}")
        self.notify("Reply ready", title="Archon", timeout=3, severity="information")
        self._flush_audit_log()
        self._state.activity = ""
        self._safe_refresh()

    async def _run_goal(self, goal: str) -> None:
        if self._state.mode == "chat":
            await self._run_chat_goal(goal)
            return

        orchestrator: Orchestrator | None = None
        current_task_id: str | None = None
        try:
            orchestrator = Orchestrator(config=self._config)
            self._state.log("⏳ Task starting…")
            self._flush_audit_log()

            async def event_sink(event: dict[str, Any]) -> None:
                try:
                    nonlocal current_task_id
                    if str(event.get("type", "")).strip().lower() == "task_started":
                        current_task_id = str(event.get("task_id") or "").strip() or None
                    await self._handle_event(orchestrator, event)
                except Exception as exc:
                    self._state.log(f"⚠️ Event handler error: {exc}")
                    self._flush_audit_log()

            timeout_s = float(os.getenv("ARCHON_TASK_TIMEOUT_S", "300") or 300)
            result = await asyncio.wait_for(
                orchestrator.execute(
                    goal=goal,
                    mode=self._resolve_mode(self._state.mode),
                    context=dict(self._state.context),
                    event_sink=event_sink,
                ),
                timeout=timeout_s,
            )
        except Exception as exc:
            detail = str(exc) or repr(exc)
            self._state.log(f"❌ Task failed: {detail}")
            self._state.log("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            if current_task_id and current_task_id in self._state.active_tasks:
                task = self._state.active_tasks.pop(current_task_id)
                task.status = "failed"
                task.progress = 1.0
                self._state.history.append(
                    TaskHistory(
                        task_id=task.task_id,
                        goal=task.goal,
                        mode=task.mode,
                        confidence=task.confidence or 0,
                        spent_usd=task.spent_usd,
                        budget_usd=task.budget_usd,
                    )
                )
            self.notify(f"Task failed: {detail}", title="Error", timeout=5, severity="error")
            self._flush_audit_log()
        else:
            self._state.log(f"✅ Result ({result.task_id}): {result.final_answer[:100]}...")
            self.notify(
                f"Task completed: {result.final_answer[:50]}...",
                title="Success",
                timeout=3,
                severity="information",
            )
            self._flush_audit_log()
        finally:
            if orchestrator is not None:
                await orchestrator.aclose()
            self._safe_refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        goal = event.value.strip()
        if not goal:
            return
        event.input.value = ""
        self._state.log(f"👤 You: {goal}")
        self._flush_audit_log()
        self._schedule_goal(goal)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            input_widget = self.query_one("#goal-input", Input)
            goal = input_widget.value.strip()
            if goal:
                input_widget.value = ""
                self._state.log(f"👤 You: {goal}")
                self._flush_audit_log()
                self._schedule_goal(goal)

    def _schedule_goal(self, goal: str) -> None:
        """Schedule goal execution on the app event loop and capture errors."""
        if self._pending_tasks or (self._state.mode != "chat" and self._state.active_tasks):
            self._state.log("⏸️ Archon is already busy. Please wait for the current turn to finish.")
            self._flush_audit_log()
            return
        if self._state.mode == "chat":
            self._state.log("💬 Sending message to Archon...")
        else:
            self._state.log("🧭 Scheduling task...")
        self._flush_audit_log()

        async def _runner() -> None:
            await self._run_goal(goal)

        def _attach(task: asyncio.Task[None]) -> None:
            self._pending_tasks.add(task)

            def _done(t: asyncio.Task[None]) -> None:
                self._pending_tasks.discard(t)
                if t.cancelled():
                    self._state.log("⚠️ Task cancelled")
                    self._flush_audit_log()
                    return
                exc = t.exception()
                if exc is not None:
                    self._state.log(f"❌ Task exception: {exc}")
                    self._state.log(traceback.format_exc())
                    self._flush_audit_log()

            task.add_done_callback(lambda t: self.call_later(_done, t))

        try:
            task = asyncio.create_task(_runner())
            _attach(task)
        except RuntimeError:
            # If no running loop, defer to the app loop.
            self.call_later(lambda: _attach(asyncio.create_task(_runner())))

    def _resolve_mode(self, mode: str) -> TaskMode:
        if mode == "tools":
            return "single"
        return "debate"


def _swarm_stage_label(agent: str, skill: str | None) -> str:
    agent_name = str(agent or "Agent")
    name = agent_name.lower()
    if "planner" in name:
        return "Planner drafting plan"
    if "skill" in name:
        return f"Skill running {skill or ''}".strip()
    if "validator" in name:
        return "Validator checking facts"
    if "synth" in name:
        return "Synthesizer composing final answer"
    return f"{agent_name} working"


async def run_agentic_tui(
    *,
    config: ArchonConfig,
    initial_mode: str = "chat",
    initial_context: dict[str, Any] | None = None,
    config_path: str = "config.archon.yaml",
    onboarding: object | None = None,
    show_launcher: bool = False,
) -> None:
    """Run the enhanced Textual-based ARCHON operator dashboard."""

    del onboarding, show_launcher
    app = ArchonTuiApp(
        config=config,
        initial_mode=initial_mode,
        initial_context=dict(initial_context or {}),
        config_path=config_path,
    )
    await app.run_async()
