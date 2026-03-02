"""
ReAct 执行器单元测试
"""
import pytest
import json
from unittest.mock import Mock, patch

from api_data_gen.agents.executor import (
    ReActExecutor,
    ExecutionResult,
    ExecutionStatus,
    ToolCall,
)
from api_data_gen.agents.skills.decorator import skill, clear_registry


class MockLLMClient:
    """模拟 LLM 客户端"""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0

    def complete(self, system_prompt=None, user_prompt=None):
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return "Thought: Task completed\nFinal Answer: Done"


def test_react_executor_initialization():
    """测试执行器初始化"""
    mock_llm = Mock()
    executor = ReActExecutor(llm_client=mock_llm)

    assert executor._llm is mock_llm
    assert executor._max_iterations == 15


def test_react_executor_get_available_tools():
    """测试获取可用工具"""
    clear_registry()

    @skill(name="test_tool", description="A test tool")
    def test_tool(param: str) -> str:
        return param

    mock_llm = Mock()
    executor = ReActExecutor(llm_client=mock_llm)

    tools = executor.get_available_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "test_tool"


def test_react_executor_parse_response_with_tool_call():
    """测试解析带工具调用的响应"""
    clear_registry()

    @skill(name="sample_data", description="Sample data")
    def sample_data(table_name: str) -> list:
        return [{"id": 1}]

    mock_llm = Mock()
    executor = ReActExecutor(llm_client=mock_llm)

    response = """Thought: I need to sample data from the table
Action: sample_data
Action Input: {"table_name": "t_customer"}"""

    thought, tool_calls, is_complete, final_answer = executor._parse_response(response)

    assert "sample data" in thought.lower()
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "sample_data"
    assert tool_calls[0].arguments["table_name"] == "t_customer"
    assert not is_complete


def test_react_executor_parse_response_complete():
    """测试解析完成响应"""
    mock_llm = Mock()
    executor = ReActExecutor(llm_client=mock_llm)

    response = """Thought: Task completed successfully
Final Answer: Generated 10 rows of test data"""

    thought, tool_calls, is_complete, final_answer = executor._parse_response(response)

    assert is_complete
    assert "Generated 10 rows" in final_answer
    assert len(tool_calls) == 0


def test_react_executor_execute_simple_task():
    """测试执行简单任务"""
    clear_registry()

    @skill(name="add", description="Add two numbers")
    def add(a: int, b: int) -> int:
        return a + b

    mock_llm = MockLLMClient(responses=[
        "Thought: I will add the numbers\nAction: add\nAction Input: {\"a\": 5, \"b\": 3}",
        "Thought: Task completed\nFinal Answer: Result is 8",
    ])

    executor = ReActExecutor(llm_client=mock_llm)

    result = executor.execute(
        task="Calculate 5 + 3",
        context={},
        max_turns=2,
    )

    assert result.success
    assert "8" in result.final_output
    assert len(result.tool_calls) == 1


def test_react_executor_max_iterations():
    """测试最大迭代次数"""
    clear_registry()

    @skill(name="test_tool", description="Test tool")
    def test_tool(param: str) -> str:
        return param

    # LLM 总是返回需要调用工具
    mock_llm = MockLLMClient(responses=[
        "Thought: Need to call tool\nAction: test_tool\nAction Input: {\"param\": \"value\"}",
    ] * 20)

    executor = ReActExecutor(llm_client=mock_llm, max_iterations=3)

    result = executor.execute(
        task="Test task",
        context={},
        max_turns=3,
    )

    # 应该达到最大迭代次数
    assert not result.success
    assert "最大迭代次数" in result.error


def test_react_executor_tool_execution_error():
    """测试工具执行错误"""
    clear_registry()

    @skill(name="failing_tool", description="A tool that fails")
    def failing_tool(param: str) -> str:
        raise ValueError("Tool execution failed")

    mock_llm = MockLLMClient(responses=[
        "Thought: Call failing tool\nAction: failing_tool\nAction Input: {\"param\": \"test\"}",
        "Thought: Task completed\nFinal Answer: Done",
    ])

    executor = ReActExecutor(llm_client=mock_llm)

    result = executor.execute(
        task="Test error handling",
        context={},
        max_turns=2,
    )

    # 第一个工具调用应该失败
    assert len(result.tool_calls) >= 1
    assert result.tool_calls[0].status == ExecutionStatus.FAILED
    assert "Tool execution failed" in result.tool_calls[0].error


def test_react_executor_format_messages():
    """测试消息格式化"""
    from api_data_gen.agents.executor.base import AgentMessage, ToolCall

    mock_llm = Mock()
    executor = ReActExecutor(llm_client=mock_llm)

    messages = [
        AgentMessage(role="user", content="Hello"),
        AgentMessage(
            role="assistant",
            content="I will help you",
            tool_calls=[
                ToolCall(tool_name="test", arguments={"param": "value"})
            ]
        ),
        AgentMessage(role="tool", content='{"result": "ok"}'),
    ]

    formatted = executor._format_messages_for_llm(messages)

    assert "Hello" in formatted
    assert "test" in formatted
    assert "value" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
