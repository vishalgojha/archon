"""Studio workflow serialization and validation helpers."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from archon.evolution.engine import DEFAULT_KNOWN_AGENTS, Step, WorkflowDefinition

CONTROL_NODE_AGENTS = {
    "DebateNode",
    "ApprovalNode",
    "ConditionNode",
    "LoopNode",
    "OutputNode",
}


@dataclass(slots=True, frozen=True)
class ValidationError:
    """One workflow validation error.

    Example:
        >>> ValidationError("cycle", "Cycle detected", "node-a").code
        'cycle'
    """

    code: str
    message: str
    node_id: str = ""


def serialize(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> WorkflowDefinition:
    """Serialize React Flow nodes and edges into `WorkflowDefinition`.

    Example:
        >>> workflow = serialize([{"id":"a","type":"AgentNode","position":{"x":0,"y":0},"data":{"agent_class":"ResearcherAgent","action":"research"}}], [])
        >>> workflow.steps[0].step_id
        'a'
    """

    edge_map: dict[str, list[str]] = {}
    for edge in edges:
        target = str(edge.get("target") or "").strip()
        source = str(edge.get("source") or "").strip()
        if target and source:
            edge_map.setdefault(target, []).append(source)
    steps: list[Step] = []
    studio_nodes: dict[str, Any] = {}
    for node in nodes:
        node_id = str(node.get("id") or f"node-{uuid.uuid4().hex[:8]}")
        node_type = str(node.get("type") or "AgentNode")
        data = dict(node.get("data") or {})
        agent = str(data.get("agent_class") or node_type)
        action = str(data.get("action") or node_type.lower())
        config = dict(data)
        config.setdefault("node_type", node_type)
        config.setdefault("label", data.get("label") or node_id)
        steps.append(
            Step(
                step_id=node_id,
                agent=agent,
                action=action,
                config=config,
                dependencies=edge_map.get(node_id, []),
            )
        )
        studio_nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "position": dict(node.get("position") or {"x": 0, "y": 0}),
            "data": data,
        }
    return WorkflowDefinition(
        workflow_id=f"workflow-{uuid.uuid4().hex[:12]}",
        name="Studio Workflow",
        steps=steps,
        metadata={"studio": {"nodes": studio_nodes, "edges": list(edges)}},
        version=1,
        created_at=time.time(),
    )


def deserialize(workflow: WorkflowDefinition | dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Deserialize `WorkflowDefinition` back into nodes and edges.

    Example:
        >>> workflow = serialize([{"id":"a","type":"AgentNode","position":{"x":0,"y":0},"data":{"agent_class":"ResearcherAgent","action":"research"}}], [])
        >>> deserialize(workflow)["nodes"][0]["id"]
        'a'
    """

    data = _workflow_dict(workflow)
    steps = data.get("steps", [])
    metadata = data.get("metadata", {})
    studio = metadata.get("studio", {}) if isinstance(metadata, dict) else {}
    studio_nodes = studio.get("nodes", {}) if isinstance(studio, dict) else {}
    edges = studio.get("edges", []) if isinstance(studio, dict) else []
    nodes: list[dict[str, Any]] = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        node_id = str(step.get("step_id") or "")
        saved = studio_nodes.get(node_id, {}) if isinstance(studio_nodes, dict) else {}
        config = step.get("config", {}) if isinstance(step.get("config"), dict) else {}
        node_type = str(config.get("node_type") or saved.get("type") or "AgentNode")
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "position": dict(saved.get("position") or {"x": 0, "y": 0}),
                "data": dict(saved.get("data") or config),
            }
        )
    if not edges:
        for step in steps if isinstance(steps, list) else []:
            if not isinstance(step, dict):
                continue
            for dependency in step.get("dependencies", []) if isinstance(step.get("dependencies"), list) else []:
                edges.append(
                    {
                        "id": f"{dependency}->{step.get('step_id')}",
                        "source": str(dependency),
                        "target": str(step.get("step_id") or ""),
                        "label": str(((step.get("config") or {}).get("data_type")) or ""),
                    }
                )
    return {"nodes": nodes, "edges": list(edges)}


