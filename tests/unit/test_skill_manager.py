import pytest
from app.skills.base import Skill, MemoryStrategy
from app.skills.manager import SkillManager

def test_skill_model():
    """测试 Skill 模型定义"""
    skill = Skill(
        skill_id="test_skill",
        name="Test Skill",
        description="A test skill",
        prompt_template="Hello {name}"
    )
    assert skill.skill_id == "test_skill"
    assert skill.memory_strategy.include_short_term is True

def test_skill_manager():
    """测试 SkillManager 功能"""
    manager = SkillManager()
    
    skill = Skill(
        skill_id="chat",
        name="Chat",
        description="Simple chat",
        prompt_template="Chat: {input}"
    )
    
    # 1. 注册
    manager.register_skill(skill)
    assert len(manager.list_skills()) == 1
    
    # 2. 获取
    retrieved = manager.get_skill("chat")
    assert retrieved is not None
    assert retrieved.name == "Chat"
    
    # 3. 获取不存在的
    assert manager.get_skill("non_existent") is None
    
    # 4. 覆盖
    new_skill = Skill(
        skill_id="chat",
        name="Advanced Chat", # Name changed
        description="Simple chat",
        prompt_template="Chat: {input}"
    )
    manager.register_skill(new_skill)
    assert manager.get_skill("chat").name == "Advanced Chat"
