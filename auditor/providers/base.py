from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(Exception):
    pass


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
        **kw,
    ) -> str: ...

    async def health_check(self, model: str | None = None) -> bool:
        try:
            await self.complete([{"role": "user", "content": "ping"}], model=model, max_tokens=5)
            return True
        except Exception:
            return False

    def estimate_cost(
        self, prompt_tokens: int, completion_tokens: int, model: str | None = None
    ) -> float:
        return 0.0
