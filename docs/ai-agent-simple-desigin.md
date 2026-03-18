# AI Agent 架构设计（简化版）

## 文档版本
- **版本号**: v1.5
- **最后更新**: 2026-03-16
- **架构类型**: 轻量级通用 AI Agent 架构

---

## 1. 设计目标

构建一个轻量级但功能完整的 AI Agent 系统，具备以下核心能力：

1. **统一 LLM 调用**：支持多种模型供应商
2. **工具调用能力**：Agent 可以调用外部工具完成复杂任务
3. **记忆管理**：支持多轮对话上下文
4. **技能系统**：基于 `SKILL.md` 的动态技能包（Metadata 路由 + 懒加载执行）
5. **工作流引擎**：支持顺序、并行、条件分支执行
6. **Agent 系统**：具备规划、执行、反思能力的智能体，支持子 Agent 协作
7. **错误感知自我纠错**：收集执行错误，通过 LLM 分析根因并指导重规划，防止反复触碰失败路径
8. **对话服务**：支持普通对话场景
9. **渠道接入**：支持多渠道接入
10. **REST API**：提供标准化的接口

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

### 2.3 动态技能数据流（已落地）

```
用户任务
  ↓
[技能发现] SkillManager.discover_skills()
  └─ 扫描 app/skills/skills_md/*/SKILL.md，建立轻量元数据索引
  ↓
[技能路由] _route_skills_by_metadata()
  └─ 第一阶段（规则预筛）：
     - 基于任务文本 + 技能 metadata（when_to_use/tags/inputs/description）打分
     - `skill_boost_rules` 由 metadata 动态构建（非写死技能映射），并做通用词抑制
     - 输出 Top-K 候选技能
  ↓
[规划] PlanningEngine 仅看到“已筛选技能”的轻量信息（非全文 Prompt）
  └─ 第二阶段（LLM 决策）：由 LLM 在候选技能中决定是否调用技能、调用哪个技能及参数
  ↓
[执行] ExecutionEngine._execute_skill()
  └─ skill_manager.get_skill() 按需懒加载完整技能正文与资源
  └─ 按技能声明工具白名单过滤，执行局部推理
  ↓
返回技能结果 / 继续执行后续步骤（如 file_write、final_answer）
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

### 5.1 运行级记忆 (AgentRunMemory)

存储单次 `execute` 任务过程中的详细行为消息（包括计划、工具调用、反思结论等），格式兼容 OpenAI `messages` 数组格式，便于在整个流程引擎的计算节点（Planning Engine, Execution Engine, Reflection Engine）间流转。

### 5.2 会话级任务摘要记忆 (AgentSessionMemory)

存储跨次任务的压缩摘要条目。每次 `execute` 完成后，系统会提取该次任务的核心结论和数据特征（TaskSummaryEntry），并追加至该会话的记忆仓库中。在下一次执行新任务时，这些摘要将作为前置背景上下文（conversation_history），提供给大模型参考，实现对话的连贯度与避免信息重复获取。

---

## 6. Skill System（技能系统）

技能系统已从“代码硬注册”升级为“文件系统动态加载”模式，核心原则如下：

1. 决策阶段只暴露轻量元信息（Metadata），不把所有技能正文塞进 Prompt  
2. 执行阶段按需懒加载（Lazy Loading）目标技能全文、脚本与资源  
3. 技能执行时按技能声明做工具白名单收敛，防止无关工具循环  

### 6.1 技能包目录规范

```
app/skills/skills_md/
├── weather/
│   ├── SKILL.md
│   ├── scripts/
│   └── resources/
├── tmux/
├── github/
├── api-log-reporter/
└── ...
```

每个技能是一个独立目录，最小要求是 `SKILL.md`，可选包含：
- `scripts/`：确定性脚本（推荐承载复杂统计与解析）
- `resources/`：参数说明、模板、规则文件等静态资源

### 6.2 `SKILL.md` 协议（YAML + Markdown）

```markdown
---
name: api-log-reporter
description: 读取 API 运行日志并生成结构化日报
required_tools: ["shell_exec", "file_read"]
optional_tools: []
tags: ["api", "log", "report"]
memory_include_short_term: true
---

