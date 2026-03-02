"""
MCP (Model Context Protocol) 适配器

提供两种集成方式:
1. MCP Server: 将技能暴露为 MCP 工具
2. Claude Code Skill: 将技能注册为 Claude Code 可用技能
"""
from __future__ import annotations

import json
from typing import Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from ..skills.decorator import get_skill, list_skills


class MCPToolAdapter:
    """
    MCP 工具适配器

    将技能转换为 MCP 协议格式的工具
    """

    def __init__(self):
        pass

    def to_mcp_tools(self) -> list[dict]:
        """
        转换为 MCP tools list

        MCP 协议格式:
        {
            "name": "tool_name",
            "description": "tool description",
            "inputSchema": {
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        }
        """
        skills = list_skills()
        tools = []

        for skill in skills:
            tools.append(skill.to_tool_spec())

        return tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        """
        调用 MCP 工具

        MCP 协议格式:
        {
            "content": [
                {
                    "type": "text",
                    "text": "result"
                }
            ],
            "isError": false
        }
        """
        from ..skills.decorator import _skill_registry

        try:
            skill_def = _skill_registry.get(name)
            if not skill_def:
                return {
                    "content": [{"type": "text", "text": f"Tool not found: {name}"}],
                    "isError": True,
                }

            result = skill_def.handler(**arguments)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2)
                        if isinstance(result, (dict, list))
                        else str(result),
                    }
                ],
                "isError": False,
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            }

    def list_tools(self) -> dict:
        """
        列出所有工具

        MCP 协议格式:
        {
            "tools": [...]
        }
        """
        return {"tools": self.to_mcp_tools()}


class MCPServer:
    """
    简化的 MCP Server 实现

    用于独立进程运行，接收 JSON-RPC 消息
    """

    def __init__(self, adapter: MCPToolAdapter):
        self._adapter = adapter

    def handle_request(self, request: dict) -> dict:
        """处理 MCP 请求"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "tools/list":
            result = self._adapter.list_tools()
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            result = self._adapter.call_tool(name, arguments)
        else:
            result = {"error": f"Unknown method: {method}"}

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }


class SkillHTTPServer:
    """
    Skill HTTP Server

    提供 HTTP 接口供 Claude Code 调用
    """

    def __init__(self, adapter: MCPToolAdapter, port: int = 8000):
        self._adapter = adapter
        self._port = port
        self._server = None
        self._thread = None

    def start(self):
        """启动服务"""
        self._server = HTTPServer(("localhost", self._port), self._RequestHandler)
        self._server.adapter = self._adapter

        self._thread = threading.Thread(target=self._server.serve_forever)
        self._thread.daemon = True
        self._thread.start()

        print(f"Skill server started at http://localhost:{self._port}")
        return self

    def stop(self):
        """停止服务"""
        if self._server:
            self._server.shutdown()

    class _RequestHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            # 解析请求
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                request = json.loads(body)
            except json.JSONDecodeError:
                self._send_error(400, "Invalid JSON")
                return

            # 处理请求
            method = request.get("method")
            params = request.get("params", {})
            request_id = request.get("id")

            if method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments", {})
                result = self.server.adapter.call_tool(name, arguments)
            else:
                result = {"error": f"Unknown method: {method}"}

            # 发送响应
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def do_GET(self):
            if self.path == "/tools":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(self.server.adapter.list_tools()).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def _send_error(self, code: int, message: str):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            error_response = {
                "jsonrpc": "2.0",
                "error": {"code": code, "message": message},
            }
            self.wfile.write(json.dumps(error_response).encode())

        def log_message(self, format, *args):
            pass  # 抑制日志
