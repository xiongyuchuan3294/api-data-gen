from __future__ import annotations

import json
import re
import logging
from datetime import datetime
from typing import Any

from .base import AgentExecutor, AgentMessage, ExecutionResult, ExecutionStatus, ToolCall
from ..skills.decorator import get_skill, list_skills

logger = logging.getLogger(__name__)


class ReActExecutor(AgentExecutor):
    """
    ReAct (Reason + Act) 执行器

    执行循环:
    1. 思考 (Think): 模型分析当前状态，决定下一步
    2. 行动 (Act): 模型选择一个工具并生成参数
    3. 观察 (Observe): 执行工具，返回结果
    4. 重复直到完成
    """

    def __init__(
        self,
        llm_client,
        system_prompt: str | None = None,
        max_iterations: int = 15,
        timeout_seconds: int = 300,
        retry_on_error: int = 2,
    ):
        self._llm = llm_client
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self._timeout_seconds = timeout_seconds
        self._retry_on_error = retry_on_error

    def execute(
        self,
        task: str,
        context: dict[str, Any],
        max_turns: int = 10,
    ) -> ExecutionResult:
        messages = self._build_initial_messages(task, context)
        tool_calls_history: list[ToolCall] = []
        consecutive_errors = 0

        for turn in range(max_turns):
            # 1. 调用 LLM 获取响应
            try:
                response = self._llm.complete(
                    system_prompt=self._get_system_prompt(),
                    user_prompt=self._format_messages_for_llm(messages),
                )
            except Exception as e:
                logger.warning(f"LLM call failed (turn {turn + 1}): {e}")
                consecutive_errors += 1
                if consecutive_errors >= self._retry_on_error:
                    return ExecutionResult(
                        success=False,
                        error=f"LLM 调用失败: {str(e)}",
                        tool_calls=tool_calls_history,
                        messages=messages,
                    )
                continue

            consecutive_errors = 0  # 成功后重置错误计数

            # 2. 解析响应，提取思考和工具调用
            thought, tool_calls, is_complete, final_answer = self._parse_response(response or "")

            # 3. 添加助手消息
            messages.append(
                AgentMessage(
                    role="assistant",
                    content=thought,
                    tool_calls=tool_calls,
                )
            )

            # 4. 检查是否完成
            if is_complete and final_answer:
                return ExecutionResult(
                    success=True,
                    final_output=final_answer,
                    tool_calls=tool_calls_history,
                    messages=messages,
                )

            # 5. 如果没有工具调用但也没完成，可能需要追问
            if not tool_calls:
                messages.append(
                    AgentMessage(
                        role="user",
                        content="请通过调用工具来完成这个任务。如果已经完成任务，请输出 'Final Answer:' 标记最终结果。",
                    )
                )
                continue

            # 6. 执行工具调用
            for tool_call in tool_calls:
                tool_call.status = ExecutionStatus.RUNNING
                tool_call.started_at = datetime.now()
                result = None

                # 带重试的工具执行
                for retry in range(self._retry_on_error):
                    try:
                        result = self._execute_tool(tool_call.tool_name, tool_call.arguments)
                        tool_call.result = result
                        tool_call.status = ExecutionStatus.COMPLETED
                        tool_call.completed_at = datetime.now()
                        break  # 成功，跳出重试循环
                    except Exception as e:
                        if retry == self._retry_on_error - 1:
                            # 最后一次重试失败
                            tool_call.error = str(e)
                            tool_call.status = ExecutionStatus.FAILED
                            tool_call.completed_at = datetime.now()
                            logger.warning(
                                f"Tool '{tool_call.tool_name}' failed after {self._retry_on_error} retries: {e}"
                            )
                        else:
                            # 继续重试
                            continue

                # 添加工具结果消息
                if tool_call.status == ExecutionStatus.COMPLETED:
                    messages.append(
                        AgentMessage(
                            role="tool",
                            content=json.dumps(result, ensure_ascii=False, indent=2) if result else "null",
                            tool_call_id=tool_call.id,
                        )
                    )
                else:
                    messages.append(
                        AgentMessage(
                            role="tool",
                            content=f"Error: {tool_call.error or 'Unknown error'}",
                            tool_call_id=tool_call.id,
                        )
                    )

                tool_calls_history.append(tool_call)

            # 7. 检查是否达到最大迭代
            if turn >= max_turns - 1:
                return ExecutionResult(
                    success=False,
                    error=f"达到最大迭代次数 {max_turns}",
                    final_output=messages[-1].content if messages else None,
                    tool_calls=tool_calls_history,
                    messages=messages,
                )

        return ExecutionResult(
            success=False,
            error="未完成任务",
            tool_calls=tool_calls_history,
            messages=messages,
        )

    def get_available_tools(self) -> list[dict]:
        """获取可用工具列表"""
        skills = list_skills()
        tools = []

        for skill_def in skills:
            tools.append(skill_def.to_tool_spec())

        return tools

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        if self._system_prompt:
            return self._system_prompt

        tools_json = json.dumps(self.get_available_tools(), ensure_ascii=False, indent=2)

        return f"""你是一个测试数据生成的智能助手。你可以通过调用工具来完成以下任务：

1. 理解业务需求和接口信息
2. 设计测试场景
3. 生成测试数据
4. 验证数据质量

## 可用工具

```json
{tools_json}
```

## 执行模式

你采用 ReAct (Reason + Act) 模式：
1. 先分析当前状态和需求
2. 选择合适的工具并提供参数
3. 根据工具返回结果决定下一步

## 输出格式

你必须按照以下格式输出：

```
Thought: <你的思考和分析>
Action: <工具名称>
Action Input: <JSON 格式的工具参数>
```

如果任务完成，直接输出：
```
Thought: 任务已完成
Final Answer: <最终结果>
```

## 注意事项

- 所有参数必须提供，除非有默认值
- 返回结果会自动格式化，你可以基于结果继续推理
- 如果遇到错误，分析原因并尝试其他方法
"""

    def _build_initial_messages(
        self,
        task: str,
        context: dict[str, Any],
    ) -> list[AgentMessage]:
        """构建初始消息"""
        context_str = self._format_context(context)

        return [
            AgentMessage(
                role="user",
                content=f"{task}\n\n## 上下文信息\n\n{context_str}",
            )
        ]

    def _format_context(self, context: dict[str, Any]) -> str:
        """格式化上下文"""
        parts = []
        for key, value in context.items():
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False, indent=2)
                parts.append(f"### {key}\n```\n{value_str}\n```")
            else:
                parts.append(f"### {key}\n{value}")
        return "\n\n".join(parts)

    def _format_messages_for_llm(self, messages: list[AgentMessage]) -> str:
        """将消息格式化为 LLM 输入"""
        parts = []

        for msg in messages:
            if msg.role == "system":
                continue  # system prompt 单独处理

            if msg.role == "user":
                parts.append(f"User: {msg.content}")

            elif msg.role == "assistant":
                content_parts = []
                if msg.content:
                    content_parts.append(msg.content)
                for tc in msg.tool_calls:
                    content_parts.append(
                        f"Action: {tc.tool_name}\n"
                        f"Action Input: {json.dumps(tc.arguments, ensure_ascii=False)}"
                    )
                parts.append("Thought: " + "\n".join(content_parts))

            elif msg.role == "tool":
                parts.append(
                    f"Observation: {msg.content}"
                )

        return "\n\n".join(parts)

    def _parse_response(
        self, response: str
    ) -> tuple[str, list[ToolCall], bool, str | None]:
        """解析 LLM 响应"""
        tool_calls = []
        thought = ""
        is_complete = False
        final_answer = None

        # 提取 Thought
        thought_match = re.search(
            r"Thought:\s*(.+?)(?=\n(?:Action:|Final Answer:)|$)", response, re.DOTALL
        )
        if thought_match:
            thought = thought_match.group(1).strip()

        # 提取 Final Answer
        final_answer_match = re.search(
            r"Final Answer:\s*(.+?)$", response, re.DOTALL
        )
        if final_answer_match:
            final_answer = final_answer_match.group(1).strip()
            is_complete = True

        # 提取 Action
        action_match = re.search(r"Action:\s*(\w+)", response)
        action_name = action_match.group(1).strip() if action_match else ""

        # 提取 Action Input
        if action_name:
            # 尝试多种格式
            input_match = re.search(
                r"Action Input:\s*```(?:json)?\s*(.+?)```", response, re.DOTALL
            )
            if not input_match:
                input_match = re.search(
                    r"Action Input:\s*(\{.+?\})", response, re.DOTALL
                )

            if input_match:
                try:
                    arguments = json.loads(input_match.group(1))
                    tool_calls.append(
                        ToolCall(
                            tool_name=action_name,
                            arguments=arguments,
                        )
                    )
                except json.JSONDecodeError:
                    pass

        return thought, tool_calls, is_complete, final_answer

    def _execute_tool(self, tool_name: str, arguments: dict) -> Any:
        """执行工具"""
        skill_def = get_skill(tool_name)
        if not skill_def:
            raise ValueError(f"Unknown tool: {tool_name}")

        # 调用实际处理函数
        result = skill_def.handler(**arguments)
        return result
