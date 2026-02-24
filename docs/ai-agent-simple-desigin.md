# AI Agent 架构设计（简化版）

## 文档版本
- **版本号**: v1.1
- **最后更新**: 2026-02-24
- **架构类型**: 轻量级通用 AI Agent 架构

---

## 1. 设计目标

构建一个轻量级但功能完整的 AI Agent 系统，具备以下核心能力：

1. **统一 LLM 调用**：支持多种模型供应商
2. **工具调用能力**：Agent 可以调用外部工具完成复杂任务
3. **记忆管理**：支持多轮对话上下文
4. **技能系统**：预定义可复用的 AI 技能
5. **工作流引擎**：支持顺序、并行、条件分支执行
6. **Agent 系统**：具备规划、执行、反思能力的智能体，支持子 Agent 协作
7. **对话服务**：支持普通对话场景
8. **渠道接入**：支持多渠道接入
9. **REST API**：提供标准化的接口

---

## 2. 平台架构

### 2.1 架构分层视图

```
┌─────────────────────────────────────────────────────────────┐
│                   Channel Layer（渠道层）                      │
│     REST API | Web Chat | Feishu | WhatsApp | SDK           │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                 Application Layer（应用层）                    │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐│
│  │   Chat Service │  │     Agent      │  │ Automation     ││
│  │                │  │    System     │  │    Service     ││
│  └────────────────┘  └────────────────┘  └────────────────┘│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│              Orchestration Layer（编排层）                      │
│  ┌────────────────────────┐  ┌────────────────────────────┐│
│  │      Workflow Engine   │  │      Task Orchestrator      ││
│  │     (工作流引擎)       │  │       (任务编排)            ││
│  └────────────────────────┘  └────────────────────────────┘│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│               Capability Layer（能力层）                       │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐│
│  │    Tool Hub    │  │   Memory      │  │     Skill      ││
│  │    (工具)      │  │   System      │  │    System      ││
│  └────────────────┘  └────────────────┘  └────────────────┘│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│              ⭐ LLM Hub（推理基础设施）⭐                       │
│  • 统一模型接入  • Prompt构建  • 流式输出  • 工具调用网关       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流向

```
用户请求
  ↓
Channel Layer (接入)
  ↓
Application Layer (路由到对应服务)
  ↓
Orchestration Layer (流程编排)
  ↓
Capability Layer (能力调用)
  ↓
LLM Hub (统一推理)
  ↓
响应返回
```

---

## 3. LLM Hub（推理基础设施）

LLM Hub 是系统的核心，负责统一管理所有 LLM 调用。

```
LLM Hub
├─ Provider Layer        # 供应商适配器
├─ Model Registry        # 模型注册中心
├─ Inference Engine      # 统一推理引擎
├─ Prompt Builder        # Prompt 构建器
├─ Streaming Manager     # 流式输出管理
└─ Tool Calling Gateway  # 工具调用网关
```

### 3.1 供应商适配器

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any

class LLMProvider(ABC):
    """LLM 供应商抽象接口"""
    
    @abstractmethod
    async def chat(
        self, 
        messages: list[dict],
        config: dict
    ) -> dict:
        """非流式对话"""
        pass
    
    @abstractmethod
    async def stream(
        self, 
        messages: list[dict],
        config: dict
    ) -> AsyncIterator[dict]:
        """流式对话"""
        pass
    
    @abstractmethod
    async def embeddings(
        self,
        texts: list[str],
        model: str
    ) -> list[list[float]]:
        """文本向量化"""
        pass
```

**支持的供应商：**
- OpenAI（GPT-4、GPT-3.5-turbo）
- Anthropic（Claude-3 系列）

### 3.2 模型注册中心

```python
from pydantic import BaseModel
from typing import Optional

class ModelMetadata(BaseModel):
    """模型元数据"""
    model_id: str                    # 模型唯一标识
    provider: str                    # 供应商
    model_name: str                  # 模型名称
    capabilities: list[str]          # 能力标签
    context_window: int              # 上下文窗口大小
    max_output_tokens: int          # 最大输出 tokens
    is_available: bool              # 是否可用

class ModelRegistry:
    """模型注册中心"""
    
    def register_model(self, metadata: ModelMetadata):
        """注册模型"""
        pass
    
    def get_model(self, model_id: str) -> ModelMetadata:
        """获取模型"""
        pass
    
    def list_models(self) -> list[ModelMetadata]:
        """列出所有模型"""
        pass
```

### 3.3 统一推理引擎