def validate(workflow: WorkflowDefinition | dict[str, Any]) -> list[ValidationError]:
    """Validate topology and agent constraints for one Studio workflow.

    Example:
        >>> workflow = serialize([{"id":"a","type":"AgentNode","position":{"x":0,"y":0},"data":{"agent_class":"ResearcherAgent","action":"research"}}], [])
        >>> validate(workflow)
        []
    """

    data = _workflow_dict(workflow)
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return [ValidationError("schema", "steps must be a list.")]
    step_map: dict[str, dict[str, Any]] = {}
    errors: list[ValidationError] = []
    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}
    known_agents = set(DEFAULT_KNOWN_AGENTS) | CONTROL_NODE_AGENTS
    output_nodes: list[str] = []

    for step in steps:
        if not isinstance(step, dict):
            errors.append(ValidationError("schema", "Each step must be an object."))
            continue
        step_id = str(step.get("step_id") or "").strip()
        if not step_id:
            errors.append(ValidationError("schema", "step_id is required."))
            continue
        if step_id in step_map:
            errors.append(ValidationError("duplicate", f"Duplicate step_id '{step_id}'.", step_id))
            continue
        step_map[step_id] = step
        config = step.get("config", {}) if isinstance(step.get("config"), dict) else {}
        node_type = str(config.get("node_type") or "")
        if node_type == "OutputNode":
            output_nodes.append(step_id)
        agent = str(step.get("agent") or "").strip()
        if node_type == "AgentNode" and agent not in known_agents:
            errors.append(ValidationError("missing_agent_class", f"Unknown agent_class '{agent}'.", step_id))
        if node_type != "AgentNode" and agent and agent not in known_agents:
            errors.append(ValidationError("unknown_node_agent", f"Unknown node agent '{agent}'.", step_id))
        dependencies = step.get("dependencies", [])
        if not isinstance(dependencies, list):
            errors.append(ValidationError("schema", "dependencies must be a list.", step_id))
            continue
        for dep in dependencies:
            dep_id = str(dep)
            outgoing.setdefault(dep_id, set()).add(step_id)
            incoming.setdefault(step_id, set()).add(dep_id)

    for step_id, step in step_map.items():
        for dep in step.get("dependencies", []) if isinstance(step.get("dependencies"), list) else []:
            if str(dep) not in step_map:
                errors.append(
                    ValidationError(
                        "missing_dependency",
                        f"Missing dependency '{dep}' for step '{step_id}'.",
                        step_id,
                    )
                )

    visited: dict[str, int] = {}

    def dfs(node_id: str) -> None:
        state = visited.get(node_id, 0)
        if state == 1:
            errors.append(ValidationError("cycle", "Cycle detected in workflow.", node_id))
            return
        if state == 2 or node_id not in step_map:
            return
        visited[node_id] = 1
        for dep in step_map[node_id].get("dependencies", []):
            dfs(str(dep))
        visited[node_id] = 2

    for step_id in step_map:
        dfs(step_id)

    for step_id in step_map:
        if not incoming.get(step_id) and not outgoing.get(step_id):
            errors.append(ValidationError("orphan", f"Node '{step_id}' is orphaned.", step_id))

    if not output_nodes:
        errors.append(ValidationError("output_unreachable", "Output node is not reachable."))
    elif not any(_reachable_from_any_root(step_map, node_id) for node_id in output_nodes):
        errors.append(ValidationError("output_unreachable", "Output node is not reachable."))

    deduped: dict[tuple[str, str], ValidationError] = {}
    for error in errors:
        deduped[(error.code, error.node_id)] = error
    return list(deduped.values())


def _workflow_dict(workflow: WorkflowDefinition | dict[str, Any]) -> dict[str, Any]:
    if isinstance(workflow, WorkflowDefinition):
        return {
            "workflow_id": workflow.workflow_id,
            "name": workflow.name,
            "steps": [
                {
                    "step_id": step.step_id,
                    "agent": step.agent,
                    "action": step.action,
                    "config": dict(step.config),
                    "dependencies": list(step.dependencies),
                }
                for step in workflow.steps
            ],
            "metadata": dict(workflow.metadata),
            "version": workflow.version,
            "created_at": workflow.created_at,
        }
    return dict(workflow)


def _reachable_from_any_root(step_map: dict[str, dict[str, Any]], target_id: str) -> bool:
    roots = [
        step_id
        for step_id, step in step_map.items()
        if not list(step.get("dependencies", []) if isinstance(step.get("dependencies"), list) else [])
    ]
    reverse: dict[str, list[str]] = {}
    for step_id, step in step_map.items():
        for dep in step.get("dependencies", []) if isinstance(step.get("dependencies"), list) else []:
            reverse.setdefault(str(dep), []).append(step_id)
    for root in roots:
        queue = [root]
        seen = set()
        while queue:
            current = queue.pop(0)
            if current == target_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            queue.extend(reverse.get(current, []))
    return False
