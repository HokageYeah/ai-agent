# Agent 记忆储备系统设计方案 v2（消息格式化传递版）

## 与 v1 的核心差异

| 对比维度 | v1（文本拼接） | v2（消息格式，本方案）|
|---|---|---|
| 记忆传递方式 | 把历史拼接成一段大文本追加到 prompt 末尾 | 以 OpenAI `messages` 数组格式传递，每条记忆是独立的消息 |
| 上下文结构 | 一个 `user` 消息包含所有内容 | `system` 定义角色 → `agent历史行为` 以 `assistant + tool` 消息对呈现 → 最新 `user` 触发本轮任务 |
| LLM 感知能力 | LLM 把历史当作"描述文本"理解 | LLM 把历史当作"真实发生过的对话"理解，精准感知每一次工具调用和结果 |
| 工具调用历史 | 文字描述拼到 prompt | 以 `assistant.tool_calls + tool result` 角色对呈现，完全符合 Function Calling 协议 |

---

## 目标：让每个引擎都"看到"完整的行为记忆

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    传入规划 / 反思 / 执行引擎的 messages 结构                    │
│                                                                               │
│  [0] {"role": "system",    "content": "你是 {agent.name}，{role}"}            │
│  [1] {"role": "user",      "content": "任务: 帮我查询订单 1002..."}             │
│                                                                               │
│  ── 第 0 轮历史记忆（从 AgentRunMemory 序列化生成） ──                           │
│  [2] {"role": "assistant", "tool_calls": [                                    │
│         {"id":"call_1", "type":"function",                                    │
│          "function": {"name":"database_query","arguments":"..."}}              │
│       ]}                                                                      │
│  [3] {"role": "tool",      "tool_call_id": "call_1",                          │
│       "name": "database_query", "content": "{\"status\":\"success\",...}"}    │
│  [4] {"role": "assistant", "content": "【反思结论-第0轮】success=true..."}      │
│                                                                               │
│  ── 第 1 轮历史记忆（若发生重规划） ──                                           │
│  [5] {"role": "assistant", "tool_calls": [...]}  ← 上一轮规划调用              │
│  [6] {"role": "tool",      ...}                  ← 上一轮工具返回              │
│  [7] {"role": "user",      "content": "【用户操作】拒绝了 file_write 操作"}     │
│  [8] {"role": "assistant", "content": "【反思结论-第1轮】needs_replanning=true"}│
│                                                                               │
│  ── 当前轮触发消息 ──                                                          │
│  [9] {"role": "user",      "content": "请基于以上历史，制定新的执行计划"}         │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 数据结构设计

### 1. `AgentMemoryMessage`（记忆消息单元）

```python
# app/memory/agent_run_memory.py

from dataclasses import dataclass, field
from typing import Any, Literal, Optional
import time, uuid

@dataclass
class AgentMemoryMessage:
    """
    一条标准化的 Agent 记忆消息
    
    完全对齐 OpenAI messages 格式，可直接合并到 LLM 调用的 messages 数组。
    """
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    
    # assistant 角色发起工具调用时填写（对应 Function Calling 输出）
    tool_calls: Optional[list[dict]] = None
    
    # tool 角色返回结果时填写
    tool_call_id: Optional[str] = None
    name: Optional[str] = None  # tool 角色：工具名称
    
    # 元数据（不传给 LLM，仅用于内部追踪/过滤）
    meta: dict = field(default_factory=dict)
    # 如: {"iteration": 0, "entry_type": "tool_call", "timestamp": 1234567.89}
    
    def to_openai_dict(self) -> dict:
        """
        转换为 OpenAI API 兼容格式（去掉 meta 等内部字段）
        """
        msg: dict = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg
```

### 2. `AgentRunMemory`（运行级记忆仓库）

