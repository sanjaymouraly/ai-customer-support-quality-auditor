from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_audit import router as audit_router
from .api.routes_misc import router as misc_router
from .api.routes_policies import router as policy_router
from .api.routes_projects import router as project_router
from .api.routes_providers import router as provider_router
from .api.routes_scenarios import router as scenarios_router
from .database import SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        from backend.services.projects import ensure_default_project

        db = SessionLocal()
        try:
            ensure_default_project(db)
        finally:
            db.close()
    except Exception:
        # A project-store failure should not make the API unusable; explicit project
        # requests will return a clear error.
        pass
    try:
        from auditor.policies.store import load_policies_from_dir

        load_policies_from_dir()
    except Exception:
        # Policy loading errors are surfaced by the manager; the API can still start for repair.
        pass
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Customer Support Response Quality Auditor",
        version="0.2.0",
        description="Policy-grounded, explainable quality auditor for AI support responses",
        lifespan=lifespan,
    )
    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(audit_router)
    app.include_router(policy_router)
    app.include_router(project_router)
    app.include_router(provider_router)
    app.include_router(misc_router)
    app.include_router(scenarios_router)

    # Optional bearer-token gate for shared/network deployments. Local single-user setup is open by default.
    @app.middleware("http")
    async def optional_auth(request, call_next):
        token = os.getenv("API_ACCESS_TOKEN", "").strip()
        open_paths = {"/", "/api/health", "/docs", "/openapi.json", "/redoc"}
        if (
            token
            and request.method != "OPTIONS"
            and request.url.path not in open_paths
        ):
            supplied = request.headers.get("authorization", "")
            expected = f"Bearer {token}"
            if not hmac.compare_digest(supplied, expected):
                from fastapi.responses import JSONResponse

                return JSONResponse(status_code=401, content={"detail": "Authentication required"})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.middleware("http")
    async def bound_request_size(request, call_next):
        # Content-Length is advisory but catches accidental large JSON submissions before
        # parsing. Policy uploads have their own streaming limit.
        try:
            limit = int(os.getenv("MAX_REQUEST_BYTES", str(2 * 1024 * 1024)))
        except ValueError:
            limit = 2 * 1024 * 1024
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > limit:
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        status_code=413, content={"detail": "Request body exceeds configured limit"}
                    )
            except ValueError:
                pass
        return await call_next(request)

    @app.get("/")
    def root():
        return {
            "app": "AI Customer Support Response Quality Auditor",
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
