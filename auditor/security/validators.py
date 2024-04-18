from __future__ import annotations

import os
import re
from pathlib import Path

MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "10")))
ALLOWED_EXT = {".md", ".txt", ".json", ".pdf", ".csv", ".jsonl"}


def validate_upload(filename: str, size_bytes: int):
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"File type {ext} not allowed. Allowed: {ALLOWED_EXT}")
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"File too large: {size_bytes} bytes exceeds {MAX_UPLOAD_MB} MB")


def sanitize_filename(name: str) -> str:
    # Keep only a single basename, normalize traversal markers and dot-only names.
    base = Path(name.replace("\\", "/")).name
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", base).replace("..", "_")
    safe = safe.strip("._") or "upload"
    return safe[:120]


def strip_injection(text: str) -> str:
    # Prevent prompt injection: strip system-like directives
    patterns = [r"ignore previous", r"system:", r"you are now", r"disregard policy"]
    for p in patterns:
        text = re.sub(p, "[filtered]", text, flags=re.I)
    return text


def sanitize_csv_value(v: str) -> str:
    # Prefix cells that Excel/LibreOffice may interpret as formulas, including when
    # whitespace or control characters precede the formula sigil.
    if not v:
        return v
    trimmed = v.lstrip(" \t\r\n\ufeff")
    if v[0] in "\t\r\n" or (trimmed and trimmed[0] in ("=", "+", "-", "@", "|")):
        return "'" + v
    return v


def redact_pii(text: str) -> str:
    # Partial output-side redaction for LLM-generated explanations/evidence; this is not
    # input anonymization, and the underlying audit record still contains submitted text.
    text = re.sub(r"\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b", "[REDACTED_CARD]", text)
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", text)
    text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[REDACTED_EMAIL]",
        text,
    )
    text = re.sub(
        r"(?<!\d)(?:\+?91[-.\s]?)?[6-9]\d{4}[-.\s]?\d{5}(?!\d)",
        "[REDACTED_PHONE]",
        text,
    )
    return text