```python
@dataclass
class AgentRunMemory:
    """
    本次 Agent 任务的完整运行记忆
    
    存储所有历史消息，提供按引擎需求输出对应 messages 子集的接口。
    生命周期：单次 execute() / execute_stream() 调用期间。
    挂载位置：AgentState["run_memory"]
    """
    task: str
    agent_id: str
    agent_name: str
    started_at: float = field(default_factory=time.time)
    
    # 按时序追加的记忆消息（含元数据，不直接用于 LLM）
    _messages: list[AgentMemoryMessage] = field(default_factory=list)

    # ─── 写入接口（由 langgraph_executor 各节点调用）───

    def write_plan(self, iteration: int, reasoning: str, steps: list[dict]) -> None:
        """
        记录规划产出（assistant 角色的一条规划说明消息）
        """
        content = f"【规划-第{iteration}轮】推理: {reasoning}\n步骤: {steps}"
        self._messages.append(AgentMemoryMessage(
            role="assistant",
            content=content,
            meta={"iteration": iteration, "entry_type": "plan"}
        ))

    def write_tool_call(
        self, iteration: int,
        tool_name: str, tool_args: dict,
        tool_result: Any, success: bool,
        call_id: str | None = None
    ) -> None:
        """
        记录工具调用（assistant.tool_calls + tool result 配对消息）
        严格遵循 OpenAI Function Calling 格式。
        """
        import json
        call_id = call_id or f"call_{uuid.uuid4().hex[:8]}"
        
        # Step1: assistant 发起工具调用
        self._messages.append(AgentMemoryMessage(
            role="assistant",
            tool_calls=[{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_args, ensure_ascii=False)
                }
            }],
            meta={"iteration": iteration, "entry_type": "tool_call", "success": success}
        ))
        
        # Step2: tool 返回结果
        result_str = json.dumps(tool_result, ensure_ascii=False) if not isinstance(tool_result, str) else tool_result
        if not success:
            result_str = f"[ERROR] {result_str}"
        self._messages.append(AgentMemoryMessage(
            role="tool",
            tool_call_id=call_id,
            name=tool_name,
            content=result_str,
            meta={"iteration": iteration, "entry_type": "tool_result", "success": success}
        ))

    def write_skill_call(self, iteration: int, skill_id: str, result: Any, success: bool) -> None:
        """记录技能调用（以 assistant + tool 对呈现，team 名为 skill_id）"""
        import json
        call_id = f"skill_{uuid.uuid4().hex[:8]}"
        self._messages.append(AgentMemoryMessage(
            role="assistant",
            tool_calls=[{
                "id": call_id, "type": "function",
                "function": {"name": skill_id, "arguments": "{}"}
            }],
            meta={"iteration": iteration, "entry_type": "skill_call"}
        ))
        result_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
        self._messages.append(AgentMemoryMessage(
            role="tool", tool_call_id=call_id, name=skill_id,
            content=result_str if success else f"[ERROR] {result_str}",
            meta={"iteration": iteration, "entry_type": "skill_result"}
        ))

    def write_delegate(self, iteration: int, child_agent_id: str, task: str, result: str) -> None:
        """记录子 Agent 委派（以 assistant 说明 + user 返回摘要呈现）"""
        self._messages.append(AgentMemoryMessage(
            role="assistant",
            content=f"【委派子Agent: {child_agent_id}】任务: {task}",
            meta={"iteration": iteration, "entry_type": "delegate"}
        ))
        self._messages.append(AgentMemoryMessage(
            role="user",
            content=f"【子Agent返回-{child_agent_id}】{result}",
            meta={"iteration": iteration, "entry_type": "delegate_result"}
        ))

    def write_user_action(self, iteration: int, action: str, tool_name: str) -> None:
        """记录用户确认/拒绝操作"""
        action_desc = "确认" if action == "confirm" else "拒绝"
        self._messages.append(AgentMemoryMessage(
            role="user",
            content=f"【用户操作】用户{action_desc}了 [{tool_name}] 操作",
            meta={"iteration": iteration, "entry_type": "user_action", "action": action}
        ))

    def write_reflection(self, iteration: int, result: dict) -> None:
        """记录反思结论（assistant 角色说明当前轮的反思判断）"""
        success = result.get("success", False)
        needs_replan = result.get("needs_replanning", False)
        feedback = result.get("feedback", "")
        self._messages.append(AgentMemoryMessage(
            role="assistant",
            content=(
                f"【反思结论-第{iteration}轮】"
                f"success={success}, needs_replanning={needs_replan}. "
                f"反馈: {feedback}"
            ),
            meta={"iteration": iteration, "entry_type": "reflection"}
        ))

    # ─── 读取接口（由各引擎调用，输出符合 OpenAI 格式的 messages 数组）───

    def build_messages_for_planning(
        self,
        system_prompt: str,
        task: str,
        current_iteration: int,
        trigger_prompt: str = "请基于以上历史记录，制定本轮的执行计划。"
    ) -> list[dict]:
        """
        为规划引擎组装完整的 messages 数组。
        
        结构：
          [system] 角色定义
          [user]   原始任务
          [历史记忆消息...] (iteration < current_iteration 的所有记录)
          [user]   本轮规划触发指令
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"任务: {task}"},
        ]
        # 注入历史记忆（排除当前轮，只看之前迭代的记录）
        history = [
            m.to_openai_dict()
            for m in self._messages
            if m.meta.get("iteration", 9999) < current_iteration
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": trigger_prompt})
        return messages

    def build_messages_for_reflection(
        self,
        system_prompt: str,
        task: str,
        current_iteration: int,
        trigger_prompt: str = "请基于以上执行过程，进行反思评估。"
    ) -> list[dict]:
        """
        为反思引擎组装完整的 messages 数组。
        
        结构：
          [system] 角色定义
          [user]   原始任务
          [历史记忆...] 含当前轮的工具调用记录（iteration <= current_iteration）
          [user]   反思触发指令
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"任务: {task}"},
        ]
        # 包含当前轮的执行结果（用于反思），但排除当前轮的 "reflection" 消息
        history = [
            m.to_openai_dict()
            for m in self._messages
            if m.meta.get("iteration", 9999) <= current_iteration
            and m.meta.get("entry_type") != "reflection"
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": trigger_prompt})
        return messages

    def get_timeline(self) -> list[dict]:
        """返回完整的时序记忆快照（含 meta，用于调试和前端展示）"""
        return [
            {**m.to_openai_dict(), "meta": m.meta}
            for m in self._messages
        ]
```

