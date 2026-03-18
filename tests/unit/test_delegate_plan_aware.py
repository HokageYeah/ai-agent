"""
测试：计划感知的委派需求完整性检查
=======================================

验证 _is_keyword_covered_by_remaining_steps 辅助方法
以及 _delegate_to_agent 中的 CAPABILITY_KEYWORDS 映射表逻辑。

测试场景覆盖：
1. 后续步骤通过 skill_id 覆盖关键词（如 text_writing 覆盖"保存到"）
2. 后续步骤通过 tool_name 覆盖关键词（如 file_write 覆盖"写入文件"）
3. 后续步骤通过 action 类型覆盖关键词（如 delegate 覆盖"保存到"）
4. 后续步骤通过参数文本包含关键词（兜底模糊匹配）
5. 后续步骤均未覆盖 → 需注入
6. remaining_steps 为空 → 需注入
7. 多关键词混合场景（部分覆盖、部分未覆盖）

作者: AI Agent Team
创建时间: 2026-03-18
"""

import pytest

from app.agents.planning import PlanStep
from app.agents.execution import ExecutionEngine
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry


# ── 测试固件：创建最小化的 ExecutionEngine 实例 ────────────────────────
@pytest.fixture
def engine():
    """
    创建一个最小化的 ExecutionEngine 实例，
    仅用于测试 _is_keyword_covered_by_remaining_steps 方法。
    不需要完整的 LLM/Tool/Skill 集成。
    """
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    return ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )


# ── 常用的 coverage_config 定义（与 execution.py 中 CAPABILITY_KEYWORDS 保持一致） ──
SAVE_FILE_CONFIG = {
    "tools": ["file_write", "file_manager"],
    "skills": ["text_writing"],
    "actions": ["delegate"]
}

FILE_WRITE_CONFIG = {
    "tools": ["file_write"],
    "skills": [],
    "actions": []
}


# =============================================================================
# 测试 _is_keyword_covered_by_remaining_steps
# =============================================================================

class TestIsKeywordCoveredByRemainingSteps:
    """测试 _is_keyword_covered_by_remaining_steps 辅助方法"""

    # ── 场景 1：后续步骤的 skill_id 匹配覆盖 ─────────────────────────
    def test_covered_by_skill_id(self, engine):
        """
        场景：delegate(查数据) → text_writing(写报告)
        "保存到" 关键词应被 text_writing skill 覆盖
        """
        remaining = [
            PlanStep(action="skill", skill_id="text_writing", params={"topic": "订单报告"}),
            PlanStep(action="final_answer", content="完成"),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="保存到",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=remaining
        )
        assert result is True, "text_writing skill 应覆盖'保存到'关键词"

    # ── 场景 2：后续步骤的 tool_name 匹配覆盖 ────────────────────────
    def test_covered_by_tool_name(self, engine):
        """
        场景：delegate(查数据) → file_write(保存文件)
        "写入文件" 关键词应被 file_write tool 覆盖
        """
        remaining = [
            PlanStep(action="tool", tool_name="file_write", params={"path": "/tmp/report.txt"}),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="写入文件",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=remaining
        )
        assert result is True, "file_write 工具应覆盖'写入文件'关键词"

    # ── 场景 3：后续步骤的 action 类型匹配覆盖 ───────────────────────
    def test_covered_by_action_type(self, engine):
        """
        场景：delegate(查数据) → delegate(写文件给 general_agent)
        "保存到" 关键词应被 delegate action 覆盖
        """
        remaining = [
            PlanStep(action="delegate", agent_id="general_agent", task="保存报告"),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="保存到",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=remaining
        )
        assert result is True, "delegate action 应覆盖'保存到'关键词"

    # ── 场景 4：后续步骤参数文本中包含关键词（兜底模糊匹配） ─────────
    def test_covered_by_keyword_in_params(self, engine):
        """
        场景：后续步骤的参数描述中包含关键词
        即使 action/tool/skill 不直接匹配，参数文本也能兜底
        """
        remaining = [
            PlanStep(action="skill", skill_id="some_other_skill",
                     description="使用技能保存到本地文件"),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="保存到",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=remaining
        )
        assert result is True, "参数文本中包含关键词时应视为已覆盖"

    # ── 场景 5：后续步骤均未覆盖 → 应返回 False ──────────────────────
    def test_not_covered_when_no_matching_steps(self, engine):
        """
        场景：后续步骤中没有能覆盖该关键词的工具/技能/action
        """
        remaining = [
            PlanStep(action="tool", tool_name="search_tool", params={"query": "天气"}),
            PlanStep(action="final_answer", content="完成"),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="保存到",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=remaining
        )
        assert result is False, "无匹配步骤时不应视为已覆盖"

    # ── 场景 6：remaining_steps 为空列表 → 应返回 False ──────────────
    def test_not_covered_when_empty_remaining(self, engine):
        """
        场景：这是最后一步（没有后续步骤），应返回 False
        """
        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="保存到",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=[]
        )
        assert result is False, "空 remaining_steps 不应视为已覆盖"

    # ── 场景 7：file_write 专用配置（只匹配工具，不匹配技能/action）──
    def test_file_write_config_only_matches_tool(self, engine):
        """
        场景：FILE_WRITE_CONFIG 只有 tools=["file_write"]，
        后续步骤是 text_writing 技能，不应匹配
        """
        remaining = [
            PlanStep(action="skill", skill_id="text_writing", params={"topic": "报告"}),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="file_write",
            coverage_config=FILE_WRITE_CONFIG,
            remaining_steps=remaining
        )
        assert result is False, "FILE_WRITE_CONFIG 不包含 text_writing 技能，不应覆盖"

    # ── 场景 8：多步骤中后面的步骤匹配 ───────────────────────────────
    def test_covered_by_later_step_in_sequence(self, engine):
        """
        场景：第2步不匹配，但第3步匹配
        验证方法会扫描所有后续步骤而非仅第一个
        """
        remaining = [
            PlanStep(action="tool", tool_name="search", params={"q": "数据"}),
            PlanStep(action="tool", tool_name="analysis", params={"data": "结果"}),
            PlanStep(action="skill", skill_id="text_writing", params={"topic": "最终报告"}),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="保存文件",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=remaining
        )
        assert result is True, "后续第3步的 text_writing 应能覆盖'保存文件'"

    # ── 场景 9：final_answer 步骤不应覆盖任何关键词 ────────────────────
    def test_final_answer_does_not_cover(self, engine):
        """
        场景：后续只有 final_answer，不应被视为覆盖
        """
        remaining = [
            PlanStep(action="final_answer", content="生成最终答案"),
        ]

        result = engine._is_keyword_covered_by_remaining_steps(
            keyword="保存到",
            coverage_config=SAVE_FILE_CONFIG,
            remaining_steps=remaining
        )
        assert result is False, "final_answer 不是 delegate，不应覆盖'保存到'"


