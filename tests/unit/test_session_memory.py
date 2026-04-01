"""
会话记忆测试
============

重点验证：
1. 会话摘要会保留跨轮可直接复用的精确标识，而不是只保留一句自然语言结论；
2. 相邻场景下，结构化工具结果也会被保留到下一轮，避免修复只对技能搜索案例生效。
"""

from app.memory.agent_run_memory import AgentRunMemory
from app.memory.session_memory import (
    AgentSessionMemory,
    TaskSummaryEntry,
    extract_summary_from_run_memory,
    rank_history_answer_candidates,
    select_relevant_conversation_history,
)


def _make_summary_entry(
    *,
    task: str,
    summary: str,
    key_data: dict | None = None,
    user_actions: list[dict] | None = None,
    tools_used: list[str] | None = None,
    conversation_turn_id: str = "",
    source_user_task: str = "",
    entry_scope: str = "primary",
) -> TaskSummaryEntry:
    """构造用于会话记忆筛选测试的摘要条目。"""
    return TaskSummaryEntry(
        task_id=f"task-{task}",
        agent_id="general_agent",
        agent_name="通用助手",
        task=task,
        success=True,
        summary=summary,
        key_data=key_data or {},
        tools_used=tools_used or ["find-skills"],
        iterations=1,
        started_at=0.0,
        ended_at=1.0,
        conversation_turn_id=conversation_turn_id,
        source_user_task=source_user_task or task,
        entry_scope=entry_scope,
        user_actions=user_actions or [],
    )


def test_extract_summary_from_run_memory_should_preserve_actionable_skill_refs():
    """技能搜索结果中的完整安装引用与标签映射应写入会话记忆。"""
    run_memory = AgentRunMemory(
        task="使用find-skills工具查询 新闻的技能",
        agent_id="general_agent",
        agent_name="通用助手",
    )
    run_memory.write_skill_call(
        iteration=0,
        skill_id="find-skills",
        skill_result="搜索成功",
        success=True,
    )
    run_memory.write_reflection(
        iteration=0,
        result={
            "success": True,
            "needs_replanning": False,
            "summary": "使用 find-skills 工具成功查询到新闻相关技能",
            "feedback": "工具返回了完整技能列表与推荐项",
        },
    )

    final_result = {
        "success": True,
        "result": (
            "根据搜索关键词“新闻”和“news”，为你找到相关技能。\n"
            "- **AI/科技领域新闻**：推荐 **yyh211/claude-meta-skill@daily-ai-news**（1.6K installs）。\n"
            "- 如需安装，可使用 `npx skills add yyh211/claude-meta-skill@daily-ai-news`。"
        ),
        "step_results": [
            {
                "action": "skill",
                "skill_id": "find-skills",
                "success": True,
                "result": (
                    "候选技能：\n"
                    "4. yyh211/claude-meta-skill@daily-ai-news\n"
                    "   - 安装命令：npx skills add yyh211/claude-meta-skill@daily-ai-news\n"
                    "建议：若关注AI领域新闻，可选择 **yyh211/claude-meta-skill@daily-ai-news**（1.6K installs）。"
                ),
            }
        ],
    }

    entry = extract_summary_from_run_memory(run_memory=run_memory, final_result=final_result)

    actionable_facts = entry.key_data.get("actionable_facts") or []
    assert any(
        fact.get("kind") == "package_ref"
        and fact.get("value") == "yyh211/claude-meta-skill@daily-ai-news"
        for fact in actionable_facts
    )
    assert any(
        fact.get("kind") == "command"
        and fact.get("value") == "npx skills add yyh211/claude-meta-skill@daily-ai-news"
        for fact in actionable_facts
    )
    assert any(
        fact.get("label") == "AI/科技领域新闻"
        and fact.get("value") == "yyh211/claude-meta-skill@daily-ai-news"
        for fact in actionable_facts
    )

    context_message = entry.to_context_message()["content"]
    assert "AI/科技领域新闻 -> yyh211/claude-meta-skill@daily-ai-news" in context_message
    assert "npx skills add yyh211/claude-meta-skill@daily-ai-news" in context_message
    assert entry.capability_trace["skills_used"] == ["find-skills"]


