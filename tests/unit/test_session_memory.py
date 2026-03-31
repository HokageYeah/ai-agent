"""
会话记忆测试
============

重点验证：
1. 会话摘要会保留跨轮可直接复用的精确标识，而不是只保留一句自然语言结论；
2. 相邻场景下，结构化工具结果也会被保留到下一轮，避免修复只对技能搜索案例生效。
"""

from app.memory.agent_run_memory import AgentRunMemory
from app.memory.session_memory import extract_summary_from_run_memory


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
