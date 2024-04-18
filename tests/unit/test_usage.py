import pytest

from backend.services.usage import provider_prices, reserve_provider_usage


def test_usage_budget_enforced(monkeypatch):
    # Service is covered through a tiny in-memory DB fixture below.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import backend.services.usage as usage
    from backend.database import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(usage.settings, "daily_token_budget", 100)
    with pytest.raises(ValueError, match="budget exceeded"):
        reserve_provider_usage(db, "openai", "test", "x" * 1000)
    db.close()
    engine.dispose()


def test_price_schedule_is_operator_configured(monkeypatch):
    monkeypatch.delenv("PROVIDER_PRICING_JSON", raising=False)
    assert provider_prices() == {}
    monkeypatch.setenv(
        "PROVIDER_PRICING_JSON", '{"openai":{"input_usd_per_1m":1.0,"output_usd_per_1m":2.0}}'
    )
    assert provider_prices()["openai"]["output_usd_per_1m"] == 2.0


def test_spend_cap_and_retry_reservations(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import backend.services.usage as usage
    from backend.database import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(usage.settings, "daily_token_budget", 100_000)
    monkeypatch.setattr(usage.settings, "daily_spend_limit_usd", 0.001)
    monkeypatch.setenv("PROVIDER_RETRY_ATTEMPTS", "3")
    monkeypatch.setenv(
        "PROVIDER_PRICING_JSON",
        '{"openai":{"input_usd_per_1m":10,"output_usd_per_1m":10}}',
    )
    with pytest.raises(ValueError, match="spend limit"):
        usage.reserve_provider_usage(db, "openai", "test", "hello")
    assert db.query(usage.ProviderUsage).count() == 0
    monkeypatch.setattr(usage.settings, "daily_spend_limit_usd", 1.0)
    record = usage.reserve_provider_usage(db, "openai", "test", "hello")
    assert record.estimated_input_tokens >= 3
    assert record.reserved_output_tokens == usage.OUTPUT_TOKEN_RESERVE * 3
    assert (
        record.estimated_total_tokens
        == record.estimated_input_tokens + record.reserved_output_tokens
    )
    db.close()
    engine.dispose()
