from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict

class NodeType(str, Enum):
    """
    工作流节点类型枚举
    """
    LLM_CALL = "llm_call"       # 调用 LLM
    TOOL_CALL = "tool_call"     # 调用工具
    SKILL_CALL = "skill_call"   # 调用技能
    CONDITION = "condition"     # 条件分支
    PARALLEL = "parallel"       # 并行执行 (预留)

class WorkflowNode(BaseModel):
    """
    工作流节点定义
    
    代表工作流中的一个执行单元
    """
    node_id: str = Field(..., description="节点唯一标识")
    node_type: NodeType = Field(..., description="节点类型")
    config: Dict[str, Any] = Field(default_factory=dict, description="节点配置参数")
    inputs: List[str] = Field(default_factory=list, description="输入来源节点ID列表")
    outputs: List[str] = Field(default_factory=list, description="输出目标 (通常由 edge 定义，此处作为辅助信息)")

class Workflow(BaseModel):
    """
    工作流定义
    
    由节点和边组成的有向无环图 (DAG)
    """
    workflow_id: str = Field(..., description="工作流唯一标识")
    name: str = Field(..., description="工作流名称")
    description: str = Field(..., description="工作流描述")
    nodes: List[WorkflowNode] = Field(..., description="节点列表")
    edges: List[List[str]] = Field(..., description="边列表，每个元素为 [source_node_id, target_node_id]")
    entry_node: str = Field(..., description="入口节点 ID")
    exit_nodes: List[str] = Field(..., description="出口节点 ID 列表")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "workflow_id": "simple_flow",
                "name": "Simple Workflow",
                "description": "A linear workflow.",
                "nodes": [
                    {"node_id": "start", "node_type": "llm_call", "config": {}},
                    {"node_id": "end", "node_type": "tool_call", "config": {}}
                ],
                "edges": [["start", "end"]],
                "entry_node": "start",
                "exit_nodes": ["end"]
            }
        }
    )