```python
class InferenceEngine:
    """统一推理引擎"""
    
    async def infer(
        self,
        messages: list[dict],
        config: dict
    ) -> dict:
        """执行推理"""
        
        # 1. 构建 Prompt
        prompt = await self.prompt_builder.build(messages)
        
        # 2. 选择模型（简单选择，可扩展路由）
        model = config.get("model", "gpt-4")
        
        # 3. 执行推理
        provider = self._get_provider(model)
        result = await provider.chat(prompt, config)
        
        return result
```

### 3.4 Prompt 构建器

```python
class PromptBuilder:
    """Prompt 构建器"""
    
    async def build(
        self,
        messages: list[dict]
    ) -> list[dict]:
        """构建完整 Prompt"""
        return messages
```

### 3.5 流式输出管理

```python
class StreamingManager:
    """流式输出管理器"""
    
    async def stream_response(
        self,
        provider: LLMProvider,
        messages: list[dict],
        config: dict
    ) -> AsyncIterator[dict]:
        """处理流式响应"""
        
        async for chunk in provider.stream(messages, config):
            yield chunk
```

### 3.6 工具调用网关

```python
class ToolCallingGateway:
    """工具调用网关"""
    
    async def execute_tool_calls(
        self,
        llm_response: dict,
        available_tools: list[Tool]
    ) -> list[dict]:
        """执行 LLM 请求的工具调用"""
        
        results = []
        
        # 解析工具调用
        tool_calls = self._parse_tool_calls(llm_response)
        
        for call in tool_calls:
            tool = self._find_tool(call.name, available_tools)
            result = await tool.execute(call.parameters)
            
            results.append({
                "tool_call_id": call.id,
                "tool_name": call.name,
                "result": result
            })
        
        return results
```

---

## 4. Tool Hub（工具系统）

### 4.1 工具抽象

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class ToolSchema(BaseModel):
    """工具 Schema"""
    name: str
    description: str
    parameters: dict  # JSON Schema 格式

class Tool(ABC):
    """工具抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass
    
    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """工具 Schema"""
        pass
    
    @abstractmethod
    async def execute(self, params: dict) -> dict:
        """执行工具"""
        pass
```

### 4.2 内置工具集

```python
# 搜索工具
class SearchTool(Tool):
    """网络搜索工具（DuckDuckGo）"""
    pass

# HTTP 请求工具
class HTTPRequestTool(Tool):
    """HTTP 请求工具"""
    pass

# 数据库查询工具
class DatabaseQueryTool(Tool):
    """安全的 SQL 查询工具"""
    pass

# 代码执行工具
class PythonExecutorTool(Tool):
    """Python 代码执行工具"""
    pass

# 文件读取工具
class FileReadTool(Tool):
    """文件读取工具"""
    pass

# 文件写入工具
class FileWriteTool(Tool):
    """文件写入工具"""
    pass

# 计算器工具
class CalculatorTool(Tool):
    """数学计算工具"""
    pass

# 日期时间工具
class DateTimeTool(Tool):
    """获取当前日期时间工具"""
    pass
```

### 4.3 工具中心

```python
class ToolHub:
    """工具中心"""
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register_tool(self, tool: Tool):
        """注册工具"""
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(name)
    
    def list_tools(self) -> list[Tool]:
        """列出所有工具"""
        return list(self._tools.values())
    
    def get_schemas(self, tools: list[Tool]) -> list[dict]:
        """获取工具 Schema 列表（用于 LLM）"""
        return [tool.schema.dict() for tool in tools]
```

---

## 5. Memory System（记忆系统）

### 5.1 短期记忆（会话上下文）

```python
class ShortTermMemory:
    """短期记忆（会话上下文）"""
    
    def __init__(self, max_messages: int = 10):
        self.max_messages = max_messages
        self.sessions: Dict[str, list[dict]] = {}
    
    def add_message(self, conversation_id: str, message: dict):
        """添加消息"""
        if conversation_id not in self.sessions:
            self.sessions[conversation_id] = []
        
        self.sessions[conversation_id].append(message)
        
        # 保持窗口大小
        if len(self.sessions[conversation_id]) > self.max_messages:
            self.sessions[conversation_id] = \
                self.sessions[conversation_id][-self.max_messages:]
    
    def get_context(self, conversation_id: str) -> list[dict]:
        """获取上下文"""
        return self.sessions.get(conversation_id, []).copy()
    
    def clear(self, conversation_id: str):
        """清空会话"""
        if conversation_id in self.sessions:
            self.sessions[conversation_id] = []
```

---

## 6. Skill System（技能系统）

技能是预定义的 AI 能力组合，包含 Prompt 模板和所需工具。

### 6.1 技能定义

```python
from enum import Enum
from pydantic import BaseModel

class MemoryStrategy(BaseModel):
    """记忆策略"""
    include_short_term: bool = True

class Skill(BaseModel):
    """技能定义"""
    skill_id: str
    name: str
    description: str
    prompt_template: str              # Prompt 模板
    required_tools: list[str]         # 所需工具
    optional_tools: list[str] = []    # 可选工具
    memory_strategy: MemoryStrategy    # 记忆策略
    examples: list[dict] = []         # Few-shot 示例
    tags: list[str] = []              # 标签
```

### 6.2 示例技能

```python
# 数据分析技能
DATA_ANALYSIS_SKILL = Skill(
    skill_id="data_analysis",
    name="数据分析",
    description="分析数据并生成洞察",
    prompt_template="""
