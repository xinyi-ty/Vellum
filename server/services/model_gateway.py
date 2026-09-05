"""Small provider adapter for JSON responses from supported LLM APIs."""

import json
import os
import re
from typing import Any

from anthropic import Anthropic
from openai import OpenAI


class ModelGatewayError(RuntimeError):
    pass


class ModelGateway:
    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.api_base = os.getenv("LLM_API_BASE", "").strip()
        self.model = os.getenv("LLM_MODEL", "").strip()
        self.provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
        mock_setting = os.getenv("USE_MOCK", "").strip().lower()
        self.is_mock = mock_setting == "true" or not self.api_key

        if self.provider not in {"anthropic", "openai"}:
            raise ModelGatewayError("LLM_PROVIDER must be anthropic or openai")

        self._client: Anthropic | OpenAI | None = None
        if not self.is_mock:
            if not self.model:
                raise ModelGatewayError("LLM_MODEL is required in live mode")
            if self.provider == "openai":
                kwargs: dict[str, Any] = {"api_key": self.api_key, "timeout": 60.0}
                if self.api_base:
                    kwargs["base_url"] = self.api_base
                self._client = OpenAI(**kwargs)
            else:
                kwargs = {"api_key": self.api_key, "timeout": 60.0}
                if self.api_base:
                    kwargs["base_url"] = self.api_base
                self._client = Anthropic(**kwargs)

    def config(self) -> dict[str, str | bool]:
        return {
            "provider": self.provider,
            "model": self.model or "mock",
            "mock": self.is_mock,
        }

    def call_json(self, system: str, payload: dict, max_tokens: int = 1800) -> dict:
        if self.is_mock:
            raise ModelGatewayError("model call requested while mock mode is active")

        user_message = json.dumps(payload, ensure_ascii=False)
        try:
            if isinstance(self._client, OpenAI):
                response = self._client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=0.7,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
                )
                text = response.choices[0].message.content or ""
            elif isinstance(self._client, Anthropic):
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=0.7,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                )
                text = "".join(block.text for block in response.content if block.type == "text")
            else:
                raise ModelGatewayError("model client is unavailable")
        except ModelGatewayError:
            raise
        except Exception as exc:
            raise ModelGatewayError(f"model request failed: {exc}") from exc

        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> dict:
        candidates = [text.strip()]
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fenced:
            candidates.append(fenced.group(1).strip())
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        raise ModelGatewayError("model returned invalid JSON")

