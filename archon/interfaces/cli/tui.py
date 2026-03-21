"""Enhanced Textual-based terminal UI for ARCHON orchestration sessions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Button,
    Input,
    Markdown,
    RichLog,
    Static,
    Header,
    Footer,
    ProgressBar,
    Tabs,
    Tab,
    DataTable,
    Label,
    Rule,
)
from textual.screen import ModalScreen
from textual.reactive import reactive
from textual.timer import Timer

from archon.config import ArchonConfig
from archon.core.orchestrator import Orchestrator
from archon.core.types import TaskMode
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

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.audit_log.append(f"[{timestamp}] {message}")

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
            self.log(f"⚡ Task started {task_id} ({self.active_tasks[task_id].mode})")
            return

        if event_type in {"agent_start", "agent_end", "debate_round_completed"}:
            task_id = str(event.get("task_id", "")).strip()
            task = self.active_tasks.get(task_id)
            if task is not None:
                task.agent = str(event.get("agent", "unknown"))
                if "confidence" in event:
                    task.confidence = int(event.get("confidence", 0) or 0)
                task.updated_at = time.time()
                # Update progress based on event type
                if event_type == "debate_round_completed":
                    round_num = int(event.get("round", 0) or 0)
                    total = int(event.get("total_rounds", 6) or 6)
                    task.progress = min(round_num / total, 0.9)
                    self.log(f"🔄 {event.get('agent', 'unknown')} round {round_num}/{total} complete")
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
            return

        if event_type == "approval_required":
            request_id = str(event.get("request_id", "")).strip()
            self.pending_approvals[request_id] = dict(event)
            self.log(f"⚠️ Confirmation needed: {event.get('action_type', 'action')} ({event.get('risk_level', 'unknown')})")
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
        risk_color = "#ff6b6b" if self._risk == "high" else "#ffd93d" if self._risk == "medium" else "#6bcb77"
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

    Tabs > Tab --active {
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

    #log-panel {
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
        padding: 1 2;
        background: #1a1a2e;
        border-top: solid #2a2a2a;
        dock: bottom;
    }

    #input-container {
        height: 3;
        min-height: 3;
    }

    #goal-input {
        width: 1fr;
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
        margin-left: 1;
        background: #f5b86c;
        color: #0b0b0b;
        text-style: bold;
    }

    #status-bar {
        height: 1;
        color: #8a8a8a;
        padding: 0 1;
        dock: bottom;
    }

    #budget-display {
        height: 1;
        color: #6bcb77;
        padding: 0 1;
        dock: bottom;
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
        Binding("ctrl+1", "show_overview", "Overview"),
        Binding("ctrl+2", "show_tasks", "Tasks"),
        Binding("ctrl+3", "show_history", "History"),
        Binding("ctrl+4", "show_log", "Log"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("ctrl+l", "clear_log", "Clear"),
        Binding("ctrl+n", "new_task", "New"),
        Binding("f1", "help", "Help"),
    ]

    current_tab = reactive(0)

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
        self._state = TuiState(
            mode=initial_mode,
            context=dict(initial_context),
        )
        self._log_cursor = 0
        self._pending_tasks: set[asyncio.Task[None]] = set()
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
                Tab("📊 Overview", id="tab-overview"),
                Tab("🔄 Tasks", id="tab-tasks"),
                Tab("📜 History", id="tab-history"),
                Tab("📝 Log", id="tab-log"),
                id="tabs-container",
            )
            
            with Container(id="content-area"):
                with ScrollableContainer(id="overview-panel"):
                    yield Markdown(id="overview-markdown")
                
                with ScrollableContainer(id="tasks-panel"):
                    yield DataTable(id="tasks-table")
                
                with ScrollableContainer(id="history-panel"):
                    yield DataTable(id="history-table")
                
                with ScrollableContainer(id="log-panel"):
                    yield RichLog(id="evolution-log", wrap=True, highlight=True, markup=True)
            
            with Container(id="input-bar"):
                yield Static(id="budget-display")
                with Horizontal(id="input-container"):
                    yield Input(placeholder="Enter goal and press Enter...", id="goal-input")
                    yield Button("Send", id="submit-btn", variant="primary")
            
            yield Static(id="status-bar")

    def on_mount(self) -> None:
        self._state.log("🚀 ARCHON online - Ready for orchestration")
        self._flush_audit_log()
        self._refresh_overview()
        self._refresh_budget_display()
        self._refresh_status_bar()
        self._setup_data_tables()
        self.query_one("#goal-input", Input).focus()
        self.set_interval(2.0, self._auto_refresh)

    def _setup_data_tables(self) -> None:
        tasks_table = self.query_one("#tasks-table", DataTable)
        tasks_table.add_columns("Task ID", "Goal", "Mode", "Status", "Agent", "Progress", "Confidence", "Spent")
        
        history_table = self.query_one("#history-table", DataTable)
        history_table.add_columns("Task ID", "Goal", "Mode", "Confidence", "Spent", "Completed")

    def _flush_audit_log(self) -> None:
        log = self.query_one("#evolution-log", RichLog)
        while self._log_cursor < len(self._state.audit_log):
            log.write(self._state.audit_log[self._log_cursor])
            self._log_cursor += 1
        log.scroll_end(animate=False)

    def _build_overview_markdown(self) -> str:
        config_exists = Path(self._config_path).exists()
        version = resolve_version()
        
        lines = [
            "# 🤖 ARCHON Control Panel",
            "",
            f"**Status**: {'🟢 Online' if config_exists else '🔴 Config Missing'}",
            f"**Version**: {version}",
            f"**Mode**: {self._state.mode}",
            "",
            "## 📈 Quick Stats",
            "",
            f"- Active Tasks: {len(self._state.active_tasks)}",
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
        
        lines.extend([
            "",
            "## ⚙️ Context",
            "",
        ])
        
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

    def _refresh_budget_display(self) -> None:
        spent = self._state.total_spent_usd
        limit = self._state.total_budget_usd
        
        if limit > 0:
            remaining = max(limit - spent, 0.0)
            percentage = (spent / limit) * 100
            color = "#6bcb77" if percentage < 50 else "#ffd93d" if percentage < 80 else "#ff6b6b"
            text = f"💰 Budget: ${spent:.2f} / ${limit:.2f} ({percentage:.1f}%) - ${remaining:.2f} remaining"
        else:
            text = f"💰 Budget: ${spent:.2f} used"
        
        self.query_one("#budget-display", Static).update(text)

    def _refresh_status_bar(self) -> None:
        status = f"📡 Connected | 🎯 Mode: {self._state.mode} | 📝 Tasks: {len(self._state.active_tasks)} active, {len(self._state.history)} completed"
        self.query_one("#status-bar", Static).update(status)

    def _auto_refresh(self) -> None:
        self._refresh_overview()
        self._refresh_tasks_table()
        self._refresh_history_table()
        self._refresh_budget_display()
        self._refresh_status_bar()

    def action_show_overview(self) -> None:
        self.current_tab = 0
        self._switch_tab("overview-panel")

    def action_show_tasks(self) -> None:
        self.current_tab = 1
        self._switch_tab("tasks-panel")

    def action_show_history(self) -> None:
        self.current_tab = 2
        self._switch_tab("history-panel")

    def action_show_log(self) -> None:
        self.current_tab = 3
        self._switch_tab("log-panel")

    def _switch_tab(self, panel_id: str) -> None:
        for panel in ["overview-panel", "tasks-panel", "history-panel", "log-panel"]:
            widget = self.query_one(f"#{panel}", ScrollableContainer)
            widget.display = (panel == panel_id)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id
        if tab_id == "tab-overview":
            self.action_show_overview()
        elif tab_id == "tab-tasks":
            self.action_show_tasks()
        elif tab_id == "tab-history":
            self.action_show_history()
        elif tab_id == "tab-log":
            self.action_show_log()

    def action_refresh(self) -> None:
        self._auto_refresh()
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

- `Ctrl+1`: Overview panel
- `Ctrl+2`: Tasks panel  
- `Ctrl+3`: History panel
- `Ctrl+4`: Log panel
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
        self._flush_audit_log()
        self._auto_refresh()
        
        if str(event.get("type", "")).strip().lower() == "approval_required":
            self._present_approval(orchestrator, event)

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
            self._auto_refresh()

        self.push_screen(
            ApprovalScreen(
                request_id=request_id,
                action=action,
                risk=risk,
                context=context,
            ),
            _resolve,
        )

    async def _run_goal(self, goal: str) -> None:
        orchestrator = Orchestrator(config=self._config)
        try:
            result = await orchestrator.execute(
                goal=goal,
                mode=self._resolve_mode(self._state.mode),
                context=dict(self._state.context),
                event_sink=lambda event: self._handle_event(orchestrator, event),
            )
        except Exception as exc:
            detail = str(exc) or repr(exc)
            self._state.log(f"❌ Task failed: {detail}")
            self.notify(f"Task failed: {detail}", title="Error", timeout=5, severity="error")
            self._flush_audit_log()
        else:
            self._state.log(f"✅ Result ({result.task_id}): {result.final_answer[:100]}...")
            self.notify(f"Task completed: {result.final_answer[:50]}...", title="Success", timeout=3, severity="information")
            self._flush_audit_log()
        finally:
            await orchestrator.aclose()
            self._auto_refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        goal = event.value.strip()
        if not goal:
            return
        event.input.value = ""
        self._state.log(f"🎯 Goal received: {goal}")
        self._flush_audit_log()
        task = asyncio.create_task(self._run_goal(goal))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            input_widget = self.query_one("#goal-input", Input)
            goal = input_widget.value.strip()
            if goal:
                input_widget.value = ""
                self._state.log(f"🎯 Goal received: {goal}")
                task = asyncio.create_task(self._run_goal(goal))
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)

    def _resolve_mode(self, mode: str) -> TaskMode:
        if mode != "auto":
            return mode  # type: ignore
        return "debate"


async def run_agentic_tui(
    *,
    config: ArchonConfig,
    initial_mode: str = "auto",
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
