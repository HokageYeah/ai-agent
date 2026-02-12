# AI Agent 实施任务分解文档

本文档基于 `docs/ai-agent-design.md` 设计文档，将系统实施拆分为十个主要阶段。**每个任务都包含明确的输入、输出、验收标准和依赖关系**，确保任务可执行、可测试、可追踪。

**核心改进：**
- 根据 `docs/task-bug.md` 问题分析新增 P0/P1/P2 模块
- 修正 Memory Manager 依赖方向
- 优化任务执行顺序
- 新增 Runtime Sandbox、EventBus、Cache Layer、LLM Mock Layer、Feature Flag System

---

## 📅 阶段零：平台基础能力

**目标**：建立 AI 平台的基础能力层，包括 Prompt 管理、Agent 注册、工具安全和租户管理。这些是后续所有功能的基础依赖。

**执行顺序（按依赖顺序）：**

```
Task 0.1 (LLM Mock Layer)  ← 新增：测试基础设施
    ↓
Task 0.2 (LLM Hub 核心)
    ↓
Task 0.3 (Memory Manager)  ← 修正：Memory 作为基础设施
    ↓
Task 0.4 (Tool Hub 基础)
    ↓
Task 0.5 (Prompt 管理系统)
    ↓
Task 0.6 (Agent Registry & Factory)
    ↓
Task 0.7 (Tenant 管理核心)
    ↓
Task 0.8 (Task 生命周期模型)
```

||- [ ] **Task 0.1: LLM Mock Layer**
    - **输入**: 测试需求、设计文档 LLM Hub 接口
    - **输出**: `app/core/llm_mock.py`, `app/core/llm_factory.py`
    - **需求**:
        1. 实现 `LLMInterface` 抽象接口：
           - `chat()` 方法
           - `stream()` 方法
           - `embeddings()` 方法
        2. 实现 `MockLLM` 类：
           - 基于配置的 Mock 响应
           - 延迟模拟（配置延迟时间）
           - 错误模拟（配置错误率）
        3. 实现 `LLMFactory` 类：
           - 根据配置创建 Mock 或真实 LLM
           - 支持多供应商切换
        4. 实现响应模板系统：
           - 基于消息内容的模式匹配
           - 变量替换支持
           - 随机响应选择
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_llm_mock.py` 通过
        - [ ] 验证 Mock 响应正确返回
        - [ ] 验证延迟模拟生效
        - [ ] 验证错误模拟生效
        - [ ] 验证工厂切换功能
    - **依赖**: 无
    - **工时估算**: 1.5 天

||- [ ] **Task 0.2: LLM Hub 核心抽象与供应商基类**
    - **输入**: 设计文档 3.2-3.3 节
    - **输出**: `app/llm_hub/providers/base.py`
    - **需求**:
        1. 定义 `LLMProvider` 抽象基类，包含 `chat()`, `stream()`, `embeddings()` 抽象方法
        2. 定义 `ModelMetadata` Pydantic 模型（包含 model_id, provider, capabilities, cost, context_window 等字段）
        3. 定义 `InferenceConfig` 配置模型
        4. 定义统一响应模型 `InferenceResult`
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_llm_provider_base.py` 通过
        - [ ] 能够实例化 MockProvider 并调用基类方法
        - [ ] 使用 Task 0.1 Mock Layer 进行测试
    - **依赖**: Task 0.1
    - **工时估算**: 1 天

||- [ ] **Task 0.3: Memory Manager 基础设施**
    - **输入**: 设计文档 4.2 节、task-bug.md 依赖修正要求
    - **输出**: `app/memory/manager.py`, `app/memory/base.py`
    - **需求**:
        1. 定义 `MemoryInterface` 抽象接口：
           - `store()` 存储记忆
           - `retrieve()` 检索记忆
           - `delete()` 删除记忆
        2. 实现 `MemoryAggregator`：
           - 整合短期记忆和长期记忆
           - 去重和冲突检测
           - 相关性评分排序
        3. 实现 `MemoryPrioritizer`：
           - 基于时间衰减的优先级
           - 基于访问频率的优先级
           - 基于重要性的优先级
        4. 实现 `MemorySummarizer`：
           - 自动摘要长记忆
           - 关键信息提取
           - 摘要存储和检索
        5. 实现 `MemoryTTLManager`：
           - 基于时间的过期策略
           - 基于容量的淘汰策略
           - 手动清理接口
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_memory_manager.py` 通过
        - [ ] 验证记忆聚合
        - [ ] 验证优先级排序
        - [ ] 验证自动摘要
        - [ ] 验证 TTL 清理
    - **依赖**: Task 0.1
    - **工时估算**: 2 天

||- [ ] **Task 0.4: Tool Hub 核心**
    - **输入**: 设计文档 4.1 节
    - **输出**: `app/tools/base.py`, `app/tools/hub.py`
    - **需求**:
        1. 定义 `Tool` 抽象基类（name, description, schema, execute）
        2. 定义 `ToolSchema` 模型
        3. 实现 `ToolHub` 类（工具注册、查找）
        4. 实现 `@tool` 装饰器简化工具注册
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_tool_hub.py` 通过
        - [ ] 验证工具注册和查找功能
    - **依赖**: Task 0.2
    - **工时估算**: 1 天

||- [ ] **Task 0.5: Prompt 管理系统**
    - **输入**: 设计文档 3.7 节
    - **输出**: `app/core/prompt_manager.py`
    - **需求**:
        1. 实现 `PromptRegistry` 类：
           - Prompt 模板的注册和发现
           - Prompt 元数据管理（名称、描述、标签）
           - Prompt 分类和搜索
        2. 实现 `PromptVersionManager`：
           - 版本化存储 Prompt
           - 版本历史记录
           - 版本回滚能力
           - 版本对比（diff）
        3. 实现 `PromptABTester`：
           - A/B 测试配置
           - 流量分配（百分比路由）
           - 效果指标收集
           - 胜出版本自动切换
        4. 实现 `PromptTemplateEngine`：
           - 参数化模板渲染
           - 变量插值
           - 条件渲染
           - 循环支持
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_prompt_manager.py` 通过
        - [ ] 验证 Prompt 注册和发现
        - [ ] 验证版本管理
        - [ ] 验证 A/B 测试
        - [ ] 验证模板渲染
    - **依赖**: Task 0.3
    - **工时估算**: 2 天

||- [ ] **Task 0.6: Agent Registry & Factory**
    - **输入**: 设计文档 6.8 节、task-bug.md 执行顺序修正
    - **输出**: `app/agents/registry.py`, `app/agents/factory.py`
    - **需求**:
        1. 实现 `AgentRegistry` 类：
           - Agent 元数据注册和查询
           - Agent 版本管理（支持多版本并存）
           - Agent 分类和标签系统
        2. 实现 `AgentFactory` 类：
           - 基于配置的 Agent 实例构建
           - 依赖注入（Tool、Skill、Memory）
           - 配置验证和默认值处理
        3. 实现 `AgentLoader` 类：
           - 从配置文件加载 Agent 定义
           - 从数据库加载持久化的 Agent
           - 动态 Agent 注册发现机制
        4. 实现 Agent A/B 测试支持：
           - 多版本路由
           - 流量分配
           - 效果追踪
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_agent_registry.py` 通过
        - [ ] 验证 Agent 动态加载
        - [ ] 验证配置化创建
        - [ ] 验证 A/B 测试路由
    - **依赖**: Task 0.4, Task 0.5
    - **工时估算**: 2 天