你是一个数据分析专家。请分析以下数据:
{data}

要求:
1. 识别关键趋势
2. 发现异常值
3. 提供可行建议
""",
    required_tools=["python_executor"],
    memory_strategy=MemoryStrategy(include_short_term=True)
)

# 代码生成技能
CODE_GENERATION_SKILL = Skill(
    skill_id="code_generation",
    name="代码生成",
    description="根据需求生成代码",
    prompt_template="""
你是一个资深开发者。请根据以下需求生成代码:
{requirements}

语言: {language}
框架: {framework}

要求:
1. 代码符合最佳实践
2. 包含必要的注释
3. 处理边界情况
""",
    required_tools=["code_executor"],
    memory_strategy=MemoryStrategy(include_short_term=True)
)

# 文本写作技能
TEXT_WRITING_SKILL = Skill(
    skill_id="text_writing",
    name="文本写作",
    description="专业文本写作",
    prompt_template="""
请根据以下要求撰写文本:
主题: {topic}
类型: {content_type}
风格: {style}
字数要求: {word_count}
""",
    required_tools=[],
    memory_strategy=MemoryStrategy(include_short_term=False)
)

# 翻译技能
TRANSLATION_SKILL = Skill(
    skill_id="translation",
    name="翻译",
    description="多语言翻译",
    prompt_template="""
请将以下文本翻译成{target_language}:
{text}

