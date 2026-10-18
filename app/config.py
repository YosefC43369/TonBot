"""
Configuration loading and validation.

Reads from environment variables (and optionally a .env file).
Fails clearly on missing required secrets — never prints their values.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Don't expose secret values in repr/str
        str_strip_whitespace=True,
    )
    
    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: SecretStr = Field(
        ..., description="Bot token from @BotFather"
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: SecretStr = Field(
        ..., description="asyncpg DSN: postgresql+asyncpg://user:pass@host/db"
    )

    # ── TON Provider ──────────────────────────────────────────────────────────
    tonapi_base_url: str = Field(
        default="https://tonapi.io",
        description="TonAPI base URL",
    )
    tonapi_api_key: SecretStr = Field(
        ..., description="API key from tonconsole.com"
    )

    # ── Application ───────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    default_timezone: str = Field(default="UTC")

    admin_user_ids: list[int] = Field(
        default_factory=list,
        description="Telegram numeric user IDs with admin access",
    )
    
    http_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    max_watchlist_per_user: int = Field(default=20, ge=1, le=200)
    
    monitor_poll_interval_seconds: int = Field(default=60, ge=10)
    monitor_max_concurrency: int = Field(default=5, ge=1, le=50)
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper