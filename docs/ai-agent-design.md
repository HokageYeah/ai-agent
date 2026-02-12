# 通用企业级 AI 平台架构设计

## 文档版本
- **版本号**: v1.0
- **最后更新**: 2026-02-11
- **架构类型**: LLM 完全解耦的通用 AI 能力平台

---

## 1. 设计目标与定位

### 1.1 系统定位

本系统旨在构建一个**通用 AI 能力平台**（Universal AI Capability Platform），提供：

- ✅ 统一的 LLM 推理能力
- ✅ 智能体（Agent）系统
- ✅ 普通对话服务
- ✅ 自动化任务服务
- ✅ 外部系统 API 调用
- ✅ 多模态能力支持

### 1.2 核心设计原则

```
LLM Hub          = AI 基础设施层（统一推理）
Capability Layer = AI 能力组合层（工具、记忆、技能）
Orchestration    = AI 流程控制层（工作流、任务编排）
Application      = AI 应用层（Agent、服务）
Channel Layer    = AI 接口层（多渠道接入）
```

### 1.3 关键设计理念

1. **完全解耦**: LLM 作为独立基础设施,所有上层应用通过统一接口调用
2. **能力复用**: 工具、记忆、技能可被多个应用共享
3. **灵活编排**: 支持 DAG、条件分支、并行执行等复杂流程
4. **多租户隔离**: 支持企业级多租户部署
5. **可观测性**: 全链路追踪、成本管理、质量监控

---

## 2. 平台总体架构

### 2.1 架构分层视图

```
┌─────────────────────────────────────────────────────────┐
│         Channel Layer（渠道层）                          │
│  Feishu | Web Chat | WhatsApp | REST API | SDK          │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│       Application Layer（AI 应用层）                     │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐        │
│  │  Agent   │  │   Chat   │  │  Automation    │        │
│  │  System  │  │  Service │  │   Service      │        │
│  └──────────┘  └──────────┘  └────────────────┘        │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│     Orchestration Layer（AI 编排层）                     │
│  ┌──────────────────┐  ┌─────────────────────┐         │
│  │ Workflow Engine  │  │  Task Orchestrator  │         │
│  │  (DAG/流程控制)   │  │   (任务调度拆分)     │         │
│  └──────────────────┘  └─────────────────────┘         │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│      Capability Layer（AI 能力层）                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Tool Hub │  │  Memory  │  │  Skill   │             │
│  │  (工具)   │  │  System  │  │  System  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│    ⭐ LLM Infrastructure Layer（LLM 基础设施层）⭐         │
│                                                          │
│              LLM Hub（通用推理平台）                      │
│  • 统一模型接入    • 智能路由      • 成本管理            │
│  • 流式输出管理    • 安全防护      • 可观测性            │
└──────────────────────────────────────────────────────────┘
```

### 2.2 数据流向

```
用户请求
  ↓
Channel Layer (接入)
  ↓
Application Layer (业务处理)
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

## 3. LLM 基础设施层设计（核心）

### 3.1 LLM Hub 定位

**LLM Hub 是全平台统一的 AI 推理基础设施**，所有需要 AI 能力的组件都通过 LLM Hub 调用。

#### 3.1.1 调用方包括

- Agent 系统（智能体）
- Chat Service（对话服务）
- Workflow Engine（工作流引擎）
- API Service（外部 API 服务）
- Automation Service（自动化服务）
- Analytics Service（数据分析服务）

### 3.2 LLM Hub 架构设计

```
LLM Hub
├─ Provider Adapter Layer      # 多模型供应商适配
├─ Model Registry              # 模型注册中心
├─ Model Router                # 智能路由选择
├─ Inference Engine            # 统一推理引擎
├─ Prompt Builder              # Prompt 构建器
├─ Tool Calling Gateway        # 工具调用网关
├─ Streaming Manager           # 流式输出管理
├─ Cost & Budget Manager       # 成本与预算管理
├─ Observability Layer         # 可观测性层
└─ Policy & Guardrail Layer    # 策略与护栏层
```

### 3.3 Provider Adapter Layer（供应商适配层）

#### 3.3.1 设计目标

统一接入不同 LLM 供应商,屏蔽底层差异。

#### 3.3.2 接口设计

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

#### 3.3.3 支持的供应商

| 供应商                     | 类型   | 优先级 |
| -------------------------- | ------ | ------ |
| OpenAI                     | 云服务 | P0     |
| Anthropic (Claude)         | 云服务 | P0     |
| Google (Gemini)            | 云服务 | P0     |
| Azure OpenAI               | 云服务 | P0     |
| AWS Bedrock                | 云服务 | P1     |
| 本地部署模型 (Ollama/vLLM) | 私有化 | P1     |
| 企业定制模型               | 私有化 | P2     |

### 3.4 Model Registry（模型注册中心）

#### 3.4.1 模型元数据

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
    max_output_tokens: int           # 最大输出 tokens
    cost_per_1k_input: float         # 输入成本(USD/1K tokens)
    cost_per_1k_output: float        # 输出成本(USD/1K tokens)
    avg_latency_ms: Optional[int]    # 平均延迟(毫秒)
    supported_features: list[str]    # 支持的功能
    is_available: bool               # 是否可用
    tags: dict[str, str]             # 自定义标签
```

#### 3.4.2 能力标签示例

```python
CAPABILITIES = [
    "text-generation",      # 文本生成
    "function-calling",     # 函数调用
    "vision",              # 视觉理解
    "streaming",           # 流式输出
    "json-mode",           # JSON 模式
    "code-execution",      # 代码执行
    "embeddings",          # 向量化
]
```

### 3.5 Model Router（智能路由）

#### 3.5.1 路由策略

```python
from enum import Enum

class RoutingStrategy(Enum):
    """路由策略"""
    COST_OPTIMIZED = "cost_optimized"          # 成本优先
    QUALITY_OPTIMIZED = "quality_optimized"    # 质量优先
    LATENCY_OPTIMIZED = "latency_optimized"    # 延迟优先
    BALANCED = "balanced"                      # 平衡模式
    MANUAL = "manual"                          # 手动指定
```

#### 3.5.2 路由决策因素

```python
class RoutingContext(BaseModel):
    """路由上下文"""
    task_type: str                      # 任务类型
    required_capabilities: list[str]    # 所需能力
    max_budget_usd: Optional[float]     # 预算上限
    target_quality_level: int           # 目标质量等级 (1-5)
    max_latency_ms: Optional[int]       # 延迟要求
    tenant_policy: dict                 # 租户策略
    user_preference: Optional[str]      # 用户偏好
```

#### 3.5.3 路由算法

```python
class ModelRouter:
    """模型路由器"""
    
    async def select_model(
        self,
        context: RoutingContext,
        strategy: RoutingStrategy
    ) -> str:
        """根据策略选择最优模型"""
        
        # 1. 过滤:满足能力要求的模型
        candidates = self._filter_by_capabilities(
            context.required_capabilities
        )
        
        # 2. 过滤:满足预算要求
        if context.max_budget_usd:
            candidates = self._filter_by_budget(
                candidates, context.max_budget_usd
            )
        
        # 3. 根据策略排序
        if strategy == RoutingStrategy.COST_OPTIMIZED:
            return self._select_cheapest(candidates)
        elif strategy == RoutingStrategy.QUALITY_OPTIMIZED:
            return self._select_best_quality(candidates)
        elif strategy == RoutingStrategy.LATENCY_OPTIMIZED:
            return self._select_fastest(candidates)
        else:  # BALANCED
            return self._select_balanced(candidates, context)
```

### 3.6 Inference Engine（推理引擎）

#### 3.6.1 统一推理流程

```python
class InferenceEngine:
    """统一推理引擎"""
    
    async def infer(
        self,
        messages: list[dict],
        config: InferenceConfig
    ) -> InferenceResult:
        """执行推理"""
        
        # 1. 请求预处理
        processed = await self._preprocess_request(messages, config)
        
        # 2. Prompt 构建
        prompt = await self.prompt_builder.build(processed)
        
        # 3. 模型选择
        model = await self.router.select_model(config.routing_context)
        
        # 4. 执行推理
        raw_result = await self.provider_adapter.chat(
            model=model,
            messages=prompt,
            config=config
        )
        
        # 5. 结果后处理
        result = await self._postprocess_result(raw_result)
        
        # 6. 记录和监控
        await self._log_and_monitor(request, result, config)
        
        return result
```

### 3.7 Prompt Builder（Prompt 构建器）

#### 3.7.1 Prompt 组装

```python
class PromptBuilder:
    """Prompt 构建器"""
    
    async def build(
        self,
        request: InferenceRequest
    ) -> list[dict]:
        """构建完整 Prompt"""
        
        messages = []
        
        # 1. System Prompt
        if request.system_prompt:
            messages.append({
                "role": "system",
                "content": request.system_prompt
            })
        
        # 2. Role Prompt (如果有特定角色设定)
        if request.role_definition:
            messages.append({
                "role": "system",
                "content": f"You are {request.role_definition}"
            })
        
        # 3. Memory Context (上下文记忆)
        if request.include_memory:
            memory_context = await self.memory.retrieve(
                request.conversation_id
            )
            messages.extend(memory_context)
        
        # 4. Tool Schema (如果需要工具调用)
        # 工具定义会根据不同供应商格式自动转换
        
        # 5. Few-shot Examples (如果有)
        if request.examples:
            messages.extend(request.examples)
        
        # 6. User Input
        messages.append({
            "role": "user",
            "content": request.user_input
        })
        
        return messages
```

### 3.8 Tool Calling Gateway（工具调用网关）

#### 3.8.1 设计目标

- 统一不同 LLM 的工具调用格式
- 连接 LLM 与 Tool Hub
- 处理工具调用的编排和执行

#### 3.8.2 工具调用流程

```python
class ToolCallingGateway:
    """工具调用网关"""
    
    async def execute_tool_call(
        self,
        llm_response: dict,
        available_tools: list[Tool]
    ) -> list[dict]:
        """执行 LLM 请求的工具调用"""
        
        results = []
        
        # 解析 LLM 的工具调用请求
        tool_calls = self._parse_tool_calls(llm_response)
        
        for call in tool_calls:
            # 查找对应工具
            tool = self._find_tool(call.name, available_tools)
            
            # 验证参数
            validated_params = self._validate_params(
                call.parameters, 
                tool.schema
            )
            
            # 执行工具
            result = await tool.execute(validated_params)
            
            results.append({
                "tool_call_id": call.id,
                "tool_name": call.name,
                "result": result
            })
        
        return results
```

### 3.9 Streaming Manager（流式输出管理）

#### 3.9.1 流式输出处理

```python
class StreamingManager:
    """流式输出管理器"""
    
    async def stream_response(
        self,
        model: str,
        messages: list[dict],
        config: dict
    ) -> AsyncIterator[StreamChunk]:
        """处理流式响应"""
        
        provider = self._get_provider(model)
        
        async for chunk in provider.stream(messages, config):
            # 1. 格式标准化
            standardized = self._standardize_chunk(chunk)
            
            # 2. Token 计数
            await self._count_tokens(standardized)
            
            # 3. 内容过滤(如果需要)
            if config.content_filter:
                standardized = await self._filter_content(standardized)
            
            yield standardized
```

### 3.10 Cost & Budget Manager（成本与预算管理）

#### 3.10.1 成本追踪

```python
class CostManager:
    """成本管理器"""
    
    async def track_usage(
        self,
        request_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        tenant_id: str,
        user_id: Optional[str] = None
    ):
        """追踪使用情况和成本"""
        
        model_info = await self.registry.get_model(model)
        
        # 计算成本
        input_cost = (input_tokens / 1000) * model_info.cost_per_1k_input
        output_cost = (output_tokens / 1000) * model_info.cost_per_1k_output
        total_cost = input_cost + output_cost
        
        # 记录到数据库
        await self.db.log_usage(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=total_cost,
            timestamp=datetime.utcnow()
        )
        
        # 检查预算
        await self._check_budget_limits(tenant_id, total_cost)
```

#### 3.10.2 预算控制

```python
class BudgetController:
    """预算控制器"""
    
    async def check_budget(
        self,
        tenant_id: str,
        estimated_cost: float
    ) -> bool:
        """检查是否超出预算"""
        
        budget = await self.get_tenant_budget(tenant_id)
        current_usage = await self.get_current_month_usage(tenant_id)
        
        if current_usage + estimated_cost > budget.monthly_limit:
            # 触发预算告警
            await self._trigger_budget_alert(tenant_id, current_usage)
            return False
        
        return True
```

### 3.11 Observability Layer（可观测性层）

#### 3.11.1 监控指标

```python
class ObservabilityMetrics:
    """可观测性指标"""
    
    # 性能指标
    latency_p50: float          # 50分位延迟
    latency_p95: float          # 95分位延迟
    latency_p99: float          # 99分位延迟
    throughput_rps: float       # 吞吐量(请求/秒)
    
    # 质量指标
    success_rate: float         # 成功率
    error_rate: float           # 错误率
    timeout_rate: float         # 超时率
    
    # 成本指标
    total_cost_usd: float       # 总成本
    cost_per_request: float     # 平均每请求成本
    
    # Token 指标
    total_tokens: int           # 总 tokens
    avg_input_tokens: float     # 平均输入 tokens
    avg_output_tokens: float    # 平均输出 tokens
```

#### 3.11.2 链路追踪

```python
class TraceManager:
    """链路追踪管理器"""
    
    async def trace_request(
        self,
        request_id: str,
        trace_context: dict
    ):
        """追踪请求链路"""
        
        # 使用 OpenTelemetry 或类似工具
        with self.tracer.start_span("llm_inference") as span:
            span.set_attribute("request_id", request_id)
            span.set_attribute("model", trace_context["model"])
            span.set_attribute("tenant_id", trace_context["tenant_id"])
            
            # 记录每个阶段
            # ... 推理执行 ...
```

### 3.12 Policy & Guardrail Layer（策略与护栏层）

#### 3.12.1 安全防护

```python
class GuardrailLayer:
    """安全护栏层"""
    
    async def validate_input(
        self,
        user_input: str,
        config: GuardrailConfig
    ) -> ValidationResult:
        """验证输入安全性"""
        
        checks = []
        
        # 1. PII 检测
        if config.check_pii:
            pii_result = await self.pii_detector.detect(user_input)
            checks.append(pii_result)
        
        # 2. 有害内容检测
        if config.check_harmful_content:
            harmful_result = await self.content_filter.check(user_input)
            checks.append(harmful_result)
        
        # 3. Prompt 注入检测
        if config.check_prompt_injection:
            injection_result = await self.injection_detector.check(user_input)
            checks.append(injection_result)
        
        # 4. 自定义策略检查
        for policy in config.custom_policies:
            policy_result = await policy.check(user_input)
            checks.append(policy_result)
        
        return ValidationResult(checks=checks)
    
    async def validate_output(
        self,
        llm_output: str,
        config: GuardrailConfig
    ) -> ValidationResult:
        """验证输出安全性"""
        # 类似的输出检查逻辑
        pass
```

---

## 4. AI 能力层设计

### 4.1 Tool Hub（工具中心）

#### 4.1.1 工具抽象

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
    
    async def validate_params(self, params: dict) -> bool:
        """验证参数"""
        # 使用 JSON Schema 验证
        pass
```

#### 4.1.2 内置工具类型

```python
# 数据检索工具
class SearchTool(Tool):
    """搜索工具"""
    pass

class DatabaseQueryTool(Tool):
    """数据库查询工具"""
    pass

# API 调用工具
class HTTPRequestTool(Tool):
    """HTTP 请求工具"""
    pass

class APIIntegrationTool(Tool):
    """第三方 API 集成"""
    pass

# 代码执行工具
class PythonExecutorTool(Tool):
    """Python 代码执行"""
    pass

class SQLExecutorTool(Tool):
    """SQL 执行"""
    pass

# 文件操作工具
class FileReadTool(Tool):
    """文件读取"""
    pass

class FileWriteTool(Tool):
    """文件写入"""
    pass
```

#### 4.1.3 Tool Hub 管理器

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
    
    def list_tools(
        self,
        category: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> list[Tool]:
        """列出可用工具"""
        tools = list(self._tools.values())
        
        # 根据类别过滤
        if category:
            tools = [t for t in tools if t.category == category]
        
        # 根据租户权限过滤
        if tenant_id:
            tools = [t for t in tools if self._has_permission(tenant_id, t)]
        
        return tools
    
    def get_schemas(self, tools: list[Tool]) -> list[dict]:
        """获取工具的 Schema 列表(用于 LLM)"""
        return [tool.schema.dict() for tool in tools]
```

### 4.2 Memory System（记忆系统）

#### 4.2.1 记忆类型

```python
from enum import Enum

class MemoryType(Enum):
    """记忆类型"""
    SHORT_TERM = "short_term"      # 短期记忆(会话级)
    LONG_TERM = "long_term"        # 长期记忆(持久化)
    WORKING = "working"            # 工作记忆(任务级)
    EPISODIC = "episodic"          # 情景记忆(事件级)
    SEMANTIC = "semantic"          # 语义记忆(知识级)
```

#### 4.2.2 短期记忆（会话记忆）

```python
class ShortTermMemory:
    """短期记忆(会话上下文)"""
    
    def __init__(self, max_messages: int = 10):
        self.max_messages = max_messages
        self.messages: list[dict] = []
    
    def add_message(self, message: dict):
        """添加消息"""
        self.messages.append(message)
        
        # 保持窗口大小
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
    
    def get_context(self) -> list[dict]:
        """获取上下文"""
        return self.messages.copy()
    
    def clear(self):
        """清空记忆"""
        self.messages = []
```

#### 4.2.3 长期记忆（向量数据库）

```python
class LongTermMemory:
    """长期记忆(向量数据库)"""
    
    def __init__(self, vector_db: VectorDB):
        self.vector_db = vector_db
    
    async def store(
        self,
        content: str,
        metadata: dict,
        namespace: str
    ):
        """存储记忆"""
        
        # 1. 向量化
        embedding = await self.llm_hub.embeddings([content])
        
        # 2. 存储到向量数据库
        await self.vector_db.upsert(
            vectors=[embedding[0]],
            metadata=[metadata],
            namespace=namespace
        )
    
    async def retrieve(
        self,
        query: str,
        namespace: str,
        top_k: int = 5
    ) -> list[dict]:
        """检索相关记忆"""
        
        # 1. 查询向量化
        query_embedding = await self.llm_hub.embeddings([query])
        
        # 2. 向量检索
        results = await self.vector_db.query(
            vector=query_embedding[0],
            namespace=namespace,
            top_k=top_k
        )
        
        return results
```

#### 4.2.4 记忆管理器

```python
class MemoryManager:
    """统一记忆管理器"""
    
    def __init__(self):
        self.short_term = {}  # conversation_id -> ShortTermMemory
        self.long_term = LongTermMemory(vector_db)
    
    async def get_context(
        self,
        conversation_id: str,
        include_long_term: bool = False,
        long_term_query: Optional[str] = None
    ) -> list[dict]:
        """获取完整上下文"""
        
        context = []
        
        # 1. 短期记忆
        if conversation_id in self.short_term:
            context.extend(
                self.short_term[conversation_id].get_context()
            )
        
        # 2. 长期记忆(可选)
        if include_long_term and long_term_query:
            long_term_memories = await self.long_term.retrieve(
                query=long_term_query,
                namespace=f"conversation:{conversation_id}"
            )
            # 将检索到的记忆转换为消息格式
            context.extend(
                self._format_long_term_memories(long_term_memories)
            )
        
        return context
```

### 4.3 Skill System（技能系统）

#### 4.3.1 技能定义

```python
class Skill(BaseModel):
    """技能定义"""
    skill_id: str
    name: str
    description: str
    prompt_template: str              # Prompt 模板
    required_tools: list[str]         # 所需工具
    optional_tools: list[str]         # 可选工具
    memory_strategy: MemoryStrategy   # 记忆策略
    model_preference: ModelPreference # 模型偏好
    examples: list[dict]              # Few-shot 示例
    tags: list[str]                   # 标签
```

#### 4.3.2 示例技能

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
    required_tools=["python_executor", "visualization"],
    optional_tools=["database_query"],
    memory_strategy=MemoryStrategy(
        include_short_term=True,
        include_long_term=False
    ),
    model_preference=ModelPreference(
        preferred_models=["gpt-4", "claude-3-opus"],
        routing_strategy=RoutingStrategy.QUALITY_OPTIMIZED
    )
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
    model_preference=ModelPreference(
        preferred_models=["gpt-4", "claude-3-sonnet"],
        routing_strategy=RoutingStrategy.BALANCED
    )
)
```

#### 4.3.3 Skill Manager

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
            self.tool_hub.get_tool(name) 
            for name in skill.required_tools
        ]
        
        # 3. 选择模型
        model = await self.model_router.select_model(
            context=context,
            strategy=skill.model_preference.routing_strategy
        )
        
        # 4. 执行推理
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            model=model,
            config=context
        )
        
        return result
```

---

## 5. AI 编排层设计

### 5.1 Workflow Engine（工作流引擎）

#### 5.1.1 支持的执行模式

```python
from enum import Enum

class ExecutionMode(Enum):
    """执行模式"""
    SEQUENTIAL = "sequential"      # 顺序执行
    PARALLEL = "parallel"          # 并行执行
    CONDITIONAL = "conditional"    # 条件执行
    DAG = "dag"                    # DAG 执行
    LOOP = "loop"                  # 循环执行
    MAP_REDUCE = "map_reduce"      # Map-Reduce
```

#### 5.1.2 Workflow 定义

