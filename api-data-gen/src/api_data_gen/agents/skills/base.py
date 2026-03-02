from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SkillParameter:
    """技能参数定义"""

    name: str
    type_hint: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class SkillDefinition:
    """技能定义"""

    name: str
    description: str
    parameters: list[SkillParameter]
    return_type: str
    handler: Callable
    category: str = "general"

    def to_tool_spec(self) -> dict:
        """转换为 MCP tool 格式"""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = {
                "type": _python_type_to_json(param.type_hint),
                "description": param.description,
            }
            if param.default is not None:
                properties[param.name]["default"] = param.default
            elif param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


def _python_type_to_json(type_hint: str) -> str:
    """Python 类型转 JSON Schema 类型"""
    mapping = {
        "str": "string",
        "string": "string",
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "number": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "list": "array",
        "array": "array",
        "dict": "object",
        "object": "object",
    }
    # 提取基础类型，处理多种格式:
    # - "int" -> int
    # - "<class 'int'>" -> int
    # - "list[str]" -> list
    import re
    # 匹配 <class 'int'> 格式
    class_match = re.search(r"<class '(\w+)'", type_hint)
    if class_match:
        base = class_match.group(1)
    else:
        # 提取第一个单词
        base = type_hint.split("[")[0].split("|")[0].strip().split()[0]
    return mapping.get(base, "string")
