"""Studio workflow execution adapters."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from archon.evolution.engine import Step, WorkflowDefinition

_LOCAL_BACKEND = "local"
_OPENCLAW_BACKEND = "openclaw"
_CONTROL_NODE_TYPES = {"ApprovalNode", "ConditionNode", "LoopNode", "OutputNode", "DebateNode"}
_OPENCLAW_DEFAULT_PORT = 18789
_OPENCLAW_CONFIG_FILENAMES = ("openclaw.json", "propaiclaw.json")
_OPENCLAW_LAUNCHER_FILENAMES = ("gateway.cmd", "gateway.sh")


@dataclass(slots=True, frozen=True)
class StepExecutionResult:
    """One executed workflow step result."""

    step_id: str
    executor: str
    status: str
    summary: str
    output_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "executor": self.executor,
            "status": self.status,
            "summary": self.summary,
            "output_text": self.output_text,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class OpenClawExecutionConfig:
    """Resolved OpenClaw execution settings."""

    base_url: str
    token: str
    agent_id: str
    timeout_s: float
    user_prefix: str

    @property
    def responses_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/responses"


@dataclass(slots=True, frozen=True)
class _DiscoveredOpenClawState:
    """Best-effort OpenClaw settings resolved from local state."""

    source: str
    base_url: str | None = None
    token: str | None = None
    agent_id: str | None = None


class StudioStepExecutor:
    """Abstract studio step executor."""

    backend_name = _LOCAL_BACKEND

    async def execute_step(
        self,
        *,
        step: Step,
        workflow: WorkflowDefinition,
        run_id: str,
        tenant_id: str,
        prior_results: list[StepExecutionResult],
        orchestrator: Any,
        event_sink,
    ) -> StepExecutionResult:
        raise NotImplementedError


class LocalStudioStepExecutor(StudioStepExecutor):
    """Default in-process Studio executor."""

    backend_name = _LOCAL_BACKEND

    async def execute_step(
        self,
        *,
        step: Step,
        workflow: WorkflowDefinition,
        run_id: str,
        tenant_id: str,
        prior_results: list[StepExecutionResult],
        orchestrator: Any,
        event_sink,
    ) -> StepExecutionResult:
        del workflow, run_id, tenant_id, prior_results, orchestrator, event_sink
        node_type = str(step.config.get("node_type") or step.agent or "AgentNode")
        if node_type in _CONTROL_NODE_TYPES:
            return StepExecutionResult(
                step_id=step.step_id,
                executor=self.backend_name,
                status="completed",
                summary=f"{node_type} registered in the local Studio execution layer.",
                output_text="",
                metadata={"node_type": node_type, "action": step.action},
            )
        label = str(step.config.get("label") or step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            executor=self.backend_name,
            status="completed",
            summary=f"Prepared local step '{label}' for ARCHON synthesis.",
            output_text=str(step.config.get("description") or step.action or label),
            metadata={"node_type": node_type, "action": step.action},
        )


class OpenClawStudioStepExecutor(StudioStepExecutor):
    """Dispatch agent-like Studio steps through OpenClaw OpenResponses."""

    backend_name = _OPENCLAW_BACKEND

    def __init__(self, config: OpenClawExecutionConfig) -> None:
        self.config = config
        self._dispatch_approved = False

    async def execute_step(
        self,
        *,
        step: Step,
        workflow: WorkflowDefinition,
        run_id: str,
        tenant_id: str,
        prior_results: list[StepExecutionResult],
        orchestrator: Any,
        event_sink,
    ) -> StepExecutionResult:
        node_type = str(step.config.get("node_type") or step.agent or "AgentNode")
        if node_type in _CONTROL_NODE_TYPES:
            return await LocalStudioStepExecutor().execute_step(
                step=step,
                workflow=workflow,
                run_id=run_id,
                tenant_id=tenant_id,
                prior_results=prior_results,
                orchestrator=orchestrator,
                event_sink=event_sink,
            )

        await self._ensure_dispatch_approved(
            step=step,
            workflow=workflow,
            run_id=run_id,
            tenant_id=tenant_id,
            orchestrator=orchestrator,
            event_sink=event_sink,
        )
        payload = await self._request_response(
            step=step,
            workflow=workflow,
            run_id=run_id,
            tenant_id=tenant_id,
            prior_results=prior_results,
        )
        output_text = _extract_response_text(payload)
        label = str(step.config.get("label") or step.step_id)
        summary = (
            output_text.strip().splitlines()[0]
            if output_text.strip()
            else (f"OpenClaw completed '{label}'.")
        )
        return StepExecutionResult(
            step_id=step.step_id,
            executor=self.backend_name,
            status="completed",
            summary=summary[:280],
            output_text=output_text.strip(),
            metadata={
                "node_type": node_type,
                "action": step.action,
                "agent_id": self.config.agent_id,
                "session_user": self._session_user(
                    tenant_id=tenant_id, workflow=workflow, run_id=run_id
                ),
            },
        )

    async def _ensure_dispatch_approved(
        self,
        *,
        step: Step,
        workflow: WorkflowDefinition,
        run_id: str,
        tenant_id: str,
        orchestrator: Any,
        event_sink,
    ) -> None:
        if self._dispatch_approved:
            return
        await orchestrator.approval_gate.guard(
            action_type="external_api_call",
            payload={
                "provider": "openclaw",
                "url": self.config.responses_url,
                "workflow_id": workflow.workflow_id,
                "workflow_name": workflow.name,
                "run_id": run_id,
                "tenant_id": tenant_id,
                "step_id": step.step_id,
                "action": step.action,
                "agent": step.agent,
                "agent_id": self.config.agent_id,
                "session_user": self._session_user(
                    tenant_id=tenant_id,
                    workflow=workflow,
                    run_id=run_id,
                ),
            },
            event_sink=event_sink,
        )
        self._dispatch_approved = True

    async def _request_response(
        self,
        *,
        step: Step,
        workflow: WorkflowDefinition,
        run_id: str,
        tenant_id: str,
        prior_results: list[StepExecutionResult],
    ) -> dict[str, Any]:
        body = {
            "model": f"openclaw:{self.config.agent_id}",
            "instructions": _openclaw_instructions(step=step, workflow=workflow),
            "input": _openclaw_input(
                step=step,
                workflow=workflow,
                run_id=run_id,
                tenant_id=tenant_id,
                prior_results=prior_results,
            ),
            "user": self._session_user(tenant_id=tenant_id, workflow=workflow, run_id=run_id),
        }
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
            "x-openclaw-agent-id": self.config.agent_id,
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
            response = await client.post(self.config.responses_url, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("OpenClaw response must decode to a JSON object.")
        return payload

    def _session_user(self, *, tenant_id: str, workflow: WorkflowDefinition, run_id: str) -> str:
        safe_tenant = str(tenant_id or "tenant").strip() or "tenant"
        safe_workflow = str(workflow.workflow_id or "workflow").strip() or "workflow"
        safe_run = str(run_id or "run").strip() or "run"
        return f"{self.config.user_prefix}:{safe_tenant}:{safe_workflow}:{safe_run}"


def build_step_executor() -> StudioStepExecutor:
    """Build the configured Studio execution backend."""

    backend = str(os.getenv("ARCHON_STUDIO_EXECUTION_LAYER", _LOCAL_BACKEND)).strip().lower()
    if not backend or backend == _LOCAL_BACKEND:
        return LocalStudioStepExecutor()
    if backend != _OPENCLAW_BACKEND:
        raise ValueError(
            f"ARCHON_STUDIO_EXECUTION_LAYER must be 'local' or 'openclaw'. Received '{backend}'."
        )
    return OpenClawStudioStepExecutor(_load_openclaw_config())


def _load_openclaw_config() -> OpenClawExecutionConfig:
    discovered = _discover_openclaw_state()
    base_url = (
        str(os.getenv("ARCHON_OPENCLAW_BASE_URL", "")).strip()
        or (discovered.base_url if discovered else "")
        or f"http://127.0.0.1:{_OPENCLAW_DEFAULT_PORT}"
    )
    token = str(os.getenv("ARCHON_OPENCLAW_TOKEN", "")).strip() or (
        discovered.token if discovered and discovered.token else ""
    )
    agent_id = (
        str(os.getenv("ARCHON_OPENCLAW_AGENT_ID", "")).strip()
        or (discovered.agent_id if discovered and discovered.agent_id else "")
        or "main"
    )
    timeout_text = str(os.getenv("ARCHON_OPENCLAW_TIMEOUT_S", "60")).strip() or "60"
    user_prefix = (
        str(os.getenv("ARCHON_OPENCLAW_USER_PREFIX", "archon-studio")).strip() or "archon-studio"
    )
    if not base_url:
        raise ValueError("ARCHON_OPENCLAW_BASE_URL must be set when using the OpenClaw backend.")
    if not token:
        raise ValueError(
            "ARCHON_OPENCLAW_TOKEN must be set when using the OpenClaw backend or discoverable "
            "from local OpenClaw state."
        )
    try:
        timeout_s = float(timeout_text)
    except ValueError as exc:
        raise ValueError("ARCHON_OPENCLAW_TIMEOUT_S must be a number.") from exc
    if timeout_s <= 0:
        raise ValueError("ARCHON_OPENCLAW_TIMEOUT_S must be greater than zero.")
    return OpenClawExecutionConfig(
        base_url=base_url.rstrip("/"),
        token=token,
        agent_id=agent_id,
        timeout_s=timeout_s,
        user_prefix=user_prefix,
    )


def _discover_openclaw_state() -> _DiscoveredOpenClawState | None:
    config_path_env = str(os.getenv("ARCHON_OPENCLAW_CONFIG_PATH", "")).strip()
    if config_path_env:
        return _discover_openclaw_state_from_dir(
            state_dir=Path(config_path_env).expanduser().resolve().parent,
            config_path=Path(config_path_env).expanduser().resolve(),
        )

    explicit_state_dirs = _split_discovery_paths(
        str(os.getenv("ARCHON_OPENCLAW_STATE_DIR", "")).strip()
    ) or _split_discovery_paths(str(os.getenv("OPENCLAW_STATE_DIR", "")).strip())
    if explicit_state_dirs:
        return _discover_openclaw_state_from_dirs(explicit_state_dirs)

    home = Path.home()
    return _discover_openclaw_state_from_dirs(
        [
            home / ".openclaw",
            home / ".openclaw-dev",
            home / ".propaiclaw",
        ]
    )


def _split_discovery_paths(raw: str) -> list[Path]:
    if not raw:
        return []
    candidates: list[Path] = []
    for part in raw.split(os.pathsep):
        value = part.strip()
        if not value:
            continue
        candidates.append(Path(value).expanduser())
    return candidates


def _discover_openclaw_state_from_dirs(state_dirs: list[Path]) -> _DiscoveredOpenClawState | None:
    seen: set[str] = set()
    for state_dir in state_dirs:
        resolved = str(state_dir.expanduser())
        if resolved in seen:
            continue
        seen.add(resolved)
        discovered = _discover_openclaw_state_from_dir(state_dir=state_dir.expanduser())
        if discovered is not None:
            return discovered
    return None


def _discover_openclaw_state_from_dir(
    *,
    state_dir: Path,
    config_path: Path | None = None,
) -> _DiscoveredOpenClawState | None:
    resolved_state_dir = state_dir.expanduser()
    launcher_values = _read_openclaw_launcher_env(resolved_state_dir)
    selected_config = config_path or _find_openclaw_config_path(resolved_state_dir)
    document = _read_openclaw_document(selected_config) if selected_config else {}
    if not document and not launcher_values:
        return None

    gateway = document.get("gateway") if isinstance(document.get("gateway"), dict) else {}
    auth = gateway.get("auth") if isinstance(gateway.get("auth"), dict) else {}

    port = (
        _coerce_int(gateway.get("port"))
        or _coerce_int(launcher_values.get("OPENCLAW_GATEWAY_PORT"))
        or _OPENCLAW_DEFAULT_PORT
    )
    bind = str(gateway.get("bind") or "").strip()
    token = str(auth.get("token") or launcher_values.get("OPENCLAW_GATEWAY_TOKEN") or "").strip()
    agent_id = _discover_openclaw_agent_id(document)

    return _DiscoveredOpenClawState(
        source=str(selected_config or resolved_state_dir),
        base_url=_build_openclaw_base_url(bind=bind, port=port),
        token=token or None,
        agent_id=agent_id,
    )


def _find_openclaw_config_path(state_dir: Path) -> Path | None:
    for filename in _OPENCLAW_CONFIG_FILENAMES:
        candidate = state_dir / filename
        if candidate.is_file():
            return candidate
    return None


def _read_openclaw_document(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_openclaw_launcher_env(state_dir: Path) -> dict[str, str]:
    for filename in _OPENCLAW_LAUNCHER_FILENAMES:
        candidate = state_dir / filename
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        values: dict[str, str] = {}
        for line in lines:
            parsed = _parse_launcher_assignment(candidate.suffix.lower(), line)
            if parsed is None:
                continue
            key, value = parsed
            values[key] = value
        if values:
            return values
    return {}


def _parse_launcher_assignment(suffix: str, line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    if suffix == ".cmd":
        lowered = stripped.lower()
        if not lowered.startswith("set "):
            return None
        body = stripped[4:].strip()
        if body.startswith('"') and body.endswith('"') and len(body) >= 2:
            body = body[1:-1]
    else:
        if stripped.startswith("export "):
            body = stripped[7:].strip()
        else:
            body = stripped
    if "=" not in body:
        return None
    key, _, value = body.partition("=")
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if not key:
        return None
    return key, value


def _discover_openclaw_agent_id(document: dict[str, Any]) -> str | None:
    agents = document.get("agents")
    if not isinstance(agents, dict):
        return None
    listed_agents = agents.get("list")
    if not isinstance(listed_agents, list):
        return None

    first_agent_id: str | None = None
    for item in listed_agents:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        if not agent_id:
            continue
        if first_agent_id is None:
            first_agent_id = agent_id
        if bool(item.get("default")):
            return agent_id
    return first_agent_id


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _build_openclaw_base_url(*, bind: str, port: int) -> str:
    normalized_bind = bind.strip().lower()
    if not normalized_bind or normalized_bind in {"loopback", "localhost", "127.0.0.1", "::1"}:
        host = "127.0.0.1"
    elif normalized_bind in {"0.0.0.0", "::", "all", "any"}:
        host = "127.0.0.1"
    else:
        host = bind.strip()
    return f"http://{host}:{port}"


def build_synthesis_goal(
    workflow: WorkflowDefinition,
    step_results: list[StepExecutionResult],
) -> str:
    """Build the ARCHON synthesis prompt from workflow step outputs."""

    goal = str(workflow.metadata.get("goal") or workflow.name or "Studio workflow").strip()
    if not step_results:
        return goal
    summarized_results = [
        {
            "step_id": row.step_id,
            "executor": row.executor,
            "status": row.status,
            "summary": row.summary,
            "output_text": row.output_text,
            "metadata": dict(row.metadata),
        }
        for row in step_results
    ]
    return (
        f"{goal}\n\n"
        "Executed workflow step results:\n"
        f"{json.dumps(summarized_results, indent=2, ensure_ascii=True)}\n\n"
        "Synthesize a final operator answer from these executed step results. "
        "Call out any missing information or approvals that would block a production rollout."
    )


def _openclaw_instructions(*, step: Step, workflow: WorkflowDefinition) -> str:
    label = str(step.config.get("label") or step.step_id).strip()
    return (
        "You are executing one ARCHON Studio workflow step inside OpenClaw. "
        "Use the gateway's available tools only when they are necessary for this step. "
        "Respect the step scope strictly, avoid speculative side effects, and return a concise "
        "operator-facing result.\n\n"
        f"Workflow: {workflow.name} ({workflow.workflow_id})\n"
        f"Step label: {label}\n"
        f"Step agent: {step.agent}\n"
        f"Step action: {step.action}"
    )


def _openclaw_input(
    *,
    step: Step,
    workflow: WorkflowDefinition,
    run_id: str,
    tenant_id: str,
    prior_results: list[StepExecutionResult],
) -> str:
    dependency_outputs = [
        {
            "step_id": row.step_id,
            "summary": row.summary,
            "output_text": row.output_text,
        }
        for row in prior_results
        if row.output_text or row.summary
    ]
    payload = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "workflow_id": workflow.workflow_id,
        "workflow_name": workflow.name,
        "step": {
            "step_id": step.step_id,
            "agent": step.agent,
            "action": step.action,
            "config": dict(step.config),
            "dependencies": list(step.dependencies),
        },
        "prior_step_results": dependency_outputs,
    }
    return json.dumps(payload, indent=2, ensure_ascii=True)


def _extract_response_text(payload: dict[str, Any]) -> str:
    direct = str(payload.get("output_text") or "").strip()
    if direct:
        return direct
    output_items = payload.get("output", [])
    collected: list[str] = []
    if isinstance(output_items, list):
        for item in output_items:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text_value = (
                        part.get("text")
                        or part.get("output_text")
                        or (part.get("content") if isinstance(part.get("content"), str) else "")
                    )
                    text = str(text_value or "").strip()
                    if text:
                        collected.append(text)
            text_value = item.get("text") or item.get("output_text")
            text = str(text_value or "").strip()
            if text:
                collected.append(text)
    if collected:
        return "\n".join(collected)
    return json.dumps(payload, ensure_ascii=True)
