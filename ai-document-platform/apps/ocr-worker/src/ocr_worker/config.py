"""OCR Worker configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """OCR Worker settings.

    All values are read from environment variables. Defaults are safe for
    local development; production values come from Kubernetes Secrets.
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

    # ---------- PostgreSQL ----------
    database_url: PostgresDsn = Field(
        ...,
        description="PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host:5432/db",
    )
    db_pool_min_size: int = 2
    db_pool_max_size: int = 5      # воркер меньше, чем API
    db_command_timeout: float = 60.0

    # ---------- S3 / MinIO ----------
    s3_endpoint: str = Field(..., description="S3 endpoint")
    s3_bucket: str = "documents"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_region: str = "us-east-1"

    # ---------- RabbitMQ ----------
    rabbitmq_url: SecretStr = Field(..., description="AMQP URL")
    ocr_queue: str = "ocr.queue"
    llm_queue: str = "llm.queue"
    prefetch_count: int = 1        # по одному сообщению за раз

    # ---------- OCR ----------
    ocr_languages: str = "rus+eng"          # Tesseract: русский + английский
    ocr_dpi: int = 300                      # DPI при конвертации PDF → image
    ocr_timeout_seconds: int = 120          # таймаут на один документ
    ocr_max_pages: int = 50                 # ограничение: не больше N страниц


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (parsed once per process)."""
    return Settings()  # type: ignore[call-arg]