def test_extract_summary_from_run_memory_should_preserve_nested_delegate_capability_trace():
    """父 Agent 摘要应能保留子 Agent 内部真实使用的技能/工具轨迹。"""
    run_memory = AgentRunMemory(
        task="使用find-skills技能查询 新闻技能",
        agent_id="cs_master",
        agent_name="客服总监",
    )
    run_memory.write_delegate(
        iteration=0,
        child_agent_id="general_agent",
        sub_task="使用find-skills技能查询 新闻技能",
        result_summary="子 Agent 已完成技能查询",
        success=True,
    )
    run_memory.write_reflection(
        iteration=0,
        result={
            "success": True,
            "needs_replanning": False,
            "summary": "已通过通用助手完成新闻技能查询",
            "feedback": "后续同类续问可沿用这条委派链路",
        },
    )

    final_result = {
        "success": True,
        "result": "已查到新闻相关技能。",
        "step_results": [
            {
                "action": "delegate",
                "agent_id": "general_agent",
                "success": True,
                "result": {
                    "success": True,
                    "result": "已查到新闻相关技能。",
                    "step_results": [
                        {
                            "action": "skill",
                            "skill_id": "find-skills",
                            "success": True,
                            "result": {
                                "success": True,
                                "step_results": [
                                    {
                                        "action": "tool",
                                        "tool_name": "shell_exec",
                                        "success": True,
                                        "result": "npx --yes skills find 新闻",
                                    }
                                ],
                            },
                        }
                    ],
                },
            }
        ],
    }

    entry = extract_summary_from_run_memory(run_memory=run_memory, final_result=final_result)

    assert entry.capability_trace["delegated_agents"] == ["general_agent"]
    assert entry.capability_trace["skills_used"] == ["find-skills"]
    assert entry.capability_trace["tools_used"] == ["shell_exec"]


def test_extract_summary_from_run_memory_should_keep_structured_step_results():
    """相邻场景下，结构化工具结果应保留为步骤摘要，供下一轮直接复用。"""
    run_memory = AgentRunMemory(
        task="查询订单 1002 的状态",
        agent_id="order_agent",
        agent_name="订单助手",
    )
    run_memory.write_tool_call(
        iteration=0,
        tool_name="database_query",
        tool_args={"sql": "SELECT * FROM orders WHERE order_id='1002'"},
        tool_result={"order_id": "1002", "status": "shipped", "eta": "明天"},
        success=True,
    )
    run_memory.write_reflection(
        iteration=0,
        result={
            "success": True,
            "needs_replanning": False,
            "summary": "成功查询到订单 1002 的物流状态",
            "feedback": "结果完整，可以直接回复用户",
        },
    )

    final_result = {
        "success": True,
        "result": "订单 1002 已发货，预计明天送达。",
        "step_results": [
            {
                "action": "tool",
                "tool_name": "database_query",
                "success": True,
                "result": {"order_id": "1002", "status": "shipped", "eta": "明天"},
            }
        ],
    }

    entry = extract_summary_from_run_memory(run_memory=run_memory, final_result=final_result)

    structured_result = entry.key_data.get("structured_result")
    assert structured_result
    assert structured_result[0]["name"] == "database_query"
    assert structured_result[0]["result"]["order_id"] == "1002"

    step_results_summary = entry.key_data.get("step_results_summary") or []
    assert step_results_summary
    assert step_results_summary[0]["name"] == "database_query"
    assert "1002" in step_results_summary[0]["result_preview"]


