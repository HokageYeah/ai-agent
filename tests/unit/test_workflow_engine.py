import pytest
from app.workflows.nodes import Workflow, WorkflowNode, NodeType
from app.workflows.engine import WorkflowEngine

@pytest.mark.asyncio
async def test_workflow_engine_execution():
    """测试简单的线性工作流执行"""
    nodes = [
        WorkflowNode(node_id="start", node_type=NodeType.LLM_CALL, config={}),
        WorkflowNode(node_id="process", node_type=NodeType.TOOL_CALL, config={}),
        WorkflowNode(node_id="end", node_type=NodeType.LLM_CALL, config={})
    ]
    edges = [["start", "process"], ["process", "end"]]
    
    wf = Workflow(
        workflow_id="test_wf",
        name="Test Workflow",
        description="Linear test",
        nodes=nodes,
        edges=edges,
        entry_node="start",
        exit_nodes=["end"]
    )
    
    engine = WorkflowEngine()
    result = await engine.execute(wf, {"input": "test"})
    
    assert "end" in result
    assert result["end"] == "Executed end"

@pytest.mark.asyncio
async def test_workflow_cycle_detection():
    """测试循环检测"""
    nodes = [
        WorkflowNode(node_id="A", node_type=NodeType.LLM_CALL),
        WorkflowNode(node_id="B", node_type=NodeType.LLM_CALL)
    ]
    edges = [["A", "B"], ["B", "A"]] # Cycle
    
    wf = Workflow(
        workflow_id="cycle_wf",
        name="Cycle Workflow",
        description="Cycle test",
        nodes=nodes,
        edges=edges,
        entry_node="A",
        exit_nodes=["B"]
    )
    
    engine = WorkflowEngine()
    
    with pytest.raises(ValueError, match="Cycle detected"):
        await engine.execute(wf, {})