```python
class WorkflowNode(BaseModel):
    """工作流节点"""
    node_id: str
    node_type: str  # "llm_call", "tool_call", "skill_call", "condition", "fork", "join"
    config: dict
    inputs: list[str]   # 输入来源(其他节点ID)
    outputs: list[str]  # 输出目标(其他节点ID)

class Workflow(BaseModel):
    """工作流定义"""
    workflow_id: str
    name: str
    description: str
    nodes: list[WorkflowNode]
    edges: list[tuple[str, str]]  # (from_node_id, to_node_id)
    entry_node: str
    exit_nodes: list[str]
```

#### 5.1.3 Workflow Engine 实现

```python
class WorkflowEngine:
    """工作流引擎"""
    
    async def execute(
        self,
        workflow: Workflow,
        initial_input: dict
    ) -> dict:
        """执行工作流"""
        
        # 构建执行图
        graph = self._build_execution_graph(workflow)
        
        # 拓扑排序获取执行顺序
        execution_order = self._topological_sort(graph)
        
        # 存储节点执行结果
        node_results = {}
        
        # 按顺序执行节点
        for node_id in execution_order:
            node = workflow.get_node(node_id)
            
            # 收集输入
            node_input = self._collect_node_input(
                node, node_results, initial_input
            )
            
            # 执行节点
            result = await self._execute_node(node, node_input)
            
            # 保存结果
            node_results[node_id] = result
        
        # 返回最终输出
        return self._collect_final_output(
            workflow.exit_nodes, node_results
        )
    
    async def _execute_node(
        self,
        node: WorkflowNode,
        input_data: dict
    ) -> dict:
        """执行单个节点"""
        
        if node.node_type == "llm_call":
            return await self._execute_llm_node(node, input_data)
        elif node.node_type == "tool_call":
            return await self._execute_tool_node(node, input_data)
        elif node.node_type == "skill_call":
            return await self._execute_skill_node(node, input_data)
        elif node.node_type == "condition":
            return await self._execute_condition_node(node, input_data)
        else:
            raise ValueError(f"Unknown node type: {node.node_type}")
```

#### 5.1.4 条件分支示例

```python
# Workflow 示例:根据用户意图路由到不同技能
INTENT_ROUTING_WORKFLOW = Workflow(
    workflow_id="intent_routing",
    name="意图路由",
    nodes=[
        WorkflowNode(
            node_id="intent_classification",
            node_type="llm_call",
            config={
                "prompt": "分析用户意图,返回: data_analysis, code_generation, 或 general_chat",
                "model": "gpt-3.5-turbo"
            }
        ),
        WorkflowNode(
            node_id="route_decision",
            node_type="condition",
            config={
                "conditions": [
                    {"if": "intent == 'data_analysis'", "goto": "data_skill"},
                    {"if": "intent == 'code_generation'", "goto": "code_skill"},
                    {"else": "chat_skill"}
                ]
            }
        ),
        WorkflowNode(
            node_id="data_skill",
            node_type="skill_call",
            config={"skill_id": "data_analysis"}
        ),
        WorkflowNode(
            node_id="code_skill",
            node_type="skill_call",
            config={"skill_id": "code_generation"}
        ),
        WorkflowNode(
            node_id="chat_skill",
            node_type="skill_call",
            config={"skill_id": "general_chat"}
        )
    ]
)
```

### 5.2 Task Orchestrator（任务编排器）

#### 5.2.1 任务调度

```python
class TaskOrchestrator:
    """任务编排器"""
    
    async def schedule_task(
        self,
        task: Task,
        priority: int = 0
    ):
        """调度任务"""
        
        # 1. 任务入队
        await self.task_queue.enqueue(
            task, priority=priority
        )
        
        # 2. 分配执行器
        executor = await self._allocate_executor(task)
        
        # 3. 执行任务
        result = await executor.execute(task)
        
        return result
    
    async def _allocate_executor(self, task: Task):
        """分配执行器"""
        
        # 根据任务类型选择执行器
        if task.task_type == "agent":
            return self.agent_executor
        elif task.task_type == "workflow":
            return self.workflow_executor
        else:
            return self.default_executor
```

#### 5.2.2 任务拆分

```python
class TaskDecomposer:
    """任务拆分器"""
    
    async def decompose(
        self,
        complex_task: Task
    ) -> list[Task]:
        """将复杂任务拆分为子任务"""
        
        # 使用 LLM 进行任务拆分
        decomposition_prompt = f"""
将以下复杂任务拆分为可执行的子任务:

任务: {complex_task.description}

要求:
1. 子任务之间有明确的依赖关系
2. 每个子任务都是原子性的
3. 以 JSON 格式返回子任务列表
"""
        
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": decomposition_prompt}],
            config={"json_mode": True}
        )
        
        subtasks = self._parse_subtasks(result)
        
        return subtasks
```

---

## 6. Agent 系统设计（应用层）

### 6.1 Agent 定位

**Agent 是调用 AI 能力层完成复杂任务的执行单元**

Agent 不直接依赖特定 LLM,而是通过 LLM Hub 调用推理能力。

### 6.2 Agent 核心架构

```python
class Agent(BaseModel):
    """智能体"""
    agent_id: str
    name: str
    description: str
    role: str                          # 角色定义
    capabilities: list[str]            # 能力列表
    available_tools: list[str]         # 可用工具
    available_skills: list[str]        # 可用技能
    memory_config: MemoryConfig        # 记忆配置
    model_config: ModelConfig          # 模型配置
    child_agents: list[str]            # 子 Agent
```

### 6.3 Agent 组件

```
Agent
├─ Runtime                 # 运行时环境
├─ Planning Engine         # 规划引擎
├─ Execution Engine        # 执行引擎
├─ Reflection Engine       # 反思引擎
├─ Skill Manager          # 技能管理器
├─ Tool Access            # 工具访问接口
├─ Memory Access          # 记忆访问接口
├─ LLM Hub Client         # LLM Hub 客户端
└─ Child Agent Manager    # 子 Agent 管理器
```

### 6.4 Agent 执行流程

```python
class AgentExecutor:
    """Agent 执行器"""
    
    async def execute(
        self,
        agent: Agent,
        task: str
    ) -> AgentResult:
        """执行 Agent 任务"""
        
        # 1. Planning(规划)
        plan = await self.planning_engine.create_plan(
            agent=agent,
            task=task
        )
        
        # 2. Execution(执行)
        execution_result = await self.execution_engine.execute_plan(
            agent=agent,
            plan=plan
        )
        
        # 3. Reflection(反思)
        reflection = await self.reflection_engine.reflect(
            agent=agent,
            task=task,
            result=execution_result
        )
        
        # 4. 决定是否需要重新规划
        if reflection.needs_replanning:
            return await self.execute(agent, task)
        
        return AgentResult(
            success=True,
            result=execution_result,
            reflection=reflection
        )
```

### 6.5 Planning Engine（规划引擎）

```python
class PlanningEngine:
    """规划引擎"""
    
    async def create_plan(
        self,
        agent: Agent,
        task: str
    ) -> ExecutionPlan:
        """创建执行计划"""
        
        planning_prompt = f"""
你是 {agent.name}, {agent.description}

任务: {task}

可用工具: {agent.available_tools}
可用技能: {agent.available_skills}

请制定详细的执行计划,以 JSON 格式返回:
{{
  "steps": [
    {{"action": "use_tool", "tool": "...", "params": {{...}}}},
    {{"action": "use_skill", "skill": "...", "params": {{...}}}},
    {{"action": "delegate", "sub_agent": "...", "task": "..."}}
  ]
}}
"""
        
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": planning_prompt}],
            config={
                "model": agent.model_config.planning_model,
                "json_mode": True
            }
        )
        
        return ExecutionPlan.parse_obj(result)
```

