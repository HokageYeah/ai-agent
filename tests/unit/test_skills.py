"""
技能库测试模块

测试所有预定义技能的定义正确性。

测试内容:
1. 验证技能基本属性（skill_id, name, description）
2. 验证 prompt_template 包含必要的占位符
3. 验证工具依赖配置正确
4. 验证记忆策略配置正确
5. 验证技能可以通过 SkillManager 注册和检索
"""

import pytest
from app.skills.base import Skill, MemoryStrategy
from app.skills.manager import SkillManager
from app.skills.library import (
    DATA_ANALYSIS_SKILL,
    CODE_GENERATION_SKILL,
    TEXT_WRITING_SKILL,
    TRANSLATION_SKILL
)


class TestDataAnalysisSkill:
    """测试数据分析技能"""
    
    def test_skill_definition(self):
        """测试技能定义正确"""
        assert DATA_ANALYSIS_SKILL.skill_id == "data_analysis"
        assert DATA_ANALYSIS_SKILL.name == "数据分析"
        assert "分析数据" in DATA_ANALYSIS_SKILL.description
    
    def test_prompt_template(self):
        """测试 Prompt 模板正确"""
        # 验证模板包含必要的占位符
        assert "{data}" in DATA_ANALYSIS_SKILL.prompt_template
        # 验证模板包含关键指导内容
        assert "趋势" in DATA_ANALYSIS_SKILL.prompt_template
        assert "异常值" in DATA_ANALYSIS_SKILL.prompt_template
    
    def test_required_tools(self):
        """测试所需工具配置正确"""
        assert "python_executor" in DATA_ANALYSIS_SKILL.required_tools
    
    def test_memory_strategy(self):
        """测试记忆策略配置正确"""
        assert DATA_ANALYSIS_SKILL.memory_strategy.include_short_term is True


class TestCodeGenerationSkill:
    """测试代码生成技能"""
    
    def test_skill_definition(self):
        """测试技能定义正确"""
        assert CODE_GENERATION_SKILL.skill_id == "code_generation"
        assert CODE_GENERATION_SKILL.name == "代码生成"
        assert "代码" in CODE_GENERATION_SKILL.description
    
    def test_prompt_template(self):
        """测试 Prompt 模板正确"""
        # 验证模板包含必要的占位符
        assert "{requirements}" in CODE_GENERATION_SKILL.prompt_template
        assert "{language}" in CODE_GENERATION_SKILL.prompt_template
        assert "{framework}" in CODE_GENERATION_SKILL.prompt_template
        # 验证模板包含关键指导内容
        assert "最佳实践" in CODE_GENERATION_SKILL.prompt_template
        assert "注释" in CODE_GENERATION_SKILL.prompt_template
    
    def test_required_tools(self):
        """测试所需工具配置正确"""
        assert "python_executor" in CODE_GENERATION_SKILL.required_tools
    
    def test_memory_strategy(self):
        """测试记忆策略配置正确"""
        assert CODE_GENERATION_SKILL.memory_strategy.include_short_term is True


class TestTextWritingSkill:
    """测试文本写作技能"""
    
    def test_skill_definition(self):
        """测试技能定义正确"""
        assert TEXT_WRITING_SKILL.skill_id == "text_writing"
        assert TEXT_WRITING_SKILL.name == "文本写作"
        assert "写作" in TEXT_WRITING_SKILL.description
    
    def test_prompt_template(self):
        """测试 Prompt 模板正确"""
        # 验证模板包含必要的占位符
        assert "{topic}" in TEXT_WRITING_SKILL.prompt_template
        assert "{content_type}" in TEXT_WRITING_SKILL.prompt_template
        assert "{style}" in TEXT_WRITING_SKILL.prompt_template
        assert "{word_count}" in TEXT_WRITING_SKILL.prompt_template
    
    def test_no_required_tools(self):
        """测试无工具依赖"""
        assert len(TEXT_WRITING_SKILL.required_tools) == 0
    
    def test_memory_strategy(self):
        """测试记忆策略配置正确"""
        # 文本写作不需要短期记忆
        assert TEXT_WRITING_SKILL.memory_strategy.include_short_term is False


class TestTranslationSkill:
    """测试翻译技能"""
    
    def test_skill_definition(self):
        """测试技能定义正确"""
        assert TRANSLATION_SKILL.skill_id == "translation"
        assert TRANSLATION_SKILL.name == "翻译"
        assert "翻译" in TRANSLATION_SKILL.description
    
    def test_prompt_template(self):
        """测试 Prompt 模板正确"""
        # 验证模板包含必要的占位符
        assert "{text}" in TRANSLATION_SKILL.prompt_template
        assert "{target_language}" in TRANSLATION_SKILL.prompt_template
        # 验证模板包含关键指导内容
        assert "风格" in TRANSLATION_SKILL.prompt_template
        assert "术语" in TRANSLATION_SKILL.prompt_template
    
    def test_no_required_tools(self):
        """测试无工具依赖"""
        assert len(TRANSLATION_SKILL.required_tools) == 0
    
    def test_memory_strategy(self):
        """测试记忆策略配置正确"""
        # 翻译不需要短期记忆
        assert TRANSLATION_SKILL.memory_strategy.include_short_term is False


class TestSkillIntegration:
    """测试技能集成"""
    
    def test_all_skills_can_be_registered(self):
        """测试所有技能可以注册到 SkillManager"""
        manager = SkillManager()
        
        # 注册所有技能
        manager.register_skill(DATA_ANALYSIS_SKILL)
        manager.register_skill(CODE_GENERATION_SKILL)
        manager.register_skill(TEXT_WRITING_SKILL)
        manager.register_skill(TRANSLATION_SKILL)
        
        # 验证技能数量
        assert len(manager.list_skills()) == 4
        
        # 验证每个技能都可以检索
        assert manager.get_skill("data_analysis") is not None
        assert manager.get_skill("code_generation") is not None
        assert manager.get_skill("text_writing") is not None
        assert manager.get_skill("translation") is not None
    
    def test_skill_ids_are_unique(self):
        """测试技能ID唯一性"""
        skill_ids = [
            DATA_ANALYSIS_SKILL.skill_id,
            CODE_GENERATION_SKILL.skill_id,
            TEXT_WRITING_SKILL.skill_id,
            TRANSLATION_SKILL.skill_id
        ]
        
        # 验证没有重复的 skill_id
        assert len(skill_ids) == len(set(skill_ids))
    
    def test_all_skills_are_skill_instances(self):
        """测试所有技能都是 Skill 实例"""
        assert isinstance(DATA_ANALYSIS_SKILL, Skill)
        assert isinstance(CODE_GENERATION_SKILL, Skill)
        assert isinstance(TEXT_WRITING_SKILL, Skill)
        assert isinstance(TRANSLATION_SKILL, Skill)
