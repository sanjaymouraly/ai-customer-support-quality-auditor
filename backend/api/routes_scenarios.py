"""Local, user-authored scenarios kept separate from the immutable public benchmark."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from auditor.datasets.models import Case

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])
DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "custom_scenarios.json"


def _load() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("scenario file must contain a JSON array")
        return data
    except Exception as exc:
        raise HTTPException(500, "Custom scenario store is corrupt") from exc


def _save(rows: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, DATA_FILE)


def _valid_id(case_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", case_id))


@router.get("")
def list_custom_scenarios():
    return {"total": len(_load()), "scenarios": _load()}


@router.post("")
def create_scenario(payload: Case):
    if not _valid_id(payload.case_id):
        raise HTTPException(422, "case_id may contain only letters, digits, underscore, and hyphen")
    rows = _load()
    if any(row.get("case_id") == payload.case_id for row in rows):
        raise HTTPException(409, "case_id already exists")
    data = payload.model_dump()
    data.setdefault("evaluation_metadata", {})
    data["evaluation_metadata"] = {
        **data["evaluation_metadata"],
        "label_provenance": "user_authored_reference_not_human_reviewed",
        "dataset": "local_custom",
    }
    rows.append(data)
    _save(rows)
    return {"created": payload.case_id, "scenario": data}


@router.put("/{case_id}")
def update_scenario(case_id: str, payload: Case):
    if not _valid_id(case_id) or payload.case_id != case_id:
        raise HTTPException(422, "path and body case_id must match and be path-safe")
    rows = _load()
    for idx, row in enumerate(rows):
        if row.get("case_id") == case_id:
            data = payload.model_dump()
            data["evaluation_metadata"] = {
                **data.get("evaluation_metadata", {}),
                "label_provenance": "user_authored_reference_not_human_reviewed",
                "dataset": "local_custom",
            }
            rows[idx] = data
            _save(rows)
            return {"updated": case_id, "scenario": data}
    raise HTTPException(404, "Custom scenario not found")


@router.delete("/{case_id}")
def delete_scenario(case_id: str):
    if not _valid_id(case_id):
        raise HTTPException(422, "case_id is not valid")
    rows = _load()
    kept = [row for row in rows if row.get("case_id") != case_id]
    if len(kept) == len(rows):
        raise HTTPException(404, "Custom scenario not found")
    _save(kept)
    return {"deleted": case_id}
