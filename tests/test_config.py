from app.config import Settings, _ai_api_key, _apify_api_token


def test_openrouter_does_not_fall_back_to_openai_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-provider-key")

    assert _ai_api_key() == ""


def test_openrouter_accepts_provider_specific_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")

    assert _ai_api_key() == "openrouter-key"


def test_apify_token_reads_dedicated_env(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "apify-token")

    assert _apify_api_token() == "apify-token"


def test_default_report_budget_reserves_half_for_ai_and_half_for_apify(monkeypatch):
    monkeypatch.delenv("REPORT_MAX_COST_USD", raising=False)
    monkeypatch.delenv("AI_MAX_COST_USD", raising=False)
    monkeypatch.delenv("APIFY_MAX_COST_USD", raising=False)

    settings = Settings()

    assert settings.report_max_cost_usd == 0.15
    assert settings.ai_max_cost_usd == 0.075
    assert settings.apify_max_cost_usd == 0.075