要求:
1. 保持原文风格
2. 确保专业术语准确
""",
    required_tools=[],
    memory_strategy=MemoryStrategy(include_short_term=False)
)
```

### 6.3 技能管理器

```python
class SkillManager:
    """技能管理器"""
    
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
    
    def register_skill(self, skill: Skill):
        """注册技能"""
        self._skills[skill.skill_id] = skill
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取技能"""
        return self._skills.get(skill_id)
    
    def list_skills(self) -> list[Skill]:
        """列出所有技能"""
        return list(self._skills.values())
    
    async def execute_skill(
        self,
        skill_id: str,
        parameters: dict,
        context: dict
    ) -> dict:
        """执行技能"""
        
        skill = self.get_skill(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        # 1. 构建 Prompt
        prompt = skill.prompt_template.format(**parameters)
        
        # 2. 准备工具
        tools = [
            context["tool_hub"].get_tool(name)
            for name in skill.required_tools
        ]
        
        # 3. 执行推理
        result = await context["llm_hub"].infer(
            messages=[{"role": "user", "content": prompt}],
            tools=[t for t in tools if t],
            config=context.get("config", {})
        )
        
        return result
```

---

## 7. Workflow Engine（工作流引擎）

### 7.1 工作流定义

```python
from enum import Enum
from pydantic import BaseModel

class NodeType(Enum):
    """节点类型"""
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    SKILL_CALL = "skill_call"
    CONDITION = "condition"
    PARALLEL = "parallel"

class WorkflowNode(BaseModel):
    """工作流节点"""
    node_id: str
    node_type: NodeType
    config: dict                      # 节点配置
    inputs: list[str] = []           # 输入来源
    outputs: list[str] = []           # 输出目标

class Workflow(BaseModel):
    """工作流定义"""
    workflow_id: str
    name: str
    description: str
    nodes: list[WorkflowNode]
    edges: list[tuple[str, str]]     # (from, to)
    entry_node: str
    exit_nodes: list[str]
```

### 7.2 工作流引擎

```python
class WorkflowEngine:
    """工作流引擎"""
    
    async def execute(
        self,
        workflow: Workflow,
        initial_input: dict
    ) -> dict:
        """执行工作流"""
        
        # 1. 构建执行图
        graph = self._build_graph(workflow)
        
        # 2. 拓扑排序
        execution_order = self._topological_sort(graph)
        
        # 3. 执行节点
        node_results = {}
        
        for node_id in execution_order:
            node = self._get_node(workflow, node_id)
            node_input = self._collect_input(node, node_results, initial_input)
            
            result = await self._execute_node(node, node_input)
            node_results[node_id] = result
        
        return self._collect_output(workflow, node_results)
    
    async def _execute_node(self, node: WorkflowNode, input_data: dict) -> dict:
        """执行单个节点"""
        
        if node.node_type == NodeType.LLM_CALL:
            return await self._execute_llm_node(node, input_data)
        elif node.node_type == NodeType.TOOL_CALL:
            return await self._execute_tool_node(node, input_data)
        elif node.node_type == NodeType.SKILL_CALL:
            return await self._execute_skill_node(node, input_data)
        elif node.node_type == NodeType.CONDITION:
            return await self._execute_condition_node(node, input_data)
```

### 7.3 工作流示例

```python
# 意图路由工作流
INTENT_ROUTING_WORKFLOW = Workflow(
    workflow_id="intent_routing",
    name="意图路由工作流",
    nodes=[
        WorkflowNode(
            node_id="classify_intent",
            node_type=NodeType.LLM_CALL,
            config={
                "prompt": "分析用户意图，返回: data_analysis, code_generation, translation, general_chat",
                "model": "gpt-3.5-turbo"
            }
        ),
        WorkflowNode(
            node_id="route_decision",
            node_type=NodeType.CONDITION,
            config={
                "conditions": {
                    "data_analysis": "data_skill",
                    "code_generation": "code_skill",
                    "translation": "translate_skill",
                    "general_chat": "chat_skill"
                }
            }
        ),
        WorkflowNode(
            node_id="data_skill",
            node_type=NodeType.SKILL_CALL,
            config={"skill_id": "data_analysis"}
        ),
        WorkflowNode(
            node_id="code_skill",
            node_type=NodeType.SKILL_CALL,
            config={"skill_id": "code_generation"}
        ),
        WorkflowNode(
            node_id="translate_skill",
            node_type=NodeType.SKILL_CALL,
            config={"skill_id": "translation"}
        ),
        WorkflowNode(
            node_id="chat_skill",
            node_type=NodeType.SKILL_CALL,
            config={"skill_id": "text_writing"}
        )
    ],
    edges=[
        ("classify_intent", "route_decision"),
        ("route_decision", "data_skill"),
        ("route_decision", "code_skill"),
        ("route_decision", "translate_skill"),
        ("route_decision", "chat_skill")
    ],
    entry_node="classify_intent",
    exit_nodes=["data_skill", "code_skill", "translate_skill", "chat_skill"]
)
```

---

## 8. Agent 系统

### 8.1 Agent 定义

```python
class Agent(BaseModel):
    """智能体"""
    agent_id: str
    name: str
    description: str
    role: str                          # 角色定义
    system_prompt: str                 # 系统提示词
    capabilities: list[str]           # 能力列表
    available_tools: list[str]         # 可用工具
    available_skills: list[str]       # 可用技能
    child_agents: list[str] = []      # 子 Agent
    model_config: dict                # 模型配置

class AgentConfig(BaseModel):
    """Agent 配置"""
    planning_model: str = "gpt-4"
    execution_model: str = "gpt-3.5-turbo"
    max_iterations: int = 10
    timeout_seconds: int = 60
```

### 8.2 Agent 组件架构

```
Agent
├─ Planning Engine         # 规划引擎
├─ Execution Engine        # 执行引擎
├─ Reflection Engine       # 反思引擎
├─ Tool Access            # 工具访问接口
├─ Skill Access           # 技能访问接口
├─ Memory Access          # 记忆访问接口
├─ LLM Hub Client         # LLM Hub 客户端
└─ Child Agent Manager    # 子 Agent 管理器
```

### 8.3 规划引擎

```python
class PlanningEngine:
    """规划引擎"""
    
    async def create_plan(
        self,
        agent: Agent,
        task: str,
        available_tools: list[Tool],
        available_skills: list[Skill]
    ) -> dict:
        """创建执行计划"""
        
        prompt = f"""
你是 {agent.name}，{agent.description}

任务: {task}

可用工具:
{self._format_tools(available_tools)}

可用技能:
{self._format_skills(available_skills)}

子 Agent:
{agent.child_agents}

请制定详细的执行计划，以 JSON 格式返回:
{{
  "steps": [
    {{"action": "tool", "tool_name": "...", "params": {{...}}}},
    {{"action": "skill", "skill_id": "...", "params": {{...}}}},
    {{"action": "delegate", "agent_id": "...", "task": "..."}},
    {{"action": "final_answer", "content": "..."}}
  ],
  "reasoning": "你的推理过程"
}}
"""
        
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": prompt}],
            config={"model": agent.model_config.planning_model}
        )
        
        return self._parse_plan(result)
```

### 8.4 执行引擎

```python
class ExecutionEngine:
    """执行引擎"""
    
    async def execute_plan(
        self,
        agent: Agent,
        plan: dict,
        tool_hub: ToolHub,
        skill_manager: SkillManager,
        child_agent_manager
    ) -> dict:
        """执行计划"""
        
        results = []
        
        for step in plan.steps:
            if step.action == "tool":
                result = await self._execute_tool(
                    tool_hub, step.tool_name, step.params
                )
                results.append(result)
            elif step.action == "skill":
                result = await self._execute_skill(
                    skill_manager, step.skill_id, step.params
                )
                results.append(result)
            elif step.action == "delegate":
                result = await self._delegate_to_agent(
                    child_agent_manager, step.agent_id, step.task
                )
                results.append(result)
            elif step.action == "final_answer":
                return {"success": True, "result": step.content}
        
        return {"success": False, "result": results}
```

### 8.5 反思引擎

```python
class ReflectionEngine:
    """反思引擎"""
    
    async def reflect(
        self,
        agent: Agent,
        task: str,
        execution_result: dict
    ) -> dict:
        """反思执行结果"""
        
        prompt = f"""
任务: {task}
执行结果: {execution_result}

请评估:
1. 任务是否完成?
2. 结果质量如何?
3. 是否需要改进?
4. 下一步应该做什么?

以 JSON 格式返回:
{{
  "success": true/false,
  "needs_replanning": true/false,
  "feedback": "改进建议",
  "summary": "结果总结"
}}
"""
        
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": prompt}],
            config={"model": agent.model_config.execution_model}
        )
        
        return self._parse_reflection(result)
```

### 8.6 子 Agent 管理器

```python
class ChildAgentManager:
    """子 Agent 管理器"""
    
    def __init__(self, agent_registry):
        self.agent_registry = agent_registry
    
    async def delegate_task(
        self,
        parent_agent: Agent,
        child_agent_id: str,
        task: str
    ) -> dict:
        """委派任务给子 Agent"""
        
        child_agent = self.agent_registry.get_agent(child_agent_id)
        if not child_agent:
            return {"error": f"Agent not found: {child_agent_id}"}
        
        executor = AgentExecutor(
            llm_hub=self.llm_hub,
            tool_hub=self.tool_hub,
            skill_manager=self.skill_manager
        )
        
        result = await executor.execute(
            agent=child_agent,
            task=task
        )
        
        return result
```

### 8.7 主子 Agent 示例

```python
# 客服主 Agent
CUSTOMER_SERVICE_MASTER = Agent(
    agent_id="cs_master",
    name="客服总监",
    description="负责客户服务的总协调",
    role="你是专业的客服总监，负责协调处理客户问题",
    system_prompt="你是一个专业的客服总监...",
    capabilities=["问题分类", "任务委派", "结果整合"],
    available_tools=["database_query"],
    available_skills=["text_writing"],
    child_agents=["order_agent", "refund_agent", "technical_agent"]
)

# 订单处理 Worker Agent
ORDER_AGENT = Agent(
    agent_id="order_agent",
    name="订单专员",
    description="专业处理订单相关问题",
    role="你是订单处理专员...",
    system_prompt="你是一个专业的订单处理专员...",
    capabilities=["订单查询", "订单更新"],
    available_tools=["database_query"],
    available_skills=["data_analysis"],
    child_agents=[]
)

