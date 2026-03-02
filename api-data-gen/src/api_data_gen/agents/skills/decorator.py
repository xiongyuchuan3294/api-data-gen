from __future__ import annotations

import re
import inspect
from functools import wraps
from typing import Callable, Any

from .base import SkillDefinition, SkillParameter

# 全局技能注册表
_skill_registry: dict[str, SkillDefinition] = {}


def skill(
    name: str | None = None,
    description: str = "",
    category: str = "general",
):
    """
    技能装饰器

    用法:
        @skill(name="generate_scenarios_ai", description="生成测试场景")
        def generate_scenarios_ai(requirement: str, ...) -> list[ScenarioDraft]:
            ...
    """

    def decorator(func: Callable) -> Callable:
        skill_name = name or func.__name__

        # 从函数签名提取参数
        parameters = []
        sig = inspect.signature(func)
        for param_name, param in sig.parameters.items():
            # 从类型注解获取信息
            type_hint = str(param.annotation) if param.annotation != inspect.Parameter.empty else "str"

            # 从 docstring 提取描述
            param_desc = _extract_param_description(func.__doc__, param_name)

            parameters.append(
                SkillParameter(
                    name=param_name,
                    type_hint=type_hint,
                    description=param_desc,
                    required=param.default == inspect.Parameter.empty,
                    default=param.default if param.default != inspect.Parameter.empty else None,
                )
            )

        # 从返回类型注解获取返回类型
        return_type = ""
        if func.__annotations__ and "return" in func.__annotations__:
            return_type = str(func.__annotations__["return"])

        # 创建技能定义
        skill_def = SkillDefinition(
            name=skill_name,
            description=description or func.__doc__ or "",
            parameters=parameters,
            return_type=return_type,
            handler=func,
            category=category,
        )

        # 注册到全局表
        _skill_registry[skill_name] = skill_def

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # 附加元数据
        wrapper._skill_def = skill_def

        return wrapper

    return decorator


def _extract_param_description(docstring: str | None, param_name: str) -> str:
    """从 docstring 提取参数描述"""
    if not docstring:
        return ""

    # 简单的 docstring 解析
    # 期望格式: :param param_name: description
    pattern = rf":param\s+{param_name}:\s*(.+?)(?=\n|:param|\Z)"
    match = re.search(pattern, docstring, re.DOTALL)
    return match.group(1).strip() if match else ""


def get_skill(name: str) -> SkillDefinition | None:
    """获取技能定义"""
    return _skill_registry.get(name)


def list_skills(category: str | None = None) -> list[SkillDefinition]:
    """列出所有技能"""
    skills = list(_skill_registry.values())
    if category:
        skills = [s for s in skills if s.category == category]
    return skills


def register_skill(skill_def: SkillDefinition, handler: Callable):
    """手动注册技能"""
    skill_def.handler = handler
    _skill_registry[skill_def.name] = skill_def


def clear_registry():
    """清空注册表（主要用于测试）"""
    _skill_registry.clear()
