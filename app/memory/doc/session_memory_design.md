# 会话级任务摘要记忆（AgentSessionMemory）设计方案

## 背景与定位

| 层级       | 类名                 | 生命周期               | 内容粒度                                       | 状态       |
| ---------- | -------------------- | ---------------------- | ---------------------------------------------- | ---------- |
| 任务运行级 | [AgentRunMemory](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/memory/agent_run_memory.py#99-646)     | 单次 [execute()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1486-1589) 调用  | 每一轮的计划/工具调用/反思的完整 messages      | ✅ 已实现   |
| **会话级** | `AgentSessionMemory` | 跨越同一会话内多次任务 | 每次任务完成后的压缩摘要（任务结论、关键数据） | 🚧 本次设计 |

**核心问题**：同一用户在一次会话中连续问多个问题，第二个任务（新的 [execute()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1486-1589) 调用）完全不知道第一个任务的结果是什么，导致：
- Agent 重复调用工具查询已知数据
- 无法利用前序任务的上下文（如已查到的订单号、用户信息）
- 用户体验割裂

**解决思路**：每次任务完成后，从 [AgentRunMemory](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/memory/agent_run_memory.py#99-646) 中提取一条**压缩摘要**，追加到该会话的 `AgentSessionMemory` 中；下一次任务启动时，把会话级摘要作为 [conversation_history](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/services/chat_service.py#232-246) 的一部分注入 `AgentState.messages`。

---

## 架构调用流程

```
第1次任务调用（execute_stream）
  ├─ 初始化 AgentRunMemory
  ├─ Plan → Execute → Reflect × N轮
  └─ 任务完成 → 提取摘要 → 写入 AgentSessionMemory
                                    ↓
第2次任务调用（execute_stream）
  ├─ 从 AgentSessionMemory 读取摘要
  ├─ 注入到 initial_state["messages"]（作为会话历史前置）
  ├─ 初始化新的 AgentRunMemory
  └─ Plan（此时 LLM 能感知"上一个任务做了什么"）
```

---

## 数据结构设计

### `TaskSummaryEntry`（单次任务摘要条目）

```python
@dataclass
class TaskSummaryEntry:
    """
    一次 Agent 任务执行的压缩摘要条目。

    为什么压缩而不全量保存 AgentRunMemory：
      - AgentRunMemory 含有大量细节（每条工具调用、每轮规划）
      - 跨任务注入时 token 消耗太高
      - 只有「任务结论 + 关键数据 + 用户行为」对下一个任务有价值
    """
    task_id: str                    # 任务唯一 ID（uuid4，用于去重）
    agent_id: str                   # 执行的 Agent ID
    agent_name: str                 # Agent 显示名
    task: str                       # 原始任务描述
    source_user_task: str           # 当前轮原始用户问题（主/子 Agent 统一挂回这条主线）
    success: bool                   # 任务是否成功
    summary: str                    # LLM / 规则提取的结论摘要（≤300字）
    key_data: dict                  # 关键结构化数据（如查到的 order_id、price）
    tools_used: list[str]           # 本次使用的工具列表
    iterations: int                 # 经过了几轮 Plan-Execute-Reflect
    started_at: float               # 开始时间戳
    ended_at: float                 # 结束时间戳
    conversation_turn_id: str       # 会话轮次 ID，同一轮主/子 Agent 共享
    entry_scope: str                # 记录属于主线任务(primary)还是子任务(subtask)
    # NOTE: 记录本次任务中用户的所有操作行为（如确认/拒绝某个工具操作）
    # 这些行为能让下一个任务感知"用户的偏好或限制"
    # 例如：用户拒绝了 file_write → 下次规划时主动避开
    user_actions: list[dict]        # 格式: [{"action": "reject", "tool": "file_write", "iteration": 0}]

    def to_context_message(self) -> dict:
        """
        转换为注入 LLM 的 messages 格式（user 角色）。

        为什么用 user 角色：
          这条摘要是「历史上下文」，从 Agent 视角来看等同于
          用户在新任务之前告知的背景信息，语义上最匹配 user 角色。
        """
        status = "✅ 成功" if self.success else "❌ 失败"
        lines = [
            f"【历史任务摘要】",
            f"任务: {self.task}",
            f"主线任务: {self.source_user_task}",
            f"结果: {status}",
            f"结论: {self.summary}",
        ]
        
        if self.key_data:
            lines.append(f"关键数据: {self.key_data}")
            
        if self.tools_used:
            lines.append(f"使用工具: {', '.join(self.tools_used)}")
            
        if self.user_actions:
            # NOTE: 用户行为是最重要的限制信息之一，优先展示给 LLM
            # 让下一个任务在规划时就能感知「这个用户拒绝过哪些操作」
            action_desc = []
            for act in self.user_actions:
                tool = act.get("tool", "")
                action = act.get("action", "")
                if action == "reject":
                    action_desc.append(f"拒绝了 [{tool}] 操作")
                elif action == "confirm":
                    action_desc.append(f"确认了 [{tool}] 操作")
            if action_desc:
                lines.append(f"用户操作行为: {'; '.join(action_desc)}")
                
        lines.append(f"执行轮次: {self.iterations} 轮")
        
        return {"role": "user", "content": "\n".join(lines)}
```

### `AgentSessionMemory`（会话级摘要仓库）

```python
class AgentSessionMemory:
    """
    跨任务的会话级摘要记忆仓库。

    生命周期：与 conversation_id 绑定，跨越多次 execute() 调用。
    存储位置：进程内字典（原型阶段），key = conversation_id。

    TODO（扩展阶段）：可替换为 Redis 或 SQLite 实现持久化。
    """
    def __init__(self, conversation_id: str, max_entries: int = 10):
        ...

    # 写入（任务完成后调用）
    def append_task_summary(self, entry: TaskSummaryEntry) -> None: ...

    # 读取（新任务开始前调用）
    def build_context_messages(self) -> list[dict]:
        """
        返回注入 initial_state["messages"] 的历史摘要消息列表。

        结构示例：
          [
            {"role": "user", "content": "【历史任务摘要 #1】任务：查询订单1002\n结论：已发货，预计明天到\n关键数据：{\"order_id\":\"1002\", \"status\":\"shipped\"}"},
            {"role": "user", "content": "【历史任务摘要 #2】..."},
          ]
        """

    # 调试
    def get_summary_list(self) -> list[dict]: ...
```

---

## 核心流程——摘要的生成方式

**选项A（本次采用，不增加 LLM 开销）**：规则提取  
从 [AgentRunMemory](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/memory/agent_run_memory.py#99-646) 的最后一条 [reflection](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/memory/agent_run_memory.py#388-431) 条目 + `final_result` 中直接提取摘要文字和键值数据，无需额外 LLM 调用。

```python
def extract_summary_from_run_memory(run_memory: AgentRunMemory) -> TaskSummaryEntry:
    """
    从 AgentRunMemory 规则化提取任务摘要。

    提取内容：
      - 最后一条 reflection 的 summary 字段 → 作为 summary 文字
      - final_result 中的结构化数据 → 作为 key_data
      - final_result / step_results 中可直接复用的“精确标识”
        （如 owner/repo@skill、安装命令、URL、订单号、资源 ID）→ 作为 actionable facts
      - 历史 messages 中 tool_result 类型的 tool_name 列表 → tools_used
      - 最大 iteration 值 → iterations
    """
```

### 关键补充：会话记忆不能只保留“自然语言结论”

如果上一轮任务已经产出了下一轮可直接执行的精确标识，例如：

- `owner/repo@skill`
- `npx skills add ...`
- URL
- 订单号 / 资源 ID / 文件路径

则这些标识必须进入 `key_data`，并在 `to_context_message()` 中以可直接复用的形式呈现给 LLM。

否则下一轮只能知道“之前查过/做过”，却不知道“具体该用哪个精确引用”，容易触发：

- 再次重复搜索；
- 重新枚举候选；
- 根据模糊别名猜测错误目标；
- 在安装/下载/访问类任务中走到错误引用或错误 URL。

**选项B（后续可升级）**：LLM 二次总结  
调用 LLM 对 `run_memory.get_timeline()` 进行一次专项总结，获取更高质量的摘要。预留接口，本次不实现。

### 关键补充：需要同时保留“会话主线”和“子任务轨迹”

仅保存 `task + summary` 还不够，因为真实会话里通常同时存在：

- 主 Agent 面向用户的原始问题；
- 子 Agent 为完成该问题而生成的改写子任务；
- 同一轮里的技能/工具/委派链路。

因此每条 `TaskSummaryEntry` 还需要保留：

- `conversation_turn_id`：把同一轮主/子 Agent 摘要聚合到一起；
- `source_user_task`：无论子任务怎么改写，都能回到原始用户问题；
- `entry_scope`：区分这是主线任务还是子任务摘要。

当用户问“第一轮问了什么”“刚才做了什么”“前面聊到哪了”这类元历史问题时，
会话记忆公共层会按 `conversation_turn_id` 聚合出“会话主线回顾”，而不是把零散的子任务摘要直接丢给 LLM。

---

## 全局注册表（单例）

```python
# app/memory/session_memory.py

_session_registry: dict[str, AgentSessionMemory] = {}

def get_session_memory(conversation_id: str) -> AgentSessionMemory:
    """获取或创建指定会话的 AgentSessionMemory 实例（懒加载单例）"""
    if conversation_id not in _session_registry:
        _session_registry[conversation_id] = AgentSessionMemory(conversation_id)
    return _session_registry[conversation_id]

def clear_session_memory(conversation_id: str) -> None:
    """清空会话记忆（会话过期或用户主动清空时调用）"""
    _session_registry.pop(conversation_id, None)
```

---

## 文件改动清单

### 新增文件

#### [NEW] `app/memory/session_memory.py`
- `TaskSummaryEntry` 数据类
- `AgentSessionMemory` 仓库类
- `extract_summary_from_run_memory()` 规则提取函数
- `get_session_memory()` / `clear_session_memory()` 全局注册表

### 修改文件

#### [MODIFY] [app/memory/__init__.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/memory/__init__.py)
导出 `AgentSessionMemory`, `get_session_memory`, `TaskSummaryEntry`

---

#### [MODIFY] [app/agents/langgraph_executor.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py)

**改动1：[execute()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1486-1589) 和 [execute_stream()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1707-1970) 接收 `conversation_id` 参数**

```python
async def execute(
    self,
    agent: Agent,
    task: str,
    conversation_id: Optional[str] = None,   # ← 新增
    conversation_history: Optional[list] = None,
    ...
)
```

**改动2：读取会话摘要注入 `initial_state["messages"]`**
```python
# 从会话级记忆取出摘要，注入到 messages 前置（作为对话历史）
session_ctx_messages = []
if conversation_id:
    from app.memory.session_memory import get_session_memory
    session_mem = get_session_memory(conversation_id)
    session_ctx_messages = session_mem.build_context_messages()
    if session_ctx_messages:
        logger.info(f"[会话记忆] 注入 {len(session_ctx_messages)} 条历史任务摘要")

initial_state = {
    "messages": session_ctx_messages + (conversation_history or []),
    "run_memory": AgentRunMemory(task=task, ...),
    ...
}
```

**改动3：任务结束后写入摘要**
```python
# 在 execute() 的 finally 块（或任务完成回调）中
if conversation_id and state.get("run_memory"):
    from app.memory.session_memory import get_session_memory, extract_summary_from_run_memory
    entry = extract_summary_from_run_memory(
        run_memory=state["run_memory"],
        final_result=final_result
    )
    get_session_memory(conversation_id).append_task_summary(entry)
    logger.info(f"[会话记忆] 任务摘要已写入 conversation_id={conversation_id}")
```

---

#### [MODIFY] [app/api/endpoints/agents.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/api/endpoints/agents.py)
把请求中的 `conversation_id`（前端已有字段）透传给 [execute()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1486-1589) 和 [execute_stream()](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#1707-1970)。

#### [MODIFY] [app/schemas/agent_data.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/schemas/agent_data.py)
[AgentExecuteRequest](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/schemas/agent_data.py#49-60) 已有 [conversation_history](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/services/chat_service.py#232-246) 字段，补充 `conversation_id: Optional[str]`（如尚未有）。

---

## 注入后的 messages 结构示意

```
第2次任务：「帮我查询同一个用户的退款状态」

[0] {role: system,     content: "你是客服总监..."}
[1] {role: user,       content: "【历史任务摘要 #1】
                                  任务: 查询订单1002详情
                                  结论: 已发货，预计明天到
                                  关键数据: {order_id: 1002, status: shipped, user_id: U888}
                                  用时: 2轮规划，1次委派"}
[2] {role: user,       content: "帮我查询同一个用户的退款状态"}   ← 本次任务目标
[3] {role: user,       content: "请制定本轮的执行计划。"}           ← 触发指令
```

LLM 通过 [1] 直接获知"同一个用户"对应 `user_id=U888`，无需重新查询。

---

## 验证计划

### 自动化测试（Python 脚本）
```bash
# 快速冒烟测试（无需真实 LLM）
cd /Users/yuye/YeahWork/AIAgent项目/ai-agent
poetry run python -c "
from app.memory.session_memory import AgentSessionMemory, TaskSummaryEntry, get_session_memory
mem = get_session_memory('test-conv-001')
from dataclasses import asdict
import time
entry = TaskSummaryEntry(
    task_id='t1', agent_id='cs', agent_name='客服', task='查订单1002',
    success=True, summary='订单已发货', key_data={'order_id':'1002'},
    tools_used=['database_query'], iterations=1,
    started_at=time.time(), ended_at=time.time()
)
mem.append_task_summary(entry)
msgs = mem.build_context_messages()
print(f'摘要消息数: {len(msgs)}')
print(f'内容预览: {msgs[0][\"content\"][:100]}')
assert msgs[0]['role'] == 'user'
print('✅ session_memory 冒烟测试通过')
"
```

### 集成测试
```bash
# 现有集成测试（验证改动未破坏原有功能）
poetry run pytest tests/integration/test_end_to_end_phase0_to_5.py -v
```

### 人工验证（启动服务后）
1. 启动服务：`poetry run uvicorn app.main:app --reload`
2. 发起第1次任务，观察日志：`[会话记忆] 任务摘要已写入 conversation_id=xxx`
3. 用相同 `conversation_id` 发起第2次任务，观察日志：`[会话记忆] 注入 1 条历史任务摘要`
4. 查看规划引擎 messages 结构日志（黄色分隔线），确认第 [1] 条是历史摘要