def test_build_relevant_context_messages_should_select_topic_matched_summary():
    """会话级摘要应优先选择与当前任务同主题的历史条目。"""
    session_memory = AgentSessionMemory("conv-topic")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能，最高安装量是 news-summary(405次)",
            key_data={
                "actionable_facts": [
                    {"kind": "package_ref", "label": "新闻技能", "value": "zjfls/zhoujie-claude-skills@news-summary"}
                ]
            },
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="继续查找查询 浏览器相关技能",
            summary="已查到浏览器相关技能，最高安装量是 agent-browser(142.8K)",
            key_data={
                "actionable_facts": [
                    {"kind": "package_ref", "label": "浏览器技能", "value": "vercel-labs/agent-browser@agent-browser"}
                ]
            },
        )
    )

    messages = session_memory.build_relevant_context_messages(
        task="新闻相关技能中 下载安装量最高的是哪个",
        max_entries=1,
    )

    assert len(messages) == 1
    assert "新闻技能" in messages[0]["content"]
    assert "浏览器技能" not in messages[0]["content"]


def test_build_relevant_context_messages_should_prefer_recent_entries_for_follow_up_task():
    """显式续问场景下，应优先保留最近一轮相关摘要。"""
    session_memory = AgentSessionMemory("conv-followup")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="继续查找查询 浏览器相关技能",
            summary="已查到浏览器相关技能，最高安装量是 agent-browser(142.8K)",
        )
    )

    messages = session_memory.build_relevant_context_messages(
        task="刚才那个里下载安装量最高的是哪个",
        max_entries=1,
    )

    assert len(messages) == 1
    assert "浏览器相关技能" in messages[0]["content"]


def test_build_relevant_context_messages_should_not_match_only_on_same_skill_carrier():
    """同一个技能载体但不同主题时，不应仅因命中 skill_id 就注入旧摘要。"""
    session_memory = AgentSessionMemory("conv-same-skill-diff-topic")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
        )
    )

    messages = session_memory.build_relevant_context_messages(
        task="使用find-skills技能查询 mcp技能",
        max_entries=4,
    )

    assert messages == []


def test_build_relevant_context_messages_should_not_match_only_on_same_tool_carrier_in_adjacent_scene():
    """相邻场景中，同一个工具载体但不同实体时，也不应误复用旧摘要。"""
    session_memory = AgentSessionMemory("conv-same-tool-diff-entity")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用database_query工具查询 1001 订单",
            summary="已查到订单 1001 的状态为已发货",
            key_data={
                "structured_result": [
                    {
                        "action": "tool",
                        "name": "database_query",
                        "result": {"order_id": "1001", "status": "shipped"},
                    }
                ]
            },
            tools_used=["database_query"],
        )
    )

    messages = session_memory.build_relevant_context_messages(
        task="使用database_query工具查询 1002 订单",
        max_entries=4,
    )

    assert messages == []


def test_build_relevant_context_messages_should_drop_older_irrelevant_summary_when_follow_up_has_explicit_topic():
    """续问里如果已经出现明确主题词，不应再把旧主题摘要仅因“最近性”混入。"""
    session_memory = AgentSessionMemory("conv-followup-topic")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="继续查找查询 浏览器相关技能",
            summary="已查到浏览器相关技能，最高安装量是 agent-browser(142.8K)",
        )
    )

    messages = session_memory.build_relevant_context_messages(
        task="继续，告诉我刚才那个浏览器相关技能里安装量最高的是哪个",
        max_entries=4,
    )

    assert len(messages) == 1
    assert "浏览器相关技能" in messages[0]["content"]
    assert "新闻相关技能" not in messages[0]["content"]


def test_build_relevant_context_messages_should_match_repeated_order_question_with_embedded_numeric_entity():
    """同题重复问且实体编号与中文相连时，仍应命中历史摘要。"""
    session_memory = AgentSessionMemory("conv-repeat-order-question")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="订单1002的商品是谁买的",
            summary="成功查询到订单1002的商品购买者是李娜",
            key_data={
                "result_preview": "订单1002的商品是由李娜购买的。",
                "structured_result": [
                    {
                        "action": "tool",
                        "name": "database_query",
                        "result": {"order_id": "1002", "buyer_name": "李娜"},
                    }
                ],
            },
            tools_used=["database_query"],
        )
    )

    messages = session_memory.build_relevant_context_messages(
        task="订单1002的商品是谁买的",
        max_entries=1,
    )

    assert len(messages) == 1
    assert "李娜" in messages[0]["content"]
    assert "1002" in messages[0]["content"]


