from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.projects import (
    create_project,
    delete_project,
    ensure_default_project,
    list_projects,
    project_to_dict,
    update_project,
)
from .schemas import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def get_projects(db: Session = Depends(get_db)):
    return {"projects": list_projects(db)}


@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    from ..models import Project

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project_to_dict(project)


@router.post("")
def add_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    try:
        project = create_project(
            db, payload.project_id, payload.name, payload.description, payload.policy_ids
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"created": project.project_id, "project": project_to_dict(project)}


@router.put("/{project_id}")
def edit_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)):
    try:
        project = update_project(
            db, project_id, payload.name, payload.description, payload.policy_ids
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"updated": project.project_id, "project": project_to_dict(project)}


@router.delete("/{project_id}")
def remove_project(project_id: str, db: Session = Depends(get_db)):
    try:
        delete_project(db, project_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": project_id}


__all__ = ["router", "ensure_default_project"]
