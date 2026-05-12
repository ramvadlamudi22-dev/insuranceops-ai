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

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)
