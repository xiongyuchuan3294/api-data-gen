"""
Agent 配置管理

提供 Agent 执行相关的配置支持
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os


class AgentMode(Enum):
    """Agent 执行模式"""

    LOCAL = "local"
    DIRECT = "direct"
    AGENT_PROMPT = "agent_prompt"
    AGENT_AUTO = "agent_auto"


class ThinkingMode(Enum):
    """思考模式"""

    REACT = "react"
    CHAIN_OF_THOUGHT = "chain_of_thought"
    PLAN_EXECUTE = "plan_execute"


@dataclass
class AgentConfig:
    """Agent 配置"""

    # 执行模式
    default_mode: AgentMode = AgentMode.AGENT_PROMPT

    # Agent 自动模式配置
    auto: "AgentAutoConfig" = field(default_factory=lambda: AgentAutoConfig())

    # MCP 配置
    mcp: "McpConfig" = field(default_factory=lambda: McpConfig())

    # 提示词配置
    prompts: "PromptConfig" = field(default_factory=lambda: PromptConfig())

    # 技能配置
    skills: "SkillConfig" = field(default_factory=lambda: SkillConfig())


@dataclass
class AgentAutoConfig:
    """Agent 自动模式配置"""

    max_turns: int = 15
    timeout_seconds: int = 300
    fallback_to_local: bool = True
    thinking_mode: ThinkingMode = ThinkingMode.REACT


@dataclass
class McpConfig:
    """MCP 配置"""

    enabled: bool = False
    port: int = 8000
    host: str = "localhost"


@dataclass
class PromptConfig:
    """提示词配置"""

    system: str = "You are a test data generation assistant..."
    max_context_length: int = 8000


@dataclass
class SkillConfig:
    """技能配置"""

    enabled: list[str] | None = None  # None 表示全部启用
    timeout: int = 60  # 技能执行超时（秒）
    retry: int = 2  # 技能重试次数


def load_agent_config(env_file: str | Path | None = None) -> AgentConfig:
    """
    从环境变量加载 Agent 配置

    环境变量:
    - API_DATA_GEN_AGENT_MODE: 执行模式 (local/direct/agent_prompt/agent_auto)
    - API_DATA_GEN_AGENT_MAX_TURNS: 最大迭代次数
    - API_DATA_GEN_AGENT_TIMEOUT: 超时秒数
    - API_DATA_GEN_AGENT_FALLBACK: 是否回退到本地 (true/false)
    - API_DATA_GEN_AGENT_MCP_ENABLED: 是否启用 MCP (true/false)
    - API_DATA_GEN_AGENT_MCP_PORT: MCP 端口
    """
    env_path = Path(env_file) if env_file else Path(".env")

    # 加载环境变量
    env_values = _load_env_file(env_path)

    def read(key: str, default: str) -> str:
        return os.getenv(key, env_values.get(key, default))

    def read_bool(key: str, default: bool) -> bool:
        value = read(key, "true" if default else "false").strip().lower()
        return value in {"1", "true", "yes", "on"}

    def read_int(key: str, default: int) -> int:
        try:
            return int(read(key, str(default)))
        except ValueError:
            return default

    # 解析模式
    mode_str = read("API_DATA_GEN_AGENT_MODE", "agent_prompt").lower()
    try:
        default_mode = AgentMode(mode_str)
    except ValueError:
        default_mode = AgentMode.AGENT_PROMPT

    # 解析思考模式
    thinking_str = read("API_DATA_GEN_AGENT_THINKING_MODE", "react").lower()
    try:
        thinking_mode = ThinkingMode(thinking_str)
    except ValueError:
        thinking_mode = ThinkingMode.REACT

    return AgentConfig(
        default_mode=default_mode,
        auto=AgentAutoConfig(
            max_turns=read_int("API_DATA_GEN_AGENT_MAX_TURNS", 15),
            timeout_seconds=read_int("API_DATA_GEN_AGENT_TIMEOUT", 300),
            fallback_to_local=read_bool("API_DATA_GEN_AGENT_FALLBACK", True),
            thinking_mode=thinking_mode,
        ),
        mcp=McpConfig(
            enabled=read_bool("API_DATA_GEN_AGENT_MCP_ENABLED", False),
            port=read_int("API_DATA_GEN_AGENT_MCP_PORT", 8000),
            host=read("API_DATA_GEN_AGENT_MCP_HOST", "localhost"),
        ),
        prompts=PromptConfig(
            system=read("API_DATA_GEN_AGENT_SYSTEM_PROMPT", "You are a test data generation assistant..."),
            max_context_length=read_int("API_DATA_GEN_AGENT_MAX_CONTEXT", 8000),
        ),
        skills=SkillConfig(
            timeout=read_int("API_DATA_GEN_AGENT_SKILL_TIMEOUT", 60),
            retry=read_int("API_DATA_GEN_AGENT_SKILL_RETRY", 2),
        ),
    )


def _load_env_file(env_path: Path) -> dict[str, str]:
    """加载环境变量文件"""
    if not env_path.exists():
        return {}

    result: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result