### 6.6 Execution Engine（执行引擎）

```python
class ExecutionEngine:
    """执行引擎"""
    
    async def execute_plan(
        self,
        agent: Agent,
        plan: ExecutionPlan
    ) -> dict:
        """执行计划"""
        
        results = []
        
        for step in plan.steps:
            if step.action == "use_tool":
                result = await self._execute_tool(
                    tool_name=step.tool,
                    params=step.params
                )
            elif step.action == "use_skill":
                result = await self._execute_skill(
                    skill_id=step.skill,
                    params=step.params
                )
            elif step.action == "delegate":
                result = await self._delegate_to_subagent(
                    agent_id=step.sub_agent,
                    task=step.task
                )
            elif step.action == "llm_call":
                result = await self._llm_call(
                    prompt=step.prompt,
                    config=step.config
                )
            
            results.append(result)
            
            # 检查是否需要提前终止
            if self._should_terminate(results):
                break
        
        return self._aggregate_results(results)
```

### 6.7 Reflection Engine（反思引擎）

```python
class ReflectionEngine:
    """反思引擎"""
    
    async def reflect(
        self,
        agent: Agent,
        task: str,
        result: dict
    ) -> Reflection:
        """对执行结果进行反思"""
        
        reflection_prompt = f"""
任务: {task}
执行结果: {result}

请评估:
1. 任务是否完成?
2. 结果质量如何?
3. 是否需要改进?
4. 下一步应该做什么?

以 JSON 格式返回评估结果。
"""
        
        reflection_result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": reflection_prompt}],
            config={
                "model": agent.model_config.reflection_model,
                "json_mode": True
            }
        )
        
        return Reflection.parse_obj(reflection_result)
```

### 6.8 主子 Agent 架构

```python
class MasterAgent(Agent):
    """主 Agent"""
    
    async def execute_with_delegation(
        self,
        task: str
    ) -> dict:
        """通过委派子 Agent 执行任务"""
        
        # 1. 分析任务,决定是否需要委派
        delegation_plan = await self._create_delegation_plan(task)
        
        # 2. 如果不需要委派,自己执行
        if not delegation_plan.needs_delegation:
            return await self.execute(task)
        
        # 3. 委派给子 Agent
        sub_results = []
        for subtask in delegation_plan.subtasks:
            sub_agent = self.get_child_agent(subtask.agent_id)
            result = await sub_agent.execute(subtask.task)
            sub_results.append(result)
        
        # 4. 整合子 Agent 的结果
        final_result = await self._integrate_results(
            task, sub_results
        )
        
        return final_result

class WorkerAgent(Agent):
    """工作 Agent(专业领域)"""
    
    def __init__(self, specialization: str):
        self.specialization = specialization
        # 配置特定领域的工具和技能
```

#### 6.8.1 示例:客服 Agent 系统

```python
# 主客服 Agent
CUSTOMER_SERVICE_MASTER = MasterAgent(
    agent_id="cs_master",
    name="客服总监",
    description="负责客户服务的总协调",
    child_agents=[
        "order_agent",      # 订单处理 Agent
        "refund_agent",     # 退款处理 Agent
        "technical_agent"   # 技术支持 Agent
    ]
)

# 订单处理 Worker Agent
ORDER_AGENT = WorkerAgent(
    agent_id="order_agent",
    name="订单专员",
    specialization="order_processing",
    available_tools=["order_query", "order_update", "inventory_check"],
    available_skills=["order_analysis"]
)

# 退款处理 Worker Agent
REFUND_AGENT = WorkerAgent(
    agent_id="refund_agent",
    name="退款专员",
    specialization="refund_processing",
    available_tools=["refund_check", "refund_process", "payment_gateway"],
    available_skills=["refund_policy_check"]
)
```

---

## 7. 非 Agent AI 服务

LLM Hub 也支持独立的 AI 服务(不需要完整 Agent 能力)

### 7.1 Chat Service（对话服务）

```python
class ChatService:
    """对话服务"""
    
    async def chat(
        self,
        messages: list[dict],
        config: ChatConfig
    ) -> ChatResponse:
        """处理对话"""
        
        # 1. 获取会话上下文
        context = await self.memory.get_context(
            config.conversation_id
        )
        
        # 2. 组合消息
        full_messages = context + messages
        
        # 3. 调用 LLM Hub
        response = await self.llm_hub.infer(
            messages=full_messages,
            config=config
        )
        
        # 4. 更新记忆
        await self.memory.add_message(
            config.conversation_id,
            messages[-1]
        )
        await self.memory.add_message(
            config.conversation_id,
            {"role": "assistant", "content": response.content}
        )
        
        return response
```

### 7.2 AI API Service（AI API 服务）

```python
class AIAPIService:
    """AI API 服务(为外部系统提供 AI 能力)"""
    
    async def text_generation(
        self,
        prompt: str,
        max_tokens: int = 1000
    ) -> str:
        """文本生成"""
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": prompt}],
            config={"max_tokens": max_tokens}
        )
        return result.content
    
    async def summarization(
        self,
        text: str,
        max_length: int = 200
    ) -> str:
        """文本摘要"""
        prompt = f"请将以下文本总结为不超过 {max_length} 字的摘要:\n\n{text}"
        return await self.text_generation(prompt, max_length)
    
    async def translation(
        self,
        text: str,
        target_language: str
    ) -> str:
        """翻译"""
        prompt = f"请将以下文本翻译成{target_language}:\n\n{text}"
        return await self.text_generation(prompt)
    
    async def classification(
        self,
        text: str,
        categories: list[str]
    ) -> str:
        """分类"""
        prompt = f"请将以下文本分类到这些类别之一: {', '.join(categories)}\n\n文本: {text}"
        result = await self.text_generation(prompt, max_tokens=50)
        return result.strip()
    
    async def sentiment_analysis(
        self,
        text: str
    ) -> dict:
        """情感分析"""
        prompt = f"分析以下文本的情感(积极/中性/消极),并给出置信度:\n\n{text}"
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": prompt}],
            config={"json_mode": True}
        )
        return result
```

### 7.3 Automation Service（自动化服务）

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
        # 使用代码生成技能
        pass
```

---

## 8. 渠道系统（Channel Layer）

### 8.1 多渠道接入

```python
class ChannelAdapter(ABC):
    """渠道适配器"""
    
    @abstractmethod
    async def receive_message(self) -> Message:
        """接收消息"""
        pass
    
    @abstractmethod
    async def send_message(self, message: Message):
        """发送消息"""
        pass

# 飞书
class FeishuAdapter(ChannelAdapter):
    pass

# Web Chat
class WebChatAdapter(ChannelAdapter):
    pass

# WhatsApp
class WhatsAppAdapter(ChannelAdapter):
    pass

# REST API
class RESTAPIAdapter(ChannelAdapter):
    pass
```

### 8.2 Channel Manager

```python
class ChannelManager:
    """渠道管理器"""
    
    def __init__(self):
        self.adapters: Dict[str, ChannelAdapter] = {}
    
    def register_channel(
        self,
        channel_id: str,
        adapter: ChannelAdapter
    ):
        """注册渠道"""
        self.adapters[channel_id] = adapter
    
    async def route_message(
        self,
        channel_id: str,
        message: Message
    ):
        """路由消息到对应的 AI 服务"""
        
        # 1. 识别意图
        intent = await self._classify_intent(message)
        
        # 2. 路由到对应服务
        if intent == "agent_task":
            result = await self.agent_service.execute(message)
        elif intent == "chat":
            result = await self.chat_service.chat(message)
        elif intent == "automation":
            result = await self.automation_service.process(message)
        
        # 3. 返回结果
        adapter = self.adapters[channel_id]
        await adapter.send_message(result)
