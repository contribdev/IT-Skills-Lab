"""LLM Worker configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """LLM Worker settings."""

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
    database_url: PostgresDsn = Field(...)
    db_pool_min_size: int = 2
    db_pool_max_size: int = 5
    db_command_timeout: float = 60.0

    # ---------- S3 / MinIO ----------
    s3_endpoint: str = Field(...)
    s3_bucket: str = "documents"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_region: str = "us-east-1"

    # ---------- RabbitMQ ----------
    rabbitmq_url: SecretStr = Field(...)
    llm_queue: str = "llm.queue"
    prefetch_count: int = 1

    # ---------- Ollama ----------
    ollama_endpoint: str = Field(..., min_length=1)
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_seconds: int = 180
    ollama_temperature: float = 0.1
    ollama_num_predict: int = 2048

    # ---------- Text limits ----------
    max_text_chars: int = 30000

    # ---------- Metrics ----------
    metrics_port: int = 9091

    # ---------- Validators ----------
    @field_validator("ollama_endpoint")
    @classmethod
    def _validate_ollama_endpoint(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(
                "ollama_endpoint must start with http:// or https://"
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (parsed once per process)."""
    return Settings()  # type: ignore[call-arg]