# 退款处理 Worker Agent
REFUND_AGENT = Agent(
    agent_id="refund_agent",
    name="退款专员",
    description="专业处理退款相关问题",
    role="你是退款处理专员...",
    system_prompt="你是一个专业的退款处理专员...",
    capabilities=["退款查询", "退款处理"],
    available_tools=["database_query"],
    available_skills=[],
    child_agents=[]
)
```

### 8.8 客服 + 订单场景的落地实现（本项目）

在当前代码仓库中，以上通用模型已经被具体化为一个**客服 + 订单查询** Demo，核心实现位于：

- `app/agents/library/customer_service.py`：定义了三个典型 Agent：
  - `cs_master`（客服总监，主 Agent）
  - `order_agent`（订单专员，子 Agent）
  - `refund_agent`（退款专员，子 Agent）
- `app/tools/builtin/database.py` + `app/db/seed_order_data.py`：封装 `DatabaseQueryTool` 与内存订单数据库（包含 `customers / products / orders / order_items / refunds` 等表），启动时自动注入 1001–1010 号订单测试数据并同步 Schema 到工具描述。

**具体策略如下：**

- `cs_master`：
  - `available_tools=["datetime"]`，**不具备数据库查询能力**。
  - 角色 Prompt 明确要求：若问题涉及订单 / 配送 / 退款，必须委派给 `order_agent` 或 `refund_agent`，自己只做任务拆分与结果整合。
- `order_agent`：
  - `available_tools=["database_query", "http_request", "datetime"]`，专职处理订单查询、订单状态、配送跟踪。
  - 直接对接内存订单数据库，通过 `DatabaseQueryTool` 查询真实数据。
- `refund_agent`：
  - `available_tools=["database_query", "calculator", "datetime"]`，专职处理退款相关问题。

**执行过程示例（订单查询）：**

1. 用户调用 `cs_master`：`"帮我查询订单号 1002 的详细情况，包括商品、客户和配送状态。"`
2. 规划引擎根据 `cs_master.available_tools` 发现其不具备 `database_query` 能力，规划步骤中不会出现数据库工具调用，而是生成 `delegate` 步骤，将任务委派给 `order_agent`。
3. `order_agent` 使用 `database_query` 一次性 JOIN 多表（`orders + customers + order_items`），拿到订单状态、客户信息和商品明细。
4. 执行引擎收集工具结果，调用 LLM 合成自然语言答案，返回给用户（不再包含 `{status}`、`[customer_name]` 这类占位符，而是落地的真实字段值）。

> 总结：`available_tools` 和 `available_skills` 不仅是元数据声明，实际在 **规划阶段用于过滤可见能力**，在 **执行阶段用于强制授权校验**，从而实现“主 Agent 负责协调，子 Agent 负责落地”的多智能体协作模式。
```

---

## 9. LangGraph 集成

使用 LangGraph 作为 Agent 的执行引擎。

```python
from typing import TypedDict
from langgraph.graph import StateGraph

class AgentState(TypedDict):
    """Agent 状态"""
    messages: list[dict]           # 对话消息
    current_plan: dict             # 当前计划
    tool_outputs: list[dict]       # 工具输出
    iterations: int                # 迭代次数
    final_result: dict             # 最终结果

class LangGraphAgentExecutor:
    """基于 LangGraph 的 Agent 执行器"""
    
    def __init__(self, llm_hub, tool_hub, skill_manager):
        self.llm_hub = llm_hub
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """构建状态图"""
        
        graph = StateGraph(AgentState)
        
        # 添加节点
        graph.add_node("plan", self._plan_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("reflect", self._reflect_node)
        
        # 添加边
        graph.set_entry_point("plan")
        graph.add_edge("plan", "execute")
        graph.add_edge("execute", "reflect")
        
        # 条件边
        graph.add_conditional_edges(
            "reflect",
            self._should_continue,
            {"continue": "plan", "end": "final_result"}
        )
        
        return graph.compile()
    
    async def execute(
        self,
        agent: Agent,
        task: str,
        conversation_history: list[dict] = []
    ) -> dict:
        """执行 Agent"""
        
        initial_state = {
            "messages": conversation_history,
            "current_plan": {},
            "tool_outputs": [],
            "iterations": 0,
            "final_result": {}
        }
        
        result = await self.graph.ainvoke(initial_state)
        
        return result["final_result"]
```

---

## 10. Chat Service（对话服务）

```python
class ChatService:
    """对话服务"""
    
    def __init__(self, llm_hub, memory: ShortTermMemory):
        self.llm_hub = llm_hub
        self.memory = memory
    
    async def chat(
        self,
        conversation_id: str,
        message: str,
        system_prompt: str = None
    ) -> dict:
        """处理对话"""
        
        # 1. 获取上下文
        context = self.memory.get_context(conversation_id)
        
        # 2. 构建消息
        messages = context + [{"role": "user", "content": message}]
        
        # 3. 添加 System Prompt
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages
        
        # 4. 调用 LLM
        response = await self.llm_hub.infer(messages=messages, config={})
        
        # 5. 更新记忆
        self.memory.add_message(conversation_id, {"role": "user", "content": message})
        self.memory.add_message(conversation_id, {"role": "assistant", "content": response.content})
        
        return response
```

---

## 11. Automation Service（自动化服务）

