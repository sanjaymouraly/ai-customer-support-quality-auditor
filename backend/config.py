from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Provider adapters read process environment only; load the project-local .env once, server-side.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./auditor.db")
    max_upload_mb: int = 10
    request_timeout_s: int = 30
    daily_token_budget: int = 100000
    daily_spend_limit_usd: float = 0.0
    api_base_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