||- [ ] **Task 0.7: Tenant 管理核心**
    - **输入**: 设计文档第 9 章
    - **输出**: `app/tenants/manager.py`, `app/tenants/models.py`
    - **需求**:
        1. 实现完整的 `Tenant` 模型：
           - 租户基本信息
           - 套餐和配额
           - 模型白名单/黑名单
           - 速率限制配置
        2. 实现 `TenantModelRegistry`：
           - 租户级别的可用模型
           - 模型使用配额
           - 自定义模型配置
        3. 实现租户隔离机制：
           - 内存隔离
           - 存储隔离
           - Agent 隔离
           - 工具隔离
        4. 实现 `TenantBilling`：
           - 使用量统计
           - 费用计算
           - 账单生成
           - 欠费处理
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_tenant_manager.py` 通过
        - [ ] 验证租户配置加载
        - [ ] 验证数据隔离
        - [ ] 验证配额限制
    - **依赖**: Task 0.2
    - **工时估算**: 2 天

||- [ ] **Task 0.8: Task 生命周期模型**
    - **输入**: 设计文档 5.2 节
    - **输出**: `app/orchestrator/task_models.py`
    - **需求**:
        1. 定义 `Task` 数据模型：
           - 任务状态（pending, running, completed, failed, cancelled）
           - 任务优先级
           - 任务依赖关系
           - 任务元数据
        2. 实现 `TaskStateMachine`：
           - 状态转换验证
           - 状态变更回调
           - 非法状态转换阻止
        3. 实现 `TaskStateStore`：
           - 任务状态持久化
           - 状态查询和历史记录
           - 状态恢复机制
        4. 实现 `TaskRetryPolicy`：
           - 最大重试次数配置
           - 重试间隔策略（指数退避）
           - 可重试和不可重试错误区分
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_task_models.py` 通过
        - [ ] 验证状态机转换
        - [ ] 验证状态持久化
        - [ ] 验证重试策略
    - **依赖**: Task 0.2
    - **工时估算**: 1.5 天

---

## 📅 阶段一：LLM Hub 基础设施

**目标**：建立完整的 LLM Hub，包括多供应商支持和核心功能。

||- [ ] **Task 1.1: OpenAI 供应商适配器**
    - **输入**: 设计文档 3.3 节
    - **输出**: `app/llm_hub/providers/openai.py`
    - **需求**:
        1. 实现 `OpenAIProvider` 类，继承 `LLMProvider`
        2. 实现非流式 `chat()` 方法（支持 function calling）
        3. 实现流式 `stream()` 方法（支持 Server-Sent Events）
        4. 实现 `embeddings()` 方法
        5. 集成 token 计数（使用 `tiktoken`）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_openai_provider.py` 通过
        - [ ] 集成测试：配置真实 API Key，成功调用 GPT-4/GPT-3.5-turbo
        - [ ] 流式输出正确解析 Delta 格式
    - **依赖**: Task 0.2
    - **工时估算**: 1.5 天

||- [ ] **Task 1.2: Anthropic 供应商适配器**
    - **输入**: 设计文档 3.3 节
    - **输出**: `app/llm_hub/providers/anthropic.py`
    - **需求**:
        1. 实现 `AnthropicProvider` 类
        2. 实现 `chat()`, `stream()`, `embeddings()` 方法
        3. 支持 Claude 特有的 `thinking` 模式
        4. 适配 Anthropic 的消息格式（区别于 OpenAI）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_anthropic_provider.py` 通过
        - [ ] 集成测试：配置 API Key，成功调用 Claude-3 系列模型
    - **依赖**: Task 0.2
    - **工时估算**: 1.5 天

||- [ ] **Task 1.3: 模型注册中心 (Model Registry)**
    - **输入**: 设计文档 3.4 节
    - **输出**: `app/llm_hub/registry.py`
    - **需求**:
        1. 实现 `ModelRegistry` 类，管理所有可用模型
        2. 实现 `register_model()` 方法注册模型元数据
        3. 实现 `get_model()` 方法按 ID 或名称查询
        4. 实现 `list_models()` 方法列出所有模型（支持过滤）
        5. 从配置文件 `models.yaml` 加载初始模型列表
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_model_registry.py` 通过
        - [ ] 注册的 OpenAI 和 Anthropic 模型可被正确查询
    - **依赖**: Task 0.2
    - **工时估算**: 1 天

||- [ ] **Task 1.4: Prompt 构建器**
    - **输入**: 设计文档 3.7 节
    - **输出**: `app/llm_hub/prompt_builder.py`
    - **需求**:
        1. 实现 `PromptBuilder` 类
        2. 实现 `build()` 方法，支持组装：
           - System Prompt（使用 Task 0.5 Prompt 管理系统）
           - Role Prompt
           - Memory Context（会话历史）
           - Few-shot Examples
           - User Input
        3. 支持不同供应商的消息格式转换（OpenAI/Anthropic）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_prompt_builder.py` 通过
        - [ ] 验证不同格式的消息正确转换为目标供应商格式
    - **依赖**: Task 0.2, Task 0.5
    - **工时估算**: 1 天

||- [ ] **Task 1.5: 流式输出管理器**
    - **输入**: 设计文档 3.9 节
    - **输出**: `app/llm_hub/streaming.py`
    - **需求**:
        1. 实现 `StreamingManager` 类
        2. 实现 `stream_response()` 方法，标准化不同供应商的流式响应格式
        3. 实现 Token 计数和内容过滤回调
        4. 支持 SSE (Server-Sent Events) 格式输出
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_streaming.py` 通过
        - [ ] OpenAI 和 Anthropic 流式输出格式统一
    - **依赖**: Task 1.1, Task 1.2
    - **工时估算**: 1 天

||- [ ] **Task 1.6: 统一推理引擎 (Inference Engine)**
    - **输入**: 设计文档 3.6 节
    - **输出**: `app/llm_hub/inference.py`
    - **需求**:
        1. 实现 `InferenceEngine` 类
        2. 实现 `infer()` 方法：
           - 请求预处理
           - Prompt 构建（使用 Task 1.4）
           - 模型选择（暂简单选择，后续 Task 1.7 实现路由）
           - 执行推理
           - 结果后处理
           - 监控记录
        3. 集成 Prompt Builder 和 Streaming Manager
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_inference_engine.py` 通过
        - [ ] 端到端测试：调用 `InferenceEngine.infer()` 获取正确响应
    - **依赖**: Task 1.3, Task 1.4, Task 1.5
    - **工时估算**: 1.5 天