# =============================================================================
# 测试：多关键词混合场景（模拟 _delegate_to_agent 中的完整检查逻辑）
# =============================================================================

class TestMultiKeywordScenarios:
    """测试多关键词同时检查的场景"""

    def test_partial_coverage(self, engine):
        """
        场景：用户需求包含"保存到"和某个自定义关键词，
        后续步骤只覆盖了"保存到"但未覆盖另一个
        """
        remaining = [
            PlanStep(action="skill", skill_id="text_writing", params={"topic": "报告"}),
        ]

        # "保存到" 能被 text_writing 覆盖
        assert engine._is_keyword_covered_by_remaining_steps(
            "保存到", SAVE_FILE_CONFIG, remaining
        ) is True

        # "写入文件" 也能被 text_writing 覆盖（因为 skills 中有 text_writing）
        assert engine._is_keyword_covered_by_remaining_steps(
            "写入文件", SAVE_FILE_CONFIG, remaining
        ) is True

    def test_all_uncovered(self, engine):
        """
        场景：后续步骤完全不相关，所有关键词均未覆盖
        """
        remaining = [
            PlanStep(action="tool", tool_name="calculator", params={"expr": "1+1"}),
        ]

        # 所有关键词都不应被覆盖
        for kw in ["保存到", "写入文件", "保存文件"]:
            assert engine._is_keyword_covered_by_remaining_steps(
                kw, SAVE_FILE_CONFIG, remaining
            ) is False, f"'{kw}' 不应被 calculator 工具覆盖"

    def test_real_world_order_scenario(self, engine):
        """
        真实场景：用户说"查询订单并写分析文章保存到桌面"
        父计划: step1=delegate(order_agent查数据) → step2=skill(text_writing) → step3=final_answer

        当处理 step1 的 delegate 时：
        - remaining_steps = [step2(text_writing), step3(final_answer)]
        - "保存到" 应被 step2 的 text_writing 技能覆盖 → 跳过注入
        """
        remaining = [
            PlanStep(action="skill", skill_id="text_writing",
                     params={"topic": "订单分析报告", "task": "写分析文章保存到桌面"}),
            PlanStep(action="final_answer", content="返回最终结果"),
        ]

        # 验证各个文件写入相关关键词都被覆盖
        for kw in ["保存到", "保存文件", "写入本地", "写入文件", "写到"]:
            result = engine._is_keyword_covered_by_remaining_steps(
                kw, SAVE_FILE_CONFIG, remaining
            )
            assert result is True, (
                f"真实场景中 '{kw}' 应被 text_writing 技能覆盖，"
                f"避免 order_agent 越权执行文件写入"
            )