# 何时使用 (When to use)
- 需要分析 API 日志并输出日报

# 输入参数 (Inputs)
- log_path: 日志文件路径
- date_range: today/all/区间

# 执行指令 (Instructions)
...技能执行规则...

# 脚本 (Scripts)
- scripts/analyze_api_log.py

# 资源 (Resources)
- resources/param_schemas.json
```

说明：
- Frontmatter 用于发现阶段解析，构建 `SkillMetadata`
- Markdown 正文用于执行阶段注入 Prompt（Instructions）
- Inputs/Scripts/Resources 由 `SkillManager` 标准章节解析器提取

### 6.3 运行时数据模型

```python
class SkillMetadata(BaseModel):
    skill_id: str
    description: str
    source_path: str
    when_to_use: list[str]
    inputs: list[str]
    input_descriptions: dict[str, str]
    required_tools: list[str]
    optional_tools: list[str]
    tags: list[str]
    scripts: list[str]
    resources: list[str]

class Skill(BaseModel):
    skill_id: str
    description: str
    prompt_template: str         # Instructions 正文
    required_tools: list[str]
    optional_tools: list[str]
    param_schemas: dict[str, ParamSchema]
    source_path: str
    scripts: list[str]
    resources: list[str]
```

### 6.4 SkillManager 生命周期（Discover -> Route -> Lazy Load -> Runtime）

```python
class SkillManager:
    def discover_skills(force_reload=False, include_unavailable=False):
        # 扫描 skills_md/*/SKILL.md，解析 frontmatter + 标准章节
        ...

    def list_skill_metadata(include_unavailable=False):
        # 返回轻量元信息，供路由阶段使用
        ...

    def load_skill(skill_name):
        # 按需读取完整技能正文与参数元数据（懒加载）
        ...

    def list_skills():
        # 返回轻量 Skill 视图（供规划展示）
        ...

    async def execute_skill_runtime(...):
        # 组装运行时 Prompt 并调用 llm_hub.infer()
        ...