||- [ ] **Task 1.7: 模型路由器 (Model Router)**
    - **输入**: 设计文档 3.5 节
    - **输出**: `app/llm_hub/router.py`
    - **需求**:
        1. 实现 `ModelRouter` 类
        2. 实现 `select_model()` 方法，支持路由策略：
           - `COST_OPTIMIZED`: 成本优先
           - `QUALITY_OPTIMIZED`: 质量优先
           - `LATENCY_OPTIMIZED`: 延迟优先
           - `BALANCED`: 平衡模式
        3. 实现 `RoutingContext` 模型（任务类型、所需能力、预算、延迟要求等）
        4. 实现基于能力的模型过滤逻辑
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_model_router.py` 通过
        - [ ] 不同策略返回正确的模型选择
    - **依赖**: Task 1.3
    - **工时估算**: 1.5 天

||- [ ] **Task 1.8: 工具调用网关 (Tool Calling Gateway)**
    - **输入**: 设计文档 3.8 节
    - **输出**: `app/llm_hub/tool_gateway.py`
    - **需求**:
        1. 实现 `ToolCallingGateway` 类
        2. 实现 `execute_tool_call()` 方法：
           - 解析 LLM 的工具调用请求
           - 验证工具参数
           - 执行工具
           - 返回结果
        3. 支持 OpenAI function calling 格式
        4. 支持 Anthropic tool use 格式
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_tool_gateway.py` 通过
        - [ ] 验证参数校验和错误处理
    - **依赖**: Task 1.1, Task 1.2, Task 0.4
    - **工时估算**: 1.5 天

---

## 📅 阶段二：LLM Hub 高阶特性

**目标**：实现成本管理、安全护栏和可观测性。

||- [ ] **Task 2.1: 成本与预算管理器**
    - **输入**: 设计文档 3.10 节
    - **输出**: `app/llm_hub/cost_manager.py`
    - **需求**:
        1. 实现 `CostManager` 类
        2. 实现 `track_usage()` 方法（记录 token 使用和成本到数据库）
        3. 实现 `BudgetController` 类（预算检查和告警）
        4. 集成到 Inference Engine
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_cost_manager.py` 通过
        - [ ] 验证成本计算正确（对比官方定价）
        - [ ] 验证预算超限时的告警触发
    - **依赖**: Task 1.6
    - **工时估算**: 1 天

||- [ ] **Task 2.2: 安全护栏层 (Guardrail Layer)**
    - **输入**: 设计文档 3.12 节
    - **输出**: `app/llm_hub/guardrails.py`
    - **需求**:
        1. 实现 `GuardrailLayer` 类
        2. 实现 `validate_input()` 方法：
           - PII 检测
           - 有害内容检测
           - Prompt 注入检测
        3. 实现 `validate_output()` 方法（输出内容过滤）
        4. 实现自定义策略检查接口
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_guardrails.py` 通过
        - [ ] 验证 PII 和有害内容被正确检测和过滤
    - **依赖**: Task 1.6
    - **工时估算**: 1.5 天

||- [ ] **Task 2.3: 可观测性层 (Observability Layer)**
    - **输入**: 设计文档 3.11 节、task-bug.md P1 要求
    - **输出**: `app/llm_hub/observability.py`
    - **需求**:
        1. 实现 `ObservabilityMetrics` 类（性能、质量、成本指标收集）
        2. 实现 `TraceManager` 类（集成 OpenTelemetry）
        3. 实现请求全链路追踪：
           - Execution Trace（执行链路追踪）
           - Prompt Trace（Prompt 变更追踪）
           - Token Cost Analysis（Token 使用和成本分析）
           - Agent Behavior Analysis（Agent 行为模式分析）
           - Performance Metrics（性能指标收集）
        4. 集成 Prometheus 指标暴露
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_observability.py` 通过
        - [ ] 验证 Prometheus 指标正确暴露 `/metrics` 端点
        - [ ] 验证 traces 正确发送到追踪后端
    - **依赖**: Task 1.6
    - **工时估算**: 2 天

||- [ ] **Task 2.4: Strategy Engine**
    - **输入**: task-bug.md P1 要求、设计文档策略控制
    - **输出**: `app/core/strategy_engine.py`
    - **需求**:
        1. 实现 `StrategyEngine` 类
        2. 实现 `PlanningStrategy`（计划深度控制）：
           - SHALLOW: 浅层规划（1-2 步）
           - MEDIUM: 中层规划（3-5 步）
           - DEEP: 深层规划（5-10 步）
           - UNLIMITED: 无限制
        3. 实现 `ReflectionStrategy`（反思策略控制）：
           - 最大反思次数
           - 反思阈值
           - 退避因子
        4. 实现 `ModelSelectionStrategy`（模型选择策略）
        5. 实现 `CollaborationStrategy`（协作策略控制）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_strategy_engine.py` 通过
        - [ ] 验证策略执行正确
    - **依赖**: Task 0.5
    - **工时估算**: 1.5 天

||- [ ] **Task 2.5: Azure/Google 供应商扩展**
    - **输入**: 设计文档 3.3 节
    - **输出**: `app/llm_hub/providers/azure.py`, `app/llm_hub/providers/google.py`
    - **需求**:
        1. 实现 `AzureOpenAIProvider` 类
        2. 实现 `GoogleProvider` 类（Gemini）
        3. 统一使用 LLM Provider 接口
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_azure_provider.py`, `pytest tests/unit/test_google_provider.py` 通过
        - [ ] 集成测试验证 Azure 和 Gemini API 调用
    - **依赖**: Task 0.2
    - **工时估算**: 2 天（可选）

---

## 📅 阶段三：Runtime Sandbox 与事件驱动

**目标**：根据 task-bug.md P0 要求，实现 Runtime Sandbox 和 EventBus。

||- [ ] **Task 3.1: Runtime Sandbox 核心**
    - **输入**: task-bug.md P0 要求、安全执行需求
    - **输出**: `app/runtime/sandbox.py`, `app/runtime/container.py`
    - **需求**:
        1. 实现 `RuntimeSandbox` 类：
           - Agent 执行容器
           - 文件系统隔离（限制访问目录范围、敏感文件保护）
           - CPU/内存限制（防止资源耗尽攻击）
           - 安全执行策略（白名单机制控制执行范围）
        2. 实现 `ExecutionContainer` 类：
           - 进程级隔离
           - 资源配额限制
           - 超时控制
           - 执行状态监控
        3. 实现资源限制机制：
           - CPU 时间片限制
           - 内存使用上限
           - 网络访问控制
           - 临时文件自动清理
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_runtime_sandbox.py` 通过
        - [ ] 验证资源限制生效
        - [ ] 验证文件系统隔离
        - [ ] 验证超时控制
    - **依赖**: Task 0.4, Task 0.8
    - **工时估算**: 3 天