```

---

## 9. 多租户设计

### 9.1 租户隔离

```python
class Tenant(BaseModel):
    """租户"""
    tenant_id: str
    name: str
    tier: str  # "free", "pro", "enterprise"
    
    # 配置
    model_config: TenantModelConfig
    agent_config: TenantAgentConfig
    tool_config: TenantToolConfig
    workflow_config: TenantWorkflowConfig
    policy_config: TenantPolicyConfig
    
    # 限额
    quota: TenantQuota
    
    # 自定义
    custom_models: list[str]
    custom_tools: list[str]
    custom_skills: list[str]
```

### 9.2 租户级配置

```python
class TenantModelConfig(BaseModel):
    """租户模型配置"""
    allowed_providers: list[str]
    allowed_models: list[str]
    default_routing_strategy: RoutingStrategy
    monthly_budget_usd: float
    rate_limit_rpm: int  # 每分钟请求数

class TenantQuota(BaseModel):
    """租户配额"""
    max_agents: int
    max_workflows: int
    max_tools: int
    max_api_calls_per_month: int
    max_storage_gb: int
```

### 9.3 租户上下文

```python
class TenantContext:
    """租户上下文"""
    
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.tenant = self._load_tenant(tenant_id)
    
    def get_allowed_models(self) -> list[str]:
        """获取允许使用的模型"""
        return self.tenant.model_config.allowed_models
    
    def check_quota(self, resource_type: str) -> bool:
        """检查配额"""
        current_usage = self._get_current_usage(resource_type)
        quota_limit = getattr(self.tenant.quota, f"max_{resource_type}")
        return current_usage < quota_limit
    
    async def log_usage(
        self,
        resource_type: str,
        amount: int = 1
    ):
        """记录资源使用"""
        await self.db.increment_usage(
            tenant_id=self.tenant_id,
            resource_type=resource_type,
            amount=amount
        )
```

---

## 10. 完整请求生命周期

```
1. 用户请求
   ↓
2. Channel Layer (接收)
   - 消息解析
   - 认证鉴权
   ↓
3. Application Layer (路由)
   - 意图识别
   - 选择服务(Agent/Chat/API)
   ↓
4. Orchestration Layer (编排)
   - 任务分解
   - 工作流编排
   ↓
5. Capability Layer (能力调用)
   - 工具调用
   - 记忆检索
   - 技能应用
   ↓
6. LLM Hub (统一推理)
   - 模型选择
   - Prompt 构建
   - 推理执行
   - 成本追踪
   ↓
7. 结果处理
   - 后处理
   - 格式化
   ↓
8. 响应返回
   - 通过 Channel 返回
```

---

## 11. 技术栈建议

### 11.1 核心框架

| 组件       | 技术选型               | 说明             |
| ---------- | ---------------------- | ---------------- |
| Web 框架   | FastAPI                | 高性能异步框架   |
| LLM 抽象层 | LiteLLM                | 统一多供应商接口 |
| Agent 框架 | LangGraph              | DAG 执行引擎     |
| 数据验证   | Pydantic               | 类型安全         |
| ORM        | SQLAlchemy             | 数据库访问       |
| 缓存       | Redis                  | 会话缓存、队列   |
| 数据库     | PostgreSQL             | 主数据库         |
| 向量数据库 | Pinecone/Qdrant        | 长期记忆         |
| 任务队列   | Celery/Redis           | 异步任务         |
| 监控       | Prometheus + Grafana   | 指标监控         |
| 链路追踪   | OpenTelemetry          | 分布式追踪       |
| 日志       | Elasticsearch + Kibana | 日志分析         |

### 11.2 开发工具

```python
# requirements.txt
fastapi>=0.100.0
uvicorn>=0.23.0
pydantic>=2.0.0
sqlalchemy>=2.0.0
redis>=4.6.0
psycopg2-binary>=2.9.0
celery>=5.3.0
litellm>=1.0.0
langgraph>=0.1.0
opentelemetry-api>=1.20.0
opentelemetry-sdk>=1.20.0
prometheus-client>=0.17.0
python-multipart>=0.0.6
httpx>=0.24.0
tiktoken>=0.5.0  # Token 计数
```

---

## 12. 推荐目录结构

> **设计原则**：将 AI Agent 架构整合到现有的 `app/` 目录下，与现有工程结构保持一致。

```
app/
├── api/                      # API 路由层（扩展）
│   ├── api.py               # API 路由集合
│   └── endpoints/           # API 端点
│       ├── agents.py        # Agent 管理接口
│       ├── chat.py          # 对话服务接口
│       ├── workflows.py     # 工作流接口
│       ├── tools.py         # 工具管理接口
│       └── admin.py         # 管理接口
│
├── llm_hub/                  # LLM 基础设施层（新增）
│   ├── __init__.py
│   ├── providers/           # 供应商适配器
│   │   ├── __init__.py
│   │   ├── base.py         # 供应商抽象基类
│   │   ├── openai.py       # OpenAI 适配器
│   │   ├── anthropic.py    # Claude 适配器
│   │   ├── google.py       # Gemini 适配器
│   │   └── local.py        # 本地模型适配器（Ollama/vLLM）
│   ├── registry.py          # 模型注册中心
│   ├── router.py            # 模型路由器
│   ├── inference.py         # 推理引擎
│   ├── prompt_builder.py    # Prompt 构建器
│   ├── tool_gateway.py      # 工具调用网关
│   ├── streaming.py         # 流式输出管理
│   ├── cost_manager.py      # 成本管理
│   ├── observability.py     # 可观测性
│   └── guardrails.py        # 安全护栏
│
├── agents/                   # Agent 系统（新增）
│   ├── __init__.py
│   ├── base.py              # Agent 基类
│   ├── executor.py          # Agent 执行器
│   ├── planning.py          # 规划引擎
│   ├── execution.py         # 执行引擎
│   ├── reflection.py        # 反思引擎
│   └── library/             # Agent 库
│       ├── __init__.py
│       ├── customer_service.py  # 客服 Agent
│       ├── data_analyst.py      # 数据分析 Agent
│       └── code_assistant.py    # 代码助手 Agent
│
├── tools/                   # 工具层（新增）
│   ├── __init__.py
│   ├── base.py             # 工具基类
│   ├── hub.py              # 工具中心
│   ├── builtin/             # 内置工具
│   │   ├── __init__.py
│   │   ├── search.py       # 搜索工具
│   │   ├── database.py     # 数据库查询工具
│   │   ├── http.py         # HTTP 请求工具
│   │   ├── executor.py     # 代码执行工具
│   │   ├── file.py         # 文件操作工具
│   │   └── calculator.py    # 计算工具
│   └── custom/             # 自定义工具
│       └── __init__.py
│
├── memory/                  # 记忆系统（新增）
│   ├── __init__.py
│   ├── short_term.py       # 短期记忆（会话上下文）
│   ├── long_term.py        # 长期记忆（向量存储）
│   ├── vector_store.py     # 向量存储接口
│   └── manager.py          # 记忆管理器
│
├── skills/                  # 技能系统（新增）
│   ├── __init__.py
│   ├── base.py             # 技能基类
│   ├── manager.py          # 技能管理器
│   └── library/            # 技能库
│       ├── __init__.py
│       ├── data_analysis.py    # 数据分析技能
│       ├── code_generation.py  # 代码生成技能
│       ├── text_writing.py     # 文本写作技能
│       └── translation.py     # 翻译技能
│
├── workflows/               # 工作流引擎（新增）
│   ├── __init__.py
│   ├── engine.py           # 工作流引擎
│   ├── nodes.py            # 节点定义
│   ├── templates/         # 工作流模板
│   │   ├── __init__.py
│   │   ├── intent_routing.py
│   │   └── data_pipeline.py
│   └── validator.py        # 工作流校验
│
├── orchestrator/            # 任务编排器（新增）
│   ├── __init__.py
│   ├── task_orchestrator.py
│   ├── task_decomposer.py
│   └── scheduler.py        # 任务调度器
│
├── channels/                # 渠道层（新增）
│   ├── __init__.py
│   ├── base.py            # 渠道基类
│   ├── manager.py         # 渠道管理器
│   └── adapters/          # 渠道适配器
│       ├── __init__.py
│       ├── feishu.py      # 飞书适配器
│       ├── web_chat.py    # Web Chat 适配器
│       ├── whatsapp.py    # WhatsApp 适配器
│       └── telegram.py    # Telegram 适配器
│
├── services/               # AI 服务（扩展现有 services/）
│   ├── __init__.py
│   ├── wx_public.py        # 现有：微信公众号服务
│   ├── chat_service.py     # 新增：对话服务
│   ├── api_service.py      # 新增：AI API 服务
│   └── automation_service.py # 新增：自动化服务
│
├── tenants/                 # 多租户系统（新增）
│   ├── __init__.py
│   ├── models.py           # 租户数据模型
│   ├── manager.py          # 租户管理器
│   └── context.py          # 租户上下文
│
├── core/                    # 核心模块（保持现有）
│   ├── __init__.py
│   ├── config.py           # 应用配置
│   └── logging.py          # 日志配置
│
├── db/                      # 数据库层（保持现有）
│   ├── __init__.py
│   └── sqlalchemy_db.py    # SQLAlchemy 配置
│
├── models/                  # 数据模型（保持现有，扩展）
│   ├── __init__.py
│   ├── article.py          # 现有：文章模型
│   ├── agent.py            # 新增：Agent 模型
│   ├── workflow.py         # 新增：工作流模型
│   ├── task.py             # 新增：任务模型
│   └── usage.py            # 新增：使用记录模型
│
├── schemas/                 # Pydantic 模型（保持现有，扩展）
│   ├── __init__.py
│   ├── wx_data.py          # 现有：微信公众号数据
│   ├── common_data.py      # 现有：通用数据
│   ├── agent.py            # 新增：Agent Schemas
│   ├── chat.py             # 新增：对话 Schemas
│   └── workflow.py         # 新增：工作流 Schemas
│
├── middleware/              # 中间件（保持现有）
│   ├── __init__.py
│   └── exception_handlers.py
│
├── decorators/              # 装饰器（保持现有）
│   ├── __init__.py
│   └── cache_decorator.py
│
├── scripts/                 # 脚本工具（保持现有）
│   ├── __init__.py
│   ├── create_database.py
│   ├── init_database.py
│   ├── manage_db.py
│   ├── set_env.py
│   └── migrate_llm_models.py  # 新增：LLM 模型迁移脚本
│
├── utils/                   # 工具函数（新增）
│   ├── __init__.py
│   ├── metrics.py          # 指标收集
│   ├── validators.py        # 验证工具
│   └── token_counter.py     # Token 计数
│
├── main.py                  # 应用入口（保持现有）
└── __init__.py             # 包初始化
│
alembic/                     # 数据库迁移（保持现有）
│
logs/                        # 日志目录（保持现有）
│
src/                         # 源代码根目录（用于 Poetry）
└── ai_agent/                # 主包
    └── __init__.py
│
.dockerignore               # Docker 忽略文件
.docker/
│   ├── Dockerfile
│   └── docker-compose.yml
│
.env.example                 # 环境变量示例
.env.development             # 开发环境配置
.env.test                    # 测试环境配置
.env.production              # 生产环境配置
│
pyproject.toml              # Poetry 项目配置
poetry.lock                  # Poetry 锁定文件
requirements.txt             # Python 依赖（可选，Poetry 替代）
│
run.sh                       # 启动脚本
run_app.py                   # 应用启动脚本
│
README.md                    # 项目文档
└── docs/                    # 文档目录
    └── ai-agent-design.md   # AI Agent 设计文档
```

### 目录结构说明

| 模块 | 说明 | 与现有结构的关系 |
|------|------|------------------|
| `api/endpoints/` | API 接口端点 | 扩展现有结构 |
| `llm_hub/` | LLM 基础设施层 | **新增** |
| `agents/` | Agent 系统 | **新增** |
| `tools/` | 工具层 | **新增** |
| `memory/` | 记忆系统 | **新增** |
| `skills/` | 技能系统 | **新增** |
| `workflows/` | 工作流引擎 | **新增** |
| `orchestrator/` | 任务编排器 | **新增** |
| `channels/` | 渠道层 | **新增** |
| `services/` | AI 服务 | **整合** 现有服务 |
| `tenants/` | 多租户系统 | **新增** |
| `models/` | 数据模型 | **扩展** 现有模型 |
| `schemas/` | Pydantic 模型 | **扩展** 现有 Schemas |
| `utils/` | 工具函数 | **新增** |

### 关键整合点

1. **API 整合**：`api/endpoints/` 目录扩展为包含 Agent、Chat、Workflows 等新端点，同时保持与现有 `wx_public.py` 服务的兼容性。

2. **服务整合**：在现有的 `services/` 目录中保留 `wx_public.py`（微信公众号爬虫服务），并添加新的 AI 服务。

3. **数据模型整合**：现有的 `models/article.py` 保持不变，新增 `agent.py`、`workflow.py` 等 AI 相关模型。

4. **配置整合**：使用现有的 `core/config.py` 加载 LLM 相关配置（API Key、模型设置等）。

5. **依赖注入整合**：使用 FastAPI 的依赖注入系统管理 LLM Hub、Agent 工厂等核心组件的生命周期。

---

## 13. 扩展能力设计

### 13.1 多模态支持

```python
class MultimodalLLMHub(LLMHub):
    """多模态 LLM Hub"""
    
    async def vision_inference(
        self,
        messages: list[dict],  # 包含图片的消息
        config: dict
    ) -> dict:
        """视觉推理"""
        pass
    
    async def audio_inference(
        self,
        audio_data: bytes,
        config: dict
    ) -> dict:
        """音频推理"""
        pass
    
    async def video_inference(
        self,
        video_data: bytes,
        config: dict
    ) -> dict:
        """视频推理"""
        pass
```

### 13.2 模型微调与优化

```python
class ModelOptimizer:
    """模型优化器"""
    
    async def fine_tune(
        self,
        base_model: str,
        training_data: list[dict],
        config: FineTuneConfig
    ) -> str:
        """微调模型"""
        pass
    
    async def evaluate(
        self,
        model: str,
        test_data: list[dict]
    ) -> EvaluationMetrics:
        """评估模型"""
        pass
