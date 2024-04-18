import pytest

from auditor.policies.ingest import activate_policy_version, ingest_markdown, save_policy
from auditor.policies.store import load_policies_from_dir


def test_policy_versions_are_retained_and_activated(tmp_path):
    first = ingest_markdown(
        "## Eligibility\nRefunds are allowed within 20 days.",
        "test_refunds",
        "Refunds",
        "refund",
        version="1.0",
        effective_date="2024-01-01",
    )
    save_policy(first, tmp_path)
    second = ingest_markdown(
        "## Eligibility\nRefunds are allowed within 30 days.",
        "test_refunds",
        "Refunds",
        "refund",
        version="2.0",
        effective_date="2025-01-01",
    )
    save_policy(second, tmp_path)
    policies = load_policies_from_dir(tmp_path)
    assert len([p for p in policies if p.policy_id == "test_refunds"]) == 2
    assert len([p for p in policies if p.status == "active"]) == 1
    activate_policy_version("test_refunds", "1.0", tmp_path)
    policies = load_policies_from_dir(tmp_path)
    active = [p for p in policies if p.status == "active"]
    assert len(active) == 1 and active[0].version == "1.0"

    # A failed activation must leave the currently active version untouched.
    with pytest.raises(ValueError, match="not found"):
        activate_policy_version("test_refunds", "9.9", tmp_path)
    policies = load_policies_from_dir(tmp_path)
    active = [p for p in policies if p.status == "active"]
    assert len(active) == 1 and active[0].version == "1.0"


def test_policy_id_path_traversal_rejected(tmp_path):
    doc = ingest_markdown("## Section\nBody", "../outside", "bad", "general")
    with pytest.raises(ValueError):
        save_policy(doc, tmp_path)
    assert not list(tmp_path.parent.glob("outside*"))


def test_same_version_is_immutable(tmp_path):
    d1 = ingest_markdown("## Section\nOriginal", "immut", "Policy", "general", version="1.0")
    save_policy(d1, tmp_path)
    d2 = ingest_markdown("## Section\nChanged", "immut", "Policy", "general", version="1.0")
    with pytest.raises(ValueError):
        save_policy(d2, tmp_path)


def test_pdf_ingestion_keeps_version_and_enforces_page_limit(monkeypatch):
    from types import SimpleNamespace

    import pypdf

    from auditor.policies.ingest import ingest_pdf_bytes

    page = SimpleNamespace(extract_text=lambda: "## Refund window\nThirty days.")
    monkeypatch.setattr(pypdf, "PdfReader", lambda _: SimpleNamespace(pages=[page]))
    doc = ingest_pdf_bytes(
        b"fake-pdf",
        "pdf_policy",
        "PDF policy",
        "refund",
        version="3.1",
        effective_date="2026-02-15",
    )
    assert doc.version == "3.1"
    assert doc.effective_date == "2026-02-15"

    monkeypatch.setattr(pypdf, "PdfReader", lambda _: SimpleNamespace(pages=[page] * 101))
    with pytest.raises(ValueError, match="100-page"):
        ingest_pdf_bytes(b"fake-pdf", "too_many", "PDF", "general")
