from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import time
from urllib import error, request


class AiChatClient:
    def __init__(self, settings):
        self._settings = settings
        self._last_call_monotonic = 0.0

    def is_configured(self) -> bool:
        provider = self._provider()
        if provider == "claude_code":
            return shutil.which("claude") is not None
        return bool(self._settings.ai_base_url and self._settings.ai_model_name)

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int | None = None,
        response_format: dict[str, object] | None = None,
        stop_sequences: list[str] | None = None,
    ) -> str:
        if not self.is_configured():
            raise ValueError(
                "AI client is not configured. Set the provider-specific AI settings or install the `claude` CLI for claude_code mode."
            )

        self._respect_rate_limit()
        provider = self._provider()
        if provider == "claude_code":
            return self._complete_with_claude_code(system_prompt, user_prompt)
        payload = self._build_payload(
            provider,
            system_prompt,
            user_prompt,
            max_output_tokens=max_output_tokens,
            response_format=response_format,
            stop_sequences=stop_sequences,
        )
        headers = self._build_headers(provider)

        url = self._completion_url(provider)
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._settings.ai_timeout_sec, context=self._build_ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"AI request failed with HTTP {exc.code}: {_extract_error_text(body)}") from exc

        message = _extract_error_message(data)
        if message is not None:
            raise ValueError(f"AI request failed: {message}")
        return self._extract_text(provider, data)

    def _completion_url(self, provider: str) -> str:
        base_url = self._settings.ai_base_url.rstrip("/")
        if provider == "anthropic":
            if base_url.endswith("/v1/messages") or base_url.endswith("/messages"):
                return base_url
            return f"{base_url}/v1/messages"
        if base_url.endswith("/chat/completions") or base_url.endswith("/v1/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        delay = (self._settings.ai_rate_limit_ms / 1000.0) - (now - self._last_call_monotonic)
        if delay > 0:
            time.sleep(delay)
        self._last_call_monotonic = time.monotonic()

    def _build_ssl_context(self):
        if not self._settings.ai_base_url.lower().startswith("https://"):
            return None
        if not self._settings.ai_verify_ssl:
            return ssl._create_unverified_context()
        if self._settings.ai_ca_file:
            return ssl.create_default_context(cafile=self._settings.ai_ca_file)
        return None

    def _provider(self) -> str:
        configured = (self._settings.ai_provider or "auto").strip().lower()
        if configured in {"openai", "anthropic"}:
            return configured
        if configured == "claude_code":
            return configured
        base_url = self._settings.ai_base_url.lower()
        if "/anthropic" in base_url or base_url.endswith("/v1/messages") or base_url.endswith("/messages"):
            return "anthropic"
        return "openai"

    def _build_payload(
        self,
        provider: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int | None = None,
        response_format: dict[str, object] | None = None,
        stop_sequences: list[str] | None = None,
    ) -> dict[str, object]:
        if provider == "anthropic":
            payload = {
                "model": self._settings.ai_model_name,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self._settings.ai_temperature,
                "max_tokens": max_output_tokens or 2048,
            }
            if stop_sequences:
                payload["stop_sequences"] = stop_sequences
            return payload
        payload = {
            "model": self._settings.ai_model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._settings.ai_temperature,
        }
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        if stop_sequences:
            payload["stop"] = stop_sequences
        return payload

    def _build_headers(self, provider: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.ai_api_key:
            headers["Authorization"] = f"Bearer {self._settings.ai_api_key}"
        if provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
            if self._settings.ai_api_key:
                headers["x-api-key"] = self._settings.ai_api_key
        return headers

    def _extract_text(self, provider: str, data: dict[str, object]) -> str:
        if provider == "anthropic":
            content = _extract_anthropic_text(data)
            if content is not None:
                return content
            fallback = _extract_openai_text(data)
            if fallback is not None:
                return fallback
            raise ValueError("AI response did not contain Anthropic text content.")

        content = _extract_openai_text(data)
        if content is not None:
            return content
        fallback = _extract_anthropic_text(data)
        if fallback is not None:
            return fallback
        raise ValueError("AI response did not contain message content.")

    def _complete_with_claude_code(self, system_prompt: str, user_prompt: str) -> str:
        prompt = f"{system_prompt}\n\n{user_prompt}".strip()
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            prompt,
        ]
        if self._settings.ai_model_name:
            cmd.extend(["--model", self._settings.ai_model_name])
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise ValueError(f"Claude Code request failed: {stderr or f'exit {result.returncode}'}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Claude Code response was not valid JSON.") from exc
        if payload.get("is_error"):
            detail = payload.get("result") or payload.get("subtype") or "unknown error"
            raise ValueError(f"Claude Code request failed: {detail}")
        content = payload.get("result")
        if not isinstance(content, str):
            raise ValueError("Claude Code response did not contain result text.")
        return content


def _extract_error_message(data: dict[str, object]) -> str | None:
    if isinstance(data.get("error"), dict):
        message = data["error"].get("message")
        if message:
            return str(message)
    if data.get("success") is False and data.get("msg"):
        return str(data["msg"])
    if data.get("code") not in {None, 0, "0", 200, "200"} and data.get("msg"):
        return str(data["msg"])
    return None


def _extract_error_text(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    return _extract_error_message(data) or body.strip()


def _extract_anthropic_text(data: dict[str, object]) -> str | None:
    content = data.get("content")
    text = _extract_text_parts(content)
    if text is not None:
        return text

    message = data.get("message")
    if isinstance(message, dict):
        return _extract_text_parts(message.get("content"))
    return None


def _extract_openai_text(data: dict[str, object]) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    first = choices[0]
    if not isinstance(first, dict):
        return None

    for key in ("message", "delta"):
        message = first.get(key)
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        text = _extract_text_parts(content)
        if text is not None:
            return text
    return None


def _extract_text_parts(content: object) -> str | None:
    if isinstance(content, str) and content:
        return content
    if not isinstance(content, list):
        return None

    # Support multiple content types including thinking (reasoning models like DeepSeek R1)
    text_types = {"text", "output_text", "thinking"}

    text_parts = [
        str(item.get("text"))
        for item in content
        if isinstance(item, dict) and item.get("type") in text_types and item.get("text")
    ]
    if text_parts:
        return "\n".join(text_parts)

    # For thinking type content, check for 'thinking' field
    if content:
        for item in content:
            if isinstance(item, dict) and item.get("type") == "thinking" and item.get("thinking"):
                return str(item.get("thinking"))

    return None
