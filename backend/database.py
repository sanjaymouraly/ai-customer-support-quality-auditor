from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from .models import AuditRecord, HumanReview, PolicyRecord, Project, ProviderUsage  # noqa

    Base.metadata.create_all(bind=engine)
    # Small forward-only migration for existing SQLite installs. New deployments are created above.
    migrations = {
        "config_snapshot": "JSON",
        "confidence_basis": "TEXT",
        "batch_id": "VARCHAR(100)",
        "batch_item_key": "VARCHAR(120)",
        "request_hash": "VARCHAR(64)",
        "responder_model": "VARCHAR(200)",
        "evidence_highlights": "JSON",
        "hallucination_flags": "JSON",
        "uncertainty_flags": "JSON",
        "strengths": "JSON",
        "project_id": "VARCHAR(80)",
        "policy_ids": "JSON",
        "expected_actions": "JSON",
        "expected_escalation": "VARCHAR(40)",
        "severity": "VARCHAR(20)",
    }
    if engine.dialect.name == "sqlite":
        columns = {col["name"] for col in inspect(engine).get_columns("audits")}
        missing = {name: sql_type for name, sql_type in migrations.items() if name not in columns}
        if missing:
            with engine.begin() as conn:
                for name, sql_type in missing.items():
                    conn.execute(text(f"ALTER TABLE audits ADD COLUMN {name} {sql_type}"))
    elif engine.dialect.name == "postgresql":
        columns = {col["name"] for col in inspect(engine).get_columns("audits")}
        with engine.begin() as conn:
            for name, sql_type in migrations.items():
                if name not in columns:
                    conn.execute(
                        text(f"ALTER TABLE audits ADD COLUMN IF NOT EXISTS {name} {sql_type}")
                    )
