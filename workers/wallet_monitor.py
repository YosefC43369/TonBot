"""
Background wallet monitoring worker.

Polls active watchlist addresses for new on-chain events.
- Bounded concurrency via asyncio.Semaphore
- Per-address checkpoints persisted in provider_cursors
- Deduplication via TransactionRepository
- Graceful shutdown via asyncio.Event
- Transient provider failures are logged and skipped (not fatal)

Phase 1 limitation: detected new events are logged but not
yet delivered as Telegram notifications (Phase 2 adds that).
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from app.config import get_settings
from app.logging_config import get_logger
from database.repositories import WatchlistRepository
from database.session import get_session
from security.redaction import safe_error_message
from services.transaction_service import TransactionService
from ton.base_client import ProviderError
from ton.tonapi_client import TonApiClient

log = get_logger(__name__)

_PROVIDER_ID = "tonapi"


class WalletMonitorWorker:
    """
    Continuous wallet monitoring worker.

    Usage:
        worker = WalletMonitorWorker()
        asyncio.create_task(worker.run())
        # on shutdown:
        worker.stop()
        await worker.wait_stopped()
    """

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._stopped_event = asyncio.Event()

    def stop(self) -> None:
        """Signal the worker to stop after the current poll cycle."""
        self._stop_event.set()

    async def wait_stopped(self, timeout: float = 10.0) -> None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stopped_event.wait(), timeout=timeout)

    async def run(self) -> None:
        settings = get_settings()
        log.info(
            "wallet_monitor_started",
            interval_seconds=settings.monitor_poll_interval_seconds,
            max_concurrency=settings.monitor_max_concurrency,
        )

        try:
            while not self._stop_event.is_set():
                await self._poll_cycle(settings)

                # Wait for the interval or until stop is signalled
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=float(settings.monitor_poll_interval_seconds),
                    )
                except asyncio.TimeoutError:
                    pass  # normal — interval elapsed, loop again
        except asyncio.CancelledError:
            log.info("wallet_monitor_cancelled")
        finally:
            self._stopped_event.set()
            log.info("wallet_monitor_stopped")

    async def _poll_cycle(self, settings: object) -> None:
        """Fetch one batch of addresses and check for new events."""
        async with get_session() as session:
            repo = WatchlistRepository(session)
            addresses = await repo.all_active_addresses()

        if not addresses:
            return

        semaphore = asyncio.Semaphore(settings.monitor_max_concurrency)  # type: ignore[attr-defined]

        async def _check_one(address: str) -> None:
            async with semaphore:
                await self._check_address(address, settings)

        await asyncio.gather(*[_check_one(addr) for addr in addresses])

    async def _check_address(self, canonical_address: str, settings: object) -> None:
        """
        Fetch new events for one address and persist them.
        Provider errors are logged but not propagated — one bad address
        must not abort the whole cycle.
        """
        try:
            async with TonApiClient(
                base_url=settings.tonapi_base_url,  # type: ignore[attr-defined]
                api_key=settings.tonapi_key,  # type: ignore[attr-defined]
                timeout_seconds=settings.http_timeout_seconds,  # type: ignore[attr-defined]
            ) as client, get_session() as session:
                svc = TransactionService(session=session, ton_client=client)
                new_ids = await svc.fetch_and_store_new(canonical_address)

            if new_ids:
                log.info(
                    "new_events_detected",
                    address=canonical_address,
                    count=len(new_ids),
                    event_ids=new_ids[:5],  # log first 5 only
                )
                # Phase 2: deliver notifications here

        except ProviderError as exc:
            log.warning(
                "monitor_provider_error",
                address=canonical_address,
                error=safe_error_message(exc),
            )
        except Exception as exc:
            log.exception(
                "monitor_unexpected_error",
                address=canonical_address,
                error=safe_error_message(exc),
            )