from __future__ import annotations

from pydantic import BaseModel, Field


class PolicySection(BaseModel):
    section_id: str
    title: str
    content: str
    conditions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class PolicyDocument(BaseModel):
    policy_id: str
    title: str
    version: str
    effective_date: str
    expires_on: str | None = None
    status: str = "active"  # active|deprecated
    category: str
    sections: list[PolicySection]
    source_file: str | None = None

    def full_text(self) -> str:
        return "\n\n".join(f"## {s.title}\n{s.content}" for s in self.sections)


class RetrievedPolicy(BaseModel):
    policy_id: str
    version: str
    section_id: str
    section_title: str
    excerpt: str
    score: float = 0.0