```python
class AutomationService:
    """自动化服务"""
    
    async def data_processing(
        self,
        data: dict,
        processing_config: dict
    ) -> dict:
        """数据处理自动化"""
        # 使用 LLM + 工具进行数据处理
        pass
    
    async def report_generation(
        self,
        data_source: str,
        template: str
    ) -> str:
        """报告生成自动化"""
        # 使用 LLM 生成报告
        pass
    
    async def code_generation(
        self,
        requirements: str,
        language: str
    ) -> str:
        """代码生成自动化"""
        pass
```

---

## 12. Channel Layer（渠道层）

### 12.1 渠道适配器抽象

```python
from abc import ABC, abstractmethod

class ChannelAdapter(ABC):
    """渠道适配器"""
    
    @abstractmethod
    async def receive_message(self) -> dict:
        """接收消息"""
        pass
    
    @abstractmethod
    async def send_message(self, message: dict):
        """发送消息"""
        pass

class ChannelManager:
    """渠道管理器"""
    
    def __init__(self):
        self.adapters: Dict[str, ChannelAdapter] = {}
    
    def register_channel(self, channel_id: str, adapter: ChannelAdapter):
        """注册渠道"""
        self.adapters[channel_id] = adapter
    
    async def route_message(self, channel_id: str, message: dict):
        """路由消息到对应服务"""
        # 识别意图
        intent = await self._classify_intent(message)
        
        # 路由到对应服务
        if intent == "agent_task":
            result = await self.agent_service.execute(message)
        elif intent == "chat":
            result = await self.chat_service.chat(message)
        elif intent == "automation":
            result = await self.automation_service.process(message)
        
        # 发送响应
        adapter = self.adapters[channel_id]
        await adapter.send_message(result)
```

### 12.2 REST API 适配器

```python
class RESTAPIAdapter(ChannelAdapter):
    """REST API 渠道适配器"""
    
    async def receive_message(self) -> dict:
        """从请求中获取消息"""
        pass
    
    async def send_message(self, message: dict):
        """返回响应"""
        pass
```

### 12.3 Web Chat 适配器

```python
class WebChatAdapter(ChannelAdapter):
    """Web Chat 渠道适配器"""
    
    async def receive_message(self) -> dict:
        """接收 WebSocket 消息"""
        pass
    
    async def send_message(self, message: dict):
        """发送 WebSocket 消息"""
        pass
```

---

## 13. API 设计

### 13.1 端点定义

```python
# app/api/endpoints/chat.py
router = APIRouter()

@router.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """对话接口"""
    pass

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口"""
    pass

@router.delete("/chat/{conversation_id}")
async def clear_chat(conversation_id: str):
    """清空对话"""
    pass

# app/api/endpoints/agents.py
router = APIRouter()

@router.post("/agents/{agent_id}/execute")
async def execute_agent(
    agent_id: str,
    request: AgentExecuteRequest
) -> AgentExecuteResponse:
    """执行 Agent"""
    pass

@router.get("/agents")
async def list_agents() -> list[AgentInfo]:
    """列出所有 Agent"""
    pass

@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> AgentDetail:
    """获取 Agent 详情"""
    pass

# app/api/endpoints/workflows.py
router = APIRouter()

@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecuteRequest
) -> WorkflowExecuteResponse:
    """执行工作流"""
    pass

@router.get("/workflows")
async def list_workflows() -> list[WorkflowInfo]:
    """列出所有工作流"""
    pass

# app/api/endpoints/skills.py
router = APIRouter()

@router.get("/skills")
async def list_skills() -> list[SkillInfo]:
    """列出所有技能"""
    pass

@router.post("/skills/{skill_id}/execute")
async def execute_skill(
    skill_id: str,
    request: SkillExecuteRequest
) -> SkillExecuteResponse:
    """执行技能"""
    pass

# app/api/endpoints/tools.py
router = APIRouter()

@router.get("/tools")
async def list_tools() -> list[ToolInfo]:
    """列出所有工具"""
    pass
```

---

## 14. 目录结构

