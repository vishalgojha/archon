"""Enhanced Textual-based terminal UI for ARCHON orchestration sessions."""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import sqlite3
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ════════════════════════════════════════════════════════════════════════════════
# CYBERPUNK VISUAL EFFECTS ENGINE - PARTICLES, RADAR, HOLOGRAPHIC UI
# ════════════════════════════════════════════════════════════════════════════════

PARTICLE_COLORS = ["#00ffff", "#ff00ff", "#00ff88", "#f5b86c", "#ff4444"]


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    color: str
    size: int
    life: float


class ParticleSystem:
    """Animated particle system for visual effects."""
    
    def __init__(self, width: int = 80, height: int = 24):
        self.width = width
        self.height = height
        self.particles: list[Particle] = []
    
    def spawn(self, count: int = 5) -> None:
        for _ in range(count):
            self.particles.append(Particle(
                x=random.random() * self.width,
                y=random.random() * self.height,
                vx=(random.random() - 0.5) * 0.5,
                vy=(random.random() - 0.5) * 0.5,
                color=random.choice(PARTICLE_COLORS),
                size=random.randint(1, 3),
                life=random.random() * 100 + 50
            ))
    
    def update(self) -> list[Particle]:
        for p in self.particles[:]:
            p.x += p.vx
            p.y += p.vy
            p.life -= 1
            if p.life <= 0 or p.x < 0 or p.x >= self.width or p.y < 0 or p.y >= self.height:
                self.particles.remove(p)
        if len(self.particles) < 20:
            self.spawn(3)
        return self.particles
    
    def render(self) -> str:
        grid = [[" " for _ in range(self.width)] for _ in range(self.height)]
        for p in self.particles:
            gx, gy = int(p.x), int(p.y)
            if 0 <= gx < self.width and 0 <= gy < self.height:
                char = "●" if p.size > 1 else "·"
                grid[gy][gx] = f"[{p.color}]{char}[/{p.color}]"
        return "\n".join("".join(row) for row in grid)


@dataclass
class RadarBlip:
    angle: float
    distance: float
    label: str = ""


class RadarWidget:
    """Animated radar display for tracking agents/tasks."""
    
    def __init__(self, radius: int = 10):
        self.radius = radius
        self.blips: list[RadarBlip] = []
        self.sweep_angle = 0.0
    
    def add_blip(self, angle: float, distance: float, label: str = "") -> None:
        self.blips.append(RadarBlip(angle, distance, label))
    
    def clear_blips(self) -> None:
        self.blips.clear()
    
    def update(self) -> None:
        self.sweep_angle = (self.sweep_angle + 5) % 360
    
    def render(self) -> str:
        lines = []
        center = self.radius + 1
        for y in range(self.radius * 2 + 3):
            line = ""
            for x in range(self.radius * 2 + 3):
                dist = ((x - center) ** 2 + (y - center) ** 2) ** 0.5
                if dist <= self.radius:
                    if dist < 1:
                        line += "◎"
                    elif dist < self.radius * 0.3:
                        line += "○"
                    elif dist < self.radius * 0.6:
                        line += "◔"
                    elif dist < self.radius * 0.9:
                        line += "◑"
                    else:
                        line += "◉"
                else:
                    line += " "
            lines.append(line)
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════════
# MAIN TUI IMPORTS
# ════════════════════════════════════════════════════════════════════════════════

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


