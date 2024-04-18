from __future__ import annotations

import json
import re
from pathlib import Path

from .models import PolicyDocument, PolicySection


def ingest_markdown(
    text: str,
    policy_id: str,
    title: str,
    category: str,
    version: str = "1.0",
    effective_date: str = "2024-01-01",
) -> PolicyDocument:
    sections: list[PolicySection] = []
    # split by markdown headers
    chunks = re.split(r"(?m)^##\s+", text)
    if chunks[0].strip() == "" or text.lstrip().startswith("#"):
        chunks = chunks[1:]
    else:
        # first chunk is intro before first ##
        intro = chunks[0].strip()
        if intro:
            sections.append(
                PolicySection(
                    section_id=f"{policy_id}-intro",
                    title="Introduction",
                    content=intro,
                    keywords=_keywords(intro),
                )
            )
        chunks = chunks[1:]
    for idx, ch in enumerate(chunks):
        lines = ch.strip().splitlines()
        if not lines:
            continue
        title_ = lines[0].strip()
        content = "\n".join(lines[1:]).strip()
        if not content:
            content = title_
            title_ = f"Section {idx + 1}"
        sections.append(
            PolicySection(
                section_id=f"{policy_id}-s{idx + 1}",
                title=title_,
                content=content,
                keywords=_keywords(content),
            )
        )
    return PolicyDocument(
        policy_id=policy_id,
        title=title,
        version=version,
        effective_date=effective_date,
        category=category,
        sections=sections,
    )


def ingest_txt(text: str, policy_id: str, title: str, category: str, **kw) -> PolicyDocument:
    return ingest_markdown(text, policy_id, title, category, **kw)


def ingest_json(path: Path) -> PolicyDocument:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PolicyDocument(**data)


def ingest_pdf_bytes(
    data: bytes,
    policy_id: str,
    title: str,
    category: str,
    version: str = "1.0",
    effective_date: str = "2024-01-01",
) -> PolicyDocument:
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > 100:
            raise ValueError("PDF exceeds 100-page ingestion limit")
        txt = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        if len(txt) > 200_000:
            raise ValueError("Extracted PDF text exceeds 200,000 characters")
        if not txt.strip():
            txt = "Empty PDF extracted."
        return ingest_markdown(
            txt, policy_id, title, category, version=version, effective_date=effective_date
        )
    except Exception as e:
        raise ValueError(f"PDF ingest failed: {e}") from e


def _keywords(text: str, n=8) -> list[str]:
    import re

    stop = {
        "the",
        "and",
        "or",
        "a",
        "an",
        "to",
        "for",
        "of",
        "in",
        "on",
        "is",
        "are",
        "be",
        "will",
        "with",
        "you",
        "we",
        "our",
        "your",
        "as",
        "by",
        "at",
        "if",
        "it",
        "this",
        "that",
    }
    words = re.findall(r"[a-z]{3,}", text.lower())
    freq = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq, key=lambda k: -freq[k])[:n]


def save_policy(doc: PolicyDocument, dest_dir: Path):
    # Policy IDs must be path-safe. Retain prior versions and mark them inactive before save.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", doc.policy_id):
        raise ValueError("policy_id may contain only letters, digits, underscore, and hyphen")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", doc.version):
        raise ValueError("version contains unsupported characters")
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{doc.policy_id}__v{doc.version}.json"
    path = dest_dir / filename
    if path.exists():
        existing_data = json.loads(path.read_text(encoding="utf-8"))
        existing_doc = PolicyDocument(**existing_data)
        candidate = doc.model_copy(update={"status": existing_doc.status})
        if existing_doc.model_dump() != candidate.model_dump():
            raise ValueError(
                "Policy versions are immutable; increment version to publish changed content"
            )
        return path
    # Deactivate the old version only after the new version has passed validation.
    for existing in dest_dir.glob("*.json"):
        try:
            data = json.loads(existing.read_text(encoding="utf-8"))
            if data.get("policy_id") == doc.policy_id and data.get("status") == "active":
                data["status"] = "deprecated"
                existing.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            continue
    doc.status = "active"
    path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return path


def activate_policy_version(policy_id: str, version: str, dest_dir: Path) -> PolicyDocument:
    # Resolve and validate the target before mutating any file. A missing version must
    # not deactivate the currently active policy as a side effect of a failed request.
    candidates = []
    for existing in dest_dir.glob("*.json"):
        try:
            data = json.loads(existing.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("policy_id") == policy_id:
            candidates.append((existing, data))
    target_data = next(
        (data for _path, data in candidates if data.get("version") == version), None
    )
    if target_data is None:
        raise ValueError("policy version not found")

    target = PolicyDocument(**target_data)
    for existing, data in candidates:
        data["status"] = "active" if data.get("version") == version else "deprecated"
        existing.write_text(json.dumps(data, indent=2), encoding="utf-8")
    target.status = "active"
    return target
