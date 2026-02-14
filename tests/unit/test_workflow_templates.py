"""
工作流模板测试模块

测试预定义工作流模板的定义正确性。

测试内容:
1. 验证工作流基本属性
2. 验证节点定义正确
3. 验证边定义正确
4. 验证入口和出口节点配置正确
5. 验证节点类型和配置正确
"""

import pytest
from app.workflows.nodes import Workflow, WorkflowNode, NodeType
from app.workflows.templates import INTENT_ROUTING_WORKFLOW


class TestIntentRoutingWorkflow:
    """测试意图路由工作流"""
    
    def test_workflow_definition(self):
        """测试工作流定义正确"""
        assert INTENT_ROUTING_WORKFLOW.workflow_id == "intent_routing"
        assert INTENT_ROUTING_WORKFLOW.name == "意图路由工作流"
        assert "意图" in INTENT_ROUTING_WORKFLOW.description
    
    def test_node_count(self):
        """测试节点数量正确"""
        # 应该有6个节点:
        # 1. classify_intent (LLM调用)
        # 2. route_decision (条件)
        # 3-6. 四个技能节点
        assert len(INTENT_ROUTING_WORKFLOW.nodes) == 6
    
    def test_edge_count(self):
        """测试边数量正确"""
        # 应该有5条边:
        # 1. classify_intent -> route_decision
        # 2-5. route_decision -> 四个技能节点
        assert len(INTENT_ROUTING_WORKFLOW.edges) == 5
    
    def test_entry_node(self):
        """测试入口节点正确"""
        assert INTENT_ROUTING_WORKFLOW.entry_node == "classify_intent"
    
    def test_exit_nodes(self):
        """测试出口节点正确"""
        exit_nodes = INTENT_ROUTING_WORKFLOW.exit_nodes
        assert len(exit_nodes) == 4
        assert "data_skill" in exit_nodes
        assert "code_skill" in exit_nodes
        assert "translate_skill" in exit_nodes
        assert "chat_skill" in exit_nodes
    
    def test_classify_intent_node(self):
        """测试意图分类节点"""
        # 查找 classify_intent 节点
        classify_node = None
        for node in INTENT_ROUTING_WORKFLOW.nodes:
            if node.node_id == "classify_intent":
                classify_node = node
                break
        
        assert classify_node is not None
        assert classify_node.node_type == NodeType.LLM_CALL
        assert "prompt" in classify_node.config
        assert "model" in classify_node.config
    
    def test_route_decision_node(self):
        """测试路由决策节点"""
        # 查找 route_decision 节点
        route_node = None
        for node in INTENT_ROUTING_WORKFLOW.nodes:
            if node.node_id == "route_decision":
                route_node = node
                break
        
        assert route_node is not None
        assert route_node.node_type == NodeType.CONDITION
        assert "conditions" in route_node.config
        
        # 验证条件映射
        conditions = route_node.config["conditions"]
        assert conditions["data_analysis"] == "data_skill"
        assert conditions["code_generation"] == "code_skill"
        assert conditions["translation"] == "translate_skill"
        assert conditions["general_chat"] == "chat_skill"
    
    def test_skill_nodes(self):
        """测试技能节点"""
        skill_nodes = []
        for node in INTENT_ROUTING_WORKFLOW.nodes:
            if node.node_type == NodeType.SKILL_CALL:
                skill_nodes.append(node)
        
        # 应该有4个技能节点
        assert len(skill_nodes) == 4
        
        # 验证每个技能节点的配置
        skill_ids = [node.config.get("skill_id") for node in skill_nodes]
        assert "data_analysis" in skill_ids
        assert "code_generation" in skill_ids
        assert "translation" in skill_ids
        assert "text_writing" in skill_ids
    
    def test_edges_structure(self):
        """测试边结构正确"""
        edges = INTENT_ROUTING_WORKFLOW.edges
        
        # 验证从 classify_intent 到 route_decision 的边
        assert ["classify_intent", "route_decision"] in edges
        
        # 验证从 route_decision 到各个技能的边
        assert ["route_decision", "data_skill"] in edges
        assert ["route_decision", "code_skill"] in edges
        assert ["route_decision", "translate_skill"] in edges
        assert ["route_decision", "chat_skill"] in edges
    
    def test_workflow_is_valid(self):
        """测试工作流是有效的 Workflow 实例"""
        assert isinstance(INTENT_ROUTING_WORKFLOW, Workflow)
        
        # 验证所有节点都是 WorkflowNode 实例
        for node in INTENT_ROUTING_WORKFLOW.nodes:
            assert isinstance(node, WorkflowNode)
    
    def test_node_ids_are_unique(self):
        """测试节点ID唯一性"""
        node_ids = [node.node_id for node in INTENT_ROUTING_WORKFLOW.nodes]
        assert len(node_ids) == len(set(node_ids))
    
    def test_all_edge_nodes_exist(self):
        """测试所有边引用的节点都存在"""
        node_ids = {node.node_id for node in INTENT_ROUTING_WORKFLOW.nodes}
        
        for edge in INTENT_ROUTING_WORKFLOW.edges:
            source, target = edge
            assert source in node_ids, f"源节点 {source} 不存在"
            assert target in node_ids, f"目标节点 {target} 不存在"