||- [ ] **Task 3.2: EventBus Framework 核心**
    - **输入**: task-bug.md P0 要求、事件驱动架构需求
    - **输出**: `app/events/event_bus.py`, `app/events/models.py`
    - **需求**:
        1. 实现事件模型：
           - `EventType` 枚举（AgentEvent, TaskEvent, ToolEvent, MemoryEvent, WorkflowEvent）
           - `Event` 模型（event_id, event_type, timestamp, source, target, payload, correlation_id）
        2. 实现 `EventBus` 类：
           - 事件发布（同步/异步）
           - 事件订阅（按类型、按来源）
           - 事件过滤（条件过滤）
           - 事件持久化（支持回放和重试）
           - 死信队列（处理无法路由的事件）
        3. 实现 `EventPublisher` 接口
        4. 实现 `EventSubscriber` 接口
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_event_bus.py` 通过
        - [ ] 验证事件发布和订阅
        - [ ] 验证事件过滤
        - [ ] 验证事件持久化
    - **依赖**: Task 0.1
    - **工时估算**: 2.5 天

||- [ ] **Task 3.3: Agent 事件系统**
    - **输入**: Task 3.2 EventBus
    - **输出**: `app/events/agent_events.py`
    - **需求**:
        1. 实现 `AgentEventHandler` 类：
           - AGENT_STARTED 事件处理
           - AGENT_COMPLETED 事件处理
           - AGENT_FAILED 事件处理
        2. 实现事件发布方法：
           - 发布 Agent 启动事件
           - 发布 Agent 完成事件
           - 发布 Agent 错误事件
        3. 实现 Agent 状态变更的事件驱动
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_agent_events.py` 通过
        - [ ] 验证事件正确发布
        - [ ] 验证事件正确路由
    - **依赖**: Task 3.2
    - **工时估算**: 1 天

||- [ ] **Task 3.4: Task 事件系统**
    - **输入**: Task 3.2 EventBus, Task 0.8 Task Lifecycle
    - **输出**: `app/events/task_events.py`
    - **需求**:
        1. 实现 `TaskEventHandler` 类：
           - TASK_CREATED 事件处理
           - TASK_STARTED 事件处理
           - TASK_COMPLETED 事件处理
           - TASK_FAILED 事件处理
        2. 实现任务状态变更的事件发布
        3. 实现任务依赖的事件通知
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_task_events.py` 通过
        - [ ] 验证任务事件正确发布
    - **依赖**: Task 3.2, Task 0.8
    - **工时估算**: 1 天

||- [ ] **Task 3.5: Tool 事件系统**
    - **输入**: Task 3.2 EventBus, Task 0.4 Tool Hub
    - **输出**: `app/events/tool_events.py`
    - **需求**:
        1. 实现 `ToolEventHandler` 类：
           - TOOL_INVOKED 事件处理
           - TOOL_STARTED 事件处理
           - TOOL_COMPLETED 事件处理
           - TOOL_FAILED 事件处理
        2. 实现工具调用的事件发布
        3. 实现工具执行时间追踪
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_tool_events.py` 通过
        - [ ] 验证工具事件正确发布
    - **依赖**: Task 3.2, Task 0.4
    - **工时估算**: 1 天

---

## 📅 阶段四：能力层建设

**目标**：构建 AI 的"手"（工具）、"脑"（记忆）和"技能"（Skills）。

||- [ ] **Task 4.1: 工具权限与安全模型**
    - **输入**: 设计文档 4.1 节、task-bug.md 安全要求
    - **输出**: `app/tools/security.py`
    - **需求**:
        1. 实现 `ToolACL` 类：
           - 基于角色的访问控制
           - 基于用户的权限配置
           - 权限继承和覆盖
        2. 实现 `ToolTenantIsolation`：
           - 租户级别的工具可见性
           - 租户级别的工具配额
           - 跨租户工具共享机制
        3. 实现 `ToolResourceLimiter`：
           - 执行时间限制
           - 内存使用限制
           - 网络请求限制
           - 并发调用限制
        4. 实现 `ToolAuditLogger`：
           - 完整的调用日志
           - 参数脱敏
           - 审计查询接口
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_tool_security.py` 通过
        - [ ] 验证权限控制
        - [ ] 验证租户隔离
        - [ ] 验证资源限制
        - [ ] 验证审计日志
    - **依赖**: Task 0.4, Task 0.7
    - **工时估算**: 2 天

||- [ ] **Task 4.2: 内置工具集实现**
    - **输入**: 设计文档 4.1.2 节
    - **输出**: `app/tools/builtin/`
    - **需求**:
        1. 实现 `CalculatorTool`（数学计算）
        2. 实现 `DateTimeTool`（获取当前时间）
        3. 实现 `RandomTool`（随机数生成）
        4. 实现 `FileReadTool`（安全文件读取）
        5. 实现 `FileWriteTool`（安全文件写入）
        6. 实现 `DatabaseQueryTool`（安全的 SQL 查询）
        7. 实现 `HTTPRequestTool`（HTTP 请求）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_builtin_tools.py` 通过
        - [ ] 集成测试验证每个工具功能正确
    - **依赖**: Task 0.4
    - **工时估算**: 2 天

||- [ ] **Task 4.3: 搜索与网页工具**
    - **输入**: 设计文档 4.1.2 节
    - **输出**: `app/tools/builtin/search.py`, `app/tools/builtin/web_reader.py`
    - **需求**:
        1. 实现 `SearchTool`（集成 DuckDuckGo 或 Google Search API）
        2. 实现 `WebReaderTool`（网页内容抓取和解析）
        3. 实现 `URLParseTool`（URL 解析和验证）
    - **验收标准**:
        - [ ] 集成测试验证搜索和网页抓取功能
        - [ ] 验证 HTML 解析和关键信息提取
    - **依赖**: Task 0.4
    - **工时估算**: 1.5 天

||- [ ] **Task 4.4: 短期记忆系统**
    - **输入**: 设计文档 4.2.2 节
    - **输出**: `app/memory/short_term.py`
    - **需求**:
        1. 实现 `ShortTermMemory` 类
        2. 实现 `ConversationManager`（会话管理）
        3. 支持 Redis 存储（配置可选）
        4. 实现消息窗口滚动（控制上下文长度）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_short_term_memory.py` 通过
        - [ ] 集成测试验证多轮对话上下文正确
    - **依赖**: Task 0.3
    - **工时估算**: 1 天

||- [ ] **Task 4.5: 技能系统核心**
    - **输入**: 设计文档 4.3 节
    - **输出**: `app/skills/base.py`, `app/skills/manager.py`
    - **需求**:
        1. 定义 `Skill` 数据模型（skill_id, name, description, prompt_template, required_tools 等）
        2. 实现 `SkillManager` 类
        3. 实现技能注册和查询功能
        4. 实现技能执行方法
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_skill_manager.py` 通过
        - [ ] 验证技能定义和执行正确
    - **依赖**: Task 0.5, Task 0.4
    - **工时估算**: 1 天

