"""Textual-based terminal UI for ARCHON orchestration sessions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, RichLog, Static, TabbedContent, TabPane

from archon.config import ArchonConfig
from archon.core.orchestrator import Orchestrator
from archon.versioning import resolve_version


@dataclass(slots=True)
class TaskHistory:
    task_id: str
    goal: str
    mode: str
    confidence: int
    spent_usd: float
    budget_usd: float


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
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class TuiState:
    mode: str
    live_provider_calls: bool
    context: dict[str, Any]
    active_tasks: dict[str, ActiveTask] = field(default_factory=dict)
    history: list[TaskHistory] = field(default_factory=list)
    pending_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    audit_log: list[str] = field(default_factory=list)

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
            )
            self.log(f"Task started {task_id} ({self.active_tasks[task_id].mode}).")
            return

        if event_type in {"agent_start", "agent_end", "debate_round_completed"}:
            task_id = str(event.get("task_id", "")).strip()
            task = self.active_tasks.get(task_id)
            if task is not None:
                task.agent = str(event.get("agent", "unknown"))
                if "confidence" in event:
                    task.confidence = int(event.get("confidence", 0) or 0)
                task.updated_at = time.time()
            if event_type == "debate_round_completed":
                round_num = int(event.get("round", 0) or 0)
                total = int(event.get("total_rounds", 0) or 0)
                self.log(f"{event.get('agent', 'unknown')} round {round_num}/{total} complete.")
            return

        if event_type == "cost_update":
            task_id = str(event.get("task_id", "")).strip()
            task = self.active_tasks.get(task_id)
            if task is not None:
                task.spent_usd = float(event.get("spent", 0.0) or 0.0)
                task.budget_usd = float(event.get("budget", 0.0) or 0.0)
                task.updated_at = time.time()
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
            self.log(f"Task completed {task_id} ({confidence}%).")
            return

        if event_type == "approval_required":
            request_id = str(event.get("request_id", "")).strip()
            self.pending_approvals[request_id] = dict(event)
            self.log(
                "Approval required "
                f"{event.get('action_type', 'action')} "
                f"({event.get('risk_level', 'unknown')})."
            )
            return

        if event_type == "approval_resolved":
            request_id = str(event.get("request_id", "")).strip()
            approved = bool(event.get("approved", False))
            self.pending_approvals.pop(request_id, None)
            self.log(f"Approval resolved {request_id} approved={approved}.")
            return


class ApprovalScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "deny", "Deny"),
    ]

    def __init__(self, *, request_id: str, action: str, risk: str, context: dict[str, Any]):
        super().__init__()
        self._request_id = request_id
        self._action = action
        self._risk = risk
        self._context = context

    def compose(self) -> ComposeResult:
        summary = (
            f"Approval required: {self._action}\n"
            f"Risk: {self._risk}\n"
            f"Request: {self._request_id}\n"
            f"Context: {self._context}"
        )
        yield Container(
            Static(summary, id="approval-summary"),
            Horizontal(
                Button("Approve", id="approve"),
                Button("Deny", id="deny"),
                id="approval-buttons",
            ),
            id="approval-modal",
        )

    def action_deny(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")


class ArchonTuiApp(App[None]):
    CSS = """
    Screen {
        background: #0f1116;
        color: #e6e6e6;
    }

    #root {
        height: 100%;
    }

    TabbedContent {
        height: 1fr;
    }

    #system-status {
        padding: 1 2;
    }

    #input-bar {
        height: 3;
        padding: 0 1;
        background: #151a22;
    }

    #goal-input {
        border: round #2d3642;
        background: #0f1116;
    }

    DataTable {
        border: round #2d3642;
        background: #0f1116;
    }

    RichLog {
        border: round #2d3642;
        background: #0f1116;
    }

    #approval-modal {
        width: 70%;
        height: auto;
        padding: 1 2;
        border: round #3c4656;
        background: #121620;
    }

    #approval-buttons {
        margin-top: 1;
        height: 3;
    }

    #approval-summary {
        padding-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("tab", "next_tab", "Next Tab"),
        Binding("shift+tab", "prev_tab", "Previous Tab"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    TAB_IDS = ("system", "tasks", "cost", "evolution")

    def __init__(
        self,
        *,
        config: ArchonConfig,
        initial_mode: str,
        live_provider_calls: bool,
        initial_context: dict[str, Any],
        config_path: str,
    ) -> None:
        super().__init__()
        self._config = config
        self._config_path = config_path
        self._state = TuiState(
            mode=initial_mode,
            live_provider_calls=live_provider_calls,
            context=dict(initial_context),
        )
        self._log_cursor = 0
        self._pending_tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with TabbedContent(id="tabs"):
                with TabPane("System Status", id="system"):
                    yield Static(id="system-status")
                with TabPane("Active Tasks", id="tasks"):
                    yield DataTable(id="tasks-table")
                with TabPane("Cost Summary", id="cost"):
                    yield DataTable(id="cost-table")
                with TabPane("Evolution Log", id="evolution"):
                    yield RichLog(id="evolution-log", wrap=True)
            with Container(id="input-bar"):
                yield Input(placeholder="Send a goal to ARCHON...", id="goal-input")

    def on_mount(self) -> None:
        self._init_tables()
        self._state.log("ARCHON online. Provide a goal to start orchestration.")
        self._flush_audit_log()
        self._refresh_system_status()
        self._refresh_live_views()
        self.set_interval(2.0, self._refresh_live_views)
        self.query_one("#goal-input", Input).focus()

    def _init_tables(self) -> None:
        tasks_table = self.query_one("#tasks-table", DataTable)
        tasks_table.add_columns("Task", "Goal", "Mode", "Status", "Agent", "Conf", "Spent")
        costs_table = self.query_one("#cost-table", DataTable)
        costs_table.add_columns("Task", "Budget", "Spent", "Remaining")

    def action_next_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        current = getattr(tabs, "active", self.TAB_IDS[0])
        if current not in self.TAB_IDS:
            tabs.active = self.TAB_IDS[0]
            return
        index = (self.TAB_IDS.index(current) + 1) % len(self.TAB_IDS)
        tabs.active = self.TAB_IDS[index]

    def action_prev_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        current = getattr(tabs, "active", self.TAB_IDS[0])
        if current not in self.TAB_IDS:
            tabs.active = self.TAB_IDS[0]
            return
        index = (self.TAB_IDS.index(current) - 1) % len(self.TAB_IDS)
        tabs.active = self.TAB_IDS[index]

    def _flush_audit_log(self) -> None:
        log = self.query_one("#evolution-log", RichLog)
        while self._log_cursor < len(self._state.audit_log):
            log.write(self._state.audit_log[self._log_cursor])
            self._log_cursor += 1

    def _refresh_system_status(self) -> None:
        status = self.query_one("#system-status", Static)
        config_exists = Path(self._config_path).exists()
        provider_lines = [
            f"primary: {self._config.byok.primary}",
            f"coding: {self._config.byok.coding}",
            f"vision: {self._config.byok.vision}",
            f"fast: {self._config.byok.fast}",
            f"embedding: {self._config.byok.embedding}",
            f"fallback: {self._config.byok.fallback}",
        ]
        lines = [
            f"Config: {self._config_path} ({'found' if config_exists else 'missing'})",
            f"Mode: {self._state.mode}",
            f"Live providers: {'on' if self._state.live_provider_calls else 'off'}",
            f"Version: {resolve_version()}",
            f"Context keys: {', '.join(sorted(self._state.context)) or 'none'}",
            "Providers:",
            *[f"- {line}" for line in provider_lines],
        ]
        status.update("\n".join(lines))

    def _refresh_tasks_table(self) -> None:
        table = self.query_one("#tasks-table", DataTable)
        table.clear()
        for task in self._state.active_tasks.values():
            table.add_row(
                task.task_id,
                task.goal,
                task.mode,
                task.status,
                task.agent,
                "-" if task.confidence is None else f"{task.confidence}%",
                f"${task.spent_usd:.4f}",
            )

    def _refresh_cost_table(self) -> None:
        table = self.query_one("#cost-table", DataTable)
        table.clear()
        rows: list[tuple[str, float, float, float]] = []
        for task in self._state.active_tasks.values():
            remaining = max(task.budget_usd - task.spent_usd, 0.0)
            rows.append((task.task_id, task.budget_usd, task.spent_usd, remaining))
        for task in self._state.history:
            remaining = max(task.budget_usd - task.spent_usd, 0.0)
            rows.append((task.task_id, task.budget_usd, task.spent_usd, remaining))
        for task_id, budget, spent, remaining in rows:
            table.add_row(
                task_id,
                f"${budget:.4f}" if budget else "-",
                f"${spent:.4f}",
                f"${remaining:.4f}" if budget else "-",
            )

    def _refresh_live_views(self) -> None:
        self._refresh_tasks_table()
        self._refresh_cost_table()

    async def _handle_event(self, orchestrator: Orchestrator, event: dict[str, Any]) -> None:
        self._state.apply_event(event)
        self._flush_audit_log()
        self._refresh_live_views()
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
                self._state.log(f"Approved {request_id}.")
            else:
                orchestrator.approval_gate.deny(
                    request_id, reason="denied_in_textual", approver="tui-user"
                )
                self._state.log(f"Denied {request_id}.")
            self._flush_audit_log()
            self._refresh_live_views()

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
        orchestrator = Orchestrator(
            config=self._config,
            live_provider_calls=self._state.live_provider_calls,
        )
        try:
            result = await orchestrator.execute(
                goal=goal,
                mode=_resolve_mode(self._state.mode),
                context=dict(self._state.context),
                event_sink=lambda event: self._handle_event(orchestrator, event),
            )
        except Exception as exc:
            self._state.log(f"Task failed: {exc}")
            self._flush_audit_log()
        else:
            self._state.log(f"Result ({result.task_id}): {result.final_answer}")
            self._flush_audit_log()
        finally:
            await orchestrator.aclose()
            self._refresh_live_views()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        goal = event.value.strip()
        if not goal:
            return
        event.input.value = ""
        self._state.log(f"Goal received: {goal}")
        self._flush_audit_log()
        task = asyncio.create_task(self._run_goal(goal))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)


def _resolve_mode(mode: str) -> str:
    if mode != "auto":
        return mode
    return "debate"


async def run_agentic_tui(
    *,
    config: ArchonConfig,
    initial_mode: str = "auto",
    live_provider_calls: bool = False,
    initial_context: dict[str, Any] | None = None,
    config_path: str = "config.archon.yaml",
    onboarding: object | None = None,
    show_launcher: bool = False,
) -> None:
    """Run the Textual-based ARCHON operator dashboard."""

    del onboarding, show_launcher
    app = ArchonTuiApp(
        config=config,
        initial_mode=initial_mode,
        live_provider_calls=live_provider_calls,
        initial_context=dict(initial_context or {}),
        config_path=config_path,
    )
    await app.run_async()
