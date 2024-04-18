from __future__ import annotations

import json
from pathlib import Path

from .models import PolicyDocument

POLICY_DIR = Path(__file__).resolve().parents[2] / "data" / "policies"

_builtin_policies: list[PolicyDocument] | None = None


def load_policies_from_dir(pdir: Path | None = None) -> list[PolicyDocument]:
    global _builtin_policies
    d = Path(pdir) if pdir else POLICY_DIR
    docs: list[PolicyDocument] = []
    if not d.exists():
        return docs
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            docs.append(PolicyDocument(**data))
        except Exception as e:
            print(f"Failed to load {f}: {e}")
    _builtin_policies = docs
    return docs


def get_all_policies() -> list[PolicyDocument]:
    global _builtin_policies
    if _builtin_policies is None:
        return load_policies_from_dir()
    return _builtin_policies


def get_policy_map() -> dict[str, PolicyDocument]:
    # Active versions only; latest effective date breaks ties deterministically.
    active = [p for p in get_all_policies() if p.status == "active"]
    out: dict[str, PolicyDocument] = {}
    for p in sorted(active, key=lambda d: (d.effective_date, d.version)):
        out[p.policy_id] = p
    return out


def get_policy_versions(policy_id: str) -> list[PolicyDocument]:
    return sorted(
        [p for p in get_all_policies() if p.policy_id == policy_id],
        key=lambda d: (d.effective_date, d.version),
        reverse=True,
    )


def get_policy(policy_id: str) -> PolicyDocument | None:
    return get_policy_map().get(policy_id)
