from __future__ import annotations

import json
import time
from typing import Any, cast

import httpx

from agentmesh.core.models.exceptions import ModelProviderError


class GroqStructuredOutputClient:
    """Small Groq adapter for strict JSON-schema chat completions."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        reasoning_effort: str,
        temperature: float,
        max_completion_tokens: int,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
        retry_attempts: int = 3,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self.max_completion_tokens = max_completion_tokens
        self.retry_attempts = retry_attempts
        self._client = httpx.Client(
            base_url=api_base.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    def create_structured_output(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if self.reasoning_effort:
            request_body["reasoning_effort"] = self.reasoning_effort

        response = self._post(request_body)
        content = self._extract_content(response)
        try:
            parsed = cast(object, json.loads(content))
        except json.JSONDecodeError as exc:
            raise ModelProviderError("Groq returned malformed JSON.") from exc
        if not isinstance(parsed, dict):
            raise ModelProviderError("Groq structured output must be a JSON object.")
        return cast(dict[str, Any], parsed)

    def create_text_completion(self, *, messages: list[dict[str, str]]) -> str:
        """Return one plain-text chat completion for a worker agent."""

        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
        }
        if self.reasoning_effort:
            request_body["reasoning_effort"] = self.reasoning_effort
        return self._extract_content(self._post(request_body))

    def _post(self, request_body: dict[str, Any]) -> httpx.Response:
        for attempt in range(self.retry_attempts):
            try:
                response = self._client.post("chat/completions", json=request_body)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                retry_after = exc.response.headers.get("retry-after")
                retryable = status_code == 429 or status_code >= 500
                if retryable and attempt + 1 < self.retry_attempts:
                    delay = self._retry_delay(retry_after, attempt)
                    time.sleep(delay)
                    continue
                detail = f"Groq returned HTTP {status_code}."
                if retry_after:
                    detail = f"{detail} Retry after {retry_after} seconds."
                raise ModelProviderError(
                    detail,
                    retryable=retryable,
                    status_code=status_code,
                    retry_after_seconds=self._parse_retry_after(retry_after),
                ) from exc
            except httpx.HTTPError as exc:
                if attempt + 1 < self.retry_attempts:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise ModelProviderError("Groq is currently unreachable.", retryable=True) from exc
        raise ModelProviderError("Groq retry loop exited unexpectedly.", retryable=True)

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        parsed = GroqStructuredOutputClient._parse_retry_after(retry_after)
        if parsed is not None:
            return min(parsed, 30.0)
        return float(0.5 * (2**attempt))

    @staticmethod
    def _parse_retry_after(retry_after: str | None) -> float | None:
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return None

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        try:
            raw_response = cast(object, response.json())
        except ValueError as exc:
            raise ModelProviderError("Groq returned a non-JSON response.") from exc
        if not isinstance(raw_response, dict):
            raise ModelProviderError("Groq returned an invalid response object.")
        choices = raw_response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelProviderError("Groq returned no completion choices.")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ModelProviderError("Groq returned an invalid completion choice.")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ModelProviderError("Groq returned an invalid completion message.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError("Groq returned an empty completion.")
        return content.strip()

    def close(self) -> None:
        self._client.close()
