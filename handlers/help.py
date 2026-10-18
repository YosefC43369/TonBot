"""Handler for /help command."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="help")

_HELP_TEXT = (
    "<b>Sombra TON Guardian — Commands</b>\n\n"
    "<b>Watchlist</b>\n"
    "• <code>/watch ADDRESS [label]</code> — add address to watchlist\n"
    "• <code>/unwatch ADDRESS</code> — remove address from watchlist\n"
    "• <code>/watchlist</code> — show your watchlist\n\n"
    "<b>On-chain data</b>\n"
    "• <code>/balance ADDRESS</code> — TON and Jetton balances\n"
    "• <code>/history ADDRESS</code> — recent transaction events\n\n"
    "<b>Bot</b>\n"
    "• <code>/status</code> — bot operational status\n"
    "• <code>/help</code> — this message\n\n"
    "<i>This bot is strictly read-only. It never requests private keys "
    "or initiates any transactions.</i>"
)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT, parse_mode="HTML")