def test_rank_history_answer_candidates_should_extract_repeat_question_candidate():
    """历史摘要应能提炼出可供规划层复用的答案候选。"""
    entry = _make_summary_entry(
        task="订单1002的商品是谁买的",
        summary="成功查询到订单1002的商品购买者是李娜",
        key_data={
            "result_preview": "订单1002的商品是由李娜购买的。",
            "structured_result": [
                {
                    "action": "tool",
                    "name": "database_query",
                    "result": {"order_id": "1002", "buyer_name": "李娜"},
                }
            ],
        },
        tools_used=["database_query"],
    )

    candidates = rank_history_answer_candidates(
        task="订单1002的商品是谁买的",
        context_messages=[entry.to_context_message()],
    )

    assert len(candidates) == 1
    assert candidates[0]["exact_task_match"] is True
    assert candidates[0]["answer_preview"] == "订单1002的商品是由李娜购买的。"
    assert "命中相同任务" in candidates[0]["reasons"]


def test_build_conversation_recall_context_messages_should_group_primary_and_subtask_by_same_turn():
    """回顾类任务应看到按用户轮次聚合后的主线，而不是零散的主/子 Agent 摘要。"""
    session_memory = AgentSessionMemory("conv-recall")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
            conversation_turn_id="turn-1",
            source_user_task="使用find-skills技能查询 新闻技能",
            entry_scope="primary",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="查询关键词“新闻”对应的技能结果，并整理安装量",
            summary="子任务执行成功，已筛出 news-summary 等候选",
            tools_used=["shell_exec"],
            conversation_turn_id="turn-1",
            source_user_task="使用find-skills技能查询 新闻技能",
            entry_scope="subtask",
        )
    )
    session_memory._entries[1].capability_trace = {
        "delegated_agents": ["general_agent"],
        "skills_used": ["find-skills"],
        "tools_used": ["shell_exec"],
    }

    messages = session_memory.build_conversation_recall_context_messages(
        task="我的第一个问题是什么",
    )

    assert len(messages) == 1
    content = messages[0]["content"]
    assert "【会话主线回顾】" in content
    assert "1. 用户问题: 使用find-skills技能查询 新闻技能" in content
    assert "相关子任务: 查询关键词“新闻”对应的技能结果，并整理安装量" in content
    assert "技能=find-skills" in content


def test_build_conversation_recall_context_messages_should_support_generic_nth_question_lookup():
    """历史追问应支持通用的“第 N 个问题”定位，而不是只识别第一个问题。"""
    session_memory = AgentSessionMemory("conv-recall-nth")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
            conversation_turn_id="turn-1",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="订单1002的商品详情，并且找到订单客户",
            summary="已查到订单1002的商品与客户信息",
            conversation_turn_id="turn-2",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="继续查询 mcp技能",
            summary="已查到 mcp 相关技能",
            conversation_turn_id="turn-3",
        )
    )

    messages = session_memory.build_conversation_recall_context_messages(
        task="我的第三个问题是什么",
    )

    assert len(messages) == 1
    content = messages[0]["content"]
    assert "【会话主线回顾】" in content
    assert "当前定位问题: 第3个问题 -> 继续查询 mcp技能" in content
    assert "当前定位轮次数据:" in content


def test_rank_history_answer_candidates_should_parse_target_turn_from_conversation_recall_context():
    """会话主线回顾里的目标轮次也应进入统一历史候选，供规划层直接复用。"""
    session_memory = AgentSessionMemory("conv-recall-candidate")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
            conversation_turn_id="turn-1",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="继续查询 mcp技能",
            summary="已查到 mcp 相关技能",
            conversation_turn_id="turn-2",
        )
    )

    context_messages = session_memory.build_conversation_recall_context_messages(
        task="我的第二个问题是什么",
    )
    candidates = rank_history_answer_candidates(
        task="我的第二个问题是什么",
        context_messages=context_messages,
    )

    assert len(candidates) == 1
    assert candidates[0]["candidate_kind"] == "conversation_recall_target"
    assert candidates[0]["answer_preview"] == "继续查询 mcp技能"
    assert candidates[0]["target_label"] == "第2个问题"
    assert "命中会话主线中的目标轮次" in candidates[0]["reasons"]


