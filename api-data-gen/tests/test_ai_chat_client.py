from __future__ import annotations

import ssl
from unittest import mock
import unittest

import tests._bootstrap  # noqa: F401

from api_data_gen.config import Settings
from api_data_gen.services.ai_chat_client import AiChatClient


class AiChatClientTest(unittest.TestCase):
    def test_build_ssl_context_skips_verification_when_disabled(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="https://example.internal/v1",
                ai_model_name="demo-model",
                ai_verify_ssl=False,
            )
        )

        context = client._build_ssl_context()

        self.assertIsNotNone(context)
        self.assertEqual(ssl.CERT_NONE, context.verify_mode)
        self.assertFalse(context.check_hostname)

    def test_build_ssl_context_returns_none_for_http(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="http://example.internal/v1",
                ai_model_name="demo-model",
            )
        )

        self.assertIsNone(client._build_ssl_context())

    def test_provider_auto_detects_anthropic_urls(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="https://gateway.internal/api/anthropic",
                ai_model_name="demo-model",
            )
        )

        self.assertEqual("anthropic", client._provider())
        self.assertEqual("https://gateway.internal/api/anthropic/v1/messages", client._completion_url("anthropic"))

    def test_extracts_anthropic_text_blocks(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="https://gateway.internal/api/anthropic",
                ai_model_name="demo-model",
            )
        )

        text = client._extract_text(
            "anthropic",
            {
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "world"},
                ]
            },
        )

        self.assertEqual("hello\nworld", text)

    def test_anthropic_provider_accepts_openai_style_choices(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="https://gateway.internal/api/anthropic",
                ai_model_name="demo-model",
            )
        )

        text = client._extract_text(
            "anthropic",
            {
                "choices": [
                    {
                        "message": {
                            "content": "[]",
                        }
                    }
                ]
            },
        )

        self.assertEqual("[]", text)

    def test_openai_provider_accepts_content_blocks(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="https://gateway.internal/v1",
                ai_model_name="demo-model",
            )
        )

        text = client._extract_text(
            "openai",
            {
                "content": [
                    {"type": "thinking", "text": "ignore"},
                    {"type": "text", "text": "{\"ok\":true}"},
                ]
            },
        )

        self.assertEqual("{\"ok\":true}", text)

    def test_openai_payload_supports_output_limits_and_response_format(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="https://gateway.internal/v1",
                ai_model_name="demo-model",
            )
        )

        payload = client._build_payload(
            "openai",
            "system",
            "user",
            max_output_tokens=512,
            response_format={"type": "json_object"},
            stop_sequences=["END"],
        )

        self.assertEqual(512, payload["max_tokens"])
        self.assertEqual({"type": "json_object"}, payload["response_format"])
        self.assertEqual(["END"], payload["stop"])

    def test_anthropic_payload_supports_output_limits_and_stop_sequences(self) -> None:
        client = AiChatClient(
            Settings(
                ai_base_url="https://gateway.internal/api/anthropic",
                ai_model_name="demo-model",
            )
        )

        payload = client._build_payload(
            "anthropic",
            "system",
            "user",
            max_output_tokens=768,
            stop_sequences=["END"],
        )

        self.assertEqual(768, payload["max_tokens"])
        self.assertEqual(["END"], payload["stop_sequences"])

    def test_claude_code_mode_uses_cli_result(self) -> None:
        client = AiChatClient(
            Settings(
                ai_provider="claude_code",
                ai_model_name="sonnet",
            )
        )

        with (
            mock.patch("shutil.which", return_value="/usr/local/bin/claude"),
            mock.patch("subprocess.run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(
                returncode=0,
                stdout='{"type":"result","subtype":"success","is_error":false,"result":"ok"}',
                stderr="",
            )

            result = client.complete("system prompt", "user prompt")

        self.assertEqual("ok", result)
        run_args = run_mock.call_args.args[0]
        self.assertEqual("claude", run_args[0])
        self.assertIn("--model", run_args)
        prompt_arg = next(arg for arg in run_args if "system prompt" in arg)
        self.assertIn("user prompt", prompt_arg)


if __name__ == "__main__":
    unittest.main()