```

### 13.3 Agent Marketplace

```python
class AgentMarketplace:
    """Agent 市场"""
    
    async def publish_agent(
        self,
        agent: Agent,
        metadata: AgentMetadata
    ):
        """发布 Agent"""
        pass
    
    async def discover_agents(
        self,
        query: str,
        filters: dict
    ) -> list[Agent]:
        """发现 Agent"""
        pass
    
    async def install_agent(
        self,
        agent_id: str,
        tenant_id: str
    ):
        """安装 Agent"""
        pass
```

### 13.4 自动化运维

```python
class AIDevOps:
    """AI 自动运维"""
    
    async def auto_scale(
        self,
        metrics: SystemMetrics
    ):
        """自动扩缩容"""
        pass
    
    async def detect_anomaly(
        self,
        metrics: SystemMetrics
    ) -> list[Anomaly]:
        """异常检测"""
        pass
    
    async def auto_optimize(
        self,
        performance_data: dict
    ):
        """自动优化"""
        pass
```

### 13.5 动态 Workflow 生成

```python
class WorkflowGenerator:
    """工作流生成器"""
    
    async def generate_from_description(
        self,
        description: str
    ) -> Workflow:
        """从描述生成工作流"""
        
        # 使用 LLM 理解描述并生成工作流定义
        prompt = f"""
根据以下描述生成工作流定义:

{description}

请以 JSON 格式返回工作流的节点和边。
"""
        
        result = await self.llm_hub.infer(
            messages=[{"role": "user", "content": prompt}],
            config={"json_mode": True}
        )
        
        return Workflow.parse_obj(result)
```

---

## 14. 设计优势总结

### 14.1 架构优势

✅ **完全解耦**: LLM 作为独立基础设施,上层应用不直接依赖特定模型  
✅ **能力复用**: 工具、记忆、技能可被多个应用共享  
✅ **灵活编排**: 支持复杂的工作流和任务编排  
✅ **多租户**: 原生支持企业级多租户部署  
✅ **可观测**: 全链路追踪、成本管理、质量监控  
✅ **可扩展**: 易于添加新模型、新工具、新服务  

### 14.2 成本优势

✅ **智能路由**: 根据任务选择最优性价比模型  
✅ **成本追踪**: 实时监控每个租户、用户、请求的成本  
✅ **预算控制**: 支持预算告警和限制  
✅ **缓存优化**: 减少重复推理  

### 14.3 性能优势

✅ **异步处理**: 全异步架构,高并发  
✅ **流式输出**: 更好的用户体验  
✅ **并行执行**: 工作流支持并行节点  
✅ **缓存策略**: Redis 缓存提升响应速度  

### 14.4 安全优势

✅ **内容过滤**: 输入输出双向安全检查  
✅ **Prompt 注入防护**: 检测和防御 Prompt 攻击  
✅ **租户隔离**: 数据和配置完全隔离  
✅ **审计日志**: 完整的操作审计  

---

## 15. 最终架构哲学

```
┌─────────────────────────────────────────┐
│  LLM Hub = AI 基础设施                   │
│  • 统一推理平台                          │
│  • 所有 AI 能力的底层支撑                 │
└─────────────────────────────────────────┘
                   ↑
┌─────────────────────────────────────────┐
│  Capability Layer = AI 能力组合层        │
│  • 工具、记忆、技能的组织和管理           │
│  • 为上层提供可组合的 AI 能力            │
└─────────────────────────────────────────┘
                   ↑
┌─────────────────────────────────────────┐
│  Orchestration = AI 流程控制层           │
│  • 工作流编排                            │
│  • 任务调度和拆分                        │
└─────────────────────────────────────────┘
                   ↑
┌─────────────────────────────────────────┐
│  Application = AI 应用层                 │
│  • Agent 系统                            │
│  • Chat 服务                             │
│  • Automation 服务                       │
└─────────────────────────────────────────┘
                   ↑
┌─────────────────────────────────────────┐
│  Channels = AI 入口层                    │
│  • 多渠道接入                            │
│  • 统一的用户界面                        │
└─────────────────────────────────────────┘
```

### 核心设计原则

1. **单一职责**: 每层专注自己的职责
2. **开放封闭**: 对扩展开放,对修改封闭
3. **依赖倒置**: 高层不依赖低层的具体实现
4. **接口隔离**: 清晰的接口定义
5. **组合优于继承**: 通过组合构建复杂能力

---

## 附录 A: 快速开始示例

### A.1 创建一个简单的 Chat Service

```python
from ai_platform import LLMHub, ChatService, MemoryManager

# 1. 初始化 LLM Hub
llm_hub = LLMHub()

# 2. 初始化记忆管理器
memory = MemoryManager()

# 3. 创建 Chat Service
chat_service = ChatService(
    llm_hub=llm_hub,
    memory=memory
)

# 4. 处理对话
response = await chat_service.chat(
    messages=[
        {"role": "user", "content": "你好"}
    ],
    config={
        "conversation_id": "user_123",
        "model": "gpt-4"
    }
)

print(response.content)
```

### A.2 创建一个简单的 Agent

```python
from ai_platform import Agent, AgentExecutor, ToolHub, SkillManager

# 1. 创建 Agent
data_analyst_agent = Agent(
    agent_id="data_analyst",
    name="数据分析师",
    description="专业的数据分析 Agent",
    available_tools=["python_executor", "database_query"],
    available_skills=["data_analysis"],
    model_config=ModelConfig(
        planning_model="gpt-4",
        execution_model="gpt-3.5-turbo"
    )
)

# 2. 执行任务
executor = AgentExecutor(
    llm_hub=llm_hub,
    tool_hub=tool_hub,
    skill_manager=skill_manager
)

result = await executor.execute(
    agent=data_analyst_agent,
    task="分析过去 30 天的销售数据,找出销售趋势"
)

print(result)
```

### A.3 创建一个 Workflow

```python
from ai_platform import Workflow, WorkflowEngine, WorkflowNode

# 1. 定义 Workflow
data_pipeline = Workflow(
    workflow_id="data_pipeline",
    name="数据处理流水线",
    nodes=[
        WorkflowNode(
            node_id="extract",
            node_type="tool_call",
            config={"tool": "database_query"}
        ),
        WorkflowNode(
            node_id="transform",
            node_type="skill_call",
            config={"skill": "data_transformation"}
        ),
        WorkflowNode(
            node_id="load",
            node_type="tool_call",
            config={"tool": "database_write"}
        )
    ],
    edges=[
        ("extract", "transform"),
        ("transform", "load")
    ],
    entry_node="extract",
    exit_nodes=["load"]
)

# 2. 执行 Workflow
engine = WorkflowEngine(llm_hub=llm_hub)
result = await engine.execute(
    workflow=data_pipeline,
    initial_input={"source": "sales_db"}
)

print(result)
```

---

## 结语

本架构设计提供了一个完整的、可扩展的、企业级的 AI 平台解决方案。通过 **LLM 完全解耦** 的设计,实现了:

- 🎯 **灵活性**: 轻松切换和组合不同的 LLM
- 🔧 **可维护性**: 清晰的分层和职责划分
- 📈 **可扩展性**: 易于添加新功能和服务
- 💰 **成本效益**: 智能路由和成本管理
- 🔒 **安全性**: 多层安全防护
- 👥 **多租户**: 原生支持企业级部署

此架构可以作为构建各类 AI 应用的基础平台。