```

### 6.5 Agent 主链路中的技能动态路由与执行

1. **规划前路由**（`langgraph_executor.py`）  
   - `list_skills()` 获取候选技能轻量视图  
   - `_route_skills_by_metadata()` 采用“规则预筛 + LLM 决策”的混合模式：  
     - 规则预筛：基于任务文本、`when_to_use`、`tags`、`inputs`、`description` 打分  
     - `skill_boost_rules` 由 `_build_dynamic_skill_boost_rules()` 基于技能 metadata 动态构建，不再写死具体技能映射  
     - 对跨技能高频通用词做抑制、对低频区分词做增强，降低误召回  
   - 仅 Top-K 技能进入 Planning Prompt，降低噪声和 token 成本
   - LLM 规划阶段在候选集中做最终决策：是否调用技能、调用哪个技能、参数如何填写

2. **执行时懒加载**（`execution.py`）  
   - `_execute_skill()` 调用 `skill_manager.get_skill(skill_id)` 触发懒加载  
   - 使用 `safe_format` 构建技能 Prompt，并注入技能参数与执行硬约束  
   - 结合技能声明做工具过滤：  
     `agent.available_tools ∩ (required_tools ∪ optional_tools)`  
     再减去敏感工具（如 `file_write`）和用户已拒绝工具
   - 若 `required_tools` 缺失则快速失败，避免无效循环

3. **最终答案合成阶段**  
   - 合成阶段禁用工具调用（`InferenceConfig` 不注入 tools），避免总结阶段再次触发工具循环

4. **独立技能 API 路径一致性**（`/api/v1/skills/{skill_id}/execute`）  
   - 直调技能入口同样按 `required_tools/optional_tools` 过滤工具定义  
   - 缺失必需工具会快速返回错误，防止“带病运行”  
   - 敏感工具（如 `file_write`）默认不允许在技能内部隐式触发

### 6.6 技能动态加载时序（主路径）

```mermaid
flowchart TD
    A[用户任务] --> B[SkillManager.discover_skills]
    B --> C[list_skill_metadata]
    C --> D[_route_skills_by_metadata 规则预筛 Top-K]
    D --> E[PlanningEngine: LLM 在候选集中做最终技能决策]
    E --> F[ExecutionEngine _execute_skill]
    F --> G[load_skill(skill_id) 懒加载完整技能]
    G --> H[按技能工具白名单过滤可用工具]
    H --> I[LLM 执行技能指令]
    I --> J[返回技能结果/进入后续工具步骤]
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
├─ Execution Engine        # 执行引擎（委派步骤经 Tool Hub 的 spawn_agent 执行）
├─ Reflection Engine      # 反思引擎
├─ Tool Access            # 工具访问接口（含 SpawnAgentTool）
├─ Skill Access           # 技能访问接口
├─ Memory Access          # 记忆访问接口
├─ LLM Hub Client         # LLM Hub 客户端
└─ Child Agent Manager    # 子 Agent 管理器（委派时由 SpawnAgentTool 内调，兜底直调）
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
```

**规划修正规则 (Interactive Pause Logic)**:
- **原则**: 除了交互场景外，最后一步必须是 `final_answer`。
- **例外**: 若本轮计划的核心动作是调用 `send_message` 工具（`message_type='input'` 或 `'confirm'`）挂起并等待用户。此时**禁止**在计划中包含 `final_answer`。只需规划 `send_message` 即可，系统会在用户回复后自动触发下一轮迭代进行后续真实业务处理。
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
        child_agent_manager,
        on_step_start: Optional[Callable] = None,   # 新增：步骤开始回调
        on_step_complete: Optional[Callable] = None # 步骤完成回调
    ) -> dict:
        """执行计划"""
        
        results = []
        
        for step_idx, step in enumerate(plan.steps):
            # 1. 触发步骤开始回调（推送 tool_start/delegate_start 等）
            if on_step_start:
                await on_step_start(step, step_idx, len(plan.steps))
                
            # 2. 执行具体步骤
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
        execution_result: dict,
        error_context: list[dict] = None,    # 历史失败步骤列表（跨迭代累积）
        available_tools: list[Tool] = None   # 授权工具（过滤 LLM function calling 列表）
    ) -> dict:
        """反思执行结果，携带 error_context 时进行错误感知反思"""
        
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


### 8.6 子 Agent 管理器与委派统一路径

#### 8.6.1 ChildAgentManager

```python
class ChildAgentManager:
    """子 Agent 管理器"""
    
    def __init__(self, agent_registry):
        self.agent_registry = agent_registry
    
    async def delegate_task(
        self,
        parent_agent_id: str | None,
        child_agent_id: str,
        task: str,
        stream_callback=None,
        pending_confirmations=None,
        user_rejected_tools=None
    ) -> dict:
        """委派任务给子 Agent，透传流式回调与确认状态"""
        
        child_agent = self.agent_registry.get_agent(child_agent_id)
        if not child_agent:
            return {"success": False, "error": f"Agent not found: {child_agent_id}"}
        
        # 使用 execute_with_callback 执行子 Agent，保证 SSE 与确认透传
        result = await self._executor.execute_with_callback(
            agent=child_agent,
            task=task,
            stream_callback=stream_callback,
            pending_confirmations=pending_confirmations,
            user_rejected_tools=user_rejected_tools
        )
        return result
