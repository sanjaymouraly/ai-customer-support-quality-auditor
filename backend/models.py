from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class AuditRecord(Base):
    __tablename__ = "audits"
    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(String, nullable=True, index=True)
    project_id = Column(String, nullable=True, index=True)
    batch_id = Column(String, nullable=True, index=True)
    batch_item_key = Column(String, nullable=True, index=True)
    request_hash = Column(String, nullable=True)
    category = Column(String, nullable=True)
    customer_message = Column(Text, nullable=False)
    candidate_response = Column(Text, nullable=False)
    facts = Column(JSON, nullable=True)
    policy_ids = Column(JSON, nullable=True)
    expected_actions = Column(JSON, nullable=True)
    expected_escalation = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    evaluation_mode = Column(String, default="deterministic")
    evaluator_model = Column(String, nullable=True)
    responder_model = Column(String, nullable=True)
    config_snapshot = Column(JSON, nullable=True)
    overall_score = Column(Integer)
    decision = Column(String)
    decision_reason = Column(Text)
    dimension_scores = Column(JSON)
    escalation = Column(JSON, nullable=True)
    policy_refs = Column(JSON, nullable=True)
    hard_stop_triggered = Column(Boolean, default=False)
    hard_stop_reasons = Column(JSON, nullable=True)
    missing_info = Column(JSON, nullable=True)
    improvement_suggestions = Column(JSON, nullable=True)
    evidence_highlights = Column(JSON, nullable=True)
    hallucination_flags = Column(JSON, nullable=True)
    uncertainty_flags = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    confidence = Column(Float, default=0.5)
    confidence_basis = Column(Text, nullable=True)
    reviewer = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HumanReview(Base):
    __tablename__ = "human_reviews"
    id = Column(Integer, primary_key=True)
    audit_id = Column(Integer, index=True)
    reviewer_id = Column(String, nullable=False)
    dimension_scores = Column(JSON)
    overall_score = Column(Integer, nullable=True)
    decision = Column(String, nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PolicyRecord(Base):
    __tablename__ = "policies"
    id = Column(Integer, primary_key=True)
    policy_id = Column(String, unique=True, index=True)
    title = Column(String)
    version = Column(String)
    category = Column(String)
    content = Column(JSON)
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    """A workspace/profile that groups audits and restricts the policy catalogue."""

    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    project_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    policy_ids = Column(JSON, nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ProviderUsage(Base):
    __tablename__ = "provider_usage"
    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=True)
    estimated_input_tokens = Column(Integer, nullable=False)
    reserved_output_tokens = Column(Integer, nullable=False)
    estimated_total_tokens = Column(Integer, nullable=False)
    estimated_cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
