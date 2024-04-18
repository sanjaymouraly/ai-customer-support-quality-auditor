"""Persisted evaluation rubric and threshold configuration.

Defaults are documented in rubric.py. Updates are validated before writing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .schemas import DEFAULT_WEIGHTS, DIMENSION_LIST

SETTINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "app_settings.json"
DEFAULT_THRESHOLDS = {"approve": 85, "revision": 65, "human_review": 40}


class EvaluationConfig(BaseModel):
    weights: dict[str, float] = Field(default_factory=lambda: DEFAULT_WEIGHTS.copy())
    thresholds: dict[str, int] = Field(default_factory=lambda: DEFAULT_THRESHOLDS.copy())

    @model_validator(mode="after")
    def validate_config(self):
        if set(self.weights) != set(DIMENSION_LIST):
            raise ValueError("Weights must include all nine rubric dimensions exactly once")
        if any(v < 0 or v > 1 for v in self.weights.values()):
            raise ValueError("Weights must be between 0 and 1")
        if sum(self.weights.values()) <= 0:
            raise ValueError("At least one rubric weight must be positive")
        if set(self.thresholds) != set(DEFAULT_THRESHOLDS):
            raise ValueError("Thresholds must define approve, revision, and human_review")
        if not (
            0
            <= self.thresholds["human_review"]
            < self.thresholds["revision"]
            < self.thresholds["approve"]
            <= 100
        ):
            raise ValueError(
                "Thresholds must satisfy 0 <= human_review < revision < approve <= 100"
            )
        return self

    def normalized_weights(self) -> dict[str, float]:
        total = sum(self.weights.values())
        return {key: value / total for key, value in self.weights.items()}


def get_evaluation_config() -> EvaluationConfig:
    if not SETTINGS_PATH.exists():
        return EvaluationConfig()
    try:
        return EvaluationConfig.model_validate_json(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt settings never take down auditing; defaults remain explicit.
        return EvaluationConfig()


def save_evaluation_config(payload: dict[str, Any]) -> EvaluationConfig:
    config = EvaluationConfig.model_validate(payload)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
    temporary.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(SETTINGS_PATH)
    return config
