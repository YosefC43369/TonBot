"""
Application lifecycle — startup and graceful shutdown.

Startup order:
1. Validate configuration (fails clearly, never logs secret values)
2. Configure structured logging
3. Initialize database engine
4. Verify database connectivity
5. Start background worker

Shutdown order (reverse):
1. Stop background worker
2. Dispose database engine
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from database.session import check_connectivity, dispose_engine, init_engine
from workers.wallet_monitor import WalletMonitorWorker

log = get_logger(__name__)

_monitor_worker: WalletMonitorWorker | None = None
_monitor_task: asyncio.Task | None = None  # type: ignore[type-arg]


async def startup() -> None:
    """
    Initialize all application dependencies.
    Raises RuntimeError if a required dependency cannot be reached.
    Pydantic ValidationError (from get_settings()) is allowed to propagate —
    it never prints secret values.
    """
    global _monitor_worker, _monitor_task

    settings = get_settings()
    configure_logging(settings.log_level)

    log.info("application_startup_begin")

    init_engine(settings.db_url)

    if not await check_connectivity():
        raise RuntimeError(
            "Cannot connect to the database. "
            "Check DATABASE_URL and ensure PostgreSQL is running."
        )
    log.info("database_connectivity_ok")

    _monitor_worker = WalletMonitorWorker()
    _monitor_task = asyncio.create_task(
        _monitor_worker.run(), name="wallet_monitor"
    )
    log.info("background_worker_started")

    log.info("application_startup_complete")


async def shutdown() -> None:
    """Stop all background tasks and release resources."""
    global _monitor_worker, _monitor_task

    log.info("application_shutdown_begin")

    if _monitor_worker:
        _monitor_worker.stop()
        await _monitor_worker.wait_stopped(timeout=15.0)
        _monitor_worker = None

    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
        _monitor_task = None

    await dispose_engine()
    log.info("application_shutdown_complete")