||- [ ] **Task 4.6: 技能库实现**
    - **输入**: 设计文档 4.3.2 节
    - **输出**: `app/skills/library/`
    - **需求**:
        1. 实现 `DataAnalysisSkill`（数据分析技能）
        2. 实现 `CodeGenerationSkill`（代码生成技能）
        3. 实现 `TextWritingSkill`（文本写作技能）
        4. 实现 `TranslationSkill`（翻译技能）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_skills.py` 通过
        - [ ] 验证每个技能正确组装 Prompt 和调用 LLM
    - **依赖**: Task 4.5
    - **工时估算**: 2 天

---

## 📅 阶段五：Agent 核心系统

**目标**：实现具备感知、规划、行动能力的智能体。

||- [ ] **Task 5.1: Agent 抽象基类**
    - **输入**: 设计文档 6.2-6.3 节
    - **输出**: `app/agents/base.py`
    - **需求**:
        1. 定义 `Agent` 数据模型（agent_id, name, role, capabilities, available_tools 等）
        2. 定义 `AgentConfig` 配置模型
        3. 定义 Agent 生命周期接口（init, plan, execute, reflect）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_agent_base.py` 通过
        - [ ] 验证 Agent 配置正确加载
    - **依赖**: Task 0.6
    - **工时估算**: 1 天

||- [ ] **Task 5.2: Agent Runtime 管理器**
    - **输入**: 设计文档 6.3 节
    - **输出**: `app/agents/runtime.py`
    - **需求**:
        1. 实现 `AgentRuntime` 类，管理 Agent Session 生命周期
        2. 实现 `ContextInjector` 类，动态注入上下文信息
        3. 实现资源限制机制：
           - 迭代计数上限（防止无限循环）
           - 超时控制（最大执行时间）
           - 内存使用限制
        4. 实现执行状态持久化（集成 Checkpointer）
        5. 实现并发控制（限制并行运行的 Agent 数量）
        6. 集成 Task 3.1 Runtime Sandbox
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_agent_runtime.py` 通过
        - [ ] 验证迭代限制正确触发
        - [ ] 验证超时控制生效
        - [ ] 验证状态恢复功能
    - **依赖**: Task 3.1, Task 5.1
    - **工时估算**: 2 天

||- [ ] **Task 5.3: 规划引擎 (Planning Engine)**
    - **输入**: 设计文档 6.5 节
    - **输出**: `app/agents/planning.py`
    - **需求**:
        1. 实现 `PlanningEngine` 类
        2. 实现 `create_plan()` 方法
        3. 设计通用的 Planning Prompt 模板（使用 Task 0.5 Prompt 管理系统）
        4. 支持 JSON 格式计划输出
        5. 集成 Task 2.4 Strategy Engine
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_planning_engine.py` 通过
        - [ ] 验证复杂任务能生成合理的执行步骤
        - [ ] 验证规划结果正确传递给执行节点
    - **依赖**: Task 5.1, Task 0.5, Task 2.4
    - **工时估算**: 1 天

||- [ ] **Task 5.4: 执行引擎 (Execution Engine)**
    - **输入**: 设计文档 6.6 节
    - **输出**: `app/agents/execution.py`
    - **需求**:
        1. 实现 `ExecutionEngine` 类
        2. 实现 `execute_plan()` 方法（按序执行步骤）
        3. 实现工具调用执行（集成 Task 4.1）
        4. 实现错误处理和重试机制
        5. 集成 Task 3.2 EventBus 事件发布
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_execution_engine.py` 通过
        - [ ] 验证执行过程中的错误恢复
        - [ ] 验证执行结果正确传递给反思节点
    - **依赖**: Task 5.3, Task 4.1
    - **工时估算**: 1 天

||- [ ] **Task 5.5: 反思引擎 (Reflection Engine)**
    - **输入**: 设计文档 6.7 节
    - **输出**: `app/agents/reflection.py`
    - **需求**:
        1. 实现 `ReflectionEngine` 类
        2. 实现 `reflect()` 方法（评估结果质量）
        3. 实现重新规划触发逻辑
        4. 实现结果总结生成
        5. 集成 Task 2.4 Strategy Engine 控制反思策略
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_reflection_engine.py` 通过
        - [ ] 验证失败场景下的反思和重试
    - **依赖**: Task 5.4, Task 2.4
    - **工时估算**: 1 天

||- [ ] **Task 5.6: Multi-Agent 协作框架**
    - **输入**: 设计文档 6.8 节
    - **输出**: `app/agents/multi_agent.py`
    - **需求**:
        1. 实现 `SubAgentScheduler` 类：
           - 基于任务类型选择合适的子 Agent
           - 子 Agent 负载均衡
           - 调度优先级管理
        2. 实现 `AgentMessageProtocol`：
           - 主 Agent 与子 Agent 之间的消息格式
           - 消息路由和转发机制
           - 消息超时和重试
        3. 实现 `ResultMerger` 类：
           - 多个子 Agent 结果的合并策略
           - 冲突检测和解决
           - 结果聚合和汇总
        4. 实现子 Agent 失败恢复：
           - 自动重试机制
           - 备用 Agent 切换
           - 部分失败容忍
        5. 集成 Task 3.2 EventBus 进行事件通信
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_multi_agent.py` 通过
        - [ ] 验证子 Agent 调度正确
        - [ ] 验证消息传递
        - [ ] 验证结果合并
    - **依赖**: Task 5.2, Task 3.2
    - **工时估算**: 2.5 天

||- [ ] **Task 5.7: Agent 库实现**
    - **输入**: 设计文档 6.8.1 节
    - **输出**: `app/agents/library/`
    - **需求**:
        1. 实现 `CustomerServiceAgent`（客服 Agent）
        2. 实现 `DataAnalystAgent`（数据分析 Agent）
        3. 实现 `CodeAssistantAgent`（代码助手 Agent）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_agent_library.py` 通过
        - [ ] 验证各 Agent 正确配置和执行
    - **依赖**: Task 5.2
    - **工时估算**: 1.5 天

---

## 📅 阶段六：缓存层与优化

**目标**：根据 task-bug.md P1 要求，实现 Cache Layer 降低运行成本。