---

## 各引擎的改造方式

### [planning.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py) — [create_plan()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#98-203) 改造

```python
# 改造前 —— 单条 user message + 文本拼接
response = await self.llm_hub.infer(
    messages=[{"role": "user", "content": prompt}],
    config=config
)

# 改造后 —— 从 run_memory 取出完整 messages 数组传入
messages = run_memory.build_messages_for_planning(
    system_prompt=self._build_system_prompt(agent, available_tools, available_skills),
    task=task,
    current_iteration=iteration,
    trigger_prompt=self._build_trigger_prompt(context)  # 只保留任务要求，不再拼接错误/反思
)
response = await self.llm_hub.infer(messages=messages, config=config)
```

**改造要点**：
- [_build_planning_prompt()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#204-393) 拆分为 `_build_system_prompt()`（固定的角色+工具描述+输出格式要求）和 `_build_trigger_prompt()`（本轮规划指令），后者仍为单条 `user` 消息。
- 错误记录、反思历史、用户拒绝等不再文字拼接——它们已经在 `run_memory` 的历史消息里，LLM 直接通过 messages 上下文感知。

### [reflection.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/reflection.py) — [reflect()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/reflection.py#85-182) 改造

```python
# 改造前
response = await self.llm_hub.infer(
    messages=[{"role": "user", "content": prompt}],
    config=config
)

# 改造后
messages = run_memory.build_messages_for_reflection(
    system_prompt=self._build_reflection_system_prompt(),
    task=task,
    current_iteration=iteration,
    trigger_prompt=self._build_reflection_trigger()
)
response = await self.llm_hub.infer(messages=messages, config=config)
```

### [langgraph_executor.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py) — 三个节点增加写入调用

```python
# _plan_node：规划完成后写入
state["run_memory"].write_plan(iteration, plan.reasoning, [s.to_dict() for s in plan.steps])

# _execute_node：每个步骤完成后立即写入
# 工具调用
state["run_memory"].write_tool_call(iteration, tool_name, params, result, success)
# 用户操作
state["run_memory"].write_user_action(iteration, action, tool_name)

# _reflect_node：反思完成后写入
state["run_memory"].write_reflection(iteration, reflection_result.to_dict())
```

---

## 消息格式完整示例（一次完整执行）

```json
[
  {
    "role": "system",
    "content": "你是客服总监（cs_master）...\n可用工具: datetime\n可用子Agent: order_agent, refund_agent\n请制定执行计划，返回JSON..."
  },
  {
    "role": "user",
    "content": "任务: 帮我查询订单 1002 的详情"
  },
  
  // ── 第 0 轮记忆（重规划时 LLM 可以看到以下内容）──
  {
    "role": "assistant",
    "content": "【规划-第0轮】推理: 需要委派给 order_agent 查询\n步骤: [{\"action\":\"delegate\",...}]"
  },
  {
    "role": "assistant",
    "tool_calls": [{
      "id": "call_abc123",
      "type": "function",
      "function": {"name": "order_agent", "arguments": "{\"task\": \"查询订单1002\"}"}
    }]
  },
  {
    "role": "tool",
    "tool_call_id": "call_abc123",
    "name": "order_agent",
    "content": "{\"success\": true, \"result\": \"订单1002：华为手机，已发货，预计明天到\"}"
  },
  {
    "role": "assistant",
    "content": "【反思结论-第0轮】success=true, needs_replanning=false. 反馈: 任务已完成"
  },
  
  // ── 本轮触发 ──
  {
    "role": "user",
    "content": "请基于以上历史记录，制定本轮的执行计划。"
  }
]
```

---

## 文件改动清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `app/memory/agent_run_memory.py` | `AgentMemoryMessage` + `AgentRunMemory` 完整实现 |

### 修改文件

| 文件 | 改动说明 |
|------|----------|
| [app/agents/langgraph_executor.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py) | ① [AgentState](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#36-75) 新增 `run_memory` 字段；② [execute()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1390-1487)/[execute_stream()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1599-1855) 初始化时创建 `AgentRunMemory`；③ 三个节点加入 write_xxx 写入调用；④ [_plan_node](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#349-510) / [_reflect_node](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#955-1102) 改为从 `run_memory` 读取 messages 而非临时组装 context 字典 |
| [app/agents/planning.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py) | [create_plan()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#98-203) 新增 `run_memory` 参数；[_build_planning_prompt()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#204-393) 拆分为 system_prompt + trigger_prompt；核心 `messages` 参数改由 `run_memory.build_messages_for_planning()` 生成 |
| [app/agents/reflection.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/reflection.py) | [reflect()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/reflection.py#85-182) 新增 `run_memory` 参数；`messages` 改由 `run_memory.build_messages_for_reflection()` 生成；去掉 `error_context` 文本拼接逻辑（已在 messages 中体现） |
| `app/memory/__init__.py` | 导出新模块 |

---

## 验证计划

### 自动化测试

```bash
# 运行现有全阶段集成测试（确保改造没有破坏现有能力）
cd /Users/yuye/YeahWork/AIAgent项目/ai-agent
poetry run pytest tests/integration/test_end_to_end_phase0_to_6.py -v

# 运行 phase0~5 基础测试
poetry run pytest tests/integration/test_end_to_end_phase0_to_5.py -v
```

### 日志人工观察项

改造完成后，启动服务并发起一次任务，在日志中应能看到：
1. `[记忆系统] 初始化 AgentRunMemory: task=...` — 确认记忆实例创建成功
2. `[记忆写入] write_plan iteration=0 steps=N` — 规划后写入成功
3. `[记忆写入] write_tool_call: tool=database_query success=True` — 工具调用后写入成功
4. `[记忆写入] write_reflection iteration=0` — 反思后写入成功
5. `[规划引擎] 从 run_memory 组装 messages, 共 X 条（含 Y 条历史记忆）` — 二轮规划时可以看到携带了历史

---

> [!IMPORTANT]
> **与 v1 方案的关键区别**：本方案不需要在 Prompt 里再维护任何"历史摘要文本"，所有历史行为都以规范的 OpenAI messages 格式传递，LLM 可以直接"看到"自己之前做了什么、工具返回了什么、用户怎么操作的，无需靠文字描述二次转述。
