"""Handler for /history command."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import get_settings
from app.logging_config import get_logger
from database.session import get_session
from security.input_validation import escape_mdv2, validate_command_arg
from security.redaction import safe_error_message
from services.transaction_service import TransactionService
from ton.address import AddressValidationError
from ton.base_client import ProviderError
from ton.tonapi_client import TonApiClient

log = get_logger(__name__)
router = Router(name="transactions")

_PAGE_SIZE = 10


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    """
    /history ADDRESS
    Show recent transaction events for an address.
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/history ADDRESS</code>", parse_mode="HTML"
        )
        return

    raw_address = validate_command_arg(args[1])
    settings = get_settings()

    await message.answer("⏳ Fetching history…", parse_mode=None)

    try:
        async with TonApiClient(
            base_url=settings.tonapi_base_url,
            api_key=settings.tonapi_key,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client, get_session() as session:
            svc = TransactionService(session=session, ton_client=client)
            try:
                result = await svc.get_history(raw_address, limit=_PAGE_SIZE)
            except AddressValidationError as exc:
                await message.answer(f"Invalid address: {exc}", parse_mode=None)
                return
            except ProviderError as exc:
                log.warning("history_provider_error", error=safe_error_message(exc))
                await message.answer(
                    "Could not retrieve history right now. Please try again later.",
                    parse_mode=None,
                )
                return
    except Exception as exc:
        log.exception("history_unexpected_error", error=safe_error_message(exc))
        await message.answer(
            "An unexpected error occurred. Please try again later.", parse_mode=None
        )
        return

    if not result.transactions:
        await message.answer(
            f"No transaction history found for:\n<code>{result.canonical_address}</code>",
            parse_mode="HTML",
        )
        return

    lines = [
        f"<b>Recent Transactions</b>",
        f"<code>{result.canonical_address}</code>\n",
    ]

    for tx in result.transactions:
        ts_str = (
            tx.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            if tx.timestamp
            else "unknown time"
        )
        action = escape_mdv2(tx.action_type or "unknown")
        status_icon = "⏳" if tx.in_progress else "✅"
        scam_flag = " ⚠ SCAM" if tx.is_scam else ""
        lines.append(
            f"{status_icon} <code>{tx.event_id[:12]}…</code> "
            f"| {action} | {ts_str}{scam_flag}"
        )

    if result.next_cursor:
        lines.append(
            f"\n<i>More history available — "
            f"pagination cursor: {result.next_cursor}</i>"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")