```

#### 8.6.2 委派统一路径：SpawnAgentTool 优先

委派有两种触发方式，但**执行时统一经由 SpawnAgentTool（工具层）**，保证上下文注入与行为一致：

| 触发方式 | 说明 | 执行入口 |
|----------|------|----------|
| 规划步骤 `action: "delegate"` | LLM 直接产出委派步骤 | `ExecutionEngine._delegate_to_agent` → 优先调用 **SpawnAgentTool.execute()**，失败时兜底 `ChildAgentManager.delegate_task` |
| 规划步骤 `action: "tool", tool_name: "spawn_agent"` | LLM 选择调用 spawn_agent 工具 | `ExecutionEngine._execute_tool` → 经工具网关执行 SpawnAgentTool |

**设计要点**：

- **SpawnAgentTool**（`app/tools/builtin/spawn.py`）：在 ToolHub 中注册为 `spawn_agent`，内部调用 `ChildAgentManager.delegate_task`。支持 **update_context(stream_callback, pending_confirmations, user_rejected_tools)**，在每次执行前由执行引擎注入当前运行时上下文，确保子 Agent 的 SSE 事件与用户确认行为与主 Agent 一致。
- **执行引擎**：`_execute_tool` 对带有 `update_context` 方法的工具（如 SpawnAgentTool、MessageAgentTool）在调用前注入 `context` 中的 `stream_callback`、`pending_confirmations`、`user_rejected_tools`；`_delegate_to_agent` 从 ToolHub 获取 `spawn_agent` 并先对其执行 `update_context` 再调用 `execute()`，实现委派路径统一。
- **兜底**：若 SpawnAgentTool 未注册或执行异常，`_delegate_to_agent` 会回退为直接调用 `ChildAgentManager.delegate_task`，仍能完成委派，但建议保持 SpawnAgentTool 可用以保证流式与确认透传。

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


### 8.9 错误感知机制（Error-Aware Self-Correction）

在 Agent 执行过程中，步骤可能由于以下原因失败：工具执行异常、工具权限被拒绝、技能调用失败、子 Agent 委派错误等。若不加处理，LLM 在重规划时会继续尝试相同的失败路径，导致死循环直至达到 `max_iterations` 上限。

#### 错误记录结构（error_context）

每次步骤执行失败，均生成一条结构化错误记录并追加到 `AgentState.error_context` 列表（跨迭代累积）：

```python
error_record = {
    "step": step.action,           # 步骤类型: tool / skill / delegate
    "tool_name": step.tool_name,   # 工具名称（如 database_query）
    "error": str(error),           # 错误消息
    "iteration": iteration,        # 发生的迭代轮次
    "params": step.params          # 调用参数（便于根因分析）
}
```

#### LLM 根因分析（_analyze_errors → error_analysis）

当 `error_context` 非空时，执行引擎额外调用 LLM 进行根因分析，生成结构化的 `error_analysis`：

```python
error_analysis = {
    "root_cause": "database_query 工具未在该 Agent 的授权列表中",
    "suggestions": ["将任务委派给具有数据库权限的子 Agent"],
    "corrective_plan": "重规划时生成 delegate 步骤，而不是直接调用工具"
}
```

分析结果通过 SSE 推送 `error_analysis` 事件，前端实时展示根因、建议和纠正方案。

#### 规划阶段工具 Schema 白名单过滤（核心防线）

**从根源上防止 LLM 规划禁用工具**：规划引擎在构建 LLM function calling 工具列表时，只传入 `available_tools` 白名单中的工具 Schema，被禁止的工具在 LLM 视角中完全不可见：

```python
# planning.py — create_plan() 核心过滤逻辑
allowed_tool_names = {t.name for t in available_tools}   # 白名单
all_schemas = self.tool_hub.get_schemas()                 # 全量
tools = [
    s for s in all_schemas
    if s.get("function", {}).get("name") in allowed_tool_names  # 白名单过滤
]
# reflection.py 中 reflect() 的 available_tools 参数用于同样的过滤
```

#### 错误感知完整流程

```
[执行步骤]
    │
    ├─ 步骤成功 ──────────────────────────────→ [继续执行下一步]
    │
    └─ 步骤失败
           │
           ↓
    生成 error_record，追加到 AgentState.error_context
           │
           ↓
    调用 _analyze_errors（LLM 根因分析）
       输出: root_cause / suggestions / corrective_plan
       流式推送 SSE: error_analysis_start → error_analysis
           │
           ↓
    [反思节点]  携带 error_context 调用反思 LLM
       工具 Schema 已按 available_tools 过滤（禁用工具不可见）
           │
           ├─ needs_replanning=false → [返回结果]
           │
           └─ needs_replanning=true
                   │
                   ↓
           [规划节点]  携带 error_context + error_analysis 重新规划
              Prompt 包含: 错误历史 + 根因分析 + 纠正建议
              工具列表: 白名单过滤，LLM 只看到授权工具
                   │
                   ↓
           生成新方案（不包含被禁工具，规避已知失败路径）
                   │
                   ↓
           [执行节点] 使用新方案继续执行
