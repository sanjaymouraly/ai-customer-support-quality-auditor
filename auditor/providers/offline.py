from __future__ import annotations


class OfflineProvider:
    name = "offline"

    async def complete(
        self, messages: list[dict], model=None, temperature=0.2, max_tokens=800, **kw
    ) -> str:
        # Mock: return empty JSON for evaluation - deterministic fallback handles it
        # This provider is never actually used for LLM judging - it signals offline mode
        raise RuntimeError(
            "Offline provider does not support LLM completion; use deterministic mode."
        )

    async def health_check(self, model=None):
        return True