||- [ ] **Task 6.1: Cache Layer 核心**
    - **输入**: task-bug.md P1 要求、缓存策略需求
    - **输出**: `app/core/cache.py`
    - **需求**:
        1. 实现 `CacheLayer` 核心类：
           - LLM Response Cache（LLM 响应缓存）
           - Embedding Cache（向量嵌入缓存）
           - Tool Result Cache（工具调用结果缓存）
        2. 实现 `CacheConfig` 配置：
           - `LRU` 最近最少使用
           - `LFU` 最不经常使用
           - `FIFO` 先进先出
           - `TTL` 基于过期时间
        3. 实现 `CacheKey` 生成器：
           - 基于请求内容的哈希
           - 支持参数区分
        4. 实现缓存失效机制：
           - 基于 TTL 过期
           - 基于容量淘汰
           - 手动失效
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_cache.py` 通过
        - [ ] 验证 LLM 响应缓存命中
        - [ ] 验证 Embedding 缓存命中
        - [ ] 验证 TTL 过期生效
    - **依赖**: Task 0.1
    - **工时估算**: 1.5 天

||- [ ] **Task 6.2: Redis 缓存后端**
    - **输入**: Task 6.1 Cache Layer
    - **输出**: `app/core/cache_redis.py`
    - **需求**:
        1. 实现 `RedisCacheBackend` 类：
           - 连接池管理
           - 分布式锁支持
           - 集群支持
        2. 实现序列化/反序列化：
           - JSON 序列化
           - 压缩支持
        3. 实现分布式缓存一致性
    - **验收标准**:
        - [ ] 集成测试：Redis 连接成功
        - [ ] 验证分布式缓存正确工作
    - **依赖**: Task 6.1
    - **工时估算**: 1 天

||- [ ] **Task 6.3: Cache 集成到 LLM Hub**
    - **输入**: Task 6.1 Cache Layer, Task 1.6 Inference Engine
    - **输出**: `app/llm_hub/cache_integration.py`
    - **需求**:
        1. 实现 `LLMResponseCache` 类：
           - 基于请求内容的缓存键生成
           - 响应序列化存储
           - 缓存命中检测和返回
        2. 实现 `EmbeddingCache` 类：
           - 文本嵌入结果缓存
           - 相似文本缓存查找
        3. 实现缓存集成到 Inference Engine
    - **验收标准**:
        - [ ] 集成测试：LLM 调用缓存生效
        - [ ] 验证缓存命中率统计
    - **依赖**: Task 6.1, Task 1.6
    - **工时估算**: 1 天

---

## 📅 阶段七：LangGraph 集成

**目标**：集成 LangGraph 框架作为 Agent 和工作流的执行引擎。

||- [ ] **Task 7.1: LangGraph 基础集成**
    - **输入**: 设计文档 11.1 节、LangGraph 官方文档
    - **输出**: `app/langgraph/__init__.py`, `app/langgraph/base.py`
    - **需求**:
        1. 安装 `langgraph>=0.2.0` 依赖
        2. 创建 `app/langgraph/` 目录结构
        3. 实现基础类型定义：
           - LangGraph 状态类型（TypedDict）
           - 节点类型枚举
           - 边的类型（普通边、条件边）
        4. 实现 `app/langgraph/checkpointer.py`：
           - 内存版 Checkpointer
           - Redis 版 Checkpointer（支持状态持久化）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_langgraph_base.py` 通过
        - [ ] 验证 StateGraph 能够正确创建和编译
        - [ ] 验证 Checkpointer 正确保存和恢复状态
    - **依赖**: Task 3.1
    - **工时估算**: 1.5 天

||- [ ] **Task 7.2: LangGraph Agent 状态机**
    - **输入**: LangGraph StateGraph 文档
    - **输出**: `app/langgraph/agent_state_machine.py`
    - **需求**:
        1. 定义 AgentState TypedDict：
           - messages: 对话消息列表
           - current_step: 当前执行步骤
           - plan: 执行计划
           - context: 记忆上下文
           - tools_output: 工具调用结果
           - iterations: 迭代次数
        2. 实现 Agent StateGraph：
           - 节点：plan_node, execute_node, reflect_node, tool_node
           - 边：START -> plan, execute -> tool/tool_output -> reflect, reflect -> END/plan
           - 条件边：reflect -> (END if success else plan)
        3. 集成 Task 5.3、5.4、5.5 的引擎节点
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_langgraph_agent.py` 通过
        - [ ] 验证 StateGraph 正确执行 Agent 生命周期
    - **依赖**: Task 7.1, Task 5.3, Task 5.4, Task 5.5
    - **工时估算**: 2 天

||- [ ] **Task 7.3: LangGraph Agent 执行器**
    - **输入**: Task 7.2 Agent StateGraph
    - **输出**: `app/agents/executor.py`
    - **需求**:
        1. 实现基于 LangGraph 的 `LangGraphAgentExecutor` 类
        2. 复用 Task 7.2 的 Agent StateGraph
        3. 实现 `execute()` 方法：
           - 初始化 AgentState
           - 编译 StateGraph
           - 执行工作流
           - 返回执行结果
        4. 支持流式输出（使用 LangGraph 的 stream 模式）
        5. 集成 Task 3.2 EventBus 进行事件发布
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_agent_executor.py` 通过
        - [ ] 端到端测试：Agent 能够完成简单任务
        - [ ] 验证状态恢复功能
    - **依赖**: Task 7.2, Task 3.2
    - **工时估算**: 2 天

||- [ ] **Task 7.4: LangGraph 工作流引擎**
    - **输入**: 设计文档 5.1 节
    - **输出**: `app/langgraph/workflow_engine.py`
    - **需求**:
        1. 实现 `WorkflowState` TypedDict：
           - inputs: 工作流输入数据
           - outputs: 工作流输出数据
           - intermediate_values: 中间结果
           - checkpoints: 检查点数据
        2. 实现基于 LangGraph 的工作流引擎：
           - 节点工厂方法（LLMNode, ToolNode, ConditionNode, ParallelNode）
           - 边注册方法
           - 工作流编译和执行
        3. 支持执行模式：
           - Sequential（顺序执行）
           - Parallel（并行执行）
           - Conditional（条件分支）
           - Map-Reduce
        4. 集成 Task 4.5 Skill 节点
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_langgraph_workflow.py` 通过
        - [ ] 验证 "翻译 -> 摘要" 串行工作流正确执行
        - [ ] 验证并行工作流正确执行
    - **依赖**: Task 7.1, Task 4.5
    - **工时估算**: 2.5 天

---

## 📅 阶段八：Feature Flag 与服务化

**目标**：实现 Feature Flag 系统和 API 服务化。

||- [ ] **Task 8.1: Feature Flag System**
    - **输入**: task-bug.md P2 要求、功能灰度发布需求
    - **输出**: `app/core/feature_flags.py`
    - **需求**:
        1. 实现 `FeatureFlag` 模型：
           - BOOLEAN: 开关型
           - PERCENTAGE: 百分比型
           - USER_LIST: 用户列表型
           - CONDITIONAL: 条件型
        2. 实现 `FeatureFlagManager` 类：
           - Flag 注册和查询
           - Flag 评估（根据用户属性）
           - Flag 变更通知
        3. 实现 `FlagEvaluation` 追踪：
           - 评估日志
           - 使用统计
           - 效果分析
        4. 实现 Feature Flag 中间件：
           - FastAPI 集成
           - 请求拦截
           - 动态配置
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_feature_flags.py` 通过
        - [ ] 验证 Flag 评估正确
        - [ ] 验证中间件拦截生效
    - **依赖**: Task 0.7
    - **工时估算**: 2 天

