import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.schemas import NodeFailurePolicy, NodeRun, NodeStatus, WorkflowRun


@dataclass(frozen=True)
class WorkflowNode:
    name: str
    runner: Callable[[], Awaitable[Any]]
    version: str = "v1"
    failure_policy: NodeFailurePolicy = NodeFailurePolicy.PARTIAL


@dataclass(frozen=True)
class NodeOutcome:
    name: str
    value: Any = None
    error: Exception | None = None


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, WorkflowNode] = {}

    def register(self, node: WorkflowNode) -> None:
        if node.name in self._nodes:
            raise ValueError(f"workflow node already registered: {node.name}")
        self._nodes[node.name] = node

    def values(self) -> list[WorkflowNode]:
        return list(self._nodes.values())


async def execute_node(workflow: WorkflowRun, node: WorkflowNode) -> NodeOutcome:
    run = NodeRun(
        name=node.name,
        version=node.version,
        failure_policy=node.failure_policy,
        status=NodeStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    workflow.node_runs.append(run)
    try:
        value = await node.runner()
    except Exception as exc:
        run.status = NodeStatus.FAILED
        run.message = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(UTC)
        if node.failure_policy == NodeFailurePolicy.FATAL:
            raise
        return NodeOutcome(name=node.name, error=exc)
    run.status = NodeStatus.COMPLETE
    run.finished_at = datetime.now(UTC)
    return NodeOutcome(name=node.name, value=value)


async def execute_parallel_nodes(
    workflow: WorkflowRun,
    nodes: list[WorkflowNode],
) -> dict[str, NodeOutcome]:
    outcomes = await asyncio.gather(*(execute_node(workflow, node) for node in nodes))
    return {outcome.name: outcome for outcome in outcomes}
