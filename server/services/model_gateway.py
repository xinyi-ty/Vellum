"""Small provider adapter for JSON responses from supported LLM APIs."""

import ast
import json
import os
import re
from typing import Any

from anthropic import Anthropic
from openai import OpenAI
from pydantic import BaseModel, ValidationError


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

    def call_json(
        self,
        system: str,
        payload: dict,
        max_tokens: int = 1800,
        response_model: type[BaseModel] | None = None,
    ) -> dict:
        if self.is_mock:
            raise ModelGatewayError("model call requested while mock mode is active")

        user_message = json.dumps(payload, ensure_ascii=False)
        text = self._request_text(system, user_message, max_tokens, temperature=0.45, json_mode=True)
        try:
            # JSON mode usually guarantees syntax, not the business schema. Validate both here so
            # malformed objects never leak into the service layer as successful model responses.
            return self._parse_and_validate(text, response_model)
        except (ModelGatewayError, ValidationError) as first_error:
            schema = response_model.model_json_schema() if response_model else {"type": "object"}
            repair_system = (
                "你是 JSON 结构修复器。请根据 validation_error 和 target_schema 修复"
                "response_to_repair。必须返回符合 target_schema 的目标对象本身；"
                "不要返回 response_to_repair、invalid_response、validation_error 或 target_schema"
                "这些包装字段，不要解释，不要使用 Markdown 代码块。"
            )
            repair_message = json.dumps(
                {
                    "response_to_repair": text,
                    "validation_error": self._validation_summary(first_error),
                    "target_schema": schema,
                },
                ensure_ascii=False,
            )
            repaired = self._request_text(
                repair_system,
                repair_message,
                max_tokens=max_tokens,
                temperature=0,
                json_mode=True,
            )
            try:
                return self._parse_and_validate(repaired, response_model)
            except (ModelGatewayError, ValidationError) as exc:
                raise ModelGatewayError("模型返回内容不符合要求，自动修复后仍缺少必要字段，请重试") from exc

    @classmethod
    def _parse_and_validate(cls, text: str, response_model: type[BaseModel] | None) -> dict:
        value = cls._parse_json(text)
        if response_model is not None:
            response_model.model_validate(value)
        return value

    @staticmethod
    def _validation_summary(exc: Exception) -> list[dict[str, str]] | str:
        if not isinstance(exc, ValidationError):
            return str(exc)
        return [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "error": error["msg"],
            }
            for error in exc.errors(include_url=False, include_input=False)
        ]

    def _request_text(
        self,
        system: str,
        user_message: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> str:
        try:
            if isinstance(self._client, OpenAI):
                request: dict[str, Any] = {
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
                }
                if json_mode:
                    request["response_format"] = {"type": "json_object"}
                try:
                    response = self._client.chat.completions.create(**request)
                except Exception as exc:
                    # OpenAI-compatible providers do not all implement response_format.
                    if not json_mode or not self._json_mode_is_unsupported(exc):
                        raise
                    request.pop("response_format", None)
                    response = self._client.chat.completions.create(**request)
                return response.choices[0].message.content or ""

            if isinstance(self._client, Anthropic):
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                )
                return "".join(block.text for block in response.content if block.type == "text")

            raise ModelGatewayError("model client is unavailable")
        except ModelGatewayError:
            raise
        except Exception as exc:
            raise ModelGatewayError(f"model request failed: {exc}") from exc

    @staticmethod
    def _json_mode_is_unsupported(exc: Exception) -> bool:
        message = str(exc).lower()
        return "response_format" in message or "json_object" in message or "json mode" in message

    @staticmethod
    def _parse_json(text: str) -> dict:
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip().lstrip("\ufeff")
        candidates = [cleaned]
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
        if fenced:
            candidates.append(fenced.group(1).strip())
        extracted = ModelGateway._extract_json_object(cleaned)
        if extracted:
            candidates.append(extracted)

        for candidate in candidates:
            normalized = re.sub(r",\s*([}\]])", r"\1", candidate.strip())
            try:
                parsed = json.loads(normalized, strict=False)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(normalized)
                    if isinstance(parsed, dict):
                        return parsed
                except (ValueError, SyntaxError):
                    continue
        raise ModelGatewayError("model returned invalid JSON")

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        # A balanced scan avoids cutting early when a JSON string itself contains a brace.
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None
