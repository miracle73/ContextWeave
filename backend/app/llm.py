"""Streaming OpenRouter client (OpenAI-compatible SSE)."""

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from .config import settings


class LLMError(Exception):
    def __init__(self, code: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after


class LLM(Protocol):
    def stream(self, messages: list[dict], model: str, max_tokens: int) -> AsyncIterator[str]: ...


class OpenRouterClient:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))

    async def stream(self, messages: list[dict], model: str, max_tokens: int) -> AsyncIterator[str]:
        if not settings.openrouter_api_key:
            raise LLMError("config", "OPENROUTER_API_KEY is not set on the server")
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "HTTP-Referer": settings.app_url,
            "X-Title": "ContextWeave",
        }
        body = {"model": model, "messages": messages, "stream": True,
                "max_tokens": max_tokens, "temperature": 0.4}
        try:
            # Leaving this context (e.g. on task cancellation) closes the connection, which aborts the stream upstream.
            async with self.client.stream("POST", f"{settings.openrouter_base_url}/chat/completions",
                                          json=body, headers=headers) as r:
                if r.status_code != 200:
                    await r.aread()
                    _raise_for(r)
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # SSE comments such as ": OPENROUTER PROCESSING"
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    obj = json.loads(data)
                    if "error" in obj:
                        raise LLMError("provider_error", obj["error"].get("message", "Provider error"))
                    choices = obj.get("choices") or []
                    delta = (choices[0].get("delta") or {}).get("content") if choices else None
                    if delta:
                        yield delta
        except httpx.HTTPError as e:
            raise LLMError("network", f"OpenRouter connection failed: {e}") from e


def _raise_for(r: httpx.Response) -> None:
    try:
        msg = r.json().get("error", {}).get("message", r.text)
    except ValueError:
        msg = r.text
    if r.status_code == 429:
        ra = r.headers.get("retry-after")
        raise LLMError("rate_limited", "Model rate limit reached, retry shortly", float(ra) if ra and ra.isdigit() else None)
    if r.status_code in (401, 403):
        raise LLMError("auth", "OpenRouter rejected the API key")
    if r.status_code == 402:
        raise LLMError("credits", "OpenRouter account has insufficient credits")
    raise LLMError("provider_error", f"OpenRouter error {r.status_code}: {msg[:200]}")
