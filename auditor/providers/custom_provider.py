from __future__ import annotations

import json
import os

from tenacity import retry, stop_after_attempt, wait_exponential


def _retry_attempts():
    try:
        return max(1, min(int(os.getenv("PROVIDER_RETRY_ATTEMPTS", "2")), 5))
    except ValueError:
        return 2


class CustomProvider:
    name = "custom"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        max_tokens: int | None = None,
    ):
        self.api_key = api_key or os.getenv("CUSTOM_API_KEY")
        self.base_url = base_url or os.getenv("CUSTOM_BASE_URL") or "http://localhost:11434/v1"
        self.default_model = default_model or os.getenv("CUSTOM_MODEL") or "llama3.2"
        self.timeout = timeout
        self.max_tokens = max_tokens
        if headers is None:
            try:
                headers = json.loads(os.getenv("CUSTOM_HEADERS_JSON", "{}"))
            except json.JSONDecodeError:
                headers = {}
        self.default_headers = {
            str(k): str(v)
            for k, v in (headers or {}).items()
            if "\r" not in str(k) + str(v) and "\n" not in str(k) + str(v)
        }

    async def complete(
        self,
        messages: list[dict],
        model=None,
        temperature=0.2,
        max_tokens=1200,
        timeout=None,
        response_format: dict | None = None,
        **kw,
    ) -> str:
        from openai import AsyncOpenAI

        timeout = timeout or self.timeout or int(os.getenv("REQUEST_TIMEOUT_S", "30"))
        client = AsyncOpenAI(
            api_key=self.api_key or "ollama",
            base_url=self.base_url,
            timeout=timeout,
            default_headers=self.default_headers,
            max_retries=0,
        )
        m = model or self.default_model

        @retry(
            stop=stop_after_attempt(_retry_attempts()),
            wait=wait_exponential(multiplier=1, min=1, max=6),
            reraise=True,
        )
        async def _call():
            request: dict = {
                "model": m,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            # Ollama and many OpenAI-compatible servers support JSON mode. Providers that
            # do not understand the field will reject the call, so callers opt in only
            # where the endpoint is known to support it.
            if response_format:
                request["response_format"] = response_format
            resp = await client.chat.completions.create(**request)
            return resp.choices[0].message.content or ""

        try:
            return await _call()
        finally:
            await client.close()

    async def list_models(self) -> list[str]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key or "ollama",
            base_url=self.base_url,
            timeout=10,
            default_headers=self.default_headers,
            max_retries=0,
        )
        try:
            response = await client.models.list()
            return sorted(item.id for item in response.data)
        finally:
            await client.close()

    async def health_check(self, model=None):
        try:
            await self.complete(
                [{"role": "user", "content": "Say OK"}], model=model, max_tokens=5, timeout=10
            )
            return True
        except Exception:
            return False


class OllamaProvider(CustomProvider):
    name = "ollama"

    def __init__(self, api_key=None, base_url=None, default_model=None, timeout=None, max_tokens=None):
        super().__init__(
            api_key=api_key or os.getenv("OLLAMA_API_KEY") or "ollama",
            base_url=base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1",
            default_model=default_model or os.getenv("OLLAMA_MODEL") or "llama3.2",
            timeout=timeout,
            max_tokens=max_tokens,
        )


class OpenRouterProvider(CustomProvider):
    name = "openrouter"

    def __init__(
        self,
        api_key=None,
        base_url=None,
        default_model=None,
        headers=None,
        timeout=None,
        max_tokens=None,
    ):
        if headers is None:
            try:
                headers = json.loads(os.getenv("OPENROUTER_HEADERS_JSON", "{}"))
            except json.JSONDecodeError:
                headers = {}
        super().__init__(
            api_key=api_key or os.getenv("OPENROUTER_API_KEY"),
            base_url=base_url or os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
            default_model=default_model
            or os.getenv("OPENROUTER_MODEL")
            or "anthropic/claude-3.5-sonnet",
            headers=headers,
            timeout=timeout,
            max_tokens=max_tokens,
        )
