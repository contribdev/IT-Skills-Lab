"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API service settings.

    All values are read from environment variables. Defaults are safe for
    local development; production values are injected via Kubernetes Secrets.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- General ----------
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_port: int = 8080

    # ---------- PostgreSQL ----------
    database_url: PostgresDsn = Field(
        ...,
        description="PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host:5432/db",
    )
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10
    db_command_timeout: float = 30.0

    # ---------- S3 / MinIO ----------
    s3_endpoint: str = Field(..., description="S3 endpoint, e.g. http://minio:9000")
    s3_bucket: str = "documents"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_region: str = "us-east-1"

    # ---------- RabbitMQ ----------
    rabbitmq_url: SecretStr = Field(
        ...,
        description="AMQP URL, e.g. amqp://user:pass@rabbitmq:5672/",
    )
    ocr_queue: str = "ocr.queue"

    # ---------- Upload limits ----------
    max_upload_size_mb: int = 50


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    The lru_cache ensures we parse environment variables only once per process.
    """
    return Settings()  # type: ignore[call-arg]