from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ai-incident-commander"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    log_file: str = "logs/payment-api.log"
    redis_url: str = "redis://redis:6379/0"

    request_timeout_seconds: float = 2.0
    db_pool_size: int = 10
    default_simulation_mode: str = "normal"

    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    claude_api_url: str = "https://api.anthropic.com/v1/messages"

    slack_webhook_url: str = ""

    runbook_dir: str = "logs/runbooks"

    # Incident detection thresholds for automation signals.
    alert_error_rate_threshold_percent: float = 5.0
    alert_p95_latency_threshold_seconds: float = 1.0
    alert_timeout_threshold: float = 3.0
    alert_db_exhausted_threshold: float = 1.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
