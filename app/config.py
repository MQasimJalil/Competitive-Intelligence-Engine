import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    if maximum is not None and value > maximum:
        return maximum
    return value


def _float_env(name: str, default: float, *, minimum: float = 0.1) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _first_defined_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return ""


def _ai_api_key() -> str:
    provider = os.getenv("AI_PROVIDER", "openrouter").casefold()
    provider_key = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
    return _first_defined_env("AI_API_KEY", provider_key)


def _apify_api_token() -> str:
    return os.getenv("APIFY_API_TOKEN", "")


def _report_max_cost_usd() -> float:
    return _float_env("REPORT_MAX_COST_USD", 0.15, minimum=0.0)


def _ai_max_cost_usd() -> float:
    return _float_env("AI_MAX_COST_USD", _report_max_cost_usd() / 2, minimum=0.0)


def _apify_max_cost_usd() -> float:
    return _float_env("APIFY_MAX_COST_USD", _report_max_cost_usd() / 2, minimum=0.0)


def _session_cookie_secure() -> bool:
    return _bool_env(
        "SESSION_COOKIE_SECURE",
        os.getenv("APP_ENV", "development").casefold() == "production",
    )


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Competitor Brief")
    app_env: str = os.getenv("APP_ENV", "development")
    app_base_url: str = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    crawler_user_agent: str = os.getenv(
        "CRAWLER_USER_AGENT",
        "CompetitorBriefBot/0.1 (+mailto:owner@example.com)",
    )
    crawl_timeout_seconds: float = _float_env("CRAWL_TIMEOUT_SECONDS", 12.0)
    crawl_max_pages_per_domain: int = _int_env("CRAWL_MAX_PAGES_PER_DOMAIN", 12, maximum=30)
    crawl_max_response_bytes: int = _int_env(
        "CRAWL_MAX_RESPONSE_BYTES", 5_000_000, maximum=10_000_000
    )
    crawl_max_redirects: int = _int_env("CRAWL_MAX_REDIRECTS", 5, maximum=10)
    crawl_max_sitemap_urls: int = _int_env("CRAWL_MAX_SITEMAP_URLS", 500, maximum=2_000)
    crawl_selection_limit: int = _int_env("CRAWL_SELECTION_LIMIT", 5, maximum=10)
    crawl_concurrency: int = _int_env("CRAWL_CONCURRENCY", 3, maximum=5)
    robots_max_response_bytes: int = _int_env("ROBOTS_MAX_RESPONSE_BYTES", 250_000)
    robots_cache_ttl_seconds: int = _int_env(
        "ROBOTS_CACHE_TTL_SECONDS",
        300,
        maximum=60 * 60,
    )
    rendered_browser_enabled: bool = _bool_env("RENDERED_BROWSER_ENABLED", True)
    rendered_browser_channel: str = os.getenv("RENDERED_BROWSER_CHANNEL", "chrome")
    rendered_browser_timeout_seconds: float = _float_env("RENDERED_BROWSER_TIMEOUT_SECONDS", 20.0)
    ai_provider: str = os.getenv("AI_PROVIDER", "openrouter")
    ai_api_key: str = _ai_api_key()
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
    ai_model: str = os.getenv("AI_MODEL") or os.getenv("OPENAI_MODEL", "openai/gpt-5.4")
    ai_http_referer: str = os.getenv("AI_HTTP_REFERER", "")
    ai_app_title: str = os.getenv("AI_APP_TITLE", "Competitor Brief")
    ai_analysis_enabled: bool = _bool_env("AI_ANALYSIS_ENABLED", True)
    ai_prompt_version: str = os.getenv("AI_PROMPT_VERSION", "competitor-brief-v1")
    ai_schema_version: str = os.getenv("AI_SCHEMA_VERSION", "analysis-v1")
    ai_cache_enabled: bool = _bool_env("AI_CACHE_ENABLED", True)
    ai_cache_dir: str = os.getenv("AI_CACHE_DIR", "var/ai_cache")
    ai_run_log_path: str = os.getenv("AI_RUN_LOG_PATH", "var/logs/ai_runs.jsonl")
    ai_max_input_tokens: int = _int_env("AI_MAX_INPUT_TOKENS", 12_000, maximum=100_000)
    ai_max_output_tokens: int = _int_env("AI_MAX_OUTPUT_TOKENS", 2_000, maximum=20_000)
    report_max_cost_usd: float = field(default_factory=_report_max_cost_usd)
    ai_max_cost_usd: float = field(default_factory=_ai_max_cost_usd)
    ai_input_cost_per_million: float = _float_env("AI_INPUT_COST_PER_MILLION", 0.0, minimum=0.0)
    ai_output_cost_per_million: float = _float_env("AI_OUTPUT_COST_PER_MILLION", 0.0, minimum=0.0)
    job_store_dir: str = os.getenv("JOB_STORE_DIR", "var/jobs")
    job_repository: str = os.getenv("JOB_REPOSITORY", "file")
    database_url: str = os.getenv("DATABASE_URL", "")
    postgres_pool_max_size: int = _int_env("POSTGRES_POOL_MAX_SIZE", 8, maximum=50)
    local_owner_id: str = os.getenv("LOCAL_OWNER_ID", "local-development-user")
    user_store_dir: str = os.getenv("USER_STORE_DIR", "var/users")
    user_repository: str = os.getenv("USER_REPOSITORY", os.getenv("JOB_REPOSITORY", "file"))
    auth_secret: str = os.getenv("AUTH_SECRET", "dev-insecure-change-me")
    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "competitor_brief_session")
    session_cookie_secure: bool = field(default_factory=_session_cookie_secure)
    session_max_age_seconds: int = _int_env(
        "SESSION_MAX_AGE_SECONDS",
        60 * 60 * 24 * 14,
        maximum=60 * 60 * 24 * 90,
    )
    job_rate_limit_window_seconds: int = _int_env(
        "JOB_RATE_LIMIT_WINDOW_SECONDS",
        60,
        maximum=60 * 60,
    )
    job_rate_limit_max_per_window: int = _int_env(
        "JOB_RATE_LIMIT_MAX_PER_WINDOW",
        6,
        maximum=100,
    )
    job_user_concurrency_limit: int = _int_env(
        "JOB_USER_CONCURRENCY_LIMIT",
        1,
        maximum=10,
    )
    job_global_concurrency_limit: int = _int_env(
        "JOB_GLOBAL_CONCURRENCY_LIMIT",
        3,
        maximum=50,
    )
    admin_name: str = os.getenv("ADMIN_NAME", "Admin")
    admin_email: str = os.getenv("ADMIN_EMAIL", "")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    report_retention_days: int = _int_env("REPORT_RETENTION_DAYS", 30, maximum=365)
    optional_search_api_key: str = os.getenv("OPTIONAL_SEARCH_API_KEY", "")
    optional_tech_lookup_api_key: str = os.getenv("OPTIONAL_TECH_LOOKUP_API_KEY", "")
    apify_api_token: str = _apify_api_token()
    apify_enabled: bool = _bool_env("APIFY_ENABLED", True)
    apify_timeout_seconds: float = _float_env("APIFY_TIMEOUT_SECONDS", 120.0)
    apify_max_cost_usd: float = field(default_factory=_apify_max_cost_usd)
    apify_reddit_actor_id: str = os.getenv("APIFY_REDDIT_ACTOR_ID", "apify/reddit-scraper")

    @property
    def openai_api_key(self) -> str:
        return self.ai_api_key

    @property
    def openai_model(self) -> str:
        return self.ai_model


settings = Settings()