def test_build_conversation_recall_context_messages_should_support_multi_target_question_lookup():
    """会话主线回顾应支持一次定位多个轮次目标，而不是只保留最后一个。"""
    session_memory = AgentSessionMemory("conv-recall-multi")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
            conversation_turn_id="turn-1",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="订单1002的商品详情，并且找到订单客户",
            summary="已查到订单1002的商品与客户信息",
            conversation_turn_id="turn-2",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="继续查询 mcp技能",
            summary="已查到 mcp 相关技能",
            conversation_turn_id="turn-3",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="订单1002的商品是谁买的",
            summary="已查到订单1002的购买者",
            conversation_turn_id="turn-4",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="我的第一个问题是什么",
            summary="已回答首个问题",
            conversation_turn_id="turn-5",
        )
    )

    messages = session_memory.build_conversation_recall_context_messages(
        task="第四、第五个问题分别是什么",
    )

    assert len(messages) == 1
    content = messages[0]["content"]
    assert "当前定位问题: 第4个问题 -> 订单1002的商品是谁买的" in content
    assert "当前定位问题: 第5个问题 -> 我的第一个问题是什么" in content
    assert "当前定位轮次数据列表:" in content


def test_rank_history_answer_candidates_should_keep_multi_target_recall_candidates():
    """多目标会话回顾应生成与目标数一致的历史候选，供覆盖度校验使用。"""
    session_memory = AgentSessionMemory("conv-recall-multi-candidate")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
            conversation_turn_id="turn-1",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="订单1002的商品详情，并且找到订单客户",
            summary="已查到订单1002的商品与客户信息",
            conversation_turn_id="turn-2",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="继续查询 mcp技能",
            summary="已查到 mcp 相关技能",
            conversation_turn_id="turn-3",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="订单1002的商品是谁买的",
            summary="已查到订单1002的购买者",
            conversation_turn_id="turn-4",
        )
    )
    session_memory.append_task_summary(
        _make_summary_entry(
            task="我的第一个问题是什么",
            summary="已回答首个问题",
            conversation_turn_id="turn-5",
        )
    )

    context_messages = session_memory.build_conversation_recall_context_messages(
        task="第四、第五个问题分别是什么",
    )
    candidates = rank_history_answer_candidates(
        task="第四、第五个问题分别是什么",
        context_messages=context_messages,
        max_candidates=4,
    )

    assert len(candidates) == 2
    assert {candidate["target_label"] for candidate in candidates} == {"第4个问题", "第5个问题"}
    assert all(candidate["target_count"] == 2 for candidate in candidates)


def test_build_follow_up_capability_context_messages_should_reuse_recent_successful_skill_trace():
    """换主题续问时，应保留最近成功的能力链路，但不把旧主题摘要混入。"""
    session_memory = AgentSessionMemory("conv-followup-capability")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
        )
    )
    session_memory._entries[0].capability_trace = {
        "delegated_agents": ["general_agent"],
        "skills_used": ["find-skills"],
        "tools_used": ["shell_exec"],
    }

    messages = session_memory.build_follow_up_capability_context_messages(
        task="继续查询 mcp技能",
    )

    assert len(messages) == 1
    assert "general_agent" in messages[0]["content"]
    assert "find-skills" in messages[0]["content"]
    assert "新闻相关技能" in messages[0]["content"]


