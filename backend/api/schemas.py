from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectCreate(BaseModel):
    project_id: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    policy_ids: list[str] = Field(default_factory=list, max_length=30)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    policy_ids: list[str] = Field(default_factory=list, max_length=30)


class GenerateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    customer_message: str = Field(min_length=3, max_length=4000)
    facts: dict[str, Any] = Field(default_factory=dict, max_length=100)
    category: str | None = Field(default=None, max_length=80)
    project_id: str | None = Field(default=None, max_length=80)
    policy_ids: list[str] | None = Field(default=None, max_length=30)
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=600, ge=64, le=2000)


class AuditRequest(BaseModel):
    case_id: str | None = Field(default=None, max_length=100)
    project_id: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=80)
    customer_message: str = Field(min_length=3, max_length=4000)
    candidate_response: str = Field(min_length=3, max_length=4000)
    facts: dict[str, Any] = Field(default_factory=dict, max_length=100)
    expected_actions: list[str] = Field(default_factory=list, max_length=50)
    expected_escalation: (
        Literal[
            "resolve",
            "ask_info",
            "verify_identity",
            "refer",
            "escalate_billing",
            "escalate_supervisor",
            "escalate_security",
        ]
        | None
    ) = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    policy_ids: list[str] | None = Field(default=None, max_length=30)
    evaluation_mode: Literal["deterministic", "hybrid", "llm", "offline"] = "deterministic"
    provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    responder_model: str | None = Field(default=None, max_length=200)
    temperature: float = Field(default=0.2, ge=0, le=2)


class BatchRequest(BaseModel):
    cases: list[AuditRequest] = Field(min_length=1, max_length=500)
    evaluation_mode: Literal["deterministic", "hybrid", "llm", "offline"] = "deterministic"
    provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    batch_id: str | None = Field(default=None, max_length=100)
    project_id: str | None = Field(default=None, max_length=80)
    resume: bool = False


class ReviewDimensionScore(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dimension: Literal[
        "factual_accuracy",
        "completeness",
        "policy_compliance",
        "hallucination",
        "resolution_guidance",
        "tone_clarity",
        "privacy_safety",
        "escalation",
        "actionability",
    ]
    score: int = Field(ge=0, le=4)
    reviewer_explanation: str = Field(default="", max_length=1000)


class ReviewCreate(BaseModel):
    audit_id: int = Field(ge=1)
    reviewer_id: str = Field(min_length=1, max_length=80)
    dimension_scores: list[ReviewDimensionScore] | None = Field(default=None, max_length=9)
    overall_score: int | None = Field(default=None, ge=0, le=100)
    decision: (
        Literal[
            "Approve",
            "Needs Revision",
            "Human Review Required",
            "Escalation Required",
            "Critical Failure",
        ]
        | None
    ) = None
    comments: str | None = Field(default=None, max_length=10_000)

    @field_validator("reviewer_id")
    @classmethod
    def normalize_reviewer_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reviewer_id cannot be blank")
        return value

    @model_validator(mode="after")
    def require_complete_unique_dimensions(self):
        if self.dimension_scores is not None:
            names = [item.dimension for item in self.dimension_scores]
            if len(names) != 9 or len(set(names)) != 9:
                raise ValueError("dimension_scores must contain each of the nine dimensions once")
        return self
