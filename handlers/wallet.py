"""
Handlers for watchlist management and bot status.

Commands: /watch, /unwatch, /watchlist, /status
All business logic delegated to WalletService.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import get_settings
from app.logging_config import get_logger
from database.session import check_connectivity, get_session
from security.input_validation import escape_mdv2, sanitize_label, validate_command_arg
from services.wallet_service import (
    WalletService,
    WatchlistDuplicate,
    WatchlistFull,
    WatchlistNotFound,
)
from ton.address import AddressValidationError

log = get_logger(__name__)
router = Router(name="wallet")


def _user_id_from(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


@router.message(Command("watch"))
async def cmd_watch(message: Message) -> None:
    """
    /watch ADDRESS [optional label]
    Add a wallet address to the user's watchlist.
    """
    user_id = _user_id_from(message)
    if user_id is None:
        return

    args = (message.text or "").split(maxsplit=2)
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/watch ADDRESS [label]</code>", parse_mode="HTML"
        )
        return

    raw_address = validate_command_arg(args[1])
    label: str | None = None
    if len(args) >= 3:
        label = sanitize_label(args[2])

    settings = get_settings()
    async with get_session() as session:
        svc = WalletService(session, max_per_user=settings.max_watchlist_per_user)
        try:
            result = await svc.add_wallet(user_id, raw_address, label=label)
        except AddressValidationError as exc:
            await message.answer(f"Invalid address: {exc}", parse_mode=None)
            return
        except WatchlistFull as exc:
            await message.answer(str(exc), parse_mode=None)
            return
        except WatchlistDuplicate as exc:
            await message.answer(str(exc), parse_mode=None)
            return

    display = result.address.canonical
    label_line = f"\nLabel: <code>{escape_mdv2(label)}</code>" if label else ""
    await message.answer(
        f"✅ Added to watchlist:\n<code>{display}</code>{label_line}",
        parse_mode="HTML",
    )


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message) -> None:
    """
    /unwatch ADDRESS
    Remove an address from the user's watchlist.
    """
    user_id = _user_id_from(message)
    if user_id is None:
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/unwatch ADDRESS</code>", parse_mode="HTML"
        )
        return

    raw_address = validate_command_arg(args[1])

    async with get_session() as session:
        svc = WalletService(session)
        try:
            addr = await svc.remove_wallet(user_id, raw_address)
        except AddressValidationError as exc:
            await message.answer(f"Invalid address: {exc}", parse_mode=None)
            return
        except WatchlistNotFound as exc:
            await message.answer(str(exc), parse_mode=None)
            return

    await message.answer(
        f"🗑 Removed from watchlist:\n<code>{addr.canonical}</code>",
        parse_mode="HTML",
    )


@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message) -> None:
    """
    /watchlist
    Show all addresses on the user's watchlist.
    Paginates at 10 entries per message.
    """
    user_id = _user_id_from(message)
    if user_id is None:
        return

    async with get_session() as session:
        svc = WalletService(session)
        entries = await svc.list_wallets(user_id)

    if not entries:
        await message.answer(
            "Your watchlist is empty.\nUse <code>/watch ADDRESS</code> to add one.",
            parse_mode="HTML",
        )
        return

    lines = [f"👁 <b>Your watchlist</b> ({len(entries)} address(es)):\n"]
    for i, entry in enumerate(entries, start=1):
        label_part = f" — {escape_mdv2(entry.label)}" if entry.label else ""
        lines.append(f"{i}. <code>{entry.canonical_address}</code>{label_part}")

    # Paginate: 10 per message
    page_size = 10
    for chunk_start in range(0, len(lines), page_size):
        chunk = lines[chunk_start : chunk_start + page_size]
        await message.answer("\n".join(chunk), parse_mode="HTML")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """
    /status
    Show safe operational information only — no secrets, no internal paths.
    """
    db_ok = await check_connectivity()
    db_status = "✅ Connected" if db_ok else "❌ Unavailable"

    settings = get_settings()
    await message.answer(
        f"<b>Sombra TON Guardian — Status</b>\n\n"
        f"Database: {db_status}\n"
        f"Provider: {settings.tonapi_base_url}\n"
        f"Mode: read-only",
        parse_mode="HTML",
    )