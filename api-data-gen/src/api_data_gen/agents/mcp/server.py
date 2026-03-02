#!/usr/bin/env python
"""
MCP Server 启动入口

使用方法:
    python -m api_data_gen.agents.mcp.server --port 8000

或者:
    python -m api_data_gen.agents.mcp.server --help
"""
from __future__ import annotations

import argparse
import sys

from api_data_gen.agents.mcp import MCPToolAdapter, SkillHTTPServer


def main():
    parser = argparse.ArgumentParser(
        description="启动 MCP Skill Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python -m api_data_gen.agents.mcp.server --port 8000
    python -m api_data_gen.agents.mcp.server --port 9000 --host 0.0.0.0
        """
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="服务端口 (默认: 8000)"
    )
    parser.add_argument(
        "--host", type=str, default="localhost",
        help="服务地址 (默认: localhost)"
    )
    parser.add_argument(
        "--init-skills", action="store_true",
        help="初始化技能容器（需要先配置数据库连接）"
    )

    args = parser.parse_args()

    # 如果需要初始化技能
    if args.init_skills:
        print("正在初始化技能...")
        try:
            # 延迟导入，避免不必要的依赖
            from api_data_gen.config import load_settings
            from api_data_gen.infra.db.mysql_client import MysqlClient
            from api_data_gen.infra.db.sample_repository import SampleRepository
            from api_data_gen.infra.db.schema_repository import SchemaRepository
            from api_data_gen.agents.skills.manager import SkillManager

            settings = load_settings()
            client = MysqlClient(settings)
            schema_repository = SchemaRepository(client)
            sample_repository = SampleRepository(
                client,
                settings.trace_schema,
                schema_repository,
            )

            SkillManager.initialize(
                sample_repository=sample_repository,
                schema_repository=schema_repository,
            )
            print("技能初始化完成")
        except Exception as e:
            print(f"技能初始化失败: {e}")
            print("将以简化模式启动（部分技能可能不可用）")

    # 创建适配器
    adapter = MCPToolAdapter()

    # 创建并启动服务
    server = SkillHTTPServer(adapter, port=args.port)

    print(f"启动 MCP Skill Server: http://{args.host}:{args.port}")
    print(f"访问 http://{args.host}:{args.port}/tools 查看可用工具")
    print("按 Ctrl+C 停止服务")

    try:
        server.start()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
        server.stop()
        print("服务已停止")
        sys.exit(0)


if __name__ == "__main__":
    main()
