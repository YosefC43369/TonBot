"""
Background worker — polls incoming TON payments and notifies users.

Each cycle:
1. Expires stale PENDING invoices.
2. Polls every receiving address that has PENDING invoices via
   PaymentMatchingService (handles deduplication + state machine).
3. Sends Telegram notifications for CONFIRMED / UNDERPAID / OVERPAID / LATE.
"""
from __future__ import annotations
import asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from app.config import get_settings
from app.logging_config import get_logger
from database.invoice_repository import InvoiceRepository
from database.invoice_service import InvoiceService
from database.payment_matching_service import MatchOutcome, PaymentMatchingService
from database.repositories import UserRepository
from database.session import get_session
from ton.tonapi_client import TonApiClient
from ton.units import format_ton

log = get_logger(__name__)


class PaymentMonitorWorker:
    def __init__(self) -> None:
        self._bot: Bot | None = None
        self._stop_event: asyncio.Event | None = None
        self._stopped_event: asyncio.Event | None = None

    def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()

    async def wait_stopped(self, timeout: float = 15.0) -> None:
        if self._stopped_event is None:
            return
        try:
            await asyncio.wait_for(self._stopped_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("payment_monitor_stop_timeout", timeout=timeout)

    async def run(self) -> None:
        self._stop_event = asyncio.Event()
        self._stopped_event = asyncio.Event()
        settings = get_settings()
        interval = settings.payment_poll_interval_seconds
        self._bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        log.info("payment_monitor_started", poll_interval=interval)
        try:
            while not self._stop_event.is_set():
                try:
                    await self._poll_cycle(settings)
                except Exception as exc:
                    log.error("payment_monitor_cycle_error", error=str(exc))
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._stop_event.wait()),
                        timeout=float(interval),
                    )
                    break
                except asyncio.TimeoutError:
                    pass
        finally:
            if self._bot:
                await self._bot.session.close()
            self._stopped_event.set()
            log.info("payment_monitor_stopped")

    async def _poll_cycle(self, settings) -> None:
        # Expire stale invoices
        async with get_session() as session:
            expired = await InvoiceService(session).expire_pending_invoices()
            if expired:
                log.info("payment_monitor_expired", count=expired)

        # Match incoming transactions
        async with (
            TonApiClient(
                base_url=settings.tonapi_base_url,
                api_key=settings.tonapi_key,
                timeout_seconds=settings.http_timeout_seconds,
            ) as client,
            get_session() as session,
        ):
            matcher = PaymentMatchingService(session=session, ton_client=client)
            poll_results = await matcher.poll_all_pending_addresses()

        for poll_result in poll_results:
            for candidate in poll_result.results:
                if candidate.outcome in (
                    MatchOutcome.CONFIRMED,
                    MatchOutcome.UNDERPAID,
                    MatchOutcome.OVERPAID,
                    MatchOutcome.LATE,
                ):
                    await self._notify(candidate.outcome, candidate.public_ref)

    async def _notify(self, outcome: MatchOutcome, public_ref: str | None) -> None:
        if not public_ref or not self._bot:
            return
        async with get_session() as session:
            inv = await InvoiceRepository(session).get_by_public_ref(public_ref)
            if inv is None:
                return
            user = await UserRepository(session).get_by_id(inv.user_id)
            if user is None:
                return
            telegram_id = user.telegram_id
            ton_str = format_ton(inv.amount_nanotons)

        ref_short = f"{public_ref[:12]}…"
        text = {
            MatchOutcome.CONFIRMED: (
                f"✅ <b>Payment confirmed!</b>\n\n"
                f"Amount: <b>{ton_str} TON</b>\n"
                f"Ref: <code>{ref_short}</code>"
            ),
            MatchOutcome.UNDERPAID: (
                f"⚠️ <b>Underpaid</b>\n\n"
                f"Expected: <b>{ton_str} TON</b>\n"
                f"Ref: <code>{ref_short}</code>\n"
                f"<i>Contact support if needed.</i>"
            ),
            MatchOutcome.OVERPAID: (
                f"⚠️ <b>Overpaid</b>\n\n"
                f"Expected: <b>{ton_str} TON</b>\n"
                f"Ref: <code>{ref_short}</code>\n"
                f"<i>Contact support for refund.</i>"
            ),
            MatchOutcome.LATE: (
                f"🕐 <b>Late payment received</b>\n\n"
                f"Amount: <b>{ton_str} TON</b>\n"
                f"Ref: <code>{ref_short}</code>\n"
                f"<i>Invoice had expired. Contact support.</i>"
            ),
        }.get(outcome)
        if not text:
            return
        try:
            await self._bot.send_message(telegram_id, text, parse_mode="HTML")
            log.info("payment_notification_sent", telegram_id=telegram_id, outcome=outcome.value)
        except Exception as exc:
            log.warning("payment_notification_failed", telegram_id=telegram_id, error=str(exc))