def test_build_follow_up_capability_context_messages_should_prefer_same_domain_and_skip_failed_latest_entry():
    """显式续问应优先选择同能力域的最近成功轨迹，而不是最近一次失败或无关链路。"""
    session_memory = AgentSessionMemory("conv-followup-domain")
    session_memory.append_task_summary(
        _make_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
            tools_used=["find-skills"],
        )
    )
    session_memory._entries[0].capability_trace = {
        "delegated_agents": ["general_agent"],
        "skills_used": ["find-skills"],
        "tools_used": ["shell_exec"],
    }

    session_memory.append_task_summary(
        TaskSummaryEntry(
            task_id="task-order",
            agent_id="order_agent",
            agent_name="订单助手",
            task="查询订单 1002 的状态",
            success=True,
            summary="已查到订单 1002 的物流状态",
            key_data={},
            tools_used=["database_query"],
            iterations=1,
            started_at=0.0,
            ended_at=1.0,
            capability_trace={
                "delegated_agents": ["order_agent"],
                "tools_used": ["database_query"],
            },
        )
    )

    session_memory.append_task_summary(
        TaskSummaryEntry(
            task_id="task-failed",
            agent_id="cs_master",
            agent_name="客服总监",
            task="继续查询 mcp技能",
            success=False,
            summary="由于工具受限未能完成",
            key_data={},
            tools_used=[],
            iterations=1,
            started_at=0.0,
            ended_at=1.0,
            capability_trace={},
        )
    )

    messages = session_memory.build_follow_up_capability_context_messages(
        task="继续查找查询 浏览器相关技能",
    )

    assert len(messages) == 1
    assert "find-skills" in messages[0]["content"]
    assert "database_query" not in messages[0]["content"]


def test_select_relevant_conversation_history_should_keep_recent_follow_up_and_trim_long_message():
    """外部 conversation_history 应按续问相关性保留最近消息，并对超长内容做裁剪。"""
    conversation_history = [
        {"role": "user", "content": "第一轮：查新闻技能"},
        {"role": "assistant", "content": "无关铺垫" * 400},
        {"role": "user", "content": "第二轮：查浏览器技能"},
        {"role": "assistant", "content": "浏览器技能结果：" + "agent-browser 很热门。 " * 200},
    ]

    selected = select_relevant_conversation_history(
        task="继续，告诉我刚才那个里安装量最高的是哪个",
        conversation_history=conversation_history,
        max_messages=2,
        recent_window=2,
    )

    assert len(selected) == 2
    assert "第二轮：查浏览器技能" in selected[0]["content"]
    assert "中间内容仅因控制提示词长度而省略" in selected[1]["content"]


def test_select_relevant_conversation_history_should_not_match_only_on_same_skill_carrier():
    """外部对话历史中，若只命中同一个技能载体而未命中主题，也不应被注入。"""
    conversation_history = [
        {"role": "user", "content": "请使用find-skills技能查询 新闻技能"},
        {"role": "assistant", "content": "我已经用 find-skills 查到了新闻相关技能。"},
    ]

    selected = select_relevant_conversation_history(
        task="使用find-skills技能查询 mcp技能",
        conversation_history=conversation_history,
        max_messages=4,
        recent_window=4,
    )

    assert selected == []


def test_select_relevant_conversation_history_should_prefer_explicit_topic_match_over_blind_recent_window():
    """续问里若已出现明确主题词，应优先保留命中主题的问答对，而不是整段最近窗口。"""
    conversation_history = [
        {"role": "user", "content": "第一轮：查新闻技能"},
        {"role": "assistant", "content": "新闻技能结果：news-summary 很热门。"},
        {"role": "user", "content": "第二轮：查浏览器技能"},
        {"role": "assistant", "content": "浏览器技能结果：" + "agent-browser 很热门。 " * 200},
    ]

    selected = select_relevant_conversation_history(
        task="继续，告诉我刚才那个浏览器相关技能里安装量最高的是哪个",
        conversation_history=conversation_history,
        max_messages=4,
        recent_window=4,
    )

    assert len(selected) == 2
    assert "第二轮：查浏览器技能" in selected[0]["content"]
    assert "浏览器技能结果：" in selected[1]["content"]
    assert all("新闻技能" not in item["content"] for item in selected)
