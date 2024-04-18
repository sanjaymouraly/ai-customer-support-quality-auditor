from __future__ import annotations

import json
from pathlib import Path

from .models import Case

SYNTHETIC_PATH = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "cases.json"


def load_cases(path: Path | None = None) -> list[Case]:
    p = Path(path) if path else SYNTHETIC_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [Case(**row) for row in data]


def filter_cases(
    cases: list[Case],
    category: str | None = None,
    severity: str | None = None,
    label: str | None = None,
    search: str | None = None,
):
    out = cases
    if category:
        out = [c for c in out if c.category == category]
    if severity:
        out = [c for c in out if c.severity == severity]
    if label:
        out = [c for c in out if c.label == label]
    if search:
        q = search.lower()
        out = [
            c
            for c in out
            if q in c.customer_message.lower()
            or q in c.candidate_response.lower()
            or q in c.case_id.lower()
        ]
    return out
