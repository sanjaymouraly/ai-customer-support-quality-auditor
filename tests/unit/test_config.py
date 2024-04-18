import pytest

from auditor.evaluation.config import (
    EvaluationConfig,
    get_evaluation_config,
    save_evaluation_config,
)
from auditor.evaluation.schemas import DEFAULT_WEIGHTS


def test_config_normalizes_weights():
    config = EvaluationConfig(weights={k: v * 2 for k, v in DEFAULT_WEIGHTS.items()})
    assert abs(sum(config.normalized_weights().values()) - 1) < 1e-9


def test_invalid_config_rejected():
    weights = DEFAULT_WEIGHTS.copy()
    weights.pop("privacy_safety")
    with pytest.raises(ValueError):
        EvaluationConfig(weights=weights)
    with pytest.raises(ValueError):
        EvaluationConfig(thresholds={"approve": 50, "revision": 70, "human_review": 40})


def test_config_save_reload(monkeypatch, tmp_path):
    import auditor.evaluation.config as config_module

    monkeypatch.setattr(config_module, "SETTINGS_PATH", tmp_path / "settings.json")
    cfg = EvaluationConfig()
    saved = save_evaluation_config(cfg.model_dump())
    loaded = get_evaluation_config()
    assert saved.weights == loaded.weights
    assert loaded.thresholds["approve"] == 85
