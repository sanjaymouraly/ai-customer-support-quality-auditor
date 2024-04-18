"""Project (workspace) profiles.

A project groups audit history and can restrict which policy documents are eligible for
retrieval. The concept is deliberately small: it is a local policy profile, not a
multi-tenant authentication boundary.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from auditor.policies.store import get_all_policies

from ..models import AuditRecord, Project

DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Default workspace"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,80}$")


def all_policy_ids() -> list[str]:
    return sorted({p.policy_id for p in get_all_policies() if p.status == "active"})


def ensure_default_project(db: Session) -> Project:
    project = db.query(Project).filter(Project.project_id == DEFAULT_PROJECT_ID).first()
    if project is None:
        project = Project(
            project_id=DEFAULT_PROJECT_ID,
            name=DEFAULT_PROJECT_NAME,
            description="Local default profile. Uses all active policy documents.",
            policy_ids=[],
            is_default=True,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
    return project


def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "name": project.name,
        "description": project.description or "",
        "policy_ids": project.policy_ids or [],
        "is_default": bool(project.is_default),
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


def resolve_project(db: Session, project_id: str | None) -> Project:
    """Return the requested project or the default project.

    Raises LookupError when an explicitly requested project does not exist so callers do
    not silently file an audit under the wrong workspace.
    """

    if project_id and project_id != DEFAULT_PROJECT_ID:
        project = db.query(Project).filter(Project.project_id == project_id).first()
        if not project:
            raise LookupError(f"Unknown project_id: {project_id}")
        return project
    return ensure_default_project(db)


def effective_policy_ids(
    db: Session, project_id: str | None, requested: list[str] | None
) -> list[str] | None:
    """Precedence: explicit request policy IDs, project profile, then all active policies."""

    if requested:
        return requested
    project = resolve_project(db, project_id)
    if project.policy_ids:
        return list(project.policy_ids)
    # None is intentional: retrieval then considers the whole active catalogue.
    return None


def list_projects(db: Session) -> list[dict[str, Any]]:
    from sqlalchemy import func

    ensure_default_project(db)
    projects = db.query(Project).order_by(Project.is_default.desc(), Project.name).all()
    counts = dict(
        db.query(AuditRecord.project_id, func.count(AuditRecord.id))
        .group_by(AuditRecord.project_id)
        .all()
    )
    result = []
    for project in projects:
        row = project_to_dict(project)
        row["audit_count"] = int(counts.get(project.project_id, 0))
        result.append(row)
    return result


def create_project(
    db: Session, project_id: str, name: str, description: str, policy_ids: list[str]
) -> Project:
    project_id = project_id.strip()
    if not _ID_RE.fullmatch(project_id):
        raise ValueError("project_id must be 2-80 letters, digits, underscores, or hyphens")
    if project_id == DEFAULT_PROJECT_ID:
        raise ValueError("project_id 'default' is reserved")
    if db.query(Project).filter(Project.project_id == project_id).first():
        raise ValueError("project_id already exists")
    _validate_name_and_policies(name, policy_ids)
    project = Project(
        project_id=project_id,
        name=name.strip(),
        description=(description or "").strip()[:1000],
        policy_ids=policy_ids,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project(
    db: Session,
    project_id: str,
    name: str,
    description: str,
    policy_ids: list[str],
) -> Project:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise LookupError("Project not found")
    _validate_name_and_policies(name, policy_ids)
    project.name = name.strip()
    project.description = (description or "").strip()[:1000]
    project.policy_ids = policy_ids
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project_id: str) -> None:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise LookupError("Project not found")
    if project.is_default:
        raise ValueError("The default project cannot be deleted")
    if db.query(AuditRecord).filter(AuditRecord.project_id == project_id).count():
        raise ValueError("Project has saved audits; export or delete them before deleting the project")
    db.delete(project)
    db.commit()


def _validate_name_and_policies(name: str, policy_ids: list[str]) -> None:
    if not name or not name.strip():
        raise ValueError("Project name is required")
    if len(name) > 120:
        raise ValueError("Project name is too long")
    known = set(all_policy_ids())
    unknown = sorted(set(policy_ids) - known)
    if unknown:
        raise ValueError(f"Unknown or inactive policy IDs: {', '.join(unknown)}")
    if len(set(policy_ids)) != len(policy_ids):
        raise ValueError("policy_ids must not contain duplicates")
