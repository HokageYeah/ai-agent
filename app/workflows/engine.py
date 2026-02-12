from typing import Dict, Any, List, Set
from collections import deque
from loguru import logger
from colorama import Fore, Style
from app.workflows.nodes import Workflow, NodeType, WorkflowNode

class WorkflowEngine:
    """
    工作流引擎
    
    负责解析和执行工作流
    注意：这是 Phase 0 的核心抽象实现，仅包含基础调度逻辑，
    实际执行逻辑将在后续阶段集成 LLM/Tool/Skill 后完善。
    """
    
    def __init__(self):
        logger.info(f"{Fore.BLUE}WorkflowEngine initialized.{Style.RESET_ALL}")
    
    async def execute(self, workflow: Workflow, initial_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工作流
        
        Args:
            workflow: Workflow 定义对象
            initial_input: 初始输入数据
            
        Returns:
            Dict[str, Any]: 工作流执行结果
        """
        logger.info(f"Starting execution of workflow: {Fore.CYAN}{workflow.name} ({workflow.workflow_id}){Style.RESET_ALL}")
        
        # 1. 构建图结构 (Adjacency List)
        graph = {node.node_id: [] for node in workflow.nodes}
        in_degree = {node.node_id: 0 for node in workflow.nodes}
        nodes_map = {node.node_id: node for node in workflow.nodes}
        
        for edge in workflow.edges:
            source, target = edge[0], edge[1]
            if source in graph and target in graph:
                graph[source].append(target)
                in_degree[target] += 1
            else:
                logger.error(f"{Fore.RED}Invalid edge: {source} -> {target}{Style.RESET_ALL}")
                raise ValueError(f"Invalid edge: {source} -> {target}")

        # 2. 拓扑排序 (Kahn's Algorithm)
        queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
        execution_order = []
        
        while queue:
            node_id = queue.popleft()
            execution_order.append(node_id)
            
            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        if len(execution_order) != len(workflow.nodes):
            logger.error(f"{Fore.RED}Cycle detected in workflow!{Style.RESET_ALL}")
            raise ValueError("Cycle detected in workflow")

        logger.debug(f"Execution order: {execution_order}")

        # 3. 按序执行 (Mock Execution)
        context = {"initial_input": initial_input}
        results = {}
        
        for node_id in execution_order:
            node = nodes_map[node_id]
            logger.info(f"Executing node: {Fore.YELLOW}{node_id}{Style.RESET_ALL} ({node.node_type})")
            
            # 模拟执行
            step_result = await self._execute_node(node, context)
            results[node_id] = step_result
            context[node_id] = step_result # 将结果存入上下文供后续节点使用
            
        # 4. 收集最终结果 (Exit Nodes)
        final_output = {node_id: results[node_id] for node_id in workflow.exit_nodes}
        logger.info(f"{Fore.GREEN}Workflow execution completed.{Style.RESET_ALL}")
        
        return final_output

    async def _execute_node(self, node: WorkflowNode, context: Dict[str, Any]) -> Any:
        # Mock implementation for Phase 0
        return f"Executed {node.node_id}"