||- [ ] **Task 8.2: 数据模型迁移（Alembic）**
    - **输入**: 设计文档数据库模型
    - **输出**: `alembic/versions/` 迁移文件
    - **需求**:
        1. 创建 `app/models/ai_models.py`（Agent、Workflow、Task、Usage 等模型）
        2. 生成 Alembic 迁移脚本
        3. 实现数据库表创建
    - **验收标准**:
        - [ ] `alembic revision --autogenerate` 成功生成迁移
        - [ ] `alembic upgrade head` 成功应用迁移
    - **依赖**: Task 0.7
    - **工时估算**: 1 天

||- [ ] **Task 8.3: Task Orchestrator 完善**
    - **输入**: 设计文档 5.2 节、Task 0.8 Task Lifecycle
    - **输出**: `app/orchestrator/task_orchestrator.py`, `app/orchestrator/task_decomposer.py`
    - **需求**:
        1. 完善 `TaskOrchestrator` 类：
           - 任务调度（基于优先级和依赖）
           - 执行器分配
        2. 完善 `TaskDecomposer` 类：
           - 基于 LLM 的任务拆分
           - 依赖关系解析
        3. 实现 Task DAG 依赖执行（基于 Task 7.4）
        4. 实现任务取消机制：
           - 用户取消请求处理
           - 取消传播到子任务
           - 取消后的资源清理
        5. 集成 Task 3.2 EventBus 进行事件发布
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_task_orchestrator.py` 通过
        - [ ] 验证任务状态机
        - [ ] 验证 DAG 执行
        - [ ] 验证取消机制
    - **依赖**: Task 0.8, Task 7.4, Task 3.2
    - **工时估算**: 2.5 天

||- [ ] **Task 8.4: Chat Service 实现**
    - **输入**: 设计文档 7.1 节
    - **输出**: `app/services/chat_service.py`
    - **需求**:
        1. 实现 `ChatService` 类
        2. 实现对话历史管理
        3. 实现流式响应生成
        4. 集成 LLM Hub 和 Memory Manager
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_chat_service.py` 通过
        - [ ] 集成测试验证对话功能正确
    - **依赖**: Task 5.2
    - **工时估算**: 1.5 天

||- [ ] **Task 8.5: API Endpoints 开发**
    - **输入**: 设计文档 API 路由设计
    - **输出**: `app/api/endpoints/chat.py`, `app/api/endpoints/agents.py`, `app/api/endpoints/workflows.py`
    - **需求**:
        1. 实现 `/api/v1/chat/completions` 端点
        2. 实现 `/api/v1/agents/{agent_id}/execute` 端点
        3. 实现 `/api/v1/workflows/{workflow_id}/execute` 端点
        4. 实现 `/api/v1/tools` 端点
        5. 集成 Swagger/OpenAPI 文档
        6. 实现认证中间件（API Key / JWT）
        7. 实现租户隔离（集成 Task 0.7）
        8. 集成 Feature Flag 中间件（Task 8.1）
    - **验收标准**:
        - [ ] 端到端测试：`pytest tests/api/test_endpoints.py` 通过
        - [ ] 使用 TestClient 测试所有接口
        - [ ] 验证租户隔离生效
    - **依赖**: Task 0.7, Task 8.1, Task 8.4
    - **工时估算**: 2.5 天

---

## 📅 阶段九：治理与合规

**目标**：实现企业级安全治理体系。

||- [ ] **Task 9.1: 安全策略中心**
    - **输入**: 设计文档 3.12 节、安全合规要求
    - **输出**: `app/security/policy_center.py`
    - **需求**:
        1. 实现统一的安全策略配置：
           - 内容安全策略
           - 访问控制策略
           - 资源限制策略
        2. 实现策略执行引擎：
           - 策略匹配
           - 策略评估
           - 策略执行
        3. 实现策略管理界面：
           - 策略 CRUD
           - 策略版本管理
           - 策略模拟测试
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_security_policy.py` 通过
        - [ ] 验证策略执行
    - **依赖**: Task 4.1, Task 0.7
    - **工时估算**: 2 天

||- [ ] **Task 9.2: Prompt Injection 防护**
    - **输入**: 设计文档 3.12 节、攻击模式研究
    - **输出**: `app/security/prompt_injection.py`
    - **需求**:
        1. 实现注入检测：
           - 模式匹配检测
           - 语义分析检测
           - 机器学习检测
        2. 实现注入防御：
           - 输入清洗
           - 上下文分离
           - 特殊字符处理
        3. 实现攻击响应：
           - 告警通知
           - 攻击追踪
           - 防御增强
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_prompt_injection.py` 通过
        - [ ] 验证注入检测准确率
    - **依赖**: Task 0.5
    - **工时估算**: 2.5 天

||- [ ] **Task 9.3: 审计日志系统**
    - **输入**: 合规审计要求
    - **输出**: `app/security/audit.py`
    - **需求**:
        1. 实现全链路日志记录：
           - 请求日志
           - 响应日志
           - 工具调用日志
           - 状态变更日志
        2. 实现日志安全：
           - 敏感数据脱敏
           - 日志完整性保护
           - 日志加密存储
        3. 实现审计查询：
           - 时间范围查询
           - 用户维度查询
           - 异常行为检测
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_audit.py` 通过
        - [ ] 验证日志完整性
    - **依赖**: Task 0.1
    - **工时估算**: 2 天

||- [ ] **Task 9.4: 成本计费系统**
    - **输入**: 设计文档 3.10 节、商业化需求
    - **输出**: `app/security/billing.py`
    - **需求**:
        1. 实现成本追踪：
           - Token 计数
           - 模型计费
           - 资源计费
        2. 实现预算控制：
           - 月度预算设置
           - 超预算告警
           - 超预算限制
        3. 实现账单生成：
           - 使用报告
           - 费用明细
           - 账单导出
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_billing.py` 通过
        - [ ] 验证成本追踪
    - **依赖**: Task 2.1
    - **工时估算**: 2 天

---

## 📅 阶段十：高阶特性

**目标**：实现企业级高阶特性。

