"""Handler for /start command."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from keyboards.main_menu import main_menu_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if not message.from_user:
        return
    await message.answer(
        "👁 <b>CrypBot</b>\n\n"
        "Add wallet addresses to your watchlist and check balances "
        "or transaction history at any time.\n\n"
        "<b>Quick start:</b>\n"
        "• <code>/watch ADDRESS</code> — add an address\n"
        "• <code>/balance ADDRESS</code> — check balance\n"
        "• <code>/help</code> — full command list",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )