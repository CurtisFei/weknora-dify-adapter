"""Environment-backed application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated adapter configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    weknora_base_url: AnyHttpUrl
    weknora_api_key: SecretStr
    dify_adapter_api_key: SecretStr
    weknora_timeout_seconds: float = Field(default=15, ge=1, le=120)
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("weknora_api_key", "dify_adapter_api_key", mode="before")
    @classmethod
    def reject_blank_secret(cls, value: object) -> object:
        plain_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(plain_value, str) or not plain_value.strip():
            raise ValueError("secret must not be blank")
        return value

    @property
    def weknora_api_url(self) -> str:
        """Return the base URL with exactly one `/api/v1` suffix."""

        base_url = str(self.weknora_base_url).rstrip("/")
        if base_url.endswith("/api/v1"):
            return base_url
        return f"{base_url}/api/v1"


@lru_cache
def get_settings() -> Settings:
    """Load process settings once."""

    return Settings()
