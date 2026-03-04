from __future__ import annotations

import contextlib
import io
import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.cli.main import build_parser


class CliMainParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_draft_defaults_to_agent_auto(self) -> None:
        args = self.parser.parse_args(
            [
                "draft",
                "--requirement-file",
                "req.txt",
                "--api",
                "demo=/path",
            ]
        )

        self.assertEqual("agent_auto", args.strategy_mode)

    def test_generate_defaults_to_agent_auto(self) -> None:
        args = self.parser.parse_args(
            [
                "generate",
                "--requirement-file",
                "req.txt",
                "--api",
                "demo=/path",
            ]
        )

        self.assertEqual("agent_auto", args.strategy_mode)

    def test_direct_mode_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(
                    [
                        "generate",
                        "--requirement-file",
                        "req.txt",
                        "--api",
                        "demo=/path",
                        "--strategy-mode",
                        "direct",
                    ]
                )

    def test_legacy_ai_flags_are_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(
                    [
                        "draft",
                        "--requirement-file",
                        "req.txt",
                        "--api",
                        "demo=/path",
                        "--use-ai-scenarios",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