```

#### SSE 事件类型扩展

错误处理流程新增以下 SSE 事件：

| 事件名                 | 触发时机          | 数据内容                                               |
| ---------------------- | ----------------- | ------------------------------------------------------ |
| `error_analysis_start` | 开始 LLM 根因分析 | `{ message }`                                          |
| `error_analysis`       | 分析完成          | `{ root_cause, suggestions, corrective_plan, errors }` |
| `step_error`           | 单步骤执行失败    | `{ step, error, iteration }`                           |

---

### 8.10 用户确认流程（敏感操作需用户确认）

对写入本地文件等敏感工具（如 `file_write`），执行前需用户确认，避免误操作。

- **需确认工具**：在 `langgraph_executor` 中维护 `TOOLS_REQUIRING_CONFIRM`（如 `file_write`），执行到对应步骤时暂停并生成 `confirm_id`，通过 SSE 推送 `user_confirm_required`（含 `tool_name`、`message`、`params`、`confirm_id`）。
- **确认接口**：`POST /api/v1/agents/confirm/{confirm_id}`，请求体 `{"allowed": true|false}`。后端用 `asyncio.Event` 唤醒执行：允许则继续执行该步骤，拒绝则从计划中移除该步骤并将工具名加入 `user_rejected_tools`。
- **状态扩展**：`AgentState` 增加 `pending_confirmations: Dict[str, Any]`（key 为 confirm_id）、`user_rejected_tools: List[str]`。规划与反思阶段从 `available_tools` 中排除 `user_rejected_tools`，避免 LLM 再次规划已被用户拒绝的操作。
- **子 Agent**：子 Agent 与主 Agent 共用同一 `pending_confirmations` 引用，子 Agent 内触发的确认同样推送到前端，用户确认/拒绝后子 Agent 继续或跳过该步骤。

---

### 8.11 子 Agent 流式与确认传递

子 Agent 委派时需透传流式回调和确认状态，保证轨迹与确认行为一致。

- **透传**：主执行器将 `stream_callback`、`pending_confirmations`、`pending_user_inputs`、`user_rejected_tools`、`run_memory`（含 `user_inputs_cache`）以及 `iteration` 传入执行引擎；委派时优先通过 **SpawnAgentTool**（执行前对其调用 `update_context` 注入上述上下文），再由其内部调用 `ChildAgentManager.delegate_task`；子执行器使用 `execute_with_callback`，与主 Agent 共用同一挂起字典与流式通道。
- **运行时上下文注入**：对需依赖运行时上下文的工具（如 `spawn_agent`、`send_message`、`python_executor`），执行引擎在 `_execute_tool` 中检测工具的 `update_context` 方法，若存在则在执行前注入当前 `stream_callback`、`pending_confirmations`、`pending_user_inputs`、`user_rejected_tools`、`user_inputs_cache`，避免子 Agent 事件无法推流、输入弹窗无法唤醒或同一配置被重复询问。
- **事件**：委派前发送 `sub_agent_start`（含 `sub_agent_id`、`sub_agent_name`、`task`），委派后发送 `sub_agent_end`（含 `success`）；子 Agent 内部所有 SSE 事件在 payload 中附带 `is_sub_agent: true`、`sub_agent_id`、`sub_agent_name`，前端可据此做区块展示与配色区分。
- **子 Agent 执行结果约定**：`execute_with_callback` 的返回结构与 `ExecutionResult.to_dict()` 一致，使用 **`success`（布尔）** 表示是否成功，**不要**使用 `status == "success"` 等字符串判断；错误信息放在 `error` 字段。委派步骤的 `step_result` 会携带 `success`、`result`、`error`，供错误收集与前端展示。
- **合成答案**：子 Agent 的 `final_answer` 步骤结果会写回 `step_result.result`（真实合成文本），主 Agent 的 `step_complete` 事件中 `action=final_answer` 时携带 `answer` 字段，供前端在「合成最终答案」下展示具体答案。

---

### 8.12 交互式消息与行为透传设计

为了实现 Agent 与用户的高效互动及执行过程的透明化，系统设计了统一的交互与反馈机制，核心通过 `send_message` 工具及与之配套的 SSE 事件流实现。

#### 1. 核心交互工具：send_message
`send_message` (定义于 `app/tools/builtin/message.py`) 是 Agent 与前端通信的枢纽，其设计涵盖了以下场景：

- **收集必要输入**：当大模型判断完成当前任务（或后续工具调用/程序编写）必须依赖用户提供的特定参数（如邮箱地址、SMTP 配置等）时，通过 `message_type='input'` 主动下发输入表单。
- **操作确认**：对于敏感或高成本操作，利用 `message_type='confirm'` 引导用户进行二次确认。
- **用户选择**：通过预定义的选项（options）让用户在多个分支逻辑中做出选择。

#### 2. 执行状态与进度反馈
除直接交互外，Agent 的“思维流”也通过消息工具及运行时注入的流式回调实时同步至前端：

- **中间状态汇报**：模型在执行思考（thinking）、规划（planning）、反思（reflection）及具体步骤执行（execution）时，会通过该机制推送中间进展、思考摘要或当前状态。
- **非阻塞进度反馈**：在长耗时任务中，发送不带输入需求的进度通知，确保前端实时感知 Agent 存活及当前进度。

#### 3. 行为透传与上下文注入
为了保证主子 Agent 协作时交互的一致性，系统在执行引擎层实现了运行时上下文的自动注入。对于标记为交互类的工具（如 `send_message`、`python_executor`），执行引擎会在执行前自动注入当前的 `stream_callback`、`pending_confirmations`、`pending_user_inputs`、`run_memory.user_inputs_cache` 等核心对象，确保跨层级的消息都能准确触达前端并正确挂起/唤醒。

#### 4. 用户输入缓存与防重复询问（user_inputs_cache）
为避免同一任务内反复弹出相同输入表单（如 SMTP 配置），系统增加任务级缓存并接入执行链路：

- **缓存载体**：`AgentRunMemory.user_inputs_cache`，生命周期与单次任务一致，不跨任务共享。
- **写入时机**：
  - `send_message(message_type='input')` 收到用户反馈后，按字段分组写入（如 `smtp_config`、`db_config`）。
  - `await_user_input` 流程收到用户输入后，同步写入缓存。
- **读取时机**：`python_executor` 执行前若检测到 SMTP 场景，优先读取 `smtp_config`，命中即注入代码并跳过再次询问。
- **预检查规则**：SMTP 预检查只判断 SMTP 相关字段/调用是否为占位符，不再因业务数据中的 `example.com`（如客户邮箱）误判为“缺少 SMTP 配置”。

---

### 8.13 提示词模板架构（Prompt Template Architecture）

为避免在 `planning.py`、`execution.py`、`reflection.py`、`langgraph_executor.py` 中维护大段内联字符串，系统将核心提示词升级为「外置模板 + 统一渲染管理」：

- **模板目录分层**：`app/prompt/plan`、`app/prompt/reflection`、`app/prompt/langgraph`、`app/prompt/execution`
- **统一渲染入口**：`app/utils/prompt_manager.py`
  - 使用 Jinja2 模板渲染
  - 内置缓存，减少重复 IO 与重复编译
  - 启用 `StrictUndefined`，变量缺失时快速失败，避免静默错误
- **统一路径解析**：`app/utils/resource_path.py`，确保在不同启动目录下都能稳定定位资源文件
- **可靠性策略**：
  - 引擎初始化阶段尝试预加载关键模板，尽早暴露资源配置问题
  - 关键执行链路保留「模板渲染失败 -> 内置提示词回退」兜底，保障主流程可用性

该设计将 Prompt 从“实现细节”提升为“可管理资产”，便于版本化、审阅与后续灰度演进。

---

## 9. LangGraph 集成

使用 LangGraph 作为 Agent 的执行引擎。

```python
from typing import TypedDict
from langgraph.graph import StateGraph

