from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auditor.providers.generation import build_generation_messages, generate_candidate_response
from auditor.providers.manager import (
    PROVIDER_META,
    PROVIDERS,
    delete_connection,
    list_connections,
    mark_test_result,
    public_connection,
    resolve_provider_config,
    save_connection,
)
from auditor.providers.registry import get_provider, provider_health_env

from ..database import get_db
from ..services.projects import resolve_project
from .schemas import GenerateRequest

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
def providers():
    return {
        "available": list(PROVIDERS),
        "env_configured": provider_health_env(),
        "connection_profiles": list_connections(),
        "metadata": PROVIDER_META,
        "credential_notice": "API keys are stored server-side (encrypted at rest) and are never returned to the browser. Environment variables remain supported and take effect when no saved connection overrides them.",
    }


@router.get("/connections")
def connections():
    return {"connections": list_connections()}


@router.put("/connections/{provider}")
def upsert_connection(provider: str, payload: dict[str, Any]):
    try:
        row = save_connection(provider, payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"saved": True, "connection": row}


@router.delete("/connections/{provider}")
def remove_connection(provider: str):
    if provider.lower().strip() == "offline":
        raise HTTPException(422, "Offline mode has no connection settings")
    if not delete_connection(provider.lower().strip()):
        raise HTTPException(404, "No saved connection for this provider")
    return {"deleted": provider, "connection": public_connection(provider)}


@router.post("/test")
async def test_provider(payload: dict):
    name = str(payload.get("provider", "offline")).lower().strip()
    if name not in PROVIDERS:
        raise HTTPException(422, "Unknown provider")
    if name == "offline":
        return {"provider": "offline", "ok": True, "model": "rule-engine-v1"}
    overrides = {
        "api_key": payload.get("api_key") or None,
        "base_url": payload.get("base_url") or None,
        "default_model": payload.get("model") or None,
    }
    try:
        prov = get_provider(name, {k: v for k, v in overrides.items() if v})
        ok = await prov.health_check(payload.get("model") or None)
        if ok:
            mark_test_result(name, True)
        return {
            "provider": name,
            "ok": bool(ok),
            "model": payload.get("model")
            or getattr(prov, "default_model", None)
            or resolve_provider_config(name).get("default_model"),
            "saved_profile": bool(public_connection(name).get("configured")),
        }
    except Exception as e:
        # Provider SDK exceptions can contain request metadata; disclose only the class.
        return {
            "provider": name,
            "ok": False,
            "error": f"Provider request failed ({type(e).__name__}). Verify credentials, model, endpoint, timeout, and network access.",
        }


@router.get("/usage")
def provider_usage(db: Session = Depends(get_db)):
    from backend.services.usage import usage_summary

    return usage_summary(db)


@router.get("/models")
async def discover_models(provider: str, base_url: str | None = None):
    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        raise HTTPException(422, "Unknown provider")
    try:
        overrides = {"base_url": base_url} if base_url else {}
        prov = get_provider(provider, overrides)
        if not hasattr(prov, "list_models"):
            return {
                "provider": provider,
                "models": [],
                "error": "Model discovery is not supported by this adapter.",
            }
        models = await prov.list_models()
        return {"provider": provider, "models": models}
    except Exception as e:
        return {
            "provider": provider,
            "models": [],
            "error": f"Model discovery failed ({type(e).__name__}); verify server-side credentials and endpoint.",
        }


@router.post("/generate")
async def generate(payload: GenerateRequest, db: Session = Depends(get_db)):
    """Generate a candidate response with an explicitly selected model.

    This convenience endpoint is for matched comparison and drafting. It is not used to
    generate a response inside the audit endpoint, keeping responder and evaluator roles
    visibly separate.
    """

    if payload.provider == "offline":
        raise HTTPException(422, "Choose a model provider; offline mode only evaluates.")
    try:
        project = resolve_project(db, payload.project_id)
    except LookupError as exc:
        raise HTTPException(422, str(exc)) from exc
    policy_ids = payload.policy_ids or (project.policy_ids or None)
    try:
        provider = get_provider(payload.provider, {})
    except Exception as exc:
        raise HTTPException(400, "Provider configuration is invalid") from exc
    from backend.services.usage import reserve_provider_usage

    # Reserve against the full generation prompt before making the call.
    policy_text = ""
    try:
        from auditor.policies.retrieval import retrieve_for_case

        policy_text = "\n".join(
            item.excerpt
            for item in retrieve_for_case(
                payload.customer_message,
                "",
                policy_ids,
                top_k=4,
                category=payload.category,
            )
        )
    except Exception:
        policy_text = ""
    prompt_text = "\n".join(
        [
            payload.customer_message,
            json.dumps(payload.facts, ensure_ascii=False),
            payload.category or "",
            policy_text,
        ]
    )
    try:
        reservation = reserve_provider_usage(
            db,
            payload.provider,
            payload.model or getattr(provider, "default_model", None),
            prompt_text,
            output_tokens=payload.max_tokens,
        )
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc
    try:
        text = await generate_candidate_response(
            provider,
            customer_message=payload.customer_message,
            facts=payload.facts,
            policy_ids=policy_ids,
            category=payload.category,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except Exception as exc:
        raise HTTPException(
            502,
            f"Generation failed ({type(exc).__name__}). Check the provider connection and model.",
        ) from exc
    return {
        "provider": payload.provider,
        "model": payload.model or getattr(provider, "default_model", None),
        "response": text,
        "reserved_tokens": reservation.estimated_total_tokens,
        "estimated_cost_usd": reservation.estimated_cost_usd,
        "note": "Generated text must be audited before use. The responder is not the evaluator unless explicitly selected as the judge.",
    }


@router.post("/prompt-preview")
def prompt_preview(payload: GenerateRequest):
    """Return the exact responder prompt shape without calling a provider (safe introspection)."""

    if payload.provider == "offline":
        raise HTTPException(422, "Choose a model provider.")
    messages = build_generation_messages(
        payload.customer_message,
        payload.facts,
        [],
        category=payload.category,
    )
    return {"messages": messages, "note": "Policy excerpts are retrieved at generation time."}
