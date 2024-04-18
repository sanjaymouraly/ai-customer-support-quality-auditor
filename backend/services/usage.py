"""Conservative estimated token/spend budget for external judge calls.

Token counts use a documented rough estimate (four characters per token) plus a prompt overhead.
Costs are estimated only when the operator supplies a price schedule; no prices are hard-coded.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import ProviderUsage

_lock = threading.Lock()
OUTPUT_TOKEN_RESERVE = 1500


def configured_attempts() -> int:
    try:
        return max(1, min(int(os.getenv("PROVIDER_RETRY_ATTEMPTS", "2")), 5))
    except ValueError:
        return 2


def provider_prices() -> dict:
    raw = os.getenv("PROVIDER_PRICING_JSON", "").strip()
    prices: dict = {}
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for provider, price in data.items():
                    if not isinstance(price, dict):
                        continue
                    inp = float(price.get("input_usd_per_1m", -1))
                    out = float(price.get("output_usd_per_1m", -1))
                    if inp >= 0 and out >= 0:
                        prices[provider.lower()] = {
                            "input_usd_per_1m": inp,
                            "output_usd_per_1m": out,
                        }
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    # Saved connection pricing is an operator-supplied current rate schedule and takes
    # precedence over the environment JSON for that provider.
    try:
        from auditor.providers.manager import saved_pricing

        prices.update(saved_pricing())
    except Exception:
        pass
    return prices


def reserve_provider_usage(
    db: Session,
    provider: str,
    model: str | None,
    prompt_text: str,
    output_tokens: int = OUTPUT_TOKEN_RESERVE,
) -> ProviderUsage:
    single_attempt_input = max(1, math.ceil((len(prompt_text) + 1800) / 4))
    attempts = configured_attempts()
    # Reserve for every possible provider attempt so retries cannot bypass the daily cap.
    input_tokens = single_attempt_input * attempts
    output_tokens = output_tokens * attempts
    total = input_tokens + output_tokens
    today = datetime.now(UTC).date().isoformat()
    price = provider_prices().get(provider.lower())
    estimated_cost = None
    if price:
        estimated_cost = (
            input_tokens * price["input_usd_per_1m"] + output_tokens * price["output_usd_per_1m"]
        ) / 1_000_000
    with _lock:
        used_tokens = int(
            db.query(func.coalesce(func.sum(ProviderUsage.estimated_total_tokens), 0))
            .filter(func.date(ProviderUsage.created_at) == today)
            .scalar()
            or 0
        )
        if used_tokens + total > settings.daily_token_budget:
            raise ValueError(
                "Daily estimated token budget exceeded; increase DAILY_TOKEN_BUDGET or wait for UTC day reset."
            )
        if settings.daily_spend_limit_usd > 0:
            if estimated_cost is None:
                raise ValueError(
                    "DAILY_SPEND_LIMIT_USD is enabled but no PROVIDER_PRICING_JSON entry exists for this provider."
                )
            used_cost = (
                db.query(func.coalesce(func.sum(ProviderUsage.estimated_cost_usd), 0.0))
                .filter(func.date(ProviderUsage.created_at) == today)
                .scalar()
                or 0.0
            )
            if float(used_cost) + estimated_cost > settings.daily_spend_limit_usd:
                raise ValueError("Daily estimated spend limit exceeded; request not sent.")
        record = ProviderUsage(
            provider=provider,
            model=model,
            estimated_input_tokens=input_tokens,
            reserved_output_tokens=output_tokens,
            estimated_total_tokens=total,
            estimated_cost_usd=estimated_cost,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record


def usage_summary(db: Session) -> dict:
    today = datetime.now(UTC).date().isoformat()
    q = db.query(ProviderUsage).filter(func.date(ProviderUsage.created_at) == today)
    rows = q.all()
    return {
        "date_utc": today,
        "estimated_tokens_reserved": sum(r.estimated_total_tokens for r in rows),
        "estimated_input_tokens": sum(r.estimated_input_tokens for r in rows),
        "reserved_output_tokens": sum(r.reserved_output_tokens for r in rows),
        "daily_token_budget": settings.daily_token_budget,
        "daily_spend_limit_usd": settings.daily_spend_limit_usd or None,
        "estimated_cost_usd": sum(r.estimated_cost_usd or 0 for r in rows)
        if rows and any(r.estimated_cost_usd is not None for r in rows)
        else None,
        "cost_estimate_note": "Estimated only; tokenization and provider billing can differ. Cost omitted unless operator configures PROVIDER_PRICING_JSON.",
        "calls": len(rows),
    }