class AgentState(TypedDict):
    """Agent 状态"""
    messages: list[dict]           # 对话消息（可含 LangChain BaseMessage，规划时仅用 dict 消息）
    current_plan: dict             # 当前计划
    tool_outputs: list[dict]       # 工具输出
    iterations: int                # 迭代次数
    final_result: dict             # 最终结果，来自 ExecutionResult.to_dict()，含 success(bool)、result、step_results、error 等
    error_context: list[dict]      # 历史失败步骤（跨迭代累积）
    error_analysis: dict           # LLM 对错误的根因分析结果
    reflection_history: list[dict] # 历次反思结论（跨迭代），供下一轮规划使用
    pending_confirmations: dict    # 待用户确认操作，key=confirm_id，value=Event 等
    pending_user_inputs: dict      # 待用户输入操作，key=input_request_id，value=Event 等
    user_rejected_tools: list[str] # 用户拒绝过的工具名，规划/反思时从可用工具中排除
    run_memory: AgentRunMemory     # 任务内运行记忆（含 user_inputs_cache）

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

#### 跨迭代规划上下文（规划时带入上一轮记忆）

重规划时，除 `error_context` / `error_analysis` 外，将上一轮的计划、执行与反思结果注入规划 Prompt，减少重复执行、尊重用户拒绝：

