# Agent 记忆储备系统设计方案

## 背景与问题

当前项目采用 **LangGraph StateGraph** 驱动的 `Plan → Execute → Reflect` 循环。每一轮 Agent 的思考、工具调用、反思结论、报错等信息都**通过 [AgentState](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#36-75) 的各个字段在节点间传递**，但：

1. **只有「单次 Agent 执行」内的上下文**：[AgentState](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#36-75) 在每次 [execute_stream()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1599-1855) / [execute()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1390-1487) 调用时重新初始化，前一次任务的记忆完全消失。
2. **无结构化记忆读写接口**：各节点直接操作 `state` 字典，没有统一抽象层，记忆的"写入时机"和"读取位置"分散在代码各处。
3. **现有 [ShortTermMemory](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/memory/short_term.py#4-57) 只存消息**：[app/memory/short_term.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/memory/short_term.py) 仅保存 `conversation_id → messages[]`，不涉及计划、工具调用结果、反思、报错等 Agent 行为层面的数据。

---

## 设计目标

| 目标 | 说明 |
|------|------|
| **行为级记忆** | 记录 Agent 的计划、每步执行结果、反思结论、报错信息、用户操作行为 |
| **跨迭代持续** | 同一次任务内，每一轮（iteration）的记忆追加写入，不被覆盖 |
| **读写统一接口** | 每个节点（plan/execute/reflect）进入时先"读记忆"，结束时"写记忆" |
| **轻量无侵入** | 不破坏现有 LangGraph 状态流，作为 [AgentState](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#36-75) 的一个字段注入 |
| **可选持久化** | 默认内存存储，可扩展为 SQLite / Redis 热备，支持服务重启恢复 |

---

## 核心设计思路：「双层记忆模型」

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Memory System                           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Layer 1: AgentRunMemory（本次任务运行级记忆）              │    │
│  │  作用域: 单次 execute / execute_stream 整个生命周期          │    │
│  │  ─ 每个 iteration 的计划快照                                 │    │
│  │  ─ 每个步骤的执行结果（工具/技能/委派/final_answer）         │    │
│  │  ─ 每次反思的完整结论                                        │    │
│  │  ─ 每条报错记录（与现有 error_context 对齐）                  │    │
│  │  ─ 用户操作行为（确认/拒绝）                                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Layer 2: AgentSessionMemory（会话级任务摘要记忆）          │    │
│  │  作用域: 同一 conversation_id 下的多次任务历史              │    │
│  │  ─ 本次任务摘要（任务目标 + 最终答案）                       │    │
│  │  ─ 关键能力发现（哪些工具/技能有效、哪些失败）                │    │
│  │  ─ 用户偏好记录（拒绝/允许过的操作类型）                     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

> **第一期优先实现 Layer 1**，让 Agent 在单次任务执行中拥有完整的行为记忆；Layer 2 作为后续扩展方向。

---

## 记忆数据结构设计

### 1. `MemoryEntry`（记忆条目基类）

```python
# app/memory/agent_run_memory.py

from dataclasses import dataclass, field
from typing import Any, Literal, Optional
import time

@dataclass
class MemoryEntry:
    """单条记忆条目 - Agent 每一个行为节点的快照"""
    
    # 记忆类型（决定读取时如何使用）
    entry_type: Literal[
        "plan",           # 规划产出：步骤列表 + 推理过程
        "tool_call",      # 工具调用：工具名 + 入参 + 结果 + 是否成功
        "skill_call",     # 技能调用：技能ID + 结果
        "delegate",       # 子 Agent 委派：目标 Agent + 任务 + 结果
        "reflection",     # 反思结论：是否成功 + 是否需重规划 + 建议
        "error",          # 报错记录：错误类型 + 错误消息 + 建议
        "user_action",    # 用户操作：确认/拒绝 + 工具名
        "final_answer",   # 最终答案合成
    ]
    
    iteration: int          # 所属迭代轮次（0-indexed）
    timestamp: float        # 写入时间戳（秒）
    data: dict[str, Any]    # 实际载荷数据
    success: bool = True    # 该条目是否代表「成功」状态
    metadata: dict = field(default_factory=dict)  # 扩展元数据
```

### 2. `AgentRunMemory`（本次任务运行记忆）

```python
@dataclass 
class AgentRunMemory:
    """
    本次 Agent 任务运行的完整记忆
    
    在 execute() / execute_stream() 的生命周期内持续存在。
    通过 AgentState["run_memory"] 挂载到 LangGraph 状态中。
    """
    
    task: str                           # 任务目标
    agent_id: str                       # 执行者 Agent ID
    started_at: float = field(default_factory=time.time)
    
    # 按时序追加的记忆条目
    entries: list[MemoryEntry] = field(default_factory=list)
    
    # 快速查询索引 (从 entries 导出，避免全量扫描)
    _plan_snapshots: list[dict] = field(default_factory=list)  # 历次计划
    _errors: list[dict] = field(default_factory=list)          # 历次报错
    _reflections: list[dict] = field(default_factory=list)     # 历次反思
    _user_actions: list[dict] = field(default_factory=list)    # 用户操作历史
    
    # ───── 写入接口 ─────
    
    def write_plan(self, iteration: int, steps: list, reasoning: str): ...
    def write_tool_call(self, iteration: int, tool_name: str, params: dict, 
                        result: Any, success: bool, error: str = ""): ...
    def write_reflection(self, iteration: int, result: dict): ...
    def write_error(self, iteration: int, error_record: dict): ...
    def write_user_action(self, iteration: int, action: str, tool_name: str): ...
    def write_final_answer(self, iteration: int, answer: str): ...
    
    # ───── 读取接口 ─────
    
    def get_memory_summary_for_planning(self, current_iteration: int) -> dict: ...
    """规划前调用：返回历次计划、反思建议、错误摘要、用户拒绝工具"""
    
    def get_memory_summary_for_reflection(self, current_iteration: int) -> dict: ...
    """反思前调用：返回本轮执行结果记忆 + 历史反思 + 已知错误"""
    
    def get_full_timeline(self) -> list[dict]: ...
    """获取时序完整记忆流（用于调试或前端展示）"""
```

---

## 与现有架构的集成方案

### 3.1 [AgentState](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#36-75) 新增字段

```python
# langgraph_executor.py

class AgentState(TypedDict):
    # ... 现有字段保持不变 ...
    
    # 🆕 本次任务运行级记忆（新增）
    # NOTE: 在 execute()/execute_stream() 中初始化，
    #       贯穿整个 Plan-Execute-Reflect 循环生命周期
    run_memory: Optional[AgentRunMemory]
```

### 3.2 初始化时机（在 execute_stream 中创建）

```python
# LangGraphAgentExecutor.execute_stream()

initial_state = AgentState(
    messages=[...],
    task=task,
    agent=agent,
    # ... 现有字段 ...
    
    # 🆕 初始化本次任务的运行记忆
    run_memory=AgentRunMemory(
        task=task,
        agent_id=agent.agent_id
    )
)
```

### 3.3 各节点读写规则

```
┌──────────────────────────────────────────────────────────────────────┐
│  _plan_node                                                          │
│  ┌─ [读] run_memory.get_memory_summary_for_planning(iteration)      │
│  │       → 提取: 历次计划、历次反思、错误列表、用户拒绝工具            │
│  │       → 注入 planning_engine.create_plan(context=memory_summary) │
│  └─ [写] run_memory.write_plan(iteration, steps, reasoning)         │
└──────────────────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────────────────┐
│  _execute_node                                                       │
│  ┌─ [写] 每个步骤执行完毕后立即写入:                                   │
│  │       run_memory.write_tool_call(...)                             │
│  │       run_memory.write_error(...)       （失败步骤）               │
│  │       run_memory.write_user_action(...) （用户确认/拒绝）           │
│  └─ (不读取，该阶段只负责写入)                                         │
└──────────────────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────────────────┐
│  _reflect_node                                                       │
│  ┌─ [读] run_memory.get_memory_summary_for_reflection(iteration)     │
│  │       → 读取本轮执行摘要 + 历次反思历史 + 错误脉络                  │
│  │       → 注入 reflection_engine.reflect(memory_context=...)       │
│  └─ [写] run_memory.write_reflection(iteration, reflection_result)  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 记忆注入到 LLM Prompt 的方式

规划引擎 (`planning.py`) 和反思引擎 (`reflection.py`) 在组装 Prompt 时，将记忆摘要以**结构化文本块**方式插入：

```
#### [行为记忆摘要 - 历次迭代]

**第 0 轮**
- 计划: [步骤1] 调用 database_query 查订单 | [步骤2] 合成答案
- 执行: database_query → 成功，返回订单 1002 信息
- 反思: 任务已完成，无需重规划

**第 1 轮 (重规划)**
- 报错: file_write → 用户拒绝（UserRejected）
- 用户操作: 拒绝了 file_write 操作
- 反思: 需重规划，应放弃文件写入，直接返回内容
```

---

## 文件改动清单（初步设计，非最终实现）

### 新增文件

| 文件 | 说明 |
|------|------|
| `app/memory/agent_run_memory.py` | `MemoryEntry` + `AgentRunMemory` 核心实现 |
| `app/memory/agent_session_memory.py` | （第二期）跨任务的会话摘要记忆 |

### 修改文件

| 文件 | 改动说明 |
|------|----------|
| [app/agents/langgraph_executor.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py) | [AgentState](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#36-75) 新增 `run_memory` 字段；在三个节点中加入读/写调用 |
| [app/agents/planning.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py) | `create_plan()` 增加 `memory_context` 参数，拼入 Prompt |
| [app/agents/reflection.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/reflection.py) | [reflect()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#955-1102) 增加 `memory_context` 参数，拼入 Prompt |
| `app/memory/__init__.py` | 导出新模块 |

---

## 方案对比：为什么不用数据库持久化（第一期）

| 方案 | 优点 | 缺点 |
|------|------|------|
| **内存对象（本方案）** | 零延迟、零依赖、与现有 AgentState 天然兼容 | 进程重启后记忆丢失（单次任务内无此问题） |
| SQLite 序列化 | 跨进程恢复 | 需要 JSON 序列化/反序列化开销，增加 I/O |
| Redis | 分布式共享 | 需要新的基础设施依赖 |

> 第一期目标是**让 Agent 在单次任务（5轮迭代内）拥有行为记忆**，内存对象完全满足需求。后续可将 `AgentRunMemory` 序列化到 SQLite，实现历史任务查看。

---

## 💬 需要与你确认的几个设计决策

> [!IMPORTANT]
> 在开始实现前，希望你确认以下几点：

1. **Layer 2（会话级摘要记忆）是否纳入本期**？即：同一个 `conversation_id` 的多次任务之间，Agent 是否应该记住"上次任务中用户拒绝了 file_write"？还是每次任务都全新开始？

2. **记忆是否需要前端展示**？如果需要，可以在 SSE 事件中新增一个 `memory_snapshot` 事件类型，把当前记忆时间线推送到前端可视化展示。

3. **记忆摘要注入 Prompt 的粒度**：方案中每轮只注入「摘要」，不注入完整原始数据（避免 Prompt 爆长）。你是否希望对某类记忆（如工具调用的完整结果）进行完整注入？

4. **子 Agent 的记忆隔离策略**：子 Agent 执行时，是拥有独立的 `AgentRunMemory` 实例，还是共享父 Agent 的记忆（以子树形式挂载）？建议独立实例，父 Agent 仅接收子 Agent 的摘要结果。
