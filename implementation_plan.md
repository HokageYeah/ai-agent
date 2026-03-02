# Agent 迭代上下文传递优化 + 用户确认交互

## 问题背景

当 Agent 遇到超出能力范围的任务时，会启动重规划循环。**核心缺陷**：

1. **重规划 Prompt 无历史信息**：[_plan_node](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#331-439) 每轮调用 [create_plan](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#98-193) 时，传入的 Prompt 仅含原始任务和工具列表，**不含上一轮的反思结论（feedback/summary）**，导致 LLM 重复生成完全相同的计划。

2. **无能力边界感知**：当执行步骤均技术上"成功"（只是返回"我无法处理"），`error_context` 为空，下一轮规划引擎无任何有效上下文信息可用，形成无效迭代。

3. **缺少用户确认机制**：`file_write` 等具有副作用的操作在没有用户确认的情况下直接执行。

---

## Proposed Changes

### 后端核心逻辑层

---

#### [MODIFY] [planning.py](file:///Users/yuye/YeahWork/AI%20Agent%20项目/ai-agent/app/agents/planning.py)

- [create_plan()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#98-193) 增加参数 `reflection_history: Optional[List[Dict]] = None`
- [_build_planning_prompt()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#194-302) 增加参数 `reflection_history`
- 在 Prompt 末尾注入历史反思区块，引导 LLM 从历史中学习，若仍无法完成则明确告知用户

---

#### [MODIFY] [langgraph_executor.py](file:///Users/yuye/YeahWork/AI%20Agent%20项目/ai-agent/app/agents/langgraph_executor.py)

- [AgentState](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#36-62) 增加新字段：
  - `reflection_history: List[Dict]`：累积历次反思结论
  - `pending_confirmations: Dict[str, asyncio.Event]`：等待用户确认的事件字典
- [_reflect_node()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#704-813)：在完成反思后，将 `reflection_result.to_dict()` + `iteration` 追加到 `state["reflection_history"]`
- [_plan_node()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#331-439)：调用 [create_plan()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#98-193) 时传入 `reflection_history=state["reflection_history"]`
- [_execute_node()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#440-703)：执行 `file_write` 步骤**前**，推送 `user_confirm_required` 事件，挂起等待用户确认

---

#### [MODIFY] [agents.py](file:///Users/yuye/YeahWork/AI%20Agent%20项目/ai-agent/app/api/endpoints/agents.py)

- 增加接口：`POST /api/v1/agents/confirm/{confirm_id}`
  - 接收用户 confirm/reject 操作，触发挂起执行继续

---

### 前端交互层

#### [MODIFY] [AgentsView.vue](file:///Users/yuye/YeahWork/AI%20Agent%20项目/ai-agent/web/src/views/agents/AgentsView.vue)

- 新增事件类型 `user_confirm_required` 的渲染模板（含确认/取消按钮）
- 点击后调用后端 confirm 接口，并将按钮设为 disabled
- 新增事件类型 `user_confirm_result`：展示确认/拒绝结果

---

## Verification Plan

### 自动化测试

```bash
# 后端进入 ai-agent 目录
cd /Users/yuye/YeahWork/AI\ Agent\ 项目/ai-agent

# 规划引擎单元测试（验证 reflection_history 注入 Prompt）
poetry run pytest tests/unit/test_planning_engine.py -v

# LangGraph executor 单元测试
poetry run pytest tests/unit/test_langgraph_executor.py -v

# 端到端集成测试
poetry run pytest tests/integration/test_end_to_end_phase0_to_6.py -v
```

### 手动验证

**验证重规划上下文修复：**
1. 启动后端：`cd /Users/yuye/YeahWork/AI\ Agent\ 项目/ai-agent && poetry run uvicorn app.main:app --reload`
2. 在 Agent 页面选择 `通用助手`，输入：`查询订单号是1002的订单`
3. 期望迭代 2 的规划 Prompt 中包含"历史迭代反思记录"，最终明确拒绝而不是无限循环

**验证用户确认交互（file_write）：**
1. 同上启动
2. 选择 `通用助手`，输入：`把 "Hello World" 写入 /tmp/test.txt`
3. 期望执行轨迹出现确认卡片，点击确认后文件写入，点击取消后步骤失败继续

> [!NOTE]
> 后端 confirm 事件通过进程内 Dict 存储 `asyncio.Event`，适合单进程开发环境。