```
app/
├── api/
│   ├── __init__.py
│   ├── api.py              # API 路由集合
│   └── endpoints/
│       ├── __init__.py
│       ├── chat.py        # 对话接口
│       ├── agents.py      # Agent 接口
│       ├── workflows.py   # 工作流接口
│       ├── skills.py      # 技能接口
│       └── tools.py       # 工具接口
│
├── llm_hub/
│   ├── __init__.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py       # 供应商抽象基类
│   │   ├── openai.py     # OpenAI 适配器
│   │   └── anthropic.py  # Anthropic 适配器
│   ├── registry.py       # 模型注册中心
│   ├── inference.py      # 推理引擎
│   ├── prompt_builder.py # Prompt 构建器
│   ├── streaming.py      # 流式输出管理
│   └── tool_gateway.py    # 工具调用网关
│
├── agents/
│   ├── __init__.py
│   ├── base.py           # Agent 基类
│   ├── planning.py      # 规划引擎
│   ├── execution.py     # 执行引擎
│   ├── reflection.py     # 反思引擎
│   └── library/          # Agent 库
│       ├── __init__.py
│       ├── customer_service.py
│       ├── data_analyst.py
│       └── code_assistant.py
│
├── tools/
│   ├── __init__.py
│   ├── base.py          # 工具基类
│   ├── hub.py           # 工具中心
│   └── builtin/         # 内置工具
│       ├── __init__.py
│       ├── search.py
│       ├── http.py
│       ├── database.py
│       ├── file.py
│       ├── executor.py
│       ├── calculator.py
│       └── datetime.py
│
├── memory/
│   ├── __init__.py
│   └── short_term.py    # 短期记忆
│
├── skills/
│   ├── __init__.py
│   ├── base.py         # 技能基类
│   ├── manager.py      # 技能管理器
│   └── library/        # 技能库
│       ├── __init__.py
│       ├── data_analysis.py
│       ├── code_generation.py
│       ├── text_writing.py
│       └── translation.py
│
├── workflows/
│   ├── __init__.py
│   ├── engine.py       # 工作流引擎
│   ├── nodes.py        # 节点定义
│   └── templates/      # 工作流模板
│       ├── __init__.py
│       └── intent_routing.py
│
├── channels/
│   ├── __init__.py
│   ├── base.py        # 渠道基类
│   ├── manager.py     # 渠道管理器
│   └── adapters/      # 渠道适配器
│       ├── __init__.py
│       ├── rest_api.py
│       └── web_chat.py
│
├── services/
│   ├── __init__.py
│   ├── chat_service.py     # 对话服务
│   └── automation_service.py # 自动化服务
│
├── core/
│   ├── __init__.py
│   └── config.py          # 配置
│
├── main.py                 # 应用入口
└── __init__.py
```

---

## 15. 核心流程

### 15.1 对话流程

```
用户消息
  ↓
获取会话上下文
  ↓
构建 Prompt
  ↓
调用 LLM Hub
  ↓
返回响应
  ↓
更新记忆
```

### 15.2 Agent 执行流程

```
用户任务
  ↓
规划引擎：创建执行计划
  ↓
执行引擎：按计划执行
  ↓
反思引擎：评估结果
  ↓
成功？→ 返回结果
  ↓ 否
迭代次数 < 最大？ → 重新规划
  ↓
达到最大迭代 → 返回失败
```

### 15.3 工作流执行流程

```
工作流定义
  ↓
构建执行图
  ↓
拓扑排序
  ↓
按序执行节点
  ↓
收集最终结果
```

### 15.4 子 Agent 协作流程

```
主 Agent 接收任务
  ↓
分析任务，判断是否需要委派
  ↓
不需要委派 → 自己执行
  ↓
委派给子 Agent
  ↓
子 Agent 执行任务
  ↓
主 Agent 整合结果
```

---

## 16. 依赖配置

```toml
[tool.poetry.dependencies]
python = "^3.11"

# Web 框架
fastapi = "^0.109.0"
uvicorn = {extras = ["standard"], version = "^0.27.0"}

# 数据验证
pydantic = "^2.5.0"
pydantic-settings = "^2.1.0"

# LLM 集成
openai = "^1.12.0"
anthropic = "^0.21.0"
httpx = "^0.26.0"

# LangGraph 框架
langgraph = "^0.2.0"

# 缓存
redis = "^5.0.0"

# 日志与工具
loguru = "^0.7.2"
python-dotenv = "^1.0.0"
pyyaml = "^6.0.1"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.0"
pytest-asyncio = "^0.23.0"
httpx = "^0.26.0"
```

---

## 17. 后续扩展方向

完成核心功能后，可逐步添加：

1. **成本管理**：Token 计数、成本追踪
2. **安全防护**：输入输出过滤、权限控制
3. **可观测性**：链路追踪、性能监控
4. **多租户**：租户隔离、配额管理
5. **更多供应商**：Google Gemini、Azure OpenAI
6. **向量记忆**：长期记忆、语义检索
7. **EventBus**：事件驱动架构
8. **Runtime Sandbox**：安全执行环境
