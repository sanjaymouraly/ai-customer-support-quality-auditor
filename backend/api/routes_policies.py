from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from auditor.policies.ingest import (
    activate_policy_version,
    ingest_markdown,
    ingest_pdf_bytes,
    save_policy,
)
from auditor.policies.models import PolicyDocument
from auditor.policies.store import (
    get_all_policies,
    get_policy_map,
    get_policy_versions,
    load_policies_from_dir,
)
from auditor.security.validators import validate_upload

from ..database import get_db
from ..models import PolicyRecord

router = APIRouter(prefix="/api/policies", tags=["policies"])
POLICY_DIR = Path("data/policies")


@router.get("/")
def list_policies(db: Session = Depends(get_db)):
    # Prefer file store but also DB
    policies = get_all_policies()
    if policies:
        return [
            {
                "policy_id": p.policy_id,
                "title": p.title,
                "version": p.version,
                "effective_date": p.effective_date,
                "status": p.status,
                "category": p.category,
                "sections": len(p.sections),
            }
            for p in policies
        ]
    rows = db.query(PolicyRecord).all()
    return [
        {
            "policy_id": r.policy_id,
            "title": r.title,
            "version": r.version,
            "status": r.status,
            "category": r.category,
        }
        for r in rows
    ]


@router.get("/{policy_id}")
def get_policy(policy_id: str):
    mp = get_policy_map()
    p = mp.get(policy_id)
    if not p:
        raise HTTPException(404, "Policy not found")
    return p.model_dump()


@router.get("/{policy_id}/versions")
def list_policy_versions(policy_id: str):
    versions = get_policy_versions(policy_id)
    if not versions:
        raise HTTPException(404, "Policy not found")
    return [
        {
            "policy_id": p.policy_id,
            "title": p.title,
            "version": p.version,
            "effective_date": p.effective_date,
            "status": p.status,
            "category": p.category,
            "sections": len(p.sections),
        }
        for p in versions
    ]


@router.get("/{policy_id}/compare")
def compare_policy_versions(policy_id: str, left: str, right: str):
    versions = {p.version: p for p in get_policy_versions(policy_id)}
    if left not in versions or right not in versions:
        raise HTTPException(404, "Requested policy version not found")
    left_sections = {s.section_id: s for s in versions[left].sections}
    right_sections = {s.section_id: s for s in versions[right].sections}
    ids = sorted(set(left_sections) | set(right_sections))
    diff = []
    for sid in ids:
        a = left_sections.get(sid)
        b = right_sections.get(sid)
        if not a or not b or a.content != b.content or a.title != b.title:
            diff.append(
                {
                    "section_id": sid,
                    "left": a.model_dump() if a else None,
                    "right": b.model_dump() if b else None,
                }
            )
    return {
        "policy_id": policy_id,
        "left_version": left,
        "right_version": right,
        "differences": diff,
    }


@router.post("/{policy_id}/activate/{version}")
def activate_version(policy_id: str, version: str):
    try:
        active = activate_policy_version(policy_id, version, POLICY_DIR)
        load_policies_from_dir(POLICY_DIR)
        return {
            "policy_id": active.policy_id,
            "active_version": active.version,
            "status": active.status,
        }
    except ValueError as e:
        raise HTTPException(404, "Policy version not found") from e


@router.post("/ingest")
async def ingest_policy(
    title: str = Form(...),
    policy_id: str = Form(...),
    category: str = Form(...),
    version: str = Form("1.0"),
    effective_date: str = Form("2024-01-01"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    from auditor.security.validators import MAX_UPLOAD_MB

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    chunks = []
    total = 0
    while True:
        chunk = await file.read(min(64 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"Upload exceeds {MAX_UPLOAD_MB} MB limit")
    content = b"".join(chunks)
    if len(content) == 0:
        raise HTTPException(400, "Empty file")
    try:
        validate_upload(file.filename or "upload", len(content))
    except ValueError as e:
        raise HTTPException(415, str(e)) from e
    ext = Path(file.filename or "").suffix.lower()
    try:
        if ext == ".pdf":
            doc = ingest_pdf_bytes(
                content, policy_id, title, category, version=version, effective_date=effective_date
            )
        elif ext == ".json":
            data = json.loads(content.decode("utf-8"))
            doc = PolicyDocument(**data)
            if doc.policy_id != policy_id:
                raise ValueError("JSON policy_id must match the submitted policy_id")
        elif ext in (".md", ".txt"):
            txt = content.decode("utf-8", errors="ignore")
            doc = ingest_markdown(
                txt, policy_id, title, category, version=version, effective_date=effective_date
            )
        else:
            txt = content.decode("utf-8", errors="ignore")
            doc = ingest_markdown(
                txt, policy_id, title, category, version=version, effective_date=effective_date
            )
        # save
        save_policy(doc, POLICY_DIR)
        # reload store
        load_policies_from_dir(POLICY_DIR)
        # also DB
        existing = db.query(PolicyRecord).filter(PolicyRecord.policy_id == policy_id).first()
        if existing:
            existing.title = doc.title
            existing.version = doc.version
            existing.category = doc.category
            existing.content = doc.model_dump()
        else:
            db.add(
                PolicyRecord(
                    policy_id=doc.policy_id,
                    title=doc.title,
                    version=doc.version,
                    category=doc.category,
                    content=doc.model_dump(),
                )
            )
        db.commit()
        return {"ingested": policy_id, "sections": len(doc.sections)}
    except Exception as e:
        raise HTTPException(400, f"Policy ingestion failed ({type(e).__name__})") from e


@router.post("/ingest/text")
def ingest_text(payload: dict, db: Session = Depends(get_db)):
    policy_id = payload.get("policy_id")
    title = payload.get("title", "Untitled")
    category = payload.get("category", "general")
    content = payload.get("content", "")
    if len(content) > 200_000:
        raise HTTPException(413, "Text policy content exceeds 200,000 characters")
    version = payload.get("version", "1.0")
    effective_date = payload.get("effective_date", "2024-01-01")
    if not policy_id or not content:
        raise HTTPException(400, "policy_id and content required")
    doc = ingest_markdown(
        content, policy_id, title, category, version=version, effective_date=effective_date
    )
    save_policy(doc, POLICY_DIR)
    load_policies_from_dir(POLICY_DIR)
    db.query(PolicyRecord).filter(PolicyRecord.policy_id == policy_id).delete()
    db.add(
        PolicyRecord(
            policy_id=doc.policy_id,
            title=doc.title,
            version=doc.version,
            category=doc.category,
            content=doc.model_dump(),
        )
    )
    db.commit()
    return {"ingested": policy_id}


@router.post("/retrieve")
def retrieve_policy(payload: dict):
    from auditor.policies.retrieval import retrieve

    query = payload.get("query", "")
    policy_ids = payload.get("policy_ids")
    top_k = payload.get("top_k", 5)
    if not query:
        raise HTTPException(400, "query required")
    res = retrieve(query, policy_ids, top_k)
    return {"results": [r.model_dump() for r in res]}