||- [ ] **Task 10.1: 向量数据库集成**
    - **输入**: 设计文档 4.2.3 节
    - **输出**: `app/memory/vector_store.py`, `app/memory/long_term.py`
    - **需求**:
        1. 实现 `VectorStore` 抽象接口
        2. 实现 Qdrant/PGvector 向量存储后端
        3. 实现 `LongTermMemory` 类
        4. 实现文本 Embedding 集成（调用 LLM Hub embeddings）
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_vector_store.py` 通过
        - [ ] 集成测试验证语义检索正确
    - **依赖**: Task 0.2
    - **工时估算**: 2 天

||- [ ] **Task 10.2: 工作流模板库**
    - **输入**: 设计文档 5.1.4 节
    - **输出**: `app/workflows/templates/`
    - **需求**:
        1. 实现 `IntentRoutingWorkflow`（意图路由工作流）
        2. 实现 `DataPipelineWorkflow`（数据处理工作流）
        3. 实现工作流验证器
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_workflow_templates.py` 通过
    - **依赖**: Task 7.4
    - **工时估算**: 1.5 天

||- [ ] **Task 10.3: 本地模型支持**
    - **输入**: 设计文档 3.3 节
    - **输出**: `app/llm_hub/providers/local.py`
    - **需求**:
        1. 实现 `OllamaProvider` 类
        2. 实现 `vLLMProvider` 类
        3. 实现本地模型热加载
    - **验收标准**:
        - [ ] 单元测试：`pytest tests/unit/test_local_providers.py` 通过
        - [ ] 集成测试验证本地模型调用
    - **依赖**: Task 0.2
    - **工时估算**: 1.5 天（可选）

---

## 📋 附录 A: 依赖配置

### 核心依赖 (pyproject.toml)

```toml
[tool.poetry.dependencies]
python = "^3.11"

# Web 框架
fastapi = "^0.109.0"
uvicorn = {extras = ["standard"], version = "^0.27.0"}

# 数据验证
pydantic = "^2.5.0"
pydantic-settings = "^2.1.0"

# 数据库
sqlalchemy = "^2.0.25"
alembic = "^1.13.0"
mysql-connector-python = "^8.2.0"

# LLM 集成
openai = "^1.12.0"
anthropic = "^0.21.0"
httpx = "^0.26.0"
tiktoken = "^0.5.0"

# LangGraph 框架
langgraph = "^0.2.0"

# 向量数据库
qdrant-client = "^1.7.0"
sentence-transformers = "^2.2.2"

# 缓存与任务队列
redis = "^5.0.0"
celery = "^5.3.0"

# 可观测性
opentelemetry-api = "^1.22.0"
opentelemetry-sdk = "^1.22.0"
prometheus-client = "^0.19.0"

# 日志与工具
loguru = "^0.7.2"
python-dotenv = "^1.0.0"
pyyaml = "^6.0.1"
```

### 开发依赖

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^7.4.0"
pytest-asyncio = "^0.23.0"
pytest-cov = "^4.1.0"
httpx = "^0.26.0"
black = "^24.0.0"
isort = "^5.13.0"
ruff = "^0.2.0"
mypy = "^1.8.0"
```

---

## 📊 任务统计

| 阶段 | 任务数量 | 总工时估算 |
|------|---------|------------|
| Phase 0: 平台基础 | 8 | 13 天 |
| Phase 1: LLM Hub 基础设施 | 8 | 10.5 天 |
| Phase 2: LLM Hub 高阶 | 5 | 7 天 |
| Phase 3: Runtime Sandbox 与事件驱动 | 5 | 8.5 天 |
| Phase 4: 能力层 | 6 | 9.5 天 |
| Phase 5: Agent 核心 | 7 | 9.5 天 |
| Phase 6: 缓存层与优化 | 3 | 3.5 天 |
| Phase 7: LangGraph 集成 | 4 | 8 天 |
| Phase 8: Feature Flag 与服务化 | 5 | 9.5 天 |
| Phase 9: 治理与合规 | 4 | 8.5 天 |
| Phase 10: 高阶特性 | 3 | 5 天（可选） |
| **总计** | **58** | **约 87 天** |

---

## 📝 实施建议

### 优先级排序

1. **P0（必须实现）**：Phase 0 - Phase 5
2. **P1（强烈建议）**：Phase 6 - Phase 7
3. **P2（可选优化）**：Phase 8 - Phase 10

### 分阶段实施

**第一阶段（基础建设）**：Phase 0 - Phase 3，约 48 天
- 完成平台基础、LLM 基础设施、Runtime Sandbox、事件驱动

**第二阶段（能力构建）**：Phase 4 - Phase 5，约 19 天
- 完成能力层、Agent 核心

**第三阶段（优化增强）**：Phase 6 - Phase 7，约 11.5 天
- 完成缓存层、LangGraph 集成

**第四阶段（服务化与治理）**：Phase 8 - Phase 9，约 18 天
- 完成服务化、安全治理

**第五阶段（高阶特性）**：Phase 10，约 5 天（可选）

### 关键路径

```
Task 0.1 (LLM Mock) 
    ↓
Task 0.2 (LLM Hub Core)
    ↓
Task 1.1-1.8 (LLM Hub Features)
    ↓
Task 3.1 (Runtime Sandbox) ← Task 0.4, Task 0.8
    ↓
Task 3.2 (EventBus) ← Task 0.1
    ↓
Task 5.2 (Agent Runtime) ← Task 3.1, Task 5.1
    ↓
Task 7.3 (LangGraph Executor) ← Task 7.2, Task 3.2
```

---

## ✅ 核心改进总结

根据 `docs/task-bug.md` 问题分析，本任务文档已实现以下核心改进：

### 新增模块（按 P0/P1/P2 优先级）

| 优先级 | 模块 | 任务 | 状态 |
|--------|------|------|------|
| **P0** | Runtime Sandbox | Task 3.1 | ✅ 已添加 |
| **P0** | EventBus Framework | Task 3.2-3.5 | ✅ 已添加 |
| **P0** | Memory Manager 依赖修正 | Task 0.3 | ✅ 已修正 |
| **P1** | Observability System | Task 2.3 | ✅ 已添加 |
| **P1** | Cache Layer | Task 6.1-6.3 | ✅ 已添加 |
| **P1** | Strategy Engine | Task 2.4 | ✅ 已添加 |
| **P2** | Feature Flag System | Task 8.1 | ✅ 已添加 |
| **P2** | LLM Mock Layer | Task 0.1 | ✅ 已添加 |

### 修正的依赖关系

1. **Memory Manager**：从依赖 Agent 改为被 Agent 依赖（Task 0.3 作为基础设施）
2. **Agent Registry**：调整执行顺序至 Capability Layer 之后
3. **Task Lifecycle**：独立为基础模块

### 新增阶段

1. **Phase 3**: Runtime Sandbox 与事件驱动
2. **Phase 6**: 缓存层与优化
3. **Phase 8**: Feature Flag 与服务化

### 任务总数对比

| 对比项 | 之前 | 现在 |
|--------|------|------|
| 总阶段数 | 8 | 10 |
| 总任务数 | 51 | 58 |
| 总工时估算 | 约 79 天 | 约 87 天 |
