from __future__ import annotations

import json
import os

from tenacity import retry, stop_after_attempt, wait_exponential


def _retry_attempts():
    try:
        return max(1, min(int(os.getenv("PROVIDER_RETRY_ATTEMPTS", "2")), 5))
    except ValueError:
        return 2


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        max_tokens: int | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        self.default_model = default_model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.timeout = timeout
        self.max_tokens = max_tokens
        if headers is None:
            try:
                headers = json.loads(os.getenv("OPENAI_HEADERS_JSON", "{}"))
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
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout: int | None = None,
        response_format: dict | None = None,
        **kw,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        from openai import AsyncOpenAI

        timeout = timeout or self.timeout or int(os.getenv("REQUEST_TIMEOUT_S", "30"))
        client = AsyncOpenAI(
            api_key=self.api_key,
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
            if response_format:
                request["response_format"] = response_format
            resp = await client.chat.completions.create(**request)
            return resp.choices[0].message.content or ""

        try:
            return await _call()
        finally:
            await client.close()

    async def list_models(self) -> list[str]:
        if not self.api_key:
            raise RuntimeError("Provider credentials are not configured")
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key,
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
