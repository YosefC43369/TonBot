"""
Async SQLAlchemy session factory.

Usage:
    async with get_session() as session:
        result = await session.execute(...)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.logging_config import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> None:
    """
    Create the global async engine and session factory.

    Call once during application startup, before any database access.
    The database_url must use the asyncpg driver:
        postgresql+asyncpg://user:pass@host/dbname
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        echo=False,         # set True for SQL debug logging
        pool_pre_ping=True, # detect stale connections
        pool_size=10,
        max_overflow=20,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    log.info("database_engine_initialized")


async def dispose_engine() -> None:
    """Close all connections. Call during graceful shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        log.info("database_engine_disposed")


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized — call init_engine() first")
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager that yields an AsyncSession and commits/rolls back."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connectivity() -> bool:
    """
    Verify database connectivity without mutating state.
    Returns True on success, False on failure.
    """
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception as exc:
        log.error("database_connectivity_check_failed", error=str(exc))
        return False