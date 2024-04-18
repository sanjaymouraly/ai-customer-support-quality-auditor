from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Case(BaseModel):
    case_id: str
    category: str
    customer_message: str = Field(min_length=3, max_length=4000)
    facts: dict[str, Any] = Field(default_factory=dict, max_length=100)
    policy_ids: list[str] = Field(default_factory=list, max_length=30)
    candidate_response: str = Field(min_length=3, max_length=4000)
    expected_actions: list[str] = Field(default_factory=list, max_length=50)
    expected_escalation: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"  # low|medium|high|critical
    label: Literal["positive", "negative", "borderline"] = "negative"
    notes: str = ""
    evaluation_metadata: dict[str, Any] = Field(default_factory=dict)