- **planning_context**（在 `_plan_node` 中从 `state["messages"]` 与 `final_result` 提取）：`iteration`、`user_rejected_tools`、`last_plan`、`last_execution`、`last_final_result`；规划引擎 `create_plan(..., context=planning_context)`，在 `_build_planning_prompt` 中追加「跨迭代执行上下文」区块，约束 LLM 复用已有数据、勿重复调用已拒绝工具。
- **reflection_history**：每轮反思完成后将结果追加到 `AgentState.reflection_history`，规划时可一并传入，供 LLM 参考历史反思结论。

#### 迭代防循环（_should_continue）

在条件边 `_should_continue` 中增加熔断，避免用户拒绝关键工具后子 Agent 反复给出相同建议：

- **无可执行动作**：若 `user_rejected_tools` 非空且本轮步骤结果中仅有 `final_answer`（无新工具/委派），判定为无新可执行动作，直接结束。
- **重复反思**：若最近 3 轮反思均为「未成功 + 需要重规划」且反馈/总结高度相似，判定为重复反思循环，直接结束。

---

## 10. Chat Service（对话服务）

```python
class ChatService:
    """对话服务"""
    
    def __init__(self, llm_hub):
        self.llm_hub = llm_hub
    
    async def chat(
        self,
        conversation_id: str,
        message: str,
        system_prompt: str = None
    ) -> dict:
        """处理对话"""
        
        # 1. 获取上下文（从 Redis 或数据库获取，目前存在内存中）
        from app.services.chat_service import _chat_memory
        context = _chat_memory.get(conversation_id, [])
        
        # 2. 构建消息
        messages = context + [{"role": "user", "content": message}]
        
        # 3. 添加 System Prompt
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages
        
        # 4. 调用 LLM
        response = await self.llm_hub.infer(messages=messages, config={})
        
        # 5. 更新记忆
        _chat_memory.setdefault(conversation_id, []).extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": response.content}
        ])
        
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
│   ├── langgraph_executor.py # LangGraph 调度与错误分析
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
│   ├── skills.py       # 兼容层/辅助加载器
│   ├── skills_md/      # 主技能仓库（动态技能包）
│   │   └── <skill_name>/
│   │       ├── SKILL.md
│   │       ├── scripts/
│   │       └── resources/
│   └── library/        # 历史兼容目录（可逐步迁移）
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
├── utils/
│   ├── __init__.py
│   ├── prompt_manager.py  # 提示词加载/缓存/Jinja2 渲染
│   └── resource_path.py   # 资源路径解析
│
├── prompt/
│   ├── plan/              # 规划提示词模板
│   ├── reflection/        # 反思提示词模板
│   ├── langgraph/         # 错误分析提示词模板
│   └── execution/         # 执行阶段合成提示词模板
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

### 15.2 Agent 执行流程（含错误感知自我纠错）

```
用户任务
  ↓
