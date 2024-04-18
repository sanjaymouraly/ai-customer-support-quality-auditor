from __future__ import annotations

import json
import os

from tenacity import retry, stop_after_attempt, wait_exponential


def _retry_attempts():
    try:
        return max(1, min(int(os.getenv("PROVIDER_RETRY_ATTEMPTS", "2")), 5))
    except ValueError:
        return 2


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        max_tokens: int | None = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.default_model = (
            default_model or os.getenv("ANTHROPIC_MODEL") or "claude-3-5-sonnet-20241022"
        )
        self.base_url = base_url or os.getenv("ANTHROPIC_BASE_URL") or None
        self.timeout = timeout
        self.max_tokens = max_tokens
        if headers is None:
            try:
                headers = json.loads(os.getenv("ANTHROPIC_HEADERS_JSON", "{}"))
            except json.JSONDecodeError:
                headers = {}
        self.default_headers = {
            str(k): str(v)
            for k, v in (headers or {}).items()
            if "\r" not in str(k) + str(v) and "\n" not in str(k) + str(v)
        }

    async def complete(
        self, messages: list[dict], model=None, temperature=0.2, max_tokens=1200, timeout=None, **kw
    ) -> str:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        import anthropic

        timeout = timeout or self.timeout or int(os.getenv("REQUEST_TIMEOUT_S", "30"))
        client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            max_retries=0,
            default_headers=self.default_headers,
        )
        m = model or self.default_model
        # convert messages: anthropic expects alternating user/assistant, no system; use system param
        system = None
        conv = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                conv.append(msg)

        @retry(
            stop=stop_after_attempt(_retry_attempts()),
            wait=wait_exponential(multiplier=1, min=1, max=6),
            reraise=True,
        )
        async def _call():
            # anthropic sdk uses messages.create
            resp = await client.messages.create(
                model=m,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system or "",
                messages=conv,
            )
            # content is list of blocks
            txt = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    txt += block.text
            return txt

        try:
            return await _call()
        finally:
            await client.close()

    async def list_models(self) -> list[str]:
        if not self.api_key:
            raise RuntimeError("Provider credentials are not configured")
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=10,
            max_retries=0,
            default_headers=self.default_headers,
        )
        try:
            response = await client.models.list(limit=100)
            return sorted(item.id for item in response.data)
        finally:
            await client.close()

    async def health_check(self, model=None):
        try:
            await self.complete([{"role": "user", "content": "Say OK"}], max_tokens=5, timeout=10)
            return True
        except Exception:
            return False
