"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform configuration loaded from environment variables."""

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/insuranceops"
    REDIS_URL: str = "redis://localhost:6379/0"
    API_KEY_HASH_PEPPER: str = ""
    MAX_REQUEST_BYTES: int = 20_971_520
    WORKER_VISIBILITY_TIMEOUT_S: int = 60
    WORKER_CONCURRENCY: int = 1
    LOG_LEVEL: str = "INFO"
    ENV: str = "local"
    ASSUME_TLS_TERMINATOR: bool = False
    PAYLOAD_STORAGE_PATH: str = "/data/payloads"

    # Rate limiting (per-API-key fixed-window)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_OPERATOR_MAX: int = 1200
    RATE_LIMIT_SUPERVISOR_MAX: int = 1200
    RATE_LIMIT_VIEWER_MAX: int = 600

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)