[规划节点] 规划引擎：创建执行计划
  │  工具列表按 available_tools 白名单过滤后传给 LLM
  │  技能先经过 metadata 路由筛选（Top-K）再进入规划上下文
  │  若有 error_context，携带历史错误与纠正建议一起生成计划
  ↓
[执行节点] 执行引擎：按计划逐步执行
  │  工具步骤经 Tool Hub 执行
  │  技能步骤经 SkillManager 懒加载后调用 LLM 执行（并按技能声明过滤工具白名单）
  │  委派步骤经 SpawnAgentTool 注入上下文后执行
  │
  │  [步骤开始] 触发 on_step_start 回调
  │       ↓ 推送 tool_start / delegate_start / skill_start SSE 事件
  │       ↓ (确保前端进度条先于 send_message 输入框出现)
  │
  │  [步骤执行]
  │  ┌─ 步骤成功 → 收集结果，触发 on_step_complete 推送完成事件，继续下一步
  │  └─ 步骤失败 → 生成 error_record 追加到 error_context
  │             → 调用 _analyze_errors（LLM 根因分析）
  │             → 推送 error_analysis 事件到前端
  ↓
[反思节点] 反思引擎：携带 error_context 评估结果
  │  工具 Schema 同样按 available_tools 白名单过滤
  ├─ 成功 + needs_replanning=false → 返回结果
  └─ needs_replanning=true + 未超最大迭代 → 重新规划
                                     ↓
                             [规划节点]（携带 error_context）
                                     ↓
                        LLM 看到新方案，规避已知错误路径
  ↓
达到最大迭代（max_iterations=5） → 返回失败摘要
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
不需要委派 → 自己执行（工具/技能）
  ↓
需要委派 → 执行引擎经 SpawnAgentTool（Tool Hub）注入 stream_callback / 确认状态
  ↓
SpawnAgentTool 调用 ChildAgentManager.delegate_task → 子 Agent 执行任务
  ↓
子 Agent 结果回填（success/result/error），主 Agent 整合结果
```

---

## 16. 依赖配置

```toml
[tool.poetry.dependencies]
python = "^3.13"

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

> ✅ **已完成（v1.2）**：错误感知自我纠错机制 — 包括执行错误收集（`error_context`）、LLM 根因分析（`_analyze_errors` + `error_analysis`）、规划阶段工具 Schema 白名单过滤（防止 LLM 重复规划禁用工具）、以及前端 SSE 实时推送错误分析结果（`error_analysis_start` / `error_analysis` 事件）。

> ✅ **已完成（v1.3）**：用户确认流程（敏感工具执行前需用户确认，`/agents/confirm`、`user_rejected_tools`）；子 Agent 流式与确认透传（`sub_agent_start`/`sub_agent_end`、`is_sub_agent`、合成答案 `answer`）；跨迭代规划上下文（`planning_context`、`reflection_history`）；迭代防循环熔断（无可执行动作、重复反思时结束）。

> ✅ **已完成（v1.4）**：子 Agent 委派统一路径（`action: "delegate"` 与 `action: "tool", tool_name: "spawn_agent"` 均优先经 **SpawnAgentTool** 执行，并对其注入 `stream_callback`/`pending_confirmations`/`user_rejected_tools`）；执行引擎对支持 `update_context` 的工具做运行时上下文注入；子 Agent 执行结果统一使用 `ExecutionResult.to_dict()` 的 `success`（布尔）与 `error` 字段，`execute_with_callback` 据此返回，避免误报“Unknown error”；前端轨迹对事件重排序，使「工具/技能完成」在「委派子 Agent」之前展示，符合“先执行本层再委派”的阅读顺序。

> ✅ **已完成（v1.5）**：技能系统完成动态加载重构（`skills_md/*/SKILL.md` 文件系统发现、`SkillMetadata` 路由、执行阶段懒加载）；规划阶段仅注入候选技能元信息，执行阶段按 `required_tools/optional_tools` 进行工具白名单收敛并屏蔽敏感工具隐式调用；独立技能执行接口（`/api/v1/skills/{skill_id}/execute`）与主执行链路在工具过滤与缺失必需工具快速失败策略上保持一致。
