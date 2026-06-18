import asyncio

from app.schemas import NodeFailurePolicy, NodeStatus, WorkflowRun
from app.workflow import NodeRegistry, WorkflowNode, execute_node, execute_parallel_nodes


def test_parallel_nodes_record_independent_runs():
    async def value(name):
        await asyncio.sleep(0)
        return name

    workflow = WorkflowRun(domain="example.com")
    outcomes = asyncio.run(
        execute_parallel_nodes(
            workflow,
            [
                WorkflowNode("one", lambda: value("first")),
                WorkflowNode("two", lambda: value("second")),
            ],
        )
    )

    assert outcomes["one"].value == "first"
    assert outcomes["two"].value == "second"
    assert {run.status for run in workflow.node_runs} == {NodeStatus.COMPLETE}


def test_optional_node_failure_is_recorded_without_raising():
    async def fail():
        raise ValueError("unavailable")

    workflow = WorkflowRun(domain="example.com")
    outcome = asyncio.run(
        execute_node(
            workflow,
            WorkflowNode("optional", fail, failure_policy=NodeFailurePolicy.OPTIONAL),
        )
    )

    assert outcome.error
    assert workflow.node_runs[0].status == NodeStatus.FAILED


def test_node_registry_rejects_duplicate_names():
    async def value():
        return "ok"

    registry = NodeRegistry()
    registry.register(WorkflowNode("same", value))

    try:
        registry.register(WorkflowNode("same", value))
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate workflow node name was accepted")
