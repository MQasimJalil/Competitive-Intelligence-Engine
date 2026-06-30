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


def test_session_cookie_secure_can_be_forced_without_production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")

    settings = Settings()

    assert settings.session_cookie_secure is True


def test_job_guardrail_defaults_are_enabled_for_internal_testing(monkeypatch):
    monkeypatch.delenv("JOB_RATE_LIMIT_MAX_PER_WINDOW", raising=False)
    monkeypatch.delenv("JOB_USER_CONCURRENCY_LIMIT", raising=False)
    monkeypatch.delenv("JOB_GLOBAL_CONCURRENCY_LIMIT", raising=False)

    settings = Settings()

    assert settings.job_rate_limit_max_per_window > 0
    assert settings.job_user_concurrency_limit > 0
    assert settings.job_global_concurrency_limit > 0


def test_supabase_auth_and_credit_configuration(monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "jwt-secret")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://supabase")
    monkeypatch.setenv("BETA_STARTING_CREDITS", "7")
    monkeypatch.setenv("CREDIT_REPOSITORY", "postgres")

    settings = Settings()

    assert settings.auth_provider == "supabase"
    assert settings.supabase_url == "https://project.supabase.co"
    assert settings.supabase_anon_key == "anon-key"
    assert settings.supabase_service_role_key == "service-role-key"
    assert settings.supabase_jwt_secret == "jwt-secret"
    assert settings.supabase_db_url == "postgresql://supabase"
    assert settings.beta_starting_credits == 7
    assert settings.credit_repository == "postgres"
