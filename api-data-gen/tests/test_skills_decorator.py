"""
技能装饰器单元测试
"""
import pytest
import json

from api_data_gen.agents.skills.decorator import (
    skill,
    get_skill,
    list_skills,
    clear_registry,
)


def test_skill_decorator_basic():
    """测试技能装饰器基本功能"""
    clear_registry()

    @skill(name="test_skill", description="A test skill")
    def test_skill(param1: str, param2: int = 5) -> str:
        """A test function"""
        return f"{param1}: {param2}"

    # 验证技能注册
    skill_def = get_skill("test_skill")
    assert skill_def is not None
    assert skill_def.name == "test_skill"
    assert skill_def.description == "A test skill"

    # 验证参数提取
    assert len(skill_def.parameters) == 2
    param_names = [p.name for p in skill_def.parameters]
    assert "param1" in param_names
    assert "param2" in param_names

    # 验证参数属性
    param1 = next(p for p in skill_def.parameters if p.name == "param1")
    assert param1.required == True
    param2 = next(p for p in skill_def.parameters if p.name == "param2")
    assert param2.required == False
    assert param2.default == 5


def test_skill_decorator_without_name():
    """测试不带名称的装饰器"""
    clear_registry()

    @skill(description="Auto named skill")
    def auto_named_skill():
        return "result"

    skill_def = get_skill("auto_named_skill")
    assert skill_def is not None
    assert skill_def.name == "auto_named_skill"


def test_skill_execution():
    """测试技能执行"""
    clear_registry()

    @skill(name="add_numbers", description="Add two numbers")
    def add_numbers(a: int, b: int = 10) -> int:
        return a + b

    skill_def = get_skill("add_numbers")
    result = skill_def.handler(5, 3)
    assert result == 8

    # 测试默认参数
    result2 = skill_def.handler(5)
    assert result2 == 15


def test_to_tool_spec():
    """测试转换为 MCP tool 格式"""
    clear_registry()

    @skill(name="sample_data", description="Sample table data")
    def sample_data(table_name: str, limit: int = 3) -> list:
        return []

    skill_def = get_skill("sample_data")
    tool_spec = skill_def.to_tool_spec()

    assert tool_spec["name"] == "sample_data"
    assert tool_spec["description"] == "Sample table data"
    assert tool_spec["inputSchema"]["type"] == "object"

    # 验证参数
    props = tool_spec["inputSchema"]["properties"]
    assert "table_name" in props
    assert props["table_name"]["type"] == "string"
    assert "limit" in props
    assert props["limit"]["type"] == "integer"
    assert props["limit"]["default"] == 3


def test_list_skills():
    """测试列出所有技能"""
    clear_registry()

    @skill(name="skill_a", description="Skill A")
    def skill_a():
        pass

    @skill(name="skill_b", description="Skill B")
    def skill_b():
        pass

    skills = list_skills()
    assert len(skills) == 2

    skill_names = [s.name for s in skills]
    assert "skill_a" in skill_names
    assert "skill_b" in skill_names


def test_category_filter():
    """测试按类别筛选"""
    clear_registry()

    @skill(name="skill_1", description="Skill 1", category="data")
    def skill_1():
        pass

    @skill(name="skill_2", description="Skill 2", category="data")
    def skill_2():
        pass

    @skill(name="skill_3", description="Skill 3", category="schema")
    def skill_3():
        pass

    data_skills = list_skills(category="data")
    assert len(data_skills) == 2

    schema_skills = list_skills(category="schema")
    assert len(schema_skills) == 1


def test_clear_registry():
    """测试清空注册表"""
    clear_registry()

    @skill(name="temp_skill")
    def temp_skill():
        pass

    assert get_skill("temp_skill") is not None

    clear_registry()

    assert get_skill("temp_skill") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