def _get_workspace_context() -> dict[str, Any]:
    """Get current workspace context (git branch, dir, modified files)."""
    ctx: dict[str, Any] = {
        "dir": str(Path.cwd()),
        "git_branch": None,
        "git_dirty": False,
        "git_ahead": 0,
        "modified_files": [],
    }

    # Check for git
    git = shutil.which("git")
    if not git:
        return ctx

    try:
        # Get branch
        result = subprocess.run(
            [git, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2, cwd=ctx["dir"],
        )
        if result.returncode == 0:
            ctx["git_branch"] = result.stdout.strip()

        # Get dirty status
        result = subprocess.run(
            [git, "status", "--porcelain"],
            capture_output=True, text=True, timeout=2, cwd=ctx["dir"],
        )
        if result.returncode == 0:
            lines = [line for line in result.stdout.strip().splitlines() if line]
            ctx["git_dirty"] = len(lines) > 0
            ctx["modified_files"] = lines[:10]  # Limit to 10

        # Get ahead count
        result = subprocess.run(
            [git, "rev-list", "--count", "HEAD..@{upstream}"],
            capture_output=True, text=True, timeout=2, cwd=ctx["dir"],
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            ctx["git_ahead"] = int(result.stdout.strip())

    except Exception:
        pass

    return ctx


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


class CommandPaletteScreen(ModalScreen[str | None]):
    """VS Code-style command palette."""

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("enter", "select", "Select"),
    ]

    COMMANDS: list[tuple[str, str, str]] = [
        ("chat", "💬", "Start interactive chat"),
        ("overview", "📊", "Show overview panel"),
        ("tasks", "🔄", "Show tasks panel"),
        ("skills", "🧠", "Show skills panel"),
        ("history", "📜", "Show history panel"),
        ("ollama", "🦙", "Show Ollama configuration"),
        ("providers", "🔌", "List providers"),
        ("validate", "✓", "Validate config"),
        ("config", "⚙️", "Edit configuration"),
        ("files", "📁", "Open file browser"),
        ("clear", "🗑️", "Clear chat log"),
    ]

    def __init__(self, *, commands: list[tuple[str, str, str]] | None = None):
        super().__init__()
        self._commands = commands or self.COMMANDS
        self._filtered = list(self._commands)
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        yield Container(
            Input(placeholder="Type to search commands...", id="palette-input"),
            Label(id="palette-results"),
            id="command-palette",
        )

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()
        self._render_results()

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.lower().strip()
        if not query:
            self._filtered = list(self._commands)
        else:
            self._filtered = [
                (name, icon, desc) for name, icon, desc in self._commands
                if query in name.lower() or query in desc.lower()
            ]
        self._selected_index = 0
        self._render_results()

    def _render_results(self) -> None:
        lines = []
        for i, (name, icon, desc) in enumerate(self._filtered[:10]):
            marker = "▸" if i == self._selected_index else " "
            lines.append(f"{marker} {icon} [bold cyan]{name}[/] - {desc}")
        if not self._filtered:
            lines.append("[dim]No matching commands[/]")
        self.query_one("#palette-results", Label).update("\n".join(lines))

    def on_key(self, event) -> None:
        if event.key == "up":
            self._selected_index = max(0, self._selected_index - 1)
            self._render_results()
            event.prevent_default()
        elif event.key == "down":
            self._selected_index = min(len(self._filtered) - 1, self._selected_index + 1)
            self._render_results()
            event.prevent_default()
        elif event.key == "enter":
            self.action_select()
            event.prevent_default()

    def action_select(self) -> None:
        if self._filtered:
            self.dismiss(self._filtered[self._selected_index][0])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

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
    /* ═══════════════════════════════════════════════════════════════════════════════
       ARCHON CYBERPUNK TUI - VISUAL EXPERIENCE
    ═══════════════════════════════════════════════════════════════════════════════ */
    
    Screen {
        background: #050508;
        color: #e0e0e0;
    }

    Header {
        background: #0a0a15;
        color: #00ffff;
    }

    Footer {
        background: #0a0a15;
        color: #808090;
    }

    $surface: #0a0a15;
    $surface-hover: #151525;
    $surface-active: #1a1a2e;
    $text: #e0e0e0;
    $text-muted: #808090;
    $border: #2a2a4e;

    /* ─────────────────────────────────────────────────────────────────────────────
       ROOT LAYOUT
    ───────────────────────────────────────────────────────────────────────────── */
    #root {
        height: 100%;
        width: 100%;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       CYBERPUNK GLOW EFFECTS
    ───────────────────────────────────────────────────────────────────────────── */
    .glow-cyan {
        text-shadow: 0 0 10px #00ffff, 0 0 20px #00ffff, 0 0 30px #00ffff;
    }
    
    .glow-magenta {
        text-shadow: 0 0 10px #ff00ff, 0 0 20px #ff00ff, 0 0 30px #ff00ff;
    }
    
    .glow-gold {
        text-shadow: 0 0 10px #f5b86c, 0 0 20px #f5b86c;
    }
    
    .glow-green {
        text-shadow: 0 0 10px #00ff88, 0 0 20px #00ff88;
    }

    .glow-red {
        text-shadow: 0 0 10px #ff4444, 0 0 20px #ff4444;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       SCANLINES OVERLAY
    ───────────────────────────────────────────────────────────────────────────── */
    #scanlines {
        background: transparent;
        opacity: 0.03;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       BACKGROUND GRID
    ───────────────────────────────────────────────────────────────────────────── */
    #background-grid {
        background: #030308;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       PARTICLE CANVAS
    ───────────────────────────────────────────────────────────────────────────── */
    #particles {
        background: transparent;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       SIDEBAR NAVIGATION
    ───────────────────────────────────────────────────────────────────────────── */
    #sidebar {
        width: 80;
        min-width: 80;
        background: $surface;
        border-right: solid $border;
    }

    #sidebar-tabs {
        height: 100%;
        background: $surface;
    }

    #sidebar-tabs Tabs {
        background: $surface;
    }

    #sidebar-tabs Tabs > Tab {
        background: $surface;
        color: $text-muted;
        width: 100%;
        height: 60;
        padding: 8 0;
    }

    #sidebar-tabs Tabs > Tab:hover {
        background: $surface-hover;
        color: $text;
    }

    #sidebar-tabs Tabs > Tab.-active {
        background: $surface-active;
        color: #00ffff;
        border-left: 3px solid #00ffff;
    }

    #sidebar-tabs Tabs > Tab.-active > .tab--label {
        color: #00ffff;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       MAIN CONTENT AREA
    ───────────────────────────────────────────────────────────────────────────── */
    #main-area {
        height: 100%;
        width: 1fr;
        background: #080810;
    }

    #content-area {
        width: 1fr;
        height: 1fr;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       CHAT PANEL - FLOATING MESSAGES
    ───────────────────────────────────────────────────────────────────────────── */
    #chat-panel {
        width: 100%;
        height: 100%;
        padding: 1 2;
        background: transparent;
    }

    #evolution-log {
        background: rgba(10, 10, 20, 0.8);
        border: 1px solid rgba(0, 255, 255, 0.2);
        color: #c0c0d0;
        overflow-y: auto;
    }

    #evolution-log UserInput {
        color: #00ffff;
        text-style: bold;
    }

    #evolution-log BotResponse {
        color: #ff00ff;
    }

    #evolution-log SystemMessage {
        color: #f5b86c;
        text-style: italic;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       SIDE PANEL - HUD
    ───────────────────────────────────────────────────────────────────────────── */
    #side-panel {
        width: 320;
        min-width: 280;
        background: $surface;
        border-left: 2px solid #00ffff;
    }

    #side-panel-title {
        color: #00ffff;
        text-style: bold;
        text-align: center;
        padding: 1 0;
        background: rgba(0, 255, 255, 0.1);
        border-bottom: 1px solid rgba(0, 255, 255, 0.3);
    }

    #side-log {
        background: rgba(5, 5, 15, 0.9);
        border: 1px solid rgba(255, 0, 255, 0.2);
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       HUD ELEMENTS
    ───────────────────────────────────────────────────────────────────────────── */
    .hud-container {
        padding: 1;
        background: rgba(0, 0, 0, 0.3);
        border: 1px solid $border;
    }

    .hud-label {
        color: #00ffff;
        text-style: bold;
    }

    .hud-value {
        color: #ffffff;
    }

    .hud-bar-container {
        width: 100%;
        height: 12;
        background: #1a1a2e;
        border: 1px solid #2a2a4e;
    }

    .hud-bar {
        height: 100%;
        background: #00ff88;
    }

    .hud-bar-health {
        background: #ff00ff;
    }

    .hud-bar-energy {
        background: #0088ff;
    }

    .hud-bar-xp {
        background: #f5b86c;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       RADAR WIDGET
    ───────────────────────────────────────────────────────────────────────────── */
    #radar-container {
        width: 100%;
        height: 200;
        background: rgba(0, 20, 0, 0.5);
        border: 2px solid #00ff88;
    }

    #radar-sweep {
        background: rgba(0, 255, 136, 0.3);
    }

    #radar-blip {
        background: #00ff88;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       STATUS BARS - GAME STYLE
    ───────────────────────────────────────────────────────────────────────────── */
    .status-frame {
        border: 1px solid #2a2a4e;
        background: rgba(10, 10, 30, 0.8);
    }

    .status-frame-title {
        color: #f5b86c;
        text-style: bold;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       INPUT BAR
    ───────────────────────────────────────────────────────────────────────────── */
    #input-bar {
        height: 80;
        min-height: 80;
        padding: 0 2;
        background: $surface;
        border-top: 2px solid #00ffff;
    }

    #input-container {
        height: 60;
        min-height: 60;
    }

    #goal-input {
        width: 1fr;
        height: 50;
        border: 2px solid #00ffff;
        background: #0a0a15;
        color: #00ffff;
        padding: 0 1;
    }

    #goal-input:focus {
        border: 2px solid #ff00ff;
        box-shadow: 0 0 15px rgba(255, 0, 255, 0.5);
    }

    #submit-btn {
        width: 100;
        height: 50;
        background: #00aaaa;
        color: #000000;
        text-style: bold;
    }

    #submit-btn:hover {
        background: #aa0088;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       SUGGESTIONS
    ───────────────────────────────────────────────────────────────────────────── */
    #suggestions-panel {
        height: 40;
        background: $surface;
        border-top: 1px solid $border;
    }

    #suggestions-text {
        color: #808090;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       STATUS BAR
    ───────────────────────────────────────────────────────────────────────────── */
    #status-bar {
        height: 30;
        background: $surface;
        color: #00ff88;
        text-style: bold;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       DATA TABLES
    ───────────────────────────────────────────────────────────────────────────── */
    DataTable {
        background: #0a0a15;
        border: 1px solid #2a2a4e;
    }

    DataTable > .datatable--header {
        background: #1a1a3e;
        color: #00ffff;
    }

    DataTable > .datatable--cursor {
        background: rgba(0, 255, 255, 0.2);
    }

    DataTable > .datatable--row:hover {
        background: rgba(0, 255, 255, 0.1);
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       TABS
    ───────────────────────────────────────────────────────────────────────────── */
    #tabs-container {
        height: 50;
        dock: top;
        background: $surface;
        border-bottom: 2px solid #00ffff;
    }

    Tabs {
        background: $surface;
    }

    Tabs > Tab {
        background: $surface;
        color: $text-muted;
    }

    Tabs > Tab:hover {
        background: $surface-hover;
        color: $text;
    }

    Tabs > Tab.-active {
        background: rgba(0, 255, 255, 0.1);
        color: #00ffff;
        border-bottom: 3px solid #ff00ff;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       MARKDOWN
    ───────────────────────────────────────────────────────────────────────────── */
    Markdown {
        color: #c0c0d0;
        background: transparent;
    }

    Markdown H1 {
        color: #00ffff;
        text-style: bold;
        text-shadow: 0 0 10px #00ffff;
    }

    Markdown H2 {
        color: #ff00ff;
        text-style: bold;
    }

    Markdown H3 {
        color: #f5b86c;
    }

    Markdown Code {
        color: #00ff88;
        background: rgba(0, 255, 136, 0.1);
    }

    Markdown BlockQuote {
        color: #8080a0;
        border-left: 3px solid #00ffff;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       BUTTONS
    ───────────────────────────────────────────────────────────────────────────── */
    Button {
        background: #1a1a3e;
        color: #00ffff;
        border: 1px solid #00ffff;
    }

    Button:hover {
        background: #2a2a5e;
        border-color: #ff00ff;
    }

    Button:focus {
        border-color: #ff00ff;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       INPUT FIELDS
    ───────────────────────────────────────────────────────────────────────────── */
    Input {
        background: #0a0a15;
        color: #ffffff;
        border: 1px solid #2a2a4e;
    }

    Input:focus {
        border: 1px solid #00ffff;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       LABELS
    ───────────────────────────────────────────────────────────────────────────── */
    Label {
        color: #a0a0b0;
    }

    /* ─────────────────────────────────────────────────────────────────────────────
       SCROLLBARS
    ───────────────────────────────────────────────────────────────────────────── */
    ScrollableContainer {
        background: transparent;
    }

    """


    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+p", "command_palette", "Palette"),
        Binding("ctrl+1", "show_chat", "Chat"),
        Binding("ctrl+2", "show_overview", "Overview"),
        Binding("ctrl+3", "show_tasks", "Tasks"),
        Binding("ctrl+4", "show_skills", "Skills"),
        Binding("ctrl+5", "show_history", "History"),
        Binding("ctrl+6", "show_files", "Files"),
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
        
        # ════════════════════════════════════════════════════════════════════════
        # CYBERPUNK VISUAL EFFECTS - PARTICLES & RADAR
        # ════════════════════════════════════════════════════════════════════════
        self._particles = ParticleSystem(width=60, height=15)
        self._radar = RadarWidget(radius=8)
        self._holographic_glitch = 0
        self._effects_enabled = True

    def _tick_particles(self) -> None:
        """Update particle system for visual effects."""
        if not self._effects_enabled:
            return
        self._particles.update()
        self._radar.update()
        self._holographic_glitch = (self._holographic_glitch + 1) % 100

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
            with Horizontal(id="sidebar"):
                yield Tabs(
                    Tab("💬", id="tab-chat", title="Chat"),
                    Tab("📊", id="tab-overview", title="Overview"),
                    Tab("🔄", id="tab-tasks", title="Tasks"),
                    Tab("🧠", id="tab-skills", title="Skills"),
                    Tab("📜", id="tab-history", title="History"),
                    Tab("📁", id="tab-files", title="Files"),
                    id="sidebar-tabs",
                )

            with Horizontal(id="main-area"):
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

                    with ScrollableContainer(id="files-panel"):
                        yield Label("File Browser", id="files-label")
                        yield Input(placeholder="Glob pattern (e.g. **/*.py)...", id="files-search-input")
                        yield DataTable(id="files-table")

                with Container(id="side-panel"):
                    yield Static("◈ HUD PANEL ◈", id="side-panel-title")
                    yield Static("╔═══════════════════╗", id="radar-display")
                    yield Static("║   RADAR SCAN     ║", id="radar-display")
                    yield Static("╚═══════════════════╝", id="radar-display")
                    yield RichLog(id="side-log", wrap=True, highlight=True, markup=True)
                    yield Static("┌─ STATUS ────────┐", id="stats-title")
                    yield Static("│ ● SYSTEM: OK   │", id="stats-system")
                    yield Static("│ ⚡ CPU: 12%    │", id="stats-cpu")
                    yield Static("│ ♻ MEM: 4.2GB   │", id="stats-mem")
                    yield Static("│ ◷ UPTIME: 5m   │", id="stats-uptime")
                    yield Static("└────────────────┘", id="stats-footer")

            with Container(id="input-bar"):
                yield Static(id="budget-display")
                with Horizontal(id="input-container"):
                    yield Input(placeholder="Message / command...", id="goal-input")
                    yield Button("Send", id="submit-btn", variant="primary")

            with Container(id="suggestions-panel"):
                yield Static("💡 /ollama, /pull, /models, /config", id="suggestions-text")

            yield Static(id="status-bar")

    def on_mount(self) -> None:
        if self._state.mode == "chat":
            self._state.log("🚀 ARCHON v3.0 [CYBERPUNK] - Online")
        else:
            self._state.log("🚀 ARCHON v3.0 [CYBERPUNK] - Ready")
        self._state.log("╔════════════════════════════════════════════════════════════╗")
        self._state.log("║  ⚡ PARTICLE SYSTEM ACTIVE  │  RADAR TRACKING  ⚡       ║")
        self._state.log("╚════════════════════════════════════════════════════════════╝")
        self._state.log(f"Log file: {self._log_file}")
        self._flush_audit_log()
        self.action_show_chat()
        self._refresh_overview()
        self._refresh_side_panel()
        self._refresh_budget_display()
        self._refresh_status_bar()
        self._setup_data_tables()
        self._refresh_skills_table()
        self.query_one("#goal-input", Input).focus()
        self.set_interval(2.0, self._safe_refresh)
        self.set_interval(0.2, self._tick_spinner)
        self.set_interval(0.1, self._tick_particles)

    def _refresh_side_panel(self) -> None:
        """Refresh the side panel with current status."""
        side_log = self.query_one("#side-log", RichLog)
        byok = self._config.byok
        lines = [
            f"📦 Model: {byok.ollama_primary_model}",
            f"💻 Coding: {byok.ollama_coding_model}",
            f"⚡ Fast: {byok.ollama_fast_model}",
            f"👁️ Vision: {byok.ollama_vision_model}",
            "",
            f"💰 Budget: ${byok.budget_per_task_usd}/task",
            f"📊 Daily: ${byok.budget_per_month_usd}/mo",
        ]
        side_log.clear()
        for line in lines:
            side_log.write(line)

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

    def _refresh_files_table(self, pattern: str = "**/*.py") -> None:
        """Refresh the files table with glob pattern."""
        table = self.query_one("#files-table", DataTable)
        table.clear()
        table.add_columns("Type", "Name", "Size")

        import fnmatch
        from pathlib import Path as PathLib

        base = PathLib.cwd()
        count = 0
        try:
            for path in base.rglob("*"):
                if count >= 200:
                    break
                rel = str(path.relative_to(base))
                if not fnmatch.fnmatch(rel, pattern):
                    continue
                file_type = "dir" if path.is_dir() else "file"
                size = ""
                if path.is_file():
                    try:
                        s = path.stat().st_size
                        size = f"{s:,}"
                    except OSError:
                        size = "?"
                table.add_row(file_type, rel, size)
                count += 1
        except Exception:
            pass

        if count == 0:
            self._state.log(f"📁 No files matching: {pattern}")

    def on_files_search_input_changed(self, event: Input.Changed) -> None:
        """Handle file search input changes."""
        if event.input.id == "files-search-input":
            pattern = event.value.strip() or "**/*.py"
            self._refresh_files_table(pattern)

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

        # Workspace context
        ws = _get_workspace_context()
        branch = ws.get("git_branch")
        branch_str = f" [{branch}]" if branch else ""
        dirty_str = " *" if ws.get("git_dirty") else ""
        dir_short = Path(ws.get("dir", ".")).name

        status = (
            f"{spinner}{activity} | "
            f"📁 {dir_short}{branch_str}{dirty_str} | "
            f"🎯 {mode_label} | "
            f"📝 {work_label}: {active} active, {len(self._state.history)} done | "
            f"Ctrl+P: palette | Ctrl+Q: quit"
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

    def action_show_files(self) -> None:
        self.current_tab = 5
        self._switch_tab("files-panel")
        self._refresh_files_table()

    async def action_command_palette(self) -> None:
        """Open the command palette."""
        def on_dismiss(command: str | None) -> None:
            if not command:
                return
            self.call_later(self._handle_palette_command, command)

        self.push_screen(CommandPaletteScreen(), on_dismiss)

    def _handle_palette_command(self, command: str) -> None:
        """Execute a command from the palette."""
        self._state.log(f"📋 Command: {command}")
        if command == "chat":
            self.action_show_chat()
        elif command == "overview":
            self.action_show_overview()
        elif command == "tasks":
            self.action_show_tasks()
        elif command == "skills":
            self.action_show_skills()
        elif command == "history":
            self.action_show_history()
        elif command == "files":
            self.action_show_files()
        elif command == "clear":
            self.action_clear_log()
        elif command == "providers":
            self._show_providers_info()
        elif command == "ollama":
            self._show_ollama_info()
        elif command == "validate":
            self._validate_config()
        elif command == "config":
            self._open_config_editor()

    def _show_providers_info(self) -> None:
        """Show providers info in overview."""
        self._refresh_overview()
        self.action_show_overview()

    def _show_ollama_info(self) -> None:
        """Show Ollama info in log."""
        from archon.cli.drawers.providers import _probe_ollama
        probe = _probe_ollama(self._config.byok.ollama_base_url)
        reachable = probe.get("reachable", False)
        models = probe.get("models", [])
        self._state.log(f"🦙 Ollama: {'reachable' if reachable else 'unreachable'}")
        for m in models[:10]:
            self._state.log(f"   - {m}")

    def _validate_config(self) -> None:
        """Run config validation."""
        from archon.validate_config import validate_config
        self._state.log("✓ Validating config...")
        report = validate_config(self._config_path)
        status = "PASSED" if report.ok else "FAILED"
        self._state.log(f"✓ Config validation: {status}")

    def _open_config_editor(self) -> None:
        """Open config in default editor."""
        import subprocess
        editor = os.environ.get("EDITOR", "notepad")
        try:
            subprocess.Popen([editor, self._config_path])
            self._state.log(f"📝 Opened {self._config_path} in {editor}")
        except Exception as exc:
            self._state.log(f"✗ Failed to open editor: {exc}")

    def _switch_tab(self, panel_id: str) -> None:
        for panel in [
            "chat-panel",
            "overview-panel",
            "tasks-panel",
            "skills-panel",
            "history-panel",
            "files-panel",
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
        elif tab_id == "tab-files":
            self.action_show_files()

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

- `Ctrl+P`: Command palette
- `Ctrl+1`: Chat panel
- `Ctrl+2`: Overview panel
- `Ctrl+3`: Tasks panel  
- `Ctrl+4`: Skills panel
- `Ctrl+5`: History panel
- `Ctrl+6`: Files panel
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

    async def _handle_slash_command(self, goal: str) -> None:
        """Handle slash commands like /ollama, /pull, /config."""
        import httpx

        parts = goal.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/ollama":
            self._state.activity = "🦙 Fetching models..."
            self._flush_audit_log()
            try:
                response = httpx.get(f"{self._config.byok.ollama_base_url.rstrip('/v1')}/api/tags", timeout=10)
                response.raise_for_status()
                models = response.json().get("models", [])
                self._state.activity = ""
                if models:
                    lines = ["🦙 Available Ollama Models:"]
                    for m in models:
                        size_mb = m.get("size", 0) // 1024 // 1024
                        lines.append(f"  • {m['name']} ({size_mb}MB)")
                    self._state.log("\n".join(lines))
                else:
                    self._state.log("🦙 No models found. Pull one with /pull <model>")
            except Exception as exc:
                self._state.log(f"🦙 Ollama unreachable: {exc}")

        elif cmd == "/pull":
            if not arg:
                self._state.log("Usage: /pull <model> (e.g., /pull gemma4:e4b)")
                return
            self._state.activity = f"⬇️ Pulling {arg}..."
            self._flush_audit_log()
            try:
                import subprocess
                result = subprocess.run(["ollama", "pull", arg], capture_output=True, text=True)
                self._state.activity = ""
                if result.returncode == 0:
                    self._state.log(f"✅ Successfully pulled {arg}")
                    self._state.log("Analyzing model for best role...")
                    
                    model_lower = arg.lower()
                    role = "primary"
                    if any(x in model_lower for x in ["code", "coder", "qwen"]):
                        role = "coding"
                    elif any(x in model_lower for x in ["vision", "llava", "vision"]):
                        role = "vision"
                    elif any(x in model_lower for x in ["embed"]):
                        role = "embedding"
                    elif any(x in model_lower for x in ["3b", "1b", "2b", "mini", "small"]):
                        role = "fast"
                    
                    config_path = self._config_path
                    with open(config_path, "r") as f:
                        import yaml
                        cfg = yaml.safe_load(f)
                    
                    role_map = {
                        "primary": "ollama_primary_model",
                        "coding": "ollama_coding_model", 
                        "fast": "ollama_fast_model",
                        "vision": "ollama_vision_model",
                        "embedding": "ollama_embedding_model",
                    }
                    key = role_map.get(role, "ollama_primary_model")
                    old_model = cfg["byok"].get(key, "")
                    cfg["byok"][key] = arg
                    
                    with open(config_path, "w") as f:
                        yaml.dump(cfg, f, default_flow_style=False)
                    
                    self._state.log(f"🔧 Auto-configured {arg} as {role} (was: {old_model})")
                    self._state.log("Config updated! Restart chat or run /models to verify.")
                else:
                    self._state.log(f"❌ Failed: {result.stderr}")
            except Exception as exc:
                self._state.log(f"❌ Error: {exc}")

        elif cmd == "/models":
            byok = self._config.byok
            self._state.log(f"📋 Current config:\n  primary: {byok.ollama_primary_model}\n  coding: {byok.ollama_coding_model}\n  fast: {byok.ollama_fast_model}\n  vision: {byok.ollama_vision_model}")

        elif cmd == "/config":
            self._state.activity = "📝 Opening config..."
            self._flush_audit_log()
            import subprocess
            editor = subprocess.run(["cmd", "/c", "echo %EDITOR%"], capture_output=True, text=True).stdout.strip() or "notepad"
            if editor == "notepad":
                subprocess.Popen(["notepad", self._config_path])
            else:
                subprocess.Popen([editor, self._config_path])
            self._state.activity = ""
            self._state.log(f"📝 Opened config in {editor}")

        else:
            self._state.log(f"Unknown command: {cmd}")
            self._state.log("Available: /ollama, /pull <model>, /models, /config")

    async def _run_chat_goal(self, goal: str) -> None:
        if goal.startswith("/"):
            await self._handle_slash_command(goal)
            return
        try:
            session = await self._ensure_chat_session()
            self._state.activity = "Thinking..."
            self._flush_audit_log()

            # Show thinking indicator
            thinking_id = len(self._state.audit_log)
            self._state.audit_log.append(f"[dim][{time.strftime('%H:%M:%S')}] 🤔 Thinking...[/dim]")
            self._flush_audit_log()

            result = await session.send(message=goal, event_sink=self._handle_chat_event)

            # Remove thinking indicator
            if thinking_id < len(self._state.audit_log):
                self._state.audit_log[thinking_id] = ""

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

        # Show reply with typing effect
        reply = result.reply or "[no reply]"
        self._state.log(f"🤖 Archon: {reply}")
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
        self._update_suggestions("")
        self._state.log(f"👤 You: {goal}")
        self._flush_audit_log()
        self._schedule_goal(goal)

    def _update_suggestions(self, text: str) -> None:
        """Update suggestions panel based on input."""
        panel = self.query_one("#suggestions-text", Static)
        if text.startswith("/"):
            cmds = {
                "/ollama": "List available Ollama models",
                "/pull": "Pull a model (usage: /pull modelname)",
                "/models": "Show current model configuration",
                "/config": "Open config in editor",
                "/status": "Show runtime status",
                "/clear": "Clear chat log",
            }
            matched = [f"{k}: {v}" for k, v in cmds.items() if k.startswith(text.lower())]
            if matched:
                panel.update("\n".join(matched))
            else:
                panel.update("💡 Commands: /ollama, /pull <model>, /models, /config")
        else:
            panel.update("💡 Commands: /ollama, /pull <model>, /models, /config")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "goal-input":
            self._update_suggestions(event.value)

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
