# [Fixing Agent UI Order and Executor Missing Tool Calls]

This plan addresses the two problems reported by the user:
1. The `send_message` input form appears before the UI visual indication (the step progress block) that the tool has started.
2. The `python_executor` tool is not planned when it needs to send an email, because the LLM includes a `final_answer` right after `send_message` and prematurely terminates the loop.

## Proposed Changes

### 1. Fix UI Order for Tools 

Currently, [app/agents/execution.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py) ([execute_plan](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#115-343)) only emits an [on_step_complete](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#791-896) callback *after* [_execute_step](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#707-776) finishes. For interactive tools like `send_message`, the tool execution blocks and sends the input form to the frontend immediately. Because there is no `on_step_start` callback, the input form appears before the backend has announced that the `send_message` tool just started.

#### [MODIFY] app/agents/execution.py
- Add `on_step_start` argument to [execute_plan](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#115-343) function.
- Invoke `await on_step_start(step, i, step_total)` right before calling [_execute_step(agent, step, context, step_results)](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#707-776).

#### [MODIFY] app/agents/langgraph_executor.py
- Inside [_execute_node](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/langgraph_executor.py#558-1124), create `_on_step_start` callback.
- Depending on the `action` type in the step, emit:
  - `TOOL_START` (tool_start)
  - `DELEGATE_START` (delegate_start)
  - `SKILL_START` (skill_start)
- Pass `_on_step_start` to [execute_plan](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#115-343).

### 2. Fix Missing python_executor Invocation

Currently, the [PlanningEngine](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#85-651) prompts dictate that "最后一步必须是 final_answer" (The final step MUST be `final_answer`). Because of this strict rule, the LLM always follows the `send_message` step with a `final_answer` step, completing the plan and terminating the LangGraph early without giving it a chance to write Python code in the next iteration.

#### [MODIFY] app/agents/planning.py
- Update [_build_system_prompt](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#254-318) and [_build_planning_prompt](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/planning.py#352-544) rules regarding `final_answer`.
- Modify the rule to specify an **exception**: "如果本轮计划的**核心目的**是调用 `send_message`（message_type='input' 或 'confirm'）等待用户后续输入或确认，那么本轮计划**禁止**包含 `final_answer`，只需规划 `send_message` 即可。系统会在用户回复后自动发起下一轮规划进行真实业务步骤（如 `python_executor`）。除此之外的常规情况，最后一步必须是 `final_answer`。"
- This allows the agent to intentionally pause the graph without terminating the main objective, and upon resumption, it can plan the `python_executor` properly.

## Verification Plan

### Automated Tests
- Run existing phase integration tests: [tests/integration/test_end_to_end_phase0_to_6.py](file:///Users/yuye/YeahWork/AIAgent%E9%A1%B9%E7%9B%AE/ai-agent/tests/integration/test_end_to_end_phase0_to_6.py) via `poetry run pytest` to ensure basic functionality remains intact.

### Manual Verification
1. Start the backend and frontend.
2. Input the exact prompt: "帮我查询订单号 1002 的详细情况，并把商品详情，发送到659672626@qq.com邮箱中".
3. Verify that the UI displays the `send_message` progress block indicator *first*, followed by the text input pop-up / form.
4. Provide the SMTP details and see if the Agent automatically resumes planning, successfully invokes the `python_executor`, and actually sends out the email.
