from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar
import uuid
import json
from datetime import datetime

T = TypeVar("T")


class ExecutionStatus(Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_TOOL = "waiting_tool"


@dataclass
class ToolCall:
    """工具调用请求"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class AgentMessage:
    """Agent 消息"""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # 用于 tool result 消息
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionResult:
    """执行结果"""

    success: bool
    final_output: Any = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)
    error: str | None = None
    tokens_used: int = 0


class AgentExecutor(ABC):
    """Agent 执行器抽象基类"""

    @abstractmethod
    def execute(
        self,
        task: str,
        context: dict[str, Any],
        max_turns: int = 10,
    ) -> ExecutionResult:
        """执行任务"""
        pass

    @abstractmethod
    def get_available_tools(self) -> list[dict]:
        """获取可用工具列表"""
        pass
