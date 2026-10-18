"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

# Set required env vars before any app import touches get_settings()
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:test_token_placeholder_aaaaaaaaaaaaaaaaaaa")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://guardian:pass@localhost/test_db")
os.environ.setdefault("TONAPI_API_KEY", "test_api_key_placeholder")
os.environ.setdefault("ADMIN_USER_IDS", "999")