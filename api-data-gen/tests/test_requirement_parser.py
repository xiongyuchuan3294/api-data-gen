from __future__ import annotations

import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.services.requirement_parser import RequirementParser


class RequirementParserTest(unittest.TestCase):
    def test_parse_extracts_summary_constraints_and_keywords(self) -> None:
        parser = RequirementParser()
        requirement_text = """
需求描述：
【背景】希望基于需求描述和接口SQL查询行为来生成测试场景和造数。
【任务】
1. 将 java 脚本重构成 python 脚本
2. 建议在本地MySQL生成新的表
【要求】
1. 分步生成 markdown 落地方案后再执行
2. 不要直接写代码
3. 希望用 agent skill 或模块化方案
"""

        summary = parser.parse(requirement_text)

        self.assertIn("希望基于需求描述和接口SQL查询行为来生成测试场景和造数", summary.summary)
        self.assertIn("建议在本地MySQL生成新的表", summary.constraints)
        self.assertIn("不要直接写代码", summary.constraints)
        self.assertIn("测试场景", summary.keywords)
        self.assertIn("本地MySQL", summary.keywords)
        self.assertIn("agent", summary.keywords)


if __name__ == "__main__":
    unittest.main()
